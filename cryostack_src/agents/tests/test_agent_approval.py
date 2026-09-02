"""Human-approval boundary (A5): lifecycle transitions, and the core guarantee
that an approval for configuration A cannot be spent on configuration B."""
from __future__ import annotations

from dataclasses import replace

import pytest

from cryostack_src.agents.approval import (
    Approval,
    ApprovalError,
    ManagedPlan,
    PlanState,
    PlanStore,
    assert_approved_for_execution,
)
from cryostack_src.agents.planning import RunPlan, SlurmRequest
from cryostack_src.workspace import WorkspaceUser

_USER = WorkspaceUser(user_id="appr-u", source="cryostack-auth")
_OTHER = WorkspaceUser(user_id="somebody-else", source="cryostack-auth")


def _plan(**over) -> RunPlan:
    base = dict(application="icesheets", model="icepack", example="e",
                execution_mode="remote", compute_resource="pace", backend="spack",
                parameter_overrides={"ice_temperature": 260})
    base.update(over)
    return RunPlan(**base)


def _approved(store: PlanStore | None = None):
    store = store or PlanStore()
    mp = store.create(owner=_USER, plan=_plan())
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    mp.approve(_USER)
    return store, mp


# ── lifecycle ────────────────────────────────────────────────────────
def test_happy_path_reaches_completed():
    store, mp = _approved()
    assert mp.state is PlanState.APPROVED
    mp.mark_executing()
    assert mp.state is PlanState.EXECUTING
    mp.mark_completed("run-123")
    assert mp.state is PlanState.COMPLETED and mp.run_id == "run-123"


def test_cannot_approve_before_validation():
    mp = ManagedPlan(plan_id="p", owner_user_id=_USER.user_id, plan=_plan())
    with pytest.raises(ApprovalError):
        mp.submit_for_approval()
    with pytest.raises(ApprovalError):
        mp.approve(_USER)


def test_validation_errors_block_approval_request():
    bad = _plan(slurm=SlurmRequest(nodes=0))
    mp = ManagedPlan(plan_id="p", owner_user_id=_USER.user_id, plan=bad)
    mp.mark_validated(bad.with_findings(
        [__import__("cryostack_src.agents.planning", fromlist=["PlanFinding"])
         .PlanFinding("error", "slurm", "Nodes must be >= 1")]))
    assert mp.state is PlanState.DRAFT
    with pytest.raises(ApprovalError):
        mp.submit_for_approval()


def test_only_the_owner_can_approve():
    store = PlanStore()
    mp = store.create(owner=_USER, plan=_plan())
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    with pytest.raises(ApprovalError):
        mp.approve(_OTHER)


def test_store_is_scoped_by_owner():
    store = PlanStore()
    mp = store.create(owner=_USER, plan=_plan())
    with pytest.raises(KeyError):
        store.get(mp.plan_id, owner=_OTHER)
    assert store.get(mp.plan_id, owner=_USER) is mp


# ── the core guarantee ───────────────────────────────────────────────
def test_approve_A_then_mutate_then_execute_is_rejected():
    """Approval binds to a digest. Change a scientific parameter after
    approval and the executor must refuse — no side effects."""
    store, mp = _approved()
    approved_digest = mp.approval.plan_digest

    mp.revise(replace(mp.plan, parameter_overrides={"ice_temperature": 270}))

    assert mp.state is PlanState.DRAFT
    assert mp.approval is None
    assert mp.plan.digest() != approved_digest
    with pytest.raises(ApprovalError):
        assert_approved_for_execution(mp)
    with pytest.raises(ApprovalError):
        mp.mark_executing()
    assert mp.state is PlanState.DRAFT      # unchanged; nothing executed


def test_forged_approval_record_is_caught_by_digest_check():
    """Even if an approval object is fabricated for the wrong digest, the
    execution gate compares against the live plan digest."""
    mp = ManagedPlan(plan_id="p", owner_user_id=_USER.user_id, plan=_plan())
    mp.state = PlanState.APPROVED
    mp.approval = Approval(plan_digest="deadbeef" * 8,
                           approver_user_id=_USER.user_id,
                           approved_at="2026-01-01T00:00:00Z")
    with pytest.raises(ApprovalError):
        assert_approved_for_execution(mp)


def test_advisory_findings_do_not_invalidate_an_approval():
    from cryostack_src.agents.planning import PlanFinding
    store, mp = _approved()
    mp.revise(mp.plan.with_findings([PlanFinding("info", "plan", "fyi")]))
    # digest unchanged -> approval could remain, but revise() conservatively
    # resets from APPROVED. Re-approval is cheap and the digest still matches.
    assert mp.state is PlanState.DRAFT
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    mp.approve(_USER)
    assert_approved_for_execution(mp)      # no raise


def test_digest_matches_approval_flag_in_view():
    store, mp = _approved()
    assert mp.to_dict()["digest_matches_approval"] is True
    mp.plan = replace(mp.plan, parameter_overrides={"ice_temperature": 265})
    assert mp.to_dict()["digest_matches_approval"] is False


def test_failed_run_records_reason():
    store, mp = _approved()
    mp.mark_executing()
    mp.mark_failed("sbatch rejected: bad account")
    assert mp.state is PlanState.FAILED
    assert mp.failure_reason == "sbatch rejected: bad account"
