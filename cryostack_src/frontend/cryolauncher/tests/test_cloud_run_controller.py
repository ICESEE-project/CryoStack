"""Offline tests for the C6 cloud run controller.

No AWS, no ipywidgets, no real event loop wait -- ``to_thread`` and ``sleep``
are injected as immediate coroutines and the whole lifecycle is driven with
``asyncio.run(controller.run_once(...))``.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.frontend.cryolauncher.cloud_run_controller import (
    CANCELLED,
    CLOUD_STATES,
    COMPLETED,
    FAILED,
    QUEUED,
    RUNNING,
    STAGING,
    SUBMITTING,
    CloudRunController,
    classify_cloud_failure,
    cloud_run_plan_summary,
    is_terminal,
    normalize_aws_state,
    resolve_job_definition,
    user_run_prefix,
)

_ALLOW = {"issm": "cryostack-issm", "icepack": "cryostack-icepack"}


# ── immediate async shims ────────────────────────────────────────────────
async def _immediate(fn):
    return fn()


async def _no_sleep(_seconds):
    return None


class _Status:
    def __init__(self, state: str, *, raw: str = "", reason: str = "") -> None:
        self.state = state
        self.raw_state = raw or state.upper()
        self.reason = reason


class _SubmitResult:
    def __init__(self, job_id="job-42", s3_run="s3://b/runs/u/x", run_id="x") -> None:
        self.job_id = job_id
        self.working_directory = None
        self.metadata = {"s3_run": s3_run, "run_id": run_id}
        self.messages = [f"submitted AWS Batch job {job_id}"]


class FakeBridge:
    """One stable instance -- the controller's bridge_factory returns *this*."""

    def __init__(self, *, states=None, submit_error=None, status_error_once=False,
                 terminate_error=None) -> None:
        self._states = list(states or [QUEUED, RUNNING, COMPLETED])
        self._i = 0
        self.submit_error = submit_error
        self._status_error_once = status_error_once
        self.terminate_error = terminate_error
        self.submitted = 0
        self.terminated = []

    def submit(self, **kw):
        self.submitted += 1
        if self.submit_error:
            raise self.submit_error
        return _SubmitResult()

    def status(self, *, job_id):
        if self._status_error_once:
            self._status_error_once = False
            raise RuntimeError("transient describe-jobs throttling")
        state = self._states[min(self._i, len(self._states) - 1)]
        self._i += 1
        return _Status(state, reason="Essential container in task exited"
                       if state == FAILED else "")

    def terminate(self, *, job_id):
        if self.terminate_error:
            raise self.terminate_error
        self.terminated.append(job_id)
        return {"ok": True}


def _controller(bridge, **over):
    sink = {"states": [], "logs": [], "registered": [], "results_ready": 0,
            "synced": []}

    def _sync(**kw):
        sink["synced"].append(kw)
        return "/local/cache/cloud_outputs"

    ctl = CloudRunController(
        bridge_factory=lambda: bridge,
        register_run=lambda **kw: sink["registered"].append(kw),
        sync_results=_sync,
        on_state=sink["states"].append,
        on_log=sink["logs"].append,
        on_results_ready=lambda: sink.__setitem__("results_ready",
                                                  sink["results_ready"] + 1),
        poll_interval=0.0,
        to_thread=_immediate,
        sleep=_no_sleep,
        **over,
    )
    return ctl, sink


def _run(coro):
    return asyncio.run(coro)


# ── pure helpers ─────────────────────────────────────────────────────────
def test_states_and_terminal():
    assert {STAGING, SUBMITTING, QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED} <= set(CLOUD_STATES)
    assert is_terminal(COMPLETED) and is_terminal(FAILED) and is_terminal(CANCELLED)
    assert not is_terminal(RUNNING) and not is_terminal(QUEUED)


@pytest.mark.parametrize(("raw", "want"), [
    ("SUBMITTED", QUEUED), ("PENDING", QUEUED), ("RUNNABLE", QUEUED),
    ("STARTING", RUNNING), ("RUNNING", RUNNING),
    ("SUCCEEDED", COMPLETED), ("FAILED", FAILED), ("weird", QUEUED),
])
def test_normalize_aws_state(raw, want):
    assert normalize_aws_state(raw) == want


@pytest.mark.parametrize(("msg", "needle"), [
    ("Unable to locate credentials", "credentials are not configured"),
    ("The config profile (x) could not be found", "profile does not exist"),
    ("An error occurred (NoSuchBucket)", "S3 bucket is missing"),
    ("AccessDenied when calling PutObject", "Access denied"),
    ("RepositoryNotFoundException", "image is not in ECR"),
    ("Job queue cryostack-queue does not exist", "job queue does not exist"),
    ("job definition cryostack-issm does not exist", "job definition does not exist"),
    ("MATLAB licensing is not configured", "MATLAB license"),
    ("aws batch submit-job failed", "AWS Batch rejected"),
    ("cloud results sync failed", "outputs could not be retrieved"),
    ("Essential container in task exited", "failed. Open the log"),
    ("the job timed out", "time limit"),
    ("totally novel error", "See the log"),
])
def test_classify_cloud_failure(msg, needle):
    short, detail = classify_cloud_failure(RuntimeError(msg))
    assert needle.lower() in short.lower()
    assert detail == msg


def test_classify_cloud_failure_redacts_a_matlab_license_value_in_the_detail():
    # a raw MATLAB / FlexNet error must not echo the license endpoint into
    # the "[cloud][detail]" Run Log line (dummy values only)
    short, detail = classify_cloud_failure(RuntimeError(
        "License checkout failed. License path: "
        "27000@test-license.invalid:/opt/matlab/R2024b/licenses"))
    assert "27000@test-license.invalid" not in detail
    assert "<redacted>" in detail
    assert "/opt/matlab/R2024b/licenses" in detail          # non-secret path kept

    short, detail = classify_cloud_failure(RuntimeError(
        "container env MLM_LICENSE_FILE=27000@test-license.invalid rejected"))
    assert "27000@test-license.invalid" not in detail
    assert "MLM_LICENSE_FILE=<redacted>" in detail          # key kept, value gone


def test_classify_cloud_failure_leaves_ordinary_host_port_text_alone():
    for msg in ("could not connect to https://batch.us-east-2.amazonaws.com:443",
                "endpoint example.com:8080 refused the connection",
                "Job queue cryostack-queue does not exist"):
        _short, detail = classify_cloud_failure(RuntimeError(msg))
        assert detail == msg
        assert "<redacted>" not in detail


def test_plan_summary_has_charge_warning_and_no_dollar_figure():
    s = cloud_run_plan_summary(model="issm", region="us-east-2", bucket="b",
                               job_queue="cryostack-queue",
                               job_definition="cryostack-issm")
    assert "may incur charges" in s
    assert "$" not in s
    assert "cryostack-issm" in s and "us-east-2" in s


# -- Fargate/EC2 labeling ---------------------------------------------------
def test_plan_summary_defaults_to_fargate_wording():
    s = cloud_run_plan_summary(model="issm", region="us-east-2", bucket="b",
                               job_queue="cryostack-queue",
                               job_definition="cryostack-issm")
    assert "This submits an AWS Batch (Fargate) job." in s
    assert "AWS Batch (EC2)" not in s


def test_plan_summary_names_ec2_when_that_is_the_resolved_compute_mode():
    s = cloud_run_plan_summary(model="issm", region="us-east-2", bucket="b",
                               job_queue="cryostack-ec2-queue",
                               job_definition="cryostack-issm-ec2",
                               compute_mode="ec2")
    assert "This submits an AWS Batch (EC2) job." in s
    assert "AWS Batch (Fargate)" not in s


def test_resolve_job_definition_is_controlled():
    assert resolve_job_definition("issm", "", allow_list=_ALLOW) == ("cryostack-issm", [])
    assert resolve_job_definition("issm", "cryostack-issm:9", allow_list=_ALLOW) == ("cryostack-issm:9", [])
    jd, warn = resolve_job_definition("issm", "arbitrary-thing", allow_list=_ALLOW)
    assert jd == "cryostack-issm" and warn and "Ignoring" in warn[0]
    jd, warn = resolve_job_definition("issm", "cryostack-icepack", allow_list=_ALLOW)
    assert jd == "cryostack-icepack" and not warn        # a known name, still allowed


# ── compute-mode aware default -- the live Review & Launch/submit bug ────
# Before this fix, resolve_job_definition() always returned the Fargate name
# (allow_list is Fargate-only) regardless of the selected compute mode, so a
# blank job-definition field silently submitted to Fargate even with EC2
# selected -- and a manually-typed EC2 override was REJECTED as "not a
# CryoStack job definition" because allow_list.values() never contained an
# EC2 name.
def test_resolve_job_definition_defaults_to_fargate_when_compute_mode_is_unspecified():
    # backward compatible: identical to the pre-EC2 behaviour
    assert resolve_job_definition(
        "icepack", "", allow_list=_ALLOW) == ("cryostack-icepack", [])
    assert resolve_job_definition(
        "icepack", "", allow_list=_ALLOW, compute_mode="fargate"
    ) == ("cryostack-icepack", [])


def test_resolve_job_definition_ec2_default_is_never_the_fargate_name():
    jd, warn = resolve_job_definition(
        "icepack", "", allow_list=_ALLOW, compute_mode="ec2")
    assert jd == "cryostack-icepack-ec2" and not warn
    assert jd != "cryostack-icepack"           # the exact regression this guards


def test_resolve_job_definition_ec2_gpu_and_multinode_suffixes():
    from cryostack_src.cloud.drivers.aws.batch_config import EC2ComputeConfig

    jd, _ = resolve_job_definition(
        "issm", "", allow_list=_ALLOW, compute_mode="ec2",
        ec2=EC2ComputeConfig(accelerator="gpu"))
    assert jd == "cryostack-issm-ec2-gpu"

    jd, _ = resolve_job_definition(
        "issm", "", allow_list=_ALLOW, compute_mode="ec2",
        ec2=EC2ComputeConfig(topology="multi_node"))
    assert jd == "cryostack-issm-ec2-mnp"


def test_resolve_job_definition_accepts_a_manually_typed_ec2_override():
    # an EC2 name is a known CryoStack job definition even while the current
    # selection's own default would be Fargate -- never silently rejected
    jd, warn = resolve_job_definition(
        "icepack", "cryostack-icepack-ec2", allow_list=_ALLOW, compute_mode="fargate")
    assert jd == "cryostack-icepack-ec2" and not warn
    jd, warn = resolve_job_definition(
        "icepack", "cryostack-icepack-ec2:3", allow_list=_ALLOW, compute_mode="ec2")
    assert jd == "cryostack-icepack-ec2:3" and not warn


def test_user_run_prefix_is_one_safe_segment():
    assert user_run_prefix("alice-abc123def456").rstrip("/") == "alice-abc123def456"
    p = user_run_prefix("weird id/../with spaces!@#")
    assert p.endswith("/") and p.count("/") == 1
    assert all(c.isalnum() or c in "._-/" for c in p)
    assert user_run_prefix("") == "user/"


# ── lifecycle ────────────────────────────────────────────────────────────
def test_happy_path_submit_poll_retrieve():
    b = FakeBridge(states=[QUEUED, RUNNING, COMPLETED])
    ctl, sink = _controller(b)
    _run(ctl.run_once(staged_source="/x", model="issm", run_target="runme.m", bucket="b"))
    assert ctl.state == COMPLETED
    assert ctl.job_id == "job-42"
    assert sink["registered"] and sink["synced"] and sink["results_ready"] == 1
    # states progressed through the machine
    for s in (STAGING, SUBMITTING, QUEUED, RUNNING, COMPLETED):
        assert s in sink["states"]


def test_failed_job_stops_and_does_not_retrieve():
    b = FakeBridge(states=[QUEUED, RUNNING, FAILED])
    ctl, sink = _controller(b)
    _run(ctl.run_once(staged_source="/x", model="issm", run_target="runme.m", bucket="b"))
    assert ctl.state == FAILED
    assert not sink["synced"] and sink["results_ready"] == 0
    assert any("failed" in m.lower() for m in sink["logs"])


def test_submit_error_is_classified_and_state_failed():
    b = FakeBridge(submit_error=RuntimeError("Unable to locate credentials"))
    ctl, sink = _controller(b)
    _run(ctl.run_once(staged_source="/x", model="issm", run_target="runme.m", bucket="b"))
    assert ctl.state == FAILED
    assert any("credentials are not configured" in m for m in sink["logs"])
    assert not sink["registered"]


def test_transient_status_error_keeps_polling():
    b = FakeBridge(states=[RUNNING, COMPLETED], status_error_once=True)
    ctl, sink = _controller(b)
    _run(ctl.run_once(staged_source="/x", model="issm", run_target="runme.m", bucket="b"))
    assert ctl.state == COMPLETED
    assert any("retrying" in m for m in sink["logs"])


def test_completed_but_sync_fails_stays_completed():
    b = FakeBridge(states=[COMPLETED])
    ctl, sink = _controller(b)

    def _boom(**kw):
        raise RuntimeError("cloud results sync failed")

    ctl._sync_results = _boom
    _run(ctl.run_once(staged_source="/x", model="issm", run_target="runme.m", bucket="b"))
    assert ctl.state == COMPLETED                     # the job DID finish
    assert any("could not be retrieved" in m for m in sink["logs"])
    assert sink["results_ready"] == 0


def test_terminate_sets_cancelled():
    b = FakeBridge(states=[QUEUED, QUEUED, QUEUED])
    ctl, sink = _controller(b)
    ctl._handle.job_id = "job-42"
    _run(ctl._terminate_worker("job-42"))
    assert ctl.state == CANCELLED and b.terminated == ["job-42"]


def test_attach_resumes_polling_for_a_live_job():
    b = FakeBridge(states=[RUNNING, COMPLETED])
    ctl, sink = _controller(b)
    # attach() calls start_polling -> _spawn -> asyncio.run (no running loop)
    ctl.attach(job_id="job-9", s3_run="s3://b/runs/u/x", model="issm",
               region="us-east-2", state=QUEUED)
    assert ctl.state == COMPLETED and sink["synced"]


def test_duplicate_submit_is_rejected_while_running():
    # a controller whose task is a never-finishing sentinel
    b = FakeBridge(states=[QUEUED])
    ctl, sink = _controller(b)

    class _Pending:
        def done(self):
            return False

    ctl._task = _Pending()
    ctl.submit(staged_source="/x", model="issm", run_target="runme.m", bucket="b")
    assert b.submitted == 0
    assert any("already in progress" in m for m in sink["logs"])
