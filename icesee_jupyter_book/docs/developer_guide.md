# Developer Guide

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

    <div class="cryostack-section-label">
      CryoStack Documentation
    </div>

    <h1>Developer Guide</h1>

    <p>
      Build, extend, test, and integrate applications with the
      CryoStack scientific-computing platform.
    </p>

    <div class="cryostack-docs-actions">
      <a class="cryostack-btn primary"
         href="https://github.com/ICESEE-project/CryoLauncher"
         target="_blank" rel="noopener noreferrer">
        CryoLauncher Repository
      </a>

      <a class="cryostack-btn secondary" href="../documentation.html">
        Platform Documentation
      </a>
    </div>

  </section>

  <section id="navigation" class="cryostack-section">

    <div class="cryostack-section-label">
      On this page
    </div>

    <h2>Where to go next.</h2>

    <p class="cryostack-section-intro">
      Cards navigate to the sections below. Detailed material stays as
      readable documentation, not cards.
    </p>

    <div class="cryostack-docs-summary-grid">

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">AR</div>
        <h3><a href="#architecture">Architecture</a></h3>
        <p>How the web shell, gateways, application layer, and execution
           backends fit together.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">AP</div>
        <h3><a href="#application-development">Application development</a></h3>
        <p>Local environment, running a gateway, Basic and Advanced modes.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">UI</div>
        <h3><a href="#shared-ui">Shared UI</a></h3>
        <p>Reusable application-shell components and the single responsive
           stylesheet.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">MA</div>
        <h3><a href="#models-and-adapters">Models and adapters</a></h3>
        <p>The model-adapter contract and the WorkspaceManager boundaries.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">RV</div>
        <h3><a href="#results-and-visualization">Results and visualization</a></h3>
        <p>The transport-neutral result package and deterministic rendering.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">TE</div>
        <h3><a href="#testing">Testing</a></h3>
        <p>The Python suite, Node tests, the book build, and source guards.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">CN</div>
        <h3><a href="#connector-development">Connector development</a></h3>
        <p>Connector architecture and how to build one locally.</p>
      </div>

      <div class="cryostack-docs-summary-card">
        <div class="cryostack-docs-summary-icon">CW</div>
        <h3><a href="#contribution-workflow">Contribution workflow</a></h3>
        <p>Branching, commits, and the checks every change must pass.</p>
      </div>

    </div>

  </section>

  <section id="scope" class="cryostack-section">

    <div class="cryostack-section-label">Scope</div>
    <h2>What this guide covers.</h2>

    <p class="cryostack-section-intro">
      This guide is for people <strong>building on or extending</strong>
      CryoStack. Instructions for ordinary users who install and pair the
      CryoStack Connector, and for configuring HPC access, live in the
      CryoLauncher <strong>User Manual</strong>.
    </p>

    <p>
      Operating a CryoStack <em>deployment</em> &mdash; publishing production
      connector binaries, the canonical release store, nginx and service
      administration, production rollback &mdash; is covered by a separate
      <strong>Maintainer Guide</strong> at <code>/docs/maintainer/</code>.
      That guide is restricted at the authentication boundary to accounts
      holding a <code>developer</code>, <code>maintainer</code>,
      <code>admin</code>, or <code>owner</code> role; a project owner grants
      roles from the CryoStack Control Center. It is not part of this public
      build.
    </p>

    <p>
      <span class="cryostack-status supported">Stable</span>
      architecture, application development, shared UI, models, results,
      testing, contribution workflow.
      <span class="cryostack-status dev">In progress</span>
      expanded model-adapter reference and integration examples.
    </p>

  </section>

</div>
:::

---

## Architecture

CryoStack separates four layers so each can evolve independently:

```text
  WEB SHELL            GATEWAY UI            APPLICATION           EXECUTION
 ┌───────────┐  ──►   ┌───────────┐  ──►   ┌───────────┐  ──►   ┌───────────┐
 │ book +    │        │ Voilà     │        │ adapters, │        │ Remote /  │
 │ auth +    │        │ gateways  │        │ workspace,│        │ HPC,      │
 │ proxies   │        │ (per-user │        │ results,  │        │ containers│
 │ (aiohttp) │        │  kernel)  │        │ profiles  │        │ Spack, …  │
 └───────────┘        └───────────┘        └───────────┘        └───────────┘
```

**Request flow.** A browser request reaches nginx, which forwards everything
to the aiohttp app (`bin/icesee_app.py`) on a local port. That app serves the
built book as static files, installs the authentication routes, mounts the
role-gated Control Center, and wraps each application proxy in `require_login`
so an unauthenticated request never reaches a gateway kernel. The proxy
forwards the caller's verified CryoStack identity to the kernel as a request
header; the kernel treats that header as the **only** trusted identity and
namespaces every workspace by it.

**Ownership boundaries.** Resource facts (login host, scheduler defaults,
supported access/auth mechanisms) belong to a `ComputeProfile` and are never
personal. Per-user, per-resource settings (HPC username, remote directory,
allocation) are persisted only for an authenticated user and are never
inferred from the server process environment. Secrets (bootstrap passwords,
pairing codes, relay tokens) are never persisted and never written to a
manifest, run plan, or log.

**Repository layout.**

| Path | Contents |
|---|---|
| `bin/icesee_app.py` | aiohttp web shell: static book, auth, Control Center, gateway proxies |
| `icesee_jupyter_book/` | Jupyter Book source, gateway UI (`ui/`), gateway core (`core/`) |
| `icesee_jupyter_book/ui/` | Voilà gateways + shared application-shell components |
| `cryostack_src/` | model adapters, workspace, submission, results, visualization, resource profiles, remote bridge |
| `icesee_auth/` | session + role storage, OAuth providers, `require_login` / `require_roles` |
| `control_center/` | role-gated operator console mounted at `/control/` |
| `icesee_hpc_connector/` | the desktop Connector application |
| `deployment/` | build, release, and nginx tooling (see the Maintainer Guide) |

## Application development

**Environment.** Development uses the project conda environment
(`icesee1-dev`). Clone with submodules, create the environment from the
project spec, then run the web shell:

```bash
git clone --recurse-submodules https://github.com/ICESEE-project/CryoLauncher.git
cd CryoLauncher
python bin/icesee_app.py        # serves http://127.0.0.1:8080
```

The shell expects the book to be built
(`jupyter-book build icesee_jupyter_book`) and the two gateway notebooks to
be present. It starts one Voilà process per application and proxies to them.

**Gateway shape.** Each gateway is a single `build_*_ui()` function returning
one `ipywidgets` tree. It composes:

- shared application-shell components (header, Remote Connection panel, Slurm
  Resources panel) from `icesee_jupyter_book/ui/`;
- model-specific run settings, example discovery, and the Run Plan;
- a Workspace panel (persistent, per-user) and a Results panel.

**Basic and Advanced modes.** Basic mode presents curated, validated
configuration — for ISSM this is a solver-aware parameter panel that stages a
user-owned working copy and never mutates a canonical example. Advanced mode
exposes a generic, model-neutral file editor over the same workspace, with
canonical material read-only and a **Clone to My Workspace** action. Both
modes converge on the same submission contract.

## Shared UI

The gateways share generic, model-neutral building blocks in
`icesee_jupyter_book/ui/`. These components **arrange the gateway's existing
widget instances** — they do not own transport, the Run gate, identity
verification, or model logic.

| Component | Responsibility |
|---|---|
| `shared_application_header.build_application_header(app_name)` | Compact shell header: fixed **CryoStack** wordmark above a distinct application name. The mark is derived from the one canonical `cryostack.png`. |
| `shared_remote_connection_panel.build_remote_connection_panel(...)` | Remote Connection organised as *Compute resource / Your HPC identity / Access / Status*, with a status chip driven by the access state, the connector card, and a **Diagnostics** accordion holding the session id, websocket path, and relay state. |
| `shared_slurm_resources_panel.build_slurm_resources_panel(...)` | Slurm request grouped as *Job settings / Compute resources / Allocation and notifications*, full-word labels, help text, responsive 3→2→1 numeric grid. Serializer keys and submission arguments are unchanged. |
| `shared_auth_ux` | Authentication options come from `ComputeProfile.auth_modes` / `ssh_agent_supported`; certificates, token auth, and portal *provisioning* are never advertised. Manual key registration shows a fixed six-step checklist and never collects an institutional web-portal password. |
| `shared_validation` | Pure pre-submit checks: node/task/tasks-per-node floors and consistency, wall-time and memory syntax, allocation required only when the profile says so. No invented site limits. |

All responsive rules for the `cryostack-*` component classes live in a single
stylesheet, `icesee_jupyter_book/ui/shared_app_styles.py`. Do not add a
per-gateway visual system.

## Models and adapters

**Model adapters** (`cryostack_src/models/`) present a uniform interface to
the gateway: discover runnable examples, resolve an entrypoint, describe
templates, and — where relevant — expose a curated parameter schema. A new
model is added by implementing that interface; the gateway code stays
model-neutral.

**WorkspaceManager contracts.** Every workspace is scoped to one
authenticated CryoStack user and stored under a per-user owner root. The
manager enforces containment: a path outside the owner root is rejected, and
canonical application material is read-only and surfaced with a
**Clone to My Workspace** action. User examples and datasets live under
`<owner_root>/examples/<model>/` and `<owner_root>/datasets/`; discovery
merges canonical and user entries and filters utility directories.

**SSH credential namespace.** The server-side SSH Key Manager and the
workstation Connector namespace the generated key by resource + HPC username
(and, server-side, the authenticated CryoStack user), so two people
configuring the same resource never collide on one key. Keys live under
`~/.ssh/cryostack/`. An older cluster-only key is reported but never read or
adopted automatically.

**Execution backends.** A model runs on one of two remote backends, selected
in the gateway:

- **ICESEE-Spack** — a source build activated on the allocation. MATLAB (for
  ISSM) is site-provided. This is the path for **multi-node** runs: ISSM's
  `generic` cluster launches its solver with `mpiexec`, and the host `srun`
  is available, so PRRTE can place ranks across the allocation.
- **ICESEE-Container** — a digest-pinned Apptainer image. The Slurm job runs
  **one** `apptainer exec` on the batch node; ISSM's `solve()` then
  self-launches `mpiexec` (Spack OpenMPI 5 / PRRTE 4) *inside* the image. The
  image ships no Slurm or SSH client, so that launch is confined to the batch
  node by three `apptainer exec --env` flags (`PRTE_MCA_ras=^slurm`,
  `PRTE_MCA_plm=ssh`, `PRTE_MCA_rmaps_default_mapping_policy=:oversubscribe`).
  **Container ISSM is therefore single-node.** `md.cluster.np` (2 for every
  stock ISSM example) is the MPI rank count and is owned by the example, not
  by the Slurm panel; a container ISSM run requesting `-N > 1` logs an
  advisory and still runs on the batch node. Validated end-to-end on Georgia
  Tech PACE (`SquareIceShelf`, `solve` → `outbin` → `postprocess_icesee.m` →
  `cryostack.issm.results` → Results preview). Multi-node containerized MPI is
  a deliberate, unaddressed limitation — use the Spack backend. Do not
  reintroduce the removed `srun` shim (`cryostack_src/models/submission.py`).

**Cloud execution (AWS Batch).**

- *Auth model — two modes.* **Developer / operator mode** uses ambient AWS CLI
  credentials + an optional named profile (`aws configure`); it is the local
  development and acceptance path only. **End-user mode** ("Bring your AWS
  account") is a cross-account IAM role (`CryoStackExecutionRole`) assumed via
  `sts:AssumeRole` with a per-connection `ExternalId`; CryoStack holds only
  *temporary* STS credentials for one operation and persists only non-secret
  connection metadata (`cryostack_src/cloud/connect/`). Never document
  `aws configure` for normal users — keep CLI/profile guidance in Developer /
  Maintainer scope. The onboarding template + Quick Create URL builder live in
  `cryostack_src/cloud/connect/cloudformation.py`; the CryoStack principal ARN
  is deployment config (`CRYOSTACK_AWS_PRINCIPAL_ARN`), never hardcoded, and
  the hosted template URL is `CRYOSTACK_CF_TEMPLATE_URL`.
- *Implemented:* an end-to-end ISSM path — config + preflight, a user-owned
  working copy staged to `s3://<bucket>/runs/<safe-user>/<run-id>/`,
  `aws batch submit-job` (Fargate), lifecycle status/logs/terminate.
  Submission is non-blocking (`cloud_run_controller.CloudRunController`, the
  same asyncio worker pattern as the auto-tail log worker): the UI returns at
  once, the run auto-polls, and on completion the outputs sync into the user's
  run cache and render through the same Results panel every backend uses. All
  AWS calls go through the `aws` CLI; CryoStack stores no credentials.
  Job-definition selection is controlled (the model default or a known
  CryoStack name only). A license-neutral **infrastructure smoke test**
  (`cryostack_src.cloud.smoke`) checks identity + S3 + Batch + ECR reachability
  without submitting a job.
- *Requires qualification:* budget/quota/cleanup automation, failure-recovery
  tests, IAM tightening, and one real run on a controlled account.
- *Manual checkpoint:* `overnight/CLOUD_AWS_ACCEPTANCE.md` — provisioning and
  the first paid run are human-authorised.
- *Not enabled:* a real ISSM cloud run still needs a MATLAB license configured
  for the `aws` compute profile; preflight blocks it honestly until then.

## Results and visualization

**Result package.** A completed run exports a transport-neutral package —
`outputs/{metadata.json, mesh, fields, model, figures}` — that can be read
without the original modelling stack. `discover_results()` and
`ResultPackage` present it to the gateway.

**Visualization.** Rendering is deterministic and operates only on the
neutral package: `render_field` and `render_timeseries` in
`cryostack_src/visualization/` back the Results panel's Solution / Field /
Timestep controls. Given the same package and selection, the output is
identical.

## Testing

| Suite | Command |
|---|---|
| Python | `python -m pytest cryostack_src icesee_jupyter_book icesee_hpc_connector deployment` |
| Node (connector setup page) | `node --test deployment/tests/*.test.mjs` |
| Documentation | `jupyter-book build icesee_jupyter_book` |

**Source-guard tests.** Several tests assert on source text to prevent
regressions a unit test would miss — for example that neither gateway
reintroduces a personal default, that both still call the remote-access Run
gate, and that the shared responsive classes stay in the shared stylesheet.
When you rename or move code, update the corresponding guard.

**Gateway build tests.** The gateways are built end-to-end in tests with an
injected synthetic identity, so a broken widget tree fails fast without a
browser.

## Connector development

The CryoStack Connector is the small desktop application that bridges the
browser to a VPN-protected cluster over the relay.

**Architecture.** Pairing uses a versioned protocol: a `session_id` that is
not secret, a one-time `pairing_code`, and per-session secrets that
authenticate the connector's WebSocket. The relay never exposes a
"newest session" endpoint. On macOS the Cocoa main thread does UI only (menu,
onboarding/status window, a timer status poll) while **one** background
worker owns the HTTP pairing exchange, the WebSocket connect/reconnect, and
every SSH operation. The `.app` is built `--onedir` and ad-hoc signed so a
copy in `/Applications` is not subject to Gatekeeper App Translocation.

**Build one locally.** On the platform you are targeting (connectors cannot
be cross-compiled):

```bash
bash build_connector.sh
# headless Linux:
xvfb-run bash build_connector.sh
```

`build_connector.sh` first runs `scripts/build_brand_assets.py`, which
regenerates every icon and the shared header mark from the one canonical
`icesee_jupyter_book/cryostack.png`. Do not hand-edit those outputs.

Inspect the result:

```bash
ls -lh dist/packages/
cat dist/packages/CryoStack-Connector-<platform>.<ext>.build.json
```

The `.build.json` sidecar travels with the artifact:

| Field | Meaning |
|---|---|
| `platform` | canonical platform key (`linux-x86_64`, `macos-arm64`, …) |
| `filename` | canonical artifact filename |
| `sha256`, `size_bytes` | re-verified when the artifact is registered for release |
| `built_at` | UTC build time |
| `pairing_protocol` | the connector–relay pairing protocol the binary speaks |
| `connector_build_revision` | exact source revision (`git` short SHA, `-dirty` if modified) |

`pairing_protocol` matters: a connector built from source that predates a
protocol change cannot pair with the current relay, and release registration
refuses a mismatch. Publishing and releasing a built artifact is a
maintainer operation — see the Maintainer Guide.

**Known macOS issues (accepted for the current release).** Connector v2
pairing, direct launch, the menu bar, and the visible pairing/status window
all work. Two issues are deferred: a `/Applications` copy can become
unresponsive while a direct launch works (suspected App Translocation of the
ad-hoc-signed bundle; clear with
`xattr -dr com.apple.quarantine "/Applications/CryoStack Connector.app"`),
and paste into the pairing-code field is unreliable (type the code, or export
`CRYOSTACK_PAIRING_CODE`). `bash scripts/diagnose_connector_macos.sh` audits
translocation, quarantine, and signing state. Do not regress the working
direct-launch path while addressing these.

## Contribution workflow

1. Branch from `main`. Keep a change focused — one concern per commit, a
   couple of small related commits at most.
2. Match the surrounding code: naming, comment density, and idiom.
3. Run the full Python suite, the Node tests when connector-page code
   changed, and the book build when documentation changed. State plainly
   what passed and what was skipped.
4. Never introduce a personal default, a credential, or a secret — the
   source-guard tests reject the obvious cases, but the responsibility is
   yours.
5. Open a pull request against `main` describing what changed and how it was
   verified.

:::{raw} html
<div class="cryostack-docs-page">
  <footer class="cryostack-footer">

    <div class="cryostack-footer-main">

      <div class="cryostack-footer-brand">
        <div class="cryostack-footer-logo">CryoStack</div>
        <p>
          An integrated platform for cryosphere modeling, data assimilation,
          scientific visualization, and HPC-enabled research.
        </p>
      </div>

      <div class="cryostack-footer-group">
        <h3>Platform</h3>
        <a href="../index.html">Home</a>
        <a href="../documentation.html">Documentation</a>
        <a href="../resources.html">Resources</a>
        <a href="../about.html">About</a>
      </div>

      <div class="cryostack-footer-group">
        <h3>Applications</h3>
        <a href="/icesheets/">CryoLauncher</a>
        <a href="/icesee-gui/">ICESEE</a>
        <a href="/livist/">LIVIST</a>
      </div>

      <div class="cryostack-footer-group">
        <h3>Community</h3>
        <a href="https://github.com/ICESEE-project/CryoLauncher" target="_blank" rel="noopener noreferrer">GitHub</a>
        <a href="https://github.com/ICESEE-project" target="_blank" rel="noopener noreferrer">ICESEE Project</a>
        <a href="https://github.com/ICESEE-project/CryoLauncher/issues" target="_blank" rel="noopener noreferrer">Report an Issue</a>
      </div>

    </div>

    <div class="cryostack-footer-bottom">
      <div>Developed by ICCL and PGSL at the Georgia Institute of Technology.</div>
      <div class="cryostack-footer-meta">
        <span>© 2026 CryoStack</span>
        <span>BSD 2-Clause License</span>
      </div>
    </div>

  </footer>
</div>
:::
