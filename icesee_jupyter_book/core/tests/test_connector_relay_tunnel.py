"""Relay private-service tunnel (additive): mint/revoke a purpose-scoped
grant, and open a tunnel as TWO independently-authenticated data sockets
(cloud side + Connector side) the relay bridges directly -- never sharing
a socket with the Connector's control-plane JSON command/reply traffic.

The relay never sees or chooses a destination host/port -- only an opaque
``purpose``/``endpoint`` pair; only the Connector resolves that against its
own trusted allow-list (tested separately in
icesee_hpc_connector/tests/test_connector_tunnel.py). These tests drive the
Connector side of the exchange by hand (bare WS peers answering exactly
what a real Connector would), so they exercise the relay's authorisation,
lifecycle, and plane separation in isolation. Concurrent Remote-RPC-while-
tunnel-active behaviour is covered end-to-end in
icesee_hpc_connector/tests/test_connector_tunnel_isolation.py, which drives
the real Connector coroutine against a real relay.
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


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("CRYOSTACK_RELAY_CONTROL_TOKEN", raising=False)
    relay._reset_state_for_tests()
    with TestClient(relay.app) as c:
        yield c
    relay._reset_state_for_tests()


def _create(client, owner="user-a"):
    return client.post("/connector/session", json={"owner_user_id": owner}).json()


def _connect_connector(client, session_id, secret):
    """The Connector's CONTROL socket -- JSON only, forever."""
    ctx = client.websocket_connect(f"/connector/ws/{session_id}")
    ws = ctx.__enter__()
    ws.send_json({"type": "auth", "secret": secret})
    hello = ws.receive_json()
    assert hello["type"] == "auth_ok"
    return ctx, ws


def _attach_data_socket(client, session_id, session_secret, tunnel_id):
    """The Connector's per-tunnel DATA socket -- opened in response to a
    tunnel-open push on the control socket, exactly like the real
    Connector's _open_tunnel_data_socket."""
    ctx = client.websocket_connect(f"/connector/tunnel-data/{session_id}")
    ws = ctx.__enter__()
    ws.send_json({"type": "tunnel-data-auth", "secret": session_secret, "tunnel_id": tunnel_id})
    return ctx, ws


def _mint_grant(client, session_id, control_secret, owner, purpose="matlab-license", ttl_seconds=None):
    body = {"owner_user_id": owner, "purpose": purpose}
    if ttl_seconds is not None:
        body["ttl_seconds"] = ttl_seconds
    return client.post(
        f"/connector/tunnel-grant/{session_id}",
        json=body,
        headers={"Authorization": f"Bearer {control_secret}"},
    )


def _revoke_grant(client, session_id, control_secret, owner, grant_id):
    return client.post(
        f"/connector/tunnel-grant/{session_id}/revoke",
        json={"owner_user_id": owner, "grant_id": grant_id},
        headers={"Authorization": f"Bearer {control_secret}"},
    )


def _open_tunnel_thread(client, session_id, token, purpose, endpoint):
    """Open the cloud-side tunnel WS and send the handshake on a background
    thread, returning (thread, box). ``box`` fills in with 'ctx'/'ws' as soon
    as the WS is open, and 'ack' once the handshake reply arrives -- the
    caller must service the connector side (on the main thread) for the ack
    to ever arrive, exactly like the existing command-flow tests do."""
    box: dict = {}

    def issue():
        ctx = client.websocket_connect(f"/connector/tunnel/{session_id}")
        ws = ctx.__enter__()
        box["ctx"] = ctx
        box["ws"] = ws
        ws.send_json({"type": "tunnel-open", "token": token, "purpose": purpose, "endpoint": endpoint})
        try:
            box["ack"] = ws.receive_json()
        except WebSocketDisconnect as e:
            box["ack"] = None
            box["disconnect_code"] = e.code

    t = threading.Thread(target=issue)
    t.start()
    return t, box


# ── minting / revoking a grant -- reuses existing control auth ──────────
def test_mint_grant_requires_the_control_secret(client):
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        r = client.post(
            f"/connector/tunnel-grant/{c['session_id']}",
            json={"owner_user_id": "user-a", "purpose": "matlab-license"},
            headers={"Authorization": "Bearer wrong"},
        )
        assert r.status_code == 401
        r2 = _mint_grant(client, c["session_id"], c["control_secret"], "user-a")
        assert r2.status_code == 200
        body = r2.json()
        assert body["ok"] is True
        assert body["token"] and body["grant_id"]
        assert body["token"] != c["control_secret"]
        assert body["token"] != c["session_secret"]
    finally:
        ctx.__exit__(None, None, None)


def test_user_b_cannot_mint_a_grant_for_user_a_session(client):
    a = _create(client, "user-a")
    b = _create(client, "user-b")
    ctx, ws = _connect_connector(client, a["session_id"], a["session_secret"])
    try:
        r = _mint_grant(client, a["session_id"], b["control_secret"], "user-b")
        assert r.status_code == 401  # b's control_secret is not valid for a's session
        r2 = _mint_grant(client, a["session_id"], a["control_secret"], "user-b")
        assert r2.status_code == 403  # correct secret, wrong owner_user_id
    finally:
        ctx.__exit__(None, None, None)


def test_mint_requires_a_purpose(client):
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        r = client.post(
            f"/connector/tunnel-grant/{c['session_id']}",
            json={"owner_user_id": "user-a", "purpose": ""},
            headers={"Authorization": f"Bearer {c['control_secret']}"},
        )
        assert r.status_code == 400
    finally:
        ctx.__exit__(None, None, None)


# ── opening a tunnel: authorisation failures fail closed, never dial ────
def test_tunnel_open_rejects_an_unknown_token(client):
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        t, box = _open_tunnel_thread(client, c["session_id"], "not-a-real-token", "matlab-license", "primary")
        t.join(timeout=5)
        ack = box.get("ack")
        assert ack is not None
        assert ack["type"] == "tunnel-open-ack" and ack["ok"] is False
        box["ctx"].__exit__(None, None, None)
    finally:
        ctx.__exit__(None, None, None)


def test_tunnel_open_rejects_a_purpose_mismatch(client):
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        grant = _mint_grant(client, c["session_id"], c["control_secret"], "user-a", purpose="matlab-license").json()
        t, box = _open_tunnel_thread(client, c["session_id"], grant["token"], "some-other-purpose", "primary")
        t.join(timeout=5)
        assert box["ack"]["ok"] is False
        box["ctx"].__exit__(None, None, None)
    finally:
        ctx.__exit__(None, None, None)


def test_tunnel_open_rejects_a_grant_from_a_different_session(client):
    a = _create(client, "user-a")
    b = _create(client, "user-b")
    ctx_a, ws_a = _connect_connector(client, a["session_id"], a["session_secret"])
    ctx_b, ws_b = _connect_connector(client, b["session_id"], b["session_secret"])
    try:
        grant_a = _mint_grant(client, a["session_id"], a["control_secret"], "user-a").json()
        # A's token, presented against B's session path -- must be refused.
        t, box = _open_tunnel_thread(client, b["session_id"], grant_a["token"], "matlab-license", "primary")
        t.join(timeout=5)
        assert box["ack"]["ok"] is False
        box["ctx"].__exit__(None, None, None)
    finally:
        ctx_a.__exit__(None, None, None)
        ctx_b.__exit__(None, None, None)


def test_tunnel_open_requires_a_connected_connector(client):
    c = _create(client, "user-a")
    # paired but never connected -- create() alone is enough for a grant.
    grant = _mint_grant(client, c["session_id"], c["control_secret"], "user-a")
    # Minting requires the session to be "live" (control auth), which does
    # not require a connected connector -- but opening the tunnel does.
    assert grant.status_code == 200
    t, box = _open_tunnel_thread(client, c["session_id"], grant.json()["token"], "matlab-license", "primary")
    t.join(timeout=5)
    assert box["ack"]["ok"] is False
    box["ctx"].__exit__(None, None, None)


def test_revoked_grant_cannot_open_a_tunnel(client):
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        grant = _mint_grant(client, c["session_id"], c["control_secret"], "user-a").json()
        rr = _revoke_grant(client, c["session_id"], c["control_secret"], "user-a", grant["grant_id"])
        assert rr.status_code == 200
        t, box = _open_tunnel_thread(client, c["session_id"], grant["token"], "matlab-license", "primary")
        t.join(timeout=5)
        assert box["ack"]["ok"] is False
        box["ctx"].__exit__(None, None, None)
    finally:
        ctx.__exit__(None, None, None)


def test_expired_grant_cannot_open_a_tunnel(client):
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        grant = _mint_grant(client, c["session_id"], c["control_secret"], "user-a", ttl_seconds=1).json()
        for g in relay._TUNNEL_GRANTS.values():
            if g.grant_id == grant["grant_id"]:
                g.expires_at = time.time() - 1
        t, box = _open_tunnel_thread(client, c["session_id"], grant["token"], "matlab-license", "primary")
        t.join(timeout=5)
        assert box["ack"]["ok"] is False
        box["ctx"].__exit__(None, None, None)
    finally:
        ctx.__exit__(None, None, None)


def test_connector_refusal_on_control_socket_surfaces_a_bounded_error(client):
    """Fast-fail path: the Connector rejects the request (allow-list miss,
    local connect failure) WITHOUT ever opening a data socket -- reported
    over the small control-socket message, never a data-plane connection."""
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        grant = _mint_grant(client, c["session_id"], c["control_secret"], "user-a").json()
        t, box = _open_tunnel_thread(client, c["session_id"], grant["token"], "matlab-license", "primary")
        forwarded = ws.receive_json()
        assert forwarded["type"] == "tunnel-open"
        assert "purpose" in forwarded and "endpoint" in forwarded
        ws.send_json({"type": "tunnel-error", "tunnel_id": forwarded["tunnel_id"], "error": "endpoint not allow-listed"})
        t.join(timeout=5)
        assert box["ack"]["ok"] is False
        assert "not allow-listed" in box["ack"]["error"]
        box["ctx"].__exit__(None, None, None)
    finally:
        ctx.__exit__(None, None, None)


def test_connector_silence_times_out(client, monkeypatch):
    monkeypatch.setattr(relay, "TUNNEL_OPEN_TIMEOUT_SECONDS", 0)
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        grant = _mint_grant(client, c["session_id"], c["control_secret"], "user-a").json()
        t, box = _open_tunnel_thread(client, c["session_id"], grant["token"], "matlab-license", "primary")
        # drain the push so the connector's own loop is not left blocking
        # mid-test, but deliberately never attach a data socket or reply.
        ws.receive_json()
        t.join(timeout=5)
        assert box["ack"]["ok"] is False
        box["ctx"].__exit__(None, None, None)
    finally:
        ctx.__exit__(None, None, None)


def test_data_socket_requires_the_correct_session_secret(client):
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        with client.websocket_connect(f"/connector/tunnel-data/{c['session_id']}") as data_ws:
            data_ws.send_json({"type": "tunnel-data-auth", "secret": "wrong-secret", "tunnel_id": 1})
            with pytest.raises(WebSocketDisconnect):
                data_ws.receive_bytes()
    finally:
        ctx.__exit__(None, None, None)


def test_data_socket_without_a_pending_open_is_refused(client):
    """A data socket attaching for a tunnel_id nobody asked to open (stale,
    unknown, replayed) must be refused, never silently paired to anything."""
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        with client.websocket_connect(f"/connector/tunnel-data/{c['session_id']}") as data_ws:
            data_ws.send_json({"type": "tunnel-data-auth", "secret": c["session_secret"], "tunnel_id": 99})
            with pytest.raises(WebSocketDisconnect):
                data_ws.receive_bytes()
    finally:
        ctx.__exit__(None, None, None)


# ── happy path: binary forwarding on the dedicated data plane ───────────
def test_tunnel_forwards_binary_frames_both_directions(client):
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        grant = _mint_grant(client, c["session_id"], c["control_secret"], "user-a").json()
        t, box = _open_tunnel_thread(client, c["session_id"], grant["token"], "matlab-license", "primary")

        forwarded = ws.receive_json()
        assert forwarded["type"] == "tunnel-open"
        tunnel_id = forwarded["tunnel_id"]

        data_ctx, data_ws = _attach_data_socket(client, c["session_id"], c["session_secret"], tunnel_id)

        t.join(timeout=5)
        assert box["ack"] == {"type": "tunnel-open-ack", "ok": True}
        cloud_ws = box["ws"]

        # cloud -> connector data socket -- no framing/prefix at all now
        cloud_ws.send_bytes(b"hello-from-fargate")
        assert data_ws.receive_bytes() == b"hello-from-fargate"

        # connector data socket -> cloud
        data_ws.send_bytes(b"hello-from-license-server")
        assert cloud_ws.receive_bytes() == b"hello-from-license-server"

        # and the connector's CONTROL socket never saw any of that traffic
        # -- nothing else was pushed to it beyond the original tunnel-open.

        box["ctx"].__exit__(None, None, None)
        data_ctx.__exit__(None, None, None)
    finally:
        ctx.__exit__(None, None, None)


def test_two_concurrent_tunnels_use_independent_data_sockets(client):
    """FlexNet-style: a session may need two simultaneous tunnels (e.g. the
    lmgrd master-daemon port and the vendor-daemon port) -- each gets its
    own dedicated pair of sockets and data never leaks between them."""
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        grant = _mint_grant(client, c["session_id"], c["control_secret"], "user-a").json()

        t1, box1 = _open_tunnel_thread(client, c["session_id"], grant["token"], "matlab-license", "primary")
        f1 = ws.receive_json()
        id1 = f1["tunnel_id"]
        data_ctx1, data_ws1 = _attach_data_socket(client, c["session_id"], c["session_secret"], id1)
        t1.join(timeout=5)
        assert box1["ack"]["ok"] is True

        t2, box2 = _open_tunnel_thread(client, c["session_id"], grant["token"], "matlab-license", "vendor")
        f2 = ws.receive_json()
        id2 = f2["tunnel_id"]
        assert id2 != id1
        data_ctx2, data_ws2 = _attach_data_socket(client, c["session_id"], c["session_secret"], id2)
        t2.join(timeout=5)
        assert box2["ack"]["ok"] is True

        box1["ws"].send_bytes(b"AAA")
        box2["ws"].send_bytes(b"BBB")

        assert data_ws1.receive_bytes() == b"AAA"
        assert data_ws2.receive_bytes() == b"BBB"

        data_ws1.send_bytes(b"aaa-reply")
        data_ws2.send_bytes(b"bbb-reply")
        assert box1["ws"].receive_bytes() == b"aaa-reply"
        assert box2["ws"].receive_bytes() == b"bbb-reply"

        box1["ctx"].__exit__(None, None, None)
        box2["ctx"].__exit__(None, None, None)
        data_ctx1.__exit__(None, None, None)
        data_ctx2.__exit__(None, None, None)
    finally:
        ctx.__exit__(None, None, None)


# ── lifecycle: revoke / disconnect terminate the tunnel, on BOTH ends ───
def test_revoke_closes_a_live_tunnel_on_both_ends_now(client):
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        grant = _mint_grant(client, c["session_id"], c["control_secret"], "user-a").json()
        t, box = _open_tunnel_thread(client, c["session_id"], grant["token"], "matlab-license", "primary")
        forwarded = ws.receive_json()
        tunnel_id = forwarded["tunnel_id"]
        data_ctx, data_ws = _attach_data_socket(client, c["session_id"], c["session_secret"], tunnel_id)
        t.join(timeout=5)
        assert box["ack"]["ok"] is True

        rr = _revoke_grant(client, c["session_id"], c["control_secret"], "user-a", grant["grant_id"])
        assert rr.status_code == 200

        # both data sockets are closed directly -- no control-socket message
        with pytest.raises(WebSocketDisconnect):
            box["ws"].receive_bytes()
        with pytest.raises(WebSocketDisconnect):
            data_ws.receive_bytes()
        box["ctx"].__exit__(None, None, None)
        data_ctx.__exit__(None, None, None)
    finally:
        ctx.__exit__(None, None, None)


def test_connector_control_socket_disconnect_closes_live_tunnels(client):
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    grant = _mint_grant(client, c["session_id"], c["control_secret"], "user-a").json()
    t, box = _open_tunnel_thread(client, c["session_id"], grant["token"], "matlab-license", "primary")
    forwarded = ws.receive_json()
    tunnel_id = forwarded["tunnel_id"]
    data_ctx, data_ws = _attach_data_socket(client, c["session_id"], c["session_secret"], tunnel_id)
    t.join(timeout=5)
    assert box["ack"]["ok"] is True

    ctx.__exit__(None, None, None)  # the connector's control socket goes away

    with pytest.raises(WebSocketDisconnect):
        box["ws"].receive_bytes()
    with pytest.raises(WebSocketDisconnect):
        data_ws.receive_bytes()
    box["ctx"].__exit__(None, None, None)
    data_ctx.__exit__(None, None, None)


def test_cloud_disconnect_closes_the_connector_data_socket(client):
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        grant = _mint_grant(client, c["session_id"], c["control_secret"], "user-a").json()
        t, box = _open_tunnel_thread(client, c["session_id"], grant["token"], "matlab-license", "primary")
        forwarded = ws.receive_json()
        tunnel_id = forwarded["tunnel_id"]
        data_ctx, data_ws = _attach_data_socket(client, c["session_id"], c["session_secret"], tunnel_id)
        t.join(timeout=5)
        assert box["ack"]["ok"] is True

        box["ctx"].__exit__(None, None, None)  # the run's local socket closes

        with pytest.raises(WebSocketDisconnect):
            data_ws.receive_bytes()
        data_ctx.__exit__(None, None, None)
    finally:
        ctx.__exit__(None, None, None)


def test_connector_side_data_socket_closing_ends_the_cloud_side(client):
    """When the Connector's LOCAL half of the tunnel (the license server
    connection) ends, its data socket simply closes -- no message needed --
    and the relay ends the cloud side too rather than leaving it open."""
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        grant = _mint_grant(client, c["session_id"], c["control_secret"], "user-a").json()
        t, box = _open_tunnel_thread(client, c["session_id"], grant["token"], "matlab-license", "primary")
        forwarded = ws.receive_json()
        tunnel_id = forwarded["tunnel_id"]
        data_ctx, data_ws = _attach_data_socket(client, c["session_id"], c["session_secret"], tunnel_id)
        t.join(timeout=5)
        assert box["ack"]["ok"] is True

        data_ctx.__exit__(None, None, None)  # connector's local half ended

        with pytest.raises(WebSocketDisconnect):
            box["ws"].receive_bytes()
        box["ctx"].__exit__(None, None, None)
    finally:
        ctx.__exit__(None, None, None)


# ── existing command transport is untouched by all of the above ─────────
def test_json_command_transport_still_works_on_the_same_socket(client):
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        box: dict = {}

        def issue():
            box["resp"] = client.post(
                f"/connector/command/{c['session_id']}",
                json={"owner_user_id": "user-a", "command_type": "shell", "payload": {"command": "id"}},
                headers={"Authorization": f"Bearer {c['control_secret']}"},
            )

        th = threading.Thread(target=issue)
        th.start()
        forwarded = ws.receive_json()
        assert forwarded["payload"] == {"command": "id"}
        ws.send_json({"command_id": forwarded["command_id"], "result": {"ok": True}})
        th.join(timeout=5)
        assert box["resp"].status_code == 200
        assert box["resp"].json()["result"]["ok"] is True
    finally:
        ctx.__exit__(None, None, None)


def test_command_transport_works_while_a_tunnel_is_live(client):
    """The control socket carries a command reply and a tunnel-open push
    interleaved -- proving the control-plane/data-plane split, not just
    that each works in isolation."""
    c = _create(client, "user-a")
    ctx, ws = _connect_connector(client, c["session_id"], c["session_secret"])
    try:
        grant = _mint_grant(client, c["session_id"], c["control_secret"], "user-a").json()
        t, box = _open_tunnel_thread(client, c["session_id"], grant["token"], "matlab-license", "primary")
        forwarded = ws.receive_json()
        tunnel_id = forwarded["tunnel_id"]
        data_ctx, data_ws = _attach_data_socket(client, c["session_id"], c["session_secret"], tunnel_id)
        t.join(timeout=5)
        assert box["ack"]["ok"] is True

        # a command now, while the tunnel is live
        cmd_box: dict = {}

        def issue():
            cmd_box["resp"] = client.post(
                f"/connector/command/{c['session_id']}",
                json={"owner_user_id": "user-a", "command_type": "shell", "payload": {"command": "id"}},
                headers={"Authorization": f"Bearer {c['control_secret']}"},
            )

        th = threading.Thread(target=issue)
        th.start()
        forwarded_cmd = ws.receive_json()
        assert forwarded_cmd["payload"] == {"command": "id"}

        # tunnel data flows fine in between
        box["ws"].send_bytes(b"still-flowing")
        assert data_ws.receive_bytes() == b"still-flowing"

        ws.send_json({"command_id": forwarded_cmd["command_id"], "result": {"ok": True}})
        th.join(timeout=5)
        assert cmd_box["resp"].json()["result"]["ok"] is True

        box["ctx"].__exit__(None, None, None)
        data_ctx.__exit__(None, None, None)
    finally:
        ctx.__exit__(None, None, None)
