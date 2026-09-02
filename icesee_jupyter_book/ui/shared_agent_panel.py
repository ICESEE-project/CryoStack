"""Run Assistant panel — preview/beta (A9 + PASS 4 task 3).

A small UI over :class:`cryostack_src.agents.RunAssistant`. It shows the
proposed configuration and the validation result, and gates an **Approve
plan** control behind an explicit human acknowledgement. There is **no Submit
button** — a real submit backend is not wired yet — so approving only hands
the plan to the host's ``on_approve`` callback (which persists it for a human
to act on).

Design rules honoured:

* reuses the shared ``cryostack-*`` style vocabulary (no new visual system);
* the safety boundary is explicit in the copy and the layout;
* the panel is self-contained — any assistant error is caught and shown here,
  never raised into the gateway;
* nothing here submits, approves-for-execution, or advances a lifecycle.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from typing import Any, Callable

import ipywidgets as W

from cryostack_src.agents import AssistantResult, RunAssistant
from cryostack_src.agents.context import ToolContext


def _h(text: Any) -> str:
    return html.escape(str(text))


def _kv(label: str, value: str) -> str:
    return (f"<tr><th style='text-align:left;padding:2px 14px 2px 0;"
            f"white-space:nowrap;vertical-align:top'>{_h(label)}</th>"
            f"<td style='padding:2px 0'>{value}</td></tr>")


def _proposed_config_html(plan: dict) -> str:
    over = plan.get("parameter_overrides") or {}
    s = plan.get("slurm") or {}
    ds = plan.get("datasets") or []
    rows = [
        _kv("Model", _h(plan.get("model", "-"))),
        _kv("Example", _h(plan.get("example", "-"))),
        _kv("Resource", _h(plan.get("compute_resource", "-"))),
        _kv("Backend", _h(f"{plan.get('execution_mode','-')} / {plan.get('backend','-')}")),
        _kv("Scientific changes",
            ", ".join(f"{_h(k)} = {_h(v)}" for k, v in over.items())
            or "<span class='cryostack-help'>none</span>"),
        _kv("Slurm resources",
            _h(f"{s.get('nodes','?')} node(s), {s.get('tasks','?')} task(s), "
               f"{s.get('tasks_per_node','?')}/node, "
               f"{s.get('wall_time') or '(resource default)'}"
               + (f", account {s.get('account')}" if s.get('account') else ""))),
        _kv("Datasets", ", ".join(_h(d) for d in ds)
            or "<span class='cryostack-help'>none</span>"),
    ]
    return ("<div class='cryostack-group-title'>Proposed configuration</div>"
            f"<table style='border-collapse:collapse'>{''.join(rows)}</table>"
            f"<div class='cryostack-help'>plan digest "
            f"<code>{_h((plan.get('digest') or '')[:16])}…</code></div>")


def _validation_html(plan: dict) -> str:
    findings = plan.get("findings") or []
    if not findings and plan.get("validated"):
        body = "<div>✓ no issues found</div>"
    else:
        lines = []
        for f in findings:
            mark = {"error": "✗", "warning": "!", "info": "✓"}.get(f["level"], "·")
            colour = {"error": "#b00", "warning": "#a60"}.get(f["level"], "inherit")
            lines.append(f"<div style='color:{colour}'>{mark} "
                         f"{_h(f['message'])}</div>")
        body = "".join(lines) or "<div class='cryostack-help'>not validated</div>"
    approvals = plan.get("approvals_required") or []
    tail = ("<div class='cryostack-help'>Before this can run: "
            + _h(", ".join(approvals)) + "</div>") if approvals else ""
    return "<div class='cryostack-group-title'>Validation</div>" + body + tail


def _transcript_html(result: AssistantResult) -> str:
    parts = []
    for step in result.steps:
        if step.text:
            parts.append(f"<div>{_h(step.text)}</div>")
        for call, res in zip(step.tool_calls, step.tool_results):
            status = "ok" if res["ok"] else f"refused — {_h(res['error'])}"
            parts.append(f"<div class='cryostack-help'>· "
                         f"<code>{_h(call['name'])}</code> → {status}</div>")
    if result.text and (not result.steps or not result.steps[-1].text):
        parts.append(f"<div>{_h(result.text)}</div>")
    return "".join(parts)


@dataclass
class AgentPanel:
    container: W.VBox
    last_result: AssistantResult | None = None
    approvable_plan: dict | None = None
    _submit: Callable[[str], Any] = field(default=None, repr=False)
    _approve: Callable[[], Any] = field(default=None, repr=False)

    def ask(self, text: str) -> Any:
        return self._submit(text)

    def approve(self) -> Any:
        return self._approve()


def build_agent_panel(
    *,
    assistant: RunAssistant,
    build_context: Callable[[], ToolContext],
    on_approve: Callable[[dict], Any] | None = None,
) -> AgentPanel:
    _beta = ("<span style='font-size:11px;font-weight:600;letter-spacing:.04em;"
             "padding:1px 7px;border:1px solid currentColor;border-radius:10px;"
             "opacity:.7;margin-left:6px'>BETA</span>")
    header = W.HTML(
        f"<div class='cryostack-group-title'>Agent-assisted experiment {_beta}</div>"
        "<div class='cryostack-help'>"
        "The assistant helps you <b>prepare</b> an experiment from a description. "
        "CryoStack then validates the plan independently (remote identity, Slurm "
        "resources, the model's parameter rules, the backend preflight), and you "
        "review the exact configuration before approving. "
        "<b>Execution stays under explicit human control</b> — the assistant "
        "cannot approve or submit. Switch to Basic or Advanced for manual "
        "configuration."
        "</div>")
    question = W.Textarea(
        placeholder="Describe your experiment, e.g. run SquareIceShelf on PACE, "
                    "account <your-allocation>",
        layout=W.Layout(width="100%", height="64px"))
    ask_btn = W.Button(description="Create plan", button_style="primary")
    transcript = W.HTML()
    config_box = W.HTML()
    validation_box = W.HTML()
    ack = W.Checkbox(value=False, indent=False,
                     description="I have reviewed this plan")
    revise_btn = W.Button(description="Revise plan")
    approve_btn = W.Button(description="Approve plan", disabled=True)
    outcome = W.HTML()

    for w in (config_box, validation_box, ack, revise_btn, approve_btn):
        w.layout.display = "none"

    panel = AgentPanel(container=W.VBox(
        [header, question, ask_btn, transcript, config_box, validation_box,
         ack, W.HBox([revise_btn, approve_btn], layout=W.Layout(gap="10px")),
         outcome],
        layout=W.Layout(width="100%", gap="8px")))

    def _has_errors(plan: dict) -> bool:
        return any(f.get("level") == "error" for f in (plan.get("findings") or []))

    def _refresh_controls() -> None:
        plan = panel.approvable_plan
        show = plan is not None
        for w in (config_box, validation_box, ack, revise_btn, approve_btn):
            w.layout.display = "" if show else "none"
        # Approve requires: a plan, the human ack, no errors, AND that the plan
        # was actually validated (validated=True) — never approve an unvalidated
        # proposal even if an adapter skipped validate_run_plan.
        ok = (show and ack.value and not _has_errors(plan)
              and bool(plan.get("validated")))
        approve_btn.disabled = not ok

    def _submit(text: str) -> Any:
        outcome.value = ""
        try:
            ctx = build_context()
            result = assistant.handle(ctx, text)
        except Exception as err:  # the assistant must never break the gateway
            transcript.value = ("<div class='cryostack-help' style='color:#b00'>"
                                f"assistant unavailable: {_h(type(err).__name__)}"
                                "</div>")
            panel.approvable_plan = None
            _refresh_controls()
            return None
        panel.last_result = result
        transcript.value = _transcript_html(result)
        plan = result.proposed_plan
        if plan is not None:
            config_box.value = _proposed_config_html(plan)
            validation_box.value = _validation_html(plan)
        panel.approvable_plan = plan
        ack.value = False
        _refresh_controls()
        return result

    def _approve() -> Any:
        plan = panel.approvable_plan
        if plan is None or not ack.value or _has_errors(plan):
            outcome.value = ("<div class='cryostack-help' style='color:#b00'>"
                             "Review the plan and tick the box first.</div>")
            return None
        try:
            ref = on_approve(plan) if on_approve else None
        except Exception as err:
            outcome.value = ("<div class='cryostack-help' style='color:#b00'>"
                             f"could not record the approval: {_h(err)}</div>")
            return None
        outcome.value = (
            "<div class='cryostack-help'>Plan recorded for approval"
            + (f" (<code>{_h(ref)}</code>)" if ref else "")
            + ". It will not run until a human approves it — there is no "
            "automatic submission.</div>")
        return ref

    def _revise(_=None) -> None:
        panel.approvable_plan = None
        outcome.value = ""
        _refresh_controls()
        question.focus()

    ask_btn.on_click(lambda _b: _submit(question.value))
    approve_btn.on_click(lambda _b: _approve())
    revise_btn.on_click(_revise)
    ack.observe(lambda _c: _refresh_controls(), names="value")

    panel._submit = _submit
    panel._approve = _approve
    return panel


def build_agent_accordion(**kwargs) -> W.Accordion:
    """The gateway mounts this: a collapsed Accordion so the manual workflow
    stays primary and the agent is opt-in."""
    panel = build_agent_panel(**kwargs)
    acc = W.Accordion(children=[panel.container])
    acc.set_title(0, "🤖 Run Assistant (Beta)")
    acc.selected_index = None                 # collapsed by default
    acc._cryostack_agent_panel = panel        # for tests / callers
    return acc
