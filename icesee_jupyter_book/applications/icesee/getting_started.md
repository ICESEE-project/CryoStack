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
      ICESEE Documentation
    </div>

    <h1>Getting Started with ICESEE</h1>

    <p>
      Configure and run your first ensemble data assimilation workflow
      through CryoStack using supported models, filters, observations,
      and computing backends.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary" href="/icesee-gui/">
        Open ICESEE
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

ICESEE, the Ice Sheet State and Parameter Estimator, is the data assimilation
application within CryoStack. It combines a forecast model, an ensemble Kalman
filter, and observations to estimate model states and uncertain parameters.

This guide runs a first experiment — Lorenz-96 in **Local** mode — and points
to the Remote and Cloud paths.

## Before You Begin

You need:

- a modern web browser;
- access to the CryoStack platform;
- for **Remote** runs: your own access to an HPC system (username, allocation,
  and an SSH key you can register) — the same access CryoLauncher uses;
- for **Cloud** runs: an AWS account you can connect to CryoStack.

A first Lorenz-96 experiment needs none of the Remote or Cloud prerequisites.

## Open ICESEE

Open
[https://cryostack.eas.gatech.edu/icesee-gui/](https://cryostack.eas.gatech.edu/icesee-gui/).

The interface has two areas:

1. **Run settings** — the **Local / Remote / Cloud** tabs, the example,
   filter, ensemble size, seed, output, and the example's parameter sections.
2. **Workspace** — **Runs**, **Files**, **Run Log**, and **Results**.

## Choose Where to Run

:::{raw} html
<p>
  <b>Local</b> <span class="cryostack-status supported">Supported</span>
  &nbsp;— a single process on the CryoStack server, with no scheduler or MPI.
  For Lorenz-96 and small tests.
</p>
<p>
  <b>Remote</b> <span class="cryostack-status supported">Supported</span>
  &nbsp;— a Slurm batch job on an HPC system, under your own HPC identity,
  using ICESEE-Spack or a container. Required for ISSM.
</p>
<p>
  <b>Cloud</b> <span class="cryostack-status dev">Lorenz-96 only</span>
  &nbsp;— AWS Batch on your own AWS account, through the same Connect AWS
  Account &rarr; Prepare cloud &rarr; Review &amp; Launch flow as CryoLauncher.
  Verified for exactly one configuration: Lorenz-96 at a single process.
  Other examples, or more processes, are refused at Review.
</p>
:::

## Select an Example

The **Example** menu shows each example's status:

| Example | Status | Where it runs today |
|---|---|---|
| Lorenz-96 | fully runnable locally | Local and Cloud (one process); Remote is available |
| ISSM (ISMIP_Choi) | fully runnable in Remote | Remote |
| Flowline | under development | not yet an end-to-end workflow |
| Icepack | under development | not yet an end-to-end workflow |

See <a href="user_manual.html#examples-and-maturity">Examples and maturity</a>
in the User Manual for details.

## Configure the Experiment

- **Preset** — only **Default** (the example's own configuration) is offered.
- **Filter** — **EnKF**, **DEnKF**, **EnTKF**, or **EnRSKF**. Keep the
  example's default for a first run.
- **Ensemble size** — 1 to 200 members (default 30). Larger ensembles
  represent uncertainty better and cost more.
- **Seed** — the random seed; keep it fixed to repeat an experiment exactly.
- **Output** — which result set the report reads: *true-wrong* (the
  demonstration output) or *EnKF*.
- **Generate report** — run the example's results notebook after a
  successful Local run.

The example's parameter sections (`physical-parameters`,
`modeling-parameters`, `enkf-parameters`) hold everything else, including the
observation settings and the parallel settings. Review them, but leave them
unchanged for a first run.

## Run Your First ICESEE Experiment

1. Open ICESEE and select the **Local** tab.
2. Choose **Lorenz-96** in the **Example** menu.
3. Keep the default filter, ensemble size, and seed.
4. Leave **Output** at *true-wrong* and **Generate report** ticked.
5. Click **Run**.
6. Follow the **Run Log**: configuration, ensemble initialization, forecast
   and analysis cycles, then report generation.
7. When the run finishes, select it in **Runs** and open **Results**.

Lorenz-96 is a lightweight synthetic model, so this completes quickly and
shows the whole assimilation cycle: a true state and synthetic observations
are generated, the ensemble is initialized and advanced, and the filter
updates it at each observation time.

## View Results

**Results** shows the figures the run produced and lists its HDF5 result
files; **Download results** downloads them. With **Generate report** ticked,
the report notebook is executed into the run folder.

## Next Steps

- Read the [ICESEE User Manual](user_manual) for Remote and Cloud runs, the
  parameter sections, and the parallel settings.
- Review [ICESEE Resources](resources) for repositories, publications, models,
  and data assimilation references.
- Open <a href="../icesheets/getting_started.html">CryoLauncher</a> for model
  runs without data assimilation.

:::{raw} html
  </div>
</div>
:::
