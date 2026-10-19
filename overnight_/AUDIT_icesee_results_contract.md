# AUDIT — a future `cryostack.icesee.results` contract (PASS 4, task 12)

Scope: ICESEE data-assimilation (EnKF family) framework vendored at
`external/ICESEE/`. Read-only. All claims traced to `file:line`; where a thing
does not exist it is called out. Nothing here is inferred from documentation or
naming alone.

## 0. Executive summary

- ICESEE has **no result-package contract, no manifest, no run-directory
  abstraction, no provenance record**. It writes a loose pile of HDF5 files
  (plus transient Zarr) into a single, reused, non-timestamped directory named
  by the `data_path` param (default literal `_modelrun_datasets`), located
  under the current working directory (the example folder).
- The **only run-identity artifact** is `icesee_fingerprint()` — a 5-key SHA1
  over `(model_name, nd, nt, Nens, base_seed)`, stamped as an HDF5 attribute on
  `true_nurged_states.h5`, and only in full-parallel mode.
- Scientifically meaningful outputs that genuinely exist and are persisted:
  **ensemble trajectory** `(nd, Nens, nt+1)`, **ensemble mean** `(nd, nt+1)`,
  **true state**, **nurged (background) state**, **synthetic observations +
  obs-error covariance R**, **observation schedule**, **observation operator
  H**.
- DA diagnostics **computed and persisted**: ensemble mean only. RMSE,
  ensemble spread, innovations, analysis increments, analysis-error covariance,
  Kalman gain, rank histograms, KL divergence — **none are persisted**; most
  are not even computed at runtime (RMSE is a dead method; increments /
  covariances have their `return` statements commented out).
- Timing/wallclock **is computed** but only logged to `icesee_timing.log` /
  stderr, never written to a results file (and in serial mode the timing block
  is fully commented out).
- `cryostack_src/` has **zero** ICESEE-DA result handling. Every `icesee` hit
  in `cryostack_src/` refers to ICESEE-Container / ICESEE-Spack /
  ICESEE-project branding, not the DA framework. Only `issm` and `icepack` are
  registered models with result contracts
  (`cryostack_src/models/capabilities.py:75-101`).

---

## 1. Output files ICESEE actually writes

Directory base: `data_path` param, default the literal string
`_modelrun_datasets` (`config/_utility_imports.py` — `--data_path` default;
`enkf_params.get('data_path', '_modelrun_datasets')`). Created with
`os.makedirs(..., exist_ok=True)` in
`src/run_model_da/icesee_da_full_parallel.py:107-109`,
`icesee_da_partial_parallel.py:92-94,247-249`, `config/_utility_imports.py`.

### 1a. `<data_path>/icesee_ensemble_data.h5` — the main result (serial + partial + finalized full)

| dataset | shape | dtype | writer |
|---|---|---|---|
| `ensemble` | `(nd, Nens, nt+1)` | f8 | created `src/EnKF/_ensemble_initialization.py:137-142`; filled per step `src/run_model_da/icesee_da_serial.py:524-525` |
| `ensemble_mean` | `(nd, nt+1)` | f8 | created `_ensemble_initialization.py:144`; filled `icesee_da_serial.py:512-513` |

Full-parallel builds the same file via `finalize_stack(...)`
(`icesee_da_full_parallel.py:663-665`) → `consolidate_h5()` in
`src/utils/tools.py:98-166`: dataset `ensemble` `(nd, nens, nt)`
(`tools.py:130-135`), dataset `ensemble_mean` `(nd, nt)` via `np.nanmean`
(`tools.py:136-141,164`), **root attrs** `{nd, nens, nt, stack_type:
"materialized", source_dir: <abspath>, dataset_name}` (`tools.py:142-147`).
VDS variant `build_vds()` `tools.py:53-95` sets `stack_type: "VDS"`.

Verified on disk —
`applications/lorenz_model/examples/lorenz96/_modelrun_datasets/icesee_ensemble_data.h5`:
`ensemble (3, 30, 1001) f8`, `ensemble_mean (3, 1001) f8`, no attrs (serial run
does not set the stack attrs).

### 1b. `<data_path>/icesee_enkf_ens_XXXX.h5` — per-timestep ensemble slices (full-parallel only)

- dataset `states` `(nd, Nens)` —
  `src/parallelization/EnKF_parallel_io.py:174-181,214-223,255-261`
- filename pattern `icesee_enkf_ens_(\d+)\.h5` (`tools.py:22`), zero-padded 4
  digits (`icesee_da_full_parallel.py:392`)
- consumed by `finalize_stack` / `scripts/data_management/stack_icesee_data.py`

### 1c. `<data_path>/icesee_enkf_mean.h5` — parallel ensemble-mean file

- dataset `mean` `(nd, nt)` — `EnKF_parallel_io.py:408-432,1221-1230`

### 1d. `<data_path>/true_nurged_states.h5` — truth + background

- `true_state` `(nd, nt+1)` — `src/EnKF/_generate_true_wrong_state.py:91-94`;
  parallel `src/parallelization/_mpi_generate_true_wrong_state.py:178-179,390-391`
- `nurged_state` `(nd, nt+1)` — `_generate_true_wrong_state.py:108-111`;
  parallel `:211-212,423-424`
- only written when `generate_true_state` / `generate_nurged_state` params are
  truthy (`_generate_true_wrong_state.py:62-63`)
- **full-parallel** stamps attrs `icesee_fingerprint=<sha1>`,
  `dataset_name_true="true_state"`, `dataset_name_nurged="nurged_state"`
  (`icesee_da_full_parallel.py:239-243` → `mark_h5_with_fingerprint`
  `tools.py:973-979`)
- Verified on disk: `true_state (3, 1001)`, `nurged_state (3, 1001)`, no attrs
  (serial).

### 1e. `<data_path>/synthetic_obs.h5` — synthetic observations

- `hu_obs` `(obs_state_dim, num_obs_instants)` —
  `src/EnKF/_generate_synthetic_observations.py:58-59`; parallel
  `EnKF_parallel_io.py:735-739`
- `R` — obs-error covariance — `_generate_synthetic_observations.py:60`;
  parallel `EnKF_parallel_io.py:740-744` (`error_R`)
- Verified on disk: `hu_obs (3, 10)`, `R (10, 3)`.

### 1f. `<data_path>/H_matrix.h5` — observation operator

- datasets `H_matrix`, `obs_indices` (`i8`) — `EnKF_parallel_io.py:894-903`

### 1g. `<data_path>/ensemble_before_analysis_step_XXXX.h5` — pre-analysis forecast snapshot

- `src/parallelization/_parallel_i_o.py:471-472,761`;
  `icesee_da_partial_parallel.py:479`

### 1h. `<data_path>/mesh_idxy_0.h5` — mesh index mapping

- `EnKF_parallel_io.py:665-667`

### 1i. Transient Zarr stores (full-parallel; deleted at end)

`ensemble_initialization.zarr`, `synthetic_observations.zarr`, `error_R.zarr`,
`H_matrix.zarr`, `States_local_<rank>.zarr`. Cleanup:
`icesee_da_full_parallel.py:666-674`.

### 1j. `results/{filter_type}-{model}.h5` — top-level "results" file (metadata only, today)

- `output_dir = "results"` (relative to CWD), `output_file =
  f"{output_dir}/{filter_type}-{model}.h5"` — `src/utils/tools.py:237-238`
- writer `save_arrays_to_h5()` `tools.py:223-256`: creates `results/`, **deletes
  any existing file** (`tools.py:247-249`), writes each kwarg as a gzip dataset
- **In every current code path only the `nofilter=True` call runs**, so
  `filter_type` is forced to `"true-wrong"` (`tools.py:302`) and the file is
  `results/true-wrong-{model}.h5` containing exactly: `t` `(nt+1,)`, `b_io`
  `[b_in,b_out]`, `Lxy` `[Lx,Ly]`, `nxy` `[nx,ny]`, `obs_max_time` `(1,)`,
  `obs_index`, `run_mode` `[execution_flag]` (`icesee_da_serial.py:560-571`).
- The second `save_all_data(...)` that would write `ensemble_vec_full`,
  `ensemble_vec_mean`, `ensemble_bg` is **commented out**
  (`icesee_da_serial.py:539-558`).
- Verified on disk:
  `applications/lorenz_model/examples/lorenz96/results/true-wrong-lorenz.h5`
  contains only `Lxy, b_io, nxy, obs_index, obs_max_time, run_mode, t`.

### 1k. `<data_path>/_checkpoints/icesee_ckpt.json` — restart checkpoint (full-parallel)

- `tools.py:858-877`; payload keys `last_done_k, km, nt, nd, nens,
  dataset_dir, timestamp (time.time() float), base_seed`
  (`icesee_da_full_parallel.py:598-607`)

### 1l. `icesee_timing.log` — timing table (text, not machine-readable)

- `logging.FileHandler("icesee_timing.log")` — `tools.py:664-676`; rows from
  `display_timing_verbose` `tools.py:687-764`

### 1m. `figures/*.png`

- only via helper `icesee_savefig(...)` → `Path("figures").mkdir(...)` —
  `tools.py:1050-1078`. Called from notebooks / example post-processing, **not
  from the DA core**.

### 1n. `scripts/data_management/post_processing.py` (optional, manual)

- writes `<data_path>/icesee_ensemble_dataset.h5` with `ensemble_data`
  `(nd, nens, nt)` + `time_indices`.

**Formats:** HDF5 (h5py) everywhere; Zarr for transient parallel scratch; JSON
for the checkpoint; plain-text log for timing; PNG for figures. **No** NetCDF,
xarray, `.mat`, pickle, `.npy`/`.npz` in the DA core.

---

## 2. DA diagnostics that genuinely exist

| diagnostic | computed? | persisted? | evidence |
|---|---|---|---|
| ensemble mean | yes | **yes** (`ensemble_mean`) | `icesee_da_serial.py:513`; `tools.py:93,164`; `EnKF_parallel_io.py:408-432` |
| full ensemble over time | yes | **yes** (`ensemble` / `states`) | `icesee_da_serial.py:524-525`; `EnKF_parallel_io.py:174-181` |
| true state | yes | **yes** (`true_state`) | `_generate_true_wrong_state.py:91-94` |
| nurged / background state | yes | **yes** (`nurged_state`) | `_generate_true_wrong_state.py:108-111` |
| synthetic observations | yes | **yes** (`hu_obs`) | `_generate_synthetic_observations.py:58-59` |
| obs-error covariance R | yes | **yes** (`R` / `error_R`) | `_generate_synthetic_observations.py:60` |
| observation operator H | yes | **yes** (`H_matrix`, `obs_indices`) | `EnKF_parallel_io.py:894-903` |
| observation schedule (`obs_index`, `obs_max_time`, freq) | yes | **yes** | `icesee_da_serial.py:568` |
| pre-analysis (forecast) ensemble snapshot | yes (full/partial) | **yes** (`ensemble_before_analysis_step_XXXX.h5`) | `_parallel_i_o.py:471-472` |
| RMSE (truth vs estimate) | **no** — `rmse()` defined, **zero callers** | no | def only: `src/EnKF/_localization_inflation.py:433-442` |
| ensemble spread / std as a diagnostic | **no** — `np.std` only in commented code | no | `_parallel_i_o.py:128-129` (commented) |
| innovation `d = y − H x` | transient inside the update, **not returned/persisted** | no | `_mpi_analysis_functions.py:350` (comment) |
| analysis increment | **no** — `return ensemble_increment` commented out | no | `EnKF.py:514-521` |
| analysis-error covariance | **no** — `return ..., analysis_error_cov` commented out (all four filters) | no | `EnKF.py:401-408,428-448,465-481,496-521` |
| Kalman gain | computed, returned to caller, **not persisted** | no | `EnKF.py:365-370` |
| inflation | **applied**, not recorded beyond the input `inflation_factor` | no | `_localization_inflation.py:126`; `EnKF_parallel_io.py:1190` |
| localization matrix | computed when `localization_flag` true | no | `_localization_inflation.py:282-296,381-428` |
| rank histogram | **absent** | — | grep: no matches |
| KL divergence | **absent** | — | grep: no matches |
| timing / wallclock breakdown | **yes** (`MPI.Wtime()` accumulators, `allreduce`) | **no** — text log only; serial block commented | compute: `icesee_da_partial_parallel.py:787-823`; display `tools.py:687-764` |
| assimilation cycle bookkeeping (`k`, `km`) | yes | partially (`last_done_k`, `km` in checkpoint JSON) | `icesee_da_full_parallel.py:598-607` |
| parameter ensemble (joint estimation) | yes — param fields appended to the state vector | **yes, not separated** — same `ensemble` rows beyond `num_state_vars*hdim` | `vec_inputs` e.g. `['h','u','v','smb']` (`synthetic_ice_stream/params.yaml:40`) |

---

## 3. Run directory structure after a run

There is **no run container**. `run_da_*.py` does
`os.chdir(Path(__file__).resolve().parent)` (e.g.
`applications/icepack_model/examples/synthetic_ice_stream/run_da_icepack.py:14`),
so all relative paths resolve inside the **example source directory**:

```
applications/<model>/examples/<example>/
├── params.yaml                     # INPUT (or -F <file>)
├── run_da_<model>.py               # entry script
├── _modelrun_datasets/             # = data_path param (default literal name)
│   ├── icesee_ensemble_data.h5     # ensemble (nd,Nens,nt+1), ensemble_mean (nd,nt+1)
│   ├── icesee_enkf_ens_0000.h5 …   # per-step 'states' (nd,Nens)  [full-parallel]
│   ├── icesee_enkf_mean.h5         # 'mean' (nd,nt)               [parallel]
│   ├── true_nurged_states.h5       # true_state, nurged_state (nd,nt+1)  [+ icesee_fingerprint attr]
│   ├── synthetic_obs.h5            # hu_obs, R
│   ├── H_matrix.h5                 # H_matrix, obs_indices        [parallel]
│   ├── mesh_idxy_0.h5              # mesh index map               [parallel]
│   ├── ensemble_before_analysis_step_XXXX.h5   [partial/full]
│   ├── *.zarr                      # transient, deleted at finalize
│   └── _checkpoints/icesee_ckpt.json           [full-parallel]
├── results/
│   └── true-wrong-<model>.h5       # metadata only: t, obs_index, obs_max_time, b_io, Lxy, nxy, run_mode
├── figures/*.png                   # only if a notebook / icesee_savefig is used
└── icesee_timing.log               # timing table (text)
```

- **Not timestamped, not per-run.** Re-running overwrites: `save_arrays_to_h5`
  deletes the prior `results/*.h5` (`tools.py:247-249`); `_modelrun_datasets`
  is reused.
- `data_path` (`--data_path`) is the **only** built-in output-location knob and
  the natural sweep hook.
- The `find_outputs_dir` / `metadata.json` / `model/` / `fields/` / `mesh/`
  layout that `cryostack_src/models/results_common.py` expects — **ICESEE
  produces none of it.** A CryoStack exporter must synthesize that layout.

---

## 4. Run parameterization & identity

### 4a. Parameter file — single YAML, three sections

- `physical-parameters` — domain geometry (`Lx, Ly, nx, ny, degree`, boundary
  values); Lorenz uses `sigma_96, beta_96, rho_96`.
- `modeling-parameters` — `num_years, timesteps_per_year, dt, T, a_in, da, …`,
  `example_name`; ISSM adds `ParamFile, steps, reference_data, …`.
- `enkf-parameters` — the DA config (see 4c).

Assembled in `config/_utility_imports.py` (`params`, `kwargs`,
`modeling_params`, `enkf_params`, `physical_params`).

### 4b. CLI args (`config/_utility_imports.py`, argparse)

`--Nens <int>`, `--data_path <str>` (default `_modelrun_datasets`),
`--model_nprocs <int>`, `--verbose`, positional `execution_mode ∈ {0,1,2}`,
`--default_run|--sequential_run|--even_distribution`, `-F/--force-params <yaml>`
(default `params.yaml`).

### 4c. Parameters that identify / define a DA run

`model_name` (`icepack|issm|lorenz|flowline`), `model_solver`, `example_name`,
`filter_type` (`EnKF|DEnKF|EnTKF|EnRSKF`), `Nens`, `nt = num_years *
timesteps_per_year`, `dt`, `nd` (from the model mesh at runtime),
`num_state_vars`, `num_param_vars`, `vec_inputs`, `observed_vars`,
`observed_params`, `joint_estimation`, `parameter_estimation`,
`state_estimation`, `sig_model`, `sig_obs`, `sig_Q`, `length_scale`, `Q_rho`,
`inflation_factor`, `localization_flag`, `local_analysis`, `freq_obs`,
`obs_max_time`, `obs_start_time`, `seed`, `base_seed`, nurging params
(`h_nurge_ic`, `u_nurge_ic`, `nurged_entries_percentage`, `a_in_p`, `da_p`),
execution (`mode`, `parallel_flag`, `n_modeltasks`, `model_nprocs`,
`batch_size`), restart (`restart_enabled`, `force_fresh_start`,
`checkpoint_every`, `k_start_override`).

### 4d. Run identity that exists

`icesee_fingerprint(params, keys=("model_name","nd","nt","Nens","base_seed"))`
(`src/utils/tools.py:951-954`): `sha1(json.dumps(sub, sort_keys=True,
separators=(",",":")))`. Computed `icesee_da_full_parallel.py:131-137`, used to
gate artifact reuse (`:222`), stamped on `true_nurged_states.h5` (`:240-243`).
**Serial and partial modes never compute or write it.** It deliberately omits
`filter_type`, `seed`, sigmas, obs schedule, localization/inflation,
joint-estimation config — two scientifically different runs can share a
fingerprint.

---

## 5. Existing run-identity / manifest / hash / provenance concept?

**Essentially NO.** No manifest file, no params dump next to outputs, no
`metadata.json`, no git SHA, no UUID, no schema/version stamp. The only
timestamp is the bare `time.time()` float inside
`_checkpoints/icesee_ckpt.json`. The only content hash is `icesee_fingerprint`
(full-parallel only) + per-rank RNG seeding hashes (not provenance).

---

## 6. Ensemble / experiment structure & mapping to the CryoStack Experiment abstraction

### 6a. How ICESEE represents things

- **Ensemble**: `Nens` members; per-step `(nd, Nens)`; time-stacked
  `(nd, Nens, nt+1)`.
- **State vs parameter members**: joint estimation appends parameter fields as
  extra rows of the same state vector; no separate parameter-ensemble dataset.
- **Assimilation cycles**: a single forward pass of `nt` model steps; the
  analysis update is applied at steps in `obs_index` (`if (km <
  number_obs_instants) and (k == obs_index[km])`,
  `icesee_da_full_parallel.py:573`). There is **no** notion of multiple
  independent DA cycles / repeated windows; restart just resumes the same pass.
- **Multiple experiments / parameter sweep**: not first-class. Mechanisms:
  `--data_path <dir>` (per-invocation output isolation — the one clean knob),
  `-F/--force-params <file>` (swap the whole param file), hand-authored sibling
  param files (convention only), SLURM scaling scripts that vary rank counts /
  `--Nens` and recover results by **parsing log text**
  (`scripts/plotting/scaling_line_bar_plots.py:52`).

### 6b. Mapping to "Experiment = base run + one swept parameter"

Must be **entirely CryoStack-side**. ICESEE offers only per-run inputs:

| CryoStack concept | ICESEE realization | evidence |
|---|---|---|
| base run | one `params.yaml` (3 sections) + `run_da_<model>.py` | `run_da_icepack.py`, `_utility_imports.py` |
| swept parameter | one key overridden in `enkf-parameters`, or `--Nens`. Natural axes: `Nens`, `filter_type`, `inflation_factor`, `localization_flag`, `seed`/`base_seed`, `length_scale`, `sig_obs`, `freq_obs`/`obs_max_time`, `nurged_entries_percentage` | params.yaml keys; `--Nens` |
| one experiment member (a single DA run) | derived `params_<value>.yaml` (or base + `--Nens`) **and** a distinct `--data_path <dir_i>`; invoke `run_da_<model>.py -F params_<value>.yaml --data_path <dir_i>` | `-F` and `--data_path` |
| member output | that member's own `<dir_i>/icesee_ensemble_data.h5` + `<dir_i>/true_nurged_states.h5` + `<dir_i>/synthetic_obs.h5`; **`results/` is CWD-relative and shared** — collides across members unless CWD / `output_dir` is also isolated | §1j |
| experiment manifest | **does not exist** — CryoStack must create it | — |
| member identity | `icesee_fingerprint` only distinguishes `model_name/nd/nt/Nens/base_seed`; CryoStack should hash the full effective param dict | `tools.py:951-954` |

**Warning:** sweeping any parameter **not** in the fingerprint key set
(`filter_type`, `inflation_factor`, `seed`, …) while sharing a `data_path` in
full-parallel mode makes ICESEE **reuse** the previous member's
`true_nurged_states.h5` (`icesee_da_full_parallel.py:222`). Each swept member
must get its own `data_path` and/or `force_fresh_start`.

---

## 7. Proposed `cryostack.icesee.results` fields — EVIDENCE-BACKED ONLY

Every field traces to a file ICESEE actually writes. Contract shape mirrors
`cryostack_src/models/results_common.py` (`schema`, `version`, `status`,
`metadata`, structured accessors).

### 7a. Top-level / metadata

| field | source | evidence |
|---|---|---|
| `schema = "cryostack.icesee.results"`, `version` | CryoStack-assigned | pattern: `icepack/results.py:34` |
| `model` | `params["model_name"]` | `synthetic_ice_stream/params.yaml:76` |
| `filter_type` | `params["filter_type"]` | `params.yaml:78`; `tools.py:238` |
| `mode` | `serial`/`partial`/`full` | `run_models_da.py:27-43` |
| `nd`, `nens`, `nt` | consolidated-file root attrs (else `ensemble.shape`) | `tools.py:142-147` |
| `stack_type` | `"materialized"` / `"VDS"` | `tools.py:144,81` |
| `source_dir` | consolidated-file attr (abspath of `_modelrun_datasets`) | `tools.py:145` |
| `icesee_fingerprint` | h5 attr on `true_nurged_states.h5` (full-parallel only; may be absent) | `icesee_da_full_parallel.py:240` |
| `time` (`t`), length `nt+1` | `results/true-wrong-<model>.h5:/t` | `icesee_da_serial.py:563`; verified `(1001,)` |
| `state_variables` (`vec_inputs`), `num_state_vars`, `num_param_vars` | `params` (would need CryoStack to persist the param dict) | `params.yaml:38-40` |
| `observed_variables` / `observed_params` | `params` | `params.yaml:41-42` |
| `checkpoint` (`last_done_k`, `km`, `timestamp`, `base_seed`) | `_checkpoints/icesee_ckpt.json` | `icesee_da_full_parallel.py:598-607` |

### 7b. Structured fields (ICESEE datasets → contract fields)

One synthetic solution (like Icepack's `SOLUTION="icepack"`), call it `"icesee"`
or `filter_type`. Fields, each a real dataset:

| contract field | dataset / file | shape | evidence |
|---|---|---|---|
| `ensemble` (analysis trajectory, all members) | `icesee_ensemble_data.h5:/ensemble` | `(nd, Nens, nt+1)` | `_ensemble_initialization.py:139`; verified `(3,30,1001)` |
| `ensemble_mean` | `…:/ensemble_mean` | `(nd, nt+1)` | `_ensemble_initialization.py:144`; verified `(3,1001)` |
| `true_state` | `true_nurged_states.h5:/true_state` | `(nd, nt+1)` | `_generate_true_wrong_state.py:91-94`; verified |
| `nurged_state` (background) | `…:/nurged_state` | `(nd, nt+1)` | `:108-111`; verified |
| `observations` | `synthetic_obs.h5:/hu_obs` | `(obs_dim, n_obs_instants)` | `_generate_synthetic_observations.py:59`; verified `(3,10)` |
| `obs_error_cov` (R) | `…:/R` (or `error_R`) | — | `:60`; verified `(10,3)` |
| `obs_operator` (H) | `H_matrix.h5:/H_matrix` | model-dependent | `EnKF_parallel_io.py:894-903` (parallel only) |
| `obs_index` / `obs_max_time` | `results/true-wrong-<model>.h5` | `(n_obs,)` / `(1,)` | verified |
| `forecast_ensemble` (pre-analysis) | `ensemble_before_analysis_step_XXXX.h5` | `(nd, Nens)` per obs step | `_parallel_i_o.py:471-472` (partial/full) |
| `per_step_states` | `icesee_enkf_ens_XXXX.h5:/states` | `(nd, Nens)` × nt | `EnKF_parallel_io.py:174-181` (full only) |
| geometry: `b_io`, `Lxy`, `nxy` | `results/true-wrong-<model>.h5` | `(2,)` each | verified |
| parameter sub-vector (joint estimation) | rows `≥ num_state_vars*hdim` of `ensemble`/`true_state` | — | `read_results.ipynb` slicing |

### 7c. Figures / native artifacts

| field | source | evidence |
|---|---|---|
| `figures` | `figures/*.png` (only if produced) | `tools.py:1050-1078` |
| `native_artifacts` | all `*.h5` under `<data_path>` + `results/` | §1a-1k |
| `timing_log` (opaque text) | `icesee_timing.log` | `tools.py:664` |

---

## 8. Fields we must NOT fabricate (do not exist yet)

Do not put these in v1 unless CryoStack computes them itself from `ensemble` /
`true_state` / `observations`:

- **`rmse` / analysis-vs-truth error** — `rmse()` exists but is never called.
- **`ensemble_spread` / spread-skill ratio** — not computed as a diagnostic.
- **`innovation` / `chi_square` / normalized innovation** — computed transiently
  and discarded.
- **`analysis_increment`** — `return` commented out (`EnKF.py:514-521`).
- **`analysis_error_covariance` / posterior covariance** — `return` commented
  out in all four filters.
- **`kalman_gain`** — computed, returned to caller, never persisted.
- **`rank_histogram` / talagrand** — no code.
- **`kl_divergence`** — no code.
- **`observation_impact` / DFS / information content** — no code.
- **`wallclock_seconds` / structured timing** — text log only.
- **`convergence` / iteration count** — single forward pass, nothing iterative.
- **`run_id` / `git_sha` / `manifest` / `created_at` / full parameter record** —
  none exist; closest is the 5-key `icesee_fingerprint` (full-parallel only).
- **`metadata.json` / `outputs/` / `model/` / `fields/` / `mesh/` layout** — a
  CryoStack exporter must synthesize it.
- **per-timestep model `times`** — only the uniform `t` linspace is stored.

---

## 9. `cryostack_src/` check — existing ICESEE-DA result handling

`grep -rn "icesee" cryostack_src/ --include=*.py -l` → 60+ files, **all** ICESEE-
Container / ICESEE-Spack / ICESEE-project branding (image builds, spack envs,
cloud auth), e.g. `cryostack_src/models/submission.py:140`
(`_ICESEE_CONTAINERS_REPO`), `cryostack_src/frontend/icesee/__init__.py`
(re-exports `CloudEnvironmentWidgets`). No `cryostack_src/models/icesee/`
package. `MODEL_CAPABILITIES` registers only `issm` and `icepack`
(`capabilities.py:75-101`).

**Conclusion:** a `cryostack.icesee.results` contract would be greenfield. The
reliably-populated core is `ensemble (nd,Nens,nt+1)`, `ensemble_mean
(nd,nt+1)`, `true_state`, `nurged_state`, `observations (hu_obs)`,
`obs_error_cov (R)`, `t`, plus geometry scalars and (full-parallel) the
`icesee_fingerprint` attr. Everything diagnostic (RMSE, spread, innovations,
increments) must be computed by a CryoStack-side exporter from those
primitives — ICESEE does not compute or persist them today.

---

## 10. Recommendation for PASS 4 / next parity phase

1. **Do not implement `cryostack.icesee.results` this pass.** OWNER_CHECKPOINT:
   the contract is greenfield and every useful diagnostic requires a
   CryoStack-side exporter that computes it (RMSE, spread, innovations) from
   the ensemble/truth/obs primitives — that is scientific work needing owner
   review, not evidence-driven wiring.
2. **When it is built**, the exporter reads the raw h5 files under `data_path`
   and synthesizes the `outputs/{metadata.json,fields,mesh}` layout
   `results_common` expects. v1 fields = §7 only.
3. **Experiment mapping:** a CryoStack ICESEE experiment must give each swept
   member its own `--data_path` **and** its own working directory (so the
   CWD-relative `results/` does not collide), and should hash the full
   effective param dict for member identity (ICESEE's `icesee_fingerprint` is
   too narrow). The `ExperimentPlan` sweep axis maps cleanly onto a single
   `enkf-parameters` key or `--Nens`.
4. **Provenance:** CryoStack must write the run manifest itself — ICESEE writes
   none. The `params.yaml` used is the reproducibility record; capture it.
