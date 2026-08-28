from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class CloudRuntimeCallbacks:
    status: Callable
    logs: Callable
    terminate: Callable


def build_cloud_runtime_callbacks(
    *,
    runtime_status,
    log_output,
    status_widget,
    status_html,
    bridge_factory,
) -> CloudRuntimeCallbacks:
    def on_status(_=None):
        log_output.clear_output()
        job_id = runtime_status.get("batch_job_id")
        if not job_id:
            with log_output:
                print("[cloud] No Batch job id yet. Submit first.")
            return
        try:
            result = bridge_factory().status(job_id=str(job_id))
            with log_output:
                print("[cloud] Job status")
                print("state:", result.state)
                if result.raw_state:
                    print("AWS state:", result.raw_state)
                if result.reason:
                    print("reason:", result.reason)
            status_widget.value = status_html("done")
        except Exception as error:
            status_widget.value = status_html("fail")
            with log_output:
                print("[cloud][ERROR]", type(error).__name__, error)

    def on_logs(_=None):
        log_output.clear_output()
        job_id = runtime_status.get("batch_job_id")
        if not job_id:
            with log_output:
                print("[cloud] No Batch job id yet. Submit first.")
            return
        try:
            result = bridge_factory().logs(job_id=str(job_id))
            with log_output:
                print("[cloud] Logs")
                if isinstance(result, dict):
                    log_text = (
                        result.get("logs")
                        or result.get("log")
                        or result.get("message")
                        or ""
                    )
                    print(log_text or "(no log output)")
                else:
                    print(result or "(no log output)")
            status_widget.value = status_html("done")
        except Exception as error:
            status_widget.value = status_html("fail")
            with log_output:
                print("[cloud][ERROR]", type(error).__name__, error)

    def on_terminate(_=None):
        log_output.clear_output()
        job_id = runtime_status.get("batch_job_id")
        if not job_id:
            with log_output:
                print("[cloud] No Batch job id yet. Submit first.")
            return
        try:
            result = bridge_factory().terminate(job_id=str(job_id))
            with log_output:
                print("[cloud] Termination requested.")
                if result:
                    print(result)
            status_widget.value = status_html("done")
        except Exception as error:
            status_widget.value = status_html("fail")
            with log_output:
                print("[cloud][ERROR]", type(error).__name__, error)

    return CloudRuntimeCallbacks(
        status=on_status,
        logs=on_logs,
        terminate=on_terminate,
    )
