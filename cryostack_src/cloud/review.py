# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Review & Launch
# File        : review.py
#
# Description :
#     Assemble the "Review cloud run" surface: experiment + resources +
#     expected runtime + estimated cost + infrastructure readiness + launch
#     gating + a drift-detection digest.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-09-03
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
:func:`build_cloud_run_review` produces one :class:`CloudRunReview` -- the
single object the Review & Launch card renders and the launch gate consults.

Design rules:

* the resource values shown are the **canonical** ones from
  :class:`~cryostack_src.cloud.config.CloudRunConfig.fargate` -- the same
  values C7.5's submit path uses. No cost-specific copy.
* a missing cost estimate never blocks Launch (only shows "unavailable").
* :func:`review_digest` fingerprints the billable scientific + resource
  configuration; the UI recomputes it before Launch and forces a re-review if
  it changed. This is an integrity check, not an approval workflow.
* no secret is ever placed in a review (no STS credentials, no ExternalId).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

from cryostack_src.cloud.config import CloudRunConfig
from cryostack_src.cloud.estimate.models import CloudCostEstimate, RuntimeEstimate
from cryostack_src.cloud.preflight import SUPPORTED_CLOUD_MODELS


@dataclass
class InfrastructureReadiness:
    account: bool = False
    storage: bool = False
    container: bool = False
    compute: bool = False

    @property
    def all_ready(self) -> bool:
        return all((self.account, self.storage, self.container, self.compute))

    def as_dict(self) -> dict:
        return {
            "account": self.account,
            "storage": self.storage,
            "container": self.container,
            "compute": self.compute,
        }


@dataclass
class CloudRunReview:
    # experiment
    model: str
    example: str
    run_target: str
    # aws (non-secret)
    account_id: str
    region: str
    # canonical resources
    vcpu: float
    memory_gib: float
    time_limit_minutes: int
    expected_runtime_minutes: float
    runtime_source: str
    # cost
    cost: CloudCostEstimate
    # infrastructure
    infrastructure: InfrastructureReadiness
    # gating
    can_launch: bool
    blocked_reasons: list[str] = field(default_factory=list)
    # drift protection
    digest: str = ""
    # the resolved config the launch path must use verbatim
    config: CloudRunConfig | None = None

    # -- presentation ------------------------------------------------
    def resource_summary(self) -> str:
        return f"{self.vcpu:g} vCPU · {self.memory_gib:g} GiB"

    def cost_summary(self) -> str:
        return self.cost.display_total() if self.cost.available else "unavailable"

    def estimate_basis_lines(self) -> list[str]:
        lines = [
            f"AWS Fargate pricing in {self.region}",
            f"Expected runtime: ~{_round_minutes(self.expected_runtime_minutes)} "
            f"min ({self.runtime_source})",
        ]
        if self.cost.available and self.cost.source_timestamp:
            lines.append(f"Price checked: {self.cost.source_timestamp}")
        elif not self.cost.available:
            lines.append("Cost estimate unavailable")
        return lines

    def to_public_dict(self) -> dict:
        return {
            "model": self.model,
            "example": self.example,
            "run_target": self.run_target,
            "account_id": self.account_id,
            "region": self.region,
            "vcpu": self.vcpu,
            "memory_gib": self.memory_gib,
            "time_limit_minutes": self.time_limit_minutes,
            "expected_runtime_minutes": self.expected_runtime_minutes,
            "runtime_source": self.runtime_source,
            "cost": self.cost.to_public_dict(),
            "infrastructure": self.infrastructure.as_dict(),
            "can_launch": self.can_launch,
            "blocked_reasons": list(self.blocked_reasons),
            "digest": self.digest,
        }


# ---------------------------------------------------------------------------
# drift digest
# ---------------------------------------------------------------------------
BILLING_CHARGE_NOTE = (
    "This is an estimate. AWS charges apply to your AWS account. AWS "
    "promotional/free-tier credits, billing rules, and payment methods are "
    "managed by AWS, and CryoStack cannot guarantee a run is covered by them."
)


def review_digest(
    *,
    config: CloudRunConfig,
    model: str,
    example: str,
    run_target: str,
    account_id: str,
    scientific_overrides: dict | None = None,
) -> str:
    """A short stable hash over the billable scientific + resource config.

    Any change -> a new digest -> the open review is invalidated and the user
    must Review again before Launch.
    """
    payload = {
        "model": (model or "").strip().lower(),
        "example": (example or "").strip().lower(),
        "run_target": (run_target or "").strip(),
        "region": config.region,
        "account_id": account_id,
        "vcpu": config.vcpu,
        "memory_gib": round(config.memory_gib, 4),
        "time_limit_minutes": config.time_limit_minutes,
        "ephemeral_gib": config.ephemeral_gib,
        "job_definition": config.job_definition,
        "scientific_overrides": _canonical(scientific_overrides or {}),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _canonical(obj):
    if isinstance(obj, dict):
        return {k: _canonical(obj[k]) for k in sorted(obj)}
    if isinstance(obj, (list, tuple)):
        return [_canonical(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# builder
# ---------------------------------------------------------------------------
def build_cloud_run_review(
    *,
    config: CloudRunConfig,
    model: str,
    example: str,
    run_target: str,
    account_id: str,
    region: str,
    infrastructure: InfrastructureReadiness,
    runtime: RuntimeEstimate,
    cost: CloudCostEstimate,
    account_freshly_verified: bool,
    config_problems: list[str] | None = None,
    preflight_problems: list[str] | None = None,
    scientific_overrides: dict | None = None,
) -> CloudRunReview:
    """Assemble a review and decide whether Launch is allowed.

    Launch is gated on: fresh account verification + all infrastructure Ready
    + supported model + config validates + preflight passes (incl. the ISSM
    MATLAB-license requirement). A missing cost estimate does NOT gate.
    """
    reasons: list[str] = []

    if not account_freshly_verified:
        reasons.append(
            "Your AWS account connection could not be verified just now. "
            "Re-check it in Cloud Environment → AWS ACCOUNT."
        )
    for label, ready in (
        ("Storage", infrastructure.storage),
        ("Container repository", infrastructure.container),
        ("Compute (AWS Batch)", infrastructure.compute),
    ):
        if not ready:
            reasons.append(f"{label} is not prepared. Run Prepare cloud first.")

    if (model or "").strip().lower() not in SUPPORTED_CLOUD_MODELS:
        reasons.append(f"Model {model!r} has no supported cloud runtime yet.")

    for problem in (config_problems or []):
        reasons.append(problem)

    # preflight (includes: ISSM needs a cloud-reachable MATLAB license)
    for problem in (preflight_problems or []):
        cleaned = problem.replace("[cloud][ERROR] ", "").strip()
        if "MATLAB" in cleaned or "matlab" in cleaned:
            reasons.append(
                "Cloud infrastructure is ready, but ISSM execution requires a "
                "MATLAB license that is reachable from AWS."
            )
        else:
            reasons.append(cleaned)

    digest = review_digest(
        config=config, model=model, example=example, run_target=run_target,
        account_id=account_id, scientific_overrides=scientific_overrides,
    )

    return CloudRunReview(
        model=model,
        example=example,
        run_target=run_target,
        account_id=account_id,
        region=region,
        vcpu=config.vcpu,
        memory_gib=config.memory_gib,
        time_limit_minutes=config.time_limit_minutes,
        expected_runtime_minutes=runtime.minutes,
        runtime_source=runtime.source,
        cost=cost,
        infrastructure=infrastructure,
        can_launch=not reasons,
        blocked_reasons=reasons,
        digest=digest,
        config=config,
    )


def _round_minutes(minutes: float) -> str:
    m = float(minutes)
    return f"{m:.0f}" if m >= 1 else f"{m:.1f}"
