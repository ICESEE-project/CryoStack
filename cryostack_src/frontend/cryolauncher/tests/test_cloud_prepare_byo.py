"""C7.3 -- Prepare cloud routed through the connected AWS account.

UI-level: fake bridge + fake execution resolver. Proves BYO temp credentials
reach the bridge, the derived bucket is used, and a broken connection fails
closed without touching ambient credentials.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.connect import CloudDefaults
from cryostack_src.cloud.connect.execution import CloudAccessError, CloudExecution
from cryostack_src.frontend.cryolauncher.cloud_runtime import build_cloud_runtime_callbacks


class _Btn:
    def __init__(self, description="", icon="", button_style="", disabled=False):
        self.description = description
        self.icon = icon
        self.button_style = button_style
        self.disabled = disabled


class _HtmlW:
    def __init__(self):
        self.value = ""


class _Out:
    def __init__(self):
        self.text = ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def clear_output(self, *a, **k):
        self.text = ""

    def write(self, s):
        self.text += s


class _Layout:
    def __init__(self):
        self.display = "none"


class _SectionW:
    def __init__(self):
        self.layout = _Layout()


class _Env:
    def __init__(self):
        self.account_status = _HtmlW()
        self.storage_status = _HtmlW()
        self.registry_status = _HtmlW()
        self.compute_status = _HtmlW()
        self.test_button = _Btn("Test connection")
        self.prepare_button = _Btn("Prepare cloud")
        self.run_estimate_section = _SectionW()
        self.run_estimate_line = _HtmlW()


class _Caps:
    authenticated = True
    storage_ready = True
    registry_ready = True
    batch_ready = True
    messages = ["done"]


class _Bridge:
    last = {}

    def __init__(self, *, credentials=None, region=None, profile=None):
        _Bridge.last = {"credentials": credentials, "region": region, "profile": profile}
        self._credentials = credentials

    def check_environment(self):
        return _Caps()

    def prepare_environment(self, *, bucket=None):
        _Bridge.last["bucket"] = bucket
        _Bridge.last["credentials_at_prepare"] = self._credentials
        return {"success": True, "capabilities": _Caps(), "messages": ["prepared"]}


BYO_CREDS = {
    "AWS_ACCESS_KEY_ID": "ASIA_774888247882",
    "AWS_SECRET_ACCESS_KEY": "sekret",
    "AWS_SESSION_TOKEN": "tok",
}


def _byo_execution():
    return CloudExecution(
        mode="byo",
        region="us-east-2",
        credentials=dict(BYO_CREDS),
        profile=None,
        account_id="774888247882",
        defaults=CloudDefaults(
            account_id="774888247882", region="us-east-2",
            bucket="cryostack-runs-774888247882", job_queue="cryostack-queue",
            job_definition="cryostack-issm", ecr_repository="cryostack-issm",
        ),
    )


def _callbacks(resolver, *, spawn):
    env = _Env()
    return env, build_cloud_runtime_callbacks(
        runtime_status={},
        log_output=_Out(),
        status_widget=_HtmlW(),
        status_html=lambda s: s,
        bridge_factory=lambda **kw: _Bridge(**kw),
        cloud_environment=env,
        set_cloud_status=lambda w, *, state, label: setattr(w, "value", f"{state}:{label}"),
        bucket_value=lambda: "developer-bucket",
        results_output=_Out(),
        execution_resolver=resolver,
        smoke_button=_Btn("Smoke test"),
        set_chip=lambda _k: None,
        spawn=spawn,
        to_thread=_immediate,
    )


def _immediate(fn):
    async def _c():
        return fn()

    return _c()


class _Spawn:
    def __init__(self):
        self.q = []

    def __call__(self, coro):
        self.q.append(coro)

    def run(self):
        import asyncio

        while self.q:
            asyncio.run(self.q.pop(0))


def test_prepare_in_byo_mode_uses_temp_credentials_and_derived_bucket():
    spawn = _Spawn()
    env, cbs = _callbacks(_byo_execution, spawn=spawn)
    cbs.prepare_environment()
    spawn.run()
    assert _Bridge.last["credentials_at_prepare"] == BYO_CREDS
    assert _Bridge.last["region"] == "us-east-2"
    assert _Bridge.last["profile"] is None
    assert _Bridge.last["bucket"] == "cryostack-runs-774888247882"   # not developer-bucket
    assert "done" in env.storage_status.value.lower() or "ready" in env.storage_status.value.lower()


def test_prepare_in_developer_mode_keeps_the_advanced_bucket_and_no_credentials():
    spawn = _Spawn()
    env, cbs = _callbacks(
        lambda: CloudExecution(mode="developer", region="eu-west-1",
                               credentials=None, profile="cryo-dev"),
        spawn=spawn,
    )
    cbs.prepare_environment()
    spawn.run()
    assert _Bridge.last["credentials_at_prepare"] is None
    assert _Bridge.last["bucket"] == "developer-bucket"


def test_broken_byo_connection_fails_closed_without_calling_the_bridge():
    _Bridge.last = {}
    spawn = _Spawn()

    def _resolver():
        raise CloudAccessError("CryoStack could not access your AWS account: denied.")

    env, cbs = _callbacks(_resolver, spawn=spawn)
    cbs.prepare_environment()
    spawn.run()
    # the bridge was never constructed with fallback ambient credentials
    assert "credentials_at_prepare" not in _Bridge.last
    # the connection (account) is what failed; storage/containers/compute were
    # never attempted and must not read as an independent failure
    assert "fail" in env.account_status.value.lower()
    assert env.storage_status.value == "idle:Not prepared"
    assert env.compute_status.value == "idle:Not prepared"


def test_check_connection_also_routes_through_the_assumed_role():
    spawn = _Spawn()
    env, cbs = _callbacks(_byo_execution, spawn=spawn)
    cbs.check_environment()
    spawn.run()
    assert _Bridge.last["credentials"] == BYO_CREDS
    assert _Bridge.last["profile"] is None
