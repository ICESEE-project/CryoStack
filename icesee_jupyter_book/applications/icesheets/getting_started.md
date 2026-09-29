# Getting Started

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>

<div class="cryostack-app-doc-page">

  <section class="cryostack-app-doc-hero">

    <div class="cryostack-section-label">
      CryoLauncher Documentation
    </div>

    <h1>Getting Started with CryoLauncher</h1>

    <p>
      Configure and run your first ice-sheet simulation through CryoStack,
      then inspect the structured results — without installing the scientific
      software stack yourself.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary" href="/icesheets/">
        Open CryoLauncher
      </a>

      <a class="cryostack-btn secondary" href="user_manual.html">
        User Manual
      </a>

      <a class="cryostack-btn secondary" href="resources.html">
        Resources
      </a>
    </div>

  </section>

  <div class="cryostack-app-doc-content">
:::

CryoLauncher is the numerical-modeling application in CryoStack. It runs in a
web browser and lets you choose a model and example, configure it through a
guided or an advanced editing workflow, submit the run to a computing
resource, follow it in a run log, and then explore the results — figures,
fields, and downloadable output packages.

CryoLauncher supports two ice-sheet models — **ISSM** and **Icepack** — on
two execution paths: **Remote** (an HPC cluster or server you have access to)
and **Cloud** (AWS Batch on your own AWS account). Both models have guided
Basic-mode configuration, structured results, and field visualization; ISSM
runs MATLAB and therefore needs a MATLAB license, Icepack does not. The
[User Manual](user_manual) lists where the two models differ and exactly which
Cloud options have been validated.

This guide walks through a first **Remote** run with ISSM. The Cloud path
shares every step except where the run executes — see
<a href="#running-on-cloud-instead">Running on Cloud instead</a>.

## Before you begin

You need:

- a modern web browser;
- access to the CryoStack platform;
- for **Remote** execution: **your own** access to a Linux/HPC computing
  resource — your HPC username, your allocation, and the ability to add an SSH
  key to your account (directly or through your institution's portal). CryoStack
  connects *as you*; it does not provide HPC accounts. See
  <a href="#configure-access-to-your-hpc-resource-remote">Configure access to
  your HPC resource</a> below;
- for **Cloud** execution: an AWS account in which you can create a
  CloudFormation stack (one IAM role), and for ISSM your institution's MATLAB
  license information.

Browsing the interface and preparing a run does not require a local
installation.

## The workflow at a glance

:::{raw} html
<div class="cryostack-manual-grid">

  <article class="cryostack-manual-card">
    <div class="cryostack-manual-number">01</div>
    <h3>Choose &amp; configure</h3>
    <p>
      Pick a model and example, choose Basic or Advanced mode, choose an
      execution backend, and set the scientific and resource options.
    </p>
  </article>

  <article class="cryostack-manual-card">
    <div class="cryostack-manual-number">02</div>
    <h3>Prepare &amp; run</h3>
    <p>
      Check or prepare the environment where required, submit the run, and
      follow progress in the run log.
    </p>
  </article>

  <article class="cryostack-manual-card">
    <div class="cryostack-manual-number">03</div>
    <h3>Results &amp; download</h3>
    <p>
      Preview the structured results, render a Solution / Field / Timestep,
      and download the result package or figures.
    </p>
  </article>

</div>
:::

## 1. Open CryoLauncher

Open [https://cryostack.eas.gatech.edu/icesheets/](https://cryostack.eas.gatech.edu/icesheets/).

The interface has two areas:

1. **Run settings** — model, example, mode, execution backend, configuration,
   and computing resources.
2. **Workspace** — run history, files, the run log, and results.

## 2. Choose an application / model

Select the model from the **Model** menu:

:::{raw} html
<p>
  <b>ISSM</b>
  <span class="cryostack-status supported">Supported — Remote and Cloud</span>
  &nbsp;— the Ice-sheet and Sea-level System Model: solver-aware Basic-mode
  configuration, structured results, and Solution / Field / Timestep
  visualization. Needs a MATLAB license.
</p>
<p>
  <b>Icepack</b>
  <span class="cryostack-status supported">Supported — Remote and Cloud</span>
  &nbsp;— the Firedrake-based glacier-flow library: Basic-mode ice
  temperature and timestep count, structured results, and field maps of the
  final state. No MATLAB license needed.
</p>
:::

The rest of this guide uses **ISSM**.

## 3. Basic or Advanced mode

Basic and Advanced are CryoLauncher-wide application modes.

**Basic mode** is a *guided* scientific-configuration surface. You adjust a
small set of curated, validated parameters (for ISSM: solver tolerances and
iteration limits, time stepping, transient physics toggles, friction and ice
rigidity multipliers, extra requested outputs; for Icepack: ice temperature
and the number of timesteps). Example defaults are kept
unless you explicitly change a value, and every change is range-checked before
the run is submitted. You never edit raw model code in Basic mode.

**Advanced mode** is a user-owned workspace and file editor. You open and edit
the actual example files (`runme.m`, parameter files, notebooks, YAML/JSON),
with Save / Save As / New / Delete and unsaved-change protection. Application
(canonical) examples are read-only — Advanced mode offers **Clone to My
Workspace** to make an editable copy.

For a first run, start with **Basic mode**.

Where the deployment enables it, a third option, **Auto-config · Beta**,
prepares a configuration from a short written request such as "Run
SquareIceShelf on PACE with 4 CPUs". It only proposes changes to the same
controls — it never runs anything. See
<a href="user_manual.html#auto-config-beta">Auto-config · Beta</a>.

## 4. Choose an example

The **Example** menu merges two kinds of entry:

- **Application examples** — the canonical examples shipped with the model
  (for ISSM, `SquareIceShelf` is the best first choice). These are
  **read-only**.
- **My Workspace examples** — examples you own, under your personal workspace.
  These are editable and persist across sessions. Only you can see them.

You do not need to clone before a Basic-mode run: if you change a Basic-mode
parameter against a read-only application example, CryoLauncher automatically
stages a user-owned working copy for that run and leaves the canonical example
untouched. You clone explicitly (**Clone to My Workspace**) when you want to
*edit files* in Advanced mode.

## 5. Choose an execution backend

Set the **Execution** and **Backend** menus:

:::{raw} html
<p>
  <b>Remote</b>
  <span class="cryostack-status supported">Supported</span>
  &nbsp;— run on a Linux server or HPC cluster you have access to, over SSH or
  through the CryoStack Connector. Slurm settings appear when the resource is
  scheduler-managed.
</p>
<p>
  <b>Cloud</b>
  <span class="cryostack-status supported">Supported</span>
  &nbsp;— AWS Batch on your own AWS account. ISSM and Icepack have completed
  end-to-end runs on the default Fargate compute and on EC2 On-Demand
  (single node, CPU). EC2 Spot and custom networking can be selected but are
  not yet validated; GPU and multi-node are guarded and cannot be submitted.
  See <a href="#running-on-cloud-instead">Running on Cloud instead</a>.
</p>
:::

For **Remote**, choose a backend:

- **ICESEE-Spack** (selected by default) — run against a Spack-managed
  software environment on the remote resource. First-time use requires an
  onboarding step (below).
- **ICESEE-Container** — run inside a container. Its source defaults to
  **ICESEE-Containers (git)**; choose **Docker / OCI** with a *tested* image
  for the validated container path. **Local SIF** is also available.

## 6. Configure access to your HPC resource (Remote)

For **Remote** execution you connect with **your own** HPC identity — CryoStack
does not create an account and does not run through a developer's account. In
**Run settings → Remote Connection** set:

- **Compute resource** — Resource, Host, Port (host/port are pre-filled from
  the resource profile);
- **Your HPC identity** — your **HPC username** and a **remote working
  directory** you own and can write (e.g. `~/projects/cryostack` or
  `/scratch/<your-username>/cryostack`);
- **Access** — **Connection method** and **Authentication method**.

**Recommended path — the CryoStack Connector** (a small app on your
workstation, best for VPN/campus-network clusters):

```
Connection method: CryoStack Connector
      ↓  Open Connector...   (shows a pairing code)
      ↓  download the connector for your platform, launch it
      ↓  pair  →  Connector card shows Connected
      ↓  set up your SSH key, then Check SSH Access  →  Verified
```

Only platforms listed in `/downloads/connectors/manifest.json` are offered for
download. **Direct SSH from server** is a shared-trust / developer mode, not
the normal multi-user path.

**SSH key:** CryoStack generates a key scoped to your identity. Register the
**public** key with the resource — via **Password bootstrap** (a one-time
password use that installs the key; the password is not stored) or manually
through your institution's SSH-key portal. **Never** paste a private key into a
portal or share it.

**Check SSH Access** connects, reads the remote username, and compares it to
your configured **HPC username**. A remote run is blocked (with a fresh check
at submit time) if they do not match.

The full reference — trust model, manual portal registration, VPN/MFA, Slurm
Account, troubleshooting — is in the
<a href="user_manual.html#configure-access-to-your-hpc-system">User Manual →
Configure access to your HPC system</a>.

## 7. Configure the science

**Basic mode (ISSM):** open the *ISSM configuration (Basic)* panel. Enable only
the parameters you want to change; leave the rest at the example defaults. The
panel only shows parameters relevant to the solver the example actually runs,
and validates every value before the run is allowed. For Icepack, the *Icepack
configuration (Basic)* panel offers ice temperature and the number of
timesteps.

**Advanced mode:** use the file editor to inspect and edit the run target and
supporting files in your workspace copy. Save before submitting.

## 8. Prepare / check the environment

Some backends need a one-time setup on the remote resource:

- **Remote + ICESEE-Spack** — use **Check environment** to verify the Spack
  environment, and **Prepare environment** (a durable setup job) if it is not
  ready. A run is blocked until the live check reports *Ready*.
- **Remote + Container (tested image)** — no preparation step; the tested
  image is used directly.

## 9. Run and monitor

Click **Submit job**. The **Run log** reports staging, the submission
command, the scheduler job id, and progress. A scheduler job keeps running if you close the
browser, as long as submission completed.

Open the **Runs** panel to see run history and status; select a run to inspect
its files and logs.

## 10. Results

Select the completed run and open the **Results** tab, then click
**Preview Results**. CryoLauncher fetches the run's outputs into a local cache
and reads the structured result package (`metadata.json`, `mesh/`, `fields/`,
`model/`, `figures/`).

The **Field visualization** panel then populates:

- **Solution** — the ISSM solution(s) the run produced (e.g.
  `StressbalanceSolution`).
- **Field** — the fields in that solution, most useful first (e.g. `Vel`,
  `Pressure`).
- **Timestep** — shown only for transient runs; defaults to *Final*.

An initial recommended plot is rendered automatically. Use **Render** to draw
any Solution / Field / Timestep you select. Nodal, elemental, transient, and
scalar diagnostics are each rendered appropriately; a field that cannot be
plotted shows a clear reason instead of failing.

For an **Icepack** run, the viewer shows maps of the final exported fields
(for example thickness and velocity); there is no Timestep selector.

Legacy runs (from before structured export) still show their existing figures
and model file, with a note that the structured selector is unavailable.

## 11. Download

From the Results controls:

- **Download Results** — the full structured output package as an archive.
- **Download Figures** — just the rendered figures.

## Running on Cloud instead

To run the same configuration on AWS, set **Execution** to **Cloud**. The
**Cloud Environment** panel replaces the Remote connection settings:

```
Connect AWS Account  →  Open AWS Setup (CloudFormation, in your AWS console)
      ↓  paste the role ARN  →  Verify connection  →  ● Connected
Prepare cloud        →  Storage / Containers / Compute: Ready
Review & Launch      →  check the estimate  →  Launch cloud run
CLOUD RUN card       →  View log / View results
```

You connect the account once; CryoStack never asks for AWS access keys. An
ISSM Cloud run also needs a MATLAB license configured under **Cloud
Environment → MATLAB LICENSE**. Results are retrieved automatically when the
run completes and appear in the same **Results** tab.

The
<a href="https://mediaspace.gatech.edu/media/Brian+Kyanjos+Zoom+Meeting/1_edvr6a1l" target="_blank" rel="noopener noreferrer">Icepack · Cloud</a>
video tutorial shows the whole sequence, including the AWS account setup. The
full reference — compute options, what is validated, MATLAB licensing, costs,
and cleanup — is in
<a href="user_manual.html#cloud-execution-aws">User Manual → Cloud execution
(AWS)</a>.

## Next steps

- Watch the <a href="resources.html#video-tutorials">CryoLauncher video
  tutorials</a> — complete Icepack · Cloud, ISSM · Cloud, and ISSM · Remote
  workflows.
- Read the [CryoLauncher User Manual](user_manual) for the full reference.
- Browse [CryoLauncher Resources](resources) for models, containers, examples,
  and result formats.
- Use **Advanced mode** and **Clone to My Workspace** to modify an example.
- Open [ICESEE](https://cryostack.eas.gatech.edu/icesee-gui/) for ensemble data
  assimilation.

:::{raw} html
  </div>
</div>
:::
