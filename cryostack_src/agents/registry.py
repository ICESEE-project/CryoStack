"""``ToolRegistry`` — the single dispatch point for every agent tool call.

The registry is where the permission ceiling, the confirmation gate, and the
trace are enforced. An orchestrator (LLM agent, script, test) NEVER calls a tool
function directly — it calls ``registry.invoke(name, ctx, confirm=?, **kwargs)``.
"""
from __future__ import annotations

from typing import Iterable

from cryostack_src import perf

from .context import ToolContext
from .permissions import Permission, PermissionError
from .tools import Tool, ToolResult, ToolSpec, drain_pending


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # -- registration ---------------------------------------------------
    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name!r}")
        self._tools[tool.name] = tool

    def register_module_tools(self) -> None:
        """Register every ``@tool``-decorated function imported so far."""
        for t in drain_pending():
            self._tools.setdefault(t.name, t)

    # -- discovery (what an agent is allowed to see) -------------------
    def specs(self, *, ctx: ToolContext | None = None) -> list[ToolSpec]:
        out = [t.spec for t in self._tools.values()]
        if ctx is not None:
            out = [s for s in out if ctx.can(s.permission)]
        return sorted(out, key=lambda s: (s.permission, s.name))

    def describe(self, *, ctx: ToolContext | None = None) -> list[dict]:
        return [s.to_dict() for s in self.specs(ctx=ctx)]

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(f"no such tool: {name!r}") from None

    def names(self) -> list[str]:
        return sorted(self._tools)

    # -- dispatch -----------------------------------------------------
    def invoke(self, name: str, ctx: ToolContext, *, confirm: bool = False,
               **kwargs) -> ToolResult:
        try:
            tool = self.get(name)
        except KeyError as err:
            return ToolResult(ok=False, tool=name, error=str(err))

        spec = tool.spec

        # 1. permission ceiling
        if not ctx.can(spec.permission):
            ctx.trace.tool_call(name, args=_safe_args(kwargs),
                                permission=spec.permission.name, ok=False,
                                summary="refused: permission ceiling")
            return ToolResult(
                ok=False, tool=name,
                error=(f"permission denied: tool needs {spec.permission.name}, "
                       f"context ceiling is {ctx.max_permission.name}"),
            )

        # 2. confirmation gate
        if spec.requires_confirmation and not confirm:
            ctx.trace.tool_call(name, args=_safe_args(kwargs),
                                permission=spec.permission.name, ok=False,
                                summary="refused: confirmation required")
            return ToolResult(
                ok=False, tool=name,
                error=("confirmation required: this tool has a scientific / "
                       f"computational effect ({spec.scientific_effect}). "
                       "Re-invoke with confirm=True after the user acknowledges."),
            )

        # 3. dispatch
        with perf.span(f"agent tool {name}"):
            result = tool.invoke(ctx, **kwargs)
        ctx.trace.tool_call(name, args=_safe_args(kwargs),
                            permission=spec.permission.name, ok=result.ok,
                            summary=(result.summary if result.ok else (result.error or "")),
                            duration_ms=result.duration_ms)
        return result


def _safe_args(kwargs: dict) -> dict:
    # the Trace redactor handles secrets; keep args small in the trace
    return {k: (v if isinstance(v, (str, int, float, bool, type(None)))
                else f"<{type(v).__name__}>")
            for k, v in kwargs.items()}


# -- the process-wide default registry --------------------------------
_DEFAULT: ToolRegistry | None = None


def default_registry() -> ToolRegistry:
    """The lazily-built registry containing the shipped tool set."""
    global _DEFAULT
    if _DEFAULT is None:
        reg = ToolRegistry()
        from . import readonly_tools  # noqa: F401 - registers via @tool
        try:
            from . import planning_tools  # noqa: F401
        except ImportError:
            pass
        reg.register_module_tools()
        _DEFAULT = reg
    return _DEFAULT
