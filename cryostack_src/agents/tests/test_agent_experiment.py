"""Experiment abstraction (P3): a sweep expands to ordinary RunPlans, each with
its own digest; one approval binds the experiment digest AND every child
digest; a child cannot be swapped after approval."""
from __future__ import annotations

from dataclasses import replace

import pytest

from cryostack_src.agents.approval import ApprovalError, PlanState
from cryostack_src.agents.experiment import (
    ExperimentPlan,
    ManagedExperiment,
    SweepAxis,
)
from cryostack_src.agents.planning import PlanFinding, RunPlan, SlurmRequest
from cryostack_src.workspace import WorkspaceUser

_USER = WorkspaceUser(user_id="exp-u", source="cryostack-auth")
_OTHER = WorkspaceUser(user_id="not-exp-u", source="cryostack-auth")


def _base(**over) -> RunPlan:
    d = dict(application="icesheets", model="icepack", example="e",
             execution_mode="remote", compute_resource="pace", backend="spack",
             run_target="e.ipynb",
             slurm=SlurmRequest(job_name="ICEPACK", wall_time="01:00:00",
                                account="alloc"))
    d.update(over)
    return RunPlan(**d)


def _exp(values=(250, 260, 270)) -> ExperimentPlan:
    return ExperimentPlan(name="temperature sweep", base=_base(),
                          axis=SweepAxis("ice_temperature", values))


# ── expansion ────────────────────────────────────────────────────────
def test_expansion_yields_one_runplan_per_value_with_distinct_digests():
    exp = _exp()
    runs = exp.expand()
    assert [r.parameter_overrides["ice_temperature"] for r in runs] == [250, 260, 270]
    assert len({r.digest() for r in runs}) == 3
    assert exp.child_digests() == [r.digest() for r in runs]


def test_sweep_requires_distinct_values_and_a_free_parameter():
    with pytest.raises(ValueError):
        SweepAxis("x", (1, 1))
    with pytest.raises(ValueError):
        SweepAxis("x", (1,))
    with pytest.raises(ValueError):
        ExperimentPlan(name="n", base=_base(parameter_overrides={"ice_temperature": 260}),
                       axis=SweepAxis("ice_temperature", (250, 260)))


def test_experiment_digest_changes_with_the_sweep_but_not_with_advisory_findings():
    a = _exp((250, 260))
    b = _exp((250, 261))
    assert a.digest() != b.digest()
    withf = replace(a, base=a.base.with_findings([PlanFinding("info", "x", "y")]))
    assert withf.digest() == a.digest()


def test_roundtrip():
    exp = _exp()
    assert ExperimentPlan.from_dict(exp.to_dict()).digest() == exp.digest()


# ── managed lifecycle ────────────────────────────────────────────────
def _validate_ok(p: RunPlan) -> RunPlan:
    return p.with_findings([], approvals_required=("compute-submission",))


def _validate_bad(p: RunPlan) -> RunPlan:
    return p.with_findings([PlanFinding("error", "slurm", "nope")])


def test_one_approval_approves_every_child_and_binds_all_digests():
    me = ManagedExperiment.create(owner=_USER, plan=_exp())
    me.validate(_validate_ok)
    assert me.state is PlanState.VALIDATED
    me.submit_for_approval()
    appr = me.approve(_USER)

    assert me.state is PlanState.APPROVED
    assert appr.experiment_digest == me.plan.digest()
    assert set(appr.child_digests) == {mp.plan.digest() for mp in me.children}
    for mp in me.children:
        assert mp.state is PlanState.APPROVED
        assert mp.approval.plan_digest == mp.plan.digest()


def test_a_failing_child_blocks_the_whole_experiment():
    me = ManagedExperiment.create(owner=_USER, plan=_exp())

    def _mixed(p: RunPlan) -> RunPlan:
        if p.parameter_overrides["ice_temperature"] == 260:
            return _validate_bad(p)
        return _validate_ok(p)

    me.validate(_mixed)
    assert me.state is PlanState.DRAFT
    with pytest.raises(ApprovalError):
        me.submit_for_approval()


def test_only_the_owner_approves():
    me = ManagedExperiment.create(owner=_USER, plan=_exp())
    me.validate(_validate_ok)
    me.submit_for_approval()
    with pytest.raises(ApprovalError):
        me.approve(_OTHER)


def test_mutating_a_child_after_approval_breaks_its_digest_binding():
    from cryostack_src.agents.approval import assert_approved_for_execution
    me = ManagedExperiment.create(owner=_USER, plan=_exp())
    me.validate(_validate_ok)
    me.submit_for_approval()
    me.approve(_USER)

    victim = me.children[1]
    victim.plan = replace(victim.plan,
                          parameter_overrides={"ice_temperature": 999})
    with pytest.raises(ApprovalError):
        assert_approved_for_execution(victim)
    # siblings are untouched
    assert_approved_for_execution(me.children[0])
