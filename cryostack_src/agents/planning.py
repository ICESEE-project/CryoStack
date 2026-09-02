"""``RunPlan`` — a structured, deterministic proposal for a scientific run.

A plan is **data, not prose**. The agent (or a human) fills it; the planning
layer validates it against the SAME rules the gateway uses (B4 Slurm
validation, the model's Basic-mode parameter spec, B3 identity requirements,
the model/backend preflight facts); nothing is submitted.

The plan carries a **canonical digest** (:meth:`RunPlan.digest`) computed over
only the scientific + resource fields. An approval binds to that digest
(``approval.py``), so a plan mutated after approval no longer matches and must
be re-approved.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any

_MODELS = ("issm", "icepack")
_EXECUTION_MODES = ("remote", "cloud")           # no "local" -- not implemented
_BACKENDS = ("spack", "container")

_RESULT_CONTRACT = {
    "issm": "cryostack.issm.results",
    "icepack": "cryostack.icepack.results",
}


@dataclass(frozen=True)
class SlurmRequest:
    job_name: str = "CRYOSTACK"
    nodes: int = 1
    tasks: int = 1
    tasks_per_node: int = 1
    wall_time: str = ""
    memory: str = ""
    account: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PlanFinding:
    level: str            # "error" | "warning" | "info"
    where: str            # "slurm" | "parameters" | "identity" | "preflight" | "plan"
    message: str

    def to_dict(self) -> dict:
        return {"level": self.level, "where": self.where, "message": self.message}


@dataclass(frozen=True)
class RunPlan:
    # -- scientific + resource intent (digest-bearing) --------------------
    application: str
    model: str
    example: str
    execution_mode: str
    compute_resource: str
    backend: str
    run_target: str = ""
    parameter_overrides: dict = field(default_factory=dict)
    datasets: tuple[str, ...] = ()
    slurm: SlurmRequest = field(default_factory=SlurmRequest)

    # -- derived / advisory (NOT in the digest) --------------------------
    expected_result_contract: str = ""
    detected_solvers: tuple[str, ...] = ()
    findings: tuple[PlanFinding, ...] = ()
    approvals_required: tuple[str, ...] = ()
    validated: bool = False

    # -- construction ---------------------------------------------------
    def __post_init__(self) -> None:
        if self.model not in _MODELS:
            raise ValueError(f"unknown model: {self.model!r}")
        if self.execution_mode not in _EXECUTION_MODES:
            raise ValueError(
                f"execution_mode must be one of {_EXECUTION_MODES} "
                f"(local execution is not implemented)"
            )
        if self.backend not in _BACKENDS:
            raise ValueError(f"backend must be one of {_BACKENDS}")
        if not self.expected_result_contract:
            object.__setattr__(self, "expected_result_contract",
                               _RESULT_CONTRACT[self.model])
        if isinstance(self.slurm, dict):
            object.__setattr__(self, "slurm", SlurmRequest(**self.slurm))
        object.__setattr__(self, "datasets", tuple(self.datasets or ()))

    # -- the digest (approval binds to this) --------------------------
    def _digest_material(self) -> dict:
        return {
            "application": self.application,
            "model": self.model,
            "example": self.example,
            "execution_mode": self.execution_mode,
            "compute_resource": self.compute_resource,
            "backend": self.backend,
            "run_target": self.run_target,
            "parameter_overrides": {k: self.parameter_overrides[k]
                                    for k in sorted(self.parameter_overrides)},
            "datasets": sorted(self.datasets),
            "slurm": self.slurm.to_dict(),
        }

    def digest(self) -> str:
        blob = json.dumps(self._digest_material(), sort_keys=True,
                          separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    # -- serialization -----------------------------------------------
    def to_dict(self) -> dict:
        return {
            **self._digest_material(),
            "expected_result_contract": self.expected_result_contract,
            "detected_solvers": list(self.detected_solvers),
            "findings": [f.to_dict() for f in self.findings],
            "approvals_required": list(self.approvals_required),
            "validated": self.validated,
            "digest": self.digest(),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)

    @classmethod
    def from_dict(cls, d: dict) -> "RunPlan":
        return cls(
            application=d["application"], model=d["model"], example=d["example"],
            execution_mode=d["execution_mode"],
            compute_resource=d["compute_resource"], backend=d["backend"],
            run_target=d.get("run_target", ""),
            parameter_overrides=dict(d.get("parameter_overrides") or {}),
            datasets=tuple(d.get("datasets") or ()),
            slurm=SlurmRequest(**d["slurm"]) if isinstance(d.get("slurm"), dict)
            else SlurmRequest(),
        )

    # -- helpers for the approval layer -----------------------------
    @property
    def has_errors(self) -> bool:
        return any(f.level == "error" for f in self.findings)

    def scientific_changes(self) -> dict:
        """The scientific delta a human must see before approving."""
        return dict(self.parameter_overrides)

    def with_findings(self, findings, *, approvals_required=(), solvers=()) -> "RunPlan":
        return replace(
            self, findings=tuple(findings),
            approvals_required=tuple(approvals_required),
            detected_solvers=tuple(solvers) or self.detected_solvers,
            validated=True,
        )
