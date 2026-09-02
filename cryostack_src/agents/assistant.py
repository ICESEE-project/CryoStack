"""The CryoStack Run Assistant (A8).

A bounded agent. It helps a scientist *find an example, build a run plan, and
understand what the run needs*. It **cannot approve a plan and cannot submit a
run** — those are human actions (``approval`` / ``execution``). Its permission
ceiling is hard-capped at :data:`Permission.PLAN` regardless of the context it
is handed.

The loop is deterministic given the LLM: it calls
:meth:`LLMClient.complete`, runs whatever read/plan tools the model asks for
*through the registry* (which enforces the ceiling, the identity, and the
trace), feeds results back, and stops when the model emits no more tool calls
or the step budget is exhausted. If the model produced a validated plan, the
assistant returns it as a **proposal** for the human to approve — it never
advances the lifecycle itself.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from cryostack_src import perf

from .context import ToolContext
from .llm import LLMClient, LLMMessage, LLMResponse
from .permissions import Permission
from .registry import ToolRegistry, default_registry

#: hard ceiling — the assistant is never allowed above PLAN
ASSISTANT_CEILING = Permission.PLAN

_SYSTEM = """You are the CryoStack Run Assistant.

You help a scientist choose an ice-sheet model example, assemble a run plan,
and understand what running it requires. You work ONLY through the tools listed
below.

Hard rules:
* You cannot approve a plan and you cannot submit or run anything. A human does
  that. If the user asks you to "just run it", prepare and validate the plan
  and explain that they must approve it.
* You never invent scientific parameters. Use only the Basic-mode parameters a
  tool reports for the chosen model/example, and only values the user gave you
  or that a tool validates.
* If a tool returns an error, report it plainly; do not work around it.

Emit tool calls to gather information and to build/validate a plan. When you are
done, emit a final message with no tool calls summarising the plan and the
approvals it will need."""


@dataclass
class AssistantStep:
    index: int
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)


@dataclass
class AssistantResult:
    text: str
    trace_id: str
    steps: list[AssistantStep]
    proposed_plan: dict | None = None       # a validated RunPlan dict, if any
    plan_is_valid: bool = False
    approvals_required: list[str] = field(default_factory=list)
    submitted: bool = False                 # ALWAYS False — the assistant cannot submit

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "trace_id": self.trace_id,
            "steps": [vars(s) for s in self.steps],
            "proposed_plan": self.proposed_plan,
            "plan_is_valid": self.plan_is_valid,
            "approvals_required": self.approvals_required,
            "submitted": self.submitted,
        }


class RunAssistant:
    def __init__(self, *, llm: LLMClient, registry: ToolRegistry | None = None) -> None:
        self._llm = llm
        self._registry = registry or default_registry()

    def handle(self, ctx: ToolContext, user_message: str, *,
               max_steps: int = 8) -> AssistantResult:
        # hard-cap the context: the assistant never operates above PLAN
        ctx = ctx.with_ceiling(ASSISTANT_CEILING)
        ctx.trace.request(user_message)
        perf.event("agent request received")

        with perf.span("agent tool discovery"):
            tools = self._registry.describe(ctx=ctx)
        messages: list[LLMMessage] = [LLMMessage("user", user_message)]
        steps: list[AssistantStep] = []
        last_text = ""
        proposed_plan: dict | None = None

        for i in range(max_steps):
            with perf.span(f"agent model turn {i}"):
                resp: LLMResponse = self._llm.complete(
                    system=_SYSTEM, messages=list(messages), tools=tools)
            step = AssistantStep(index=i, text=resp.text)
            if resp.text:
                last_text = resp.text
                messages.append(LLMMessage("assistant", resp.text))

            if not resp.wants_tools:
                steps.append(step)
                break

            for call in resp.tool_calls:
                # the assistant NEVER passes confirm=True and never calls a
                # mutating tool; the registry would refuse anyway (ceiling).
                result = self._registry.invoke(call.name, ctx, **call.arguments)
                rd = result.to_dict()
                step.tool_calls.append({"name": call.name,
                                        "arguments": _safe(call.arguments)})
                step.tool_results.append({"name": call.name, "ok": rd["ok"],
                                          "error": rd["error"],
                                          "summary": rd["summary"]})
                messages.append(LLMMessage(
                    "tool", json.dumps(_trim(rd), sort_keys=True), name=call.name))
                if result.ok and call.name == "validate_run_plan":
                    proposed_plan = result.value
                elif result.ok and call.name == "prepare_run_plan" and proposed_plan is None:
                    proposed_plan = result.value
            steps.append(step)
        else:
            last_text = last_text or "(step budget exhausted before the model finished)"

        plan_has_errors = bool(proposed_plan) and any(
            f.get("level") == "error" for f in proposed_plan.get("findings", []))
        plan_valid = (bool(proposed_plan) and not plan_has_errors
                      and proposed_plan.get("validated", False))
        approvals = list(proposed_plan.get("approvals_required", [])) if proposed_plan else []

        return AssistantResult(
            text=last_text, trace_id=ctx.trace.trace_id, steps=steps,
            proposed_plan=proposed_plan, plan_is_valid=plan_valid,
            approvals_required=approvals, submitted=False)


def _safe(d: dict) -> dict:
    return {k: (v if isinstance(v, (str, int, float, bool, type(None)))
                else f"<{type(v).__name__}>") for k, v in (d or {}).items()}


def _trim(result_dict: dict) -> dict:
    """Keep the tool result the model sees small and free of local paths."""
    v = result_dict.get("value")
    if isinstance(v, list) and len(v) > 20:
        v = v[:20] + [f"... (+{len(v) - 20} more)"]
    return {"ok": result_dict["ok"], "error": result_dict["error"],
            "summary": result_dict["summary"], "value": v}
