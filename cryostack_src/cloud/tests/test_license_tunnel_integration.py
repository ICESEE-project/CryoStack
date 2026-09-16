"""End-to-end integration test for the private-service tunnel: a REAL relay
(uvicorn over a real TCP socket), a REAL Connector coroutine
(icesee_hpc_connector.connector_core.main), and the cloud-side client
(cryostack_src.cloud.license_tunnel_client) all talking to each other for
real -- the only thing standing in for the institution is a plain local TCP
echo server the Connector's allow-list is pointed at for this test.

This is the "does the whole thing actually work together" test; the
relay/Connector/cloud-client unit tests elsewhere cover each layer's edge
cases in isolation.
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

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import icesee_hpc_connector.connector_core as cc
import icesee_jupyter_book.core.connector_relay_server as relay
import cryostack_src.cloud.license_tunnel_client as ltc


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _kill_serve_children_with_port(port: int) -> None:
    """Best-effort, local-sandbox-only cleanup for a detached `serve`
    child: it carries no --port flag (it reads CRYOSTACK_LT_PORT from its
    own environment), so a plain argv-matching pkill cannot find it --
    cross-reference /proc/<pid>/environ instead."""
    import os
    import signal

    needle = f"CRYOSTACK_LT_PORT={port}".encode()
    proc_dir = "/proc"
    try:
        pids = [p for p in os.listdir(proc_dir) if p.isdigit()]
    except OSError:
        return
    for pid in pids:
        try:
            with open(f"{proc_dir}/{pid}/cmdline", "rb") as fh:
                cmdline = fh.read()
            if b"license_tunnel_client" not in cmdline or b"serve" not in cmdline:
                continue
            with open(f"{proc_dir}/{pid}/environ", "rb") as fh:
                environ = fh.read()
            if needle in environ:
                os.kill(int(pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            continue


class _EchoServer(threading.Thread):
    """A trivial blocking TCP echo server standing in for the institutional
    private service (e.g. the MATLAB license server)."""

    def __init__(self):
        super().__init__(daemon=True)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        self._stop = False

    def run(self):
        self._sock.settimeout(0.2)
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
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
    """Runs the real Connector coroutine (icesee_hpc_connector.connector_core
    .main) against the live relay, on its own event loop. ``relay`` (the
    plain http(s) base URL) is required so the Connector can open its own
    dedicated per-tunnel data socket (/connector/tunnel-data/{id}) -- a
    SEPARATE connection from the control socket at ``ws_url``."""

    def __init__(self, ws_url: str, session_secret: str, relay: str):
        super().__init__(daemon=True)
        self._ws_url = ws_url
        self._session_secret = session_secret
        self._relay = relay
        self._stop_event = threading.Event()

    def run(self):
        try:
            asyncio.run(cc.main(self._ws_url, self._session_secret,
                                 relay=self._relay, stop_event=self._stop_event))
        except Exception:
            pass

    def stop(self):
        self._stop_event.set()


def test_end_to_end_tunnel_bridges_a_real_local_service(live_relay, echo_server, monkeypatch):
    monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("matlab-license", "primary"), ("127.0.0.1", echo_server))

    created = requests.post(f"{live_relay}/connector/session", json={"owner_user_id": "user-a"}).json()
    session_id = created["session_id"]
    control_secret = created["control_secret"]
    session_secret = created["session_secret"]

    ws_url = f"{live_relay.replace('http://', 'ws://')}/connector/ws/{session_id}"
    connector = _ConnectorThread(ws_url, session_secret, live_relay)
    connector.start()

    try:
        # wait for the connector to actually register
        for _ in range(200):
            status = requests.get(f"{live_relay}/connector/status/{session_id}").json()
            if status["online"]:
                break
            time.sleep(0.02)
        else:
            pytest.fail("connector never came online")

        grant = requests.post(
            f"{live_relay}/connector/tunnel-grant/{session_id}",
            json={"owner_user_id": "user-a", "purpose": "matlab-license"},
            headers={"Authorization": f"Bearer {control_secret}"},
        ).json()
        assert grant["ok"] is True
        token = grant["token"]

        # 1. selfcheck must succeed BEFORE anything tries to use the tunnel.
        ok, code = asyncio.run(ltc.selfcheck(
            relay_url=live_relay, session_id=session_id, token=token,
            purpose="matlab-license", endpoint="primary",
        ))
        assert ok is True and code == ""

        # 2. bring up the local listener a real MATLAB process would connect to.
        listen_port = _free_port()
        ready = threading.Event()

        async def _serve():
            await ltc.run_local_listener(
                listen_host="127.0.0.1", listen_port=listen_port,
                relay_url=live_relay, session_id=session_id, token=token,
                purpose="matlab-license", endpoint="primary",
                ready_callback=ready.set,
            )

        loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(loop)
            loop.run_forever()

        listener_thread = threading.Thread(target=_run_loop, daemon=True)
        listener_thread.start()
        serve_future = asyncio.run_coroutine_threadsafe(_serve(), loop)
        assert ready.wait(timeout=5), "local listener never became ready"

        # 3. a plain blocking client, exactly like MATLAB's own TCP client,
        # talks to 127.0.0.1:<listen_port> and the bytes really do reach the
        # "institutional" echo server and back, through relay + connector.
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.settimeout(5)
        client_sock.connect(("127.0.0.1", listen_port))
        try:
            client_sock.sendall(b"MLM_LICENSE_FILE handshake bytes")
            received = client_sock.recv(65536)
            assert received == b"MLM_LICENSE_FILE handshake bytes"
        finally:
            client_sock.close()

        serve_future.cancel()
        loop.call_soon_threadsafe(loop.stop)
        listener_thread.join(timeout=5)
    finally:
        connector.stop()
        connector.join(timeout=5)


def test_cli_listen_subcommand_end_to_end_with_a_real_detached_process(
        live_relay, echo_server, monkeypatch):
    """Exercises exactly what the Batch runner wrapper invokes
    (``python3 -m cryostack_src.cloud.license_tunnel_client listen ...``)
    as a REAL subprocess -- not a mocked Popen -- proving the process
    genuinely detaches, binds the local port, and the tunnel actually
    carries bytes end to end through the live relay + real Connector."""
    import subprocess

    monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("matlab-license", "primary"), ("127.0.0.1", echo_server))

    created = requests.post(f"{live_relay}/connector/session", json={"owner_user_id": "user-a"}).json()
    session_id = created["session_id"]
    control_secret = created["control_secret"]
    session_secret = created["session_secret"]

    ws_url = f"{live_relay.replace('http://', 'ws://')}/connector/ws/{session_id}"
    connector = _ConnectorThread(ws_url, session_secret, live_relay)
    connector.start()

    try:
        for _ in range(200):
            status = requests.get(f"{live_relay}/connector/status/{session_id}").json()
            if status["online"]:
                break
            time.sleep(0.02)
        else:
            pytest.fail("connector never came online")

        grant = requests.post(
            f"{live_relay}/connector/tunnel-grant/{session_id}",
            json={"owner_user_id": "user-a", "purpose": "matlab-license"},
            headers={"Authorization": f"Bearer {control_secret}"},
        ).json()

        listen_port = _free_port()
        proc = subprocess.run(
            [sys.executable, "-m", "cryostack_src.cloud.license_tunnel_client", "listen",
             "--relay", live_relay, "--session", session_id, "--token", grant["token"],
             "--purpose", "matlab-license", "--endpoint", "primary",
             "--port", str(listen_port)],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"

        client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.settimeout(5)
        client_sock.connect(("127.0.0.1", listen_port))
        try:
            client_sock.sendall(b"real-subprocess-path")
            assert client_sock.recv(65536) == b"real-subprocess-path"
        finally:
            client_sock.close()
    finally:
        connector.stop()
        connector.join(timeout=5)
        # The detached "serve" child intentionally outlives its parent
        # (that IS the point being tested -- production relies on the
        # container's own lifecycle to end it, never a --port flag: it
        # reads CRYOSTACK_LT_PORT from its OWN environment, invisible to a
        # plain `ps` argv match). Best-effort local-sandbox cleanup only,
        # matched by that exact env value via /proc.
        _kill_serve_children_with_port(listen_port)
