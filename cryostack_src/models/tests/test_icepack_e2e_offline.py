"""Icepack end-to-end OFFLINE acceptance harness (I6).

The regression harness for tomorrow's real HPC test. Everything that would touch
a scheduler / container / Firedrake is mocked; the CryoStack plumbing is real:

  authenticated user -> select Icepack -> canonical example
    -> optional safe Basic override -> per-user working copy
    -> [ execution: mocked ]  -> structured export (mocked firedrake)
    -> IcepackResultPackage -> visualization discovery -> download

Plus: two authenticated users cannot see or overwrite one another's Icepack
working copies or results.
"""
from __future__ import annotations

import json
import sys
import types
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
h5py = pytest.importorskip("h5py")

from cryostack_src.models.icepack import (
    apply_overrides, entrypoint_transform_for, validate_icepack_config,
)
from cryostack_src.models.icepack._export_core import export
from cryostack_src.visualization import icepack as viz
from cryostack_src.workspace import WorkspaceManager, WorkspaceUser
from cryostack_src.workspace.models import RunInfo

USER_A = WorkspaceUser(user_id="ice-a", source="cryostack-auth")
USER_B = WorkspaceUser(user_id="ice-b", source="cryostack-auth")

_NOTEBOOK = json.dumps({
    "cells": [
        {"cell_type": "code", "source": ["import firedrake, icepack\n"]},
        {"cell_type": "code", "source": [
            "T = firedrake.Constant(255.15)\n", "A = icepack.rate_factor(T)\n"]},
        {"cell_type": "code", "source": [
            "num_timesteps = 200\n", "for step in range(num_timesteps):\n",
            "    pass\n"]},
    ],
    "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
})


class _W:
    def __init__(self, v=""):
        self.value, self.options = v, ()


class _Out:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def clear_output(self, *a, **k): pass


def _mgr(owner, root, example_dir):
    return WorkspaceManager(
        owner=owner, workspace_root=root, status={}, session={"id": "s"},
        example_dir=_W(str(example_dir)), model="icepack", backend=_W("spack"),
        file_picker=_W(), file_editor=_W(), log_output=_Out(), results_output=_Out(),
        cluster_host=_W(""), cluster_user=_W(""), cluster_port=_W(1),
        access_mode=_W(""), normalize_remote_path=lambda p: p,
        connector_fetch_archive=None, should_use_connector=lambda: False,
        connector_ssh=None, ssh_run=None, cluster_name=_W(""),
    )


@pytest.fixture
def canonical(tmp_path):
    ex = tmp_path / "shipped" / "ice-shelf"
    ex.mkdir(parents=True)
    (ex / "ice-shelf.ipynb").write_text(_NOTEBOOK)
    return ex


# ── the mocked "run": structured export from a fake namespace ─────────
def _fake_firedrake(monkeypatch):
    class _Dat:
        def __init__(self, a): self.data_ro = np.asarray(a)

    class _F:
        def __init__(self, v, sp):
            self._v = np.asarray(v, float); self._sp = sp; self.dat = _Dat(self._v)
        def function_space(self): return self._sp
        def __getitem__(self, i): return _F(self._v[:, i], self._sp)
        def interpolate(self, o):
            self._v = np.asarray(getattr(o, "_v", o), float); self.dat = _Dat(self._v); return self

    class _El:
        def family(self): return "Lagrange"
        def degree(self): return 2

    class _Sp:
        def __init__(self, m): self._m = m
        def mesh(self): return self._m
        def ufl_element(self): return _El()

    class _CNM:
        def __init__(self, c): self.values = np.asarray(c)

    class _Coords:
        def __init__(self, xy, c):
            self.dat = _Dat(np.asarray(xy, float)); self._c = _CNM(c)
        def function_space(self):
            return types.SimpleNamespace(cell_node_map=lambda: self._c)

    class _Mesh:
        def __init__(self, xy, c): self.coordinates = _Coords(xy, c)

    fk = types.ModuleType("firedrake")
    fk.FunctionSpace = lambda m, fam, d: _Sp(m)
    fk.Function = lambda sp: _F(np.zeros(sp._m.coordinates.dat.data_ro.shape[0]), sp)
    monkeypatch.setitem(sys.modules, "firedrake", fk)

    mesh = _Mesh([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], [[0, 1, 2], [1, 3, 2]])
    sp = _Sp(mesh)
    return {
        "h": _F([10.0, 20.0, 30.0, 40.0], sp),
        "u": _F([[1.0, 0.0], [2.0, 0.0], [3.0, 1.0], [4.0, 1.0]], sp),
        "s": _F([100.0, 110.0, 120.0, 130.0], sp),
    }


def _run_icepack(mgr, monkeypatch, *, overrides=None, owner_tag="A"):
    """Stage a working copy with the Basic override, then simulate the run +
    structured export into the run's cache/outputs."""
    result = validate_icepack_config(overrides or {})
    assert result["ok"], result["errors"]
    staged = mgr.stage_example_for_run(
        source_example=str(mgr.example_dir.value),
        entrypoint="ice-shelf.ipynb",
        entrypoint_transform=(entrypoint_transform_for(result["normalized"])
                              if result["normalized"] else None),
        overrides=result["normalized"] or None,
    )
    run = mgr.register_run(RunInfo(
        id=f"ip-{owner_tag}", name=f"ice-shelf {owner_tag}", model="icepack",
        backend="spack", execution_mode="remote", status="completed",
        created=datetime.now(), jobid=f"j-{owner_tag}",
        metadata={"parameter_overrides": result["normalized"],
                  "working_copy": str(staged.path)},
    ))
    mgr.select_run(run.id)

    # the "run" would have executed inside the container; here we just run the
    # export against a fake final namespace, writing into the run's cache dir.
    ns = _fake_firedrake(monkeypatch)
    run_root = run.workspace_directory / "cache"
    (run_root / "outputs").mkdir(parents=True, exist_ok=True)
    meta = export(ns, str(run_root))
    assert meta["status"] == "ok", meta
    mgr.invalidate_result_package_cache(run.id)
    return staged, run


def test_full_icepack_offline_pipeline(canonical, tmp_path, monkeypatch):
    mgr = _mgr(USER_A, tmp_path / "ws", canonical)

    staged, run = _run_icepack(mgr, monkeypatch, overrides={"ice_temperature": 260})

    # 1. per-user working copy, canonical untouched, override applied to the copy
    assert staged.from_canonical and "ice-a" in str(staged.path)
    canon_nb = json.loads((canonical / "ice-shelf.ipynb").read_text())
    assert "255.15" in "".join(canon_nb["cells"][1]["source"])          # untouched
    copy_nb = json.loads((staged.path / "ice-shelf.ipynb").read_text())
    assert "Constant(260.0)" in "".join(copy_nb["cells"][1]["source"])   # overridden
    assert staged.provenance["md_overrides"] == {"ice_temperature": 260.0}

    # 2. structured ResultPackage discovered + readable
    pkg = mgr.result_package_for_run(run.id)
    assert pkg.status == "ok" and pkg.is_readable()
    assert set(pkg.available_fields()) == {"thickness", "velocity", "surface"}

    # 3. visualization discovery + deterministic render
    plots = mgr.recommended_plots_for_run(run.id)
    assert {p["field"] for p in plots} == {"thickness", "velocity", "surface"}
    r = mgr.render_run_plot(run.id, solution="icepack", field="thickness")
    assert r.ok and Path(r.path).is_file()
    rv = viz.render_field(pkg, "icepack", "velocity")
    assert rv.ok and "vector" in rv.caption

    # 4. downloads -- the results bundle is a real zip of outputs/
    import zipfile
    bundle = mgr.local_run_cache_dir() / "results_bundle.zip"
    mgr._make_zip(pkg.outputs, bundle)
    assert zipfile.is_zipfile(bundle)
    names = zipfile.ZipFile(bundle).namelist()
    assert any(n.endswith("metadata.json") for n in names)
    assert any("fields/icepack/thickness.h5" in n for n in names)
    # figures download: the deterministic render wrote a PNG under figures/
    figs = mgr.download_figures_for_run(run.id) if hasattr(
        mgr, "download_figures_for_run") else None
    assert (pkg.outputs / "figures").is_dir()


def test_two_users_are_isolated_for_icepack(canonical, tmp_path, monkeypatch):
    root = tmp_path / "ws"
    a = _mgr(USER_A, root, canonical)
    b = _mgr(USER_B, root, canonical)

    _run_icepack(a, monkeypatch, overrides={"ice_temperature": 258}, owner_tag="A")
    _run_icepack(b, monkeypatch, overrides={"num_timesteps": 50}, owner_tag="B")

    # working copies + run caches are under different owner roots
    assert a._owner_root != b._owner_root
    assert "ice-a" in str(a._working_root) and "ice-b" in str(b._working_root)
    assert not str(b._working_root).startswith(str(a._owner_root))

    # B cannot see A's run; each reads only its own package
    assert [r.id for r in b.refresh()] == ["ip-B"]
    assert [r.id for r in a.refresh()] == ["ip-A"]
    pa = a.result_package_for_run("ip-A")
    pb = b.result_package_for_run("ip-B")
    assert pa.is_readable() and pb.is_readable()
    assert pa.root != pb.root

    # B rendering A's run id is refused (not another user's data)
    assert b.render_run_plot("ip-A", solution="icepack", field="thickness").ok is False


def test_basic_override_fails_closed_when_the_example_does_not_expose_it(canonical, tmp_path):
    mgr = _mgr(USER_A, tmp_path / "ws", canonical)
    # this notebook has num_timesteps as a literal, but not e.g. a bed param;
    # an unsupported / unknown key is rejected at validation
    assert validate_icepack_config({"bed": 3.0})["ok"] is False
    # a valid key whose assignment is absent fails at transform time
    nb_no_temp = json.dumps({"cells": [{"cell_type": "code",
                             "source": ["num_timesteps = 5\n"]}], "metadata": {},
                             "nbformat": 4, "nbformat_minor": 5})
    from cryostack_src.models.icepack.parameters import IcepackOverrideError
    with pytest.raises(IcepackOverrideError):
        apply_overrides(nb_no_temp, {"ice_temperature": 260})
