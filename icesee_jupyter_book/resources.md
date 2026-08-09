# Resources

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>
:::

:::{raw} html
<div class="cryostack-resources-page">

  <section class="cryostack-resources-hero">

    <div class="cryostack-section-label">
      CryoStack Resources
    </div>

    <h1>Documentation, software, data, and community resources.</h1>

    <p>
      Use this page to access CryoStack repositories, application guides,
      scientific software, datasets, publications, and support channels.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary" href="documentation.html">
        Platform Documentation
      </a>

      <a
        class="cryostack-btn secondary"
        href="https://github.com/ICESEE-project"
        target="_blank"
        rel="noopener noreferrer">
        View GitHub Organization
      </a>
    </div>

  </section>

  <section class="cryostack-section">

    <div class="cryostack-section-label">
      Platform
    </div>

    <h2>CryoStack resources.</h2>

    <p class="cryostack-section-intro">
      Core resources for understanding, deploying, contributing to,
      and reporting issues with the CryoStack platform.
    </p>

    <div class="cryostack-resource-grid">

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Documentation</div>
        <h3>Platform Documentation</h3>
        <p>
          Learn how CryoStack applications, computational backends,
          and scientific workflows fit together.
        </p>
        <a href="documentation.html">Open Documentation →</a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Source Code</div>
        <h3>CryoLauncher Repository</h3>
        <p>
          Access the main CryoStack gateway, application interfaces,
          deployment scripts, and platform integration code.
        </p>
        <a
          href="https://github.com/ICESEE-project/CryoLauncher"
          target="_blank"
          rel="noopener noreferrer">
          View Repository →
        </a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Support</div>
        <h3>Issue Tracker</h3>
        <p>
          Report platform bugs, deployment problems, documentation issues,
          or feature requests.
        </p>
        <a
          href="https://github.com/ICESEE-project/CryoLauncher/issues"
          target="_blank"
          rel="noopener noreferrer">
          Report an Issue →
        </a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Development</div>
        <h3>ICESEE Project Organization</h3>
        <p>
          Browse the repositories that support CryoStack, ICESEE,
          containers, Spack environments, and related scientific tools.
        </p>
        <a
          href="https://github.com/ICESEE-project"
          target="_blank"
          rel="noopener noreferrer">
          Explore Projects →
        </a>
      </article>

    </div>

  </section>

  <section class="cryostack-section">

    <div class="cryostack-section-label">
      Applications
    </div>

    <h2>Application resources.</h2>

    <div class="cryostack-resource-directory">

      <div class="cryostack-resource-directory-row">
        <div>
          <span>Numerical Modeling</span>
          <h3>CryoLauncher</h3>
          <p>
            Browser-based access to supported ice-sheet models,
            remote execution, HPC submission, and workflow monitoring.
          </p>
        </div>

        <div class="cryostack-resource-links">
          <a href="/icesheets/">Open Application</a>
          <a href="applications/icesheets/getting_started.html">Getting Started</a>
          <a href="/icesheets/">User Manual</a>
          <a href="/icesheets/">Resources</a>
        </div>
      </div>

      <div class="cryostack-resource-directory-row">
        <div>
          <span>Data Assimilation</span>
          <h3>ICESEE</h3>
          <p>
            Ensemble-based state estimation, parameter inference,
            and data assimilation with supported numerical models.
          </p>
        </div>

        <div class="cryostack-resource-links">
          <a href="/icesee-gui/">Open Application</a>
          <a href="/icesee-gui/">Getting Started</a>
          <a href="/icesee-gui/">User Manual</a>
          <a href="/icesee-gui/">Resources</a>
        </div>
      </div>

      <div class="cryostack-resource-directory-row">
        <div>
          <span>Scientific Data Products</span>
          <h3>LIVIST</h3>
          <p>
            Antarctic ice-sheet temperature visualization,
            borehole constraints, Python tools, and published datasets.
          </p>
        </div>

        <div class="cryostack-resource-links">
          <a href="/livist/">Open Application</a>
          <a href="/livist/docs/livist_user_manual/">User Manual</a>
          <a href="/livist/docs/api/">Python Documentation</a>
          <a
            href="https://source.coop/englacial/ice-sheet-temperature"
            target="_blank"
            rel="noopener noreferrer">
            Data Repository
          </a>
        </div>
      </div>

    </div>

  </section>

  <section class="cryostack-section">

    <div class="cryostack-section-label">
      Community Software
    </div>

    <h2>Scientific software used by CryoStack.</h2>

    <div class="cryostack-resource-grid">

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Ice-Sheet Model</div>
        <h3>ISSM</h3>
        <p>
          A multiphysics framework for ice-sheet and sea-level simulations.
        </p>
        <a
          href="https://issm.jpl.nasa.gov/"
          target="_blank"
          rel="noopener noreferrer">
          Visit ISSM →
        </a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Ice-Sheet Model</div>
        <h3>Icepack</h3>
        <p>
          A Python library for modeling glacier and ice-sheet flow
          using Firedrake.
        </p>
        <a
          href="https://icepack.github.io/"
          target="_blank"
          rel="noopener noreferrer">
          Visit Icepack →
        </a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Finite Elements</div>
        <h3>Firedrake</h3>
        <p>
          An automated system for solving partial differential equations
          using finite-element methods.
        </p>
        <a
          href="https://www.firedrakeproject.org/"
          target="_blank"
          rel="noopener noreferrer">
          Visit Firedrake →
        </a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Scientific Computing</div>
        <h3>PETSc</h3>
        <p>
          Scalable numerical libraries for scientific applications
          and high-performance computing.
        </p>
        <a
          href="https://petsc.org/"
          target="_blank"
          rel="noopener noreferrer">
          Visit PETSc →
        </a>
      </article>

    </div>

  </section>

  <section class="cryostack-section">

    <div class="cryostack-section-label">
      Deployment and Environments
    </div>

    <h2>Build and run reproducibly.</h2>

    <div class="cryostack-resource-grid">

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Containers</div>
        <h3>ICESEE Containers</h3>
        <p>
          Reproducible container environments for CryoStack applications
          and supported scientific software.
        </p>
        <a
          href="https://github.com/ICESEE-project/ICESEE-Containers"
          target="_blank"
          rel="noopener noreferrer">
          View Repository →
        </a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Package Management</div>
        <h3>ICESEE Spack</h3>
        <p>
          Spack-based environments for installing supported models,
          dependencies, and scientific computing tools.
        </p>
        <a
          href="https://github.com/ICESEE-project/ICESEE-Spack"
          target="_blank"
          rel="noopener noreferrer">
          View Repository →
        </a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">HPC</div>
        <h3>Remote and Slurm Execution</h3>
        <p>
          Use CryoStack with Linux servers and Slurm-managed HPC systems.
        </p>
        <a href="documentation.html">
          Read Platform Documentation →
        </a>
      </article>

      <article class="cryostack-resource-card">
        <div class="cryostack-resource-tag">Cloud</div>
        <h3>Cloud Execution</h3>
        <p>
          Connect supported workflows to cloud infrastructure
          and user-provided computing resources.
        </p>
        <a href="documentation.html">
          Learn More →
        </a>
      </article>

    </div>

  </section>

  <section class="cryostack-section cryostack-resources-support">

    <div class="cryostack-section-label">
      Support
    </div>

    <h2>Need help?</h2>

    <p>
      Use the GitHub issue tracker for platform bugs, documentation problems,
      deployment questions, or feature requests. Scientific questions related
      to an individual application should be directed through that application’s
      documentation and support channels.
    </p>

    <div class="cryostack-docs-actions">
      <a
        class="cryostack-btn primary"
        href="https://github.com/ICESEE-project/CryoLauncher/issues"
        target="_blank"
        rel="noopener noreferrer">
        Open Issue Tracker
      </a>

      <a class="cryostack-btn secondary" href="about.html">
        About CryoStack
      </a>
    </div>

  </section>

</div>
:::