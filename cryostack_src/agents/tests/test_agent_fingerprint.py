"""Run-input fingerprint (PASS 4, task 5): what the human approved == what
runs, extended to the *content* of the example / run_target / datasets."""
from __future__ import annotations

from pathlib import Path

import pytest

from cryostack_src.agents.approval import ManagedPlan, PlanState
from cryostack_src.agents.fingerprint import RunInputFingerprint, fingerprint_inputs
from cryostack_src.agents.planning import RunPlan, SlurmRequest
from cryostack_src.workspace import WorkspaceUser

_USER = WorkspaceUser(user_id="fp-u", source="cryostack-auth")


@pytest.fixture
def example(tmp_path):
    d = tmp_path / "SquareIceShelf"
    d.mkdir()
    (d / "runme.m").write_text("solve(md);\n")
    (d / "helper.m").write_text("function y = helper(x)\n y = x;\n")
    (d / "outputs").mkdir()
    (d / "outputs" / "big.mat").write_bytes(b"\x00" * 4096)   # skipped dir
    return d


def _plan(**over) -> RunPlan:
    d = dict(application="icesheets", model="issm", example="SquareIceShelf",
             execution_mode="remote", compute_resource="pace", backend="spack",
             run_target="runme.m",
             slurm=SlurmRequest(job_name="ISSM", wall_time="01:00:00", account="a"))
    d.update(over)
    return RunPlan(**d)


# ── computation ──────────────────────────────────────────────────────
def test_fingerprint_is_deterministic(example):
    a = fingerprint_inputs(example, run_target="runme.m")
    b = fingerprint_inputs(example, run_target="runme.m")
    assert a.digest() == b.digest()
    assert a.run_target["name"] == "runme.m" and a.run_target["sha256"]


def test_outputs_dir_is_excluded(example):
    fp = fingerprint_inputs(example, run_target="runme.m")
    names = {row[0] for row in fp.tree}
    assert names == {"runme.m", "helper.m"}


def test_editing_the_run_target_changes_the_digest(example):
    before = fingerprint_inputs(example, run_target="runme.m").digest()
    (example / "runme.m").write_text("solve(md); % tweaked\n")
    after = fingerprint_inputs(example, run_target="runme.m").digest()
    assert before != after


def test_editing_a_sibling_source_file_changes_the_digest(example):
    before = fingerprint_inputs(example, run_target="runme.m").digest()
    (example / "helper.m").write_text("function y = helper(x)\n y = 2*x;\n")
    after = fingerprint_inputs(example, run_target="runme.m").digest()
    assert before != after


def test_drift_report_names_the_changed_file(example):
    approved = fingerprint_inputs(example, run_target="runme.m")
    (example / "helper.m").write_text("% changed\n")
    (example / "new.m").write_text("% added\n")
    current = fingerprint_inputs(example, run_target="runme.m")
    drift = current.drift_from(approved)
    assert any("helper.m" in d and "changed" in d for d in drift)
    assert any("new.m" in d and "added" in d for d in drift)


def test_dataset_metadata_is_fingerprinted(tmp_path, example):
    ds = tmp_path / "obs.nc"
    ds.write_bytes(b"netcdf-ish" * 10)
    a = fingerprint_inputs(example, run_target="runme.m", dataset_paths=[ds])
    ds.write_bytes(b"different data" * 10)
    b = fingerprint_inputs(example, run_target="runme.m", dataset_paths=[ds])
    assert a.digest() != b.digest()
    assert any("obs.nc" in d for d in b.drift_from(a))


def test_large_dataset_is_metadata_only(tmp_path, example, monkeypatch):
    from cryostack_src.agents import fingerprint as fpmod
    monkeypatch.setattr(fpmod, "_DATASET_HASH_CAP", 8)   # tiny cap
    ds = tmp_path / "huge.nc"
    ds.write_bytes(b"x" * 64)
    fp = fingerprint_inputs(example, run_target="runme.m", dataset_paths=[ds])
    assert fp.datasets[0][3] is None          # no sha256
    assert fp.datasets[0][1] == 64            # but size is recorded


def test_roundtrip(example):
    fp = fingerprint_inputs(example, run_target="runme.m")
    assert RunInputFingerprint.from_dict(fp.to_dict()).digest() == fp.digest()


# ── binding to an approval ──────────────────────────────────────────
def test_approval_can_carry_an_input_fingerprint(example):
    fp = fingerprint_inputs(example, run_target="runme.m")
    mp = ManagedPlan(plan_id="p", owner_user_id=_USER.user_id, plan=_plan())
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    appr = mp.approve(_USER, input_fingerprint=fp.digest())
    assert appr.input_fingerprint == fp.digest()
    assert appr.to_dict()["input_fingerprint"] == fp.digest()


def test_input_fingerprint_survives_persistence(tmp_path, example):
    from cryostack_src.agents import AgentStore
    store = AgentStore(user=_USER, workspace_root=tmp_path)
    fp = fingerprint_inputs(example, run_target="runme.m")
    mp = store.plans.create(_plan())
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    mp.approve(_USER, input_fingerprint=fp.digest())
    store.plans.save(mp)

    reloaded = store.plans.load(mp.plan_id)
    assert reloaded.state is PlanState.APPROVED
    assert reloaded.approval.input_fingerprint == fp.digest()
