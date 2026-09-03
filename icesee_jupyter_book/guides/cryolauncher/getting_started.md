# Getting Started with CryoLauncher

CryoLauncher provides browser-based access to supported ice-sheet models through the CryoStack platform. It allows users to configure simulations, select computing resources, submit jobs, monitor execution, and inspect results without managing the complete scientific software environment manually.

[Open CryoLauncher](https://cryostack.eas.gatech.edu/icesheets/)

---

## Before You Begin

To use CryoLauncher, you need:

- A modern web browser.
- Access to the CryoStack platform.
- Access to a supported computing resource for remote or HPC execution.
- Valid authentication credentials when using a remote system.

Basic exploration of the interface does not require a local installation.

---

## Supported Models

CryoLauncher currently supports:

### ISSM

The Ice-sheet and Sea-level System Model is a multiphysics framework for ice-sheet and sea-level simulations.

### Icepack

Icepack is a Python library built on Firedrake for modeling ice flow and related glaciological processes.

The models and available examples shown in the interface depend on the software environments configured on the selected execution backend.

---

## Open CryoLauncher

Open:

[https://cryostack.eas.gatech.edu/icesheets/](https://cryostack.eas.gatech.edu/icesheets/)

The interface contains two principal areas:

1. **Run settings** — configure the model, example, files, execution mode, and computing resources.
2. **Run log and results preview** — monitor execution and inspect generated outputs.

---

## Choose a User Mode

CryoLauncher provides two interface modes.

### Basic Mode

Basic Mode is intended for first-time users and standard examples. It automatically discovers supported models and available examples while showing only the most commonly used controls.

Use Basic Mode when you want to:

- Run an existing model example.
- Use automatically discovered files.
- Submit a simulation with minimal configuration.
- Learn the CryoLauncher workflow.

### Advanced Mode

Advanced Mode exposes additional controls for custom paths, file editing, execution commands, and expert workflows.

Use Advanced Mode when you need to:

- Run a custom model configuration.
- Modify model input files.
- Select custom execution paths.
- Control scheduler and backend settings directly.

For your first simulation, begin with **Basic Mode**.

---

## Choose an Execution Mode

CryoLauncher supports several execution pathways.

### Local

Runs the selected workflow on the system hosting CryoStack.

Use Local mode for:

- Testing.
- Small examples.
- Development workflows.
- Applications already installed on the CryoStack server.

### Remote

Runs the workflow on another workstation, server, or HPC cluster.

Remote mode may require:

- A connector session.
- SSH configuration.
- Authentication credentials.
- A remote execution directory.

### Cloud

Runs supported workflows on **your own AWS account and credits**.

Connect the account once from **Cloud Environment → AWS ACCOUNT**:

1. **Connect AWS Account** → **Open AWS Setup** — a pre-filled CloudFormation
   page in your AWS console creates one least-privilege IAM role,
   `CryoStackExecutionRole`.
2. Paste the role ARN back and **Verify connection**.
3. **Prepare cloud** — CryoStack derives the storage bucket, queue and job
   definition and provisions what is missing.
4. **Review & Launch** — check the expected runtime, resources and estimated
   AWS cost, then **Launch cloud run**. Launch is always explicit; changing the
   run configuration after opening the review requires reviewing it again.

Cost figures are estimates. AWS controls credits and billing; if a price is
unavailable CryoStack says so and still lets you launch.

CryoStack uses temporary role access and **never stores your AWS access
keys**. You are never asked for an access key, a secret, an AWS password, or a
CLI profile. `aws configure` is not part of this workflow — it is developer
only.

---

## Run Your First Simulation

A basic first run follows this sequence:

1. Open CryoLauncher.
2. Select **Basic** user mode.
3. Select an execution mode.
4. Select a supported model.
5. Select an available example.
6. Review the automatically discovered files and run target.
7. Configure the required computing resources.
8. Submit the job.
9. Monitor the run log.
10. Inspect the results preview when the job completes.

---

## Example: Running ISSM

For an initial ISSM workflow:

1. Select **ISSM** from the model list.
2. Choose an available example, such as **ISMIP**.
3. Confirm the detected execution file and run target.
4. Select the appropriate execution mode.
5. Configure remote or Slurm settings when needed.
6. Submit the simulation.
7. Follow progress in the run log.

The exact examples available depend on the configured ISSM installation.

---

## Example: Running Icepack

For an initial Icepack workflow:

1. Select **Icepack** from the model list.
2. Choose one of the discovered examples.
3. Review the detected Python entry point and files.
4. Select the execution mode.
5. Submit the workflow.
6. Monitor the run log and results preview.

Icepack workflows may use the Firedrake environment configured on the selected backend.

---

## Remote and HPC Execution

Remote execution is organized through expandable configuration panels.

Depending on the selected workflow, you may need to configure:

- Remote host information.
- Authentication.
- Server-side SSH keys.
- Execution directory.
- Scheduler settings.
- Slurm account and partition.
- Number of nodes and tasks.
- Wall-clock time.

The CryoStack connector can be used when direct access from the platform server is not available.

---

## Monitoring a Run

After submission, CryoLauncher reports progress through the **Run log**.

The log may display:

- Connector status.
- Staging operations.
- Submission commands.
- Scheduler job identifiers.
- Execution progress.
- Errors and warnings.
- Output-file locations.

Do not close the page while configuring or submitting a workflow unless the job has already been transferred successfully to the remote backend.

---

## Viewing Results

When supported output products are available, CryoLauncher displays them in the **Results preview** area.

Results may include:

- Log files.
- Figures.
- Reports.
- Model output files.
- Downloadable archives.
- Links to the remote execution directory.

The available preview depends on the selected model and example.

---

## Next Steps

After completing your first simulation:

- Read the **CryoLauncher User Manual** for the complete interface description.
- Review **CryoLauncher Resources** for model documentation and external references.
- Use **Advanced Mode** for custom workflows.
- Use **ICESEE** when data assimilation is required.

