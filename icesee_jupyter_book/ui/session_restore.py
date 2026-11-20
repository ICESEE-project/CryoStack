"""Keep a user's work across a page reload, shared by ICESEE and CryoLauncher.

Each page load starts a fresh kernel and builds the application from scratch,
so without this a reload drops the chosen mode, experiment, parameters, Slurm
request, unsaved editor text and the open workspace tab. The application
registers what makes up "where the user is" -- plain value widgets by a stable
name, and parts (parameter forms, editors) that save and restore themselves --
and :class:`SessionRestore` keeps a snapshot in the user's own workspace:

    <owner-root>/.cryostack/session/<app>.json

It is written a couple of seconds after a change and read once when the page
is built. Only a trusted CryoStack identity (the proxy header, or the local
single-user override) gets a session file; an anonymous page never shares one.
Secrets are never registered and secret-looking keys are dropped on save.

Saved per-resource HPC settings (B2, ``resource_state``) stay where they are;
this snapshot is the page state on top of them.
"""
from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import ipywidgets as W

from cryostack_src.workspace.identity import resolve_workspace_user
from cryostack_src.workspace.resource_state import SECRET_MARKERS, strip_secrets
from cryostack_src.workspace.roots import state_owner_root as owner_root

SCHEMA_VERSION = 1
#: a larger snapshot (a huge pasted file) is not written; the last good one stays
MAX_BYTES = 2 * 1024 * 1024
#: restore passes: a restored value can rebuild dependent widgets (an
#: experiment rebuilds its parameter form), which a later pass then fills
_PASSES = 3


def session_path(app: str, *, workspace_root: str | Path | None = None) -> Path | None:
    """The session file of the current user for ``app``, or None for an
    anonymous page."""
    user = resolve_workspace_user(require_authenticated=False)
    if user.source not in ("cryostack-auth", "env-override") or not user.user_id:
        return None
    seg = "".join(c if c.isalnum() or c in "-_" else "-" for c in app).strip("-") or "app"
    return owner_root(user, workspace_root=workspace_root) / ".cryostack" / "session" / f"{seg}.json"


def load_session(path: Path | None) -> dict:
    """The saved values, or ``{}`` when there is no usable session."""
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        return {}
    values = data.get("values")
    return values if isinstance(values, dict) else {}


def save_session(path: Path | None, values: dict) -> bool:
    """Write ``values`` atomically (owner-only); False when not written."""
    if path is None:
        return False
    payload = json.dumps({"schema_version": SCHEMA_VERSION,
                          "saved": datetime.now().isoformat(timespec="seconds"),
                          "values": strip_secrets(values)}, sort_keys=True)
    if len(payload.encode("utf-8")) > MAX_BYTES:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def _is_secret(name: str) -> bool:
    low = name.lower()
    return any(marker in low for marker in SECRET_MARKERS)


def _plain(value):
    """A widget value as JSON (tuples of SelectMultiple become lists)."""
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


def _option_values(widget) -> list | None:
    options = getattr(widget, "options", None)
    if options is None:
        return None
    return [o[1] if isinstance(o, (tuple, list)) and len(o) == 2 else o for o in options]


def apply_value(widget, saved) -> bool:
    """Set ``widget`` to a saved value when it is still valid; True if it changed."""
    allowed = _option_values(widget)
    if isinstance(widget, W.SelectMultiple):
        saved = tuple(v for v in (saved or ()) if allowed is None or v in allowed)
    elif allowed is not None and saved not in allowed:
        return False
    if _plain(widget.value) == _plain(saved):
        return False
    try:
        widget.value = saved
    except Exception:  # noqa: BLE001 - out of range, wrong type: keep the default
        return False
    return _plain(widget.value) == _plain(saved)


class SessionRestore:
    """The page state of one application for the current user.

    Register in dependency order (mode and experiment before the parameters
    they rebuild), then call :meth:`restore` once the page is built and
    :meth:`start` to keep the snapshot current.
    """

    def __init__(self, app: str, *, path: Path | None = None, interval: float | None = None,
                 workspace_root: str | Path | None = None) -> None:
        self.path = path if path is not None else session_path(app, workspace_root=workspace_root)
        if interval is None:
            try:
                interval = float(os.environ.get("CRYOSTACK_SESSION_SAVE_SECONDS", "2"))
            except ValueError:
                interval = 2.0
        self.interval = interval
        self._entries: list[tuple[str, Callable[[], object], Callable[[object], bool]]] = []
        self._last: str | None = None
        self._lock = threading.Lock()
        self._ticker = None
        self.restored: list[str] = []
        #: the registered value widgets by name
        self.widgets: dict = {}

    # ── registration ─────────────────────────────────────────────────────
    def field(self, name: str, widget) -> None:
        if _is_secret(name) or isinstance(widget, W.Password):
            raise ValueError(f"{name}: secrets are never kept in the page session")
        self.widgets[name] = widget
        self._entries.append((name, lambda: _plain(widget.value), lambda v: apply_value(widget, v)))

    def fields(self, **widgets) -> None:
        for name, widget in widgets.items():
            self.field(name, widget)

    def part(self, name: str, get: Callable[[], object], restore: Callable[[object], object]) -> None:
        """A component that saves itself as JSON (``get``) and restores from
        it (``restore`` returns truthy when something changed)."""
        if _is_secret(name):
            raise ValueError(f"{name}: secrets are never kept in the page session")
        self._entries.append((name, get, lambda v: bool(restore(v))))

    # ── lifecycle ────────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        values = {}
        for name, get, _restore in self._entries:
            try:
                value = get()
                json.dumps(value)
            except Exception:  # noqa: BLE001 - one broken part never blocks the rest
                continue
            if value is not None:
                values[name] = value
        return values

    def restore(self) -> list[str]:
        """Apply the saved session; the names that changed."""
        saved = load_session(self.path)
        changed: list[str] = []
        for _ in range(_PASSES):
            moved = False
            for name, _get, put in self._entries:
                if name not in saved:
                    continue
                try:
                    if put(saved[name]):
                        moved = True
                        if name not in changed:
                            changed.append(name)
                except Exception:  # noqa: BLE001
                    continue
            if not moved:
                break
        self._last = json.dumps(self.snapshot(), sort_keys=True)
        self.restored = changed
        return changed

    def save(self) -> bool:
        """Write the snapshot when it changed since the last save."""
        with self._lock:
            values = self.snapshot()
            text = json.dumps(values, sort_keys=True)
            if text == self._last:
                return False
            if save_session(self.path, values):
                self._last = text
                return True
            return False

    def start(self) -> None:
        """Save every ``interval`` seconds while the page is open (never when
        the interval is 0)."""
        if self.path is None or self._ticker is not None or self.interval <= 0:
            return
        from icesee_jupyter_book.ui.icesee_workflow.launch import Ticker

        self._ticker = Ticker(self._autosave, interval=self.interval)

    def _autosave(self) -> None:
        # Ticker stops on a False return; "nothing changed" must keep it going
        self.save()

    def stop(self) -> None:
        if self._ticker is not None:
            self._ticker.stop()
            self._ticker = None

    def clear(self) -> None:
        """Forget the saved session (the page keeps its current values)."""
        self.stop()
        if self.path is not None:
            try:
                self.path.unlink()
            except OSError:
                pass
        self._last = json.dumps(self.snapshot(), sort_keys=True)

    def notice(self) -> W.Box:
        """A line under the stepper after a restore, with Start fresh (forget
        the session and reload the page with the defaults). Hidden when
        nothing was restored."""
        from icesee_jupyter_book.ui.icesee_workflow.components import button, callout, run_js

        js = W.Output(layout=W.Layout(height="0px", overflow="hidden"))
        fresh = button("Start fresh", icon="refresh", kind="quiet",
                       tooltip="Forget the restored settings and edits, and reload with the defaults")
        text = W.HTML(callout("Your settings and unsaved edits from your last visit were restored. "
                              "Changes are kept automatically while you work.", "info",
                              title="Picked up where you left off."))
        box = W.HBox([text, fresh, js], layout=W.Layout(width="100%", align_items="center", gap="10px"))
        box.add_class("icw-session-notice")
        box.layout.display = "" if self.restored else "none"

        def _fresh(_b=None):
            self.clear()
            run_js(js, "window.location.reload();")

        fresh.on_click(_fresh)
        return box
