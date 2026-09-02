"""RemoteSubmitBackend (PASS 4, task 4): the composition preserves B3/B4/
preflight and never lets an LLM value reach SSH. Exercised with injected seams
— no HPC, no ssh."""
from __future__ import annotations

from pathlib import Path

import pytest

from cryostack_src.agent_execution import (
    ConnectionContext,
    RemoteSubmitBackend,
    SubmitBlocked,
)
from cryostack_src.agents import Permission, Trace
from cryostack_src.agents.context import ToolContext
from cryostack_src.agents.planning import RunPlan, SlurmRequest
from cryostack_src.workspace import WorkspaceUser

_USER = WorkspaceUser(user_id="rsb-u", source="cryostack-auth")


# ── fakes ────────────────────────────────────────────────────────────
class _Bridge:
    def __init__(self, whoami="rsb-u", ok=True):
        self.whoami, self.ok = whoami, ok
        self.calls = []

    def check_backend(self, *, command, timeout=30):
        self.calls.append(command)
        return {"ok": self.ok, "stdout": f"{self.whoami}\n", "stderr": "",
                "returncode": 0 if self.ok else 1}


class _Example:
    def __init__(self, path, entrypoint="runme.m"):
        self.path = Path(path)
        self.entrypoint = entrypoint


class _Staged:
    def __init__(self, path, from_canonical=True):
        self.path = Path(path)
        self.from_canonical = from_canonical
        self.source = "canonical"
        self.provenance = {"staged_datasets": []}


class _Manager:
    def __init__(self, working_dir):
        self._working = Path(working_dir)
        self.staged_with = None
        self._datasets = []

    def list_datasets(self):
        return list(self._datasets)

    def stage_example_for_run(self, *, source_example, extra_files=None,
                              entrypoint="runme.m", entrypoint_transform=None,
                              overrides=None):
        self.staged_with = dict(source_example=source_example,
                                entrypoint=entrypoint, overrides=overrides)
        self._working.mkdir(parents=True, exist_ok=True)
        return _Staged(self._working)


class _Submitter:
    def __init__(self):
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return {"jobid": "job-777", "remote_dir": "/scratch/rsb-u/run1",
                "log_file": "/scratch/rsb-u/run1/out.log"}


def _conn(bridge, **over):
    d = dict(profile_name="pace", host="login.pace.gatech.edu", user="rsb-u",
             port=22, remote_base_dir="/scratch/rsb-u", resolved_mode="connector",
             connector_online=True, bridge=bridge)
    d.update(over)
    return ConnectionContext(**d)


def _ctx(mgr, perm=Permission.EXECUTE):
    return ToolContext(user=_USER, application="icesheets", max_permission=perm,
                       workspace_manager=mgr, trace=Trace(user_id=_USER.user_id))


def _plan(tmp_example, **over):
    d = dict(application="icesheets", model="issm", example="SquareIceShelf",
             execution_mode="remote", compute_resource="pace", backend="spack",
             run_target="runme.m",
             slurm=SlurmRequest(job_name="ISSM", nodes=1, tasks=1,
                                tasks_per_node=1, wall_time="01:00:00",
                                account="gts-alloc"))
    d.update(over)
    return RunPlan(**d)


def _backend(bridge, submitter, example_dir, registrar=None, **conn_over):
    return RemoteSubmitBackend(
        connection=_conn(bridge, **conn_over),
        submitter=submitter,
        example_resolver=lambda ctx, model, name: _Example(example_dir),
        run_registrar=registrar,
    )


@pytest.fixture
def example_dir(tmp_path):
    d = tmp_path / "canonical" / "SquareIceShelf"
    d.mkdir(parents=True)
    (d / "runme.m").write_text("% issm example\n")
    return d


# ── happy path ───────────────────────────────────────────────────────
def test_composes_the_pipeline_and_returns_a_job_id(tmp_path, example_dir):
    bridge, sub = _Bridge(), _Submitter()
    mgr = _Manager(tmp_path / "working")
    registered = {}
    be = _backend(bridge, sub, example_dir,
                  registrar=lambda **kw: registered.update(kw))
    job = be.submit(_plan(example_dir), ctx=_ctx(mgr))

    assert job == "job-777"
    assert bridge.calls == ["whoami"]                      # B3 ran fresh
    assert sub.kwargs["example_dir"] == str((tmp_path / "working").resolve())
    assert sub.kwargs["run_file"] == "runme.m"
    assert sub.kwargs["spack_install_if_needed"] is False
    assert sub.kwargs["test_mode"] is False
    assert "agent_assist" in registered["metadata"]
    assert registered["metadata"]["agent_assist"]["plan_digest"] == _plan(example_dir).digest()


def test_canonical_example_is_never_written(tmp_path, example_dir):
    before = (example_dir / "runme.m").read_text()
    bridge, sub = _Bridge(), _Submitter()
    _backend(bridge, sub, example_dir).submit(
        _plan(example_dir), ctx=_ctx(_Manager(tmp_path / "w")))
    assert (example_dir / "runme.m").read_text() == before


# ── B3 ───────────────────────────────────────────────────────────────
def test_b3_identity_mismatch_blocks_before_submit(tmp_path, example_dir):
    bridge, sub = _Bridge(whoami="someone-else"), _Submitter()
    with pytest.raises(SubmitBlocked) as e:
        _backend(bridge, sub, example_dir).submit(
            _plan(example_dir), ctx=_ctx(_Manager(tmp_path / "w")))
    assert e.value.stage == "B3"
    assert sub.kwargs is None


def test_b3_runs_even_though_the_coordinator_already_checked_approval(tmp_path, example_dir):
    bridge, sub = _Bridge(ok=False), _Submitter()
    with pytest.raises(SubmitBlocked):
        _backend(bridge, sub, example_dir).submit(
            _plan(example_dir), ctx=_ctx(_Manager(tmp_path / "w")))
    assert sub.kwargs is None


# ── B4 ───────────────────────────────────────────────────────────────
def test_b4_bad_slurm_blocks(tmp_path, example_dir):
    bridge, sub = _Bridge(), _Submitter()
    bad = _plan(example_dir, slurm=SlurmRequest(job_name="ISSM", nodes=0, tasks=4,
                                                tasks_per_node=8,
                                                wall_time="01:00:00",
                                                account="a"))
    with pytest.raises(SubmitBlocked) as e:
        _backend(bridge, sub, example_dir).submit(bad, ctx=_ctx(_Manager(tmp_path / "w")))
    assert e.value.stage == "B4"
    assert sub.kwargs is None


def test_b4_illegal_account_chars_block(tmp_path, example_dir):
    bridge, sub = _Bridge(), _Submitter()
    bad = _plan(example_dir, slurm=SlurmRequest(job_name="ISSM", nodes=1, tasks=1,
                                                tasks_per_node=1,
                                                wall_time="01:00:00",
                                                account="a; rm -rf /"))
    with pytest.raises(SubmitBlocked):
        _backend(bridge, sub, example_dir).submit(bad, ctx=_ctx(_Manager(tmp_path / "w")))


# ── preflight ────────────────────────────────────────────────────────
def test_issm_container_without_matlab_blocks(tmp_path, example_dir, monkeypatch):
    from cryostack_src.resources import profiles
    prof = profiles.get_compute_profile("pace")
    monkeypatch.setattr(type(prof), "matlab_license_config", lambda self: None)
    bridge, sub = _Bridge(), _Submitter()
    with pytest.raises(SubmitBlocked) as e:
        _backend(bridge, sub, example_dir).submit(
            _plan(example_dir, backend="container"),
            ctx=_ctx(_Manager(tmp_path / "w")))
    assert e.value.stage == "preflight"


# ── LLM value hygiene ────────────────────────────────────────────────
def test_malicious_run_target_is_rejected(tmp_path, example_dir):
    bridge, sub = _Bridge(), _Submitter()
    with pytest.raises(SubmitBlocked) as e:
        _backend(bridge, sub, example_dir).submit(
            _plan(example_dir, run_target="../../etc/passwd"),
            ctx=_ctx(_Manager(tmp_path / "w")))
    assert e.value.stage == "run-target"
    assert sub.kwargs is None


def test_shell_metachars_in_job_name_are_sanitized(tmp_path, example_dir):
    bridge, sub = _Bridge(), _Submitter()
    p = _plan(example_dir, slurm=SlurmRequest(job_name="x`whoami`;rm -rf /",
                                              nodes=1, tasks=1, tasks_per_node=1,
                                              wall_time="01:00:00", account="a"))
    _backend(bridge, sub, example_dir).submit(p, ctx=_ctx(_Manager(tmp_path / "w")))
    assert sub.kwargs["slurm_job_name"] == "x-whoami-rm-rf"


def test_no_mail_or_command_or_env_channel(tmp_path, example_dir):
    bridge, sub = _Bridge(), _Submitter()
    _backend(bridge, sub, example_dir).submit(
        _plan(example_dir), ctx=_ctx(_Manager(tmp_path / "w")))
    assert sub.kwargs["slurm_mail"] == ""
    assert "command" not in sub.kwargs
    assert "env" not in sub.kwargs and "environment" not in sub.kwargs
    assert "remote_module_lines" not in sub.kwargs


# ── resource / mode guards ───────────────────────────────────────────
def test_plan_resource_must_match_the_wired_connection(tmp_path, example_dir):
    bridge, sub = _Bridge(), _Submitter()
    be = _backend(bridge, sub, example_dir, profile_name="frontera")
    with pytest.raises(SubmitBlocked) as e:
        be.submit(_plan(example_dir), ctx=_ctx(_Manager(tmp_path / "w")))
    assert e.value.stage == "resource"


def test_direct_ssh_agent_submit_is_blocked_owner_checkpoint(tmp_path, example_dir):
    bridge, sub = _Bridge(), _Submitter()
    be = _backend(bridge, sub, example_dir, resolved_mode="direct")
    with pytest.raises(SubmitBlocked) as e:
        be.submit(_plan(example_dir), ctx=_ctx(_Manager(tmp_path / "w")))
    assert e.value.stage == "transport"
    assert sub.kwargs is None


def test_cloud_plan_is_rejected_by_the_remote_backend(tmp_path, example_dir):
    bridge, sub = _Bridge(), _Submitter()
    with pytest.raises(SubmitBlocked):
        _backend(bridge, sub, example_dir).submit(
            _plan(example_dir, execution_mode="cloud", backend="container"),
            ctx=_ctx(_Manager(tmp_path / "w")))


def test_unknown_dataset_reference_blocks(tmp_path, example_dir):
    bridge, sub = _Bridge(), _Submitter()
    mgr = _Manager(tmp_path / "w")
    with pytest.raises(SubmitBlocked) as e:
        _backend(bridge, sub, example_dir).submit(
            _plan(example_dir, datasets=("ghost-dataset",)), ctx=_ctx(mgr))
    assert e.value.stage == "datasets"


# ── input-fingerprint binding (task 5) ──────────────────────────────
def test_input_fingerprint_drift_blocks_before_staging(tmp_path, example_dir):
    from cryostack_src.agents.fingerprint import fingerprint_inputs

    class _Appr:
        input_fingerprint = fingerprint_inputs(example_dir, run_target="runme.m").digest()
        approver_user_id = "rsb-u"
        approved_at = "2026-09-02T00:00:00Z"

    bridge, sub = _Bridge(), _Submitter()
    mgr = _Manager(tmp_path / "w")
    be = _backend(bridge, sub, example_dir)

    # a matching fingerprint submits fine
    be.submit(_plan(example_dir), ctx=_ctx(mgr), approval=_Appr())
    assert sub.kwargs is not None

    # now the canonical example changes -> the approved fingerprint is stale
    (example_dir / "runme.m").write_text("% edited after approval\n")
    sub2 = _Submitter()
    be2 = _backend(bridge, sub2, example_dir)
    with pytest.raises(SubmitBlocked) as e:
        be2.submit(_plan(example_dir), ctx=_ctx(_Manager(tmp_path / "w2")),
                   approval=_Appr())
    assert e.value.stage == "inputs"
    assert sub2.kwargs is None


# ── the backend is outside the agents package ────────────────────────
def test_backend_module_is_not_under_the_agents_package():
    import cryostack_src.agent_execution.remote_backend as m
    assert "cryostack/agents/" not in m.__file__.replace("\\", "/")
