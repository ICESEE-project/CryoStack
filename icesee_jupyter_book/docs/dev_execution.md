# Execution Backends

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>
:::

:::{raw} html
<div class="cryostack-docs-page">
  <section class="cryostack-docs-hero">
    <div class="cryostack-section-label">CryoStack Developer Guide</div>
    <h1>Execution Backends</h1>
    <p>
      Local/Remote/Cloud, the two Remote access mechanisms, AWS Batch
      (Fargate/EC2), and the shared Connector/Relay path for private Cloud
      connectivity.
    </p>
    <div class="cryostack-docs-actions">
      <a class="cryostack-btn secondary" href="developer_guide.html">
        &larr; Developer Guide
      </a>
    </div>
  </section>
</div>
:::

---

## Execution architecture

**CryoLauncher and ICESEE do not share one execution adapter.** Each
application has its own submission code, its own Cloud runner, and its own
result-presentation path — verified against the actual gateways, not
assumed from the shared Local/Remote/Cloud vocabulary both happen to use.
`icesee_gateway.py` never imports `WorkspaceManager`, `discover_results`, or
any `cryostack_src.models.submission`/`cryostack_src.cloud.runtime` symbol.
What genuinely is shared across both applications is narrower: the
Remote direct-SSH-vs-Connector decision (`RemoteBridge`, both apps), the
Connector/Relay protocol itself, and (within CryoLauncher only, across its
own models) the Cloud account-connection/onboarding architecture
(`AWSDriver`/CloudFormation) and `WorkspaceManager`'s Cloud result sync.

```text
CryoStack execution
     |
     +-- CryoLauncher
     |     +-- Remote
     |     |     +-- direct SSH
     |     |     +-- Connector -> Relay -> institutional resource
     |     |     (cryostack_src/models/submission.py)
     |     |
     |     +-- Cloud
     |     |     +-- AWS Batch
     |     |           +-- Fargate (default)
     |     |           +-- EC2 (Advanced: On-Demand/Spot, GPU, multi-node)
     |     |     (cryostack_src/cloud/runtime.py, cryostack_src/cloud/bridge.py)
     |     |
     |     +-- structured result package (outputs/{metadata.json, mesh,
     |           fields, model, figures} -> discover_results() ->
     |           cryostack_src/visualization/) -- shared ACROSS
     |           CryoLauncher's own Remote and Cloud backends, and across
     |           its models (ISSM/Icepack); not shared with ICESEE.
     |
     +-- ICESEE
           +-- Local     (icesee_jupyter_book/core/local_runner.py --
           |               run_local_example(); in-kernel, no scheduler)
           |
           +-- Remote    (icesee_jupyter_book/core/remote_runner.py --
           |               submit_remote_example[_container][_via_connector]();
           |               its own ensemble/DA parameters, e.g. ens_size,
           |               cluster_mpi_np)
           |
           +-- Cloud     (icesee_jupyter_book/core/cloud_runner.py +
           |               icesee_jupyter_book/core/cloud_bridge_adapter.py's
           |               IceseeCloudBridgeConfig; its own AWSBatchConfig
           |               and ICESEE_*-prefixed env-var contract, not
           |               CRYOSTACK_*)
           |
           +-- ExperimentBridge (icesee_jupyter_book/ui/experiment_bridge.py)
                 -- its own run-record type, not WorkspaceManager/RunInfo;
                 results are a raw file-tree listing + inline image display,
                 not a discover_results()/ResultPackage read.
```

CryoLauncher's own result package and its reader/visualizer
(`discover_results()`, `render_field`/`render_timeseries`) are backend-
neutral **within CryoLauncher**: Remote's SSH/rsync/connector-archive fetch
and Cloud's `aws s3 sync` both land a run's `outputs/` tree into the same
shape under the Workspace's local run cache (`cache/outputs` for Remote,
`cache/cloud_outputs` for Cloud; `WorkspaceManager.result_package_for_run`
checks both), so nothing downstream of that boundary needs to know which
*CryoLauncher backend* produced a run, or which of CryoLauncher's models
(ISSM/Icepack) did. This does not extend to ICESEE, whose own Local/Remote/
Cloud paths above never construct a `ResultPackage` at all. See
[Models, Examples & Results](dev_models_results.md)
for the reader/visualizer contract itself, and its own scope note.

**Connector/Relay as shared infrastructure, not a Cloud-only or
CryoLauncher-only component.** One Connector pairing/session serves two
distinct capability planes: ordinary Remote command dispatch (SSH/rsync/
Slurm operations over `/connector/ws/{id}`), and, when a Cloud workflow
needs it, private-service tunneling from inside a Cloud container back to
an institutional service the Cloud provider cannot reach directly
(`/connector/tunnel-grant/{id}`, `/connector/tunnel/{id}`,
`/connector/tunnel-data/{id}` in `icesee_jupyter_book/core/connector_relay_server.py`).
Cloud execution does **not** generally require Connector/Relay — an
ordinary Fargate/EC2 Icepack or ISSM run with no private-license dependency
never touches it. The one concrete, validated case that does:

```text
Cloud scientific container
         |
         | when private institutional
         | connectivity is required
         v
Connector/Relay session          (the SAME session/pairing Remote uses --
         |                        see connector_core.py's SITE_TUNNEL_TARGETS
         v                        allow-list, resolved only on the Connector
Institutional service             side, never trusting cloud-supplied host/port)
(e.g. MATLAB licensing)
```

The validated instance of this path: ISSM submitted through CryoLauncher to
AWS Batch (Fargate and EC2 On-Demand, both confirmed end-to-end) reaches
Georgia Tech's institutional MATLAB network-license service through this
tunnel — `cryostack_src/cloud/matlab_license.py` plans the tunnel and its
optional FlexNet vendor-port hop, `cryostack_src/cloud/license_tunnel_client.py`
is staged into the Batch container as an ordinary file (never imported as a
`cryostack_src` module, since the scientific image has no CryoLauncher
package installed) and invoked by the staged ISSM runner
(`cryostack_src/cloud/runtime.py`'s `issm_cloud_runner_script()`). This
validates one institutional Cloud/Connector configuration, not arbitrary
institutional license-server arrangements. See
[Connector & Relay](dev_connector.md) for the Connector's own architecture,
build, and publishing workflow.

## Remote execution backends

This section documents **CryoLauncher's** own Remote submission
(`cryostack_src/models/submission.py`) for its ISSM/Icepack models. Despite
the names below, "ICESEE-Spack"/"ICESEE-Container" are environment-strategy
labels inherited from the wider ICESEE research project, not the ICESEE
*application*'s own Remote implementation — see the diagram above for
ICESEE's actual, separate Remote code
(`icesee_jupyter_book/core/remote_runner.py`).

A model runs on one of two remote backends, selected in the gateway:

- **ICESEE-Spack** — a source build activated on the allocation. MATLAB (for
  ISSM) is site-provided. This is the path for **multi-node** runs: ISSM's
  `generic` cluster launches its solver with `mpiexec`, and the host `srun`
  is available, so PRRTE can place ranks across the allocation.
- **ICESEE-Container** — a digest-pinned Apptainer image. The Slurm job runs
  **one** `apptainer exec` on the batch node; ISSM's `solve()` then
  self-launches `mpiexec` (Spack OpenMPI 5 / PRRTE 4) *inside* the image. The
  image ships no Slurm or SSH client, so that launch is confined to the batch
  node by three `apptainer exec --env` flags (`PRTE_MCA_ras=^slurm`,
  `PRTE_MCA_plm=ssh`, `PRTE_MCA_rmaps_default_mapping_policy=:oversubscribe`).
  **Container ISSM is therefore single-node.** `md.cluster.np` (2 for every
  stock ISSM example) is the MPI rank count and is owned by the example, not
  by the Slurm panel; a container ISSM run requesting `-N > 1` logs an
  advisory and still runs on the batch node. Validated end-to-end on Georgia
  Tech PACE (`SquareIceShelf`, `solve` → `outbin` → `postprocess_icesee.m` →
  `cryostack.issm.results` → Results preview). Multi-node containerized MPI is
  a deliberate, unaddressed limitation — use the Spack backend. Do not
  reintroduce the removed `srun` shim (`cryostack_src/models/submission.py`).

## Cloud execution (AWS Batch)

This section documents **CryoLauncher's** Cloud implementation
(`cryostack_src/cloud/*`, `cryostack_src/frontend/cryolauncher/*`). ICESEE's
Cloud path is its own separate code
(`icesee_jupyter_book/core/cloud_runner.py` +
`icesee_jupyter_book/core/cloud_bridge_adapter.py`) with its own env-var
contract and its own AWS Batch job definition; it shares the account-
connection/onboarding layer described below (`AWSDriver`/CloudFormation)
but not the submission, staging, or result-sync code that follows.

- *Auth model — two modes.* **Developer / operator mode** uses ambient AWS CLI
  credentials + an optional named profile (`aws configure`); it is the local
  development and acceptance path only. **End-user mode** ("Bring your AWS
  account") is a cross-account IAM role (`CryoStackExecutionRole`) assumed via
  `sts:AssumeRole` with a per-connection `ExternalId`; CryoStack holds only
  *temporary* STS credentials for one operation and persists only non-secret
  connection metadata (`cryostack_src/cloud/connect/`). Never document
  `aws configure` for normal users — keep CLI/profile guidance in Developer /
  Maintainer scope. The onboarding template + Quick Create URL builder live in
  `cryostack_src/cloud/connect/cloudformation.py`; the CryoStack principal ARN
  is deployment config (`CRYOSTACK_AWS_PRINCIPAL_ARN`), never hardcoded, and
  the hosted template URL is `CRYOSTACK_CF_TEMPLATE_URL`.
- *Credential routing (`cryostack_src/cloud/connect/execution.py`).*
  `resolve_cloud_execution()` picks the path per operation: a connected
  `AWSConnection` → a **fresh** `sts:AssumeRole` every time (nothing cached),
  region from the connection, bucket `cryostack-runs-<account-id>`, `profile`
  forced to `None`; **no ambient-credential fallback** — a broken connection
  raises `CloudAccessError` and the op fails closed. No connection record →
  developer mode, unchanged. `CloudBridge` / `CloudBackend` / `CloudManager`
  take a `credentials` kwarg; when set it wins and `run_aws` scrubs ambient
  `AWS_*` from the child env.
- *Run Log emission from background tasks.* Cloud Test/Prepare/Smoke and the
  run lifecycle write the Workspace Run Log from a **detached asyncio task**.
  `with output: print(...)` silently drops there — `ipywidgets.Output` binds
  its capture to the kernel's parent-message header at `__enter__`, which a
  task resumed on a later event-loop iteration no longer has. Use
  `cloud_runtime._emit_log(widget, *lines)` (it calls `Output.append_stdout`,
  writing straight to the synced `outputs` traitlet, and redacts credential
  material). This is why a failed Prepare once left the Run Log empty.
- *Prepare readiness.* `AWSDriver.bootstrap` aborts on the first failing stage
  and returns a structured partial result (`row_status` per row:
  `connected`/`ready`/`failed`/`not_attempted`, plus sanitized messages) rather
  than raising — so Storage/Containers/Compute that were never reached show a
  neutral "Not prepared", never an independent failure. An unhandled exception
  before any structured result marks only the **account** row failed.
- *Interactive BYO run lifecycle (C7.5).* `CloudRunController` takes an
  `execution_provider` (`_resolve_cloud_execution`); when set, **every** AWS
  operation of the run — stage/submit, each status poll, terminate, and the S3
  result sync — is performed with a **fresh** `CloudExecution` (a fresh
  `sts:AssumeRole` for a connected BYO account) and never falls back to
  ambient/profile. `run_once` asserts the fresh session's account matches the
  reviewed `_account_id` before staging (`_assert_same_account` → fail closed).
  `Review & Launch` submits `review.config` verbatim (no rebuilt
  `CloudRunConfig`) and re-checks the C7.4 digest — which includes the account
  id — so a config or account change after Review blocks the launch.
  `current_cloud_bridge()` auto-resolves BYO credentials for the manual
  status/log/terminate/results buttons and `resolve_workspace_run_status`
  (BYO runs carry a non-secret `account_id` in metadata for re-attach after a
  refresh; no STS credentials are persisted). The **CLOUD RUN** card
  (`cloud_active_run_runtime.py`) renders `on_run_view` state changes and ticks
  elapsed time + `live_cost_usd(cost_public, elapsed)` once a second — purely
  local, no pricing call during the run; AWS status polling keeps its
  `CRYOSTACK_CLOUD_POLL_SECONDS` (default 20 s) cadence. `sync_cloud_results`
  gained a `credentials` param (scrubs ambient `AWS_*`, drops `--profile`).
- *Cost & runtime estimate (`cryostack_src/cloud/estimate/`, `cryostack_src/cloud/review.py`).*
  `resolve_fargate_prices(region)` queries the AWS Price List API from
  `us-east-1` and selects the priced region by `regionCode` attribute;
  results are cached ~6 h; any failure → `available=False` (never a fabricated
  price, never blocks Launch). `estimate_runtime()` prefers previous
  successful CryoStack runs → a curated `KNOWN_EXAMPLE_RUNTIMES` table → the
  configured time limit, each labelled. `estimate_cloud_cost()` returns a
  `CloudCostEstimate` with an `estimate_for_elapsed()` helper C7.5 reuses.
  `build_cloud_run_review()` renders from the **canonical**
  `CloudRunConfig.fargate` (same values the submit path uses — no second
  copy); `review_digest()` fingerprints the billable scientific + resource
  config so a change after the review opens forces a re-review before Launch.
  Launch gating: fresh AssumeRole verification + all infra Ready + supported
  model + config valid + preflight (ISSM needs a usable MATLAB
  license and supported connectivity). Pricing uses ambient/host credentials
  by default (public, account-neutral data) — never the stored STS session.
- *CryoStack-provisioned IAM roles are `cryostack-*`* (`cryostack-batch-service-role`,
  `cryostack-ecs-execution-role`, `cryostack-job-role`) so they sit inside the
  cross-account role's `role/cryostack-*` scope and never collide with the
  PascalCase `CryoStackExecutionRole` the user creates. `iam.py` no longer
  matches `CryoStackExecutionRole` when discovering the ECS task-execution
  role. The C7.2 template was audited against every API call `bootstrap` +
  `prepare_batch` make; delta added: `iam:ListRoles`, `ecr:GetLifecyclePolicy`,
  `ecr:PutLifecyclePolicy` (checked-in artifact regenerated).
- *Implemented:* an end-to-end ISSM path — config + preflight, a user-owned
  working copy staged to `s3://<bucket>/runs/<safe-user>/<run-id>/`,
  `aws batch submit-job` (Fargate), lifecycle status/logs/terminate.
  Submission is non-blocking (`cloud_run_controller.CloudRunController`, the
  same asyncio worker pattern as the auto-tail log worker): the UI returns at
  once, the run auto-polls, and on completion the outputs sync into the user's
  run cache and render through the same Results panel every backend uses. All
  AWS calls go through the `aws` CLI; CryoStack stores no credentials.
  Job-definition selection is controlled (the model default or a known
  CryoStack name only). A license-neutral **infrastructure smoke test**
  (`cryostack_src.cloud.smoke`) checks identity + S3 + Batch + ECR reachability
  without submitting a job.
- *Requires qualification:* budget/quota/cleanup automation, failure-recovery
  tests and IAM review beyond the workflow-specific live checkpoints.
- *Manual checkpoint:* `overnight/CLOUD_AWS_ACCEPTANCE.md` — provisioning and
  the first paid run are human-authorised.
- *ISSM cloud MATLAB licensing.* The container and license readiness checks
  remain distinct. The normal manual setup accepts the institutional MATLAB
  license information once, configures it in the user's connected AWS account,
  and retains a secret reference. Advanced users may supply an existing secret
  reference. Connector supports the configured institutional connectivity path;
  the live-tested environment is Georgia Tech, not every institutional topology.
  See the [scientist-facing setup](../applications/icesheets/user_manual.html#matlab-licensing-for-issm-cloud-runs).
  The relevant implementation is in `cryostack_src/cloud/matlab_license.py`,
  `cryostack_src/frontend/cryolauncher/cloud_environment.py`, and the Connector
  integration. Licensing is not configured by Auto-config. Cloud readiness
  remains authoritative even after a license reference has been saved.
- *Compute mode: Fargate vs. EC2.* EC2 is not a second cloud backend — it is
  an alternate **AWS Batch compute environment** behind the same `AWSDriver`.
  Everything above (auth model, credential routing, staging, ECR/image
  resolution, S3, job submission/status/logs/terminate, result sync,
  visualization, provenance) is unchanged by the choice; only the Batch
  compute-environment/job-definition the job schedules onto differs.
  `CloudEnvironmentWidgets.compute_mode` (`fargate` default | `ec2`) in
  `cryostack_src/frontend/cryolauncher/cloud_environment.py` gates a
  progressive-disclosure `ec2_options_box`; while `compute_mode == "fargate"`
  none of it renders and Fargate behaves exactly as documented above.
  Selecting `ec2` exposes four further dropdowns, each independently gated:
  `ec2_capacity` (`on_demand` default | `spot`), `ec2_accelerator` (`none`
  default | `gpu`, its box only visible when `gpu` is selected),
  `ec2_network` (`default` | `custom`, revealing VPC id / subnet ids /
  security-group-ids text fields only when `custom`), and `ec2_topology`
  (`single_node` default | `multi_node`, revealing a node-count field only
  when `multi_node`). No AMI, launch-template, instance-profile, or other
  raw IAM/EC2 detail is ever exposed to the UI. GPU and multi-node are
  submission-guarded rather than removed: the GPU caption and multi-node
  caption in the same module state, in place, that the qualified container
  image has no CUDA runtime and that the scientific runners do not yet
  coordinate distributed MPI across Batch nodes, so selecting either stages
  infrastructure without CryoStack ever attempting a run neither the image
  nor the runners can perform. **On-Demand, single-node EC2 is now
  AWS-validated**: CryoLauncher/Icepack's `00-meshes-functions` tutorial ran
  end to end on a CryoStack-provisioned managed EC2 compute environment
  (`cryostack-ec2`), submitted to `cryostack-ec2-queue` /
  `cryostack-icepack-ec2` (2 vCPU / 8 GiB), and completed successfully. Spot
  capacity, GPU, multi-node, and custom-network EC2 provisioning are
  implemented and covered by the same test suite as Fargate, but — unlike
  the On-Demand/single-node/CPU path above — have not been exercised against
  live AWS in this repository's evidence. CryoLauncher's ISSM workflow has
  also completed the same On-Demand/single-node/CPU path on EC2 (in
  addition to Fargate): MPI-parallel solver execution, postprocessing,
  retrieval, and visualization, reaching the configured Georgia Tech
  institutional MATLAB license through Connector/Relay. ICESEE's own Cloud
  execution has not been separately validated for ISSM-based workflows. Do
  not describe Spot, GPU, multi-node, or custom-network EC2 as AWS-validated
  without a checkpoint that says otherwise.
- *CloudWatch log-group resolution (`cryostack_src/cloud/legacy/aws_batch.py`).*
  `batch_logs()` never assumes a single fixed log group. It resolves the
  group per job: `DescribeJobs(jobId)` → that job's `jobDefinition` ARN →
  `DescribeJobDefinitions` → `containerProperties.logConfiguration.options
  ["awslogs-group"]`; the log **stream** is always
  `DescribeJobs(...).container.logStreamName`. When a job definition never
  set an explicit `awslogs-group` (a legacy/default Batch job definition),
  resolution falls back to AWS Batch's own default group, `/aws/batch/job`
  — never guessed from the model name. `resolve_log_group()` never raises:
  a `DescribeJobDefinitions` failure (permissions, a deregistered
  definition) also falls back to the default group rather than blocking the
  log read. `GetLogEvents` `AccessDenied` is classified by
  `cloud_run_controller.classify_cloud_failure` /
  `is_log_read_permission_error` into a non-fatal message — the job and its
  results are unaffected by a role that cannot read CloudWatch Logs — and a
  `ResourceNotFoundException` (stream not created yet, or genuinely absent
  on a completed job) is likewise reported, never raised as a job/result
  failure. See `cryostack_src/cloud/tests/test_aws_batch_log_resolution.py`
  for the resolution-order and non-fatal-error regression coverage.

See [Models, Examples & Results](dev_models_results.md) for the model-adapter
side of a run, and [Extending CryoStack](dev_extending.md)
for how to add a new Cloud-qualified example.
