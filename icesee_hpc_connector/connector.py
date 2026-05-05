from __future__ import annotations

import socket
import subprocess
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

APP_VERSION = "0.1.0"

app = FastAPI(title="ICESEE HPC Bridge Connector", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://cryolauncher.com",
        "http://cryolauncher.com",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HostCheckRequest(BaseModel):
    host: str
    port: int = 22
    timeout: float = 3.0


class ShellRequest(BaseModel):
    command: str
    timeout: int = 60


@app.get("/status")
def status():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "name": "ICESEE HPC Bridge Connector",
        "message": "Connector is running",
    }


@app.post("/check-host")
def check_host(req: HostCheckRequest):
    try:
        with socket.create_connection((req.host, req.port), timeout=req.timeout):
            return {
                "ok": True,
                "reachable": True,
                "host": req.host,
                "port": req.port,
            }
    except Exception as e:
        return {
            "ok": False,
            "reachable": False,
            "host": req.host,
            "port": req.port,
            "error": str(e),
        }


@app.post("/shell")
def shell(req: ShellRequest):
    """
    MVP only. Later we should restrict allowed commands.
    """
    result = subprocess.run(
        ["bash", "-lc", req.command],
        capture_output=True,
        text=True,
        timeout=req.timeout,
    )

    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
