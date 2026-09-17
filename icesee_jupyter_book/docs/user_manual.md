# User Manual

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
    <h1>User Manual</h1>
    <p>
      The operational reference for running a CryoStack application: choose
      an application and workflow, configure it, choose an available
      execution environment, submit and monitor the run, then retrieve and
      visualize results.
    </p>
    <div class="cryostack-docs-actions">
      <a class="cryostack-btn secondary" href="../documentation.html">
        &larr; Documentation
      </a>
    </div>
  </section>

  <section id="navigation" class="cryostack-section">
    <div class="cryostack-section-label">On this page</div>
    <h2>Where to go next.</h2>
    <p class="cryostack-section-intro">
      Each card below is scientist-facing: how to use a capability. The
      matching implementation detail — how it is built and extended — lives
      in the <a href="developer_guide.html">Developer Guide</a>, cross-linked
      from each page rather than duplicated here.
    </p>

    <div class="cryostack-docs-summary-grid">

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">AW</div>
        <h3><a href="user_apps.html">Applications &amp; Workflows</a></h3>
        <p>What each CryoStack application does, and how their interfaces
           genuinely differ — CryoLauncher's Basic/Advanced/Auto-config,
           ICESEE's Local/Remote/Cloud, and Frozen Legacies/LIVIST's own
           shape.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">RL</div>
        <h3><a href="user_local.html">Running Locally</a></h3>
        <p>Where Local execution exists today, and why it is not offered
           for every application or workflow.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">RR</div>
        <h3><a href="user_remote.html">Running Remotely</a></h3>
        <p>Bringing your own institutional cluster or workstation: direct
           SSH or the CryoStack Connector, submission, monitoring, and
           retrieval.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">RC</div>
        <h3><a href="hpc_cloud.html">Running in the Cloud</a></h3>
        <p>AWS Batch on Fargate or EC2: configuration, submission,
           workflow-dependent institutional connectivity, and current
           scope.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">RV</div>
        <h3><a href="user_results.html">Results &amp; Visualization</a></h3>
        <p>The shared result lifecycle: retrieval, the neutral result
           package, plotting, and downloads.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">TS</div>
        <h3><a href="user_troubleshooting.html">Troubleshooting</a></h3>
        <p>Common setup, connectivity, and run problems, and where to look
           next when something fails.</p>
      </div>

    </div>
  </section>

  <section id="workflow" class="cryostack-section">
    <div class="cryostack-section-label">The normal workflow</div>
    <h2>Configure, execute, monitor, visualize.</h2>
    <p class="cryostack-section-intro">
      Every CryoStack application follows the same shape, even though the
      controls differ per application:
    </p>
    <ol>
      <li>Choose an application and a workflow/example.</li>
      <li>Configure it (Basic/Advanced/Auto-config for CryoLauncher; the
          equivalent controls for other applications).</li>
      <li>Choose an available execution environment for that workflow —
          Local where supported, Remote, or Cloud.</li>
      <li>Submit and monitor status, logs, and progress.</li>
      <li>Retrieve, visualize, and download results.</li>
    </ol>
    <p>
      Not every step applies to every application — see
      <a href="user_apps.html">Applications &amp; Workflows</a> for what is
      actually available where.
    </p>
  </section>

</div>
:::
