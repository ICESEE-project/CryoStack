# Frontend & Applications

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
    <h1>Frontend &amp; Applications</h1>
    <p>
      Local environment, running a gateway, Basic/Advanced modes, and the
      reusable application-shell components every gateway builds on.
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

## Application development

**Environment.** Development uses the project conda environment
(`icesee1-dev`). Clone with submodules, create the environment from the
project spec, then run the web shell:

```bash
git clone --recurse-submodules https://github.com/ICESEE-project/CryoStack.git
cd CryoStack
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
modes converge on the same submission contract. This Basic/Advanced/
Auto-config · Beta organization is CryoLauncher's own — ICESEE deliberately
organizes its interface as Local/Remote/Cloud plus Auto-config · Beta instead;
neither application imposes its shape on the other, and a new application is
free to choose its own configuration-experience shape (see
[Extending CryoStack](dev_extending.md)).

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

## How the applications differ

CryoStack does not impose one UI structure on every application:

- **CryoLauncher** — Basic / Advanced / Auto-config · Beta over one ISSM/
  Icepack run configuration; Remote and Cloud execution, no Local mode.
- **ICESEE** — Local / Remote / Cloud, plus Auto-config · Beta, over its
  ensemble data-assimilation configuration; Local runs a selected workflow
  in the hosting notebook.
- **Frozen Legacies** — dataset manifests, ingestion adapters, and radar
  interpretation tools; no Remote/Cloud/Auto-config execution-mode concepts.
- **LIVIST** — its own frontend and documentation, built and served through
  the CryoStack deployment registry; sharing routing and application
  context, not CryoLauncher/ICESEE's execution-mode structure.

See [Models, Examples & Results](dev_models_results.md) for the model-adapter
contract each application's gateway calls into, and
[Extending CryoStack](dev_extending.md) for how to add a new application.
