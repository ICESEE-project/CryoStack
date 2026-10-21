"""CryoLauncher Cloud Review & Launch: with a connected AWS account the review
is built in the connection's own region, so Launch's drift check must use
that region too -- otherwise a Region field that differs from the connection
(e.g. restored from saved settings) makes every Launch report "The run
configuration changed since you opened this review".

No AWS is contacted: the credential resolver, the onboarding summary and the
price lookup are local fakes.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

ACCOUNT = "123456789012"


@pytest.fixture
def review_callbacks(monkeypatch, tmp_path):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "digest-user")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("MPLBACKEND", "Agg")
    import cryostack_src.cloud.connect as connect
    import cryostack_src.cloud.estimate as estimate
    from cryostack_src.cloud.estimate.models import FargatePrices
    from cryostack_src.frontend.cryolauncher import cloud_review_runtime as crr

    def build(connection_region):
        defaults = SimpleNamespace(bucket=f"cryostack-{ACCOUNT}-{connection_region}",
                                   job_queue="cryostack-queue", job_definition="cryostack-issm")
        monkeypatch.setattr(connect, "resolve_cloud_execution", lambda **kw: SimpleNamespace(
            is_byo=True, region=connection_region, account_id=ACCOUNT, credentials={"k": "v"},
            defaults=defaults, profile=None,
            matlab_license=SimpleNamespace(configured=False, requires_tunnel=False)))

        class Onboarding:
            def __init__(self, **kw):
                pass

            def summary(self):
                return {"status": "connected", "account_id": ACCOUNT, "region": connection_region}

            def __getattr__(self, name):
                return lambda *a, **k: {"status": "connected"}

        monkeypatch.setattr(connect, "AWSOnboarding", Onboarding)
        monkeypatch.setattr(estimate, "resolve_fargate_prices",
                            lambda region, **k: FargatePrices(region=region))
        captured = {}
        original = crr.build_cloud_review_callbacks

        def capture(**kwargs):
            captured.update(kwargs)
            return original(**kwargs)

        monkeypatch.setattr(crr, "build_cloud_review_callbacks", capture)
        from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
        build_icesheets_ui()
        return captured

    return build


@pytest.mark.parametrize("connection_region", ["us-east-2", "us-east-1"])
def test_launch_digest_matches_the_review(review_callbacks, connection_region):
    c = review_callbacks(connection_region)
    c["widgets"].region.value = "us-east-2"         # the Region field, which may differ
    review = c["review_builder"]()
    assert review.region == connection_region
    assert c["digest_builder"]() == review.digest


def test_a_real_change_still_invalidates_the_review(review_callbacks):
    c = review_callbacks("us-east-1")
    review = c["review_builder"]()
    c["widgets"].compute_mode.value = "ec2"
    assert c["digest_builder"]() != review.digest
