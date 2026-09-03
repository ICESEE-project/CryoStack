# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Cost & Runtime Estimation
# File        : runtime.py
#
# Description :
#     Expected wall-clock runtime for a cloud experiment.
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
Runtime estimation, in priority order:

1. **Previous successful CryoStack runs** for the same model + example (+
   resource shape) -- the median of the most recent durations, when enough
   reliable history exists.
2. **A known-example reference table** -- curated conservative estimates for
   the demo-ready examples.
3. **The configured time limit** -- the last resort; deliberately pessimistic.

The estimate is never presented as exact -- every result carries a ``source``
label the UI shows verbatim.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from statistics import median

from .models import RuntimeEstimate

#: minimum reliable successful-run samples before history is trusted
_MIN_HISTORY_SAMPLES = 3

#: conservative reference estimates (minutes) for curated demo examples.
#: keyed by (model, example) lowercased.
KNOWN_EXAMPLE_RUNTIMES: dict[tuple[str, str], float] = {
    ("issm", "squareiceshelf"): 5.0,
    ("issm", "square"): 5.0,
    ("issm", "pig"): 25.0,
    ("issm", "79north"): 20.0,
}

#: fraction of the configured time limit used as the last-resort estimate
_TIME_LIMIT_FRACTION = 1.0


def _history_estimate(
    durations_minutes: Sequence[float],
) -> RuntimeEstimate | None:
    usable = [float(d) for d in durations_minutes if d and d > 0]
    if len(usable) < _MIN_HISTORY_SAMPLES:
        return None
    recent = usable[-10:]
    return RuntimeEstimate(
        minutes=round(median(recent), 1),
        source="Based on previous successful CryoStack runs",
        basis="history",
        sample_size=len(recent),
    )


def estimate_runtime(
    *,
    model: str,
    example: str,
    time_limit_minutes: float,
    history_provider: Callable[[], Sequence[float]] | None = None,
) -> RuntimeEstimate:
    """Return the best available runtime estimate for this experiment."""
    key = ((model or "").strip().lower(), (example or "").strip().lower())

    # 1. previous successful runs
    if history_provider is not None:
        try:
            durations = history_provider() or []
        except Exception:  # noqa: BLE001 - history is best-effort
            durations = []
        hist = _history_estimate(durations)
        if hist is not None:
            return hist

    # 2. known-example reference table
    if key in KNOWN_EXAMPLE_RUNTIMES:
        return RuntimeEstimate(
            minutes=KNOWN_EXAMPLE_RUNTIMES[key],
            source=f"Based on the {example} reference estimate",
            basis="example_table",
        )

    # 3. configured time limit (pessimistic fallback)
    minutes = max(1.0, round(float(time_limit_minutes) * _TIME_LIMIT_FRACTION, 1))
    return RuntimeEstimate(
        minutes=minutes,
        source="Based on the configured time limit",
        basis="time_limit",
    )
