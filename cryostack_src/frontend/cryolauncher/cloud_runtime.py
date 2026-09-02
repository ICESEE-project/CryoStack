# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher Cloud Runtime Callbacks
# File        : cloud_runtime.py
#
# Description :
#     UI callbacks for the Cloud panel's environment operations (Test
#     connection / Prepare cloud / Infrastructure smoke test) and the
#     job-lifecycle buttons (status / logs / terminate / results).
#
#     The three environment operations mutate the same Cloud status chip and
#     the same Account/Storage/Containers/Compute rows, so they share ONE
#     non-blocking coordinator: it owns the busy UI state, the mutual-exclusion
#     guard, task scheduling and finally-cleanup. It owns no AWS/S3/Batch
#     semantics -- the worker callables do.
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from cryostack_src.frontend.cryolauncher.cloud_run_controller import (
    classify_cloud_failure,
)


def _report(log_output, error, *, prefix="[cloud][ERROR]"):
    """Print a short actionable line plus the full detail for the log."""
    short, detail = classify_cloud_failure(error)
    with log_output:
        print(prefix, short)
        print("[cloud][detail]", detail)


def _spawn(coro):
    """Schedule ``coro`` on the running event loop, or run it to completion when
    there is none (tests / print mode). Mirrors ``CloudRunController._spawn``."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        return loop.create_task(coro)
    return asyncio.run(coro)


# ── the shared environment-operation coordinator ─────────────────────────
#: op -> (chip kind, active-button busy label, {row-key: busy label})
_BUSY = {
    "test": ("testing", "Testing…", {"account": "Checking…"}),
    "prepare": ("preparing", "Preparing…", {
        "account": "Checking…", "storage": "Preparing…",
        "registry": "Preparing…", "compute": "Preparing…"}),
    "smoke": ("smoke_testing", "Testing…", {
        "account": "Checking…", "storage": "Checking…",
        "registry": "Checking…", "compute": "Checking…"}),
}
#: op -> the rows that operation actually checks (marked Failed on failure).
#: 'test' only establishes identity, so it must not claim the other rows failed.
_FAILURE_ROWS = {
    "test": ("account",),
    "prepare": ("account", "storage", "registry", "compute"),
    "smoke": ("account", "storage", "registry", "compute"),
}


@dataclass
class CloudEnvironmentOps:
    test_connection: Callable
    prepare_cloud: Callable
    smoke_test: Callable
    #: True while any of the three is running (for callers / tests)
    is_busy: Callable[[], bool]


def build_cloud_environment_ops(
    *,
    buttons: dict,            # {"test": W.Button, "prepare": W.Button, "smoke": W.Button}
    rows: dict,               # {"account"/"storage"/"registry"/"compute": W.HTML}
    set_row: Callable,        # (widget, *, state, label) -> None
    set_chip: Callable,       # (_CLOUD_STATES kind) -> None
    status_widget=None,       # optional top-right run chip
    status_html=None,
    log_output=None,
    to_thread: Callable = asyncio.to_thread,
    spawn: Callable = _spawn,
) -> CloudEnvironmentOps:
    """A UI-only, non-blocking coordinator for the three Cloud environment
    operations. Every AWS call runs inside a worker via ``to_thread``; widgets
    are only touched on the event loop (before scheduling and in ``on_success``
    / failure handling)."""

    #: the state of the three buttons captured at the START of the current
    #: operation (NOT at build time -- a button may legitimately have been
    #: disabled between build and this click).
    _original: dict = {}
    _inflight = {"op": None}

    def is_busy() -> bool:
        return _inflight["op"] is not None

    def _capture_buttons() -> None:
        _original.clear()
        for name, b in buttons.items():
            _original[name] = {
                "description": b.description,
                "icon": b.icon,
                "button_style": b.button_style,
                "disabled": b.disabled,
            }

    def _apply_busy(op: str) -> None:
        chip_kind, busy_label, row_labels = _BUSY[op]
        set_chip(chip_kind)
        for key, label in row_labels.items():
            if key in rows:
                set_row(rows[key], state="running", label=label)
        for name, b in buttons.items():
            b.disabled = True
            if name == op:
                b.description = busy_label
                b.icon = "spinner"

    def _restore_buttons() -> None:
        for name, b in buttons.items():
            o = _original[name]
            b.description = o["description"]
            b.icon = o["icon"]
            b.button_style = o["button_style"]
            b.disabled = o["disabled"]

    def _mark_rows_failed(op: str) -> None:
        for key in _FAILURE_ROWS.get(op, ()):
            if key in rows:
                set_row(rows[key], state="fail", label="Failed")

    def _run_op(
        op: str,
        *,
        worker: Callable,
        on_success: Callable,
        failure_prefix: str,
        precheck: Callable | None = None,
    ) -> None:
        # 1. mutual exclusion -- synchronous, protects the re-entrant / programmatic
        #    path too (button.disabled only protects the mouse-click path).
        if _inflight["op"] is not None:
            return
        # 2. a cheap local pre-check (e.g. config validation) runs BEFORE any
        #    busy state or guard is taken.
        if precheck is not None:
            problems = precheck() or []
            if problems:
                if log_output is not None:
                    log_output.clear_output()
                    with log_output:
                        print(f"[cloud][{op}] fix the configuration first:")
                        for p in problems:
                            print("  -", p)
                return
        _inflight["op"] = op
        _capture_buttons()                       # exact pre-operation state
        if log_output is not None:
            log_output.clear_output()
        if status_widget is not None and status_html is not None:
            status_widget.value = status_html("running")
        # 3. busy UI applied NOW, before any AWS work.
        _apply_busy(op)

        async def _drive() -> None:
            try:
                result = await to_thread(worker)      # worker returns data only
                on_success(result)                    # widget mutation, on the loop
            except Exception as error:                # noqa: BLE001
                set_chip("failed")
                _mark_rows_failed(op)
                if status_widget is not None and status_html is not None:
                    status_widget.value = status_html("fail")
                if log_output is not None:
                    _report(log_output, error, prefix=failure_prefix)
            finally:
                _inflight["op"] = None
                _restore_buttons()

        spawn(_drive())

    # -- the three operations ------------------------------------------
    def test_connection(worker: Callable, on_success: Callable) -> None:
        _run_op("test", worker=worker, on_success=on_success,
                failure_prefix="[cloud][ERROR] AWS access check failed:")

    def prepare_cloud(worker: Callable, on_success: Callable) -> None:
        _run_op("prepare", worker=worker, on_success=on_success,
                failure_prefix="[cloud][ERROR] Could not prepare the cloud environment:")

    def smoke_test(worker: Callable, on_success: Callable,
                   precheck: Callable | None = None) -> None:
        _run_op("smoke", worker=worker, on_success=on_success, precheck=precheck,
                failure_prefix="[cloud][ERROR] Infrastructure smoke test failed:")

    return CloudEnvironmentOps(
        test_connection=test_connection,
        prepare_cloud=prepare_cloud,
        smoke_test=smoke_test,
        is_busy=is_busy,
    )


# ── job-lifecycle callbacks (status / logs / terminate / results) ────────
@dataclass
class CloudRuntimeCallbacks:
    check_environment: Callable
    prepare_environment: Callable
    smoke_test: Callable
    status: Callable
    logs: Callable
    terminate: Callable
    results: Callable
    ops: CloudEnvironmentOps


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
    on_status_result=None,
    smoke_button=None,
    set_chip=None,
    smoke_precheck=None,
    smoke_worker=None,
    to_thread: Callable = asyncio.to_thread,
    spawn: Callable = _spawn,
) -> CloudRuntimeCallbacks:

    _rows = {
        "account": cloud_environment.account_status,
        "storage": cloud_environment.storage_status,
        "registry": cloud_environment.registry_status,
        "compute": cloud_environment.compute_status,
    }

    def _update_environment(capabilities) -> None:
        """Reflect the REAL returned capabilities -- never hardcode Ready."""
        states = (
            ("account", getattr(capabilities, "authenticated", False), "Connected", "Not connected"),
            ("storage", getattr(capabilities, "storage_ready", False), "Ready", "Not prepared"),
            ("registry", getattr(capabilities, "registry_ready", False), "Ready", "Not prepared"),
            ("compute", getattr(capabilities, "batch_ready", False), "Ready", "Not prepared"),
        )
        for key, ready, ready_label, missing_label in states:
            set_cloud_status(
                _rows[key],
                state="done" if ready else "fail",
                label=ready_label if ready else missing_label,
            )

    _ops = build_cloud_environment_ops(
        buttons={
            "test": cloud_environment.test_button,
            "prepare": cloud_environment.prepare_button,
            "smoke": smoke_button,
        },
        rows=_rows,
        set_row=set_cloud_status,
        set_chip=(set_chip or (lambda _k: None)),
        status_widget=status_widget,
        status_html=status_html,
        log_output=log_output,
        to_thread=to_thread,
        spawn=spawn,
    )

    # -- Test connection ----------------------------------------------
    def _check_worker():
        return bridge_factory().check_environment()

    def _check_success(capabilities) -> None:
        _update_environment(capabilities)
        with log_output:
            print("[cloud] Environment check")
            for message in getattr(capabilities, "messages", []) or []:
                print(message)
        authed = bool(getattr(capabilities, "authenticated", False))
        if set_chip:
            set_chip("connected" if authed else "failed")
        status_widget.value = status_html("done" if authed else "fail")

    def on_check_environment(_=None):
        _ops.test_connection(_check_worker, _check_success)

    # -- Prepare cloud ----------------------------------------------
    def _prepare_worker():
        return bridge_factory().prepare_environment(bucket=bucket_value() or None)

    def _prepare_success(result) -> None:
        capabilities = result.get("capabilities") if isinstance(result, dict) else None
        if capabilities is not None:
            _update_environment(capabilities)
        with log_output:
            for message in (result.get("messages", []) if isinstance(result, dict) else []):
                print(message)
        ok = bool(result.get("success")) if isinstance(result, dict) else False
        if set_chip:
            set_chip("ready" if ok else "failed")
        status_widget.value = status_html("done" if ok else "fail")

    def on_prepare_environment(_=None):
        _ops.prepare_cloud(_prepare_worker, _prepare_success)

    # -- Infrastructure smoke test --------------------------------
    #: SmokeReport check name -> environment row key
    _SMOKE_ROW = {
        "aws identity": "account",
        "s3 write": "storage", "s3 cleanup": "storage",
        "batch job queue": "compute", "batch job definition": "compute",
        "ecr image": "registry",
    }

    def _smoke_success(report) -> None:
        with log_output:
            for line in report.lines():
                print(line)
            print("[cloud] infrastructure ready"
                  if report.infrastructure_ready
                  else "[cloud] infrastructure NOT ready - see the failures above")
        # map each check to its row using its REAL status
        seen = {}
        for check in report.checks:
            key = next((v for k, v in _SMOKE_ROW.items()
                        if check.name.lower().startswith(k)), None)
            if key is None:
                continue
            # a row is "done" only if every check mapped to it passed
            prior = seen.get(key)
            status = check.status
            if prior == "FAIL" or status == "FAIL":
                seen[key] = "FAIL"
            elif status == "SKIP" and prior is None:
                seen[key] = "SKIP"
            elif status == "PASS" and prior != "FAIL":
                seen[key] = "PASS"
        for key, st in seen.items():
            if st == "PASS":
                set_cloud_status(_rows[key], state="done", label="Ready")
            elif st == "FAIL":
                set_cloud_status(_rows[key], state="fail", label="Failed")
            else:
                set_cloud_status(_rows[key], state="running", label="Not checked")
        if set_chip:
            set_chip("ready" if report.infrastructure_ready else "failed")
        status_widget.value = status_html(
            "done" if report.infrastructure_ready else "fail")

    def on_smoke_test(_=None):
        if smoke_worker is None:
            with log_output:
                print("[cloud] the infrastructure smoke test is not configured here.")
            return
        with log_output:
            print("[cloud] Cloud infrastructure smoke test "
                  "(no job submitted, no ISSM run)…")
        _ops.smoke_test(smoke_worker, _smoke_success, precheck=smoke_precheck)

    # -- job-lifecycle (unchanged: on-demand, quick describe-* calls) --
    def on_status(_=None):
        log_output.clear_output()
        job_id = runtime_status.get("batch_job_id")
        if not job_id:
            with log_output:
                print("[cloud] No Batch job id yet. Submit first.")
            return
        try:
            result = bridge_factory().status(job_id=str(job_id))
            if on_status_result is not None:
                on_status_result(str(job_id), result.state)
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
            _report(log_output, error)

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
            _report(log_output, error)

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
            _report(log_output, error)

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
            _report(results_output, error)

    return CloudRuntimeCallbacks(
        check_environment=on_check_environment,
        prepare_environment=on_prepare_environment,
        smoke_test=on_smoke_test,
        status=on_status,
        logs=on_logs,
        terminate=on_terminate,
        results=on_results,
        ops=_ops,
    )
