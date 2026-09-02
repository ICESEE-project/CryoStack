"""Icepack result-package reader: honest status reporting, no fabricated
solution/field taxonomy, and pickup by the WorkspaceManager reader resolver."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cryostack_src.models.icepack import discover_results
from cryostack_src.models.icepack.results import SCHEMA, IcepackResultPackage


def _pkg(root, meta=None, figures=(), model_files=()):
    out = Path(root) / "outputs"
    (out / "figures").mkdir(parents=True, exist_ok=True)
    (out / "model").mkdir(parents=True, exist_ok=True)
    for f in figures:
        (out / "figures" / f).write_bytes(b"\x89PNG\r\n")
    for m in model_files:
        (out / "model" / m).write_bytes(b"\x89HDF\r\n")
    if meta is not None:
        (out / "metadata.json").write_text(json.dumps(meta))
    return discover_results(root)


def test_missing_outputs_is_missing(tmp_path):
    p = discover_results(tmp_path / "nope")
    assert p.status == "missing"
    assert p.outputs is None
    assert p.model is None


def test_schema_conformant_artifacts_package(tmp_path):
    meta = {"schema": SCHEMA, "version": 1, "model": "icepack",
            "status": "artifacts", "solutions": [], "fields": [],
            "figures": ["u.png"], "model_files": [], "note": "…"}
    p = _pkg(tmp_path, meta=meta, figures=["u.png"])
    assert isinstance(p, IcepackResultPackage)
    assert p.status == "artifacts"
    assert p.schema == SCHEMA
    assert p.model == "icepack"
    # honest: no structured field access
    assert p.is_readable() is False
    assert p.available_solutions() == []
    assert p.available_fields("anything") == []
    assert p.recommended_plots() == []
    assert [Path(f).name for f in p.legacy_artifacts()["figures"]] == ["u.png"]


def test_empty_package_reported_as_empty(tmp_path):
    meta = {"schema": SCHEMA, "status": "empty", "figures": [], "model_files": []}
    p = _pkg(tmp_path, meta=meta)
    assert p.status == "empty"


def test_outputs_without_metadata_but_with_figures_is_artifacts(tmp_path):
    p = _pkg(tmp_path, meta=None, figures=["fig1.png"])
    assert p.status == "artifacts"
    assert p.schema is None                      # no metadata to claim one


def test_outputs_with_nothing_recognisable_is_legacy(tmp_path):
    out = tmp_path / "outputs"
    (out / "model").mkdir(parents=True)
    (out / "mesh").mkdir()
    p = discover_results(tmp_path)
    assert p.status == "legacy"


def _structured(tmp_path):
    """Write a schema-v2 structured package (mesh + thickness + velocity)."""
    h5py = pytest.importorskip("h5py")
    import numpy as np
    out = tmp_path / "outputs"
    (out / "mesh").mkdir(parents=True)
    (out / "fields" / "icepack").mkdir(parents=True)
    (out / "figures").mkdir()
    with h5py.File(out / "mesh" / "mesh.h5", "w") as fh:
        fh["x"] = np.array([0.0, 1.0, 0.0, 1.0])
        fh["y"] = np.array([0.0, 0.0, 1.0, 1.0])
        fh["elements"] = np.array([[0, 1, 2], [1, 3, 2]])
    with h5py.File(out / "fields" / "icepack" / "thickness.h5", "w") as fh:
        fh["values"] = np.array([10.0, 11.0, 12.0, 13.0])
    with h5py.File(out / "fields" / "icepack" / "velocity.h5", "w") as fh:
        fh["values"] = np.array([1.0, 2.0, 3.0, 4.0])
        fh["values_y"] = np.array([0.0, 0.0, 1.0, 1.0])
        fh["magnitude"] = np.hypot([1.0, 2, 3, 4], [0.0, 0, 1, 1])
    meta = {
        "schema": SCHEMA, "version": 2, "model": "icepack", "status": "ok",
        "mesh": {"path": "mesh/mesh.h5", "numberofvertices": 4,
                 "numberofelements": 2, "dimension": 2, "cell": "triangle"},
        "fields": [
            {"name": "thickness", "components": ["thickness"], "rank": "scalar",
             "location": "nodal", "units": "meters",
             "exported_space": "CG1", "source_space": "CG2", "linearised": True,
             "path": "fields/icepack/thickness.h5", "timestep": None},
            {"name": "velocity", "components": ["velocity_x", "velocity_y"],
             "rank": "vector", "location": "nodal", "units": "meters/year",
             "path": "fields/icepack/velocity.h5", "timestep": None},
        ],
        "figures": [], "model_files": [], "skipped": [],
    }
    (out / "metadata.json").write_text(json.dumps(meta))
    return discover_results(tmp_path)


def test_structured_package_is_readable(tmp_path):
    p = _structured(tmp_path)
    assert p.status == "ok"
    assert p.is_readable() is True
    assert p.available_solutions() == ["icepack"]
    # velocity surfaced before thickness (preference order)
    assert p.available_fields() == ["velocity", "thickness"]
    assert p.timesteps() == [0]


def test_structured_package_loads_mesh_and_fields(tmp_path):
    import numpy as np
    p = _structured(tmp_path)
    mesh = p.load_mesh()
    assert mesh["numberofvertices"] == 4 and mesh["numberofelements"] == 2
    assert list(mesh["x"]) == [0.0, 1.0, 0.0, 1.0]
    assert mesh["elements"].shape == (2, 3)

    thk = p.load_field("thickness")
    assert list(thk) == [10.0, 11.0, 12.0, 13.0]

    vx, vy = p.load_field("velocity")
    assert list(vx) == [1.0, 2.0, 3.0, 4.0] and list(vy) == [0.0, 0.0, 1.0, 1.0]
    mag = p.load_field_magnitude("velocity")
    assert np.allclose(mag, np.hypot([1, 2, 3, 4], [0, 0, 1, 1]))

    plots = p.recommended_plots()
    assert {pl["field"] for pl in plots} == {"thickness", "velocity"}


def test_exporter_declared_failure_states_pass_through(tmp_path):
    out = tmp_path / "outputs"
    out.mkdir()
    (out / "metadata.json").write_text(json.dumps({
        "schema": SCHEMA, "version": 2, "status": "unsupported_geometry",
        "fields": [], "note": "extruded mesh"}))
    p = discover_results(tmp_path)
    assert p.status == "unsupported_geometry"
    assert p.is_readable() is False


def test_field_units_are_carried_through(tmp_path):
    p = _structured(tmp_path)
    assert p.field_metadata("thickness")["units"] == "meters"
    assert p.field_metadata("velocity")["rank"] == "vector"


def test_workspace_manager_resolves_the_icepack_reader():
    from cryostack_src.workspace.manager import _result_reader_for
    assert _result_reader_for("icepack") is discover_results
    # unknown model still falls back safely
    from cryostack_src.models.issm.results import discover_results as issm_discover
    assert _result_reader_for("issm") is issm_discover
