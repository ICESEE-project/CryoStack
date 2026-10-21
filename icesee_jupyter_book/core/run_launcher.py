"""Prepare, start, finish and re-attach local ICESEE runs.

The launcher UI calls these in order::

    issues = validate_launch(request)            # nothing happens on error
    prepared = prepare_local_run(request)        # state: preparing
    job = start_local_run(prepared)              # state: running
    ...
    finalize_local_run(run_dir, job.poll())      # completed / failed / cancelled

and ``reconcile_local_run`` re-attaches to (or settles) a run found in the
history after a page reload. Every step records the lifecycle transition in
the run manifest; ``provenance.json`` is written before the model starts.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import provenance, run_lifecycle, run_records
from .config_io import dump_yaml, load_yaml
from .example_discovery import find_params_template, find_report_notebook, find_run_script
from .experiment_files import Issue, validate_params
from .local_jobs import LocalJob, container_command, environments, native_command
from .local_runner import run_dir as make_run_dir, stage_example

MAX_LOCAL_PROCESSES = max(1, (os.cpu_count() or 2) - 1)
#: local runs one user may have in progress at once on the shared server
MAX_ACTIVE_LOCAL_ENV = "CRYOSTACK_ICESEE_MAX_LOCAL_RUNS"
DEFAULT_MAX_ACTIVE_LOCAL = 2


def max_active_local_runs() -> int:
    try:
        return max(1, int(os.environ.get(MAX_ACTIVE_LOCAL_ENV, DEFAULT_MAX_ACTIVE_LOCAL)))
    except ValueError:
        return DEFAULT_MAX_ACTIVE_LOCAL


def active_local_runs(run_root) -> list[str]:
    """Run ids under ``run_root`` whose local job is still alive."""
    if run_root is None or not Path(run_root).is_dir():
        return []
    active = []
    for job_file in Path(run_root).glob("*/.icesee-job.json"):
        job = LocalJob(job_file.parent)
        if job.returncode() is None and job._alive():
            active.append(job_file.parent.name)
    return sorted(active)


@dataclass
class LaunchRequest:
    example: str                      # registry key
    example_cfg: dict
    config: dict                      # the params.yaml content
    environment: str = "native"       # "native" | "container"
    np: int = 1
    model_nprocs: int = 0
    generate_report: bool = False
    run_root: Path | None = None
    drafts: dict = field(default_factory=dict)      # edited inputs: rel path -> draft file
    user_id: str = ""
    run_id: str | None = None


@dataclass
class PreparedRun:
    run_id: str
    run_dir: Path
    staged_cfg: dict
    params_file: Path
    command: list
    env: dict
    cwd: Path
    backend: str
    container: str = ""
    post: list | None = None
    model: str = ""


def new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "-" + uuid.uuid4().hex[:6]


def validate_launch(req: LaunchRequest, *, mode: str = "local") -> list[Issue]:
    """Everything that would make a launch fail or mislead, before anything
    is written. Errors block the launch; warnings are shown in Review."""
    issues: list[Issue] = []
    try:
        template = load_yaml(find_params_template(req.example_cfg))
    except Exception as exc:  # noqa: BLE001
        return [Issue("error", f"the example's params.yaml template cannot be read: {exc}")]
    issues += [i for i in validate_params(req.config, template=template) if i.level != "info"]
    model = req.example_cfg.get("model_name", "")
    if mode == "local":
        running = active_local_runs(req.run_root)
        if len(running) >= max_active_local_runs():
            issues.append(Issue("error", f"you already have {len(running)} local run(s) in progress "
                                         f"({', '.join(running)}); wait for one to finish or cancel it"))
        env = next((e for e in environments(model) if e.kind == req.environment), None)
        if env is None:
            issues.append(Issue("error", f"unknown local environment {req.environment!r}"))
        elif not env.available:
            issues.append(Issue("error", f"{env.label} cannot run this example: {env.reason}"))
        if req.environment == "container" and not 1 <= int(req.np) <= MAX_LOCAL_PROCESSES:
            issues.append(Issue("error", f"MPI processes must be between 1 and {MAX_LOCAL_PROCESSES} on this server"))
        if req.environment == "native" and int(req.np) != 1:
            issues.append(Issue("warning", "the launcher's Python runs the model as one process; "
                                           "MPI processes apply to the container environment"))
        exec_mode = str((req.config.get("enkf-parameters") or {}).get("execution_mode")).strip()
        if req.environment == "container" and exec_mode == "2":
            issues.append(Issue("error", "execution_mode 2 (full parallel) writes through parallel HDF5, "
                                         "which the ICESEE container's h5py does not support; use the "
                                         "launcher's Python environment, or execution_mode 0 or 1"))
        if req.environment == "container" and exec_mode == "0" and int(req.np) > 1:
            issues.append(Issue("error", "execution_mode 0 (serial) runs on one process; with more MPI "
                                         "processes every rank repeats the run and they do not finish "
                                         "together. Set MPI processes to 1, or use execution_mode 1"))
    elif req.drafts:
        issues.append(Issue("warning", "edited input files ("
                            + ", ".join(sorted(req.drafts)) + f") apply to Local runs only; a {mode} run "
                            "receives params.yaml and uses its own copy of the example"))
    try:
        find_run_script(req.example_cfg)
    except FileNotFoundError as exc:
        issues.append(Issue("error", str(exc)))
    return issues


def prepare_local_run(req: LaunchRequest) -> PreparedRun:
    run_id = req.run_id or new_run_id()
    rd = make_run_dir(req.run_root, run_id)
    run_records.record_run(run_dir=rd, run_id=run_id, name=f"ICESEE {req.example} (local)",
                           params=req.config, example=req.example, execution_mode="local",
                           backend=f"local-{req.environment}", source=req.example,
                           run_target=req.example_cfg.get("run_script") or "",
                           model_environment=req.environment, status=run_lifecycle.PREPARING,
                           extra_metadata={"lifecycle": [{"state": run_lifecycle.PREPARING,
                                                          "at": datetime.now().isoformat(timespec="seconds"),
                                                          "detail": "staging the example"}]})
    try:
        staged = stage_example(req.example_cfg, rd, overlays=req.drafts)
        params_file = rd / "params.yaml"
        dump_yaml(req.config, params_file)
        run_script = find_run_script(staged)
        model = staged.get("model_name", "")
        if req.environment == "container":
            nens = (req.config.get("enkf-parameters") or {}).get("Nens")
            command, env, container = container_command(
                run_dir=rd, staged_example=Path(staged["base"]), run_script=run_script, model=model,
                run_id=run_id, np=req.np, nens=nens, model_nprocs=req.model_nprocs,
                post_mesh=(model == "icepack"))
            cwd, post = rd, None
            environment = {"environment": "container", "image": command[command.index("bash") - 1]}
        else:
            command, env = native_command(run_script, params_file)
            container, cwd = "", rd
            post = None
            report = find_report_notebook(staged)
            if req.generate_report and report is not None and report.suffix == ".ipynb":
                post = [command[0], "-m", "papermill", str(report), str(rd / "report.ipynb"),
                        "--cwd", str(staged["base"])]
            environment = {"environment": "native", "python": command[0]}
        record = provenance.collect(
            run_id=run_id, run_dir=rd, example=req.example, example_cfg=req.example_cfg, mode="local",
            backend=f"local-{req.environment}", params_file=params_file, staged_example=Path(staged["base"]),
            edited={rel: "draft" for rel in req.drafts}, command=command, environment=environment,
            resources={"mpi_processes": int(req.np), "model_nprocs": int(req.model_nprocs),
                       "ensemble_size": (req.config.get("enkf-parameters") or {}).get("Nens")},
            user_id=req.user_id)
        run_records.update_run(rd, extra_metadata={"provenance": provenance.summary(record),
                                                   "command": command})
    except Exception as exc:
        run_lifecycle.transition(rd, run_lifecycle.FAILED, detail=f"could not prepare the run: {exc}")
        raise
    return PreparedRun(run_id=run_id, run_dir=rd, staged_cfg=staged, params_file=params_file, command=command,
                       env=env, cwd=cwd, backend=req.environment, container=container, post=post, model=model)


def start_local_run(prepared: PreparedRun) -> LocalJob:
    try:
        job = LocalJob.start(run_dir=prepared.run_dir, command=prepared.command, cwd=prepared.cwd,
                             env=prepared.env, backend=prepared.backend, container=prepared.container,
                             post=prepared.post)
    except Exception as exc:
        run_lifecycle.transition(prepared.run_dir, run_lifecycle.FAILED, detail=f"could not start: {exc}")
        raise
    run_lifecycle.transition(prepared.run_dir, run_lifecycle.RUNNING,
                             detail=f"process {job.meta.get('pid')}"
                                    + (f", container {prepared.container}" if prepared.container else ""),
                             jobid=f"local:{job.meta.get('pid')}")
    return job


def finalize_local_run(run_dir: Path | str, status) -> object:
    """Record a finished job's outcome (idempotent)."""
    state = {"completed": run_lifecycle.COMPLETED, "cancelled": run_lifecycle.CANCELLED}.get(
        status.state, run_lifecycle.FAILED)
    extra = {"exit_code": status.returncode, "elapsed_s": round(status.elapsed, 1)}
    if status.warnings:
        extra["warnings"] = list(status.warnings)
    try:
        return run_lifecycle.transition(run_dir, state, detail=status.detail or "", extra_metadata=extra)
    except run_lifecycle.InvalidTransition:
        return None


def reconcile_local_run(run) -> tuple[str | None, LocalJob | None]:
    """For a local run in the history: settle it if its process has ended,
    or return its job so the caller can resume monitoring. Returns the
    lifecycle state and the live job (or None)."""
    state = run_lifecycle.current_state(run)
    if run is None or run.execution_mode != "local" or state not in run_lifecycle.ACTIVE:
        return state, None
    job = LocalJob(run.workspace_directory)
    if not job.exists:
        if state == run_lifecycle.PREPARING:
            age = (datetime.now() - run.created).total_seconds()
            if age > 600:
                run_lifecycle.transition(run.workspace_directory, run_lifecycle.FAILED,
                                         detail="the run was never started")
                return run_lifecycle.FAILED, None
            return state, None
        # a pre-lifecycle local run (synchronous launcher): it finished in-session
        return state, None
    status = job.poll(model_name=(run.metadata or {}).get("forecast_model", ""))
    if status.state == "running":
        return run_lifecycle.RUNNING, job
    finalize_local_run(run.workspace_directory, status)
    return {"completed": run_lifecycle.COMPLETED, "cancelled": run_lifecycle.CANCELLED}.get(
        status.state, run_lifecycle.FAILED), None
