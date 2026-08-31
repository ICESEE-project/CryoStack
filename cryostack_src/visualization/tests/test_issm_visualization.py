"""Commit 5 -- deterministic ISSM visualization on the neutral result package.

No MATLAB, no live ISSM, no AI. Fixtures synthesise the exported package
(metadata.json + HDF5) and the renderers must produce valid figures or a clear
reason -- never raise.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np

from cryostack_src.models.issm.results import discover_results, preferred_order
from cryostack_src.visualization import issm as viz

h5py = pytest.importorskip("h5py")

# ── fixture: a small triangular mesh + representative solutions ────────────
NV, NE = 6, 4
ELEMENTS_1BASED = np.array([[1, 2, 3], [2, 3, 4], [3, 4, 5], [4, 5, 6]], dtype="int64")


def _h5(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as fh:
        for k, v in data.items():
            fh.create_dataset(k, data=np.asarray(v))


def build_package(tmp_path: Path, *, dim: int = 2) -> Path:
    outputs = tmp_path / "run" / "outputs"
    (outputs / "figures").mkdir(parents=True, exist_ok=True)
    mesh = {
        "/x": np.linspace(0.0, 1.0, NV),
        "/y": np.linspace(0.0, 1.0, NV),
        "/elements": ELEMENTS_1BASED,
    }
    if dim == 3:
        mesh["/z"] = np.linspace(0.0, 10.0, NV)
    _h5(outputs / "mesh" / "mesh.h5", mesh)

    _h5(outputs / "fields" / "StressbalanceSolution" / "Vel.h5",
        {"/values": np.arange(NV, dtype="float64") + 1.0})
    _h5(outputs / "fields" / "StressbalanceSolution" / "Pressure.h5",
        {"/values": np.arange(NE, dtype="float64") * 5.0})
    _h5(outputs / "fields" / "StressbalanceSolution" / "IceVolume.h5",
        {"/values": np.array([7.0])})

    nsteps = 3
    _h5(outputs / "fields" / "TransientSolution" / "time.h5",
        {"/time": np.array([0.0, 0.5, 1.0])})
    _h5(outputs / "fields" / "TransientSolution" / "Thickness.h5",
        {"/values": np.vstack([np.full(NV, 100.0 + s) for s in range(nsteps)])})
    _h5(outputs / "fields" / "TransientSolution" / "IceVolume.h5",
        {"/values": np.array([[10.0], [20.0], [30.0]])})
    _h5(outputs / "fields" / "TransientSolution" / "Surface.h5",
        {"/values": np.vstack([np.full(NV, np.nan), np.full(NV, 5.0), np.full(NV, 6.0)])})

    meta = {
        "schema": "cryostack.issm.results", "version": 1, "model": "issm",
        "status": "ok",
        "mesh": {"path": "mesh/mesh.h5", "numberofvertices": NV,
                 "numberofelements": NE, "dimension": dim, "element_columns": 3,
                 "connectivity_indexing": "1-based", "has_z": dim == 3},
        "solutions": [
            {"name": "StressbalanceSolution", "transient": False, "timesteps": 1,
             "time": [], "step": [], "skipped": [],
             "fields": [
                 {"name": "Pressure", "location": "elemental", "shape": [NE],
                  "dtype": "float64", "path": "fields/StressbalanceSolution/Pressure.h5"},
                 {"name": "Vel", "location": "nodal", "shape": [NV],
                  "dtype": "float64", "path": "fields/StressbalanceSolution/Vel.h5"},
                 {"name": "IceVolume", "location": "scalar", "shape": [1],
                  "dtype": "float64", "path": "fields/StressbalanceSolution/IceVolume.h5"},
             ]},
            {"name": "TransientSolution", "transient": True, "timesteps": nsteps,
             "time": [0.0, 0.5, 1.0], "step": [1, 2, 3], "skipped": [],
             "fields": [
                 {"name": "Thickness", "location": "nodal", "shape": [nsteps, NV],
                  "dtype": "float64", "path": "fields/TransientSolution/Thickness.h5",
                  "available_timesteps": [0, 1, 2]},
                 {"name": "Surface", "location": "nodal", "shape": [nsteps, NV],
                  "dtype": "float64", "path": "fields/TransientSolution/Surface.h5",
                  "available_timesteps": [1, 2]},
                 {"name": "IceVolume", "location": "scalar", "shape": [nsteps],
                  "dtype": "float64", "path": "fields/TransientSolution/IceVolume.h5",
                  "available_timesteps": [0, 1, 2]},
             ]},
        ],
    }
    (outputs / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return outputs.parent


@pytest.fixture
def pkg(tmp_path):
    return discover_results(build_package(tmp_path))


# ── preference layer ─────────────────────────────────────────────────────
def test_preferred_field_order():
    assert preferred_order("StressbalanceSolution",
                           ["Pressure", "IceVolume", "Vel"]) == \
        ["Vel", "Pressure", "IceVolume"]
    # unknown fields keep their order, after known ones
    assert preferred_order("ThermalSolution", ["Foo", "Temperature", "Bar"]) == \
        ["Temperature", "Foo", "Bar"]


def test_available_fields_uses_preference(pkg):
    assert pkg.available_fields("StressbalanceSolution") == \
        ["Vel", "Pressure", "IceVolume"]
    assert pkg.available_fields("StressbalanceSolution", preferred=False) == \
        ["Pressure", "Vel", "IceVolume"]


def test_recommended_plots_ordered_and_aggregated(pkg):
    recs = viz.recommended_plots(pkg)
    pairs = [(r["solution"], r["field"], r["kind"]) for r in recs]
    assert pairs[0] == ("StressbalanceSolution", "Vel", "map")
    assert pairs[1] == ("StressbalanceSolution", "Pressure", "map")
    assert ("TransientSolution", "Thickness", "map") in pairs
    assert ("TransientSolution", "IceVolume", "timeseries") in pairs
    thickness = next(r for r in recs if r["field"] == "Thickness")
    assert thickness["timestep"] == 2                     # final available


# ── field maps ───────────────────────────────────────────────────────────
def test_render_nodal_field(pkg):
    r = viz.render_field(pkg, "StressbalanceSolution", "Vel")
    assert r.ok and r.kind == "map"
    assert r.path.name == "StressbalanceSolution_Vel.png"
    assert r.path.is_file() and r.path.stat().st_size > 0
    assert "nodal · 6 values" in r.caption


def test_render_elemental_field(pkg):
    r = viz.render_field(pkg, "StressbalanceSolution", "Pressure")
    assert r.ok
    assert r.path.name == "StressbalanceSolution_Pressure.png"
    assert "elemental · 4 values" in r.caption


def test_transient_defaults_to_final_available_timestep(pkg):
    r = viz.render_field(pkg, "TransientSolution", "Thickness")
    assert r.ok and r.timestep == 2
    assert r.path.name == "TransientSolution_Thickness_t002.png"


def test_transient_explicit_timestep(pkg):
    r = viz.render_field(pkg, "TransientSolution", "Thickness", timestep=0)
    assert r.ok and r.timestep == 0
    assert r.path.name == "TransientSolution_Thickness_t000.png"


def test_transient_partial_availability_default_and_reject(pkg):
    default = viz.render_field(pkg, "TransientSolution", "Surface")
    assert default.ok and default.timestep == 2            # step 0 is NaN/unavailable
    rejected = viz.render_field(pkg, "TransientSolution", "Surface", timestep=0)
    assert not rejected.ok and "not available" in rejected.reason


def test_scalar_transient_field_redirects_to_timeseries(pkg):
    r = viz.render_field(pkg, "TransientSolution", "IceVolume")
    assert r.ok and r.kind == "timeseries"
    assert r.path.name == "TransientSolution_IceVolume_timeseries.png"


def test_static_scalar_has_no_map(pkg):
    r = viz.render_field(pkg, "StressbalanceSolution", "IceVolume")
    assert not r.ok and "scalar" in r.reason


# ── time series ─────────────────────────────────────────────────────────
def test_render_timeseries(pkg):
    r = viz.render_timeseries(pkg, "TransientSolution", "IceVolume")
    assert r.ok and r.kind == "timeseries"
    assert r.path.name == "TransientSolution_IceVolume_timeseries.png"
    assert "scalar · 3 timesteps" in r.caption


def test_timeseries_rejects_spatial_field(pkg):
    r = viz.render_timeseries(pkg, "TransientSolution", "Thickness")
    assert not r.ok and "scalar diagnostic" in r.reason


# ── unsupported shapes ──────────────────────────────────────────────────
def test_3d_mesh_is_unsupported(tmp_path):
    p = discover_results(build_package(tmp_path, dim=3))
    r = viz.render_field(p, "StressbalanceSolution", "Vel")
    assert not r.ok and "3-D" in r.reason


def test_unknown_field_is_unsupported(pkg):
    r = viz.render_field(pkg, "StressbalanceSolution", "NoSuchField")
    assert not r.ok and r.reason


def test_other_location_is_unsupported(tmp_path):
    run_dir = build_package(tmp_path)
    meta_path = run_dir / "outputs" / "metadata.json"
    meta = json.loads(meta_path.read_text())
    meta["solutions"][0]["fields"].append(
        {"name": "Weird", "location": "other", "shape": [99], "dtype": "float64",
         "path": "fields/StressbalanceSolution/Weird.h5"})
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    _h5(run_dir / "outputs" / "fields" / "StressbalanceSolution" / "Weird.h5",
        {"/values": np.zeros(99)})
    r = viz.render_field(discover_results(run_dir), "StressbalanceSolution", "Weird")
    assert not r.ok and "other" in r.reason


# ── legacy + missing ───────────────────────────────────────────────────
def test_legacy_run_returns_reason_not_exception(tmp_path):
    legacy = tmp_path / "old" / "outputs"
    (legacy / "figures").mkdir(parents=True)
    (legacy / "figures" / "vel.png").write_bytes(b"\x89PNG")
    p = discover_results(tmp_path / "old")
    r = viz.render_field(p, "StressbalanceSolution", "Vel")
    assert not r.ok and "legacy" in r.reason
    assert viz.recommended_plots(p) == []


def test_missing_run_returns_reason(tmp_path):
    p = discover_results(tmp_path / "nope")
    r = viz.render_field(p, "X", "Y")
    assert not r.ok and r.reason


# ── caching / determinism ──────────────────────────────────────────────
def test_figure_name_is_deterministic():
    assert viz.figure_name("StressbalanceSolution", "Vel", kind="map") == \
        "StressbalanceSolution_Vel.png"
    assert viz.figure_name("TransientSolution", "Thickness", kind="map",
                           timestep=9) == "TransientSolution_Thickness_t009.png"
    assert viz.figure_name("TransientSolution", "IceVolume", kind="timeseries") == \
        "TransientSolution_IceVolume_timeseries.png"


def test_rerender_replaces_same_cached_file(pkg):
    first = viz.render_field(pkg, "StressbalanceSolution", "Vel")
    mtime1 = first.path.stat().st_mtime_ns
    second = viz.render_field(pkg, "StressbalanceSolution", "Vel")
    assert second.path == first.path
    assert second.path.stat().st_mtime_ns >= mtime1


def test_cached_under_outputs_figures(pkg):
    r = viz.render_field(pkg, "StressbalanceSolution", "Vel")
    assert r.path.parent == pkg.outputs / "figures"


def test_custom_outdir_is_honoured(tmp_path, pkg):
    target = tmp_path / "cache" / "figs"
    r = viz.render_field(pkg, "StressbalanceSolution", "Vel", outdir=target)
    assert r.ok and r.path.parent == target


def test_render_recommended_batch(pkg):
    results = viz.render_recommended(pkg, max_plots=10)
    assert all(isinstance(x, viz.RenderResult) for x in results)
    ok = [x for x in results if x.ok]
    assert {x.field for x in ok} >= {"Vel", "Pressure", "Thickness", "IceVolume"}


def test_transport_neutral_render(tmp_path):
    run_dir = build_package(tmp_path)
    relocated = tmp_path / "s3pull" / "outputs"
    shutil.copytree(run_dir / "outputs", relocated)
    r = viz.render_field(discover_results(relocated), "StressbalanceSolution", "Vel")
    assert r.ok and r.path.parent == relocated / "figures"
