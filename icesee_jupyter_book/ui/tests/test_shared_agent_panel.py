"""Run Assistant panel (A9 + PASS 4 task 3): shows the proposed config + the
validation, gates Approve behind a human ack, has NO Submit button, and an
assistant error never escapes the panel."""
from __future__ import annotations

import sys
from pathlib import Path

import ipywidgets as W
import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.agents import (
    LLMResponse,
    LLMToolCall,
    Permission,
    RuleBasedAdapter,
    RunAssistant,
    ScriptedLLM,
    Trace,
)
from cryostack_src.agents.context import ToolContext
from cryostack_src.workspace import WorkspaceUser
from icesee_jupyter_book.ui.shared_agent_panel import (
    build_agent_accordion,
    build_agent_panel,
)

_USER = WorkspaceUser(user_id="panel-u", source="cryostack-auth")


def _ctx_factory():
    return ToolContext(user=_USER, application="icesheets",
                       max_permission=Permission.PLAN,
                       trace=Trace(user_id=_USER.user_id))


def _widgets(root, kind):
    out = []
    def walk(w):
        if isinstance(w, kind):
            out.append(w)
        for c in getattr(w, "children", ()):
            walk(c)
    walk(root)
    return out


def _html(root) -> str:
    return "\n".join(w.value for w in _widgets(root, W.HTML))


def _btn(root, desc):
    return next(b for b in _widgets(root, W.Button) if b.description == desc)


# ── no plan yet ─────────────────────────────────────────────────────
def test_no_approve_control_without_a_plan():
    asst = RunAssistant(llm=ScriptedLLM([LLMResponse(text="Which resource?")]))
    approved = []
    panel = build_agent_panel(assistant=asst, build_context=_ctx_factory,
                              on_approve=approved.append)
    panel.ask("help me run something")
    assert "Which resource?" in _html(panel.container)
    assert panel.approvable_plan is None
    assert _btn(panel.container, "Approve plan").layout.display == "none"
    panel.approve()
    assert approved == []


def test_there_is_no_submit_button():
    panel = build_agent_panel(
        assistant=RunAssistant(llm=ScriptedLLM([LLMResponse(text="hi")])),
        build_context=_ctx_factory)
    labels = {b.description.lower() for b in _widgets(panel.container, W.Button)}
    assert not any("submit" in x or "run" in x for x in labels)
    assert "approve plan" in labels and "revise plan" in labels


def test_approve_stays_disabled_for_an_unvalidated_plan():
    """PASS 4 review (security P2): even if an adapter emits prepare_run_plan
    but skips validate_run_plan, Approve must not enable."""
    from cryostack_src.agents.registry import default_registry
    reg = default_registry()
    orig = reg.invoke
    captured = {}

    def _spy(name, c, **kw):
        r = orig(name, c, **kw)
        if name == "prepare_run_plan" and r.ok:
            captured["plan"] = r.value
        return r
    reg.invoke = _spy

    llm = ScriptedLLM([
        LLMResponse(tool_calls=(LLMToolCall("prepare_run_plan", {
            "model": "issm", "example": "SquareIceShelf", "compute_resource": "pace",
            "slurm": {"account": "a", "wall_time": "01:00:00"}}),)),
        LLMResponse(text="here's a plan"),          # NO validate_run_plan
    ])
    panel = build_agent_panel(assistant=RunAssistant(llm=llm),
                              build_context=_ctx_factory)
    try:
        res = panel.ask("run SquareIceShelf on pace")
    finally:
        reg.invoke = orig
    if "plan" not in captured:
        pytest.skip("example not resolvable")
    assert res.proposed_plan is not None
    assert res.proposed_plan.get("validated") in (False, None)
    for cb in _widgets(panel.container, W.Checkbox):
        cb.value = True
    assert _btn(panel.container, "Approve plan").disabled is True


def test_assistant_error_is_contained():
    class _Boom:
        def complete(self, **kw):
            raise RuntimeError("model exploded")
    panel = build_agent_panel(assistant=RunAssistant(llm=_Boom()),
                              build_context=_ctx_factory)
    panel.ask("do a thing")            # must not raise
    assert "assistant unavailable" in _html(panel.container)
    assert panel.approvable_plan is None


# ── a valid plan ────────────────────────────────────────────────────
@pytest.mark.skipif(not Path("/home/bkyanjo3/icepack").is_dir(),
                    reason="examples not resolvable here")
def test_valid_plan_flow(monkeypatch):
    monkeypatch.setenv("ICEPACK_ROOT", "/home/bkyanjo3/icepack")
    sent = []
    panel = build_agent_panel(
        assistant=RunAssistant(llm=RuleBasedAdapter(default_example="SquareIceShelf")),
        build_context=_ctx_factory,
        on_approve=lambda plan: sent.append(plan) or "plan-42")
    result = panel.ask("run SquareIceShelf on pace, account gts-lab")
    if result.proposed_plan is None:
        pytest.skip("example not resolvable")

    assert "Proposed configuration" in _html(panel.container)
    assert "CryoStack validation" in _html(panel.container)
    # the human-review surface is built from the canonical plan
    assert "plan digest" in _html(panel.container)
    accs = _widgets(panel.container, W.Accordion)
    assert any("View full configuration" in a.get_title(0) for a in accs)
    approve = _btn(panel.container, "Approve plan")

    if not result.plan_is_valid:
        assert approve.disabled is True          # errors block approval
        return

    assert approve.disabled is True              # ack not ticked
    panel.approve()
    assert sent == []
    for cb in _widgets(panel.container, W.Checkbox):
        cb.value = True
    assert approve.disabled is False
    ref = panel.approve()
    assert ref == "plan-42" and sent
    assert "no automatic submission" in _html(panel.container)


# ── human-review surface: canonical config, provenance, digest binding ──
def _plan_dict(**over):
    from cryostack_src.agents import RunPlan, SlurmRequest
    base = dict(application="icesheets", model="issm", example="SquareIceShelf",
                execution_mode="remote", compute_resource="pace", backend="spack",
                run_target="runme.m",
                slurm=SlurmRequest(job_name="ISSM", wall_time="01:00:00",
                                   account="gts"))
    base.update(over)
    p = RunPlan(**base)
    return p.with_findings((), approvals_required=("compute-submission",)).to_dict()


class _FakeAsst:
    """Minimal stand-in: the panel only calls ``assistant.handle``."""
    def __init__(self, plan):
        self._plan = plan

    def handle(self, ctx, text):
        from cryostack_src.agents.assistant import AssistantResult
        return AssistantResult(text="here is a plan", trace_id="t", steps=[],
                               proposed_plan=self._plan)


def _scripted_panel(plan, on_approve=None):
    return build_agent_panel(assistant=_FakeAsst(plan),
                             build_context=_ctx_factory,
                             on_approve=on_approve or (lambda p: "ref-1"))


def test_review_surface_renders_the_canonical_plan_fields():
    plan = _plan_dict(parameter_overrides={"friction": 100.0})
    plan["provenance"] = {"example": "requested", "slurm.wall_time": "default",
                          "backend": "default"}
    panel = _scripted_panel(plan)
    panel.ask("run it")
    blob = _html(panel.container)
    for needle in ("Proposed configuration", "CryoStack validation",
                   "Software backend", "Compute profile", "Expected outputs",
                   "Model overrides", "friction = 100.0"):
        assert needle in blob, needle
    # provenance chips appear when the plan records provenance
    assert "from your request" in blob and "CryoStack default" in blob
    # the full-config accordion carries the resolved plan verbatim
    accs = _widgets(panel.container, W.Accordion)
    full = next(a for a in accs if "View full configuration" in a.get_title(0))
    assert plan["digest"][:16] in _html(full)


def test_approve_binds_only_to_the_displayed_digest():
    sent = []
    plan = _plan_dict()
    panel = _scripted_panel(plan, on_approve=lambda p: sent.append(p) or "ok")
    panel.ask("run it")
    for cb in _widgets(panel.container, W.Checkbox):
        cb.value = True
    assert _btn(panel.container, "Approve plan").disabled is False
    # tamper with the displayed plan after review -> digest no longer matches
    panel.approvable_plan = {**plan, "parameter_overrides": {"friction": 1.0}}
    assert panel.approve() is None
    assert sent == []
    assert "no longer matches its digest" in _html(panel.container)


def test_revise_drops_the_proposal_and_disables_approve():
    plan = _plan_dict()
    panel = _scripted_panel(plan)
    panel.ask("run it")
    for cb in _widgets(panel.container, W.Checkbox):
        cb.value = True
    assert _btn(panel.container, "Approve plan").disabled is False
    _btn(panel.container, "Revise plan").click()
    assert panel.approvable_plan is None
    assert _btn(panel.container, "Approve plan").disabled is True
    assert _btn(panel.container, "Approve plan").layout.display == "none"


def test_no_agent_config_or_workspace_execution_path():
    src = (Path(__file__).resolve().parents[1] / "shared_agent_panel.py").read_text()
    for banned in ("agent_config", "agent_workspace", "agent_submit",
                   "SubmitBackend", "agent_cloud", "agent_slurm"):
        assert banned not in src


# ── mounts as a collapsed accordion ─────────────────────────────────
def test_accordion_is_collapsed_and_titled():
    acc = build_agent_accordion(
        assistant=RunAssistant(llm=ScriptedLLM([LLMResponse(text="hi")])),
        build_context=_ctx_factory)
    assert isinstance(acc, W.Accordion)
    assert acc.selected_index is None
    assert "Run Assistant" in acc.get_title(0)
    assert hasattr(acc, "_cryostack_agent_panel")
