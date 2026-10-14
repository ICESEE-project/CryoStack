"""What a Voila kernel may ask the gateway for, without opening its databases.

Kernels run user-influenced code. When they run under their own service
account they cannot (and should not) open ``var/cryostack_auth.db``; the one
thing they read from it -- the signed-in user's saved workspace state -- is
served by the gateway on a loopback-only route instead.

The gateway proves the identity to the kernel the same way it does for the
connector relay: every proxied Voila request carries a grant derived from a
gateway-only key and the user id, which Voila exposes to that request's
kernel as :data:`WORKSPACE_GRANT_ENV`. A kernel therefore holds a grant for
its own user only, and the key never leaves the gateway process.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.parse
import urllib.request

#: request header the gateway sets for Voila; the kernel sees it as the env var
WORKSPACE_GRANT_HEADER = "X-CryoStack-Workspace-Grant"
WORKSPACE_GRANT_ENV = "HTTP_X_CRYOSTACK_WORKSPACE_GRANT"

#: loopback-only gateway route serving a user's saved workspace state
KERNEL_WORKSPACE_STATE_PATH = "/internal/kernel/workspace-state"

#: where kernels reach the gateway (bin/icesee_app.py listens on 8080)
GATEWAY_URL_ENV = "CRYOSTACK_GATEWAY_INTERNAL_URL"
DEFAULT_GATEWAY_URL = "http://127.0.0.1:8080"

_PURPOSE = b"cryostack-kernel-workspace-read\x00"


def workspace_grant(user_id: str, key: bytes) -> str | None:
    """The grant for one user, or ``None`` without a user or key."""
    user = (user_id or "").strip()
    if not user or not key:
        return None
    digest = hmac.new(key, _PURPOSE + user.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def grant_matches(user_id: str, grant: str | None, key: bytes) -> bool:
    expected = workspace_grant(user_id, key)
    return bool(expected and isinstance(grant, str) and hmac.compare_digest(expected, grant))


def kernel_workspace_grant() -> str | None:
    """The grant the gateway forwarded to this kernel, or ``None``."""
    value = (os.environ.get(WORKSPACE_GRANT_ENV) or "").strip()
    return value or None


def fetch_workspace_state(user_id: str, application: str, grant: str,
                          *, timeout: float = 5.0) -> dict:
    """The user's saved state for ``application`` from the gateway.

    Raises on transport or protocol errors; the caller decides how to degrade.
    """
    base = (os.environ.get(GATEWAY_URL_ENV) or DEFAULT_GATEWAY_URL).rstrip("/")
    query = urllib.parse.urlencode({"application": application})
    request = urllib.request.Request(
        f"{base}{KERNEL_WORKSPACE_STATE_PATH}?{query}",
        headers={"X-CryoStack-User-Id": user_id, WORKSPACE_GRANT_HEADER: grant},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed loopback URL
        payload = json.loads(response.read(1 << 22).decode("utf-8"))
    state = payload.get("state") if isinstance(payload, dict) else None
    return state if isinstance(state, dict) else {}
