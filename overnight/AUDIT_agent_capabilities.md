# AUDIT — Agent-callable capabilities over existing CryoStack APIs (Agent A1)

Subagent `afc82d54f533fcded`, PASS 3, reviewed by the coordinator. HEAD `cad59f8`.
Classified inventory of platform operations that exist as **importable
functions / public methods** (not UI callbacks). See the full per-subsystem
tables below.

## Classification legend
READ_ONLY · LOCAL_MUTATION (own workspace tree only) · REMOTE_MUTATION (HPC fs /
S3) · COMPUTE_SUBMISSION (sbatch / AWS Batch) · DESTRUCTIVE (deletes user data) ·
SECRET_BEARING (takes/returns/can-log a password/key/token/AWS cred/MATLAB
license) · UNSAFE_FOR_AGENT (arbitrary shell/command, or acts outside the
authenticated user's scope).

`agent-safe? = yes` only when READ_ONLY, or a scoped LOCAL_MUTATION with no
secret exposure and no arbitrary-command surface.
`confirm? = yes` for scientific-intent LOCAL_MUTATION, all REMOTE_MUTATION, all
COMPUTE_SUBMISSION, all DESTRUCTIVE.

## Headline
- **Read side is agent-ready.** examples discovery, the ISSM/Icepack adapter
  inspection helpers, the neutral result readers, the deterministic visualizers,
  `shared_validation`, `cloud/config`, `resources/profiles` — all pure,
  MATLAB/Firedrake-free, side-effect-free (or write only a derived PNG into an
  already-owned dir).
- **Identity anchor is sound:** `resolve_workspace_user(require_authenticated
  =True)` (`workspace/identity.py:58`) is a single fail-closed source;
  `WorkspaceManager` confines every op to `<root>/users/<safe_id>/`
  (`manager.py:166`) with repeated containment re-checks.
- **All gaps are on the write/execute side and structural, not deep.**

## Identity-spoof surface (raw owner/host/user/profile args an agent could set)
1. `WorkspaceManager.__init__(owner=, workspace_root=, require_authenticated=False)`
   — `manager.py:123-126,155-164`. Agent tools MUST build it with no `owner`,
   no `workspace_root`, `require_authenticated=True`.
2. `resolve_workspace_user` honours `CRYOSTACK_WORKSPACE_USER` (`identity.py:81`)
   — must not be settable via any agent-reachable surface.
3. `roots.user_run_root(user=)` / `owner_root(user=)` — derive, never accept.
4. `connector_relay_client.create_session(owner_user_id)` / `bind_session(...,
   control_secret, owner_user_id)` — `connector_relay_client.py:78,40`.
5. `RemoteBridge.__init__(host, user, port, session_id, ...)` — `bridge.py:27`.
6. `submit_remote_icesheets*(host, user, session_id, ...)` — `submission.py:271,671`.
7. `CloudBridge.__init__(profile=)` / `CloudManager.*(profile=)` /
   `WorkspaceManager.sync_cloud_results(profile=)`.

## NEVER expose as a tool (exact symbols)

**Arbitrary command execution:**
`RemoteBridge.check_backend` (`bridge.py:138`) + `_run_script` (`:166`);
`RemoteBridge.logs` (`:78`); `remote_runner.ssh_run` (`:485`) / `rsh` (`:797`) /
`connector_ssh` (`:970`); `connector_relay_client.send_command` (`:146`) with any
`command` payload (`ssh-run`/`slurm-submit`/`install-pubkey`/
`bootstrap-passwordless-ssh`/`fetch-archive`);
`WorkspaceManager.inspect_remote_results` (`manager.py:1250`); `.tail` (`:233`);
`.delete` (`:756`, no containment check); `.clone_example` (`:953`, writes
outside the owner tree).

**Secret-bearing / credential:**
`connector_relay_client.create_session` (`:78`), `bind_session` (`:40`),
`current_binding` (`:59`, returns `control_secret`), `clear_binding` (`:53`);
`remote_runner.bootstrap_passwordless_ssh` (`:1046`),
`remote_install_pubkey_with_password` (`:742`),
`connector_install_pubkey_with_password` (`:1021`),
`_paramiko_connect_password` (`:718`), `ensure_local_ssh_key` (`:662`);
`ComputeProfile.matlab_license_config` (`profiles.py:117`) + `.matlab_license_value`
(`:96`); `spack_env.install_sbatch_text` (`:225`, embeds license);
`submission._matlab_container_env` (`:75`).

**Compute submission / remote & infra mutation:**
`submission.submit_remote_icesheets` (`:671`) / `submit_remote_icesheets_via_connector`
(`:270`); `RemoteBridge.submit` / `submit_spack_setup_job` /
`prepare_spack_environment` / `_sbatch` / `_write_remote_file` / `terminate`
(`bridge.py:48,217,270,249,183,103`); `RemoteBackend.submit`/`.terminate`
(`remote.py:69,222`); `CloudBackend.submit`/`.terminate` (`cloud.py:81,309`);
`CloudBridge.submit`/`.terminate`/`.prepare_environment`/`.results`
(`cloud/bridge.py:37,56,76,59`); `CloudManager.{submit,terminate,bootstrap,
prepare_storage,prepare_batch,iam,network}` (`cloud/manager.py`);
`remote_runner.{connector_slurm_submit,connector_stage_archive,connector_write_text,
connector_fetch_archive,remote_cancel_job,remote_ensure_spack,
remote_maybe_install_spack,submit_remote_example*}`;
`WorkspaceManager.{refresh_results,_refresh_results_locked,download_results,
download_figures,preview_results,sync_cloud_results}`.

**Destructive:** `WorkspaceManager.{delete_user_example,delete_user_file,
delete_dataset,delete_run,delete}`.

## A3 starter set — safe read-only tools (exact underlying calls)

| tool | underlying call(s) | user-scope enforced at |
|---|---|---|
| `list_models` | `get_model_adapter` set `{issm,icepack}` (`models/__init__.py:6`); `icepack.HAS_BASIC_CONFIG` | static |
| `list_examples` | `merged_examples_for_model(model, …, user_examples=wm.list_user_examples(model), runnable_check=adapter.example_runnable)` (`icesheet_examples.py:59`, `manager.py:451`) | `list_user_examples` reads only `_examples_root` |
| `inspect_example` | `find_merged_example` (`:102`); `wm.list_editable_files` (`manager.py:241`); `wm.example_dataset_references` (`:475`); `adapter.detect_solvers`/`choose_run_target` | `read_text_file`/`resolve_user_file` containment; canonical trees read-only |
| `list_compute_resources` | `COMPUTE_PROFILES` keys + `get_compute_profile` (`profiles.py:149,156`) | site facts only |
| `inspect_resource_requirements` | `get_compute_profile(name)` fields; `initial_remote_fields` (personal fields blank) | **must** expose `has_matlab_license` bool only, never `matlab_license_config()` |
| `list_user_datasets` | `wm.list_datasets()` (`manager.py:663`) | iterates only `_datasets_root` |
| `list_runs` | `wm.list_runs()` (avoid `refresh`'s per-run remote reconcile) (`manager.py:792`) | `manifest_root` under `_owner_root`; glob only there |
| `inspect_run` | `wm.list_runs()` → `RunInfo`; `wm.files(run_id)` (`:826`); `wm.result_package_for_run(run_id).status` (`:865`) | `files()` + `result_package_for_run` guarded by `_owns` |
| `inspect_results` | `wm.result_package_for_run(run_id)` (`:865`); `pkg.status/available_solutions/mesh_metadata` | `_owns(run.workspace_directory)` |
| `list_result_fields` | `pkg.available_fields(solution)` + `pkg.field_metadata`; or `wm.recommended_plots_for_run` (`:920`) | same `_owns` guard; no path arg from the agent |

Optional safe extension: `render_run_plot(run_id, solution, field, timestep?)`
(`manager.py:928`) — scoped LOCAL_MUTATION (PNG into the owned run's `figures/`,
`_owns` guarded, never raises), acceptable as a no-confirm tool (changes no
scientific intent).

## State of agent-readiness (verbatim from A1)
The read side is in good shape. The identity story is sound in principle
(`resolve_workspace_user(require_authenticated=True)` is a single fail-closed
anchor; `WorkspaceManager` confines every operation to
`<root>/users/<safe_id>/`). The gaps are all on the write/execute side and all
structural rather than deep: `WorkspaceManager.__init__`, `roots.*`,
`RemoteBridge.__init__`, `CloudBridge.__init__`, the `submit_remote_icesheets*`
functions, and `connector_relay_client.create_session/bind_session` each take a
raw `owner`/`host`/`user`/`session owner`/`profile` argument, so a tool layer
must construct these objects itself from derived identity and never surface
those parameters. The genuinely dangerous surface is small and well-localised.
Provided the agentic layer (a) builds workspace/bridge objects from
`resolve_workspace_user`, (b) ships only the ten READ_ONLY tools plus
`render_run_plot`, and (c) routes every COMPUTE_SUBMISSION / REMOTE_MUTATION /
DESTRUCTIVE operation through explicit human confirmation rather than a tool,
the platform is ready for a bounded first cut.

---

## Full per-subsystem tables

(The subagent produced exhaustive file:line tables for all 15 subsystems —
examples, models/adapters, WorkspaceManager (~55 methods), datasets, execution
backends, RemoteConnection, Slurm validation, run staging+submission,
monitoring, Results, visualization, downloads, Connector, CloudBridge,
auth/identity. Kept in the subagent transcript; the classification summary
above and the "never expose" / "starter set" lists are the actionable
distillation the coordinator worked from.)
