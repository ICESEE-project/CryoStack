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

    if command_type == "stage-archive":
        return await run_stage_archive(payload)

    if command_type == "fetch-archive":
        return await run_fetch_archive(payload)

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

async def run_stage_archive(payload: dict):
    import base64
    import tempfile
    from pathlib import Path

    host = payload["host"]
    user = payload["user"]
    port = int(payload.get("port", 22))
    archive_name = payload["archive_name"]
    archive_b64 = payload["archive_b64"]
    remote_dir = payload["remote_dir"]
    timeout = int(payload.get("timeout", 600))

    try:
        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / archive_name
            archive_path.write_bytes(base64.b64decode(archive_b64))

            mk = await run_ssh({
                "host": host,
                "user": user,
                "port": port,
                "command": f'mkdir -p "{remote_dir}"',
                "timeout": 60,
            })
            if not mk.get("ok"):
                mk["stage"] = "mkdir_remote_dir"
                return mk

            up = await run_subprocess(
                [
                    "rsync",
                    "-az",
                    "-e",
                    f"ssh -p {port} -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
                    str(archive_path),
                    f"{user}@{host}:{remote_dir}/",
                ],
                timeout=timeout,
            )
            if not up.get("ok"):
                up["stage"] = "rsync_archive"
                return up

            remote_archive = f"{remote_dir.rstrip('/')}/{archive_name}"
            ex = await run_ssh({
                "host": host,
                "user": user,
                "port": port,
                "command": f'cd "{remote_dir}" && tar -xzf "{remote_archive}" && ls -lah "{remote_dir}"',
                "timeout": timeout,
            })
            ex["stage"] = "extract_archive"
            return ex

    except Exception as e:
        return {
            "ok": False,
            "stage": "python_exception",
            "error": f"{type(e).__name__}: {e}",
        }

async def run_fetch_archive(payload: dict):
    import base64
    import tarfile
    import tempfile
    from pathlib import Path

    host = payload["host"]
    user = payload["user"]
    port = int(payload.get("port", 22))
    remote_path = payload["remote_path"].rstrip("/") + "/"
    timeout = int(payload.get("timeout", 600))

    try:
        with tempfile.TemporaryDirectory() as td:
            local_dir = Path(td) / "outputs"
            local_dir.mkdir(parents=True, exist_ok=True)

            down = await run_subprocess(
                [
                    "rsync",
                    "-az",
                    "-e",
                    f"ssh -p {port} -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
                    f"{user}@{host}:{remote_path}",
                    f"{local_dir}/",
                ],
                timeout=timeout,
            )

            if not down.get("ok"):
                down["stage"] = "rsync_remote_outputs"
                return down

            archive_path = Path(td) / "outputs.tar.gz"
            with tarfile.open(archive_path, "w:gz") as tar:
                for p in local_dir.rglob("*"):
                    if p.is_file():
                        tar.add(p, arcname=str(p.relative_to(local_dir)))

            archive_b64 = base64.b64encode(archive_path.read_bytes()).decode("ascii")

            return {
                "ok": True,
                "stage": "fetch_archive",
                "archive_name": "outputs.tar.gz",
                "archive_b64": archive_b64,
                "stdout": down.get("stdout", ""),
                "stderr": down.get("stderr", ""),
            }

    except Exception as e:
        return {
            "ok": False,
            "stage": "python_exception",
            "error": f"{type(e).__name__}: {e}",
        }

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