"""A9: prototype Run Assistant panel -- shows the plan, gates Approve behind a
human acknowledgement, never submits."""
from __future__ import annotations

import sys
from pathlib import Path

import ipywidgets as W

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.agents import (
    LLMResponse,
    LLMToolCall,
    Permission,
    RunAssistant,
    ScriptedLLM,
    Trace,
)
from cryostack_src.agents.context import ToolContext
from cryostack_src.workspace import WorkspaceUser
from icesee_jupyter_book.ui.shared_agent_panel import build_agent_panel

_USER = WorkspaceUser(user_id="panel-u", source="cryostack-auth")


def _ctx_factory():
    return ToolContext(user=_USER, application="icesheets",
                       max_permission=Permission.PLAN,
                       trace=Trace(user_id=_USER.user_id))


def _all_html(widget) -> str:
    out = []
    def walk(w):
        if isinstance(w, W.HTML):
            out.append(w.value)
        for c in getattr(w, "children", ()):
            walk(c)
    walk(widget)
    return "\n".join(out)


def test_panel_shows_transcript_and_no_approve_control_without_a_plan():
    asst = RunAssistant(llm=ScriptedLLM([
        LLMResponse(text="I can help with that. Which resource?")]))
    approved = []
    panel = build_agent_panel(assistant=asst, build_context=_ctx_factory,
                              on_approve=approved.append)
    panel.ask("help me run something")

    assert "I can help with that" in _all_html(panel.container)
    assert panel.approvable_plan is None
    # approve is a no-op with no plan
    panel.approve()
    assert approved == []


def test_valid_plan_enables_approve_only_after_acknowledgement():
    prepared = {}
    class _LLM(ScriptedLLM):
        def complete(self, **kw):
            r = super().complete(**kw)
            calls = []
            for c in r.tool_calls:
                if c.name == "validate_run_plan" and "plan" in prepared:
                    calls.append(LLMToolCall("validate_run_plan",
                                             {"plan": prepared["plan"]}))
                else:
                    calls.append(c)
            return LLMResponse(text=r.text, tool_calls=tuple(calls))

    llm = _LLM([
        LLMResponse(tool_calls=(LLMToolCall("prepare_run_plan", {
            "model": "issm", "example": "SquareIceShelf", "compute_resource": "pace",
            "slurm": {"account": "a", "wall_time": "01:00:00"}}),)),
        LLMResponse(tool_calls=(LLMToolCall("validate_run_plan", {"plan": "?"}),)),
        LLMResponse(text="Ready for your approval."),
    ])
    asst = RunAssistant(llm=llm)
    from cryostack_src.agents.registry import default_registry
    reg = default_registry()
    orig = reg.invoke
    def _spy(name, c, **kw):
        res = orig(name, c, **kw)
        if name == "prepare_run_plan" and res.ok:
            prepared["plan"] = res.value
        return res
    reg.invoke = _spy

    sent = []
    panel = build_agent_panel(assistant=asst, build_context=_ctx_factory,
                              on_approve=sent.append)
    try:
        result = panel.ask("run SquareIceShelf on pace")
    finally:
        reg.invoke = orig

    if not result.plan_is_valid:
        import pytest
        pytest.skip("issm example x not resolvable here")

    # find the approve button + ack checkbox
    btns = []
    def walk(w):
        if isinstance(w, W.Button):
            btns.append(w)
        for c in getattr(w, "children", ()):
            walk(c)
    walk(panel.container)
    approve_btn = [b for b in btns if b.description == "Submit for approval"][0]

    assert approve_btn.disabled is True          # not acknowledged yet
    panel.approve()
    assert sent == []                            # refused without the tick

    # tick and approve
    for w in _iter(panel.container):
        if isinstance(w, W.Checkbox):
            w.value = True
    assert approve_btn.disabled is False
    panel.approve()
    assert sent and sent[0]["digest"] == result.proposed_plan["digest"]


def _iter(widget):
    yield widget
    for c in getattr(widget, "children", ()):
        yield from _iter(c)
