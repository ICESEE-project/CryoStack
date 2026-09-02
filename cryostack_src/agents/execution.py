"""Dry-run execution coordinator (A6).

The coordinator walks the *phases* a real run goes through and stops exactly
at the point where a job would be submitted:

    revalidate -> check_approval -> resolve_identity -> stage
    -> precheck_scheduler -> SUBMIT (boundary)

In dry-run mode (the default, and the only mode wired in PASS 3) the SUBMIT
phase produces a **description** of the command that *would* be issued
(``sbatch …`` on the remote, or ``aws batch submit-job …``) and returns.
Nothing is sent to an HPC scheduler or to AWS Batch.

A real backend is injected as :class:`SubmitBackend`. There is deliberately
none in the tree: wiring one is a human integration step, gated on the same
B3 remote-identity verification the gateway uses. The coordinator itself
never imports the remote / cloud submission modules, so this file stays clean
under ``policy.assert_tool_modules_are_clean``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from .approval import ApprovalError, ManagedPlan, PlanState, assert_approved_for_execution
from .permissions import Permission, PermissionError
from .planning import RunPlan


class ExecutionPhase(str, Enum):
    REVALIDATE = "revalidate"
    CHECK_APPROVAL = "check_approval"
    RESOLVE_IDENTITY = "resolve_identity"
    STAGE = "stage"
    PRECHECK_SCHEDULER = "precheck_scheduler"
    SUBMIT = "submit"


@dataclass(frozen=True)
class PhaseOutcome:
    phase: str
    status: str          # "ok" | "would-run" | "blocked" | "skipped"
    detail: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"phase": self.phase, "status": self.status,
                "detail": self.detail, "data": self.data}


@dataclass(frozen=True)
class DryRunReport:
    plan_id: str
    plan_digest: str
    execution_mode: str
    dry_run: bool
    outcomes: tuple[PhaseOutcome, ...]
    submission_command: str      # what WOULD be issued (redacted, no secrets)
    submitted: bool
    job_id: str | None = None
    blocked_reason: str | None = None

    @property
    def reached_submit_boundary(self) -> bool:
        return any(o.phase == ExecutionPhase.SUBMIT.value for o in self.outcomes)

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "plan_digest": self.plan_digest,
            "execution_mode": self.execution_mode,
            "dry_run": self.dry_run,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "submission_command": self.submission_command,
            "submitted": self.submitted,
            "job_id": self.job_id,
            "blocked_reason": self.blocked_reason,
            "reached_submit_boundary": self.reached_submit_boundary,
        }


class SubmitBackend(Protocol):
    """A real submitter. Implementations live outside the agents package and
    are wired in by an explicit human integration step (never by an agent).
    Must perform B3 remote-identity verification before issuing anything."""

    def submit(self, plan: RunPlan, *, ctx: Any) -> str:  # returns a job id
        ...


class ExecutionBlocked(RuntimeError):
    """A phase before SUBMIT failed; the run did not proceed."""


def _describe_submission(plan: RunPlan) -> str:
    """The command that WOULD be issued. Names and counts only — no host, no
    account, no credentials, no paths."""
    if plan.execution_mode == "cloud":
        return (f"aws batch submit-job --job-name {plan.slurm.job_name} "
                f"--job-queue <cryostack-queue> --job-definition <cryostack-{plan.model}> "
                f"(env: CRYOSTACK_MODEL={plan.model}, "
                f"CRYOSTACK_RUN_TARGET={plan.run_target or '<default>'})")
    s = plan.slurm
    return (f"sbatch --job-name {s.job_name} --nodes {s.nodes} "
            f"--ntasks {s.tasks} --ntasks-per-node {s.tasks_per_node}"
            + (f" --time {s.wall_time}" if s.wall_time else "")
            + (f" --mem {s.memory}" if s.memory else "")
            + " <staged>/run.sbatch   [on the verified remote]")


class DryRunExecutionCoordinator:
    def __init__(self, *, submit_backend: SubmitBackend | None = None) -> None:
        self._backend = submit_backend

    def execute(self, ctx, mp: ManagedPlan, *, dry_run: bool = True) -> DryRunReport:
        plan = mp.plan
        outcomes: list[PhaseOutcome] = []
        submission = _describe_submission(plan)

        def report(*, submitted=False, job_id=None, blocked=None) -> DryRunReport:
            return DryRunReport(
                plan_id=mp.plan_id, plan_digest=plan.digest(),
                execution_mode=plan.execution_mode,
                dry_run=dry_run or self._backend is None,
                outcomes=tuple(outcomes), submission_command=submission,
                submitted=submitted, job_id=job_id, blocked_reason=blocked)

        ctx.trace.append("execution_decision", {
            "plan_digest": plan.digest(), "dry_run": dry_run,
            "backend_wired": self._backend is not None})

        # 1. permission ceiling — an EXECUTE action needs an EXECUTE context.
        if not dry_run and not ctx.can(Permission.EXECUTE):
            outcomes.append(PhaseOutcome(
                ExecutionPhase.REVALIDATE.value, "blocked",
                "context is not permitted to execute (needs EXECUTE)"))
            ctx.trace.failure("execution", "permission ceiling below EXECUTE")
            return report(blocked="permission")

        # 2. revalidate against the live rules
        v = _revalidate(ctx, plan)
        if v["has_errors"]:
            outcomes.append(PhaseOutcome(
                ExecutionPhase.REVALIDATE.value, "blocked",
                "plan no longer validates", {"errors": v["errors"]}))
            return report(blocked="validation")
        outcomes.append(PhaseOutcome(
            ExecutionPhase.REVALIDATE.value, "ok",
            "plan validates; digest unchanged", {"digest": v["digest"]}))

        # 3. approval must be present AND bound to the live digest
        try:
            assert_approved_for_execution(mp)
        except ApprovalError as e:
            outcomes.append(PhaseOutcome(
                ExecutionPhase.CHECK_APPROVAL.value, "blocked", str(e)))
            ctx.trace.failure("execution", f"approval: {e}")
            return report(blocked="approval")
        outcomes.append(PhaseOutcome(
            ExecutionPhase.CHECK_APPROVAL.value, "ok",
            f"approved by {mp.approval.approver_user_id} for this digest"))

        # 4. identity — described, not performed
        if plan.execution_mode == "remote":
            outcomes.append(PhaseOutcome(
                ExecutionPhase.RESOLVE_IDENTITY.value, "would-run",
                "a real run verifies the remote identity (B3): runs the "
                "resource's verification command and compares it to your "
                "configured HPC username before staging"))
        else:
            outcomes.append(PhaseOutcome(
                ExecutionPhase.RESOLVE_IDENTITY.value, "skipped",
                "cloud runs use the Batch task role; no interactive identity"))

        # 5. stage — described, not performed
        outcomes.append(PhaseOutcome(
            ExecutionPhase.STAGE.value, "would-run",
            "stage a working copy of the example, apply the approved "
            "parameter overrides, generate the run + post-process scripts, "
            "archive and upload", {
                "run_target": plan.run_target,
                "parameter_overrides": dict(plan.parameter_overrides),
                "datasets": list(plan.datasets),
                "expected_result_contract": plan.expected_result_contract,
            }))

        # 6. scheduler precheck — described
        outcomes.append(PhaseOutcome(
            ExecutionPhase.PRECHECK_SCHEDULER.value, "would-run",
            "write the scheduler directives", {
                "nodes": plan.slurm.nodes, "tasks": plan.slurm.tasks,
                "tasks_per_node": plan.slurm.tasks_per_node,
                "wall_time": plan.slurm.wall_time or "(resource default)",
            }))

        # 7. SUBMIT boundary
        if dry_run or self._backend is None:
            outcomes.append(PhaseOutcome(
                ExecutionPhase.SUBMIT.value, "would-run",
                "STOP: dry run. The line below is what a wired backend would "
                "issue; nothing was submitted.",
                {"command": submission}))
            ctx.trace.append("execution_decision",
                             {"submitted": False, "reason": "dry_run"})
            return report(submitted=False)

        # live path (no backend ships in PASS 3)
        job_id = self._backend.submit(plan, ctx=ctx)
        mp.mark_executing()
        outcomes.append(PhaseOutcome(
            ExecutionPhase.SUBMIT.value, "ok", "submitted",
            {"job_id": job_id}))
        ctx.trace.append("execution_decision",
                         {"submitted": True, "job_id": job_id})
        return report(submitted=True, job_id=job_id)


def _revalidate(ctx, plan: RunPlan) -> dict:
    """Re-run the planning validator against the live plan."""
    from .planning_tools import validate_run_plan
    result = validate_run_plan(ctx, plan=plan.to_dict())
    errors = [f["message"] for f in result["findings"] if f["level"] == "error"]
    return {"has_errors": bool(errors), "errors": errors,
            "digest": result["digest"]}
