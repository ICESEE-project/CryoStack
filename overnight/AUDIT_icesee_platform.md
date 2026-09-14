# ICESEE ↔ IceSheets platform-sharing audit (Agent C-1, read-only)

Subagent `a65c945f762e38c52`, 2026-09-01, reviewed by the coordinating agent.
Branch `gatech_vm_backend`. See `AGENT_TRAIL.md` §C for decisions taken.

## Capability matrix

| Platform capability | IceSheets | ICESEE today | Adopt-now? | Blast radius |
|---|---|---|---|---|
| Per-user **run-file** isolation | `WorkspaceManager` owner root `<root>/users/<safe_id>/.cryostack/runs/<run_id>` | **Absent.** Local → `BOOK/icesee_runs/<YYYYMMDD_HHMMSS>/`, process-global, 1-s granularity, `mkdir(exist_ok=True)`. Remote-fetch cache → same tree. No user component. | **SAFE** (B2-class) | `local_runner.run_dir` + `cloud_runner` + 3 gateway helpers |
| Per-user **settings** (B2) | server-side, keyed by trusted `HTTP_X_CRYOSTACK_USER_ID` | **Present & shared** (`make_state_io(...,"icesee",user_id)`) | done | — |
| Local **run history** (RunInfo + manifest + cards) | `WorkspaceBridge.start_run` → `RunHistory` + `register_run` writes `.cryostack-run.json`; `build_workspace_history_panel` | **Absent.** Only `experiment_bridge.create()` POSTs to the web API — no local record, no re-selection, no per-run dir | **SAFE** | additive |
| Structured `outputs/` **ResultPackage** | `models/*/results.py::discover_results`, cached per run | **Absent.** Ad-hoc `rglob("*.png"/"*.h5")` previews | **DA-CARE** | needs an `icesee` adapter + a DA output schema |
| Results **visualization** panel | `visualization/issm.py` + `build_visualization_panel` | **Absent** | **DA-CARE** | depends on the schema |
| **Download** buttons | `_auto_download` JS blob per selected run | Partial: remote-only zip; **local mode has no download button** | SAFE (helper) / DA-CARE (per-run wiring) | additive |
| Execution mode dispatch | `current_remote_bridge().submit()` + `CloudBridge`; `ExecutionResult` normalized | Hand-rolled tab-index → `run_example_{local,remote_submit,cloud_submit}`; 6 bespoke `submit_remote_example*` | DA-CARE (partial SAFE) | `execution/*` accepts an injected `submitter`; rewiring 6 call sites is not safe |
| Remote transport / connector / B3 gate / SSH-key mgr | shared | **Present & shared** | done | — |
| Shared B4 UI panels | shared | **Present & shared** | done | — |
| Cloud backend | C4/C5 `CloudBridge` → `CloudManager`/`AWSDriver`, deterministic job-def, CryoStack image | **Legacy** `core/cloud_runner.py`: user-typed queue/job-def, user-supplied Batch image reading `ICESEE_S3_RUN`/`ICESEE_RUN_SCRIPT` | **ICESEE-SPECIFIC** for now | needs a provisioned `cryostack-icesee` image + job def |
| Reproducibility provenance | resolved stack in manifest | n/a — ICESEE-Spack carries no resolved stack | ICESEE-SPECIFIC (manifest already tolerates `{}`) | — |
| Filter algo / `Nens` / seed / params.yaml form / `-F` / papermill | n/a | ICESEE core science UI | **ICESEE-SPECIFIC** — keep separate | — |

## Where ICESEE writes (isolation status)

| Path | Isolation |
|---|---|
| `icesee_jupyter_book/icesee_runs/<sec-ts>/{params.yaml,results/,figures/}` (`local_runner.py:22-26`) | **None.** Same-second → shared dir, mutual overwrite; every user can enumerate/read/delete every other user's local runs. |
| `.../icesee_runs/<ts>/_remote_fetch/outputs/` (`icesee_gateway.py`) | **None.** `rmtree` + re-extract per Preview/Download — one user's fetch wipes another's. |
| Cloud staging `run_dir()/params.yaml` before `s3 cp` (`cloud_runner.py`) | **None** locally; S3 side under the user-typed bucket/prefix. |
| Remote `<remote_base_dir>/<remote_tag>/...` (`icesee_gateway.py:1462`) | **Convention only.** B3 gate ensures SSH login == configured HPC username; two CryoStack users on one HPC account still collide. Not platform-enforced. |

## `params.yaml` DA contract (unchanged, do not touch)

Sections `physical-parameters`, `modeling-parameters`, `enkf-parameters`. The
last holds `Nens`, `freq_obs`, `obs_*_time`, `num_state_vars`/`num_param_vars`,
`vec_inputs`/`observed_vars`, `sig_obs`/`sig_Q`/`length_scale`,
`joint_/state_/parameter_estimation`, `seed`, `inflation_factor`,
`localization_flag`, `filter_type` (`EnKF|DEnKF|EnTKF|EnRSKF`), `parallel_flag`
(`serial|MPI|MPI_model`), `execution_mode` (0/1/2). Each ICESEE example ships
its own `params.yaml`; the UI builds a per-key widget grid dynamically. DA run
outputs: `.h5` in `<run>/results/`, `.png` in `<run>/figures/` — **no
structured `metadata.json`/fields/ensemble-stats layout**.

## Can WorkspaceManager / RunHistory / manifest accept `model="icesee"` (no stack)?

- `RunInfo`, `manifest.write/read`, `RunHistory`, `WorkspaceBridge.start_run`,
  `register_run`, `refresh` — **Yes, zero changes.** `model` is opaque `str`;
  `container`/`software` default `{}`; `manifest.py:46-48` anticipates
  stackless (ICESEE-Spack) runs; schema v2 live.
- `WorkspaceManager` — **Yes, with a ~5-line shim** (done, `1e68ae8`): its
  `model` arg was expected to be a widget (`select_run` reads `.options`,
  assigns `.value`). Now accepts a `str`.
- No `cryostack_src/workspace` rewrite required for isolation + history — only
  `run_dir` parameterisation (done, `3a7705f`) + the shim.

## Needs a scientific/design decision (agent must NOT decide)

1. What is a "run" for DA? One ensemble = one `RunInfo`, or N?
2. The canonical ICESEE `outputs/` schema (forecast vs analysis ensembles,
   mean/spread, RMSE/rank-histogram, per-cycle state) — nothing like the ISSM
   `ResultPackage`. Must be defined before an `icesee` `discover_results` /
   visualizer can exist.
3. Whether ICESEE local runs may keep writing into the canonical example `base`
   (`ensure_report_h5` behaviour) or must stage a working copy.
4. Provision a `cryostack-icesee` Batch image + job definition (MATLAB-free MPI
   ensemble) vs. keep the user-supplied-image contract.
5. A `params.yaml` validation/derivation UI (EnKF parameter-space consistency).
6. Whether ISSM/Icepack forward models launched *through* ICESEE inherit
   IceSheets' stack-resolution / license preflight / Spack-readiness gates.

## Highest-value, lowest-risk first adoption (done this session, partial)

Per-user run-directory isolation via `user_run_root(app="icesee")` (C-3).
The full `WorkspaceManager` + `WorkspaceBridge.start_run` + history panel is the
next reviewed step, gated on decision #1 + #2.
