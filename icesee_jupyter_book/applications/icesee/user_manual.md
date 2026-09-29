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

ICESEE, the Ice Sheet State and Parameter Estimator, is CryoStack's ensemble
data-assimilation application. It advances an ensemble of forecast-model runs,
assimilates observations with an ensemble Kalman filter, and estimates model
states and, where the example is set up for it, uncertain parameters.

This manual describes the ICESEE interface as deployed in CryoStack today: its
examples, its Local, Remote, and Cloud execution modes, the configuration
controls, and where results appear. ICESEE has its own runners and run
records; it does not go through CryoLauncher's execution pipeline.

## ICESEE workflow

1. Choose where to run: the **Local**, **Remote**, or **Cloud** tab.
2. Select an **Example**.
3. Choose the **Filter**, **Ensemble size**, and **Seed**.
4. Review the example's parameter sections and, if needed, its parallel
   settings.
5. Choose the **Output** and whether to **Generate report**.
6. Run: **Run** (Local), **Submit (Remote)**, or the Cloud review and launch.
7. Follow the **Run Log**, then inspect **Results**.

## Interface overview

**Run settings** (left):

| Control | What it does |
|---|---|
| **Local / Remote / Cloud** tabs | Where the experiment runs (see <a href="#execution-modes">Execution modes</a>). |
| **Example** | The ICESEE example to run (see <a href="#examples-and-maturity">Examples and maturity</a>). |
| **Preset** | The starting configuration. Only **Default** — the example's own `params.yaml` — is offered today. |
| **Filter** | EnKF, DEnKF, EnTKF, or EnRSKF. Written into the example's `filter_type`. |
| **Ensemble size** | Number of ensemble members, 1–200 (default 30). Written into `Nens`. |
| **Seed** | Random seed. Written into `seed`. |
| **Output** | Which result set the report reads: *true-wrong* (the demonstration output with the true and wrong-model states) or *EnKF*. |
| **Generate report** | After a successful Local run, execute the example's `read_results.ipynb` into the run folder. |
| **Parameter sections** | The example's `params.yaml` sections — `physical-parameters`, `modeling-parameters`, `enkf-parameters` — as editable fields. |
| **Auto-config · Beta** | An expandable request box, where the deployment enables it (see <a href="#auto-config-beta">Auto-config</a>). |

**Workspace** (right): **Runs**, **Files**, **Run Log**, and **Results**
tabs. The Runs tab lists your ICESEE run history; you only see your own runs.

## Examples and maturity

The **Example** menu labels each example with its current status:

| Example | Forecast model | Status in the menu | Local | Remote | Cloud |
|---|---|---|---|---|---|
| Lorenz-96 | Lorenz-96 (synthetic) | fully runnable locally | **Supported** | Available | **Supported** — the only verified cloud configuration (one process) |
| ISSM — ISMIP_Choi | ISSM | fully runnable in Remote | Not intended (needs MATLAB, ISSM, and MPI on the server) | **Supported** (ships a Slurm batch script) | Refused |
| Flowline — flowline_1d | 1-D flowline | **Under development** | Under development | Under development | Refused |
| Icepack — synthetic_ice_stream | Icepack | **Under development** | Under development | Under development | Refused |

Flowline and Icepack are visible so they can be developed and tested; they are
not at the maturity of Lorenz-96 or ISSM, and no end-to-end workflow is claimed
for them. ISSM needs MATLAB and ISSM on the Remote resource, which the
ICESEE-Spack environment provides; the ISSM example is too heavy for Local.

## Execution modes

### Local Mode

Local runs the example as a **single process on the CryoStack server**, in a
per-user run folder, with no scheduler, no MPI, and no remote connection. It
is intended for Lorenz-96 and small tests. Click **Run**; the Run Log streams
the output, and on success the report is generated if **Generate report** is
ticked.

### Remote Mode

Remote runs on an HPC system you have access to, under your own HPC identity,
through a Slurm batch job. The Remote tab contains:

- **Remote connection** — the same panel CryoLauncher uses: resource, your HPC
  username and remote working directory, the **Connection method** (CryoStack
  Connector recommended, Direct SSH from server, or Auto), **Authentication
  method**, **Open Connector...**, and **Check SSH Access**. See CryoLauncher's
  <a href="../icesheets/user_manual.html#configure-access-to-your-hpc-system">Configure
  access to your HPC system</a> for the full access guide; it applies here
  unchanged.
- **Execution backend** — **ICESEE-Spack** (default) or **ICESEE-Container**
  (image source **Docker Hub** or **AWS Registry**). ICESEE-Spack can check,
  and if requested install, the ICESEE-Spack environment on the resource.
- **Slurm resources** — job name, wall time, nodes, tasks, tasks per node,
  partition, memory, account, email, plus ICESEE's **MPI np** (total
  processes for the job, default 40) and **Model nprocs** (processes per
  forecast-model run, default 4).

**Submit (Remote)** submits the job. The Run Log toolbar offers **Test SSH**,
**Check status**, **Tail log**, and **Clear**; **Terminate job** stops a
running job; **Preview results** and **Download results** fetch the run's
outputs.

### Cloud Mode

Cloud mode runs ICESEE on your own AWS account (bring-your-own-AWS) on AWS
Batch, using the same infrastructure CryoLauncher's Cloud Environment panel
provides. Batch runs on a default **Fargate** compute mode. The EC2 options in
**Advanced cloud settings** exist for ICESEE too, but ICESEE's verified cloud
run is on Fargate; EC2 has not been validated for ICESEE — see
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
shows the field; an **ISSM** forecast model does, because that workflow uses
ISSM — and Launch stays blocked until a
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
**Lorenz-96** example at a single process (**Processes = 1** on the Review
card). Selecting a
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

3. In **Run settings**, select the **Cloud** tab.
4. If you have not connected an AWS account yet, follow
   [Connecting your AWS account](https://cryostack.eas.gatech.edu/docs/hpc_cloud.html#connecting-your-aws-account-byo-aws)
   now. CloudFormation onboarding happens in a separate browser tab — your
   AWS console — not inside CryoStack.
5. Return to CryoStack and click **Verify connection**; confirm the panel
   shows **● Connected**.
6. Click **Prepare cloud** and wait for **Account / Storage / Containers /
   Compute** to all read **Ready**.
7. Set **MPI np** to **1**. This field is on the **Remote** tab under
   **Slurm resources** (default 40), and the Cloud Review card shows it as
   **Processes**. One process is the only value CryoStack will let you
   launch today for ICESEE (see the verified contract above).
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


## Filters

The **Filter** menu selects the analysis scheme. All four are available for
every example; the example's own default is a good first choice.

- **EnKF** — the stochastic Ensemble Kalman Filter: updates each member with
  perturbed observations and an ensemble-estimated forecast covariance.
- **DEnKF** — the Deterministic EnKF: updates the ensemble mean and
  perturbations deterministically, without perturbing observations.
- **EnTKF** — the Ensemble Transform Kalman Filter: performs the analysis in
  ensemble space.
- **EnRSKF** — the Ensemble Reduced Square Root Kalman Filter: a square-root
  update in a reduced ensemble representation.

## Ensemble and experiment settings

The top-level controls write into the example's `enkf-parameters`:
**Ensemble size** → `Nens`, **Seed** → `seed`, **Filter** → `filter_type`.
Everything else the example defines is in its parameter sections, shown as
editable fields (lists and nested values as YAML text). For Lorenz-96, for
example, `enkf-parameters` contains:

| Setting | Meaning |
|---|---|
| `freq_obs`, `obs_start_time`, `obs_max_time` | when observations are assimilated |
| `observed_vars`, `sig_obs` | which variables are observed, and their error standard deviations |
| `vec_inputs`, `num_state_vars`, `num_param_vars` | the state (and parameter) vector |
| `state_estimation`, `parameter_estimation`, `joint_estimation` | what is estimated |
| `sig_Q`, `length_scale` | process-noise level and covariance length scale |
| `inflation_factor`, `localization_flag` | ensemble inflation and localization |
| `generate_synthetic_obs`, `generate_true_state` | synthetic truth and observations for a twin experiment |

Other examples define their own settings; the names shown are the ones the
example's `params.yaml` uses. Change one thing at a time, and keep the seed
fixed while comparing runs.

## Parallel settings

Two settings in `enkf-parameters` decide how an ICESEE run uses processes.
Each example ships a working combination; change them only for Remote runs
where you also set **MPI np** and **Model nprocs**.

**`execution_mode`** — how the data-assimilation workflow itself runs:

| Value | Mode | Meaning |
|---|---|---|
| `0` | serial | One process does all the work. For small models and testing the filter variants. |
| `1` | partial | Ensemble forecasts run in parallel; the analysis is computed on one process and shared. Suited to small and medium models. |
| `2` | full | Forecasts, file I/O, and the analysis step are all parallel. Intended for large models and datasets. |

**`parallel_flag`** — how the forecast model is run:

| Value | Meaning |
|---|---|
| `serial` | The forecast model runs without MPI. Used with `execution_mode: 0`. |
| `MPI_model` | The forecast model is itself MPI-parallel: each model run gets its own group of **Model nprocs** processes. Used with `execution_mode: 1` or `2`. |
| `MPI` | Listed in the menu, but the current ICESEE version has no separate code path for it: serial mode rejects it and the parallel modes only parallelize with `MPI_model`. Use `serial` or `MPI_model`. |

The shipped defaults are `execution_mode: 0` with `serial` for Lorenz-96 and
Flowline, and `execution_mode: 1` with `MPI_model` for ISSM and Icepack.
`execution_flag` (0 default, 1 sequential, 2 even distribution) controls how
ensemble members are assigned to process groups; keep the example's value
unless you know you need another.

These settings only take effect with several processes: **Local** always runs
one process, and **Cloud** is limited to one process today. On **Remote**,
**MPI np** sets the total number of processes and **Model nprocs** the
processes per model run.

## Running and monitoring

| Mode | Start | Monitor |
|---|---|---|
| Local | **Run** | The Run Log streams output until the run ends. |
| Remote | **Submit (Remote)** | **Check status**, **Tail log**; **Terminate job** stops it. The job keeps running if you close the browser. |
| Cloud | **Review & Launch** → **Launch cloud run** | **Check status** and **Logs hint** in the Run Log toolbar; **Terminate cloud job** stops it. ICESEE does not poll AWS in the background. |

The Run Log shows the parameter file used, the runner, environment
activation, ensemble and forecast progress, analysis steps, report
generation, warnings, and errors — it is the first place to look when a run
fails.

## Results and reports

Select a run in the **Runs** tab and open **Results**. ICESEE shows the
figures the run produced (PNG files from its `figures/` or `results/` folder)
and lists its HDF5 result files. For Remote runs, **Preview results** fetches
the outputs first; **Download results** downloads them. Cloud outputs are
synchronized from S3 when you open the run.

When **Generate report** is ticked, a successful Local run executes the
example's `read_results.ipynb` into the run folder, reading the result set
chosen in **Output** (`results/<output>-<model>.h5`). Report generation adds
runtime and needs the reporting packages in the environment.

Each run folder keeps the `params.yaml` it ran with, and the run record stores
the data-assimilation identity — example, forecast model, filter, ensemble
size, seed, observation and estimation settings, and parallel settings — so a
run can be understood and repeated later.

## Auto-config · Beta

Where the deployment enables it, expand **Auto-config · Beta** in Run settings
and describe the experiment, for example:

> Prepare Lorenz96 locally with 20 ensemble members and DEnKF.

Auto-config uses the same deterministic, domain-constrained rules as
CryoLauncher's — not a general-purpose language model. It recognizes the
registered examples and their forecast models, the execution mode, filter,
ensemble size, CPU count, and resource settings, starting from the current
controls. Requests such as "Change the ensemble size to 60 but keep the rest
of my configuration" or "Change only the filter to EnKF and use 8 CPUs" refine
the current configuration. Anything it cannot interpret, including
contradictions and requests to submit, is reported rather than guessed.

**Create plan** shows **Setting | Current | Proposed | Source** (From request /
Suggested / Retained); **Apply to configuration** updates the controls only —
it never runs anything. A proposal is rejected if the controls changed after
it was created. Diagnosis ("Why can't I run this?"), conservative repair
("Fix my configuration"), and explanations ("What did you change?") work as in
<a href="../icesheets/user_manual.html#auto-config-beta">CryoLauncher's
Auto-config</a>. Example availability does not establish runtime readiness:
the verified Lorenz-96 cloud contract does not qualify other forecast
workflows.

## Troubleshooting

:::{raw} html
<div class="cryostack-troubleshooting">

  <details>
    <summary>Cloud: Launch is blocked for my example</summary>
    <p>
      Only Lorenz-96 with one process is verified on Cloud. Select Lorenz-96,
      and set <b>MPI np</b> to <b>1</b> on the Remote tab under
      <b>Slurm resources</b> — the Review card shows it as <b>Processes</b>.
    </p>
  </details>

  <details>
    <summary>A run fails with "Invalid parallel flag"</summary>
    <p>
      <code>parallel_flag: MPI</code> has no separate code path in the current
      ICESEE version. Use <code>serial</code> with
      <code>execution_mode: 0</code>, or <code>MPI_model</code> with
      <code>execution_mode: 1</code> or <code>2</code>.
    </p>
  </details>

  <details>
    <summary>The workflow fails before the model runs</summary>
    <p>
      Read the Run Log for a missing file, an environment-activation error, a
      missing package, or an invalid parameter value. On Remote, confirm
      <b>Check SSH Access</b> reads <b>Verified</b> and, for ICESEE-Spack, that
      the environment is installed.
    </p>
  </details>

  <details>
    <summary>An ISSM, Flowline, or Icepack example fails in Local</summary>
    <p>
      Local runs one process on the CryoStack server. ISSM is a Remote
      example, and Flowline and Icepack are under development; use Lorenz-96
      for Local runs.
    </p>
  </details>

  <details>
    <summary>The report is not generated</summary>
    <p>
      Reports run only after a successful Local run with <b>Generate
      report</b> ticked, and need the result file named by <b>Output</b>
      (<code>results/&lt;output&gt;-&lt;model&gt;.h5</code>) and the notebook
      runner in the environment.
    </p>
  </details>

  <details>
    <summary>The filter diverges or the ensemble spread collapses</summary>
    <p>
      Try a larger <b>Ensemble size</b>, an <code>inflation_factor</code>
      above 1, localization where the example supports it, or a larger
      observation error (<code>sig_obs</code>). Change one setting at a time
      with a fixed seed.
    </p>
  </details>

  <details>
    <summary>Remote execution fails</summary>
    <p>
      Check network access (VPN), SSH access, the remote working directory,
      the Slurm account and partition, and the remote environment. Use
      <b>Tail log</b> for the job's own output.
    </p>
  </details>

</div>
:::

## Related documentation

- Read [Getting Started with ICESEE](getting_started) to run a first experiment.
- Review [ICESEE Resources](resources) for repositories, publications, software, and supporting documentation.
- Open <a href="../icesheets/getting_started.html">CryoLauncher</a> for model runs without data assimilation.
- Launch [ICESEE](https://cryostack.eas.gatech.edu/icesee-gui/) through the CryoStack platform.

:::{raw} html
  </div>
</div>
:::
