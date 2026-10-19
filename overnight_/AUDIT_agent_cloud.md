# AUDIT — Agent layer → AWS cloud execution path (PASS 4, task 13)

Read-only review. No AWS commands issued, nothing enabled. Evidence is
`file:line` against the working tree at HEAD `5453605`.

## Summary

There is currently **no wired connection** between the agent layer
(`cryostack_src/agents/`) and the cloud submission path (`cryostack_src/cloud/`).
The agent execution coordinator is dry-run only and ships with **no
`SubmitBackend`** (`cryostack_src/agents/execution.py:14-18`, `:83-89`,
`:198-206`). The cloud path is today driven exclusively by the human
Voila/ipywidgets gateway (`icesee_jupyter_book/ui/icesheets_gateway.py:633`).
This audit describes (a) the existing pipeline, and (b) where a future agent
`SubmitBackend` would attach and how it could be abused if written carelessly.

Key structural facts:
- The `RunPlan` dataclass **cannot even express** a bucket, region, profile,
  AWS Batch job definition, job queue, or S3 run-id — its digest material is
  purely scientific/resource intent (`cryostack_src/agents/planning.py:96-114`).
  A `SubmitBackend` that receives only a `RunPlan` has no agent-supplied
  channel for those values.
- The low-level driver `AWSDriver.submit(**kwargs)` **does** accept
  `job_definition`, `job_queue`, `bucket`, `run_id`,
  `matlab_license_configured`, `job_name` as caller kwargs
  (`cryostack_src/cloud/drivers/aws/driver.py:543-554`). Whether an agent can
  abuse the cloud path depends entirely on **which layer** the `SubmitBackend`
  calls and **what it forwards**.

---

## Existing cloud pipeline (call order)

Entry points:
- `cryostack_src/cloud/__init__.py:27-52` re-exports the public surface
  (`cloud_run_preflight`, `assert_cloud_run_allowed`, `SUPPORTED_CLOUD_MODELS`,
  `stage_run_inputs`, `submit_batch_job`, `AWSDriver`, `CloudRunConfig`, …).
- `CloudBridge` (`cryostack_src/cloud/bridge.py:12-48`) is the
  "presentation-neutral" façade. `CloudBridge.submit(**kwargs)` drops
  presentation kwargs and calls `self.backend.submit(**kwargs)`
  (`bridge.py:37-48`).

Call chain for a real submit:

1. **Gateway handler** `_submit_cloud_run(staged_dir, md_provenance)` —
   `icesee_jupyter_book/ui/icesheets_gateway.py:633`
   - `resolve_cloud_config(provider="aws", region, bucket, profile, model,
     job_queue, job_definition)` → `CloudRunConfig`
     (`icesheets_gateway.py:637-645`; impl `cryostack_src/cloud/config.py:90-109`).
     Queue/job-def default to deterministic names `cryostack-queue` /
     `cryostack-<model>` when the user field is blank.
   - `_lic = get_compute_profile("aws").has_matlab_license`
     (`icesheets_gateway.py:646`) — license **fact** (bool), not a value.
   - `validate_cloud_config(_cfg, model=_model)` (`config.py:112-138`): provider
     in `("aws",)`, region regex, bucket regex, non-empty queue + job
     definition.
   - `cloud_run_preflight(model=_model, matlab_license_configured=_lic)`
     (`cryostack_src/cloud/preflight.py:42-61`).
   - On any problem: set failed state, print, `return None` — **never billable**
     (`icesheets_gateway.py:651-658`).
   - `workspace_manager.stage_example_for_run(...)` for a user-owned working
     copy if the staged dir is still the canonical example
     (`icesheets_gateway.py:662-674`).
   - `current_cloud_bridge().submit(staged_source=…, model, run_target, bucket,
     job_queue, job_definition, job_name, matlab_license_configured=_lic)`
     (`icesheets_gateway.py:686-695`).
2. **`CloudBridge.submit`** → `CloudBackend.submit` (`bridge.py:37-48` →
   `cryostack_src/execution/cloud.py:81-94`).
3. **`CloudBackend.submit`** → `self.manager.submit(provider, region, profile,
   submitter=self._submitter, **kwargs)` (`execution/cloud.py:88-94`).
4. **`CloudManager.submit`** → `AWSDriver(...).submit(**kwargs)`
   (`cryostack_src/cloud/manager.py:215-232`, `:45-70`).
5. **`AWSDriver.submit(**kwargs)`** — `cryostack_src/cloud/drivers/aws/driver.py:520-602`:
   1. If `self._submitter is not None` → legacy path wins:
      `return self._submitter(**kwargs)` (`driver.py:535-536`) — legacy
      `params.yaml` path in `icesee_jupyter_book/core/cloud_runner.py:55-160`.
   2. Import `assert_cloud_run_allowed`, `stage_run_inputs`, `submit_batch_job`,
      `JOB_QUEUE_NAME`, `job_definition_name` (`driver.py:538-541`).
   3. Read kwargs: `staged_source`, `model`, `run_target` (default `runme.m`),
      `bucket`, `working_directory`, `run_id`, `job_name` (default `cryostack`),
      `job_queue` (default `JOB_QUEUE_NAME`), `job_definition` (default
      `job_definition_name(model)`), `matlab_license_configured` (default
      `False`), `s3`, `aws` (`driver.py:543-554`).
   4. Guard: `staged_source` and `bucket` required (`driver.py:556-559`).
   5. **Gate** `assert_cloud_run_allowed(model=model,
      matlab_license_configured=matlab_license_configured)` — before any upload
      (`driver.py:561-564`).
   6. **Stage** `stage_run_inputs(self.config, source=staged_source, model,
      run_target, bucket, run_id, working_directory, s3=s3)`
      (`driver.py:566-576`).
   7. **Submit** `submit_batch_job(self.config, job_name, job_queue,
      job_definition, s3_run=staging.s3_run, model, run_target,
      run_id=staging.run_id, aws=aws)` (`driver.py:578-589`).
   8. Return dict `{run_id, batch_job_id, s3_run, s3_input, s3_outputs, model,
      run_target, job_queue, job_definition, messages}` (`driver.py:591-602`).
6. **`stage_run_inputs`** — `cryostack_src/cloud/drivers/aws/staging.py:97-173`:
   - `bucket` required (`:115-116`); `is_supported_cloud_model(model)` else
     raise (`:117-119`).
   - `_local_dir(source)` — resolves `StagedExample.path` or path, must be a
     dir, refuses filesystem root (`:86-94`).
   - `run_target` must exist as a file in the staged dir (`:122-125`).
   - `run_id = (run_id or _mint_run_id()).strip()`; `_mint_run_id()` =
     `cloud-<UTC-timestamp>-<uuid4[:8]>` (`:79-83`, `:127`); validated against
     `_RUN_ID_RE = \A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z` (`:61`, `:128-129`).
   - `s3_run = f"s3://{bucket}/runs/{run_id}"`, `s3_input = f"{s3_run}/input"`,
     `s3_outputs = f"{s3_run}/outputs"` (`:131-133`).
   - **Upload 1:** `aws s3 sync <local>/ <s3_input>/ --only-show-errors`
     (`:139-145`).
   - **Descriptor:** `build_run_descriptor(model, run_target=target,
     working_directory)` (`cryostack_src/cloud/runtime.py:71-101`), then
     `descriptor_is_clean(descriptor)` no-secrets check (`runtime.py:104-117`).
   - **Upload 2:** descriptor → `NamedTemporaryFile`, `aws s3 cp <tmp>
     <s3_input>/cryostack-run.json` (`:153-166`).
7. **`submit_batch_job`** — `cryostack_src/cloud/drivers/aws/submit.py:130-167`:
   - `build_submit_job_args(job_name, job_queue, job_definition, s3_run, model,
     run_target, run_id)` (`:105-127`):
     - `job_queue` and `job_definition` must be non-empty (`:116-119`).
     - `build_container_overrides(s3_run, model, run_target)` (`:82-102`):
       requires `s3_run` starts `s3://`, `model` non-empty, `run_target` not
       `/`/`~`-prefixed and no `..`; builds exactly **three** env entries
       `CRYOSTACK_S3_RUN`, `CRYOSTACK_MODEL`, `CRYOSTACK_RUN_TARGET`; then
       `_FORBIDDEN_ENV_HINTS` no-secrets check on the JSON blob (`:50-54`,
       `:99-101`).
     - Args: `["batch","submit-job","--job-name", sanitize_job_name(job_name,
       suffix=run_id), "--job-queue", job_queue, "--job-definition",
       job_definition, "--container-overrides", json(overrides)]` (`:121-127`).
   - `run_aws` → nonzero → `CloudSubmitError` (`:152-154`); parse `jobId`
     (`:155-160`).
8. **`run_aws`** — `cryostack_src/cloud/drivers/aws/auth.py:69-84`:
   `subprocess.run(["aws"] + (["--profile", profile] if set) + (["--region",
   region] if set) + arguments, capture_output=True)`. **No boto3, no explicit
   credentials.**
9. Back in the gateway: `CloudBackend.submit` wraps the dict into an
   `ExecutionResult` (`execution/cloud.py:100-206`), then `_submit_cloud_run`
   registers the run: `workspace_bridge.start_run(name=<run_id or job_id>,
   model, backend="aws", execution_mode="cloud", jobid=_job_id,
   remote_directory=Path(s3_run), log_file=None, metadata={**md_provenance,
   cloud_run, s3_outputs, run_id, region, job_queue, job_definition,
   provider="aws"})` (`icesheets_gateway.py:717-736`).

Lifecycle ops (`status/logs/terminate`) delegate to
`cryostack_src/cloud/legacy/aws_batch.py` (`driver.py:96-100`, `:604-630`).

---

## Where the agent RunPlan would plug in

- `DryRunExecutionCoordinator.execute(ctx, mp, dry_run=True)` —
  `cryostack_src/agents/execution.py:112-216`. Phase order:
  `REVALIDATE → CHECK_APPROVAL → RESOLVE_IDENTITY → STAGE → PRECHECK_SCHEDULER
  → SUBMIT` (`:31-38`, `:133-206`).
- Gates enforced **before** the SUBMIT boundary:
  1. Permission ceiling: non-dry-run requires `ctx.can(Permission.EXECUTE)`
     (`:134-139`; `EXECUTE = 40`, `PLAN = 20` — `permissions.py:14-25`).
  2. Live re-validation: `_revalidate` re-runs `validate_run_plan` and blocks
     on any error (`:141-150`, `:219-225`).
  3. Approval: `assert_approved_for_execution(mp)` — `APPROVED` **and** live
     digest == approved digest (`:152-162`; `approval.py:162-175`).
- SUBMIT boundary: if `dry_run or self._backend is None` → **described**
  command only, `submitted=False`, return (`:198-206`). Only if a
  `SubmitBackend` was injected **and** `dry_run=False` does it call
  `self._backend.submit(plan, ctx=ctx)` then `mp.mark_executing()` (`:208-216`).
- `SubmitBackend` is a `Protocol` — "Implementations live outside the agents
  package … Must perform B3 remote-identity verification before issuing
  anything." (`:83-89`). **No implementation exists in the tree.**
- The described cloud command hard-codes deterministic names and only two env
  facts, no host/account/credentials: `_describe_submission` (`:96-109`).
- `RunAssistant` is hard-capped at `Permission.PLAN` (`assistant.py:28-29`,
  `:88-92`); approval is human-only (`approval.py:14-16`, `:101-104`); shipped
  tools are all OBSERVE/PLAN read-only (`planning_tools.py:24-28`, `:82-88`,
  `:154-159`); `default_registry()` registers only `readonly_tools` +
  `planning_tools` (`registry.py:103-113`).

---

## Job-definition selection

- Deterministic mapping: `JOB_DEFINITION_NAMES = {"issm": "cryostack-issm",
  "icepack": "cryostack-icepack"}`; `job_definition_name(model)` returns that or
  `f"cryostack-{model}"` fallback
  (`cryostack_src/cloud/drivers/aws/batch_config.py:45-48`, `:133-134`).
- `AWSDriver.submit`: job definition is **caller-supplied with a deterministic
  fallback** — `job_definition = (kwargs.get("job_definition") or "").strip() or
  job_definition_name(model)` (`driver.py:551`). Same for `job_queue`
  (`:550`).
- `resolve_cloud_config` does the same (`config.py:99-109`);
  `validate_cloud_config` only checks **non-empty** — no allow-list
  (`config.py:133-137`). `submit_batch_job` only checks truthy (`submit.py:118-119`)
  then passes straight to `aws batch submit-job --job-definition <value>`.
- The gateway UI exposes an editable `batch_job_def` field
  (`icesheets_gateway.py:644`, `:1050`).
- The provisioner only registers `cryostack-issm` (+ optional `cryostack-icepack`
  behind `include_icepack`) pinned to a digest-verified ECR image
  (`driver.py:191-257`, `batch_provision.py:257-369`). Nothing restricts
  submission to those names.

**Conclusion:** job-definition selection is caller-supplied at every layer an
agent backend could call. Only the deterministic default and the agent
`_describe_submission` string are safe-by-construction. The `RunPlan` has no
job-definition field, so a plan-only backend is safe unless it deliberately
adds one.

---

## Env-var injection surface

- `build_container_overrides(*, s3_run, model, run_target)` emits a **fixed
  3-key** env (`CRYOSTACK_S3_RUN`, `CRYOSTACK_MODEL`, `CRYOSTACK_RUN_TARGET`) —
  no parameter for arbitrary env (`submit.py:82-102`).
- Values validated: `s3_run` `s3://` prefix; `model` non-empty; `run_target`
  not `/`/`~`-prefixed, no `..` (`submit.py:87-92`).
- No-secrets guard: `_FORBIDDEN_ENV_HINTS = ("aws_access","aws_secret",
  "aws_session","secret","token","password","mlm_license","license_file",
  "credential")` over the lowercased JSON (`submit.py:50-54`, `:99-101`).
- The runner script is **baked into the job definition command** at
  provisioning (`runtime.py:120-183`, used `driver.py:242-252`) — a submit
  cannot change the entrypoint, only the 3 env values.
- **Weakness — `run_target` hygiene is inconsistent:** `build_run_descriptor`
  applies `_RUN_TARGET_RE = \A[A-Za-z0-9][A-Za-z0-9._/-]{0,255}\Z`
  (`runtime.py:59`, `:86-90`), but `build_container_overrides` only does the
  prefix/`..` checks (`submit.py:91-92`). In the full `AWSDriver.submit` flow,
  `stage_run_inputs` requires the target to be an existing file
  (`staging.py:122-125`) and runs the regex-enforced descriptor builder — so a
  metacharacter `run_target` is caught there. A caller invoking
  `submit_batch_job` **directly**, skipping staging, could pass a payload that
  lands in `CRYOSTACK_RUN_TARGET`, which the runner interpolates into a
  `matlab -batch "... run('${RUN_TARGET}') ..."` string (`runtime.py:141`,
  `:151-152`). **Recommend `submit.py` reuse `_RUN_TARGET_RE`.**

**Conclusion:** the sanctioned submit builder gives **no arbitrary-env
channel** and screens for secret-like keys. The only concern is `run_target`
value hygiene when `submit_batch_job` is called without `stage_run_inputs`.

---

## S3 run isolation

- `s3_run = f"s3://{bucket}/runs/{run_id}"` (`staging.py:131`).
- `run_id`: `kwargs.get("run_id")` → used verbatim after passing the permissive
  `_RUN_ID_RE` (`driver.py:548`, `staging.py:61`, `:127-129`) — **not** bound to
  a user/session or the minted `cloud-<ts>-<uuid>` shape.
- `bucket`: caller kwarg (`driver.py:546`); default is a **single account-wide**
  bucket `cryostack-runs-<account-id>` (`storage.py:59-88`, `:253-259`). **Not
  per-user.**
- IAM: the Batch job role grants `s3:GetObject/PutObject/DeleteObject` on
  `arn:aws:s3:::<bucket>/runs/*` and `s3:ListBucket` on the whole `runs` prefix
  (`iam_policies.py:94-143`). Every cloud job can read/overwrite/delete **every**
  run — no per-user or per-run IAM scoping.
- `submit_batch_job(s3_run=...)` accepts any `s3://` URI directly
  (`submit.py:82-88`, `:130-141`).
- In the full `AWSDriver.submit` flow, `s3_run` is `staging.s3_run`
  (server-derived from `bucket` + `run_id`) — so the abuse requires influencing
  `bucket` or `run_id`.

**Conclusion:** there is **no cryptographic or IAM-level S3 run isolation
between users**. Isolation depends entirely on the caller letting `run_id` be
minted server-side, a per-user bucket/prefix that does not exist today, and
callers never being handed another user's run-id.

---

## Credential handling

- All AWS calls go through `run_aws(config, args)` = `subprocess.run(["aws"] +
  optional --profile + optional --region + args)` (`auth.py:48-84`). **No
  boto3, no `Session(...)`, no `assume_role`** anywhere under
  `cryostack_src/cloud/`.
- Credentials are whatever the ambient `aws` CLI resolves (env, named profile,
  instance/task role). `config.profile` is a **local CLI profile selector**,
  not a credential (`config.py:38-41`, `:70-79`; `models.py:32-43`).
- `profile` is caller-supplied (`bridge.py:15-28`,
  `icesheets_gateway.py:596-612`) → `run_aws` `--profile <value>`
  (`auth.py:48-66`). **Minor abuse vector:** a caller naming a different,
  more-privileged profile that exists on the host would run AWS calls under it.
  It never becomes a stored credential and is never placed in container env.
- The container gets AWS credentials only from the Batch task role
  (`batch_config.py:164-205`, `batch_provision.py:257-273`); coordinator
  `RESOLVE_IDENTITY` for cloud is `skipped` (`execution.py:171-174`).
- Two no-secrets screens: container overrides `_FORBIDDEN_ENV_HINTS`
  (`submit.py:50-54`, `:99-101`); run descriptor `_SECRET_HINTS` incl.
  `aws_access_key`, `aws_secret`, `mlm_license`, `ssh`, `password`, `token`,
  `/home/`, `/users/`, `credential` (`runtime.py:104-117`, `staging.py:150-151`).
- Agent policy source-scan forbids tool modules from referencing `os.environ`,
  `getpass`, `matlab_license_config`, `deployment_token`, ssh helpers
  (`policy.py:22-36`, `:63-76`; `test_r2_malicious_agent.py:174-175`).

**Conclusion:** **no path where a caller-supplied value becomes an AWS
credential** or is placed in container env. The only caller-controlled
credential-adjacent input is the local CLI `profile` name.

---

## Agent-abuse assessment

Assessed for a hypothetical agent-approved cloud `RunPlan` reaching a future
`SubmitBackend`.

### 1. Arbitrary AWS Batch job definition? — **NO today / YES if a backend forwards it**
No agent→cloud wiring; `RunPlan` has no job-definition field; the described
command hard-codes `<cryostack-{plan.model}>`. But `AWSDriver.submit` /
`submit_batch_job` / `resolve_cloud_config` accept `job_definition` as a free
string with only a non-empty check + deterministic fallback (`driver.py:551`,
`submit.py:118-127`, `config.py:133-137`). **The safe default exists; the
enforcement does not.**

### 2. Smuggle credentials / arbitrary env into the container? — **NO**
Fixed 3-key env, no arbitrary-env parameter, `_FORBIDDEN_ENV_HINTS` +
`_SECRET_HINTS` screens, task-role-only credentials. Residual: `run_target`
value is not regex-screened in `submit.py` (only in staging).

### 3. Bypass the MATLAB-license preflight? — **YES if a backend calls the driver / NO via the gateway**
`assert_cloud_run_allowed` blocks only when `model == "issm" and not
matlab_license_configured` (`preflight.py:42-61`). In `AWSDriver.submit`,
`matlab_license_configured` is a **caller-supplied boolean** (`driver.py:552`,
`:561-564`) — never re-derived server-side inside the driver. A caller passing
`True` skips the gate. The gateway is safe (always passes the real
`get_compute_profile("aws").has_matlab_license` and runs `cloud_run_preflight`
first). **A `SubmitBackend` must re-assert it from `get_compute_profile`.**

### 4. Bypass the model-support check (icepack on cloud)? — **NO**
Defence in depth: `SUPPORTED_CLOUD_MODELS = ("issm",)` (`runtime.py:50`);
`cloud_run_preflight` blocks (`preflight.py:52-56`); `assert_cloud_run_allowed`
raises (`preflight.py:64-70`, called `driver.py:561-564`); `stage_run_inputs`
raises (`staging.py:117-119`); the baked runner `fail 64` for icepack
(`runtime.py:155-157`); provisioner gates the icepack job def behind
`include_icepack` (`batch_provision.py:362-369`); `validate_run_plan` adds an
**error** finding (`planning_tools.py:137-141`) and `cloud_supported` is
import-time asserted == `SUPPORTED_CLOUD_MODELS` membership
(`capabilities.py:132-141`); a plan with an error finding cannot be approved
(`approval.py:91-93`) and is re-blocked at `_revalidate` (`execution.py:141-150`).

### 5. Reference another user's S3 run? — **YES (structurally possible; no isolation control)**
Single shared bucket, no per-user namespacing (`staging.py:131`,
`storage.py:59-88`); `run_id`/`bucket` are caller kwargs;
`submit_batch_job(s3_run=...)` accepts any `s3://` URI; job-role IAM allows
read/write/delete across the entire `runs/*` prefix (`iam_policies.py:94-143`).
The `RunPlan` cannot express a run-id or bucket, so a strict plan-only backend
that always mints its own run-id is safe — but nothing in `cloud/` enforces
that, and the running container can touch any run's objects regardless.

### 6. Submit without approval? — **YES (the cloud path itself has no approval-object gate)**
The **gateway** cloud path is a human UI action with no `ManagedPlan`/`Approval`
involvement — by design (it is the human path). For an **agent**: today it
cannot submit at all. If a `SubmitBackend` is wired via the coordinator,
approval **is** enforced (`execution.py:152-162`, `approval.py:162-175`, +
EXECUTE ceiling). **Risk:** a `SubmitBackend` that calls `CloudBridge.submit` /
`AWSDriver.submit` **directly** (not through the coordinator) inherits none of
those gates — the cloud modules never check for an `Approval`.

---

## Recommended invariants for an agent cloud SubmitBackend

1. **Only reachable via `DryRunExecutionCoordinator`.** Keep the backend out of
   `agents/` (so `policy.assert_tool_modules_are_clean` and `PROHIBITED_SYMBOLS`
   stay meaningful). Entry only after `assert_approved_for_execution` +
   `ctx.can(EXECUTE)`.
2. **Server-derived infra only.** `bucket`, `region`, `profile`, `job_queue`,
   `job_definition` from a trusted server-side `CloudRunConfig` / resource
   profile — never from the `RunPlan`, tool args, or LLM. Reject any
   `job_definition` not in `JOB_DEFINITION_NAMES[plan.model]`; do not accept the
   free-string fallback.
3. **Re-derive the MATLAB-license fact** from `get_compute_profile(...).has_matlab_license`
   inside the backend; never accept it as an argument. Call
   `assert_cloud_run_allowed` again in the backend.
4. **Never pass a caller/plan `run_id` or `s3_run`.** Let `stage_run_inputs`
   mint the run-id; call `AWSDriver.submit` (uses `staging.s3_run`/`run_id`),
   never `submit_batch_job` directly. Consider per-user S3 prefix
   (`runs/<user-id>/<run-id>/`) and tightening the job-role policy from
   `runs/*`.
5. **Enforce `run_target` hygiene at submit** — apply `runtime._RUN_TARGET_RE`
   in `submit.build_container_overrides` too.
6. **No legacy submitter** — construct `AWSDriver`/`CloudBridge` with
   `submitter=None`.
7. **Model gate stays ISSM-only** — add an explicit
   `is_supported_cloud_model(plan.model)` assert in the backend.
8. **Digest re-binding at submit** — do not re-read the plan from any mutable
   source after `execution.py:152-162`.
9. **Register the RunInfo like the gateway** — `workspace_bridge.start_run(...,
   execution_mode="cloud", backend="aws", ...)` with server-derived metadata,
   owned by the context user.
10. **Record provenance, not secrets** — only `CloudRunConfig.provenance()`
    fields; keep the existing screens in the path.
11. **Profile allow-listing** — constrain `profile` to a single configured
    value.
