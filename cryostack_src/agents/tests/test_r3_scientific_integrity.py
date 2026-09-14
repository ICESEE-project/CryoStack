"""R3 — an agent must not silently change scientific intent.

Every scientific change must be visible (in the digest, in scientific_changes,
in approvals_required) and must require a fresh human approval.
"""
from __future__ import annotations

import os
from dataclasses import replace

import pytest

from cryostack_src.agents import Permission, Trace, default_registry
from cryostack_src.agents.approval import PlanState, PlanStore
from cryostack_src.agents.context import ToolContext
from cryostack_src.agents.planning import RunPlan, SlurmRequest
from cryostack_src.agents.trace_store import assert_no_agent_chatter, run_manifest_stamp
from cryostack_src.workspace import WorkspaceUser

_USER = WorkspaceUser(user_id="r3-u", source="cryostack-auth")


def _ctx(perm=Permission.PLAN):
    return ToolContext(user=_USER, application="icesheets", max_permission=perm,
                       trace=Trace(user_id=_USER.user_id))


def _plan(**over) -> RunPlan:
    d = dict(application="icesheets", model="icepack", example="e",
             execution_mode="remote", compute_resource="pace", backend="spack",
             run_target="e.ipynb",
             slurm=SlurmRequest(job_name="ICEPACK", wall_time="01:00:00", account="a"))
    d.update(over)
    return RunPlan(**d)


# 1. scientific changes are visible -------------------------------
def test_a_parameter_override_shows_in_every_surface():
    p = _plan(parameter_overrides={"ice_temperature": 255})
    assert p.scientific_changes() == {"ice_temperature": 255}
    assert p.digest() != _plan().digest()

    reg = default_registry()
    v = reg.invoke("validate_run_plan", _ctx(), plan=p.to_dict())
    assert "scientific-parameter-change" in v.value["approvals_required"]


def test_changing_a_parameter_after_approval_forces_re_approval():
    store = PlanStore()
    mp = store.create(owner=_USER, plan=_plan(parameter_overrides={"ice_temperature": 255}))
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    mp.approve(_USER)
    assert mp.state is PlanState.APPROVED

    mp.revise(replace(mp.plan, parameter_overrides={"ice_temperature": 260}))
    assert mp.state is PlanState.DRAFT
    assert mp.approval is None


# 2. invalid science is blocked ----------------------------------
def test_out_of_range_basic_mode_value_is_a_validation_error():
    reg = default_registry()
    # ice_temperature domain is 200..273.15 K
    p = _plan(parameter_overrides={"ice_temperature": 5000}).to_dict()
    v = reg.invoke("validate_run_plan", _ctx(), plan=p)
    errs = [f for f in v.value["findings"] if f["level"] == "error"]
    assert errs
    assert "resolve-validation-errors-first" in v.value["approvals_required"]


def test_the_assistant_never_invents_a_parameter_not_in_the_users_request():
    # the assistant only passes through overrides the model gave it; there is no
    # tool that generates scientific values. Assert no tool has a mutating,
    # value-producing scientific effect at PLAN or below.
    reg = default_registry()
    for name in reg.names():
        spec = reg.get(name).spec
        if spec.permission <= Permission.PLAN:
            assert spec.read_only is True
            assert spec.scientific_effect == "none"


# 3. canonical examples stay read-only --------------------------
def test_no_agent_tool_can_write_to_a_canonical_example():
    reg = default_registry()
    for name in reg.names():
        spec = reg.get(name).spec
        # everything shipped is OBSERVE/PLAN and read-only
        assert spec.read_only is True
        assert spec.permission <= Permission.PLAN


@pytest.mark.skipif(not os.path.isdir("/home/bkyanjo3/icepack"),
                    reason="icepack root not resolvable")
def test_inspect_example_reports_canonical_examples_as_read_only(monkeypatch):
    monkeypatch.setenv("ICEPACK_ROOT", "/home/bkyanjo3/icepack")
    reg = default_registry()
    exs = reg.invoke("list_examples", _ctx(Permission.OBSERVE), model="icepack").value
    canonical = [e for e in exs if not e["owned"]]
    assert canonical and all(e["read_only"] for e in canonical)


# 4. result contract is preserved ------------------------------
def test_plan_carries_the_models_result_contract_unchanged():
    for model, contract in (("issm", "cryostack.issm.results"),
                            ("icepack", "cryostack.icepack.results")):
        p = RunPlan(application="icesheets", model=model, example="x",
                    execution_mode="remote", compute_resource="pace",
                    backend="spack")
        assert p.expected_result_contract == contract


# 5. provenance stays clean -----------------------------------
def test_agent_assisted_run_manifest_carries_only_a_pointer():
    stamp = run_manifest_stamp(trace_id="t", plan_digest="d",
                               approver_user_id=_USER.user_id,
                               approved_at="2026-09-01T00:00:00Z")
    manifest = {"model": "icepack", "run_target": "e.ipynb", **stamp}
    assert_no_agent_chatter(manifest)          # no raise
    # smuggling the transcript in is rejected
    with pytest.raises(AssertionError):
        assert_no_agent_chatter({**manifest, "messages": ["hi"]})
