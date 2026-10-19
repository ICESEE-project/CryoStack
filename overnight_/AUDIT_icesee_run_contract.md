# AUDIT — ICESEE "DA run" contract (Agent C-Run, read-only)

Subagent `a3e2613e90d7cc092`, PASS 2, reviewed by the coordinator. Paths
relative to `/home/bkyanjo3/CryoLauncher/`. ICESEE science under `external/ICESEE/`.

## 1. What a "DA run" is (from the implementation)

**A run = one `python applications/<model>/examples/<ex>/run_da_<model>.py -F <rundir>/params.yaml`** (`icesee_jupyter_book/core/local_runner.py:146`). Lifecycle:

1. Config load (import): `external/ICESEE/config/_utility_imports.py:66-377` parses
   `params.yaml` -> `physical-parameters` / `modeling-parameters` /
   `enkf-parameters`; derives `nt = num_years*timesteps_per_year` (:148),
   `dt = 1/timesteps_per_year` (:149), `obs_index` schedule (:228-229).
2. Model init: `initialize_model()` then `icesee_model_data_assimilation()`
   (`run_da_*.py:46/67`).
3. Mode dispatch serial/partial/full from `enkf-parameters.execution_mode` 0/1/2
   (`external/ICESEE/src/run_model_da/run_models_da.py:27-43`; default partial).
4. Truth+nurged -> `<datapath>/true_nurged_states.h5` (`true_state`,`nurged_state`).
5. Synthetic obs -> `<datapath>/synthetic_obs.h5` (`hu_obs`, `R`).
6. Ensemble init -> `<datapath>/icesee_ensemble_data.h5`
   (`ensemble` (nd,Nens,nt+1), `ensemble_mean` (nd,nt+1)).
7. `for k in range(nt)`: forecast all members -> analysis only when
   `k == obs_index[km]` (EnKF/DEnKF/EnRSKF/EnTKF in
   `external/ICESEE/src/EnKF/python_enkf/EnKF.py:373/410/450/483`) -> checkpoint
   (full-parallel only).
8. Finalize: `save_all_data(...)` -> `results/true-wrong-<model>.h5` (metadata:
   `t`,`obs_index`,`obs_max_time`,`run_mode`,`Lxy`,`nxy`,`b_io`); filter output
   `results/{filter_type}-{model}.h5` (`ensemble_vec_full/_mean/_bg`) for
   run_mode!=0 / MPI (`external/ICESEE/src/utils/tools.py:238`, **overwrites**
   :247-249).
9. (CryoLauncher only) `ensure_report_h5` + papermill `read_results.ipynb` ->
   `<rundir>/report.ipynb` + `<rundir>/figures/*.png` (`local_runner.py:60-112`).

**State vector** = one flat length-`nd` vector, equal blocks of `hdim = nd /
total_state_param_vars`, one per name in `enkf-parameters.vec_inputs`.

**No numerical diagnostics exist.** `rmse` is defined
(`external/ICESEE/src/EnKF/_localization_inflation.py:433`) but never called.
No rank histogram / CRPS / spread. "Diagnostics" = the qualitative
True/Background/Obs/Analysis plots the report notebook draws.

**One ensemble = one run.** `Nens` is scalar; no sweep driver exists. A
parameter sweep = N runs (CryoLauncher already mints a fresh run id per click).

**No run-identity concept inside `external/ICESEE/`** — no uuid/hash/manifest.
Identity = the strings in `params.yaml` + the `data_path` folder name.
`experiment_bridge` (POST to `/api/v1/experiments`) is a CryoLauncher concept,
not persisted into the run dir except as the raw `params.yaml`.

## 2. Contract table (Concept | source of truth | CryoStack representation | confidence | safe now?)

| Concept | Source (file:line) | CryoStack representation | Conf | Safe now? |
|---|---|---|---|---|
| Experiment identity | `_utility_imports.py:142-144,161`; run id `icesee_gateway.py:695` | `RunInfo.id` (uuid) = the run; `model="icesee"`; `name = "ICESEE <filter> run"`; store `params.yaml` verbatim as config-of-record; `metadata={example,model_name,filter_type}` | high | yes |
| Ensemble size | `enkf-parameters.Nens` (`_utility_imports.py:176`), CLI `--Nens` (`remote_runner.py:421,589`) | `metadata["Nens"]` | high | yes |
| Forecast model | `enkf-parameters.model_name` + example dir (`example_registry.py:12-63`) | `metadata["model_name"]` / `["example"]` — NOT `RunInfo.model` (fixed "icesee") | high | yes |
| Observation source/freq | synthetic flags + `freq_obs`/`obs_start_time`/`obs_max_time`/`observed_vars`/`observed_params` (`_utility_imports.py:228-267`) | `metadata["observations"]={synthetic,freq_obs,obs_start_time,obs_max_time,observed_vars,observed_params}` | high(values) | yes for scalars; external-obs wiring unused, don't model |
| Assimilation cycle boundary | `k == obs_index[km]` (`icesee_da_serial.py:385,516`) | `metadata["cycles"]=len(obs_index)` read FROM the finished run; cycles = time-axis subset, not sub-runs | high | count yes; per-cycle hierarchy = OWNER DECISION |
| Filter type | `enkf-parameters.filter_type` (`icesee_da_serial.py:249-252`) | `metadata["filter_type"]` | high | yes |
| State vs parameter est. | `joint/state/parameter_estimation` (`_utility_imports.py:230-233`) | `metadata["estimation"]={joint,state,parameter,joint_estimated_params,num_state_vars,num_param_vars}` | high | yes |
| MPI / parallel layout | `parallel_flag`+`execution_mode`(0/1/2)+`n_modeltasks`+`model_nprocs` (`_utility_imports.py:158-163`); UI `cluster_mpi_np`/`cluster_model_nprocs` (`icesee_gateway.py:682-683`) | `metadata["icesee_run_mode"]` (int) + `metadata["parallel"]={parallel_flag,n_modeltasks,model_nprocs}` + `metadata["mpi"]` (remote/cloud only). **Rename** to avoid colliding with `RunInfo.execution_mode` (transport axis) | high | yes with renamed keys |
| Checkpoint/restart | full-parallel only: `_checkpoints/` + JSON `last_done_k` (`icesee_da_full_parallel.py:293-313,595-609`); resume continues SAME dir | `metadata["restart"]={enabled,checkpoint_every,k_start_override}`; resume updates the SAME RunInfo | high(mech) | record yes; resume UX = OWNER DECISION |
| Per-cycle output | ensemble slice in `icesee_ensemble_data.h5`; partial extra `ensemble_before_analysis_step_{k:04d}.h5` | time-axis slice, not a separate artifact; record `nt`,`obs_index` | high | yes |
| Final ensemble/state | run_mode==0 (DEFAULT): `<datapath>/_modelrun_datasets/icesee_ensemble_data.h5` — **NOT under results/**; run_mode!=0: `results/<filter>-<model>.h5` | `results_directory=<rundir>` (whole dir) OR `metadata["state_h5"]` resolved by run_mode | high | partial — must fix the path mapping, `results/` alone != the state in default mode |
| Diagnostics | **none computed/stored** | do NOT model | high | no (nothing to represent) |
| Figures | side effect of papermill `read_results.ipynb`; filenames per-example inconsistent | `figures_directory=<rundir>/figures`; enumerate `*.png`, never assume names | med | dir yes, filename no |
| Log | local: in-memory `LocalRunResult.log_text`, NOT a file; remote: `result.log_file` on cluster | persist local `log_text` -> `<rundir>/run.log`, set `RunInfo.log_file` | high | yes (small write) |
| Report notebook | papermill -> `<rundir>/report.ipynb`; ISSM `report_nb="read_results.m"` (MATLAB) papermill can't run -> silently None | `metadata["report"]={generated,path}` | high | yes to record; ISSM `.m` misconfig is a pre-existing bug |

## 3. `cryostack.icesee.results` hierarchy justified by current outputs

Derived strictly from what every `read_results.ipynb` opens:

```
experiment   (= the run: <rundir> + params.yaml + model_name/example_name/filter_type)
  attrs: model_name, example_name, filter_type, Nens, seed, nt, dt,
         t[nt+1], obs_index[m_obs], obs_max_time, run_mode, Lxy[2], nxy[2], b_io[2]
  series "ensemble"          <- icesee_ensemble_data.h5:/ensemble        (nd, Nens, nt+1)
  series "ensemble_mean"     <- icesee_ensemble_data.h5:/ensemble_mean   (nd, nt+1)  [= analysis mean]
  series "true_state"        <- true_nurged_states.h5:/true_state        (nd, nt+1)
  series "background_state"  <- true_nurged_states.h5:/nurged_state      (nd, nt+1)
  series "observations"      <- synthetic_obs.h5:/hu_obs                 (nd, m_obs)

  index: [variable_block][spatial_index_within_block][time_index]  (+ member for "ensemble")
    variable_block = position in enkf-parameters.vec_inputs; block len = hdim = nd / total_state_param_vars
    time index in [0..nt]; "cycle" k = subset where time == obs_index[km]
```

So the operator's `experiment -> cycle -> member/statistic -> variable -> diagnostic`
collapses to **`experiment -> series -> variable_block -> spatial_index -> time_index [-> member]`**.
Cycle is not a level (it's a time subset). Member vs statistic is not a shared
level (only `ensemble` has members). Diagnostic is not a level (no data).

## 4. Safe now vs OWNER DECISION

**Safe now:** register one `RunInfo` (`model="icesee"`, `execution_mode` in
{local,remote,cloud}, rich `metadata` per the table, `params.yaml` as
config-of-record, `figures_directory=<rundir>/figures`,
`workspace_directory=<rundir>` under `user_run_root`); persist local log to a
file; keep "one run = one fresh dir" invariant; manifest v2 stackless.

**OWNER DECISION:** `results_directory` semantics (default mode ensemble is in
`_modelrun_datasets/`, not `results/`); whether "cycle" is a first-class
concept; restart/resume model; trusting local `status` (`run_models_da.py:75-78`
swallows exceptions, can exit 0 after a traceback); the `output_label` dropdown
extra-H5-copy; fixing ISSM `report_nb="read_results.m"`; metadata key naming for
the `execution_mode` collision; whether CryoStack should compute RMSE/spread
itself.
