# Deployment & Maintenance

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
    <div class="cryostack-section-label">CryoStack Developer Guide</div>
    <h1>Deployment &amp; Maintenance</h1>
    <p>
      Contribution workflow, documentation builds, and where the actual
      supported deployment/release procedures live.
    </p>
    <div class="cryostack-docs-actions">
      <a class="cryostack-btn secondary" href="developer_guide.html">
        &larr; Developer Guide
      </a>
    </div>
  </section>
</div>
:::

---

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

## Documentation build

Build the book with `jupyter-book build icesee_jupyter_book` and inspect the
rendered `_build/html/` output, not just the source files — navigation
nesting, internal links/anchors, and styling only show up in the built
sidebar. The application sub-books (e.g. Frozen Legacies) build separately;
see `bin/build_application_docs.sh`.

## Runtime environment variables

The GUI (`bin/icesee_app.py` and its Voilà children) and the Connector relay
read their deployment settings from the environment. `deployment/services.sh`
sets the defaults marked below; **everything else is inherited from the shell
that runs `reboot_gui.sh` / `services.sh`** — including variables exported in
that user's shell start-up files. Never put a value in this repository, and
keep development-only overrides out of the deployment account's shell
profile.

**Application runtime**

| Variable | Default | Effect |
|---|---|---|
| `CRYOSTACK_HOST` | `127.0.0.1` | Bind address of the single app on port 8080 (Voilà children use 8866 for ICESEE and 8870 for CryoLauncher; the relay uses 8899). |
| `CRYOSTACK_APP_START_MODE` | `background` | `background` starts the Voilà services at boot; `lazy` starts each on first request. |
| `CRYOSTACK_VOILA_MODE` | `managed` | `managed`: the gateway starts its two Voilà servers. `external`: they run under their own account (`bin/icesee_app.py voila <icesee\|icesheets>`, see `deployment/README.md`) and the gateway only proxies to them. |
| `CRYOSTACK_VOILA_TOKEN_FILE` | unset | Required with `CRYOSTACK_VOILA_MODE=external`: file holding the token the gateway and the Voilà servers share (not readable by other accounts, at least 32 characters). |
| `CRYOSTACK_KERNEL_SANDBOX` | `off` | `bwrap`: every Voilà kernel runs in a per-user bubblewrap sandbox (see `deployment/README.md`); a kernel without identity or bubblewrap does not start. |
| `CRYOSTACK_KERNEL_AWS_DIR` | unset | Directory with the kernels' own AWS `config`/`credentials`, mounted read-only into sandboxed kernels; nothing else from AWS is visible to them. |
| `CRYOSTACK_KERNEL_RO_PATHS` | unset | Extra directories (path-separated) mounted read-only into sandboxed kernels. |
| `CRYOSTACK_KERNEL_HIDE` | unset | Extra repository paths (path-separated, relative) hidden from sandboxed kernels, beyond `var/`, `users/`, logs and `radar_sources.local.yaml`. |
| `CRYOSTACK_GATEWAY_INTERNAL_URL` | `http://127.0.0.1:8080` | Where kernels reach the gateway's loopback route for the signed-in user's saved workspace state. |
| `CRYOSTACK_AGENT_PANEL` | `1` (set by `services.sh`) | Shows **Auto-config · Beta** in CryoLauncher and ICESEE. `0` hides it. The code default without `services.sh` is off. |
| `CRYOSTACK_CLOUD_POLL_SECONDS` | `20` | Poll interval of CryoLauncher's CLOUD RUN card. |
| `CRYOSTACK_PERF` | off | Truthy value enables the timing spans of `cryostack_src/perf.py`. |
| `CRYOSTACK_WORKSPACE_ROOT` | process working directory | Root of every user's workspace (`<root>/users/<safe-id>/`). **Development/testing only** — pointing it elsewhere moves every user's examples, datasets, and run history. |
| `CRYOSTACK_WORKSPACE_USER` | unset | Single-user identity override for local/CLI use. **Must not be set in a web deployment**: it is used whenever the proxy identity header is absent, which defeats the fail-closed identity check. |
| `HTTP_X_CRYOSTACK_USER_ID` / `_NAME` | set per request | Not operator-set: Voilà maps the proxy-verified `X-CryoStack-User-*` headers into each kernel. |

**Authentication**

| Variable | Effect |
|---|---|
| `CRYOSTACK_AUTH_DATABASE` | Path of the authentication database (a default path is used when unset). |
| `CRYOSTACK_GITHUB_CLIENT_ID`, `CRYOSTACK_GITHUB_CLIENT_SECRET`, `CRYOSTACK_GITHUB_REDIRECT_URI` | GitHub OAuth sign-in. |
| `CRYOSTACK_ORCID_CLIENT_ID`, `CRYOSTACK_ORCID_CLIENT_SECRET`, `CRYOSTACK_ORCID_REDIRECT_URI`, `CRYOSTACK_ORCID_BASE_URL` | ORCID sign-in. |

**Connector relay**

| Variable | Default | Effect |
|---|---|---|
| `CRYOSTACK_RELAY_CONTROL_TOKEN` | generated by `services.sh` | Shared control token between the gateway and the relay. Voilà kernels never receive it; the gateway forwards each signed-in user a grant derived from it that can create only that user's connector sessions. |
| `CRYOSTACK_RELAY_SESSION_TTL` | `43200` s | Connector session lifetime. |
| `CRYOSTACK_RELAY_PAIRING_TTL` | `1800` s | Pairing-code lifetime. |
| `CRYOSTACK_RELAY_COMMAND_TIMEOUT` | `900` s | Per-command timeout for relayed SSH commands. |
| `CRYOSTACK_RELAY_TUNNEL_GRANT_TTL` | `21600` s | Default lifetime of a private-service tunnel grant (MATLAB license tunnel). |
| `CRYOSTACK_RELAY_TUNNEL_OPEN_TIMEOUT` | `20` s | Time allowed to open a tunnel. |
| `CRYOSTACK_CONNECTOR_STORE` | `~/.cryostack/connector-artifacts` | Canonical store of built Connector artifacts (`deployment/connector_store.py`). |

**LIVIST**

| Variable | Default | Effect |
|---|---|---|
| `CRYOSTACK_LIVIST_ENV` | `~/.cryostack-envs/livist` | Isolated LIVIST toolchain and virtual environment. |
| `CRYOSTACK_LIVIST_DATABASE` | `var/livist.db` | Job and publication store. |
| `CRYOSTACK_LIVIST_INPUT_CACHE` | `var/livist_input_cache` | Shared, content-addressed cache of source.coop inputs. A copy is reused only while its SHA-256 verifies and source.coop reports the same size/ETag; each job manifest records whether an input came from the cache. |
| `CRYOSTACK_LIVIST_INPUT_CACHE_MB` | `4096` | Cache size limit; least recently used inputs are removed first. |
| `CRYOSTACK_LIVIST_MAX_ACTIVE` | `2` | Concurrent generation jobs on this host. |
| `CRYOSTACK_LIVIST_JOB_TIMEOUT_S` | `21600` | Per-job time limit. |
| `CRYOSTACK_LIVIST_JOB_RESERVE_MB` | `2048` | Free disk a job needs to start; a running job is stopped when free space falls below half of it. |

Measured on this host (8 cores, 15 GB) for the real ASE input (339 MB, 1.64 M points), under a 4 GB / 2-CPU cap: 316 s wall, 370 s CPU, peak 1.3 GB resident in the largest process (2.1 GB for the job including page cache), 639 MB of products plus the 339 MB input during the run. Every job manifest records its own measured `resources` (wall and CPU time, peak RSS, disk); these are measurements, not requested limits.

**Cloud (BYO-AWS)**

| Variable | Default | Effect |
|---|---|---|
| `CRYOSTACK_AWS_PRINCIPAL_ARN` | required | The CryoStack principal allowed to assume users' `CryoStackExecutionRole`. **Connect AWS Account** fails with a clear error when it is unset. |
| `CRYOSTACK_CF_TEMPLATE_URL` | required for onboarding | Public URL of the hosted execution-role CloudFormation template. |
| `AWS_PROFILE` | `cryostack-service` (set by `services.sh`) | The service's own AWS identity, used only to assume users' roles. |

Variables such as `CRYOSTACK_S3_RUN`, `CRYOSTACK_MODEL`,
`CRYOSTACK_RUN_TARGET`, `CRYOSTACK_RUN_DIR`, and the `CRYOSTACK_LT_*`
license-tunnel settings are **injected into job containers** by CryoStack at
submission; operators never set them.

## Connector, CloudFormation, and other operational procedures

Publishing a built Connector artifact, updating the CloudFormation templates
this repository ships (`deployment/cloudformation/`), and other production
deployment/rollback procedures (nginx, service administration, the canonical
release store) are **maintainer operations**, documented in the separate
Maintainer Guide at `/docs/maintainer/` — restricted at the authentication
boundary to accounts holding a `developer`, `maintainer`, `admin`, or `owner`
role (a project owner grants roles from the CryoStack Control Center). This
Developer Guide (maintainers, admins and owners) documents what a contributor needs to build and test
changes; it intentionally does not restate that guide's operational
procedures. See [Connector & Relay](dev_connector.md)
for the specific boundary between the automated local build and the manual
publish step.
