# CryoLauncher User Manual

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

    <h1>CryoLauncher User Manual</h1>

    <p>
      The operational guide to configuring models, editing examples in your
      own workspace, managing datasets, launching runs on remote resources,
      and exploring structured results.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary" href="/icesheets/">
        Open CryoLauncher
      </a>

      <a class="cryostack-btn secondary" href="getting_started.html">
        Getting Started
      </a>

      <a class="cryostack-btn secondary" href="resources.html">
        Resources
      </a>
    </div>

  </section>

  <div class="cryostack-app-doc-content">
:::

## 1. CryoLauncher overview

CryoLauncher is the numerical-modeling application in CryoStack. It runs in a
browser and gives you one consistent workflow for supported ice-sheet models:
choose a model and example, configure it, submit it to a computing resource,
monitor it, and explore the results.

The interface has two areas:

:::{raw} html
<div class="cryostack-manual-grid">

  <article class="cryostack-manual-card">
    <div class="cryostack-manual-number">01</div>
    <h3>Run settings</h3>
    <p>
      Model, example, Basic/Advanced mode, execution mode and backend, the
      guided configuration panel or the file editor, datasets, and the
      computing-resource settings.
    </p>
  </article>

  <article class="cryostack-manual-card">
    <div class="cryostack-manual-number">02</div>
    <h3>Workspace</h3>
    <p>
      Run history and status, per-run files, the run log, and the Results tab
      with the field-visualization panel and download controls.
    </p>
  </article>

</div>
:::

## 2. Applications and maturity

:::{raw} html
<p>
  <b>ISSM</b> <span class="cryostack-status supported">Supported</span><br>
  The Ice-sheet and Sea-level System Model. This is the mature CryoLauncher
  path: guided configuration, per-user example staging, structured result
  export, and deterministic visualization are all implemented and tested.
</p>
<p>
  <b>Icepack</b> <span class="cryostack-status dev">Experimental</span><br>
  Selectable in the interface, but curated configuration, result
  interpretation, and visualization are not yet at ISSM parity. Treat Icepack
  runs as exploratory.
</p>
:::

Basic and Advanced are **CryoLauncher-wide application modes**, not model
modes. ISSM is simply the first model implemented to full maturity behind
them.

## 3. Basic mode

Basic mode is a **guided scientific-configuration surface**. It is not a raw
model-code editor.

- **Guided configuration.** You are shown a small, curated set of parameters,
  not the full model object.
- **Solver-aware.** The panel only offers parameters that are relevant to the
  solver the selected example actually runs. For ISSM this includes
  stressbalance tolerances (`restol`, `reltol`, `abstol`) and `maxiter`, time
  stepping (`time_step`, `final_time`), transient physics toggles
  (stress balance / mass transport / thermal / grounding line / moving front /
  SMB), a friction-coefficient multiplier, an ice-rigidity (rheology&nbsp;B)
  multiplier, and curated extra requested outputs.
- **Opt-in.** Nothing changes unless you explicitly enable a parameter and set
  a value. Spatial fields such as friction or rheology&nbsp;B are applied as a
  multiplier on the existing field, never replaced by a scalar.
- **Defaults preserved.** Every parameter you do not touch keeps the value
  from the example. Basic mode never rewrites example defaults you did not ask
  it to change.
- **Validated before execution.** Each value is range- and type-checked. If a
  value is out of range or malformed, the run is blocked with a clear message
  before anything is submitted.
- **Safe staging.** When you run a Basic-mode configuration against a
  read-only application example, CryoLauncher automatically stages a
  user-owned working copy under your workspace, injects the validated
  overrides into that copy immediately before the solve, and leaves the
  canonical example untouched. If the example is already one of your own, the
  overrides are applied to it in place.

## 4. Advanced mode

Advanced mode is a **model-neutral workspace and file editor** for modifying
examples and files directly.

- **Canonical examples are read-only.** Application examples shipped with a
  model cannot be edited, renamed, or deleted. Opening a file from one shows
  it disabled.
- **Clone to My Workspace.** To edit an application example, clone it. The
  copy lands under your personal workspace as a fully user-owned example.
- **Editor lifecycle.** Open a file, edit it, and use **Save**, **Save As**
  (a new file inside your workspace), **New file**, and **Delete**. A
  **Refresh** control re-reads the file list.
- **Unsaved-change protection.** Switching file, example, model, or
  Basic↔Advanced is blocked while the editor has unsaved changes, unless you
  tick **Discard unsaved changes**. Basic↔Advanced preserves the Advanced
  buffer.
- **User examples.** Create a new example, **Rename** it, or **Delete** it.
  New examples are minimal user-owned directories; if the model adapter
  provides a starter template it is used.
- **Persistence.** User examples, files, and datasets persist across page
  reloads and sessions. Reloading rediscovers them.
- **User isolation.** Everything you create lives under your authenticated
  user's workspace. Another user cannot discover, open, edit, run, rename, or
  delete your examples or files. Canonical examples remain globally visible
  and read-only for everyone.
- **Notebooks.** `.ipynb` files are shown read-only as notebook JSON in this
  version; they are never silently converted to `.py`.

## 5. Application examples vs My Workspace

The **Example** menu merges two kinds of entry, and each entry is labelled as
canonical/read-only or user-owned/editable:

- **Application examples** — the canonical examples shipped with the model
  (for ISSM, `SquareIceShelf` is the recommended first example). Globally
  visible, read-only.
- **My Workspace examples** — examples under your personal workspace. Editable,
  private to you, and persistent.

Only directories that look like a real runnable example are offered — utility
folders such as `Data/`, `Mesh/`, or `Functions/` are filtered out of the
picker.

You do **not** need to clone before a Basic-mode run: changing a Basic-mode
parameter automatically stages a working copy. Clone explicitly when you want
to **edit files** in Advanced mode.

## 6. Creating, cloning, and editing user examples

| Action | What it does |
|---|---|
| Clone to My Workspace | Copies a canonical (or another user-owned) example into `My Workspace / examples / <model> /` with provenance recording the source. |
| New example | Creates a minimal user-owned example directory (with a model starter template if one exists). |
| Rename example | Renames one of your user examples; provenance and the path are updated. |
| Delete example | Removes only that user example. Canonical examples cannot be renamed or deleted. |

User-example names are validated — path separators, `..`, leading dots, and
absolute paths are rejected.

Deleting a user example never deletes reusable datasets, and deleting a run
never deletes examples or datasets.

## 7. Dataset management

Datasets are **reusable input files that live independently of any run or
example**, in your personal dataset area.

- **Upload.** Use the uploader to add one or more files at once. Scientific
  formats (`.mat`, `.h5`, `.nc`, `.csv`, `.dat`, `.exp`, `.txt`, `.json`,
  `.yaml`, …) are all accepted; there is no restrictive extension list. Very
  large files that exceed the browser upload size are reported clearly. Each
  file has a size cap suited to the widget uploader (50&nbsp;MB).
- **List and refresh.** Datasets appear in the explorer immediately. They are
  visible even when they are not text-editable — a distinction is made between
  *visible file* and *editable text file*.
- **Overwrite protection.** Re-uploading a file with the same name is skipped
  unless you tick **Overwrite existing**.
- **Reference from an example.** From one of your user examples, **Reference
  in example** links a dataset (optionally under a chosen relative path). This
  records a reference; it does not copy the file yet.
- **Run staging.** When you run an example that references datasets, each
  referenced dataset is copied into the run's working copy under
  `data/<as>`, and the run's provenance records what was staged. The original
  dataset stays in your dataset area.
- **Delete / unreference.** Deleting a dataset requires confirmation and
  verifies ownership. Removing a reference does not delete the dataset.
  Deleting a dataset that an example still references warns you that the
  reference may become invalid; it does not touch the example's other files.
- **Isolation.** Another user cannot discover, read, reference, rename, or
  delete your datasets.

## 8. Execution modes and backends

**Execution mode** (in Run settings):

:::{raw} html
<p>
  <b>Remote</b> <span class="cryostack-status supported">Supported</span>
  &nbsp;— run on a Linux server or HPC cluster you have access to, over direct
  SSH or through the CryoStack Connector. Slurm resource settings appear when
  the resource is scheduler-managed.
</p>
<p>
  <b>Cloud</b> <span class="cryostack-status dev">In development</span>
  &nbsp;— AWS Batch execution. Infrastructure provisioning and the run
  contract exist, but real cloud execution has not been accepted. Do not
  depend on Cloud for production work yet.
</p>
:::

**Backend** (under Remote):

- **ICESEE-Container** — run inside a container. The container source can be:
  - **Docker / OCI** with a *tested* image — the validated container path;
  - **Local SIF** — a pre-built `.sif` on the remote resource;
  - **ICESEE-Containers (git)** — build from the container definitions.
- **ICESEE-Spack** — run against a Spack-managed software environment on the
  remote resource. First-time use requires onboarding (Section&nbsp;9).

The tested-image path pins the container by a verified digest so the software
stack is reproducible.

## 9. Preparing and launching runs

### Environment preparation

Some backends need a one-time setup on the remote resource:

- **Remote + ICESEE-Spack.** Use **Check environment** for a fast probe
  (repository, activation, `ISSM_DIR`, executables). Use **Prepare
  environment** to install or repair it — this runs as a durable setup job on
  the resource, not synchronously in the browser. After preparation, a deep
  verification confirms the environment is genuinely usable before it is
  marked **Ready**. A scientific run is blocked until the live check reports
  Ready, with a clear message.
- **Remote + Container (tested image).** No preparation step.
- **ISSM + MATLAB licensing.** ISSM runs MATLAB inside the container. The
  MATLAB license is a property of the compute resource, injected at run time.
  If the selected resource has no license configured, the run fails fast with
  a clear message before MATLAB is launched.

### Launching

Before submitting, confirm the model and example, the run target, the
execution mode and backend, authentication and remote directory, and any
scheduler resources. Submit the run. The Run log reports staging, the
submission command, the scheduler job id, and progress.

## 10. Run monitoring and history

- **Runs panel.** Lists your run history with model, date, and status. Select
  a run to make it the active run for logs and results.
- **Run log.** Shows connector activity, file staging, the submission command,
  the job id, standard output and error, warnings, failures, and output
  locations. A scheduler job keeps running after you close the browser, as
  long as submission completed.
- **Files panel.** Shows the selected run's workspace files.
- **Isolation.** You only see your own runs. A run id owned by another user is
  simply absent from your history.

## 11. Results

CryoLauncher discovers **what a completed ISSM run actually produced**, rather
than assuming every example has the same outputs.

### Preview Results

Select a completed run, open the **Results** tab, and click **Preview
Results**. CryoLauncher:

1. synchronizes the run's outputs from the remote resource into a local cache
   for that run;
2. reads the structured result package;
3. populates the field-visualization panel;
4. renders an initial recommended plot.

If the outputs have not been fetched yet, the panel says so and offers a
**Fetch results** button. The controller never performs remote transfers
itself — fetching is always the execution backend's responsibility.

### Preview Results vs Render

- **Preview Results** — fetch/synchronize, discover, populate the selectors,
  and show a useful initial preview.
- **Render** — draw the specific Solution / Field / Timestep currently
  selected.

### Legacy runs

Runs produced before structured export still work: their existing figures and
model file are shown, with a note that the structured selector is unavailable
for that run. Old results are never silently rewritten.

## 12. Visualization

The **Field visualization** panel is model-neutral: it only knows
Solution → Field → Timestep and delegates the scientific rendering to the
model.

- **Solution selector.** Lists the solution(s) the run actually produced
  (for example `StressbalanceSolution`, `TransientSolution`,
  `ThermalSolution`). Only what exists in the run appears.
- **Field selector.** Lists the fields in the selected solution, most useful
  first (for a stress-balance run, `Vel` and `Pressure` before the rest).
  Changing the solution repopulates the field list.
- **Timestep selector.** Shown only for transient results. It offers
  **Final** plus each available timestep, and defaults to Final. For a field
  that was only computed at some timesteps, only those are offered.
- **Field types, at a user level:**
  - *nodal* spatial fields (defined at mesh vertices) — rendered as a
    triangulation field map;
  - *elemental* spatial fields (defined per element) — rendered as an
    element-coloured map;
  - *scalar transient diagnostics* (a single number per timestep, e.g. ice
    volume) — rendered as a time series;
  - *static scalar diagnostics* and other shapes — reported with a clear
    reason rather than a broken plot.
- **Deterministic rendering.** The same selection always produces the same
  plot. Rendering does not require MATLAB or a live model installation, and
  figures with masked / non-finite regions (common on ice fronts) are drawn
  with those regions omitted rather than failing.
- **Not everything is plottable.** Available solutions and fields come from
  the actual run. Unusual result shapes are handled explicitly — an
  unsupported field shows a short reason and never breaks the Results tab.

## 13. Downloads

From the Results controls:

- **Download Results** — the full structured output package as an archive.
- **Download Figures** — only the rendered figures.

Downloads operate on the local cache for the selected run, so run Preview
Results (or Fetch results) first.

## 14. Reproducibility and provenance

Each run records provenance so it can be understood later:

- the source example and whether a working copy was staged;
- Basic-mode overrides that were applied (which parameters, which values);
- datasets that were staged into the run;
- the container image or software environment used, resolved to a specific
  identity (a tested image is pinned by digest);
- the run's status and timing.

Sensitive values — credentials and the MATLAB license value — are treated as
runtime configuration only and are never written into provenance, the run
manifest, or the logs.

### Result format (reference)

The structured result package is a transport-neutral directory:

```text
outputs/
  metadata.json          # what the run produced: solutions, fields, shapes
  mesh/mesh.h5           # mesh coordinates and connectivity
  fields/<Solution>/...  # one file per exported field
  model/md_final.mat    # the full model, for MATLAB-based analysis
  figures/              # rendered figures (initially empty)
```

You normally never interact with these files directly — the Results tab and
the download controls do it for you. `metadata.json` is the authoritative
description of what a run produced.

## 15. Troubleshooting

:::{raw} html
<div class="cryostack-troubleshooting">

  <details>
    <summary>The Results selectors are empty</summary>
    <p>
      Click <b>Preview Results</b> (or <b>Fetch results</b>) for the selected
      run. The selectors populate only after the run's outputs are
      synchronized into the local cache. If the panel says the run is a legacy
      run, structured visualization is not available for it.
    </p>
  </details>

  <details>
    <summary>A Basic-mode run is blocked before submission</summary>
    <p>
      A curated parameter is out of range or not applicable to the example's
      solver. The message names the parameter; adjust or disable it.
    </p>
  </details>

  <details>
    <summary>ICESEE-Spack run is blocked as "not ready"</summary>
    <p>
      Run <b>Check environment</b>, then <b>Prepare environment</b> if needed.
      A scientific run is only allowed once the live probe reports Ready.
    </p>
  </details>

  <details>
    <summary>ISSM run fails immediately on a MATLAB license error</summary>
    <p>
      The selected compute resource has no MATLAB license configured. Choose a
      resource that does, or contact the platform administrators.
    </p>
  </details>

  <details>
    <summary>Connector status stays offline</summary>
    <p>
      Confirm the connector is running on your workstation and that the
      browser and connector share the same session identifier.
    </p>
  </details>

  <details>
    <summary>Slurm rejects the job</summary>
    <p>
      Review the account, partition, wall time, memory, and node/task counts
      against the cluster's policies.
    </p>
  </details>

  <details>
    <summary>An example or field you expected is missing</summary>
    <p>
      The example picker only lists runnable examples, and the Field selector
      only lists what the run actually produced. Confirm the run completed and
      that the analysis you expected was enabled.
    </p>
  </details>

</div>
:::

## Related documentation

- [Getting Started](getting_started)
- [CryoLauncher Resources](resources)
- [CryoStack Documentation](https://cryostack.eas.gatech.edu/documentation.html)
- [Open ICESEE](https://cryostack.eas.gatech.edu/icesee-gui/)

:::{raw} html
  </div>
</div>
:::
