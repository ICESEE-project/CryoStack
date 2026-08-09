# About

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>
:::

:::{raw} html
<div class="cryostack-about-page">

  <section class="cryostack-about-hero">

    <div class="cryostack-section-label">
      About CryoStack
    </div>

    <h1>A shared platform for accessible cryosphere computing.</h1>

    <p>
      CryoStack connects scientific applications, community models,
      observational products, and high-performance computing resources
      through a unified browser-based environment.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary" href="documentation.html">
        Read the Documentation
      </a>

      <a
        class="cryostack-btn secondary"
        href="https://github.com/ICESEE-project/CryoLauncher"
        target="_blank"
        rel="noopener noreferrer">
        View Source Code
      </a>
    </div>

  </section>

  <section class="cryostack-section">

    <div class="cryostack-section-label">
      Our Mission
    </div>

    <h2>Lowering barriers to cryosphere research.</h2>

    <p class="cryostack-section-intro">
      Contemporary cryosphere models and scientific workflows often require
      specialized software, complex dependencies, high-performance computing
      systems, and model-specific expertise. These technical requirements can
      make it difficult for students, researchers, educators, and collaborators
      to access and reuse existing scientific tools.
    </p>

    <div class="cryostack-about-mission">

      <div>
        <h3>Accessible</h3>
        <p>
          Provide browser-based access to scientific applications without
          requiring users to install and maintain complete software stacks
          locally.
        </p>
      </div>

      <div>
        <h3>Connected</h3>
        <p>
          Link numerical models, observational products, data assimilation,
          remote computing, and scientific analysis within one platform.
        </p>
      </div>

      <div>
        <h3>Reproducible</h3>
        <p>
          Support documented workflows, containers, managed software
          environments, and reusable scientific configurations.
        </p>
      </div>

      <div>
        <h3>Extensible</h3>
        <p>
          Allow new cryosphere applications to be integrated without
          redesigning the complete platform.
        </p>
      </div>

    </div>

  </section>

  <section class="cryostack-section">

    <div class="cryostack-section-label">
      Platform Scope
    </div>

    <h2>One platform, several scientific workflows.</h2>

    <p class="cryostack-section-intro">
      CryoStack is designed as an umbrella platform rather than a single
      application. Each integrated application provides a focused scientific
      capability while sharing common navigation, documentation, deployment,
      and execution infrastructure.
    </p>

    <div class="cryostack-about-app-grid">

      <article class="cryostack-about-app-card">
        <div class="cryostack-card-tag">
          Numerical Modeling
        </div>

        <h3>CryoLauncher</h3>

        <p>
          Provides browser-based access to supported ice-sheet models,
          including remote execution and HPC job submission.
        </p>

        <a href="/icesheets/">
          Open CryoLauncher →
        </a>
      </article>

      <article class="cryostack-about-app-card">
        <div class="cryostack-card-tag green">
          Data Assimilation
        </div>

        <h3>ICESEE</h3>

        <p>
          Supports ensemble-based state estimation and parameter inference
          using numerical models and observational data.
        </p>

        <a href="/icesee-gui/">
          Open ICESEE →
        </a>
      </article>

      <article class="cryostack-about-app-card">
        <div class="cryostack-card-tag green">
          Scientific Data
        </div>

        <h3>LIVIST</h3>

        <p>
          Provides interactive access to Antarctic englacial temperature
          products inferred from radar observations and borehole constraints.
        </p>

        <a href="/livist/">
          Open LIVIST →
        </a>
      </article>

      <article class="cryostack-about-app-card muted">
        <div class="cryostack-card-tag gray">
          Platform Expansion
        </div>

        <h3>Future Applications</h3>

        <p>
          Additional cryosphere modeling, data, visualization, and analysis
          tools will be integrated as the platform develops.
        </p>

        <a href="resources.html">
          View Resources →
        </a>
      </article>

    </div>

  </section>

  <section class="cryostack-section">

    <div class="cryostack-section-label">
      Design Principles
    </div>

    <h2>How CryoStack is built.</h2>

    <div class="cryostack-about-principles">

      <div class="cryostack-about-principle">
        <span>01</span>
        <h3>Browser-first access</h3>
        <p>
          Users interact with scientific applications through a consistent
          web interface while computational work runs on suitable backends.
        </p>
      </div>

      <div class="cryostack-about-principle">
        <span>02</span>
        <h3>Separation of concerns</h3>
        <p>
          The web gateway, scientific application, execution backend, and
          data sources remain separate so each can evolve independently.
        </p>
      </div>

      <div class="cryostack-about-principle">
        <span>03</span>
        <h3>Backend flexibility</h3>
        <p>
          Workflows may run locally, on remote Linux systems, on Slurm-managed
          clusters, or through configured cloud resources.
        </p>
      </div>

      <div class="cryostack-about-principle">
        <span>04</span>
        <h3>Open integration</h3>
        <p>
          CryoStack builds on open-source scientific software, community
          models, documented interfaces, and reusable environments.
        </p>
      </div>

    </div>

  </section>

  <section class="cryostack-section">

    <div class="cryostack-section-label">
      Technology
    </div>

    <h2>Built on scientific and web technologies.</h2>

    <p class="cryostack-section-intro">
      CryoStack combines browser interfaces, Python applications, scientific
      software environments, and remote execution services.
    </p>

    <div class="cryostack-about-tech-grid">

      <div>
        <h3>Web and Interface</h3>
        <p>
          Jupyter Book, Voilà, ipywidgets, React, TypeScript, Vite, and Nginx.
        </p>
      </div>

      <div>
        <h3>Scientific Computing</h3>
        <p>
          Python, MPI, PETSc, Firedrake, ISSM, Icepack, and ensemble data
          assimilation methods.
        </p>
      </div>

      <div>
        <h3>Deployment</h3>
        <p>
          Linux virtual machines, containers, Spack environments, Slurm,
          cloud infrastructure, and secure remote connections.
        </p>
      </div>

      <div>
        <h3>Scientific Data</h3>
        <p>
          Radar products, borehole observations, model outputs, geospatial
          data, and published community datasets.
        </p>
      </div>

    </div>

  </section>

  <section class="cryostack-section">

    <div class="cryostack-section-label">
      Development
    </div>

    <h2>Developed as an open scientific platform.</h2>

    <p class="cryostack-section-intro">
      CryoStack is developed through collaboration between researchers,
      software developers, scientific application contributors, and
      institutional computing teams.
    </p>

    <div class="cryostack-about-development">

      <div class="cryostack-about-development-main">
        <h3>Georgia Institute of Technology</h3>

        <p>
          CryoStack is developed within the Georgia Tech cryosphere research
          and scientific computing community, including contributions from
          ICCL and PGSL.
        </p>

        <p>
          The platform is intended to support research, education,
          collaboration, reproducible workflows, and access to institutional
          and external computing resources.
        </p>
      </div>

      <div class="cryostack-about-development-links">
        <a
          href="https://github.com/ICESEE-project"
          target="_blank"
          rel="noopener noreferrer">
          ICESEE Project Organization
        </a>

        <a
          href="https://github.com/ICESEE-project/CryoLauncher"
          target="_blank"
          rel="noopener noreferrer">
          CryoLauncher Repository
        </a>

        <a
          href="https://github.com/ICESEE-project/CryoLauncher/issues"
          target="_blank"
          rel="noopener noreferrer">
          Issue Tracker
        </a>
      </div>

    </div>

  </section>

  <section class="cryostack-section">

    <div class="cryostack-section-label">
      Open Science
    </div>

    <h2>Community software and reproducible workflows.</h2>

    <p class="cryostack-section-intro">
      CryoStack integrates open-source software and community scientific
      models while preserving the identity, documentation, and licensing
      of each project.
    </p>

    <div class="cryostack-about-open-grid">

      <div>
        <h3>Community models</h3>
        <p>
          CryoStack supports established scientific models and libraries
          rather than replacing them.
        </p>
      </div>

      <div>
        <h3>Reusable environments</h3>
        <p>
          Containers and Spack-based environments improve portability and
          reproducibility across computing systems.
        </p>
      </div>

      <div>
        <h3>Published data</h3>
        <p>
          Scientific data applications connect users to documented,
          externally hosted, and reusable data products.
        </p>
      </div>

      <div>
        <h3>Transparent development</h3>
        <p>
          Source code, issues, documentation, and platform updates are
          maintained through public project repositories.
        </p>
      </div>

    </div>

  </section>

  <section class="cryostack-section">

    <div class="cryostack-section-label">
      Citation
    </div>

    <h2>Citing CryoStack and its applications.</h2>

    <p class="cryostack-section-intro">
      Users should cite CryoStack together with the individual applications,
      scientific models, datasets, and publications used in their work.
    </p>

    <div class="cryostack-about-citation">

      <div>
        <h3>CryoStack</h3>
        <p>
          Kyanjo, B. and contributors. CryoStack: A platform for interactive
          cryosphere modeling, data products, data assimilation, and
          HPC-enabled scientific workflows. Georgia Institute of Technology,
          2026.
        </p>
      </div>

      <div>
        <h3>Application citations</h3>
        <p>
          Application-specific citations should be obtained from the
          corresponding user manual, repository, publication, or dataset
          record.
        </p>
      </div>

    </div>

    <p class="cryostack-about-citation-note">
      Formal release citations and DOI records will be added as CryoStack
      applications are archived and released.
    </p>

  </section>

  <section class="cryostack-section">

    <div class="cryostack-section-label">
      License
    </div>

    <h2>Open-source licensing.</h2>

    <p class="cryostack-section-intro">
      CryoStack is distributed under the BSD 2-Clause License. Integrated
      applications and external scientific packages may use different
      licenses. Users should consult the corresponding project repository
      before redistributing or modifying those components.
    </p>

  </section>

  <section class="cryostack-section cryostack-about-contact">

    <div class="cryostack-section-label">
      Contact and Support
    </div>

    <h2>Connect with the project.</h2>

    <p>
      For platform bugs, documentation problems, deployment questions,
      integration requests, or feature proposals, use the CryoLauncher
      GitHub issue tracker.
    </p>

    <div class="cryostack-docs-actions">
      <a
        class="cryostack-btn primary"
        href="https://github.com/ICESEE-project/CryoLauncher/issues"
        target="_blank"
        rel="noopener noreferrer">
        Open Issue Tracker
      </a>

      <a class="cryostack-btn secondary" href="resources.html">
        View Resources
      </a>
    </div>

  </section>

</div>
:::