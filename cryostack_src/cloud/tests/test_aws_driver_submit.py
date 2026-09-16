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


def test_direct_license_adds_no_tunnel_env_at_all(staged):
    """matlab_license_requires_tunnel not passed (default False) -- the
    existing direct-secret path is completely untouched; no
    CRYOSTACK_LT_* / CRYOSTACK_LICENSE_TUNNEL_* key appears anywhere."""
    batch = FakeBatch()
    AWSDriver(region="us-east-2").submit(
        staged_source=str(staged), model="issm", run_target="runme.m",
        bucket=BUCKET, matlab_license_configured=True, s3=FakeS3(), aws=batch,
    )
    overrides = json.loads(batch.calls[0][batch.calls[0].index("--container-overrides") + 1])
    names = {e["name"] for e in overrides["environment"]}
    assert names == {"CRYOSTACK_S3_RUN", "CRYOSTACK_MODEL", "CRYOSTACK_RUN_TARGET"}


# ── private-service license tunnel: wired at AWSDriver.submit() ─────────
def _bind_a_connector_session(monkeypatch, session_id="sid-1", control_secret="ctl-1"):
    from icesee_jupyter_book.core import connector_relay_client
    connector_relay_client.bind_session(session_id, control_secret, "user-a")
    monkeypatch.setattr(connector_relay_client, "mint_tunnel_grant",
                         lambda sid, purpose, *, ttl_seconds=None: {
                             "grant_id": "g-1", "token": "tok-abcXYZ789",
                             "purpose": purpose, "expires_at": 1.0,
                         })
    return connector_relay_client


@pytest.fixture(autouse=True)
def _clear_connector_binding():
    from icesee_jupyter_book.core import connector_relay_client
    connector_relay_client.clear_binding()
    yield
    connector_relay_client.clear_binding()


@pytest.mark.parametrize("compute_mode", ["fargate", "ec2"])
def test_required_tunnel_with_a_bound_connector_includes_tunnel_env(staged, monkeypatch, compute_mode):
    """Item: required tunnel + current Connector binding -> tunnel
    environment included -- identically for Fargate and EC2 (no branch on
    compute_mode anywhere in the tunnel wiring itself)."""
    relay_client = _bind_a_connector_session(monkeypatch)
    batch = FakeBatch()
    kwargs = dict(
        staged_source=str(staged), model="issm", run_target="runme.m",
        bucket=BUCKET, matlab_license_configured=True,
        matlab_license_requires_tunnel=True, compute_mode=compute_mode,
        s3=FakeS3(), aws=batch,
    )
    if compute_mode == "ec2":
        from cryostack_src.cloud.drivers.aws.batch_config import EC2ComputeConfig
        kwargs["ec2_config"] = EC2ComputeConfig()
    AWSDriver(region="us-east-2").submit(**kwargs)

    overrides = json.loads(batch.calls[0][batch.calls[0].index("--container-overrides") + 1])
    env = {e["name"]: e["value"] for e in overrides["environment"]}
    assert env["CRYOSTACK_LICENSE_TUNNEL_REQUIRED"] == "1"
    assert env["CRYOSTACK_LT_SESSION"] == "sid-1"
    assert env["CRYOSTACK_LT_TOKEN"] == "tok-abcXYZ789"
    assert env["CRYOSTACK_LT_RELAY"] == relay_client.RELAY_URL
    assert env["CRYOSTACK_LT_PURPOSE"] == "matlab-license"
    assert env["CRYOSTACK_LT_ENDPOINT"] == "primary"
    assert env["CRYOSTACK_LT_PORT"] == "1711"
    # the fixed 3 core values are still present too -- additive, not replaced
    assert env["CRYOSTACK_MODEL"] == "issm"


def test_fargate_and_ec2_produce_identical_tunnel_env_keys(staged, monkeypatch):
    """No branching on compute_mode anywhere in the tunnel mechanism --
    both submissions get the exact same set of tunnel env var NAMES."""
    from cryostack_src.cloud.drivers.aws.batch_config import EC2ComputeConfig

    _bind_a_connector_session(monkeypatch)
    batch_fargate, batch_ec2 = FakeBatch(job_id="f1"), FakeBatch(job_id="e1")
    AWSDriver(region="us-east-2").submit(
        staged_source=str(staged), model="issm", run_target="runme.m",
        bucket=BUCKET, matlab_license_configured=True,
        matlab_license_requires_tunnel=True, compute_mode="fargate",
        s3=FakeS3(), aws=batch_fargate,
    )
    AWSDriver(region="us-east-2").submit(
        staged_source=str(staged), model="issm", run_target="runme.m",
        bucket=BUCKET, matlab_license_configured=True,
        matlab_license_requires_tunnel=True, compute_mode="ec2",
        ec2_config=EC2ComputeConfig(), s3=FakeS3(), aws=batch_ec2,
    )
    ov_fargate = json.loads(batch_fargate.calls[0][batch_fargate.calls[0].index("--container-overrides") + 1])
    ov_ec2 = json.loads(batch_ec2.calls[0][batch_ec2.calls[0].index("--container-overrides") + 1])
    names_fargate = {e["name"] for e in ov_fargate["environment"]}
    names_ec2 = {e["name"] for e in ov_ec2["environment"]}
    assert names_fargate == names_ec2


def test_required_tunnel_without_a_connector_binding_blocks_before_any_aws_call(staged):
    """Item: required tunnel + no Connector -> submission blocked BEFORE
    AWS -- no S3 upload, no Batch submit-job, never a user-entered session
    id substituted."""
    from cryostack_src.cloud.matlab_license import LicenseTunnelUnavailable

    s3, batch = FakeS3(), FakeBatch()
    with pytest.raises(LicenseTunnelUnavailable):
        AWSDriver(region="us-east-2").submit(
            staged_source=str(staged), model="issm", run_target="runme.m",
            bucket=BUCKET, matlab_license_configured=True,
            matlab_license_requires_tunnel=True, s3=s3, aws=batch,
        )
    assert s3.calls == []
    assert batch.calls == []


def test_tunnel_grant_token_never_appears_in_the_returned_submission_record(staged, monkeypatch):
    _bind_a_connector_session(monkeypatch)
    batch = FakeBatch()
    out = AWSDriver(region="us-east-2").submit(
        staged_source=str(staged), model="issm", run_target="runme.m",
        bucket=BUCKET, matlab_license_configured=True,
        matlab_license_requires_tunnel=True, s3=FakeS3(), aws=batch,
    )
    assert "tok-abcXYZ789" not in json.dumps(out)


def test_tunnel_grant_token_never_reaches_a_log_or_print(staged, monkeypatch, capsys):
    _bind_a_connector_session(monkeypatch)
    batch = FakeBatch()
    AWSDriver(region="us-east-2").submit(
        staged_source=str(staged), model="issm", run_target="runme.m",
        bucket=BUCKET, matlab_license_configured=True,
        matlab_license_requires_tunnel=True, s3=FakeS3(), aws=batch,
    )
    captured = capsys.readouterr()
    assert "tok-abcXYZ789" not in captured.out
    assert "tok-abcXYZ789" not in captured.err


def test_existing_forbidden_value_is_still_rejected_even_under_an_allow_listed_name(staged, monkeypatch):
    """The narrow name-only exemption for CRYOSTACK_LT_* must not extend to
    their VALUES: if the grant token itself were ever, by a bug, a real
    AWS-credential-shaped string, submission must still fail."""
    from icesee_jupyter_book.core import connector_relay_client
    from cryostack_src.cloud.drivers.aws.submit import CloudSubmitError

    connector_relay_client.bind_session("sid-1", "ctl-1", "user-a")
    monkeypatch.setattr(connector_relay_client, "mint_tunnel_grant",
                         lambda sid, purpose, *, ttl_seconds=None: {
                             "grant_id": "g-1",
                             "token": "aws_secret_access_key=AKIAEXAMPLE",  # forbidden-shaped value
                             "purpose": purpose,
                         })
    with pytest.raises(CloudSubmitError):
        AWSDriver(region="us-east-2").submit(
            staged_source=str(staged), model="issm", run_target="runme.m",
            bucket=BUCKET, matlab_license_configured=True,
            matlab_license_requires_tunnel=True, s3=FakeS3(), aws=FakeBatch(),
        )


def test_unrelated_forbidden_env_value_is_still_rejected_when_a_tunnel_is_active(staged, monkeypatch):
    """Existing secret/credential protection for the ORIGINAL 3 core values
    remains effective even while the tunnel mechanism is active -- an
    unsafe run_target (the only caller-influenced string among them) is
    still rejected the same way it always was."""
    _bind_a_connector_session(monkeypatch)
    with pytest.raises(Exception):
        AWSDriver(region="us-east-2").submit(
            staged_source=str(staged), model="issm", run_target="/etc/password",
            bucket=BUCKET, matlab_license_configured=True,
            matlab_license_requires_tunnel=True, s3=FakeS3(), aws=FakeBatch(),
        )
