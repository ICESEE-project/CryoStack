# Run Scientific Workflows

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>

<div class="cryostack-docs-page">
  <section class="cryostack-docs-hero">
    <div class="cryostack-section-label">CryoStack Documentation</div>
    <h1>Run Scientific Workflows</h1>
    <p>
      CryoLauncher and ICESEE are CryoStack's workflow-execution
      applications. CryoLauncher runs standalone ISSM and Icepack
      simulations on Remote HPC or AWS. ICESEE runs ensemble data assimilation
      through its separate Local, Remote and Cloud implementations; its manual
      lists the model and process restrictions for each.
    </p>
    <div class="cryostack-docs-actions">
      <a class="cryostack-btn secondary" href="user_manual.html">
        &larr; User Manual
      </a>
    </div>
  </section>

  <section id="choose-an-application" class="cryostack-section">
    <div class="cryostack-section-label">Choose an application</div>
    <h2>Simulation or data assimilation.</h2>

    <div class="cryostack-docs-summary-grid">
      <div class="cryostack-docs-summary-card">
        <h3>CryoLauncher</h3>
        <p>Configure ISSM or Icepack simulations. Basic,
           Advanced, and Auto-config are configuration experiences; Remote
           and Cloud are execution backends.</p>
        <div class="cryostack-docs-actions">
          <a class="cryostack-btn secondary" href="../applications/icesheets/getting_started.html">Getting Started</a>
          <a class="cryostack-btn secondary" href="../applications/icesheets/user_manual.html">User Manual</a>
        </div>
      </div>

      <div class="cryostack-docs-summary-card">
        <h3>ICESEE</h3>
        <p>Configure and run ensemble data-assimilation workflows for state
           estimation and parameter inference. ICESEE offers its own Local,
           Remote, Cloud, and Auto-config organization.</p>
        <div class="cryostack-docs-actions">
          <a class="cryostack-btn secondary" href="../applications/icesee/getting_started.html">Getting Started</a>
          <a class="cryostack-btn secondary" href="../applications/icesee/user_manual.html">User Manual</a>
        </div>
      </div>
    </div>
  </section>
</div>
:::

## Shared platform shape

1. Choose an application, model, example, and scientific configuration.
2. Choose an execution environment that the selected workflow supports.
3. Verify credentials, connectivity, software, and requested resources.
4. Review and submit the run.
5. Monitor status and logs from that application's interface.
6. Retrieve, inspect, visualize, and download the resulting output.

This sequence is a platform concept, not a field-by-field procedure. Detailed
screens, validation rules, model options, and recovery steps stay in the
CryoLauncher and ICESEE manuals. Continue with the shared environment guides
only when you need to understand the boundary between backends:

- [Running Locally](user_local.md) — currently an ICESEE capability.
- [Running Remotely](user_remote.md) — institutional servers and HPC through
  direct SSH or the CryoStack Connector.
- [Running in the Cloud](hpc_cloud.md) — BYO AWS onboarding and the named
  CryoLauncher/ICESEE cases, with their resource and licensing restrictions.
- [Resource allocations](resource_allocations.md) — CryoStack planning
  allowances and their boundary from actual provider billing.

For data exploration rather than computational execution, use
[Explore Scientific Data](user_data.md).
