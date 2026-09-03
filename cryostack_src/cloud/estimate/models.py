# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Cost & Runtime Estimation
# File        : models.py
#
# Description :
#     Structured results for cloud runtime and cost estimation.
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

"""Estimation result models -- all plain, non-secret data."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FargatePrices:
    """Region-specific AWS Fargate on-demand rates (USD)."""

    region: str
    vcpu_usd_per_hour: float = 0.0
    gib_usd_per_hour: float = 0.0
    ephemeral_usd_per_gib_hour: float = 0.0
    #: 20 GiB of ephemeral storage are included with every Fargate task
    ephemeral_included_gib: int = 20
    source: str = ""
    source_timestamp: str = ""
    available: bool = False
    warning: str = ""


@dataclass(frozen=True)
class RuntimeEstimate:
    """Expected wall-clock runtime and where the number came from."""

    minutes: float
    source: str            # human-readable label
    #: machine tag: "history" | "example_table" | "time_limit"
    basis: str
    #: how many past runs informed a "history" estimate
    sample_size: int = 0


@dataclass
class CloudCostEstimate:
    """A structured estimate of one cloud run's AWS usage cost."""

    provider: str = "aws"
    region: str = ""
    vcpu: float = 0.0
    memory_gib: float = 0.0
    expected_runtime_minutes: float = 0.0
    billable_ephemeral_gib: float = 0.0

    compute_usd: float = 0.0
    memory_usd: float = 0.0
    storage_usd: float = 0.0
    estimated_total_usd: float = 0.0

    source: str = ""
    source_timestamp: str = ""
    assumptions: list[str] = field(default_factory=list)

    #: False when pricing could not be resolved -- the UI shows
    #: "Cost estimate unavailable" but never blocks Launch.
    available: bool = False
    warning: str = ""

    # -- presentation helpers -----------------------------------------
    def display_total(self) -> str:
        """A rounded, non-alarming dollar string (never 8 decimals)."""
        if not self.available:
            return "unavailable"
        return _format_usd(self.estimated_total_usd)

    def to_public_dict(self) -> dict:
        """Non-secret; safe for the frontend / provenance."""
        return {
            "provider": self.provider,
            "region": self.region,
            "vcpu": self.vcpu,
            "memory_gib": self.memory_gib,
            "expected_runtime_minutes": self.expected_runtime_minutes,
            "compute_usd": round(self.compute_usd, 4),
            "memory_usd": round(self.memory_usd, 4),
            "storage_usd": round(self.storage_usd, 4),
            "estimated_total_usd": round(self.estimated_total_usd, 4),
            "display_total": self.display_total(),
            "source": self.source,
            "source_timestamp": self.source_timestamp,
            "assumptions": list(self.assumptions),
            "available": self.available,
            "warning": self.warning,
        }


def _format_usd(value: float) -> str:
    """<$0.01 / $0.04 / $1.20 / $12 -- rounded, no fake precision."""
    v = max(0.0, float(value))
    if v < 0.01:
        return "<$0.01"
    if v < 10:
        return f"${v:.2f}"
    if v < 100:
        return f"${v:.1f}"
    return f"${v:.0f}"
