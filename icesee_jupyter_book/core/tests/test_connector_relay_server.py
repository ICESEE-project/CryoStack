"""Relay v2: session ownership + capability authentication.

The relay must fail closed for every foreign / unknown / expired / superseded /
disconnected session, and a connector must not be able to reach a session it
does not hold the pairing capability for.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import icesee_jupyter_book.core.connector_relay_server as relay

SECRET_KEYS = ("control_secret", "session_secret", "pairing_code")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("CRYOSTACK_RELAY_CONTROL_TOKEN", raising=False)
    relay._reset_state_for_tests()
    with TestClient(relay.app) as c:
        yield c
    relay._reset_state_for_tests()


def _create(client, owner="user-a", token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = client.post("/connector/session", json={"owner_user_id": owner}, headers=headers)
    return r


def _pair(client, code):
    return client.post("/connector/pair", json={"pairing_code": code})


def _connect(client, session_id, secret):
    """Open an authenticated connector WS; returns the ws context manager."""
    ctx = client.websocket_connect(f"/connector/ws/{session_id}")
    ws = ctx.__enter__()
    ws.send_json({"type": "auth", "secret": secret})
    hello = ws.receive_json()
    assert hello["type"] == "auth_ok"
    return ctx, ws


def _run_command(client, ws, session_id, control_secret, owner, ctype="shell", payload=None):
    """Issue a command over the control plane while driving the WS reply."""
    box: dict = {}

    def issue():
        box["resp"] = client.post(
            f"/connector/command/{session_id}",
            json={"owner_user_id": owner, "command_type": ctype, "payload": payload or {}},
            headers={"Authorization": f"Bearer {control_secret}"},
        )

    t = threading.Thread(target=issue)
    t.start()
    forwarded = ws.receive_json()
    ws.send_json({"command_id": forwarded["command_id"], "result": {"ok": True, "seen": forwarded["payload"]}})
    t.join(timeout=5)
    return box["resp"], forwarded


# ── create ────────────────────────────────────────────────────────────────
def test_create_requires_owner(client):
    assert client.post("/connector/session", json={"owner_user_id": ""}).status_code == 400
    assert client.post("/connector/session", json={}).status_code == 422


def test_create_returns_distinct_capabilities_not_just_the_id(client):
    data = _create(client, "user-a").json()
    assert data["session_id"]
    for k in SECRET_KEYS:
        assert data[k] and data[k] != data["session_id"]
    assert data["control_secret"] != data["session_secret"]


def test_deployment_token_gates_creation_when_set(client, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_RELAY_CONTROL_TOKEN", "deploy-tok")
    assert _create(client, "user-a").status_code == 401
    assert _create(client, "user-a", token="wrong").status_code == 401
    assert _create(client, "user-a", token="deploy-tok").status_code == 200


# ── pairing exchange ─────────────────────────────────────────────────────
def test_pair_is_one_time_and_yields_the_session_secret(client):
    created = _create(client, "user-a").json()
    paired = _pair(client, created["pairing_code"]).json()
    assert paired["session_id"] == created["session_id"]
    assert paired["session_secret"] == created["session_secret"]
    # already used
    assert _pair(client, created["pairing_code"]).status_code == 403


def test_pair_rejects_wrong_random_and_expired_codes(client):
    created = _create(client, "user-a").json()
    assert _pair(client, "ZZZZZ-ZZZZZ").status_code == 403
    assert _pair(client, "").status_code == 403
    relay._SESSIONS[created["session_id"]].expires_at = time.time() - 1
    assert _pair(client, created["pairing_code"]).status_code == 403


# ── connector WS registration ────────────────────────────────────────────
def test_ws_requires_the_correct_session_secret(client):
    created = _create(client, "user-a").json()
    with client.websocket_connect(f"/connector/ws/{created['session_id']}") as ws:
        ws.send_json({"type": "auth", "secret": "not-the-secret"})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_connector_a_cannot_switch_to_session_b(client):
    a = _create(client, "user-a").json()
    b = _create(client, "user-b").json()
    # connector holding A's secret tries to register on B's id
    with client.websocket_connect(f"/connector/ws/{b['session_id']}") as ws:
        ws.send_json({"type": "auth", "secret": a["session_secret"]})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


# ── command authorisation ────────────────────────────────────────────────
def test_command_happy_path(client):
    c = _create(client, "user-a").json()
    ctx, ws = _connect(client, c["session_id"], c["session_secret"])
    try:
        resp, forwarded = _run_command(
            client, ws, c["session_id"], c["control_secret"], "user-a", payload={"command": "id"}
        )
        assert resp.status_code == 200
        assert resp.json()["result"]["ok"] is True
        assert forwarded["payload"] == {"command": "id"}
    finally:
        ctx.__exit__(None, None, None)


def test_command_needs_the_control_secret(client):
    c = _create(client, "user-a").json()
    ctx, ws = _connect(client, c["session_id"], c["session_secret"])
    try:
        r = client.post(
            f"/connector/command/{c['session_id']}",
            json={"owner_user_id": "user-a", "command_type": "shell", "payload": {}},
            headers={"Authorization": "Bearer wrong"},
        )
        assert r.status_code == 401
        # the session_secret is NOT the control credential
        r2 = client.post(
            f"/connector/command/{c['session_id']}",
            json={"owner_user_id": "user-a", "command_type": "shell", "payload": {}},
            headers={"Authorization": f"Bearer {c['session_secret']}"},
        )
        assert r2.status_code == 401
    finally:
        ctx.__exit__(None, None, None)


def test_user_b_cannot_command_user_a_session(client):
    a = _create(client, "user-a").json()
    b = _create(client, "user-b").json()
    ctx, ws = _connect(client, a["session_id"], a["session_secret"])
    try:
        # B has their own control_secret; using it against A's session -> 401.
        r = client.post(
            f"/connector/command/{a['session_id']}",
            json={"owner_user_id": "user-b", "command_type": "shell", "payload": {}},
            headers={"Authorization": f"Bearer {b['control_secret']}"},
        )
        assert r.status_code == 401
        # Even with A's control_secret, a mismatched owner id is refused.
        r2 = client.post(
            f"/connector/command/{a['session_id']}",
            json={"owner_user_id": "user-b", "command_type": "shell", "payload": {}},
            headers={"Authorization": f"Bearer {a['control_secret']}"},
        )
        assert r2.status_code == 403
    finally:
        ctx.__exit__(None, None, None)


def test_disconnected_session_cannot_execute(client):
    c = _create(client, "user-a").json()
    _pair(client, c["pairing_code"])  # paired but no WS
    r = client.post(
        f"/connector/command/{c['session_id']}",
        json={"owner_user_id": "user-a", "command_type": "shell", "payload": {}},
        headers={"Authorization": f"Bearer {c['control_secret']}"},
    )
    assert r.status_code == 409


def test_superseded_session_cannot_execute(client):
    a1 = _create(client, "user-a").json()
    ctx, ws = _connect(client, a1["session_id"], a1["session_secret"])
    try:
        a2 = _create(client, "user-a").json()  # same owner -> supersedes a1
        assert a2["session_id"] != a1["session_id"]
        r = client.post(
            f"/connector/command/{a1['session_id']}",
            json={"owner_user_id": "user-a", "command_type": "shell", "payload": {}},
            headers={"Authorization": f"Bearer {a1['control_secret']}"},
        )
        assert r.status_code == 409
        assert client.get(f"/connector/status/{a1['session_id']}").json()["state"] == "superseded"
    finally:
        try:
            ctx.__exit__(None, None, None)
        except Exception:
            pass


def test_expired_session_cannot_execute(client):
    c = _create(client, "user-a").json()
    relay._SESSIONS[c["session_id"]].expires_at = time.time() - 1
    r = client.post(
        f"/connector/command/{c['session_id']}",
        json={"owner_user_id": "user-a", "command_type": "shell", "payload": {}},
        headers={"Authorization": f"Bearer {c['control_secret']}"},
    )
    assert r.status_code == 409


# ── discovery removed ────────────────────────────────────────────────────
def test_global_latest_is_gone(client):
    _create(client, "user-a")
    _create(client, "user-b")
    assert client.get("/connector/latest").status_code == 410


def test_creating_b_after_a_does_not_point_a_connector_at_b(client):
    a = _create(client, "user-a").json()
    b = _create(client, "user-b").json()
    # There is no endpoint that hands a connector "the newest session"; the only
    # way to a session's secret is its own pairing code.
    assert _pair(client, a["pairing_code"]).json()["session_id"] == a["session_id"]
    assert _pair(client, b["pairing_code"]).json()["session_id"] == b["session_id"]


# ── status leaks nothing ─────────────────────────────────────────────────
def test_status_is_coarse_and_carries_no_secret_or_owner(client):
    c = _create(client, "user-a").json()
    body = client.get(f"/connector/status/{c['session_id']}").json()
    assert set(body) == {"session_id", "online", "state"}
    assert body["state"] == "waiting" and body["online"] is False
    assert client.get("/connector/status/deadbeef").json()["state"] == "unknown"


def test_relay_module_never_logs_secrets():
    src = Path(relay.__file__).read_text()
    for bad in ("print(sess.control_secret", "print(sess.session_secret", "print(sess.pairing_code",
                "log(sess.control_secret", 'f"{sess.session_secret'):
        assert bad not in src
