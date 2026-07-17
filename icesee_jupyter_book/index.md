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
    <div class="cryostack-hero-content">

      <div class="cryostack-kicker">
        Cryosphere Computing Platform
      </div>

      <h1>CryoStack</h1>

      <p class="cryostack-hero-description">
        An integrated scientific computing platform for cryosphere modeling,
        data assimilation, visualization, and HPC-enabled research.
      </p>

      <div class="cryostack-hero-statements">
        <span>Run simulations.</span>
        <span>Assimilate observations.</span>
        <span>Explore scientific datasets.</span>
        <span>Scale from laptops to supercomputers.</span>
      </div>

      <div class="cryostack-actions">
        <a
          class="cryostack-btn primary"
          href="documentation.html">
          Documentation
        </a>

        <a
          class="cryostack-btn secondary"
          href="#applications">
          Explore Applications
        </a>
      </div>

      <div class="cryostack-capabilities">
        <span>Simulation</span>
        <span>Data Assimilation</span>
        <span>Data Products</span>
        <span>HPC Computing</span>
      </div>

    </div>
  </section>

  <section id="applications" class="cryostack-section">
    <div class="cryostack-section-label">CryoStack Ecosystem</div>

    <h2>Choose the workflow that fits your research.</h2>

    <p class="cryostack-section-intro">
      CryoStack brings together numerical modeling, data assimilation,
      and scientific data products within one connected platform.
    </p>

    <div class="cryostack-grid">

      <div class="cryostack-card featured">
        <div class="cryostack-card-eyebrow">Numerical Modeling</div>
        <div class="cryostack-card-tag">Model Simulation</div>

        <h3>CryoLauncher</h3>

        <p>
          Run supported ice-sheet models directly through an interactive
          browser interface.
        </p>

        <div class="cryostack-mini-list">
          <span>ISSM</span>
          <span>Icepack</span>
          <span>Containers</span>
          <span>Spack</span>
        </div>

        <a class="cryostack-card-btn" href="/icesheets/">
          Open Modeling GUI
        </a>
      </div>

      <div class="cryostack-card featured">
        <div class="cryostack-card-eyebrow">State and Parameter Estimation</div>
        <div class="cryostack-card-tag green">
          Data Assimilation
        </div>

        <h3>ICESEE</h3>

        <p>
          Run coupled ICESEE workflows for state estimation, parameter
          inference, and ensemble-based data assimilation with supported
          ice-sheet models.
        </p>

        <div class="cryostack-mini-list green-list">
          <span>EnKF</span>
          <span>DEnKF</span>
          <span>EnTKF</span>
          <span>EnRSKF</span>
        </div>

        <a
          class="cryostack-card-btn green-btn"
          href="/icesee-gui/">
          Open ICESEE GUI
        </a>
      </div>

      <div class="cryostack-card">
        <div class="cryostack-card-eyebrow">Scientific Data Products</div>
        <div class="cryostack-card-tag green">
          Interactive Explorer
        </div>

        <h3>Living Ice Sheet Temperature</h3>

        <p>
          Explore Antarctic ice-sheet temperatures inferred from radar
          sounding observations and constrained by borehole measurements.
        </p>

        <div class="cryostack-mini-list green-list">
          <span>Radar</span>
          <span>Attenuation</span>
          <span>Boreholes</span>
          <span>Antarctica</span>
        </div>

        <a
          class="cryostack-card-btn green-btn"
          href="/livist/">
          Open LIVIST
        </a>
      </div>

      <div class="cryostack-card muted">
        <div class="cryostack-card-eyebrow">Platform Expansion</div>
        <div class="cryostack-card-tag gray">
          Coming Soon
        </div>

        <h3>Application 4</h3>

        <p>
          Additional cryosphere tools will be integrated into the platform.
        </p>

        <a
          class="cryostack-card-link"
          href="resources.html">
          View roadmap →
        </a>
      </div>

    </div>
  </section>

  <section class="cryostack-section cryostack-workflow-section">

    <div class="cryostack-section-label">
      Connected Scientific Workflow
    </div>

    <h2>How CryoStack works.</h2>

    <p class="cryostack-section-intro">
      CryoStack connects observational products, numerical models,
      data assimilation, and analysis within one extensible platform.
      Applications can be used independently or combined into a broader
      cryosphere research workflow.
    </p>

    <div class="cryostack-workflow">

      <div class="cryostack-workflow-card">
        <div class="cryostack-workflow-number">01</div>
        <div class="cryostack-workflow-icon">OBS</div>
        <h3>Observations</h3>
        <p>
          Begin with radar products, borehole measurements,
          satellite observations, or other scientific datasets.
        </p>
      </div>

      <div class="cryostack-workflow-arrow" aria-hidden="true">
        →
      </div>

      <div class="cryostack-workflow-card">
        <div class="cryostack-workflow-number">02</div>
        <div class="cryostack-workflow-icon">LIV</div>
        <h3>Explore Data</h3>
        <p>
          Use LIVIST and future data applications to inspect,
          compare, and access cryosphere data products.
        </p>
      </div>

      <div class="cryostack-workflow-arrow" aria-hidden="true">
        →
      </div>

      <div class="cryostack-workflow-card">
        <div class="cryostack-workflow-number">03</div>
        <div class="cryostack-workflow-icon">SIM</div>
        <h3>Run Models</h3>
        <p>
          Configure and launch community ice-sheet models
          through CryoLauncher on local, HPC, or cloud resources.
        </p>
      </div>

      <div class="cryostack-workflow-arrow" aria-hidden="true">
        →
      </div>

      <div class="cryostack-workflow-card">
        <div class="cryostack-workflow-number">04</div>
        <div class="cryostack-workflow-icon">DA</div>
        <h3>Assimilate</h3>
        <p>
          Combine simulations and observations through ICESEE
          for state estimation and parameter inference.
        </p>
      </div>

      <div class="cryostack-workflow-arrow" aria-hidden="true">
        →
      </div>

      <div class="cryostack-workflow-card">
        <div class="cryostack-workflow-number">05</div>
        <div class="cryostack-workflow-icon">OUT</div>
        <h3>Analyze Results</h3>
        <p>
          Inspect outputs, download results, and continue
          analysis using reproducible scientific workflows.
        </p>
      </div>

    </div>

  </section>

  <section class="cryostack-section cryostack-value-section">

      <div class="cryostack-section-label">
        Platform Capabilities
      </div>

      <h2>Why CryoStack?</h2>

      <p class="cryostack-section-intro">
        CryoStack reduces the technical barriers associated with scientific
        software deployment, remote computing, and application integration,
        allowing users to focus on cryosphere research.
      </p>

      <div class="cryostack-value-grid">

        <div class="cryostack-value-card">
          <div class="cryostack-value-icon">WEB</div>

          <h3>Browser First</h3>

          <p>
            Access modeling, data assimilation, and visualization tools directly
            from a modern web browser without managing complex local installations.
          </p>
        </div>

        <div class="cryostack-value-card">
          <div class="cryostack-value-icon">HPC</div>

          <h3>HPC Ready</h3>

          <p>
            Connect applications to workstations, remote servers, Slurm clusters,
            and cloud computing resources while keeping the interface consistent.
          </p>
        </div>

        <div class="cryostack-value-card">
          <div class="cryostack-value-icon">MOD</div>

          <h3>Modular by Design</h3>

          <p>
            Integrate new cryosphere applications and scientific workflows without
            redesigning the entire platform.
          </p>
        </div>

        <div class="cryostack-value-card">
          <div class="cryostack-value-icon">OPEN</div>

          <h3>Built for Open Science</h3>

          <p>
            Support reproducible research through community models, open-source
            software, shared datasets, containers, and documented workflows.
          </p>
        </div>

      </div>

      <section class="cryostack-section cryostack-updates-section">

    <div class="cryostack-section-label">
      Platform Updates
    </div>

    <h2>Latest developments.</h2>

    <p class="cryostack-section-intro">
      CryoStack continues to evolve as new applications, execution backends,
      documentation, and scientific workflows are integrated into the platform.
    </p>

    <div class="cryostack-updates-grid">

      <article class="cryostack-update-card">
        <div class="cryostack-update-status">New Application</div>

        <h3>LIVIST integrated into CryoStack</h3>

        <p>
          The Living Ice Sheet Temperature explorer is now hosted directly
          within CryoStack, together with its user manual, Python documentation,
          and data repository.
        </p>

        <a href="/livist/">
          Open LIVIST →
        </a>
      </article>

      <article class="cryostack-update-card">
        <div class="cryostack-update-status">Interface</div>

        <h3>Unified application navigation</h3>

        <p>
          CryoLauncher, ICESEE, and LIVIST now follow a consistent application
          navigation pattern for accessing their interfaces, manuals, and
          supporting resources.
        </p>

        <a href="documentation.html">
          View documentation →
        </a>
      </article>

      <article class="cryostack-update-card">
        <div class="cryostack-update-status">Infrastructure</div>

        <h3>Georgia Tech deployment</h3>

        <p>
          CryoStack is now operating from the Georgia Tech virtual machine with
          support for remote execution, WebSocket applications, and connection
          to HPC resources.
        </p>

        <a href="resources.html">
          Explore resources →
        </a>
      </article>

    </div>
  </section>

  <footer class="cryostack-footer">

    <div class="cryostack-footer-main">

      <div class="cryostack-footer-brand">
        <div class="cryostack-footer-logo">CryoStack</div>

        <p>
          An integrated platform for cryosphere modeling, data assimilation,
          scientific visualization, and HPC-enabled research.
        </p>
      </div>

      <div class="cryostack-footer-group">
        <h3>Platform</h3>

        <a href="index.html">Home</a>
        <a href="documentation.html">Documentation</a>
        <a href="resources.html">Resources</a>
        <a href="about.html">About</a>
      </div>

      <div class="cryostack-footer-group">
        <h3>Applications</h3>

        <a href="/icesheets/">CryoLauncher</a>
        <a href="/icesee-gui/">ICESEE</a>
        <a href="/livist/">LIVIST</a>
      </div>

      <div class="cryostack-footer-group">
        <h3>Community</h3>

        <a
          href="https://github.com/ICESEE-project/CryoLauncher"
          target="_blank"
          rel="noopener noreferrer">
          GitHub
        </a>

        <a
          href="https://github.com/ICESEE-project"
          target="_blank"
          rel="noopener noreferrer">
          ICESEE Project
        </a>

        <a
          href="https://github.com/ICESEE-project/CryoLauncher/issues"
          target="_blank"
          rel="noopener noreferrer">
          Report an Issue
        </a>
      </div>

    </div>

    <div class="cryostack-footer-bottom">

      <div>
        Developed by ICCL and PGSL at the Georgia Institute of Technology.
      </div>

      <div class="cryostack-footer-meta">
        <span>© 2026 CryoStack</span>
        <span>BSD 2-Clause License</span>
      </div>

    </div>

  </footer>

</div>
:::