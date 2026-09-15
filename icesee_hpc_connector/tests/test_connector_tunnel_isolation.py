"""Demonstrates that Remote-mode RPC (ssh-run/slurm-submit/archive transfer/
status, modelled here by the same `shell` command_type they all reduce to
for dispatch purposes) and a Cloud private-service tunnel share exactly ONE
Connector process/session -- and that neither can stall, corrupt, or take
down the other -- against a REAL relay (uvicorn) and the REAL Connector
coroutine (icesee_hpc_connector.connector_core.main), never a bare WS
double standing in for either side.

This is the concrete evidence for the architectural review: a long-running
RPC command must not delay in-flight tunnel bytes (head-of-line blocking),
an active/high-volume tunnel must not delay RPC commands, a tunnel
disconnecting must not affect subsequent RPC, an RPC failure must not take
down an unrelated live tunnel, and multiple simultaneous tunnels must not
corrupt each other's framing or the control channel's.
"""
from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import requests
import uvicorn

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import icesee_hpc_connector.connector_core as cc
import icesee_jupyter_book.core.connector_relay_server as relay
import icesee_jupyter_book.core.connector_relay_client as relay_client


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _EchoServer(threading.Thread):
    """Stands in for the institutional private service (e.g. the MATLAB
    license server) -- a plain blocking TCP echo server that services EACH
    accepted connection on its own thread, so multiple simultaneous
    tunnels (e.g. a FlexNet primary + vendor-daemon port) are each
    genuinely serviced concurrently, not queued behind one another."""

    def __init__(self):
        super().__init__(daemon=True)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._stop = False
        self._workers: list[threading.Thread] = []

    @staticmethod
    def _serve_one(conn):
        conn.settimeout(5)
        try:
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                conn.sendall(data)
        except Exception:
            pass
        finally:
            conn.close()

    def run(self):
        self._sock.settimeout(0.2)
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            worker = threading.Thread(target=self._serve_one, args=(conn,), daemon=True)
            worker.start()
            self._workers.append(worker)

    def stop(self):
        self._stop = True
        try:
            self._sock.close()
        except Exception:
            pass


@pytest.fixture
def live_relay():
    relay._reset_state_for_tests()
    port = _free_port()
    config = uvicorn.Config(relay.app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if getattr(server, "started", False):
            break
        time.sleep(0.02)
    else:
        pytest.fail("relay did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        relay._reset_state_for_tests()


@pytest.fixture
def echo_server():
    server = _EchoServer()
    server.start()
    try:
        yield server.port
    finally:
        server.stop()


class _ConnectorThread(threading.Thread):
    """The REAL Connector coroutine -- the same one and only Connector
    process a scientist runs for Remote mode, now also carrying a Cloud
    tunnel."""

    def __init__(self, ws_url: str, session_secret: str, relay_base: str):
        super().__init__(daemon=True)
        self._ws_url = ws_url
        self._session_secret = session_secret
        self._relay = relay_base
        self._stop_event = threading.Event()
        self.error: Exception | None = None

    def run(self):
        try:
            asyncio.run(cc.main(self._ws_url, self._session_secret,
                                 relay=self._relay, stop_event=self._stop_event))
        except Exception as e:  # noqa: BLE001 - surfaced to the test, never silent
            self.error = e

    def stop(self):
        self._stop_event.set()


@pytest.fixture
def session(live_relay, monkeypatch):
    """A live session + a connected real Connector, bound for
    connector_relay_client (the SAME module CryoStack's own kernel process
    uses for Remote RPC), so both send_command(...) (Remote) and the
    tunnel-grant flow (Cloud) go through the identical binding."""
    # monkeypatch (not a raw attribute assignment) so this module-level
    # global is restored after the test, never leaking into any other
    # test file's use of the real production relay URL.
    monkeypatch.setattr(relay_client, "RELAY_URL", live_relay)
    created = requests.post(f"{live_relay}/connector/session", json={"owner_user_id": "user-a"}).json()
    relay_client.bind_session(created["session_id"], created["control_secret"], "user-a")

    ws_url = f"{live_relay.replace('http://', 'ws://')}/connector/ws/{created['session_id']}"
    connector = _ConnectorThread(ws_url, created["session_secret"], live_relay)
    connector.start()
    for _ in range(200):
        status = requests.get(f"{live_relay}/connector/status/{created['session_id']}").json()
        if status["online"]:
            break
        time.sleep(0.02)
    else:
        pytest.fail("connector never came online")

    try:
        yield created
    finally:
        connector.stop()
        connector.join(timeout=5)
        relay_client.clear_binding()


def _open_local_tunnel_socket(live_relay, session_id, token, purpose="matlab-license", endpoint="primary", *, timeout=5):
    """A plain blocking socket standing in for MATLAB's own TCP client,
    driving a real websocket client against /connector/tunnel/{id} on a
    background thread so the test's main thread stays free to drive RPC."""
    import websockets.sync.client as ws_sync

    url = f"{live_relay.replace('http://', 'ws://')}/connector/tunnel/{session_id}"
    ws = ws_sync.connect(url, open_timeout=timeout)
    ws.send('{"type":"tunnel-open","token":"%s","purpose":"%s","endpoint":"%s"}' % (token, purpose, endpoint))
    import json
    ack = json.loads(ws.recv(timeout=timeout))
    assert ack == {"type": "tunnel-open-ack", "ok": True}, ack
    return ws


def _mint(live_relay, session_id, control_secret, purpose="matlab-license"):
    grant = requests.post(
        f"{live_relay}/connector/tunnel-grant/{session_id}",
        json={"owner_user_id": "user-a", "purpose": purpose},
        headers={"Authorization": f"Bearer {control_secret}"},
    ).json()
    assert grant["ok"] is True
    return grant


# ── one Connector, one session, serving both planes ─────────────────────
def test_same_connector_session_serves_remote_rpc_and_cloud_tunnel(live_relay, echo_server, session, monkeypatch):
    monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("matlab-license", "primary"), ("127.0.0.1", echo_server))

    # Remote RPC through the SAME session (no new pairing, no second Connector).
    result = relay_client.send_command(session["session_id"], "shell", {"command": "echo remote-rpc-ok"})
    assert result["ok"] is True
    assert "remote-rpc-ok" in result["result"]["stdout"]

    # Cloud tunnel through the SAME session/token model.
    grant = _mint(live_relay, session["session_id"], session["control_secret"])
    tws = _open_local_tunnel_socket(live_relay, session["session_id"], grant["token"])
    try:
        tws.send(b"same-connector-tunnel")
        assert tws.recv(timeout=5) == b"same-connector-tunnel"
    finally:
        tws.close()


# ── the actual regression: RPC duration must not stall tunnel data ─────
def test_remote_rpc_does_not_stall_an_active_tunnel(live_relay, echo_server, session, monkeypatch):
    """The concrete head-of-line-blocking regression test: issue a
    multi-second RPC command and, WHILE it is still running, send tunnel
    data and confirm it arrives promptly -- not only after the RPC
    command finishes. This is the exact failure mode the split
    control/data transport exists to prevent."""
    monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("matlab-license", "primary"), ("127.0.0.1", echo_server))

    grant = _mint(live_relay, session["session_id"], session["control_secret"])
    tws = _open_local_tunnel_socket(live_relay, session["session_id"], grant["token"])
    try:
        rpc_box: dict = {}

        def _slow_rpc():
            rpc_box["result"] = relay_client.send_command(
                session["session_id"], "shell", {"command": "sleep 2", "timeout": 10},
            )

        rpc_thread = threading.Thread(target=_slow_rpc)
        rpc_thread.start()
        time.sleep(0.3)  # let the slow RPC actually start running

        start = time.monotonic()
        tws.send(b"ping-during-slow-rpc")
        reply = tws.recv(timeout=5)
        elapsed = time.monotonic() - start

        assert reply == b"ping-during-slow-rpc"
        # generously below the RPC's 2s duration -- if the control-socket
        # RPC were stalling the tunnel, this would take >=~1.7s instead.
        assert elapsed < 1.0, f"tunnel round-trip took {elapsed:.2f}s while an RPC command was running"

        rpc_thread.join(timeout=10)
        assert rpc_box["result"]["ok"] is True
    finally:
        tws.close()


def test_active_tunnel_traffic_does_not_stall_remote_rpc(live_relay, echo_server, session, monkeypatch):
    """The reverse direction: a burst of tunnel traffic must not delay an
    RPC command issued while it is flowing."""
    monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("matlab-license", "primary"), ("127.0.0.1", echo_server))

    grant = _mint(live_relay, session["session_id"], session["control_secret"])
    tws = _open_local_tunnel_socket(live_relay, session["session_id"], grant["token"])
    stop_flood = threading.Event()

    def _flood():
        while not stop_flood.is_set():
            try:
                tws.send(b"x" * 4096)
                tws.recv(timeout=1)
            except Exception:
                return

    flood_thread = threading.Thread(target=_flood, daemon=True)
    flood_thread.start()
    try:
        time.sleep(0.2)
        start = time.monotonic()
        result = relay_client.send_command(session["session_id"], "shell", {"command": "echo fast-rpc"})
        elapsed = time.monotonic() - start
        assert result["ok"] is True
        assert "fast-rpc" in result["result"]["stdout"]
        assert elapsed < 2.0, f"RPC command took {elapsed:.2f}s while a tunnel was flooding data"
    finally:
        stop_flood.set()
        flood_thread.join(timeout=5)
        tws.close()


# ── tunnel disconnect while Remote RPC continues ────────────────────────
def test_tunnel_disconnect_does_not_affect_subsequent_remote_rpc(live_relay, echo_server, session, monkeypatch):
    monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("matlab-license", "primary"), ("127.0.0.1", echo_server))

    grant = _mint(live_relay, session["session_id"], session["control_secret"])
    tws = _open_local_tunnel_socket(live_relay, session["session_id"], grant["token"])
    tws.send(b"before-disconnect")
    assert tws.recv(timeout=5) == b"before-disconnect"
    tws.close()  # the tunnel goes away entirely

    time.sleep(0.2)
    result = relay_client.send_command(session["session_id"], "shell", {"command": "echo still-works"})
    assert result["ok"] is True
    assert "still-works" in result["result"]["stdout"]


# ── RPC failure must not terminate an unrelated live tunnel ─────────────
def test_rpc_failure_does_not_terminate_an_unrelated_tunnel(live_relay, echo_server, session, monkeypatch):
    monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("matlab-license", "primary"), ("127.0.0.1", echo_server))

    grant = _mint(live_relay, session["session_id"], session["control_secret"])
    tws = _open_local_tunnel_socket(live_relay, session["session_id"], grant["token"])
    try:
        # a command that fails (nonzero exit / unsupported type) -- must not
        # touch the unrelated live tunnel in any way.
        result = relay_client.send_command(session["session_id"], "shell", {"command": "exit 7"})
        assert result["ok"] is True  # the RPC itself succeeds; the SCRIPT failed
        assert result["result"]["ok"] is False
        assert result["result"]["returncode"] == 7

        tws.send(b"tunnel-still-alive-after-rpc-failure")
        assert tws.recv(timeout=5) == b"tunnel-still-alive-after-rpc-failure"
    finally:
        tws.close()


# ── multiple tunnels: no cross-talk, no framing corruption ─────────────
def test_multiple_tunnels_and_rpc_concurrently_no_corruption(live_relay, echo_server, session, monkeypatch):
    monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("matlab-license", "primary"), ("127.0.0.1", echo_server))
    monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("matlab-license", "vendor"), ("127.0.0.1", echo_server))

    grant = _mint(live_relay, session["session_id"], session["control_secret"])
    tws_primary = _open_local_tunnel_socket(live_relay, session["session_id"], grant["token"], endpoint="primary")
    tws_vendor = _open_local_tunnel_socket(live_relay, session["session_id"], grant["token"], endpoint="vendor")

    try:
        results = {}

        def _rpc():
            results["rpc"] = relay_client.send_command(session["session_id"], "shell", {"command": "echo concurrent"})

        rpc_thread = threading.Thread(target=_rpc)
        rpc_thread.start()

        for i in range(20):
            tws_primary.send(f"primary-{i}".encode())
            tws_vendor.send(f"vendor-{i}".encode())
            assert tws_primary.recv(timeout=5) == f"primary-{i}".encode()
            assert tws_vendor.recv(timeout=5) == f"vendor-{i}".encode()

        rpc_thread.join(timeout=10)
        assert results["rpc"]["ok"] is True
        assert "concurrent" in results["rpc"]["result"]["stdout"]
    finally:
        tws_primary.close()
        tws_vendor.close()
