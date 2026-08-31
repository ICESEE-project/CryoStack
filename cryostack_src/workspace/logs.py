from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable


@dataclass
class WorkspaceLogs:
    on_tail: Callable
    on_auto_tail_change: Callable


def build_workspace_logs(
    *, status,
    session,
    auto_tail,
    log_output,
    status_widget,
    auto_tail_button,
    cluster_host,
    cluster_user,
    cluster_port,
    access_mode,
    normalize_remote_path,
    status_html,
    send_command,
    ssh_run,
    bridge_factory=None,
) -> WorkspaceLogs:
    def on_tail(_=None):
        with log_output:
            print("[debug] on_tail invoked")
        log_output.clear_output()

        remote_dir = normalize_remote_path(status.get("remote_dir") or "")
        jobid = status.get("jobid")
        if not remote_dir or not jobid:
            status_widget.value = status_html("fail")
            with log_output:
                print("[remote] No remote_dir / JobID yet. Submit first.")
            return

        log_file = status.get("log_file") or f"{remote_dir}/icesheets-{jobid}.out"
        log_file = normalize_remote_path(log_file)

        if bridge_factory is not None:
            try:
                bridge = bridge_factory()
                result = bridge.logs(
                    job_id=str(jobid),
                    remote_dir=remote_dir,
                    log_file=log_file,
                )
                with log_output:
                    if bridge.mode == "connector":
                        print("[connector] Tail log")
                    if (result.get("stdout") or "").strip():
                        print(result["stdout"].rstrip())
                    if (result.get("stderr") or "").strip():
                        print("--- stderr ---")
                        print(result["stderr"].strip())
                status_widget.value = status_html("done" if result.get("ok") else "fail")
            except Exception as error:
                status_widget.value = status_html("fail")
                with log_output:
                    print("[remote][ERROR]", type(error).__name__, error)
            return

        host = cluster_host.value.strip()
        user = cluster_user.value.strip()
        port = int(cluster_port.value)
        tail_cmd = f'''
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
        try:
            if access_mode.value == "connector":
                payload = send_command(
                    session["id"],
                    "ssh-run",
                    {"host": host, "user": user, "port": port, "command": tail_cmd, "timeout": 30},
                )
                result = payload.get("result", payload)
                with log_output:
                    print("[connector] Tail log")
                    if (result.get("stdout") or "").strip():
                        print(result["stdout"].rstrip())
                    if (result.get("stderr") or "").strip():
                        print("--- stderr ---")
                        print(result["stderr"].strip())
                status_widget.value = status_html("done" if result.get("ok") else "fail")
                return

            result = ssh_run(host, user, port, tail_cmd, timeout=30)
            with log_output:
                if (result.stdout or "").strip():
                    print(result.stdout.rstrip())
                if (result.stderr or "").strip():
                    print("--- stderr ---")
                    print(result.stderr.strip())
            status_widget.value = status_html("done" if result.returncode == 0 else "fail")
        except Exception as error:
            status_widget.value = status_html("fail")
            with log_output:
                print("[remote][ERROR]", type(error).__name__, error)

    async def auto_tail_worker():
        try:
            while auto_tail["running"]:
                await asyncio.to_thread(on_tail, None)
                for _ in range(20):
                    if not auto_tail["running"]:
                        return
                    await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            pass
        except Exception as error:
            with log_output:
                print("[auto-tail][ERROR]", type(error).__name__, error)
        finally:
            auto_tail["running"] = False
            auto_tail["task"] = None

    def on_auto_tail_change(change):
        if change.get("name") != "value":
            return
        if change["new"]:
            current_task = auto_tail.get("task")
            if current_task is not None and not current_task.done():
                return
            auto_tail["running"] = True
            auto_tail_button.description = "Stop auto tail"
            auto_tail_button.icon = "stop"
            auto_tail_button.button_style = "warning"
            loop = asyncio.get_running_loop()
            auto_tail["task"] = loop.create_task(auto_tail_worker())
        else:
            auto_tail["running"] = False
            task = auto_tail.get("task")
            if task is not None:
                task.cancel()
            auto_tail["task"] = None
            auto_tail_button.description = "Auto tail"
            auto_tail_button.icon = "refresh"
            auto_tail_button.button_style = "info"

    return WorkspaceLogs(on_tail=on_tail, on_auto_tail_change=on_auto_tail_change)
