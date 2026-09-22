# Architecture

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
    <h1>Architecture</h1>
    <p>
      How the web shell, gateways, application layer, and execution
      backends fit together, and where the important boundaries are.
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

**Application layer versus shared platform.** CryoStack's four scientific
applications (CryoLauncher, ICESEE, Frozen Legacies, LIVIST) each keep their
own domain-specific interface and gateway. What they share, rather than
duplicate, is the platform layer below them: identity and session handling,
per-user persistent workspaces, the execution/result contracts, the
Connector/Relay connectivity infrastructure, and application deployment
through a shared registry. Control Center is separate administrative/
operations tooling, not one of the scientific applications, mounted at
`/control/` and gated to `developer`/`maintainer`/`admin`/`owner` roles.

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

See [Frontend & Applications](dev_frontend.md) for how a gateway is built,
[Execution Backends](dev_execution.md) for what happens below the
`execution adapter` box, and [Extending CryoStack](dev_extending.md) for
concrete recipes that build on this layout.
