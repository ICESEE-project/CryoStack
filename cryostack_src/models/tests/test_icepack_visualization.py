"""Deterministic Icepack visualization (I4) -- Firedrake-free, on the neutral
result package."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
h5py = pytest.importorskip("h5py")

from cryostack_src.models.icepack.results import SCHEMA, discover_results
from cryostack_src.visualization import icepack as viz


def _pkg(tmp_path, *, vector=True, nan=False):
    out = tmp_path / "outputs"
    (out / "mesh").mkdir(parents=True)
    (out / "fields" / "icepack").mkdir(parents=True)
    (out / "figures").mkdir()
    x = np.array([0.0, 1.0, 0.0, 1.0, 0.5])
    y = np.array([0.0, 0.0, 1.0, 1.0, 0.5])
    els = np.array([[0, 1, 4], [1, 3, 4], [3, 2, 4], [2, 0, 4]])
    with h5py.File(out / "mesh" / "mesh.h5", "w") as fh:
        fh["x"] = x; fh["y"] = y; fh["elements"] = els
    thk = np.array([10.0, 11, 12, 13, 12])
    if nan:
        thk = thk.copy(); thk[2] = np.nan
    with h5py.File(out / "fields" / "icepack" / "thickness.h5", "w") as fh:
        fh["values"] = thk
    fields = [{"name": "thickness", "components": ["thickness"], "rank": "scalar",
               "location": "nodal", "units": "meters", "linearised": True,
               "path": "fields/icepack/thickness.h5", "timestep": None}]
    if vector:
        with h5py.File(out / "fields" / "icepack" / "velocity.h5", "w") as fh:
            fh["values"] = np.array([1.0, 2, 3, 4, 2])
            fh["values_y"] = np.array([0.0, 1, 0, 1, 0.5])
            fh["magnitude"] = np.hypot([1.0, 2, 3, 4, 2], [0.0, 1, 0, 1, 0.5])
        fields.append({"name": "velocity", "components": ["velocity_x", "velocity_y"],
                       "rank": "vector", "location": "nodal", "units": "meters/year",
                       "path": "fields/icepack/velocity.h5", "timestep": None})
    (out / "metadata.json").write_text(json.dumps({
        "schema": SCHEMA, "version": 2, "status": "ok",
        "mesh": {"path": "mesh/mesh.h5", "numberofvertices": 5,
                 "numberofelements": 4, "dimension": 2},
        "fields": fields, "figures": [], "model_files": [], "skipped": [],
    }))
    return discover_results(tmp_path)


def test_render_scalar_field_produces_a_png(tmp_path):
    p = _pkg(tmp_path, vector=False)
    r = viz.render_field(p, "icepack", "thickness")
    assert r.ok and r.kind == "map"
    assert Path(r.path).is_file() and Path(r.path).suffix == ".png"
    assert "meters" in r.caption and "linearised" in r.caption


def test_render_vector_field_uses_speed_plus_quiver(tmp_path):
    p = _pkg(tmp_path)
    r = viz.render_field(p, "icepack", "velocity")
    assert r.ok and "vector" in r.caption
    assert Path(r.path).is_file()


def test_render_is_deterministic_same_filename(tmp_path):
    p = _pkg(tmp_path, vector=False)
    a = viz.render_field(p, "icepack", "thickness")
    b = viz.render_field(p, "icepack", "thickness")
    assert a.path == b.path


def test_unknown_field_comes_back_unsupported_not_raised(tmp_path):
    p = _pkg(tmp_path)
    r = viz.render_field(p, "icepack", "no_such_field")
    assert r.ok is False and r.reason


def test_nan_nodes_are_masked_not_fatal(tmp_path):
    p = _pkg(tmp_path, vector=False, nan=True)
    r = viz.render_field(p, "icepack", "thickness")
    assert r.ok and "masked" in r.caption


def test_timeseries_is_not_applicable_for_tier1(tmp_path):
    p = _pkg(tmp_path, vector=False)
    r = viz.render_timeseries(p, "icepack", "thickness")
    assert r.ok is False and "final-state only" in r.reason


def test_render_recommended_covers_all_fields(tmp_path):
    p = _pkg(tmp_path)
    results = viz.render_recommended(p)
    assert {r.field for r in results} == {"thickness", "velocity"}
    assert all(r.ok for r in results)


def test_figures_only_package_is_not_renderable(tmp_path):
    out = tmp_path / "outputs" / "figures"
    out.mkdir(parents=True)
    (out / "fig.png").write_bytes(b"\x89PNG")
    p = discover_results(tmp_path)
    r = viz.render_field(p, "icepack", "thickness")
    assert r.ok is False and "not readable" in r.reason


def test_workspace_manager_resolves_the_icepack_visualizer():
    from cryostack_src.workspace.manager import _visualizer_for
    assert _visualizer_for("icepack") is viz
    assert _visualizer_for("issm") is not viz
    assert _visualizer_for("lorenz") is None
