# ICESEE Resources

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

    <h1>ICESEE Resources</h1>

    <p>
      Explore ICESEE repositories, scientific publications, supported models,
      software environments, datasets, computing technologies, and community
      resources.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary" href="/icesee-gui/">
        Open ICESEE
      </a>

      <a class="cryostack-btn secondary" href="getting_started.html">
        Getting Started
      </a>

      <a class="cryostack-btn secondary" href="user_manual.html">
        User Manual
      </a>
    </div>

  </section>

  <div class="cryostack-app-doc-content">
:::

ICESEE combines ensemble data assimilation, numerical modeling, scientific computing, and reproducible software environments. The resources on this page support users who want to run experiments, understand the underlying methods, develop new model interfaces, or contribute to the project.

## ICESEE Software

### ICESEE Repository

The ICESEE source repository contains the data assimilation framework, model interfaces, examples, configuration files, utilities, and reporting tools.

The repository is the primary resource for:

- source code,
- installation instructions,
- examples,
- issue tracking,
- development history,
- and software releases.

### CryoStack

CryoStack provides the web platform through which ICESEE workflows can be configured, launched, monitored, and analyzed.

CryoStack connects scientific applications with:

- local computing environments,
- remote workstations,
- HPC clusters,
- cloud infrastructure,
- container environments,
- and browser-based interfaces.

### CryoLauncher

CryoLauncher supports model-only simulation workflows within CryoStack.

Use CryoLauncher when you need to:

- configure an ice-sheet model,
- launch a simulation,
- monitor a remote job,
- retrieve outputs,
- or run a model without ensemble data assimilation.

### ICESEE Containers

The ICESEE container resources provide reproducible software environments for supported models and scientific dependencies.

Containerized environments can reduce differences between:

- local workstations,
- institutional servers,
- HPC systems,
- and cloud resources.

### ICESEE Spack

The ICESEE Spack repository supports reproducible builds of scientific software stacks.

It may include configurations for:

- MPI,
- PETSc,
- HDF5,
- Firedrake,
- Icepack,
- ISSM dependencies,
- compilers,
- and supporting libraries.

## Supported Models

ICESEE is designed to connect multiple numerical models to a common ensemble data assimilation workflow.

### Lorenz-96

Lorenz-96 is a low-dimensional nonlinear dynamical system commonly used to study data assimilation methods.

Within ICESEE, it is useful for:

- tutorials,
- filter verification,
- regression testing,
- ensemble experiments,
- and rapid method development.

Because it is computationally lightweight, Lorenz-96 is the recommended starting point for new users.

### ISSM

The Ice-sheet and Sea-level System Model, or ISSM, is a large-scale ice-sheet modeling framework.

ICESEE can use ISSM for experiments involving:

- ice thickness,
- surface elevation,
- velocity,
- bed elevation,
- basal parameters,
- and other model states or uncertain parameters.

ISSM workflows may require external MATLAB support, compiled numerical libraries, MPI, and access to substantial computing resources.

Official documentation:

[ISSM Documentation](https://issm.jpl.nasa.gov/)

### Icepack

Icepack is a Python package for modeling glacier and ice-sheet flow.

It is built using Firedrake and supports finite-element simulations of ice dynamics.

ICESEE can use Icepack for:

- ensemble forecasts,
- state estimation,
- parameter estimation,
- synthetic experiments,
- and distributed model execution.

Official documentation:

[Icepack Documentation](https://icepack.github.io/)

### Firedrake

Firedrake is an automated system for solving partial differential equations using the finite-element method.

It provides much of the computational foundation used by Icepack.

Official documentation:

[Firedrake Documentation](https://www.firedrakeproject.org/)

### One-Dimensional Flowline Models

Flowline examples provide an intermediate level of complexity between Lorenz-96 and full three-dimensional ice-sheet models.

They are useful for:

- state-estimation studies,
- parameter-estimation studies,
- observation-network experiments,
- algorithm testing,
- and educational demonstrations.

## Data Assimilation References

### Ensemble Kalman Filter

The Ensemble Kalman Filter uses an ensemble of model realizations to approximate forecast uncertainty and update model estimates using observations.

Important topics include:

- forecast ensembles,
- analysis updates,
- observation operators,
- covariance estimation,
- inflation,
- localization,
- and ensemble sampling error.

### Deterministic Ensemble Methods

Deterministic ensemble filters avoid perturbing observations during the analysis step.

They may improve reproducibility and reduce sampling noise in some applications.

Relevant methods include:

- Deterministic Ensemble Kalman Filter,
- Ensemble Transform Kalman Filter,
- Ensemble Square Root Filter,
- and reduced-space square-root methods.

### State Estimation

State estimation uses observations to improve estimates of evolving model variables.

For ice-sheet applications, this may involve:

- thickness,
- surface elevation,
- velocity,
- temperature,
- grounding-line position,
- or other model fields.

### Parameter Estimation

Parameter estimation uses observations to constrain uncertain model inputs.

Examples include:

- bed elevation,
- basal friction,
- rheological coefficients,
- forcing parameters,
- and boundary-condition parameters.

### Joint State and Parameter Estimation

ICESEE can represent states and parameters within the same ensemble vector.

This enables observations to update both the evolving model state and selected uncertain parameters.

## Observation Resources

ICESEE workflows may use synthetic observations, model-generated truth fields, or observational datasets.

### Synthetic Observations

Synthetic observations are useful for:

- verifying an algorithm,
- comparing filters,
- testing observation schedules,
- evaluating parameter recovery,
- and measuring errors against a known true state.

### BedMachine

BedMachine products provide mapped ice-sheet geometry and bed information.

Potential variables include:

- surface elevation,
- ice thickness,
- bed elevation,
- masks,
- and grounding information.

Users should consult the relevant dataset documentation, version information, and usage requirements before incorporating BedMachine products into an experiment.

### NASA MEaSUREs

NASA MEaSUREs products include observational datasets related to ice-sheet velocity, elevation, grounding lines, and other cryospheric quantities.

These products may support experiments involving:

- velocity assimilation,
- geometry constraints,
- validation,
- and comparison with satellite observations.

### User-Provided Observations

Custom datasets should define:

- variable names,
- units,
- spatial coordinates,
- timestamps,
- uncertainty estimates,
- missing-data values,
- and model-to-observation mapping.

Users should verify that observation data are compatible with the selected model grid and state-vector definition.

## Computing Technologies

### Message Passing Interface

MPI supports distributed-memory parallelism across processes and compute nodes.

ICESEE may use MPI to:

- distribute ensemble members,
- communicate model states,
- gather forecast results,
- perform assimilation updates,
- and coordinate parallel workflows.

The MPI implementation used by the Python environment and numerical model must be compatible.

### PETSc

PETSc provides scalable solvers, parallel vectors and matrices, nonlinear methods, time integration, and data-management tools.

PETSc is used directly or indirectly by several scientific applications within the ICESEE software stack.

Official documentation:

[PETSc Documentation](https://petsc.org/)

### HDF5

HDF5 provides structured storage for large scientific datasets.

ICESEE workflows may use HDF5 for:

- checkpoints,
- ensemble states,
- model fields,
- diagnostics,
- and generated results.

Parallel HDF5 support may be required for distributed workflows.

Official documentation:

[HDF5 Documentation](https://www.hdfgroup.org/solutions/hdf5/)

### Slurm

Slurm is a workload manager commonly used on HPC clusters.

CryoStack and ICESEE may use Slurm to:

- submit jobs,
- request nodes and processors,
- monitor job states,
- cancel jobs,
- and retrieve scheduler output.

Official documentation:

[Slurm Documentation](https://slurm.schedmd.com/documentation.html)

### Spack

Spack is a package manager for scientific software.

The ICESEE software stack may use Spack to build and manage:

- MPI libraries,
- PETSc,
- HDF5,
- compilers,
- numerical libraries,
- and other scientific dependencies.

Official documentation:

[Spack Documentation](https://spack.readthedocs.io/)

### Containers

Containers provide portable scientific environments that package software and dependencies together.

CryoStack deployments may use:

- Docker,
- Apptainer,
- or Singularity-compatible images.

Containers are particularly useful when moving a workflow between local, HPC, and cloud systems.

### Docker

Docker is commonly used for building, testing, and deploying application environments.

Official documentation:

[Docker Documentation](https://docs.docker.com/)

### Apptainer

Apptainer supports container execution on HPC systems where privileged Docker services are not available.

Official documentation:

[Apptainer Documentation](https://apptainer.org/docs/)

## CryoStack Documentation

CryoStack documentation provides information about the larger platform, deployment structure, supported applications, and computing backends.

Available application documentation includes:

- CryoLauncher Getting Started,
- CryoLauncher User Manual,
- CryoLauncher Resources,
- ICESEE Getting Started,
- ICESEE User Manual,
- and ICESEE Resources.

Return to the main platform documentation:

[CryoStack Documentation](/documentation.html)

## Developer Resources

Developers extending ICESEE should become familiar with:

- the example discovery mechanism,
- configuration-file structure,
- model interfaces,
- state-vector construction,
- observation operators,
- ensemble distribution,
- filter implementations,
- result readers,
- and reporting utilities.

A new model integration should clearly define:

1. how the model is initialized,
2. how the state vector is created,
3. how ensemble members are generated,
4. how the forecast model is executed,
5. how observations are mapped into model space,
6. how updated states are returned to the model,
7. and how results are stored and analyzed.

## Example Configurations

Example configurations provide tested starting points for supported applications.

They may define:

- physical parameters,
- model parameters,
- filter settings,
- ensemble settings,
- observations,
- execution controls,
- and output behavior.

When creating a new configuration:

- begin from a working example,
- change one section at a time,
- preserve the original configuration,
- use descriptive filenames,
- and record the corresponding software version.

## Reproducibility Resources

A reproducible ICESEE experiment should preserve:

- source-code revisions,
- Git submodule revisions,
- configuration files,
- container or environment definitions,
- input datasets,
- random seeds,
- scheduler scripts,
- execution logs,
- and generated results.

Useful reproducibility mechanisms include:

- Git,
- container images,
- Spack environments,
- Conda environments,
- tagged software releases,
- Zenodo archives,
- and machine-readable citation metadata.

## Citation

Users should cite ICESEE and any numerical models, software libraries, and observational datasets used in their work.

A complete citation record may include:

- the ICESEE software citation,
- the CryoStack or deployment citation,
- the selected numerical model,
- the data assimilation method,
- the observational dataset,
- and the software release or archived DOI.

Consult the repository's `CITATION.cff` file and project publications for the preferred citation format.

## Contributing

Contributions may include:

- bug fixes,
- documentation improvements,
- new model interfaces,
- new data assimilation methods,
- new examples,
- new reporting tools,
- tests,
- container improvements,
- and deployment enhancements.

Before contributing:

1. review existing issues,
2. create a focused branch,
3. preserve existing behavior,
4. add tests where appropriate,
5. update documentation,
6. and describe the scientific or technical motivation clearly.

## Support

When reporting a problem, include:

- the selected example,
- the execution mode,
- the filter,
- the ensemble size,
- the configuration file,
- the ICESEE revision,
- the model revision,
- relevant logs,
- and the computing environment.

For reproducible issues, provide the smallest configuration that demonstrates the problem.

## Related Documentation

- Read [Getting Started with ICESEE](getting_started) to run a first experiment.
- Use the [ICESEE User Manual](user_manual) for detailed configuration and troubleshooting.
- Open [ICESEE](https://cryostack.eas.gatech.edu/icesee-gui/) through CryoStack.
- Return to the main [CryoStack Documentation](/documentation.html).

:::{raw} html
  </div>
</div>
:::