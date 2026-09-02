# AUDIT — CryoStack Cloud (AWS Batch) path at HEAD, for Cloud phase C6

**HEAD:** `cd043fe` (branch `gatech_vm_backend`). Read-only trace. No AWS
commands issued. Goal: know exactly what C1–C5 already built before touching it,
so C6 hardens the existing path rather than adding a parallel stack.

Companion target flow (from the C6 brief): UI → config → CloudBridge → AWS CLI →
staging → S3 → Batch → job id → poll → logs → outputs → ResultPackage →
visualization → experiment/provenance.

---

## 1. The path as it exists (call order)

```
IceSheets gateway  on_run()  [icesheets_gateway.py:1764]
  mode == "cloud"  →  _submit_cloud_run(effective_example_dir, md_run_provenance)   [:681, :1989]
    resolve_cloud_config(provider, region, bucket, profile, model, queue, job_def) [cloud/config.py:90]
    validate_cloud_config(cfg, model)         [config.py:112]   region/bucket/queue/job-def syntax
    cloud_run_preflight(model, matlab_license_configured=get_compute_profile("aws").has_matlab_license)
                                              [cloud/preflight.py:42]   model in SUPPORTED_CLOUD_MODELS; ISSM needs a licence
    on any problem → _set_cloud_state("failed"), print, return None   (never billable)
    workspace_manager.stage_example_for_run(...)   →   user-owned working copy  (same as Remote)
    current_cloud_bridge().submit(staged_source, model, run_target, bucket, job_queue,
                                  job_definition, job_name, matlab_license_configured)  [:734]
      CloudBridge.submit → CloudBackend.submit → CloudManager.submit → AWSDriver.submit(**kwargs)  [cloud/drivers/aws/driver.py:520]
        (self._submitter is None for IceSheets — the legacy params.yaml path is NOT used)
        assert_cloud_run_allowed(model, matlab_license_configured)      [preflight gate, before any upload]
        stage_run_inputs(config, source, model, run_target, bucket, run_id=None, ...)  [aws/staging.py:97]
            _mint_run_id()  →  "cloud-<UTC>-<uuid8>"
            aws s3 sync <local>/  s3://<bucket>/runs/<run-id>/input/  --only-show-errors
            build_run_descriptor(...) → descriptor_is_clean() → aws s3 cp cryostack-run.json
        submit_batch_job(config, job_name, job_queue, job_definition, s3_run, model, run_target, run_id)  [aws/submit.py:130]
            build_container_overrides(s3_run, model, run_target)  → fixed 3-key env
                (CRYOSTACK_S3_RUN, CRYOSTACK_MODEL, CRYOSTACK_RUN_TARGET) + _FORBIDDEN_ENV_HINTS screen
            aws batch submit-job --job-name <sanitized>-<run-id> --job-queue <q> --job-definition <jd> --container-overrides <json>
            parse jobId
        returns {run_id, batch_job_id, s3_run, s3_input, s3_outputs, model, run_target, job_queue, job_definition, messages}
      CloudBackend wraps → ExecutionResult(job_id, working_directory=s3_run, output_directory=s3_run/outputs, metadata={...})
    _submit_cloud_run:  STATUS["batch_job_id"], STATUS["cloud_run"]
    workspace_bridge.start_run(name, model, backend="aws", execution_mode="cloud", jobid,
                               remote_directory=Path(s3_run), metadata={cloud_run, s3_outputs, run_id, region, job_queue, job_definition, provider})
    _set_cloud_state("queued")

Lifecycle (all MANUAL buttons today):
  cloud_status_btn  → cloud_runtime.status  → CloudBridge.status → CloudBackend.status
        → CloudManager.status → AWSDriver.status → legacy/aws_batch.batch_status
        → CloudBackend._normalize_state(SUBMITTED/PENDING/RUNNABLE→queued, STARTING/RUNNING→running, SUCCEEDED→completed, FAILED→failed)
        → on_status_result(job_id, state) → workspace_manager.update_run_status_by_job + _set_cloud_state
  cloud_logs_btn    → cloud_runtime.logs    → …→ legacy/aws_batch.batch_logs (CloudWatch)
  cloud_terminate_btn → cloud_runtime.terminate → …→ legacy/aws_batch.terminate_batch_job
  on_results / sync_selected_run_results → CloudBridge.results → workspace_manager.sync_cloud_results
        aws s3 sync s3://<bucket>/runs/<run-id>/outputs/  <owner_root>/…/cache/cloud_outputs/
        → local_run_cache_dir() reads cache/cloud_outputs → shared ResultPackage + Visualizer + Results panel
```

---

## 2. Implemented (C1–C5) — keep, do not rewrite

| Capability | Where | State |
|---|---|---|
| Provider-neutral config resolve + syntax validation | `cloud/config.py` | solid; deterministic queue/job-def defaults |
| Blocking preflight (model gate + MATLAB-licence gate) before any upload | `cloud/preflight.py` | solid; ISSM-only via `SUPPORTED_CLOUD_MODELS=("issm",)` |
| `CloudBridge` / `CloudBackend` / `CloudManager` / `AWSDriver` layering | `cloud/bridge.py`, `execution/cloud.py`, `cloud/manager.py`, `cloud/drivers/aws/driver.py` | works; `submit/status/logs/terminate` all wired |
| S3 input staging (whole working copy + descriptor) via `aws` CLI | `cloud/drivers/aws/staging.py` | server-minted `run_id`; `_RUN_ID_RE`; descriptor no-secrets screen |
| `aws batch submit-job` with a fixed 3-key container env | `cloud/drivers/aws/submit.py` | `_FORBIDDEN_ENV_HINTS`; job-name sanitised + run-id suffix |
| No boto3 / no static credentials — `aws` CLI + ambient chain + optional `--profile` | `cloud/drivers/aws/auth.py` | acceptance-suite guarded |
| Status normalisation to queued/running/completed/failed/unknown | `execution/cloud.py::_normalize_state` | complete |
| Status / logs / terminate | `cloud/legacy/aws_batch.py` (delegated) | works; "legacy" is a location label, not the params.yaml path |
| Gateway registers every cloud run in the experiment/workspace system | `icesheets_gateway.py::_submit_cloud_run` → `workspace_bridge.start_run(..., backend="aws", execution_mode="cloud")` | run history + status resolver + tail handler all cloud-aware |
| Per-user local result cache; S3 `outputs/` → same `outputs/{metadata,mesh,fields,model,figures}` shape → shared reader/visualizer | `workspace/manager.py::sync_cloud_results` (:980), `local_run_cache_dir` reads `cache/cloud_outputs` | **no cloud-specific results path** — already correct |
| Cloud Environment card: Provider/Region + Account/Storage/Containers/Compute status rows + Advanced (profile/prefix/queue/job-def/name) | `frontend/cryolauncher/cloud_environment.py` | present but off the shared visual system (§3) |
| `check_environment` / `prepare_environment` callbacks | `frontend/cryolauncher/cloud_runtime.py` | `prepare_environment` provisions infra — leave gated (§3) |
| ~129 offline cloud tests + gateway wiring test | `cloud/tests/`, `ui/tests/test_cloud_gateway_wiring.py` | strong base |

---

## 3. Gaps / partial — the C6 work

| # | Gap | Evidence | C6 item |
|---|---|---|---|
| G1 | **Submission blocks the Voilà kernel.** `_submit_cloud_run` runs `stage_example_for_run` + `s3 sync` + `submit-job` synchronously inside `on_run`. | `icesheets_gateway.py:1989` calls it directly; `staging.py` shells `aws s3 sync` inline | C6.4 — use the `workspace/logs.py` worker pattern (`loop.create_task` + `asyncio.to_thread`) |
| G2 | **No auto-polling.** Status only advances when the user clicks *Check status*. | `cloud_runtime.on_status` is a button handler; no task started after submit | C6.5 |
| G3 | **No auto result retrieval.** Outputs are pulled only on a manual *Preview Results* / *Results* click. | `on_results` / `sync_selected_run_results` are manual | C6.7 |
| G4 | **Panel not on the shared CryoStack visual system.** Inline `style="..."`, hardcoded hex, own border; labelled "ICESEE Cloud Environment", default job name `icesheets`. No `cryostack-*` classes, no `shared_*_panel` structure. | `cloud_environment.py` throughout | C6.2 |
| G5 | **State machine has no owner and no `staging` state.** `_CLOUD_STATES` + `_set_cloud_state` are ad-hoc strings in the gateway; states: not_configured/checking/ready/submitting/queued/running/completed/failed (no *staging*, no *cancelled*). | `icesheets_gateway.py:664` | C6.4 |
| G6 | **No cost / resource preview or charge warning before submit.** | nothing renders vCPU/memory/timeout/region/queue/job-def before `submit` | C6.11 |
| G7 | **Job-definition override is an unchecked free-text field.** `validate_cloud_config` only checks non-empty; `AWSDriver.submit` falls back to the deterministic name but accepts any string. | `config.py:135`, `driver.py:551`, `submit.py:118` | C6.2 (controlled selection) / C6.6 |
| G8 | **S3 prefix is not user-scoped.** `s3://<bucket>/runs/<run-id>/` — the run-id is server-minted (good) but there is no `<user>` segment; the job role's IAM covers `runs/*`. | `staging.py:131`; `AUDIT_agent_cloud.md` §"S3 run isolation" | C6.6 (S3 paths user/run scoped) |
| G9 | **Failure UX is one generic catch.** `_submit_cloud_run` does `except Exception as _e: print(type(_e).__name__, _e)`. No mapping to the 12 named failure classes. | `icesheets_gateway.py:744`, `cloud_runtime.py` handlers | C6.8 |
| G10 | **No license-neutral infrastructure smoke test.** `check_environment` inspects readiness but never runs S3→Batch→container→output→retrieve. There is no job that proves the pipeline without ISSM/MATLAB. | none exists | C6.10 / C6.7 |
| G11 | **Terminate has no confirmation.** `cloud_terminate_btn.on_click(on_cloud_terminate)` fires immediately. | `icesheets_gateway.py:2544` | C6.12 |
| G12 | **Offline tests missing for:** the async submit worker, the poll worker lifecycle (queued→running→completed and →failed), cancellation via the worker, auto-retrieve on completion, duplicate-poll guard, stale job, UI recovery after restart, and the smoke test. | `cloud/tests/` covers driver/staging/submit/bridge/integration but not the UI worker layer | C6.13 |

---

## 4. Duplicated / legacy

- `icesee_jupyter_book/core/cloud_runner.py` — the **legacy ICESEE `params.yaml`
  path**. Only reached when a `submitter` is injected into
  `CloudBridge`/`AWSDriver`. **The IceSheets gateway injects none**, so this file
  is dormant for IceSheets. C6 brief: *do not touch the legacy ICESEE cloud
  path.* Leave it.
- `cloud/legacy/aws_batch.py` — status/logs/terminate helpers. "legacy" is a
  directory label; these are the *current* lifecycle implementation the driver
  delegates to. Keep; a later migration moves them under `drivers/aws/`.
- `cloud/legacy/{bootstrap,provision}.py` — infra provisioning helpers used by
  `prepare_environment`. Out of C6 scope (no automatic provisioning).

---

## 5. Safety invariants already held (must not regress in C6)

- No boto3, no static credentials, no credential form — `aws` CLI + ambient
  chain + optional local `--profile` name.
- Preflight blocks a billable job on a config error / unsupported model / ISSM
  without a licence — *before* any S3 upload.
- Fixed 3-key container env + `_FORBIDDEN_ENV_HINTS` + descriptor `_SECRET_HINTS`.
- Cloud is ISSM-only (`SUPPORTED_CLOUD_MODELS`), asserted at import against
  `ModelCapabilities` and enforced in preflight + staging + the baked runner.
- Local result cache is per-`WorkspaceManager` = per authenticated user.
- Every cloud run is registered in the experiment/workspace system.

Not yet held: per-user S3 key prefix (G8); job-definition allow-list (G7);
explicit charge warning (G6); terminate confirmation (G11).

---

## 6. C6 plan (focused commits)

- **C** (`cloud state/submission UX`): non-blocking submit worker on the
  `workspace/logs.py` pattern; a single `CloudRunState` owner with a `staging`
  state; shared-style Cloud panel; **cost/resource + charge warning before
  submit**; job-definition **controlled selection** (model default + an
  explicit allow-list, no free string).
- **D** (`cloud polling/logging/failure UX`): auto-poll worker (interval,
  stop on completed/failed/cancelled, duplicate-poll guard); route logs
  through the existing log Output; map failures to the 12 named, actionable
  messages while keeping the full diagnostic in the log.
- **E** (`cloud result retrieval/integration`): on state→completed, auto
  `sync_cloud_results` then refresh the shared Results panel — no new
  `cloud_results()`/`cloud_visualizer()`.
- **F** (`cloud safety/isolation/tests`): user-scoped S3 prefix
  `runs/<safe-user>/<run-id>/`; terminate confirmation; the license-neutral
  **"Cloud infrastructure smoke test"**; the offline test matrix from G12;
  user A ≠ user B isolation test.

Then STOP at the manual AWS acceptance checkpoint — hand Brian the exact UI
steps, AWS prerequisites, environment-check commands, expected resources/cost,
S3 layout, Batch lifecycle, CryoStack outputs, and cleanup commands. No paid
run.
