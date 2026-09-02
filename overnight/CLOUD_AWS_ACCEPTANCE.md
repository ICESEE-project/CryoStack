# CryoStack Cloud — real AWS acceptance checklist (STOP: needs Brian)

Everything up to this point is implemented and tested **offline**. This
document is the manual, human-authorised procedure for the first real AWS run.
**Do not run it autonomously — it creates AWS resources and incurs charges.**

Deploy the current `cryostack_src` to the gateway VM first (`git pull` + restart
Voilà) so the new CloudRunController + smoke test are live.

---

## 0. AWS prerequisites (one-time, Brian)

A controlled, low-limit AWS account or a sandbox sub-account. Required:

| Thing | How |
|---|---|
| AWS CLI v2 on the **gateway host** | `aws --version` → `aws-cli/2.x` |
| Credentials for a **least-privilege** IAM principal | `aws configure` (or a named profile). CryoStack stores nothing — it uses the ambient chain. |
| A billing alarm / budget | AWS Budgets, e.g. \$20/month, so a runaway is caught |
| Region decision | default `us-east-2` (must match everywhere below) |

IAM permissions the principal needs (provisioning + run): `sts:GetCallerIdentity`;
`s3:*` on `arn:aws:s3:::cryostack-runs-<account-id>` and `/*`;
`ecr:*` on the `cryostack-issm` repo; `batch:*`; `iam:CreateRole`/`PassRole`/
`AttachRolePolicy` for the Batch execution + job roles; `ec2:*Vpc*`/`*Subnet*`/
`*SecurityGroup*` for the default-VPC discovery; `logs:*` on `/cryostack/batch/*`.
Scope these to the specific ARNs before a shared account.

**MATLAB licence:** the reference `aws` compute profile has **no** MATLAB
licence, so a real **ISSM** cloud run is still blocked by preflight
(by design — honest). Two options:
- run only the **infrastructure smoke test** + the **`smoke` job** (no MATLAB), or
- configure `MLM_LICENSE_FILE` for the `aws` profile in
  `cryostack_src/resources/profiles.py` (a network-reachable licence server)
  and then an ISSM cloud run becomes possible.

---

## 1. Provision the infrastructure (Brian, once)

This is the step the autonomous work stopped before. It creates the VPC
discovery, S3 bucket, IAM roles, ECR repo, and the Batch compute
environment / queue / job definition.

```sh
# from a python shell on the gateway host, in the repo venv
python - <<'PY'
from cryostack_src.cloud import CloudManager
m = CloudManager()
print(m.bootstrap(provider="aws", region="us-east-2"))          # identity + S3
print(m.prepare_batch(provider="aws", region="us-east-2"))      # VPC/IAM/ECR/Batch
PY
```

`prepare_batch` now **waits** for the Fargate compute environment to reach
`status == VALID` before it creates/attaches the job queue, and for the queue
to reach `VALID` before it registers the job definitions
(`batch_provision._poll_batch_status`, 10 s interval / 300 s timeout;
`INVALID` fails immediately with `statusReason`). It is idempotent on the
**current live partial state** (account `713938953301`): the `VALID`
`cryostack-fargate` compute environment and the existing S3 bucket / ECR repo
are **reused**, and only the missing `cryostack-queue` and `cryostack-issm`
job definition are created. Just re-run the block above.

Then push the tested ISSM image into `cryostack-issm` (the registry-delivery
helper mirrors the digest-pinned image — see `cryostack_src/cloud/drivers/aws/
registry_delivery.py`; do this from a host with Docker/buildx).

**If you added the `smoke` runner branch (commit `af0d94f`):** re-run
`prepare_batch` so the job definition picks up the new baked runner, or the
`smoke` job will fall through to `unsupported model`.

Expected resources created:
- S3: `s3://cryostack-runs-<account-id>` (SSE-S3, public access blocked)
- ECR: `cryostack-issm`
- Batch: compute env `cryostack-fargate` (Fargate, `maxvCpus=16`),
  queue `cryostack-queue`, job definition `cryostack-issm`
  (2 vCPU / 8192 MiB / 50 GiB / 3600 s / 1 attempt / `awslogs`)
- IAM: a Batch execution role + a job role scoped to `runs/*`
- CloudWatch Logs group `/cryostack/batch`

---

## 2. Infrastructure smoke test (no job, ~\$0) — do this first

**UI:** CryoLauncher → model **ISSM** → Execution **Cloud** → set **Region**
`us-east-2` and **S3 prefix** `s3://cryostack-runs-<account-id>` → open the
log area → click **Infrastructure smoke test**.

Expect in the log:
```
[cloud] Cloud infrastructure smoke test (no job submitted, no ISSM run)…
  [PASS] AWS identity — account <id>
  [PASS] S3 write + read (your prefix)
  [PASS] S3 cleanup
  [PASS] Batch job queue — cryostack-queue: ('ENABLED', 'VALID')
  [PASS] Batch job definition — cryostack-issm (ACTIVE)
  [PASS] ECR image — cryostack-issm
[cloud] infrastructure ready
```

**CLI equivalents** to run by hand if the button reports a failure:
```sh
aws sts get-caller-identity
aws s3 cp - s3://cryostack-runs-<id>/runs/<your-safe-id>/_smoke/probe.txt <<<'hi' && \
  aws s3 cp s3://cryostack-runs-<id>/runs/<your-safe-id>/_smoke/probe.txt - && \
  aws s3 rm s3://cryostack-runs-<id>/runs/<your-safe-id>/_smoke/probe.txt
aws batch describe-job-queues     --job-queues cryostack-queue --region us-east-2
aws batch describe-job-definitions --job-definition-name cryostack-issm --status ACTIVE --region us-east-2
aws ecr  describe-images          --repository-name cryostack-issm --region us-east-2
```

`<your-safe-id>` = `WorkspaceManager.owner.safe_id` (shown in the run cache
path; `<slug>-<12-hex>`).

---

## 3. Full-pipeline smoke test (one tiny job, cents) — optional, license-free

Only if the `smoke` runner branch is provisioned. There is no UI button for
this yet; submit by hand:

```sh
python - <<'PY'
from cryostack_src.cloud import CloudManager, resolve_cloud_config
# stage a 1-file dir
import tempfile, pathlib
d = pathlib.Path(tempfile.mkdtemp()); (d/"runme.m").write_text("% smoke\n")
cfg = resolve_cloud_config(provider="aws", region="us-east-2",
                           bucket="s3://cryostack-runs-<id>", model="smoke")
r = CloudManager().submit(
    provider="aws", region="us-east-2",
    staged_source=str(d), model="smoke", run_target="runme.m",
    bucket=cfg.bucket, run_prefix="acceptance/",
    job_queue="cryostack-queue", job_definition="cryostack-issm",
    matlab_license_configured=True)   # smoke has no MATLAB gate
print(r)
PY
```

Watch it: `aws batch describe-jobs --jobs <jobId>` → `SUBMITTED` → `RUNNABLE`
→ `STARTING` → `RUNNING` → `SUCCEEDED`. Then:
`aws s3 ls s3://cryostack-runs-<id>/runs/acceptance/<run-id>/outputs/` →
`metadata.json` (`schema: cryostack.cloud.smoke`).

---

## 4. Real ISSM cloud run (needs a MATLAB licence) — the full acceptance

**Only after** a licence is configured for the `aws` profile.

**UI steps:**
1. CryoLauncher → model **ISSM** → example **SquareIceShelf** → Execution **Cloud**.
2. Cloud Environment: **Provider** AWS, **Region** `us-east-2`, **S3 prefix**
   `s3://cryostack-runs-<account-id>`. Leave queue / job-def / profile blank
   (deterministic defaults) unless overriding.
3. Click **Infrastructure smoke test** → all green.
4. Click **Submit job**. The log prints the cost/resource summary:
   ```
   This submits an AWS Batch (Fargate) job. It will use AWS resources and may
   incur charges on your account.
     model issm | region us-east-2 | S3 bucket … | job queue cryostack-queue
     job definition cryostack-issm | resources 2 vCPU · 8 GiB · time limit 60 min
   ```
5. The chip goes **Staging… → Submitting… → Queued**. Control returns to the
   UI immediately. The job id prints in the log.
6. Auto-poll (every ~20 s) advances the chip **Queued → Running → Completed**.
   No need to click *Check status*.
7. On **Completed** the outputs sync automatically into your run cache and the
   **Results** panel renders a field. Use **Download Results / Download Figures**.
8. If it fails, the log shows a short actionable line + the AWS detail; **Logs**
   pulls the CloudWatch container log.
9. **Terminate** (two-click confirm) cancels a running job and stops polling.

**Expected S3 layout:**
```
s3://cryostack-runs-<id>/runs/<your-safe-id>/cloud-<UTC>-<uuid8>/
  ├── input/                       (the staged working copy)
  │   ├── runme.m  Square.par  ...
  │   ├── cryostack_md_overrides.m  (if Basic-mode overrides were set)
  │   ├── postprocess_icesee.m
  │   └── cryostack-run.json        (execution descriptor)
  └── outputs/                      (written by the container)
      ├── metadata.json             schema: cryostack.issm.results
      ├── mesh/  fields/  model/  figures/
```

**Expected Batch lifecycle:** `SUBMITTED → RUNNABLE → STARTING → RUNNING →
SUCCEEDED` (Fargate cold start ~1–2 min; SquareIceShelf solve is seconds;
total wall < 5 min).

**Expected CryoStack outputs:** a run in the Workspace history with
`backend=aws`, `execution_mode=cloud`, status `completed`; the structured
`cryostack.issm.results` package in `<owner_root>/.../cache/cloud_outputs/`;
a rendered field in the Results panel; downloadable zip.

**Approximate cost:** Fargate 2 vCPU + 8 GiB for ~5 min ≈ a few US cents per
run, plus negligible S3 + CloudWatch. The billing alarm from §0 is the
backstop.

---

## 5. Cleanup

Per run (safe any time):
```sh
aws s3 rm --recursive s3://cryostack-runs-<id>/runs/<your-safe-id>/
```

Tear down the infrastructure (when done evaluating):
```sh
# disable + delete Batch, in order
aws batch update-job-queue --job-queue cryostack-queue --state DISABLED --region us-east-2
aws batch delete-job-queue --job-queue cryostack-queue --region us-east-2
aws batch update-compute-environment --compute-environment cryostack-fargate --state DISABLED --region us-east-2
aws batch delete-compute-environment --compute-environment cryostack-fargate --region us-east-2
aws batch deregister-job-definition --job-definition <cryostack-issm:REV> --region us-east-2
# ECR + S3 + logs
aws ecr delete-repository --repository-name cryostack-issm --force --region us-east-2
aws s3 rb s3://cryostack-runs-<id> --force
aws logs delete-log-group --log-group-name /cryostack/batch --region us-east-2
# IAM roles created by prepare_batch (names in the prepare_batch output)
```

---

## What is verified vs. what still needs the real run

| Verified offline (commits b79dad6…af0d94f) | Needs the real run |
|---|---|
| non-blocking submit; state machine; auto-poll; auto-retrieve | Fargate cold-start timing; real CloudWatch log shape |
| failure classification (15 classes) | which AWS errors actually surface in practice |
| per-user S3 prefix; two-user disjoint trees | IAM actually enforcing the `runs/*` scope |
| controlled job-definition selection | — |
| infrastructure smoke test (all branches, mocked) | real `describe-*` output shapes |
| result package lands in the per-user cache and is readable | real container writing real `cryostack.issm.results` |
| cost/charge warning shown before submit | actual \$ per run |
