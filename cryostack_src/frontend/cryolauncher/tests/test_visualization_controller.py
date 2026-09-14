"""Results visualization panel: model-neutral selector, fetch-then-populate,
legacy-safe, per-user. Regression coverage for the empty-selectors bug where
the panel refreshed before the backend had synced the run locally.
"""
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


def _drop_package(base: Path, *, subdir="cache/outputs"):
    """Write a structured result package in the backend-neutral local shape."""
    outputs = base / subdir
    _h5(outputs / "mesh" / "mesh.h5",
        {"/x": np.linspace(0, 1, NV), "/y": np.linspace(0, 1, NV), "/elements": ELEMENTS})
    _h5(outputs / "fields" / "StressbalanceSolution" / "Vel.h5",
        {"/values": np.arange(NV, dtype="float64") + 1})
    _h5(outputs / "fields" / "StressbalanceSolution" / "Pressure.h5",
        {"/values": np.arange(NE, dtype="float64") * 3.0})
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
             "fields": [
                 {"name": "Vel", "location": "nodal", "shape": [NV],
                  "dtype": "float64", "path": "fields/StressbalanceSolution/Vel.h5"},
                 {"name": "Pressure", "location": "elemental", "shape": [NE],
                  "dtype": "float64", "path": "fields/StressbalanceSolution/Pressure.h5"},
             ]},
            {"name": "TransientSolution", "transient": True, "timesteps": 3,
             "time": [0.0, 1.0, 2.0], "step": [1, 2, 3], "skipped": [],
             "fields": [{"name": "Thickness", "location": "nodal",
                         "shape": [3, NV], "dtype": "float64",
                         "path": "fields/TransientSolution/Thickness.h5",
                         "available_timesteps": [0, 1, 2]}]},
        ],
    }
    (outputs / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return outputs


def _drop_screenshot_package(base: Path, *, subdir="cache/outputs"):
    """The exact run shape from the field report: a steady Stressbalance run
    (Vx, Vy, Vel, Pressure nodal + a scalar convergence diagnostic), figures/
    empty."""
    outputs = base / subdir
    _h5(outputs / "mesh" / "mesh.h5",
        {"/x": np.linspace(0, 1, NV), "/y": np.linspace(0, 1, NV), "/elements": ELEMENTS})
    _h5(outputs / "fields" / "StressbalanceSolution" / "Vel.h5",
        {"/values": np.linspace(1, 90, NV)})
    _h5(outputs / "fields" / "StressbalanceSolution" / "Vx.h5",
        {"/values": np.linspace(-5, 5, NV)})
    _h5(outputs / "fields" / "StressbalanceSolution" / "Vy.h5",
        {"/values": np.linspace(-2, 2, NV)})
    _h5(outputs / "fields" / "StressbalanceSolution" / "Pressure.h5",
        {"/values": np.linspace(0, 1e6, NV)})
    _h5(outputs / "fields" / "StressbalanceSolution" / "StressbalanceConvergenceNumSteps.h5",
        {"/values": np.array([7.0])})
    (outputs / "model").mkdir(parents=True, exist_ok=True)
    (outputs / "model" / "md_final.mat").write_bytes(b"stub")
    meta = {
        "schema": "cryostack.issm.results", "version": 1, "model": "issm",
        "status": "ok",
        "mesh": {"path": "mesh/mesh.h5", "numberofvertices": NV,
                 "numberofelements": NE, "dimension": 2, "element_columns": 3,
                 "connectivity_indexing": "1-based", "has_z": False},
        "solutions": [{
            "name": "StressbalanceSolution", "transient": False, "timesteps": 1,
            "time": [], "step": [], "skipped": [],
            "fields": [
                {"name": "Vx", "location": "nodal", "shape": [NV], "dtype": "float64",
                 "path": "fields/StressbalanceSolution/Vx.h5"},
                {"name": "Vy", "location": "nodal", "shape": [NV], "dtype": "float64",
                 "path": "fields/StressbalanceSolution/Vy.h5"},
                {"name": "Vel", "location": "nodal", "shape": [NV], "dtype": "float64",
                 "path": "fields/StressbalanceSolution/Vel.h5"},
                {"name": "Pressure", "location": "nodal", "shape": [NV], "dtype": "float64",
                 "path": "fields/StressbalanceSolution/Pressure.h5"},
                {"name": "StressbalanceConvergenceNumSteps", "location": "scalar",
                 "shape": [1], "dtype": "float64",
                 "path": "fields/StressbalanceSolution/StressbalanceConvergenceNumSteps.h5"},
            ],
        }],
    }
    (outputs / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return outputs


def _register(m, run_id="run-1", **over):
    kw = dict(id=run_id, name=run_id, model="issm", backend="c",
              execution_mode="remote", status="completed",
              created=datetime.now(), jobid="j")
    kw.update(over)
    run = m.register_run(RunInfo(**kw))
    m.select_run(run.id)
    return run


def _panel(m, fetch_results=None):
    return build_visualization_panel(
        manager=m,
        selected_run_id=lambda: (m.selected_run().id if m.selected_run() else ""),
        log_output=_Log(),
        fetch_results=fetch_results)


class _CaptureDisplay:
    """Records everything the panel display()'s into its Output area and exposes
    the concatenated HTML/text -- so a test can inspect the *actual browser
    payload* (data-URI <img>, table markup, ...) instead of a stdout repr."""

    def __enter__(self):
        from cryostack_src.frontend.cryolauncher.workspace import visualization as _viz
        self._viz = _viz
        self._orig = _viz.display
        self.items = []

        def _rec(*objs, **_):
            self.items.extend(objs)

        _viz.display = _rec
        return self

    def __exit__(self, *exc):
        self._viz.display = self._orig
        return False

    @property
    def html(self) -> str:
        out = []
        for o in self.items:
            for attr in ("data", "value"):          # IPython HTML / ipywidgets HTML
                v = getattr(o, attr, None)
                if isinstance(v, str):
                    out.append(v)
                    break
            else:
                # IPython.display.Image -> base64 payload in ._data (bytes)
                d = getattr(o, "_data", None) or getattr(o, "data", None)
                if isinstance(d, (bytes, bytearray)):
                    out.append("<image-bytes len=%d>" % len(d))
        return "\n".join(out)


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
    assert list(c.field_dd.options) == ["Vel", "Pressure"]      # preference order
    assert c.render_btn.disabled is False


def test_solution_change_repopulates_fields_and_timestep(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    _drop_package(run.workspace_directory)
    c = _panel(m).controller
    c.refresh()
    assert list(c.field_dd.options) == ["Vel", "Pressure"]
    assert c.timestep_dd.layout.display == "none"

    c.solution_dd.value = "TransientSolution"                    # triggers _on_solution
    assert list(c.field_dd.options) == ["Thickness"]
    assert c.timestep_dd.layout.display != "none"
    assert [lbl for lbl, _ in c.timestep_dd.options][0] == "Final"
    assert c.timestep_dd.value is None


def test_field_change_reevaluates_timestep_visibility(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    _drop_package(run.workspace_directory)
    c = _panel(m).controller
    c.refresh()
    c.solution_dd.value = "TransientSolution"
    assert c.timestep_dd.layout.display != "none"               # transient field
    c.solution_dd.value = "StressbalanceSolution"
    assert c.timestep_dd.layout.display == "none"               # static field


# ── the regression: fetch-then-populate ───────────────────────────────
def test_missing_results_shows_fetch_action_not_blank(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    _register(m)
    c = _panel(m, fetch_results=lambda: None).controller
    c.refresh()
    assert c.render_btn.disabled is True
    assert list(c.solution_dd.options) == []
    assert "have not been fetched" in c.status.value
    assert c.fetch_btn.layout.display != "none"                 # actionable, not blank


def test_missing_then_fetch_populates_selectors(tmp_path):
    """Run selected before its outputs were synced -> Fetch -> selectors fill.
    Reproduces the real bug (panel refreshed before refresh_results ran)."""
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    dropped = {"done": False}

    def fake_fetch():
        _drop_package(run.workspace_directory)                  # backend sync lands here
        dropped["done"] = True

    c = _panel(m, fetch_results=fake_fetch).controller
    c.refresh()
    assert list(c.solution_dd.options) == []                    # nothing local yet

    c.fetch()                                                   # user clicks "Fetch results"
    assert dropped["done"] is True
    assert list(c.solution_dd.options) == ["StressbalanceSolution", "TransientSolution"]
    assert list(c.field_dd.options) == ["Vel", "Pressure"]
    assert c.render_btn.disabled is False


def test_preview_flow_refreshes_visualization_after_fetch(tmp_path):
    """Mirrors the gateway's on_results_preview: fetch, then controller.refresh()."""
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    c = _panel(m).controller
    c.refresh()
    assert list(c.solution_dd.options) == []

    _drop_package(run.workspace_directory)                      # preview_results() synced
    c.refresh()                                                 # gateway calls this next
    assert list(c.solution_dd.options) == ["StressbalanceSolution", "TransientSolution"]


def test_screenshot_reproduction_preview_populates_all_selectors(tmp_path):
    """Field report, reproduced exactly: run selected, outputs already fetched
    into <run>/cache/outputs, selectors were empty. After the Preview Results
    entry point (controller.preview()) they must be fully populated."""
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    c = _panel(m, fetch_results=lambda: None).controller

    # 1. initial state -- nothing local yet
    c.refresh()
    assert list(c.solution_dd.options) == []
    assert "have not been fetched" in c.status.value

    # 2. Preview Results: the backend syncs outputs, then the panel previews
    _drop_screenshot_package(run.workspace_directory)           # == preview_results() sync
    c.preview()

    # 3. selectors are populated for this exact run
    assert "fetched" not in c.status.value.lower() or "have not been" not in c.status.value
    assert "StressbalanceSolution" in list(c.solution_dd.options)
    assert c.solution_dd.value == "StressbalanceSolution"
    fields = list(c.field_dd.options)
    for expected in ("Vel", "Vx", "Vy", "Pressure"):
        assert expected in fields, fields
    assert c.field_dd.value                                      # non-empty selection
    assert c.field_dd.value == "Vel"                             # preferred first
    assert c.timestep_dd.layout.display == "none"                # steady solution
    assert c.render_btn.disabled is False


def test_preview_with_empty_figures_dir_is_normal(tmp_path):
    """Commit 4 makes figures/ initially empty -- that is the normal state, not
    'nothing to preview'. Preview must still populate + render."""
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    outputs = _drop_screenshot_package(run.workspace_directory)
    assert not (outputs / "figures").exists()

    c = _panel(m).controller
    c.preview()

    assert c.solution_dd.value == "StressbalanceSolution"
    rendered = outputs / "figures" / "StressbalanceSolution_Vel.png"
    assert rendered.is_file()                                    # initial preview render
    assert "Vel" in c.meta.value


def test_preview_fetches_first_when_still_missing(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    calls = {"n": 0}

    def fake_fetch():
        calls["n"] += 1
        _drop_screenshot_package(run.workspace_directory)

    c = _panel(m, fetch_results=fake_fetch).controller
    c.preview()                                                  # nothing local -> fetch
    assert calls["n"] == 1
    assert c.solution_dd.value == "StressbalanceSolution"


def test_fetch_button_hidden_without_a_fetch_callback(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    _register(m)
    c = _panel(m).controller                                    # no fetch_results
    c.refresh()
    assert c.fetch_btn.layout.display == "none"
    assert "have not been fetched" in c.status.value


# ── auto-preview: never just empty dropdowns ─────────────────────────
def test_readable_package_auto_renders_first_recommended(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    _drop_package(run.workspace_directory)
    c = _panel(m).controller
    c.refresh()                                                 # no explicit Render click
    fig = (run.workspace_directory / "cache" / "outputs" / "figures"
           / "StressbalanceSolution_Vel.png")
    assert fig.is_file()
    assert "Vel" in c.meta.value


# ── rendering ──────────────────────────────────────────────────────────
def test_render_transient_selected_timestep(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    _drop_package(run.workspace_directory)
    c = _panel(m).controller
    c.refresh()
    c.solution_dd.value = "TransientSolution"
    c.timestep_dd.value = 0
    c.render()
    fig = (run.workspace_directory / "cache" / "outputs" / "figures"
           / "TransientSolution_Thickness_t000.png")
    assert fig.is_file()


# ── backend / mode neutrality ───────────────────────────────────────
@pytest.mark.parametrize("backend", ["c", "container", "spack"])
def test_discovery_is_identical_across_execution_backends(tmp_path, backend):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m, backend=backend)
    _drop_package(run.workspace_directory)
    c = _panel(m).controller
    c.refresh()
    assert list(c.solution_dd.options) == ["StressbalanceSolution", "TransientSolution"]
    assert list(c.field_dd.options) == ["Vel", "Pressure"]


def test_cloud_outputs_shape_is_discovered_too(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m, execution_mode="cloud", backend="aws")
    _drop_package(run.workspace_directory, subdir="cache/cloud_outputs")
    c = _panel(m).controller
    c.refresh()
    assert list(c.solution_dd.options) == ["StressbalanceSolution", "TransientSolution"]


# ── legacy ─────────────────────────────────────────────────────────────
def test_legacy_run_disables_selector_and_hides_fetch(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m)
    figs = run.workspace_directory / "cache" / "outputs" / "figures"
    figs.mkdir(parents=True)
    (figs / "old.png").write_bytes(b"\x89PNG")
    c = _panel(m, fetch_results=lambda: None).controller
    c.refresh()
    assert c.render_btn.disabled is True
    assert "legacy run" in c.status.value
    assert c.fetch_btn.layout.display == "none"


# ── model with no structured reader yet (Icepack) ──────────────────────
def test_icepack_run_shows_collected_figures_not_a_dead_end(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m, run_id="ip-1", model="icepack")
    out = run.workspace_directory / "cache" / "outputs"
    (out / "figures").mkdir(parents=True)
    (out / "figures" / "velocity.png").write_bytes(b"\x89PNG")
    (out / "metadata.json").write_text(json.dumps({
        "schema": "cryostack.icepack.results", "status": "artifacts",
        "model": "icepack", "solutions": [], "fields": [],
        "figures": ["velocity.png"], "model_files": [],
    }))
    c = _panel(m, fetch_results=lambda: None).controller
    c.refresh()
    assert c.render_btn.disabled is True
    assert c.solution_dd.options == ()
    assert "not yet available for this model" in c.status.value
    assert "have not been fetched" not in c.status.value


def _png_bytes(width=2, height=2):
    """A real, tiny, valid PNG (so base64 embedding is a meaningful assertion)."""
    import struct
    import zlib

    def _chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw))
            + _chunk(b"IEND", b""))


def test_icepack_figure_gallery_embeds_each_png_as_a_data_uri(tmp_path):
    """00-meshes-functions class: figures but no tier-1 structured fields.

    The regression this guards: each discovered PNG must reach the browser as a
    base64 data-URI <img> -- NOT a server filesystem path, NOT a bare
    ipywidgets image display()'d into an Output (which renders blank in Voilà,
    the live "large blank area" symptom)."""
    import base64 as _b64

    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m, run_id="ip-fig", model="icepack")
    out = run.workspace_directory / "cache" / "outputs"
    (out / "figures").mkdir(parents=True)
    payloads = {}
    for n in (1, 2):
        b = _png_bytes(2 + n, 2 + n)
        payloads[f"figure-0{n}.png"] = b
        (out / "figures" / f"figure-0{n}.png").write_bytes(b)
    (out / "metadata.json").write_text(json.dumps({
        "schema": "cryostack.icepack.results", "status": "artifacts",
        "model": "icepack", "solutions": [], "fields": [],
        "figures": ["figure-01.png", "figure-02.png"], "model_files": [],
        "figures_meta": {
            "figure-01.png": {"title": "Mesh of the unit square",
                              "axes_titles": ["Mesh of the unit square"]},
            # figure-02 deliberately has no title -> "Figure 2"
        },
    }))
    c = _panel(m, fetch_results=lambda: None).controller
    with _CaptureDisplay() as cap:
        c.refresh()
    shown = cap.html

    # field controls HIDDEN (not just disabled) -- nothing implies fields exist
    assert c.field_controls.layout.display == "none"
    assert c.solution_dd.options == () and c.field_dd.options == ()
    assert c.render_btn.disabled is True

    # each PNG is embedded as its own base64 data URI -- the browser gets bytes,
    # never a path
    assert shown.count("<img src='data:image/png;base64,") == 2
    for name, raw in payloads.items():
        assert _b64.b64encode(raw).decode() in shown, f"{name} not embedded"
    # not a filesystem path / file:// / /tmp reference
    assert "file://" not in shown
    assert str(out) not in shown and "/figures/figure-01.png'" not in shown

    # titled cards, title straight from the figure metadata else "Figure N"
    assert shown.count("cryostack-figure-card") == 2
    assert shown.count("cryostack-figure-title") == 2
    assert "Mesh of the unit square" in shown and "Figure 2" in shown

    # count wording is explicit about WHAT was found
    assert "2 figures found" in c.status.value
    assert "not yet available for this model" in c.status.value


def test_gallery_heading_uses_captured_title_and_label_over_figure_n(tmp_path):
    """The card heading is the figure's own name (folded 'title', or an
    explicit 'label', or a suptitle/axes-title), and only 'Figure N' when the
    metadata carries nothing."""
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m, run_id="ip-lbl", model="icepack")
    out = run.workspace_directory / "cache" / "outputs"
    (out / "figures").mkdir(parents=True)
    for n in (1, 2, 3):
        (out / "figures" / f"figure-0{n}.png").write_bytes(_png_bytes(2 + n))
    (out / "metadata.json").write_text(json.dumps({
        "schema": "cryostack.icepack.results", "status": "artifacts",
        "model": "icepack",
        "figures": ["figure-01.png", "figure-02.png", "figure-03.png"],
        "figures_meta": {
            "figure-01.png": {"title": "Ice thickness", "label": "Ice thickness"},
            "figure-02.png": {"axes_titles": ["Basal shear stress"]},   # no folded title
            # figure-03: nothing -> "Figure 3"
        },
    }))
    c = _panel(m, fetch_results=lambda: None).controller
    with _CaptureDisplay() as cap:
        c.refresh()
    shown = cap.html
    assert "Ice thickness" in shown
    assert "Basal shear stress" in shown            # axes-title fallback in the heading
    assert "Figure 3" in shown
    # the meaningful names replace the generic ones for 1 and 2
    assert "<div class='cryostack-figure-title'>Figure 1</div>" not in shown
    assert "<div class='cryostack-figure-title'>Figure 2</div>" not in shown


def test_icepack_missing_figure_file_is_skipped_not_fatal(tmp_path):
    """metadata lists a figure whose file did not sync -- the others still
    render, no exception."""
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m, run_id="ip-miss", model="icepack")
    out = run.workspace_directory / "cache" / "outputs"
    (out / "figures").mkdir(parents=True)
    good = _png_bytes()
    (out / "figures" / "figure-01.png").write_bytes(good)
    # figure-02.png referenced in metadata but never written
    (out / "metadata.json").write_text(json.dumps({
        "schema": "cryostack.icepack.results", "status": "artifacts",
        "model": "icepack", "figures": ["figure-01.png", "figure-02.png"],
    }))
    c = _panel(m, fetch_results=lambda: None).controller
    with _CaptureDisplay() as cap:
        c.refresh()
    shown = cap.html
    import base64 as _b64
    assert shown.count("<img src='data:image/png;base64,") == 1
    assert _b64.b64encode(good).decode() in shown


def test_oversized_figure_is_not_embedded_but_still_pointed_at(tmp_path, monkeypatch):
    from cryostack_src.frontend.cryolauncher.workspace import visualization as _viz
    monkeypatch.setattr(_viz, "_MAX_INLINE_FIGURE_BYTES", 8)   # tiny cap
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m, run_id="ip-big", model="icepack")
    out = run.workspace_directory / "cache" / "outputs"
    (out / "figures").mkdir(parents=True)
    (out / "figures" / "figure-01.png").write_bytes(_png_bytes(8, 8))   # > 8 bytes
    (out / "metadata.json").write_text(json.dumps({
        "schema": "cryostack.icepack.results", "status": "artifacts",
        "model": "icepack", "figures": ["figure-01.png"],
    }))
    c = _panel(m, fetch_results=lambda: None).controller
    with _CaptureDisplay() as cap:
        c.refresh()
    shown = cap.html
    assert "data:image/png;base64," not in shown
    assert "too large to preview inline" in shown
    assert "cryostack-figure-card" in shown          # the card is still there


def test_icepack_artifacts_with_only_native_files_points_to_download(tmp_path):
    """An 'artifacts' run that produced native output files but no figures
    must not show an empty figure area with no guidance -- it points at
    Download results and lists the files (name / path / type / size), and
    never shows field dropdowns."""
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m, run_id="ip-nat", model="icepack")
    out = run.workspace_directory / "cache" / "outputs"
    (out / "model").mkdir(parents=True)
    (out / "model" / "state.h5").write_bytes(b"\x89HDF")
    (out / "metadata.json").write_text(json.dumps({
        "schema": "cryostack.icepack.results", "status": "artifacts",
        "model": "icepack", "solutions": [], "fields": [],
        "figures": [], "model_files": ["state.h5"],
    }))
    c = _panel(m, fetch_results=lambda: None).controller
    with _CaptureDisplay() as cap:
        c.refresh()
    shown = cap.html
    assert c.render_btn.disabled is True
    assert c.solution_dd.options == () and c.field_dd.options == ()
    assert "Download results" in c.status.value
    assert "1 other output file found" in c.status.value
    # the file is listed in the native-output table (not crammed into the note)
    assert "cryostack-native-files" in shown
    assert "state.h5" in shown
    assert "model/state.h5" in shown          # relative path
    assert "data:image/" not in shown         # nothing fabricated as an image


def test_native_outputs_render_through_ipython_html_not_widgets(tmp_path):
    """Guards the transport: the gallery/table go out as IPython.display.HTML
    (reliable inside an Output in Voilà), never as a nested ipywidgets view."""
    import ipywidgets as _W
    from IPython.display import HTML as _HTML

    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m, run_id="ip-tr", model="icepack")
    out = run.workspace_directory / "cache" / "outputs"
    (out / "figures").mkdir(parents=True)
    (out / "figures" / "figure-01.png").write_bytes(_png_bytes())
    (out / "metadata.json").write_text(json.dumps({
        "schema": "cryostack.icepack.results", "status": "artifacts",
        "model": "icepack", "figures": ["figure-01.png"],
    }))
    c = _panel(m, fetch_results=lambda: None).controller
    with _CaptureDisplay() as cap:
        c.refresh()
    assert cap.items, "nothing was displayed into the results area"
    assert all(isinstance(o, _HTML) for o in cap.items), \
        [type(o).__name__ for o in cap.items]
    assert not any(isinstance(o, _W.Widget) for o in cap.items)


def test_icepack_empty_run_is_reported_as_such(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    run = _register(m, run_id="ip-2", model="icepack")
    out = run.workspace_directory / "cache" / "outputs"
    (out / "model").mkdir(parents=True)
    (out / "metadata.json").write_text(json.dumps({
        "schema": "cryostack.icepack.results", "status": "empty",
        "figures": [], "model_files": [],
    }))
    c = _panel(m, fetch_results=lambda: None).controller
    c.refresh()
    assert "produced no figures or output files" in c.status.value


# ── isolation ──────────────────────────────────────────────────────────
def test_user_b_cannot_render_user_a_run(tmp_path):
    root = tmp_path / "ws"
    m_a = _mgr(USER_A, root)
    run = _register(m_a)
    _drop_package(run.workspace_directory)

    m_b = _mgr(USER_B, root)
    result = m_b.render_run_plot(run.id, solution="StressbalanceSolution", field="Vel")
    assert result.ok is False and result.reason
    leaked_dir = run.workspace_directory / "cache" / "outputs" / "figures"
    # only figures A rendered (if any) exist; B wrote nothing new
    assert m_b.result_package_for_run(run.id).status == "missing"
