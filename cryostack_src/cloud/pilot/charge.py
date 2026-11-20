"""Conservative integer-cent charge for one hosted-pilot Fargate job.

The gateway settles a participant's credit from the job's own AWS Batch
timestamps. This is an allowance charge, not AWS billing: it deliberately
errs high and the caller caps it at the reservation's hold.

Rates: settlement must work with no network access, so by default this uses
:data:`DEFAULT_RATES` -- a FIXED table set above the on-demand Linux/x86
Fargate list price of every commercial region -- rather than the live AWS
Price List lookup in ``cloud.estimate.pricing``. A caller that already holds
resolved ``FargatePrices`` (or config price overrides) may pass them as
``rates``. The arithmetic itself is ``cloud.estimate.estimate_cloud_cost``,
the same formula the cost review shows.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from cryostack_src.cloud.estimate.estimator import estimate_cloud_cost
from cryostack_src.cloud.estimate.models import FargatePrices

#: Fixed offline rates (USD/hour), above every region's on-demand list price.
DEFAULT_RATES = FargatePrices(
    region="any", vcpu_usd_per_hour=0.07, gib_usd_per_hour=0.008,
    ephemeral_usd_per_gib_hour=0.00015, source="CryoStack fixed conservative table",
    available=True)
DEFAULT_ANCILLARY_CENTS = 1
#: Fargate bills from image pull, before Batch reports RUNNING.
DEFAULT_STARTUP_SECONDS = 60
#: Fargate's minimum billed duration.
MINIMUM_BILLED_SECONDS = 60


def _seconds(value) -> float | None:
    """Epoch seconds from a Batch timestamp (milliseconds) or plain seconds."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number / 1000.0 if number > 1e11 else number


def rates_from(overrides: Mapping[str, Any] | FargatePrices | None) -> FargatePrices:
    """``FargatePrices`` from config price overrides; missing or unusable -> defaults."""
    if isinstance(overrides, FargatePrices):
        ok = overrides.available and overrides.vcpu_usd_per_hour > 0 and overrides.gib_usd_per_hour > 0
        return overrides if ok else DEFAULT_RATES
    values = dict(overrides or {})
    vcpu = float(values.get("vcpu_usd_per_hour") or 0) or DEFAULT_RATES.vcpu_usd_per_hour
    gib = float(values.get("gib_usd_per_hour") or 0) or DEFAULT_RATES.gib_usd_per_hour
    return FargatePrices(region="any", vcpu_usd_per_hour=vcpu, gib_usd_per_hour=gib,
                         ephemeral_usd_per_gib_hour=DEFAULT_RATES.ephemeral_usd_per_gib_hour,
                         source="pilot config price override", available=True)


def charge_cents(*, vcpu, memory_mib, started_at, stopped_at, created_at, rates=None,
                 ancillary_cents: int = DEFAULT_ANCILLARY_CENTS,
                 startup_seconds: float = DEFAULT_STARTUP_SECONDS,
                 ephemeral_gib: float = 20.0, task_rate_usd_per_hour=None) -> int:
    """Whole cents to charge for one terminal job.

    Timestamps are AWS Batch ``createdAt`` / ``startedAt`` / ``stoppedAt``
    (epoch milliseconds; plain seconds are accepted too).

    * start known: billed from ``startup_seconds`` before the start (image
      pull), never earlier than creation, to the stop; at least 1 cent;
    * start unknown: billed from creation to the stop;
    * at least Fargate's one-minute minimum, always rounded UP to a cent;
    * plus ``ancillary_cents`` for storage, logs and transfer.

    ``task_rate_usd_per_hour`` (the reviewed execution profile's whole-task
    rate, a decimal string) replaces the per-vCPU / per-GiB table when given.

    Raises ``ValueError`` when there is no stop time or no usable interval --
    the caller then charges the full hold. The caller caps at the hold.
    """
    stop = _seconds(stopped_at)
    start = _seconds(started_at)
    created = _seconds(created_at)
    if stop is None:
        raise ValueError("a terminal job needs a stop time to be charged")
    if start is not None:
        begin = start - max(0.0, float(startup_seconds))
        if created is not None:
            begin = max(begin, min(created, start))
    elif created is not None:
        begin = created
    else:
        raise ValueError("a job needs a start or creation time to be charged")
    cpu, memory = float(vcpu), float(memory_mib)
    if not (cpu > 0 and memory > 0):
        raise ValueError("a charged job needs positive vCPU and memory")
    elapsed = max(float(MINIMUM_BILLED_SECONDS), stop - begin)
    if task_rate_usd_per_hour is not None:
        rate = float(task_rate_usd_per_hour)
        if not (math.isfinite(rate) and rate > 0):
            raise ValueError("a reviewed task rate must be positive")
        dollars = rate * elapsed / 3600.0
    else:
        dollars = estimate_cloud_cost(
            region="any", vcpu=cpu, memory_gib=memory / 1024.0,
            expected_runtime_minutes=elapsed / 60.0, ephemeral_gib=float(ephemeral_gib),
            prices=rates_from(rates)).estimated_total_usd
    cents = math.ceil(dollars * 100.0 - 1e-9)
    if start is not None:
        cents = max(1, cents)
    return int(max(0, cents) + max(0, int(ancillary_cents)))


__all__ = ["DEFAULT_RATES", "DEFAULT_ANCILLARY_CENTS", "charge_cents", "rates_from"]
