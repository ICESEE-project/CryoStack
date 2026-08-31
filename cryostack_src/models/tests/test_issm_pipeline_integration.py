"""Commit 6 -- application-layer validation of the ISSM pipeline against real
solver / result families.

No MATLAB is available in this environment, so the ISSM *execution* step cannot
run here. Everything on either side of it is exercised end to end:

    discover example -> run target -> solver detect -> Basic/Advanced stage
      -> [ ISSM executes ]  (validated structurally, not run)
      -> neutral exporter contract -> ResultPackage discovery
      -> solution / field / timestep -> deterministic render

Fixtures use real ISSM field names (from ``src/m/classes/*.m`` defaultoutputs)
and real ``runme.m`` shapes, one per solver family that is materially different.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np

from cryostack_src.models.issm import (
    build_md_override_script, build_postprocess, choose_run_target,
    detect_solvers, example_runnable, inject_override_step, order_run_targets,
    validate_md_config,
)
from cryostack_src.models.issm.md_config import OVERRIDE_SCRIPT_NAME
from cryostack_src.models.issm.results import discover_results
from cryostack_src.visualization import issm as viz

h5py = pytest.importorskip("h5py")


# ── real runme.m shapes (verbatim from the ISSM example suite) ────────────
RUNME_SQUAREICESHELF = (
    "md=model;\n"
    "md=triangle(md,'DomainOutline.exp',100000);\n"
    "md=setmask(md,'all','');\n"
    "md=parameterize(md,'Square.par');\n"
    "md=setflowequation(md,'SSA','all');\n"
    "md.cluster=generic('name',oshostname,'np',2);\n"
    "md=solve(md,'Stressbalance');\n"
)

RUNME_TRANSIENT = (  # Greenland step 4 shape
    "steps=[1:4];\n"
    "if any(steps==4)\n"
    "\tmd = loadmodel('./Models/Greenland.Control_drag');\n"
    "\tmd.timestepping.time_step=0.2;\n"
    "\tmd.timestepping.final_time=20;\n"
    "\tmd.transient.requested_outputs={'IceVolume','TotalSmb','SmbMassBalance'};\n"
    "\tmd.cluster=generic('name',oshostname,'np',2);\n"
    "\tmd=solve(md,'Transient');\n"
    "\tsave ./Models/Greenland.Transient md;\n"
    "end\n"
)

RUNME_HYDROLOGY_SHAKTI = (  # shakti step 3 shape -- transient hydrology
    "steps=[1:3];\n"
    "if any(steps==3)\n"
    "\tmd=loadmodel('MoulinParam');\n"
    "\tmd.transient=deactivateall(md.transient);\n"
    "\tmd.transient.ishydrology=1;\n"
    "\tmd.cluster=generic('np',2);\n"
    "\tmd.timestepping.time_step=3600/md.constants.yts;\n"
    "\tmd.timestepping.final_time=30/365;\n"
    "\tmd=solve(md,'Transient');\n"
    "end\n"
)

RUNME_ESA = "md=loadmodel('Models/esa');\nmd=solve(md,'Esa');\n"
RUNME_HELHEIM_ABBREV = "md=loadmodel('x');\nmd=solve(md,'sb');\n"
RUNME_SLRGRACE_ABBREV = "md=loadmodel('x');\nmd=solve(md,'tr');\n"


# ── 1. discovery + run target + solver detection ─────────────────────────
def test_runme_is_a_runnable_example(tmp_path):
    ex = tmp_path / "SquareIceShelf"
    ex.mkdir()
    (ex / "runme.m").write_text(RUNME_SQUAREICESHELF)
    (ex / "Square.par").write_text("% params\n")
    (ex / "DomainOutline.exp").write_text("## dummy\n")
    assert example_runnable(ex) is True
    assert example_runnable(tmp_path / "nope") is False


def test_run_target_selection_prefers_runme():
    names = ["Square.par", "runme.m", "PigRegion.m", "DomainOutline.exp"]
    ordered = order_run_targets(names)
    assert ordered[0].endswith((".m", ".py", ".ipynb"))
    assert choose_run_target(names) == "runme.m"


@pytest.mark.parametrize("text,expected", [
    (RUNME_SQUAREICESHELF, ("stressbalance",)),
    (RUNME_TRANSIENT, ("transient",)),
    (RUNME_HYDROLOGY_SHAKTI, ("transient",)),
    (RUNME_ESA, ("esa",)),
    (RUNME_HELHEIM_ABBREV, ("stressbalance",)),
    (RUNME_SLRGRACE_ABBREV, ("transient",)),
])
def test_solver_detection_matches_issm_solve_strings(text, expected):
    assert detect_solvers(text) == expected


# ── 2. Basic mode changes the actual script, canonical stays intact ──────
def test_basic_mode_injects_before_solve_and_leaves_canonical_intact():
    original = RUNME_SQUAREICESHELF
    v = validate_md_config({"stressbalance.maxiter": 40, "friction.coefficient": 1.5},
                           solvers=("stressbalance",))
    assert v.ok, v.errors
    override = build_md_override_script(v.normalized)
    assert "md.stressbalance.maxiter = 40;" in override
    assert "md.friction.coefficient = md.friction.coefficient .* 1.5;" in override

    injected = inject_override_step(original, script_name=OVERRIDE_SCRIPT_NAME)
    lines = injected.splitlines()
    solve_idx = next(i for i, l in enumerate(lines) if l.strip().startswith("md=solve("))
    assert lines[solve_idx - 1].strip() == f"run('{OVERRIDE_SCRIPT_NAME}');"
    assert original == RUNME_SQUAREICESHELF                      # untouched
    # disabled again -> no override, original restored
    assert inject_override_step(original, script_name=OVERRIDE_SCRIPT_NAME) != original
    v_off = validate_md_config({}, solvers=("stressbalance",))
    assert v_off.normalized == {}


def test_basic_mode_injects_inside_guarded_multistep_block():
    injected = inject_override_step(RUNME_HYDROLOGY_SHAKTI)
    lines = injected.splitlines()
    i = next(i for i, l in enumerate(lines) if "solve(md,'Transient')" in l)
    assert lines[i - 1].strip() == f"run('{OVERRIDE_SCRIPT_NAME}');"
    assert lines[i - 1].startswith("\t")                        # keeps block indent


def test_basic_mode_injection_is_idempotent():
    once = inject_override_step(RUNME_TRANSIENT)
    assert inject_override_step(once) == once


# ── 3. exporter contract stays discovery-driven ─────────────────────────
def test_exporter_is_discovery_driven_not_family_hardcoded():
    script = build_postprocess()
    # iterates whatever md.results actually contains
    assert "fieldnames(md.results)" in script
    assert "for cs_si = 1:numel(cs_sol_names)" in script
    # no per-family branching in the exporter
    for family in ("StressbalanceSolution", "TransientSolution", "ThermalSolution",
                   "EsaSolution", "HydrologySolution"):
        assert family not in script
    # status markers + skip-not-crash + no fabricated units
    for marker in ("'no-model'", "'no-results'", "cs_skipped", "cs_MARKERS"):
        assert marker in script
    assert "'units', " not in script and "'units',[" not in script   # never emitted
    assert "metadata.json" in script and "mesh.h5" in script and "md_final.mat" in script


def test_exporter_recovers_run_dir_after_clear_all():
    """A runme.m that calls `clear all` must not misdirect the export."""
    assert "getenv('ICESEE_RUN_DIR')" in build_postprocess()          # env fallback
    from cryostack_src.models import submission
    src = Path(submission.__file__).read_text()
    assert src.count("setenv('ICESEE_RUN_DIR'") >= 4                   # every matlab -r


# ── 4. per-family: exported package -> discovery -> render ──────────────
def _write(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as fh:
        for k, v in data.items():
            fh.create_dataset(k, data=np.asarray(v))


NV, NE = 8, 6
ELEMENTS = np.array([[1, 2, 3], [2, 3, 4], [3, 4, 5], [4, 5, 6], [5, 6, 7], [6, 7, 8]],
                    dtype="int64")


def _mesh(outputs: Path):
    _write(outputs / "mesh" / "mesh.h5", {
        "/x": np.linspace(0, 1000, NV), "/y": np.linspace(0, 500, NV),
        "/elements": ELEMENTS})


def _mesh_meta():
    return {"path": "mesh/mesh.h5", "numberofvertices": NV, "numberofelements": NE,
            "dimension": 2, "element_columns": 3,
            "connectivity_indexing": "1-based", "has_z": False}


def _base_meta(solutions):
    return {"schema": "cryostack.issm.results", "version": 1, "model": "issm",
            "status": "ok", "mesh": _mesh_meta(), "solutions": solutions}


def _finish(outputs: Path, meta: dict):
    (outputs / "model").mkdir(parents=True, exist_ok=True)
    (outputs / "model" / "md_final.mat").write_bytes(b"stub")
    (outputs / "figures").mkdir(parents=True, exist_ok=True)
    (outputs / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")


def _render_all(pkg):
    """Render every recommended plot; each must succeed or give a reason."""
    outcomes = []
    for rec in pkg.recommended_plots():
        if rec["kind"] == "timeseries":
            r = viz.render_timeseries(pkg, rec["solution"], rec["field"])
        else:
            r = viz.render_field(pkg, rec["solution"], rec["field"],
                                 timestep=rec.get("timestep"))
        assert r.ok or r.reason, rec
        outcomes.append(r)
    return outcomes


def test_family_stressbalance(tmp_path):
    outputs = tmp_path / "run" / "outputs"
    _mesh(outputs)
    _write(outputs / "fields" / "StressbalanceSolution" / "Vel.h5",
           {"/values": np.linspace(1, 100, NV)})
    _write(outputs / "fields" / "StressbalanceSolution" / "Vx.h5",
           {"/values": np.linspace(-5, 5, NV)})
    _write(outputs / "fields" / "StressbalanceSolution" / "Pressure.h5",
           {"/values": np.linspace(0, 1e6, NE)})
    _finish(outputs, _base_meta([{
        "name": "StressbalanceSolution", "transient": False, "timesteps": 1,
        "time": [], "step": [], "skipped": [
            {"name": "SolutionType", "reason": "string field is metadata", "kind": "char"}],
        "fields": [
            {"name": "Vx", "location": "nodal", "shape": [NV], "dtype": "float64",
             "path": "fields/StressbalanceSolution/Vx.h5"},
            {"name": "Vel", "location": "nodal", "shape": [NV], "dtype": "float64",
             "path": "fields/StressbalanceSolution/Vel.h5"},
            {"name": "Pressure", "location": "elemental", "shape": [NE], "dtype": "float64",
             "path": "fields/StressbalanceSolution/Pressure.h5"},
        ]}]))
    pkg = discover_results(tmp_path / "run")
    assert pkg.available_solutions() == ["StressbalanceSolution"]
    assert pkg.available_fields("StressbalanceSolution") == ["Vel", "Vx", "Pressure"]
    assert viz.render_field(pkg, "StressbalanceSolution", "Vel").ok           # nodal
    assert viz.render_field(pkg, "StressbalanceSolution", "Pressure").ok      # elemental
    assert all(r.ok for r in _render_all(pkg))


def test_family_transient_multistep_with_scalar_diagnostics(tmp_path):
    outputs = tmp_path / "run" / "outputs"
    _mesh(outputs)
    nsteps = 5
    _write(outputs / "fields" / "TransientSolution" / "time.h5",
           {"/time": np.linspace(0, 20, nsteps), "/step": np.arange(1, nsteps + 1)})
    _write(outputs / "fields" / "TransientSolution" / "Vel.h5",
           {"/values": np.vstack([np.linspace(1, 50, NV) * (s + 1) for s in range(nsteps)])})
    _write(outputs / "fields" / "TransientSolution" / "Thickness.h5",
           {"/values": np.vstack([np.full(NV, 500.0 - 3 * s) for s in range(nsteps)])})
    _write(outputs / "fields" / "TransientSolution" / "IceVolume.h5",
           {"/values": np.linspace(1e10, 9e9, nsteps).reshape(-1, 1)})
    # SmbMassBalance only from step 2 on
    smb = np.vstack([np.full(NV, np.nan)] * 2 + [np.full(NV, 0.3)] * (nsteps - 2))
    _write(outputs / "fields" / "TransientSolution" / "SmbMassBalance.h5", {"/values": smb})
    _finish(outputs, _base_meta([{
        "name": "TransientSolution", "transient": True, "timesteps": nsteps,
        "time": list(np.linspace(0, 20, nsteps)), "step": list(range(1, nsteps + 1)),
        "skipped": [],
        "fields": [
            {"name": "Vel", "location": "nodal", "shape": [nsteps, NV], "dtype": "float64",
             "path": "fields/TransientSolution/Vel.h5", "available_timesteps": list(range(nsteps))},
            {"name": "Thickness", "location": "nodal", "shape": [nsteps, NV], "dtype": "float64",
             "path": "fields/TransientSolution/Thickness.h5", "available_timesteps": list(range(nsteps))},
            {"name": "SmbMassBalance", "location": "nodal", "shape": [nsteps, NV], "dtype": "float64",
             "path": "fields/TransientSolution/SmbMassBalance.h5", "available_timesteps": [2, 3, 4]},
            {"name": "IceVolume", "location": "scalar", "shape": [nsteps], "dtype": "float64",
             "path": "fields/TransientSolution/IceVolume.h5", "available_timesteps": list(range(nsteps))},
        ]}]))
    pkg = discover_results(tmp_path / "run")
    # final-timestep default
    r_final = viz.render_field(pkg, "TransientSolution", "Vel")
    assert r_final.ok and r_final.timestep == 4
    assert r_final.path.name == "TransientSolution_Vel_t004.png"
    # arbitrary timestep
    assert viz.render_field(pkg, "TransientSolution", "Vel", timestep=1).timestep == 1
    # missing at some timesteps -> default = last available, early step rejected
    r_smb = viz.render_field(pkg, "TransientSolution", "SmbMassBalance")
    assert r_smb.ok and r_smb.timestep == 4
    assert not viz.render_field(pkg, "TransientSolution", "SmbMassBalance", timestep=0).ok
    # scalar diagnostic -> time series
    r_ts = viz.render_field(pkg, "TransientSolution", "IceVolume")
    assert r_ts.ok and r_ts.kind == "timeseries"
    assert all(r.ok for r in _render_all(pkg))


def test_family_thermal(tmp_path):
    outputs = tmp_path / "run" / "outputs"
    _mesh(outputs)
    _write(outputs / "fields" / "ThermalSolution" / "Temperature.h5",
           {"/values": np.linspace(240, 273, NV)})
    _write(outputs / "fields" / "ThermalSolution" / "BasalforcingsGroundediceMeltingRate.h5",
           {"/values": np.linspace(0, 0.02, NV)})
    _finish(outputs, _base_meta([{
        "name": "ThermalSolution", "transient": False, "timesteps": 1,
        "time": [], "step": [], "skipped": [],
        "fields": [
            {"name": "Temperature", "location": "nodal", "shape": [NV], "dtype": "float64",
             "path": "fields/ThermalSolution/Temperature.h5"},
            {"name": "BasalforcingsGroundediceMeltingRate", "location": "nodal",
             "shape": [NV], "dtype": "float64",
             "path": "fields/ThermalSolution/BasalforcingsGroundediceMeltingRate.h5"},
        ]}]))
    pkg = discover_results(tmp_path / "run")
    assert pkg.available_fields("ThermalSolution")[0] == "Temperature"
    assert all(r.ok for r in _render_all(pkg))


def test_family_esa_materially_different(tmp_path):
    outputs = tmp_path / "run" / "outputs"
    _mesh(outputs)
    _write(outputs / "fields" / "EsaSolution" / "EsaUmotion.h5",
           {"/values": np.linspace(-1e-3, 1e-3, NV)})
    _finish(outputs, _base_meta([{
        "name": "EsaSolution", "transient": False, "timesteps": 1,
        "time": [], "step": [],
        "skipped": [{"name": "LoveNumbers", "reason": "struct-valued field is not supported",
                     "kind": "struct"}],
        "fields": [
            {"name": "EsaUmotion", "location": "nodal", "shape": [NV], "dtype": "float64",
             "path": "fields/EsaSolution/EsaUmotion.h5"},
        ]}]))
    pkg = discover_results(tmp_path / "run")
    assert pkg.available_solutions() == ["EsaSolution"]
    assert [s.name for s in pkg.solution("EsaSolution").skipped] == ["LoveNumbers"]
    assert viz.render_field(pkg, "EsaSolution", "EsaUmotion").ok


def test_family_hydrology_shakti_mixed_locations_and_nan(tmp_path):
    outputs = tmp_path / "run" / "outputs"
    _mesh(outputs)
    nsteps = 3
    head = np.vstack([np.full(NV, 50.0 + 5 * s) for s in range(nsteps)])
    head[:, -2:] = np.nan                                        # masked outflow nodes
    gap = np.vstack([np.full(NE, 0.01 + 0.001 * s) for s in range(nsteps)])
    _write(outputs / "fields" / "TransientSolution" / "time.h5",
           {"/time": np.linspace(0, 0.08, nsteps)})
    _write(outputs / "fields" / "TransientSolution" / "HydrologyHead.h5", {"/values": head})
    _write(outputs / "fields" / "TransientSolution" / "HydrologyGapHeight.h5", {"/values": gap})
    _write(outputs / "fields" / "TransientSolution" / "EffectivePressure.h5",
           {"/values": np.vstack([np.linspace(0, 1e5, NV) for _ in range(nsteps)])})
    _finish(outputs, _base_meta([{
        "name": "TransientSolution", "transient": True, "timesteps": nsteps,
        "time": list(np.linspace(0, 0.08, nsteps)), "step": [1, 2, 3], "skipped": [],
        "fields": [
            {"name": "EffectivePressure", "location": "nodal", "shape": [nsteps, NV],
             "dtype": "float64", "path": "fields/TransientSolution/EffectivePressure.h5",
             "available_timesteps": [0, 1, 2]},
            {"name": "HydrologyHead", "location": "nodal", "shape": [nsteps, NV],
             "dtype": "float64", "path": "fields/TransientSolution/HydrologyHead.h5",
             "available_timesteps": [0, 1, 2]},
            {"name": "HydrologyGapHeight", "location": "elemental", "shape": [nsteps, NE],
             "dtype": "float64", "path": "fields/TransientSolution/HydrologyGapHeight.h5",
             "available_timesteps": [0, 1, 2]},
        ]}]))
    pkg = discover_results(tmp_path / "run")
    # hydrology fields surface via preference, then metadata order
    assert pkg.available_fields("TransientSolution")[:3] == \
        ["EffectivePressure", "HydrologyHead", "HydrologyGapHeight"]
    # nodal field with NaN-masked nodes still renders, and says so
    r_head = viz.render_field(pkg, "TransientSolution", "HydrologyHead")
    assert r_head.ok and "masked" in r_head.caption
    # elemental transient renders
    assert viz.render_field(pkg, "TransientSolution", "HydrologyGapHeight").ok
    assert all(r.ok for r in _render_all(pkg))


# ── 5. degenerate inputs never break the Results path ──────────────────
def test_all_nan_field_gives_reason_not_crash(tmp_path):
    outputs = tmp_path / "run" / "outputs"
    _mesh(outputs)
    _write(outputs / "fields" / "StressbalanceSolution" / "Vel.h5",
           {"/values": np.full(NV, np.nan)})
    _finish(outputs, _base_meta([{
        "name": "StressbalanceSolution", "transient": False, "timesteps": 1,
        "time": [], "step": [], "skipped": [],
        "fields": [{"name": "Vel", "location": "nodal", "shape": [NV], "dtype": "float64",
                    "path": "fields/StressbalanceSolution/Vel.h5"}]}]))
    pkg = discover_results(tmp_path / "run")
    r = viz.render_field(pkg, "StressbalanceSolution", "Vel")
    assert not r.ok and "non-finite" in r.reason


def test_constant_field_renders(tmp_path):
    outputs = tmp_path / "run" / "outputs"
    _mesh(outputs)
    _write(outputs / "fields" / "StressbalanceSolution" / "Vel.h5",
           {"/values": np.full(NV, 3.0)})
    _finish(outputs, _base_meta([{
        "name": "StressbalanceSolution", "transient": False, "timesteps": 1,
        "time": [], "step": [], "skipped": [],
        "fields": [{"name": "Vel", "location": "nodal", "shape": [NV], "dtype": "float64",
                    "path": "fields/StressbalanceSolution/Vel.h5"}]}]))
    pkg = discover_results(tmp_path / "run")
    assert viz.render_field(pkg, "StressbalanceSolution", "Vel").ok
