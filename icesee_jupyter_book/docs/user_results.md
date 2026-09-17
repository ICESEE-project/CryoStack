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
      Every CryoStack execution path — Local, Remote, or Cloud — lands a
      run's results in the same shape, so retrieval and visualization work
      the same way regardless of where a run executed.
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

## The shared result lifecycle

A completed run is exported to a transport-neutral, versioned result
package (metadata, mesh geometry, field arrays, and any figures). A reader
for each model's package loads it without needing that model's own
runtime — you do not need MATLAB installed locally to inspect an ISSM
result, for example.

1. **Retrieve** — Remote results are fetched over SSH/Connector; Cloud
   results are synchronized from S3. Both land in the same local run cache
   shape.
2. **Preview** — inspect what solutions and fields a run actually produced.
3. **Render** — plot a field or time series on demand from the neutral
   package.
4. **Download** — package results and figures for offline use.

## Application-specific detail

- CryoLauncher: <a href="../applications/icesheets/user_manual.html#12-results">Results</a>,
  <a href="../applications/icesheets/user_manual.html#13-visualization">Visualization</a>,
  <a href="../applications/icesheets/user_manual.html#14-downloads">Downloads</a>.
- ICESEE: <a href="../applications/icesee/user_manual.html#run-log-and-results-preview">Run Log and Results Preview</a>.

## Scope

Not every application uses the shared result-package/visualization path in
the same way today — ICESEE's own assimilation diagnostics, for instance,
do not yet use it. See each application's User Manual for what is actually
available.
