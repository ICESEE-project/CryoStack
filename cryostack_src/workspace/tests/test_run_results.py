"""WorkspaceManager.result_package_for_run -- data-only, per-user, no rendering.

The manager only *locates* a run's already-fetched ``outputs/`` tree and hands
back a :class:`ResultPackage`. Fetching (transport) and rendering (Commit 5) are
deliberately not involved here.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from cryostack_src.workspace import WorkspaceManager, WorkspaceUser
from cryostack_src.workspace.models import RunInfo

USER_A = WorkspaceUser(user_id="user-A", source="cryostack-auth")
USER_B = WorkspaceUser(user_id="user-B", source="cryostack-auth")

_METADATA = {
    "schema": "cryostack.issm.results",
    "version": 1,
    "model": "issm",
    "status": "ok",
    "mesh": {"path": "mesh/mesh.h5", "numberofvertices": 3,
             "numberofelements": 1, "dimension": 2, "element_columns": 3,
             "connectivity_indexing": "1-based", "has_z": False},
    "solutions": [
        {"name": "StressbalanceSolution", "transient": False, "timesteps": 1,
         "time": [], "step": [],
         "fields": [{"name": "Vel", "location": "nodal", "shape": [3],
                     "dtype": "float64",
                     "path": "fields/StressbalanceSolution/Vel.h5"}],
         "skipped": []},
    ],
}


class _Widget:
    def __init__(self, value=None):
        self.value = value
        self.options = ()


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


def _register(m, run_id="run-1"):
    run = m.register_run(RunInfo(
        id=run_id, name=run_id, model="issm", backend="c",
        execution_mode="remote", status="completed", created=datetime.now(),
        jobid="j"))
    m.select_run(run.id)
    return run


def _drop_package(base: Path, subdir: str = "cache/outputs") -> Path:
    outputs = base / subdir
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "metadata.json").write_text(json.dumps(_METADATA), encoding="utf-8")
    (outputs / "model").mkdir(exist_ok=True)
    (outputs / "model" / "md_final.mat").write_bytes(b"stub")
    return outputs


def test_locates_fetched_outputs(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    _drop_package(run.workspace_directory)

    pkg = m.result_package_for_run(run.id)
    assert pkg.status == "ok"
    assert pkg.available_solutions() == ["StressbalanceSolution"]
    assert pkg.available_fields("StressbalanceSolution") == ["Vel"]


def test_locates_cloud_outputs(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    _drop_package(run.workspace_directory, subdir="cache/cloud_outputs")
    pkg = m.result_package_for_run(run.id)
    assert pkg.available_solutions() == ["StressbalanceSolution"]


def test_legacy_run_does_not_crash(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    legacy = run.workspace_directory / "cache" / "outputs" / "figures"
    legacy.mkdir(parents=True)
    (legacy / "vel.png").write_bytes(b"\x89PNG")

    pkg = m.result_package_for_run(run.id)
    assert pkg.status == "legacy"
    assert pkg.available_solutions() == []


def test_unknown_run_is_missing_not_error(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    pkg = m.result_package_for_run("no-such-run")
    assert pkg.status == "missing"
    assert pkg.available_solutions() == []


def test_non_issm_model_degrades_gracefully(tmp_path):
    """Icepack has no result reader / visualizer yet -- the Results tab must
    not crash, it just offers nothing."""
    m = _mgr(USER_A, tmp_path / "ws")
    run = m.register_run(RunInfo(
        id="ip-1", name="ip-1", model="icepack", backend="c",
        execution_mode="remote", status="completed", created=datetime.now(), jobid="j"))
    m.select_run(run.id)
    _drop_package(run.workspace_directory)

    assert m.recommended_plots_for_run(run.id) == []
    result = m.render_run_plot(run.id, solution="X", field="Y")
    assert result.ok is False and "icepack" in result.reason


def test_another_user_cannot_read_the_package(tmp_path):
    root = tmp_path / "ws"
    m_a = _mgr(USER_A, root)
    run = _register(m_a)
    _drop_package(run.workspace_directory)

    m_b = _mgr(USER_B, root)
    # B references A's run id directly
    pkg = m_b.result_package_for_run(run.id)
    assert pkg.status == "missing"
    assert pkg.available_solutions() == []
