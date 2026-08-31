"""The Basic-mode ISSM configuration panel: solver-aware, opt-in, validated."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from cryostack_src.frontend.cryolauncher.issm_md_panel import build_issm_md_panel


@pytest.fixture
def example(tmp_path):
    def _make(runme: str) -> str:
        d = tmp_path / "ex"
        d.mkdir(exist_ok=True)
        (d / "runme.m").write_text(runme)
        return str(d)
    return _make


def _row(panel, key):
    return panel._state["rows"][key]


def test_stressbalance_example_shows_only_relevant_curated_rows(example):
    p = build_issm_md_panel()
    p.set_example(example("md=solve(md,'Stressbalance');"))
    keys = set(p._state["rows"])
    assert "stressbalance.restol" in keys
    assert "friction.coefficient" in keys
    assert "timestepping.time_step" not in keys       # transient only
    assert "transient.isthermal" not in keys
    assert p.solvers() == ("stressbalance",)


def test_transient_example_shows_transient_rows(example):
    p = build_issm_md_panel()
    p.set_example(example("solve(md,'Stressbalance');\nsolve(md,'Transient');"))
    keys = set(p._state["rows"])
    assert {"timestepping.final_time", "transient.isthermal",
            "transient.requested_outputs"} <= keys


def test_no_solver_no_rows(example):
    p = build_issm_md_panel()
    p.set_example(example("md=triangle(md,'x.exp',5000);"))
    assert p._state["rows"] == {}
    assert p.overrides() == {}


def test_overrides_only_returns_enabled_rows(example):
    p = build_issm_md_panel()
    p.set_example(example("md=solve(md,'Stressbalance');"))
    enable, control, _ = _row(p, "stressbalance.maxiter")
    control.value = 250
    assert p.overrides() == {}          # not enabled yet
    enable.value = True
    assert p.overrides() == {"stressbalance.maxiter": 250}


def test_enabled_noop_multiplier_is_dropped(example):
    p = build_issm_md_panel()
    p.set_example(example("md=solve(md,'Stressbalance');"))
    enable, control, _ = _row(p, "friction.coefficient")
    enable.value = True
    control.value = 1.0
    assert p.overrides() == {}
    control.value = 1.5
    assert p.overrides() == {"friction.coefficient": 1.5}


def test_validate_passes_for_in_range_and_fails_out_of_range(example):
    p = build_issm_md_panel()
    p.set_example(example("md=solve(md,'Stressbalance');"))
    enable, control, _ = _row(p, "stressbalance.maxiter")
    enable.value = True
    control.value = 100
    assert p.validate().ok
    # BoundedIntText clamps, so force an invalid value past the widget
    control.max = 10**9
    control.value = 999999
    assert not p.validate().ok


def test_switching_example_drops_stale_overrides(example):
    p = build_issm_md_panel()
    p.set_example(example("md=solve(md,'Stressbalance');"))
    _row(p, "friction.coefficient")[0].value = True
    _row(p, "friction.coefficient")[1].value = 2.0
    assert p.overrides() == {"friction.coefficient": 2.0}
    p.set_example(example("md=triangle(md,'x.exp',5000);"))   # no solver
    assert p.overrides() == {}
