"""R2 — an agent (or a compromised LLM) actively trying to misbehave.

Each test is an attack. All of them must fail closed.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from cryostack_src.agents import (
    Permission,
    ScriptedLLM,
    LLMResponse,
    LLMToolCall,
    RunAssistant,
    Trace,
    default_registry,
)
from cryostack_src.agents.approval import (
    ApprovalError,
    PlanState,
    PlanStore,
    assert_approved_for_execution,
)
from cryostack_src.agents.context import ToolContext, build_tool_context
from cryostack_src.agents.execution import DryRunExecutionCoordinator
from cryostack_src.agents.planning import RunPlan, SlurmRequest
from cryostack_src.agents.policy import assert_tool_modules_are_clean
from cryostack_src.workspace import WorkspaceUser
from cryostack_src.workspace.identity import WorkspaceIdentityError

_USER = WorkspaceUser(user_id="r2-u", source="cryostack-auth")
_VICTIM = WorkspaceUser(user_id="r2-victim", source="cryostack-auth")


def _ctx(perm=Permission.PLAN, user=_USER):
    return ToolContext(user=user, application="icesheets", max_permission=perm,
                       trace=Trace(user_id=user.user_id))


def _plan(**over) -> RunPlan:
    d = dict(application="icesheets", model="issm", example="e",
             execution_mode="remote", compute_resource="pace", backend="spack",
             run_target="runme.m",
             slurm=SlurmRequest(job_name="ISSM", wall_time="01:00:00", account="a"))
    d.update(over)
    return RunPlan(**d)


# 1. identity ---------------------------------------------------------
def test_context_cannot_be_built_without_an_authenticated_identity(monkeypatch):
    monkeypatch.delenv("CRYOSTACK_WORKSPACE_USER", raising=False)
    monkeypatch.delenv("HTTP_X_CRYOSTACK_USER_ID", raising=False)
    with pytest.raises(WorkspaceIdentityError):
        build_tool_context(application="icesheets", env={})


def test_context_rejects_a_forged_identity_source():
    forged = WorkspaceUser(user_id="root", source="totally-legit")
    with pytest.raises(WorkspaceIdentityError):
        ToolContext(user=forged, application="icesheets",
                    max_permission=Permission.PLAN)


def test_no_tool_accepts_a_user_id_argument():
    reg = default_registry()
    for name in reg.names():
        params = reg.get(name).spec.parameters or {}
        assert "user_id" not in params and "owner" not in params, name


def test_agent_cannot_read_another_users_run():
    reg = default_registry()
    r = reg.invoke("inspect_run", _ctx(Permission.OBSERVE), run_id="anything")
    assert not r.ok                       # no workspace manager / not owned


# 2. permission escalation ------------------------------------------
def test_context_ceiling_cannot_be_raised():
    ctx = _ctx(Permission.OBSERVE)
    raised = ctx.with_ceiling(Permission.DESTRUCTIVE)
    assert raised.max_permission == Permission.OBSERVE      # min(), only goes down


def test_registry_refuses_a_tool_above_the_ceiling():
    reg = default_registry()
    r = reg.invoke("prepare_run_plan", _ctx(Permission.OBSERVE),
                   model="issm", example="e", compute_resource="pace")
    assert not r.ok and "permission denied" in r.error


def test_assistant_stays_at_plan_even_with_an_execute_context():
    reg = default_registry()
    seen = {}
    class _Rec(ScriptedLLM):
        def complete(self, *, system, messages, tools):
            seen["tools"] = [t["name"] for t in tools]
            return super().complete(system=system, messages=messages, tools=tools)
    asst = RunAssistant(llm=_Rec([LLMResponse(text="hi")]), registry=reg)
    res = asst.handle(_ctx(Permission.DESTRUCTIVE), "delete everything")
    assert res.submitted is False
    # no EXECUTE/DESTRUCTIVE tool is even shown
    for name in seen["tools"]:
        assert reg.get(name).spec.permission <= Permission.PLAN


# 3. approval bypass ------------------------------------------------
def test_approve_A_execute_B_is_rejected_with_no_side_effects():
    store = PlanStore()
    mp = store.create(owner=_USER, plan=_plan())
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    mp.approve(_USER)

    # a still-valid mutation: the digest changes, so the approval no longer binds
    mp.plan = replace(mp.plan, run_target="a_different_driver.m")
    rep = DryRunExecutionCoordinator().execute(_ctx(), mp, dry_run=True)
    assert rep.blocked_reason == "approval"
    assert not rep.reached_submit_boundary
    assert rep.submitted is False


def test_fabricated_approval_object_is_caught():
    from cryostack_src.agents.approval import Approval, ManagedPlan
    mp = ManagedPlan(plan_id="x", owner_user_id=_USER.user_id, plan=_plan())
    mp.state = PlanState.APPROVED
    mp.approval = Approval(plan_digest="0" * 64, approver_user_id=_USER.user_id,
                           approved_at="2026-01-01T00:00:00Z")
    with pytest.raises(ApprovalError):
        assert_approved_for_execution(mp)


def test_a_user_cannot_approve_another_users_plan():
    store = PlanStore()
    mp = store.create(owner=_VICTIM, plan=_plan())
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    with pytest.raises(ApprovalError):
        mp.approve(_USER)


# 4. execution bypass ---------------------------------------------
def test_live_execute_without_execute_ceiling_never_calls_the_backend():
    store = PlanStore()
    mp = store.create(owner=_USER, plan=_plan())
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    mp.approve(_USER)

    class _Backend:
        called = False
        def submit(self, plan, *, ctx, approval=None):
            _Backend.called = True
            return "job"
    rep = DryRunExecutionCoordinator(submit_backend=_Backend()).execute(
        _ctx(Permission.PLAN), mp, dry_run=False)
    assert rep.blocked_reason == "permission"
    assert _Backend.called is False


# 5. secret exfiltration ----------------------------------------
def test_secrets_passed_to_a_tool_are_redacted_in_the_trace():
    ctx = _ctx()
    ctx.trace.append("tool_call", {
        "args": {"password": "p@ss", "aws_secret_access_key": "AKIAABC",
                 "note": "-----BEGIN OPENSSH PRIVATE KEY-----"}})
    blob = ctx.trace.to_json()
    for leak in ("p@ss", "AKIAABC", "BEGIN OPENSSH PRIVATE KEY"):
        assert leak not in blob


# 6. code-level policy -----------------------------------------
def test_tool_modules_reference_no_prohibited_symbol():
    assert_tool_modules_are_clean()
