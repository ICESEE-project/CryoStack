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

## What Remote means

Remote means executing on an existing remote, institutional, or HPC
resource you already have access to — a cluster, server, or workstation —
rather than AWS Cloud infrastructure. Both **CryoLauncher** and **ICESEE**
support Remote execution, and both have already been used this way.

Both applications reach that resource through the same two connectivity
concepts, via a common `RemoteBridge` pattern:

**Direct SSH** connects from the application host to your resource when
network policy and reachability allow it — you supply host, user, port,
and credentials, the same as an ordinary SSH login.

**Connector/Relay** is for resources reachable only from your own
workstation, VPN, or an approved edge environment. A packaged Connector you
install locally exchanges commands and files with CryoStack through an
authenticated relay, without requiring an inbound connection from CryoStack
to your institution. The target institution keeps its own accounts,
authentication, and scheduler policy. An **Auto** setting lets CryoStack
pick between the two.

This shared connectivity choice is as far as the similarity goes — each
application configures, submits, and reports on a Remote run through its
own implementation, described separately below.

## CryoLauncher Remote

In CryoLauncher, **Basic/Advanced** (the configuration experience) and
**Remote/Cloud** (the execution backend) are independent choices, not a
sequence. Selecting Remote shows the same Remote configuration — target
host/user/port, access mode, cluster name, Spack-vs-Container backend
choice, and Slurm resources — whether the current mode is Basic or
Advanced. **Basic** mainly simplifies the *scientific* configuration
surface (a curated parameter panel instead of the raw example files);
**Advanced** additionally exposes the raw-file editor, the dataset
manager, the Run/Test/Deploy selector, and direct working-copy access.
Both submit a Remote run through the exact same underlying path.

```text
configure scientific workflow
      |
      v
select Remote
      |
      v
configure target/access
      |
      v
choose Remote software backend where applicable
      |
      v
configure Slurm resources
      |
      v
submit
      |
      v
monitor
      |
      v
retrieve/results
```

For the full field-by-field walkthrough, see
<a href="../applications/icesheets/user_manual.html#configure-access-to-your-hpc-system">Configure access to your HPC system</a>
and
<a href="../applications/icesheets/user_manual.html#run-monitoring-and-history">Run monitoring and history</a>.

## ICESEE Remote

ICESEE has its own interface organization — **Local**, **Remote**, and
**Cloud** tabs, alongside Auto-config · Beta — not CryoLauncher's
Basic/Advanced model. Its Remote mode is operational and has already been
used for real ensemble data-assimilation runs, not planned or experimental
functionality.

Configuring an ICESEE Remote run adds the same target/access fields as
CryoLauncher (host, user, access mode) plus ICESEE's own
ensemble/data-assimilation configuration — model, filter type, ensemble
size, and the process counts relevant to a Remote submission. Submission,
status, retrieval, and visualization then follow ICESEE's own Remote
workflow, distinct from CryoLauncher's:

- **Submit** — sent through ICESEE's own Remote runner, whether by direct
  SSH or Connector.
- **Monitor** — status and logs are checked from ICESEE's own Run Log and
  results tools, not CryoLauncher's Workspace status panel.
- **Retrieve and visualize** — ICESEE presents a run's output files and any
  generated figures directly, rather than through CryoLauncher's structured
  result-package viewer; see
  <a href="../applications/icesee/user_manual.html#run-log-and-results-preview">Run Log and Results Preview</a>.

For the full walkthrough, see
<a href="../applications/icesee/user_manual.html#remote-mode">ICESEE Remote Mode</a>.

## Institutional connectivity for Cloud workflows

A Remote Connector pairing can also carry private institutional
connectivity for a Cloud workflow that needs it — see
[Running in the Cloud](hpc_cloud.md) for that case.

## Troubleshooting

Common Remote connectivity problems are consolidated in
[Troubleshooting](user_troubleshooting.md).
