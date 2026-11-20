# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Cost & Runtime Estimation
# File        : pricing.py
#
# Description :
#     Region-specific AWS Fargate rates from the AWS Price List API.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-09-03
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: MIT
#
# =============================================================================

"""
AWS Fargate price resolution.

The AWS Price List (``aws pricing get-products``) is only served from a few
endpoints; CryoStack always queries it from **us-east-1** and selects the
target region through the ``regionCode`` product attribute -- the query region
and the priced region are independent.

Pricing data is public and account-independent, so the lookup deliberately
does **not** thread the connected BYO credentials by default (a stray Pricing
call must never switch accounts or touch stored STS credentials). A caller may
pass an explicit ``fetch`` for tests or to reuse an assumed-role session that
already carries ``pricing:GetProducts``.

Every failure path returns ``FargatePrices(available=False)`` -- a price is
never invented.
"""

from __future__ import annotations

import json
import re
import urllib.request
import subprocess
import time
from datetime import datetime, timezone

from .models import FargatePrices

#: AWS Price List endpoint region (not the region being priced)
PRICING_QUERY_REGION = "us-east-1"
#: short cache so a burst of UI refreshes makes one Pricing call
PRICE_CACHE_TTL_SECONDS = 6 * 60 * 60

# suffixes of the ``usagetype`` attribute that identify each Fargate rate
_VCPU_SUFFIX = "Fargate-vCPU-Hours:perCPU"
_GB_SUFFIX = "Fargate-GB-Hours"
_EPHEMERAL_SUFFIX = "Fargate-EphemeralStorage-GB-Hours"

_CACHE: dict[str, tuple[float, FargatePrices]] = {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _default_fetch(region: str) -> list[dict]:
    """Call the real ``aws pricing get-products`` and return parsed PriceList
    entries (each entry is itself a JSON string in the raw response)."""
    filters = [
        {"Type": "TERM_MATCH", "Field": "regionCode", "Value": region},
        {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Compute"},
    ]
    completed = subprocess.run(
        [
            "aws", "pricing", "get-products",
            "--region", PRICING_QUERY_REGION,
            "--service-code", "AmazonECS",
            "--filters", json.dumps(filters),
            "--output", "json",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if completed.returncode != 0:
        return _public_offer_fetch(region)
    payload = json.loads(completed.stdout or "{}")
    return [json.loads(item) for item in payload.get("PriceList", [])]


def _public_offer_fetch(region: str) -> list[dict]:
    """Anonymous official regional pricing when the service cannot use Pricing IAM.

    Only public rate data is fetched; no connected-account credentials leave
    the process. Bound response size and duration so cost review remains usable.
    """
    if not re.fullmatch(r"[a-z]{2}-[a-z]+-\d", region):
        raise ValueError("Invalid pricing region")
    url = ("https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/"
           f"AmazonECS/current/{region}/index.json")
    limit = 8 * 1024 * 1024
    with urllib.request.urlopen(url, timeout=15) as response:
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Regional pricing response exceeds limit")
    payload = json.loads(raw)
    terms = payload.get("terms", {}).get("OnDemand", {})
    return [{"product": product, "terms": {"OnDemand": terms.get(sku, {})}}
            for sku, product in payload.get("products", {}).items()]


def _on_demand_usd(product_entry: dict) -> float | None:
    """Pull the single OnDemand USD per-unit price from a PriceList entry."""
    terms = (product_entry.get("terms") or {}).get("OnDemand") or {}
    for term in terms.values():
        for dim in (term.get("priceDimensions") or {}).values():
            usd = (dim.get("pricePerUnit") or {}).get("USD")
            if usd is not None:
                try:
                    return float(usd)
                except (TypeError, ValueError):
                    return None
    return None


def parse_fargate_prices(region: str, entries: list[dict], *, source: str) -> FargatePrices:
    """Classify raw PriceList entries into the three Fargate rates.

    ``available`` is True only when both the vCPU and the GB rate were found
    and are > 0 -- an incomplete price is treated as no price.
    """
    vcpu = gib = ephemeral = 0.0
    for entry in entries:
        usagetype = (entry.get("product") or {}).get("attributes", {}).get(
            "usagetype", ""
        )
        price = _on_demand_usd(entry)
        if price is None:
            continue
        if usagetype.endswith(_VCPU_SUFFIX):
            vcpu = price
        elif usagetype.endswith(_EPHEMERAL_SUFFIX):
            ephemeral = price
        elif usagetype.endswith(_GB_SUFFIX):
            gib = price

    if vcpu > 0 and gib > 0:
        return FargatePrices(
            region=region,
            vcpu_usd_per_hour=vcpu,
            gib_usd_per_hour=gib,
            ephemeral_usd_per_gib_hour=ephemeral,
            source=source,
            source_timestamp=_utc_now_iso(),
            available=True,
        )
    return FargatePrices(
        region=region,
        source=source,
        source_timestamp=_utc_now_iso(),
        available=False,
        warning="AWS Pricing did not return a complete Fargate rate for this region.",
    )


def resolve_fargate_prices(
    region: str,
    *,
    fetch=None,
    use_cache: bool = True,
    now=None,
) -> FargatePrices:
    """Return region-specific Fargate rates, short-cached.

    On *any* failure (network, parse, incomplete data) returns
    ``FargatePrices(available=False)`` -- the caller shows "Cost estimate
    unavailable" and never blocks Launch.
    """
    region = (region or "").strip()
    if not region:
        return FargatePrices(region="", available=False, warning="No region.")

    clock = now or time.monotonic
    if use_cache and region in _CACHE:
        stamped_at, cached = _CACHE[region]
        if clock() - stamped_at < PRICE_CACHE_TTL_SECONDS:
            return cached

    fetcher = fetch or _default_fetch
    try:
        try:
            entries = fetcher(region)
        except (OSError, subprocess.TimeoutExpired):
            if fetch is not None:
                raise
            entries = _public_offer_fetch(region)
        prices = parse_fargate_prices(
            region, entries, source="AWS Price List (API or public regional offer)"
        )
    except Exception as err:  # noqa: BLE001 - pricing must never raise upward
        prices = FargatePrices(
            region=region,
            source="AWS Price List (API or public regional offer)",
            source_timestamp=_utc_now_iso(),
            available=False,
            warning=f"AWS Pricing lookup failed: {str(err)[:200]}",
        )

    if use_cache and prices.available:
        _CACHE[region] = (clock(), prices)
    return prices


def clear_price_cache() -> None:
    _CACHE.clear()
