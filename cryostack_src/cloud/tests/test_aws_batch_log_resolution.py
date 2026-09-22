# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Batch CloudWatch log-group resolution (regression)
# File        : test_aws_batch_log_resolution.py
#
# Description :
#     Live-incident regression -- ResourceNotFoundException on
#     logs:GetLogEvents after the CryoStackLogsRead IAM fix landed.
#     `batch_logs()` was hardcoding the log GROUP to `/aws/batch/job`
#     regardless of what the job's own job definition actually configured
#     (`batch_config.py`'s `/cryostack/batch/<model>` for any job definition
#     registered after the awslogs customization). This file locks in the
#     per-job resolution (DescribeJobs -> jobDefinition ARN ->
#     DescribeJobDefinitions -> containerProperties.logConfiguration.options
#     ["awslogs-group"]) and the non-fatal handling of every log-read
#     failure mode.
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: MIT
#
# =============================================================================
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import cryostack_src.cloud.legacy.aws_batch as legacy_batch
from cryostack_src.cloud.legacy.aws_batch import (
    DEFAULT_LOG_GROUP,
    AWSConfig,
    batch_logs,
    resolve_log_group,
)

JOB_ID = "12345678-aaaa-bbbb-cccc-1234567890ab"
JOB_DEFINITION_ARN = (
    "arn:aws:batch:us-east-2:774888247882:job-definition/cryostack-icepack:7"
)


def _job(*, status="SUCCEEDED", log_stream="icepack/default/abc123",
         job_definition=JOB_DEFINITION_ARN):
    container = {}
    if log_stream is not None:
        container["logStreamName"] = log_stream
    job = {"status": status, "container": container}
    if job_definition is not None:
        job["jobDefinition"] = job_definition
    return job


class _Result:
    def __init__(self, returncode=0, stdout="{}", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_subprocess(*, describe_jobs_response=None, job_definition_response=None,
                      get_log_events_response=None):
    """A `subprocess.run` stand-in that dispatches on the AWS CLI verb --
    `describe-jobs`, `describe-job-definitions` and `get-log-events` are
    each independently configurable; every call is recorded as (cmd) for
    assertions."""
    calls: list[list[str]] = []

    def fake_run(cmd, capture_output, text, env):
        calls.append(list(cmd))
        if "describe-jobs" in cmd:
            return describe_jobs_response or _Result(
                stdout=json.dumps({"jobs": [_job()]}))
        if "describe-job-definitions" in cmd:
            return job_definition_response or _Result(stdout="{\"jobDefinitions\": []}")
        if "get-log-events" in cmd:
            return get_log_events_response or _Result(stdout=json.dumps({"events": []}))
        raise AssertionError(f"unexpected AWS CLI call: {cmd}")

    return fake_run, calls


def _job_definition_result(*, awslogs_group: str | None) -> _Result:
    options = {"awslogs-group": awslogs_group} if awslogs_group else {}
    definition = {
        "containerProperties": {
            "logConfiguration": {"logDriver": "awslogs", "options": options},
        }
    }
    return _Result(stdout=json.dumps({"jobDefinitions": [definition]}))


CFG = AWSConfig(region="us-east-2")


# ── 1. legacy/default Batch job -> /aws/batch/job ──────────────────────────
def test_resolve_log_group_falls_back_to_aws_batch_default_when_unset(monkeypatch):
    """A job definition whose logConfiguration never set awslogs-group (a
    legacy/default Batch job definition) resolves to AWS Batch's own
    default group -- never a guess."""
    fake_run, calls = _fake_subprocess(
        job_definition_response=_job_definition_result(awslogs_group=None))
    monkeypatch.setattr(legacy_batch, "subprocess",
                         type("S", (), {"run": staticmethod(fake_run)}))

    group = resolve_log_group(CFG, _job())
    assert group == DEFAULT_LOG_GROUP == "/aws/batch/job"
    assert any("describe-job-definitions" in c for c in calls)
    assert JOB_DEFINITION_ARN in calls[0]


# ── 2. CryoStack job definition -> explicit /cryostack/... group ──────────
def test_resolve_log_group_uses_the_configured_cryostack_group(monkeypatch):
    fake_run, _calls = _fake_subprocess(
        job_definition_response=_job_definition_result(
            awslogs_group="/cryostack/batch/icepack"))
    monkeypatch.setattr(legacy_batch, "subprocess",
                         type("S", (), {"run": staticmethod(fake_run)}))

    group = resolve_log_group(CFG, _job())
    assert group == "/cryostack/batch/icepack"


def test_batch_logs_reads_from_the_resolved_cryostack_group_not_the_hardcoded_default(
        monkeypatch):
    """The live-incident regression: batch_logs() must send
    --log-group-name /cryostack/batch/icepack (the job definition's actual
    configured group) to GetLogEvents, never the hardcoded
    /aws/batch/job."""
    fake_run, calls = _fake_subprocess(
        job_definition_response=_job_definition_result(
            awslogs_group="/cryostack/batch/icepack"),
        get_log_events_response=_Result(stdout=json.dumps(
            {"events": [{"message": "hello"}]})))
    monkeypatch.setattr(legacy_batch, "subprocess",
                         type("S", (), {"run": staticmethod(fake_run)}))

    text = batch_logs(CFG, JOB_ID)
    assert text == "hello"
    get_call = next(c for c in calls if "get-log-events" in c)
    i = get_call.index("--log-group-name")
    assert get_call[i + 1] == "/cryostack/batch/icepack"


# ── 3. missing / not-yet-created log stream ────────────────────────────────
def test_batch_logs_no_log_stream_yet_is_non_fatal_and_never_calls_get_log_events(
        monkeypatch):
    calls_seen = []

    def fake_run(cmd, capture_output, text, env):
        calls_seen.append(list(cmd))
        return _Result(stdout="{}")

    monkeypatch.setattr(legacy_batch, "subprocess",
                         type("S", (), {"run": staticmethod(fake_run)}))
    # describe_job() itself returns the job with no logStreamName yet
    monkeypatch.setattr(legacy_batch, "describe_job",
                         lambda cfg, job_id: _job(log_stream=None, status="RUNNABLE"))

    text = batch_logs(CFG, JOB_ID)
    assert "not available yet" in text.lower()
    assert not any("get-log-events" in c for c in calls_seen)


def test_batch_logs_resource_not_found_while_running_is_non_fatal(monkeypatch):
    """GetLogEvents ResourceNotFoundException on a job that has not
    finished yet -> the exact live-incident error -- must not raise."""
    fake_run, _calls = _fake_subprocess(
        job_definition_response=_job_definition_result(
            awslogs_group="/cryostack/batch/icepack"),
        get_log_events_response=_Result(
            returncode=254,
            stderr=("An error occurred (ResourceNotFoundException) when "
                     "calling the GetLogEvents operation: The specified "
                     "log stream does not exist.")))
    monkeypatch.setattr(legacy_batch, "subprocess",
                         type("S", (), {"run": staticmethod(fake_run)}))
    monkeypatch.setattr(legacy_batch, "describe_job",
                         lambda cfg, job_id: _job(status="RUNNING"))

    text = batch_logs(CFG, JOB_ID)
    assert "not available yet" in text.lower()
    assert "RUNNING" in text


def test_batch_logs_resource_not_found_on_completed_job_reports_diagnostic_detail(
        monkeypatch):
    """A completed job whose resolved group/stream is genuinely absent
    (e.g. expired retention) is still non-fatal, but the message must name
    the resolved group and stream so it is diagnosable."""
    fake_run, _calls = _fake_subprocess(
        job_definition_response=_job_definition_result(
            awslogs_group="/cryostack/batch/icepack"),
        get_log_events_response=_Result(
            returncode=254,
            stderr=("An error occurred (ResourceNotFoundException) when "
                     "calling the GetLogEvents operation: The specified "
                     "log stream does not exist.")))
    monkeypatch.setattr(legacy_batch, "subprocess",
                         type("S", (), {"run": staticmethod(fake_run)}))
    monkeypatch.setattr(legacy_batch, "describe_job",
                         lambda cfg, job_id: _job(status="SUCCEEDED"))

    text = batch_logs(CFG, JOB_ID)
    low = text.lower()
    assert "unavailable" in low
    assert "/cryostack/batch/icepack" in text
    assert "icepack/default/abc123" in text
    assert "results are unaffected" in low


# ── 4. GetLogEvents AccessDenied ────────────────────────────────────────────
def test_batch_logs_access_denied_still_raises_with_the_raw_aws_text(monkeypatch):
    """AccessDenied is NOT swallowed here -- it must keep raising with the
    raw AWS text (which names logs:GetLogEvents) so the frontend's existing
    classify_cloud_failure / is_log_read_permission_error can classify it as
    the non-fatal permission message."""
    fake_run, _calls = _fake_subprocess(
        job_definition_response=_job_definition_result(
            awslogs_group="/cryostack/batch/icepack"),
        get_log_events_response=_Result(
            returncode=254,
            stderr=("An error occurred (AccessDeniedException) when "
                     "calling the GetLogEvents operation: User: "
                     "arn:aws:sts::774888247882:assumed-role/x is not "
                     "authorized to perform: logs:GetLogEvents on "
                     "resource: arn:aws:logs:us-east-2:774888247882:"
                     "log-group:/cryostack/batch/icepack:log-stream:"
                     "icepack/default/abc123")))
    monkeypatch.setattr(legacy_batch, "subprocess",
                         type("S", (), {"run": staticmethod(fake_run)}))

    try:
        batch_logs(CFG, JOB_ID)
        raise AssertionError("expected batch_logs to raise")
    except RuntimeError as error:
        assert "logs:GetLogEvents" in str(error)
        assert "AccessDeniedException" in str(error)


# ── 5. successful retrieval ─────────────────────────────────────────────────
def test_batch_logs_success_joins_event_messages(monkeypatch):
    fake_run, _calls = _fake_subprocess(
        job_definition_response=_job_definition_result(awslogs_group=None),
        get_log_events_response=_Result(stdout=json.dumps({"events": [
            {"message": "line one"}, {"message": "line two"},
        ]})))
    monkeypatch.setattr(legacy_batch, "subprocess",
                         type("S", (), {"run": staticmethod(fake_run)}))

    text = batch_logs(CFG, JOB_ID)
    assert text == "line one\nline two"


def test_batch_logs_success_with_no_events_says_so(monkeypatch):
    fake_run, _calls = _fake_subprocess(
        job_definition_response=_job_definition_result(awslogs_group=None),
        get_log_events_response=_Result(stdout=json.dumps({"events": []})))
    monkeypatch.setattr(legacy_batch, "subprocess",
                         type("S", (), {"run": staticmethod(fake_run)}))

    assert batch_logs(CFG, JOB_ID) == "(no CloudWatch log output yet)"


# ── resolve_log_group: robustness ──────────────────────────────────────────
def test_resolve_log_group_falls_back_when_describe_job_definitions_fails(monkeypatch):
    """A DescribeJobDefinitions failure (permissions, deregistered
    definition, transient AWS error) must never block log resolution --
    falls back to the AWS Batch default, same as an unset awslogs-group."""
    fake_run, _calls = _fake_subprocess(
        job_definition_response=_Result(returncode=1, stderr="boom"))
    monkeypatch.setattr(legacy_batch, "subprocess",
                         type("S", (), {"run": staticmethod(fake_run)}))

    assert resolve_log_group(CFG, _job()) == DEFAULT_LOG_GROUP


def test_resolve_log_group_falls_back_when_job_has_no_job_definition(monkeypatch):
    calls_seen = []
    monkeypatch.setattr(legacy_batch, "subprocess", type("S", (), {
        "run": staticmethod(lambda *a, **k: calls_seen.append(1) or _Result())}))
    assert resolve_log_group(CFG, _job(job_definition=None)) == DEFAULT_LOG_GROUP
    assert not calls_seen          # never even called DescribeJobDefinitions
