"""End-to-end (offline) proof that the password-bootstrap workflow the operator
relied on still completes on the B3 namespaced credential.

Chain under test:
    gateway bootstrap_passwordless_ssh(access_mode="connector")
      -> relay command envelope (simulated)
      -> connector bootstrap_passwordless_ssh_local(payload)
      -> local namespaced key  +  one-time password auth (mocked)
      -> append the PUBLIC key to authorized_keys
      -> the SAME key that a Check-SSH `run_ssh` would use with -i

Everything that would touch PACE or Duo is mocked. No network, no credentials.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import icesee_hpc_connector.connector_core as cc
from icesee_jupyter_book.core import remote_runner
import icesee_jupyter_book.core.connector_relay_client as relay_client

_IDENT = dict(host="login-phoenix-rh9.pace.gatech.edu", user="testuser",
             port=22, cluster_name="pace")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def _mock_paramiko(monkeypatch, capture):
    class _Chan:
        def recv_exit_status(self): return 0

    class _S:
        channel = _Chan()
        def __init__(self, b=b""): self._b = b
        def read(self): return self._b

    class _Client:
        def set_missing_host_key_policy(self, *_a): pass
        def connect(self, **kw):
            capture["auth_user"] = kw["username"]
            capture["auth_password"] = kw["password"]
        def exec_command(self, cmd, timeout=None):
            capture["remote_append_cmd"] = cmd
            return None, _S(b"OK\n"), _S(b"")
        def close(self): pass

    monkeypatch.setitem(sys.modules, "paramiko", types.SimpleNamespace(
        SSHClient=lambda: _Client(), AutoAddPolicy=object,
        AuthenticationException=type("A", (Exception,), {}),
        SSHException=type("S", (Exception,), {})))


def test_bootstrap_completes_and_installs_the_check_ssh_key(home, monkeypatch):
    capture: dict = {}
    _mock_paramiko(monkeypatch, capture)
    # let the real (offline) ssh-keygen run; only fake the verify `ssh -i` call
    _real_run = cc.subprocess.run

    def _run(cmd, *a, **k):
        if list(cmd[:1]) == ["ssh"]:
            return types.SimpleNamespace(returncode=0, stdout="phoenix\ntestuser\n", stderr="")
        return _real_run(cmd, *a, **k)

    monkeypatch.setattr(cc.subprocess, "run", _run)

    # ---- simulate the relay: gateway send_command -> connector handler ----
    def fake_send_command(session_id, command_type, payload, *, timeout=120):
        assert command_type == "bootstrap-passwordless-ssh"
        result = asyncio.run(cc.bootstrap_passwordless_ssh_local(payload))
        return {"ok": True, "command_id": "x", "result": result}

    monkeypatch.setattr(relay_client, "send_command", fake_send_command)

    result = remote_runner.bootstrap_passwordless_ssh(
        access_mode="connector", session_id="sess-1", password="one-time-pw",
        **_IDENT,
    )

    assert result["ok"] is True
    assert result["reason"] == cc.BOOTSTRAP_OK
    assert result["key_installed"] is True

    # the password reached paramiko unmodified; nothing stripped it
    assert capture["auth_password"] == "one-time-pw"
    assert capture["auth_user"] == "testuser"

    # the key appended to PACE is exactly the key Check-SSH's run_ssh would use
    _priv, pub = cc.ensure_local_ssh_key(
        cluster_name="pace", hpc_user="testuser", host=_IDENT["host"])
    pub_text = Path(pub).read_text().strip()
    assert pub_text in capture["remote_append_cmd"]
    assert "authorized_keys" in capture["remote_append_cmd"]

    check_ssh_payload = {**_IDENT, "command": "whoami", "timeout": 30}
    assert cc.ssh_identity_args(check_ssh_payload) == ["-i", _priv]
    assert "/.ssh/cryostack/id_ed25519_pace-" in _priv       # B3 namespaced dir
    assert "id_ed25519_icesee_pace" not in _priv             # never the legacy key

    # only the PUBLIC key crosses the wire -- private key material never does
    priv_material = Path(_priv).read_text()
    assert "PRIVATE KEY" in priv_material                       # sanity: it is a real key
    assert priv_material not in capture["remote_append_cmd"]
    assert priv_material not in json.dumps(result)


def test_gateway_connector_branch_sends_the_namespace_inputs(monkeypatch):
    seen: dict = {}

    def fake_send_command(session_id, command_type, payload, *, timeout=120):
        seen["payload"] = payload
        seen["http_timeout"] = timeout
        return {"result": {"ok": False, "reason": cc.BOOTSTRAP_PASSWORD_AUTH_FAILED}}

    monkeypatch.setattr(relay_client, "send_command", fake_send_command)
    out = remote_runner.bootstrap_passwordless_ssh(
        access_mode="connector", session_id="s", password="pw", **_IDENT)

    p = seen["payload"]
    assert p["host"] == _IDENT["host"] and p["user"] == _IDENT["user"]
    assert p["cluster_name"] == "pace"
    assert p.get("hpc_user") == _IDENT["user"]   # B3 namespace input, explicit
    assert p["password"] == "pw"
    # the relay HTTP read timeout is longer than the connector-side op budget
    assert seen["http_timeout"] > p["timeout"]
    assert out["reason"] == cc.BOOTSTRAP_PASSWORD_AUTH_FAILED
