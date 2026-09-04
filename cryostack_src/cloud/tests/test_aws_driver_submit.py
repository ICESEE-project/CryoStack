"""Cloud Commit 4 -- AWSDriver.submit end to end (preflight -> stage -> submit).

Every AWS call is mocked. No AWS resources are created.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.drivers.aws.driver import AWSDriver
from cryostack_src.cloud.runtime import CloudRuntimeError

BUCKET = "cryostack-runs-123456789012"


class FakeS3:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, args):
        a = list(args)
        self.calls.append(a)
        if self.fail_on and a[:2] == ["s3", self.fail_on]:
            return (1, "", f"mock s3 {self.fail_on} failed")
        return (0, "", "")


class FakeBatch:
    def __init__(self, job_id="job-xyz", code=0):
        self.calls = []
        self.job_id, self.code = job_id, code

    def __call__(self, args):
        self.calls.append(list(args))
        return (self.code, json.dumps({"jobId": self.job_id}), "")


@pytest.fixture
def staged(tmp_path):
    d = tmp_path / "working" / "SquareIceShelf"
    d.mkdir(parents=True)
    (d / "runme.m").write_text("md=model;\nmd=solve(md,'Stressbalance');\n")
    (d / "postprocess_icesee.m").write_text("% structured export\n")
    (d / "Square.par").write_text("% params\n")
    return d


@pytest.fixture
def staged_icepack(tmp_path):
    d = tmp_path / "working" / "IcepackExample"
    d.mkdir(parents=True)
    (d / "run.py").write_text("import icepack\nprint('hello icepack')\n")
    return d


def test_happy_path_stages_then_submits_and_returns_a_full_record(staged):
    s3, batch = FakeS3(), FakeBatch(job_id="a1b2c3")
    driver = AWSDriver(region="us-east-2")
    out = driver.submit(
        staged_source=str(staged), model="issm", run_target="runme.m",
        bucket=BUCKET, matlab_license_configured=True, s3=s3, aws=batch,
    )
    assert out["batch_job_id"] == "a1b2c3"
    assert out["s3_run"].startswith(f"s3://{BUCKET}/runs/cloud-")
    assert out["s3_outputs"] == out["s3_run"] + "/outputs"
    assert out["model"] == "issm"
    assert out["job_queue"] == "cryostack-queue"
    assert out["job_definition"] == "cryostack-issm"
    # order: S3 upload(s) happened, then submit-job
    assert any(c[:2] == ["s3", "sync"] for c in s3.calls)
    assert batch.calls and batch.calls[0][:2] == ["batch", "submit-job"]


def test_preflight_blocks_before_any_s3_upload_or_submit(staged):
    """ISSM without a cloud MATLAB license -> blocked, nothing billable."""
    s3, batch = FakeS3(), FakeBatch()
    driver = AWSDriver(region="us-east-2")
    with pytest.raises(CloudRuntimeError):
        driver.submit(
            staged_source=str(staged), model="issm", run_target="runme.m",
            bucket=BUCKET, matlab_license_configured=False, s3=s3, aws=batch,
        )
    assert s3.calls == []
    assert batch.calls == []


def test_icepack_happy_path_stages_and_submits_without_a_matlab_license(staged_icepack):
    """Icepack Cloud Execution checkpoint: Icepack stages and submits exactly
    like ISSM, using ITS OWN job definition/ECR repo, and never needs a
    MATLAB license -- the license gate is ISSM-only."""
    s3, batch = FakeS3(), FakeBatch(job_id="ic3pack")
    driver = AWSDriver(region="us-east-2")
    out = driver.submit(
        staged_source=str(staged_icepack), model="icepack", run_target="run.py",
        bucket=BUCKET, matlab_license_configured=False, s3=s3, aws=batch,
    )
    assert out["batch_job_id"] == "ic3pack"
    assert out["model"] == "icepack"
    assert out["job_queue"] == "cryostack-queue"
    assert out["job_definition"] == "cryostack-icepack"
    assert any(c[:2] == ["s3", "sync"] for c in s3.calls)
    assert batch.calls and batch.calls[0][:2] == ["batch", "submit-job"]


def test_unsupported_model_blocks_before_upload(staged):
    s3, batch = FakeS3(), FakeBatch()
    driver = AWSDriver(region="us-east-2")
    with pytest.raises(CloudRuntimeError):
        driver.submit(
            staged_source=str(staged), model="not-a-real-model", run_target="runme.m",
            bucket=BUCKET, matlab_license_configured=True, s3=s3, aws=batch,
        )
    assert s3.calls == [] and batch.calls == []


def test_failed_staging_never_submits(staged):
    s3, batch = FakeS3(fail_on="sync"), FakeBatch()
    driver = AWSDriver(region="us-east-2")
    with pytest.raises(Exception):
        driver.submit(
            staged_source=str(staged), model="issm", run_target="runme.m",
            bucket=BUCKET, matlab_license_configured=True, s3=s3, aws=batch,
        )
    assert batch.calls == []  # no billable job on a staging failure


def test_missing_bucket_is_rejected(staged):
    driver = AWSDriver(region="us-east-2")
    with pytest.raises(RuntimeError):
        driver.submit(
            staged_source=str(staged), model="issm", run_target="runme.m",
            bucket="", matlab_license_configured=True, s3=FakeS3(), aws=FakeBatch(),
        )


def test_explicit_queue_and_definition_are_honoured(staged):
    s3, batch = FakeS3(), FakeBatch()
    out = AWSDriver(region="us-east-2").submit(
        staged_source=str(staged), model="issm", run_target="runme.m",
        bucket=BUCKET, matlab_license_configured=True,
        job_queue="team-queue", job_definition="team-issm:7", s3=s3, aws=batch,
    )
    assert out["job_queue"] == "team-queue"
    assert batch.calls[0][batch.calls[0].index("--job-definition") + 1] == "team-issm:7"


def test_legacy_submitter_still_wins_when_injected(staged):
    seen = {}
    driver = AWSDriver(region="us-east-2", submitter=lambda **kw: seen.update(kw) or {"batch_job_id": "legacy"})
    out = driver.submit(model="issm", example_name="x")
    assert out == {"batch_job_id": "legacy"}
    assert seen["model"] == "issm"


def test_no_secret_or_license_value_in_the_submit_command(staged):
    batch = FakeBatch()
    AWSDriver(region="us-east-2").submit(
        staged_source=str(staged), model="issm", run_target="runme.m",
        bucket=BUCKET, matlab_license_configured=True, s3=FakeS3(), aws=batch,
    )
    blob = json.dumps(batch.calls).lower()
    for hint in ("secret", "token", "password", "mlm_license", "aws_access",
                 "1711@matlablic", "credential", "/home/", "/users/"):
        assert hint not in blob
