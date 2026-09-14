# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Cost & Runtime Estimation
# File        : estimator.py
#
# Description :
#     Combine Fargate prices + a resource shape + an expected runtime into a
#     structured CloudCostEstimate.
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
:func:`estimate_cloud_cost` -- AWS Fargate usage cost for one run.

    compute = vCPU        x vcpu_rate/hr  x hours
    memory  = memory GiB  x gib_rate/hr   x hours
    storage = max(0, ephemeral GiB - 20 included) x eph_rate/hr x hours

The returned :class:`CloudCostEstimate` exposes ``estimate_for_elapsed`` so
C7.5's live "accumulated cost" display reuses exactly this pricing -- no second
copy of the formula.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import CloudCostEstimate, FargatePrices


@dataclass
class _Priced:
    """Callable cost model bound to one region's prices + resource shape."""

    prices: FargatePrices
    vcpu: float
    memory_gib: float
    billable_ephemeral_gib: float

    def for_minutes(self, minutes: float) -> tuple[float, float, float]:
        hours = max(0.0, float(minutes)) / 60.0
        compute = self.vcpu * self.prices.vcpu_usd_per_hour * hours
        memory = self.memory_gib * self.prices.gib_usd_per_hour * hours
        storage = (
            self.billable_ephemeral_gib
            * self.prices.ephemeral_usd_per_gib_hour
            * hours
        )
        return compute, memory, storage


def estimate_cloud_cost(
    *,
    region: str,
    vcpu: float,
    memory_gib: float,
    expected_runtime_minutes: float,
    ephemeral_gib: float = 20.0,
    prices: FargatePrices | None = None,
    runtime_source: str = "",
) -> CloudCostEstimate:
    """Return a :class:`CloudCostEstimate`. If ``prices`` is unavailable the
    estimate is returned with ``available=False`` and zeroed dollars -- the
    caller shows "Cost estimate unavailable" and does not block Launch."""
    vcpu = float(vcpu)
    memory_gib = float(memory_gib)
    included = float(getattr(prices, "ephemeral_included_gib", 20) or 20)
    billable_ephemeral = max(0.0, float(ephemeral_gib) - included)

    assumptions = [
        f"AWS Fargate on-demand pricing in {region}",
        f"{vcpu:g} vCPU, {memory_gib:g} GiB",
        f"Expected runtime: ~{_round_minutes(expected_runtime_minutes)} min"
        + (f" ({runtime_source})" if runtime_source else ""),
    ]
    if billable_ephemeral > 0:
        assumptions.append(
            f"{billable_ephemeral:g} GiB ephemeral storage beyond the 20 GiB "
            "included with every task"
        )

    if prices is None or not prices.available:
        return CloudCostEstimate(
            region=region,
            vcpu=vcpu,
            memory_gib=memory_gib,
            expected_runtime_minutes=float(expected_runtime_minutes),
            billable_ephemeral_gib=billable_ephemeral,
            source=(getattr(prices, "source", "") or "AWS Price List API"),
            source_timestamp=getattr(prices, "source_timestamp", ""),
            assumptions=assumptions,
            available=False,
            warning=(
                getattr(prices, "warning", "")
                or "AWS pricing could not be resolved."
            ),
        )

    model = _Priced(
        prices=prices,
        vcpu=vcpu,
        memory_gib=memory_gib,
        billable_ephemeral_gib=billable_ephemeral,
    )
    compute, memory, storage = model.for_minutes(expected_runtime_minutes)
    total = compute + memory + storage

    estimate = CloudCostEstimate(
        region=region,
        vcpu=vcpu,
        memory_gib=memory_gib,
        expected_runtime_minutes=float(expected_runtime_minutes),
        billable_ephemeral_gib=billable_ephemeral,
        compute_usd=compute,
        memory_usd=memory,
        storage_usd=storage,
        estimated_total_usd=total,
        source=prices.source,
        source_timestamp=prices.source_timestamp,
        assumptions=assumptions,
        available=True,
    )
    # attach the bound model for C7.5's live accumulated-cost display
    estimate.estimate_for_elapsed = _elapsed_helper(model)  # type: ignore[attr-defined]
    return estimate


def live_cost_usd(cost_public: dict, elapsed_seconds: float) -> float | None:
    """Estimated accumulated cost after ``elapsed_seconds``, computed purely
    from a retained ``CloudCostEstimate.to_public_dict()`` -- **no AWS Pricing
    call**.

    The C7.4 estimate is linear in time (rates x hours), so the accumulated
    cost is ``total x elapsed / expected``. Returns ``None`` when the estimate
    was unavailable at launch -- the caller shows "Unavailable", never a
    fabricated number.
    """
    if not (cost_public or {}).get("available"):
        return None
    total = float(cost_public.get("estimated_total_usd") or 0.0)
    expected_min = float(cost_public.get("expected_runtime_minutes") or 0.0)
    if expected_min <= 0:
        return None
    elapsed_min = max(0.0, float(elapsed_seconds)) / 60.0
    return total * (elapsed_min / expected_min)


def _elapsed_helper(model: _Priced):
    def estimate_for_elapsed(elapsed_seconds: float) -> float:
        compute, memory, storage = model.for_minutes(
            max(0.0, float(elapsed_seconds)) / 60.0
        )
        return compute + memory + storage

    return estimate_for_elapsed


def _round_minutes(minutes: float) -> str:
    m = float(minutes)
    return f"{m:.0f}" if m >= 1 else f"{m:.1f}"
