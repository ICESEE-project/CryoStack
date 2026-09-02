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
    assert "Validation" in _html(panel.container)
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


# ── mounts as a collapsed accordion ─────────────────────────────────
def test_accordion_is_collapsed_and_titled():
    acc = build_agent_accordion(
        assistant=RunAssistant(llm=ScriptedLLM([LLMResponse(text="hi")])),
        build_context=_ctx_factory)
    assert isinstance(acc, W.Accordion)
    assert acc.selected_index is None
    assert "Run Assistant" in acc.get_title(0)
    assert hasattr(acc, "_cryostack_agent_panel")
