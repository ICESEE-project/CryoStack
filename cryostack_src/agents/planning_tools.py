"""Planning tools (A4): construct + validate a :class:`RunPlan` without
submitting anything. PLAN-level, read-only — a plan is an inert proposal.

They reuse the SAME validation the gateway uses:
* B4 Slurm validation (`shared_validation.validate_slurm_resources`)
* the model's Basic-mode parameter spec (`icepack.validate_icepack_config`,
  `issm.validate_md_config` with solver detection)
* B3 identity requirements (surfaced as findings, not enforced here)
* the model/backend preflight facts (MATLAB licence, cloud support)
"""
from __future__ import annotations

from typing import Any

from cryostack_src.models import get_model_adapter, get_model_capabilities
from cryostack_src.resources.profiles import get_compute_profile

from .permissions import Permission
from .planning import PlanFinding, RunPlan, SlurmRequest
from .tools import tool


# ── build ─────────────────────────────────────────────────────────────
@tool(name="prepare_run_plan",
      description="Construct a structured run plan (model, example, resource, "
                  "backend, parameter overrides, Slurm request). Submits "
                  "nothing — the plan is an inert proposal.",
      permission=Permission.PLAN, read_only=True,
      parameters={
          "model": {"type": "str", "required": True},
          "example": {"type": "str", "required": True},
          "compute_resource": {"type": "str", "required": True},
          "execution_mode": {"type": "str", "required": False,
                             "help": "remote (default) | cloud"},
          "backend": {"type": "str", "required": False,
                      "help": "spack (default) | container"},
          "run_target": {"type": "str", "required": False},
          "parameter_overrides": {"type": "dict", "required": False},
          "datasets": {"type": "list", "required": False},
          "slurm": {"type": "dict", "required": False},
      })
def prepare_run_plan(ctx, *, model: str, example: str, compute_resource: str,
                     execution_mode: str = "remote", backend: str = "spack",
                     run_target: str = "", parameter_overrides: dict | None = None,
                     datasets: list | None = None, slurm: dict | None = None) -> dict:
    model = str(model).strip().lower()
    adapter = get_model_adapter(model)          # raises ValueError on unknown
    profile = get_compute_profile(compute_resource)

    ex = _resolve_example(ctx, model, example)
    if ex is None:
        raise ValueError(f"no example {example!r} for model {model!r}")

    if not run_target:
        run_target = _default_run_target(ex, adapter)

    sd = profile.scheduler_defaults
    slurm_req = SlurmRequest(**{
        "job_name": (slurm or {}).get("job_name", f"{model.upper()}"),
        "nodes": int((slurm or {}).get("nodes", 1)),
        "tasks": int((slurm or {}).get("tasks", 1)),
        "tasks_per_node": int((slurm or {}).get("tasks_per_node", 1)),
        "wall_time": (slurm or {}).get("wall_time") or sd.wall_time,
        "memory": (slurm or {}).get("memory", ""),
        "account": (slurm or {}).get("account", ""),
    })

    plan = RunPlan(
        application=ctx.application, model=model, example=example,
        execution_mode=str(execution_mode).strip().lower(),
        compute_resource=profile.name, backend=str(backend).strip().lower(),
        run_target=run_target,
        parameter_overrides=dict(parameter_overrides or {}),
        datasets=tuple(datasets or ()),
        slurm=slurm_req,
    )
    ctx.trace.append("plan", {"digest": plan.digest(), "plan": plan.to_dict()})
    return plan.to_dict()


# ── validate ──────────────────────────────────────────────────────────
@tool(name="validate_run_plan",
      description="Validate a run plan against the same rules the gateway uses "
                  "(Slurm resources, Basic-mode parameters, remote identity, "
                  "model/backend preflight). Returns findings + which approvals "
                  "the plan requires. Submits nothing.",
      permission=Permission.PLAN, read_only=True,
      parameters={"plan": {"type": "dict", "required": True}})
def validate_run_plan(ctx, *, plan: dict) -> dict:
    p = RunPlan.from_dict(plan)
    profile = get_compute_profile(p.compute_resource)
    findings: list[PlanFinding] = []
    solvers: tuple[str, ...] = ()

    # 1. Slurm (B4)
    from icesee_jupyter_book.ui.shared_validation import validate_slurm_resources
    for msg in validate_slurm_resources(
        nodes=p.slurm.nodes, tasks=p.slurm.tasks,
        tasks_per_node=p.slurm.tasks_per_node, wall_time=p.slurm.wall_time,
        memory=p.slurm.memory, account=p.slurm.account,
        account_required=profile.account_required,
    ):
        findings.append(PlanFinding("error", "slurm", msg))

    # 2. Basic-mode parameter overrides
    if p.parameter_overrides:
        if p.model == "icepack":
            from cryostack_src.models.icepack import validate_icepack_config
            res = validate_icepack_config(p.parameter_overrides)
            for e in res["errors"]:
                findings.append(PlanFinding("error", "parameters", e))
        elif p.model == "issm":
            solvers = _detect_issm_solvers(ctx, p)
            from cryostack_src.models.issm import validate_md_config
            v = validate_md_config(p.parameter_overrides, solvers=solvers)
            for e in v.errors:
                findings.append(PlanFinding("error", "parameters", e))

    # 3. remote identity (B3) — a requirement, surfaced not enforced
    if p.execution_mode == "remote":
        findings.append(PlanFinding(
            "info", "identity",
            "A remote run requires your HPC username + remote working "
            "directory, and CryoStack must verify the remote identity "
            f"(runs `{profile.verification_command}` and compares it) before "
            "submitting. This happens at approval/submit time, not now."))
        if profile.requires_vpn:
            findings.append(PlanFinding("warning", "identity",
                                        f"{profile.name} requires an active VPN."))

    # 4. model/backend preflight facts (capability-driven, not model-name)
    if (get_model_capabilities(p.model).requires_matlab
            and p.backend == "container" and not profile.has_matlab_license):
        findings.append(PlanFinding(
            "error", "preflight",
            f"{p.model.upper()} runs MATLAB in the container but {profile.name} "
            "has no MATLAB licence configured."))
    if p.execution_mode == "cloud" and not get_model_capabilities(p.model).cloud_supported:
        findings.append(PlanFinding(
            "error", "preflight",
            f"Cloud (AWS Batch) execution is ISSM-only today; {p.model} cloud "
            "runs are blocked at preflight."))

    approvals = _approvals_required(p, findings)
    out = p.with_findings(findings, approvals_required=approvals, solvers=solvers)
    ctx.trace.append("validation", {
        "digest": out.digest(),
        "errors": [f.to_dict() for f in findings if f.level == "error"],
        "approvals_required": approvals,
    })
    return out.to_dict()


# ── input fingerprint (task 5) ────────────────────────────────────────
@tool(name="fingerprint_run_inputs",
      description="Compute a content fingerprint of the run's mutable inputs "
                  "(the resolved run-target script, other source files in the "
                  "example, and referenced datasets). A human can approve a "
                  "plan bound to this fingerprint so a later edit to any of "
                  "those files blocks execution. Reads only; submits nothing.",
      permission=Permission.PLAN, read_only=True,
      parameters={"plan": {"type": "dict", "required": True}})
def fingerprint_run_inputs(ctx, *, plan: dict) -> dict:
    from .fingerprint import fingerprint_inputs
    p = RunPlan.from_dict(plan)
    ex = _resolve_example(ctx, p.model, p.example)
    if ex is None:
        raise ValueError(f"no example {p.example!r} for model {p.model!r}")
    fp = fingerprint_inputs(ex.path, run_target=p.run_target or "",
                            dataset_paths=_dataset_paths(ctx, p.datasets))
    ctx.trace.append("fingerprint", {"digest": fp.digest(),
                                     "files": len(fp.tree),
                                     "datasets": len(fp.datasets)})
    return fp.to_dict()


@tool(name="verify_run_input_fingerprint",
      description="Recompute the run-input fingerprint and report whether it "
                  "still matches a previously recorded one, naming any file or "
                  "dataset that changed. Reads only.",
      permission=Permission.PLAN, read_only=True,
      parameters={"plan": {"type": "dict", "required": True},
                  "expected": {"type": "dict", "required": True}})
def verify_run_input_fingerprint(ctx, *, plan: dict, expected: dict) -> dict:
    from .fingerprint import RunInputFingerprint, fingerprint_inputs
    p = RunPlan.from_dict(plan)
    ex = _resolve_example(ctx, p.model, p.example)
    if ex is None:
        raise ValueError(f"no example {p.example!r} for model {p.model!r}")
    want = RunInputFingerprint.from_dict(expected)
    have = fingerprint_inputs(ex.path, run_target=p.run_target or "",
                              dataset_paths=_dataset_paths(ctx, p.datasets))
    drift = have.drift_from(want)
    return {"ok": not drift, "drift": drift,
            "expected_digest": want.digest(), "current_digest": have.digest()}


def _dataset_paths(ctx, names) -> list:
    from pathlib import Path
    mgr = ctx.workspace_manager
    if mgr is None or not names:
        return []
    try:
        catalog = {d.get("name"): d.get("path") for d in mgr.list_datasets()}
    except Exception:
        return []
    return [Path(catalog[n]) for n in names if catalog.get(n)]


# ── estimate ──────────────────────────────────────────────────────────
@tool(name="estimate_execution_requirements",
      description="Summarise what running this plan would require: the compute "
                  "request, whether a Slurm allocation / VPN / MATLAB licence "
                  "is needed, the identity check, and the expected result "
                  "contract. Submits nothing.",
      permission=Permission.PLAN, read_only=True,
      parameters={"plan": {"type": "dict", "required": True}})
def estimate_execution_requirements(ctx, *, plan: dict) -> dict:
    p = RunPlan.from_dict(plan)
    profile = get_compute_profile(p.compute_resource)
    return {
        "execution_mode": p.execution_mode,
        "compute_resource": p.compute_resource,
        "backend": p.backend,
        "compute_request": {
            "nodes": p.slurm.nodes, "tasks": p.slurm.tasks,
            "tasks_per_node": p.slurm.tasks_per_node,
            "wall_time": p.slurm.wall_time or "(resource default)",
            "memory": p.slurm.memory or "(unset)",
        },
        "slurm_account_required": profile.account_required,
        "vpn_required": profile.requires_vpn,
        "mfa_required": profile.requires_mfa,
        "matlab_required": (get_model_capabilities(p.model).requires_matlab
                            and p.backend == "container"),
        "matlab_licence_configured": bool(profile.has_matlab_license),
        "remote_identity_check": (
            f"`{profile.verification_command}` must equal your configured HPC "
            "username (B3) before submit" if p.execution_mode == "remote"
            else "n/a"),
        "expected_result_contract": p.expected_result_contract,
        "scientific_changes": p.scientific_changes(),
    }


# ── helpers ───────────────────────────────────────────────────────────
def _resolve_example(ctx, model: str, name: str):
    from icesee_jupyter_book.core.icesheet_examples import merged_examples_for_model

    from .readonly_tools import example_identifier
    adapter = get_model_adapter(model)
    mgr = ctx.workspace_manager
    ue = mgr.list_user_examples(model) if mgr is not None else []
    want = str(name).strip()
    for ex in merged_examples_for_model(
        model, user_examples=ue,
        runnable_check=getattr(adapter, "example_runnable", None),
    ):
        if want in (example_identifier(ex), ex.path.name, ex.path.stem,
                    ex.label.lstrip("⧉ ").strip()):
            return ex
    return None


def _default_run_target(ex, adapter) -> str:
    if ex.entrypoint:
        return ex.entrypoint
    try:
        names = [c.name for c in ex.path.iterdir()] if ex.path.is_dir() else [ex.path.name]
        return getattr(adapter, "choose_run_target", lambda n: "")(names) or ""
    except OSError:
        return ""


def _detect_issm_solvers(ctx, p: RunPlan) -> tuple[str, ...]:
    ex = _resolve_example(ctx, "issm", p.example)
    if ex is None:
        return ()
    runme = (ex.path / (p.run_target or "runme.m")) if ex.path.is_dir() else ex.path
    try:
        text = runme.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ()
    from cryostack_src.models.issm import detect_solvers
    return tuple(detect_solvers(text))


def _approvals_required(p: RunPlan, findings) -> list[str]:
    req: list[str] = []
    if p.parameter_overrides:
        req.append("scientific-parameter-change")
    req.append("compute-submission")
    if p.execution_mode == "remote":
        req.append("remote-identity-verification")
    if any(f.level == "error" for f in findings):
        req.append("resolve-validation-errors-first")
    return req
