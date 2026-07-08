from __future__ import annotations

import shlex
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
        "https://cryostack.eas.gatech.edu",
        "http://cryostack.eas.gatech.edu",
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

class SSHRunRequest(BaseModel):
    host: str
    user: str
    port: int = 22
    command: str
    timeout: int = 60

class RsyncUploadRequest(BaseModel):
    host: str
    user: str
    port: int = 22
    local_path: str
    remote_path: str
    timeout: int = 300


class RsyncDownloadRequest(BaseModel):
    host: str
    user: str
    port: int = 22
    remote_path: str
    local_path: str
    timeout: int = 300

class SlurmSubmitRequest(BaseModel):
    host: str
    user: str
    port: int = 22
    remote_script: str
    timeout: int = 60


class SlurmStatusRequest(BaseModel):
    host: str
    user: str
    port: int = 22
    jobid: str
    timeout: int = 60


class SlurmCancelRequest(BaseModel):
    host: str
    user: str
    port: int = 22
    jobid: str
    timeout: int = 60


class TailLogRequest(BaseModel):
    host: str
    user: str
    port: int = 22
    remote_file: str
    nlines: int = 120
    timeout: int = 60

# helper function to run shell commands with timeout and capture output
def run_command(cmd: list[str], timeout: int = 300):
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

# MVP: a  generic shell endpoint.
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

@app.post("/ssh-run")
def ssh_run(req: SSHRunRequest):
    ssh_cmd = [
        "ssh",
        "-p", str(req.port),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        f"{req.user}@{req.host}",
        req.command,
    ]

    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=req.timeout,
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

@app.post("/rsync-upload")
def rsync_upload(req: RsyncUploadRequest):
    """
    Upload local_path from the user's workstation to remote_path on HPC.
    """
    cmd = [
        "rsync",
        "-az",
        "-e",
        f"ssh -p {req.port} -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
        req.local_path,
        f"{req.user}@{req.host}:{req.remote_path}",
    ]

    return run_command(cmd, timeout=req.timeout)


@app.post("/rsync-download")
def rsync_download(req: RsyncDownloadRequest):
    """
    Download remote_path from HPC to local_path on the user's workstation.
    """
    cmd = [
        "rsync",
        "-az",
        "-e",
        f"ssh -p {req.port} -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
        f"{req.user}@{req.host}:{req.remote_path}",
        req.local_path,
    ]

    return run_command(cmd, timeout=req.timeout)

@app.post("/slurm-submit")
def slurm_submit(req: SlurmSubmitRequest):
    cmd = f"sbatch {shlex.quote(req.remote_script)}"

    result = ssh_run(
        SSHRunRequest(
            host=req.host,
            user=req.user,
            port=req.port,
            command=cmd,
            timeout=req.timeout,
        )
    )

    jobid = None
    stdout = result.get("stdout", "") or ""

    for line in stdout.splitlines():
        line = line.strip()
        if "Submitted batch job" in line:
            jobid = line.split()[-1]
            break

    result["jobid"] = jobid
    result["submitted"] = bool(jobid)

    return result


@app.post("/slurm-status")
def slurm_status(req: SlurmStatusRequest):
    cmd = (
        f"squeue -j {shlex.quote(req.jobid)} "
        f"-o '%.18i %.9P %.40j %.8u %.2t %.10M %.6D %R' || "
        f"sacct -j {shlex.quote(req.jobid)} --format=JobID,JobName,State,Elapsed,ExitCode"
    )

    return ssh_run(
        SSHRunRequest(
            host=req.host,
            user=req.user,
            port=req.port,
            command=cmd,
            timeout=req.timeout,
        )
    )


@app.post("/slurm-cancel")
def slurm_cancel(req: SlurmCancelRequest):
    cmd = f"scancel {shlex.quote(req.jobid)}"

    return ssh_run(
        SSHRunRequest(
            host=req.host,
            user=req.user,
            port=req.port,
            command=cmd,
            timeout=req.timeout,
        )
    )

@app.post("/tail-log")
def tail_log(req: TailLogRequest):
    safe_file = shlex.quote(req.remote_file)
    nlines = max(1, min(int(req.nlines), 500))

    cmd = f"""
if [ -f {safe_file} ]; then
    echo "[connector] file: {req.remote_file}"
    echo "--- tail ---"
    tail -n {nlines} {safe_file}
else
    echo "[connector] log file not found: {req.remote_file}"
    parent=$(dirname {safe_file})
    echo "[connector] parent directory:"
    ls -lah "$parent" 2>/dev/null || true
fi
"""

    return ssh_run(
        SSHRunRequest(
            host=req.host,
            user=req.user,
            port=req.port,
            command=cmd,
            timeout=req.timeout,
        )
    )