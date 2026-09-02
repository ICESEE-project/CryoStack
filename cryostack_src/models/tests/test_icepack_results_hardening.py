"""Icepack result reader + visualizer: malformed / partial output degrades to a
typed error or an 'unsupported' render — never a crash (PASS 4, task 11).

No new scientific fields or parameters are introduced here; this only hardens
the readers against a broken container-side export.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

h5py = pytest.importorskip("h5py")
np = pytest.importorskip("numpy")

from cryostack_src.models.icepack import discover_results
from cryostack_src.models.icepack.results import SCHEMA, ResultError
from cryostack_src.visualization import icepack as viz


def _outputs(tmp_path) -> Path:
    out = tmp_path / "outputs"
    (out / "fields" / "icepack").mkdir(parents=True, exist_ok=True)
    (out / "mesh").mkdir(parents=True, exist_ok=True)
    return out


def _write_mesh(out: Path, *, x=(0., 1., 0., 1.), y=(0., 0., 1., 1.),
                elements=((0, 1, 2), (1, 3, 2)), keys=("x", "y", "elements")):
    with h5py.File(out / "mesh" / "mesh.h5", "w") as fh:
        if "x" in keys:
            fh["x"] = np.asarray(x, float)
        if "y" in keys:
            fh["y"] = np.asarray(y, float)
        if "elements" in keys:
            fh["elements"] = np.asarray(elements, int)


def _write_scalar(out: Path, name: str, values):
    with h5py.File(out / "fields" / "icepack" / f"{name}.h5", "w") as fh:
        if values is not None:
            fh["values"] = np.asarray(values, float)


def _write_meta(out: Path, fields, status="ok"):
    (out / "metadata.json").write_text(json.dumps({
        "schema": SCHEMA, "version": 2, "model": "icepack", "status": status,
        "fields": fields, "figures": [], "model_files": []}))


def _scalar_field(name="thickness"):
    return {"name": name, "rank": "scalar", "location": "nodal",
            "path": f"fields/icepack/{name}.h5"}


# ── missing / corrupt structure ─────────────────────────────────────
def test_missing_mesh_is_not_readable_and_field_load_raises_typed(tmp_path):
    out = _outputs(tmp_path)
    _write_scalar(out, "thickness", [1, 2, 3, 4])
    _write_meta(out, [_scalar_field()])
    # no mesh.h5
    pkg = discover_results(tmp_path)
    assert pkg.is_readable() is False
    with pytest.raises(ResultError):
        pkg.load_field("thickness")


def test_corrupt_mesh_h5_raises_result_error(tmp_path):
    out = _outputs(tmp_path)
    _write_scalar(out, "thickness", [1, 2, 3, 4])
    _write_meta(out, [_scalar_field()])
    _write_mesh(out, keys=("x", "y"))          # missing 'elements'
    pkg = discover_results(tmp_path)
    with pytest.raises(ResultError) as e:
        pkg.load_mesh()
    assert "elements" in str(e.value)


def test_missing_field_h5_raises_result_error(tmp_path):
    out = _outputs(tmp_path)
    _write_mesh(out)
    _write_meta(out, [_scalar_field()])
    # metadata references thickness.h5 but the file was never written
    pkg = discover_results(tmp_path)
    with pytest.raises(ResultError):
        pkg.load_field("thickness")


def test_field_h5_without_values_dataset(tmp_path):
    out = _outputs(tmp_path)
    _write_mesh(out)
    with h5py.File(out / "fields" / "icepack" / "thickness.h5", "w") as fh:
        fh["not_values"] = np.array([1.0, 2.0])
    _write_meta(out, [_scalar_field()])
    pkg = discover_results(tmp_path)
    with pytest.raises(ResultError) as e:
        pkg.load_field("thickness")
    assert "values" in str(e.value)


def test_vector_components_size_mismatch(tmp_path):
    out = _outputs(tmp_path)
    _write_mesh(out)
    with h5py.File(out / "fields" / "icepack" / "velocity.h5", "w") as fh:
        fh["values"] = np.array([1.0, 2.0, 3.0, 4.0])
        fh["values_y"] = np.array([0.0, 1.0])         # wrong length
    _write_meta(out, [{"name": "velocity", "rank": "vector",
                       "location": "nodal", "path": "fields/icepack/velocity.h5"}])
    pkg = discover_results(tmp_path)
    with pytest.raises(ResultError) as e:
        pkg.load_field("velocity")
    assert "disagree" in str(e.value)


def test_corrupt_metadata_field_entries_are_dropped(tmp_path):
    out = _outputs(tmp_path)
    _write_mesh(out)
    _write_scalar(out, "thickness", [1, 2, 3, 4])
    _write_meta(out, [{"rank": "scalar"}, "not-a-dict", _scalar_field()])
    pkg = discover_results(tmp_path)
    assert pkg.available_fields() == ["thickness"]
    with pytest.raises(ResultError):
        pkg.field_metadata("bogus")


def test_completely_corrupt_metadata_json_is_not_readable(tmp_path):
    out = _outputs(tmp_path)
    (out / "metadata.json").write_text("{ this is not json")
    pkg = discover_results(tmp_path)
    assert pkg.status in ("legacy", "empty", "artifacts")
    assert pkg.is_readable() is False


# ── NaN / Inf ───────────────────────────────────────────────────────
def test_all_nonfinite_field_reads_but_renders_unsupported(tmp_path):
    out = _outputs(tmp_path)
    _write_mesh(out)
    _write_scalar(out, "thickness", [np.nan, np.inf, -np.inf, np.nan])
    _write_meta(out, [_scalar_field()])
    pkg = discover_results(tmp_path)
    vals = pkg.load_field("thickness")
    assert not np.isfinite(vals).any()
    r = viz.render_field(pkg, "icepack", "thickness")
    assert r.ok is False


def test_partial_nan_field_renders_ok_with_masking(tmp_path):
    out = _outputs(tmp_path)
    _write_mesh(out)
    _write_scalar(out, "thickness", [10.0, np.nan, 12.0, 13.0])
    _write_meta(out, [_scalar_field()])
    pkg = discover_results(tmp_path)
    r = viz.render_field(pkg, "icepack", "thickness", outdir=tmp_path / "fig")
    assert r.ok is True
    assert "masked" in (r.caption or "")


def test_field_vs_mesh_size_mismatch_renders_unsupported(tmp_path):
    out = _outputs(tmp_path)
    _write_mesh(out)
    _write_scalar(out, "thickness", [1.0, 2.0, 3.0])   # 3 vs 4 vertices
    _write_meta(out, [_scalar_field()])
    pkg = discover_results(tmp_path)
    r = viz.render_field(pkg, "icepack", "thickness")
    assert r.ok is False


# ── exporter found nothing / failed ─────────────────────────────────
def test_exporter_no_supported_functions_is_empty(tmp_path):
    out = tmp_path / "outputs"
    out.mkdir(parents=True)
    (out / "metadata.json").write_text(json.dumps({
        "schema": SCHEMA, "version": 2, "model": "icepack", "status": "empty",
        "fields": [], "figures": [], "model_files": [],
        "note": "no supported Firedrake Functions found in the run namespace"}))
    pkg = discover_results(tmp_path)
    assert pkg.status == "empty"
    assert pkg.is_readable() is False
    assert pkg.recommended_plots() == []
    assert viz.render_recommended(pkg) == []


def test_exporter_declared_failure_is_surfaced(tmp_path):
    out = tmp_path / "outputs"
    out.mkdir(parents=True)
    (out / "metadata.json").write_text(json.dumps({
        "schema": SCHEMA, "version": 2, "model": "icepack",
        "status": "export_failed", "fields": [], "figures": [],
        "error": "ModuleNotFoundError: firedrake"}))
    pkg = discover_results(tmp_path)
    assert pkg.status == "export_failed"
    assert pkg.is_readable() is False
