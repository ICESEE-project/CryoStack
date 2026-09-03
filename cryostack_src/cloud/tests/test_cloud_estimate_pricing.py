"""C7.4 -- AWS Fargate price resolution (offline, injected fetch)."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.estimate.pricing import (
    PRICE_CACHE_TTL_SECONDS,
    clear_price_cache,
    parse_fargate_prices,
    resolve_fargate_prices,
)


def _price_entry(usagetype: str, usd: str) -> dict:
    return {
        "product": {"attributes": {"usagetype": usagetype}},
        "terms": {
            "OnDemand": {
                "t1": {"priceDimensions": {"d1": {"pricePerUnit": {"USD": usd}}}}
            }
        },
    }


def _ohio_pricelist() -> list[dict]:
    return [
        _price_entry("USE2-Fargate-vCPU-Hours:perCPU", "0.04048"),
        _price_entry("USE2-Fargate-GB-Hours", "0.004445"),
        _price_entry("USE2-Fargate-EphemeralStorage-GB-Hours", "0.000111"),
    ]


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_price_cache()
    yield
    clear_price_cache()


def test_parses_a_real_shaped_price_response():
    prices = parse_fargate_prices("us-east-2", _ohio_pricelist(), source="test")
    assert prices.available
    assert prices.vcpu_usd_per_hour == 0.04048
    assert prices.gib_usd_per_hour == 0.004445
    assert prices.ephemeral_usd_per_gib_hour == 0.000111
    assert prices.region == "us-east-2"


def test_target_region_selection_is_by_regioncode_filter():
    seen = {}

    def fetch(region):
        seen["region"] = region
        return _ohio_pricelist()

    resolve_fargate_prices("eu-west-1", fetch=fetch, use_cache=False)
    assert seen["region"] == "eu-west-1"


def test_incomplete_price_is_treated_as_unavailable_not_fabricated():
    only_vcpu = [_price_entry("USE2-Fargate-vCPU-Hours:perCPU", "0.04")]
    prices = parse_fargate_prices("us-east-2", only_vcpu, source="test")
    assert not prices.available
    assert prices.vcpu_usd_per_hour in (0.0, 0.04)  # never a guessed GB rate
    assert prices.gib_usd_per_hour == 0.0


def test_pricing_api_failure_returns_unavailable_and_never_raises():
    def boom(region):
        raise RuntimeError("could not connect to the endpoint URL")

    prices = resolve_fargate_prices("us-east-2", fetch=boom, use_cache=False)
    assert not prices.available
    assert "failed" in prices.warning.lower()


def test_price_result_is_cached_within_the_ttl():
    calls = {"n": 0}

    def fetch(region):
        calls["n"] += 1
        return _ohio_pricelist()

    t = {"now": 1000.0}
    resolve_fargate_prices("us-east-2", fetch=fetch, now=lambda: t["now"])
    resolve_fargate_prices("us-east-2", fetch=fetch, now=lambda: t["now"] + 60)
    assert calls["n"] == 1                       # served from cache

    t["now"] += PRICE_CACHE_TTL_SECONDS + 1
    resolve_fargate_prices("us-east-2", fetch=fetch, now=lambda: t["now"])
    assert calls["n"] == 2                       # cache expired


def test_unavailable_prices_are_not_cached():
    calls = {"n": 0}

    def fetch(region):
        calls["n"] += 1
        raise RuntimeError("nope")

    resolve_fargate_prices("us-east-2", fetch=fetch, now=lambda: 0.0)
    resolve_fargate_prices("us-east-2", fetch=fetch, now=lambda: 1.0)
    assert calls["n"] == 2
