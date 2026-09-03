"""C7.4 -- expected-runtime estimation hierarchy."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.estimate.runtime import estimate_runtime


def test_previous_successful_runs_win_when_enough_history():
    rt = estimate_runtime(
        model="issm", example="SquareIceShelf", time_limit_minutes=60,
        history_provider=lambda: [4.5, 5.5, 6.0, 5.0],
    )
    assert rt.basis == "history"
    assert rt.minutes == pytest.approx(5.25, abs=0.1)
    assert rt.sample_size == 4
    assert "previous successful CryoStack runs" in rt.source


def test_thin_history_falls_through_to_the_known_example_table():
    rt = estimate_runtime(
        model="issm", example="SquareIceShelf", time_limit_minutes=60,
        history_provider=lambda: [5.0],          # < 3 samples
    )
    assert rt.basis == "example_table"
    assert rt.minutes == 5.0
    assert "SquareIceShelf reference estimate" in rt.source


def test_unknown_example_falls_back_to_the_configured_time_limit():
    rt = estimate_runtime(model="issm", example="MyCustomThing", time_limit_minutes=60)
    assert rt.basis == "time_limit"
    assert rt.minutes == 60.0
    assert "configured time limit" in rt.source


def test_history_provider_errors_are_swallowed():
    def boom():
        raise RuntimeError("workspace unavailable")

    rt = estimate_runtime(
        model="issm", example="SquareIceShelf", time_limit_minutes=60,
        history_provider=boom,
    )
    assert rt.basis == "example_table"


def test_case_insensitive_example_match():
    rt = estimate_runtime(model="ISSM", example="squareiceshelf", time_limit_minutes=99)
    assert rt.basis == "example_table" and rt.minutes == 5.0
