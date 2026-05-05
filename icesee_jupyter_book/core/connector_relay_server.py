from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel


app = FastAPI(title="ICESEE Connector Relay")

SESSIONS: dict[str, WebSocket] = {}
PENDING: dict[str, dict[str, asyncio.Future]] = {}
SESSION_ORDER: list[str] = []
class CommandRequest(BaseModel):
    command_type: str
    payload: dict[str, Any] = {}


@app.post("/connector/session")
def create_session():
    session_id = uuid.uuid4().hex
    PENDING[session_id] = {}
    SESSION_ORDER.append(session_id)

    return {
        "session_id": session_id,
        "ws_url": f"/connector/ws/{session_id}",
    }


@app.get("/connector/status/{session_id}")
def connector_status(session_id: str):
    return {
        "session_id": session_id,
        "online": session_id in SESSIONS,
    }


@app.websocket("/connector/ws/{session_id}")
async def connector_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()

    SESSIONS[session_id] = websocket
    PENDING.setdefault(session_id, {})

    try:
        while True:
            msg = await websocket.receive_json()

            command_id = msg.get("command_id")
            if command_id and command_id in PENDING.get(session_id, {}):
                fut = PENDING[session_id].pop(command_id)
                if not fut.done():
                    fut.set_result(msg)

    except WebSocketDisconnect:
        pass

    finally:
        if SESSIONS.get(session_id) is websocket:
            SESSIONS.pop(session_id, None)


@app.post("/connector/command/{session_id}")
async def send_command(session_id: str, req: CommandRequest):
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Connector is not online")

    command_id = uuid.uuid4().hex
    fut = asyncio.get_running_loop().create_future()

    PENDING.setdefault(session_id, {})[command_id] = fut

    await SESSIONS[session_id].send_json({
        "command_id": command_id,
        "command_type": req.command_type,
        "payload": req.payload,
    })

    try:
        result = await asyncio.wait_for(fut, timeout=120)
        return result

    except asyncio.TimeoutError:
        PENDING[session_id].pop(command_id, None)
        raise HTTPException(status_code=504, detail="Connector command timed out")

@app.get("/connector/latest")
def latest_session():
    if not SESSION_ORDER:
        return {"ok": False, "error": "No connector session has been created yet."}

    sid = SESSION_ORDER[-1]

    return {
        "ok": True,
        "session_id": sid,
        "ws_url": f"/connector/ws/{sid}",
        "online": sid in SESSIONS,
    }