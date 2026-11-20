# Explore Scientific Data

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>

<div class="cryostack-docs-page">
  <section class="cryostack-docs-hero">
    <div class="cryostack-section-label">CryoStack Documentation</div>
    <h1>Explore Scientific Data</h1>
    <p>
      Frozen Legacies and LIVIST are CryoStack's data-centered scientific
      applications. Use them to explore observations and published products;
      they do not use the Local, Remote, or Cloud run controls found in the
      modeling applications.
    </p>
    <div class="cryostack-docs-actions">
      <a class="cryostack-btn secondary" href="user_manual.html">
        &larr; User Manual
      </a>
    </div>
  </section>

  <section id="choose-an-application" class="cryostack-section">
    <div class="cryostack-section-label">Choose an application</div>
    <h2>Historical radar or ice temperature.</h2>

    <div class="cryostack-docs-summary-grid">
      <div class="cryostack-docs-summary-card">
        <h3>Frozen Legacies</h3>
        <p>Browse historical Antarctic airborne-radar collections by dataset,
           flight, and observation. Inspect radar imagery, provenance, derived
           quantities and scientific products. Signed-in users with the
           required application access also use private ASTRA/TERRA manual
           workspaces and LYRA automatic picking; the selected dataset and
           installed picker determine which actions the page offers.</p>
        <div class="cryostack-docs-actions">
          <a class="cryostack-btn primary" href="/frozen-legacies/">Open Frozen Legacies</a>
          <a class="cryostack-btn secondary" href="../applications/frozen_legacies/getting_started.html">Getting Started</a>
          <a class="cryostack-btn secondary" href="../applications/frozen_legacies/user_manual.html">User Manual</a>
        </div>
      </div>

      <div class="cryostack-docs-summary-card">
        <h3>LIVIST</h3>
        <p>Explore Antarctic englacial-temperature products inferred from
           radar observations and constrained by boreholes. Compare published
           products, inspect geographic context and metadata, download data,
           or continue analysis with the LIVIST Python package.</p>
        <div class="cryostack-docs-actions">
          <a class="cryostack-btn primary" href="/livist/">Open LIVIST</a>
          <a class="cryostack-btn secondary" href="/livist/docs/livist_user_manual/">User Manual</a>
          <a class="cryostack-btn secondary" href="https://source.coop/englacial/ice-sheet-temperature" target="_blank" rel="noopener noreferrer">Data Repository</a>
        </div>
      </div>
    </div>
  </section>
</div>
:::

## What belongs here—and what belongs in each manual

This CryoStack page only distinguishes the two data applications and routes
you to the right documentation. Interface controls, scientific interpretation,
downloads, private workspaces, recovery, and troubleshooting remain in each
application's own User Manual so that there is one authoritative procedure to
maintain.

## How data exploration differs from running a workflow

Frozen Legacies and LIVIST are interactive scientific-data applications. You
select, filter, inspect, compare, and download data products. CryoLauncher and
ICESEE instead configure and submit computational workflows; their execution
guidance is grouped under [Run Scientific Workflows](user_execution.md).
