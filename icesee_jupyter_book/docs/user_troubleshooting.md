# Troubleshooting

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
    <h1>Troubleshooting</h1>
    <p>
      Common setup, connectivity, and run problems. Deep implementation
      diagnostics (log formats, internal error codes, staging internals)
      live in the Developer Guide, not here.
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

## Start with the application that shows the problem

| Application | User-facing help |
| --- | --- |
| **CryoLauncher** | <a href="../applications/icesheets/user_manual.html#troubleshooting">CryoLauncher troubleshooting</a> |
| **ICESEE** | <a href="../applications/icesee/user_manual.html">ICESEE User Manual</a> |
| **Frozen Legacies** | <a href="../applications/frozen_legacies/user_manual.html#troubleshooting">Frozen Legacies troubleshooting</a> |
| **LIVIST** | <a href="/livist/docs/livist_user_manual/#13-troubleshooting">LIVIST troubleshooting</a> |

Those manuals own application controls, missing data, run states, scientific
products, and recovery steps. This page only covers shared CryoStack concerns.

## Shared connectivity and cloud concerns

Remote/HPC connectivity through direct SSH or the CryoStack Connector applies
to CryoLauncher and ICESEE. Start with [Running Remotely](user_remote.md).
Cloud account, AWS Batch, and shared job-state concerns are consolidated in
<a href="hpc_cloud.html#troubleshooting-and-verification">Running in the Cloud &rarr; Troubleshooting and verification</a>.

Frozen Legacies and LIVIST do not use those execution modes. For them, follow
their application manual for catalog, map, product, imagery, or publication
issues rather than applying an execution-backend fix.

## Escalating a platform problem

If the application manual does not cover the issue, check the
[Developer Guide](developer_guide.md) for the platform implementation behind
the behavior you are seeing.


## Allocation access and empty states

Resource Allocations administration requires an owner or administrator session. A forbidden response should be resolved through the existing role-management process; do not substitute demo credentials. Researchers can inspect their own allocations.

A zero-budget overview means no pool budget has been configured. When CryoStack registration approval is enabled, automatic credits are evaluated at first approval, not signup. They require an enabled policy, a qualifying creation date, matching email-domain/institution filters, no prior introductory-grant marker, and enough unallocated funds for the full grant. An invitation list still requires an exact-email approval check; matching an institutional domain alone is insufficient. Older accounts need a reviewed individual adjustment rather than a policy backfill.

A missing or invalid BYO connection must fail closed. Reconnect the user's AWS account through the normal cloud workflow; do not enter a server profile to bypass verification. Test reservations do not provide real cloud execution.

When reporting an issue, include the page, time, selected application and mode, visible error, and a screenshot with private data removed. Never include passwords, access keys, session tokens, or private datasets. See the [visual walkthrough](visual_walkthrough.md).
