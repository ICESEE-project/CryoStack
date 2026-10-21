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

The page follows the order of the decisions you make; the numbered bar at the
top shows where you are, what needs attention, and the state of the active
run. Click a step to jump to it.

1. **Mode** — where the experiment runs: **Local**, **Remote HPC**, or
   **Cloud**. This comes first because it decides the rest of the setup.
2. **Experiment** — the **Example**, and its **Filter**, **Ensemble size**
   and **Seed** (filled with the example's own values when you choose it).
3. **Environment & resources** — the settings of the chosen mode.
4. **Scientific parameters** — every key of the example's `params.yaml`;
   **Edit params.yaml** opens the same configuration in the Editor.
5. **Review & launch** — a summary of what will run and where, any problems
   to fix, and one launch action (**Launch run**, **Submit to cluster**, or
   **Review cloud launch**).
6. **Monitor** — after launch the same card shows the run: its state,
   elapsed time, stage and progress, and **Cancel run**.
7. **Results** — the example's scientific figures for the selected run.

## Interface overview

**Left column** — the five numbered cards above. Problems are listed in
Review & launch next to what causes them (for example "Remote connection:
enter your HPC username"), and the launch action stays disabled until they
are fixed. A double click never starts two runs.

**Workspace** (right) — everything in it follows the **selected run**, shown
in the bar at its top:

| Tab | What it shows |
|---|---|
| **Run** | Your run history (newest first; only your runs), and for the selected run its lifecycle (preparing → submitted → queued → running → completed / failed / cancelled, with times), identifiers, mode and backend, output folder, command, and provenance. Actions: **Open results**, **View logs**, **Check status** (Remote / Cloud), **Reuse configuration**, **Reproducibility bundle**, **Cancel run** / **Delete run** (both ask for confirmation). |
| **Files** | The run folder: filter, preview text, figures and HDF5 contents (each dataset with its data-assimilation role), download a file or all outputs. |
| **Editor** | The experiment's files for your *next* run (see <a href="#editing-the-configuration">Editing the configuration</a>). |
| **Logs** | **Run output** — the model's output, updated live while it runs; **Launcher activity** — connection checks, submissions and status replies. |
| **Results** | The example's scientific figures and tables (see <a href="#results-and-reports">Results and reports</a>). |

| Control | What it does |
|---|---|
| **Example** | The ICESEE example to run (see <a href="#examples-and-maturity">Examples and maturity</a>). Shows whether it can run in the chosen mode. |
| **Filter** | EnKF, DEnKF, EnTKF, or EnRSKF. Written into the example's `filter_type`. |
| **Ensemble size** | Number of ensemble members. Written into `Nens`. |
| **Seed** | Random seed. Written into `seed`. |
| **Preset** | The starting configuration. Only **Default** — the example's own `params.yaml` — is offered today. |
| **Auto-config · Beta** | An expandable request box, where the deployment enables it (see <a href="#auto-config-beta">Auto-config</a>). |

## Examples and maturity

In the **Experiment** card, choose the **Application** (the forecast model:
Lorenz-96, ISSM, Icepack or Flowline), then one of its **Examples**. Every
example that ICESEE couples to that application is listed. The launcher
reads them from the ICESEE repository (`ICESEE/applications/<model>_model/examples/`),
and the application's reference example is marked *(default)*. Selecting
an example loads its own `params.yaml` into the form. An example counts as
coupled when it has a `params.yaml` and the application's data-assimilation
driver (`run_da_<model>.py`); notebook-only folders are not listed.

| Application | Coupled examples |
|---|---|
| Lorenz-96 | lorenz96 |
| ISSM | ISMIP_Choi (default), basal_friction_variation, ISMIP |
| Icepack | synthetic_ice_stream (default), idealized_pig |
| Flowline | flowline_1d |

A new example added to the ICESEE repository under an existing application,
with a `params.yaml` and that driver, appears in the list without any change
to the launcher. Add a `results.yaml` to give it result views (see
[Results and reports](#results-and-reports)); without one, Results reports
*no result views*. Runs recorded under the older example names (for example
"ISSM (fully runable in Remote)") still resolve to their example.

The table below covers the reference examples. The other examples of an
application share its environment requirements. Remote ISSM submissions use
`run_job_spack.sbatch` when the example ships one.

| Example | Forecast model | Local | Remote | Cloud | Results views |
|---|---|---|---|---|---|
| Lorenz-96 | Lorenz-96 (synthetic) | **Supported** (launcher Python; ICESEE container with `execution_mode` 0 or 1) | Available | **Supported** (1–2 processes) | State estimation (x, y, z), assimilation error |
| Icepack — synthetic_ice_stream | Icepack | **Supported in the ICESEE container** (Firedrake) | Available | **Supported** (1–2 processes, staged with this launcher's ICESEE) | Ensemble profiles, error maps, thickness/velocity maps, transects, SMB along x, truth vs. wrong, error tables, assimilation error |
| ISSM — ISMIP_Choi | ISSM | Not available (needs MATLAB, ISSM and MPI) | **Supported** (ships a Slurm batch script) | Refused | Five-field profile time series, assimilation error |
| Flowline — flowline_1d | 1-D flowline | **Under development** — the run finishes but its result is not usable yet | Under development | Refused | None (declared unsupported) |

ISSM needs MATLAB and ISSM on the Remote resource, which the ICESEE-Spack
environment provides; it is too heavy for Local.

Flowline runs in `execution_mode: 3` and finishes, but the current ICESEE
example produces a true state that does not change over time and an initial
ensemble with no spread, so the first analysis diverges. In
`execution_mode: 2` it still stops with an `IndexError` while generating the
synthetic observations. Results stays unavailable for Flowline until the
example is fixed in ICESEE.

## Execution modes

### Local Mode

Local runs the example on the **CryoStack server**, in a per-user run folder,
with no scheduler and no remote connection. Choose where it runs under
**Environment & resources**:

- **Launcher Python** — one process in the launcher's own Python. Enough for
  Lorenz-96 and small tests.
- **ICESEE container** — the ICESEE runtime image (the one Remote and Cloud
  runs use) on the server's Docker, with **MPI processes** (`mpirun -np`) and
  **Model processes** (`--model_nprocs`). Needed for Icepack (Firedrake). The
  container has no network access and can only write the run folder.

The card says which environments can run the selected example and switches
to one that can. **Launch run** starts the run in the background: the page
stays usable, the Logs tab streams the output, and closing or reloading the
page does not stop the run — it is shown again, with its state, when you
come back.

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

**Submit to cluster** submits the job (after checking the connection and
Slurm fields). The run appears in the Workspace as *submitted*; **Check
status** in the Run tab asks Slurm for its state, **Logs › Launcher
activity** has **Check SSH Access** and **Tail log**, and **Cancel run**
cancels the job. **Fetch outputs from cluster** (Results tab) copies the
job's outputs into the run folder so its results can be drawn.

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
- **Review cloud launch** (in Review & launch), which opens the cloud review
  — the run's forecast model, filter, ensemble size, and process count — and
  only enables **Launch cloud run** when the configuration is inside
  CryoStack's verified runtime contract;
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

A cloud run uses the tested container image CryoLauncher's cloud runs use,
with this launcher's own ICESEE code, example and `params.yaml` installed in
it for the run (the same code a Local run uses). Two examples have a cloud
runtime: **Lorenz-96** and **Icepack — synthetic_ice_stream**. Set **MPI
processes** in the Cloud card (1–2, the cloud task's vCPUs; Icepack defaults
to 2). The image's HDF5 has no parallel I/O, so a cloud run uses
`execution_mode` 1 with several processes and 0 with one; the submission
log lists any change it made. Other examples, or more processes, are refused
at Review with the reason. See the
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
     execution_mode: 0
   ```

3. In **Run settings**, select the **Cloud** tab.
4. If you have not connected an AWS account yet, follow
   [Connecting your AWS account](https://cryostack.eas.gatech.edu/docs/hpc_cloud.html#connecting-your-aws-account-byo-aws)
   now. CloudFormation onboarding happens in a separate browser tab — your
   AWS console — not inside CryoStack.
5. Return to CryoStack and click **Verify connection**; confirm the panel
   shows **● Connected**.
6. Click **Prepare cloud** and wait for **Account / Storage / Containers /
   Compute** to all read **Ready**. While a check or Prepare runs, the rows
   are blue with a spinning ring (**Checking…** / **Preparing…**); green
   means **Ready** or **Connected**, amber means something still needs you
   (**Not prepared**, **Not verified**), and red means the step failed (the
   reason is in **Logs › Launcher activity**). Once every row is Ready,
   **RUN ESTIMATE** appears with the expected runtime, the resources (the
   job's vCPU and memory) and the estimated cost, and the card's
   **Review & Launch** button. The runtime comes from your earlier completed
   cloud runs of the same example; before the first one the runtime reads
   *Not known yet* and the cost is shown per hour.
7. Set **MPI processes** in the Cloud card (1 or 2; the Remote tab's
   **MPI np** is not used for Cloud). The review shows it as **Processes**.
8. Click **Review & Launch** in the Cloud card (or **Review cloud launch** in
   Review & launch; both open the same review). Confirm the cloud review reads
   **ICESEE runtime: Ready** and **Parallel mode: 1 of 2 vCPUs** (or 2 of 2)
   — this is CryoStack's own preflight check, not a cosmetic label. After
   updating CryoStack, run **Prepare cloud** once so AWS gets the current
   ICESEE job definition.
9. Click **Launch cloud run**.
10. ICESEE does not poll AWS in the background — click **Check status** in
    the Workspace **Run** tab whenever you want to know whether the job has
    finished. The run's state (queued, running, completed) updates, and the
    AWS Batch reply (e.g. `RUNNABLE`, `RUNNING`, `SUCCEEDED`) is in
    **Logs › Launcher activity**.
11. Once the run is completed, open **Results**. Selecting a cloud run
    synchronizes its S3 outputs into the run folder in the background; the
    figures are the same ones a local run of the example shows.
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
| `2` | full | Forecasts, file I/O, and the analysis step are all parallel. Intended for large models and datasets. Writes through parallel HDF5. |
| `3` | spatially distributed | Each model state is split across processes and the ensemble is kept as checkpoints. Only examples that ship a mode-3 runner (`mode3_runner.py`) support it. |

**`parallel_flag`** is no longer read by ICESEE: the execution mode alone
decides how the forecast model runs. Older `params.yaml` files that still
set it (ISMIP_Choi does) run unchanged. A Remote submission without it adds
`parallel_flag` (`serial` for `execution_mode: 0`, otherwise `MPI_model`), so
ICESEE-Spack installs older than October 2026, which still read it, keep
working.

The shipped defaults are `execution_mode: 2` for Lorenz-96, `1` for
Icepack and ISSM, and `3` for Flowline.
`execution_flag` (0 default, 1 sequential, 2 even distribution) controls how
ensemble members are assigned to process groups; keep the example's value
unless you know you need another.

These settings only take effect with several processes: **Launcher Python**
runs one process, and **Cloud** is limited to one process today. The
**ICESEE container** cannot use `execution_mode: 2`, because its HDF5 library
has no parallel I/O; use `0` with one MPI process, or `1`. Cloud runs use the
ICESEE inside the Cloud image, which is verified only in serial mode, so a
Cloud submission sets `execution_mode: 0` and `parallel_flag: serial` and
says so in the run log. On **Remote**,
**MPI np** sets the total number of processes and **Model nprocs** the
processes per model run.

## Running and monitoring

| Mode | Start | Monitor | Stop |
|---|---|---|---|
| Local | **Launch run** | State, elapsed time, stage and assimilation step in Review & launch and the top bar; live output in **Logs**. | **Cancel run** |
| Remote | **Submit to cluster** | While the selected run is active, its state is checked with Slurm every minute (over the SSH access configured on the Remote tab); after three failed checks they pause and **Check status** (Run tab) resumes them. **Tail log** in Logs › Launcher activity. The job keeps running if you close the browser. | **Cancel run** (`scancel`) |
| Cloud | **Review cloud launch** → **Launch** in the cloud review | **Check status** (Run tab) updates the state from AWS Batch; **Logs hint**. ICESEE does not poll AWS in the background. | **Cancel run** (terminates the Batch job) |

Every run moves through the same states — *preparing*, *submitted*,
*queued*, *running*, then *completed*, *failed* or *cancelled* — whichever
backend runs it; the Run tab lists each change with its time. A local run
that printed an error is reported as failed even when the process exited
normally, with the error line; when the outputs were written and only the
shutdown printed an error (as MPI/Firedrake sometimes do), the run is
completed with a note.

The run output shows the parameter file used, the runner, ensemble and
forecast progress, analysis steps, warnings and errors — it is the first
place to look when a run fails.

### Getting from a run to its logs and results

Once a run starts, **Review & launch** becomes the active-run panel. Its
**View logs** button opens the **Logs** tab of the Workspace on the right
for that run, and **Open results** (shown as **Results** until the run
completes) opens its **Results** tab. Both select the run if it is not
already selected, refresh the tab, and scroll the page to the Workspace,
which is briefly highlighted. On narrow screens, where the Workspace sits
below the configuration, this is how you get there.

The same applies to every button that sends you to the Workspace from
elsewhere: **Open results** and **View logs** on the Run tab, **Edit
params.yaml** (Scientific parameters) and **Edit my plotting code**
(Results), which open the **Editor**, the **Monitor** and **Results** steps
of the step bar, and launch messages that point to *Logs › Launcher
activity*.

### The life of a run

1. **Review & launch** checks the configuration; **Launch run** (Local),
   **Submit to cluster** (Remote) or the cloud review's **Launch** (Cloud)
   starts it. The run gets its own folder in your workspace with the
   `params.yaml` it runs with, a copy of the example, and
   `provenance.json`.
2. While it runs, the active-run panel and the top bar show its state and
   progress, and **View logs** shows the model output.
3. When it finishes (or fails), its outputs stay in its run folder. Remote
   and Cloud outputs are fetched to the launcher when you open **Results**.
4. **Open results** draws the example's figures from those outputs, or
   your own plotting code's figures (see *Your own plotting code*).
5. **Reuse configuration** (Run tab) loads the run's settings into the form
   for the next run.

## Editing the configuration

The **Editor** tab works on the experiment you are configuring, for your next
run:

| File | Role | What you can do |
|---|---|---|
| `params.yaml` | Configuration | The current run configuration — the same values as the form. **Apply to configuration** validates it and updates the form. |
| Other YAML, JSON, CSV, TXT, EXP files | Inputs | Edit and **Save draft**; your draft replaces the shipped file in your **Local** runs of this example (Remote and Cloud runs receive `params.yaml` only — Review & launch says so). **Reset to example** discards the draft. |
| Python, MATLAB, shell files | Code | Read-only: runs execute on shared infrastructure, so code is never taken from the browser. |
| Notebooks, README | Reference | Read-only. |

**Validate** checks YAML/JSON syntax and, for `params.yaml`, what ICESEE
needs: the example's sections, number and true/false types, a filter ICESEE
knows, a positive ensemble size and observation frequency, an observation
window that starts before it ends, observed variables that are state
variables. Problems are listed with their line; nothing is applied or saved
while there is an error. Unsaved changes are marked, and switching files
asks you to apply, save or discard them first. Files over 512 KB are shown
read-only.

## Results and reports

Select a run and open **Results**. The launcher finds the run's outputs,
reads the example's `results.yaml` (which lists the result views the example
supports), and draws the figures its `read_results.ipynb` draws — the same
code: the notebooks now call the ICESEE post-processing module the launcher
uses. Each figure says which notebook cell it reproduces; views that are not
in the notebook are marked *supplementary*. Views with options (a grid point,
a time step, the years to compare) have **Update figure** and **Notebook
defaults**; click a figure to enlarge it, **Download PNG** to save it.

If something is missing, Results says what: *waiting for outputs* while the
run is going, *no outputs* when it failed or nothing was fetched, *no result
views* for an example without a contract, *unsupported* for an example
that declares it cannot produce results yet (Flowline), or which file is
missing or damaged. Icepack maps need the mesh coordinates the ICESEE
container exports after the run; without them the time-series views still
work. Runs in `execution_mode: 3` that keep no ensemble file are read from
their checkpoints (`_mode3_state_history/`); by default ICESEE keeps only the
newest two, so the figures leave the other time steps blank and say so. Set
`checkpoint_keep_last: 0` to keep every step. Figures are drawn on the
server in a separate process with time and memory limits, and cached in the
run folder.

### Your own plotting code

To change a figure or add your own, open **Results** for a run and choose
**Copy plotting code to my workspace**. This copies the example's
`results.yaml` and its plotting modules (for example `lorenz.py` and the
shared `common.py`) into your own workspace
(`.cryostack/icesee_plots/<example>/`). Then:

1. **Edit my plotting code** opens your copy in the **Editor** (marked
   *My plotting code*). Edit a view's `build` function to change its
   figure, or register a new view with
   `register(ViewSpec(id="my.view", ...))` and list `my.view` in your
   `results.yaml`. **Save** checks the Python syntax first; a file with a
   syntax error is not saved.
2. In **Results**, switch between **ICESEE figures** and **My plotting
   code**. Figures drawn from your copy are labelled *my plotting code*. If
   your code fails, Results names the file and line.
3. **Reset to example** in the Editor restores one file to ICESEE's
   version; **Delete my copy** in Results removes the whole copy.

Your plotting code reads the run's outputs but can never change them. It
runs in a sandbox with no network access. Inside it, the run's outputs and
your code are read-only, and the only place it can write is a separate
figure cache for your copy (`.icesee-results/user/` in the run folder).
ICESEE's own figures and the example's files are never modified. If the
server cannot provide the sandbox, your copy is not run at all.

For Lorenz-96 runs in the launcher's Python, **Also run read_results.ipynb**
(Environment & resources) additionally executes the notebook into
`report.ipynb` in the run folder.

## Reproducibility

Each run folder keeps the `params.yaml` it ran with, a copy of the example
as staged (including your edited inputs), and `provenance.json`: the
experiment and mode, the checksum of `params.yaml` and of every staged
input (marking the edited ones), the CryoLauncher commit (and whether the
installation had local changes), the ICESEE version, the Python packages or
container image, the command, and the requested resources. No credentials
are recorded. **Reproducibility bundle** (Run tab) downloads these files;
**Reuse configuration** loads the run's example, mode and `params.yaml` into
the form for a new run.

## Auto-config · Beta

Where the deployment enables it, expand **Auto-config · Beta** in the
**Mode** card (step 1) and describe the experiment, for example:

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
    <summary>A run fails with "Invalid parallel flag" or "h5py was built without MPI support"</summary>
    <p>
      ICESEE no longer reads <code>parallel_flag</code>; remove it or leave it
      as it is. "h5py was built without MPI support" means
      <code>execution_mode: 2</code> ran in an environment without parallel
      HDF5 (the ICESEE container or the Cloud image): use the launcher's
      Python environment, or <code>execution_mode</code> 0 or 1.
    </p>
  </details>

  <details>
    <summary>The workflow fails before the model runs</summary>
    <p>
      Read <b>Logs › Run output</b> for a missing file, an environment-activation error, a
      missing package, or an invalid parameter value. On Remote, confirm
      <b>Check SSH Access</b> reads <b>Verified</b> and, for ICESEE-Spack, that
      the environment is installed.
    </p>
  </details>

  <details>
    <summary>An example cannot run in Local</summary>
    <p>
      The Experiment card says where the selected example can run. Icepack
      needs the <b>ICESEE container</b> environment; ISSM needs MATLAB and
      ISSM, so it runs on Remote; Flowline is under development: its run
      finishes but the result is not usable yet.
    </p>
  </details>

  <details>
    <summary>Results says outputs are missing or a view is unavailable</summary>
    <p>
      Results names the missing or damaged file. A failed run usually wrote
      nothing — read its log. For Remote runs, use <b>Fetch outputs from
      cluster</b> first. Icepack maps need <code>dof_coordinates.h5</code>,
      which the ICESEE container writes after a successful run; the other
      Icepack views work without it.
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
