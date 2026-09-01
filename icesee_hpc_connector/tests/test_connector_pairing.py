"""Connector desktop client: pair with a one-time code, no global discovery."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import icesee_hpc_connector.connector_core as cc


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def test_resolve_ws_url_has_no_global_discovery():
    assert cc.resolve_ws_url("https://relay.example", session=None) is None
    assert cc.resolve_ws_url("https://relay.example", session="sid-1") == (
        "wss://relay.example/connector/ws/sid-1"
    )


def test_pair_session_exchanges_code_for_secret(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        assert url.endswith("/connector/pair")
        assert json == {"pairing_code": "ABCDE-FGHIJ"}
        return _Resp({"ok": True, "session_id": "sid-1", "session_secret": "sec-1",
                      "ws_url": "/connector/ws/sid-1"})

    monkeypatch.setattr(cc.requests, "post", fake_post)
    out = cc.pair_session("https://relay.example", "ABCDE-FGHIJ")
    assert out["session_id"] == "sid-1"
    assert out["session_secret"] == "sec-1"


def test_pair_session_returns_none_on_rejection(monkeypatch):
    monkeypatch.setattr(cc.requests, "post", lambda *a, **k: _Resp({"detail": "bad"}, status=403))
    assert cc.pair_session("https://relay.example", "WRONG") is None
    monkeypatch.setattr(cc.requests, "post", lambda *a, **k: _Resp({"ok": False}))
    assert cc.pair_session("https://relay.example", "WRONG") is None
    assert cc.pair_session("https://relay.example", "") is None


def test_run_connector_without_a_code_or_secret_does_not_touch_the_network(monkeypatch, capsys):
    monkeypatch.setattr(cc.requests, "post", lambda *a, **k: pytest.fail("no pairing -> no relay call"))
    monkeypatch.setattr(cc.requests, "get", lambda *a, **k: pytest.fail("no global discovery"))
    monkeypatch.setattr(cc.asyncio, "run", lambda *a, **k: pytest.fail("must not open a websocket"))

    cc.run_connector(relay="https://relay.example", pairing_code=None, poll=True)

    out = capsys.readouterr().out
    assert "No pairing code" in out


def test_run_connector_bad_code_stops_without_connecting(monkeypatch, capsys):
    monkeypatch.setattr(cc, "pair_session", lambda relay, code: None)
    monkeypatch.setattr(cc.asyncio, "run", lambda *a, **k: pytest.fail("must not open a websocket"))
    cc.run_connector(relay="https://relay.example", pairing_code="NOPE", poll=True)
    assert "Pairing failed" in capsys.readouterr().out


def test_connector_core_has_no_latest_endpoint_reference():
    src = Path(cc.__file__).read_text()
    assert "/connector/latest" not in src
    assert "watch_for_newer_session" not in src


def test_terminal_close_codes_stop_the_reconnect_loop(monkeypatch):
    calls = {"n": 0}

    def fake_run(coro=None, *_a, **_k):
        if hasattr(coro, "close"):
            coro.close()
        calls["n"] += 1
        err = RuntimeError("closed")
        err.code = 4401
        raise err

    monkeypatch.setattr(cc.asyncio, "run", fake_run)
    monkeypatch.setattr(cc, "pair_session", lambda relay, code: {
        "session_id": "sid-1", "session_secret": "sec-1"})
    cc.run_connector(relay="https://relay.example", pairing_code="ABCDE-FGHIJ", poll=True)
    assert calls["n"] == 1  # did not loop
