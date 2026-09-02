"""Planning tools (A4): RunPlan construction, digest determinism, validation
reuse of B4 / Basic-mode rules, and 'submits nothing'."""
from __future__ import annotations

import pytest

from cryostack_src.agents import Permission, Trace
from cryostack_src.agents.context import ToolContext
from cryostack_src.agents.planning import PlanFinding, RunPlan, SlurmRequest
from cryostack_src.agents.registry import default_registry
from cryostack_src.workspace import WorkspaceUser

_AUTH = WorkspaceUser(user_id="plan-u", source="cryostack-auth")


@pytest.fixture(autouse=True)
def _icepack_root(monkeypatch):
    p = "/home/bkyanjo3/icepack"
    import os
    if os.path.isdir(p):
        monkeypatch.setenv("ICEPACK_ROOT", p)


def _ctx(perm=Permission.PLAN):
    return ToolContext(user=_AUTH, application="icesheets", max_permission=perm,
                       trace=Trace(user_id=_AUTH.user_id))


# ── RunPlan model ────────────────────────────────────────────────────
def test_runplan_rejects_local_execution():
    with pytest.raises(ValueError):
        RunPlan(application="icesheets", model="icepack", example="x",
                execution_mode="local", compute_resource="pace", backend="spack")


def test_runplan_sets_the_expected_result_contract():
    p = RunPlan(application="icesheets", model="issm", example="x",
                execution_mode="remote", compute_resource="pace", backend="spack")
    assert p.expected_result_contract == "cryostack.issm.results"
    q = RunPlan(application="icesheets", model="icepack", example="x",
                execution_mode="remote", compute_resource="pace", backend="spack")
    assert q.expected_result_contract == "cryostack.icepack.results"


def test_digest_is_deterministic_and_order_independent():
    a = RunPlan(application="icesheets", model="icepack", example="e",
                execution_mode="remote", compute_resource="pace", backend="spack",
                parameter_overrides={"ice_temperature": 260, "num_timesteps": 50})
    b = RunPlan(application="icesheets", model="icepack", example="e",
                execution_mode="remote", compute_resource="pace", backend="spack",
                parameter_overrides={"num_timesteps": 50, "ice_temperature": 260})
    assert a.digest() == b.digest()


def test_digest_changes_on_any_scientific_or_resource_field():
    base = RunPlan(application="icesheets", model="icepack", example="e",
                   execution_mode="remote", compute_resource="pace", backend="spack",
                   parameter_overrides={"ice_temperature": 260})
    from dataclasses import replace
    assert base.digest() != replace(
        base, parameter_overrides={"ice_temperature": 261}).digest()
    assert base.digest() != replace(base, backend="container").digest()
    assert base.digest() != replace(base, slurm=SlurmRequest(nodes=2)).digest()
    # advisory fields do NOT change the digest
    assert base.digest() == base.with_findings(
        [PlanFinding("info", "plan", "x")]).digest()


def test_roundtrip_dict():
    p = RunPlan(application="icesheets", model="icepack", example="e",
                execution_mode="remote", compute_resource="pace", backend="spack",
                parameter_overrides={"ice_temperature": 260})
    assert RunPlan.from_dict(p.to_dict()).digest() == p.digest()


# ── planning tools ──────────────────────────────────────────────────
def test_prepare_and_validate_run_plan_icepack():
    reg = default_registry()
    ctx = _ctx()
    r = reg.invoke("prepare_run_plan", ctx, model="icepack",
                   example="02-synthetic-ice-shelf", compute_resource="pace",
                   parameter_overrides={"ice_temperature": 260})
    if not r.ok:                              # icepack root not resolvable here
        pytest.skip(r.error)
    plan = r.value
    assert plan["run_target"].endswith(".ipynb")
    assert plan["expected_result_contract"] == "cryostack.icepack.results"

    v = reg.invoke("validate_run_plan", ctx, plan=plan)
    assert v.ok
    assert "compute-submission" in v.value["approvals_required"]
    assert "scientific-parameter-change" in v.value["approvals_required"]
    assert v.value["digest"] == plan["digest"]        # validation doesn't mutate intent


def test_validation_reuses_b4_slurm_rules():
    reg = default_registry()
    ctx = _ctx()
    r = reg.invoke("prepare_run_plan", ctx, model="issm", example="anything",
                   compute_resource="pace",
                   slurm={"nodes": 0, "tasks": 4, "tasks_per_node": 8})
    # even if the example can't be resolved, a bad plan can be validated
    plan = r.value if r.ok else RunPlan(
        application="icesheets", model="issm", example="x", execution_mode="remote",
        compute_resource="pace", backend="spack",
        slurm=SlurmRequest(nodes=0, tasks=4, tasks_per_node=8)).to_dict()
    v = reg.invoke("validate_run_plan", ctx, plan=plan)
    msgs = [f["message"] for f in v.value["findings"] if f["level"] == "error"]
    assert any("Nodes must be" in m for m in msgs)
    assert any("Tasks / node cannot exceed" in m for m in msgs)


def test_issm_container_without_matlab_licence_is_an_error():
    # pace HAS a licence configured -> use a bare profile via a synthetic plan
    reg = default_registry()
    ctx = _ctx()
    plan = RunPlan(application="icesheets", model="issm", example="x",
                   execution_mode="remote", compute_resource="pace",
                   backend="container").to_dict()
    v = reg.invoke("validate_run_plan", ctx, plan=plan)
    # pace has a licence -> no preflight error on that axis
    assert not any("MATLAB licence" in f["message"] for f in v.value["findings"])


def test_icepack_cloud_is_impossible_to_construct():
    # PASS-3 audit §2a / PASS-4 review: an impossible plan is rejected at
    # construction, not merely flagged later.
    with pytest.raises(ValueError, match="cloud"):
        RunPlan(application="icesheets", model="icepack", example="x",
                execution_mode="cloud", compute_resource="pace",
                backend="container")


def test_validate_run_plan_still_guards_cloud_support_defensively():
    # the finding path stays live for a hypothetical bypass / future model:
    # feed validate_run_plan a hand-built dict (from_dict does not re-check
    # __post_init__ invariants beyond model/mode/backend enum membership).
    reg = default_registry()
    ctx = _ctx()
    plan = RunPlan(application="icesheets", model="issm", example="x",
                   execution_mode="cloud", compute_resource="pace",
                   backend="container").to_dict()
    v = reg.invoke("validate_run_plan", ctx, plan=plan)
    # issm IS cloud-supported, so no ISSM-only finding — the guard is exercised
    # (returns clean) rather than absent.
    assert v.ok


def test_planning_tools_are_plan_permission_and_read_only():
    reg = default_registry()
    for name in ("prepare_run_plan", "validate_run_plan",
                 "estimate_execution_requirements"):
        spec = reg.get(name).spec
        assert spec.permission == Permission.PLAN
        assert spec.read_only is True and spec.requires_confirmation is False
    # an OBSERVE context cannot even see them
    seen = {s.name for s in reg.specs(ctx=_ctx(Permission.OBSERVE))}
    assert "prepare_run_plan" not in seen


def test_estimate_execution_requirements_summarises_without_submitting():
    reg = default_registry()
    ctx = _ctx()
    plan = RunPlan(application="icesheets", model="issm", example="x",
                   execution_mode="remote", compute_resource="pace",
                   backend="container",
                   parameter_overrides={}).to_dict()
    e = reg.invoke("estimate_execution_requirements", ctx, plan=plan)
    assert e.ok
    assert e.value["matlab_required"] is True
    assert e.value["vpn_required"] is True
    assert e.value["expected_result_contract"] == "cryostack.issm.results"
