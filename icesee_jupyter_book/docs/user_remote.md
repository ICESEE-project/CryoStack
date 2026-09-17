# Running Remotely

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
    <h1>Running Remotely</h1>
    <p>
      Bring an institutional cluster or workstation you already have access
      to into a CryoStack run. This page covers how a scientist uses Remote
      execution; how it is implemented lives in the Developer Guide's
      <a href="dev_execution.html">Execution Backends</a> page.
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

## Two ways to reach your resource

**Direct SSH** connects from the application host to your resource when
network policy and reachability allow it — you supply host, user, port,
and credentials, the same as an ordinary SSH login.

**Connector/Relay** is for resources reachable only from your own
workstation, VPN, or an approved edge environment. A packaged Connector you
install locally exchanges commands and files with CryoStack through an
authenticated relay, without requiring an inbound connection from CryoStack
to your institution. The target institution keeps its own accounts,
authentication, and scheduler policy.

For step-by-step setup (SSH keys, password bootstrap, VPN/MFA, pairing a
Connector), see:

- <a href="../applications/icesheets/user_manual.html#9-configure-access-to-your-hpc-system">Configure access to your HPC system</a>
  (CryoLauncher)
- <a href="../applications/icesee/user_manual.html#remote-mode">ICESEE Remote Mode</a>

## Submission, monitoring, and retrieval

Once access is configured, Remote submission, status/log monitoring, and
result retrieval work the same way regardless of which access mode you
used to connect — see
<a href="../applications/icesheets/user_manual.html#11-run-monitoring-and-history">Run monitoring and history</a>
and [Results & Visualization](user_results.md).

## Institutional connectivity for Cloud workflows

The same Connector/Relay session you pair for Remote access can also carry
private institutional connectivity for a Cloud workflow that needs it — see
[Running in the Cloud](hpc_cloud.md) for the concrete case (ISSM on AWS
reaching an institutional MATLAB license).

## Troubleshooting

Common Remote connectivity problems are consolidated in
[Troubleshooting](user_troubleshooting.md).
