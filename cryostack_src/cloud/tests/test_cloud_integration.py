"""Cloud Commit 4/5 -- offline end-to-end integration.

Stage a real ISSM working copy -> submit -> poll status (queued -> running ->
completed) -> retrieve outputs -> the structured package is discoverable by the
same WorkspaceManager.result_package_for_run the Results UI uses.

Everything that would touch AWS is mocked. No resources, no charges.
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
from cryostack_src.workspace.manager import WorkspaceManager
from cryostack_src.workspace.models import RunInfo
from cryostack_src.workspace.identity import WorkspaceUser

BUCKET = "cryostack-runs-123456789012"
_RUNME = "md=model;\nmd=solve(md,'Stressbalance');\n"
_META = {"schema": "cryostack.issm.results", "solutions": {"StressbalanceSolution": {}}}


class _W:
    def __init__(self, v=""):
        self.value = v
        self.options = ()


class FakeS3:
    """Mocks `aws s3 sync/cp`. On an outputs download, materialises the
    structured package locally (as the real cloud runner would have written)."""

    def __init__(self, s3_store: dict):
        self.calls = []
        self.store = s3_store

    def __call__(self, args):
        a = list(args)
        self.calls.append(a)
        if "sync" in a:
            src = next((x for x in a if x.startswith("s3://")), "")
            i = a.index(src) if src else -1
            if src.endswith("/outputs/") and i >= 0 and i + 1 < len(a):
                dest = Path(a[i + 1])
                dest.mkdir(parents=True, exist_ok=True)
                (dest / "metadata.json").write_text(json.dumps(_META))
                for sub in ("mesh", "fields", "model", "figures"):
                    (dest / sub).mkdir(exist_ok=True)
                (dest / "mesh" / "mesh.h5").write_bytes(b"\x89HDF\r\n")
                (dest / "model" / "md_final.mat").write_bytes(b"MAT")
        return (0, "", "")


def _mgr(root, example_dir):
    return WorkspaceManager(
        owner=WorkspaceUser(user_id="user-cloud", source="cryostack-auth"),
        workspace_root=str(root), status={}, session={"id": "s"},
        example_dir=_W(str(example_dir)), model=_W("issm"), backend=_W("aws"),
        file_picker=_W(), file_editor=_W(), log_output=None, results_output=None,
        cluster_host=_W(""), cluster_user=_W(""), cluster_port=_W(1), access_mode=_W(""),
        normalize_remote_path=lambda p: p, connector_fetch_archive=None,
        should_use_connector=lambda: False, connector_ssh=None, ssh_run=None,
        cluster_name=_W(""),
    )


@pytest.fixture
def canonical(tmp_path):
    ex = tmp_path / "shipped" / "SquareIceShelf"
    ex.mkdir(parents=True)
    (ex / "runme.m").write_text(_RUNME)
    (ex / "postprocess_icesee.m").write_text("% structured export\n")
    return ex


def test_full_cloud_lifecycle_offline(tmp_path, canonical, monkeypatch):
    mgr = _mgr(tmp_path / "ws", canonical)
    staged = mgr.stage_example_for_run(source_example=str(canonical))

    s3 = FakeS3(s3_store={})
    batch_submit = lambda args: (0, json.dumps({"jobId": "batch-777"}), "")

    bridge = CloudBridge(
        provider="aws", region="us-east-2",
        results_sync=lambda **kw: mgr.sync_cloud_results(**kw),
    )

    # -- submit ---------------------------------------------------------
    result = bridge.submit(
        staged_source=str(staged.path), model="issm", run_target="runme.m",
        bucket=BUCKET, matlab_license_configured=True, s3=s3, aws=batch_submit,
    )
    assert result.job_id == "batch-777"
    s3_run = result.working_directory
    assert s3_run.startswith(f"s3://{BUCKET}/runs/cloud-")
    # input tree + descriptor were uploaded before submission
    assert any(c[:2] == ["s3", "sync"] and c[3].endswith("/input/") for c in s3.calls)
    assert any(c[:2] == ["s3", "cp"] and c[3].endswith("cryostack-run.json") for c in s3.calls)

    # -- register the run in the Workspace (what the gateway does) ------
    run = mgr.register_run(RunInfo(
        id=result.metadata["run_id"], name=result.metadata["run_id"],
        model="issm", backend="aws", execution_mode="cloud", status="submitted",
        jobid="batch-777", metadata={"cloud_run": s3_run, "region": "us-east-2"},
    ))
    mgr.select_run(run.id)

    # -- poll status: queued -> running -> completed -------------------
    states = iter(["SUBMITTED", "RUNNING", "SUCCEEDED"])

    def fake_run_aws(config, args):
        return (0, json.dumps({"jobs": [{"status": next(states),
                                         "container": {"exitCode": 0}}]}), "")

    monkeypatch.setattr(legacy_batch, "run_aws", fake_run_aws)
    assert bridge.status(job_id="batch-777").state == "queued"
    assert bridge.status(job_id="batch-777").state == "running"
    assert bridge.status(job_id="batch-777").state == "completed"

    # -- retrieve results --------------------------------------------
    local = bridge.results(s3_uri=s3_run, region="us-east-2", aws=s3)
    assert (local / "metadata.json").is_file()
    assert (local / "mesh" / "mesh.h5").is_file()
    assert (local / "model" / "md_final.mat").is_file()

    # -- the structured package is what the Results UI reads ----------
    mgr.invalidate_result_package_cache(run.id)
    pkg = mgr.result_package_for_run(run.id)
    assert pkg.outputs is not None
    assert pkg.status not in ("missing", "legacy")
    assert pkg.schema == "cryostack.issm.results"


def test_no_billable_job_when_the_run_is_gated(tmp_path, canonical):
    mgr = _mgr(tmp_path / "ws2", canonical)
    staged = mgr.stage_example_for_run(source_example=str(canonical))
    s3 = FakeS3(s3_store={})
    submitted = []
    bridge = CloudBridge(provider="aws", region="us-east-2")

    with pytest.raises(Exception):
        bridge.submit(
            staged_source=str(staged.path), model="issm", run_target="runme.m",
            bucket=BUCKET, matlab_license_configured=False,  # <- no cloud license
            s3=s3, aws=lambda args: submitted.append(args) or (0, "{}", ""),
        )
    assert s3.calls == []        # nothing uploaded
    assert submitted == []       # no submit-job
