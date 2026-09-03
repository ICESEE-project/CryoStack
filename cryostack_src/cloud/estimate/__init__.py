# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Cost & Runtime Estimation
# File        : __init__.py
#
# Description :
#     Provider-aware, offline-testable estimation of the expected runtime and
#     AWS usage cost of a cloud experiment, for the Review & Launch surface.
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
Cloud estimation.

* :func:`resolve_fargate_prices` — region-specific AWS Fargate rates from the
  AWS Price List API (queried from ``us-east-1``), short-cached. Never
  fabricates a price: on any failure it returns ``available=False``.
* :func:`estimate_runtime` — expected wall-clock minutes, from previous
  successful CryoStack runs → a known-example table → the configured time
  limit, each with a labelled ``source``.
* :func:`estimate_cloud_cost` — a structured :class:`CloudCostEstimate`
  (compute + memory + ephemeral storage), with an ``estimate_for_elapsed``
  helper C7.5 reuses for the live accumulated-cost display.
"""

from __future__ import annotations

from .estimator import estimate_cloud_cost
from .models import (
    CloudCostEstimate,
    FargatePrices,
    RuntimeEstimate,
)
from .pricing import PRICE_CACHE_TTL_SECONDS, resolve_fargate_prices
from .runtime import KNOWN_EXAMPLE_RUNTIMES, estimate_runtime

__all__ = [
    "CloudCostEstimate",
    "FargatePrices",
    "KNOWN_EXAMPLE_RUNTIMES",
    "PRICE_CACHE_TTL_SECONDS",
    "RuntimeEstimate",
    "estimate_cloud_cost",
    "estimate_runtime",
    "resolve_fargate_prices",
]
