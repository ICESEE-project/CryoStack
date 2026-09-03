"""C6-F: the license-neutral cloud infrastructure smoke test.

No AWS. The ``aws`` callable is a fake that records calls and returns canned
JSON, and the S3 read-back is materialised locally.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.smoke import run_infrastructure_smoke_test


class FakeAWS:
    def __init__(self, *, fail_on=None, no_image=False, queue_disabled=False):
        self.calls = []
        self.fail_on = fail_on or set()
        self.no_image = no_image
        self.queue_disabled = queue_disabled
        self._store = {}

    def __call__(self, args):
        self.calls.append(list(args))
        head = " ".join(args[:2])
        if head in self.fail_on:
            return (255, "", f"AccessDenied on {head}")
        if args[:2] == ["sts", "get-caller-identity"]:
            return (0, json.dumps({"Account": "123456789012"}), "")
        if args[:2] == ["s3", "cp"]:
            src, dst = args[2], args[3]
            if dst.startswith("s3://"):            # upload: remember the bytes
                self._store[dst] = Path(src).read_text()
            else:                                 # download: echo them back
                Path(dst).write_text(self._store.get(src, ""))
            return (0, "", "")
        if args[:2] == ["s3", "rm"]:
            self._store.pop(args[2], None)
            return (0, "", "")
        if args[:2] == ["batch", "describe-job-queues"]:
            state = "DISABLED" if self.queue_disabled else "ENABLED"
            return (0, json.dumps({"jobQueues": [{"state": state, "status": "VALID"}]}), "")
        if args[:2] == ["batch", "describe-job-definitions"]:
            return (0, json.dumps({"jobDefinitions": [{"jobDefinitionName": "cryostack-issm"}]}), "")
        if args[:2] == ["ecr", "describe-images"]:
            imgs = [] if self.no_image else [{"imageDigest": "sha256:abc"}]
            return (0, json.dumps({"imageDetails": imgs}), "")
        return (0, "{}", "")


def _kw(**over):
    base = dict(region="us-east-2", bucket="cryostack-runs-123456789012",
               user_prefix="alice-abc123", job_queue="cryostack-queue",
               job_definition="cryostack-issm", ecr_repository="cryostack-issm")
    base.update(over)
    return base


def test_all_green_infrastructure_ready():
    aws = FakeAWS()
    r = run_infrastructure_smoke_test(aws=aws, **_kw())
    assert r.ok and r.infrastructure_ready
    assert [c.status for c in r.checks].count("PASS") >= 5
    # the S3 probe used the caller's own prefix
    cp = [c for c in aws.calls if c[:2] == ["s3", "cp"]]
    assert any("runs/alice-abc123/_smoke/" in c[3] for c in cp if c[3].startswith("s3://"))
    # and it was deleted
    assert any(c[:2] == ["s3", "rm"] for c in aws.calls)
    # nothing was ever submitted
    assert not any("submit-job" in " ".join(c) for c in aws.calls)


def test_identity_failure_short_circuits():
    r = run_infrastructure_smoke_test(
        aws=FakeAWS(fail_on={"sts get-caller-identity"}), **_kw())
    assert not r.ok and not r.infrastructure_ready
    assert r.checks[0].name == "AWS identity" and r.checks[0].status == "FAIL"
    assert len(r.checks) == 1                       # stopped after identity


def test_missing_image_fails_but_still_reports_the_rest():
    r = run_infrastructure_smoke_test(aws=FakeAWS(no_image=True), **_kw())
    assert not r.infrastructure_ready
    ecr = [c for c in r.checks if c.name == "ECR image"][0]
    assert ecr.status == "FAIL"
    assert any(c.name == "AWS identity" and c.status == "PASS" for c in r.checks)


def test_disabled_queue_is_a_failure():
    r = run_infrastructure_smoke_test(aws=FakeAWS(queue_disabled=True), **_kw())
    q = [c for c in r.checks if c.name == "Batch job queue"][0]
    assert q.status == "FAIL"


def test_optional_resources_are_skipped_not_failed():
    r = run_infrastructure_smoke_test(
        aws=FakeAWS(), **_kw(job_queue="", job_definition="", ecr_repository=""))
    skipped = [c.name for c in r.checks if c.status == "SKIP"]
    assert {"Batch job queue", "Batch job definition", "ECR image"} <= set(skipped)
    assert r.ok                                     # skips do not fail the report


def test_byo_credentials_win_over_profile_in_the_config(monkeypatch):
    """C7.5: a connected BYO account probes its OWN infrastructure -- the
    assumed-role temp credentials are used and no --profile is added."""
    captured = {}

    def fake_run(cmd, capture_output, text, env):
        captured["cmd"] = cmd
        captured["env"] = env

        class R:
            returncode = 0
            stdout = json.dumps({"Account": "774888247882"})
            stderr = ""

        return R()

    monkeypatch.setattr(
        "cryostack_src.cloud.drivers.aws.auth.subprocess.run", fake_run)
    monkeypatch.setenv("AWS_PROFILE", "dev")

    creds = {"AWS_ACCESS_KEY_ID": "ASIA_B", "AWS_SECRET_ACCESS_KEY": "s",
             "AWS_SESSION_TOKEN": "t"}
    report = run_infrastructure_smoke_test(
        **_kw(profile="dev", credentials=creds))

    assert "--profile" not in captured["cmd"]
    assert captured["env"]["AWS_ACCESS_KEY_ID"] == "ASIA_B"
    assert "AWS_PROFILE" not in captured["env"]
    # identity resolves to the BYO account
    assert any(c.status == "PASS" and "774888247882" in c.detail
               for c in report.checks if c.name == "AWS identity")
