"""Agent observability (PASS 4, task 7): opt-in CRYOSTACK_PERF milestones,
static labels only, no data."""
from __future__ import annotations

import pytest

from cryostack_src import perf
from cryostack_src.agents import (
    LLMResponse,
    Permission,
    RunAssistant,
    ScriptedLLM,
    Trace,
)
from cryostack_src.agents.approval import PlanStore
from cryostack_src.agents.context import ToolContext
from cryostack_src.agents.execution import DryRunExecutionCoordinator
from cryostack_src.agents.planning import RunPlan, SlurmRequest
from cryostack_src.workspace import WorkspaceUser

_USER = WorkspaceUser(user_id="obs-u", source="cryostack-auth")


def _ctx(perm=Permission.PLAN):
    return ToolContext(user=_USER, application="icesheets", max_permission=perm,
                       trace=Trace(user_id=_USER.user_id))


def _plan():
    return RunPlan(application="icesheets", model="issm", example="e",
                   execution_mode="remote", compute_resource="pace",
                   backend="spack", run_target="runme.m",
                   slurm=SlurmRequest(job_name="ISSM", wall_time="01:00:00",
                                      account="a"))


def test_disabled_by_default(capsys, monkeypatch):
    monkeypatch.delenv("CRYOSTACK_PERF", raising=False)
    RunAssistant(llm=ScriptedLLM([LLMResponse(text="hi")])).handle(_ctx(), "x")
    assert capsys.readouterr().err == ""


def test_milestones_emitted_when_enabled(capsys, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_PERF", "1")
    RunAssistant(llm=ScriptedLLM([LLMResponse(text="done")])).handle(_ctx(), "x")
    err = capsys.readouterr().err
    assert "[perf] agent request received" in err
    assert "agent tool discovery" in err


def test_execution_handoff_and_coordinator_span(capsys, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_PERF", "1")
    store = PlanStore()
    mp = store.create(owner=_USER, plan=_plan())
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    mp.approve(_USER)
    capsys.readouterr()  # drop the "approval recorded" line

    class _B:
        def submit(self, plan, *, ctx, approval=None):
            return "job-9"

    DryRunExecutionCoordinator(submit_backend=_B()).execute(
        _ctx(Permission.EXECUTE), mp, dry_run=False)
    err = capsys.readouterr().err
    assert "agent execution coordinator" in err
    assert "agent execution handoff" in err
    assert "agent submit backend" in err


def test_event_prints_no_value(capsys, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_PERF", "1")
    perf.event("agent approval recorded")
    line = capsys.readouterr().err
    assert line == "[perf] agent approval recorded\n"      # label only, no number
