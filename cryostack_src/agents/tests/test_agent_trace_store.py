"""Agent trace persistence + the provenance boundary (A7)."""
from __future__ import annotations

import pytest

from cryostack_src.agents import (
    AGENT_PROVENANCE_KEY,
    Trace,
    TraceStore,
    assert_no_agent_chatter,
    run_manifest_stamp,
)
from cryostack_src.workspace import WorkspaceUser

_USER = WorkspaceUser(user_id="trace-u", source="cryostack-auth")


@pytest.fixture
def store(tmp_path):
    return TraceStore.for_user(_USER, workspace_root=tmp_path)


def test_trace_dir_is_separate_from_runs(store, tmp_path):
    assert "agent-traces" in str(store._dir)
    assert "runs" not in store._dir.name


def test_attach_flushes_each_event_append_only(store):
    tr = Trace(user_id=_USER.user_id)
    tr.request("run the synthetic ice shelf")
    path = store.attach(tr)
    tr.append("tool_call", {"tool": "prepare_run_plan"})
    tr.append("approval", {"plan_digest": "abc", "approver": _USER.user_id})

    lines = path.read_text().strip().splitlines()
    assert len(lines) == 3
    store.verify_append_only(tr.trace_id)
    loaded = store.load(tr.trace_id)
    assert [e["kind"] for e in loaded] == ["request", "tool_call", "approval"]
    assert [e["seq"] for e in loaded] == [0, 1, 2]


def test_secrets_never_hit_disk(store):
    tr = Trace(user_id=_USER.user_id)
    store.attach(tr)
    tr.append("tool_call", {"password": "hunter2", "session_secret": "s3cr",
                            "note": "-----BEGIN OPENSSH PRIVATE KEY-----"})
    raw = store.path_for(tr.trace_id).read_text()
    assert "hunter2" not in raw
    assert "s3cr" not in raw
    assert "BEGIN OPENSSH PRIVATE KEY" not in raw
    assert "***" in raw


def test_persist_is_append_not_truncate(store):
    tr = Trace(user_id=_USER.user_id)
    tr.append("request", {"text": "a"})
    store.persist(tr)
    tr.append("note", {"text": "b"})
    store.persist(tr)
    # second persist appended the whole trace again -> at least 3 lines, never 0
    lines = store.path_for(tr.trace_id).read_text().strip().splitlines()
    assert len(lines) >= 3


# ── provenance boundary ─────────────────────────────────────────────
def test_run_manifest_stamp_is_a_pointer_only():
    stamp = run_manifest_stamp(trace_id="t1", plan_digest="d1",
                               approver_user_id="trace-u",
                               approved_at="2026-09-01T00:00:00Z")
    body = stamp[AGENT_PROVENANCE_KEY]
    assert body["agent_assisted"] is True
    assert body["agent_trace_ref"] == "t1"
    assert set(body) == {"agent_assisted", "plan_digest", "approved_by",
                         "approved_at", "agent_trace_ref", "note"}
    assert_no_agent_chatter({**stamp, "model": "issm", "run_target": "runme.m"})


def test_assert_no_agent_chatter_rejects_smuggled_trace_content():
    bad = {
        "model": "issm",
        "provenance": {"tool_calls": [{"tool": "prepare_run_plan"}]},
    }
    with pytest.raises(AssertionError):
        assert_no_agent_chatter(bad)

    bad2 = {"prompt": "please run it"}
    with pytest.raises(AssertionError):
        assert_no_agent_chatter(bad2)


def test_assert_no_agent_chatter_rejects_extra_stamp_keys():
    with pytest.raises(AssertionError):
        assert_no_agent_chatter({AGENT_PROVENANCE_KEY: {
            "agent_assisted": True, "messages": ["hi"]}})
