from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable


@dataclass
class RemoteRuntimeCallbacks:
    check: Callable
    status: Callable
    terminate: Callable


def build_remote_runtime_callbacks(
    *,
    runtime_status,
    log_output,
    status_widget,
    status_html,
    bridge_factory,
    experiment_bridge,
    experiment_update_from_job_status,
    on_status_result=None,
) -> RemoteRuntimeCallbacks:
    def _render_connection(label, result, *, show_ok=False):
        with log_output:
            print(label)
            if show_ok:
                print("ok:", result.get("ok"))
            print("returncode:", result.get("returncode"))
            if (result.get("stdout") or "").strip():
                print("--- stdout ---")
                print(result["stdout"].strip())
            if (result.get("stderr") or "").strip():
                print("--- stderr ---")
                print(result["stderr"].strip())

    def on_check(_=None):
        log_output.clear_output()
        status_widget.value = status_html("running")
        try:
            bridge = bridge_factory()
            result = bridge.check_environment()
            if bridge.mode == "direct":
                _render_connection("[direct] Test SSH", result)
            elif bridge.mode == "connector":
                _render_connection("[connector] Test SSH via relay", result, show_ok=True)
            elif result.get("transport") == "direct" and result.get("ok"):
                _render_connection("[auto] Direct SSH works.", result)
            elif result.get("connector_missing"):
                with log_output:
                    print("[auto] Direct SSH failed.")
                    print("[connector][ERROR] No connector session found for fallback.")
                    print("--- direct stderr ---")
                    print((result.get("stderr") or "").strip())
                status_widget.value = status_html("fail")
                return
            else:
                _render_connection(
                    "[auto] Direct SSH failed. Used connector fallback.",
                    result,
                    show_ok=True,
                )
            status_widget.value = status_html("done" if result.get("ok") else "fail")
        except Exception as error:
            status_widget.value = status_html("fail")
            with log_output:
                if "No connector session" in str(error):
                    print("[connector][ERROR] No connector session found.")
                    print("Create/start a connector session first.")
                else:
                    print("[remote][ERROR]", type(error).__name__, error)

    def on_status(_=None):
        log_output.clear_output()
        job_id = runtime_status.get("jobid")
        if not job_id:
            with log_output:
                print("[remote] No JobID yet. Submit first.")
            return
        try:
            bridge = bridge_factory()
            status = bridge.status(job_id=str(job_id))
            if on_status_result is not None:
                on_status_result(str(job_id), status.state)
            result = status.metadata
            experiment_update = experiment_update_from_job_status(result)
            if experiment_update:
                experiment_bridge.update_by_job(job_id=str(job_id), **experiment_update)
            with log_output:
                print("[connector] Status" if bridge.mode == "connector" else "[remote] Status")
                if result.get("source") == "squeue":
                    print("--- squeue ---")
                else:
                    print("(squeue empty; using Slurm accounting)")
                    print("--- sacct ---")
                output = result.get("stdout") or ""
                print(
                    (output or "(no status output)")
                    if bridge.mode == "connector"
                    else output.strip() or "(no status output)"
                )
                if experiment_update:
                    print()
                    print("[experiment] CryoStack status:", experiment_update["status"])
            status_widget.value = status_html("done" if result.get("returncode") == 0 else "fail")
        except Exception as error:
            status_widget.value = status_html("fail")
            with log_output:
                print("[remote][ERROR]", type(error).__name__, error)

    def on_terminate(_=None):
        log_output.clear_output()
        job_id = runtime_status.get("jobid")
        if not job_id:
            with log_output:
                print("[remote] No JobID found.")
            return
        try:
            bridge = bridge_factory()
            result = bridge.terminate(job_id=str(job_id))
            with log_output:
                if bridge.mode == "connector":
                    print("[connector] Cancel job")
                    print("ok:", result.get("ok"))
                    print("returncode:", result.get("returncode"))
                    if (result.get("stdout") or "").strip():
                        print("--- stdout ---")
                        print(result["stdout"].strip())
                    if (result.get("stderr") or "").strip():
                        print("--- stderr ---")
                        print(result["stderr"].strip())
                else:
                    print("returncode:", result["returncode"])
                    if (result["stdout"] or "").strip():
                        print(result["stdout"].strip())
                    if (result["stderr"] or "").strip():
                        print(result["stderr"].strip())
            status_widget.value = status_html("done" if result.get("ok") else "fail")
        except Exception as error:
            status_widget.value = status_html("fail")
            with log_output:
                print("[remote][ERROR]", type(error).__name__, error)

    return RemoteRuntimeCallbacks(check=on_check, status=on_status, terminate=on_terminate)
