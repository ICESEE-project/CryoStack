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


class _CaptureOut(list):
    """Stand-in for an ipywidgets Output that records printed text."""

    def __enter__(self):
        import builtins
        self._orig = builtins.print
        builtins.print = lambda *a, **k: self.append(" ".join(str(x) for x in a))
        return self

    def __exit__(self, *exc):
        import builtins
        builtins.print = self._orig
        return False

    def clear_output(self, *a, **k):
        self.clear()

    @property
    def text(self):
        return "\n".join(self)


def _mgr(owner, root, *, results_output=None):
    return WorkspaceManager(
        owner=owner, workspace_root=root, status={}, session={"id": "s"},
        example_dir=_Widget(str(root)), model=_Widget("issm"), backend=_Widget("c"),
        file_picker=_Widget(), file_editor=_Widget(), log_output=None,
        results_output=results_output,
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


# The exact run shape from the field report: a steady Stressbalance run whose
# outputs/ was fetched into <run>/cache/outputs but whose selectors stayed empty.
_SCREENSHOT_METADATA = {
    "schema": "cryostack.issm.results", "version": 1, "model": "issm",
    "status": "ok",
    "mesh": {"path": "mesh/mesh.h5", "numberofvertices": 3, "numberofelements": 1,
             "dimension": 2, "element_columns": 3,
             "connectivity_indexing": "1-based", "has_z": False},
    "solutions": [{
        "name": "StressbalanceSolution", "transient": False, "timesteps": 1,
        "time": [], "step": [], "skipped": [],
        "fields": [
            {"name": "Vx", "location": "nodal", "shape": [3], "dtype": "float64",
             "path": "fields/StressbalanceSolution/Vx.h5"},
            {"name": "Vy", "location": "nodal", "shape": [3], "dtype": "float64",
             "path": "fields/StressbalanceSolution/Vy.h5"},
            {"name": "Vel", "location": "nodal", "shape": [3], "dtype": "float64",
             "path": "fields/StressbalanceSolution/Vel.h5"},
            {"name": "Pressure", "location": "nodal", "shape": [3], "dtype": "float64",
             "path": "fields/StressbalanceSolution/Pressure.h5"},
            {"name": "StressbalanceConvergenceNumSteps", "location": "scalar",
             "shape": [1], "dtype": "float64",
             "path": "fields/StressbalanceSolution/StressbalanceConvergenceNumSteps.h5"},
        ],
    }],
}


def _drop_screenshot_package(base: Path, subdir: str = "cache/outputs") -> Path:
    outputs = base / subdir
    for rel in ("mesh", "fields/StressbalanceSolution", "model"):
        (outputs / rel).mkdir(parents=True, exist_ok=True)
    (outputs / "metadata.json").write_text(
        json.dumps(_SCREENSHOT_METADATA), encoding="utf-8")
    (outputs / "mesh" / "mesh.h5").write_bytes(b"h5stub")
    for f in ("Vx", "Vy", "Vel", "Pressure", "StressbalanceConvergenceNumSteps"):
        (outputs / "fields" / "StressbalanceSolution" / f"{f}.h5").write_bytes(b"h5stub")
    (outputs / "model" / "md_final.mat").write_bytes(b"stub")
    return outputs


def test_diagnostic_boundary_after_fetch_returns_ok_with_all_fields(tmp_path):
    """The exact boundary the field report pointed at:
    result_package_for_run(run_id) after the fetch has landed cache/outputs."""
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    _drop_screenshot_package(run.workspace_directory)

    pkg = m.result_package_for_run(run.id)
    assert pkg.status == "ok"
    assert pkg.is_readable() is True
    assert "StressbalanceSolution" in pkg.available_solutions()
    fields = pkg.available_fields("StressbalanceSolution")
    for expected in ("Vel", "Vx", "Vy", "Pressure"):
        assert expected in fields, fields
    assert fields[0] == "Vel"                                   # preference order


def test_preview_results_reports_structured_available_when_no_pngs(tmp_path):
    """figures/ is intentionally empty on a fresh Commit-4 run -- Preview Results
    must say structured results are available, not 'nothing to preview'."""
    out = _CaptureOut()
    m = _mgr(USER_A, tmp_path / "ws", results_output=out)
    run = _register(m)
    outputs = _drop_screenshot_package(run.workspace_directory)

    class _Stub:
        stdout = ""
        stderr = ""

    m.inspect_remote_results = lambda: _Stub()
    m.refresh_results = lambda: outputs

    m.preview_results()
    assert "Structured results are available" in out.text
    assert "nothing to preview" not in out.text.lower()
    assert "No structured results" not in out.text


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


def test_icepack_figures_only_package_degrades_gracefully(tmp_path):
    """An Icepack run whose structured export produced no fields (or a figures-
    only run): the Results tab must not crash, it just offers no field plots."""
    m = _mgr(USER_A, tmp_path / "ws")
    run = m.register_run(RunInfo(
        id="ip-1", name="ip-1", model="icepack", backend="c",
        execution_mode="remote", status="completed", created=datetime.now(), jobid="j"))
    m.select_run(run.id)
    figs = run.workspace_directory / "cache" / "outputs" / "figures"
    figs.mkdir(parents=True)
    (figs / "velocity.png").write_bytes(b"\x89PNG")

    assert m.recommended_plots_for_run(run.id) == []
    result = m.render_run_plot(run.id, solution="X", field="Y")
    assert result.ok is False and result.reason        # unsupported, not a crash


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
