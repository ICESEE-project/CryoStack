# CryoStack

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>
:::

:::{raw} html
<div class="cryostack-home">

  <section class="cryostack-hero-simple">
    <div>
      <div class="cryostack-kicker">Cryosphere Computing Platform</div>
      <h1>CryoStack</h1>
      <p>
        A unified web platform for launching cryosphere simulations, running data
        assimilation workflows, and connecting scientific applications to HPC and cloud resources.
      </p>

      <div class="cryostack-actions">
        <a class="cryostack-btn primary" href="documentation.html">Documentation</a>
        <a class="cryostack-btn secondary" href="#applications">Explore Applications</a>
      </div>
    </div>
  </section>

  <section id="applications" class="cryostack-section">
    <div class="cryostack-section-label">Available Applications</div>
    <h2>Start from an application.</h2>

    <div class="cryostack-grid">

      <div class="cryostack-card featured">
        <div class="cryostack-card-tag">Model Simulation</div>
        <h3>CryoLauncher</h3>
        <p>Run supported ice-sheet models directly through an interactive browser interface.</p>
        <div class="cryostack-mini-list">
          <span>ISSM</span><span>Icepack</span><span>Containers</span><span>Spack</span>
        </div>
        <a class="cryostack-card-btn" href="/icesheets/">Open Modeling GUI</a>
      </div>

      <div class="cryostack-card featured">
        <div class="cryostack-card-tag green">Data Assimilation</div>
        <h3>ICESEE</h3>
        <p>
          Run coupled ICESEE workflows for state estimation, parameter inference,
          and ensemble-based data assimilation with supported ice-sheet models.
        </p>
        <div class="cryostack-mini-list green-list">
          <span>EnKF</span><span>DEnKF</span><span>EnTKF</span><span>EnRSKF</span>
        </div>
        <a class="cryostack-card-btn green-btn" href="/icesee-gui/">Open ICESEE GUI</a>
      </div>

    <div class="cryostack-card">
      <div class="cryostack-card-tag green">Radar-Derived Products</div>

      <h3>Living Ice Sheet Temperature</h3>

      <p>
        Explore Antarctic ice-sheet temperatures inferred from radar observations
        and constrained by borehole measurements.
      </p>

      <a class="cryostack-card-btn green-btn" href="/livist/">
        Open LIVIST
      </a>
    </div>

      <div class="cryostack-card muted">
        <div class="cryostack-card-tag gray">Coming Soon</div>
        <h3>Application 4</h3>
        <p>Additional cryosphere tools will be integrated into the platform.</p>
        <a class="cryostack-card-link" href="resources.html">View roadmap →</a>
      </div>

    </div>
  </section>

</div>
:::
