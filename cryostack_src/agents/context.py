"""``ToolContext`` — the authenticated, user-scoped context every tool runs in.

A tool NEVER receives a ``user_id`` / ``owner`` argument. It reads identity from
its context, which is built once per agent turn from the trusted CryoStack
identity (``resolve_workspace_user(require_authenticated=True)`` — the same
fail-closed path B2 uses). There is no "act as", no impersonation, no developer
fallback: if the trusted identity is missing or anonymous, a context cannot be
built.

See ``overnight/AGENT_SAFETY_MODEL.md`` §3.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cryostack_src.workspace.identity import (
    WorkspaceIdentityError,
    WorkspaceUser,
    resolve_workspace_user,
)

from .permissions import Permission
from .trace import Trace

_ALLOWED_APPS = ("icesheets", "icesee")


@dataclass(frozen=True)
class ToolContext:
    """Immutable, user-scoped context passed to every tool.

    Attributes:
        user: the authenticated CryoStack identity (never anonymous here).
        application: which CryoStack app the agent is operating in.
        max_permission: the permission ceiling for this context; the registry
            refuses a tool whose ``permission`` exceeds this.
        workspace_manager: an already user-scoped ``WorkspaceManager`` (optional
            — read-only tools that don't need run history can omit it).
        trace: the append-only operational trace sink.
        extras: opaque, app-supplied objects a tool may need (e.g. a compute-
            profile lookup) — never identity, never secrets.
    """

    user: WorkspaceUser
    application: str
    max_permission: Permission
    workspace_manager: Any | None = None
    trace: Trace = field(default_factory=Trace)
    extras: dict = field(default_factory=dict)

    #: identity sources the agent layer trusts -- exactly what
    #: ``resolve_workspace_user(require_authenticated=True)`` accepts: the
    #: proxy-verified header, or the deploy-time single-user override. NEVER the
    #: "unauthenticated" anonymous sentinel.
    _TRUSTED_SOURCES = ("cryostack-auth", "env-override")

    def __post_init__(self) -> None:
        if (not isinstance(self.user, WorkspaceUser)
                or self.user.source not in self._TRUSTED_SOURCES
                or self.user.user_id in ("", "anonymous")):
            raise WorkspaceIdentityError(
                "ToolContext requires a trusted CryoStack identity "
                "(proxy header or deploy-time override; no anonymous / "
                "developer fallback)."
            )
        if self.application not in _ALLOWED_APPS:
            raise ValueError(f"unknown application: {self.application!r}")
        object.__setattr__(self, "max_permission", Permission.parse(self.max_permission))

    # -- convenience -------------------------------------------------------
    @property
    def user_id(self) -> str:
        return self.user.user_id

    def can(self, needed: Permission) -> bool:
        return self.max_permission.covers(Permission.parse(needed))

    def with_ceiling(self, ceiling: Permission) -> "ToolContext":
        """A copy with a *lower or equal* permission ceiling (never higher)."""
        ceiling = Permission.parse(ceiling)
        new = min(self.max_permission, ceiling)
        return ToolContext(
            user=self.user, application=self.application, max_permission=new,
            workspace_manager=self.workspace_manager, trace=self.trace,
            extras=self.extras,
        )


def build_tool_context(
    *,
    application: str,
    max_permission: Permission | str = Permission.PLAN,
    workspace_manager: Any | None = None,
    trace: Trace | None = None,
    extras: dict | None = None,
    env: dict | None = None,
) -> ToolContext:
    """Build a context from the trusted CryoStack identity. Fails closed."""
    user = resolve_workspace_user(env, require_authenticated=True)
    tr = trace or Trace(user_id=user.user_id)
    return ToolContext(
        user=user, application=application,
        max_permission=Permission.parse(max_permission),
        workspace_manager=workspace_manager, trace=tr, extras=dict(extras or {}),
    )
