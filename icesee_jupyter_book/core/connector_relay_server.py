"""CryoStack Connector relay -- session-scoped, capability-authenticated (v2).

Identifiers vs. capabilities
----------------------------
``session_id``     non-secret; names a pairing session; may appear in URLs/logs.
``control_secret`` per session, high entropy. Authorises the browser/gateway ->
                   relay control plane (issue command, owner-scoped status).
                   Returned only to the CryoStack kernel that created the session.
``session_secret`` per session, high entropy. Authorises a connector's WebSocket
                   registration -- BOTH its control socket and any tunnel data
                   socket. Delivered to the connector only through the one-time
                   pairing exchange -- never in a URL or query string.
``pairing_code``   short, one-time, short-TTL. The connector exchanges it once
                   for ``{session_id, session_secret}``.
``owner_user_id``  the authenticated CryoStack user that created the session.
``tunnel_token``   per-grant, high entropy, narrowly scoped to one ``purpose``
                   (e.g. ``"matlab-license"``) and short-lived. Minted by the
                   control plane (using ``control_secret``) and handed only to
                   the cloud workload that needs a private-service tunnel --
                   it can never issue a command, read status, or open a tunnel
                   for any other purpose or session.

Endpoints
---------
``POST /connector/session``      (control)   create; body ``{owner_user_id}``;
                                 ``Authorization: Bearer <deployment token>``
                                 required only when ``CRYOSTACK_RELAY_CONTROL_TOKEN``
                                 is set. Any earlier non-expired session owned by
                                 the same user is marked *superseded*.
``POST /connector/pair``         (connector) body ``{pairing_code}``; one-time.
``WS   /connector/ws/{id}``      (connector) first frame
                                 ``{"type":"auth","secret": <session_secret>}``;
                                 relay replies ``{"type":"auth_ok"}``. Carries
                                 ONLY JSON: the existing command/reply traffic,
                                 UNCHANGED, plus two small tunnel CONTROL
                                 messages (``tunnel-open`` / ``tunnel-error``) --
                                 see "Private-service tunnel" below. It never
                                 carries a byte of tunnel DATA -- that is the
                                 whole point of the separate data-plane socket.
``POST /connector/command/{id}`` (control)   ``Authorization: Bearer <control_secret>``
                                 + body ``{owner_user_id, command_type, payload}``.
``GET  /connector/status/{id}``  (public)    coarse ``{session_id, online, state}``.
``GET  /connector/latest``       REMOVED -> ``410 Gone``.

Every control/connector operation fails closed: unknown session, wrong/blank
secret, expired or superseded session, or a disconnected connector all return an
error and never dispatch. Secrets and pairing codes are never logged, and the
global "attach to the newest session anywhere" behaviour is gone -- a connector
reaches a session only by holding that session's pairing capability.

Private-service tunnel: separate control and data planes
----------------------------------------------------------------------------
A generic, narrowly-authorised byte pipe from a cloud workload to a private
service the paired Connector can already reach (e.g. an institutional MATLAB
license server) -- reusing THIS SAME session's identity/authentication (one
Connector installation/pairing serves both Remote-mode RPC and Cloud tunnels;
nothing here mints a second pairing or a second Connector identity) and never
becoming an unrestricted TCP proxy: the relay never sees or chooses a
destination host/port, only an opaque ``purpose``/``endpoint`` pair that the
CONNECTOR alone resolves against its own trusted, site-supplied allow-list
(see ``icesee_hpc_connector/connector_core.py``). A cloud caller that is not
holding a valid, unexpired, unrevoked grant for THIS session and purpose is
refused before anything is dialled.

Tunnel DATA never touches the control WebSocket above. A long-lived or
high-volume tunnel sharing one socket with JSON command/reply traffic would
head-of-line-block Remote-mode RPC (a slow ``ssh-run``/``rsync`` command
suspends the SAME read loop that would otherwise be forwarding tunnel bytes,
and vice versa) -- so each open tunnel gets its OWN dedicated WebSocket
connection on BOTH ends, authenticated with the same ``session_secret`` the
control socket already uses. This is still exactly one Connector process,
one session, one pairing -- just two logical planes instead of one physical
socket carrying both.

``POST /connector/tunnel-grant/{id}``          (control)  mint a short-lived,
                                               purpose-scoped ``tunnel_token``.
                                               ``Authorization: Bearer <control_secret>``
                                               + body ``{owner_user_id, purpose,
                                               ttl_seconds}``.
``POST /connector/tunnel-grant/{id}/revoke``   (control)  revoke a grant now and
                                               close any tunnels opened under it
                                               -- the explicit "run ended" path.
                                               Same auth as mint.
``WS   /connector/tunnel/{id}``                (cloud workload, DATA plane)
                                               first frame ``{"type":
                                               "tunnel-open","token":
                                               <tunnel_token>,"purpose":...,
                                               "endpoint":...}``; relay
                                               allocates a ``tunnel_id``, asks
                                               the Connector's CONTROL socket to
                                               open a matching data socket, and
                                               replies ``{"type":
                                               "tunnel-open-ack","ok":
                                               true|false[,"error":...]}``. On
                                               success every subsequent frame on
                                               THIS socket is raw tunnel payload
                                               (binary WS frames, no framing
                                               overhead -- this socket carries
                                               exactly one tunnel).
``WS   /connector/tunnel-data/{id}``           (connector, DATA plane) first
                                               frame ``{"type":
                                               "tunnel-data-auth","secret":
                                               <session_secret>,"tunnel_id":N}``
                                               -- opened by the Connector itself
                                               in response to a ``tunnel-open``
                                               push on its control socket, one
                                               new connection per tunnel. Once
                                               matched to the waiting cloud-side
                                               socket, the relay bridges raw
                                               binary frames 1:1 between them
                                               until either end closes.

Tunnel control (``tunnel-open`` relay->connector, ``tunnel-error``
connector->relay) stays on the control socket -- it is tiny, infrequent, and
carries no bulk payload, so it cannot itself head-of-line-block RPC. Tunnel
*readiness* is signalled by the data socket actually attaching, not by a
control-socket reply; tunnel *teardown* is signalled by either data socket
closing -- no teardown message is sent over the control socket either.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from icesee_jupyter_book.core.connector_relay_auth import (
    constant_time_equal,
    deployment_token,
    new_pairing_code,
    new_secret,
)

app = FastAPI(title="CryoStack Connector Relay", version="2")

# session lifetime and pairing-code lifetime (seconds); env-overridable
SESSION_TTL_SECONDS = int(os.environ.get("CRYOSTACK_RELAY_SESSION_TTL", 12 * 3600))
PAIRING_TTL_SECONDS = int(os.environ.get("CRYOSTACK_RELAY_PAIRING_TTL", 30 * 60))
COMMAND_TIMEOUT_SECONDS = int(os.environ.get("CRYOSTACK_RELAY_COMMAND_TIMEOUT", 900))
#: default lifetime of a minted tunnel grant when the caller does not specify
#: one -- bounded so an abandoned grant cannot be replayed indefinitely.
DEFAULT_TUNNEL_GRANT_TTL_SECONDS = int(
    os.environ.get("CRYOSTACK_RELAY_TUNNEL_GRANT_TTL", 6 * 3600)
)
#: how long the relay waits for the Connector's data socket to attach (or an
#: explicit tunnel-error) before giving up on a tunnel-open request.
TUNNEL_OPEN_TIMEOUT_SECONDS = int(
    os.environ.get("CRYOSTACK_RELAY_TUNNEL_OPEN_TIMEOUT", 20)
)

STATE_WAITING = "waiting"
STATE_CONNECTED = "connected"
STATE_DISCONNECTED = "disconnected"
STATE_SUPERSEDED = "superseded"
STATE_EXPIRED = "expired"


@dataclass
class Session:
    session_id: str
    owner_user_id: str
    control_secret: str
    session_secret: str
    pairing_code: str
    created_at: float
    expires_at: float
    pairing_used: bool = False
    connected: bool = False
    superseded: bool = False
    pending: dict[str, asyncio.Future] = field(default_factory=dict)
    #: tunnel_id -> Future resolved EITHER by the connector's tunnel-error
    #: reply on the control socket, OR by the connector's data socket
    #: successfully attaching (see tunnel_data_ws). Additive; unrelated to
    #: `pending` above, which is for JSON command replies.
    pending_tunnels: dict[int, asyncio.Future] = field(default_factory=dict)
    #: next tunnel_id to hand out for this session, wrapping 1..255.
    _next_tunnel_id: int = 1

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    def state(self) -> str:
        if self.superseded:
            return STATE_SUPERSEDED
        if self.expired:
            return STATE_EXPIRED
        if self.connected:
            return STATE_CONNECTED
        return STATE_WAITING

    def next_tunnel_id(self) -> int:
        tid = self._next_tunnel_id
        self._next_tunnel_id = 1 if tid >= 255 else tid + 1
        return tid


@dataclass
class TunnelGrant:
    """A short-lived, purpose-scoped capability letting ONE cloud workload
    open tunnels for ONE purpose on ONE session -- never a host/port; those
    are resolved only by the Connector's own trusted allow-list."""

    grant_id: str
    session_id: str
    owner_user_id: str
    purpose: str
    token: str
    created_at: float
    expires_at: float
    revoked: bool = False

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def usable(self) -> bool:
        return not self.revoked and not self.expired


# session_id -> Session  (non-secret key)
_SESSIONS: dict[str, Session] = {}
# session_id -> live connector CONTROL WebSocket (JSON only)
_LIVE_WS: dict[str, WebSocket] = {}
# tunnel_token -> TunnelGrant
_TUNNEL_GRANTS: dict[str, TunnelGrant] = {}
# (session_id, tunnel_id) -> (cloud-side DATA WebSocket, grant_id) -- an
# ESTABLISHED tunnel (both ends attached).
_LIVE_TUNNELS: dict[tuple[str, int], tuple[WebSocket, str]] = {}
# (session_id, tunnel_id) -> connector-side DATA WebSocket for an
# established tunnel -- the other half of _LIVE_TUNNELS.
_LIVE_TUNNEL_CONNECTOR_WS: dict[tuple[str, int], WebSocket] = {}
# (session_id, tunnel_id) -> (cloud-side DATA WebSocket, grant_id) -- a
# tunnel-open in flight, waiting for the connector's data socket to attach
# (or for an explicit tunnel-error / timeout).
_PENDING_CLOUD_WS: dict[tuple[str, int], tuple[WebSocket, str]] = {}


def _get_live_session(session_id: str) -> Session:
    """A session that exists, is not expired and is not superseded, else 4xx."""
    sess = _SESSIONS.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Unknown connector session.")
    if sess.superseded:
        raise HTTPException(status_code=409, detail="This connector session has been superseded by a newer one.")
    if sess.expired:
        raise HTTPException(status_code=409, detail="This connector session has expired.")
    return sess


# ---------------------------------------------------------------------------
# control plane -- create
# ---------------------------------------------------------------------------
class CreateSessionRequest(BaseModel):
    owner_user_id: str


@app.post("/connector/session")
async def create_session(req: CreateSessionRequest, authorization: str | None = Header(default=None)):
    required = deployment_token()
    if required is not None:
        presented = authorization[7:].strip() if (authorization or "").startswith("Bearer ") else ""
        if not constant_time_equal(presented, required):
            raise HTTPException(status_code=401, detail="Relay session creation requires the deployment control token.")

    owner = (req.owner_user_id or "").strip()
    if not owner:
        # Missing / ambiguous identity fails closed.
        raise HTTPException(status_code=400, detail="owner_user_id is required to create a connector session.")

    now = time.time()
    session_id = uuid.uuid4().hex

    # Any earlier live session for this same owner is retired, so a connector
    # paired to it can no longer execute (the user intentionally started over).
    for other in _SESSIONS.values():
        if other.owner_user_id == owner and not other.superseded and not other.expired:
            other.superseded = True
            other.connected = False
            live = _LIVE_WS.pop(other.session_id, None)
            if live is not None:
                asyncio.create_task(_safe_close(live, 4409))
            await _close_session_tunnels(other.session_id)

    sess = Session(
        session_id=session_id,
        owner_user_id=owner,
        control_secret=new_secret(32),
        session_secret=new_secret(32),
        pairing_code=new_pairing_code(),
        created_at=now,
        expires_at=now + SESSION_TTL_SECONDS,
    )
    _SESSIONS[session_id] = sess

    return {
        "ok": True,
        "session_id": session_id,
        "ws_url": f"/connector/ws/{session_id}",
        "control_secret": sess.control_secret,
        "session_secret": sess.session_secret,
        "pairing_code": sess.pairing_code,
        "expires_at": sess.expires_at,
        "pairing_expires_at": min(sess.expires_at, now + PAIRING_TTL_SECONDS),
    }


async def _safe_close(ws: WebSocket, code: int) -> None:
    try:
        await ws.close(code=code)
    except Exception:
        pass


async def _close_session_tunnels(session_id: str) -> None:
    """Close every tunnel for ``session_id`` -- established or still
    pending attach -- on BOTH ends. No message is ever sent over the
    control socket for this: closing a data socket IS the teardown signal,
    detected by the other end's own read loop."""
    for registry in (_LIVE_TUNNELS,):
        stale = [key for key in registry if key[0] == session_id]
        for key in stale:
            cloud_ws, _gid = registry.pop(key, (None, None))
            data_ws = _LIVE_TUNNEL_CONNECTOR_WS.pop(key, None)
            if cloud_ws is not None:
                await _safe_close(cloud_ws, 4410)
            if data_ws is not None:
                await _safe_close(data_ws, 4410)
    pending = [key for key in _PENDING_CLOUD_WS if key[0] == session_id]
    for key in pending:
        cloud_ws, _gid = _PENDING_CLOUD_WS.pop(key, (None, None))
        if cloud_ws is not None:
            await _safe_close(cloud_ws, 4410)


# ---------------------------------------------------------------------------
# connector plane -- one-time pairing exchange
# ---------------------------------------------------------------------------
class PairRequest(BaseModel):
    pairing_code: str


@app.post("/connector/pair")
def pair(req: PairRequest):
    code = (req.pairing_code or "").strip().upper()
    now = time.time()
    for sess in _SESSIONS.values():
        if (
            not sess.pairing_used
            and not sess.superseded
            and not sess.expired
            and now - sess.created_at <= PAIRING_TTL_SECONDS
            and constant_time_equal(code, sess.pairing_code)
        ):
            sess.pairing_used = True
            return {
                "ok": True,
                "session_id": sess.session_id,
                "session_secret": sess.session_secret,
                "ws_url": f"/connector/ws/{sess.session_id}",
                "expires_at": sess.expires_at,
            }
    # Do not distinguish "wrong" from "expired" from "already used".
    raise HTTPException(status_code=403, detail="Invalid or expired pairing code.")


# ---------------------------------------------------------------------------
# connector plane -- authenticated CONTROL WebSocket (JSON only)
# ---------------------------------------------------------------------------
@app.websocket("/connector/ws/{session_id}")
async def connector_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()

    sess = _SESSIONS.get(session_id)
    if sess is None or sess.superseded or sess.expired:
        await _safe_close(websocket, 4404)
        return

    # First frame must prove possession of this session's secret.
    try:
        hello = await asyncio.wait_for(websocket.receive_json(), timeout=15)
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError):
        await _safe_close(websocket, 4401)
        return

    if hello.get("type") != "auth" or not constant_time_equal(hello.get("secret"), sess.session_secret):
        await _safe_close(websocket, 4401)
        return

    await websocket.send_json({"type": "auth_ok", "session_id": session_id})

    _LIVE_WS[session_id] = websocket
    sess.connected = True

    try:
        # JSON only -- see the module docstring. This loop's sole job is
        # command/reply dispatch plus the two tiny tunnel-open/tunnel-error
        # control messages; it never carries tunnel DATA, so nothing here
        # can be stalled by -- or itself stall -- a tunnel's throughput.
        while True:
            msg = await websocket.receive_json()

            if msg.get("type") == "tunnel-error":
                tunnel_id = msg.get("tunnel_id")
                fut = sess.pending_tunnels.pop(tunnel_id, None)
                if fut is not None and not fut.done():
                    fut.set_result(msg)
                continue

            command_id = msg.get("command_id")
            if command_id and command_id in sess.pending:
                fut = sess.pending.pop(command_id)
                if not fut.done():
                    fut.set_result(msg)
    except (WebSocketDisconnect, ValueError):
        pass
    finally:
        if _LIVE_WS.get(session_id) is websocket:
            _LIVE_WS.pop(session_id, None)
            sess.connected = False
        # The connector process itself is gone -- an intentional, explicit
        # choice to end every tunnel it was carrying too, rather than leave
        # a data socket open with a control plane that can never reopen it.
        await _close_session_tunnels(session_id)


# ---------------------------------------------------------------------------
# control plane -- issue a command
# ---------------------------------------------------------------------------
class CommandRequest(BaseModel):
    owner_user_id: str
    command_type: str
    payload: dict[str, Any] = {}


def _authorise_control(session_id: str, owner_user_id: str, authorization: str | None) -> Session:
    sess = _get_live_session(session_id)
    presented = authorization[7:].strip() if (authorization or "").startswith("Bearer ") else ""
    if not constant_time_equal(presented, sess.control_secret):
        raise HTTPException(status_code=401, detail="Missing or invalid control credential for this session.")
    if not constant_time_equal((owner_user_id or "").strip(), sess.owner_user_id):
        raise HTTPException(status_code=403, detail="This session belongs to a different CryoStack user.")
    return sess


@app.post("/connector/command/{session_id}")
async def send_command(session_id: str, req: CommandRequest, authorization: str | None = Header(default=None)):
    sess = _authorise_control(session_id, req.owner_user_id, authorization)

    ws = _LIVE_WS.get(session_id)
    if ws is None or not sess.connected:
        raise HTTPException(status_code=409, detail="The connector for this session is not connected.")

    command_id = uuid.uuid4().hex
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    sess.pending[command_id] = fut

    await ws.send_json({
        "command_id": command_id,
        "command_type": req.command_type,
        "payload": req.payload,
    })

    try:
        result = await asyncio.wait_for(fut, timeout=COMMAND_TIMEOUT_SECONDS)
        return {"ok": True, "command_id": command_id, "result": result.get("result", result)}
    except asyncio.TimeoutError:
        sess.pending.pop(command_id, None)
        raise HTTPException(status_code=504, detail="Connector command timed out.")


# ---------------------------------------------------------------------------
# control plane -- mint / revoke a tunnel grant (additive)
# ---------------------------------------------------------------------------
class TunnelGrantRequest(BaseModel):
    owner_user_id: str
    purpose: str
    ttl_seconds: int | None = None


@app.post("/connector/tunnel-grant/{session_id}")
async def create_tunnel_grant(
    session_id: str, req: TunnelGrantRequest, authorization: str | None = Header(default=None)
):
    sess = _authorise_control(session_id, req.owner_user_id, authorization)

    purpose = (req.purpose or "").strip()
    if not purpose:
        raise HTTPException(status_code=400, detail="purpose is required to mint a tunnel grant.")

    ttl = int(req.ttl_seconds or DEFAULT_TUNNEL_GRANT_TTL_SECONDS)
    if ttl <= 0 or ttl > DEFAULT_TUNNEL_GRANT_TTL_SECONDS * 4:
        raise HTTPException(status_code=400, detail="ttl_seconds out of range.")

    now = time.time()
    grant = TunnelGrant(
        grant_id=uuid.uuid4().hex,
        session_id=session_id,
        owner_user_id=sess.owner_user_id,
        purpose=purpose,
        token=new_secret(32),
        created_at=now,
        expires_at=now + ttl,
    )
    _TUNNEL_GRANTS[grant.token] = grant

    return {
        "ok": True,
        "grant_id": grant.grant_id,
        "token": grant.token,
        "purpose": grant.purpose,
        "expires_at": grant.expires_at,
    }


class TunnelGrantRevokeRequest(BaseModel):
    owner_user_id: str
    grant_id: str


@app.post("/connector/tunnel-grant/{session_id}/revoke")
async def revoke_tunnel_grant(
    session_id: str, req: TunnelGrantRevokeRequest, authorization: str | None = Header(default=None)
):
    sess = _authorise_control(session_id, req.owner_user_id, authorization)

    grant = None
    for candidate in _TUNNEL_GRANTS.values():
        if candidate.grant_id == req.grant_id and candidate.session_id == session_id:
            grant = candidate
            break
    if grant is None:
        raise HTTPException(status_code=404, detail="Unknown tunnel grant.")

    grant.revoked = True

    # Close any tunnels currently open (or still attaching) under this grant
    # -- the explicit "the run ended" path, not merely relying on the grant
    # TTL. No control-socket message needed: closing the data socket(s)
    # directly IS the teardown signal.
    stale = [key for key, (_ws, gid) in _LIVE_TUNNELS.items() if key[0] == session_id and gid == grant.grant_id]
    for key in stale:
        cloud_ws, _gid = _LIVE_TUNNELS.pop(key, (None, None))
        data_ws = _LIVE_TUNNEL_CONNECTOR_WS.pop(key, None)
        if cloud_ws is not None:
            await _safe_close(cloud_ws, 4410)
        if data_ws is not None:
            await _safe_close(data_ws, 4410)
    pending = [key for key, (_ws, gid) in _PENDING_CLOUD_WS.items() if key[0] == session_id and gid == grant.grant_id]
    for key in pending:
        cloud_ws, _gid = _PENDING_CLOUD_WS.pop(key, (None, None))
        if cloud_ws is not None:
            await _safe_close(cloud_ws, 4410)

    return {"ok": True, "grant_id": grant.grant_id, "revoked": True}


# ---------------------------------------------------------------------------
# cloud workload plane -- open a private-service tunnel (data socket, cloud side)
# ---------------------------------------------------------------------------
@app.websocket("/connector/tunnel/{session_id}")
async def tunnel_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()

    sess = _SESSIONS.get(session_id)
    if sess is None or sess.superseded or sess.expired:
        await _safe_close(websocket, 4404)
        return

    try:
        hello = await asyncio.wait_for(websocket.receive_json(), timeout=15)
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError):
        await _safe_close(websocket, 4401)
        return

    if hello.get("type") != "tunnel-open":
        await _safe_close(websocket, 4401)
        return

    token = hello.get("token") or ""
    purpose = (hello.get("purpose") or "").strip()
    endpoint = (hello.get("endpoint") or "").strip()

    grant = _TUNNEL_GRANTS.get(token)
    # constant-time-ish: always look the token up by exact dict key (already
    # unguessable, high-entropy) rather than scanning/comparing -- avoids
    # leaking which part of a wrong token was wrong via timing besides.
    if (
        grant is None
        or grant.session_id != session_id
        or not grant.usable
        or not constant_time_equal(grant.purpose, purpose)
        or not purpose
        or not endpoint
    ):
        await websocket.send_json({"type": "tunnel-open-ack", "ok": False, "error": "Invalid or expired tunnel grant."})
        await _safe_close(websocket, 4403)
        return

    connector_websocket = _LIVE_WS.get(session_id)
    if connector_websocket is None or not sess.connected:
        await websocket.send_json({"type": "tunnel-open-ack", "ok": False, "error": "The connector for this session is not connected."})
        await _safe_close(websocket, 4409)
        return

    tunnel_id = sess.next_tunnel_id()
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    sess.pending_tunnels[tunnel_id] = fut
    _PENDING_CLOUD_WS[(session_id, tunnel_id)] = (websocket, grant.grant_id)

    try:
        # tiny control-plane push -- no bulk data, cannot head-of-line-block
        # (or be blocked by) command/reply traffic on this same socket.
        await connector_websocket.send_json({
            "type": "tunnel-open",
            "tunnel_id": tunnel_id,
            "purpose": purpose,
            "endpoint": endpoint,
        })
        reply = await asyncio.wait_for(fut, timeout=TUNNEL_OPEN_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        sess.pending_tunnels.pop(tunnel_id, None)
        _PENDING_CLOUD_WS.pop((session_id, tunnel_id), None)
        await websocket.send_json({"type": "tunnel-open-ack", "ok": False, "error": "Connector did not respond to the tunnel request."})
        await _safe_close(websocket, 4504)
        return
    except Exception:
        sess.pending_tunnels.pop(tunnel_id, None)
        _PENDING_CLOUD_WS.pop((session_id, tunnel_id), None)
        await websocket.send_json({"type": "tunnel-open-ack", "ok": False, "error": "Could not reach the connector."})
        await _safe_close(websocket, 4500)
        return

    if reply.get("type") != "tunnel-attached":
        # the connector explicitly refused (tunnel-error) -- its data socket
        # never attaches, so nothing else to clean up beyond the pending entry.
        _PENDING_CLOUD_WS.pop((session_id, tunnel_id), None)
        await websocket.send_json({
            "type": "tunnel-open-ack", "ok": False,
            "error": (reply.get("error") or "The connector refused this tunnel.")[:200],
        })
        await _safe_close(websocket, 4403)
        return

    # by now tunnel_data_ws has already populated _LIVE_TUNNELS /
    # _LIVE_TUNNEL_CONNECTOR_WS and consumed the _PENDING_CLOUD_WS entry.
    await websocket.send_json({"type": "tunnel-open-ack", "ok": True})

    try:
        while True:
            raw = await websocket.receive()
            if raw.get("type") == "websocket.disconnect":
                break
            data = raw.get("bytes")
            if data is None:
                # a stray text frame on the data leg is ignored, never
                # parsed as a command -- this socket is a pure byte pipe
                # for exactly one tunnel after the handshake above.
                continue
            connector_data_ws = _LIVE_TUNNEL_CONNECTOR_WS.get((session_id, tunnel_id))
            if connector_data_ws is None:
                break
            try:
                await connector_data_ws.send_bytes(data)
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    finally:
        _LIVE_TUNNELS.pop((session_id, tunnel_id), None)
        data_ws = _LIVE_TUNNEL_CONNECTOR_WS.pop((session_id, tunnel_id), None)
        if data_ws is not None:
            await _safe_close(data_ws, 4410)


# ---------------------------------------------------------------------------
# connector plane -- private-service tunnel (data socket, connector side)
# ---------------------------------------------------------------------------
@app.websocket("/connector/tunnel-data/{session_id}")
async def tunnel_data_ws(websocket: WebSocket, session_id: str):
    """Opened by the Connector itself (never the cloud side, never a
    browser) in response to a ``tunnel-open`` push on its control socket --
    one new connection per tunnel, authenticated with the SAME
    ``session_secret`` the control socket uses. This is the piece that
    keeps a tunnel's data flow from ever sharing a read loop with Remote-
    mode RPC command dispatch.
    """
    await websocket.accept()

    sess = _SESSIONS.get(session_id)
    if sess is None or sess.superseded or sess.expired:
        await _safe_close(websocket, 4404)
        return

    try:
        hello = await asyncio.wait_for(websocket.receive_json(), timeout=15)
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError):
        await _safe_close(websocket, 4401)
        return

    if hello.get("type") != "tunnel-data-auth" or not constant_time_equal(hello.get("secret"), sess.session_secret):
        await _safe_close(websocket, 4401)
        return

    tunnel_id = hello.get("tunnel_id")
    cloud_ws, grant_id = _PENDING_CLOUD_WS.pop((session_id, tunnel_id), (None, None))
    if cloud_ws is None:
        # no matching pending open (stale, unknown, duplicate, or the cloud
        # side already gave up) -- refuse rather than attach to nothing.
        await _safe_close(websocket, 4404)
        return

    _LIVE_TUNNELS[(session_id, tunnel_id)] = (cloud_ws, grant_id)
    _LIVE_TUNNEL_CONNECTOR_WS[(session_id, tunnel_id)] = websocket

    fut = sess.pending_tunnels.pop(tunnel_id, None)
    if fut is not None and not fut.done():
        fut.set_result({"type": "tunnel-attached"})

    try:
        while True:
            raw = await websocket.receive()
            if raw.get("type") == "websocket.disconnect":
                break
            data = raw.get("bytes")
            if data is None:
                continue
            try:
                await cloud_ws.send_bytes(data)
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    finally:
        _LIVE_TUNNEL_CONNECTOR_WS.pop((session_id, tunnel_id), None)
        # the connector's LOCAL half of this tunnel ended (EOF, error, or
        # this socket simply closing) -- end the cloud side too rather than
        # leave it open with nothing to talk to. No message is sent for
        # this; closing the socket IS the signal.
        if _LIVE_TUNNELS.pop((session_id, tunnel_id), None) is not None:
            await _safe_close(cloud_ws, 4410)


# ---------------------------------------------------------------------------
# public -- coarse status (no secret, no owner)
# ---------------------------------------------------------------------------
@app.get("/connector/status/{session_id}")
def connector_status(session_id: str):
    sess = _SESSIONS.get(session_id)
    if sess is None:
        return {"session_id": session_id, "online": False, "state": "unknown"}
    return {
        "session_id": session_id,
        "online": bool(sess.connected and not sess.superseded and not sess.expired),
        "state": sess.state(),
    }


# ---------------------------------------------------------------------------
# removed -- global "attach to newest session" discovery
# ---------------------------------------------------------------------------
@app.get("/connector/latest")
def latest_session_removed():
    raise HTTPException(
        status_code=410,
        detail=(
            "Global connector discovery has been removed. Pair the connector "
            "with a pairing code from the Connector Setup page."
        ),
    )


def _reset_state_for_tests() -> None:
    """Clear all relay state (test helper)."""
    _SESSIONS.clear()
    _LIVE_WS.clear()
    _TUNNEL_GRANTS.clear()
    _LIVE_TUNNELS.clear()
    _LIVE_TUNNEL_CONNECTOR_WS.clear()
    _PENDING_CLOUD_WS.clear()
