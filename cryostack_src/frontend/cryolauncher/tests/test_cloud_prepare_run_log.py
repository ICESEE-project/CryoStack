"""Regression: a failed Prepare cloud must land a sanitized, actionable line
in the EXISTING Workspace Run Log (an ipywidgets.Output), and readiness rows
must reflect only what was actually attempted.

Root cause fixed here: `with output: print(...)` inside the detached asyncio
task that runs Prepare silently drops output (the Output widget's capture
binds to the kernel parent-header, which a resumed background task lacks). The
fix routes Run Log writes through `Output.append_stdout`, which appends
straight to the synced `outputs` traitlet.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import ipywidgets as W
import pytest

from cryostack_src.cloud.connect.execution import CloudAccessError, CloudExecution
from cryostack_src.frontend.cryolauncher.cloud_runtime import (
    _emit_log,
    _sanitize,
    build_cloud_runtime_callbacks,
)


def _log_text(out: W.Output) -> str:
    return "".join(
        o.get("text", "") for o in out.outputs if o.get("output_type") == "stream"
    )


# ---------------------------------------------------------------------------
# the emitter itself
# ---------------------------------------------------------------------------
def test_emit_log_writes_to_a_real_output_via_append_stdout():
    out = W.Output()
    _emit_log(out, "line one", "line two")
    assert _log_text(out) == "line one\nline two\n"


def test_emit_log_redacts_credential_material_and_external_id():
    out = W.Output()
    _emit_log(
        out,
        "token ASIAV3EXAMPLEKEY7Q leaked",
        "aws_session_token=FwoGZXIvYXdzEExampleTokenValue//abc",
        "x-amz-security-token: AAAAExampleHeaderValue",
        "external id cryostack:alice-abcdef123456:Zk9Q7Rm2example",
        "AKIAIOSFODNN7EXAMPLE in a message",
    )
    text = _log_text(out)
    for secret in ("ASIAV3EXAMPLEKEY7Q", "FwoGZXIvYXdzEE", "AAAAExampleHeaderValue",
                   "Zk9Q7Rm2example", "AKIAIOSFODNN7EXAMPLE"):
        assert secret not in text
    assert text.count("<redacted>") >= 5


def test_sanitize_leaves_ordinary_provisioning_messages_intact():
    assert _sanitize("Created IAM resources: cryostack-job-role") == (
        "Created IAM resources: cryostack-job-role"
    )
    assert _sanitize("An error occurred (AccessDenied) calling CreateBucket") == (
        "An error occurred (AccessDenied) calling CreateBucket"
    )


# ---------------------------------------------------------------------------
# the Prepare path, end to end, with a real Run Log widget
# ---------------------------------------------------------------------------
class _Caps:
    authenticated = True
    storage_ready = False
    registry_ready = False
    batch_ready = False
    network_ready = False
    iam_ready = False
    messages: list = []


def _env():
    e = type("E", (), {})()
    for name in ("account_status", "storage_status", "registry_status",
                 "compute_status"):
        setattr(e, name, W.HTML())
    for name in ("test_button", "prepare_button", "smoke_button"):
        setattr(e, name, W.Button())
    return e


def _rows_of(env):
    return {
        "account": env.account_status.value,
        "storage": env.storage_status.value,
        "registry": env.registry_status.value,
        "compute": env.compute_status.value,
    }


def _build(env, log, *, bridge_factory, execution_resolver):
    return build_cloud_runtime_callbacks(
        runtime_status={}, log_output=log, status_widget=W.HTML(),
        status_html=lambda s: s, bridge_factory=bridge_factory,
        cloud_environment=env, set_cloud_status=lambda w, *, state, label: setattr(
            w, "value", f"{state}:{label}"),
        bucket_value=lambda: "", results_output=W.Output(),
        execution_resolver=execution_resolver, smoke_button=env.smoke_button,
        set_chip=lambda _k: None, spawn=lambda coro: asyncio.run(coro),
        to_thread=_immediate,
    )


async def _immediate(fn):
    return fn()


BYO = CloudExecution(mode="byo", region="us-east-2", account_id="774888247882",
                     credentials={"AWS_ACCESS_KEY_ID": "ASIA_X",
                                  "AWS_SECRET_ACCESS_KEY": "s",
                                  "AWS_SESSION_TOKEN": "t"})


def test_connected_byo_prepare_raises_reason_appears_in_the_existing_run_log():
    env, log = _env(), W.Output()

    class _Bridge:
        def __init__(self, **kw):
            pass

        def prepare_environment(self, *, bucket=None):
            raise RuntimeError(
                "An error occurred (AccessDenied) when calling the CreateBucket "
                "operation: token ASIAV3EXAMPLEKEY7Q"
            )

    cb = _build(env, log, bridge_factory=lambda **kw: _Bridge(**kw),
                execution_resolver=lambda: BYO)
    cb.prepare_environment()

    text = _log_text(log)
    assert text, "the Run Log must not be empty on a Prepare failure"
    assert "Could not prepare the cloud environment" in text
    assert "AccessDenied" in text                     # useful raw detail kept
    assert "ASIAV3EXAMPLEKEY7Q" not in text           # credential material redacted
    # readiness: the connection is what we could establish; downstream was
    # never attempted -> neutral, not an independent failure
    rows = _rows_of(env)
    assert rows["account"] == "fail:Failed"
    assert rows["storage"] == "idle:Not prepared"
    assert rows["registry"] == "idle:Not prepared"
    assert rows["compute"] == "idle:Not prepared"


def test_connected_byo_prepare_partial_result_marks_only_the_failed_stage():
    env, log = _env(), W.Output()
    partial = {
        "success": False, "capabilities": _Caps(),
        "row_status": {"account": "connected", "storage": "failed",
                       "registry": "not_attempted", "compute": "not_attempted"},
        "messages": ["AWS account connected.",
                     "[cloud][ERROR] Could not prepare the cloud environment "
                     "(stage: storage). See the detail below and the AWS role's "
                     "permissions.",
                     "[cloud][detail] AccessDenied on s3:CreateBucket"],
    }

    class _Bridge:
        def __init__(self, **kw):
            pass

        def prepare_environment(self, *, bucket=None):
            return partial

    cb = _build(env, log, bridge_factory=lambda **kw: _Bridge(**kw),
                execution_resolver=lambda: BYO)
    cb.prepare_environment()

    rows = _rows_of(env)
    assert rows["account"] == "done:Connected"
    assert rows["storage"] == "fail:Failed"
    assert rows["registry"] == "idle:Not prepared"
    assert rows["compute"] == "idle:Not prepared"
    text = _log_text(log)
    assert "stage: storage" in text and "AccessDenied on s3:CreateBucket" in text


def test_broken_byo_connection_prepare_fails_closed_with_a_run_log_line():
    env, log = _env(), W.Output()
    built = {"n": 0}

    def _bridge(**kw):
        built["n"] += 1
        raise AssertionError("bridge must not be built when the connection is broken")

    def _resolver():
        raise CloudAccessError(
            "CryoStack could not access your AWS account: the CryoStack access "
            "role does not trust this principal."
        )

    cb = _build(env, log, bridge_factory=_bridge, execution_resolver=_resolver)
    cb.prepare_environment()

    assert built["n"] == 0                            # no AWS operation
    text = _log_text(log)
    assert "could not access your aws account" in text.lower()
    assert "re-check the connected aws account" in text.lower()
    assert _rows_of(env)["account"] == "fail:Failed"
    assert _rows_of(env)["compute"] == "idle:Not prepared"
