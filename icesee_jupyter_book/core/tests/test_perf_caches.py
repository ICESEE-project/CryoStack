"""Performance pass: connector-status TTL cache and canonical-example scan cache."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import icesee_jupyter_book.core.connector_relay_client as rc
from icesee_jupyter_book.core.icesheet_examples import (
    discover_examples_for_model,
    invalidate_example_cache,
)


# ── connector status TTL cache ─────────────────────────────────────────
class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


@pytest.fixture
def fake_relay(monkeypatch):
    calls = {"n": 0, "payload": {"session_id": "s1", "online": True, "state": "connected"}}

    def fake_get(url, timeout=15):
        calls["n"] += 1
        return _FakeResp(dict(calls["payload"]))

    monkeypatch.setattr(rc.requests, "get", fake_get)
    rc.invalidate_status_cache()
    return calls


def test_repeated_status_lookups_hit_the_cache(fake_relay):
    for _ in range(10):
        rc.check_status("s1")
    assert fake_relay["n"] == 1


def test_force_refresh_always_calls_the_relay(fake_relay):
    rc.check_status("s1")
    for _ in range(5):
        rc.check_status("s1", force=True)
    assert fake_relay["n"] == 6


def test_cache_is_per_session(fake_relay):
    rc.check_status("s1")
    rc.check_status("s2")
    assert fake_relay["n"] == 2
    rc.check_status("s1")
    rc.check_status("s2")
    assert fake_relay["n"] == 2


def test_cache_expires(fake_relay, monkeypatch):
    monkeypatch.setattr(rc, "STATUS_CACHE_TTL_SECONDS", 0.05)
    rc.check_status("s1")
    time.sleep(0.08)
    rc.check_status("s1")
    assert fake_relay["n"] == 2


def test_dead_session_state_is_never_cached(fake_relay):
    fake_relay["payload"] = {"session_id": "s1", "online": False, "state": "superseded"}
    rc.check_status("s1")
    rc.check_status("s1")
    assert fake_relay["n"] == 2  # re-checked, not served stale


def test_cache_holds_no_secret_fields(fake_relay):
    fake_relay["payload"] = {
        "session_id": "s1", "online": True, "state": "connected",
        "control_secret": "SECRET", "session_secret": "SECRET2", "pairing_code": "123456",
    }
    rc.check_status("s1")
    cached = rc._STATUS_CACHE["s1"][1]
    for k in cached:
        assert "secret" not in k and "pairing" not in k
    assert set(cached) == {"session_id", "online", "state"}


def test_creating_a_session_invalidates_its_cached_status(fake_relay, monkeypatch):
    rc.check_status("new-sess")
    monkeypatch.setattr(
        rc.requests, "post",
        lambda *a, **k: _FakeResp({"session_id": "new-sess", "control_secret": "x", "ws_url": "/w"}),
    )
    # raise_for_status is a no-op on our fake
    monkeypatch.setattr(_FakeResp, "raise_for_status", lambda self: None, raising=False)
    rc.create_session("owner-1")
    fake_relay["n"] = 0
    rc.check_status("new-sess")
    assert fake_relay["n"] == 1


# ── canonical example scan cache ──────────────────────────────────────
def test_canonical_scan_is_cached(monkeypatch):
    import icesee_jupyter_book.core.icesheet_examples as ex
    invalidate_example_cache()
    calls = {"n": 0}
    real = ex.discover_issm_examples

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(ex, "discover_issm_examples", counting)
    for _ in range(20):
        discover_examples_for_model("issm")
    assert calls["n"] == 1


def test_use_cache_false_bypasses(monkeypatch):
    import icesee_jupyter_book.core.icesheet_examples as ex
    invalidate_example_cache()
    calls = {"n": 0}
    real = ex.discover_issm_examples
    monkeypatch.setattr(
        ex, "discover_issm_examples",
        lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), real(*a, **k))[1],
    )
    discover_examples_for_model("issm", use_cache=False)
    discover_examples_for_model("issm", use_cache=False)
    assert calls["n"] == 2


def test_explicit_invalidation_forces_a_rescan(monkeypatch):
    import icesee_jupyter_book.core.icesheet_examples as ex
    invalidate_example_cache()
    calls = {"n": 0}
    real = ex.discover_issm_examples
    monkeypatch.setattr(
        ex, "discover_issm_examples",
        lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), real(*a, **k))[1],
    )
    discover_examples_for_model("issm")
    invalidate_example_cache("issm")
    discover_examples_for_model("issm")
    assert calls["n"] == 2


def test_cache_is_per_model():
    invalidate_example_cache()
    issm = discover_examples_for_model("issm")
    icepack = discover_examples_for_model("icepack")
    # different models never share a cache entry
    assert {e.model_name for e in issm} <= {"issm"}
    assert {e.model_name for e in icepack} <= {"icepack"}


def test_returned_list_is_a_copy():
    invalidate_example_cache()
    a = discover_examples_for_model("issm")
    a.append("mutation")
    b = discover_examples_for_model("issm")
    assert "mutation" not in b
