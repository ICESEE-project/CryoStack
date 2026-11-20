# Results & Visualization

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
    <div class="cryostack-section-label">CryoStack Documentation</div>
    <h1>Results &amp; Visualization</h1>
    <p>
      Find the right output path for all four CryoStack applications.
      CryoLauncher and ICESEE produce run results; Frozen Legacies and
      LIVIST expose scientific data products. Detailed procedures stay in
      each application's own User Manual.
    </p>
    <div class="cryostack-docs-actions">
      <a class="cryostack-btn secondary" href="user_manual.html">
        &larr; User Manual
      </a>
    </div>
  </section>
</div>
:::

---

## CryoLauncher: the structured result package

A completed CryoLauncher run (ISSM or Icepack) is exported to a
transport-neutral, versioned result package (metadata, mesh geometry, field
arrays, and any figures). A reader for each model's package loads it
without needing that model's own runtime — you do not need MATLAB
installed locally to inspect an ISSM result, for example.

1. **Retrieve** — Remote results are fetched over SSH/Connector; Cloud
   results are synchronized from S3. Both land in the same local run cache
   shape, for either backend or model.
2. **Preview** — inspect what solutions and fields a run actually produced.
3. **Render** — plot a field or time series on demand from the neutral
   package.
4. **Download** — package results and figures for offline use.

See <a href="../applications/icesheets/user_manual.html#results">Results</a>,
<a href="../applications/icesheets/user_manual.html#visualization">Visualization</a>,
and <a href="../applications/icesheets/user_manual.html#downloads">Downloads</a>
for the full walkthrough.

## ICESEE: its own results workflow

ICESEE reads each example's native results contract through its own
Results service; it does not construct CryoLauncher's result package.
Select the run, retrieve Remote or Cloud output when required, then open
**Results** for the example's scientific figures and **Files** for its output
files. Lorenz-96 shows its true/background/observed/analysed state views and
a supplementary assimilation-error view. Other examples use their own
`results.yaml`/postprocessing contract. See
<a href="../applications/icesee/user_manual.html#results-and-reports">Results and reports</a>
for the full walkthrough.

## Frozen Legacies: observations and radar products

Frozen Legacies associates shared radar observations with provenance,
imagery, derived quantities, and downloadable scientific products. It can
also keep user-provided files and generated picking outputs in a private
workspace. Availability and validation status vary by collection and product;
use the labels and provenance shown by the application. See
<a href="../applications/frozen_legacies/user_manual.html#products-and-downloads">Products and Downloads</a>
in the Frozen Legacies User Manual.

## LIVIST: published temperature products

LIVIST visualizes published englacial-temperature products and supporting
geographic or borehole layers. Downloadable datasets live in the linked data
repository, and the Python package supports analysis beyond the browser. Read
the product metadata before comparing coverage, resolution, method, or
uncertainty. See the
<a href="/livist/docs/livist_user_manual/">LIVIST User Manual</a> and
<a href="https://source.coop/englacial/ice-sheet-temperature" target="_blank" rel="noopener noreferrer">Data Repository</a>.


## Live interface walkthrough

See the [visual walkthrough](visual_walkthrough.md) for dated screenshots from the running platform, application selection, allocation administration, and the Results workspace.
