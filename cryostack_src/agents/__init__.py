"""Agentic CryoStack — a small, provider-agnostic layer that lets an
orchestrator (an LLM agent, a script, a test) drive CryoStack through **bounded,
typed, permission-declaring tools** over the APIs the UI already uses.

Design contract: `overnight/AGENT_SAFETY_MODEL.md`. In short:

* an agent has no capability the authenticated user does not have, and several
  the user *does* have are withheld (no shell, no arbitrary FS, no secrets);
* tools declare a minimum :class:`~cryostack_src.agents.permissions.Permission`;
  a :class:`~cryostack_src.agents.context.ToolContext` carries the authenticated
  identity and a permission ceiling; the registry refuses under-privileged
  calls;
* nothing with scientific or computational effect happens without an explicit,
  digest-bound human approval (see ``planning`` / ``approval`` / ``execution``).

This package never imports an LLM SDK. ``llm.LLMClient`` is an interface with a
deterministic mock for tests.
"""
from __future__ import annotations

from .context import ToolContext, build_tool_context
from .permissions import Permission, PermissionError
from .registry import ToolRegistry, default_registry
from .tools import ToolResult, ToolSpec, tool
from .trace import Trace, TraceEvent

__all__ = [
    "Permission", "PermissionError",
    "ToolContext", "build_tool_context",
    "ToolSpec", "ToolResult", "tool",
    "ToolRegistry", "default_registry",
    "Trace", "TraceEvent",
]
