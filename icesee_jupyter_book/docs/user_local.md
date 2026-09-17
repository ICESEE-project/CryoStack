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
      Local execution exists only where the specific application and
      workflow support it — it is not a universal CryoStack mode.
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

**ICESEE** offers a Local execution mode: a selected workflow runs directly
in the hosting notebook kernel, without a scheduler or cloud resource. This
is the fastest path for small examples and interactive development — see
<a href="../applications/icesee/user_manual.html">ICESEE's Local Mode</a>
for scope and limits.

**CryoLauncher** has no Local execution mode for a standalone ISSM or
Icepack run — its execution paths are [Remote](user_remote.md) and
[Cloud](hpc_cloud.md).

**Frozen Legacies** and **LIVIST** are not organized around Local/Remote/
Cloud execution modes at all; see
[Applications & Workflows](user_apps.md).

Do not assume a workflow that lacks a Local option is somehow incomplete —
some scientific workflows (an MPI-parallel ISSM solve, for example) are not
meaningfully "local" in the first place.
