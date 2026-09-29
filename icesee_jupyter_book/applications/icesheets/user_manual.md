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
      The operational guide to configuring models, editing examples in your
      own workspace, managing datasets, launching runs on remote resources or
      your own AWS account, and exploring structured results.
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

## 1. CryoLauncher overview

CryoLauncher is the numerical-modeling application in CryoStack. It runs in a
browser and gives you one consistent workflow for supported ice-sheet models:
choose a model and example, configure it, submit it to a computing resource,
monitor it, and explore the results.

The interface has two areas:

:::{raw} html
<div class="cryostack-manual-grid">

  <article class="cryostack-manual-card">
    <div class="cryostack-manual-number">01</div>
    <h3>Run settings</h3>
    <p>
      Model, example, Basic/Advanced mode, execution mode and backend, the
      guided configuration panel, datasets, and the computing-resource
      settings.
    </p>
  </article>

  <article class="cryostack-manual-card">
    <div class="cryostack-manual-number">02</div>
    <h3>Workspace</h3>
    <p>
      Run history and status, per-run files, the Advanced-mode file editor,
      the run log, and the Results tab with the field-visualization panel and
      download controls.
    </p>
  </article>

</div>
:::

## 2. Applications and maturity

:::{raw} html
<p>
  <b>ISSM</b> <span class="cryostack-status supported">Supported — Remote and Cloud</span><br>
  The Ice-sheet and Sea-level System Model. Solver-aware Basic-mode
  configuration, per-user example staging, structured result export, and
  deterministic Solution / Field / Timestep visualization. ISSM runs MATLAB,
  so every ISSM run needs a MATLAB license available to the compute resource
  (see <a href="#matlab-licensing-for-issm-cloud-runs">MATLAB licensing</a>).
</p>
<p>
  <b>Icepack</b> <span class="cryostack-status supported">Supported — Remote and Cloud</span><br>
  The Firedrake-based glacier-flow library. Example discovery, workspace
  editing and cloning, dataset staging, container and Spack backends, Slurm
  settings, Remote and Cloud submission, run history, provenance, structured
  result export, field visualization, and downloads use the same workflow as
  ISSM. Icepack needs no MATLAB license.
</p>
:::

Where Icepack differs from ISSM today:

- **Basic mode has two curated parameters** — ice temperature and the number
  of timesteps (see <a href="#basic-mode-for-icepack">Basic mode for Icepack</a>). Other
  changes are made by editing the example in Advanced mode.
- **Visualization shows maps of the final exported state.** The exported
  fields are thickness, velocity, surface, bed, accumulation, log-fluidity,
  and damage — whichever the example defines. There is no timestep selector or
  time-series plot for Icepack; figures the example saves itself are also
  collected and shown.
- **Notebook examples** are shown read-only in the Advanced editor (see
  <a href="#advanced-mode">Advanced mode</a>).
- **Cloud validation is per example.** Icepack has completed end-to-end Cloud
  runs for `04-synthetic-ice-stream-xy` (Fargate) and `00-meshes-functions`
  (EC2 On-Demand, single node, CPU). Other Icepack examples use the same code
  path but have not each been confirmed on Cloud.

Basic and Advanced are **CryoLauncher-wide configuration modes**, not model
modes and not execution backends: every model runs through the same
Remote or Cloud execution paths whichever mode you configure it in.

## 3. Basic mode

Basic mode is a **guided scientific-configuration surface**. It is not a raw
model-code editor.

- **Guided configuration.** You are shown a small, curated set of parameters,
  not the full model object.
- **Solver-aware.** The panel only offers parameters that are relevant to the
  solver the selected example actually runs. For ISSM this includes
  stressbalance tolerances (`restol`, `reltol`, `abstol`) and `maxiter`, time
  stepping (`time_step`, `final_time`), transient physics toggles
  (stress balance / mass transport / thermal / grounding line / moving front /
  SMB), a friction-coefficient multiplier, an ice-rigidity (rheology&nbsp;B)
  multiplier, and curated extra requested outputs.
- **Opt-in.** Nothing changes unless you explicitly enable a parameter and set
  a value. Spatial fields such as friction or rheology&nbsp;B are applied as a
  multiplier on the existing field, never replaced by a scalar.
- **Defaults preserved.** Every parameter you do not touch keeps the value
  from the example. Basic mode never rewrites example defaults you did not ask
  it to change.
- **Validated before execution.** Each value is range- and type-checked. If a
  value is out of range or malformed, the run is blocked with a clear message
  before anything is submitted.
- **Safe staging.** When you run a Basic-mode configuration against a
  read-only application example, CryoLauncher automatically stages a
  user-owned working copy under your workspace, injects the validated
  overrides into that copy immediately before the solve, and leaves the
  canonical example untouched. If the example is already one of your own, the
  overrides are applied to it in place.

### Basic mode for Icepack

Icepack examples are Firedrake/Python notebooks, not an ISSM `md` model object,
so the curated set is different and deliberately small. Two parameters are
exposed today, both scalars with an unambiguous physical meaning that every
flow tutorial sets the same way:

- **Ice temperature** (`T`, kelvin, 200&nbsp;K – pressure-melting point). Sets
  the depth-averaged temperature from which Icepack derives the ice fluidity.
- **Number of timesteps** — the length of the time-integration loop, only where
  the example sets it as a plain literal (it does not change the physics or the
  timestep size).

The same guarantees apply: the value is range-checked before submission; the
override is a single, exact, commented line change in a user-owned working
copy; the canonical example is never modified; run provenance records exactly
which line changed from what to what. **If the selected Icepack example does
not set the parameter as a plain literal** (for example a temperature written
as an expression, or a timestep count derived from `num_years ×
timesteps_per_year`), the run is blocked with a clear message rather than run
with a silently-ignored value — use Advanced mode to edit that example
directly. No ISSM parameter names or `md` semantics are used for Icepack.

## 4. Advanced mode

Advanced mode is a **model-neutral workspace and file editor** for modifying
examples and files directly.

- **Where it lives.** The editor is an **Editor** tab in the Workspace
  (alongside Runs, Files, Run Log, and Results), giving it substantially more
  vertical room than a Run-settings row would. It appears only in Advanced
  mode — Basic mode's Workspace has no Editor tab. This is the same editor
  widget and controller either way; switching Basic↔Advanced only shows or
  hides the tab, it never recreates the editor or discards its content.
- **Action.** Advanced mode adds an **Action** menu in Run settings that
  decides what the run button does:

  | Action | What it does |
  |---|---|
  | **Run** | Submit the run (the default). |
  | **Test** | Submit a short environment-check job instead of the example: for ISSM it starts MATLAB and reports the ISSM version, for Icepack it imports Icepack. Use it to confirm a Remote backend works before a full run. Remote only — Cloud runs always run the example. |
  | **Deploy** | Clone the selected example into My Workspace; nothing is submitted. |

- **Canonical examples are read-only.** Application examples shipped with a
  model cannot be edited, renamed, or deleted. Opening a file from one shows
  it disabled.
- **Clone to My Workspace.** To edit an application example, clone it. The
  copy lands under your personal workspace as a fully user-owned example.
- **Editor lifecycle.** Open a file, edit it, and use **Save**, **Save As**
  (a new file inside your workspace), **New file**, and **Delete**. A
  **Refresh** control re-reads the file list.
- **Unsaved-change protection.** Switching file, example, model, or
  Basic↔Advanced is blocked while the editor has unsaved changes, unless you
  tick **Discard unsaved changes**. Basic↔Advanced preserves the Advanced
  buffer.
- **User examples.** Create a new example, **Rename** it, or **Delete** it.
  New examples are minimal user-owned directories; if the model adapter
  provides a starter template it is used.
- **Persistence.** User examples, files, and datasets persist across page
  reloads and sessions. Reloading rediscovers them.
- **User isolation.** Everything you create lives under your authenticated
  user's workspace. Another user cannot discover, open, edit, run, rename, or
  delete your examples or files. Canonical examples remain globally visible
  and read-only for everyone.
- **Notebooks.** `.ipynb` files are shown read-only as notebook JSON in this
  version; they are never silently converted to `.py`.

## 5. Application examples vs My Workspace

The **Example** menu merges two kinds of entry, and each entry is labelled as
canonical/read-only or user-owned/editable:

- **Application examples** — the canonical examples shipped with the model
  (for ISSM, `SquareIceShelf` is the recommended first example). Globally
  visible, read-only.
- **My Workspace examples** — examples under your personal workspace. Editable,
  private to you, and persistent.

Only directories that look like a real runnable example are offered — utility
folders such as `Data/`, `Mesh/`, or `Functions/` are filtered out of the
picker.

You do **not** need to clone before a Basic-mode run: changing a Basic-mode
parameter automatically stages a working copy. Clone explicitly when you want
to **edit files** in Advanced mode.

## 6. Creating, cloning, and editing user examples

| Action | What it does |
|---|---|
| Clone to My Workspace | Copies a canonical (or another user-owned) example into `My Workspace / examples / <model> /` with provenance recording the source. |
| New example | Creates a minimal user-owned example directory (with a model starter template if one exists). |
| Rename example | Renames one of your user examples; provenance and the path are updated. |
| Delete example | Removes only that user example. Canonical examples cannot be renamed or deleted. |

User-example names are validated — path separators, `..`, leading dots, and
absolute paths are rejected.

Deleting a user example never deletes reusable datasets, and deleting a run
never deletes examples or datasets.

## 7. Dataset management

Datasets are **reusable input files that live independently of any run or
example**, in your personal dataset area.

- **Upload.** Use the uploader to add one or more files at once. Scientific
  formats (`.mat`, `.h5`, `.nc`, `.csv`, `.dat`, `.exp`, `.txt`, `.json`,
  `.yaml`, …) are all accepted; there is no restrictive extension list. Very
  large files that exceed the browser upload size are reported clearly. Each
  file has a size cap suited to the widget uploader (50&nbsp;MB).
- **List and refresh.** Datasets appear in the explorer immediately. They are
  visible even when they are not text-editable — a distinction is made between
  *visible file* and *editable text file*.
- **Overwrite protection.** Re-uploading a file with the same name is skipped
  unless you tick **Overwrite existing**.
- **Reference from an example.** From one of your user examples, **Reference
  in example** links a dataset (optionally under a chosen relative path). This
  records a reference; it does not copy the file yet.
- **Run staging.** When you run an example that references datasets, each
  referenced dataset is copied into the run's working copy under
  `data/<as>`, and the run's provenance records what was staged. The original
  dataset stays in your dataset area.
- **Delete / unreference.** Deleting a dataset requires confirmation and
  verifies ownership. Removing a reference does not delete the dataset.
  Deleting a dataset that an example still references warns you that the
  reference may become invalid; it does not touch the example's other files.
- **Isolation.** Another user cannot discover, read, reference, rename, or
  delete your datasets.

## 8. Execution modes and backends

**Execution mode** (in Run settings):

:::{raw} html
<p>
  <b>Remote</b> <span class="cryostack-status supported">Supported</span>
  &nbsp;— run on a Linux server or HPC cluster <b>you</b> have access to,
  through the CryoStack Connector (recommended) or direct SSH. Configure access
  with your own HPC identity — see
  <a href="#configure-access-to-your-hpc-system">Configure access to your HPC
  system</a>. Slurm resource settings appear when the resource is
  scheduler-managed.
</p>
<p>
  <b>Cloud</b> <span class="cryostack-status supported">Supported</span>
  &nbsp;— run on <b>your own</b> AWS account and credits through AWS Batch,
  on Fargate by default or on EC2 managed instances. You connect the account
  once, CryoStack prepares the infrastructure, and you review an estimated
  cost before every launch — see
  <a href="#cloud-execution-aws">Cloud execution (AWS)</a>.
</p>
:::

CryoLauncher has no Local execution mode: ISSM and Icepack runs always execute
on a Remote resource or on AWS.


**Backend** (under Remote):

- **ICESEE-Container** — run inside a container. The container source can be:
  - **Docker / OCI** with a *tested* image — the validated container path;
  - **Local SIF** — a pre-built `.sif` on the remote resource;
  - **ICESEE-Containers (git)** — build from the container definitions.
- **ICESEE-Spack** — run against a Spack-managed software environment on the
  remote resource. First-time use requires onboarding (Section&nbsp;10).

The tested-image path pins the container by a verified digest so the software
stack is reproducible.

## 9. Configure access to your HPC system

### The trust model

CryoStack does **not** create an HPC account and does **not** replace your
institution's authentication. You must already have your own access to the
target resource. CryoStack then acts entirely as **you**:

- your own **HPC username**
- your own **allocation / account**
- your own **remote working directory**
- your own **SSH credential** (a key CryoStack generates *for you*, scoped to
  your identity)

Runs never execute through a CryoStack developer's account or a shared
identity. Before any remote run, CryoStack checks the **remote** username the
resource reports and **blocks the run** when it does not match the HPC username
you configured (see *Check SSH Access* and *Run protection* below).

Your settings are stored **per CryoStack user × per compute resource** — another
user configuring the same resource never sees or reuses your username,
directory, allocation, or key.

### Where you configure it

**Run settings → Remote Connection**, laid out around your workflow:

| Group | Fields |
|---|---|
| **Compute resource** | Resource, Host, Port |
| **Your HPC identity** | HPC username, Remote working directory |
| **Access** | Connection method (CryoStack Connector, Direct SSH from server, or Auto), Authentication method |
| **Status** | ● Not checked / Checking… / Verified / Mismatch / Failed |

with **[ Check SSH Access ]** and **[ Open Connector... ]**, a **CryoStack
Connector** card, and a **Diagnostics** section for the session id and relay
details. Resource facts (host, port, scheduler defaults, VPN/MFA requirements)
come from the resource's profile; the identity fields start blank and only ever
hold *your* values.

### Recommended path — the CryoStack Connector

For clusters behind a campus network or VPN, the recommended **Connection
method** is the **CryoStack Connector**: a small desktop app on *your*
workstation that carries CryoStack's SSH through your existing network access.

1. **Remote Connection → Connection method: CryoStack Connector.**
2. Click **Open Connector...** — CryoStack creates a pairing session and
   shows a **pairing code** on the **CryoStack Connector** card.
3. On the setup page (`/connect/`), **download the connector for your
   platform**. The offered downloads are exactly the platforms listed in
   `/downloads/connectors/manifest.json`; if your platform is not listed, a
   build has not been published for it yet — check
   [/downloads/connectors/](https://cryostack.eas.gatech.edu/downloads/connectors/).
4. **Install / launch** the connector.
5. **Pair** — the connector pairs with your most recent CryoStack session
   automatically; if it was already running, quit and relaunch it, or enter the
   pairing code from the card into the connector's pairing field.
6. The **CryoStack Connector** card then shows **Connected**.
7. Fill in **HPC username** and **Remote working directory**, set up your SSH
   key (below), and click **Check SSH Access** until it shows **Verified**.

The pairing code is one-time, expires with the session, and is never added to a
download link.

**Known macOS notes (honest, not blocking normal use):** the macOS connector
can be launched directly from the downloaded disk image. Copying it into
`/Applications` has a known responsiveness issue on some systems, and
copy/paste into the pairing field is still being polished — type the code, or
run the connector from the disk image, if either bites.

### Direct SSH from server

**Direct SSH from server** connects from the CryoStack server straight to the
resource using a **shared, server-side identity**. It is a **developer /
shared-trust mode**, not the normal multi-user path — use it only for a
single-tenant deployment or local development. Everyone else should use the
Connector.

### SSH keys

CryoStack generates a dedicated SSH key for you, **namespaced by compute
resource + your HPC username** (and, on the CryoStack server, by your CryoStack
user). It is stored under `~/.ssh/cryostack/` on the machine that owns it —
your workstation for the Connector, the server for Direct SSH. One CryoStack
user's key is never reused as another user's credential. An older cluster-only
key from a previous version (`~/.ssh/id_ed25519_icesee_<cluster>`) is shown for
reference but never adopted; re-register once.

```
Generate / View your CryoStack SSH public key
        ↓
register the PUBLIC key with the HPC resource
        ↓
Check SSH Access  →  Verified
```

- The **public key** (the `...pub` file — one line starting `ssh-ed25519 …`)
  is safe to give to the HPC service.
- The **private key** must **never** be copied into an HPC portal, pasted into
  a website, emailed, or shared. CryoStack never asks you for it, and never
  asks for a portal password.

How the public key is registered depends on the resource's **Authentication
method**:

#### SSH key

Where the resource allows key installation over SSH, choose **Authentication
method: SSH key**, seed it once with **Password bootstrap** (below), then Check
SSH Access.

#### Password bootstrap (one-time)

For resources that support it, choose **Authentication method: Password
bootstrap**:

1. Enter your HPC account password in the one-time field.
2. Click **Enable passwordless SSH**.

CryoStack uses the password **once** to append your CryoStack public key to
`~/.ssh/authorized_keys` on the resource. The password is **typed input only —
it is not stored** and is not written anywhere. When it succeeds, switch back
to **SSH key** and Check SSH Access. Password bootstrap does not work on every
HPC system (some disable password SSH, or require MFA) — if it fails, use
manual registration.

#### Manual / web-portal registration

Some HPC systems do not allow a key to be installed over SSH — you register it
through an account-management website (for example sites like the University at
Buffalo CCR, where you add authorized keys on a portal). CryoStack shows a
**Register your key** checklist for these resources:

1. **Generate / view** your CryoStack public key.
2. **Copy** the *public* key.
3. Sign in to **your institution's HPC / account portal**.
4. Find **SSH keys / authorized keys / access keys**.
5. **Add** the public key.
6. **Save / apply** the change.
7. **Return to CryoStack.**
8. Click **Check SSH Access.**

The exact portal and menu names differ by institution. If the resource's
profile carries a portal URL, CryoStack links it directly; otherwise it shows
these neutral steps. **CryoStack never asks for the portal's web password.**

### VPN, MFA, campus network

Some resources require an **institutional VPN**, **multi-factor
authentication**, or being **on a campus network** before SSH works at all.
These are **resource requirements, not CryoStack credentials** — CryoStack
cannot satisfy them for you. When the resource's profile declares them,
CryoStack shows the requirement beside the resource. Because the CryoStack
Connector runs on your workstation, it naturally inherits your VPN / campus
network.

### SSH agent

An **SSH agent** authentication option appears only for resources whose profile
declares agent support. No currently configured resource does, and the
**CryoStack Connector uses a dedicated key file, not your ssh-agent**. (The
server-side SSH Key Manager has an *Add Key to Agent* action for the server's
own agent, used only by the Direct SSH path.)

### Remote working directory

The **Remote working directory** is the location *on the HPC system* where
CryoStack stages each run's files and reads back results. It must be
**writable by your HPC identity**. Use a path you own, for example:

```
~/projects/cryostack
/scratch/<your-username>/cryostack
```

Prefer a filesystem with enough quota for run inputs and outputs (often a
`scratch` or `work` area rather than `home`). If the directory is missing or
not writable, CryoStack fails the run with a clear message — it never falls
back to another location.

### Slurm resources

When the resource is scheduler-managed, a **Slurm resources** panel appears,
grouped as:

| Group | Fields |
|---|---|
| **Job settings** | Job name, Wall time |
| **Compute resources** | Nodes, Tasks, Tasks / node, Partition, Memory |
| **Allocation & notifications** | Account, Email |

- **Account** — your (or your project's) **Slurm allocation**. It can be
  **mandatory** for a resource; CryoStack blocks submission with a clear
  message when the resource requires an account and the field is empty.
- **Email** — an optional address for job start / end / fail notifications.
- **Wall time** — `MM:SS`, `HH:MM:SS`, or `D-HH:MM:SS`.
- **Memory** — for example `512M`, `4G`, `16GB`, `1T`.
- Before submission CryoStack checks internal consistency (nodes ≥ 1,
  tasks ≥ 1, tasks / node ≥ 1, tasks / node ≤ tasks) and the syntax of wall
  time and memory. It does **not** invent cluster-specific ceilings — the
  scheduler still enforces the resource's real policies.

### Check SSH Access

**Check SSH Access** does exactly this:

```
connect to the resource
   ↓
run the identity command (whoami)
   ↓
compare the result to your configured HPC username
```

The **Status** chip shows:

| State | Meaning |
|---|---|
| **Not checked** | you have not run a check yet |
| **Checking…** | a check is running (the button is disabled) |
| **Verified** | connected, and the remote username matches your configured HPC username |
| **Identity mismatch** | connected, but the remote username is **not** the one you configured — the run log shows both |
| **Failed** | could not connect or authenticate — see the run log |

Resolving **Identity mismatch**:

- confirm the **HPC username** field is your actual username on that resource;
- confirm the SSH key you registered belongs to the **intended account**;
- if using the Connector, confirm it is **paired to your current CryoStack
  session** (the Connector card shows **Connected**).

### Run protection

When you submit a **remote** run, CryoStack performs a **fresh** access
verification at submit time — it re-runs the identity check and blocks the run
on a mismatch, an unverified or incomplete configuration, a missing credential,
or (for the Connector path) an offline connector. A green **Check SSH Access**
earlier is a useful UX signal but is **not** blindly trusted for execution.

### Security and isolation

- CryoStack application state (workspace, run history, settings) is scoped to
  your **authenticated CryoStack user**.
- HPC settings are stored **per user × compute resource**.
- SSH credentials are **namespaced by user × resource × HPC identity**.
- Connector pairing sessions are **owner-bound** — a session belongs to the
  CryoStack user who created it.
- SSH private keys, bootstrap passwords, pairing codes, and relay tokens are
  **never written into run provenance** or any saved configuration.

## 10. Cloud execution (AWS)

Cloud runs execute on **your own AWS account** (bring-your-own-AWS) through
AWS Batch. You connect the account once, CryoStack prepares the required
infrastructure in it, and every launch goes through an explicit review with an
estimated cost. AWS charges apply to your account.

CryoStack uses **temporary role access** and never stores AWS access keys —
you are never asked to paste an access key, a secret, or a CLI profile.
Running `aws configure` is **not** required.

**Video tutorials.** The
<a href="https://mediaspace.gatech.edu/media/Brian+Kyanjos+Zoom+Meeting/1_edvr6a1l" target="_blank" rel="noopener noreferrer">Icepack · Cloud</a>
tutorial follows this whole sequence, including connecting your AWS account
and preparing the cloud environment. The
<a href="https://mediaspace.gatech.edu/media/Brian+Kyanjos+Zoom+Meeting/1_7aycdfrg" target="_blank" rel="noopener noreferrer">ISSM · Cloud</a>
tutorial starts from an already prepared CryoStack AWS environment. See
<a href="resources.html#video-tutorials">all CryoLauncher video tutorials</a>.

### What is validated, available, and guarded

:::{raw} html
<table>
  <thead>
    <tr><th>Cloud option</th><th>Status</th><th>What that means</th></tr>
  </thead>
  <tbody>
    <tr>
      <td><b>Fargate</b> (default)</td>
      <td><span class="cryostack-status supported">Validated</span></td>
      <td>ISSM and Icepack have completed end-to-end runs: submission,
      execution, retrieval, and visualization.</td>
    </tr>
    <tr>
      <td><b>EC2 On-Demand</b>, single node, CPU</td>
      <td><span class="cryostack-status supported">Validated</span></td>
      <td>ISSM and Icepack have completed end-to-end runs.</td>
    </tr>
    <tr>
      <td><b>EC2 Spot</b></td>
      <td><span class="cryostack-status dev">Available, not yet validated</span></td>
      <td>Can be selected and submitted; no end-to-end run has been confirmed.
      Spot capacity can be reclaimed by AWS during a run.</td>
    </tr>
    <tr>
      <td><b>EC2 custom / private network</b></td>
      <td><span class="cryostack-status dev">Available, not yet validated</span></td>
      <td>Places the compute environment in a VPC you already control. Not
      required by the validated path.</td>
    </tr>
    <tr>
      <td><b>EC2 GPU</b></td>
      <td><span class="cryostack-status planned">Guarded</span></td>
      <td>Infrastructure can be staged, but submission is blocked: the
      qualified CryoStack container image has no GPU (CUDA) runtime.</td>
    </tr>
    <tr>
      <td><b>EC2 multi-node</b></td>
      <td><span class="cryostack-status planned">Guarded</span></td>
      <td>A multi-node job definition can be registered, but scientific
      submission is blocked: the runners do not yet run distributed MPI across
      AWS Batch nodes.</td>
    </tr>
  </tbody>
</table>
:::

A control being selectable is not a claim of scientific validation. ISSM's
validated Cloud runs reached a configured Georgia Tech institutional MATLAB
license; other institutional license arrangements may need administrator
support. For the platform-wide view, see the
<a href="../../docs/hpc_cloud.html">Cloud Run Guide</a>.

### Connect AWS Account

1. Set **Execution** to **Cloud**. The **Cloud Environment** panel opens.
2. In **AWS ACCOUNT**, click **Connect AWS Account**.
3. Click **Open AWS Setup**. A CloudFormation *Quick Create* page opens in
   your AWS console, pre-filled with a unique *ExternalId* and the CryoStack
   principal. Review it and create the stack — it adds one IAM role,
   `CryoStackExecutionRole`, with least-privilege access scoped to
   `cryostack-*` resources.
4. Copy the role ARN from the stack's **Outputs** tab
   (`arn:aws:iam::<account>:role/CryoStackExecutionRole`), paste it into
   **Role ARN**, and click **Verify connection**.
5. CryoStack assumes the role with your ExternalId, confirms the account, and
   shows **● Connected** with your account ID and *Access: Temporary role*.

### Managing the AWS connection

Once connected, the account card offers:

| Control | What it does |
|---|---|
| **Re-check** | Verifies the stored connection again. |
| **Update role permissions** | Opens the CloudFormation update for your existing stack, so the role picks up the current published permissions. |
| **Disconnect** | Removes CryoStack's stored connection metadata. There are no credentials to revoke — role sessions are short-lived and never stored. |
| **Retry connection** | Shown only when verification failed; tries the same account again. |
| **Change AWS account** | Shown only when verification failed; connects a different account. Your current connection is kept until the new one verifies. |

If your browser is still signed into the **same** AWS account, use
**Retry connection** — creating a second CryoStack role in an account that
already has one fails.

### Prepare cloud

Click **Prepare cloud**. Using temporary role access, CryoStack derives the
storage bucket (`cryostack-runs-<account-id>`), job queue, and job definition,
and creates whatever is missing **in your account** — S3 storage, the
container repository, and the Batch compute environment. The panel shows
**Storage / Containers / Compute** moving to **Ready**; detailed output goes to
the Run Log. Prepare cloud is safe to run again: existing resources are reused,
not recreated.

**Test connection** checks the account connection without preparing anything.

### Compute: Fargate or EC2

Batch runs on **Fargate** (serverless) by default. **Advanced cloud
settings** in the Cloud Environment panel lets you choose **Compute: EC2 — managed
instances** instead, for more CPU or memory than Fargate allows. With EC2
selected:

| Field | Meaning |
|---|---|
| **Max vCPUs** | Ceiling for the managed compute environment (default 16). It scales to zero when idle. |
| **Instance types** | `optimal` (let AWS choose) or instance families such as `c5,m5,r5`. |
| **Capacity** | On-Demand (default) or Spot. |
| **Accelerator** | None (default) or GPU — guarded, see the table above. |
| **Network** | Default (discovered VPC) or Custom / Private: **VPC id**, **Subnet ids**, **Security groups**. CryoStack does not create any VPN or route; the VPC must already have the network path it needs. |
| **Execution** | Single node (default) or Multi-node with a **Node count** — guarded, see the table above. |

Choose these before **Prepare cloud**. Fargate-only runs never see the EC2
options, and an invalid combination (for example Spot with Fargate) is
rejected rather than silently changed.

**Region** is set in the main panel. **Advanced cloud settings** also holds
**Profile**, **S3 bucket**, **Queue**, **Job definition**, and **Job name**;
you normally leave these as CryoStack derives them.

### Review and launch

Once everything is **Ready**, a **RUN ESTIMATE** appears: expected runtime,
the resources the run will request (for example 2 vCPU · 8 GiB), and an
estimated AWS cost. Cost estimates exist for Fargate only — EC2 shows
**Estimated cost: unavailable**.

Click **Review & Launch** to open the **Review cloud run** card: experiment,
account, resources, expected runtime, estimated cost with its basis and
price-check time, and infrastructure readiness. The **Compute** row names the
backend, for example **Compute (AWS Batch Fargate)** or
**Compute (AWS Batch EC2)**; for ISSM, an **ISSM runtime** row shows whether a
MATLAB license is configured. Click **Launch cloud run** to start.

Launch is always an explicit action. If you change the example, resources, or
a model parameter after opening the review, CryoStack asks you to review the
updated estimate again.

### Monitoring a cloud run and retrieving results

A **CLOUD RUN** card shows live status (*Staging → Queued → Running →
Completed*), the AWS account and region, resources, elapsed time, estimated
cost so far, and expected runtime. It updates in the background without
blocking the interface.

- **View log** opens the run's log in the Workspace **Run Log** tab.
- **View results** (enabled on completion) opens the Workspace **Results**
  tab.
- **Terminate** stops a running job, after a confirmation step.

On completion CryoStack retrieves the run's outputs from S3 into your run
cache automatically, and Results renders them exactly as for a Remote run.
While Cloud is selected, the Run Log toolbar offers **Infrastructure smoke
test**, **Check status**, **Logs hint**, and **Clear**.

### MATLAB licensing for ISSM cloud runs

This applies to **ISSM cloud runs specifically** — the field is driven by
whether the selected workflow actually needs MATLAB, not by Basic/Advanced
mode; Icepack never shows or requires it. The tested container image ships no
license, so "Container image ready" is not the same as "ISSM runtime ready".

**First-time setup.** Normally configure the license once for the connected
AWS account and Region, then reuse it for later runs.

1. Obtain your institution's MATLAB license information and confirm that you
   are authorized to use it for the workflow.
2. Open **Cloud Environment → MATLAB LICENSE**, enter that information in the
   masked **MATLAB license** field, and select **Configure license**.
   CryoStack clears the input and keeps a reference to the license stored in
   your AWS account. You normally do not need a secret name or an AWS console
   step.
3. If your institution's license service is only reachable from its network,
   use the **INSTITUTIONAL CONNECTION** section: click **Open Connector...**,
   install the
   [Connector for your operating system](https://cryostack.eas.gatech.edu/downloads/connectors/),
   and pair it. Run it on a machine that can reach the license service —
   through your institution's VPN if required — and keep it running and
   connected while the cloud run needs the license.
4. Follow the status shown by **Prepare cloud** and **Review**. A configured
   license reference alone does not prove that the license service is
   reachable or that the scientific runtime is ready.

**Existing licenses and later changes.** Advanced users can select **Advanced
license configuration → Use an existing AWS Secrets Manager secret**, provide
an **Existing secret ARN**, and select **Use existing secret**. Revisit setup
when the account, Region, or license endpoint changes.

**Privacy.** The masked license input is handled transiently during setup;
saved configurations use a reference rather than the raw value. Do not put
license information in source files, run descriptions, or Auto-config
requests.

### Costs and cleanup

Cost figures are **estimates**. AWS charges, promotional credits, and billing
are managed by AWS — check your AWS Billing & Cost Management console. If a
price cannot be retrieved, CryoStack shows "Cost estimate unavailable" and
still lets you launch.

CryoStack does not automatically remove the AWS infrastructure a run used.
See [Cleanup](https://cryostack.eas.gatech.edu/docs/hpc_cloud.html#cleanup) in
the Cloud Run Guide before you consider a Cloud workflow finished.

## 11. Preparing and launching runs

This section covers Remote runs. Cloud runs are prepared with **Prepare
cloud** and launched from the **Review cloud run** card — see
<a href="#cloud-execution-aws">Cloud execution (AWS)</a>.

### Environment preparation

Some backends need a one-time setup on the remote resource:

- **Remote + ICESEE-Spack.** Use **Check environment** for a fast probe
  (repository, activation, `ISSM_DIR`, executables). Use **Prepare
  environment** to install or repair it — this runs as a durable setup job on
  the resource, not synchronously in the browser. After preparation, a deep
  verification confirms the environment is genuinely usable before it is
  marked **Ready**. A scientific run is blocked until the live check reports
  Ready, with a clear message.
- **Remote + Container.** No preparation step for a *tested* Docker / OCI
  image — it is used directly and pinned by digest.
- **ISSM + MATLAB licensing.** ISSM runs MATLAB inside the container. The
  MATLAB license is a property of the compute resource, injected at run time.
  If the selected resource has no license configured, the run fails fast with
  a clear message before MATLAB is launched.
  - **Remote:** the license is the compute-resource profile's network
    license server (`MLM_LICENSE_FILE=<port>@<host>`), passed to the
    container with `apptainer exec --env`. It is never logged or persisted.
  - **Cloud (AWS Batch):** "Container image ready" is **not** "ISSM runtime
    ready" — the tested image ships no license. See
    <a href="#matlab-licensing-for-issm-cloud-runs">MATLAB licensing for ISSM
    cloud runs</a> in Section&nbsp;10 for the one-time setup. The Review card shows an
    explicit **ISSM runtime** row (Ready / *Needs a MATLAB license*) distinct from the
    container row.

### Launching

Before submitting, confirm the model and example, the run target, the
execution mode and backend, your HPC access (Section&nbsp;9 — **Check SSH
Access** should read **Verified**), and any scheduler resources. Click
**Submit job**. CryoStack re-verifies remote access at submit time, then the
Run log reports staging, the submission command, the scheduler job id, and
progress.

<b>Video tutorial.</b> The
<a href="https://mediaspace.gatech.edu/media/Brian+Kyanjos+Zoom+Meeting/1_3iw27chs" target="_blank" rel="noopener noreferrer">ISSM · Remote</a>
tutorial walks through a complete ISSM workflow on an existing Remote
computing resource. See
<a href="resources.html#video-tutorials">all CryoLauncher video tutorials</a>.

## 12. Run monitoring and history

- **Runs tab.** Lists your run history with model, date, and status. Select
  a run to make it the active run for logs and results. **Refresh** re-reads
  the list; **Tail Log**, **Download**, and **Figures** act on the selected
  run; **Delete** removes it after you tick the confirmation box (deleting a
  run never deletes examples or datasets).
- **Run log.** Shows connector activity, file staging, the submission command,
  the job id, standard output and error, warnings, failures, and output
  locations. A scheduler job keeps running after you close the browser, as
  long as submission completed. For Remote runs its toolbar offers **Test
  SSH**, **Check status**, **Tail log**, and **Clear**, and **Terminate job**
  beside the run button stops a running Remote job; for Cloud runs, see
  <a href="#monitoring-a-cloud-run-and-retrieving-results">Monitoring a cloud run</a>.
- **Files tab.** Shows the selected run's workspace files.
- **Isolation.** You only see your own runs. A run id owned by another user is
  simply absent from your history.

## 13. Results

CryoLauncher discovers **what a completed ISSM or Icepack run actually
produced**, rather than assuming every example has the same outputs. Remote and
Cloud runs end up in the same Results tab: Cloud outputs are retrieved from S3
automatically when the run completes, Remote outputs when you preview or fetch
them.

### Preview Results

Select a completed run, open the **Results** tab, and click **Preview
Results**. CryoLauncher:

1. synchronizes the run's outputs into a local cache for that run (for a
   Cloud run this has usually already happened);
2. reads the structured result package;
3. populates the field-visualization panel;
4. renders an initial recommended plot.

If the outputs have not been fetched yet, the panel says so and offers a
**Fetch results** button. The controller never performs remote transfers
itself — fetching is always the execution backend's responsibility.

### Preview Results vs Render

- **Preview Results** — fetch/synchronize, discover, populate the selectors,
  and show a useful initial preview.
- **Render** — draw the specific Solution / Field / Timestep currently
  selected.

### Legacy runs

Runs produced before structured export still work: their existing figures and
model file are shown, with a note that the structured selector is unavailable
for that run. Old results are never silently rewritten.

## 14. Visualization

The **Field visualization** panel is model-neutral: it only knows
Solution → Field → Timestep and delegates the scientific rendering to the
model. The details below describe ISSM results; Icepack differences follow at
the end of this section.

- **Solution selector.** Lists the solution(s) the run actually produced
  (for example `StressbalanceSolution`, `TransientSolution`,
  `ThermalSolution`). Only what exists in the run appears.
- **Field selector.** Lists the fields in the selected solution, most useful
  first (for a stress-balance run, `Vel` and `Pressure` before the rest).
  Changing the solution repopulates the field list.
- **Timestep selector.** Shown only for transient results. It offers
  **Final** plus each available timestep, and defaults to Final. For a field
  that was only computed at some timesteps, only those are offered.
- **Field types, at a user level:**
  - *nodal* spatial fields (defined at mesh vertices) — rendered as a
    triangulation field map;
  - *elemental* spatial fields (defined per element) — rendered as an
    element-coloured map;
  - *scalar transient diagnostics* (a single number per timestep, e.g. ice
    volume) — rendered as a time series;
  - *static scalar diagnostics* and other shapes — reported with a clear
    reason rather than a broken plot.
- **Deterministic rendering.** The same selection always produces the same
  plot. Rendering does not require MATLAB or a live model installation, and
  figures with masked / non-finite regions (common on ice fronts) are drawn
  with those regions omitted rather than failing.
- **Not everything is plottable.** Available solutions and fields come from
  the actual run. Unusual result shapes are handled explicitly — an
  unsupported field shows a short reason and never breaks the Results tab.

**Icepack results.** An Icepack run exports its final state: whichever of
thickness, velocity, surface, bed, accumulation, log-fluidity, and damage the
example defines. Each is rendered as a map on the run's 2-D triangular mesh —
scalar fields as colour maps, velocity as a speed map with a light arrow
overlay. There is no timestep selector or time-series plot for Icepack.
Figures the example saves itself are collected into the package and shown
too; a run that only produced figures still shows them.

## 15. Downloads

From the Results controls:

- **Download Results** — the full structured output package as an archive.
- **Download Figures** — only the rendered figures.

Downloads operate on the local cache for the selected run, so run Preview
Results (or Fetch results) first.

## 16. Reproducibility and provenance

Each run records provenance so it can be understood later:

- the source example and whether a working copy was staged;
- Basic-mode overrides that were applied (which parameters, which values);
- datasets that were staged into the run;
- the container image or software environment used, resolved to a specific
  identity (a tested image is pinned by digest);
- the run's status and timing.

Sensitive values — credentials and the MATLAB license value — are treated as
runtime configuration only and are never written into provenance, the run
manifest, or the logs.

### Result format (reference)

The structured result package is a transport-neutral directory:

```text
outputs/
  metadata.json          # what the run produced: solutions, fields, shapes
  mesh/mesh.h5           # mesh coordinates and connectivity
  fields/<Solution>/...  # one file per exported field
  model/md_final.mat    # the full model, for MATLAB-based analysis
  figures/              # rendered figures (initially empty)
```

That layout is ISSM's. An Icepack package uses the same layout with its
fields under `fields/icepack/` and no `model/` file.

You normally never interact with these files directly — the Results tab and
the download controls do it for you. `metadata.json` is the authoritative
description of what a run produced.

## 17. Auto-config · Beta

Auto-config prepares a configuration from a short written request. It is a
**configuration aid**, not an execution agent: it proposes changes to the
existing controls, and applying a proposal changes configuration only — it
never submits, launches, or provisions anything.

When your deployment enables it, **Auto-config · Beta** appears as a third
option beside Basic and Advanced. For example:

> Run SquareIceShelf with ISSM on PACE using 4 CPUs.

### How requests are interpreted

Auto-config uses **deterministic, domain-constrained rules**, not a
general-purpose language model. It only recognizes what CryoLauncher has
registered — models, examples, compute resources, backends, resource fields,
curated scientific parameters, and their valid ranges — and it reads the
**current configuration** as its starting point. The same request against the
same configuration always gives the same proposal. It does not learn from
earlier requests or from simulation results.

What it can handle:

| Request kind | Examples |
|---|---|
| Model, example, resource, and location | "Run SquareIceShelf on PACE with 4 CPUs"; "Run my example my-shelf with 4 CPUs" (your own My Workspace examples) |
| Several resources at once | "Run SquareIceShelf on PACE with 8 cores and 32000 MB memory for 90 minutes on one node" — CPUs, nodes, tasks per node, memory, and wall time (`90 minutes` becomes `01:30:00`) |
| Registered scientific parameters | "Change ice temperature from 250 to 255" — the selected example's curated Basic-mode parameters, within their ranges |
| Relative changes | "Increase CPUs from 2 to 8"; "Double the number of CPUs"; "Reset CPUs to the default" |
| Keeping or refining the current setup | "Keep my current model but increase CPUs from 4 to 8"; "Keep ISSM and the current example but use 16 CPUs" |

Requests it will not guess at are reported instead of silently dropped:
unrecognized words or numbers; alternatives and exclusions ("instead of",
"or", "without X"); contradictions with something you asked to keep;
self-contradictory changes such as "Decrease CPUs from 4 to 8"; and negative
or zero counts. A request that also asks to submit gets no Apply button.
Cloud compute options (EC2, Spot, GPU) and MATLAB licensing are configured
through the manual controls, never through Auto-config.

### Create plan and apply

**Create plan** prepares a compact change preview: **Setting | Current |
Proposed | Source**. Changed settings are primary; important unchanged values
appear in a short retained summary. The **Source** column records why each
value is there:

- **From request** — you asked for it explicitly;
- **Suggested** — a deterministic adjustment from existing metadata or policy;
- **Retained** — a valid current value intentionally left unchanged.

Omitted settings stay as configured. A matching request reports **No changes
needed**.

**Apply to configuration** updates the existing controls and reports how many
settings changed. It never submits or launches a workflow — review the manual
controls and complete the ordinary validation and execution steps. **Review
in Advanced** opens the complete manual configuration.

A proposal is rejected at apply time if the controls or available options
changed after it was created, or if the proposal no longer matches the request
it was created from; create it again. Manual edits always remain
authoritative.

### Diagnosis, repair, and explanations

- **Diagnosis.** "Why can't I run this?" or "What's wrong with my
  configuration?" lists configuration problems without changing controls.
- **Conservative repair.** "Fix my configuration" proposes a repair only when
  existing metadata supplies a deterministic supported choice. It cannot
  repair institutional access, credentials, licensing, or infrastructure.
- **Explanations.** "Why is this Suggested?", "What did you change?", and
  "Explain this configuration" give short read-only explanations from the
  proposal's recorded sources. A stale proposal is identified as stale rather
  than explained as current.

Each request is evaluated against the current controls, without conversation
history. Auto-config only sees your own workspace examples, never another
user's. A prepared configuration is not proof that a run is ready: identity,
resource, scientific-parameter, and backend checks still run at submission.


## 18. Troubleshooting

:::{raw} html
<div class="cryostack-troubleshooting">

  <details>
    <summary>The Results selectors are empty</summary>
    <p>
      Click <b>Preview Results</b> (or <b>Fetch results</b>) for the selected
      run. The selectors populate only after the run's outputs are
      synchronized into the local cache. If the panel says the run is a legacy
      run, structured visualization is not available for it.
    </p>
  </details>

  <details>
    <summary>A Basic-mode run is blocked before submission</summary>
    <p>
      A curated parameter is out of range or not applicable to the example's
      solver. The message names the parameter; adjust or disable it.
    </p>
  </details>

  <details>
    <summary>ICESEE-Spack run is blocked as "not ready"</summary>
    <p>
      Run <b>Check environment</b>, then <b>Prepare environment</b> if needed.
      A scientific run is only allowed once the live probe reports Ready.
    </p>
  </details>

  <details>
    <summary>ISSM run fails immediately on a MATLAB license error</summary>
    <p>
      <b>Remote:</b> the selected compute resource has no MATLAB license
      configured. Choose a resource that does, or contact the platform
      administrators. <b>Cloud:</b> configure the license under
      <b>Cloud Environment &rarr; MATLAB LICENSE</b> and, if the license service
      is only reachable from your institution's network, keep the Connector
      connected in <b>INSTITUTIONAL CONNECTION</b> — see
      <a href="#matlab-licensing-for-issm-cloud-runs">MATLAB licensing for ISSM
      cloud runs</a>.
    </p>
  </details>

  <details>
    <summary>Cloud: Launch cloud run is blocked</summary>
    <p>
      The Review card names the reason. Common ones: infrastructure not yet
      <b>Ready</b> (run <b>Prepare cloud</b>), an ISSM run without a MATLAB
      license, or a guarded EC2 option — <b>GPU</b> and <b>Multi-node</b> can
      be staged but not submitted today. Spot or GPU with Fargate is rejected;
      those are EC2-only options. See
      <a href="#what-is-validated-available-and-guarded">What is validated,
      available, and guarded</a>.
    </p>
  </details>

  <details>
    <summary>Cloud: Verify connection fails</summary>
    <p>
      Confirm you copied the role ARN from the CloudFormation stack's
      <b>Outputs</b> tab of the stack you just created. Use <b>Retry
      connection</b> for the same AWS account, or <b>Change AWS account</b> for
      a different one — creating a second CryoStack role in an account that
      already has one fails.
    </p>
  </details>

  <details>
    <summary>Cloud: the run finished but Results are empty</summary>
    <p>
      CryoStack retrieves outputs from S3 automatically on completion. Open
      the run from the <b>Runs</b> tab and click <b>Preview results</b>; if
      the outputs are still missing, use <b>Fetch results</b> and check the
      run's log with <b>View log</b>.
    </p>
  </details>

  <details>
    <summary>Connector not connected</summary>
    <p>
      Confirm the connector is running on your workstation and paired to your
      <em>current</em> CryoStack session. Click <b>Open Connector...</b>
      again to refresh the session, then quit and relaunch the connector so it
      picks up the newest session.
    </p>
  </details>

  <details>
    <summary>Pairing code expired</summary>
    <p>
      Pairing codes are one-time and expire with the session. Click
      <b>Open Connector...</b> to generate a new one, then pair again.
    </p>
  </details>

  <details>
    <summary>SSH: Permission denied</summary>
    <p>
      Your CryoStack public key is not (yet) registered for this account.
      Use <b>Password bootstrap</b> once, or register the public key manually
      through your institution's portal, then <b>Check SSH Access</b>. Never
      paste a private key anywhere.
    </p>
  </details>

  <details>
    <summary>Identity mismatch</summary>
    <p>
      You connected, but the remote username is not the one you configured.
      Check the <b>HPC username</b> field, check the key you registered belongs
      to the intended account, and check the connector is paired to your
      current session. The run is blocked until this matches.
    </p>
  </details>

  <details>
    <summary>Remote working directory missing or not writable</summary>
    <p>
      Set <b>Remote working directory</b> to a path your HPC identity owns and
      can write (often under <code>scratch</code> or <code>work</code>).
      CryoStack never substitutes another location.
    </p>
  </details>

  <details>
    <summary>Slurm account required</summary>
    <p>
      This resource requires an allocation. Enter your project's Slurm
      <b>Account</b> in <em>Allocation &amp; notifications</em> and resubmit.
    </p>
  </details>

  <details>
    <summary>VPN / MFA required</summary>
    <p>
      Some resources need an institutional VPN, MFA, or a campus network before
      SSH works. These are resource requirements, not CryoStack settings.
      Connect your VPN, then use the CryoStack Connector (which runs on your
      workstation and inherits that access).
    </p>
  </details>

  <details>
    <summary>Public key registered but SSH still fails</summary>
    <p>
      Confirm you registered the <em>public</em> key (the <code>.pub</code>
      line), that it was added to the intended account, and that the change was
      saved/applied on the portal. Then check for a VPN/MFA requirement. Re-run
      <b>Check SSH Access</b>.
    </p>
  </details>

  <details>
    <summary>Connector platform not listed for download</summary>
    <p>
      The setup page only offers platforms present in
      <code>/downloads/connectors/manifest.json</code>. If yours is absent, a
      build has not been published for it yet — use another platform or contact
      the platform administrators.
    </p>
  </details>

  <details>
    <summary>macOS: connector installed in /Applications is unresponsive</summary>
    <p>
      Known issue on some systems. Run the connector directly from the
      downloaded disk image instead. If copy/paste into the pairing field also
      misbehaves, type the code.
    </p>
  </details>

  <details>
    <summary>An example or field you expected is missing</summary>
    <p>
      The example picker only lists runnable examples, and the Field selector
      only lists what the run actually produced. Confirm the run completed and
      that the analysis you expected was enabled.
    </p>
  </details>

</div>
:::

## Related documentation

- [Getting Started](getting_started)
- [CryoLauncher Resources](resources)
- [CryoStack Documentation](https://cryostack.eas.gatech.edu/documentation.html)
- [Open ICESEE](https://cryostack.eas.gatech.edu/icesee-gui/)

:::{raw} html
  </div>
</div>
:::
