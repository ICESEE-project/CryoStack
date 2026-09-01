"""CryoStack Connector relay -- session-scoped, capability-authenticated (v2).

Identifiers vs. capabilities
----------------------------
``session_id``     non-secret; names a pairing session; may appear in URLs/logs.
``control_secret`` per session, high entropy. Authorises the browser/gateway ->
                   relay control plane (issue command, owner-scoped status).
                   Returned only to the CryoStack kernel that created the session.
``session_secret`` per session, high entropy. Authorises a connector's WebSocket
                   registration. Delivered to the connector only through the
                   one-time pairing exchange -- never in a URL or query string.
``pairing_code``   short, one-time, short-TTL. The connector exchanges it once
                   for ``{session_id, session_secret}``.
``owner_user_id``  the authenticated CryoStack user that created the session.

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
                                 relay replies ``{"type":"auth_ok"}``.
``POST /connector/command/{id}`` (control)   ``Authorization: Bearer <control_secret>``
                                 + body ``{owner_user_id, command_type, payload}``.
``GET  /connector/status/{id}``  (public)    coarse ``{session_id, online, state}``.
``GET  /connector/latest``       REMOVED -> ``410 Gone``.

Every control/connector operation fails closed: unknown session, wrong/blank
secret, expired or superseded session, or a disconnected connector all return an
error and never dispatch. Secrets and pairing codes are never logged, and the
global "attach to the newest session anywhere" behaviour is gone -- a connector
reaches a session only by holding that session's pairing capability.
"""
from __future__ import annotations

import asyncio
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


# session_id -> Session  (non-secret key)
_SESSIONS: dict[str, Session] = {}
# session_id -> live connector WebSocket
_LIVE_WS: dict[str, WebSocket] = {}


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
# connector plane -- authenticated WebSocket registration
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
        while True:
            msg = await websocket.receive_json()
            command_id = msg.get("command_id")
            if command_id and command_id in sess.pending:
                fut = sess.pending.pop(command_id)
                if not fut.done():
                    fut.set_result(msg)
    except WebSocketDisconnect:
        pass
    finally:
        if _LIVE_WS.get(session_id) is websocket:
            _LIVE_WS.pop(session_id, None)
            sess.connected = False


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
