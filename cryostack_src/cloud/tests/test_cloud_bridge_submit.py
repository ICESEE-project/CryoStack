"""Cloud Commit 4/5 -- CloudBridge submit/status/results end to end (mocked).

Covers: submit -> ExecutionResult, queued/running/completed/failed state
transitions, structured-result retrieval, and per-user isolation of the
retrieval target. No AWS calls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import cryostack_src.cloud.legacy.aws_batch as legacy_batch
from cryostack_src.cloud.bridge import CloudBridge

BUCKET = "cryostack-runs-123456789012"


class FakeS3:
    def __init__(self):
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        return (0, "", "")


class FakeBatch:
    def __init__(self, job_id="job-1"):
        self.calls = []
        self.job_id = job_id

    def __call__(self, args):
        self.calls.append(list(args))
        return (0, json.dumps({"jobId": self.job_id}), "")


@pytest.fixture
def staged(tmp_path):
    d = tmp_path / "work" / "SquareIceShelf"
    d.mkdir(parents=True)
    (d / "runme.m").write_text("md=model;\n")
    (d / "postprocess_icesee.m").write_text("% export\n")
    return d


def test_submit_returns_an_execution_result_with_job_id_and_s3(staged):
    bridge = CloudBridge(provider="aws", region="us-east-2")
    result = bridge.submit(
        staged_source=str(staged), model="issm", run_target="runme.m",
        bucket=BUCKET, matlab_license_configured=True,
        s3=FakeS3(), aws=FakeBatch(job_id="abc999"),
    )
    assert result.success and result.backend == "cloud"
    assert result.job_id == "abc999"
    assert result.working_directory.startswith(f"s3://{BUCKET}/runs/cloud-")
    assert result.output_directory.endswith("/outputs")
    assert result.metadata["s3_outputs"].endswith("/outputs")
    assert result.metadata["job_queue"] == "cryostack-queue"


@pytest.mark.parametrize("aws_state,expected", [
    ("SUBMITTED", "queued"),
    ("RUNNABLE", "queued"),
    ("STARTING", "running"),
    ("RUNNING", "running"),
    ("SUCCEEDED", "completed"),
    ("FAILED", "failed"),
])
def test_status_transitions_are_normalized(monkeypatch, aws_state, expected):
    def fake_run_aws(config, args):
        assert args[:2] == ["batch", "describe-jobs"]
        return (0, json.dumps({"jobs": [{"status": aws_state, "statusReason": "r",
                                         "container": {"exitCode": 0}}]}), "")

    monkeypatch.setattr(legacy_batch, "run_aws", fake_run_aws)
    st = CloudBridge(provider="aws", region="us-east-2").status(job_id="job-1")
    assert st.state == expected
    assert st.raw_state == aws_state


def test_results_retrieval_lands_the_structured_package(monkeypatch, tmp_path):
    """bridge.results -> results_sync -> aws s3 sync <s3>/outputs/ -> local dir
    in the outputs/{metadata.json,...} shape the Results UI reads."""
    landed = tmp_path / "cache" / "cloud_outputs"

    def fake_sync(*, s3_uri, region=None, profile=None, credentials=None):
        assert s3_uri.endswith("/runs/cloud-x")
        landed.mkdir(parents=True, exist_ok=True)
        (landed / "metadata.json").write_text(json.dumps({"schema": "cryostack.issm.results"}))
        (landed / "mesh").mkdir(); (landed / "fields").mkdir()
        (landed / "model").mkdir(); (landed / "figures").mkdir()
        return landed

    bridge = CloudBridge(provider="aws", region="us-east-2", results_sync=fake_sync)
    out = bridge.results(s3_uri="s3://b/runs/cloud-x")
    assert out == landed
    assert (landed / "metadata.json").is_file()
    assert {p.name for p in landed.iterdir()} >= {"metadata.json", "mesh", "fields", "model", "figures"}


def test_results_requires_a_configured_sync():
    with pytest.raises(RuntimeError):
        CloudBridge(provider="aws").results(s3_uri="s3://b/runs/x")


def test_result_sync_target_is_per_user(monkeypatch, tmp_path):
    """Two users' bridges route to two different WorkspaceManager caches -- a
    cloud result is never synced into another user's workspace."""
    from cryostack_src.workspace.manager import WorkspaceManager
    from cryostack_src.workspace.identity import WorkspaceUser

    class _W:
        def __init__(self, v=""):
            self.value = v

    def _mgr(root, uid):
        return WorkspaceManager(
            owner=WorkspaceUser(user_id=uid, source="cryostack-auth"),
            workspace_root=str(root), status={}, session={"id": "s"},
            example_dir=_W(str(root)), model=_W("issm"), backend=_W("aws"),
            file_picker=_W(), file_editor=_W(), log_output=None, results_output=None,
            cluster_host=_W(""), cluster_user=_W(""), cluster_port=_W(1),
            access_mode=_W(""), normalize_remote_path=lambda p: p,
            connector_fetch_archive=None, should_use_connector=lambda: False,
            connector_ssh=None, ssh_run=None, cluster_name=_W(""),
        )

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    alice, bob = _mgr(tmp_path / "a", "alice"), _mgr(tmp_path / "b", "bob")

    # each user's cloud results land under that user's own owner root only
    assert alice._owner_root != bob._owner_root
    assert "alice" in str(alice._owner_root) and "bob" in str(bob._owner_root)
    assert not str(bob._owner_root).startswith(str(alice._owner_root))
    # sync_cloud_results writes into the per-manager run cache, never a shared dir
    a_out = alice.local_run_cache_dir() / "cloud_outputs"
    b_out = bob.local_run_cache_dir() / "cloud_outputs"
    assert a_out != b_out
    assert not str(b_out).startswith(str(alice._owner_root))


def test_submit_command_and_result_carry_no_secrets(staged):
    batch = FakeBatch()
    result = CloudBridge(provider="aws", region="us-east-2").submit(
        staged_source=str(staged), model="issm", run_target="runme.m",
        bucket=BUCKET, matlab_license_configured=True, s3=FakeS3(), aws=batch,
    )
    blob = (json.dumps(batch.calls) + json.dumps(result.metadata) + " ".join(result.messages)).lower()
    for hint in ("secret", "token", "password", "aws_access", "mlm_license",
                 "credential", "1711@matlablic"):
        assert hint not in blob
