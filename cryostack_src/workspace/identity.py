"""Trusted CryoStack identity for per-user Workspace isolation.

The Workspace namespace of a run history must be owned by an authenticated
CryoStack user.  The only trusted source of that identity is the
``X-CryoStack-User-Id`` header injected by the authenticating reverse proxy
(:mod:`bin.icesee_app`), which is surfaced into the Voila kernel environment as
``HTTP_X_CRYOSTACK_USER_ID`` via ``VoilaConfiguration.http_header_envs``.

Identity is never taken from a widget, an SSH username, an email field, a Slurm
account, a browser/query-string parameter, or any other user-editable input.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_ANONYMOUS_ID = "anonymous"

#: env var the reverse proxy + Voila place the trusted user id into
USER_ID_ENV = "HTTP_X_CRYOSTACK_USER_ID"
USER_NAME_ENV = "HTTP_X_CRYOSTACK_USER_NAME"
#: local/CLI single-user override (never set in the authenticated web deployment)
USER_OVERRIDE_ENV = "CRYOSTACK_WORKSPACE_USER"


class WorkspaceIdentityError(RuntimeError):
    """A protected context was reached without a trusted CryoStack identity."""


@dataclass(frozen=True)
class WorkspaceUser:
    """A CryoStack identity that owns a Workspace namespace."""

    user_id: str
    display_name: str = ""
    source: str = "unknown"

    @property
    def is_authenticated(self) -> bool:
        return self.source == "cryostack-auth" and self.user_id != _ANONYMOUS_ID

    @property
    def safe_id(self) -> str:
        """Deterministic, collision-resistant, filesystem-safe namespace key.

        A short readable slug plus a hash of the full id, so distinct ids can
        never share a directory even when their slugs collide or truncate.
        """
        raw = (self.user_id or _ANONYMOUS_ID).strip() or _ANONYMOUS_ID
        slug = _UNSAFE.sub("-", raw).strip("-.") or "user"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        return f"{slug[:40]}-{digest}"


def resolve_workspace_user(
    env: "dict[str, str] | os._Environ[str] | None" = None,
    *,
    require_authenticated: bool = False,
) -> WorkspaceUser:
    """Resolve the trusted CryoStack user from the kernel environment.

    ``require_authenticated=True`` (the protected web path) fails closed: if
    neither the proxy-verified ``HTTP_X_CRYOSTACK_USER_ID`` header nor an
    explicit ``CRYOSTACK_WORKSPACE_USER`` override is present, it raises
    :class:`WorkspaceIdentityError` instead of collapsing every web visitor
    into one shared ``anonymous`` namespace.
    """
    source_env = os.environ if env is None else env

    user_id = (source_env.get(USER_ID_ENV) or "").strip()
    if user_id:
        return WorkspaceUser(
            user_id=user_id,
            display_name=(source_env.get(USER_NAME_ENV) or "").strip(),
            source="cryostack-auth",
        )

    override = (source_env.get(USER_OVERRIDE_ENV) or "").strip()
    if override:
        return WorkspaceUser(user_id=override, display_name=override, source="env-override")

    if require_authenticated:
        raise WorkspaceIdentityError(
            "Workspace unavailable: authenticated CryoStack identity was not provided."
        )

    # Unprotected/dev context only (direct hit on Voila, no proxy). Isolated in
    # its own namespace, never shared with authenticated users.
    return WorkspaceUser(user_id=_ANONYMOUS_ID, display_name="", source="unauthenticated")
