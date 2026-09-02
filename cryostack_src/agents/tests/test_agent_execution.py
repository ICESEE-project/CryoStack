"""Dry-run execution coordinator (A6): walks every phase and stops at the
submit boundary; a live submit is refused without an approved, digest-matching
plan and without an EXECUTE context."""
from __future__ import annotations

from dataclasses import replace

import pytest

from cryostack_src.agents import Permission, Trace
from cryostack_src.agents.approval import ManagedPlan, PlanState, PlanStore
from cryostack_src.agents.context import ToolContext
from cryostack_src.agents.execution import (
    DryRunExecutionCoordinator,
    ExecutionPhase,
)
from cryostack_src.agents.planning import RunPlan, SlurmRequest
from cryostack_src.agents.policy import assert_tool_modules_are_clean
from cryostack_src.workspace import WorkspaceUser

_USER = WorkspaceUser(user_id="exec-u", source="cryostack-auth")


def _ctx(perm=Permission.PLAN):
    return ToolContext(user=_USER, application="icesheets", max_permission=perm,
                       trace=Trace(user_id=_USER.user_id))


def _plan(**over) -> RunPlan:
    base = dict(application="icesheets", model="issm", example="e",
                execution_mode="remote", compute_resource="pace", backend="spack",
                run_target="runme.m",
                slurm=SlurmRequest(job_name="ISSM", wall_time="01:00:00",
                                   account="test-alloc"))
    base.update(over)
    return RunPlan(**base)


def _approved_plan(store, **over) -> ManagedPlan:
    mp = store.create(owner=_USER, plan=_plan(**over))
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    mp.approve(_USER)
    return mp


# ── dry run ──────────────────────────────────────────────────────────
def test_dry_run_walks_every_phase_and_stops_at_submit():
    mp = _approved_plan(PlanStore())
    rep = DryRunExecutionCoordinator().execute(_ctx(), mp, dry_run=True)

    phases = [o.phase for o in rep.outcomes]
    for p in ExecutionPhase:
        assert p.value in phases
    submit = [o for o in rep.outcomes if o.phase == ExecutionPhase.SUBMIT.value][0]
    assert submit.status == "would-run"
    assert rep.submitted is False and rep.job_id is None
    assert rep.dry_run is True
    assert "sbatch" in rep.submission_command
    assert mp.state is PlanState.APPROVED          # coordinator did not advance it


def test_dry_run_cloud_plan_describes_batch_submit():
    mp = _approved_plan(PlanStore(), execution_mode="cloud", backend="container")
    rep = DryRunExecutionCoordinator().execute(_ctx(), mp, dry_run=True)
    assert "aws batch submit-job" in rep.submission_command
    assert not rep.submitted


def test_no_backend_means_live_execute_still_does_not_submit():
    mp = _approved_plan(PlanStore())
    # ask for a live run, EXECUTE context, but no backend is wired
    rep = DryRunExecutionCoordinator().execute(_ctx(Permission.EXECUTE), mp,
                                               dry_run=False)
    assert rep.submitted is False
    assert rep.dry_run is True                     # forced: backend is None
    assert mp.state is PlanState.APPROVED


# ── the guards ───────────────────────────────────────────────────────
def test_unapproved_plan_is_blocked_before_any_staging():
    store = PlanStore()
    mp = store.create(owner=_USER, plan=_plan())
    mp.mark_validated(mp.plan)                     # validated, NOT approved
    rep = DryRunExecutionCoordinator().execute(_ctx(), mp, dry_run=True)
    assert rep.blocked_reason == "approval"
    assert not rep.reached_submit_boundary
    assert {o.phase for o in rep.outcomes} == {
        ExecutionPhase.REVALIDATE.value, ExecutionPhase.CHECK_APPROVAL.value}


def test_mutation_after_approval_blocks_execution():
    mp = _approved_plan(PlanStore())
    # still a valid plan, but a different resource request => different digest
    mp.plan = replace(mp.plan, slurm=SlurmRequest(
        job_name="ISSM", nodes=2, tasks=2, tasks_per_node=1,
        wall_time="01:00:00", account="test-alloc"))
    rep = DryRunExecutionCoordinator().execute(_ctx(), mp, dry_run=True)
    assert rep.blocked_reason == "approval"
    assert not rep.reached_submit_boundary


def test_live_execute_needs_an_execute_context():
    class _Spy:
        called = False
        def submit(self, plan, *, ctx, approval=None):
            self.__class__.called = True
            return "job-1"

    mp = _approved_plan(PlanStore())
    coord = DryRunExecutionCoordinator(submit_backend=_Spy())
    rep = coord.execute(_ctx(Permission.PLAN), mp, dry_run=False)
    assert rep.blocked_reason == "permission"
    assert _Spy.called is False


def test_live_execute_with_backend_and_execute_context_submits_once():
    calls = []
    class _Backend:
        def submit(self, plan, *, ctx, approval=None):
            calls.append(plan.digest())
            return "job-42"

    mp = _approved_plan(PlanStore())
    coord = DryRunExecutionCoordinator(submit_backend=_Backend())
    rep = coord.execute(_ctx(Permission.EXECUTE), mp, dry_run=False)
    assert rep.submitted and rep.job_id == "job-42"
    assert calls == [mp.plan.digest()]
    assert mp.state is PlanState.EXECUTING


def test_execution_module_is_policy_clean():
    assert_tool_modules_are_clean()
