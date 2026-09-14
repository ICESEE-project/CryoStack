"""Experiment abstraction (P3) — a named group of runs that share a base
configuration and differ in one swept scientific parameter.

This is **purely additive**. An experiment expands to a list of ordinary
:class:`~cryostack_src.agents.planning.RunPlan` objects; each child run still
goes through the exact same approval + dry-run-execution boundary
(``approval.py`` / ``execution.py``) with its own digest. Nothing in the run
manifest, the WorkspaceManager, or the gateway changes.

The point: an agent (or a human) can propose "run the synthetic ice shelf at
250, 260, 270 K" as one reviewable object. Approving the *experiment* records
the experiment digest **and the full set of child digests**, so a child cannot
be swapped after approval any more than a single run can.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from cryostack_src.workspace.identity import WorkspaceUser

from .approval import Approval, ApprovalError, ManagedPlan, PlanState
from .planning import RunPlan, canonical_digest

_MAX_RUNS = 32          # a guard rail: an experiment is reviewable, not a fleet


@dataclass(frozen=True)
class SweepAxis:
    """One swept parameter: ``parameter`` takes each value in ``values``."""
    parameter: str
    values: tuple[Any, ...]

    def __post_init__(self) -> None:
        if not self.parameter:
            raise ValueError("sweep parameter name is required")
        vals = tuple(self.values)
        if len(vals) < 2:
            raise ValueError("a sweep needs at least two values")
        if len(vals) > _MAX_RUNS:
            raise ValueError(f"a sweep is capped at {_MAX_RUNS} values")
        if len(set(map(_hashable, vals))) != len(vals):
            raise ValueError("sweep values must be distinct")
        object.__setattr__(self, "values", vals)

    def to_dict(self) -> dict:
        return {"parameter": self.parameter, "values": list(self.values)}


def _hashable(v: Any):
    return json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v


@dataclass(frozen=True)
class ExperimentPlan:
    """A base run plan plus one sweep axis. ``expand()`` yields the children."""
    name: str
    base: RunPlan
    axis: SweepAxis

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("experiment name is required")
        if self.axis.parameter in self.base.parameter_overrides:
            # the base pins the swept parameter -> ambiguous intent
            raise ValueError(
                f"base plan already sets {self.axis.parameter!r}; remove it "
                "from the base or sweep a different parameter")

    # -- expansion --------------------------------------------------
    def expand(self) -> list[RunPlan]:
        out = []
        for value in self.axis.values:
            overrides = {**self.base.parameter_overrides,
                         self.axis.parameter: value}
            out.append(replace(self.base, parameter_overrides=overrides,
                               findings=(), approvals_required=(),
                               validated=False))
        return out

    @property
    def run_count(self) -> int:
        return len(self.axis.values)

    def child_digests(self) -> list[str]:
        return [p.digest() for p in self.expand()]

    # -- the experiment digest (approval binds to this) ------------
    def digest(self) -> str:
        return canonical_digest({
            "name": self.name.strip(),
            "base": self.base._digest_material(),
            "axis": self.axis.to_dict(),
            "children": self.child_digests(),
        })

    def scientific_changes(self) -> dict:
        return {
            "base_overrides": dict(self.base.parameter_overrides),
            "sweep": self.axis.to_dict(),
            "runs": self.run_count,
        }

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "base": self.base.to_dict(),
            "axis": self.axis.to_dict(),
            "run_count": self.run_count,
            "child_digests": self.child_digests(),
            "digest": self.digest(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExperimentPlan":
        return cls(
            name=d["name"],
            base=RunPlan.from_dict(d["base"]),
            axis=SweepAxis(parameter=d["axis"]["parameter"],
                           values=tuple(d["axis"]["values"])),
        )


@dataclass(frozen=True)
class ExperimentApproval:
    experiment_digest: str
    child_digests: tuple[str, ...]
    approver_user_id: str
    approved_at: str

    def to_dict(self) -> dict:
        return {
            "experiment_digest": self.experiment_digest,
            "child_digests": list(self.child_digests),
            "approver_user_id": self.approver_user_id,
            "approved_at": self.approved_at,
        }


@dataclass
class ManagedExperiment:
    """An experiment under lifecycle management. Owns one
    :class:`~cryostack_src.agents.approval.ManagedPlan` per child run; one human
    action approves them all, but each child keeps its own digest-bound
    approval so a child cannot be swapped afterwards."""

    experiment_id: str
    owner_user_id: str
    plan: ExperimentPlan
    children: list[ManagedPlan]
    state: PlanState = PlanState.DRAFT
    approval: ExperimentApproval | None = None

    @classmethod
    def create(cls, *, owner: WorkspaceUser, plan: ExperimentPlan) -> "ManagedExperiment":
        children = [
            ManagedPlan(plan_id=uuid.uuid4().hex, owner_user_id=owner.user_id,
                        plan=child)
            for child in plan.expand()
        ]
        return cls(experiment_id=uuid.uuid4().hex, owner_user_id=owner.user_id,
                   plan=plan, children=children)

    def validate(self, validate_fn: Callable[[RunPlan], RunPlan]) -> None:
        """``validate_fn`` maps a plan to a validated plan (findings attached).
        The experiment is VALIDATED only if every child is."""
        for mp in self.children:
            mp.mark_validated(validate_fn(mp.plan))
        ok = all(mp.state is PlanState.VALIDATED for mp in self.children)
        self.state = PlanState.VALIDATED if ok else PlanState.DRAFT

    def submit_for_approval(self) -> None:
        if self.state is not PlanState.VALIDATED:
            raise ApprovalError("every run in the experiment must validate first")
        for mp in self.children:
            mp.submit_for_approval()
        self.state = PlanState.AWAITING_APPROVAL

    def approve(self, approver: WorkspaceUser) -> ExperimentApproval:
        if approver.user_id != self.owner_user_id:
            raise ApprovalError("the approver must own the experiment")
        if self.state is not PlanState.AWAITING_APPROVAL:
            raise ApprovalError(f"cannot approve from state {self.state.value!r}")
        # the child digests must still match what the experiment expands to
        live_children = self.plan.child_digests()
        if [mp.plan.digest() for mp in self.children] != live_children:
            raise ApprovalError(
                "experiment expansion no longer matches its managed runs")
        for mp in self.children:
            mp.approve(approver)
        self.approval = ExperimentApproval(
            experiment_digest=self.plan.digest(),
            child_digests=tuple(live_children),
            approver_user_id=approver.user_id,
            approved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        self.state = PlanState.APPROVED
        return self.approval

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "owner_user_id": self.owner_user_id,
            "state": self.state.value,
            "plan": self.plan.to_dict(),
            "children": [mp.to_dict() for mp in self.children],
            "approval": self.approval.to_dict() if self.approval else None,
        }
