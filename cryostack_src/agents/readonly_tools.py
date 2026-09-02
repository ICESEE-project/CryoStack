"""The A3 starter set: OBSERVE-level tools over CryoStack's existing read APIs.

Every tool here is READ_ONLY, needs no confirmation, and has no scientific
effect. Each calls the same underlying API the gateway uses; none contains
business logic. User scope is always the context's authenticated identity —
a tool never takes a ``user_id``.

Absolute local paths are not returned to the agent (``_slim_example`` /
``_slim_run`` elide them); the agent works with names and ids.
"""
from __future__ import annotations

from typing import Any

from cryostack_src.models import (
    SUPPORTED_MODELS,
    get_model_adapter,
    get_model_capabilities,
)
from cryostack_src.resources.profiles import COMPUTE_PROFILES, get_compute_profile

from .permissions import Permission
from .tools import tool

# models CryoStack ships adapters for — from the ModelCapabilities registry (P1)
_MODELS = SUPPORTED_MODELS


# ── models ────────────────────────────────────────────────────────────
@tool(name="list_models",
      description="List the ice-sheet models CryoStack can run and a one-line "
                  "note on each.",
      permission=Permission.OBSERVE)
def list_models(ctx) -> list[dict]:
    out = []
    for m in _MODELS:
        cap = get_model_capabilities(m)
        out.append({"name": cap.name, "display_name": cap.display_name,
                    "language": cap.language, "note": cap.notes})
    return out


@tool(name="list_model_capabilities",
      description="For each model, what CryoStack can actually do with it: "
                  "Basic-mode config, structured results + contract, offline "
                  "result reader, visualization, MATLAB requirement, execution "
                  "modes and backends, cloud support.",
      permission=Permission.OBSERVE)
def list_model_capabilities(ctx) -> list[dict]:
    return [get_model_capabilities(m).to_dict() for m in _MODELS]


# ── examples ──────────────────────────────────────────────────────────
def _example_provider(ctx):
    """Import lazily so the agents package has no hard UI dependency."""
    from icesee_jupyter_book.core.icesheet_examples import merged_examples_for_model
    return merged_examples_for_model


def example_identifier(ex) -> str:
    """A stable name an agent passes back to prepare_run_plan / inspect_example:
    the directory name for ISSM, the notebook stem for Icepack."""
    return ex.path.stem if ex.kind == "notebook" else ex.path.name


def _slim_example(ex) -> dict:
    d = ex.to_dict()
    return {
        "name": example_identifier(ex),
        "display": d["label"].lstrip("⧉ ").strip(),
        "model": d["model_name"],
        "kind": d["kind"],
        "category": d["category"],
        "beginner_friendly": d["beginner_friendly"],
        "description": d.get("description", ""),
        "entrypoint": d.get("entrypoint"),
        "owned": d["owned"],
        "read_only": d["read_only"],
        "runnable": d["runnable"],
    }


@tool(name="list_examples",
      description="List the runnable examples for a model — the canonical "
                  "(read-only) ones plus this user's own workspace examples.",
      permission=Permission.OBSERVE,
      parameters={"model": {"type": "str", "required": True,
                            "help": "issm | icepack"}})
def list_examples(ctx, *, model: str) -> list[dict]:
    model = str(model).strip().lower()
    if model not in _MODELS:
        raise ValueError(f"unknown model: {model!r}")
    return _list_examples_raw(ctx, model)


@tool(name="inspect_example",
      description="Describe one example: its model, kind, entrypoint / run "
                  "targets, whether it is editable, and (for Icepack) which "
                  "Basic-mode parameters it exposes.",
      permission=Permission.OBSERVE,
      parameters={"model": {"type": "str", "required": True},
                  "name": {"type": "str", "required": True}})
def inspect_example(ctx, *, model: str, name: str) -> dict:
    model = str(model).strip().lower()
    matches = _list_examples_raw(ctx, model)
    hit = next((e for e in matches if e["name"] == name), None)
    if hit is None:
        raise ValueError(f"no example {name!r} for model {model!r}")
    out = dict(hit)
    if model == "icepack":
        from cryostack_src.models.icepack import BASIC_MODE_PARAMETERS
        out["basic_mode_parameters"] = [
            {"name": p.name, "label": p.label, "units": p.units,
             "minimum": p.minimum, "maximum": p.maximum, "kind": p.kind}
            for p in BASIC_MODE_PARAMETERS
        ]
    elif model == "issm":
        out["basic_mode"] = ("curated md.* parameters, solver-aware; see the "
                             "ISSM configuration panel")
    return out


def _list_examples_raw(ctx, model: str) -> list[dict]:
    adapter = get_model_adapter(model)
    mgr = ctx.workspace_manager
    ue = mgr.list_user_examples(model) if mgr is not None else []
    merged = _example_provider(ctx)(
        model, user_examples=ue,
        runnable_check=getattr(adapter, "example_runnable", None))
    return [_slim_example(e) for e in merged if e.runnable]


# ── compute resources ─────────────────────────────────────────────────
def _slim_profile(p) -> dict:
    """RESOURCE / SITE facts only. Never the MATLAB license value, never
    anything personal."""
    return {
        "name": p.name,
        "login_host": p.login_host,
        "ssh_port": p.ssh_port,
        "username_hint": p.username_hint,
        "requires_vpn": p.requires_vpn,
        "requires_mfa": p.requires_mfa,
        "supported_access_modes": list(p.supported_access_modes),
        "auth_modes": list(p.auth_modes),
        "key_registration_method": p.key_registration_method,
        "portal_url": p.portal_url or None,
        "verification_command": p.verification_command,
        "account_required": p.account_required,
        "default_partition": p.scheduler_defaults.partition,
        "default_wall_time": p.scheduler_defaults.wall_time,
        "matlab_license_configured": bool(p.has_matlab_license),
    }


@tool(name="list_compute_resources",
      description="List the HPC compute resources CryoStack has profiles for.",
      permission=Permission.OBSERVE)
def list_compute_resources(ctx) -> list[dict]:
    return [_slim_profile(p) for p in COMPUTE_PROFILES.values()]


@tool(name="inspect_resource_requirements",
      description="Describe what a compute resource requires: connection "
                  "method, authentication, VPN/MFA, whether a Slurm allocation "
                  "is mandatory, and whether MATLAB licensing is configured.",
      permission=Permission.OBSERVE,
      parameters={"resource": {"type": "str", "required": True}})
def inspect_resource_requirements(ctx, *, resource: str) -> dict:
    p = get_compute_profile(resource)
    slim = _slim_profile(p)
    slim["notes"] = _resource_notes(p)
    return slim


def _resource_notes(p) -> list[str]:
    out: list[str] = []
    if p.requires_vpn:
        out.append("Requires an active institutional VPN.")
    if p.requires_mfa:
        out.append("Requires MFA / a second factor at login.")
    if p.account_required:
        out.append("A Slurm allocation / account is mandatory for jobs here.")
    if "password_bootstrap" in p.auth_modes:
        out.append("One-time password bootstrap of the CryoStack SSH key is "
                   "supported (the password is used once and never stored).")
    if p.key_registration_method in ("portal", "manual"):
        out.append("The CryoStack public key must be registered by hand "
                   + (f"via {p.portal_name or p.portal_url}." if p.portal_url
                      else "with the resource."))
    return out


# ── datasets ──────────────────────────────────────────────────────────
@tool(name="list_user_datasets",
      description="List the datasets in the authenticated user's own workspace.",
      permission=Permission.OBSERVE)
def list_user_datasets(ctx) -> list[dict]:
    mgr = _require_manager(ctx)
    out = []
    for d in mgr.list_datasets():
        item = dict(d) if isinstance(d, dict) else {"name": str(d)}
        item.pop("path", None)          # no absolute paths to the agent
        out.append(item)
    return out


# ── runs ──────────────────────────────────────────────────────────────
def _slim_run(r) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "model": r.model,
        "backend": r.backend,
        "execution_mode": r.execution_mode,
        "status": r.status,
        "jobid": r.jobid,
        "created": r.created.isoformat() if getattr(r, "created", None) else None,
        "has_overrides": bool(r.metadata.get("parameter_overrides")
                              or r.metadata.get("md_overrides")),
    }


@tool(name="list_runs",
      description="List the authenticated user's run history (most recent "
                  "first).",
      permission=Permission.OBSERVE)
def list_runs(ctx) -> list[dict]:
    mgr = _require_manager(ctx)
    runs = mgr.refresh()
    return [_slim_run(r) for r in runs]


@tool(name="inspect_run",
      description="Describe one of the user's runs: model, backend, status, "
                  "the scientific parameter overrides recorded, and the compute "
                  "resource used.",
      permission=Permission.OBSERVE,
      parameters={"run_id": {"type": "str", "required": True}})
def inspect_run(ctx, *, run_id: str) -> dict:
    mgr = _require_manager(ctx)
    run = _get_owned_run(mgr, run_id)
    md = dict(run.metadata or {})
    return {
        **_slim_run(run),
        "cluster_name": md.get("cluster_name"),
        "access_mode": md.get("access_mode"),
        "parameter_overrides": md.get("parameter_overrides")
        or md.get("md_overrides") or {},
        "container": run.container or {},
        "software": run.software or {},
    }


@tool(name="inspect_results",
      description="Describe the structured results available for one of the "
                  "user's completed runs (status, readability, solutions).",
      permission=Permission.OBSERVE,
      parameters={"run_id": {"type": "str", "required": True}})
def inspect_results(ctx, *, run_id: str) -> dict:
    mgr = _require_manager(ctx)
    _get_owned_run(mgr, run_id)
    pkg = mgr.result_package_for_run(run_id)
    from cryostack_src.models.results_common import describe_package
    summary = describe_package(pkg)
    summary["run_id"] = run_id
    summary["solutions"] = [s["name"] for s in summary.get("solutions", [])]
    return summary


@tool(name="list_result_fields",
      description="List the scientific fields available to visualize for one "
                  "of the user's completed runs, in preference order.",
      permission=Permission.OBSERVE,
      parameters={"run_id": {"type": "str", "required": True},
                  "solution": {"type": "str", "required": False}})
def list_result_fields(ctx, *, run_id: str, solution: str | None = None) -> list[dict]:
    mgr = _require_manager(ctx)
    _get_owned_run(mgr, run_id)
    pkg = mgr.result_package_for_run(run_id)
    if not getattr(pkg, "is_readable", lambda: False)():
        return []
    sols = pkg.available_solutions()
    sol = solution or (sols[0] if sols else None)
    if sol is None:
        return []
    out = []
    for name in pkg.available_fields(sol):
        try:
            info = pkg.field_metadata(sol, name)
            out.append({
                "field": name,
                "units": getattr(info, "units", None),
                "location": getattr(info, "location", None),
                "transient": bool(getattr(info, "transient", False)),
                "rank": getattr(info, "rank", "scalar"),
            })
        except Exception:
            out.append({"field": name})
    return out


# ── helpers ───────────────────────────────────────────────────────────
def _require_manager(ctx):
    if ctx.workspace_manager is None:
        raise RuntimeError(
            "this tool needs a workspace: the agent context was built without a "
            "WorkspaceManager")
    return ctx.workspace_manager


def _get_owned_run(mgr, run_id: str):
    """Look a run up by id and confirm it belongs to this user's workspace."""
    run = None
    for r in mgr.refresh():
        if r.id == run_id:
            run = r
            break
    if run is None:
        raise ValueError(f"run {run_id!r} is not in your workspace")
    if hasattr(mgr, "_owns") and not mgr._owns(run.workspace_directory):
        raise ValueError(f"run {run_id!r} is not in your workspace")
    return run
