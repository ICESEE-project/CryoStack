"""``RemoteSubmitBackend`` — turn an approved :class:`RunPlan` into a real HPC
submission by **composing existing CryoStack APIs** in the same order the human
Run button uses. No parallel submission system.

Call order (see ``overnight/AUDIT_agent_submit_backend.md`` §3):

    0. EXECUTE ceiling (defensive)
    1. re-derive ComputeProfile from plan.compute_resource; assert it matches
       the wired connection
    2. B3  enforce_remote_access  (fresh remote-identity verification)
    3. B4  validate_slurm_resources
    4. model/backend preflight (MATLAB licence from the profile; remote-only)
    5. resolve the canonical example  (READ-ONLY)
    6. run_target hygiene  (basename, must exist in the example)
    7. stage a user-owned working copy  (canonical never touched)
    8. resolve dataset references through the user-scoped WorkspaceManager
    9. stack provenance (container backend)
   10. submit via the injected submitter  (submit_remote_icesheets[_via_connector])
   11. register the RunInfo, owned by ctx.user, stamped with the plan digest
   12. return the job id

Every value handed to the submitter is a plan scalar (already schema-typed), a
validated basename, a model-schema-validated override dict, or a connection
value the authenticated user configured in the gateway. No raw path, no shell
command, no arbitrary env, no LLM free string.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from cryostack_src.agents.execution import SubmitError

_JOB_NAME_RE = re.compile(r"[^A-Za-z0-9_-]")
_ACCOUNT_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class SubmitBlocked(SubmitError):
    """A pre-submit invariant failed; nothing was submitted. The coordinator
    catches this (as a :class:`SubmitError`) and reports it, rather than letting
    it escape."""

    def __init__(self, stage: str, messages: list[str] | str) -> None:
        msgs = [messages] if isinstance(messages, str) else list(messages)
        super().__init__(f"{stage}: " + "; ".join(msgs))
        self.stage = stage
        self.messages = msgs


def _safe_job_name(raw: str, *, fallback: str) -> str:
    cleaned = _JOB_NAME_RE.sub("-", (raw or "").strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return (cleaned or fallback)[:48]


def _safe_basename(raw: str) -> str:
    name = Path(str(raw or "")).name
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise SubmitBlocked("run-target", f"not a safe basename: {raw!r}")
    if _JOB_NAME_RE.sub("", name.replace(".", "")) != name.replace(".", ""):
        raise SubmitBlocked("run-target", f"illegal characters in {raw!r}")
    return name


@dataclass(frozen=True)
class ConnectionContext:
    """Everything the submitter needs that is NOT in the plan — filled by the
    gateway from the authenticated user's own connection/software panels. Never
    serialized, never in a trace, never from the LLM."""

    profile_name: str                    # must equal plan.compute_resource
    host: str
    user: str
    port: int
    remote_base_dir: str
    resolved_mode: str                   # "direct" | "connector"
    access_mode: str = "auto"
    connector_online: bool | None = None
    remote_tag: str = "icesheets"
    exec_dir: str = ""
    image_uri: str = ""
    container_source: str = ""
    spack_enable: bool = True
    spack_repo_url: str = "https://github.com/ICESEE-project/ICESEE-Spack.git"
    spack_dirname: str = "ICESEE-Spack"
    spack_install_mode: str = ""
    slurm_partition: str = ""
    software_selections: dict = field(default_factory=dict)
    tested_image_key: str = ""

    #: the RemoteBridge (duck: check_backend(command=, timeout=)) for B3
    bridge: Any = None

    def require_connector_for_agent(self) -> None:
        """OWNER_CHECKPOINT (audit §7.3): agent submits over *direct* SSH use a
        shared service-account identity. Until an owner decision, block it."""
        if self.resolved_mode != "connector":
            raise SubmitBlocked(
                "transport",
                "agent-initiated submit requires the CryoStack Connector "
                "(direct SSH uses a shared, non-per-user identity) — "
                "OWNER_CHECKPOINT")


class DryRunSubmitBackend:
    """An explicit no-op backend. Handed to the coordinator when you want the
    named object instead of ``submit_backend=None``. Never submits; records the
    described command on the trace."""

    def submit(self, plan, *, ctx: Any, approval: Any = None) -> str:
        from cryostack_src.agents.execution import _describe_submission
        ctx.trace.append("execution_decision", {
            "backend": "dry-run", "submitted": False,
            "would_run": _describe_submission(plan)})
        raise SubmitBlocked("dry-run", "DryRunSubmitBackend never submits")


class RemoteSubmitBackend:
    """Composes the existing remote-submit pipeline for an approved plan.

    Seams are injected so the whole sequence is unit-testable without an HPC:

    * ``submitter``     -> ``submit_remote_icesheets`` / ``…_via_connector``
    * ``example_resolver(ctx, model, name)`` -> the canonical example object
    * ``stack_resolver(**kw)`` -> ``resolve_stack`` (container backend only)
    * ``run_registrar(**kw)``  -> ``workspace_bridge.start_run``
    """

    def __init__(
        self,
        *,
        connection: ConnectionContext,
        submitter: Callable,
        example_resolver: Callable | None = None,
        stack_resolver: Callable | None = None,
        run_registrar: Callable | None = None,
        enforce_connector_for_agent: bool = True,
    ) -> None:
        self._conn = connection
        self._submitter = submitter
        self._resolve_example = example_resolver or _default_example_resolver
        self._resolve_stack = stack_resolver
        self._register = run_registrar
        self._enforce_connector = enforce_connector_for_agent

    # -- the SubmitBackend protocol -----------------------------------
    def submit(self, plan, *, ctx: Any, approval: Any = None) -> str:
        from cryostack_src.agents.permissions import Permission
        from cryostack_src.models import get_model_capabilities
        from cryostack_src.resources.profiles import get_compute_profile

        # 0. defensive ceiling check (coordinator already enforced it)
        if not ctx.can(Permission.EXECUTE):
            raise SubmitBlocked("permission", "context is not permitted to EXECUTE")

        # 1. re-derive the profile; the plan's resource must match the wired one
        profile = get_compute_profile(plan.compute_resource)
        if profile.name != self._conn.profile_name:
            raise SubmitBlocked(
                "resource",
                f"plan targets {profile.name!r} but this backend is wired for "
                f"{self._conn.profile_name!r}")
        if plan.execution_mode != "remote":
            raise SubmitBlocked("mode", "RemoteSubmitBackend handles remote runs only")
        if not get_model_capabilities(plan.model).supports_mode("remote"):
            raise SubmitBlocked("mode", f"{plan.model} does not support remote execution")

        if self._enforce_connector:
            self._conn.require_connector_for_agent()

        # 2. B3 — fresh remote-identity verification
        self._enforce_b3(profile)

        # 3. B4 — Slurm resource validation (same function the gateway uses)
        self._enforce_b4(plan, profile)

        # 4. model/backend preflight
        matlab_license = self._preflight(plan, profile)

        # 5. resolve the canonical example (READ-ONLY)
        ex = self._resolve_example(ctx, plan.model, plan.example)
        if ex is None:
            raise SubmitBlocked("example", f"no example {plan.example!r} for {plan.model}")
        canonical_dir = Path(ex.path).resolve()

        # 6. run_target hygiene
        run_target = _safe_basename(plan.run_target or _adapter_default_target(ex, plan.model))
        target_file = canonical_dir / run_target
        if canonical_dir.is_dir() and not target_file.is_file():
            raise SubmitBlocked("run-target",
                                f"{run_target!r} is not a file in the example")

        # 6b. input-fingerprint binding (task 5): if the human approved a
        #     specific set of file contents, a later edit blocks the run.
        self._verify_input_fingerprint(ctx, plan, approval, canonical_dir, run_target)

        # 7. stage a user-owned working copy — canonical is never touched
        mgr = ctx.workspace_manager
        if mgr is None:
            raise SubmitBlocked("workspace", "no WorkspaceManager on the context")
        extra_files, entry_transform = _staging_glue(plan.model, plan.parameter_overrides)
        staged = mgr.stage_example_for_run(
            source_example=str(canonical_dir),
            extra_files=extra_files,
            entrypoint=run_target,
            entrypoint_transform=entry_transform,
            overrides=plan.parameter_overrides or None,
        )
        if Path(staged.path).resolve() == canonical_dir:
            raise SubmitBlocked("staging", "refusing to run against the canonical example")

        # 8. dataset references beyond the example's own -> user-scoped resolve
        self._check_datasets(plan, mgr)

        # 9. stack provenance (container backend)
        stack = self._resolve_stack_provenance(plan, profile)

        # 10. SUBMIT via the injected submitter
        result = self._submitter(**self._submit_kwargs(
            plan, profile, staged, run_target, matlab_license, stack))
        job_id = getattr(result, "job_id", None) or (
            result.get("jobid") if isinstance(result, dict) else None)
        working_dir = getattr(result, "working_directory", None) or (
            result.get("remote_dir") if isinstance(result, dict) else "")
        log_path = getattr(result, "log_path", None) or (
            result.get("log_file") if isinstance(result, dict) else None)

        # 11. register the run, owned by ctx.user, stamped with the digest
        self._register_run(ctx, plan, profile, staged, job_id, working_dir,
                           log_path, stack)

        ctx.trace.append("execution_decision", {
            "backend": "remote", "submitted": True, "job_id": job_id,
            "plan_digest": plan.digest()})
        return str(job_id)

    # -- steps -------------------------------------------------------
    def _verify_input_fingerprint(self, ctx, plan, approval, canonical_dir,
                                  run_target) -> None:
        expected = getattr(approval, "input_fingerprint", "") or ""
        if not expected:
            return
        from cryostack_src.agents.fingerprint import fingerprint_inputs
        mgr = ctx.workspace_manager
        ds_paths = []
        if mgr is not None and plan.datasets:
            try:
                cat = {d.get("name"): d.get("path") for d in mgr.list_datasets()}
                ds_paths = [Path(cat[n]) for n in plan.datasets if cat.get(n)]
            except Exception:
                ds_paths = []
        have = fingerprint_inputs(canonical_dir, run_target=run_target,
                                  dataset_paths=ds_paths)
        if have.digest() != expected:
            raise SubmitBlocked(
                "inputs",
                "the approved input fingerprint no longer matches — a source "
                "file or dataset changed since approval; re-validate and "
                "re-approve")

    def _enforce_b3(self, profile) -> None:
        from cryostack_src.remote.access_state import enforce_remote_access
        gate = enforce_remote_access(
            self._conn.bridge,
            profile=profile,
            access_mode=self._conn.access_mode,
            resolved_mode=self._conn.resolved_mode,
            hpc_username=self._conn.user,
            remote_directory=self._conn.remote_base_dir,
            connector_online=self._conn.connector_online,
        )
        if not gate.ok:
            raise SubmitBlocked("B3", gate.messages or ["remote access not verified"])

    def _enforce_b4(self, plan, profile) -> None:
        from icesee_jupyter_book.ui.shared_validation import validate_slurm_resources
        msgs = validate_slurm_resources(
            nodes=plan.slurm.nodes, tasks=plan.slurm.tasks,
            tasks_per_node=plan.slurm.tasks_per_node,
            wall_time=plan.slurm.wall_time, memory=plan.slurm.memory,
            account=plan.slurm.account, account_required=profile.account_required,
        )
        if plan.slurm.account and not _ACCOUNT_RE.match(plan.slurm.account):
            msgs = list(msgs) + [f"account {plan.slurm.account!r} has illegal characters"]
        if msgs:
            raise SubmitBlocked("B4", msgs)

    def _preflight(self, plan, profile):
        from cryostack_src.models import get_model_capabilities
        matlab_license = None
        if plan.backend == "container" and get_model_capabilities(plan.model).requires_matlab:
            matlab_license = profile.matlab_license_config()
            if matlab_license is None:
                raise SubmitBlocked(
                    "preflight",
                    f"{plan.model.upper()} runs MATLAB in the container but "
                    f"{profile.name} has no MATLAB licence configured")
        return matlab_license

    def _check_datasets(self, plan, mgr) -> None:
        if not plan.datasets:
            return
        try:
            owned = {d["name"] if isinstance(d, dict) else str(d)
                     for d in mgr.list_datasets()}
        except Exception:
            owned = set()
        missing = [d for d in plan.datasets if d not in owned]
        if missing:
            raise SubmitBlocked("datasets",
                                f"not in your workspace: {', '.join(missing)}")

    def _resolve_stack_provenance(self, plan, profile) -> dict:
        if plan.backend != "container" or self._resolve_stack is None:
            return {}
        try:
            return self._resolve_stack(
                model=plan.model, profile=self._conn.software_selections.get("profile"),
                selections=self._conn.software_selections,
                container_source=self._conn.container_source,
                image_uri=self._conn.image_uri,
                tested_image_key=self._conn.tested_image_key,
                digest_resolver=None,
            ) or {}
        except Exception as err:
            raise SubmitBlocked("stack", f"{type(err).__name__}: {err}")

    def _submit_kwargs(self, plan, profile, staged, run_target,
                       matlab_license, stack) -> dict:
        stack_line = ""
        if stack:
            try:
                from cryostack_src.models.stack import stack_log_line
                stack_line = stack_log_line(stack)
            except Exception:
                stack_line = ""
        return dict(
            host=self._conn.host, user=self._conn.user, port=int(self._conn.port),
            remote_base_dir=self._conn.remote_base_dir,
            remote_tag=self._conn.remote_tag,
            backend=plan.backend, model=plan.model,
            example_dir=str(staged.path), exec_dir=self._conn.exec_dir,
            image_uri=self._conn.image_uri,
            container_source=self._conn.container_source,
            spack_enable=self._conn.spack_enable,
            spack_repo_url=self._conn.spack_repo_url,
            spack_dirname=self._conn.spack_dirname,
            spack_install_if_needed=False,          # NEVER install at submit
            spack_install_mode=(
                self._conn.spack_install_mode
                or ("--with-issm" if plan.model == "issm" else "--with-icepack")),
            spack_slurm_dir="", spack_pmix_dir="",
            slurm_time=plan.slurm.wall_time,
            slurm_job_name=_safe_job_name(plan.slurm.job_name,
                                          fallback=plan.model.upper()),
            slurm_nodes=int(plan.slurm.nodes), slurm_ntasks=int(plan.slurm.tasks),
            slurm_tpn=int(plan.slurm.tasks_per_node),
            slurm_part=self._conn.slurm_partition,
            slurm_mem=plan.slurm.memory, slurm_account=plan.slurm.account,
            slurm_mail="",                          # no LLM-supplied mail
            test_mode=False, run_file=run_target,
            stack_log_line=stack_line,
            stack_software=(stack.get("software") if stack else {}) or {},
            matlab_license=matlab_license,
        )

    def _register_run(self, ctx, plan, profile, staged, job_id, working_dir,
                      log_path, stack) -> None:
        from cryostack_src.agents.trace_store import run_manifest_stamp
        appr = getattr(ctx, "_approval", None)   # optional, set by the coordinator
        stamp = run_manifest_stamp(
            trace_id=ctx.trace.trace_id, plan_digest=plan.digest(),
            approver_user_id=getattr(appr, "approver_user_id", ctx.user_id),
            approved_at=getattr(appr, "approved_at", ""),
        )
        metadata = {
            "cluster_name": profile.name,
            "access_mode": self._conn.access_mode,
            "parameter_overrides": dict(plan.parameter_overrides),
            "working_copy": str(staged.path),
            "working_copy_from_canonical": staged.from_canonical,
            **stamp,
        }
        if self._register is not None:
            self._register(
                name=Path(str(working_dir)).name or str(job_id),
                model=plan.model, backend=plan.backend, execution_mode="remote",
                jobid=str(job_id) if job_id else None,
                remote_directory=Path(str(working_dir)) if working_dir else Path("."),
                log_file=Path(str(log_path)) if log_path else None,
                metadata=metadata,
                container=(stack.get("container") if stack else {}) or {},
                software=(stack.get("software") if stack else {}) or {},
            )


# ── default seams ────────────────────────────────────────────────────
def _default_example_resolver(ctx, model: str, name: str):
    from cryostack_src.agents.planning_tools import _resolve_example
    return _resolve_example(ctx, model, name)


def _adapter_default_target(ex, model: str) -> str:
    from cryostack_src.models import get_model_adapter
    adapter = get_model_adapter(model)
    if getattr(ex, "entrypoint", None):
        return ex.entrypoint
    try:
        names = ([c.name for c in Path(ex.path).iterdir()]
                 if Path(ex.path).is_dir() else [Path(ex.path).name])
        return getattr(adapter, "choose_run_target", lambda n: "")(names) or ""
    except OSError:
        return ""


def _staging_glue(model: str, overrides: dict) -> tuple[dict | None, Any]:
    """Return (extra_files, entrypoint_transform) for a model's Basic-mode
    overrides — the same glue the gateway uses at submit time."""
    overrides = overrides or {}
    if not overrides:
        return None, None
    if model == "issm":
        from cryostack_src.models.issm import build_md_override_script, inject_override_step
        # validate_md_config already ran in planning; normalized == overrides
        return ({"cryostack_md_overrides.m": build_md_override_script(overrides)},
                inject_override_step)
    if model == "icepack":
        from cryostack_src.models.icepack import entrypoint_transform_for
        return None, entrypoint_transform_for(overrides)
    return None, None
