"""Pre-release HPC-access polish: the connector `ssh-run` payloads carry
`cluster_name`, so the connector selects the same B3 namespaced key that the
bootstrap flow registered (instead of falling back to its "pace" default)."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import cryostack_src.remote.bridge as bridge_mod
from cryostack_src.remote.bridge import RemoteBridge


def _capture(monkeypatch):
    seen = []

    def fake_send_command(session_id, command_type, payload):
        seen.append((command_type, payload))
        return {"result": {"ok": True, "returncode": 0, "stdout": "h\nalice\n/p\n", "stderr": ""}}

    monkeypatch.setattr(bridge_mod, "send_command", fake_send_command)
    return seen


def _bridge():
    return RemoteBridge(mode="connector", host="login.example.edu", user="alice",
                        port=22, session_id="sess-1", cluster_name="ub-ccr")


def test_connector_check_sends_cluster_name(monkeypatch):
    seen = _capture(monkeypatch)
    _bridge().check_environment()
    assert seen and seen[0][0] == "ssh-run"
    assert seen[0][1]["cluster_name"] == "ub-ccr"


def test_connector_logs_and_status_send_cluster_name(monkeypatch):
    seen = _capture(monkeypatch)
    b = _bridge()
    b.logs(job_id="123", remote_dir="/scratch/alice")
    b.status(job_id="123")
    assert all(p["cluster_name"] == "ub-ccr" for _t, p in seen)
