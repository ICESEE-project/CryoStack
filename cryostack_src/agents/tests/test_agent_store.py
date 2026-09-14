"""User-scoped persistence for agent plans and traces (PASS 4, task 2):
round-trip, atomicity, digest survival, approval-survives-reload,
edit-invalidates-approval, append-only traces, secret rejection, and A/B
isolation.
"""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from cryostack_src.agents import (
    AgentStore,
    ManagedPlan,
    PlanRepository,
    PlanState,
    RunPlan,
    SecretInPayloadError,
    SlurmRequest,
    Trace,
)
from cryostack_src.agents.approval import restore_managed_plan
from cryostack_src.workspace import WorkspaceUser
from cryostack_src.workspace.identity import WorkspaceIdentityError

_A = WorkspaceUser(user_id="store-a", source="cryostack-auth")
_B = WorkspaceUser(user_id="store-b", source="cryostack-auth")


def _plan(**over) -> RunPlan:
    d = dict(application="icesheets", model="icepack", example="e",
             execution_mode="remote", compute_resource="pace", backend="spack",
             run_target="e.ipynb",
             slurm=SlurmRequest(job_name="ICEPACK", wall_time="01:00:00",
                                account="alloc"))
    d.update(over)
    return RunPlan(**d)


@pytest.fixture
def store_a(tmp_path):
    return AgentStore(user=_A, workspace_root=tmp_path)


@pytest.fixture
def store_b(tmp_path):
    return AgentStore(user=_B, workspace_root=tmp_path)


# ── layout ───────────────────────────────────────────────────────────
def test_layout_is_under_the_users_workspace(store_a):
    assert str(store_a.root).endswith("/.cryostack/agents")
    assert store_a.plans._dir.name == "plans"
    assert store_a.traces._dir.name == "traces"
    assert "store-a" in str(store_a.root)


def test_needs_an_authenticated_user(tmp_path):
    with pytest.raises(WorkspaceIdentityError):
        AgentStore(user=WorkspaceUser(user_id="anonymous",
                                      source="unauthenticated"),
                   workspace_root=tmp_path)


# ── round trip ───────────────────────────────────────────────────────
def test_plan_digest_survives_serialization(store_a):
    mp = store_a.plans.create(_plan(parameter_overrides={"ice_temperature": 255}))
    before = mp.plan.digest()
    reloaded = store_a.plans.load(mp.plan_id)
    assert reloaded.plan.digest() == before
    assert reloaded.plan.parameter_overrides == {"ice_temperature": 255}


def test_write_is_atomic_no_partial_file(store_a, monkeypatch):
    mp = store_a.plans.create(_plan())
    path = store_a.plans._path(mp.plan_id)
    # a real file is present and parses; no leftover .tmp
    json.loads(path.read_text())
    assert not list(path.parent.glob("*.tmp"))


def test_approval_survives_reload(store_a):
    repo = store_a.plans
    mp = repo.create(_plan())
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    mp.approve(_A)
    repo.save(mp)

    reloaded = repo.load(mp.plan_id)
    assert reloaded.state is PlanState.APPROVED
    assert reloaded.approval is not None
    assert reloaded.approval.plan_digest == reloaded.plan.digest()


def test_editing_an_approved_plan_on_disk_invalidates_approval(store_a):
    repo = store_a.plans
    mp = repo.create(_plan(parameter_overrides={"ice_temperature": 255}))
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    mp.approve(_A)
    repo.save(mp)

    # tamper with the persisted file: change a scientific parameter, keep the
    # old approval block
    path = repo._path(mp.plan_id)
    d = json.loads(path.read_text())
    d["plan"]["parameter_overrides"]["ice_temperature"] = 270
    path.write_text(json.dumps(d))

    reloaded = repo.load(mp.plan_id)
    assert reloaded.state is PlanState.DRAFT
    assert reloaded.approval is None
    assert any(h["event"] == "reload_digest_mismatch" for h in reloaded.history)


def test_reload_ignores_a_forged_owner_in_the_blob(store_a):
    repo = store_a.plans
    mp = repo.create(_plan())
    path = repo._path(mp.plan_id)
    d = json.loads(path.read_text())
    d["owner_user_id"] = "store-b"          # forge
    path.write_text(json.dumps(d))

    reloaded = repo.load(mp.plan_id)
    assert reloaded.owner_user_id == "store-a"   # bound to the storage path


def test_approval_by_a_different_user_in_the_blob_is_dropped(store_a):
    repo = store_a.plans
    mp = repo.create(_plan())
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    mp.approve(_A)
    repo.save(mp)
    path = repo._path(mp.plan_id)
    d = json.loads(path.read_text())
    d["approval"]["approver_user_id"] = "store-b"
    path.write_text(json.dumps(d))

    reloaded = repo.load(mp.plan_id)
    assert reloaded.approval is None
    assert reloaded.state is PlanState.DRAFT


# ── traces stay append-only ──────────────────────────────────────────
def test_trace_store_is_append_only(store_a):
    tr = Trace(user_id=_A.user_id)
    store_a.traces.attach(tr)
    tr.request("do a thing")
    tr.append("tool_call", {"tool": "list_models"})
    tr.append("note", {"text": "done"})
    store_a.traces.verify_append_only(tr.trace_id)
    assert [e["seq"] for e in store_a.traces.load(tr.trace_id)] == [0, 1, 2]


def test_trace_secret_scrub_catches_what_redact_misses(store_a):
    # a GitHub token under an innocuous key: redact() (deny-by-known-key +
    # marker) does not catch it; the structural scan does.
    token = "ghp_" + "A" * 36
    tr = Trace(user_id=_A.user_id)
    store_a.traces.attach(tr)
    tr.append("tool_call", {"detail": f"the value is {token}"})
    raw = store_a.traces.path_for(tr.trace_id).read_text()
    assert token not in raw
    assert "scrubbed" in raw
    assert "github-token" in raw


# ── secret rejection for plans ───────────────────────────────────────
def test_a_plan_carrying_a_secret_is_refused(store_a):
    bad = _plan(parameter_overrides={"note": "-----BEGIN OPENSSH PRIVATE KEY-----"})
    with pytest.raises(SecretInPayloadError):
        store_a.plans.create(bad)


def test_a_plan_with_an_aws_key_in_job_name_is_refused(store_a):
    bad = _plan(slurm=SlurmRequest(job_name="AKIA" + "B" * 16,
                                   wall_time="01:00:00", account="a"))
    with pytest.raises(SecretInPayloadError):
        store_a.plans.create(bad)


# ── A / B isolation ─────────────────────────────────────────────────
def test_user_b_cannot_load_or_enumerate_user_a_plans(store_a, store_b):
    mp = store_a.plans.create(_plan())
    assert store_a.plans.list_ids() == [mp.plan_id]
    assert store_b.plans.list_ids() == []
    with pytest.raises(KeyError):
        store_b.plans.load(mp.plan_id)


def test_repository_refuses_to_save_another_owners_plan(store_a):
    foreign = ManagedPlan(plan_id="x", owner_user_id="store-b", plan=_plan())
    with pytest.raises(WorkspaceIdentityError):
        store_a.plans.save(foreign)


def test_a_and_b_traces_are_in_separate_directories(store_a, store_b):
    assert store_a.traces._dir != store_b.traces._dir
    ta = Trace(user_id=_A.user_id)
    store_a.traces.attach(ta)
    ta.request("a")
    assert store_b.traces.list_ids() == []


# ── malicious ids ───────────────────────────────────────────────────
@pytest.mark.parametrize("bad_id", ["../escape", "/etc/passwd", "..", "",
                                    "a/b", "a\x00b"])
def test_path_traversal_ids_are_rejected(store_a, bad_id):
    with pytest.raises((ValueError, KeyError)):
        store_a.plans.load(bad_id)


def test_url_and_basic_auth_credentials_are_scrubbed_from_traces(store_a):
    tr = Trace(user_id=_A.user_id)
    store_a.traces.attach(tr)
    tr.append("note", {"url": "https://alice:s3cr3tPass@repo.example/x.git",
                       "hdr": "Authorization: Basic YWxpY2U6c2VjcmV0eHh4eHh4"})
    raw = store_a.traces.path_for(tr.trace_id).read_text()
    assert "s3cr3tPass" not in raw
    assert "YWxpY2U6c2VjcmV0" not in raw
    assert "scrubbed" in raw


# ── PASS 4 review (ARCH P1): concurrent writers ─────────────────────
def test_concurrent_modification_is_detected(tmp_path):
    from cryostack_src.agents import ConcurrentModificationError
    # two Voila kernels for the same user == two store instances, same dir
    kernel_a = AgentStore(user=_A, workspace_root=tmp_path).plans
    kernel_b = AgentStore(user=_A, workspace_root=tmp_path).plans

    mp = kernel_a.create(_plan())
    a = kernel_a.load(mp.plan_id)
    b = kernel_b.load(mp.plan_id)

    b.mark_validated(b.plan)
    b.submit_for_approval()
    b.approve(_A)
    kernel_b.save(b)                     # B saves first — fine

    a._log("stale edit")
    with pytest.raises(ConcurrentModificationError):
        kernel_a.save(a)                 # A's save would clobber B's approval

    kernel_a.save(a, force=True)         # explicit override still possible
