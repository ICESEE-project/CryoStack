"""C7.5 -- the BYO-AWS cloud run lifecycle through CloudRunController.

Offline: every AWS boundary is a fake. Proves each lifecycle operation
(stage/submit, poll, terminate, result sync) runs with a FRESH assumed-role
context for the reviewed account, never falls back to ambient/profile, and
that a broken connection or account mismatch fails closed.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.connect.execution import CloudAccessError, CloudExecution
from cryostack_src.frontend.cryolauncher.cloud_run_controller import (
    CANCELLED,
    COMPLETED,
    FAILED,
    RUNNING,
    CloudRunController,
)

BYO_A = {"AWS_ACCESS_KEY_ID": "ASIA_A", "AWS_SECRET_ACCESS_KEY": "s", "AWS_SESSION_TOKEN": "t"}


async def _immediate(fn):
    return fn()


async def _no_sleep(_s):
    return None


class _Status:
    def __init__(self, state):
        self.state = state
        self.raw_state = state.upper()
        self.reason = ""


class _SubmitResult:
    job_id = "job-A1"
    working_directory = None
    metadata = {"s3_run": "s3://cryostack-runs-713938953301/runs/u/x", "run_id": "x"}
    messages = ["submitted"]


class RecordingBridge:
    """bridge_factory(**kw) returns a fresh one per AWS op (mirrors a fresh
    AssumeRole). Poll state is SHARED at class level -- like real AWS job
    state, it does not reset when a new session is created."""

    instances: list = []
    poll_sequence: list = [RUNNING, RUNNING, COMPLETED]
    _poll_i: int = 0

    def __init__(self, *, credentials=None, region=None, profile=None):
        self.credentials = credentials
        self.region = region
        self.profile = profile
        RecordingBridge.instances.append(self)

    def submit(self, **kw):
        return _SubmitResult()

    def status(self, *, job_id):
        seq = RecordingBridge.poll_sequence
        state = seq[min(RecordingBridge._poll_i, len(seq) - 1)]
        RecordingBridge._poll_i += 1
        return _Status(state)

    def terminate(self, *, job_id):
        return {"ok": True}


@pytest.fixture(autouse=True)
def _reset():
    RecordingBridge.instances = []
    RecordingBridge.poll_sequence = [RUNNING, RUNNING, COMPLETED]
    RecordingBridge._poll_i = 0
    yield


def _byo_execution(account="713938953301", *, calls=None):
    def provider():
        if calls is not None:
            calls.append(1)
        return CloudExecution(mode="byo", region="us-east-2", credentials=dict(BYO_A),
                              profile=None, account_id=account)

    return provider


def _controller(*, execution_provider, **over):
    sink = {"states": [], "logs": [], "synced": [], "views": []}

    def _sync(**kw):
        sink["synced"].append(kw)
        return "/local/cloud_outputs"

    ctl = CloudRunController(
        bridge_factory=lambda **kw: RecordingBridge(**kw),
        register_run=lambda **kw: None,
        sync_results=_sync,
        on_state=sink["states"].append,
        on_log=sink["logs"].append,
        on_run_view=lambda **v: sink["views"].append(v),
        execution_provider=execution_provider,
        poll_interval=0.0,
        to_thread=_immediate,
        sleep=_no_sleep,
        **over,
    )
    return ctl, sink


# -- A. BYO launch -----------------------------------------------
def test_every_operation_uses_a_fresh_assume_role_and_the_temp_creds():
    calls = []
    ctl, sink = _controller(execution_provider=_byo_execution(calls=calls))
    ctl.submit(
        staged_source="/tmp/x", model="issm", run_target="runme.m",
        bucket="cryostack-runs-713938953301", _account_id="713938953301",
    )
    # submit + 3 polls + retrieve == 5 fresh resolves (one per AWS op)
    assert len(calls) >= 5
    # every bridge built carried the assumed-role creds, never a profile
    assert RecordingBridge.instances
    for b in RecordingBridge.instances:
        assert b.credentials == BYO_A
        assert b.profile is None
    assert sink["synced"][-1]["credentials"] == BYO_A
    assert sink["synced"][-1]["profile"] is None
    assert COMPLETED in sink["states"]


def test_reviewed_account_and_resources_ride_the_handle_to_the_view():
    ctl, sink = _controller(execution_provider=_byo_execution())
    ctl.submit(
        staged_source="/tmp/x", model="issm", run_target="runme.m",
        bucket="cryostack-runs-713938953301",
        _account_id="713938953301", _example="SquareIceShelf",
        _vcpu=2, _memory_gib=8, _expected_runtime_minutes=5,
        _cost_public={"available": True, "estimated_total_usd": 0.01,
                      "expected_runtime_minutes": 5},
    )
    v = sink["views"][-1]
    assert v["account_id"] == "713938953301" and v["example"] == "SquareIceShelf"
    assert v["vcpu"] == 2 and v["memory_gib"] == 8


# -- B. fail closed -------------------------------------------
def test_broken_byo_connection_fails_closed_no_ambient_fallback():
    def boom():
        raise CloudAccessError("Your AWS connection could not be refreshed.")

    ctl, sink = _controller(execution_provider=boom)
    ctl.submit(
        staged_source="/tmp/x", model="issm", run_target="runme.m",
        bucket="cryostack-runs-713938953301", _account_id="713938953301",
    )
    assert sink["states"][-1] == FAILED
    assert RecordingBridge.instances == []          # no bridge, no AWS call
    assert any("Re-check the connected AWS account" in m for m in sink["logs"])


def test_account_mismatch_blocks_submission_before_any_aws_call():
    # provider now resolves to account B, but the run was reviewed for A
    ctl, sink = _controller(execution_provider=_byo_execution("774888247882"))
    ctl.submit(
        staged_source="/tmp/x", model="issm", run_target="runme.m",
        bucket="cryostack-runs-713938953301", _account_id="713938953301",
    )
    assert sink["states"][-1] == FAILED
    assert RecordingBridge.instances == []
    assert any("account" in m.lower() and "mismatch" in m.lower()
               for m in sink["logs"])


# -- C. developer mode --------------------------------------
def test_developer_mode_has_no_execution_provider_and_uses_the_plain_bridge():
    plain = RecordingBridge(credentials=None, region=None, profile="cryo-dev")
    RecordingBridge.instances = []
    sink = {"states": [], "logs": []}
    ctl = CloudRunController(
        bridge_factory=lambda: plain,               # no kwargs -- classic path
        register_run=lambda **kw: None,
        sync_results=lambda **kw: "/local",
        on_state=sink["states"].append,
        on_log=sink["logs"].append,
        execution_provider=None,                    # developer mode
        poll_interval=0.0, to_thread=_immediate, sleep=_no_sleep,
    )
    ctl.submit(staged_source="/tmp/x", model="issm",
               run_target="runme.m", bucket="b", _profile="cryo-dev")
    assert COMPLETED in sink["states"]


# -- D. lifecycle + cancellation --------------------------
def test_lifecycle_states_progress_staging_to_completed():
    ctl, sink = _controller(execution_provider=_byo_execution())
    ctl.submit(staged_source="/tmp/x", model="issm",
               run_target="runme.m", bucket="b", _account_id="713938953301")
    seq = [s for s in sink["states"]]
    assert seq.index("staging") < seq.index("submitting") < seq.index("queued")
    assert seq[-1] == COMPLETED


def test_terminate_uses_a_fresh_context_for_the_same_account():
    ctl, sink = _controller(execution_provider=_byo_execution())
    ctl._handle.job_id = "job-A1"
    ctl._handle.account_id = "713938953301"
    asyncio.run(ctl._terminate_worker("job-A1"))
    assert ctl.state == CANCELLED
    assert RecordingBridge.instances[-1].credentials == BYO_A
    assert RecordingBridge.instances[-1].profile is None


# -- E. account-switch isolation: a selected run keeps its OWN account -----
def test_terminate_fails_closed_when_connected_account_diverges_from_the_run():
    """A run recorded under account A, terminated while the CryoStack user is
    now connected to account B (they used "Change AWS account"), must never
    reach AWS with B's credentials pretending to be A's job. It must fail
    closed and touch no bridge."""
    ctl, sink = _controller(execution_provider=_byo_execution("774888247882"))  # now on B
    ctl._handle.job_id = "job-A1"
    ctl._handle.account_id = "713938953301"                                     # run is A's
    asyncio.run(ctl._terminate_worker("job-A1"))
    assert ctl.state != CANCELLED               # never claims success
    assert RecordingBridge.instances == []       # no AWS call was made
    assert any("account" in m.lower() and "mismatch" in m.lower()
               for m in sink["logs"])


def test_poll_fails_closed_when_connected_account_diverges_from_the_run():
    ctl, sink = _controller(execution_provider=_byo_execution("774888247882"))  # now on B
    ctl._handle.job_id = "job-A1"
    ctl._handle.account_id = "713938953301"                                     # run is A's
    asyncio.run(ctl._poll_loop("job-A1"))
    assert COMPLETED not in sink["states"]
    assert RecordingBridge.instances == []       # the mismatch is caught before
                                                  # any AWS status call is made


def test_result_retrieval_fails_closed_when_connected_account_diverges():
    ctl, sink = _controller(execution_provider=_byo_execution("774888247882"))  # now on B
    ctl._handle.job_id = "job-A1"
    ctl._handle.s3_run = "s3://cryostack-runs-713938953301/runs/u/x"
    ctl._handle.account_id = "713938953301"                                     # run is A's
    asyncio.run(ctl._retrieve_results())
    assert sink["synced"] == []                  # never synced using B's creds
    assert any("account" in m.lower() and "mismatch" in m.lower()
               for m in sink["logs"])


def test_switching_accounts_does_not_disturb_an_unrelated_attached_run():
    """Attaching (selecting) a run for the account CURRENTLY connected still
    works normally after a "Change AWS account" -- the guard only blocks a
    genuine cross-account mismatch, never same-account use."""
    ctl, sink = _controller(execution_provider=_byo_execution("774888247882"))
    ctl.attach(job_id="job-B1", s3_run="s3://cryostack-runs-774888247882/runs/u/y",
               model="issm", region="us-east-2", account_id="774888247882",
               state=RUNNING)
    asyncio.run(ctl._terminate_worker("job-B1"))
    assert ctl.state == CANCELLED
    assert RecordingBridge.instances
