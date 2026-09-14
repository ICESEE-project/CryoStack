"""Password bootstrap on the connected desktop Connector.

The bootstrap must:
  * install the SAME B3 namespaced PUBLIC key that Check SSH later uses,
  * return a machine-readable ``reason`` for every failure boundary,
  * never echo the password back in its result,
  * only ever send the public key (private key stays on the workstation).
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import icesee_hpc_connector.connector_core as cc

_PACE = dict(host="login-phoenix-rh9.pace.gatech.edu", user="bkyanjo3",
            port=22, password="hunter2", cluster_name="pace")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def _run(payload):
    return asyncio.run(cc.bootstrap_passwordless_ssh_local(payload))


# ── the exact namespaced key ─────────────────────────────────────────
def test_bootstrap_installs_the_same_namespaced_key_check_ssh_uses(home, monkeypatch):
    priv_expected, pub_expected = cc.ensure_local_ssh_key(
        cluster_name="pace", hpc_user="bkyanjo3", host=_PACE["host"])
    assert Path(pub_expected).name == "id_ed25519_pace-a6505fbb04b5.pub"

    installed = {}

    class _Chan:
        def recv_exit_status(self): return 0

    class _Stream:
        def __init__(self, s=b""): self._s = s
        channel = _Chan()
        def read(self): return self._s

    class _Client:
        def set_missing_host_key_policy(self, *_a): pass
        def connect(self, **kw): installed["connected_as"] = kw["username"]
        def exec_command(self, cmd, timeout=None):
            installed["remote_cmd"] = cmd
            return None, _Stream(b"OK\n"), _Stream(b"")
        def close(self): pass

    fake_paramiko = types.SimpleNamespace(
        SSHClient=lambda: _Client(), AutoAddPolicy=object,
        AuthenticationException=type("A", (Exception,), {}),
        SSHException=type("S", (Exception,), {}),
    )
    monkeypatch.setitem(sys.modules, "paramiko", fake_paramiko)
    monkeypatch.setattr(cc.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, stdout="phoenix\nbkyanjo3\n", stderr=""))

    res = _run(dict(_PACE))
    assert res["reason"] == cc.BOOTSTRAP_OK and res["ok"] is True
    assert res["key_installed"] is True
    # the remote append command carried exactly our namespaced .pub contents
    pub_text = Path(pub_expected).read_text().strip()
    assert pub_text in installed["remote_cmd"]
    assert "authorized_keys" in installed["remote_cmd"]
    # never the legacy cluster-only key
    assert "id_ed25519_icesee_pace" not in installed["remote_cmd"]
    # the private key path is never put into the remote command
    assert str(priv_expected) not in installed["remote_cmd"]


# ── failure boundaries all produce a reason ──────────────────────────
def test_missing_paramiko_is_reported_not_silent(home, monkeypatch):
    monkeypatch.setitem(sys.modules, "paramiko", None)  # import paramiko -> ImportError
    res = _run(dict(_PACE))
    assert res["reason"] == cc.BOOTSTRAP_PARAMIKO_MISSING
    assert res["ok"] is False


def test_wrong_password_maps_to_password_auth_failed(home, monkeypatch):
    auth_exc = type("AuthenticationException", (Exception,), {})

    class _Client:
        def set_missing_host_key_policy(self, *_a): pass
        def connect(self, **kw): raise auth_exc("bad password")
        def close(self): pass

    monkeypatch.setitem(sys.modules, "paramiko", types.SimpleNamespace(
        SSHClient=lambda: _Client(), AutoAddPolicy=object,
        AuthenticationException=auth_exc, SSHException=type("S", (Exception,), {})))
    res = _run(dict(_PACE))
    assert res["reason"] == cc.BOOTSTRAP_PASSWORD_AUTH_FAILED


def test_unreachable_resource_maps_to_connect_failed(home, monkeypatch):
    class _Client:
        def set_missing_host_key_policy(self, *_a): pass
        def connect(self, **kw): raise OSError("timed out")
        def close(self): pass

    monkeypatch.setitem(sys.modules, "paramiko", types.SimpleNamespace(
        SSHClient=lambda: _Client(), AutoAddPolicy=object,
        AuthenticationException=type("A", (Exception,), {}),
        SSHException=type("S", (Exception,), {})))
    res = _run(dict(_PACE))
    assert res["reason"] == cc.BOOTSTRAP_CONNECT_FAILED


def test_missing_fields_do_not_crash_the_worker(home):
    res = _run({"host": "", "user": "", "password": ""})
    assert res["ok"] is False and res["reason"]


# ── password hygiene ────────────────────────────────────────────────
def test_result_never_contains_the_password(home, monkeypatch):
    class _Client:
        def set_missing_host_key_policy(self, *_a): pass
        def connect(self, **kw): raise type("AuthenticationException", (Exception,), {})("no")
        def close(self): pass

    monkeypatch.setitem(sys.modules, "paramiko", types.SimpleNamespace(
        SSHClient=lambda: _Client(), AutoAddPolicy=object,
        AuthenticationException=Exception, SSHException=Exception))
    res = _run(dict(_PACE, password="S3cr3t-do-not-leak"))
    assert "S3cr3t-do-not-leak" not in json.dumps(res)
    assert "S3cr3t-do-not-leak" not in repr(res)
