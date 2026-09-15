"""Connector-side private-service tunnel: allow-list resolution, and real
local TCP forwarding (binary, over a dedicated per-tunnel data socket) --
the connector-internal half of the split control/data transport.

The Connector NEVER dials a host/port the cloud side (or the relay) hands
it -- only a symbolic ``(purpose, endpoint)`` pair, resolved exclusively
against the site-supplied, trusted :data:`connector_core.SITE_TUNNEL_TARGETS`
table. These tests exercise that resolver plus the real asyncio TCP
forwarding against a genuine loopback server -- not a mock socket -- with
the relay's data-plane WebSocket replaced by a small in-process fake (no
live relay needed for these unit tests; the real, live-relay end-to-end
path -- including Remote RPC running concurrently -- is covered in
test_connector_tunnel_isolation.py).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import icesee_hpc_connector.connector_core as cc


class FakeControlWS:
    """Stand-in for the Connector's control-plane WebSocket: records every
    ``send()`` call (JSON text only -- the control socket never carries
    tunnel data) so a test can assert on exactly what would have gone to
    the relay."""

    def __init__(self):
        self.sent: list = []

    async def send(self, data):
        self.sent.append(data)

    def json_messages(self) -> list[dict]:
        return [json.loads(m) for m in self.sent]


class FakeDataWS:
    """Stand-in for one tunnel's dedicated data-plane WebSocket
    (icesee_jupyter_book.core.connector_relay_server:tunnel_data_ws on the
    real relay). Supports the same shape connector_core actually uses:
    ``await data_ws.send(bytes)``, ``async for raw in data_ws``, and
    ``await data_ws.close()``."""

    def __init__(self):
        self.sent: list[bytes] = []
        self._incoming: "asyncio.Queue" = asyncio.Queue()
        self.closed = False

    async def send(self, data: bytes):
        self.sent.append(data)

    async def close(self):
        if not self.closed:
            self.closed = True
            await self._incoming.put(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self._incoming.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def push(self, data: bytes):
        await self._incoming.put(data)


async def _start_echo_server():
    """A tiny asyncio TCP server that echoes back whatever it receives, on
    an OS-assigned loopback port. Returns (server, host, port)."""

    async def handle(reader, writer):
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    return server, host, port


async def _start_closing_server():
    """A server that accepts and immediately closes -- for EOF testing."""

    async def handle(reader, writer):
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    return server, host, port


# ── allow-list resolution: the cloud side can never supply host/port ────
def test_resolve_tunnel_target_known_purpose_and_endpoint():
    assert cc.resolve_tunnel_target("matlab-license", "primary") == (
        "matlablic.ecs.gatech.edu", 1711,
    )


def test_resolve_tunnel_target_unknown_purpose_or_endpoint_is_none():
    assert cc.resolve_tunnel_target("matlab-license", "made-up-endpoint") is None
    assert cc.resolve_tunnel_target("made-up-purpose", "primary") is None
    assert cc.resolve_tunnel_target("", "") is None


def test_vendor_port_is_not_yet_confirmed_and_fails_closed():
    """The FlexNet vendor-daemon port has not been confirmed for this site
    (no live network access, nothing in existing site config pins it) --
    the table must say so explicitly (None), not guess a port."""
    assert ("matlab-license", "vendor") in cc.SITE_TUNNEL_TARGETS
    assert cc.SITE_TUNNEL_TARGETS[("matlab-license", "vendor")] is None
    assert cc.resolve_tunnel_target("matlab-license", "vendor") is None


def test_a_message_supplied_host_or_port_is_never_consulted(monkeypatch):
    """Even if a tunnel-open message carries fields that LOOK like a host or
    port, _handle_tunnel_open only ever looks at (purpose, endpoint) through
    the trusted table -- it has no code path that reads any other field for
    connection purposes."""
    monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("test-purpose", "primary"), ("127.0.0.1", 9))
    # A message trying to smuggle a different destination via extra fields.
    msg = {
        "tunnel_id": 1, "purpose": "test-purpose", "endpoint": "primary",
        "host": "evil.example.com", "port": 4444,
    }

    async def run():
        control_ws = FakeControlWS()
        tunnels: dict = {}
        await cc._handle_tunnel_open("http://relay.invalid", "sid", "sec", tunnels, msg, control_ws=control_ws)
        return control_ws

    control_ws = asyncio.run(run())
    # Connects to whatever the TABLE says for ("test-purpose","primary")
    # (127.0.0.1:9, "discard" -- refused/unreachable in practice), never to
    # the message's own host/port -- confirmed by it failing closed with
    # tunnel-error rather than "succeeding" against the smuggled address.
    errors = [m for m in control_ws.json_messages() if m["type"] == "tunnel-error"]
    assert errors and errors[0]["tunnel_id"] == 1


def test_unknown_target_is_rejected_without_ever_connecting():
    msg = {"tunnel_id": 7, "purpose": "nope", "endpoint": "nope"}

    async def run():
        control_ws = FakeControlWS()
        tunnels: dict = {}
        await cc._handle_tunnel_open("http://relay.invalid", "sid", "sec", tunnels, msg, control_ws=control_ws)
        return control_ws, tunnels

    control_ws, tunnels = asyncio.run(run())
    assert tunnels == {}
    assert control_ws.json_messages() == [{"type": "tunnel-error", "tunnel_id": 7,
                                            "error": ("This connector has no allow-listed destination for "
                                                      "'nope'/'nope'.")}]


# ── real local TCP forwarding over a (faked) dedicated data socket ─────
def test_open_forwards_and_echoes_binary_data(monkeypatch):
    async def run():
        server, host, port = await _start_echo_server()
        monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("test-purpose", "primary"), (host, port))

        fake_data_ws = FakeDataWS()

        async def fake_open_data_socket(relay, session_id, session_secret, tunnel_id, **kw):
            return fake_data_ws

        monkeypatch.setattr(cc, "_open_tunnel_data_socket", fake_open_data_socket)

        try:
            control_ws = FakeControlWS()
            tunnels: dict = {}
            await cc._handle_tunnel_open("http://relay.invalid", "sid", "sec", tunnels, {
                "tunnel_id": 3, "purpose": "test-purpose", "endpoint": "primary",
            }, control_ws=control_ws)

            # no reply on the control socket for success -- the data socket
            # attaching (simulated here by the fake) IS the ready signal.
            assert control_ws.json_messages() == []
            assert 3 in tunnels

            await fake_data_ws.push(b"ping-the-license-server")

            for _ in range(50):
                if fake_data_ws.sent:
                    break
                await asyncio.sleep(0.02)

            assert fake_data_ws.sent == [b"ping-the-license-server"]

            await cc._close_tunnel(tunnels, 3)
            assert tunnels == {}
            assert fake_data_ws.closed is True
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_two_tunnels_use_independent_data_sockets_no_cross_talk(monkeypatch):
    async def run():
        server, host, port = await _start_echo_server()
        monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("test-purpose", "a"), (host, port))
        monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("test-purpose", "b"), (host, port))

        fake_1, fake_2 = FakeDataWS(), FakeDataWS()
        fakes = {1: fake_1, 2: fake_2}

        async def fake_open_data_socket(relay, session_id, session_secret, tunnel_id, **kw):
            return fakes[tunnel_id]

        monkeypatch.setattr(cc, "_open_tunnel_data_socket", fake_open_data_socket)

        try:
            control_ws = FakeControlWS()
            tunnels: dict = {}
            await cc._handle_tunnel_open("http://relay.invalid", "sid", "sec", tunnels,
                                          {"tunnel_id": 1, "purpose": "test-purpose", "endpoint": "a"},
                                          control_ws=control_ws)
            await cc._handle_tunnel_open("http://relay.invalid", "sid", "sec", tunnels,
                                          {"tunnel_id": 2, "purpose": "test-purpose", "endpoint": "b"},
                                          control_ws=control_ws)
            assert set(tunnels) == {1, 2}

            await fake_1.push(b"AAA")
            await fake_2.push(b"BBB")

            for _ in range(50):
                if fake_1.sent and fake_2.sent:
                    break
                await asyncio.sleep(0.02)

            assert fake_1.sent == [b"AAA"]
            assert fake_2.sent == [b"BBB"]
        finally:
            await cc._close_tunnel(tunnels, 1)
            await cc._close_tunnel(tunnels, 2)
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_local_service_closing_ends_the_tunnel_with_no_control_message(monkeypatch):
    """Unlike the earlier multiplexed design, ending a tunnel because the
    local service closed no longer sends ANYTHING over the control
    socket -- closing the data socket IS the signal."""
    async def run():
        server, host, port = await _start_closing_server()
        monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("test-purpose", "primary"), (host, port))

        fake_data_ws = FakeDataWS()

        async def fake_open_data_socket(relay, session_id, session_secret, tunnel_id, **kw):
            return fake_data_ws

        monkeypatch.setattr(cc, "_open_tunnel_data_socket", fake_open_data_socket)

        try:
            control_ws = FakeControlWS()
            tunnels: dict = {}
            await cc._handle_tunnel_open("http://relay.invalid", "sid", "sec", tunnels, {
                "tunnel_id": 5, "purpose": "test-purpose", "endpoint": "primary",
            }, control_ws=control_ws)

            for _ in range(50):
                if fake_data_ws.closed:
                    break
                await asyncio.sleep(0.02)

            assert fake_data_ws.closed is True
            assert control_ws.json_messages() == []   # no tunnel-eof, no message at all
            assert 5 not in tunnels
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_connect_failure_reports_tunnel_error_not_a_crash(monkeypatch):
    async def run():
        # port 1 on loopback: reserved, nothing listens, connection refused
        # is effectively immediate rather than a long timeout.
        monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("test-purpose", "primary"), ("127.0.0.1", 1))
        control_ws = FakeControlWS()
        tunnels: dict = {}
        await cc._handle_tunnel_open("http://relay.invalid", "sid", "sec", tunnels, {
            "tunnel_id": 9, "purpose": "test-purpose", "endpoint": "primary",
        }, control_ws=control_ws)
        return control_ws, tunnels

    control_ws, tunnels = asyncio.run(run())
    assert tunnels == {}
    msgs = control_ws.json_messages()
    assert len(msgs) == 1 and msgs[0]["type"] == "tunnel-error" and msgs[0]["tunnel_id"] == 9


def test_data_socket_open_failure_reports_tunnel_error_and_closes_local_socket(monkeypatch):
    """If the local service connects fine but the relay's data-plane
    socket cannot be opened, the local TCP connection must not leak and a
    tunnel-error is reported on the control socket."""
    async def run():
        server, host, port = await _start_echo_server()
        monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("test-purpose", "primary"), (host, port))

        async def fake_open_data_socket(relay, session_id, session_secret, tunnel_id, **kw):
            raise RuntimeError("relay unreachable")

        monkeypatch.setattr(cc, "_open_tunnel_data_socket", fake_open_data_socket)

        try:
            control_ws = FakeControlWS()
            tunnels: dict = {}
            await cc._handle_tunnel_open("http://relay.invalid", "sid", "sec", tunnels, {
                "tunnel_id": 11, "purpose": "test-purpose", "endpoint": "primary",
            }, control_ws=control_ws)
            return control_ws, tunnels
        finally:
            server.close()
            await server.wait_closed()

    control_ws, tunnels = asyncio.run(run())
    assert tunnels == {}
    msgs = control_ws.json_messages()
    assert len(msgs) == 1 and msgs[0]["type"] == "tunnel-error" and msgs[0]["tunnel_id"] == 11


def test_close_tunnel_cancels_pump_tasks_and_closes_writer_and_data_socket(monkeypatch):
    async def run():
        server, host, port = await _start_echo_server()
        monkeypatch.setitem(cc.SITE_TUNNEL_TARGETS, ("test-purpose", "primary"), (host, port))

        fake_data_ws = FakeDataWS()

        async def fake_open_data_socket(relay, session_id, session_secret, tunnel_id, **kw):
            return fake_data_ws

        monkeypatch.setattr(cc, "_open_tunnel_data_socket", fake_open_data_socket)

        try:
            control_ws = FakeControlWS()
            tunnels: dict = {}
            await cc._handle_tunnel_open("http://relay.invalid", "sid", "sec", tunnels, {
                "tunnel_id": 4, "purpose": "test-purpose", "endpoint": "primary",
            }, control_ws=control_ws)
            tasks = list(tunnels[4]["tasks"])
            await cc._close_tunnel(tunnels, 4)
            assert 4 not in tunnels
            assert fake_data_ws.closed is True
            await asyncio.sleep(0)  # let cancellation land
            assert all(t.cancelled() or t.done() for t in tasks)
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_data_for_an_unknown_tunnel_id_is_a_no_op():
    """_close_tunnel on an id with no handle must not raise."""
    async def run():
        tunnels: dict = {}
        await cc._close_tunnel(tunnels, 42)  # must not raise

    asyncio.run(run())
