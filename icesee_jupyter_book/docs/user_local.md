# Running Locally

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
    <h1>Running Locally</h1>
    <p>
      ICESEE has a Local mode on the CryoStack application host.
      CryoLauncher uses Remote HPC or AWS; Frozen Legacies and LIVIST expose
      data tools rather than a Local/Remote/Cloud selector.
    </p>
    <div class="cryostack-docs-actions">
      <a class="cryostack-btn secondary" href="user_manual.html">
        &larr; User Manual
      </a>
    </div>
  </section>
</div>
:::

---

**ICESEE** offers a Local execution mode: a selected workflow runs as a
Python subprocess on the application host, without a scheduler or cloud
resource. Start with the Lorenz-96 example to run without an HPC login or
AWS connection — see
<a href="../applications/icesee/user_manual.html">ICESEE's Local Mode</a>
for scope and limits.

**CryoLauncher** has no Local execution mode for a standalone ISSM or
Icepack run — its execution paths are [Remote](user_remote.md) and
[Cloud](hpc_cloud.md).

**Frozen Legacies** and **LIVIST** are not organized around Local/Remote/
Cloud execution modes at all; see
[Applications & Workflows](user_apps.md).

Local here means the application host, not your laptop. To reproduce a
CryoLauncher result on your own computer, install the matching model
environment and follow the <a href="/applications/icesheets/soft_launch/comparison">PC/AWS comparison</a>.
That comparison is separate from an in-app Local execution mode.
