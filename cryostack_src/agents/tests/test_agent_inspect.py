"""Agent replay/debug inspector (PASS 4, task 6): renders a saved session,
never replays a side effect."""
from __future__ import annotations

import json

import pytest

from cryostack_src.agents import AgentStore, RunPlan, SlurmRequest, Trace
from cryostack_src.agents.inspect import inspect, main, render_managed_plan, render_trace
from cryostack_src.workspace import WorkspaceUser

_USER = WorkspaceUser(user_id="insp-u", source="cryostack-auth")


def _plan() -> RunPlan:
    return RunPlan(application="icesheets", model="issm", example="X",
                   execution_mode="remote", compute_resource="pace",
                   backend="spack", run_target="runme.m",
                   parameter_overrides={"friction": 1.0},
                   slurm=SlurmRequest(job_name="ISSM", wall_time="01:00:00",
                                      account="a"))


@pytest.fixture
def store(tmp_path):
    return AgentStore(user=_USER, workspace_root=tmp_path)


def test_inspect_a_persisted_managed_plan(store):
    mp = store.plans.create(_plan())
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    mp.approve(_USER)
    store.plans.save(mp)

    kind, data = inspect(str(store.plans._path(mp.plan_id)))
    assert kind == "managed_plan"
    text = "\n".join(render_managed_plan(data))
    assert "state                  approved" in text
    assert "digest still binds     yes" in text
    assert mp.plan.digest() in text


def test_inspect_shows_stale_approval_after_a_tamper(store):
    from dataclasses import replace
    mp = store.plans.create(_plan())
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    mp.approve(_USER)
    mp.plan = replace(mp.plan, parameter_overrides={"friction": 2.0})
    d = mp.to_dict()
    assert "NO — plan changed after approval" in "\n".join(render_managed_plan(d))


def test_inspect_a_trace_lists_permission_decisions(store):
    tr = Trace(user_id=_USER.user_id)
    store.traces.attach(tr)
    tr.request("run X")
    tr.tool_call("prepare_run_plan", args={}, permission="PLAN", ok=True,
                 summary="ok")
    tr.tool_call("submit_job", args={}, permission="EXECUTE", ok=False,
                 summary="refused: permission ceiling")
    tr.append("execution_decision", {"submitted": False, "dry_run": True})

    kind, events = inspect(str(store.traces.path_for(tr.trace_id)))
    assert kind == "trace"
    text = "\n".join(render_trace(events))
    assert "PERMISSION DECISIONS" in text
    assert "prepare_run_plan: PLAN (granted)" in text
    assert "submit_job: EXECUTE (refused)" in text
    assert "no side effect" not in text     # that line is added by main(), not render


def test_cli_resolves_a_bare_id_against_the_store(store, capsys, monkeypatch):
    mp = store.plans.create(_plan())
    base = store.root
    rc = main([mp.plan_id, "--store", str(base)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "MANAGED PLAN" in out
    assert "read-only — no side effect was replayed" in out


def test_cli_has_no_run_flag():
    import argparse
    from cryostack_src.agents import inspect as mod
    # the parser must not expose anything that executes
    src = mod.__doc__ or ""
    assert "never replays a side effect" in src.lower() or "never replay" in src.lower()
    with pytest.raises(SystemExit):
        main(["--run", "whatever"])
