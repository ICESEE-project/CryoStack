# Developer Guide

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

    <h1>Developer Guide</h1>

    <p>
      Build, extend, test, and integrate applications with the
      CryoStack scientific-computing platform.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary"
         href="https://github.com/ICESEE-project/CryoStack"
         target="_blank" rel="noopener noreferrer">
        CryoStack Repository
      </a>

      <a class="cryostack-btn secondary" href="../documentation.html">
        Platform Documentation
      </a>
    </div>

  </section>

  <section id="navigation" class="cryostack-section">

    <div class="cryostack-section-label">
      On this page
    </div>

    <h2>Where to go next.</h2>

    <p class="cryostack-section-intro">
      Cards navigate to the sections below. Detailed material stays as
      readable documentation, not cards.
    </p>

    <div class="cryostack-docs-summary-grid">

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">AR</div>
        <h3><a href="dev_architecture.html">Architecture</a></h3>
        <p>How the web shell, gateways, application layer, and execution
           backends fit together.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">FA</div>
        <h3><a href="dev_frontend.html">Frontend &amp; Applications</a></h3>
        <p>Local environment, running a gateway, Basic/Advanced modes, and
           the shared application-shell components.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">EX</div>
        <h3><a href="dev_execution.html">Execution Backends</a></h3>
        <p>Local/Remote/Cloud, AWS Batch (Fargate/EC2), and the shared
           Connector/Relay path for private Cloud connectivity.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">CN</div>
        <h3><a href="dev_connector.html">Connector &amp; Relay</a></h3>
        <p>Connector architecture, building one locally, versioning, and
           the publishing workflow.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">MR</div>
        <h3><a href="dev_models_results.html">Models, Examples &amp; Results</a></h3>
        <p>The model-adapter contract, WorkspaceManager boundaries, the
           result package, and visualization.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">EC</div>
        <h3><a href="dev_extending.html">Extending CryoStack</a></h3>
        <p>Concrete recipes: a new application, model adapter, Remote/Cloud
           example, capability, or Auto-config change.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">AC</div>
        <h3><a href="building_agents.html">Auto-config &middot; Beta</a></h3>
        <p>The deterministic configuration layer's behavioral contract and
           implementation files.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">TE</div>
        <h3><a href="dev_testing.html">Testing</a></h3>
        <p>The Python suite, Node tests, the book build, source guards, and
           what to run for each kind of change.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">DM</div>
        <h3><a href="dev_deployment.html">Deployment &amp; Maintenance</a></h3>
        <p>Contribution workflow, documentation builds, and where the
           actual maintainer-only procedures live.</p>
      </div>

    </div>

  </section>

  <section id="scope" class="cryostack-section">

    <div class="cryostack-section-label">Scope</div>
    <h2>What this guide covers.</h2>

    <p class="cryostack-section-intro">
      This guide is for people <strong>building on or extending</strong>
      CryoStack. Instructions for ordinary users who install and pair the
      CryoStack Connector, and for configuring HPC access, live in the
      CryoLauncher <strong>User Manual</strong>.
    </p>

    <p>
      Operating a CryoStack <em>deployment</em> &mdash; publishing production
      connector binaries, the canonical release store, nginx and service
      administration, production rollback &mdash; is covered by a separate
      <strong>Maintainer Guide</strong> at <code>/docs/maintainer/</code>.
      That guide is restricted at the authentication boundary to accounts
      holding a <code>developer</code>, <code>maintainer</code>,
      <code>admin</code>, or <code>owner</code> role; a project owner grants
      roles from the CryoStack Control Center. It is not part of this public
      build.
    </p>

    <p>
      <span class="cryostack-status supported">Stable</span>
      architecture, application development, shared UI, models, results,
      testing, contribution workflow.
      <span class="cryostack-status dev">In progress</span>
      expanded model-adapter reference and integration examples.
    </p>

  </section>

</div>
:::

---

:::{raw} html
<div class="cryostack-docs-page">
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
        <a href="../index.html">Home</a>
        <a href="../documentation.html">Documentation</a>
        <a href="../resources.html">Resources</a>
        <a href="../about.html">About</a>
      </div>

      <div class="cryostack-footer-group">
        <h3>Applications</h3>
        <a href="/icesheets/">CryoLauncher</a>
        <a href="/icesee-gui/">ICESEE</a>
        <a href="/livist/">LIVIST</a>
      </div>

      <div class="cryostack-footer-group">
        <h3>Community</h3>
        <a href="https://github.com/ICESEE-project/CryoStack" target="_blank" rel="noopener noreferrer">GitHub</a>
        <a href="https://github.com/ICESEE-project" target="_blank" rel="noopener noreferrer">ICESEE Project</a>
        <a href="https://github.com/ICESEE-project/CryoStack/issues" target="_blank" rel="noopener noreferrer">Report an Issue</a>
      </div>

    </div>

    <div class="cryostack-footer-bottom">
      <div>Developed by ICCL and PGSL at the Georgia Institute of Technology.</div>
      <div class="cryostack-footer-meta">
        <span>© 2026 CryoStack</span>
        <span>BSD 2-Clause License</span>
      </div>
    </div>

  </footer>
</div>
:::


### Agent configuration integration

`CRYOSTACK_AGENT_PANEL` enables the configuration planner in both gateways.
The mounted planner uses `cryostack_src/agents/intent.py` and
`icesee_jupyter_book/ui/configuration_agent.py`. It creates an inert delta over
manual widget state, not an executable or approved RunPlan. The older
RunAssistant/tool-loop APIs remain available for integrations but are no longer
the mounted CryoLauncher configuration path.

Catalogs are rebuilt from model capabilities, runnable workspace/application
examples, compute profiles, curated solver-aware parameters, and ICESEE's
example registry/templates. Missing or unsupported requests are surfaced;
there is no new model/runtime capability registry. GPU/multi-node restrictions
come from `resolve_workflow_capabilities`.

Applying requires unchanged catalog/configuration state and independently
recomputed inference. It mutates only allowlisted configuration controls and
runs the existing model/Slurm or cloud checks. It never invokes approval,
job staging, or submission. Example selection may perform the same local
workspace preparation as a manual selection. The normal manual execution handlers remain responsible
for fresh identity, backend, scientific staging and cloud readiness checks.
A configuration check is not an execution authorization. On an application
error, the current configuration is displayed for review; no run is started.

The planner is deterministic and supports a bounded natural-language grammar.
It is not a conversational scientific reasoning service. Add new vocabulary
through metadata where possible, and test real gateway controls as well as
inference. New core planner modules must remain in the agent policy scan.
