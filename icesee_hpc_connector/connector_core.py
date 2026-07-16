from __future__ import annotations

import argparse
import asyncio
import json
import shlex
# from jupyter_server_terminals import msg
from click import command
import requests
import subprocess

import websockets

# DEFAULT_RELAY = "https://cryolauncher.com"
DEFAULT_RELAY = "https://cryostack.eas.gatech.edu"

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
    
def ssh_identity_args(cluster_name="pace"):
    priv, _ = ensure_local_ssh_key(cluster_name=cluster_name)
    return ["-i", priv]
    
async def run_ssh(payload: dict):
    host = payload["host"]
    user = payload["user"]
    port = int(payload.get("port", 22))
    command = payload["command"]
    timeout = int(payload.get("timeout", 60))

    cluster_name = payload.get("cluster_name", "pace")

    ssh_cmd = [
        "ssh",
        *ssh_identity_args(cluster_name),
        "-p", str(port),
        "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes",
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
        "-e", f"ssh -i {shlex.quote(ensure_local_ssh_key(payload.get('cluster_name', 'pace'))[0])} "
        f"-p {port} -o BatchMode=yes -o IdentitiesOnly=yes "
        f"-o StrictHostKeyChecking=accept-new",
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
    
    if command_type == "bootstrap-passwordless-ssh":
        return await bootstrap_passwordless_ssh_local(payload)
    
    if command_type == "get-public-key":
        return await get_public_key_local(payload)

    return {
        "ok": False,
        "error": f"Unsupported command_type: {command_type}",
    }


async def main(ws_url: str, relay: str = DEFAULT_RELAY, poll_seconds: int = 5):
    print(f"[connector] connecting to {ws_url}")

    async with websockets.connect(ws_url) as ws:
        print("[connector] connected")

        async def watch_for_newer_session():
            while True:
                await asyncio.sleep(poll_seconds)

                try:
                    latest = resolve_ws_url(relay=relay, session=None, ws_url=None)

                    if latest and latest != ws_url:
                        print("[connector] newer ICESEE session detected")
                        print("[connector] old:", ws_url)
                        print("[connector] new:", latest)
                        await ws.close()
                        return

                except Exception as e:
                    print("[connector] session watcher error:", type(e).__name__, e)

        watcher = asyncio.create_task(watch_for_newer_session())

        try:
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

        finally:
            watcher.cancel()

async def run_rsync_upload(payload: dict):
    local_path = payload["local_path"]
    remote_path = payload["remote_path"]
    host = payload["host"]
    user = payload["user"]
    port = int(payload.get("port", 22))
    timeout = int(payload.get("timeout", 300))

    cmd = [
        "rsync", "-az",
        "-e", f"ssh -i {shlex.quote(ensure_local_ssh_key(payload.get('cluster_name', 'pace'))[0])} "
        f"-p {port} -o BatchMode=yes -o IdentitiesOnly=yes "
        f"-o StrictHostKeyChecking=accept-new",
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
        "cluster_name": payload.get("cluster_name", "pace"),
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
                    f"ssh -i {shlex.quote(ensure_local_ssh_key(payload.get('cluster_name', 'pace'))[0])} "
                    f"-p {port} -o BatchMode=yes -o IdentitiesOnly=yes "
                    f"-o StrictHostKeyChecking=accept-new",
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
                    f"ssh -i {shlex.quote(ensure_local_ssh_key(payload.get('cluster_name', 'pace'))[0])} "
                    f"-p {port} -o BatchMode=yes -o IdentitiesOnly=yes "
                    f"-o StrictHostKeyChecking=accept-new",
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

def resolve_ws_url(relay: str, session: str | None = None, ws_url: str | None = None):
    if ws_url:
        return ws_url

    relay = relay.rstrip("/")

    if session:
        relay_ws_base = relay.replace("http://", "ws://").replace("https://", "wss://")
        return f"{relay_ws_base}/connector/ws/{session}"

    try:
        response = requests.get(f"{relay}/connector/latest", timeout=10)

        if response.status_code != 200:
            print("[connector] relay returned status:", response.status_code)
            print("[connector] response preview:", response.text[:120])
            return None

        # try:
        #     resp = response.json()
        # except Exception:
        #     print("[connector] relay did not return JSON")
        #     print("[connector] response preview:", response.text[:120])
        #     return None
        try:
            resp = response.json()
        except Exception as e:
            print("[connector][ERROR] Failed to parse JSON response")
            print("[connector][ERROR] URL:", response.url)
            print("[connector][ERROR] status:", response.status_code)
            print("[connector][ERROR] content-type:", response.headers.get("content-type"))
            print("[connector][ERROR] text:")
            print(response.text[:1000])
            raise

        print("[connector] latest response:", resp)

        if not resp.get("ok"):
            return None

        relay_ws_base = relay.replace("http://", "ws://").replace("https://", "wss://")
        return f"{relay_ws_base}{resp['ws_url']}"

    except Exception as e:
        print("[connector] could not contact relay:", type(e).__name__, e)
        return None


def run_connector(
    relay: str = DEFAULT_RELAY,
    session: str | None = None,
    ws_url: str | None = None,
    poll: bool = True,
    poll_seconds: int = 5,
):
    
    import pathlib, datetime

    LOG_FILE = pathlib.Path.home() / "icesee_connector.log"

    def log(msg):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a") as f:
            f.write(f"[{ts}] {msg}\n")
        print(msg)

    while True:
        target = resolve_ws_url(relay=relay, session=session, ws_url=ws_url)

        if not target:
            if not poll:
                print("[connector] No active session found.")
                return

            print(f"[connector] waiting for ICESEE session... retrying in {poll_seconds}s")
            import time
            time.sleep(poll_seconds)
            continue

        print("[connector] using ws_url:", target)

        try:
            asyncio.run(main(target, relay=relay, poll_seconds=poll_seconds))
        except KeyboardInterrupt:
            print("[connector] stopped")
            return
        except Exception as e:
            print("[connector] disconnected:", type(e).__name__, e)

        if not poll:
            return

        print(f"[connector] reconnecting in {poll_seconds}s")
        import time
        time.sleep(poll_seconds)

def ensure_local_ssh_key(cluster_name="pace", key_type="ed25519"):
    from pathlib import Path
    import subprocess, os, getpass

    ssh_dir = Path.home() / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(ssh_dir, 0o700)

    priv = ssh_dir / f"id_{key_type}_icesee_{cluster_name}"
    pub = Path(str(priv) + ".pub")

    if not priv.exists() or not pub.exists():
        subprocess.run(
            [
                "ssh-keygen",
                "-t", key_type,
                "-f", str(priv),
                "-N", "",
                "-C", f"icesee-{cluster_name}-{getpass.getuser()}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        os.chmod(priv, 0o600)
        os.chmod(pub, 0o644)

    return str(priv), str(pub)

async def bootstrap_passwordless_ssh_local(payload):
    try:
        import paramiko
        import subprocess

        host = payload["host"]
        user = payload["user"]
        port = int(payload.get("port", 22))
        password = payload["password"]
        cluster_name = payload.get("cluster_name", "pace")

        priv, pub = ensure_local_ssh_key(cluster_name=cluster_name)
        pubkey_text = open(pub, "r", encoding="utf-8").read().strip()

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=host,
            port=port,
            username=user,
            password=password,
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
            banner_timeout=15,
            auth_timeout=15,
        )

        quoted_key = shlex.quote(pubkey_text)

        cmd = f"""
    set -e
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh
    touch ~/.ssh/authorized_keys
    chmod 600 ~/.ssh/authorized_keys
    grep -Fqx {quoted_key} ~/.ssh/authorized_keys || echo {quoted_key} >> ~/.ssh/authorized_keys
    echo OK
    """
        stdin, stdout, stderr = client.exec_command(cmd)
        out = stdout.read().decode()
        err = stderr.read().decode()
        rc = stdout.channel.recv_exit_status()
        client.close()

        if rc != 0:
            return {"ok": False, "stdout": out, "stderr": err, "private_key": priv, "public_key": pub}

        test = subprocess.run(
            [
                "ssh",
                "-i", priv,
                "-p", str(port),
                "-o", "BatchMode=yes",
                "-o", "IdentitiesOnly=yes",
                "-o", "StrictHostKeyChecking=accept-new",
                f"{user}@{host}",
                "hostname && whoami && date",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

        return {
            "ok": test.returncode == 0,
            "returncode": test.returncode,
            "stdout": test.stdout,
            "stderr": test.stderr,
            "private_key": priv,
            "public_key": pub,
            "messages": [
                "[auth] Connector bootstrap selected.",
                "[auth] Creating/installing SSH key on the local connector machine.",
                f"[auth] private key: {priv}",
                f"[auth] public key : {pub}",
                "[auth] Testing passwordless SSH through connector.",
            ],
        }
    except Exception as e:
        cluster_name = payload.get("cluster_name", "pace")

        priv, pub = ensure_local_ssh_key(
            cluster_name=cluster_name
        )

        pub_text = ""

        try:
            with open(pub, "r", encoding="utf-8") as f:
                pub_text = f.read().strip()

        except Exception:
            pub_text = ""

        messages = [
            "[ssh] Automatic key installation did not complete.",
            "[ssh] Some clusters require SSH keys to be added through a web portal.",
            "",
            "[ssh] Step 1: Copy the public key below.",
            pub_text or f"[ssh][ERROR] Could not read public key file: {pub}",
            "",
            "[ssh] Step 2: Open your cluster SSH key portal.",
            "[ssh] Step 3: Paste and save the key.",
            "[ssh] Step 4: Return here and click Test SSH.",
            "[ssh] Step 5: Continue using Key-only mode.",
        ]

        return {
            "ok": False,
            "stage": "bootstrap_exception",
            "error": f"{type(e).__name__}: {e}",
            "private_key": str(priv),
            "public_key": str(pub),
            "public_key_text": pub_text,
            "messages": messages,
        }

def main_auto():
    run_connector(relay=DEFAULT_RELAY, poll=True)

async def get_public_key_local(payload: dict):
    cluster_name = payload.get("cluster_name", "pace")
    priv, pub = ensure_local_ssh_key(cluster_name=cluster_name)

    return {
        "ok": True,
        "private_key": priv,
        "public_key": pub,
        "public_key_text": open(pub, "r", encoding="utf-8").read().strip(),
        "messages": [
            "[ssh] Connector SSH key ready.",
            f"[ssh] private key: {priv}",
            f"[ssh] public key : {pub}",
            "[ssh] If automatic bootstrap fails, copy the public key text into your cluster SSH key portal.",
        ],
    }