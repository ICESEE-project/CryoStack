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
      For CryoStack's two workflow-execution applications — CryoLauncher
      and ICESEE — a completed run's results can be retrieved, inspected,
      and visualized, though the underlying representation differs between
      them; see below for what each actually does. Frozen Legacies and
      LIVIST are their own applications with their own interaction models,
      not a run/results lifecycle — see
      <a href="user_apps.html">Applications &amp; Workflows</a>.
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

ICESEE currently has its own, separate results path — not the structured
result package above. A completed run's output files and any generated
figures are presented directly from ICESEE's own experiment/run-record
tooling: retrieve them from the run's Remote or Cloud location, then
inspect the file listing and any generated images through ICESEE's own Run
Log and Results Preview. See
<a href="../applications/icesee/user_manual.html#run-log-and-results-preview">Run Log and Results Preview</a>
for the full walkthrough.
