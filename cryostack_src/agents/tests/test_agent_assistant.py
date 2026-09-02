"""The Run Assistant (A8): deterministic loop over the mock LLM, hard PLAN
ceiling, and the guarantee that it never approves or submits."""
from __future__ import annotations

import os

import pytest

from cryostack_src.agents import (
    LLMResponse,
    LLMToolCall,
    Permission,
    RunAssistant,
    ScriptedLLM,
    Trace,
    default_registry,
)
from cryostack_src.agents.context import ToolContext
from cryostack_src.agents.permissions import Permission as P
from cryostack_src.agents.registry import ToolRegistry
from cryostack_src.agents.tools import drain_pending, tool
from cryostack_src.workspace import WorkspaceUser

_USER = WorkspaceUser(user_id="asst-u", source="cryostack-auth")


def _ctx(perm=Permission.PLAN):
    return ToolContext(user=_USER, application="icesheets", max_permission=perm,
                       trace=Trace(user_id=_USER.user_id))


@pytest.fixture(autouse=True)
def _icepack_root(monkeypatch):
    p = "/home/bkyanjo3/icepack"
    if os.path.isdir(p):
        monkeypatch.setenv("ICEPACK_ROOT", p)


# ── loop ─────────────────────────────────────────────────────────────
def test_assistant_runs_read_and_plan_tools_then_stops():
    llm = ScriptedLLM([
        LLMResponse(text="Let me look at the examples.",
                    tool_calls=(LLMToolCall("list_examples", {"model": "icepack"}),)),
        LLMResponse(tool_calls=(
            LLMToolCall("prepare_run_plan", {
                "model": "icepack", "example": "02-synthetic-ice-shelf",
                "compute_resource": "pace",
                "slurm": {"account": "test-alloc", "wall_time": "01:00:00"},
                "parameter_overrides": {"ice_temperature": 260}}),)),
        LLMResponse(tool_calls=(LLMToolCall("validate_run_plan", {"plan": "<from-previous>"}),)),
        LLMResponse(text="Plan ready. You must approve it before it runs."),
    ])

    # the scripted model can't actually thread the plan dict through; drive
    # validate_run_plan off the prepared plan by hand via a small wrapper LLM.
    class _Threaded(ScriptedLLM):
        last_plan = None
        def complete(self, **kw):
            r = super().complete(**kw)
            calls = []
            for c in r.tool_calls:
                if c.name == "validate_run_plan" and self.last_plan is not None:
                    calls.append(LLMToolCall("validate_run_plan", {"plan": self.last_plan}))
                else:
                    calls.append(c)
            return LLMResponse(text=r.text, tool_calls=tuple(calls))

    threaded = _Threaded(llm._script)
    asst = RunAssistant(llm=threaded)
    ctx = _ctx()

    # patch: capture prepared plan into the threaded llm
    reg = default_registry()
    orig = reg.invoke
    def _spy(name, c, **kw):
        res = orig(name, c, **kw)
        if name == "prepare_run_plan" and res.ok:
            threaded.last_plan = res.value
        return res
    reg.invoke = _spy
    try:
        result = asst.handle(ctx, "run the synthetic ice shelf at 260 K")
    finally:
        reg.invoke = orig

    if result.proposed_plan is None:
        pytest.skip("icepack example not resolvable in this environment")
    assert result.submitted is False
    assert result.plan_is_valid is True
    assert "compute-submission" in result.approvals_required
    assert "scientific-parameter-change" in result.approvals_required
    # the trace recorded the request + the tool calls
    kinds = [e.kind for e in ctx.trace.events]
    assert kinds[0] == "request"
    assert "tool_call" in kinds


def test_assistant_hard_caps_the_context_at_plan():
    reg = ToolRegistry()
    drain_pending()

    @tool(name="_asst_execute_probe", description="pretend to submit",
          permission=P.EXECUTE, read_only=False, requires_confirmation=True,
          scientific_effect="submits a job")
    def _probe(ctx):
        return "SUBMITTED"

    reg.register_module_tools()

    llm = ScriptedLLM([
        LLMResponse(tool_calls=(LLMToolCall("_asst_execute_probe", {}),)),
        LLMResponse(text="done"),
    ])
    asst = RunAssistant(llm=llm, registry=reg)
    # even with an EXECUTE context, the assistant caps itself at PLAN
    result = asst.handle(_ctx(Permission.EXECUTE), "submit it now")

    assert result.submitted is False
    probe_results = [r for s in result.steps for r in s.tool_results
                     if r["name"] == "_asst_execute_probe"]
    assert probe_results and probe_results[0]["ok"] is False
    assert "permission denied" in probe_results[0]["error"]


def test_assistant_never_sees_execute_tools_in_its_toolset():
    reg = ToolRegistry()
    drain_pending()

    @tool(name="_asst_hidden_execute", description="x", permission=P.EXECUTE,
          read_only=False, scientific_effect="runs")
    def _h(ctx):
        return "x"

    reg.register_module_tools()

    seen = {}
    class _Recorder(ScriptedLLM):
        def complete(self, *, system, messages, tools):
            seen["names"] = [t["name"] for t in tools]
            return super().complete(system=system, messages=messages, tools=tools)

    asst = RunAssistant(llm=_Recorder([LLMResponse(text="ok")]), registry=reg)
    asst.handle(_ctx(Permission.EXECUTE), "hi")
    assert "_asst_hidden_execute" not in seen["names"]


def test_assistant_result_is_serialisable():
    asst = RunAssistant(llm=ScriptedLLM([LLMResponse(text="hello")]))
    r = asst.handle(_ctx(), "hi")
    d = r.to_dict()
    assert d["submitted"] is False and d["text"] == "hello"


def test_plan_is_captured_by_result_kind_not_by_tool_name():
    """A renamed planning tool must not break plan capture — the assistant
    matches ToolSpec.result_kind (PASS 4 review, ARCH P1)."""
    reg = ToolRegistry()
    drain_pending()

    @tool(name="_totally_renamed_planner", description="build a plan",
          permission=P.PLAN, read_only=True, result_kind="run_plan")
    def _planner(ctx, *, x: int = 1):
        return {"model": "issm", "digest": "abc", "findings": [],
                "validated": False, "approvals_required": ["compute-submission"]}

    reg.register_module_tools()
    llm = ScriptedLLM([
        LLMResponse(tool_calls=(LLMToolCall("_totally_renamed_planner", {}),)),
        LLMResponse(text="done"),
    ])
    res = RunAssistant(llm=llm, registry=reg).handle(_ctx(), "make a plan")
    assert res.proposed_plan is not None
    assert res.proposed_plan["digest"] == "abc"
