"""Results visualization panel: model-neutral selector, per-user, legacy-safe."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np

from cryostack_src.frontend.cryolauncher.workspace.visualization import (
    build_visualization_panel,
)
from cryostack_src.workspace import WorkspaceManager, WorkspaceUser
from cryostack_src.workspace.models import RunInfo

h5py = pytest.importorskip("h5py")

USER_A = WorkspaceUser(user_id="user-A", source="cryostack-auth")
USER_B = WorkspaceUser(user_id="user-B", source="cryostack-auth")

NV, NE = 6, 4
ELEMENTS = np.array([[1, 2, 3], [2, 3, 4], [3, 4, 5], [4, 5, 6]], dtype="int64")


class _Widget:
    def __init__(self, value=None):
        self.value = value
        self.options = ()


class _Log(list):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def clear_output(self):
        self.clear()


def _mgr(owner, root):
    return WorkspaceManager(
        owner=owner, workspace_root=root, status={}, session={"id": "s"},
        example_dir=_Widget(str(root)), model=_Widget("issm"), backend=_Widget("c"),
        file_picker=_Widget(), file_editor=_Widget(), log_output=None, results_output=None,
        cluster_host=_Widget(""), cluster_user=_Widget(""), cluster_port=_Widget(1),
        access_mode=_Widget(""), normalize_remote_path=lambda p: p,
        connector_fetch_archive=None, should_use_connector=lambda: False,
        connector_ssh=None, ssh_run=None, cluster_name=_Widget(""),
    )


def _h5(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as fh:
        for k, v in data.items():
            fh.create_dataset(k, data=np.asarray(v))


def _drop_package(base: Path):
    outputs = base / "cache" / "outputs"
    _h5(outputs / "mesh" / "mesh.h5",
        {"/x": np.linspace(0, 1, NV), "/y": np.linspace(0, 1, NV), "/elements": ELEMENTS})
    _h5(outputs / "fields" / "StressbalanceSolution" / "Vel.h5",
        {"/values": np.arange(NV, dtype="float64") + 1})
    _h5(outputs / "fields" / "TransientSolution" / "Thickness.h5",
        {"/values": np.vstack([np.full(NV, 10.0 + s) for s in range(3)])})
    _h5(outputs / "fields" / "TransientSolution" / "time.h5",
        {"/time": np.array([0.0, 1.0, 2.0])})
    meta = {
        "schema": "cryostack.issm.results", "version": 1, "model": "issm",
        "status": "ok",
        "mesh": {"path": "mesh/mesh.h5", "numberofvertices": NV,
                 "numberofelements": NE, "dimension": 2, "element_columns": 3,
                 "connectivity_indexing": "1-based", "has_z": False},
        "solutions": [
            {"name": "StressbalanceSolution", "transient": False, "timesteps": 1,
             "time": [], "step": [], "skipped": [],
             "fields": [{"name": "Vel", "location": "nodal", "shape": [NV],
                         "dtype": "float64",
                         "path": "fields/StressbalanceSolution/Vel.h5"}]},
            {"name": "TransientSolution", "transient": True, "timesteps": 3,
             "time": [0.0, 1.0, 2.0], "step": [1, 2, 3], "skipped": [],
             "fields": [{"name": "Thickness", "location": "nodal",
                         "shape": [3, NV], "dtype": "float64",
                         "path": "fields/TransientSolution/Thickness.h5",
                         "available_timesteps": [0, 1, 2]}]},
        ],
    }
    (outputs / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")


def _register(m, run_id="run-1"):
    run = m.register_run(RunInfo(
        id=run_id, name=run_id, model="issm", backend="c", execution_mode="remote",
        status="completed", created=datetime.now(), jobid="j"))
    m.select_run(run.id)
    return run


def _panel(m):
    return build_visualization_panel(
        manager=m,
        selected_run_id=lambda: (m.selected_run().id if m.selected_run() else ""),
        log_output=_Log())


# ── selector population ─────────────────────────────────────────────────
def test_no_run_selected_disables_panel(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    p = _panel(m)
    assert p.controller.render_btn.disabled is True
    assert "Select a run" in p.controller.status.value


def test_solution_and_field_selectors_populate(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    _drop_package(run.workspace_directory)
    p = _panel(m)
    p.controller.refresh()
    c = p.controller
    assert list(c.solution_dd.options) == ["StressbalanceSolution", "TransientSolution"]
    assert list(c.field_dd.options) == ["Vel"]
    assert c.render_btn.disabled is False


def test_transient_shows_timestep_selector(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    _drop_package(run.workspace_directory)
    p = _panel(m)
    p.controller.refresh()
    c = p.controller
    c.solution_dd.value = "TransientSolution"
    assert list(c.field_dd.options) == ["Thickness"]
    assert c.timestep_dd.layout.display != "none"
    labels = [lbl for lbl, _ in c.timestep_dd.options]
    assert labels[0] == "Final"
    assert c.timestep_dd.value is None                    # defaults to Final


def test_static_field_hides_timestep_selector(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    _drop_package(run.workspace_directory)
    p = _panel(m)
    p.controller.refresh()
    assert p.controller.timestep_dd.layout.display == "none"


# ── rendering ──────────────────────────────────────────────────────────
def test_render_creates_cached_figure_and_meta(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    _drop_package(run.workspace_directory)
    p = _panel(m)
    p.controller.refresh()
    p.controller.render()
    fig = run.workspace_directory / "cache" / "outputs" / "figures" / "StressbalanceSolution_Vel.png"
    assert fig.is_file()
    assert "Vel" in p.controller.meta.value


def test_render_transient_selected_timestep(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    _drop_package(run.workspace_directory)
    p = _panel(m)
    p.controller.refresh()
    c = p.controller
    c.solution_dd.value = "TransientSolution"
    c.timestep_dd.value = 0
    c.render()
    fig = run.workspace_directory / "cache" / "outputs" / "figures" / "TransientSolution_Thickness_t000.png"
    assert fig.is_file()


# ── legacy ─────────────────────────────────────────────────────────────
def test_legacy_run_disables_selector_with_note(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    figs = run.workspace_directory / "cache" / "outputs" / "figures"
    figs.mkdir(parents=True)
    (figs / "old.png").write_bytes(b"\x89PNG")
    p = _panel(m)
    p.controller.refresh()
    c = p.controller
    assert c.render_btn.disabled is True
    assert "legacy run" in c.status.value


def test_missing_results_disables_selector(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    _register(m)
    p = _panel(m)
    p.controller.refresh()
    assert p.controller.render_btn.disabled is True
    assert "No structured results" in p.controller.status.value


# ── isolation ──────────────────────────────────────────────────────────
def test_user_b_cannot_render_user_a_run(tmp_path):
    root = tmp_path / "ws"
    m_a = _mgr(USER_A, root)
    run = _register(m_a)
    _drop_package(run.workspace_directory)

    m_b = _mgr(USER_B, root)
    result = m_b.render_run_plot(run.id, solution="StressbalanceSolution",
                                field="Vel")
    assert result.ok is False
    assert result.reason
    # and no figure was written into A's run by B
    leaked = list((run.workspace_directory / "cache" / "outputs" / "figures").glob("*.png")) \
        if (run.workspace_directory / "cache" / "outputs" / "figures").exists() else []
    assert leaked == []
