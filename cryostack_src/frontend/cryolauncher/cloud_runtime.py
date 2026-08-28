from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class CloudRuntimeCallbacks:
    check_environment: Callable
    prepare_environment: Callable
    status: Callable
    logs: Callable
    terminate: Callable
    results: Callable


def build_cloud_runtime_callbacks(
    *,
    runtime_status,
    log_output,
    status_widget,
    status_html,
    bridge_factory,
    cloud_environment,
    set_cloud_status,
    bucket_value,
    results_output,
) -> CloudRuntimeCallbacks:
    def _update_environment(capabilities):
        states = (
            (cloud_environment.account_status, capabilities.authenticated, "Connected", "Not connected"),
            (cloud_environment.storage_status, capabilities.storage_ready, "Ready", "Not prepared"),
            (cloud_environment.registry_status, capabilities.registry_ready, "Ready", "Not prepared"),
            (cloud_environment.compute_status, capabilities.batch_ready, "Ready", "Not prepared"),
        )
        for widget, ready, ready_label, missing_label in states:
            set_cloud_status(
                widget,
                state="done" if ready else "fail",
                label=ready_label if ready else missing_label,
            )

    def on_check_environment(_=None):
        log_output.clear_output()
        status_widget.value = status_html("running")
        try:
            capabilities = bridge_factory().check_environment()
            _update_environment(capabilities)
            with log_output:
                print("[cloud] Environment check")
                for message in capabilities.messages:
                    print(message)
            status_widget.value = status_html("done" if capabilities.authenticated else "fail")
        except Exception as error:
            _mark_environment_failed()
            status_widget.value = status_html("fail")
            with log_output:
                print("[cloud][ERROR] AWS credentials or CLI connection are unavailable.")
                print(type(error).__name__, error)

    def on_prepare_environment(_=None):
        log_output.clear_output()
        status_widget.value = status_html("running")
        with log_output:
            print("[cloud] Preparing environment...")
        try:
            result = bridge_factory().prepare_environment(bucket=bucket_value() or None)
            capabilities = result.get("capabilities")
            if capabilities is not None:
                _update_environment(capabilities)
            with log_output:
                for message in result.get("messages", []):
                    print(message)
            status_widget.value = status_html("done" if result.get("success") else "fail")
        except Exception as error:
            _mark_environment_failed()
            status_widget.value = status_html("fail")
            with log_output:
                print("[cloud][ERROR] Could not prepare the cloud environment.")
                print(type(error).__name__, error)

    def _mark_environment_failed():
        for widget, label in (
            (cloud_environment.account_status, "Not connected"),
            (cloud_environment.storage_status, "Not prepared"),
            (cloud_environment.registry_status, "Not prepared"),
            (cloud_environment.compute_status, "Not prepared"),
        ):
            set_cloud_status(widget, state="fail", label=label)

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

    def on_results(_=None):
        results_output.clear_output()
        cloud_run = runtime_status.get("cloud_run")
        if not cloud_run:
            with results_output:
                print("[cloud] No cloud run location yet. Submit first.")
            return
        try:
            path = bridge_factory().results(s3_uri=str(cloud_run))
            with results_output:
                print("[cloud] Results synchronized:", path)
        except Exception as error:
            with results_output:
                print("[cloud][ERROR]", type(error).__name__, error)

    return CloudRuntimeCallbacks(
        check_environment=on_check_environment,
        prepare_environment=on_prepare_environment,
        status=on_status,
        logs=on_logs,
        terminate=on_terminate,
        results=on_results,
    )
