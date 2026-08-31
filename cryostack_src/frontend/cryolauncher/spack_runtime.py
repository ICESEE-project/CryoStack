"""Callbacks for the Remote + ICESEE-Spack "Environment" block.

Lifecycle wiring only -- the actual probe / setup-job logic lives in
:mod:`cryostack_src.remote.spack_env` and :class:`cryostack_src.remote.RemoteBridge`.

    [ Check environment ]   -> live probe -> Not installed / Not built / Ready
    [ Prepare environment ] -> probe first; if not Ready, sbatch a setup job
    [ View setup log ]      -> tail the setup job + (on completion) re-verify -> Ready
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from cryostack_src.frontend.shared import status_badge
from cryostack_src.remote.spack_env import EnvStatus, SetupSlurmOpts, deep_verify_ok


@dataclass
class SpackRuntimeCallbacks:
    check: Callable
    prepare: Callable
    view_setup_log: Callable


def build_spack_runtime_callbacks(
    *,
    runtime_status,
    log_output,
    status_widget,
    status_html,
    bridge_factory,
    ensure_connector_session,
    env_badge,
    setup_job_label,
    view_log_button,
    model_value: Callable[[], str],
    remote_base_value: Callable[[], str],
    spack_dirname_value: Callable[[], str],
    spack_repo_value: Callable[[], str],
    setup_slurm_opts: Callable[[], SetupSlurmOpts],
    matlab_license_for: Callable[[str], dict | None],
) -> SpackRuntimeCallbacks:

    def _badge(status: EnvStatus, *, suffix: str = "") -> None:
        env_badge.value = status_badge(
            status.badge_state, label=status.label + (f" · {suffix}" if suffix else "")
        )

    def _setup_label(text: str = "") -> None:
        setup_job_label.value = (
            f"<span class='icesee-subtle'>{text}</span>" if text else ""
        )
        view_log_button.layout.display = "" if runtime_status.get("spack_setup_jobid") else "none"

    def _bridge():
        if ensure_connector_session is not None:
            ensure_connector_session()
        return bridge_factory()

    # ---------------------------------------------------------------- check
    def on_check(_=None):
        log_output.clear_output()
        status_widget.value = status_html("running")
        model = model_value()
        try:
            report = _bridge().environment_status(
                model=model,
                remote_base=remote_base_value(),
                spack_dirname=spack_dirname_value(),
            )
            _badge(report.status)
            with log_output:
                print(f"[spack] Environment check ({model.upper()})")
                for line in report.messages:
                    print(" ", line)
            status_widget.value = status_html("done" if report.is_ready else "fail")
        except Exception as error:
            _badge(EnvStatus.FAILED)
            status_widget.value = status_html("fail")
            with log_output:
                print("[spack][ERROR]", type(error).__name__, error)

    # -------------------------------------------------------------- prepare
    def on_prepare(_=None):
        log_output.clear_output()
        status_widget.value = status_html("running")
        model = model_value()
        with log_output:
            print(f"[spack] Prepare environment ({model.upper()})")
        try:
            result = _bridge().prepare_spack_environment(
                model=model,
                remote_base=remote_base_value(),
                spack_dirname=spack_dirname_value(),
                repo_url=spack_repo_value(),
                slurm=setup_slurm_opts(),
                matlab_license=matlab_license_for(model),
            )
            if result.get("reused"):
                _badge(EnvStatus.READY)
                _setup_label()
                with log_output:
                    print("  ICESEE-Spack is already ready on this resource. Reusing it.")
                status_widget.value = status_html("done")
                return

            job = result["job"]
            runtime_status["spack_setup_jobid"] = job["job_id"]
            runtime_status["spack_setup_dir"] = job["setup_dir"]
            runtime_status["spack_setup_log"] = job["log_file"]
            runtime_status["spack_setup_model"] = model
            _badge(EnvStatus.INSTALLING, suffix=f"Job {job['job_id']}")
            _setup_label(f"Setup job {job['job_id']} queued")
            with log_output:
                print(f"  setup job submitted: {job['job_id']}")
                print(f"  install + deep verification run on a compute node")
                print(f"  use 'View setup log' to follow progress")
            status_widget.value = status_html("done")
        except Exception as error:
            _badge(EnvStatus.FAILED)
            status_widget.value = status_html("fail")
            with log_output:
                print("[spack][ERROR] Could not prepare the environment.")
                print(type(error).__name__, error)

    # --------------------------------------------------- view setup log
    def on_view_setup_log(_=None):
        log_output.clear_output()
        job_id = runtime_status.get("spack_setup_jobid")
        if not job_id:
            with log_output:
                print("[spack] No setup job yet. Use 'Prepare environment' first.")
            return
        model = runtime_status.get("spack_setup_model") or model_value()
        try:
            bridge = _bridge()
            state = bridge.status(job_id=str(job_id)).state
            logs = bridge.logs(
                job_id=str(job_id),
                remote_dir=runtime_status.get("spack_setup_dir", ""),
                log_file=runtime_status.get("spack_setup_log"),
            )
            log_text = (logs.get("stdout") or "") if isinstance(logs, dict) else str(logs)
            with log_output:
                print(f"[spack] Setup job {job_id} — state: {state}")
                print(log_text.rstrip() or "(no log output yet)")

            if state == "completed":
                report = bridge.environment_status(
                    model=model,
                    remote_base=remote_base_value(),
                    spack_dirname=spack_dirname_value(),
                )
                verified = deep_verify_ok(log_text)
                if report.is_ready and verified:
                    _badge(EnvStatus.READY)
                    _setup_label(f"Verified · setup job {job_id}")
                    status_widget.value = status_html("done")
                    with log_output:
                        print("  deep verification: passed — ICESEE-Spack is Ready.")
                else:
                    _badge(EnvStatus.FAILED)
                    status_widget.value = status_html("fail")
                    with log_output:
                        print("  setup job finished but the environment did not verify.")
            elif state in {"failed", "cancelled", "unknown"}:
                _badge(EnvStatus.FAILED)
                _setup_label(f"Setup job {job_id} failed")
                status_widget.value = status_html("fail")
            else:
                _badge(EnvStatus.INSTALLING, suffix=f"Job {job_id}")
                status_widget.value = status_html("running")
        except Exception as error:
            status_widget.value = status_html("fail")
            with log_output:
                print("[spack][ERROR]", type(error).__name__, error)

    return SpackRuntimeCallbacks(
        check=on_check, prepare=on_prepare, view_setup_log=on_view_setup_log
    )
