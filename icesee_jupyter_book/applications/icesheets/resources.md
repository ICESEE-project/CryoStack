# CryoLauncher Resources

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>

<div class="cryostack-app-doc-page">

  <section class="cryostack-app-doc-hero">

    <div class="cryostack-section-label">
      CryoLauncher Documentation
    </div>

    <h1>CryoLauncher Resources</h1>

    <p>
      A launchpad for the CryoLauncher documentation, supported models,
      execution environments, containers, datasets, source code, and support.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary" href="/icesheets/">
        Open CryoLauncher
      </a>

      <a class="cryostack-btn secondary" href="getting_started.html">
        Getting Started
      </a>

      <a class="cryostack-btn secondary" href="user_manual.html">
        User Manual
      </a>
    </div>

  </section>

  <div class="cryostack-app-doc-content">
:::

## Documentation

:::{raw} html
<div class="cryostack-resource-card-grid">

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Guide</div>
    <h3>Getting Started</h3>
    <p>
      Configure and run your first ice-sheet simulation, then inspect the
      structured results.
    </p>
    <a href="getting_started.html">Open Getting Started &rarr;</a>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Reference</div>
    <h3>User Manual</h3>
    <p>
      The full operational guide: Basic and Advanced mode, My Workspace,
      datasets, execution, runs, results, visualization, and downloads.
    </p>
    <a href="user_manual.html">Open User Manual &rarr;</a>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Platform</div>
    <h3>CryoStack Documentation</h3>
    <p>
      How CryoLauncher fits into the wider CryoStack platform.
    </p>
    <a href="../../documentation.html">Open Documentation &rarr;</a>
  </article>

</div>
:::

## Supported models

:::{raw} html
<div class="cryostack-resource-card-grid">

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Ice-Sheet Model</div>
    <h3>ISSM <span class="cryostack-status supported">Supported</span></h3>
    <p>
      The Ice-sheet and Sea-level System Model &mdash; the mature CryoLauncher
      path, with guided configuration, structured results, and deterministic
      visualization.
    </p>
    <div class="cryostack-resource-inline-links">
      <a href="https://issm.jpl.nasa.gov/" target="_blank" rel="noopener noreferrer">Website</a>
      <a href="https://issmteam.github.io/ISSM-Documentation/" target="_blank" rel="noopener noreferrer">Documentation</a>
      <a href="https://github.com/ISSMteam/ISSM" target="_blank" rel="noopener noreferrer">GitHub</a>
    </div>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Ice-Sheet Model</div>
    <h3>Icepack <span class="cryostack-status dev">Experimental</span></h3>
    <p>
      A Python library built on Firedrake. Selectable in CryoLauncher, but not
      yet at ISSM feature parity for configuration and results.
    </p>
    <div class="cryostack-resource-inline-links">
      <a href="https://icepack.github.io/" target="_blank" rel="noopener noreferrer">Documentation</a>
      <a href="https://github.com/icepack/icepack" target="_blank" rel="noopener noreferrer">GitHub</a>
    </div>
  </article>

</div>
:::

## Examples

:::{raw} html
<div class="cryostack-resource-card-grid">

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Application Examples</div>
    <h3>ISSM examples</h3>
    <p>
      CryoLauncher discovers the examples installed with ISSM. Application
      examples are read-only; <code>SquareIceShelf</code> is the recommended
      first run. Clone any example into My Workspace to edit it.
    </p>
    <a href="user_manual.html#application-examples-vs-my-workspace">How examples work &rarr;</a>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Model Suite</div>
    <h3>ISSM example suite</h3>
    <p>
      The upstream ISSM tutorials and example models that the installed
      examples are drawn from.
    </p>
    <a href="https://issmteam.github.io/ISSM-Documentation/" target="_blank" rel="noopener noreferrer">
      ISSM tutorials &rarr;
    </a>
  </article>

</div>
:::

## Execution environments

:::{raw} html
<div class="cryostack-resource-card-grid">

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Execution Mode</div>
    <h3>Remote <span class="cryostack-status supported">Supported</span></h3>
    <p>
      Run on a Linux server or HPC cluster you have access to, through the
      CryoStack Connector (recommended) or direct SSH, with Slurm settings for
      scheduler-managed systems.
    </p>
    <a href="user_manual.html#execution-modes-and-backends">Execution guide &rarr;</a>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Access</div>
    <h3>Configure HPC access</h3>
    <p>
      Connect with your own HPC username, allocation, remote directory, and a
      CryoStack-generated SSH key scoped to your identity. Trust model,
      Connector setup, key registration, VPN/MFA, and troubleshooting.
    </p>
    <a href="user_manual.html#configure-access-to-your-hpc-system">Access guide &rarr;</a>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Download</div>
    <h3>CryoStack Connector</h3>
    <p>
      The desktop app that carries CryoStack's SSH through your workstation's
      network access. Available platforms are those listed in the download
      manifest.
    </p>
    <a href="/connect/">Connector setup &rarr;</a>
    <a href="/downloads/connectors/">All downloads &rarr;</a>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Execution Mode</div>
    <h3>Cloud <span class="cryostack-status dev">In development</span></h3>
    <p>
      AWS Batch execution. Infrastructure provisioning and the run contract
      exist; real cloud execution has not been accepted yet.
    </p>
    <a href="../../documentation.html">Platform status &rarr;</a>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Scheduler</div>
    <h3>Slurm</h3>
    <p>
      Reference for the account, partition, node, task, memory, and wall-time
      settings CryoLauncher exposes for scheduler-managed resources.
    </p>
    <a href="https://slurm.schedmd.com/documentation.html" target="_blank" rel="noopener noreferrer">
      Slurm documentation &rarr;
    </a>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Georgia Tech HPC</div>
    <h3>PACE</h3>
    <p>
      Georgia Tech research computing and HPC services.
    </p>
    <a href="https://pace.gatech.edu/" target="_blank" rel="noopener noreferrer">Visit PACE &rarr;</a>
  </article>

</div>
:::

## Reproducible software environments

:::{raw} html
<div class="cryostack-resource-card-grid">

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Containers</div>
    <h3>Tested container images</h3>
    <p>
      CryoLauncher's Docker / OCI path uses a curated tested image whose full
      software stack is validated and pinned by verified digest, so a run's
      environment is reproducible.
    </p>
    <a href="https://github.com/ICESEE-project/ICESEE-Containers" target="_blank" rel="noopener noreferrer">
      ICESEE-Containers &rarr;
    </a>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Package Management</div>
    <h3>ICESEE-Spack</h3>
    <p>
      Spack-managed software environments for the ICESEE-Spack execution
      backend, with a first-time onboarding check and prepare workflow.
    </p>
    <a href="https://github.com/ICESEE-project/ICESEE-Spack" target="_blank" rel="noopener noreferrer">
      ICESEE-Spack &rarr;
    </a>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Containers</div>
    <h3>Apptainer</h3>
    <p>
      Container technology commonly used on institutional HPC systems.
    </p>
    <a href="https://apptainer.org/" target="_blank" rel="noopener noreferrer">Visit Apptainer &rarr;</a>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Finite Elements</div>
    <h3>Firedrake</h3>
    <p>
      The automated finite-element system that Icepack is built on.
    </p>
    <a href="https://www.firedrakeproject.org/" target="_blank" rel="noopener noreferrer">Visit Firedrake &rarr;</a>
  </article>

</div>
:::

## Data and results

:::{raw} html
<div class="cryostack-resource-card-grid">

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">My Workspace</div>
    <h3>Datasets</h3>
    <p>
      Upload reusable input files to your personal dataset area, reference
      them from user examples, and let CryoLauncher stage them with the run.
    </p>
    <a href="user_manual.html#dataset-management">Dataset guide &rarr;</a>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Results</div>
    <h3>Structured result format</h3>
    <p>
      What a completed ISSM run produces: <code>metadata.json</code>, mesh,
      per-field data, the final model, and figures &mdash; discovered rather
      than assumed.
    </p>
    <a href="user_manual.html#result-format-reference">Result format &rarr;</a>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Visualization</div>
    <h3>Solution / Field / Timestep</h3>
    <p>
      How the field-visualization panel discovers solutions and fields,
      handles transient timesteps, and renders nodal, elemental, and scalar
      results deterministically.
    </p>
    <a href="user_manual.html#visualization">Visualization guide &rarr;</a>
  </article>

</div>
:::

## Source code and project

:::{raw} html
<div class="cryostack-resource-card-grid">

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Source Code</div>
    <h3>CryoLauncher repository</h3>
    <p>
      The gateway, application layer, connector, and deployment source.
    </p>
    <a href="https://github.com/ICESEE-project/CryoLauncher" target="_blank" rel="noopener noreferrer">
      View repository &rarr;
    </a>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Organization</div>
    <h3>ICESEE project</h3>
    <p>
      The umbrella organization for ICESEE, CryoLauncher, containers, and
      Spack environments.
    </p>
    <a href="https://github.com/ICESEE-project" target="_blank" rel="noopener noreferrer">
      View organization &rarr;
    </a>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Data Assimilation</div>
    <h3>ICESEE</h3>
    <p>
      Ensemble state estimation and parameter inference with supported
      ice-sheet models.
    </p>
    <a href="/icesee-gui/">Open ICESEE &rarr;</a>
  </article>

  <article class="cryostack-resource-card">
    <div class="cryostack-resource-tag">Citation</div>
    <h3>Citing CryoStack</h3>
    <p>
      How to cite CryoStack together with the models, datasets, and
      publications used in your work.
    </p>
    <a href="../../about.html">Citation guidance &rarr;</a>
  </article>

</div>
:::

## Tutorials

:::{raw} html
<p>
  <span class="cryostack-status planned">Planned</span>
  &nbsp;Step-by-step CryoLauncher tutorials (a first ISSM run, editing an
  example in My Workspace, working with datasets, and reading results) are
  planned. Until then, the
  <a href="getting_started.html">Getting Started</a> guide and the
  <a href="user_manual.html">User Manual</a> cover the full workflow.
</p>
:::

## Support

Use the [CryoLauncher issue tracker](https://github.com/ICESEE-project/CryoLauncher/issues)
for application bugs, connector and remote-execution problems, documentation
issues, and feature requests.

Questions about ISSM, Icepack, Firedrake, or PETSc themselves should go to
that project's own documentation and support channels.

:::{raw} html
  </div>
</div>
:::
