"""C7.4 -- CloudCostEstimate: Fargate compute + memory + ephemeral storage."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.estimate.estimator import estimate_cloud_cost
from cryostack_src.cloud.estimate.models import FargatePrices, _format_usd

OHIO = FargatePrices(
    region="us-east-2",
    vcpu_usd_per_hour=0.04048,
    gib_usd_per_hour=0.004445,
    ephemeral_usd_per_gib_hour=0.000111,
    source="AWS Price List API (us-east-1)",
    source_timestamp="2026-09-03T00:00:00+00:00",
    available=True,
)


def test_compute_and_memory_scale_with_runtime():
    e5 = estimate_cloud_cost(region="us-east-2", vcpu=2, memory_gib=8,
                             expected_runtime_minutes=5, prices=OHIO)
    e60 = estimate_cloud_cost(region="us-east-2", vcpu=2, memory_gib=8,
                              expected_runtime_minutes=60, prices=OHIO)
    assert e60.estimated_total_usd == pytest.approx(e5.estimated_total_usd * 12, rel=1e-6)
    # 2 vCPU * 0.04048 * 1h + 8 GiB * 0.004445 * 1h
    assert e60.estimated_total_usd == pytest.approx(2 * 0.04048 + 8 * 0.004445, rel=1e-6)
    assert e60.available


def test_ephemeral_storage_only_billed_beyond_the_20_gib_included():
    included = estimate_cloud_cost(region="us-east-2", vcpu=2, memory_gib=8,
                                   expected_runtime_minutes=60, ephemeral_gib=20,
                                   prices=OHIO)
    over = estimate_cloud_cost(region="us-east-2", vcpu=2, memory_gib=8,
                               expected_runtime_minutes=60, ephemeral_gib=50,
                               prices=OHIO)
    assert included.storage_usd == 0.0
    assert over.storage_usd == pytest.approx(30 * 0.000111, rel=1e-6)
    assert over.billable_ephemeral_gib == 30


def test_unavailable_prices_produce_an_unavailable_estimate_not_a_fake_number():
    e = estimate_cloud_cost(region="us-east-2", vcpu=2, memory_gib=8,
                            expected_runtime_minutes=5,
                            prices=FargatePrices(region="us-east-2", available=False,
                                                 warning="Pricing lookup failed"))
    assert not e.available
    assert e.estimated_total_usd == 0.0
    assert e.display_total() == "unavailable"
    assert "unavailable" in e.warning.lower() or "failed" in e.warning.lower()


def test_none_prices_also_yield_unavailable():
    e = estimate_cloud_cost(region="us-east-2", vcpu=2, memory_gib=8,
                            expected_runtime_minutes=5, prices=None)
    assert not e.available


def test_estimate_for_elapsed_reuses_the_same_pricing_formula():
    e = estimate_cloud_cost(region="us-east-2", vcpu=2, memory_gib=8,
                            expected_runtime_minutes=60, prices=OHIO)
    # 30 minutes elapsed == half the 60-minute estimate
    assert e.estimate_for_elapsed(30 * 60) == pytest.approx(
        e.estimated_total_usd / 2, rel=1e-6
    )
    assert e.estimate_for_elapsed(0) == 0.0


@pytest.mark.parametrize(
    "value,shown",
    [(0.0, "<$0.01"), (0.004, "<$0.01"), (0.04, "$0.04"), (1.2, "$1.20"),
     (12.7, "$12.7"), (250.0, "$250")],
)
def test_usd_formatting_avoids_fake_precision(value, shown):
    assert _format_usd(value) == shown


def test_public_dict_is_rounded_and_carries_no_secret():
    e = estimate_cloud_cost(region="us-east-2", vcpu=2, memory_gib=8,
                            expected_runtime_minutes=5, prices=OHIO)
    pub = e.to_public_dict()
    assert isinstance(pub["estimated_total_usd"], float)
    # the DATA keeps enough precision for a sub-cent live-cost tick; the
    # DISPLAY (format_usd / display_total) is what rounds to cents.
    assert len(str(pub["estimated_total_usd"]).split(".")[-1]) <= 6
    assert e.display_total() in ("<$0.01", "$0.01")
    assert "AWS_SECRET_ACCESS_KEY" not in str(pub)
