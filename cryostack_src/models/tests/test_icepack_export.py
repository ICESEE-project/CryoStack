"""Container-side Icepack structured exporter (I3). Firedrake is mocked (not
installed here); h5py + numpy are real."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from cryostack_src.models.icepack import export as E
from cryostack_src.models.icepack._export_core import export


# ── a minimal fake Firedrake ─────────────────────────────────────────
class _Dat:
    def __init__(self, arr):
        self.data_ro = np.asarray(arr)


class _FakeFunction:
    """Duck-types firedrake.Function for _is_firedrake_function + the export."""
    def __init__(self, values, space, mesh=None):
        self._v = np.asarray(values, dtype=float)
        self._space = space
        self._mesh = mesh
        self.dat = _Dat(self._v)

    def function_space(self):
        return self._space

    # vector component access f[0], f[1]
    def __getitem__(self, i):
        return _FakeFunction(self._v[:, i], self._space, self._mesh)

    def interpolate(self, other):
        # CG1 "interpolation" of a scalar/component fake: identity
        self._v = np.asarray(getattr(other, "_v", other), dtype=float)
        self.dat = _Dat(self._v)
        return self


class _Element:
    def __init__(self, family, degree):
        self._f, self._d = family, degree
    def family(self): return self._f
    def degree(self): return self._d


class _Space:
    def __init__(self, mesh, family="Lagrange", degree=2):
        self._mesh = mesh
        self._el = _Element(family, degree)
    def mesh(self): return self._mesh
    def ufl_element(self): return self._el


class _CellNodeMap:
    def __init__(self, cells): self.values = np.asarray(cells)


class _Coords:
    def __init__(self, xy, cells):
        self.dat = _Dat(np.asarray(xy, dtype=float))
        self._cnm = _CellNodeMap(cells)
    def function_space(self):
        m = types.SimpleNamespace(cell_node_map=lambda: self._cnm)
        return m


class _Mesh:
    def __init__(self, xy, cells):
        self.coordinates = _Coords(xy, cells)


def _fake_firedrake(monkeypatch):
    fk = types.ModuleType("firedrake")
    fk.FunctionSpace = lambda mesh, fam, deg: _Space(mesh, "Lagrange", deg)
    fk.Function = lambda space: _FakeFunction(np.zeros(_n(space)), space, getattr(space, "_mesh", None))
    monkeypatch.setitem(sys.modules, "firedrake", fk)
    return fk


def _n(space):
    # number of CG1 nodes == number of mesh vertices in our fake
    return space._mesh.coordinates.dat.data_ro.shape[0]


_XY = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]
_CELLS = [[0, 1, 2], [1, 3, 2]]


# ── tests ────────────────────────────────────────────────────────────
def test_exports_thickness_and_velocity_in_the_issm_h5_shape(tmp_path, monkeypatch):
    _fake_firedrake(monkeypatch)
    h5py = pytest.importorskip("h5py")

    mesh = _Mesh(_XY, _CELLS)
    sp = _Space(mesh, "Lagrange", 2)
    class IceShelf:  # a stand-in icepack.models.IceShelf
        pass

    ns = {
        "h": _FakeFunction([10.0, 11.0, 12.0, 13.0], sp, mesh),
        "u": _FakeFunction([[1.0, 0.0], [2.0, 0.0], [3.0, 1.0], [4.0, 1.0]], sp, mesh),
        "model": IceShelf(),
    }

    (tmp_path / "outputs").mkdir()
    meta = export(ns, str(tmp_path))

    assert meta["status"] == "ok"
    assert meta["schema"] == E.SCHEMA and meta["version"] == 2
    names = {f["name"] for f in meta["fields"]}
    assert names == {"thickness", "velocity"}
    thick = next(f for f in meta["fields"] if f["name"] == "thickness")
    assert thick["units"] == "meters" and thick["location"] == "nodal"
    assert thick["exported_space"] == "CG1" and thick["source_space"] == "CG2"
    assert thick["linearised"] is True
    vel = next(f for f in meta["fields"] if f["name"] == "velocity")
    assert vel["rank"] == "vector" and vel["components"] == ["velocity_x", "velocity_y"]

    out = tmp_path / "outputs"
    with h5py.File(out / "mesh" / "mesh.h5") as fh:
        assert list(fh["x"][()]) == [0.0, 1.0, 0.0, 1.0]
        assert fh["elements"].shape == (2, 3)
    with h5py.File(out / "fields" / "icepack" / "thickness.h5") as fh:
        assert list(fh["values"][()]) == [10.0, 11.0, 12.0, 13.0]
    with h5py.File(out / "fields" / "icepack" / "velocity.h5") as fh:
        assert "values" in fh and "values_y" in fh and "magnitude" in fh
    assert meta["mesh"]["numberofvertices"] == 4 and meta["mesh"]["cell"] == "triangle"


def test_no_recognised_function_is_reported_empty_not_failed(tmp_path, monkeypatch):
    _fake_firedrake(monkeypatch)
    (tmp_path / "outputs").mkdir()
    meta = export({"x": 3, "some_dict": {}}, str(tmp_path))
    assert meta["status"] == "empty"
    assert meta["fields"] == []
    assert (tmp_path / "outputs" / "metadata.json").is_file()


def test_non_triangular_mesh_is_unsupported_geometry_not_a_crash(tmp_path, monkeypatch):
    _fake_firedrake(monkeypatch)
    mesh = _Mesh([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2, 0]])  # 3-D coords, quad cell
    sp = _Space(mesh, "Lagrange", 1)
    (tmp_path / "outputs").mkdir()
    meta = export({"h": _FakeFunction([1.0, 2.0, 3.0], sp, mesh)}, str(tmp_path))
    assert meta["status"] == "unsupported_geometry"


def test_export_never_raises_even_on_broken_firedrake(tmp_path, monkeypatch):
    broken = types.ModuleType("firedrake")
    broken.FunctionSpace = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    broken.Function = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "firedrake", broken)
    mesh = _Mesh(_XY, _CELLS)
    sp = _Space(mesh, "Lagrange", 2)
    (tmp_path / "outputs").mkdir()
    meta = export({"h": _FakeFunction([1.0, 2, 3, 4], sp, mesh)}, str(tmp_path))
    assert meta["status"] in ("export_failed", "empty")
    assert (tmp_path / "outputs" / "metadata.json").is_file()   # honest record written


def test_shell_block_writes_both_modules_and_is_non_fatal():
    blk = E.build_export_shell_block(
        run_dir="/run", example_dir="/ex", backend="container",
        sif_path="/img.sif", stack_binds="", run_file_name="ex.ipynb", run_file_py="ex.py",
    )
    assert "cryostack_icepack_export.py" in blk and "cryostack_icepack_runner.py" in blk
    assert "with-icepack bash -lc" in blk
    assert '|| echo "[cryostack][warn]' in blk         # non-fatal
    assert "CRYOSTACK_ICEPACK_EXPORT_EOF" not in E.export_module_source()  # no delimiter leak
    assert 'runpy.run_path' in E.runner_module_source()


def test_submission_appends_export_then_collector_for_icepack():
    src = (Path(__file__).resolve().parents[2] / "models/submission.py").read_text()
    assert "build_icepack_export_block(" in src
    # export before collector so the collector merges, never clobbers
    assert src.index("build_icepack_export_block(") < src.index("build_icepack_collection_block(\n            run_dir=remote_run_dir")
