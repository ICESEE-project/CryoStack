"""``ToolSpec`` / ``ToolResult`` / the ``@tool`` decorator.

A tool is a thin, typed, permission-declaring wrapper around an API CryoStack
already exposes. It contains no business logic of its own. Metadata a tool
declares:

* ``name`` / ``description``
* ``permission`` — the minimum :class:`Permission` it needs
* ``read_only`` — asserts it performs no mutation (checked against permission)
* ``requires_confirmation`` — the orchestrator must surface + get an ack first
* ``scientific_effect`` — one line: what a scientist would care about ("none"
  for pure reads)

A tool function has the signature ``fn(ctx: ToolContext, **kwargs) -> Any`` and
its return value is wrapped in a :class:`ToolResult`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .permissions import Permission
from .trace import redact


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    permission: Permission
    read_only: bool
    requires_confirmation: bool
    scientific_effect: str
    #: JSON-ish description of accepted kwargs: {name: {"type", "required", "help"}}
    parameters: dict = field(default_factory=dict)
    #: what kind of object this tool's value is, when it is a first-class
    #: artifact a caller threads onward (e.g. "run_plan"). Lets the assistant
    #: capture a plan by capability, not by matching the tool's name.
    result_kind: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "permission", Permission.parse(self.permission))
        if self.read_only and self.permission > Permission.PLAN:
            raise ValueError(
                f"tool {self.name!r} is read_only but needs {self.permission.name}"
            )
        if self.read_only and self.requires_confirmation:
            raise ValueError(
                f"tool {self.name!r} is read_only but requires confirmation"
            )
        if not self.read_only and (self.scientific_effect or "none") == "none":
            raise ValueError(
                f"tool {self.name!r} mutates but declares no scientific_effect"
            )

    def to_dict(self) -> dict:
        return {
            "name": self.name, "description": self.description,
            "permission": self.permission.name, "read_only": self.read_only,
            "requires_confirmation": self.requires_confirmation,
            "scientific_effect": self.scientific_effect,
            "parameters": self.parameters,
            "result_kind": self.result_kind,
        }


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    tool: str
    value: Any = None
    error: str | None = None
    summary: str = ""
    duration_ms: float | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok, "tool": self.tool, "value": redact(self.value),
            "error": self.error, "summary": self.summary,
            "duration_ms": self.duration_ms,
        }


class Tool:
    """A bound (spec, function) pair. Call via the registry, not directly."""

    def __init__(self, spec: ToolSpec, fn: Callable) -> None:
        self.spec = spec
        self._fn = fn

    @property
    def name(self) -> str:
        return self.spec.name

    def invoke(self, ctx, /, **kwargs) -> ToolResult:
        t0 = time.perf_counter()
        try:
            value = self._fn(ctx, **kwargs)
            summary = _summarise(value)
            return ToolResult(ok=True, tool=self.name, value=value, summary=summary,
                              duration_ms=(time.perf_counter() - t0) * 1000)
        except Exception as err:  # noqa: BLE001 - tools must never leak a traceback to the LLM
            return ToolResult(ok=False, tool=self.name,
                              error=f"{type(err).__name__}: {err}",
                              duration_ms=(time.perf_counter() - t0) * 1000)


def _summarise(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return f"{len(value)} item(s)"
    if isinstance(value, dict):
        return ", ".join(sorted(value)[:6]) + ("…" if len(value) > 6 else "")
    return str(value)[:120]


# module-level registry of decorated tools, drained by ToolRegistry
_PENDING: list[Tool] = []


def tool(
    *,
    name: str,
    description: str,
    permission: Permission | str = Permission.OBSERVE,
    read_only: bool = True,
    requires_confirmation: bool = False,
    scientific_effect: str = "none",
    parameters: dict | None = None,
    result_kind: str = "",
) -> Callable:
    """Decorator that registers ``fn`` as a CryoStack tool."""

    def _wrap(fn: Callable) -> Callable:
        spec = ToolSpec(
            name=name, description=description,
            permission=Permission.parse(permission), read_only=read_only,
            requires_confirmation=requires_confirmation,
            scientific_effect=scientific_effect, parameters=parameters or {},
            result_kind=result_kind,
        )
        _PENDING.append(Tool(spec, fn))
        fn._cryostack_tool_spec = spec  # type: ignore[attr-defined]
        return fn

    return _wrap


def drain_pending() -> list[Tool]:
    out = list(_PENDING)
    _PENDING.clear()
    return out
