# Getting Started with CryoLauncher

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

    <h1>Getting Started with CryoLauncher</h1>

    <p>
      Configure and run your first ice-sheet simulation through CryoStack
      using local, remote, HPC, or cloud computing resources.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary" href="/icesheets/">
        Open CryoLauncher
      </a>

      <a
        class="cryostack-btn secondary"
        href="user_manual.html">
        User Manual
      </a>

      <a
        class="cryostack-btn secondary"
        href="resources.html">
        Resources
      </a>
    </div>

  </section>

  <div class="cryostack-app-doc-content">
:::

CryoLauncher provides browser-based access to supported ice-sheet models through the CryoStack platform. It allows users to configure simulations, select computing resources, submit jobs, monitor execution, and inspect results without manually managing the complete scientific software environment.

## Before You Begin

To use CryoLauncher, you need:

- A modern web browser.
- Access to the CryoStack platform.
- Access to a supported computing resource for remote or HPC execution.
- Valid credentials when connecting to a remote system.

Basic exploration of the interface does not require a local software installation.

## Supported Models

CryoLauncher currently supports:

### ISSM

The Ice-sheet and Sea-level System Model is a multiphysics framework for ice-sheet and sea-level simulations.

### Icepack

Icepack is a Python library built on Firedrake for modeling ice flow and related glaciological processes.

The models and examples available in the interface depend on the scientific environments configured on the selected execution backend.

## Open CryoLauncher

Open:

[https://cryostack.eas.gatech.edu/icesheets/](https://cryostack.eas.gatech.edu/icesheets/)

The interface contains two main areas:

1. **Run settings** — configure the model, example, execution mode, files, and computing resources.
2. **Run log and results preview** — monitor the simulation and inspect available outputs.

## Choose a User Mode

CryoLauncher provides two user modes.

### Basic Mode

Basic Mode is intended for first-time users and standard examples. It automatically discovers supported models, examples, files, and execution targets.

Use Basic Mode to:

- Run an existing model example.
- Use automatically discovered paths and files.
- Submit a simulation with minimal configuration.
- Learn the standard CryoLauncher workflow.

### Advanced Mode

Advanced Mode provides more control over paths, files, execution commands, and backend configuration.

Use Advanced Mode to:

- Run a custom model setup.
- Modify input files.
- Select custom execution paths.
- Configure expert workflows.

For your first simulation, begin with **Basic Mode**.

## Choose an Execution Mode

CryoLauncher supports several execution pathways.

### Local

Runs the selected workflow on the system hosting CryoStack.

Use Local mode for testing, development, and smaller examples.

### Remote

Runs the workflow on another workstation, server, or HPC cluster.

Remote mode may require:

- SSH configuration.
- Authentication credentials.
- A connector session.
- A remote execution directory.
- Scheduler settings.

### Cloud

Runs supported workflows using configured cloud infrastructure.

Cloud execution depends on the available deployment and user-provided computing resources or cloud credits.

## Run Your First Simulation

A typical first run follows these steps:

1. Open CryoLauncher.
2. Select **Basic** user mode.
3. Select an execution mode.
4. Select a supported model.
5. Select an available example.
6. Review the automatically discovered files and run target.
7. Configure the required computing resources.
8. Submit the simulation.
9. Monitor progress in the run log.
10. Inspect the results preview when execution completes.

## Running an ISSM Example

For an initial ISSM workflow:

1. Select **ISSM**.
2. Choose an available example, such as **ISMIP**.
3. Review the detected directory, files, and run target.
4. Select the required execution mode.
5. Configure remote or Slurm settings when needed.
6. Submit the simulation.
7. Follow progress in the run log.

The available examples depend on the configured ISSM installation.

## Running an Icepack Example

For an initial Icepack workflow:

1. Select **Icepack**.
2. Choose one of the available examples.
3. Review the detected Python entry point and configuration files.
4. Select the execution mode.
5. Submit the workflow.
6. Monitor the run log and results preview.

Icepack workflows use the Firedrake environment configured on the selected backend.

## Remote and HPC Execution

Remote execution settings are organized into expandable sections.

Depending on the workflow, you may need to configure:

- Remote connection details.
- Authentication.
- Server-side SSH keys.
- Execution directory.
- Slurm account and partition.
- Number of nodes and tasks.
- Wall-clock time.
- Execution backend.

The CryoStack connector can be used when the remote system cannot be reached directly from the CryoStack server.

## Monitoring a Run

After submission, the **Run log** reports the workflow status.

The log may include:

- Connector status.
- File-staging operations.
- Submission commands.
- Scheduler job identifiers.
- Execution progress.
- Warnings and errors.
- Output locations.

## Viewing Results

When supported outputs are available, CryoLauncher displays them in the **Results preview** area.

Results may include:

- Figures.
- Reports.
- Log files.
- Model outputs.
- Downloadable archives.
- Links to execution directories.

The available results depend on the selected model and example.

## Next Steps

After completing your first simulation:

- Read the [CryoLauncher User Manual](user_manual) for a complete description of the interface.
- Review [CryoLauncher Resources](resources) for model documentation and external references.
- Use **Advanced Mode** for custom workflows.
- Open [ICESEE](https://cryostack.eas.gatech.edu/icesee-gui/) when ensemble data assimilation is required.

:::{raw} html
  </div>
</div>
:::