"""Prototype "Run Assistant" panel (A9).

A deliberately small UI over :class:`cryostack_src.agents.RunAssistant`. It:

* takes a natural-language question, runs the assistant loop, shows the
  transcript and every tool call it made;
* renders the proposed run plan (model, example, overrides, the approvals it
  will need) when one was produced;
* shows an **Approve** control that is disabled until a *valid* plan exists and
  a human ticks the acknowledgement box. Approving only calls the host's
  ``on_approve`` callback with the plan dict — this panel never validates the
  approval, advances the lifecycle, or submits anything.

Presentation + wiring only. All policy lives in the agents package.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from typing import Any, Callable

import ipywidgets as W

from cryostack_src.agents import AssistantResult, RunAssistant
from cryostack_src.agents.context import ToolContext


def _h(text: str) -> str:
    return html.escape(str(text))


def _plan_summary_html(plan: dict) -> str:
    rows = [
        ("Model", plan.get("model")),
        ("Example", plan.get("example")),
        ("Execution", f"{plan.get('execution_mode')} / {plan.get('backend')}"),
        ("Compute resource", plan.get("compute_resource")),
        ("Run target", plan.get("run_target") or "(model default)"),
    ]
    over = plan.get("parameter_overrides") or {}
    rows.append(("Scientific overrides",
                 ", ".join(f"{k} = {v}" for k, v in over.items()) or "none"))
    body = "".join(
        f"<tr><th style='text-align:left;padding-right:12px;"
        f"vertical-align:top'>{_h(k)}</th><td>{_h(v)}</td></tr>"
        for k, v in rows)
    approvals = plan.get("approvals_required") or []
    errs = [f for f in plan.get("findings", []) if f.get("level") == "error"]
    warn = [f for f in plan.get("findings", []) if f.get("level") == "warning"]
    tail = ""
    if approvals:
        tail += ("<div class='cryostack-help'>Approvals required before this "
                 "can run: <b>" + _h(", ".join(approvals)) + "</b></div>")
    if errs:
        tail += ("<div class='cryostack-help' style='color:#b00'>Validation "
                 "errors: " + _h("; ".join(f["message"] for f in errs)) + "</div>")
    if warn:
        tail += ("<div class='cryostack-help'>Warnings: "
                 + _h("; ".join(f["message"] for f in warn)) + "</div>")
    return (f"<div class='cryostack-group-title'>Proposed run plan</div>"
            f"<table>{body}</table>{tail}"
            f"<div class='cryostack-help'>Plan digest "
            f"<code>{_h((plan.get('digest') or '')[:16])}…</code></div>")


def _transcript_html(result: AssistantResult) -> str:
    parts = [f"<div class='cryostack-group-title'>Assistant</div>"]
    for step in result.steps:
        if step.text:
            parts.append(f"<p>{_h(step.text)}</p>")
        for call, res in zip(step.tool_calls, step.tool_results):
            status = "ok" if res["ok"] else f"refused — {_h(res['error'])}"
            parts.append(
                f"<div class='cryostack-help'>· tool <code>{_h(call['name'])}</code>"
                f" ({_h(json.dumps(call['arguments']))}) → {status}</div>")
    if result.text and (not result.steps or not result.steps[-1].text):
        parts.append(f"<p>{_h(result.text)}</p>")
    return "".join(parts)


@dataclass
class AgentPanel:
    container: W.VBox
    #: last assistant result (None until a question is asked)
    last_result: AssistantResult | None = None
    #: the plan the human may approve (None unless valid)
    approvable_plan: dict | None = None
    _submit: Callable[[str], AssistantResult] = field(default=None, repr=False)
    _approve: Callable[[], Any] = field(default=None, repr=False)

    def ask(self, text: str) -> AssistantResult:
        return self._submit(text)

    def approve(self) -> Any:
        return self._approve()


def build_agent_panel(
    *,
    assistant: RunAssistant,
    build_context: Callable[[], ToolContext],
    on_approve: Callable[[dict], Any] | None = None,
) -> AgentPanel:
    question = W.Textarea(
        placeholder="e.g. set up the synthetic ice shelf on PACE at 260 K",
        layout=W.Layout(width="100%", height="70px"))
    ask_btn = W.Button(description="Ask the assistant", button_style="primary")
    transcript = W.HTML()
    plan_box = W.HTML()
    ack = W.Checkbox(value=False, indent=False,
                     description="I have reviewed this plan and approve it")
    approve_btn = W.Button(description="Submit for approval", disabled=True)
    approve_out = W.HTML()

    ack.layout.display = "none"
    approve_btn.layout.display = "none"

    panel = AgentPanel(container=W.VBox([
        W.HTML("<div class='cryostack-group-title'>CryoStack Run Assistant</div>"
               "<div class='cryostack-help'>The assistant can look things up and "
               "build a run plan. It cannot approve or submit a run — you do "
               "that.</div>"),
        question, ask_btn, transcript, plan_box, ack, approve_btn, approve_out,
    ], layout=W.Layout(width="100%", gap="8px")))

    def _refresh_approve_state() -> None:
        ok = panel.approvable_plan is not None
        ack.layout.display = "" if ok else "none"
        approve_btn.layout.display = "" if ok else "none"
        approve_btn.disabled = not (ok and ack.value)

    def _submit(text: str) -> AssistantResult:
        approve_out.value = ""
        ctx = build_context()
        result = assistant.handle(ctx, text)
        panel.last_result = result
        transcript.value = _transcript_html(result)
        if result.proposed_plan is not None:
            plan_box.value = _plan_summary_html(result.proposed_plan)
        else:
            plan_box.value = ""
        panel.approvable_plan = (
            result.proposed_plan if result.plan_is_valid else None)
        ack.value = False
        _refresh_approve_state()
        return result

    def _approve() -> Any:
        if panel.approvable_plan is None or not ack.value:
            approve_out.value = ("<div class='cryostack-help' style='color:#b00'>"
                                 "Review and tick the box first.</div>")
            return None
        out = on_approve(panel.approvable_plan) if on_approve else None
        approve_out.value = ("<div class='cryostack-help'>Plan sent to the "
                             "approval queue. It will not run until a human "
                             "approves it there.</div>")
        return out

    ask_btn.on_click(lambda _btn: _submit(question.value))
    approve_btn.on_click(lambda _btn: _approve())
    ack.observe(lambda _ch: _refresh_approve_state(), names="value")

    panel._submit = _submit
    panel._approve = _approve
    return panel
