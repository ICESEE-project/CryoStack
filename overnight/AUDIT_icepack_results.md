# AUDIT — Icepack/Firedrake result representation (Agent I-Results, read-only)

Subagent `aa41b24be3b73e690`, PASS 2, reviewed by the coordinator. Evidence:
the 12 upstream Icepack notebooks at `/home/bkyanjo3/icepack/notebooks/`
(icepack 1.1.0), the CryoLauncher Icepack adapter, and ICESEE's own Icepack
read-back code under `external/ICESEE/applications/icepack_model/`.
`icepack`/`firedrake` not importable here.

## 0. HEADLINE

**Run headless, the upstream tutorial notebooks produce essentially nothing on
disk.** Every "result" is a `firedrake.tripcolor`/matplotlib figure displayed
inline in Jupyter and never saved — no `plt.savefig`, no `firedrake.File`, no
`CheckpointFile` write anywhere in `tutorials/`. CryoLauncher runs them as
`jupyter nbconvert --to script` + `python file.py`
(`cryostack_src/models/submission.py:555,969`) so the figures are computed and
thrown away. `IcepackResultPackage.status` is `"empty"` for ~all tutorials
today; `"artifacts"` only for `how-to/02-checkpointing` (opaque `.h5`) and the
Larsen notebooks (input datasets, not results).

**A scientifically meaningful `cryostack.icepack.results` requires a
container-side export step** — `apptainer exec "$sif" with-icepack python
<exporter>` after the notebook script, pulling final `Function`s from the
namespace and serialising them. This mirrors ISSM, where `postprocess_icesee.m`
runs inside `with-issm matlab` (`submission.py:538`). There is no honest way to
get fields without executing Firedrake code in the container.

## 1. Cross-notebook field vocabulary

Recurring, physically-named, worth exporting: **thickness `h`** (m, CG2),
**velocity `u`** (m/yr, VectorCG2; scalar in 1-D), **surface `s`** (m a.s.l.,
CG2), **bed `b`** (m a.s.l., CG2), **accumulation `a`** (m/yr, CG2 — often a
`Constant`), **log_fluidity `θ`** (dimensionless, CG2 — inverse notebook 05
only), **damage `D`** (dimensionless, DG1 — notebook 02 epilogue only),
**strain_rate `ε` / membrane_stress `M`** (DG1 tensor — 02 epilogue only, never
plotted raw), **temperature `T`** (K, scalar `Constant`). Plus the **mesh** and
per-step scalar diagnostics (`dh_max` vs years).

Spaces: **CG2 nodal** dominates; **CG1** in `solver-fail`, `how-to/01`, phase-1
of `how-to/02`; **DG1 elemental** for D/ε/M; **GL-spectral extruded** for the
two hybrid notebooks; **1-D interval** for `04-x` and `06-xz`.

Viz primitives: `firedrake.tripcolor` (workhorse), `firedrake.streamplot`
(velocity, ice shelves), `firedrake.triplot` (mesh), `firedrake.plot` (1-D
line). No notebook `tripcolor`s a raw tensor.

Per-notebook table: see the full agent report in AGENT_TRAIL (kept there);
tier-1 2-D-triangular coverage = notebooks 01, 02, 03, 04-xy, 05, solver-fail,
how-to/01.

## 2. Firedrake serialization mechanisms

| Mechanism | Write needs FD | Read needs FD | Plain reader (h5py/numpy/mpl) | Lossy |
|---|---|---|---|---|
| `CheckpointFile` .h5 | yes | **yes** | no | no |
| VTK `.pvd`/`.vtu` | yes | no (meshio/pyvista) | yes | yes (linearised) |
| plain h5: DOF array + mesh *params* | yes | no, needs FD-version-matched mesh rebuild | fragile | no |
| **plain h5: DOF array + node coords + connectivity, same space** | yes | **no** | **yes, robustly** | optional (CG2->CG1 for display) |

`CheckpointFile` is Firedrake's current recommended checkpoint (process-count
independent) but has **no cross-version format guarantee** and is not readable
without Firedrake. The Voila Results kernel has no Firedrake, so a CheckpointFile
is archival only.

**ICESEE's working Icepack read-back** (`examples/synthetic_ice_stream/
read_results.ipynb`): flat `.dat.data` DOF vectors in plain HDF5, re-hydrated
into `firedrake.Function`s over a parametrically-reconstructed mesh, then
`firedrake.tripcolor`. Depends on same-Firedrake-build DOF ordering — works but
undocumented as a contract. `examples/idealized_pig/` uses `CheckpointFile`
end-to-end (`_icepack_model.py:94-102`, `getCheckPointVars.py`).

## 3. Container: `firedrake-icepack-*.def` under
`external/ICESEE/applications/icepack_model/icepack_utils/containers/` provides
firedrake + petsc + hdf5(-mpi) + h5py + icepack + pyrol + gmsh + numpy +
matplotlib. `CheckpointFile`, `VTKFile`, `h5py` all available.

## 4. RECOMMENDATION — minimal defensible `cryostack.icepack.results`

**Format: plain HDF5, DOF array + node coords + triangle connectivity, written
by a container-side exporter, in the EXACT ISSM on-disk shape**
(`cryostack_src/models/issm/postprocess.py:82-96` writes `/x /y /z /elements`;
`cryostack_src/visualization/issm.py:124-127` does
`matplotlib.tri.Triangulation(x,y,elements)` + `ax.tripcolor`). Reusing that
shape keeps `results_common.py` and the Results panel unchanged and gives a
zero-dependency, version-independent, deterministic reader.

**Tier 1 (safe, 7/12 notebooks):** `thickness`, `velocity` (-> `velocity_x`,
`velocity_y`), `surface`, `bed`, `accumulation` (if a `Function`), `log_fluidity`
(05), `damage` (02) — final state, 2-D triangular non-extruded mesh, CG2 -> CG1
interpolation for display (same as VTK; state `linearised: true` in metadata).
Hard-coded units from notebook labels: thickness=meters, surface/bed=meters
above sea level, velocity=meters/year, accumulation=meters/year,
damage/log_fluidity=dimensionless.

**metadata.json** schema v2: keep `figures`/`model_files`/`skipped`/`status`;
populate `fields[]` with `{name, components, rank, location, exported_space,
source_space, linearised, units, units_source, mesh, path, timestep,
source_example, source_variable, model_class}` + a top-level `mesh` block.

**Plain-Python reader CAN build a tripcolor-equivalent** for tier-1 fields:
`matplotlib.tri.Triangulation(x,y,elements)` + `ax.tripcolor(triang, values)` —
`visualization/issm.py` is a drop-in; only the reader + field/units vocabulary
differ. Vectors -> magnitude map + quiver. 1-D -> `ax.plot`.

## 5. Safe to implement now vs OWNER DECISION

**Safe now:**
1. Add `.msh` to the collector's native-suffix list (`postprocess.py:29-30`,
   `results_common.py:27-30`).
2. Container-side exporter `cryostack_icepack_export.py` + a second
   `apptainer exec ... with-icepack python` line after the run block, non-fatal,
   guarded `model=="icepack" and not test_mode`.
3. Exporter tier-1 logic (allow-list of var names, CG1 interpolation, write ISSM
   h5 shape + real `fields[]`).
4. `IcepackResultPackage.is_readable()` -> True when `fields[]` non-empty;
   `available_fields()`, `load_field()`, `load_mesh()` reusing `results_common`.
5. `cryostack_src/visualization/icepack.py` — thin adapter over
   `visualization/issm.py` triangulation renderer; deterministic PNG cache.
6. Archive any run-written `CheckpointFile` into `outputs/model/` (already
   happens), note as `native_checkpoint`.
7. Tests mirroring `test_icepack_results.py` (h5py fixtures; firedrake mocked).

**OWNER DECISION (D-1..D-8):**
- D-1 panel shape: does the Results panel require non-empty `solutions[]`
  (ISSM-shaped selector) or can it show a flat field list?
- D-2 CG2 linearisation: accept CG1-for-display, or also ship raw CG2 arrays for
  a future Firedrake reader?
- D-3 which variables + transient vs final (notebooks give no save cadence;
  final-state snapshot is probably adequate for spin-ups).
- D-4 1-D (`04-x`, `06-xz`) and extruded 3-D (`06-xyz`, needs `depth_average`).
- D-5 tensor + derived stress fields (`ε`, `M`, `τ`).
- D-6 inverse (`05`): capture loss/regularization history?
- D-7 namespace extraction: `runpy.run_path` + globals-scrape (fragile if a
  notebook wraps code in a function, e.g. `04-x` `run_simulation`,
  `how-to/02`) vs re-import + re-solve (deterministic but doubles cost; `05` is
  30-45 min).
- D-8 DOF-order contract / Firedrake version pin if raw CG2 arrays are shipped.

## Coordinator note
The exporter is Firedrake code that CANNOT be validated on this box (no
firedrake, no container, no HPC). It will be implemented with the tier-1 logic,
structurally unit-tested with firedrake/h5py mocked, wired non-fatally, and
flagged for an HPC validation pass (morning). D-1..D-8 are morning checkpoints;
the implemented subset uses the conservative reading of each.
