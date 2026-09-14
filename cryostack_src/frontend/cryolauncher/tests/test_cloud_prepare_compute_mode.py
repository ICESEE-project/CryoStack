# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher Cloud Runtime -- Prepare cloud compute mode
# File        : test_cloud_prepare_compute_mode.py
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""Prepare cloud must consume the FINAL selected compute configuration --
whatever the Cloud Environment widgets hold at the moment the user clicks
Prepare, not a stale snapshot. This is a workflow-ordering guarantee (the
live EC2 validation's Issue 1): the widgets are read live in
``_prepare_worker`` at click time.

All AWS CLI / Batch calls are mocked -- no real AWS resources are touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.frontend.cryolauncher.cloud_runtime import build_cloud_runtime_callbacks


class _Btn:
    def __init__(self, description="", icon="", button_style=""):
        self.description = description
        self.icon = icon
        self.button_style = button_style
        self.disabled = False


class _HtmlW:
    def __init__(self, value=""):
        self.value = value


class _Layout:
    def __init__(self):
        self.display = "none"


class _SectionW:
    def __init__(self):
        self.layout = _Layout()


class _Val:
    """A minimal ipywidgets-shaped stand-in exposing only ``.value``."""

    def __init__(self, value):
        self.value = value


class _Out:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def clear_output(self, *a, **k):
        pass

    def write(self, s):
        pass


class _Env:
    """A Cloud Environment stand-in carrying the compute-mode widgets
    ``_ec2_config_from_widgets``/``_prepare_worker`` actually read."""

    def __init__(self, *, compute_mode="fargate", capacity="on_demand",
                 accelerator="none", network="default", topology="single_node"):
        self.account_status = _HtmlW()
        self.storage_status = _HtmlW()
        self.registry_status = _HtmlW()
        self.compute_status = _HtmlW()
        self.test_button = _Btn("Test connection")
        self.prepare_button = _Btn("Prepare cloud")
        self.run_estimate_section = _SectionW()
        self.run_estimate_line = _HtmlW()

        self.compute_mode = _Val(compute_mode)
        self.ec2_capacity = _Val(capacity)
        self.ec2_accelerator = _Val(accelerator)
        self.ec2_network = _Val(network)
        self.ec2_topology = _Val(topology)
        self.ec2_max_vcpus = _Val(0)
        self.ec2_instance_types = _Val("")
        self.ec2_vpc_id = _Val("")
        self.ec2_subnet_ids = _Val("")
        self.ec2_security_group_ids = _Val("")
        self.ec2_node_count = _Val(2)


class _Caps:
    authenticated = True
    storage_ready = True
    registry_ready = True
    batch_ready = True
    messages = ["done"]


class _Bridge:
    last: dict = {}

    def __init__(self, *, credentials=None, region=None, profile=None):
        self._credentials = credentials

    def check_environment(self):
        return _Caps()

    def prepare_environment(self, *, bucket=None, compute_mode=None,
                             ec2_config=None, matlab_secret_arn=None):
        _Bridge.last = {
            "bucket": bucket,
            "compute_mode": compute_mode,
            "ec2_config": ec2_config,
        }
        return {"success": True, "capabilities": _Caps(), "messages": ["prepared"]}


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


def _prepare(env):
    spawn = _Spawn()
    cbs = build_cloud_runtime_callbacks(
        runtime_status={},
        log_output=_Out(),
        status_widget=_HtmlW(),
        status_html=lambda s: s,
        bridge_factory=lambda **kw: _Bridge(**kw),
        cloud_environment=env,
        set_cloud_status=lambda w, *, state, label: setattr(w, "value", f"{state}:{label}"),
        bucket_value=lambda: "developer-bucket",
        results_output=_Out(),
        smoke_button=_Btn("Smoke test"),
        set_chip=lambda _k: None,
        spawn=spawn,
        to_thread=_immediate,
    )
    cbs.prepare_environment()
    spawn.run()
    return _Bridge.last


def test_fargate_prepare_cloud_omits_ec2_kwargs():
    env = _Env(compute_mode="fargate")
    last = _prepare(env)
    assert "compute_mode" not in last or last["compute_mode"] is None
    assert last["ec2_config"] is None


def test_ec2_on_demand_prepare_cloud_passes_the_on_demand_config():
    env = _Env(compute_mode="ec2", capacity="on_demand")
    last = _prepare(env)
    assert last["compute_mode"] == "ec2"
    assert last["ec2_config"].capacity == "on_demand"
    assert last["ec2_config"].is_spot is False


def test_ec2_spot_prepare_cloud_passes_the_spot_config():
    env = _Env(compute_mode="ec2", capacity="spot")
    last = _prepare(env)
    assert last["compute_mode"] == "ec2"
    assert last["ec2_config"].capacity == "spot"
    assert last["ec2_config"].is_spot is True


def test_prepare_cloud_reads_widget_values_live_not_a_stale_snapshot():
    """The user switches Fargate -> EC2 Spot AFTER the callbacks object
    exists (e.g. between two Prepare clicks) -- the very next Prepare must
    reflect the widget's current value, never the value at wiring time."""
    env = _Env(compute_mode="fargate")
    spawn = _Spawn()
    cbs = build_cloud_runtime_callbacks(
        runtime_status={},
        log_output=_Out(),
        status_widget=_HtmlW(),
        status_html=lambda s: s,
        bridge_factory=lambda **kw: _Bridge(**kw),
        cloud_environment=env,
        set_cloud_status=lambda w, *, state, label: setattr(w, "value", f"{state}:{label}"),
        bucket_value=lambda: "developer-bucket",
        results_output=_Out(),
        smoke_button=_Btn("Smoke test"),
        set_chip=lambda _k: None,
        spawn=spawn,
        to_thread=_immediate,
    )

    cbs.prepare_environment()
    spawn.run()
    assert _Bridge.last["compute_mode"] is None          # Fargate: no kwarg

    env.compute_mode.value = "ec2"
    env.ec2_capacity.value = "spot"
    cbs.prepare_environment()
    spawn.run()
    assert _Bridge.last["compute_mode"] == "ec2"
    assert _Bridge.last["ec2_config"].capacity == "spot"
