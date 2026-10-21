"""ICESEE Cloud card after Test connection / Prepare cloud: the RUN ESTIMATE
(runtime, resources, cost) and Review & Launch appear once every
infrastructure row is Ready, rows that need action read amber rather than
failed, and a failed re-check never leaves rows on "Preparing…".

No real AWS is contacted: the environment operations, the price lookup and
the estimate thread are replaced by local fakes.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import ipywidgets as W
import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.estimate.models import FargatePrices
from icesee_jupyter_book.core.cloud_review import completed_cloud_minutes, icesee_run_estimate

PRICES = FargatePrices(region="us-east-1", vcpu_usd_per_hour=0.04, gib_usd_per_hour=0.004,
                       available=True, source="test")
READY = SimpleNamespace(authenticated=True, storage_ready=True, registry_ready=True, batch_ready=True,
                        messages=[])
NOT_PREPARED = SimpleNamespace(authenticated=True, storage_ready=False, registry_ready=False,
                               batch_ready=False, messages=[])


def _run(example, mode="cloud", started="2026-10-20T10:00:00", finished="2026-10-20T10:06:00"):
    events = [{"state": "submitted", "at": "2026-10-20T09:59:00"}, {"state": "running", "at": started}]
    if finished:
        events.append({"state": "completed", "at": finished})
    return SimpleNamespace(execution_mode=mode, metadata={"example": example, "lifecycle": events})


# ── estimate helpers ───────────────────────────────────────────────────────
def test_durations_come_from_completed_cloud_runs_of_the_example():
    runs = [_run("Lorenz-96"), _run("Lorenz-96", finished=None), _run("Lorenz-96", mode="local"),
            _run("Icepack"), _run("Lorenz-96", started="2026-10-20T11:00:00", finished="2026-10-20T11:04:00")]
    assert completed_cloud_minutes(runs, example="Lorenz-96") == [6.0, 4.0]


def test_estimate_with_history_gives_a_total():
    e = icesee_run_estimate(region="us-east-1", compute_mode="fargate", durations_minutes=[6.0, 4.0],
                            prices=PRICES)
    assert e["runtime_text"].startswith("~5 min") and "2 earlier cloud runs" in e["runtime_text"]
    assert e["resource_text"] == "2 vCPU · 8 GiB · AWS Batch Fargate"
    assert "$" in e["cost_text"] and "per hour" not in e["cost_text"] and not e["unavailable"]


def test_estimate_without_history_is_per_hour_not_a_guess():
    e = icesee_run_estimate(region="us-east-1", compute_mode="fargate", durations_minutes=[], prices=PRICES)
    assert "Not known yet" in e["runtime_text"] and e["cost_text"].endswith("per hour")


def test_ec2_and_missing_prices_are_unavailable():
    assert icesee_run_estimate(region="us-east-1", compute_mode="ec2", durations_minutes=[5],
                               prices=None)["unavailable"]
    assert icesee_run_estimate(region="us-east-1", compute_mode="fargate", durations_minutes=[5],
                               prices=FargatePrices(region="us-east-1"))["unavailable"]


# ── the Cloud card in the ICESEE gateway ───────────────────────────────────
@pytest.fixture
def card(monkeypatch, tmp_path):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "estimate-user")
    monkeypatch.setenv("CRYOSTACK_CLOUD_OPERATOR_USER_IDS", "estimate-user")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("MPLBACKEND", "Agg")
    from cryostack_src.cloud.estimate import pricing
    from icesee_jupyter_book.ui import icesee_gateway as gw

    captured = {}
    original_card = gw.build_cloud_environment_card

    def capture_card(**kwargs):
        captured["env"] = original_card(**kwargs)
        return captured["env"]

    def fake_ops(**kwargs):
        def run(worker, on_success):
            captured["last"] = (worker, on_success)
        return SimpleNamespace(test_connection=run, prepare_cloud=run, smoke_test=run, is_busy=lambda: False)

    class _Now:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(gw, "build_cloud_environment_card", capture_card)
    monkeypatch.setattr(gw, "build_cloud_environment_ops", fake_ops)
    monkeypatch.setattr(gw, "threading", SimpleNamespace(Thread=_Now))
    monkeypatch.setattr(pricing, "resolve_fargate_prices", lambda region, **_: PRICES)
    captured["page"] = gw.build_icesee_ui()
    captured["gw"] = gw
    return captured


def _shown(widget):
    return widget.layout.display != "none"


def test_estimate_and_review_appear_once_everything_is_ready(card):
    env = card["env"]
    assert not _shown(env.run_estimate_section)          # nothing to estimate before Prepare
    env.test_button.click()
    _worker, on_success = card["last"]
    on_success(READY)
    assert _shown(env.run_estimate_section) and _shown(env.review_button)
    line = env.run_estimate_line.value
    assert "Expected runtime" in line and "2 vCPU · 8 GiB" in line and "per hour" in line
    assert "cryostack-status-success" in env.compute_status.value


def test_rows_that_need_action_are_amber_and_hide_the_estimate(card):
    env = card["env"]
    env.test_button.click()
    card["last"][1](READY)
    env.test_button.click()
    card["last"][1](NOT_PREPARED)
    assert not _shown(env.run_estimate_section)
    assert "cryostack-status-warning" in env.storage_status.value and "Not prepared" in env.storage_status.value
    assert "cryostack-status-error" not in env.storage_status.value


def test_a_failed_recheck_after_prepare_never_stays_on_preparing(card, monkeypatch):
    env = card["env"]
    monkeypatch.setattr(card["gw"], "build_icesee_cloud_bridge",
                        lambda _cfg: (_ for _ in ()).throw(RuntimeError("no access")))
    env.prepare_button.click()
    card["last"][1]({"messages": ["prepared"]})
    for row in (env.account_status, env.storage_status, env.registry_status, env.compute_status):
        assert "Not verified" in row.value and "cryostack-status-warning" in row.value
    assert not _shown(env.run_estimate_section)


def test_status_styles_colour_every_state():
    from icesee_jupyter_book.ui import shared_app_styles as styles
    css = " ".join(str(v) for v in vars(styles).values() if isinstance(v, str))
    for name in ("success", "warning", "error", "running"):
        assert f".cryostack-status-{name}" in css
    assert "cryostack-status-spin" in css and "prefers-reduced-motion" in css
