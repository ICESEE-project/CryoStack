"""Non-blocking warm-up for the application Voila servers.

The CryoStack web shell (home, docs, auth, Control Center, ``/connect/``,
static assets) must be usable the instant the aiohttp process is up. The two
Voila application servers take several seconds to bind their ports, so they
are warmed **in the background** -- the shell does not wait for them.

Each managed service is a small state machine::

    STOPPED --ensure_started()--> STARTING --port binds--> READY
                                     |
                                     +--- times out / crashes --> FAILED --retry()--> STOPPED

Concurrency: exactly one start operation per service. ``ensure_started`` is
non-blocking (it schedules the work and returns the current state); the
actual start is guarded by an ``asyncio.Lock`` so concurrent requests -- or a
request racing the background warm-up -- never launch a duplicate process.
"""
from __future__ import annotations

import asyncio
import contextlib
import socket
import time
from enum import Enum

from cryostack_src import perf


class ServiceState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"


async def _wait_for_port(host: str, port: int, timeout: float) -> bool:
    """Poll a TCP port without blocking the event loop."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=1.0
            )
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            return True
        except (OSError, asyncio.TimeoutError):
            await asyncio.sleep(0.25)
    # one last synchronous check (covers a port that opened in the final gap)
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


class ManagedVoilaService:
    """One background-warmed Voila application server.

    ``process`` is any object exposing ``start()`` / ``stop()`` (and, for
    tests, ``poll``-able ``proc``). ``start()`` must itself be idempotent.
    """

    def __init__(
        self,
        *,
        name: str,
        process,
        port: int,
        host: str = "127.0.0.1",
        port_timeout: float = 45.0,
        origin_epoch: float | None = None,
    ) -> None:
        self.name = name
        self.port = port
        self.host = host
        self._process = process
        self._port_timeout = port_timeout
        self._origin_epoch = origin_epoch  # perf: seconds since process start
        self._state = ServiceState.STOPPED
        self._error = ""
        self._lock = asyncio.Lock()
        self._ready_seconds: float | None = None

    # -- observable state ------------------------------------------------
    @property
    def state(self) -> ServiceState:
        return self._state

    @property
    def error(self) -> str:
        return self._error

    @property
    def ready_seconds(self) -> float | None:
        """Seconds from process start to READY (perf reporting)."""
        return self._ready_seconds

    # -- lifecycle ----------------------------------------------------
    async def _do_start(self) -> ServiceState:
        """The actual start, serialized by the lock. Exactly one process is
        launched no matter how many callers race here."""
        async with self._lock:
            # Another holder already finished the work while we waited.
            if self._state is ServiceState.READY:
                return self._state
            if self._state is ServiceState.FAILED:
                # A failure is terminal until request_retry() resets to STOPPED.
                return self._state

            self._state = ServiceState.STARTING
            self._error = ""
            started = time.perf_counter()
            try:
                self._process.start()   # itself idempotent
                ok = await _wait_for_port(self.host, self.port, self._port_timeout)
                if not ok:
                    raise TimeoutError(
                        f"{self.name} did not bind {self.host}:{self.port} "
                        f"within {self._port_timeout:.0f}s"
                    )
            except Exception as exc:  # noqa: BLE001 - reported via .error / FAILED
                self._state = ServiceState.FAILED
                self._error = f"{type(exc).__name__}: {exc}"
                return self._state

            self._state = ServiceState.READY
            elapsed = time.perf_counter() - started
            if self._origin_epoch is not None:
                self._ready_seconds = time.time() - self._origin_epoch
                perf.mark(f"{self.name} voila ready", self._ready_seconds)
            else:
                perf.mark(f"{self.name} voila ready", elapsed)
            return self._state

    def ensure_started(self) -> ServiceState:
        """Non-blocking. Returns the current state; if the service is STOPPED,
        schedules the start as a background task and returns STARTING. A FAILED
        service is *not* auto-retried -- call :meth:`request_retry` first."""
        if self._state is ServiceState.STOPPED:
            self._state = ServiceState.STARTING
            asyncio.ensure_future(self._do_start())
        return self._state

    async def warm_up(self) -> ServiceState:
        """Await a full start (used by the background warm-up task)."""
        return await self._do_start()

    def request_retry(self) -> None:
        """Move a FAILED service back to STOPPED so the next request re-warms."""
        if self._state is ServiceState.FAILED:
            self._state = ServiceState.STOPPED

    def stop(self) -> None:
        self._process.stop()
        self._state = ServiceState.STOPPED


async def warm_up_all(services, *, origin_label: str = "aiohttp ready",
                      origin_seconds: float | None = None) -> None:
    """Background task: warm every service concurrently. Cancellation-safe."""
    if origin_seconds is not None:
        perf.mark(origin_label, origin_seconds)
    try:
        await asyncio.gather(*(svc.warm_up() for svc in services))
    except asyncio.CancelledError:  # shutdown during warm-up
        raise
