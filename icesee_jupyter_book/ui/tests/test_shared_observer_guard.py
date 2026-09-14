"""Performance pass: the shared observer-suppression / coalesced-refresh guard."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.ui.shared_observer_guard import UIRefreshCoordinator


def test_batch_coalesces_guarded_observers_into_one_settle():
    settles = {"n": 0}
    coord = UIRefreshCoordinator(on_settle=lambda: settles.__setitem__("n", settles["n"] + 1))
    obs = coord.guard(lambda change=None: settles.__setitem__("n", settles["n"] + 100))

    with coord.batch():
        for _ in range(10):
            obs()          # would each fire outside a batch
    assert settles["n"] == 1   # exactly one settle, at the end


def test_guarded_observer_runs_normally_outside_a_batch():
    calls = {"n": 0}
    coord = UIRefreshCoordinator()
    obs = coord.guard(lambda change=None: calls.__setitem__("n", calls["n"] + 1))
    obs()
    obs()
    assert calls["n"] == 2


def test_no_settle_when_nothing_requested_a_refresh():
    settles = {"n": 0}
    coord = UIRefreshCoordinator(on_settle=lambda: settles.__setitem__("n", settles["n"] + 1))
    with coord.batch():
        pass
    assert settles["n"] == 0


def test_batches_are_reentrant():
    settles = {"n": 0}
    coord = UIRefreshCoordinator(on_settle=lambda: settles.__setitem__("n", settles["n"] + 1))
    with coord.batch():
        assert coord.suppressed
        with coord.batch():
            assert coord.suppressed
            coord.request_refresh()
        assert coord.suppressed        # still inside the outer batch
        assert settles["n"] == 0
    assert not coord.suppressed
    assert settles["n"] == 1           # one settle when the outer batch closes


def test_run_guarded_skips_imperative_work_during_a_batch():
    ran = {"n": 0}
    coord = UIRefreshCoordinator()

    def side_effect():
        ran["n"] += 1

    with coord.batch():
        coord.run_guarded(side_effect)
    assert ran["n"] == 0
    coord.run_guarded(side_effect)
    assert ran["n"] == 1


def test_request_refresh_is_immediate_outside_a_batch():
    settles = {"n": 0}
    coord = UIRefreshCoordinator(on_settle=lambda: settles.__setitem__("n", settles["n"] + 1))
    coord.request_refresh()
    assert settles["n"] == 1
