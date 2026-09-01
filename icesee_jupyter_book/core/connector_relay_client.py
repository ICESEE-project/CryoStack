"""Gateway/kernel-side client for the CryoStack Connector relay (v2).

The relay control plane (create session, issue command) is authenticated by a
per-session ``control_secret`` that the relay hands back at creation. This module
holds that secret in a process-global *binding* for the lifetime of the Voila
kernel -- which is inherently one authenticated CryoStack user, one connector
session -- so the ~40 existing ``send_command(...)`` call sites do not each have
to carry credentials.

``send_command`` fails closed: with no binding, or a binding for a different
``session_id``, it raises :class:`RelayAuthError` instead of issuing an
unauthenticated request.
"""
from __future__ import annotations

import threading
import time

import requests

from icesee_jupyter_book.core.connector_relay_auth import deployment_token

RELAY_URL = "https://cryostack.eas.gatech.edu"

_LOCK = threading.Lock()
_BINDING: dict[str, str] = {}

#: short read-through cache for the coarse, unauthenticated session status so a
#: burst of UI changes does not fan out into one relay HTTP call each. The
#: cached value is only ``{session_id, online, state}`` -- never a secret.
STATUS_CACHE_TTL_SECONDS = 2.0
_STATUS_CACHE: dict[str, tuple[float, dict]] = {}
_STATUS_LOCK = threading.Lock()


class RelayAuthError(RuntimeError):
    """A relay control operation was attempted without a valid session binding."""


def bind_session(session_id: str, control_secret: str, owner_user_id: str) -> None:
    """Record the credentials for the connector session this kernel owns."""
    if not session_id or not control_secret or not owner_user_id:
        raise RelayAuthError("bind_session requires session_id, control_secret and owner_user_id.")
    with _LOCK:
        _BINDING.clear()
        _BINDING.update(
            session_id=session_id,
            control_secret=control_secret,
            owner_user_id=owner_user_id,
        )


def clear_binding() -> None:
    with _LOCK:
        _BINDING.clear()
    invalidate_status_cache()


def current_binding() -> dict[str, str]:
    with _LOCK:
        return dict(_BINDING)


def _control_headers_for(session_id: str) -> tuple[dict[str, str], str]:
    with _LOCK:
        binding = dict(_BINDING)
    if binding.get("session_id") != session_id or not binding.get("control_secret"):
        raise RelayAuthError(
            "No connector session is bound to this kernel (or it is a different "
            "session). Create/refresh the connector session before issuing commands."
        )
    return (
        {"Authorization": f"Bearer {binding['control_secret']}"},
        binding["owner_user_id"],
    )


def create_session(owner_user_id: str) -> dict:
    """Create a relay session owned by ``owner_user_id`` and bind it locally."""
    owner = (owner_user_id or "").strip()
    if not owner:
        raise RelayAuthError("create_session requires an authenticated CryoStack owner_user_id.")

    headers = {}
    token = deployment_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    r = requests.post(
        f"{RELAY_URL}/connector/session",
        json={"owner_user_id": owner},
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    bind_session(data["session_id"], data["control_secret"], owner)
    invalidate_status_cache(data["session_id"])
    return data


def check_status(session_id: str, *, force: bool = False) -> dict:
    """Coarse, unauthenticated session state: ``{session_id, online, state}``.

    Served from a short (``STATUS_CACHE_TTL_SECONDS``) per-session cache so
    rapid UI changes do not each hit the relay. Pass ``force=True`` when
    freshness matters (Check SSH, the Run gate). A ``superseded`` / ``expired``
    / ``unknown`` state is never cached, so a dead session is re-checked
    immediately next time.
    """
    key = str(session_id or "")
    if not force:
        with _STATUS_LOCK:
            hit = _STATUS_CACHE.get(key)
        if hit and (time.monotonic() - hit[0]) < STATUS_CACHE_TTL_SECONDS:
            return dict(hit[1])

    r = requests.get(f"{RELAY_URL}/connector/status/{key}", timeout=15)
    data = r.json()

    coarse = {
        "session_id": data.get("session_id", key),
        "online": bool(data.get("online")),
        "state": data.get("state", "unknown"),
    }
    if coarse["state"] not in {"superseded", "expired", "unknown"}:
        with _STATUS_LOCK:
            _STATUS_CACHE[key] = (time.monotonic(), dict(coarse))
    else:
        with _STATUS_LOCK:
            _STATUS_CACHE.pop(key, None)
    # return the full relay payload (callers read extra fields) but merge the
    # normalised coarse view so cached and uncached results agree.
    return {**data, **coarse}


def invalidate_status_cache(session_id: str | None = None) -> None:
    """Drop the cached status for one session (or all sessions)."""
    with _STATUS_LOCK:
        if session_id is None:
            _STATUS_CACHE.clear()
        else:
            _STATUS_CACHE.pop(str(session_id), None)


def send_command(session_id: str, command_type: str, payload: dict) -> dict:
    """Issue a command to the bound session's connector. Fails closed."""
    headers, owner_user_id = _control_headers_for(session_id)
    r = requests.post(
        f"{RELAY_URL}/connector/command/{session_id}",
        json={
            "owner_user_id": owner_user_id,
            "command_type": command_type,
            "payload": payload,
        },
        headers=headers,
        timeout=120,
    )
    return r.json()
