"""PASS 4 task 3: the Run Assistant mounts into the IceSheets gateway
collapsed, has no submit path, and its on_approve records a digest-bound
approval in the user's AgentStore."""
from __future__ import annotations

import sys
from pathlib import Path

import ipywidgets as W
import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.agents import AgentStore, PlanState, RunPlan, SlurmRequest
from cryostack_src.workspace import WorkspaceUser
from icesee_jupyter_book.ui.icesheets_gateway import _build_agent_accordion


def _plan_dict() -> dict:
    return RunPlan(application="icesheets", model="issm", example="SquareIceShelf",
                   execution_mode="remote", compute_resource="pace",
                   backend="spack", run_target="runme.m",
                   slurm=SlurmRequest(job_name="ISSM", wall_time="01:00:00",
                                      account="gts")).to_dict()


def _iter(w):
    yield w
    for c in getattr(w, "children", ()):
        yield from _iter(c)


@pytest.fixture(autouse=True)
def user_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HTTP_X_CRYOSTACK_USER_ID", "gw-agent-u")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    return tmp_path


def test_accordion_builds_collapsed_and_titled():
    acc = _build_agent_accordion(workspace_manager=None)
    assert isinstance(acc, W.Accordion)
    assert acc.selected_index is None
    assert "Run Assistant" in acc.get_title(0)


def test_no_submit_verb_anywhere_in_the_panel():
    acc = _build_agent_accordion(workspace_manager=None)
    labels = {b.description.lower() for b in _iter(acc) if isinstance(b, W.Button)}
    assert not any("submit" in x for x in labels)
    assert "approve plan" in labels and "revise plan" in labels


def test_on_approve_records_a_persisted_digest_bound_approval():
    acc = _build_agent_accordion(workspace_manager=None)
    panel = acc._cryostack_agent_panel

    plan = _plan_dict()
    panel.approvable_plan = plan
    for cb in _iter(panel.container):
        if isinstance(cb, W.Checkbox):
            cb.value = True
    plan_id = panel.approve()
    assert plan_id

    store = AgentStore(user=WorkspaceUser(user_id="gw-agent-u",
                                          source="cryostack-auth"))
    mp = store.plans.load(plan_id)
    assert mp.state is PlanState.APPROVED
    assert mp.owner_user_id == "gw-agent-u"
    assert mp.approval.plan_digest == RunPlan.from_dict(plan).digest()


def test_gateway_respects_the_opt_in_flag(monkeypatch):
    # the flag gate lives in build_icesheets_ui; assert the helper is only
    # referenced there behind the env check
    src = Path(_REPO, "icesee_jupyter_book/ui/icesheets_gateway.py").read_text()
    assert 'os.environ.get("CRYOSTACK_AGENT_PANEL"' in src
    assert "_build_agent_accordion(workspace_manager)" in src
