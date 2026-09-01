"""Performance pass: gateway construction defers expensive work.

* no ssh-add / ssh-agent subprocess during build (SSH Key Manager probe is lazy);
* no relay HTTP call during build or a resource switch (connector session is
  created lazily);
* run history lists runs at build but does not inspect a run;
* B1-B4 / security behaviour unchanged.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import ipywidgets as W

_ICESHEETS = _REPO / "icesee_jupyter_book/ui/icesheets_gateway.py"
_ICESEE = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"
_GATEWAYS = (_ICESHEETS, _ICESEE)


# ── source guards ─────────────────────────────────────────────────────
@pytest.mark.parametrize("path", _GATEWAYS)
def test_ssh_key_manager_probe_is_deferred(path):
    src = path.read_text()
    assert "defer_probe=True" in src


@pytest.mark.parametrize("path", _GATEWAYS)
def test_no_connector_session_observer_on_access_mode(path):
    src = path.read_text()
    assert "create_or_refresh_connector_session() if change" not in src


@pytest.mark.parametrize("path", _GATEWAYS)
def test_resource_name_field_commits_not_per_keystroke(path):
    src = path.read_text()
    assert "cluster_name_for_keys = W.Text(" in src
    head = src.split("cluster_name_for_keys = W.Text(", 1)[1][:200]
    assert "continuous_update=False" in head


def test_icesheets_history_panel_is_deferred():
    assert "defer_initial_load=True" in _ICESHEETS.read_text()


# ── functional: build spawns no ssh-add subprocess, makes no relay call ──
@pytest.mark.parametrize(
    "builder_name", ["build_icesheets_ui", "build_icesee_ui"],
)
def test_build_does_no_ssh_subprocess_or_relay_http(builder_name, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "perf-guard-user")
    monkeypatch.setenv("USER", "perf-guard-service")

    import matplotlib
    matplotlib.use("Agg")

    seen = {"ssh_add": 0, "http": 0}

    real_run = subprocess.run

    def watched_run(cmd, *a, **k):
        if isinstance(cmd, (list, tuple)) and cmd and "ssh-add" in str(cmd[0]):
            seen["ssh_add"] += 1
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", watched_run)

    import icesee_jupyter_book.core.connector_relay_client as rc

    def boom_get(*a, **k):
        seen["http"] += 1
        raise AssertionError("relay HTTP during gateway build")

    def boom_post(*a, **k):
        seen["http"] += 1
        raise AssertionError("relay HTTP during gateway build")

    monkeypatch.setattr(rc.requests, "get", boom_get)
    monkeypatch.setattr(rc.requests, "post", boom_post)

    if builder_name == "build_icesheets_ui":
        from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui as build
    else:
        from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui as build

    page = build()
    assert page is not None
    assert seen["ssh_add"] == 0
    assert seen["http"] == 0


# ── perf instrumentation is opt-in and silent by default ──────────────
def test_perf_span_is_noop_without_the_env(monkeypatch, capsys):
    monkeypatch.delenv("CRYOSTACK_PERF", raising=False)
    from cryostack_src import perf
    with perf.span("something"):
        pass
    perf.mark("other", 1.23)
    assert capsys.readouterr().err == ""


def test_perf_span_emits_when_enabled(monkeypatch, capsys):
    monkeypatch.setenv("CRYOSTACK_PERF", "1")
    from cryostack_src import perf
    with perf.span("a-labelled-block"):
        pass
    err = capsys.readouterr().err
    assert "[perf]" in err and "a-labelled-block" in err
