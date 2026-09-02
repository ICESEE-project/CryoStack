"""Provider-agnostic LLM adapter interface + a deterministic mock (A8).

CryoStack never imports an LLM vendor SDK. An orchestrator that wants to use a
real model implements :class:`LLMClient` in its own integration package and
passes it to :class:`~cryostack_src.agents.assistant.RunAssistant`.

:class:`ScriptedLLM` is the in-tree implementation used by every test: it
replays a fixed list of :class:`LLMResponse` objects, so assistant behaviour is
fully deterministic and no network call is ever made.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class LLMMessage:
    role: str            # "user" | "assistant" | "tool"
    content: str
    name: str = ""       # tool name, when role == "tool"


@dataclass(frozen=True)
class LLMToolCall:
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    """One model turn: free text and/or a set of tool calls to run."""
    text: str = ""
    tool_calls: tuple[LLMToolCall, ...] = ()

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@runtime_checkable
class LLMClient(Protocol):
    def complete(self, *, system: str, messages: list[LLMMessage],
                 tools: list[dict]) -> LLMResponse:
        ...


class ScriptedLLM:
    """Deterministic mock. Replays ``script`` one entry per ``complete`` call.
    Records what it was asked, for assertions."""

    def __init__(self, script: list[LLMResponse]) -> None:
        self._script = list(script)
        self._i = 0
        self.calls: list[dict] = []

    def complete(self, *, system: str, messages: list[LLMMessage],
                 tools: list[dict]) -> LLMResponse:
        self.calls.append({
            "system": system,
            "messages": [(m.role, m.content) for m in messages],
            "tool_names": [t.get("name") for t in tools],
        })
        if self._i >= len(self._script):
            return LLMResponse(text="(scripted model exhausted)")
        resp = self._script[self._i]
        self._i += 1
        return resp

    @property
    def exhausted(self) -> bool:
        return self._i >= len(self._script)
