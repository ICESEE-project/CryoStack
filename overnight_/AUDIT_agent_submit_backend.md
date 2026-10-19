# AUDIT — the real `SubmitBackend` adapter (PASS 4, task 4)

Read-only review + design. No HPC job run, no AWS job run. Evidence is
`file:line` at HEAD `550f35e`.

The question: can an agent-approved `RunPlan` reach a **real** HPC submission by
**composing existing CryoStack APIs**, without building a parallel submission
system and without weakening B2/B3/B4? And which functions, in which order?

**Verdict:** the composition is *possible* and the invariants *can* be
preserved — but only if the backend lives **outside** `cryostack_src/agents/`,
receives connection config from the gateway (never the plan/LLM), and re-runs
B3/B4/preflight itself. There is one genuine ambiguity (per-user identity for
*direct* SSH — see §7.3) that is left **OWNER_CHECKPOINT**. A dry-run backend
remains the default regardless.

---

## 1. The existing human submission path (remote / HPC), in call order

Source: `icesee_jupyter_book/ui/icesheets_gateway.py` `on_run` handler
(`:1740`–`:2209`).

| # | Step | Function | File:line |
|---|---|---|---|
| 1 | Resolve connector vs direct | `should_use_connector()` / `current_remote_bridge(mode=…)` | gateway `:1764`, `:2036` |
| 2 | **B3 — fresh remote-identity gate** | `enforce_remote_access(bridge, profile=, access_mode=, resolved_mode=, hpc_username=, remote_directory=, connector_online=)` → runs `verify_remote_identity` → `bridge.check_backend(command=profile.verification_command)` → compares to `hpc_username` | `cryostack_src/remote/access_state.py:238`, `:200`; gateway `:1765` |
| 3 | **B4 — Slurm resource validation** | `validate_slurm_resources(nodes, tasks, tasks_per_node, wall_time, memory, account, account_required)` | `icesee_jupyter_book/ui/shared_validation.py:81`; gateway `:1793` |
| 4 | Example path present + exists locally | inline | gateway `:1812`–`:1827` |
| 5 | **Model config validation + working-copy staging** (canonical never touched) | `md_panel.validate()` / `icepack_basic_panel.validate()` → `workspace_manager.stage_example_for_run(source_example=, extra_files=, entrypoint_transform=, overrides=)` | gateway `:1836`, `:1854`, `:1902`; `cryostack_src/workspace/manager.py:526` |
| 6 | Spack env live-probe (spack backend) | `current_remote_bridge(...).environment_status(model=, remote_base=, spack_dirname=)` — must be `is_ready` | gateway `:1947` |
| 7 | Stack provenance resolved **before** submit (container backend) | `resolve_stack(model=, profile=, selections=, container_source=, image_uri=, tested_image_key=, digest_resolver=None)` | gateway `:1996` |
| 8 | MATLAB-license fact from the **compute profile** | `get_compute_profile(cluster).matlab_license_config()`; ISSM+container+`None` → block | gateway `:2017`–`:2034` |
| 9 | **Submit** | `RemoteBridge.submit(direct_kwargs=…)` / `(connector_kwargs=…)` → `RemoteBackend(submitter=…).submit(**kwargs)` → `submit_remote_icesheets(**kwargs)` or `submit_remote_icesheets_via_connector(**kwargs)` | `cryostack_src/remote/bridge.py:48`; `cryostack_src/models/submission.py:671`, `:270` |
| 10 | **Register the run** | `workspace_bridge.start_run(name=, model=, backend=, execution_mode=, jobid=, remote_directory=, log_file=, metadata={host,user,port,access_mode,cluster_name,**md_run_provenance}, container=, software=)` | `cryostack_src/workspace/bridge.py:26`; gateway `:2127` |
| 11 | Experiment tracking + workspace save | `experiment_bridge.create(...)`, `workspace_bridge.save(...)` | gateway `:2151`, `:2191` |
| 12 | Monitoring | `build_remote_runtime_callbacks(...)` → `RemoteBridge.status/logs` | gateway `:2216` |

`submit_remote_icesheets` itself (`submission.py:671`): preflight MATLAB env
(`_matlab_container_env`, `:719`), resolve remote base dir
(`require_remote_base_dir` → `expand_remote_home` → `resolve_remote_abs_path`,
`:726-728`), compute `remote_run_dir` /
`remote_submit_script` (`:734-735`), build the sbatch script, `rsync`/`scp` the
staged dir, `sbatch` it — all over `ssh_run` / `connector_ssh` imported at
module top (`submission.py:9-17`).

---

## 2. What a `RunPlan` carries vs what submission needs

`RunPlan._digest_material()` (`planning.py:96`): `application, model, example,
execution_mode, compute_resource, backend, run_target, parameter_overrides,
datasets, slurm{job_name,nodes,tasks,tasks_per_node,wall_time,memory,account}`.

Submission **also** needs, and the plan deliberately does **not** carry (so the
digest never depends on a user's credentials or host layout):

| Needed | Source that is NOT the plan |
|---|---|
| `host`, `user`, `port` | gateway connection panel / `ComputeProfile` |
| `remote_base_dir`, `remote_tag`, `exec_dir` | gateway connection panel |
| connector `session_id` | `SESSION["id"]` (relay-owned, per session) |
| `image_uri`, `container_source`, spack repo/dirname/mode | gateway software panel / profile defaults |
| `matlab_license` config | `get_compute_profile(cluster).matlab_license_config()` |
| `stack_software` / `stack_provenance` | `resolve_stack(...)` |
| the canonical example's **local path** | example registry, resolved read-only |

**Design consequence:** the `SubmitBackend` is necessarily a **gateway-side /
integration-layer adapter**. It is constructed with a *connection context*
(host, user, port, remote dirs, session, profile, software selections) that the
authenticated user configured in the gateway — the same values the human Run
button uses — and it receives the approved `plan` for the scientific + resource
intent. It must never accept any of those connection values from the plan, a
tool argument, or LLM output.

---

## 3. Proposed composition — exact calls, in order

`RemoteSubmitBackend.submit(plan: RunPlan, *, ctx: ToolContext) -> str`:

```
 0. assert ctx.can(Permission.EXECUTE)                        # defensive; coordinator already checked
 1. profile = get_compute_profile(plan.compute_resource)      # re-derive, do not trust a passed profile
    assert profile.name == self._conn.profile.name            # plan resource == wired connection
 2. B3  enforce_remote_access(
          self._conn.bridge, profile=profile,
          access_mode=self._conn.access_mode,
          resolved_mode=self._conn.resolved_mode,
          hpc_username=self._conn.hpc_username,
          remote_directory=self._conn.remote_base_dir,
          connector_online=self._conn.connector_online)
        -> gate.ok is False  => raise SubmitBlocked("B3: " + messages)
        # this RUNS profile.verification_command fresh over the transport
 3. B4  msgs = validate_slurm_resources(
          nodes=plan.slurm.nodes, tasks=plan.slurm.tasks,
          tasks_per_node=plan.slurm.tasks_per_node,
          wall_time=plan.slurm.wall_time, memory=plan.slurm.memory,
          account=plan.slurm.account, account_required=profile.account_required)
        msgs => raise SubmitBlocked("B4: " + msgs)
 4. preflight:
      matlab_license = profile.matlab_license_config()        # the CONFIG, from the profile
      if plan.model == "issm" and plan.backend == "container" and matlab_license is None:
          raise SubmitBlocked("MATLAB licence not configured for {profile.name}")
      if plan.execution_mode == "cloud": raise SubmitBlocked   # this backend is remote-only
      assert get_model_capabilities(plan.model).supports_mode("remote")
 5. resolve the example -> canonical local dir (READ-ONLY):
      ex = resolve_example(ctx, plan.model, plan.example)      # same resolver planning uses
      canonical_dir = ex.path                                   # never written to
 6. run_target hygiene:
      rt = _safe_basename(plan.run_target or adapter.choose_run_target(...))
      assert (canonical_dir / rt).is_file()                     # must exist in the example
 7. stage a user-owned working copy (canonical untouched):
      staged = ctx.workspace_manager.stage_example_for_run(
          source_example=str(canonical_dir),
          extra_files=adapter_extra_files(plan.model, plan.parameter_overrides),
          entrypoint=rt,
          entrypoint_transform=adapter_override_transform(plan.model, plan.parameter_overrides),
          overrides=plan.parameter_overrides or None)
      # WorkspaceManager confines staged.path to <owner_root>/.cryostack/working/
 8. datasets: staged already copied example-referenced datasets via
    _stage_referenced_datasets; plan.datasets that are user-workspace datasets
    are resolved through ctx.workspace_manager only (user-scoped), never a path.
 9. stack provenance (container backend):
      stack = resolve_stack(model=plan.model, profile=self._conn.software_profile,
                            selections=self._conn.software_selections,
                            container_source=self._conn.container_source,
                            image_uri=self._conn.image_uri,
                            tested_image_key=self._conn.tested_image_key,
                            digest_resolver=None)
10. SUBMIT via the existing function (injected, tested with a fake):
      result = self._submitter(                                 # submit_remote_icesheets[_via_connector]
          host=self._conn.host, user=self._conn.user, port=self._conn.port,
          remote_base_dir=self._conn.remote_base_dir, remote_tag=self._conn.remote_tag,
          backend=plan.backend, model=plan.model,
          example_dir=str(staged.path), exec_dir=self._conn.exec_dir,
          image_uri=self._conn.image_uri, container_source=self._conn.container_source,
          spack_enable=self._conn.spack_enable, spack_repo_url=self._conn.spack_repo_url,
          spack_dirname=self._conn.spack_dirname,
          spack_install_if_needed=False,                        # NEVER install at submit
          spack_install_mode=self._conn.spack_install_mode,
          spack_slurm_dir="", spack_pmix_dir="",
          slurm_time=plan.slurm.wall_time, slurm_job_name=_safe_job_name(plan.slurm.job_name),
          slurm_nodes=plan.slurm.nodes, slurm_ntasks=plan.slurm.tasks,
          slurm_tpn=plan.slurm.tasks_per_node, slurm_part=self._conn.slurm_partition,
          slurm_mem=plan.slurm.memory, slurm_account=plan.slurm.account,
          slurm_mail="",                                        # no LLM-supplied mail
          test_mode=False, run_file=rt,
          stack_log_line=stack_log_line(stack), stack_software=stack.get("software") or {},
          matlab_license=matlab_license)
11. register the run (owned by ctx.user):
      run = workspace_bridge.start_run(
          name=Path(result.working_directory).name, model=plan.model,
          backend=plan.backend, execution_mode="remote",
          jobid=result.job_id, remote_directory=Path(result.working_directory),
          log_file=Path(result.log_path) if result.log_path else None,
          metadata={ "cluster_name": profile.name, "access_mode": self._conn.access_mode,
                     "parameter_overrides": plan.parameter_overrides,
                     "working_copy": str(staged.path),
                     "working_copy_from_canonical": staged.from_canonical,
                     **run_manifest_stamp(trace_id=ctx.trace.trace_id,
                                          plan_digest=plan.digest(),
                                          approver_user_id=mp.approval.approver_user_id,
                                          approved_at=mp.approval.approved_at) },
          container=stack.get("container") or {}, software=stack.get("software") or {})
12. return result.job_id
```

Every argument to `_submitter` is either: a `plan` scalar already schema-typed
(`SlurmRequest` ints; `wall_time`/`account`/`memory`/`job_name` — see §7.4),
a validated **basename** (`rt`), a `parameter_overrides` dict already
schema-validated by the model spec, or a **connection value the gateway user
set**. No raw path, no command, no arbitrary env, no LLM free string.

---

## 4. Invariant checklist

| # | Invariant | Preserved by | Confidence |
|---|---|---|---|
| 1 | Fresh B3 verification at submission | step 2 calls `enforce_remote_access` which calls `verify_remote_identity` → `bridge.check_backend(profile.verification_command)` **every time**, no stale cache (`access_state.py:252-270`) | HIGH |
| 2 | Approved scientific config cannot change after approval | The coordinator calls `assert_approved_for_execution(mp)` (`execution.py:152`) **immediately before** `self._backend.submit(plan, ctx=ctx)` (`execution.py:208`); the backend receives `mp.plan` and must not re-read from any mutable source. Digest = `sha256` of scientific+resource fields. | HIGH |
| 3 | Slurm validation still happens | step 3 re-runs `validate_slurm_resources` on `plan.slurm` (the same B4 function) | HIGH |
| 4 | Canonical examples immutable | step 5 resolves the canonical dir **read-only**; step 7 `stage_example_for_run` copies to `<owner_root>/.cryostack/working/` when `from_canonical` (`manager.py:552-556`) and only writes into the **copy** (`manager.py:558-566`). Add an assertion that `staged.path != canonical_dir`. | HIGH |
| 5 | User working copy is used | step 10 passes `example_dir=str(staged.path)` | HIGH |
| 6 | Datasets stage through the existing mechanism | `stage_example_for_run` calls `_stage_referenced_datasets` (`manager.py:568`); `plan.datasets` resolved only via `ctx.workspace_manager` (user-scoped) | MEDIUM — needs a dataset-name → workspace-dataset resolver (plan carries names only) |
| 7 | Run provenance records the approved configuration | step 11 metadata includes `parameter_overrides` + `run_manifest_stamp(plan_digest=plan.digest(), …)` | HIGH |
| 8 | No arbitrary LLM command reaches SSH | `_submitter` takes no command parameter; it builds the sbatch script itself from typed fields. `run_file=rt` is a validated basename. `remote_module_lines`/`remote_export_lines` default `""` and are **not** exposed. | HIGH |
| 9 | No arbitrary LLM env vars reach execution | `submit_remote_icesheets` builds env from `matlab_license` (profile config) + fixed lines; there is no caller env dict. `parameter_overrides` are model-schema-validated values injected into a **working copy of the entrypoint**, not into the process env. | HIGH |

---

## 5. Where the backend must live

**Not** `cryostack_src/agents/` — `submit_remote_icesheets` transitively imports
`ssh_run`, `connector_ssh`, `connector_slurm_submit` (`submission.py:9-17`), all
in `policy.PROHIBITED_SYMBOLS` (`policy.py:22-32`). Putting the backend in
`agents/` would either fail `assert_tool_modules_are_clean` or force removing
those names from the scan — both unacceptable.

Proposed: a **new top-level package `cryostack_src/agent_execution/`** (sibling
to `agents/`, `cloud/`, `remote/`), holding `RemoteSubmitBackend`,
`ConnectionContext`, `SubmitBlocked`. It is imported by the gateway when it
wires the coordinator, never by a tool module. The agent core stays clean.

---

## 6. Tests possible tonight (no HPC)

`RemoteSubmitBackend` takes an **injected** `submitter` (like `RemoteBridge`
takes `direct_submitter`) and an injected `bridge` (duck-typed
`check_backend`). Tests:

- B3 gate blocks when the fake `check_backend` returns a mismatched `whoami` →
  `SubmitBlocked`, `_submitter` never called.
- B4 gate blocks a `nodes=0` plan → `_submitter` never called.
- MATLAB preflight blocks ISSM+container when the fake profile has no licence.
- canonical dir is never written (assert mtime / content unchanged).
- `_submitter` is called with `example_dir == staged.path` and
  `run_file == <validated basename>`.
- a `plan.run_target` of `../../etc/x` or `x; rm -rf /` is rejected before
  staging.
- a `plan.slurm.job_name` with shell metacharacters is sanitized.
- the registered `RunInfo.metadata` carries `agent_assist.plan_digest ==
  plan.digest()` and `assert_no_agent_chatter` passes on it.
- digest re-bind: mutate `mp.plan` after approval → coordinator blocks before
  the backend is entered (already covered by `test_r2`).

---

## 7. Open items / ambiguities

### 7.1 Connection context provenance — RESOLVED
The `ConnectionContext` is built by the gateway from the authenticated user's
own connection panel + `SESSION`. It is not serialized, not in the plan, not
in the trace. The backend asserts `profile.name == plan.compute_resource`.

### 7.2 `resolve_stack` for the container backend — RESOLVED
Same call the human path makes (`gateway:1996`); inputs are gateway software-
panel values, not plan/LLM. Failure → `SubmitBlocked` before submit.

### 7.3 Direct-SSH per-user identity — **OWNER_CHECKPOINT**
`enforce_remote_access` already emits `"[access][WARN] Direct SSH from the
CryoStack server uses a shared service-account identity and is NOT per-user
isolated"` (`access_state.py:287-292`). For an **agent-initiated** submit this
is worse than for a human click, because the human at least saw the warning.
**Decision needed:** should an agent `SubmitBackend` refuse `resolved_mode ==
"direct"` entirely and require the Connector (per-user relay identity), or
inherit the human policy (warn + proceed)? Recommendation: **agent submits
require the Connector**; direct-SSH agent submit is `SubmitBlocked` until an
owner decision.

### 7.4 `slurm.job_name` / `slurm.account` sanitization — fix in planning
`validate_slurm_resources` does not take or check `job_name`
(`shared_validation.py:81-128`); `account` is only checked for presence. The
backend applies `_safe_job_name()` (alnum + `-_`, ≤ N chars) and treats
`account` as an opaque token passed to `--account` (already quoted by
`slurm_optional_lines`). Add a charset check to `RunPlan.__post_init__` or
`prepare_run_plan` so an invalid `job_name`/`account` never gets into an
approved plan. (Feeds task 5.)

### 7.5 `datasets` resolution — needs a small resolver
`plan.datasets` are names. `stage_example_for_run` stages *example-referenced*
datasets automatically. If a plan names an *additional* user dataset, the
backend must resolve it via `ctx.workspace_manager.list_datasets()` and pass it
as an `extra_files` / dataset reference — **user-scoped, name-matched, never a
path**. If a named dataset is not in the user's workspace → `SubmitBlocked`.

---

## 8. Recommendation

1. **Implement now (safe, testable):**
   - `DryRunSubmitBackend` in `cryostack_src/agents/execution.py` — an explicit,
     inspectable no-op backend (makes the default behaviour a named object).
   - `cryostack_src/agent_execution/remote_backend.py` — `RemoteSubmitBackend`
     + `ConnectionContext` + `SubmitBlocked`, composing the exact calls in §3,
     with the injected `submitter`/`bridge` seams, and the full §6 test suite
     using fakes. **Not wired into the gateway.**
2. **OWNER_CHECKPOINT:**
   - §7.3 direct-SSH agent policy.
   - Wiring `RemoteSubmitBackend` into `icesheets_gateway` (needs a live PACE
     run to validate end-to-end; and the panel must gain an explicit
     "Submit approved run" affordance separate from the human Run button).
   - Cloud `SubmitBackend` — deferred entirely (see `AUDIT_agent_cloud.md` §
     "Recommended invariants"; the driver-layer `matlab_license_configured`
     bool and `job_definition` free-string need tightening first).
3. **Feeds task 5:** `job_name`/`account` charset validation in planning;
   `run_target` existence + basename check in `prepare_run_plan`.
