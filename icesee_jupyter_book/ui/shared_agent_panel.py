"""Run Assistant panel — preview/beta (A9 + PASS 4 task 3).

A small UI over :class:`cryostack_src.agents.RunAssistant`. After **Create
plan** it renders a human-review surface built entirely from the canonical
validated ``RunPlan`` dict (never from assistant prose, never from a parallel
agent-specific config object):

* **Proposed configuration** — the important experiment settings by default,
  each tagged with its provenance where the plan records it (``requested`` vs
  ``CryoStack default``), plus a collapsible **View full configuration** with
  the complete resolved plan;
* **CryoStack validation** — errors, warnings and info, clearly separated,
  plus what must still be approved before the plan can run.

An **Approve plan** control is gated behind an explicit human acknowledgement
and binds only to the exact digest shown. There is **no Submit button** — a
real submit backend is not wired — so approving only hands the plan to the
host's ``on_approve`` callback (which persists it for a human to act on).
**Revise plan** drops the current proposal, so any prior approval no longer
applies (the digest changes).

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

from cryostack_src.agents import AssistantResult, RunAssistant, RunPlan
from cryostack_src.agents.context import ToolContext


def _h(text: Any) -> str:
    return html.escape(str(text))


def _kv(label: str, value: str) -> str:
    return (f"<tr><th style='text-align:left;padding:2px 14px 2px 0;"
            f"white-space:nowrap;vertical-align:top'>{_h(label)}</th>"
            f"<td style='padding:2px 0'>{value}</td></tr>")


#: provenance value -> (chip text, fg, bg)
_PROV = {
    "requested": ("from your request", "#1d4ed8", "rgba(37, 99, 235, 0.10)"),
    "inferred": ("assistant inferred", "#1d4ed8", "rgba(37, 99, 235, 0.10)"),
    "default": ("CryoStack default", "#a16207", "rgba(202, 138, 4, 0.13)"),
}


def _prov(plan: dict, *keys: str) -> str:
    """A small provenance chip for the first key the plan records, or ''."""
    prov = plan.get("provenance") or {}
    for key in keys:
        src = prov.get(key)
        if src in _PROV:
            label, fg, bg = _PROV[src]
            return (f"<span style='margin-left:8px;font-size:10px;"
                    f"font-weight:700;padding:1px 6px;border-radius:9px;"
                    f"color:{fg};background:{bg};white-space:nowrap'>"
                    f"{label}</span>")
    return ""


def _proposed_config_html(plan: dict) -> str:
    over = plan.get("parameter_overrides") or {}
    s = plan.get("slurm") or {}
    ds = plan.get("datasets") or []
    solvers = plan.get("detected_solvers") or []
    none = "<span class='cryostack-help'>none</span>"

    slurm_defaulted = any(
        (plan.get("provenance") or {}).get(f"slurm.{k}") == "default"
        for k in ("nodes", "tasks", "tasks_per_node", "wall_time"))
    rows = [
        _kv("Model", _h(plan.get("model", "-")) + _prov(plan, "model")),
        _kv("Example", _h(plan.get("example", "-")) + _prov(plan, "example")),
        _kv("Run target", _h(plan.get("run_target") or "-")
            + _prov(plan, "run_target")),
        _kv("Execution mode", _h(plan.get("execution_mode", "-"))
            + _prov(plan, "execution_mode")),
        _kv("Software backend",
            _h(plan.get("backend", "-"))
            + " <span class='cryostack-help'>("
            + ("Spack environment" if plan.get("backend") == "spack"
               else "tested container image") + ")</span>"
            + _prov(plan, "backend")),
        _kv("Compute profile", _h(plan.get("compute_resource", "-"))
            + _prov(plan, "compute_resource")),
        _kv("Slurm resources",
            _h(f"{s.get('nodes', '?')} node(s), {s.get('tasks', '?')} task(s), "
               f"{s.get('tasks_per_node', '?')}/node, "
               f"{s.get('wall_time') or '(resource default)'}"
               + (f", account {s.get('account')}" if s.get('account') else ""))
            + (" <span style='margin-left:8px;font-size:10px;font-weight:700;"
               "padding:1px 6px;border-radius:9px;color:#a16207;"
               "background:rgba(202,138,4,0.13)'>CryoStack default</span>"
               if slurm_defaulted else "")),
        _kv("Model overrides",
            ", ".join(f"{_h(k)} = {_h(v)}" for k, v in over.items()) or none),
        _kv("Datasets", ", ".join(_h(d) for d in ds) or none),
        _kv("Expected outputs", _h(plan.get("expected_result_contract") or "-")),
    ]
    if solvers:
        rows.append(_kv("Detected solvers", ", ".join(_h(x) for x in solvers)))

    legend = ""
    if plan.get("provenance"):
        legend = (
            "<div class='cryostack-help' style='margin:2px 0 6px'>"
            "<span style='font-weight:700;color:#1d4ed8'>from your request</span>"
            " — taken from your description &nbsp;·&nbsp; "
            "<span style='font-weight:700;color:#a16207'>CryoStack default</span>"
            " — filled in for you from the compute profile or the example"
            "</div>")
    return ("<div class='cryostack-group-title'>Proposed configuration</div>"
            + legend
            + f"<table style='border-collapse:collapse'>{''.join(rows)}</table>"
            + "<div class='cryostack-help'>plan digest "
            + f"<code>{_h((plan.get('digest') or '')[:16])}…</code></div>")


def _full_config_html(plan: dict) -> str:
    """The complete resolved configuration, verbatim from the canonical plan."""
    shown = {k: v for k, v in plan.items() if k != "findings"}
    body = _h(json.dumps(shown, indent=2, sort_keys=True))
    return ("<div class='cryostack-help' style='margin-bottom:4px'>"
            "The exact resolved plan this approval binds to.</div>"
            f"<pre class='cryostack-code-block' style='max-height:340px;"
            f"overflow:auto'>{body}</pre>")


def _validation_html(plan: dict) -> str:
    findings = plan.get("findings") or []
    by = {"error": [], "warning": [], "info": []}
    for f in findings:
        by.get(f.get("level"), by["info"]).append(f.get("message", ""))

    parts = ["<div class='cryostack-group-title'>CryoStack validation</div>"]
    if not findings and plan.get("validated"):
        parts.append("<div>✓ no issues found</div>")
    elif not findings:
        parts.append("<div class='cryostack-help'>not validated</div>")
    if by["error"]:
        parts.append("<div style='font-weight:700;color:#b00;margin-top:4px'>"
                     "Errors — the plan cannot run until these are fixed</div>")
        parts += [f"<div style='color:#b00'>✗ {_h(m)}</div>" for m in by["error"]]
    if by["warning"]:
        parts.append("<div style='font-weight:700;color:#a60;margin-top:4px'>"
                     "Warnings</div>")
        parts += [f"<div style='color:#a60'>! {_h(m)}</div>" for m in by["warning"]]
    if by["info"]:
        parts.append("<div style='font-weight:700;margin-top:4px'>"
                     "Before this can run</div>")
        parts += [f"<div>✓ {_h(m)}</div>" for m in by["info"]]

    approvals = plan.get("approvals_required") or []
    if approvals:
        parts.append("<div class='cryostack-help' style='margin-top:4px'>"
                     "Still required: " + _h(", ".join(approvals)) + "</div>")
    return "".join(parts)


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
        "review the exact configuration below before approving. "
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
    full_config_box = W.HTML()
    full_config_acc = W.Accordion(children=[full_config_box])
    full_config_acc.set_title(0, "View full configuration")
    full_config_acc.selected_index = None
    ack = W.Checkbox(value=False, indent=False,
                     description="I have reviewed this plan")
    revise_btn = W.Button(description="Revise plan")
    approve_btn = W.Button(description="Approve plan", disabled=True)
    outcome = W.HTML()

    _reviewables = (config_box, validation_box, full_config_acc, ack,
                    revise_btn, approve_btn)
    for w in _reviewables:
        w.layout.display = "none"

    panel = AgentPanel(container=W.VBox(
        [header, question, ask_btn, transcript, config_box, validation_box,
         full_config_acc, ack,
         W.HBox([revise_btn, approve_btn], layout=W.Layout(gap="10px")),
         outcome],
        layout=W.Layout(width="100%", gap="8px")))

    def _has_errors(plan: dict) -> bool:
        return any(f.get("level") == "error" for f in (plan.get("findings") or []))

    def _digest_matches(plan: dict) -> bool:
        """Approve must bind to the exact configuration shown."""
        want = plan.get("digest")
        if not want:
            return False
        try:
            return RunPlan.from_dict(plan).digest() == want
        except Exception:
            return False

    def _refresh_controls() -> None:
        plan = panel.approvable_plan
        show = plan is not None
        for w in _reviewables:
            w.layout.display = "" if show else "none"
        # Approve requires: a plan, the human ack, no errors, the plan was
        # actually validated, AND the displayed digest still matches the plan.
        ok = (show and ack.value and not _has_errors(plan)
              and bool(plan.get("validated")) and _digest_matches(plan))
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
            full_config_box.value = _full_config_html(plan)
        panel.approvable_plan = plan
        ack.value = False
        full_config_acc.selected_index = None
        _refresh_controls()
        return result

    def _approve() -> Any:
        plan = panel.approvable_plan
        if plan is None or not ack.value or _has_errors(plan):
            outcome.value = ("<div class='cryostack-help' style='color:#b00'>"
                             "Review the plan and tick the box first.</div>")
            return None
        if not _digest_matches(plan):
            outcome.value = ("<div class='cryostack-help' style='color:#b00'>"
                             "The displayed configuration no longer matches its "
                             "digest — create the plan again before approving."
                             "</div>")
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
            + f", bound to digest <code>{_h((plan.get('digest') or '')[:16])}…"
            "</code>. It will not run until a human approves it — there is no "
            "automatic submission.</div>")
        return ref

    def _revise(_=None) -> None:
        # Drop the current proposal: any prior approval no longer applies
        # because the next plan carries a different digest.
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
