"""C6-F: user A's cloud run inputs and outputs are S3-scoped to A's prefix and
never land in user B's local cache.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.drivers.aws.models import AWSConfig
from cryostack_src.cloud.drivers.aws.staging import CloudStagingError, stage_run_inputs
from cryostack_src.frontend.cryolauncher.cloud_run_controller import user_run_prefix

_CFG = AWSConfig(region="us-east-2")


@pytest.fixture
def staged(tmp_path):
    d = tmp_path / "SquareIceShelf"
    d.mkdir()
    (d / "runme.m").write_text("md=model;\n")
    return d


def _fake_s3():
    calls = []

    def _s3(args):
        calls.append(list(args))
        return (0, "", "")

    return _s3, calls


def test_run_prefix_puts_the_run_under_the_users_segment(staged):
    s3, calls = _fake_s3()
    prefix = user_run_prefix("alice-abc123def456")
    out = stage_run_inputs(_CFG, source=str(staged), model="issm",
                           run_target="runme.m", bucket="cryo-b",
                           run_prefix=prefix, s3=s3)
    assert out.s3_run.startswith("s3://cryo-b/runs/alice-abc123def456/cloud-")
    assert out.s3_input == f"{out.s3_run}/input"
    assert out.s3_outputs == f"{out.s3_run}/outputs"
    # every upload targeted that user's tree
    for c in calls:
        dst = next((x for x in c if x.startswith("s3://")), "")
        if dst:
            assert dst.startswith("s3://cryo-b/runs/alice-abc123def456/")


def test_two_users_get_disjoint_s3_trees(staged):
    s3, _ = _fake_s3()
    a = stage_run_inputs(_CFG, source=str(staged), model="issm", run_target="runme.m",
                         bucket="cryo-b", run_prefix=user_run_prefix("alice-aaa"), s3=s3)
    b = stage_run_inputs(_CFG, source=str(staged), model="issm", run_target="runme.m",
                         bucket="cryo-b", run_prefix=user_run_prefix("bob-bbb"), s3=s3)
    assert a.s3_run.startswith("s3://cryo-b/runs/alice-aaa/")
    assert b.s3_run.startswith("s3://cryo-b/runs/bob-bbb/")
    assert not a.s3_run.startswith(b.s3_run.rsplit("/", 1)[0])


def test_no_prefix_is_still_valid_backward_compatible(staged):
    s3, _ = _fake_s3()
    out = stage_run_inputs(_CFG, source=str(staged), model="issm",
                           run_target="runme.m", bucket="cryo-b", s3=s3)
    assert out.s3_run.startswith("s3://cryo-b/runs/cloud-")


@pytest.mark.parametrize("bad", ["../escape/", "a//b/", "seg with space/",
                                 "x" * 70 + "/"])
def test_unsafe_run_prefix_is_rejected(staged, bad):
    s3, _ = _fake_s3()
    with pytest.raises(CloudStagingError):
        stage_run_inputs(_CFG, source=str(staged), model="issm",
                         run_target="runme.m", bucket="cryo-b", run_prefix=bad, s3=s3)


def test_sync_cloud_results_writes_only_the_calling_users_run_cache(tmp_path):
    """sync_cloud_results lands under the selected run's per-user working dir."""
    from cryostack_src.workspace.identity import WorkspaceUser
    from cryostack_src.workspace.manager import WorkspaceManager
    from cryostack_src.workspace.models import RunInfo

    class _W:
        def __init__(self, v=""):
            self.value = v
            self.options = ()

    def _mk(uid):
        return WorkspaceManager(
            owner=WorkspaceUser(user_id=uid, source="cryostack-auth"),
            workspace_root=str(tmp_path), status={}, session={"id": "s"},
            example_dir=_W(), model=_W("issm"), backend=_W("aws"),
            file_picker=_W(), file_editor=_W(), log_output=None, results_output=None,
            cluster_host=_W(), cluster_user=_W(), cluster_port=_W(1), access_mode=_W(),
            normalize_remote_path=lambda p: p, connector_fetch_archive=None,
            should_use_connector=lambda: False, connector_ssh=None, ssh_run=None,
            cluster_name=_W(),
        )

    def _s3(args):
        dst = args[-1]
        Path(dst).mkdir(parents=True, exist_ok=True)
        (Path(dst) / "metadata.json").write_text(json.dumps({"schema": "x"}))
        return (0, "", "")

    a, b = _mk("alice"), _mk("bob")
    for m, uid in ((a, "alice"), (b, "bob")):
        run = m.register_run(RunInfo(
            id=f"{uid}-run", name=f"{uid}-run", model="issm", backend="aws",
            execution_mode="cloud", status="submitted", jobid="j",
            metadata={"cloud_run": f"s3://x/runs/{uid}/x"}))
        m.select_run(run.id)

    a_out = a.sync_cloud_results(s3_uri="s3://x/runs/alice/x", aws=_s3)
    assert (a_out / "metadata.json").is_file()
    # alice's outputs are under alice's owner root, not bob's
    assert a.owner.safe_id in str(a_out.resolve())
    assert b.owner.safe_id not in str(a_out.resolve())
