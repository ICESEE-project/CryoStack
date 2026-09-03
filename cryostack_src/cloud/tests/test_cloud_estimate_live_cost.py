"""C7.5 -- live accumulated cost from the retained C7.4 estimate (no pricing)."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.estimate import (
    estimate_cloud_cost,
    format_usd,
    live_cost_usd,
)
from cryostack_src.cloud.estimate.models import FargatePrices

OHIO = FargatePrices(region="us-east-2", vcpu_usd_per_hour=0.04048,
                     gib_usd_per_hour=0.004445, available=True,
                     source="AWS Price List API (us-east-1)")


def test_live_cost_matches_estimate_for_elapsed_from_the_bound_model():
    e = estimate_cloud_cost(region="us-east-2", vcpu=2, memory_gib=8,
                            expected_runtime_minutes=60, prices=OHIO)
    pub = e.to_public_dict()
    for elapsed_s in (0, 60, 900, 1800, 3600, 7200):
        # the retained public dict rounds the total, so live cost tracks
        # estimate_for_elapsed to well under a cent (rel 1e-4 here).
        assert live_cost_usd(pub, elapsed_s) == pytest.approx(
            e.estimate_for_elapsed(elapsed_s), rel=1e-4, abs=1e-6
        )


def test_live_cost_is_linear_and_uncapped_past_the_estimate():
    e = estimate_cloud_cost(region="us-east-2", vcpu=2, memory_gib=8,
                            expected_runtime_minutes=5, prices=OHIO)
    pub = e.to_public_dict()
    at_5 = live_cost_usd(pub, 5 * 60)
    at_10 = live_cost_usd(pub, 10 * 60)
    assert at_5 == pytest.approx(pub["estimated_total_usd"], rel=1e-9)
    assert at_10 == pytest.approx(at_5 * 2, rel=1e-9)     # overran -> keeps climbing


def test_unavailable_estimate_gives_none_never_a_number():
    e = estimate_cloud_cost(region="us-east-2", vcpu=2, memory_gib=8,
                            expected_runtime_minutes=5,
                            prices=FargatePrices(region="us-east-2", available=False))
    assert live_cost_usd(e.to_public_dict(), 120) is None
    assert live_cost_usd({}, 120) is None
    assert live_cost_usd({"available": True, "estimated_total_usd": 1.0,
                          "expected_runtime_minutes": 0}, 60) is None


def test_live_cost_needs_no_pricing_object_only_the_public_dict():
    # a dict that could have been JSON-persisted and reloaded
    pub = {"available": True, "estimated_total_usd": 0.12,
           "expected_runtime_minutes": 5}
    assert live_cost_usd(pub, 150) == pytest.approx(0.12 * 2.5 / 5, rel=1e-9)
    assert format_usd(live_cost_usd(pub, 12)) == "<$0.01"
