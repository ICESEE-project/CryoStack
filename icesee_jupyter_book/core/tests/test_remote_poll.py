"""Automatic status checks for the selected Remote ICESEE run (remote_poll.py)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.core.remote_poll import RemoteStatusPoller

RUNNING = {"source": "squeue", "state": "RUNNING", "returncode": 0, "stdout": "1|RUNNING", "stderr": ""}


def _run(mode="remote", status="running", jobid="4242"):
    return SimpleNamespace(execution_mode=mode, status=status, jobid=jobid, metadata={"lifecycle": [
        {"state": status, "at": "2026-10-20T09:00:00", "detail": ""}]})


def _poller(run, results):
    seen = {"checks": [], "applied": [], "notes": []}

    def check(jobid):
        seen["checks"].append(jobid)
        r = results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    poller = RemoteStatusPoller(selected=lambda: run["value"], check=check,
                                apply=lambda r, u: seen["applied"].append(u["status"]),
                                notify=lambda text, kind: seen["notes"].append((kind, text)))
    return poller, seen


def test_only_an_active_remote_run_with_a_job_is_checked():
    for run in (None, _run(mode="local"), _run(jobid=None), _run(status="completed")):
        poller, seen = _poller({"value": run}, [])
        assert poller.tick() == "skipped" and not seen["checks"]


def test_a_scheduler_state_is_applied():
    poller, seen = _poller({"value": _run()}, [dict(RUNNING)])
    assert poller.tick() == "updated"
    assert seen["checks"] == ["4242"] and seen["applied"] == ["running"]


def test_repeated_failures_pause_until_resumed():
    poller, seen = _poller({"value": _run()}, [TimeoutError("ssh"), {"returncode": 255, "stderr": "denied"},
                                               OSError(), dict(RUNNING)])
    assert [poller.tick() for _ in range(3)] == ["failed"] * 3
    assert poller.paused and seen["notes"] and seen["notes"][0][0] == "warn"
    assert "3 failed attempts" in seen["notes"][0][1]
    assert poller.tick() == "paused" and len(seen["checks"]) == 3
    poller.resume()
    assert poller.tick() == "updated"


def test_a_success_resets_the_failure_count():
    poller, _ = _poller({"value": _run()}, [OSError(), OSError(), dict(RUNNING), OSError(), OSError()])
    for _ in range(5):
        poller.tick()
    assert not poller.paused and poller.failures == 2


def test_selecting_another_run_starts_a_fresh_budget():
    state = {"value": _run(jobid="1")}
    poller, _ = _poller(state, [OSError()] * 3 + [dict(RUNNING)])
    for _ in range(3):
        poller.tick()
    assert poller.paused
    state["value"] = _run(jobid="2")
    assert poller.tick() == "updated" and not poller.paused
