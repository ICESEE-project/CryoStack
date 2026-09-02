"""Deterministic Run Assistant evaluation harness (PASS 4, task 9)."""
from __future__ import annotations

import os

import pytest

from cryostack_src.agents import Permission, Trace
from cryostack_src.agents.context import ToolContext
from cryostack_src.agents.eval import default_suite, run_scenario, run_suite
from cryostack_src.workspace import WorkspaceUser

_USER = WorkspaceUser(user_id="eval-u", source="cryostack-auth")

pytestmark = pytest.mark.skipif(
    not os.path.isdir("/home/bkyanjo3/icepack"),
    reason="planning tools need a resolvable example root")


@pytest.fixture(autouse=True)
def _roots(monkeypatch):
    monkeypatch.setenv("ICEPACK_ROOT", "/home/bkyanjo3/icepack")


def _ctx_factory():
    return lambda: ToolContext(user=_USER, application="icesheets",
                               max_permission=Permission.PLAN,
                               trace=Trace(user_id=_USER.user_id))


def test_every_shipped_scenario_passes():
    results = run_suite(_ctx_factory())
    failed = [f"{r.name}: {r.detail}" for r in results if not r.ok]
    assert not failed, "\n".join(failed)


def test_nothing_is_ever_submitted():
    for r in run_suite(_ctx_factory()):
        assert r.submitted is False


def test_zero_nodes_scenario_blocks_with_a_validation_error():
    sc = next(s for s in default_suite() if s.name == "zero nodes is a validation error")
    r = run_scenario(sc, _ctx_factory())
    assert r.ok and r.plan_is_valid is False
    assert "resolve-validation-errors-first" in r.approvals_required


def test_aws_secret_scenario_is_rejected_at_validation():
    sc = next(s for s in default_suite() if s.name == "AWS secret in the job env")
    r = run_scenario(sc, _ctx_factory())
    assert r.ok and r.plan_is_valid is False


def test_unsupported_icepack_parameter_scenario_is_rejected():
    sc = next(s for s in default_suite() if s.name == "unsupported icepack parameter")
    r = run_scenario(sc, _ctx_factory())
    assert r.ok and r.plan_is_valid is False


def test_scientific_parameter_change_requires_approval():
    sc = next(s for s in default_suite()
              if s.name == "icepack ice temperature 250 K")
    r = run_scenario(sc, _ctx_factory())
    assert "scientific-parameter-change" in r.approvals_required
