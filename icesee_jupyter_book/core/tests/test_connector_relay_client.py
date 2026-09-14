"""Gateway/kernel-side relay client: per-session control binding, fail-closed."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import icesee_jupyter_book.core.connector_relay_client as rc


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    rc.clear_binding()
    monkeypatch.delenv("CRYOSTACK_RELAY_CONTROL_TOKEN", raising=False)
    yield
    rc.clear_binding()


def test_create_session_sends_owner_and_binds(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json, headers=headers or {})
        return _Resp({
            "session_id": "sid-1", "control_secret": "ctl-1",
            "session_secret": "sec-1", "pairing_code": "AAAAA-BBBBB",
        })

    monkeypatch.setattr(rc.requests, "post", fake_post)
    data = rc.create_session("user-a")

    assert seen["url"].endswith("/connector/session")
    assert seen["json"] == {"owner_user_id": "user-a"}
    assert "Authorization" not in seen["headers"]           # no deployment token set
    assert data["session_id"] == "sid-1"
    assert rc.current_binding() == {
        "session_id": "sid-1", "control_secret": "ctl-1", "owner_user_id": "user-a"
    }


def test_create_session_attaches_deployment_token_when_present(monkeypatch):
    monkeypatch.setenv("CRYOSTACK_RELAY_CONTROL_TOKEN", "deploy-tok")
    seen = {}
    monkeypatch.setattr(rc.requests, "post", lambda url, json=None, headers=None, timeout=None: (
        seen.update(headers=headers), _Resp({
            "session_id": "s", "control_secret": "c", "session_secret": "x", "pairing_code": "p",
        }))[1])
    rc.create_session("user-a")
    assert seen["headers"]["Authorization"] == "Bearer deploy-tok"


def test_create_session_requires_authenticated_owner(monkeypatch):
    monkeypatch.setattr(rc.requests, "post", lambda *a, **k: pytest.fail("must not call relay"))
    with pytest.raises(rc.RelayAuthError):
        rc.create_session("")


def test_send_command_fails_closed_without_a_binding(monkeypatch):
    monkeypatch.setattr(rc.requests, "post", lambda *a, **k: pytest.fail("must not call relay"))
    with pytest.raises(rc.RelayAuthError):
        rc.send_command("sid-1", "shell", {"command": "id"})


def test_send_command_fails_closed_for_a_different_session(monkeypatch):
    rc.bind_session("sid-1", "ctl-1", "user-a")
    monkeypatch.setattr(rc.requests, "post", lambda *a, **k: pytest.fail("must not call relay"))
    with pytest.raises(rc.RelayAuthError):
        rc.send_command("sid-OTHER", "shell", {})


def test_send_command_uses_the_bound_control_secret_and_owner(monkeypatch):
    rc.bind_session("sid-1", "ctl-1", "user-a")
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json, headers=headers)
        return _Resp({"ok": True, "result": {"ok": True}})

    monkeypatch.setattr(rc.requests, "post", fake_post)
    rc.send_command("sid-1", "ssh-run", {"host": "h"})

    assert seen["url"].endswith("/connector/command/sid-1")
    assert seen["headers"]["Authorization"] == "Bearer ctl-1"
    assert seen["json"]["owner_user_id"] == "user-a"
    assert seen["json"]["command_type"] == "ssh-run"
    assert seen["json"]["payload"] == {"host": "h"}


def test_bind_session_rejects_incomplete_credentials():
    with pytest.raises(rc.RelayAuthError):
        rc.bind_session("sid", "", "user")
    with pytest.raises(rc.RelayAuthError):
        rc.bind_session("", "ctl", "user")
