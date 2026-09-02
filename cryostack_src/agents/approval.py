"""Human-approval boundary for run plans (A5).

Lifecycle::

    DRAFT -> VALIDATED -> AWAITING_APPROVAL -> APPROVED -> EXECUTING
                                                        -> COMPLETED / FAILED

An :class:`Approval` binds to the plan's **canonical digest**. The executor
(``execution.py``) refuses any plan whose live digest != the approved digest,
so an agent cannot get approval for configuration A and run configuration B.
Revising a plan (any scientific / resource field) resets it to ``DRAFT`` and
drops the approval.

There is **no agent tool that approves a plan** — approval is a human action,
performed by the same authenticated user the agent is acting for.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

from cryostack_src.workspace.identity import WorkspaceUser

from .planning import RunPlan


class PlanState(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalError(RuntimeError):
    """A plan was executed without a valid, digest-matching approval, or an
    illegal lifecycle transition was attempted."""


@dataclass(frozen=True)
class Approval:
    plan_digest: str
    approver_user_id: str
    approved_at: str            # ISO-8601 UTC
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "plan_digest": self.plan_digest,
            "approver_user_id": self.approver_user_id,
            "approved_at": self.approved_at,
            "note": self.note,
        }


@dataclass
class ManagedPlan:
    """A plan under lifecycle management. One per plan id."""

    plan_id: str
    owner_user_id: str
    plan: RunPlan
    state: PlanState = PlanState.DRAFT
    approval: Approval | None = None
    run_id: str | None = None
    failure_reason: str | None = None
    history: list[dict] = field(default_factory=list)

    def _log(self, event: str, **extra) -> None:
        self.history.append({
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event, "state": self.state.value, **extra,
        })

    # -- transitions --------------------------------------------------
    def mark_validated(self, validated_plan: RunPlan) -> None:
        # validation is advisory: it must not change the plan's scientific /
        # resource intent. If it did, that is a revision, not a validation.
        if validated_plan.digest() != self.plan.digest():
            self.revise(validated_plan)
            return
        self.plan = validated_plan
        self.state = (PlanState.VALIDATED if not validated_plan.has_errors
                      else PlanState.DRAFT)
        self._log("validated", errors=validated_plan.has_errors)

    def submit_for_approval(self) -> None:
        if self.plan.has_errors:
            raise ApprovalError("plan has validation errors; resolve them first")
        if self.state not in (PlanState.VALIDATED, PlanState.AWAITING_APPROVAL):
            raise ApprovalError(
                f"cannot request approval from state {self.state.value!r} "
                "(validate the plan first)")
        self.state = PlanState.AWAITING_APPROVAL
        self._log("submitted_for_approval", digest=self.plan.digest())

    def approve(self, approver: WorkspaceUser, *, note: str = "") -> Approval:
        if approver.user_id != self.owner_user_id:
            raise ApprovalError(
                "the approver must be the user the plan belongs to")
        if self.state != PlanState.AWAITING_APPROVAL:
            raise ApprovalError(
                f"cannot approve from state {self.state.value!r}")
        self.approval = Approval(
            plan_digest=self.plan.digest(),
            approver_user_id=approver.user_id,
            approved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            note=note,
        )
        self.state = PlanState.APPROVED
        self._log("approved", digest=self.approval.plan_digest,
                  approver=approver.user_id)
        return self.approval

    def revise(self, new_plan: RunPlan) -> None:
        """Replace the plan. Any change of scientific / resource intent drops
        the approval and returns to DRAFT."""
        changed = new_plan.digest() != self.plan.digest()
        self.plan = new_plan
        if changed or self.state in (PlanState.APPROVED, PlanState.AWAITING_APPROVAL):
            self.approval = None
            self.state = PlanState.DRAFT
            self._log("revised", digest=new_plan.digest(), intent_changed=changed)

    def mark_executing(self) -> None:
        assert_approved_for_execution(self)
        self.state = PlanState.EXECUTING
        self._log("executing")

    def mark_completed(self, run_id: str) -> None:
        self.state = PlanState.COMPLETED
        self.run_id = run_id
        self._log("completed", run_id=run_id)

    def mark_failed(self, reason: str) -> None:
        self.state = PlanState.FAILED
        self.failure_reason = reason
        self._log("failed", reason=reason)

    # -- view -------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "owner_user_id": self.owner_user_id,
            "state": self.state.value,
            "plan": self.plan.to_dict(),
            "approval": self.approval.to_dict() if self.approval else None,
            "run_id": self.run_id,
            "failure_reason": self.failure_reason,
            "digest_matches_approval": (
                self.approval is not None
                and self.approval.plan_digest == self.plan.digest()
            ),
            "history": list(self.history),
        }


def assert_approved_for_execution(mp: ManagedPlan) -> None:
    """The single gate the executor calls. Raises :class:`ApprovalError` unless
    the plan is APPROVED and its live digest matches the approved digest."""
    if mp.state != PlanState.APPROVED:
        raise ApprovalError(
            f"plan {mp.plan_id} is {mp.state.value!r}, not approved")
    if mp.approval is None:
        raise ApprovalError(f"plan {mp.plan_id} has no approval record")
    live = mp.plan.digest()
    if live != mp.approval.plan_digest:
        raise ApprovalError(
            f"plan {mp.plan_id} was modified after approval "
            f"(approved digest {mp.approval.plan_digest[:12]}…, "
            f"current {live[:12]}…) — re-validate and re-approve")


class PlanStore:
    """In-memory store of managed plans, keyed by plan id and scoped by owner.
    A real deployment would back this with the workspace; the interface is the
    same."""

    def __init__(self) -> None:
        self._plans: dict[str, ManagedPlan] = {}

    def create(self, *, owner: WorkspaceUser, plan: RunPlan) -> ManagedPlan:
        mp = ManagedPlan(plan_id=uuid.uuid4().hex, owner_user_id=owner.user_id,
                         plan=plan)
        mp._log("created", digest=plan.digest())
        self._plans[mp.plan_id] = mp
        return mp

    def get(self, plan_id: str, *, owner: WorkspaceUser) -> ManagedPlan:
        mp = self._plans.get(plan_id)
        if mp is None or mp.owner_user_id != owner.user_id:
            raise KeyError(f"no plan {plan_id!r} for this user")
        return mp

    def list_for(self, owner: WorkspaceUser) -> list[ManagedPlan]:
        return [mp for mp in self._plans.values()
                if mp.owner_user_id == owner.user_id]
