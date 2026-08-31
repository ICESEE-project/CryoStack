from __future__ import annotations

import base64
import re
import shlex
from collections.abc import Callable

import cryostack_src.remote.spack_env as spack_env
from cryostack_src.execution.backend import ExecutionResult, ExecutionStatus
from cryostack_src.execution.remote import RemoteBackend
from cryostack_src.remote.spack_env import EnvReport, EnvStatus, SetupSlurmOpts
from icesee_jupyter_book.core.connector_relay_client import send_command
from icesee_jupyter_book.core.remote_runner import (
    connector_slurm_submit,
    connector_ssh,
    remote_cancel_job,
    remote_job_status,
    remote_test_connection,
    ssh_run,
)


class RemoteBridge:
    """Widget-free gateway API for direct and connector-backed execution."""

    def __init__(
        self,
        *,
        mode: str,
        host: str,
        user: str,
        port: int,
        session_id: str | None = None,
        cluster_name: str = "pace",
        direct_submitter: Callable | None = None,
        connector_submitter: Callable | None = None,
    ) -> None:
        self.mode = mode
        self.host = host
        self.user = user
        self.port = int(port)
        self.session_id = session_id
        self.cluster_name = cluster_name
        self.direct_submitter = direct_submitter
        self.connector_submitter = connector_submitter

    def submit(self, *, direct_kwargs: dict, connector_kwargs: dict) -> ExecutionResult:
        use_connector = self.mode == "connector"
        submitter = self.connector_submitter if use_connector else self.direct_submitter
        if submitter is None:
            raise RuntimeError("Remote submitter has not been configured.")
        kwargs = connector_kwargs if use_connector else direct_kwargs
        return RemoteBackend(submitter=submitter).submit(**kwargs)

    def status(self, *, job_id: str) -> ExecutionStatus:
        if self.mode != "connector":
            status = RemoteBackend().status(
                job_id=job_id,
                host=self.host,
                user=self.user,
                port=self.port,
            )
            status.metadata.update(
                state=status.raw_state,
                exit_code=status.exit_code,
            )
            return status
        result = self._connector_status(job_id)
        raw_state = (result.get("state") or "").strip()
        return ExecutionStatus(
            state=RemoteBackend._normalize_state(raw_state),
            raw_state=raw_state,
            exit_code=result.get("exit_code"),
            metadata=result,
        )

    def logs(self, *, job_id: str, remote_dir: str, log_file: str | None = None):
        log_file = log_file or f"{remote_dir}/icesheets-{job_id}.out"
        command = self._tail_command(remote_dir, log_file)
        if self.mode == "connector":
            response = send_command(
                self._require_session(),
                "ssh-run",
                {
                    "host": self.host,
                    "user": self.user,
                    "port": self.port,
                    "command": command,
                    "timeout": 30,
                },
            )
            return response.get("result", response)
        result = ssh_run(self.host, self.user, self.port, command, timeout=30)
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def terminate(self, *, job_id: str):
        if self.mode == "connector":
            return connector_ssh(
                self._require_session(),
                self.host,
                self.user,
                self.port,
                f"scancel {job_id}",
                timeout=300,
                cluster_name=self.cluster_name,
            )
        return remote_cancel_job(self.host, self.user, self.port, job_id)

    def check_environment(self):
        if self.mode == "direct":
            return remote_test_connection(self.host, self.user, self.port)
        if self.mode == "connector":
            return self._connector_check()
        direct = remote_test_connection(self.host, self.user, self.port)
        if direct.get("ok"):
            return {**direct, "transport": "direct"}
        if not self.session_id:
            return {**direct, "transport": "direct", "connector_missing": True}
        return {**self._connector_check(), "transport": "connector", "direct": direct}

    def uses_connector(self) -> bool:
        if self.mode == "connector":
            return True
        if self.mode == "direct":
            return False
        try:
            return not remote_test_connection(self.host, self.user, self.port).get("ok", False)
        except Exception:
            return True

    def check_backend(self, *, command: str, timeout: int = 120) -> dict:
        if self.mode == "connector":
            return connector_ssh(
                self._require_session(),
                self.host,
                self.user,
                self.port,
                command,
                timeout=timeout,
                cluster_name=self.cluster_name,
            )
        result = ssh_run(self.host, self.user, self.port, command, timeout=timeout)
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def prepare_environment(self, **kwargs):
        preparer = kwargs.pop("preparer", None)
        if preparer is None:
            raise RuntimeError("Remote environment preparer has not been configured.")
        return preparer(**kwargs)

    # ------------------------------------------------------------------
    # ICESEE-Spack environment lifecycle (Remote backend)
    # ------------------------------------------------------------------
    def _run_script(self, script: str, *, timeout: int = 180) -> dict:
        """Run a shell script on the resource over the active transport."""
        return self.check_backend(command=script, timeout=timeout)

    def resolve_remote_base(self, path: str) -> str:
        """Expand ~ and resolve to an absolute remote path (both transports)."""
        expr = f"import os,sys; print(os.path.abspath(os.path.expanduser({path!r})))"
        res = self._run_script(f"python3 -c {shlex.quote(expr)}", timeout=60)
        out = (res.get("stdout") or "").strip().splitlines()
        if not res.get("ok") or not out:
            raise RuntimeError(
                f"Could not resolve remote base dir {path!r}: "
                f"{(res.get('stderr') or res.get('stdout') or '').strip()}"
            )
        return out[-1].strip()

    def _write_remote_file(self, remote_path: str, text: str) -> None:
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        writer = (
            "import base64, pathlib; "
            f"p = pathlib.Path({remote_path!r}); "
            "p.parent.mkdir(parents=True, exist_ok=True); "
            f"p.write_text(base64.b64decode({encoded!r}).decode('utf-8'), encoding='utf-8'); "
            "print(str(p))"
        )
        res = self._run_script(f"python3 -c {shlex.quote(writer)}", timeout=60)
        if not res.get("ok"):
            raise RuntimeError(
                "Failed to write remote file "
                f"{remote_path}: {(res.get('stderr') or res.get('stdout') or '').strip()}"
            )

    def environment_status(
        self,
        *,
        model: str,
        remote_base: str,
        spack_dirname: str = spack_env.DEFAULT_SPACK_DIRNAME,
        base_is_absolute: bool = False,
    ) -> EnvReport:
        """Fast, live readiness probe for ICESEE-Spack + the selected model."""
        base_abs = remote_base if base_is_absolute else self.resolve_remote_base(remote_base)
        paths = spack_env.spack_paths(base_abs, spack_dirname)
        res = self._run_script(
            spack_env.probe_script(model=model, paths=paths), timeout=180
        )
        return spack_env.classify_probe(
            res.get("stdout") or "", model=model, ok=bool(res.get("ok"))
        )

    def submit_spack_setup_job(
        self,
        *,
        model: str,
        remote_base: str,
        setup_dir: str | None = None,
        spack_dirname: str = spack_env.DEFAULT_SPACK_DIRNAME,
        repo_url: str = spack_env.DEFAULT_SPACK_REPO,
        slurm: SetupSlurmOpts | None = None,
        matlab_license: dict | None = None,
        base_is_absolute: bool = False,
    ) -> dict:
        """Stage + sbatch the durable ICESEE-Spack setup job. Returns immediately."""
        base_abs = remote_base if base_is_absolute else self.resolve_remote_base(remote_base)
        paths = spack_env.spack_paths(base_abs, spack_dirname)
        setup_dir = (setup_dir or f"{base_abs.rstrip('/')}/ICESEE-Spack-setup").rstrip("/")
        script = spack_env.install_sbatch_text(
            model=model, paths=paths, setup_dir=setup_dir,
            repo_url=repo_url, slurm=slurm, matlab_license=matlab_license,
        )
        script_path = f"{setup_dir}/spack_setup.sbatch"
        self._run_script(f"mkdir -p {shlex.quote(setup_dir)}", timeout=60)
        self._write_remote_file(script_path, script)

        job_id = self._sbatch(script_path)
        return {
            "job_id": job_id,
            "setup_dir": setup_dir,
            "log_file": f"{setup_dir}/spack-setup-{job_id}.out",
            "spack_repo": paths.repo,
        }

    def _sbatch(self, script_path: str) -> str:
        if self.mode == "connector":
            res = connector_slurm_submit(
                self._require_session(), self.host, self.user, self.port,
                script_path, timeout=60,
            )
            if not res.get("ok") or not res.get("submitted"):
                raise RuntimeError(
                    "Failed to submit setup job through connector: "
                    f"{(res.get('stderr') or res.get('stdout') or '').strip()}"
                )
            return str(res["jobid"])
        res = ssh_run(self.host, self.user, self.port,
                      f"sbatch {shlex.quote(script_path)}", timeout=60)
        if res.returncode != 0:
            raise RuntimeError(f"sbatch failed: {(res.stderr or res.stdout).strip()}")
        m = re.search(r"Submitted batch job\s+(\d+)", res.stdout or "")
        if not m:
            raise RuntimeError(f"Could not parse setup job id from: {res.stdout!r}")
        return m.group(1)

    def prepare_spack_environment(
        self,
        *,
        model: str,
        remote_base: str,
        setup_dir: str | None = None,
        spack_dirname: str = spack_env.DEFAULT_SPACK_DIRNAME,
        repo_url: str = spack_env.DEFAULT_SPACK_REPO,
        slurm: SetupSlurmOpts | None = None,
        matlab_license: dict | None = None,
    ) -> dict:
        """Probe first (decision 4). If Ready, reuse. Otherwise sbatch a setup job.

        Never runs a synchronous multi-hour install: the build is a Slurm job and
        this returns as soon as it is queued.
        """
        base_abs = self.resolve_remote_base(remote_base)
        report = self.environment_status(
            model=model, remote_base=base_abs,
            spack_dirname=spack_dirname, base_is_absolute=True,
        )
        if report.is_ready:
            return {"status": EnvStatus.READY, "reused": True, "report": report}

        job = self.submit_spack_setup_job(
            model=model, remote_base=base_abs, setup_dir=setup_dir,
            spack_dirname=spack_dirname, repo_url=repo_url, slurm=slurm,
            matlab_license=matlab_license, base_is_absolute=True,
        )
        return {"status": EnvStatus.INSTALLING, "reused": False, "job": job,
                "previous": report}

    def _connector_check(self):
        response = send_command(
            self._require_session(),
            "ssh-run",
            {
                "host": self.host,
                "user": self.user,
                "port": self.port,
                "command": "hostname && whoami && pwd",
                "timeout": 30,
            },
        )
        return response.get("result", response)

    def _connector_status(self, job_id: str) -> dict:
        command = f"""
        set +e
        live=$(squeue -j {job_id} -h -o '%i|%T|%M|%D|%R' 2>/dev/null)
        if [ -n "$live" ]; then
            echo "__CRYOSTACK_SOURCE__=squeue"
            echo "$live"
            exit 0
        fi
        echo "__CRYOSTACK_SOURCE__=sacct"
        sacct -j {job_id} --noheader --parsable2 --format=JobIDRaw,State,ExitCode
        exit $?
        """
        response = send_command(
            self._require_session(), "ssh-run",
            {"host": self.host, "user": self.user, "port": self.port, "command": command, "timeout": 30},
        )
        payload = response.get("result", response)
        lines = [line.strip() for line in (payload.get("stdout") or "").splitlines() if line.strip()]
        source = None
        status_lines = []
        for line in lines:
            if line == "__CRYOSTACK_SOURCE__=squeue":
                source = "squeue"
            elif line == "__CRYOSTACK_SOURCE__=sacct":
                source = "sacct"
            else:
                status_lines.append(line)
        state = exit_code = None
        if source == "squeue" and status_lines:
            parts = status_lines[0].split("|")
            state = parts[1].strip() if len(parts) > 1 else None
        elif source == "sacct":
            for line in status_lines:
                parts = line.split("|")
                if len(parts) >= 3 and parts[0].strip() == str(job_id):
                    state, exit_code = parts[1].strip(), parts[2].strip()
                    break
        return {
            "source": source,
            "state": state,
            "exit_code": exit_code,
            "stdout": "\n".join(status_lines),
            "stderr": payload.get("stderr", ""),
            "returncode": payload.get("returncode", 0 if payload.get("ok") else 1),
        }

    def _require_session(self) -> str:
        if not self.session_id:
            raise RuntimeError("No connector session found.")
        return self.session_id

    @staticmethod
    def _tail_command(remote_dir: str, log_file: str) -> str:
        return f'''
set -e
log_file="{log_file}"
run_dir="{remote_dir}"

echo "[remote] checking run dir: $run_dir"
if [ -d "$run_dir" ]; then
    echo "[remote] run dir exists"
else
    echo "[remote] run dir missing"
fi

if [ -f "$log_file" ]; then
    echo "[remote] file: $log_file"
    echo "--- tail ---"
    tail -n 120 "$log_file"
else
    echo "[remote] log file not found yet: $log_file"
    echo
    echo "[remote] contents of run dir:"
    ls -lah "$run_dir" || true
fi
'''
