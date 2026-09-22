# Cloud Run Guide

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>

<div class="cryostack-docs-page">

  <section class="cryostack-docs-hero">

    <div class="cryostack-section-label">
      CryoStack Documentation
    </div>

    <h1>Running on your own AWS account</h1>

    <p>
      How CryoStack launches, monitors, and retrieves the results of a run
      on AWS Batch — using an AWS account you connect yourself
      (bring-your-own-AWS), and the same application configuration you
      already use locally or on HPC.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary" href="../applications/icesheets/user_manual.html#execution-modes-and-backends">
        CryoLauncher Cloud Reference
      </a>

      <a class="cryostack-btn secondary" href="../applications/icesee/user_manual.html#cloud-mode">
        ICESEE Cloud Mode
      </a>

      <a class="cryostack-btn secondary" href="developer_guide.html">
        Developer Guide
      </a>
    </div>

  </section>

  <section id="on-this-page" class="cryostack-section">

    <div class="cryostack-section-label">
      On this page
    </div>

    <h2>Where to go next.</h2>

    <p class="cryostack-section-intro">
      Cards navigate to the sections below. This page describes the
      platform-wide cloud execution path shared by CryoLauncher and ICESEE —
      application-specific fields and screens stay in each application's own
      User Manual.
    </p>

    <div class="cryostack-docs-summary-grid">

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">JM</div>
        <h3><a href="#the-cloud-run-journey">The cloud run journey</a></h3>
        <p>The real sequence: application, configuration, backend, AWS
           connection, launch, monitor, results.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">BK</div>
        <h3><a href="#what-stays-the-same-what-changes">Local, HPC, or Cloud</a></h3>
        <p>What is identical across backends, and what genuinely changes.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">AC</div>
        <h3><a href="#connecting-your-aws-account-byo-aws">Connecting your AWS account</a></h3>
        <p>CloudFormation onboarding, ExternalId, and temporary credentials.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">PC</div>
        <h3><a href="#preparing-cloud-infrastructure">Preparing cloud infrastructure</a></h3>
        <p>Prepare cloud: storage, container registry, and AWS Batch.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">CM</div>
        <h3><a href="#compute-mode-fargate-default-or-ec2-advanced">Compute mode</a></h3>
        <p>Fargate (default) or EC2 (Advanced): capacity, accelerator,
           network, and execution options.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">RL</div>
        <h3><a href="#reviewing-and-launching-a-run">Review &amp; Launch</a></h3>
        <p>The run estimate, the review card, and what actually launches.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">MR</div>
        <h3><a href="#monitoring-a-run-and-retrieving-results">Monitoring &amp; results</a></h3>
        <p>Run states, logs, and how outputs come back to your Workspace.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">WE</div>
        <h3><a href="#worked-examples-verified-on-aws">Worked examples verified on AWS</a></h3>
        <p>What has actually run end-to-end, and where to find the exact
           step-by-step walkthrough for each application.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">TS</div>
        <h3><a href="#troubleshooting-and-verification">Troubleshooting</a></h3>
        <p>Common failure points and how to verify your deployment.</p>
      </div>

    </div>

  </section>

  <section id="scope" class="cryostack-section">

    <div class="cryostack-section-label">Scope and status</div>
    <h2>What this page documents.</h2>

    <p class="cryostack-section-intro">
      This describes <strong>software that exists today</strong> — every
      button, label, and step name below matches the running application.
      Nothing here is a roadmap. "Cloud parity" is not one fact — it is
      five separate ones, and they are not all at the same maturity:
    </p>

    <div class="cryostack-docs-summary-grid">

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">SA</div>
        <h3>Shared architecture <span class="cryostack-status supported">Working</span></h3>
        <p>CryoLauncher and ICESEE both provision cloud infrastructure
           through the same <code>AWSDriver</code>/CloudFormation-onboarding
           architecture — one implementation, not two.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">CP</div>
        <h3>Configuration portability <span class="cryostack-status supported">Working</span></h3>
        <p>The same scientific/example configuration (<code>params.yaml</code>,
           model settings) carries over across Local, Remote/HPC, and Cloud —
           there is no separate cloud-only configuration to maintain.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">CE</div>
        <h3>Cloud exposure <span class="cryostack-status dev">Partial</span></h3>
        <p>CryoLauncher and ICESEE currently expose a Cloud execution mode in
           the UI. This is not true of every CryoStack application — do not
           assume a third application has a cloud path just because these
           two do.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">VW</div>
        <h3>Validated workflows <span class="cryostack-status supported">Demonstrated</span></h3>
        <p>Three configurations have been run and confirmed end-to-end on AWS Batch's
           <strong>Fargate</strong> compute mode: <strong>ICESEE Lorenz-96 at
           NP&nbsp;=&nbsp;1</strong>, <strong>CryoLauncher/Icepack
           04-synthetic-ice-stream-xy</strong>, and <strong>CryoLauncher/ISSM</strong>
           (MPI-parallel solver execution, postprocessing into CryoStack's shared
           result package, retrieval, and visualization). CryoLauncher/ISSM has
           also completed the same end-to-end path on <strong>EC2 On-Demand</strong>,
           in both cases reaching the configured Georgia Tech institutional MATLAB
           license through the same Connector/Relay infrastructure used for Remote
           access. This validates one institutional Cloud/Connector configuration;
           it does not establish compatibility with arbitrary institutional
           license-server arrangements. See
           <a href="../applications/icesheets/user_manual.html#matlab-licensing-for-issm-cloud-runs">MATLAB licensing and Connector setup</a>.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">CM</div>
        <h3>Compute mode <span class="cryostack-status supported">Fargate and EC2 On-Demand validated</span></h3>
        <p><strong>Fargate</strong> is the default AWS Batch compute mode.
           <strong>EC2 (Advanced)</strong> is an opt-in alternative; its
           <strong>On-Demand, single-node, CPU</strong> configuration has now
           also run end to end on live AWS — CryoLauncher/Icepack's
           <code>00-meshes-functions</code> tutorial and CryoLauncher/ISSM,
           both submitted to a CryoStack-provisioned managed EC2 compute
           environment. EC2 <strong>Spot</strong>, <strong>GPU</strong>, and
           <strong>multi-node</strong>, and EC2 for ICESEE, remain
           implemented/provisioned but not yet run against live AWS in this
           repository's evidence. See
           <a href="#compute-mode-fargate-default-or-ec2-advanced">Compute mode</a>
           below.</p>
      </div>

    </div>

    <p class="cryostack-section-intro">
      In short: CryoStack has backend/configuration parity at the
      <strong>architecture</strong> level today. Application-level
      <strong>operational validation</strong> — an actual completed run,
      end to end, on live AWS — is still expanding, one configuration at a
      time, and this page names exactly which one.
      <span class="cryostack-status planned">Not yet available</span>
      in-app teardown of AWS-side infrastructure (stack/role deletion) — see
      <a href="#cleanup">Cleanup</a> below for exactly what that does and
      does not cover.
    </p>

  </section>

</div>
:::

## The cloud run journey

CryoStack's cloud path follows the same shape as Local and Remote/HPC
execution — the application and its configuration do not change; only the
**execution backend** changes:

```text
 Application  →  Configuration  →  Compute backend  →  AWS connection
                                                              │
                                                              ▼
                    Results  ←  Monitor  ←  Launch  ←  Prepare cloud
                                                              ▲
                                                              │
                                              AWS Batch  ──┬── Fargate (default)
                                                            └── EC2 (Advanced)
                                                                ├─ On-Demand / Spot
                                                                ├─ Default / Custom network
                                                                └─ Single node / Multi-node*
```

Both branches converge on the same Prepare cloud → Launch → Monitor → Results
path below — EC2 changes what Batch schedules the job onto, not the
application, the staging, or the result pipeline. (`*` guarded/experimental —
see <a href="#compute-mode-fargate-default-or-ec2-advanced">Compute mode</a>.)

This is the shared architecture, not a claim that Monitor/Results behave
identically in every application today: CryoLauncher uses an active
cloud-run controller that polls the job and synchronizes results
automatically after a successful completion, while ICESEE currently uses
explicit, manual status and result actions instead (details in
<a href="#monitoring-a-run-and-retrieving-results">Monitoring a run and retrieving results</a>).

**For CryoLauncher, Basic/Advanced and Remote/Cloud are separate choices** —
Basic/Advanced is *how you configure* a run; Remote/Cloud is *where it
executes*. Selecting Cloud does not by itself change which Cloud controls
you see:

```text
CryoLauncher Basic  + Cloud  ->  simplified Cloud surface  ->  Fargate-only

CryoLauncher Advanced + Cloud  ->  advanced Cloud controls  ->  supported
    Fargate/EC2 configuration and other exposed controls, subject to the
    documented capability limitations below
```

Basic mode always submits to Fargate — the entire Advanced Cloud panel
(compute-mode choice, EC2 capacity/accelerator/network/execution options)
is hidden. Switching to Advanced exposes those controls, but exposing a
control is not the same as that capability being AWS-validated — see
<a href="#compute-mode-fargate-default-or-ec2-advanced">Compute mode</a>
below for exactly which Advanced options have and have not been run
against live AWS.

In the application's own terms, this is:

:::{raw} html
<ol>
  <li>Open the application (CryoLauncher or ICESEE) and select an example.</li>
  <li>Configure it exactly as you would for a local or Remote/HPC run.</li>
  <li>In <b>Run settings</b>, set <b>Execution mode</b> to <b>Cloud</b>.</li>
  <li>Under <b>Cloud Environment → AWS ACCOUNT</b>, connect your AWS account
    (once) — see
    <a href="#connecting-your-aws-account-byo-aws">Connecting your AWS account</a>.</li>
  <li>Click <b>Prepare cloud</b> to provision what your account needs — see
    <a href="#preparing-cloud-infrastructure">Preparing cloud infrastructure</a>.</li>
  <li>Click <b>Review &amp; Launch</b>, then <b>Launch cloud run</b> — see
    <a href="#reviewing-and-launching-a-run">Reviewing and launching a run</a>.</li>
  <li>Watch the <b>CLOUD RUN</b> status card, then open <b>Results</b> — see
    <a href="#monitoring-a-run-and-retrieving-results">Monitoring a run and retrieving results</a>.</li>
</ol>
:::

## What stays the same, what changes

:::{raw} html
<div class="cryostack-docs-page">
  <section class="cryostack-section">

    <div class="cryostack-docs-environments">

      <div>
        <h3>Configuration <span class="cryostack-status supported">Identical</span></h3>
        <p>
          The example, model parameters, filter/solver settings, ensemble
          size, and dataset references are the same object regardless of
          backend. There is no separate "cloud version" of a scientific
          configuration to create or maintain.
        </p>
      </div>

      <div>
        <h3>Local</h3>
        <p>
          Runs inside the CryoStack server process itself. No connection,
          no queue — the fastest path for small runs and iteration.
        </p>
      </div>

      <div>
        <h3>Remote / HPC</h3>
        <p>
          Runs on a Linux server or Slurm-managed cluster you already have
          access to, through the CryoStack Connector or direct SSH. Adds:
          your HPC identity, a remote working directory, and (for ICESEE)
          a first-time Spack environment Check/Prepare step.
        </p>
      </div>

      <div>
        <h3>Cloud</h3>
        <p>
          Runs on AWS Batch, in <strong>your own</strong> AWS account. Adds:
          connecting the account once, letting CryoStack prepare the AWS
          infrastructure, and reviewing an estimated cost before launch. It
          does not add a different scientific workflow.
        </p>
      </div>

    </div>

  </section>
</div>
:::

## Compute mode: Fargate (default) or EC2 (Advanced)

Every run above submits to **AWS Batch**. Batch itself needs a compute
environment to schedule jobs onto, and CryoStack lets you choose which kind
under **Advanced** in Cloud Environment:

- **Fargate** — the default. No infrastructure to choose or manage; this is
  the compute mode every validated Cloud run to date has actually run
  against (see
  <a href="#worked-examples-verified-on-aws">Worked examples verified on AWS</a>).
- **EC2 (Advanced)** — CryoStack provisions its own EC2-backed Batch compute
  environment instead. Selecting it reveals four further choices, each
  purpose-built rather than exposing raw AWS knobs:

  - **Capacity** — **On-Demand** (default; predictable EC2 capacity) or
    **Spot** (lower-cost, interruptible capacity that AWS can reclaim).
  - **Accelerator** — **None** (default) or **GPU** — stages GPU-capable EC2
    infrastructure, but CryoStack's qualified container image has no CUDA
    runtime, so a GPU job is refused at submission until a GPU-qualified
    image exists. This is infrastructure preparation, not a working
    scientific execution mode.
  - **Network** — **Default** or **Custom / Private** — places the EC2
    compute environment into a VPC, subnets, and security groups you already
    control (a `vpc-…`, `subnet-…`, `sg-…` you supply), for example one
    already routed to an institutional network. CryoStack does not create a
    VPN, Direct Connect connection, Transit Gateway, or firewall rule itself
    — the VPC you point it at must already have whatever route it needs. See
    <a href="../applications/icesheets/user_manual.html#matlab-licensing-for-issm-cloud-runs">MATLAB
    licensing for ISSM cloud runs</a> for the supported Connector alternative;
    custom networking is not required by the validated Fargate/EC2 path.
  - **Execution** — **Single node** (default) or **Multi-node** — registers
    an AWS Batch multi-node parallel job definition (EC2 only), but
    CryoStack's scientific runners do not yet coordinate distributed MPI
    across Batch nodes, so this stages the infrastructure ahead of a
    scientific run rather than enabling one today.

**On-Demand, single-node capacity has now run end to end against live AWS**
for CryoLauncher/Icepack's `00-meshes-functions` tutorial (Advanced Cloud,
EC2, On-Demand, single node, CPU, 2 vCPU / 8 GiB) — CryoStack submitted to
its own managed EC2 compute environment (`cryostack-ec2`), the
`cryostack-ec2-queue` job queue, and the `cryostack-icepack-ec2` job
definition, and the job completed successfully. This does **not** extend
to: **Spot** capacity, **GPU**, **multi-node** execution, custom/private
networking, ISSM on EC2, ICESEE on EC2, or every Icepack example — each of
those is implemented and exercised locally but not yet run against live AWS
in this repository's evidence, so treat them as advanced, not-yet-AWS-validated
configurations rather than a second fully validated backend. GPU and
multi-node are additionally guarded at submission specifically so that
selecting them stages infrastructure without ever silently attempting a
scientific run neither the image nor the runners can actually perform.

## Connecting your AWS account (BYO-AWS)

CryoStack never asks for an AWS access key, secret, or CLI profile. Instead,
you create a cross-account IAM role yourself, in your own AWS console, and
CryoStack assumes it for short-lived (temporary) credentials only.

1. In **Cloud Environment → AWS ACCOUNT**, click **Connect AWS Account**.
2. Click **Open AWS Setup**. This opens a CloudFormation *Quick Create* page
   in your own AWS console, pre-filled with a unique **ExternalId** (a
   confused-deputy defence — the role can only be assumed with this exact
   value) and the CryoStack principal it should trust. Review the stack and
   click **Create stack**.
3. The stack creates one IAM role scoped to `cryostack-*` resources only —
   no `AdministratorAccess`, no wildcard actions. Copy the **Role ARN** from
   the stack's **Outputs** tab.
4. Paste the Role ARN back into CryoStack and click **Verify connection**.
   CryoStack assumes the role with your ExternalId, confirms your account,
   and shows **● Connected**.

Each CryoStack connection gets its **own** CloudFormation stack and its own
IAM role — connecting a second AWS identity, or reconnecting after a
previous attempt didn't finish, never requires deleting an existing,
working role first.

```{note}
**Retry connection** (after a failed verification) and **Change AWS
account** (to connect a different account without losing the current one)
are separate, explicit actions in the AWS ACCOUNT panel — see the
CryoLauncher User Manual's <a href="../applications/icesheets/user_manual.html#connect-aws-account">Connect AWS Account</a>
walkthrough for every button and state in detail.
```

**Disconnect** removes only the connection metadata CryoStack stored
locally. There are no long-lived credentials to revoke — STS sessions are
short-lived and are never stored. It does not delete anything in your AWS
account.

## Preparing cloud infrastructure

Once connected, click **Prepare cloud**. Using your temporary role session,
CryoStack creates whatever is missing in **your** account — nothing is
created in a CryoStack-owned account:

- an S3 bucket for run input/output (`cryostack-runs-<your-account-id>`);
- an ECR repository holding the exact, digest-pinned tested container image;
- an AWS Batch compute environment, job queue, and job definition.

The **Account / Storage / Containers / Compute** rows move to **Ready** as
each step completes. **Prepare cloud is safe to run again** — existing
resources are reused, never recreated or duplicated.

## Reviewing and launching a run

Once infrastructure is **Ready**, a **RUN ESTIMATE** appears (expected
runtime, requested resources, and an estimated AWS cost when pricing is
available — on **Fargate**; **EC2** has no cost model implemented yet, so
its review honestly shows **Estimated cost: unavailable** rather than a
guessed figure). Click **Review & Launch** to open the full review card, which
shows the experiment, the AWS account and region, the resources, and an
infrastructure-readiness checklist. **Launch cloud run** is only enabled
once every check passes — CryoStack never launches a configuration it
cannot honestly claim is ready, and it asks you to review again if you
change anything after opening the review.

AWS charges apply to your own AWS account for whatever the run actually
uses; cost figures shown here are estimates only, not a bill.

## Monitoring a run and retrieving results

The underlying job passes through the same states either way:

```text
Staging → Submitting → Queued → Running → Completed
                                        ↘ Failed
                                        ↘ Cancelled
```

**How you observe those states, and how results come back, currently
differs by application — this is a real implementation difference, not an
unvalidated version of the same behavior:**

- **CryoLauncher** shows a **CLOUD RUN** card that tracks the job in the
  background and automatically syncs results on completion — no click
  required before Results is populated. See
  <a href="../applications/icesheets/user_manual.html#connect-aws-account">Connect
  AWS Account</a> (step 7) for the full **View log** / **View results** /
  **Terminate** walkthrough.
- **ICESEE** has no background poller — you click **Check status** yourself,
  and opening a completed run triggers a best-effort result sync before
  showing Results. See
  <a href="../applications/icesee/user_manual.html#cloud-mode">ICESEE Cloud
  Mode</a> for the exact steps.

**View log** reads CloudWatch Logs from whichever log group the job's own
Batch job definition actually configured — never a single fixed group — so
it works the same way whether the job used the CryoStack-managed log group
or AWS Batch's own default. If the run's log stream is not available yet
(too early after submission) or genuinely absent, CryoStack says so directly
in the Run Log rather than presenting it as a run failure — **your job and
its results are unaffected either way.**

## Worked examples verified on AWS

See <a href="#scope">Validated workflows</a> above for exactly which
configurations have been confirmed end-to-end, and
<a href="#compute-mode-fargate-default-or-ec2-advanced">Compute mode</a>
for the EC2-specific evidence (job queue/definition names). Every validated
run follows the identical Connect → Prepare cloud → Review & Launch →
Monitor → Results sequence described above; only the application/example
you open and, for an EC2 run, selecting **Advanced → EC2 → On-Demand** under
Compute mode before Prepare cloud, differ.

For the exact, button-by-button steps:

- **CryoLauncher** — see
  <a href="../applications/icesheets/user_manual.html#connect-aws-account">Connect
  AWS Account</a> in the CryoLauncher User Manual.
- **ICESEE** — see
  <a href="../applications/icesee/user_manual.html#cloud-mode">Cloud Mode</a>
  in the ICESEE User Manual for the full Lorenz-96 walkthrough, including
  the **Processes = 1** restriction (see
  <a href="#verified-runtime-contracts">Verified runtime contracts</a>
  below) and its own monitoring/retrieval steps.

See <a href="#cleanup">Cleanup</a> below before you consider any run
finished — nothing about the AWS infrastructure a run used is removed
automatically.

## Cleanup

Cleanup is not one action — CryoStack handles some of it, and some of it is
entirely manual today:

- **Individual Batch jobs** — CryoLauncher's **Terminate** button, and
  ICESEE's own cloud termination action, stop a running or queued job
  directly from CryoStack. This works today.
- **AWS job history** — nothing to do; AWS retains completed/terminated job
  records at no ongoing cost. CryoStack does not need to (and does not)
  clean these up.
- **S3 input/output objects** — **not deleted automatically.** Every run's
  staged inputs and outputs persist in your S3 bucket until you remove them
  yourself.
- **AWS Batch resources** (compute environment, job queue, job
  definitions) — created once by Prepare cloud and reused afterward.
  **There is currently no in-app "unprepare" or teardown action.**
- **Disconnecting an AWS account** (the **Disconnect** button) — removes
  only CryoStack's local connection record (ExternalId, role ARN,
  metadata). **It does not delete or modify anything in AWS.**
- **The CloudFormation stack and its IAM role** (from Connecting your AWS
  account) — **not deleted through CryoStack.** If you want to tear down a
  connection's AWS infrastructure entirely, delete the stack yourself from
  the AWS Console or CLI; deleting it removes the IAM role with it.

## Verified runtime contracts

**ICESEE's** cloud container has been verified, locally and against the
exact published image, for exactly:

- **Example:** `lorenz96`
- **Processes (`ICESEE_NP`):** `1`

Multi-process execution was tested and found unsafe on this image (the
default execution path has no coordination between MPI ranks and races on
shared output files), and no ICESEE example other than Lorenz-96 has been
run against the cloud container. CryoStack's Review card enforces this
directly for ICESEE — a different example or a higher process count is
**refused with an explicit reason**, never silently changed to a value that
would pass. This is a deliberate design choice: the goal is an honest
preflight, not a best-effort launch.

An ISSM-coupled ICESEE forecast model is a separate, stronger limitation
than the process-count restriction above. ICESEE's Cloud Environment shows
the same MATLAB license field CryoLauncher's does, for interface
consistency, but that field is not currently connected to ICESEE's own
Cloud submission path — no institutional license or Connector tunnel is
actually configured for an ICESEE Cloud job. An ISSM-based ICESEE workflow
that needs MATLAB is therefore not operational on Cloud today, independent
of and in addition to the example/process restriction above. This does not
affect ICESEE's Lorenz-96 or Icepack forecast models, which need no
license, or CryoLauncher's own ISSM Cloud path, which does have this
connectivity (see <a href="#scope">Validated workflows</a> above).

**Icepack's** cloud path has confirmed one example end-to-end,
`04-synthetic-ice-stream-xy`, sharing the same Firedrake export and
figure-capture code the Remote/Slurm path uses. Unlike ICESEE, CryoLauncher
does not currently refuse a different Icepack example at Review — the code
path is model-neutral, so other examples are expected to run, but only this
one has actually been confirmed against the cloud container. Treat other
Icepack examples on Cloud the same way you would treat them on Remote:
architecturally supported, not yet individually verified.

## Screenshots

```{admonition} Screenshots not yet captured
:class: note
The repository does not yet contain screenshots for this workflow. The UI
is stable enough to capture now; the following would materially improve
this page and are listed in capture order:

1. **AWS ACCOUNT** panel before connecting (the "Connect AWS Account" state).
2. The CloudFormation Quick Create page, pre-filled, in the AWS console.
3. **AWS ACCOUNT** panel showing **● Connected** with account ID.
4. **Prepare cloud** in progress, then Account/Storage/Containers/Compute
   all **Ready**.
5. The **Review cloud run** card for the Lorenz-96 / Processes = 1 example,
   showing **ICESEE runtime: Ready**.
6. The **CLOUD RUN** status card mid-run (**Running**).
7. The Workspace **Results** tab after a completed cloud run.

Until these are captured, no screenshots are embedded on this page —
inserting placeholders styled as real screenshots would be misleading.
```

## Downloads and reference material

- **CloudFormation template source** —
  `deployment/cloudformation/cryostack-execution-role.json` in the
  CryoStack repository is the exact source of the template your
  administrator publishes at the URL CryoStack opens during
  **Open AWS Setup**. See
  <a href="#preparing-cloud-infrastructure">Preparing cloud infrastructure</a> above
  for what it creates.
- [CryoStack on GitHub](https://github.com/ICESEE-project/CryoStack) —
  browse the full source, including the CloudFormation template and the
  cloud execution code referenced throughout this page.

## Troubleshooting and verification

**"Resource of type 'AWS::IAM::Role' ... already exists" during stack
creation.** This was a real defect in an earlier template revision (a fixed
role name collided across connections) and has been fixed — CloudFormation
now generates a unique role name per stack. If you still see this error,
your deployment's published template may be stale; ask your administrator
to confirm it matches the checked-in
`deployment/cloudformation/cryostack-execution-role.json`
(`sha256sum` the two files and compare).

**A CloudFormation stack is stuck in `ROLLBACK_COMPLETE`.** Retrying with
the exact same stack name is refused by AWS once a stack has failed. Use
**Retry connection**, not a manual re-submission of the same Quick Create
URL — CryoStack mints a fresh, non-colliding stack name for the same
connection without changing your ExternalId or an already-working role.

**Launch is disabled and the review lists a reason.** This is intentional —
read the listed reason (infrastructure not yet Ready, account connection
stale, or an unverified example/process count for ICESEE) rather than
retrying blindly; each reason names exactly what to fix.

## Related documentation

- [CryoLauncher User Manual — Execution modes and backends](https://cryostack.eas.gatech.edu/applications/icesheets/user_manual.html#execution-modes-and-backends)
- [ICESEE User Manual — Cloud Mode](https://cryostack.eas.gatech.edu/applications/icesee/user_manual.html#cloud-mode)
- [Developer Guide](https://cryostack.eas.gatech.edu/docs/developer_guide.html)
- [CryoStack Documentation](https://cryostack.eas.gatech.edu/documentation.html)

:::{raw} html
<div class="cryostack-docs-page">
  <footer class="cryostack-footer">

    <div class="cryostack-footer-main">

      <div class="cryostack-footer-brand">
        <div class="cryostack-footer-logo">CryoStack</div>
        <p>
          An integrated platform for cryosphere modeling, data assimilation,
          scientific visualization, and HPC-enabled research.
        </p>
      </div>

      <div class="cryostack-footer-group">
        <h3>Platform</h3>
        <a href="../index.html">Home</a>
        <a href="../documentation.html">Documentation</a>
        <a href="../resources.html">Resources</a>
        <a href="../about.html">About</a>
      </div>

      <div class="cryostack-footer-group">
        <h3>Applications</h3>
        <a href="/icesheets/">CryoLauncher</a>
        <a href="/icesee-gui/">ICESEE</a>
        <a href="/livist/">LIVIST</a>
      </div>

      <div class="cryostack-footer-group">
        <h3>Community</h3>
        <a href="https://github.com/ICESEE-project/CryoStack" target="_blank" rel="noopener noreferrer">GitHub</a>
        <a href="https://github.com/ICESEE-project" target="_blank" rel="noopener noreferrer">ICESEE Project</a>
        <a href="https://github.com/ICESEE-project/CryoStack/issues" target="_blank" rel="noopener noreferrer">Report an Issue</a>
      </div>

    </div>

    <div class="cryostack-footer-bottom">
      <div>Developed by ICCL and PGSL at the Georgia Institute of Technology.</div>
      <div class="cryostack-footer-meta">
        <span>© 2026 CryoStack</span>
        <span>MIT License</span>
      </div>
    </div>

  </footer>
</div>
:::
