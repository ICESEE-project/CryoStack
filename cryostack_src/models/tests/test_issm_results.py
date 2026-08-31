"""Commit 4 -- the neutral ISSM result export / discovery contract.

Fixtures synthesise the on-disk package that
:data:`cryostack_src.models.issm.postprocess._MATLAB` writes (metadata.json +
HDF5 arrays), then exercise the MATLAB-free reader in
:mod:`cryostack_src.models.issm.results`.
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

from cryostack_src.models.issm import (
    ResultError, ResultPackage, discover_results,
)

h5py = pytest.importorskip("h5py")


# ── fixture builders ───────────────────────────────────────────────────────
NV = 6          # vertices
NE = 4          # triangles
ELEMENTS_1BASED = np.array(
    [[1, 2, 3], [2, 3, 4], [3, 4, 5], [4, 5, 6]], dtype="int64"
)


def _write_h5(path: Path, datasets: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as fh:
        for name, data in datasets.items():
            fh.create_dataset(name, data=np.asarray(data))


def _write_mesh(outputs: Path, *, transpose_elements: bool = False,
                with_z: bool = False) -> None:
    elements = ELEMENTS_1BASED.T if transpose_elements else ELEMENTS_1BASED
    data = {
        "/x": np.linspace(0.0, 1.0, NV),
        "/y": np.linspace(0.0, 2.0, NV),
        "/elements": elements,
    }
    if with_z:
        data["/z"] = np.zeros(NV)
    _write_h5(outputs / "mesh" / "mesh.h5", data)


def _mesh_meta(*, with_z: bool = False) -> dict:
    return {
        "path": "mesh/mesh.h5",
        "numberofvertices": NV,
        "numberofelements": NE,
        "dimension": 3 if with_z else 2,
        "element_columns": 3,
        "connectivity_indexing": "1-based",
        "has_z": with_z,
    }


def build_package(tmp_path: Path, *, transpose_elements: bool = False,
                  transpose_transient: bool = False) -> Path:
    """A realistic run: a steady Stressbalance + a 3-step Transient +
    a Thermal solution, plus a couple of unsupported fields."""
    outputs = tmp_path / "run-123" / "outputs"
    (outputs / "figures").mkdir(parents=True, exist_ok=True)
    (outputs / "model").mkdir(parents=True, exist_ok=True)
    (outputs / "model" / "md_final.mat").write_bytes(b"MATLAB 7.3 stub")
    _write_mesh(outputs, transpose_elements=transpose_elements)

    vel = np.arange(NV, dtype="float64") + 0.5
    pressure = np.arange(NE, dtype="float64") * 10.0

    # steady Stressbalance -----------------------------------------------
    _write_h5(outputs / "fields" / "StressbalanceSolution" / "Vel.h5",
              {"/values": vel})
    _write_h5(outputs / "fields" / "StressbalanceSolution" / "Pressure.h5",
              {"/values": pressure})
    _write_h5(outputs / "fields" / "StressbalanceSolution" / "IceVolume.h5",
              {"/values": np.array([42.0])})

    # transient (3 steps): Thickness nodal, IceVolume scalar ------------
    nsteps = 3
    thickness = np.vstack([np.full(NV, 100.0 + s) for s in range(nsteps)])
    icevol_t = np.array([[10.0], [20.0], [30.0]])
    _write_h5(outputs / "fields" / "TransientSolution" / "time.h5",
              {"/time": np.array([0.0, 1.0, 2.0]),
               "/step": np.array([1.0, 2.0, 3.0])})
    _write_h5(
        outputs / "fields" / "TransientSolution" / "Thickness.h5",
        {"/values": thickness.T if transpose_transient else thickness},
    )
    _write_h5(outputs / "fields" / "TransientSolution" / "IceVolume.h5",
              {"/values": icevol_t})
    # Surface only available at steps 1 and 2 (0-based)
    surface = np.vstack([np.full(NV, np.nan), np.full(NV, 5.0), np.full(NV, 6.0)])
    _write_h5(
        outputs / "fields" / "TransientSolution" / "Surface.h5",
        {"/values": surface.T if transpose_transient else surface},
    )

    # thermal ----------------------------------------------------------
    _write_h5(outputs / "fields" / "ThermalSolution" / "Temperature.h5",
              {"/values": np.full(NV, 263.15)})

    metadata = {
        "schema": "cryostack.issm.results",
        "version": 1,
        "model": "issm",
        "created": "2026-08-31T12:00:00",
        "status": "ok",
        "mesh": _mesh_meta(),
        "solutions": [
            {
                "name": "StressbalanceSolution",
                "transient": False,
                "timesteps": 1,
                "time": [],
                "step": [],
                "fields": [
                    {"name": "Vel", "location": "nodal", "shape": [NV],
                     "dtype": "float64", "path": "fields/StressbalanceSolution/Vel.h5"},
                    {"name": "Pressure", "location": "elemental", "shape": [NE],
                     "dtype": "float64",
                     "path": "fields/StressbalanceSolution/Pressure.h5"},
                    {"name": "IceVolume", "location": "scalar", "shape": [1],
                     "dtype": "float64",
                     "path": "fields/StressbalanceSolution/IceVolume.h5"},
                ],
                "skipped": [
                    {"name": "SolutionType", "reason":
                     "string field is metadata, not a scientific array",
                     "kind": "char"},
                ],
            },
            {
                "name": "TransientSolution",
                "transient": True,
                "timesteps": nsteps,
                "time": [0.0, 1.0, 2.0],
                "step": [1.0, 2.0, 3.0],
                "fields": [
                    {"name": "Thickness", "location": "nodal",
                     "shape": [nsteps, NV], "dtype": "float64",
                     "path": "fields/TransientSolution/Thickness.h5",
                     "available_timesteps": [0, 1, 2]},
                    {"name": "IceVolume", "location": "scalar",
                     "shape": [nsteps], "dtype": "float64",
                     "path": "fields/TransientSolution/IceVolume.h5",
                     "available_timesteps": [0, 1, 2]},
                    {"name": "Surface", "location": "nodal",
                     "shape": [nsteps, NV], "dtype": "float64",
                     "path": "fields/TransientSolution/Surface.h5",
                     "available_timesteps": [1, 2]},
                ],
                "skipped": [
                    {"name": "SolverConvergence", "reason":
                     "struct-valued field is not supported", "kind": "struct"},
                ],
            },
            {
                "name": "ThermalSolution",
                "transient": False,
                "timesteps": 1,
                "time": [],
                "step": [],
                "fields": [
                    {"name": "Temperature", "location": "nodal", "shape": [NV],
                     "dtype": "float64",
                     "path": "fields/ThermalSolution/Temperature.h5"},
                ],
                "skipped": [],
            },
        ],
    }
    (outputs / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return outputs.parent


# ── discovery + metadata ──────────────────────────────────────────────────
def test_discover_from_run_dir_or_outputs_dir(tmp_path):
    run_dir = build_package(tmp_path)
    from_run = discover_results(run_dir)
    from_outputs = discover_results(run_dir / "outputs")
    assert from_run.outputs == from_outputs.outputs == run_dir / "outputs"
    assert from_run.is_readable() and from_run.status == "ok"
    assert from_run.schema == "cryostack.issm.results"
    assert from_run.version == 1 and from_run.model == "issm"


def test_metadata_round_trip(tmp_path):
    pkg = discover_results(build_package(tmp_path))
    assert pkg.available_solutions() == [
        "StressbalanceSolution", "TransientSolution", "ThermalSolution",
    ]
    assert pkg.available_fields("StressbalanceSolution") == [
        "Vel", "Pressure", "IceVolume",
    ]
    vel = pkg.field_metadata("StressbalanceSolution", "Vel")
    assert vel.location == "nodal"
    assert vel.shape == (NV,)
    assert vel.dtype == "float64"
    assert vel.transient is False
    assert vel.units is None


def test_field_classification(tmp_path):
    pkg = discover_results(build_package(tmp_path))
    loc = {f: pkg.field_metadata("StressbalanceSolution", f).location
           for f in pkg.available_fields("StressbalanceSolution")}
    assert loc == {"Vel": "nodal", "Pressure": "elemental", "IceVolume": "scalar"}


def test_skipped_unsupported_fields_are_recorded(tmp_path):
    pkg = discover_results(build_package(tmp_path))
    skipped = pkg.solution("TransientSolution").skipped
    assert [s.name for s in skipped] == ["SolverConvergence"]
    assert skipped[0].kind == "struct"
    assert "not supported" in skipped[0].reason
    # a skipped field is not offered as a loadable field
    assert "SolverConvergence" not in pkg.available_fields("TransientSolution")


# ── mesh ─────────────────────────────────────────────────────────────────
def test_mesh_connectivity_converted_to_zero_based(tmp_path):
    pkg = discover_results(build_package(tmp_path))
    mesh = pkg.load_mesh()
    assert mesh["numberofvertices"] == NV
    assert mesh["numberofelements"] == NE
    assert mesh["dimension"] == 2
    assert mesh["elements"].shape == (NE, 3)
    assert mesh["connectivity_indexing"] == "0-based"
    assert mesh["connectivity_indexing_source"] == "1-based"
    np.testing.assert_array_equal(mesh["elements"], ELEMENTS_1BASED - 1)
    assert mesh["elements"].min() == 0
    assert mesh["elements"].max() == NV - 1


def test_mesh_element_orientation_is_tolerated(tmp_path):
    """A MATLAB-native [ncols x ne] dataset is transposed back deterministically."""
    pkg = discover_results(build_package(tmp_path, transpose_elements=True))
    mesh = pkg.load_mesh()
    assert mesh["elements"].shape == (NE, 3)
    np.testing.assert_array_equal(mesh["elements"], ELEMENTS_1BASED - 1)


def test_mesh_coordinates(tmp_path):
    pkg = discover_results(build_package(tmp_path))
    mesh = pkg.load_mesh()
    assert mesh["x"].shape == (NV,)
    assert "z" not in mesh
    np.testing.assert_allclose(mesh["x"], np.linspace(0.0, 1.0, NV))


# ── static fields ────────────────────────────────────────────────────────
def test_load_static_nodal_field(tmp_path):
    pkg = discover_results(build_package(tmp_path))
    vel = pkg.load_field("StressbalanceSolution", "Vel")
    assert vel.shape == (NV,)
    np.testing.assert_allclose(vel, np.arange(NV) + 0.5)


def test_load_static_scalar_field(tmp_path):
    pkg = discover_results(build_package(tmp_path))
    vol = pkg.load_field("StressbalanceSolution", "IceVolume")
    assert vol.reshape(-1)[0] == 42.0


def test_static_field_rejects_timestep(tmp_path):
    pkg = discover_results(build_package(tmp_path))
    with pytest.raises(ResultError):
        pkg.load_field("StressbalanceSolution", "Vel", timestep=1)


# ── transient fields ─────────────────────────────────────────────────────
def test_transient_timestep_indexing(tmp_path):
    pkg = discover_results(build_package(tmp_path))
    assert pkg.timesteps("TransientSolution") == [0, 1, 2]
    assert pkg.times("TransientSolution") == [0.0, 1.0, 2.0]
    full = pkg.load_field("TransientSolution", "Thickness")
    assert full.shape == (3, NV)
    for step in range(3):
        row = pkg.load_field("TransientSolution", "Thickness", timestep=step)
        assert row.shape == (NV,)
        np.testing.assert_allclose(row, 100.0 + step)


def test_transient_orientation_is_tolerated(tmp_path):
    pkg = discover_results(build_package(tmp_path, transpose_transient=True))
    row = pkg.load_field("TransientSolution", "Thickness", timestep=2)
    np.testing.assert_allclose(row, 102.0)


def test_transient_scalar_series(tmp_path):
    pkg = discover_results(build_package(tmp_path))
    series = pkg.load_field("TransientSolution", "IceVolume")
    np.testing.assert_allclose(series.reshape(-1), [10.0, 20.0, 30.0])


def test_single_available_timestep_scalar_from_matlab(tmp_path):
    """MATLAB jsonencode writes a length-1 array as a bare scalar."""
    run_dir = build_package(tmp_path)
    meta_path = run_dir / "outputs" / "metadata.json"
    meta = json.loads(meta_path.read_text())
    for sol in meta["solutions"]:
        if sol["name"] == "TransientSolution":
            for fld in sol["fields"]:
                if fld["name"] == "Surface":
                    fld["available_timesteps"] = 2      # bare scalar, not [2]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    pkg = discover_results(run_dir)
    assert pkg.field_metadata("TransientSolution", "Surface").available_timesteps == (2,)
    np.testing.assert_allclose(
        pkg.load_field("TransientSolution", "Surface", timestep=2), 6.0)
    with pytest.raises(ResultError):
        pkg.load_field("TransientSolution", "Surface", timestep=1)


def test_transient_partial_availability(tmp_path):
    pkg = discover_results(build_package(tmp_path))
    surface = pkg.field_metadata("TransientSolution", "Surface")
    assert surface.available_timesteps == (1, 2)
    np.testing.assert_allclose(
        pkg.load_field("TransientSolution", "Surface", timestep=1), 5.0)
    with pytest.raises(ResultError):
        pkg.load_field("TransientSolution", "Surface", timestep=0)
    with pytest.raises(ResultError):
        pkg.load_field("TransientSolution", "Thickness", timestep=9)


# ── recommendations (metadata only, nothing rendered) ────────────────────
def test_recommended_plots_are_descriptions_only(tmp_path):
    run_dir = build_package(tmp_path)
    pkg = discover_results(run_dir)
    recs = pkg.recommended_plots("TransientSolution")
    kinds = {(r["field"], r["kind"]) for r in recs}
    assert ("Thickness", "map") in kinds
    assert ("Surface", "map") in kinds
    assert ("IceVolume", "timeseries") in kinds
    thickness_rec = next(r for r in recs if r["field"] == "Thickness")
    assert thickness_rec["timestep"] == 2          # last step
    # nothing was rendered
    assert list((run_dir / "outputs" / "figures").glob("*")) == []

    steady = pkg.recommended_plots("StressbalanceSolution")
    assert {(r["field"], r["kind"]) for r in steady} == {
        ("Vel", "map"), ("Pressure", "map"),
    }


# ── legacy + missing (backward compat -- must not crash) ─────────────────
def test_legacy_results_do_not_crash(tmp_path):
    legacy = tmp_path / "old-run" / "outputs"
    (legacy / "figures").mkdir(parents=True)
    (legacy / "figures" / "vel.png").write_bytes(b"\x89PNG stub")
    (legacy / "model").mkdir()
    (legacy / "model" / "md_final.mat").write_bytes(b"stub")

    pkg = discover_results(tmp_path / "old-run")
    assert pkg.status == "legacy"
    assert pkg.legacy is True
    assert pkg.is_readable() is False
    assert pkg.available_solutions() == []
    arts = pkg.legacy_artifacts()
    assert arts["model_mat"] is not None
    assert any(p.endswith("vel.png") for p in arts["figures"])
    with pytest.raises(ResultError):
        pkg.load_mesh()


def test_corrupt_metadata_falls_back_to_legacy(tmp_path):
    outputs = tmp_path / "run" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "metadata.json").write_text("{ not json", encoding="utf-8")
    pkg = discover_results(tmp_path / "run")
    assert pkg.status == "legacy"
    assert pkg.is_readable() is False


def test_missing_results(tmp_path):
    pkg = discover_results(tmp_path / "nope")
    assert pkg.status == "missing"
    assert pkg.outputs is None
    assert pkg.available_solutions() == []
    with pytest.raises(ResultError):
        pkg.load_mesh()


def test_status_markers_pass_through(tmp_path):
    outputs = tmp_path / "run" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "metadata.json").write_text(json.dumps({
        "schema": "cryostack.issm.results", "version": 1, "model": "issm",
        "status": "no-results", "solutions": [],
    }), encoding="utf-8")
    pkg = discover_results(tmp_path / "run")
    assert pkg.status == "no-results"
    assert pkg.is_readable() is True
    assert pkg.available_solutions() == []


# ── transport neutrality ────────────────────────────────────────────────
def test_transport_neutral_local_copy(tmp_path):
    run_dir = build_package(tmp_path)
    original = discover_results(run_dir)

    relocated = tmp_path / "elsewhere" / "s3_pull" / "outputs"
    shutil.copytree(run_dir / "outputs", relocated)
    copy = discover_results(relocated)

    assert copy.available_solutions() == original.available_solutions()
    for sol in original.available_solutions():
        assert copy.available_fields(sol) == original.available_fields(sol)
    np.testing.assert_array_equal(
        copy.load_mesh()["elements"], original.load_mesh()["elements"])
    np.testing.assert_allclose(
        copy.load_field("TransientSolution", "Thickness", timestep=1),
        original.load_field("TransientSolution", "Thickness", timestep=1))


# ── package export surface ─────────────────────────────────────────────
def test_reader_is_exported_from_adapter():
    from cryostack_src.models import get_model_adapter

    issm = get_model_adapter("issm")
    assert hasattr(issm, "discover_results")
    assert issm.discover_results is discover_results
    assert isinstance(discover_results(Path("/nonexistent")), ResultPackage)
