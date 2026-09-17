# Getting Started

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
    <h1>Getting Started</h1>
    <p>
      A short orientation to CryoStack: what it is, which application fits
      your work, and where to go next. It does not replace any application's
      own setup instructions — it routes you to them.
    </p>
    <div class="cryostack-docs-actions">
      <a class="cryostack-btn secondary" href="../documentation.html">
        &larr; Documentation
      </a>
    </div>
  </section>

  <section id="what-is-cryostack" class="cryostack-section">
    <div class="cryostack-section-label">What is CryoStack?</div>
    <h2>One platform, several scientific applications.</h2>
    <p class="cryostack-section-intro">
      CryoStack is the shared platform underneath CryoStack's scientific
      applications: identity, per-user workspaces, experiment records, and
      execution/result contracts that those applications reuse rather than
      each rebuilding. It is not itself a scientific application, and it
      does not impose one interface on every application built on it.
    </p>
  </section>

  <section id="which-application" class="cryostack-section">
    <div class="cryostack-section-label">Which application should I use?</div>
    <h2>Pick by scientific task, not by platform.</h2>

    <div class="cryostack-docs-summary-grid">

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">CL</div>
        <h3>CryoLauncher</h3>
        <p>Configure and run ISSM or Icepack ice-sheet models. Basic,
           Advanced, and Auto-config &middot; Beta configuration experiences
           over the same run configuration; Remote and Cloud execution.</p>
        <div class="cryostack-docs-actions">
          <a class="cryostack-btn secondary"
             href="../applications/icesheets/getting_started.html">
            CryoLauncher Getting Started
          </a>
        </div>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">IE</div>
        <h3>ICESEE</h3>
        <p>Ensemble-based state and parameter estimation for ice-sheet
           models. Organized as Local, Remote, or Cloud execution, with
           Auto-config &middot; Beta available alongside it — a different
           interface shape from CryoLauncher's, by design.</p>
        <div class="cryostack-docs-actions">
          <a class="cryostack-btn secondary"
             href="../applications/icesee/getting_started.html">
            ICESEE Getting Started
          </a>
        </div>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">FL</div>
        <h3>Frozen Legacies</h3>
        <p>Discover and work with historical Antarctic radar observations
           and derived products through a manifest-driven catalog. Not
           organized around Local/Remote/Cloud execution.</p>
        <div class="cryostack-docs-actions">
          <a class="cryostack-btn secondary"
             href="../applications/frozen_legacies/getting_started.html">
            Frozen Legacies Getting Started
          </a>
        </div>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">LV</div>
        <h3>LIVIST</h3>
        <p>Explore Antarctic englacial-temperature products inferred from
           radar and constrained by boreholes. Its own frontend and
           documentation, sharing CryoStack's deployment registry.</p>
        <div class="cryostack-docs-actions">
          <a class="cryostack-btn secondary" href="/livist/">
            Open LIVIST
          </a>
          <a class="cryostack-btn secondary"
             href="/livist/docs/livist_user_manual/">
            LIVIST User Manual
          </a>
        </div>
      </div>

    </div>
  </section>

  <section id="next" class="cryostack-section">
    <div class="cryostack-section-label">Where to go next</div>
    <h2>After setup: the User Manual.</h2>
    <p class="cryostack-section-intro">
      Once you have an application open and a first example running, the
      <a href="user_manual.html">User Manual</a> is the operational
      reference for execution, results, and troubleshooting — how to
      configure a run, choose Local/Remote/Cloud where each is available,
      submit and monitor it, then retrieve and visualize results. Building
      or extending CryoStack itself is covered separately in the
      <a href="developer_guide.html">Developer Guide</a>.
    </p>
  </section>

</div>
:::
