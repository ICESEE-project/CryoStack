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

**ISSM is the mature CryoLauncher path today.** Icepack is available in the
interface and shares the same discovery, workspace, staging, remote-submission,
run-history and downloads workflow; after a run its figures and output files are
collected into the results package. Icepack does **not** yet have curated
Basic-mode configuration or an interactive field viewer (edit the
notebook/script in Advanced mode), and Cloud execution is ISSM-only. Cloud
execution generally is in development and is not yet accepted for real runs; use
**Remote** execution.

## Before you begin

You need:

- a modern web browser;
- access to the CryoStack platform;
- for **Remote** execution: **your own** access to a Linux/HPC computing
  resource — your HPC username, your allocation, and the ability to add an SSH
  key to your account (directly or through your institution's portal). CryoStack
  connects *as you*; it does not provide HPC accounts. See
  <a href="#configure-access-to-your-hpc-resource-remote">Configure access to
  your HPC resource</a> below.

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
  <span class="cryostack-status supported">Supported</span>
  &nbsp;— the Ice-sheet and Sea-level System Model. This is the mature
  CryoLauncher path: curated configuration, structured results, and
  deterministic visualization are all implemented.
</p>
<p>
  <b>Icepack</b>
  <span class="cryostack-status dev">Experimental</span>
  &nbsp;— available in the interface, but configuration, result
  interpretation, and visualization are not yet at ISSM parity.
</p>
:::

The rest of this guide uses **ISSM**.

## 3. Basic or Advanced mode

Basic and Advanced are CryoLauncher-wide application modes.

**Basic mode** is a *guided* scientific-configuration surface. You adjust a
small set of curated, validated parameters (for ISSM: solver tolerances and
iteration limits, time stepping, transient physics toggles, friction and ice
rigidity multipliers, extra requested outputs). Example defaults are kept
unless you explicitly change a value, and every change is range-checked before
the run is submitted. You never edit raw model code in Basic mode.

**Advanced mode** is a user-owned workspace and file editor. You open and edit
the actual example files (`runme.m`, parameter files, notebooks, YAML/JSON),
with Save / Save As / New / Delete and unsaved-change protection. Application
(canonical) examples are read-only — Advanced mode offers **Clone to My
Workspace** to make an editable copy.

For a first run, start with **Basic mode**.

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
  <span class="cryostack-status dev">In development</span>
  &nbsp;— AWS Batch execution. Provisioning and the run contract exist, but
  real cloud execution has not been accepted yet.
</p>
:::

For **Remote**, choose a backend:

- **ICESEE-Container** — run inside a container. The **Docker / OCI** source
  with a *tested* image is the validated container path. Local SIF and the
  ICESEE-Containers (git) build are also available.
- **ICESEE-Spack** — run against a Spack-managed software environment on the
  remote resource. First-time use requires an onboarding step (below).

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
      ↓  Open Connector Setup   (shows a pairing code)
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
and validates every value before the run is allowed.

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

Submit the run. The **Run log** reports staging, the submission command, the
scheduler job id, and progress. A scheduler job keeps running if you close the
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

Legacy runs (from before structured export) still show their existing figures
and model file, with a note that the structured selector is unavailable.

## 11. Download

From the Results controls:

- **Download Results** — the full structured output package as an archive.
- **Download Figures** — just the rendered figures.

## Next steps

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
