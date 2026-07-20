# Documentation

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

    <div class="cryostack-section-label">
      CryoStack Documentation
    </div>

    <h1>Build, run, and explore cryosphere workflows.</h1>

    <p>
      CryoStack brings together numerical modeling, data assimilation,
      scientific data products, and remote computing through one integrated
      browser-based platform.
    </p>

    <div class="cryostack-docs-actions">
    <a class="cryostack-btn primary" href="#applications">
        Browse Application Guides
    </a>

    <a class="cryostack-btn secondary" href="resources.html">
        View Resources
    </a>
    </div>

  </section>

  <section class="cryostack-section">

    <div class="cryostack-section-label">
      Platform Overview
    </div>

    <h2>What is CryoStack?</h2>

    <p class="cryostack-section-intro">
      CryoStack is a modular scientific computing platform designed to lower
      the technical barriers associated with cryosphere modeling, data
      assimilation, visualization, software deployment, and high-performance
      computing.
    </p>

    <div class="cryostack-docs-summary-grid">

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">SIM</div>
        <h3>Modeling</h3>
        <p>
          Configure and launch supported ice-sheet models through
          browser-based applications.
        </p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">DA</div>
        <h3>Data Assimilation</h3>
        <p>
          Combine simulations and observations for state estimation
          and parameter inference.
        </p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">DATA</div>
        <h3>Scientific Data</h3>
        <p>
          Explore and access observational products through interactive
          web applications.
        </p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">HPC</div>
        <h3>Remote Computing</h3>
        <p>
          Connect CryoStack applications to local, HPC, and cloud
          computing resources.
        </p>
      </div>

    </div>

  </section>

  <section id="applications" class="cryostack-section">

    <div class="cryostack-section-label">
      Application Documentation
    </div>

    <h2>Choose an application.</h2>

    <p class="cryostack-section-intro">
      Each CryoStack application maintains its own documentation,
      user guidance, and supporting resources.
    </p>

    <div class="cryostack-docs-app-grid">

      <article class="cryostack-docs-app-card">

        <div class="cryostack-card-eyebrow">
          Numerical Modeling
        </div>

        <div class="cryostack-card-tag">
          Simulation
        </div>

        <h3>CryoLauncher</h3>

        <p>
          Run supported ice-sheet models through a browser interface
          and connect simulations to local, remote, HPC, or cloud resources.
        </p>

        <div class="cryostack-mini-list">
          <span>ISSM</span>
          <span>Icepack</span>
          <span>Containers</span>
          <span>Slurm</span>
        </div>

        <div class="cryostack-docs-card-actions">
            <a href="/icesheets/">Open Application</a>
            <a href="applications/icesheets/getting_started.html">Getting Started</a>
            <a href="applications/icesheets/user_manual.html">User Manual</a>
            <a href="applications/icesheets/resources.html">Resources</a>
        </div>

      </article>

      <article class="cryostack-docs-app-card">

        <div class="cryostack-card-eyebrow">
          State and Parameter Estimation
        </div>

        <div class="cryostack-card-tag green">
          Data Assimilation
        </div>

        <h3>ICESEE</h3>

        <p>
          Run ensemble data assimilation workflows with supported
          numerical models for state estimation and parameter inference.
        </p>

        <div class="cryostack-mini-list green-list">
          <span>EnKF</span>
          <span>DEnKF</span>
          <span>EnTKF</span>
          <span>EnRSKF</span>
        </div>

        <div class="cryostack-docs-card-actions">
          <a href="/icesee-gui/">Open Application</a>
          <a href="applications/icesee/getting_started.html">Getting Started</a>
          <a href="applications/icesee/user_manual.html">User Manual</a>
          <a href="applications/icesee/resources.html">Resources</a>
        </div>

      </article>

      <article class="cryostack-docs-app-card">

        <div class="cryostack-card-eyebrow">
          Scientific Data Products
        </div>

        <div class="cryostack-card-tag green">
          Interactive Explorer
        </div>

        <h3>LIVIST</h3>

        <p>
          Explore Antarctic ice-sheet temperature products inferred from
          radar observations and constrained by borehole measurements.
        </p>

        <div class="cryostack-mini-list green-list">
          <span>Radar</span>
          <span>Boreholes</span>
          <span>Temperature</span>
          <span>Antarctica</span>
        </div>

        <div class="cryostack-docs-card-actions">
          <a href="/livist/">
            Open Application
          </a>

          <a href="/livist/docs/livist_user_manual/">
            User Manual
          </a>

          <a href="/livist/docs/api/">
            Python Documentation
          </a>

          <a
            href="https://source.coop/englacial/ice-sheet-temperature"
            target="_blank"
            rel="noopener noreferrer">
            Data Repository
          </a>
        </div>

      </article>

      <article class="cryostack-docs-app-card muted">

        <div class="cryostack-card-eyebrow">
          Platform Expansion
        </div>

        <div class="cryostack-card-tag gray">
          Coming Soon
        </div>

        <h3>Future Applications</h3>

        <p>
          Additional cryosphere modeling, visualization, and analysis
          tools will be integrated as the platform expands.
        </p>

        <div class="cryostack-docs-card-actions">
          <a href="resources.html">
            View Roadmap
          </a>
        </div>

      </article>

    </div>

  </section>

  <section class="cryostack-section">

    <div class="cryostack-section-label">
      Platform Architecture
    </div>

    <h2>How the pieces connect.</h2>

    <p class="cryostack-section-intro">
      CryoStack separates the web interface, application layer,
      computational backends, and scientific data sources so that each
      component can evolve independently.
    </p>

    <div class="cryostack-docs-architecture">

      <div class="cryostack-architecture-node">
        <span>01</span>
        <h3>Browser</h3>
        <p>
          Users access CryoStack through a modern web browser.
        </p>
      </div>

      <div class="cryostack-architecture-arrow">→</div>

      <div class="cryostack-architecture-node">
        <span>02</span>
        <h3>Platform Gateway</h3>
        <p>
          CryoStack provides shared navigation, routing, and application access.
        </p>
      </div>

      <div class="cryostack-architecture-arrow">→</div>

      <div class="cryostack-architecture-node">
        <span>03</span>
        <h3>Applications</h3>
        <p>
          CryoLauncher, ICESEE, LIVIST, and future tools provide scientific capabilities.
        </p>
      </div>

      <div class="cryostack-architecture-arrow">→</div>

      <div class="cryostack-architecture-node">
        <span>04</span>
        <h3>Backends</h3>
        <p>
          Applications connect to local systems, clusters, clouds, and scientific datasets.
        </p>
      </div>

    </div>

  </section>

  <section class="cryostack-section">

    <div class="cryostack-section-label">
      Computing Environments
    </div>

    <h2>Run where your science needs to run.</h2>

    <div class="cryostack-docs-environments">

      <div>
        <h3>Local Workstations</h3>
        <p>
          Use CryoStack for development, testing, and smaller scientific workflows.
        </p>
      </div>

      <div>
        <h3>Remote Servers</h3>
        <p>
          Connect to Linux systems through secure remote-execution workflows.
        </p>
      </div>

      <div>
        <h3>HPC Clusters</h3>
        <p>
          Submit and monitor jobs on Slurm-managed systems such as Georgia Tech PACE.
        </p>
      </div>

      <div>
        <h3>Cloud Resources</h3>
        <p>
          Execute applications using cloud infrastructure and user-provided compute resources.
        </p>
      </div>

    </div>

  </section>

  <section class="cryostack-section cryostack-docs-next">

    <div class="cryostack-section-label">
      Next Steps
    </div>

    <h2>Start with an application.</h2>

    <p>
      Open CryoLauncher for numerical modeling, ICESEE for data assimilation,
      or LIVIST for Antarctic temperature exploration.
    </p>

    <div class="cryostack-docs-actions">
    <a class="cryostack-btn primary" href="#applications">
        Browse Application Guides
    </a>

    <a class="cryostack-btn secondary" href="resources.html">
        View Resources
    </a>
    </div>

  </section>

</div>
:::
