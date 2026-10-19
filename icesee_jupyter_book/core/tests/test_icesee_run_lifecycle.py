"""Run lifecycle: state vocabulary, legal transitions, manifest history."""
from __future__ import annotations

import pytest

from icesee_jupyter_book.core import run_lifecycle as lc
from icesee_jupyter_book.core import run_records

PARAMS = {"enkf-parameters": {"Nens": 4, "filter_type": "EnKF", "model_name": "lorenz"}}


def _record(tmp_path, status="preparing"):
    run_records.record_run(run_dir=tmp_path / "r1", run_id="r1", name="t", params=PARAMS, example="Lorenz",
                           execution_mode="local", backend="local-native", status=status)
    return tmp_path / "r1"


@pytest.mark.parametrize("raw, state", [
    ("PD", "queued"), ("PENDING", "queued"), ("RUNNABLE", "queued"), ("STARTING", "running"),
    ("R", "running"), ("CD", "completed"), ("SUCCEEDED", "completed"), ("done", "completed"),
    ("FAILED", "failed"), ("TIMEOUT", "failed"), ("OUT_OF_MEMORY", "failed"), ("fail", "failed"),
    ("CANCELLED by 1234", "cancelled"), ("CANCELLED+", "cancelled"), ("terminated", "cancelled"),
    ("SUBMITTED", "submitted"), ("preparing", "preparing"),
])
def test_backend_words_map_to_states(raw, state):
    assert lc.normalize(raw) == state


@pytest.mark.parametrize("raw", [None, "", "wibble", "42"])
def test_unknown_words_are_not_guessed(raw):
    assert lc.normalize(raw) is None


def test_local_path_preparing_running_completed(tmp_path):
    rd = _record(tmp_path)
    lc.transition(rd, lc.RUNNING, detail="pid 1")
    info = lc.transition(rd, lc.COMPLETED, extra_metadata={"exit_code": 0})
    assert info.status == "completed" and info.finished is not None
    assert [e["state"] for e in info.metadata["lifecycle"]] == ["running", "completed"]
    assert info.metadata["exit_code"] == 0


def test_hpc_path_and_repeated_polls(tmp_path):
    rd = _record(tmp_path)
    for word in ("SUBMITTED", "PD", "PD", "R", "R", "CD"):
        lc.apply_backend_status(rd, word)
    info = run_records.load_run(tmp_path, "r1")
    assert [e["state"] for e in info.metadata["lifecycle"]] == ["submitted", "queued", "running", "completed"]


def test_final_states_are_final(tmp_path):
    rd = _record(tmp_path)
    lc.transition(rd, lc.FAILED, detail="boom")
    with pytest.raises(lc.InvalidTransition):
        lc.transition(rd, lc.RUNNING)
    assert lc.apply_backend_status(rd, "R") is None      # a stale poll is ignored
    info = run_records.load_run(tmp_path, "r1")
    assert info.status == "failed" and info.metadata["final_detail"] == "boom"


def test_cancelled_records_finish_time(tmp_path):
    rd = _record(tmp_path)
    lc.transition(rd, lc.RUNNING)
    info = lc.transition(rd, lc.CANCELLED, detail="by the user")
    assert info.finished is not None


def test_legacy_status_is_understood(tmp_path):
    rd = _record(tmp_path, status="running")
    info = run_records.load_run(tmp_path, "r1")
    assert lc.current_state(info) == "running"
    lc.transition(rd, lc.COMPLETED)


def test_unknown_state_rejected_and_missing_manifest(tmp_path):
    rd = _record(tmp_path)
    with pytest.raises(lc.InvalidTransition):
        lc.transition(rd, "exploded")
    assert lc.transition(tmp_path / "nope", lc.RUNNING) is None
