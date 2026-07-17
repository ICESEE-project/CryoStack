# CryoLauncher User Manual

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

<h1>CryoLauncher User Manual</h1>

<p>
A complete reference to the CryoLauncher interface, execution modes,
supported workflows, and remote computing capabilities.
</p>

<div class="cryostack-docs-actions">
<a class="cryostack-btn primary" href="/icesheets/">
Open CryoLauncher
</a>

<a class="cryostack-btn secondary" href="getting_started.html">
Getting Started
</a>

<a class="cryostack-btn secondary" href="resources.html">
Resources
</a>
</div>

</section>

<div class="cryostack-app-doc-content">
:::

## Overview

CryoLauncher is the numerical-modeling application within CryoStack. It provides a browser-based interface for configuring and executing supported ice-sheet models on local computers, remote Linux systems, HPC clusters, and cloud resources.

Unlike the **Getting Started** guide, this manual explains every major component of the interface and how each configuration option affects workflow execution.

---

## Interface Overview

The CryoLauncher interface is organized into two primary panels.

### Run Settings

The left panel contains all configuration controls required before submitting a simulation.

Typical controls include:

- User Mode
- Execution Mode
- Model Selection
- Example Selection
- File Discovery
- Run Target
- Editable Configuration
- Remote Connection
- Authentication
- Server-side SSH Keys
- Execution Backend
- Scheduler Resources

Each section expands independently, allowing users to expose only the controls needed for the selected workflow.

---

### Run Log

The upper-right panel displays runtime information including

- Connector status
- File staging
- Environment activation
- Submission commands
- Scheduler messages
- Standard output
- Standard error
- Runtime diagnostics

The log updates continuously while a simulation is running.

---

### Results Preview

When supported outputs are generated, CryoLauncher automatically presents them in the Results Preview panel.

Available outputs may include

- Figures
- Reports
- HTML summaries
- Download links
- Log files
- Model outputs

The displayed content depends on the selected model and workflow.

---

## User Modes

### Basic Mode

Basic Mode automatically discovers available models, examples, files, and run targets.

Recommended for

- First-time users
- Tutorials
- Demonstrations
- Standard workflows

---

### Advanced Mode

Advanced Mode exposes expert controls.

Typical use cases include

- Custom model directories
- Modified input files
- Alternative run scripts
- Custom execution paths
- Research workflows

---

## Execution Modes

CryoLauncher currently supports three execution environments.

### Local Execution

Runs the workflow directly on the CryoStack host.

Best suited for

- Testing
- Tutorials
- Small examples

---

### Remote Execution

Executes workflows on external Linux systems.

Remote execution typically requires

- SSH access
- Authentication
- Remote working directory
- Software installation
- Optional scheduler configuration

---

### Cloud Execution

Cloud execution allows supported workflows to run using configured cloud resources.

Availability depends on the CryoStack deployment.

---

## Supported Models

CryoLauncher currently supports

### ISSM

The Ice-sheet and Sea-level System Model.

CryoLauncher automatically discovers supported ISSM examples and MATLAB entry points.

---

### Icepack

Icepack is a Python-based ice-flow model built on Firedrake.

CryoLauncher discovers available Python examples and associated configuration files.

---

## Remote Computing

CryoLauncher can communicate with

- Linux workstations
- Institutional servers
- Slurm clusters
- Cloud virtual machines

Connections may be established directly through SSH or through the CryoStack Connector.

---

## Authentication

Depending on the deployment, CryoLauncher supports

- SSH keys
- Password authentication
- Connector sessions
- Stored server-side credentials

Authentication methods available to users are determined by the system administrator.

---

## Slurm Integration

When using Slurm-managed HPC systems, CryoLauncher can configure

- Account
- Partition
- Nodes
- Tasks
- CPUs
- Memory
- Wall time
- Job name

These parameters are translated into scheduler submission commands.

---

## CryoStack Connector

The CryoStack Connector enables execution on systems that cannot be reached directly from the CryoStack server.

Typical workflow

1. Launch the Connector.
2. Establish a session.
3. Connect CryoLauncher.
4. Submit the workflow.
5. Monitor execution.
6. Retrieve results.

---

## Security

Users are responsible for protecting

- SSH keys
- Authentication credentials
- Remote accounts
- Cloud credentials

Sensitive information should never be embedded in model source files.

---

## Troubleshooting

### Connector Offline

Verify that the connector is running and the session is active.

### Authentication Failed

Confirm the hostname, username, SSH keys, and remote permissions.

### Scheduler Errors

Review Slurm account information, requested resources, and cluster policies.

### Missing Examples

Verify that the scientific software is installed correctly on the selected backend.

### Missing Results

Inspect the Run Log for execution errors and verify the output directory.

---

## Related Documentation

- [Getting Started](getting_started)
- [Resources](resources)
- [ICESEE](https://cryostack.eas.gatech.edu/icesee-gui/)
- [CryoStack Documentation](../../documentation)

:::{raw} html
</div>
</div>
:::