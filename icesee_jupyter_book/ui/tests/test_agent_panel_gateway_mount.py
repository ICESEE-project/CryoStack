"""Agent as the third interaction mode (Basic | Advanced | Agent).

* Agent is opt-in via CRYOSTACK_AGENT_PANEL -- without it the mode selector is
  exactly Basic / Advanced and nothing agent-related is built;
* the Run Assistant panel has no submit verb;
* on_approve records a persisted, digest-bound approval in the user's own
  AgentStore;
* Agent mode converges on the same services (no agent_submit / agent_results /
  agent_workspace parallel path).
"""
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
from icesee_jupyter_book.ui.icesheets_gateway import (
    _agent_mode_enabled,
    _build_agent_panel,
)

_ICESHEETS = _REPO / "icesee_jupyter_book/ui/icesheets_gateway.py"


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


# ── opt-in ───────────────────────────────────────────────────────────────
def test_agent_mode_is_off_by_default(monkeypatch):
    monkeypatch.delenv("CRYOSTACK_AGENT_PANEL", raising=False)
    assert _agent_mode_enabled() is False


@pytest.mark.parametrize("v", ["1", "true", "on", "YES"])
def test_agent_mode_opt_in_values(monkeypatch, v):
    monkeypatch.setenv("CRYOSTACK_AGENT_PANEL", v)
    assert _agent_mode_enabled() is True


# ── the panel ────────────────────────────────────────────────────────────
def test_panel_has_no_submit_verb():
    panel = _build_agent_panel(workspace_manager=None)
    labels = {b.description.lower() for b in _iter(panel.container)
              if isinstance(b, W.Button)}
    assert not any("submit" in x for x in labels)
    assert "approve plan" in labels and "revise plan" in labels
    assert "create plan" in labels


def test_panel_copy_states_the_boundary():
    panel = _build_agent_panel(workspace_manager=None)
    blob = " ".join(h.value for h in _iter(panel.container) if isinstance(h, W.HTML))
    assert "Execution stays under explicit human control" in blob
    assert "cannot approve or submit" in blob
    assert "Basic or Advanced" in blob


def test_on_approve_records_a_persisted_digest_bound_approval():
    panel = _build_agent_panel(workspace_manager=None)
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


# ── the gateway wiring ──────────────────────────────────────────────────
def test_gateway_builds_agent_only_behind_the_opt_in():
    src = _ICESHEETS.read_text()
    assert "_agent_mode_enabled()" in src
    assert "_build_agent_panel(workspace_manager)" in src
    # the third mode is added only when opted in
    assert '("Agent · Beta", "agent")' in src
    # no parallel execution stack
    for banned in ("agent_submit(", "agent_results(", "agent_workspace(",
                   "agent_cloud(", "agent_slurm("):
        assert banned not in src


def test_agent_mode_hides_manual_config_and_the_run_button():
    src = _ICESHEETS.read_text()
    assert "is_agent = ui_mode_dd.value == \"agent\"" in src
    # the manual Run button + Run Plan are hidden in agent mode
    assert 'actions_card.layout.display = "none" if is_agent else ""' in src
    assert 'run_plan.container.layout.display = "none" if is_agent else ""' in src


@pytest.mark.parametrize("builder", ["build_icesheets_ui"])
def test_gateway_builds_with_agent_mode_on(builder, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_AGENT_PANEL", "1")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "agent-mode-build-user")
    monkeypatch.setenv("USER", "agent-mode-service")
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    page = build_icesheets_ui()
    toggles = [w for w in _iter(page) if isinstance(w, W.ToggleButtons)]
    mode_toggles = [t for t in toggles if set(dict(t.options).values()) >= {"basic", "advanced"}]
    assert mode_toggles and "agent" in dict(mode_toggles[0].options).values()


def test_mode_switching_keeps_one_intact_workspace(monkeypatch):
    """Basic -> Agent -> Advanced -> Agent -> Basic must not duplicate the
    Workspace Tab or lose its Runs/Files/Run Log/Results structure."""
    monkeypatch.setenv("CRYOSTACK_AGENT_PANEL", "1")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "mode-switch-user")
    monkeypatch.setenv("USER", "mode-switch-service")
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    page = build_icesheets_ui()

    def _tabs():
        return [w for w in _iter(page)
                if isinstance(w, W.Tab)
                and "cryostack-workspace-tabs" in getattr(w, "_dom_classes", ())]

    ws = _tabs()
    assert len(ws) == 1 and len(ws[0].children) == 4

    toggles = [w for w in _iter(page) if isinstance(w, W.ToggleButtons)]
    mode = next(t for t in toggles
                if set(dict(t.options).values()) >= {"basic", "advanced", "agent"})
    for value in ("basic", "agent", "advanced", "agent", "basic"):
        mode.value = value
        again = _tabs()
        assert len(again) == 1 and again[0] is ws[0]        # same Tab, no duplicate
        assert len(again[0].children) == 4                  # structure intact


@pytest.mark.parametrize("builder", ["build_icesheets_ui"])
def test_gateway_builds_with_agent_mode_off(builder, monkeypatch):
    monkeypatch.delenv("CRYOSTACK_AGENT_PANEL", raising=False)
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "no-agent-build-user")
    monkeypatch.setenv("USER", "no-agent-service")
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    page = build_icesheets_ui()
    toggles = [w for w in _iter(page) if isinstance(w, W.ToggleButtons)]
    for t in toggles:
        vals = set(dict(t.options).values())
        if vals >= {"basic", "advanced"}:
            assert "agent" not in vals            # never offered without the opt-in
