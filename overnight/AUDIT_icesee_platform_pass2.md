# ICESEE C4/C5 audit — PASS 2 extension (Agent C-Platform, read-only)

Subagent `aa633909ea8faa9ac`. Extends `AUDIT_icesee_platform.md`. HEAD `12bd3ac`.

## TASK A — application-shell parity (line by line)

| Capability | ICESEE state | Shared component | Adopt now? |
|---|---|---|---|
| Shared header | SHARED (`icesee_gateway.py:320,2851` → `application_menus._build_application_menu`) | — | done |
| Responsive CSS | SHARED sheet + a **bespoke inline `<style>` overlay** `icesee_gateway.py:2483-2521,2846` (light-mode only, overrides shared tokens) + dead `build_sidebar` w/ its own style `:202-288` | `shared_application_styles` | **YES — delete overlay + dead sidebar** (breaks dark theme) |
| B2 persistence | SHARED `icesee_gateway.py:1046-1056` | `ResourceStateController` | done (dedupe: Q1) |
| Remote Connection panel | SHARED `icesee_gateway.py:2627` | `build_remote_connection_panel` | done |
| B3 identity | SHARED lib / bespoke call site `:1413,1707` | `remote.access_state` | engine done |
| Slurm panel | SHARED `:2661` (+MPI extras via `extra_children`) | `build_slurm_resources_panel` | done |
| Pre-submit validation | Remote SHARED `:1445`; **Cloud LACKS** (`run_example_cloud_submit :2056-2098` — no `validate_cloud_config`, no `cloud_run_preflight`) | `validate_slurm_resources` / `validate_cloud_config`+`cloud_run_preflight` | Slurm done; cloud = Task B |
| Workspace isolation | BESPOKE, run-root only (`_icesee_run_dir_base` → `user_run_root`, PASS-1). No `WorkspaceManager` containment / manifest. `_remote_fetch` still `rmtree`+re-extract per Preview | `WorkspaceManager` | YES, gated on "what is a DA run" |
| Run history | **LACKS.** `workspace_bridge = WorkspaceBridge()` at `:336` is the UI *persistence* bridge (`.save`/`.widget` only), NOT `cryostack_src.workspace.WorkspaceBridge`. `start_run` never called. Local + cloud persist nothing. Remote only POSTs to `experiment_bridge`. | `WorkspaceBridge.start_run` + `build_workspace_history_panel` | YES, gated on run-granularity decision |
| Logs panel | BESPOKE trivial (`W.Output` + hand `<div>` heading) | `build_logs_panel` / `build_run_details` | YES (low value alone) |
| Results panel | BESPOKE (`refresh_results_preview :174-193`, `preview_remote_results :782-810` — ad-hoc png/h5 glob) | `build_visualization_panel` + `ResultPackage` | **NO — needs the DA `outputs/` schema** (AUDIT_icesee_run_contract §3) |
| Downloads | BESPOKE partial (remote-only `FileLink`, no auto-download, **no local-mode button**) | `WorkspaceManager._auto_download` / `_make_zip` | YES, after run history |
| Documentation | SHARED (`_build_application_menu` nav) | — | done; remove dead sidebar nav |

### Q1 — duplicated logic between the two gateways (reusable)
1. `create_or_refresh_connector_session` — `icesee:931` ↔ `icesheets:949`
2. `on_bootstrap_keys` + `_bootstrap_panel` — `icesee:1217,1211` ↔ `icesheets:852,846` (`_bootstrap_panel` **byte-identical**)
3. `show_connector_public_key_help` — `icesee:1186` ↔ `icesheets:821` (**identical**)
4. `_probe_ssh_key_manager` — `icesee:2711` ↔ `icesheets:2522` (**identical**)
5. `_toggle_auth_widgets` — `icesee:1125` ↔ `icesheets:2875` (**identical**)
6. B2 wiring block (`_b2_read_personal`/`_b2_apply_personal`/`_sync_resource_facts`/`_on_resource_changed` + `ResourceStateController`) — ~80 dup lines each
7. `should_use_connector` — `icesee:1166` ↔ `icesheets:1703`
8. `form_pair` — `icesee:832` ↔ `icesheets:1167`
9. `current_experiment_configuration`/`current_workspace_state` envelope — `icesee:2148,2278` ↔ `icesheets:749,2396`
11. `make_zip_from_dir` `icesee:196` ↔ `WorkspaceManager._make_zip` `manager.py:1120` (empty `cryostack_src/workspace/downloads.py` stub already exists)

Grouping: (a) `shared_connector_actions.py` (1,2,3,7); (b) `shared_resource_state.py` (6); (c) fold 4,5,8 into existing shared; (d) 11 → `workspace/downloads.py`.

## TASK B — legacy `cloud_runner` → `CloudBridge`

**AWS Batch here is FARGATE-ONLY, single-container. NO multi-node MPI.**
`COMPUTE_ENVIRONMENT_NAME="cryostack-fargate"`; `compute_resources_payload` →
`{"type":"FARGATE"}` (`batch_config.py:154-161`); `container_properties_payload`
builds ONE container — no `nodeProperties`/`numNodes`/`--node-property-overrides`
anywhere in `cryostack_src/cloud` or `cryostack_src/execution`. AWS Batch MNP
needs an EC2 CE + `nodeProperties` job-def; not on Fargate. Fargate caps 16 vCPU
/ 120 GiB.

ICESEE remote = genuine multi-node MPI: `#SBATCH -N/-n` + `srun --mpi=pmix -n
{cluster_mpi_np}` (default 40) inside Apptainer (`remote_runner.py:357,415`).
**Does not fit current infra.**

`SUPPORTED_CLOUD_MODELS=("issm",)` (`runtime.py:50`) enforced in 3 gates
(`preflight.py:52`, `staging.py:117`, submit). ICESEE is architecturally excluded
today.

**Safe now (NO infra):**
- Adopt `CloudBridge`+`CloudBackend`+`ExecutionResult` as ICESEE's cloud
  *interface* with an injected `submitter`=adapter to `cloud_runner
  .submit_cloud_example` and `results_sync=…`. `CloudBridge` already accepts
  both (`bridge.py:21,26`; `AWSDriver.submit` honours an injected submitter
  first, `driver.py:535`). Unifies status/logs/terminate/`_normalize_state`,
  no image-contract change, no provisioning.
- Route ICESEE cloud submits through `WorkspaceBridge.start_run` (run history).
- Delete the bespoke `css` overlay + dead `build_sidebar`.
- Q1 dedupe; shared zip helper + local-mode download button.

**Needs infra provisioning:** `cryostack-icesee` ECR image + `icesee` entries in
`JOB_DEFINITION_NAMES`/`ECR_REPOSITORY_NAMES` + `ensure_batch_resources` +
`runtime.py` runner branch; lift the `SUPPORTED_CLOUD_MODELS`/preflight gates
(MATLAB-license gate must become conditional).

**OWNER ARCHITECTURE DECISION (agent must NOT decide):** the compute primitive
for the ICESEE MPI ensemble — AWS ParallelCluster (managed Slurm + EFA) vs
Batch-MNP-on-EC2 + EFA vs single-node `mpirun` Batch for small ensembles only vs
EKS + MPI operator. And whether cloud ICESEE is scoped to demo-scale ensembles
or production multi-node DA.
