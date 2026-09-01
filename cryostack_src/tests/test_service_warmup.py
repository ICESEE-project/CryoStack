"""Performance commit 2 -- non-blocking application warm-up state machine.

All timing is mocked: `_wait_for_port` is replaced, nothing sleeps for seconds.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src import service_warmup as sw
from cryostack_src.service_warmup import ManagedVoilaService, ServiceState, warm_up_all


class _FakeProcess:
    def __init__(self):
        self.starts = 0
        self.stops = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def port_up(monkeypatch):
    async def ok(host, port, timeout):
        await asyncio.sleep(0)  # yield once, never seconds
        return True

    monkeypatch.setattr(sw, "_wait_for_port", ok)


@pytest.fixture
def port_down(monkeypatch):
    async def bad(host, port, timeout):
        await asyncio.sleep(0)
        return False

    monkeypatch.setattr(sw, "_wait_for_port", bad)


def test_starts_stopped_and_reaches_ready(port_up):
    proc = _FakeProcess()
    svc = ManagedVoilaService(name="x", process=proc, port=9999, port_timeout=1)
    assert svc.state is ServiceState.STOPPED
    assert _run(svc.warm_up()) is ServiceState.READY
    assert proc.starts == 1


def test_concurrent_starts_launch_exactly_one_process(port_up):
    proc = _FakeProcess()
    svc = ManagedVoilaService(name="x", process=proc, port=9999, port_timeout=1)

    async def hammer():
        # ensure_started (non-blocking) x5 + warm_up x2, all racing
        for _ in range(5):
            svc.ensure_started()
        await asyncio.gather(svc.warm_up(), svc.warm_up())
        # drain any tasks ensure_started scheduled
        await asyncio.sleep(0)
        await asyncio.gather(*[t for t in asyncio.all_tasks() if t is not asyncio.current_task()])

    _run(hammer())
    assert svc.state is ServiceState.READY
    assert proc.starts == 1


def test_ready_service_is_reused_not_restarted(port_up):
    proc = _FakeProcess()
    svc = ManagedVoilaService(name="x", process=proc, port=9999, port_timeout=1)
    _run(svc.warm_up())
    for _ in range(10):
        assert svc.ensure_started() is ServiceState.READY
    _run(svc.warm_up())
    assert proc.starts == 1


def test_failed_startup_is_controlled_and_reports_diagnostics(port_down):
    proc = _FakeProcess()
    svc = ManagedVoilaService(name="x", process=proc, port=9999, port_timeout=1)
    assert _run(svc.warm_up()) is ServiceState.FAILED
    assert "did not bind" in svc.error
    # a failed service is NOT auto-retried by ensure_started
    assert svc.ensure_started() is ServiceState.FAILED
    assert proc.starts == 1


def test_retry_after_failure(monkeypatch):
    proc = _FakeProcess()
    svc = ManagedVoilaService(name="x", process=proc, port=9999, port_timeout=1)
    outcomes = iter([False, True])

    async def flaky(host, port, timeout):
        await asyncio.sleep(0)
        return next(outcomes)

    monkeypatch.setattr(sw, "_wait_for_port", flaky)

    assert _run(svc.warm_up()) is ServiceState.FAILED
    svc.request_retry()
    assert svc.state is ServiceState.STOPPED
    assert _run(svc.warm_up()) is ServiceState.READY
    assert proc.starts == 2


def test_warm_up_all_starts_every_service(port_up):
    a = ManagedVoilaService(name="a", process=_FakeProcess(), port=1, port_timeout=1)
    b = ManagedVoilaService(name="b", process=_FakeProcess(), port=2, port_timeout=1)
    _run(warm_up_all([a, b]))
    assert a.state is ServiceState.READY and b.state is ServiceState.READY


def test_warm_up_task_is_cancellable(monkeypatch):
    proc = _FakeProcess()
    svc = ManagedVoilaService(name="x", process=proc, port=9999, port_timeout=5)

    async def slow(host, port, timeout):
        await asyncio.sleep(10)
        return True

    monkeypatch.setattr(sw, "_wait_for_port", slow)

    async def scenario():
        task = asyncio.create_task(warm_up_all([svc]))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    _run(scenario())
    assert proc.starts == 1  # process was launched, then warm-up cancelled


def test_stop_resets_state(port_up):
    proc = _FakeProcess()
    svc = ManagedVoilaService(name="x", process=proc, port=9999, port_timeout=1)
    _run(svc.warm_up())
    svc.stop()
    assert svc.state is ServiceState.STOPPED
    assert proc.stops == 1
