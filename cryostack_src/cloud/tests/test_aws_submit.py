"""Cloud Commit 4 -- AWS Batch job submission (payload builders + submit call).

Every AWS call is mocked; nothing here touches AWS or incurs charges.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.drivers.aws.models import AWSConfig
from cryostack_src.cloud.drivers.aws.submit import (
    CloudSubmitError,
    build_container_overrides,
    build_submit_job_args,
    sanitize_job_name,
    submit_batch_job,
)

CONFIG = AWSConfig(region="us-east-2")
S3_RUN = "s3://cryostack-runs-123456789012/runs/cloud-20260101-000000-abcd1234"


class FakeBatch:
    def __init__(self, *, job_id="job-abc123", code=0, out=None, err=""):
        self.calls: list[list[str]] = []
        self._job_id, self._code, self._out, self._err = job_id, code, out, err

    def __call__(self, args):
        self.calls.append(list(args))
        out = self._out if self._out is not None else json.dumps({"jobId": self._job_id})
        return (self._code, out, self._err)


# ── job name ──────────────────────────────────────────────────────────
def test_job_name_is_sanitized_and_carries_the_run_id():
    n = sanitize_job_name("ICESHEETS run!!", suffix="cloud-20260101-000000-abcd1234")
    assert n == "ICESHEETS-run-cloud-20260101-000000-abcd1234"
    assert all(c.isalnum() or c in "-_" for c in n)
    assert n[0].isalnum()


def test_job_name_never_empty_or_over_128():
    assert sanitize_job_name("") == "cryostack"
    assert sanitize_job_name("...") == "cryostack"
    assert len(sanitize_job_name("x" * 400, suffix="y" * 400)) <= 128


# ── container overrides ──────────────────────────────────────────────
def test_overrides_carry_only_the_three_non_secret_env_values():
    ov = build_container_overrides(s3_run=S3_RUN, model="issm", run_target="runme.m")
    names = {e["name"] for e in ov["environment"]}
    assert names == {"CRYOSTACK_S3_RUN", "CRYOSTACK_MODEL", "CRYOSTACK_RUN_TARGET"}
    by = {e["name"]: e["value"] for e in ov["environment"]}
    assert by["CRYOSTACK_S3_RUN"] == S3_RUN
    assert by["CRYOSTACK_MODEL"] == "issm"
    assert by["CRYOSTACK_RUN_TARGET"] == "runme.m"


@pytest.mark.parametrize("bad_target", ["/abs/path.m", "~/x.m", "../escape.m", ""])
def test_overrides_reject_an_unsafe_run_target(bad_target):
    with pytest.raises(CloudSubmitError):
        build_container_overrides(s3_run=S3_RUN, model="issm", run_target=bad_target)


def test_overrides_reject_a_non_s3_run_location():
    with pytest.raises(CloudSubmitError):
        build_container_overrides(s3_run="/local/run", model="issm", run_target="runme.m")


def test_overrides_reject_a_secret_smuggled_into_the_run_target():
    with pytest.raises(CloudSubmitError):
        build_container_overrides(
            s3_run=S3_RUN, model="issm", run_target="aws_secret_access_key",
        )


# ── submit-job args ─────────────────────────────────────────────────
def test_submit_job_args_are_well_formed():
    args = build_submit_job_args(
        job_name="cryostack", job_queue="cryostack-queue",
        job_definition="cryostack-issm", s3_run=S3_RUN, model="issm",
        run_target="runme.m", run_id="cloud-20260101-000000-abcd1234",
    )
    assert args[:2] == ["batch", "submit-job"]
    assert args[args.index("--job-queue") + 1] == "cryostack-queue"
    assert args[args.index("--job-definition") + 1] == "cryostack-issm"
    overrides = json.loads(args[args.index("--container-overrides") + 1])
    assert {e["name"] for e in overrides["environment"]} == {
        "CRYOSTACK_S3_RUN", "CRYOSTACK_MODEL", "CRYOSTACK_RUN_TARGET"}


@pytest.mark.parametrize("missing", ["job_queue", "job_definition"])
def test_submit_job_args_require_queue_and_definition(missing):
    kw = dict(job_name="c", job_queue="q", job_definition="d", s3_run=S3_RUN,
              model="issm", run_target="runme.m")
    kw[missing] = ""
    with pytest.raises(CloudSubmitError):
        build_submit_job_args(**kw)


# ── submit_batch_job ────────────────────────────────────────────────
def test_submit_captures_the_job_id():
    fake = FakeBatch(job_id="a1b2c3")
    sub = submit_batch_job(
        CONFIG, job_name="cryostack", job_queue="cryostack-queue",
        job_definition="cryostack-issm", s3_run=S3_RUN, model="issm",
        run_target="runme.m", run_id="cloud-20260101-000000-abcd1234", aws=fake,
    )
    assert sub.job_id == "a1b2c3"
    assert sub.job_queue == "cryostack-queue"
    assert len(fake.calls) == 1 and fake.calls[0][:2] == ["batch", "submit-job"]


def test_submit_failure_is_a_clear_error_and_no_partial_state():
    fake = FakeBatch(code=255, err="AccessDeniedException: not authorized")
    with pytest.raises(CloudSubmitError) as e:
        submit_batch_job(
            CONFIG, job_name="c", job_queue="q", job_definition="d",
            s3_run=S3_RUN, model="issm", run_target="runme.m", aws=fake,
        )
    assert "not authorized" in str(e.value)


def test_submit_unparseable_output_is_a_clear_error():
    fake = FakeBatch(out="not json")
    with pytest.raises(CloudSubmitError):
        submit_batch_job(
            CONFIG, job_name="c", job_queue="q", job_definition="d",
            s3_run=S3_RUN, model="issm", run_target="runme.m", aws=fake,
        )
