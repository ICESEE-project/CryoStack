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

## Connectivity (Remote)

- SSH key, password bootstrap, and manual/web-portal registration issues —
  see <a href="../applications/icesheets/user_manual.html#473-ssh-keys">SSH keys</a>.
- VPN/MFA/campus-network reachability — see
  <a href="../applications/icesheets/user_manual.html#541-vpn-mfa-campus-network">VPN, MFA, campus network</a>.
- Verifying a connection before submitting a run — see
  <a href="../applications/icesheets/user_manual.html#597-check-ssh-access">Check SSH Access</a>.

## Cloud

Cloud-specific submission, connectivity, and job-state problems are
consolidated in
<a href="hpc_cloud.html#troubleshooting-and-verification">Running in the Cloud &rarr; Troubleshooting and verification</a>.

## Runs and results

- A run that never appears to start, or a state that looks stuck — see
  <a href="../applications/icesheets/user_manual.html#11-run-monitoring-and-history">Run monitoring and history</a>.
- A results view with nothing to preview, or only legacy figures — see
  <a href="../applications/icesheets/user_manual.html#764-legacy-runs">Legacy runs</a>.

## Where to look next

If a problem is not covered here, check the specific application's own
User Manual, then the [Developer Guide](developer_guide.md) for the
implementation behind the behavior you are seeing.
