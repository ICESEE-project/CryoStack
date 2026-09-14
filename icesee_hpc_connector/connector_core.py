from __future__ import annotations

import asyncio
import json
import shlex
import subprocess

import requests
import websockets


def _noop(*_a, **_k) -> None:
    """Default lifecycle-event sink."""

# DEFAULT_RELAY = "https://cryolauncher.com"
DEFAULT_RELAY = "https://cryostack.eas.gatech.edu"

# Connector <-> relay pairing protocol. Bumped when the wire protocol changes in
# a way that makes an older connector unable to pair (e.g. ea0a70d: capability
# secrets + a one-time pairing code replaced the old global "newest session"
# discovery). build_connector.sh stamps this into every artifact's .build.json
# so the release pipeline never publishes an incompatible binary as current.
PAIRING_PROTOCOL = "v2"

async def _run(cmd, *, timeout: int):
    """Run a blocking subprocess off the event loop (keeps the worker's async
    loop -- and any stop-watcher -- responsive during long SSH operations)."""
    return await asyncio.to_thread(
        subprocess.run, cmd, capture_output=True, text=True, timeout=timeout
    )


async def run_shell(payload: dict):
    command = payload.get("command", "")
    timeout = int(payload.get("timeout", 60))

    try:
        result = await _run(["bash", "-lc", command], timeout=timeout)

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
        result = await _run(cmd, timeout=timeout)
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
    
def ssh_identity_args(payload):
    """``payload`` is the command payload (cluster_name/user/host) so the key
    is namespaced by resource + HPC identity, not cluster name alone."""
    priv, _ = ensure_local_ssh_key(
        cluster_name=payload.get("cluster_name", "pace"),
        hpc_user=payload.get("user", ""),
        host=payload.get("host", ""),
    )
    return ["-i", priv]
    
async def run_ssh(payload: dict):
    host = payload["host"]
    user = payload["user"]
    port = int(payload.get("port", 22))
    command = payload["command"]
    timeout = int(payload.get("timeout", 60))

    ssh_cmd = [
        "ssh",
        *ssh_identity_args(payload),
        "-p", str(port),
        "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
        command,
    ]

    try:
        result = await _run(ssh_cmd, timeout=timeout)

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
        "-e", f"ssh -i {shlex.quote(ensure_local_ssh_key(payload.get('cluster_name', 'pace'), hpc_user=payload.get('user', ''), host=payload.get('host', ''))[0])} "
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


class PairingRejected(RuntimeError):
    """The relay refused this connector's session credential -- do not retry."""


# WebSocket close codes the relay uses to reject a connector permanently.
_TERMINAL_WS_CODES = {4401, 4404, 4409}


_SSH_COMMANDS = {
    "ssh-run", "rsync-upload", "rsync-download", "slurm-submit",
    "stage-archive", "fetch-archive", "bootstrap-passwordless-ssh",
}


async def main(ws_url: str, session_secret: str, poll_seconds: int = 5,
               *, stop_event=None, on_event=_noop):
    print(f"[connector] connecting to {ws_url}")

    # Bounded connect: a stalled TLS/WS handshake must not hang the worker.
    ws = await asyncio.wait_for(
        websockets.connect(ws_url, open_timeout=20, close_timeout=5, ping_interval=20),
        timeout=25,
    )

    # Close the socket promptly when asked to stop, so the reconnect loop and
    # Quit do not have to wait for a network timeout.
    async def _watch_stop():
        while stop_event is not None and not stop_event.is_set():
            await asyncio.sleep(0.25)
        try:
            await ws.close(code=1001)
        except Exception:
            pass

    watcher = asyncio.create_task(_watch_stop()) if stop_event is not None else None
    try:
        await ws.send(json.dumps({"type": "auth", "secret": session_secret}))
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        except (asyncio.TimeoutError, ValueError) as e:
            raise PairingRejected(f"no auth acknowledgement from relay ({e})")
        if hello.get("type") != "auth_ok":
            raise PairingRejected(hello.get("type") or "relay rejected the session secret")

        print("[connector] authenticated to session", hello.get("session_id"))
        on_event("websocket-connected")

        async for raw in ws:
            if stop_event is not None and stop_event.is_set():
                break
            msg = json.loads(raw)
            if "command_id" not in msg and "command_type" not in msg:
                continue

            command_id = msg.get("command_id")
            command_type = msg.get("command_type")
            payload = msg.get("payload", {})

            is_ssh = command_type in _SSH_COMMANDS
            if is_ssh:
                on_event("ssh-command-start")
            try:
                result = await handle_command(command_type, payload)
            finally:
                if is_ssh:
                    on_event("ssh-command-complete")

            await ws.send(json.dumps({
                "command_id": command_id,
                "command_type": command_type,
                "result": result,
            }))
    finally:
        if watcher is not None:
            watcher.cancel()
        try:
            await ws.close()
        except Exception:
            pass
        on_event("websocket-disconnected")

async def run_rsync_upload(payload: dict):
    local_path = payload["local_path"]
    remote_path = payload["remote_path"]
    host = payload["host"]
    user = payload["user"]
    port = int(payload.get("port", 22))
    timeout = int(payload.get("timeout", 300))

    cmd = [
        "rsync", "-az",
        "-e", f"ssh -i {shlex.quote(ensure_local_ssh_key(payload.get('cluster_name', 'pace'), hpc_user=payload.get('user', ''), host=payload.get('host', ''))[0])} "
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
                    f"ssh -i {shlex.quote(ensure_local_ssh_key(payload.get('cluster_name', 'pace'), hpc_user=payload.get('user', ''), host=payload.get('host', ''))[0])} "
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
                    f"ssh -i {shlex.quote(ensure_local_ssh_key(payload.get('cluster_name', 'pace'), hpc_user=payload.get('user', ''), host=payload.get('host', ''))[0])} "
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

def _relay_ws_base(relay: str) -> str:
    return relay.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")


def pair_session(relay: str, pairing_code: str) -> dict | None:
    """Exchange a one-time pairing code for ``{session_id, session_secret}``.

    Returns ``None`` when the code is wrong, already used, or expired.
    """
    code = (pairing_code or "").strip()
    if not code:
        return None
    try:
        resp = requests.post(
            f"{relay.rstrip('/')}/connector/pair",
            json={"pairing_code": code},
            timeout=15,
        )
    except Exception as e:
        print("[connector] could not reach relay to pair:", type(e).__name__, e)
        return None

    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    return data if data.get("ok") and data.get("session_secret") else None


def resolve_ws_url(relay: str, session: str | None = None, ws_url: str | None = None):
    """Build the connector WebSocket URL. No global session discovery."""
    if ws_url:
        return ws_url
    if session:
        return f"{_relay_ws_base(relay)}/connector/ws/{session}"
    return None


def run_connector(
    relay: str = DEFAULT_RELAY,
    pairing_code: str | None = None,
    session: str | None = None,
    session_secret: str | None = None,
    ws_url: str | None = None,
    poll: bool = True,
    poll_seconds: int = 5,
    *,
    stop_event=None,
    on_event=None,
):
    """Blocking pair + connect + reconnect loop. Meant to run on a background
    thread. ``stop_event`` (a ``threading.Event``) interrupts every wait and
    closes the socket. ``on_event(name)`` receives non-secret lifecycle names.
    """
    import time

    on_event = on_event or _noop

    def _stopped() -> bool:
        return stop_event is not None and stop_event.is_set()

    # Resolve the session + secret exactly once. A connector reaches a session
    # only by holding that session's pairing capability -- never by asking the
    # relay for "the latest session".
    if not session_secret and pairing_code:
        on_event("pairing-request-start")
        paired = pair_session(relay, pairing_code)
        on_event("pairing-request-complete")
        if not paired:
            print("[connector] Pairing failed: the pairing code is invalid or expired.")
            print("[connector] Open the Connector Setup page for a fresh code.")
            return
        session = paired["session_id"]
        session_secret = paired["session_secret"]

    if not (session and session_secret):
        print("[connector] No pairing code provided.")
        print("[connector] Open the Connector Setup page, copy your pairing code,")
        print("[connector] and pair the connector with it.")
        return

    target = ws_url or resolve_ws_url(relay=relay, session=session)
    print("[connector] session:", session)

    while not _stopped():
        on_event("websocket-thread-start")
        try:
            asyncio.run(main(
                target, session_secret=session_secret, poll_seconds=poll_seconds,
                stop_event=stop_event, on_event=on_event,
            ))
        except KeyboardInterrupt:
            print("[connector] stopped")
            return
        except PairingRejected as e:
            print("[connector] session is no longer valid:", e)
            print("[connector] Re-pair from the Connector Setup page.")
            return
        except Exception as e:
            code = getattr(e, "code", None)
            if code in _TERMINAL_WS_CODES:
                print("[connector] relay closed the session (code", code, ") -- re-pair to continue.")
                return
            print("[connector] disconnected:", type(e).__name__, e)

        if not poll or _stopped():
            return

        print(f"[connector] reconnecting in {poll_seconds}s")
        if stop_event is not None:
            stop_event.wait(poll_seconds)          # interruptible
        else:
            time.sleep(poll_seconds)

def _credential_namespace(cluster_name: str, hpc_user: str = "", host: str = "") -> str:
    """B3: fold (resource, HPC username[, host]) into one safe, deterministic
    key name. Deliberately self-contained (no cryostack_src import) -- the
    connector is packaged and distributed standalone."""
    import hashlib
    import re

    parts = [p.strip() for p in (cluster_name, hpc_user, host) if p and p.strip()]
    if not parts:
        return "unscoped"
    joined = "|".join(p.lower() for p in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9]+", "-", parts[0].lower()).strip("-")[:24] or "resource"
    return f"{slug}-{digest}"


def ensure_local_ssh_key(cluster_name="pace", key_type="ed25519", *, hpc_user="", host=""):
    """The credential is namespaced by resource + HPC identity, not cluster
    name alone -- two people using this workstation for different HPC
    accounts never share a key. The OLD cluster-only key
    (``~/.ssh/id_<type>_icesee_<cluster>``) is never read or adopted here; if
    present it is simply orphaned, and a fresh, correctly-scoped key is
    generated (the user re-registers/re-bootstraps it)."""
    from pathlib import Path
    import subprocess, os, getpass

    namespace = _credential_namespace(cluster_name, hpc_user, host)

    ssh_dir = Path.home() / ".ssh" / "cryostack"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(ssh_dir, 0o700)

    priv = ssh_dir / f"id_{key_type}_{namespace}"
    pub = Path(str(priv) + ".pub")

    if not priv.exists() or not pub.exists():
        subprocess.run(
            [
                "ssh-keygen",
                "-t", key_type,
                "-f", str(priv),
                "-N", "",
                "-C", f"cryostack-{namespace}-{getpass.getuser()}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        os.chmod(priv, 0o600)
        os.chmod(pub, 0o644)

    return str(priv), str(pub)

#: machine-readable outcomes of a password-bootstrap attempt. The gateway maps
#: these to explicit UI states -- a bare exception string must never be the only
#: thing the user gets back.
BOOTSTRAP_OK = "ok"
BOOTSTRAP_PARAMIKO_MISSING = "paramiko_missing"
BOOTSTRAP_PASSWORD_AUTH_FAILED = "password_auth_failed"
BOOTSTRAP_CONNECT_FAILED = "connect_failed"
BOOTSTRAP_INSTALL_FAILED = "install_failed"
BOOTSTRAP_VERIFY_FAILED = "verify_failed"


def _bootstrap_passwordless_ssh_sync(host, user, port, password, cluster_name):
    """Blocking password-bootstrap. Returns a dict that always carries a
    ``reason`` (one of the ``BOOTSTRAP_*`` constants). Only the PUBLIC key ever
    leaves this machine; the private key stays on the workstation.
    """
    priv, pub = ensure_local_ssh_key(cluster_name=cluster_name, hpc_user=user, host=host)
    try:
        pubkey_text = open(pub, "r", encoding="utf-8").read().strip()
    except Exception as e:  # pragma: no cover - unreadable key file
        return {"ok": False, "reason": BOOTSTRAP_INSTALL_FAILED,
                "error": f"could not read public key: {e}",
                "private_key": priv, "public_key": pub}

    try:
        import paramiko
    except Exception as e:
        return {
            "ok": False,
            "reason": BOOTSTRAP_PARAMIKO_MISSING,
            "error": f"{type(e).__name__}: {e}",
            "private_key": priv, "public_key": pub, "public_key_text": pubkey_text,
            "messages": [
                "[auth] This Connector build cannot do password bootstrap "
                "(the SSH library is missing).",
                "[auth] Register the public key below with your resource, then "
                "Check SSH Access.",
                pubkey_text,
            ],
        }

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=host, port=int(port), username=user, password=password,
            look_for_keys=False, allow_agent=False,
            timeout=15, banner_timeout=15, auth_timeout=20,
        )
    except paramiko.AuthenticationException as e:
        return {"ok": False, "reason": BOOTSTRAP_PASSWORD_AUTH_FAILED,
                "error": f"{type(e).__name__}: {e}",
                "private_key": priv, "public_key": pub}
    except Exception as e:   # socket timeout, SSHException, DNS, refused, ...
        return {"ok": False, "reason": BOOTSTRAP_CONNECT_FAILED,
                "error": f"{type(e).__name__}: {e}",
                "private_key": priv, "public_key": pub}

    quoted_key = shlex.quote(pubkey_text)
    cmd = (
        "set -e\n"
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh\n"
        "touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys\n"
        f"grep -Fqx {quoted_key} ~/.ssh/authorized_keys || echo {quoted_key} >> ~/.ssh/authorized_keys\n"
        "echo OK\n"
    )
    try:
        _stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
    except Exception as e:
        client.close()
        return {"ok": False, "reason": BOOTSTRAP_INSTALL_FAILED,
                "error": f"{type(e).__name__}: {e}",
                "private_key": priv, "public_key": pub}
    finally:
        try:
            client.close()
        except Exception:
            pass

    if rc != 0:
        return {"ok": False, "reason": BOOTSTRAP_INSTALL_FAILED,
                "stdout": out, "stderr": err,
                "private_key": priv, "public_key": pub}

    try:
        test = subprocess.run(
            ["ssh", "-i", priv, "-p", str(int(port)),
             "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
             "-o", "StrictHostKeyChecking=accept-new",
             f"{user}@{host}", "hostname && whoami && date"],
            capture_output=True, text=True, timeout=25,
        )
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "reason": BOOTSTRAP_VERIFY_FAILED,
                "stdout": e.stdout or "", "stderr": e.stderr or "verify timed out",
                "private_key": priv, "public_key": pub, "key_installed": True}

    return {
        "ok": test.returncode == 0,
        "reason": BOOTSTRAP_OK if test.returncode == 0 else BOOTSTRAP_VERIFY_FAILED,
        "returncode": test.returncode,
        "stdout": test.stdout,
        "stderr": test.stderr,
        "private_key": priv,
        "public_key": pub,
        "key_installed": True,
        "messages": [
            "[auth] Connector bootstrap: public key installed on the resource.",
            f"[auth] public key : {pub}",
        ],
    }


async def bootstrap_passwordless_ssh_local(payload):
    host = payload.get("host", "")
    user = payload.get("user", "")
    port = int(payload.get("port", 22))
    password = payload.get("password", "")
    cluster_name = payload.get("cluster_name", "pace")

    if not host or not user or not password:
        return {"ok": False, "reason": BOOTSTRAP_CONNECT_FAILED,
                "error": "host, user and password are all required for bootstrap"}

    try:
        return await asyncio.to_thread(
            _bootstrap_passwordless_ssh_sync, host, user, port, password, cluster_name
        )
    except Exception as e:  # pragma: no cover - defensive
        return {"ok": False, "reason": BOOTSTRAP_CONNECT_FAILED,
                "error": f"{type(e).__name__}: {e}"}

def main_auto():
    """Entry point for the packaged connector: pair from CRYOSTACK_PAIRING_CODE."""
    import os

    code = (os.environ.get("CRYOSTACK_PAIRING_CODE") or "").strip()
    run_connector(relay=DEFAULT_RELAY, pairing_code=code or None, poll=True)

async def get_public_key_local(payload: dict):
    cluster_name = payload.get("cluster_name", "pace")
    priv, pub = ensure_local_ssh_key(
        cluster_name=cluster_name,
        hpc_user=payload.get("user", ""),
        host=payload.get("host", ""),
    )

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