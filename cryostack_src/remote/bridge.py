from __future__ import annotations

from collections.abc import Callable

from cryostack_src.execution.backend import ExecutionResult, ExecutionStatus
from cryostack_src.execution.remote import RemoteBackend
from icesee_jupyter_book.core.connector_relay_client import send_command
from icesee_jupyter_book.core.remote_runner import (
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
            return RemoteBackend().status(
                job_id=job_id,
                host=self.host,
                user=self.user,
                port=self.port,
            )
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

    def prepare_environment(self, **kwargs):
        preparer = kwargs.pop("preparer", None)
        if preparer is None:
            raise RuntimeError("Remote environment preparer has not been configured.")
        return preparer(**kwargs)

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
