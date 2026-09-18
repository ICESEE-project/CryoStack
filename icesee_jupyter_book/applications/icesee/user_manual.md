# ICESEE User Manual

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>

<div class="cryostack-app-doc-page">

  <section class="cryostack-app-doc-hero">

    <div class="cryostack-section-label">
      ICESEE Documentation
    </div>

    <h1>ICESEE User Manual</h1>

    <p>
      Understand the ICESEE interface, configure ensemble data assimilation
      experiments, manage observations and model parameters, monitor execution,
      and analyze generated results.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary" href="/icesee-gui/">
        Open ICESEE
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

ICESEE, the Ice Sheet State and Parameter Estimator, provides a unified framework for ensemble-based data assimilation experiments. It connects numerical models, observations, filtering methods, parallel computing resources, and scientific diagnostics through a configurable workflow.

This manual describes the ICESEE application interface and the main configuration options used to prepare, execute, and analyze an experiment.

## ICESEE Workflow

A typical ICESEE experiment follows this sequence:

1. Select an execution mode.
2. Choose an example or numerical model.
3. Load a predefined configuration or preset.
4. Select a data assimilation method.
5. Configure the ensemble.
6. Define observations and uncertain parameters.
7. Select output and reporting options.
8. Launch the workflow.
9. Monitor the run log.
10. Review the generated results.

Although the details vary between applications, this structure remains consistent across Lorenz-96, ISSM, Icepack, flowline models, and other supported examples.

## Interface Overview

The ICESEE interface is organized into two principal areas.

### Run Settings

The Run Settings panel contains the controls used to configure an experiment.

Depending on the selected example, it may include:

- execution mode,
- example selection,
- preset selection,
- data assimilation filter,
- ensemble size,
- random seed,
- physical parameters,
- modeling parameters,
- observation settings,
- output selection,
- report generation,
- and remote execution options.

### Run Log and Results Preview

The Run Log and Results preview area displays information generated during and after execution.

It may include:

- configuration validation,
- environment activation,
- model initialization,
- ensemble generation,
- forecast progress,
- assimilation updates,
- warnings,
- errors,
- generated figures,
- reports,
- and downloadable result files.

## Execution Modes

The execution mode determines where the ICESEE workflow runs.

### Local Mode

Local mode runs the experiment on the system hosting the CryoStack application.

It is suitable for:

- tutorials,
- Lorenz-96 experiments,
- development,
- debugging,
- demonstrations,
- and small ensemble workflows.

Local execution avoids remote authentication and scheduler configuration, making it the recommended mode for a first experiment.

### Remote Mode

Remote mode sends the workflow to another workstation, server, or HPC system.

A remote workflow may require:

- a hostname,
- a username,
- SSH authentication,
- a remote working directory,
- a configured Python or container environment,
- a scheduler,
- and access to the selected model.

Remote mode is appropriate when the local CryoStack server does not have sufficient computational resources or does not contain the required scientific software.

### HPC Mode

HPC execution is used for workflows that require distributed-memory parallelism, larger ensembles, or computationally intensive numerical models.

An HPC configuration may include:

- scheduler type,
- partition or queue,
- account name,
- wall-clock limit,
- number of nodes,
- tasks per node,
- CPUs per task,
- memory,
- module commands,
- environment activation,
- and container execution commands.

ICESEE workflows may use Slurm or another scheduler depending on the connected computing environment.

### Cloud Mode

Cloud mode runs ICESEE on your own AWS account (bring-your-own-AWS) on AWS
Batch, using the same infrastructure CryoLauncher's Cloud Environment panel
provides. Batch runs on a default **Fargate** compute mode; an **Advanced**
section exposes an **EC2** alternative (On-Demand/Spot capacity, a
custom/private network, and guarded GPU/multi-node options) — see
[Compute mode](https://cryostack.eas.gatech.edu/docs/hpc_cloud.html#compute-mode-fargate-default-or-ec2-advanced)
in the Cloud Run Guide.

- **Connect AWS Account** once, through a CloudFormation role your own AWS
  console creates (CryoStack never asks for an access key or secret);
- **Prepare cloud**, which provisions S3 storage, an ECR repository, and an
  AWS Batch job definition for ICESEE in your account, reusing what already
  exists;
- **Review & Launch**, which shows the run's forecast model, filter, ensemble
  size, and process count, and only enables **Launch cloud run** when the
  configuration is inside CryoStack's verified runtime contract;
- live status, log, and result retrieval once a run is submitted.

The **MATLAB license** field (Cloud Environment) only appears when ICESEE's
own forecast model actually needs one — it follows the same capability
resolver every ISSM-driven run uses, not the ICESEE application name or
Basic/Advanced mode. A **Lorenz-96** or **Icepack** forecast model never
shows the field; an **ISSM** (or coupled **ISSM+Icepack**) forecast model
does, because that workflow uses ISSM — and Launch stays blocked until a
usable license is configured for it. Normally you provide the institutional
MATLAB license information once through the dedicated license controls;
Connector supplies supported institutional connectivity when required.
This requirement does not itself qualify an ISSM-based ICESEE workflow for
cloud execution: the example and process restrictions still apply.
See CryoLauncher's
<a href="../icesheets/user_manual.html#matlab-licensing-for-issm-cloud-runs">MATLAB
licensing for ISSM cloud runs</a> for the one-time setup — the same
mechanism applies here.

Today that verified contract covers exactly one configuration: the
**Lorenz-96** example at a single process (**Processes = 1**). Selecting a
different example, or more than one process, is refused at Review — not
silently coerced — because it has not been run end-to-end against the
current container image. See the
[Cloud Run Guide](https://cryostack.eas.gatech.edu/docs/hpc_cloud.html) for
the platform-wide AWS account/infrastructure concepts this reuses, and the
walkthrough below for the exact ICESEE steps.

#### Worked example: Lorenz-96 on AWS

1. **Open ICESEE** and select the **Lorenz-96** example.
2. Leave its configuration at the default (or your own edits) — the same
   `params.yaml` used for a local or Remote run:

   ```yaml
   modeling-parameters:
     example_name: "lorenz96"
     dt: 0.01
     num_years: 10
     timesteps_per_year: 2

   enkf-parameters:
     Nens: 30
     filter_type: "EnKF"
     model_name: "lorenz"
     parallel_flag: "serial"
   ```

3. In **Run settings**, set **Execution mode** to **Cloud**.
4. If you have not connected an AWS account yet, follow
   [Connecting your AWS account](https://cryostack.eas.gatech.edu/docs/hpc_cloud.html#connecting-your-aws-account-byo-aws)
   now. CloudFormation onboarding happens in a separate browser tab — your
   AWS console — not inside CryoStack.
5. Return to CryoStack and click **Verify connection**; confirm the panel
   shows **● Connected**.
6. Click **Prepare cloud** and wait for **Account / Storage / Containers /
   Compute** to all read **Ready**.
7. Set **Processes** to **1** — this is the only value CryoStack will let
   you launch today for ICESEE (see the verified contract above).
8. Click **Review & Launch**. Confirm the card reads
   **ICESEE runtime: Ready**, **Parallel mode: Single-rank verified**,
   **Processes: 1** — this is CryoStack's own honest preflight check, not a
   cosmetic label.
9. Click **Launch cloud run**.
10. ICESEE does not poll AWS in the background — click **Check status** in
    the Run Log toolbar whenever you want to know whether the job has
    finished. It prints the current AWS Batch state (e.g. `RUNNABLE`,
    `RUNNING`, `SUCCEEDED`) to the Run Log.
11. Once status reads `SUCCEEDED`, open the run from the Workspace **Runs**
    list. Selecting it triggers a best-effort sync of its S3 outputs into
    your local run cache, then shows Results — figures and fields render
    the same way a local run's results do.
12. To change anything (ensemble size, seed, observation settings), edit
    the configuration and repeat from step 8 — a new review is always
    required before a changed configuration can launch.
13. See
    [Cleanup](https://cryostack.eas.gatech.edu/docs/hpc_cloud.html#cleanup)
    in the Cloud Run Guide before you consider the run finished — nothing
    about the AWS infrastructure this used is removed automatically.

## Example Selection

The Example menu identifies the numerical application used in the experiment.

Available examples depend on the ICESEE installation and may include:

- Lorenz-96,
- ISSM,
- Icepack,
- one-dimensional flowline models,
- synthetic data assimilation examples,
- and additional user-provided applications.

Selecting an example may change the remaining interface because each application defines its own parameters, observations, state variables, and output products.

## Presets

A preset provides a predefined starting configuration for an example.

A preset may define:

- model parameters,
- physical constants,
- time-stepping controls,
- ensemble size,
- assimilation interval,
- observed variables,
- observation covariance,
- inflation,
- localization,
- initial perturbations,
- and output behavior.

Presets are intended to reduce configuration effort and provide reproducible starting points.

Use the default preset before modifying advanced settings. This helps confirm that the model, environment, and data assimilation workflow are functioning correctly.

## Data Assimilation Methods

The Filter menu selects the ensemble-based data assimilation method.

### Ensemble Kalman Filter

The Ensemble Kalman Filter, or EnKF, updates an ensemble using observations and an ensemble-derived approximation of forecast uncertainty.

The EnKF is useful for:

- nonlinear dynamical systems,
- state estimation,
- parameter estimation,
- synthetic experiments,
- and large numerical models where explicitly storing a full covariance matrix is impractical.

Depending on the implementation, stochastic observation perturbations may be used during the analysis step.

### Deterministic Ensemble Kalman Filter

The Deterministic Ensemble Kalman Filter, or DEnKF, applies a deterministic update to the ensemble perturbations.

It avoids directly perturbing observations and may reduce sampling noise in some experiments.

### Ensemble Transform Kalman Filter

The Ensemble Transform Kalman Filter, or EnTKF, performs the analysis through a transformation in ensemble space.

This approach can be useful when:

- the model-state dimension is large,
- the ensemble is much smaller than the state dimension,
- and computations are more efficient in ensemble space.

### Ensemble Reduced Square Root Kalman Filter

The Ensemble Reduced Square Root Kalman Filter, or EnRSKF, applies a square-root update in a reduced ensemble representation.

Its availability and behavior depend on the selected ICESEE example and configuration.

## Ensemble Configuration

The ensemble represents uncertainty in the model state, parameters, forcing, or initial conditions.

### Ensemble Size

The ensemble size determines the number of model realizations advanced during each forecast cycle.

A larger ensemble can provide a better representation of uncertainty, but it also increases:

- runtime,
- memory consumption,
- model evaluations,
- inter-process communication,
- and storage requirements.

Small ensembles are useful for tutorials and debugging. Larger ensembles are generally more appropriate for high-dimensional ice-sheet experiments.

### Ensemble Initialization

The initial ensemble may be created by perturbing:

- model states,
- initial conditions,
- physical parameters,
- boundary conditions,
- forcing fields,
- or combinations of these quantities.

The perturbation method is defined by the selected example.

### Random Seed

The random seed controls stochastic components of the experiment.

These may include:

- ensemble perturbations,
- synthetic observation noise,
- parameter sampling,
- and initialization errors.

Using the same random seed improves reproducibility when the software environment and configuration remain unchanged.

### Inflation

Inflation increases the spread of the ensemble to compensate for underestimated forecast uncertainty.

Inflation may be applied:

- before assimilation,
- after assimilation,
- multiplicatively,
- additively,
- or through an adaptive method.

Too little inflation can produce ensemble collapse. Too much inflation can produce unstable or excessively uncertain estimates.

### Localization

Localization reduces the influence of spurious long-distance correlations caused by a limited ensemble size.

Localization may depend on:

- physical distance,
- grid connectivity,
- observation location,
- state-variable type,
- or a model-specific covariance structure.

Not every ICESEE example exposes localization controls through the interface.

## State and Parameter Estimation

ICESEE can estimate model states, uncertain parameters, or both.

### State Variables

State variables describe the evolving condition of the model.

For an ice-sheet application, these may include:

- ice thickness,
- surface elevation,
- horizontal velocity,
- temperature,
- damage,
- grounding-line indicators,
- or other model-dependent fields.

### Model Parameters

Parameters control model behavior but may not evolve through the same governing equations as state variables.

Examples include:

- bed elevation,
- basal friction,
- rheological parameters,
- flow-law coefficients,
- forcing parameters,
- and boundary-condition parameters.

The selected example determines which variables and parameters are included in the ensemble vector.

### State-Vector Construction

ICESEE may combine multiple fields into a single ensemble state vector.

The state vector can contain:

- state variables,
- estimated parameters,
- observed quantities,
- and unobserved quantities.

The ordering and dimensions of the state vector are defined by the application interface.

## Observation Configuration

Observations constrain the forecast ensemble during assimilation.

### Observed Variables

The selected example determines which variables can be observed.

Possible observations include:

- surface elevation,
- ice velocity,
- thickness,
- bed elevation,
- temperature,
- or synthetic model-state measurements.

### Observation Locations

Observations may be available:

- at all model nodes,
- on a regular spatial grid,
- at selected indices,
- along profiles,
- within grounded regions,
- or at externally supplied coordinates.

Sparse observations reduce data volume but may require careful localization and uncertainty treatment.

### Observation Schedule

The observation schedule determines when data are assimilated.

Observations may be available:

- at every time step,
- at fixed intervals,
- at selected snapshots,
- or at irregular times.

The assimilation schedule should be compatible with the model time step and available observation times.

### Observation Covariance

The observation covariance describes uncertainty in the measurements.

It may be specified using:

- a scalar variance,
- one variance per observed variable,
- a diagonal covariance matrix,
- or a more general covariance structure.

Observation uncertainty affects how strongly the analysis follows the data relative to the forecast ensemble.

### Synthetic Observations

Synthetic observations are generated from a known true state and are useful for:

- method development,
- verification,
- filter comparison,
- parameter-identification experiments,
- and observing-system simulation experiments.

Synthetic observations may include controlled random noise.

### Real Observations

Real-data workflows require observation files that are compatible with the selected model and example.

The workflow may need:

- coordinates,
- timestamps,
- variable names,
- units,
- uncertainty estimates,
- masks,
- and interpolation or mapping information.

## Physical Parameters

Physical parameters describe the scientific system represented by the model.

Depending on the selected application, they may include:

- density,
- gravity,
- accumulation,
- basal friction,
- viscosity,
- rheology,
- ocean forcing,
- atmospheric forcing,
- and boundary conditions.

Changing physical parameters can alter both the model forecast and the interpretation of the assimilation results.

## Modeling Parameters

Modeling parameters control the numerical experiment.

They may include:

- time step,
- final time,
- mesh resolution,
- solver tolerances,
- nonlinear iteration limits,
- checkpoint frequency,
- output interval,
- and model-specific configuration files.

For a first experiment, retain the values supplied by the selected preset.

## Output Configuration

The Output menu identifies the result configuration or reporting pathway used by the selected example.

Outputs may include:

- analyzed states,
- forecast states,
- ensemble means,
- ensemble members,
- parameter estimates,
- true-state comparisons,
- wrong-model comparisons,
- observation residuals,
- RMSE values,
- ensemble spread,
- and scientific plots.

Available outputs vary between examples.

## Report Generation

When report generation is enabled, ICESEE may run an additional post-processing workflow after the primary experiment.

A report may contain:

- experiment metadata,
- selected model,
- selected filter,
- ensemble size,
- observation settings,
- estimated variables,
- state trajectories,
- parameter trajectories,
- RMSE diagnostics,
- ensemble spread,
- and generated figures.

Report generation can increase the total runtime, particularly when large result files must be read and processed.

## Running an Experiment

Before launching an experiment, confirm the following:

1. The selected example is installed.
2. The required environment is available.
3. The preset is compatible with the model.
4. The filter is supported by the example.
5. The ensemble size is appropriate for the selected backend.
6. Observation files are available when required.
7. The output directory is writable.
8. Remote or HPC credentials are valid when applicable.

After reviewing the configuration, launch the workflow using the run control in the ICESEE interface.

## Monitoring Execution

The Run Log provides information about the active experiment.

Messages may include:

- configuration-file discovery,
- preset loading,
- model initialization,
- MPI initialization,
- ensemble distribution,
- forecast advancement,
- observation loading,
- analysis updates,
- checkpoint writing,
- output generation,
- report generation,
- and cleanup.

A successful workflow should progress from configuration loading to model execution, assimilation, result writing, and report generation without an unrecoverable error.

## Understanding Results

ICESEE results should be interpreted using both estimation accuracy and ensemble behavior.

### Ensemble Mean

The ensemble mean represents the central state or parameter estimate.

It can be compared with:

- observations,
- a known true state,
- an independent reference dataset,
- or a control simulation.

### Ensemble Spread

The ensemble spread describes uncertainty within the ensemble.

A spread that is too small may indicate:

- ensemble collapse,
- insufficient inflation,
- excessive observational influence,
- or underestimated model uncertainty.

A spread that is too large may indicate:

- excessive inflation,
- large initial perturbations,
- weak observational constraints,
- or model instability.

### Root-Mean-Square Error

Root-mean-square error, or RMSE, measures the difference between an estimate and a reference state.

RMSE may be computed for:

- the full state,
- individual variables,
- observed locations,
- unobserved locations,
- estimated parameters,
- or selected time snapshots.

RMSE should be interpreted together with ensemble spread and the spatial distribution of observations.

### Innovation

The innovation is the difference between an observation and its forecasted equivalent.

Large innovations may indicate:

- poor initialization,
- model bias,
- incorrect observation mapping,
- underestimated uncertainty,
- or inconsistent units.

### Parameter Estimates

Estimated parameters should be assessed for:

- convergence,
- physical plausibility,
- sensitivity to observations,
- sensitivity to the initial ensemble,
- and consistency across repeated experiments.

## Advanced Configuration

Advanced controls should be modified only after the default workflow runs successfully.

These controls may include:

- model-specific state-vector definitions,
- observation operators,
- covariance models,
- ensemble perturbation methods,
- localization parameters,
- inflation parameters,
- MPI distribution,
- checkpoint settings,
- and post-processing scripts.

Record all changes when comparing experiments.

## Reproducibility

For reproducible experiments, preserve:

- the ICESEE version,
- the model version,
- the preset,
- the full configuration,
- the random seed,
- the observation dataset,
- the execution environment,
- the number of MPI processes,
- and the generated logs.

Container images, locked software environments, and version-controlled configuration files can improve reproducibility across computing systems.

## Troubleshooting

### The selected example does not appear

Confirm that:

- the example exists in the ICESEE installation,
- its configuration files are present,
- its run script is discoverable,
- and the required model environment is installed.

Restart the application after adding a new example.

### The workflow fails before model execution

Inspect the Run Log for:

- missing configuration files,
- invalid paths,
- environment activation errors,
- missing Python packages,
- or unsupported parameter values.

### MPI initialization fails

Verify:

- the MPI installation,
- the selected launcher,
- environment variables,
- process counts,
- and compatibility between the model, Python packages, and MPI implementation.

Avoid mixing incompatible MPI libraries within the same environment.

### Observations are not loaded

Check:

- the observation-file path,
- variable names,
- data dimensions,
- timestamps,
- coordinates,
- masks,
- and expected units.

Confirm that the observation schedule overlaps the simulation period.

### The filter diverges

Possible remedies include:

- increasing the ensemble size,
- changing the initial perturbations,
- applying inflation,
- using localization,
- increasing observation uncertainty,
- reducing the assimilation interval,
- or reviewing the model configuration.

Filter divergence can also result from model bias or inconsistent observations.

### The ensemble spread collapses

Consider:

- increasing inflation,
- increasing model-error perturbations,
- increasing the ensemble size,
- reducing observational influence,
- or revising the covariance configuration.

### The experiment consumes too much memory

Reduce:

- ensemble size,
- state-vector size,
- output frequency,
- number of stored ensemble members,
- or report complexity.

For larger workflows, use a distributed HPC backend.

### The report is not generated

Confirm that:

- report generation is enabled,
- the primary workflow completed,
- the expected result file exists,
- the output directory is writable,
- and the reporting dependencies are installed.

### Remote execution fails

Verify:

- network access,
- SSH credentials,
- the remote hostname,
- the remote working directory,
- the scheduler configuration,
- and the remote environment.

Inspect both the CryoStack log and the remote scheduler output.

## Recommended Practices

For reliable experiments:

- Begin with a supported preset.
- Run a small local test before using HPC resources.
- Use a fixed random seed during debugging.
- Increase ensemble size gradually.
- Check observation units and dimensions.
- Compare ensemble spread with RMSE.
- Preserve logs and configuration files.
- Avoid changing many parameters simultaneously.
- Use version-controlled model and data assimilation settings.
- Use containers or reproducible environments when moving between systems.

## Related Documentation

- Read [Getting Started with ICESEE](getting_started) to run a first experiment.
- Review [ICESEE Resources](resources) for repositories, publications, software, and supporting documentation.
- Open <a href="../../documentation.html">CryoLauncher Documentation</a> for model execution without data assimilation.
- Launch [ICESEE](https://cryostack.eas.gatech.edu/icesee-gui/) through the CryoStack platform.

:::{raw} html
  </div>
</div>
:::

### Auto-config · Beta: prepare an ICESEE experiment

When enabled, expand **Auto-config · Beta** in Run settings. For example:

> Prepare Lorenz96 locally with ensemble size 20 and DEnKF.

The selected example identifies its forecast model through existing metadata.
Ensemble and filter changes populate the same controls you edit manually; for
example, “Use the same configuration with 50 ensemble members” or “Change only
the filter to EnKF”. Inspect the normal Run settings after applying.
Example availability does not establish runtime readiness, and the verified
Lorenz-96 cloud contract does not qualify other forecast workflows.

**Create plan** prepares a compact change preview: **Setting | Current |
Proposed | Source**. Changed settings are primary; important unchanged values
appear in a short retained summary. **From request** means explicitly requested,
**Suggested** means a deterministic adjustment from existing metadata or policy,
and **Retained** means a valid current value is intentionally unchanged.
Omitted settings stay as configured. Ambiguity requires clarification;
unsupported requests cannot be applied. A matching request reports **No changes
needed**.

**Apply to configuration** updates the existing controls and reports the number
of settings changed. It never submits or launches a workflow. Review the manual
controls and complete the ordinary validation and execution steps. A proposal
becomes stale if the controls change; create it again before applying. Manual
edits always remain authoritative.

You can refine the current controls with requests such as “Change the CPUs to
8” or “Keep everything but run this on PACE”. Each request uses the current
configuration, without conversation history. If a requested change invalidates
another setting, the preview includes a deterministic required adjustment or
asks for clarification; it does not silently discard the setting.

“Why can't I run this?” diagnoses configuration issues without changing controls.
“Fix my configuration” proposes a repair only when existing metadata supplies a
deterministic supported choice. It cannot repair institutional access, credentials,
licensing, or infrastructure. “Why is this Suggested?”, “What did you change?”,
and “Explain this configuration” provide compact read-only explanations from
proposal provenance and existing capability information. A stale proposal is
identified as stale rather than explained as current.

This is a bounded configuration aid, not an autonomous scientist or a general
chat service. It does not authorize execution, provision infrastructure, or
modify licensing. Existing identity, resource, scientific-parameter, and backend
checks remain authoritative; a prepared configuration is not proof that a run
is ready.
