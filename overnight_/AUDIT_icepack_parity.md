# ISSM ↔ Icepack parity audit (Agent B-1, read-only)

Produced by subagent `aa66a8ef02d414872` on 2026-09-01, reviewed by the
coordinating agent. Repo HEAD at audit time: `416da3d`. This is the verbatim
finding set the Phase-B implementation is built on; see `AGENT_TRAIL.md` §B for
the decisions taken from it.

## 15-row summary

| # | Area | ISSM | Icepack | Shared infra reusable | Gap type |
|---|---|---|---|---|---|
| 1 | Example discovery + metadata | `discover_issm_examples` + capability heuristics | `discover_icepack_examples` (notebooks/tutorials/how-to) | `icesheet_examples.py` merged/user/cache layer is model-neutral | PARTIAL (discovery done; curation ISSM-only) |
| 2 | Basic-mode config + safe overrides | `md_config.py` (291 L) + `issm_md_panel.py` | absent — panel hidden when `model!="issm"` | staging (`stage_example_for_run` transform/extra_files) is neutral | SCIENTIFIC-DIFFERENCE + ENGINEERING |
| 3 | Advanced editor / clone | `.m` editable | `.ipynb`,`.py` editable | `workspace/files.py`, `manager.py`, `editor.py` fully neutral | none (parity) |
| 4 | Dataset staging | `_stage_referenced_datasets` | same code path | `workspace/manager.py` datasets neutral | none (parity) |
| 5 | Local execution | absent | absent | — | ENGINEERING (+ scientific for Firedrake) |
| 6 | Remote / HPC execution | full | wired (spack + container blocks in `submission.py`) | `submission.py`, `remote/`, `execution/remote.py` dispatch on `model` | PARTIAL (Icepack paths untested) |
| 7 | Tested-container / backend selection | tested image maps ISSM | same image maps `icepack`; `with-icepack` wrapper | `stack/images.py`, `components.py`, `compat.py` component-aware | PARTIAL (registry ready; Icepack ref overrides blocked by Firedrake compat) |
| 8 | Slurm config + validation | neutral | neutral | `shared_slurm_resources_panel.py`, `shared_validation.py`, `models/*/slurm.py` | none (parity) |
| 9 | Run staging / submission / monitor / logs | full | same submission path | `submission.py`, `manager.py` run registration, `RemoteBackend` status | PARTIAL |
| 10 | Deterministic postprocessing | MATLAB neutral-export (314 L) | absent (`build_postprocess` identity; never invoked) | the `outputs/{...}` on-disk contract | SCIENTIFIC-DIFFERENCE |
| 11 | Structured ResultPackage | `results.py` reader (495 L) | absent | `manager.py:_result_reader_for` fallback | SCIENTIFIC-DIFFERENCE (fields) + ENGINEERING (scaffold) |
| 12 | Result discovery / viz / field-timestep | `visualization/issm.py` (319 L) | absent — `_visualizer_for("icepack")` → `None` | model-neutral panel shell in `frontend/.../visualization.py` | SCIENTIFIC-DIFFERENCE |
| 13 | Results / Figures downloads | works | works (same code) | `manager.py` `download_results`/`download_figures` model-agnostic | none (parity) |
| 14 | Provenance + run-history | full (manifest v2, stack `software`/`container`) | full — same manifest; `MODEL_COMPONENTS["icepack"]` resolved | `manifest.py`, `models.py`, `history.py`, `stack/provenance.py` neutral | none (parity) |
| 15 | Documentation + tests | extensive | "Experimental" stubs; **zero dedicated Icepack tests** | stack/compat/spack-env tests exercise `icepack` as data | ENGINEERING |

## Safe to generalize now
1. Example discovery — at parity; only curation heuristic + optional capability list.
2. ResultPackage scaffolding — neutral `find_outputs`, `status` states, `figures()`, `legacy_artifacts()`.
3. Run-history / provenance — nothing to do; already Icepack-aware.
4. Downloads — nothing to do.
5. Slurm config + validation — nothing to do.
6. Advanced editor + dataset staging — nothing to do (rename ISSM-shaped `entrypoint="runme.m"` default).
7. Docs — real Icepack getting-started / how-to.
8. Tests — `test_icepack_examples.py`, `test_icepack_adapter.py`, pipeline cases.
9. Gateway model-branch cleanup — capability queries instead of `if model == "issm"`.

## Needs a scientific decision
1. Icepack Basic-mode parameter set (temperature, fluidity A, friction C, model choice, dt/num_timesteps) + ranges + "scale a spatial field" semantics for a Firedrake `Function`.
2. Icepack config injection mechanism (no `solve(...)` anchor): convention file vs AST rewrite vs required parameter dict.
3. What "Local execution" means for Firedrake (`apptainer exec … with-icepack python` on the workstation is viable — no MATLAB/license).
4. Icepack release / solver-option policy (`compat.py` forbids every non-image Icepack version today).
5. Icepack postprocessing math — neutral Firedrake export (`CheckpointFile` vs per-field HDF5 + DOF/coordinate layout; transient = list of `Function`s).
6. Icepack field/timestep semantics — the `FieldInfo.location` (`scalar`/`nodal`/`elemental`) taxonomy does not map to Firedrake function spaces.
7. Icepack `recommended_plots` ordering (no `SolutionType`).
8. Cloud enablement for Icepack (`SUPPORTED_CLOUD_MODELS`, ECR `cryostack-icepack` image, cloud runner command).

## Genuine scientific differences to preserve
1. `md` model struct (MATLAB) vs Firedrake `Function`s (Python) — configuration, override injection, "what changed" provenance are per-model.
2. MATLAB runtime + license (`with-issm matlab`, `_matlab_container_env`, `srun`→`mpiexec` shim, cloud license preflight) vs pure Python — `_matlab_container_env` correctly returns `("","")` for Icepack.
3. Solver families — ISSM `Stressbalance/Transient/Thermal/…` with distinct `defaultoutputs`; Icepack diagnostic (`diagnostic_solve`) + prognostic (`prognostic_solve`) on `IceStream`/`IceShelf`/`HeatTransport3D`. Not a shared vocabulary.
4. Mesh + result representation — ISSM `md.mesh.{x,y,z,elements}` + struct-array-per-timestep + `md_final.mat`; Icepack `firedrake.Mesh` + function spaces + DOF vectors + `CheckpointFile`. The ISSM MATLAB postprocess and `visualization/issm.py` 2-D triangular `tripcolor` are correctly ISSM-isolated.
5. Example shape — ISSM directories with `runme.m` (`EXAMPLE_ENTRYPOINTS=("runme.m",)`); Icepack notebooks in `notebooks/{tutorials,how-to}` (`EXAMPLE_ENTRYPOINTS=()`, globs `*.ipynb`,`*.py`). Discovery layer already models this via the adapter's `example_runnable`.
6. Container component coupling — ISSM `COMPILED`/`OVERRIDE_NONE` (linked against PETSc/MPICH/MATLAB); Icepack `SOURCE_OVERRIDABLE` but `gated_by="firedrake"` (`ENVIRONMENT_SENSITIVE`). Real `components.py` facts.

## Gateway ISSM assumptions (for the B3 cleanup)
`icesheets_gateway.py`: `:587` always `build_issm_md_panel()`; `:653` cloud target default `runme.m`; `:1239` `if model=="issm": md_panel.set_example`; `:1481` md panel display toggle; `:1518` placeholder text branch; `:1531` "Model root" branch; `:1820` whole Basic-mode staged-override block `if model=="issm" and not test_mode`; `:1961` MATLAB-license preflight; `:2034` `--with-issm`/`--with-icepack`; `:2484` accordion title `"⚙️ ISSM configuration (Basic)"`; `:2731` `_spack_matlab_license`.
