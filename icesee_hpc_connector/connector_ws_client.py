from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import requests
import subprocess

import websockets


async def run_shell(payload: dict):
    command = payload.get("command", "")
    timeout = int(payload.get("timeout", 60))

    try:
        result = subprocess.run(
            ["bash", "-lc", command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": command,
        }

    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": e.stdout or "",
            "stderr": e.stderr or "Command timed out",
            "command": command,
        }

async def run_subprocess(cmd: list[str], timeout: int = 300):
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": " ".join(shlex.quote(x) for x in cmd),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": e.stdout or "",
            "stderr": e.stderr or "Command timed out",
            "command": " ".join(shlex.quote(x) for x in cmd),
        }
    
async def run_ssh(payload: dict):
    host = payload["host"]
    user = payload["user"]
    port = int(payload.get("port", 22))
    command = payload["command"]
    timeout = int(payload.get("timeout", 60))

    ssh_cmd = [
        "ssh",
        "-p", str(port),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
        command,
    ]

    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": " ".join(shlex.quote(x) for x in ssh_cmd),
        }

    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": e.stdout or "",
            "stderr": e.stderr or "SSH command timed out",
            "command": " ".join(shlex.quote(x) for x in ssh_cmd),
        }
async def run_rsync_download(payload: dict):
    remote_path = payload["remote_path"]
    local_path = payload["local_path"]
    host = payload["host"]
    user = payload["user"]
    port = int(payload.get("port", 22))
    timeout = int(payload.get("timeout", 300))

    cmd = [
        "rsync", "-az",
        "-e", f"ssh -p {port} -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
        f"{user}@{host}:{remote_path}",
        local_path,
    ]

    return await run_subprocess(cmd, timeout)

async def handle_command(command_type: str, payload: dict):
    if command_type == "shell":
        return await run_shell(payload)

    if command_type == "ssh-run":
        return await run_ssh(payload)

    if command_type == "rsync-upload":
        return await run_rsync_upload(payload)

    if command_type == "slurm-submit":
        return await run_slurm_submit(payload)
    
    if command_type == "rsync-download":
        return await run_rsync_download(payload)

    return {
        "ok": False,
        "error": f"Unsupported command_type: {command_type}",
    }


async def main(ws_url: str):
    print(f"[connector] connecting to {ws_url}")

    async with websockets.connect(ws_url) as ws:
        print("[connector] connected")

        async for raw in ws:
            msg = json.loads(raw)

            command_id = msg.get("command_id")
            command_type = msg.get("command_type")
            payload = msg.get("payload", {})

            result = await handle_command(command_type, payload)

            await ws.send(json.dumps({
                "command_id": command_id,
                "command_type": command_type,
                "result": result,
            }))

async def run_rsync_upload(payload: dict):
    local_path = payload["local_path"]
    remote_path = payload["remote_path"]
    host = payload["host"]
    user = payload["user"]
    port = int(payload.get("port", 22))
    timeout = int(payload.get("timeout", 300))

    cmd = [
        "rsync", "-az",
        "-e", f"ssh -p {port} -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
        local_path,
        f"{user}@{host}:{remote_path}",
    ]

    return await run_subprocess(cmd, timeout)


async def run_slurm_submit(payload: dict):
    remote_script = payload["remote_script"]
    host = payload["host"]
    user = payload["user"]
    port = int(payload.get("port", 22))
    timeout = int(payload.get("timeout", 60))

    cmd = f"sbatch {shlex.quote(remote_script)}"
    result = await run_ssh({
        "host": host,
        "user": user,
        "port": port,
        "command": cmd,
        "timeout": timeout,
    })

    jobid = None
    for line in (result.get("stdout") or "").splitlines():
        if "Submitted batch job" in line:
            jobid = line.split()[-1]
            break

    result["jobid"] = jobid
    result["submitted"] = bool(jobid)
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # parser.add_argument("--ws-url", required=True)
    parser.add_argument("--ws-url", default=None)
    parser.add_argument("--relay", default="http://127.0.0.1:8899")
    parser.add_argument("--session", default=None)
    args = parser.parse_args()

    # asyncio.run(main(args.ws_url))
    if args.ws_url:
        ws_url = args.ws_url
    elif args.session:
        relay_ws_base = args.relay.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{relay_ws_base}/connector/ws/{args.session}"
    else:
        resp = requests.get(f"{args.relay}/connector/latest", timeout=5).json()
        
        print("[connector] latest response:", resp)

        if not resp.get("ok"):
            print("[connector] No active session found.")
            exit(1)

        relay_ws_base = args.relay.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{relay_ws_base}{resp['ws_url']}"

    print("[connector] using ws_url:", ws_url)
    asyncio.run(main(ws_url))