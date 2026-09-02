"""Provider adapter boundary (PASS 4, task 8).

``llm.LLMClient`` is the whole contract a production model provider implements.
This module gives:

* :func:`assert_declarative_tools` — the guard that proves an adapter only ever
  sees **tool descriptions** (name / description / JSON-ish params /
  permission), never a callable, a path, an SSH handle, or an AWS primitive;
* :class:`RuleBasedAdapter` — a deterministic, **network-free** adapter that
  turns a few English intents into structured tool calls. Not an LLM; used by
  demos and the evaluation harness so behaviour is reproducible;
* :class:`AnthropicAdapterSkeleton` / :class:`OpenAIAdapterSkeleton` — commented
  reference implementations that raise ``NotImplementedError``. They show the
  request/response mapping and nothing else. **No SDK is imported; no API key
  is read; no network call is made anywhere in this file.**

The rule the boundary enforces: *a provider helps transform user intent into
structured planning / tool requests. It never receives an execution
primitive.* Everything with effect (approval, execution, submission) happens on
the CryoStack side, after a human approves a digest.
"""
from __future__ import annotations

import re
from typing import Any

from .llm import LLMMessage, LLMResponse, LLMToolCall

_ALLOWED_LEAF = (str, int, float, bool, type(None))


def assert_declarative_tools(tools: list[dict]) -> None:
    """Raise if anything handed to a provider is not plain declarative data.

    A tool spec must be a dict of leaf values / nested dicts / lists of those —
    never a callable, a Path, a socket, a bridge, or an object with behaviour.
    """
    def _check(obj: Any, where: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                _check(v, f"{where}.{k}")
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                _check(v, f"{where}[{i}]")
        elif callable(obj) or not isinstance(obj, _ALLOWED_LEAF):
            raise TypeError(
                f"non-declarative value passed to the LLM provider at {where}: "
                f"{type(obj).__name__}")

    for spec in tools:
        if not isinstance(spec, dict) or "name" not in spec:
            raise TypeError("each tool must be a dict with a 'name'")
        _check(spec, spec.get("name", "?"))


class BaseAdapter:
    """Optional base: runs :func:`assert_declarative_tools` on every call so a
    subclass physically cannot be handed an execution primitive."""

    def complete(self, *, system: str, messages: list[LLMMessage],
                 tools: list[dict]) -> LLMResponse:
        assert_declarative_tools(tools)
        return self._complete(system=system, messages=messages, tools=tools)

    def _complete(self, *, system: str, messages: list[LLMMessage],
                  tools: list[dict]) -> LLMResponse:  # pragma: no cover
        raise NotImplementedError


# ── deterministic, network-free adapter ─────────────────────────────
_MODEL_RE = re.compile(r"\b(issm|icepack)\b", re.I)
_RESOURCE_RE = re.compile(r"\b(pace|frontera|anvil|expanse|bridges2?|delta)\b", re.I)
_TEMP_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:k|kelvin)\b", re.I)
_NODES_RE = re.compile(r"\b(\d+)\s*nodes?\b", re.I)
_EXAMPLE_RE = re.compile(r"\b(?:run|use|example)\s+([A-Za-z0-9][\w./-]{2,})", re.I)


class RuleBasedAdapter(BaseAdapter):
    """Maps a single English instruction to a deterministic tool-call plan:
    ``list_examples`` → ``prepare_run_plan`` → ``validate_run_plan`` → a final
    message. It never fabricates a scientific value the user did not state and
    never emits an approve/execute call (there are none to emit).

    ``default_resource`` / ``default_example`` fill gaps so a bare request still
    produces a plan for review.
    """

    def __init__(self, *, default_resource: str = "pace",
                 default_example: str = "") -> None:
        self._default_resource = default_resource
        self._default_example = default_example
        self._step = 0
        self._plan: dict | None = None

    def _complete(self, *, system, messages, tools) -> LLMResponse:
        names = {t["name"] for t in tools}
        user = next((m.content for m in messages if m.role == "user"), "")
        model = (_MODEL_RE.search(user) or [None, "issm"])[1].lower() \
            if _MODEL_RE.search(user) else "issm"
        resource = (_RESOURCE_RE.search(user).group(1).lower()
                    if _RESOURCE_RE.search(user) else self._default_resource)
        example = (_EXAMPLE_RE.search(user).group(1)
                   if _EXAMPLE_RE.search(user) else self._default_example)
        overrides: dict = {}
        if model == "icepack" and _TEMP_RE.search(user):
            overrides["ice_temperature"] = float(_TEMP_RE.search(user).group(1))
        slurm: dict = {}
        if _NODES_RE.search(user):
            slurm["nodes"] = int(_NODES_RE.search(user).group(1))

        self._step += 1
        if self._step == 1 and "prepare_run_plan" in names and example:
            args = {"model": model, "example": example, "compute_resource": resource}
            if overrides:
                args["parameter_overrides"] = overrides
            if slurm:
                args["slurm"] = slurm
            return LLMResponse(text=f"Preparing a {model} plan for {example} on "
                                    f"{resource}.",
                              tool_calls=(LLMToolCall("prepare_run_plan", args),))
        if self._step == 2 and self._plan and "validate_run_plan" in names:
            return LLMResponse(tool_calls=(
                LLMToolCall("validate_run_plan", {"plan": self._plan}),))
        return LLMResponse(
            text="Plan ready for your review. It will not run until you "
                 "approve it." if self._plan else
                 "I could not build a plan from that request — tell me the "
                 "model, example, and compute resource.")

    # the harness feeds tool results back so the adapter can thread the plan
    def observe_tool_result(self, name: str, value: Any) -> None:
        if name in ("prepare_run_plan", "validate_run_plan") and isinstance(value, dict):
            self._plan = value


# ── reference skeletons (no SDK, no network, no key) ────────────────
class AnthropicAdapterSkeleton(BaseAdapter):
    """Reference only. A real implementation would, inside ``_complete``:

    1. ``client = anthropic.Anthropic()``  (key from the provider's own env,
       never from CryoStack, never logged);
    2. translate ``tools`` (already declarative) to the Messages API
       ``tools=[{"name", "description", "input_schema"}]`` shape;
    3. map :class:`LLMMessage` → ``messages=[{"role", "content"}]`` and
       ``system`` → the ``system`` parameter;
    4. call ``client.messages.create(model=…, max_tokens=…, tools=…, …)``;
    5. map ``response.content`` blocks back: ``text`` blocks → ``LLMResponse.text``,
       ``tool_use`` blocks → ``LLMToolCall(name=block.name, arguments=block.input)``.

    It returns ONLY text + tool calls. It has no way to submit, approve, ssh,
    or touch AWS — those verbs are not in ``tools`` (the registry only exposes
    OBSERVE/PLAN tools to an assistant context).
    """

    def _complete(self, *, system, messages, tools):
        raise NotImplementedError(
            "AnthropicAdapterSkeleton is a reference; implement _complete in "
            "your own integration package (see the docstring).")


class OpenAIAdapterSkeleton(BaseAdapter):
    """Reference only. Same shape via the Chat Completions / Responses API:
    ``tools`` → ``[{"type": "function", "function": {"name", "description",
    "parameters"}}]``; a returned ``tool_calls`` array →
    ``LLMToolCall(name=call.function.name,
    arguments=json.loads(call.function.arguments))``.
    """

    def _complete(self, *, system, messages, tools):
        raise NotImplementedError(
            "OpenAIAdapterSkeleton is a reference; implement _complete in your "
            "own integration package (see the docstring).")
