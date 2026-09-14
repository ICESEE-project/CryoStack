"""B2: authenticated read of the user's saved workspace state.

Save still goes through the existing browser bridge (session-authenticated
``PUT /api/v1/workspaces/{application}``). Restore is a server-side read of the
*same* store (the ``workspaces`` table), scoped by the proxy-verified
``HTTP_X_CRYOSTACK_USER_ID`` -- the Voila kernel has no browser cookie, so it
cannot call the HTTP API, but it can read the shared auth database directly.

Fail closed: any problem -> ``{}`` (blank personal fields). Never a global
file, localStorage, the process environment, or another user's row.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

_APP_ALIASES = {"cryolauncher": "cryolauncher", "icesheets": "cryolauncher", "icesee": "icesee"}


def auth_database_path() -> Path:
    """Same resolution as :class:`icesee_auth.manager.AuthManager`."""
    env = (os.environ.get("CRYOSTACK_AUTH_DATABASE") or "").strip()
    if env:
        return Path(env)
    import icesee_auth  # noqa: PLC0415

    return Path(icesee_auth.__file__).resolve().parent.parent / "var" / "cryostack_auth.db"


def load_user_workspace_state(user_id: str | None, application: str) -> dict:
    """The authenticated user's saved workspace state, or ``{}``.

    Returns ``{}`` (not ``None``) on a missing row so the caller cannot tell
    "no row" from "blank row"; returns ``{}`` on *any* failure so a broken
    store degrades to blank, never to another source.
    """
    uid = (user_id or "").strip()
    app = _APP_ALIASES.get(application.strip().lower(), application.strip().lower())
    if not uid:
        return {}
    try:
        db = auth_database_path()
        if not db.is_file():
            return {}
        from icesee_auth.storage import AuthStorage  # noqa: PLC0415

        ws = AuthStorage(db).get_workspace(user_id=uid, application=app)
        if ws is None:
            return {}
        data = json.loads(ws.state_json)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def make_state_io(
    workspace_bridge, application: str, user_id: str | None
) -> tuple[Callable[[], dict], Callable[[dict], None]]:
    """``(load_state, save_state)`` callbacks for a ResourceStateController.

    ``save_state`` reuses the existing browser PUT bridge unchanged.
    """
    app = _APP_ALIASES.get(application.strip().lower(), application.strip().lower())

    def load_state() -> dict:
        return load_user_workspace_state(user_id, app)

    def save_state(state: dict) -> None:
        workspace_bridge.save(application=app, state=state)

    return load_state, save_state
