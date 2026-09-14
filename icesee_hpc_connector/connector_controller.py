"""Platform-agnostic lifecycle controller for the CryoStack Connector.

The GUI (rumps on macOS, pystray elsewhere) must only touch the UI event loop.
Everything else -- the HTTP pairing exchange, the WebSocket connect/reconnect,
relay commands and SSH -- runs on ONE background worker thread owned here. The
GUI reads :meth:`status_label` from a main-thread timer; the controller never
calls back into the GUI framework itself.

Lifecycle events are logged by fixed name only (:data:`LIFECYCLE_EVENTS`); no
payload, code, secret or SSH argument is ever passed to the logger, so a secret
cannot reach the log through this path.
"""
from __future__ import annotations

import datetime
import threading
from collections.abc import Callable

from icesee_hpc_connector.connector_core import DEFAULT_RELAY, run_connector

#: the only strings this module will ever write to the lifecycle log
LIFECYCLE_EVENTS = frozenset({
    "app-start",
    "menu-loop-started",
    "single-instance-blocked",
    "pairing-dialog-open",
    "pairing-dialog-cancelled",
    "pairing-request-start",
    "pairing-request-complete",
    "websocket-thread-start",
    "websocket-connected",
    "websocket-disconnected",
    "ssh-command-start",
    "ssh-command-complete",
    "worker-started",
    "worker-stopped",
    "worker-error",
    "app-shutdown",
})


class ConnectorState:
    IDLE = "idle"
    WAITING = "waiting"
    PAIRING = "pairing"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"
    STOPPED = "stopped"
    ERROR = "error"


_LABELS = {
    ConnectorState.IDLE: "Status: not paired",
    ConnectorState.WAITING: "Status: waiting to pair",
    ConnectorState.PAIRING: "Status: pairing…",
    ConnectorState.CONNECTED: "Status: connected ✓",
    ConnectorState.RECONNECTING: "Status: reconnecting…",
    ConnectorState.DISCONNECTED: "Status: disconnected",
    ConnectorState.STOPPED: "Status: stopped",
    ConnectorState.ERROR: "Status: error — re-pair",
}

_EVENT_STATE = {
    "pairing-request-start": ConnectorState.PAIRING,
    "websocket-thread-start": ConnectorState.RECONNECTING,
    "websocket-connected": ConnectorState.CONNECTED,
    "websocket-disconnected": ConnectorState.RECONNECTING,
    "worker-error": ConnectorState.ERROR,
}


class ConnectorController:
    def __init__(
        self,
        relay: str = DEFAULT_RELAY,
        *,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._relay = relay
        self._log = log or (lambda _s: None)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = ConnectorState.IDLE

    # -- lifecycle logging (name-only, allowlisted) -------------------
    def emit(self, event: str) -> None:
        if event not in LIFECYCLE_EVENTS:
            return
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._log(f"[lifecycle] {ts} {event}")
        with self._lock:
            if event in _EVENT_STATE:
                self._state = _EVENT_STATE[event]

    # -- state (thread-safe) ----------------------------------------
    def status(self) -> str:
        with self._lock:
            return self._state

    def status_label(self) -> str:
        return _LABELS.get(self.status(), _LABELS[ConnectorState.IDLE])

    def is_running(self) -> bool:
        t = self._thread
        return bool(t and t.is_alive())

    # -- start / stop ---------------------------------------------
    def start(self, pairing_code: str | None) -> bool:
        """Begin pairing + connecting on a background thread. Returns False if a
        worker is already running. Never blocks on the network."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self._state = ConnectorState.PAIRING if pairing_code else ConnectorState.WAITING
            self._thread = threading.Thread(
                target=self._run, args=(pairing_code,),
                name="cryostack-connector-worker", daemon=True,
            )
        self._thread.start()
        return True

    def stop(self, timeout: float = 6.0) -> None:
        """Signal the worker to exit, close the socket, and join."""
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout)
        with self._lock:
            self._thread = None
            if self._state not in (ConnectorState.ERROR,):
                self._state = ConnectorState.STOPPED
        self.emit("worker-stopped")

    def _run(self, pairing_code: str | None) -> None:
        self.emit("worker-started")
        try:
            run_connector(
                relay=self._relay,
                pairing_code=pairing_code or None,
                poll=True,
                stop_event=self._stop,
                on_event=self.emit,
            )
        except Exception:
            self.emit("worker-error")
        finally:
            with self._lock:
                if not self._stop.is_set() and self._state != ConnectorState.ERROR:
                    self._state = ConnectorState.DISCONNECTED
