"""The CryoStack agent permission ladder.

Least -> most privileged. A tool declares the *minimum* level it needs; a
:class:`~cryostack_src.agents.context.ToolContext` is granted a *maximum* level;
a call is refused unless ``context.max_permission >= tool.permission``.

See ``overnight/AGENT_SAFETY_MODEL.md`` §2.
"""
from __future__ import annotations

from enum import IntEnum


class Permission(IntEnum):
    #: pure reads within the caller's own scope; no mutation anywhere
    OBSERVE = 10
    #: construct / validate structured proposals; still no mutation
    PLAN = 20
    #: mutations confined to the authenticated user's workspace that do NOT
    #: change scientific intent and do NOT submit compute
    PREPARE = 30
    #: compute submission (sbatch / AWS Batch) and remote-filesystem writes
    EXECUTE = 40
    #: deletes / overwrites user data
    DESTRUCTIVE = 50

    @classmethod
    def parse(cls, value: "Permission | str | int") -> "Permission":
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            return cls(value)
        return cls[str(value).strip().upper()]

    def covers(self, needed: "Permission") -> bool:
        return int(self) >= int(needed)


class PermissionError(RuntimeError):
    """A tool call was attempted above the context's permission ceiling, or a
    confirmation/approval gate was not satisfied."""

    def __init__(self, message: str, *, needed: Permission | None = None,
                 granted: Permission | None = None) -> None:
        super().__init__(message)
        self.needed = needed
        self.granted = granted
