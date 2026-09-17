# Applications & Workflows

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
    <div class="cryostack-section-label">CryoStack Documentation</div>
    <h1>Applications &amp; Workflows</h1>
    <p>
      CryoStack's principal applications share platform services but keep
      their own interfaces. Do not expect one application's controls to
      predict another's.
    </p>
    <div class="cryostack-docs-actions">
      <a class="cryostack-btn secondary" href="user_manual.html">
        &larr; User Manual
      </a>
    </div>
  </section>
</div>
:::

---

## CryoLauncher — ISSM and Icepack

CryoLauncher configures and runs ISSM and Icepack. Its configuration
experiences are **Basic** (curated, solver-aware parameters), **Advanced**
(the full working copy), and **Auto-config · Beta** (natural-language
proposals over the same configuration state) — see the
<a href="../applications/icesheets/user_manual.html">CryoLauncher User Manual</a>
and <a href="../applications/icesheets/getting_started.html">Getting Started</a>.

CryoLauncher's execution paths are **Remote** and **Cloud**; it has no
Local execution mode for a standalone ISSM or Icepack run. ISSM's container
workflow uses MATLAB and requires a license; Icepack does not.

## ICESEE — ensemble data assimilation

ICESEE organizes execution as **Local**, **Remote**, or **Cloud**, with
**Auto-config · Beta** available alongside that organization — not a
Basic/Advanced split. See the
<a href="../applications/icesee/user_manual.html">ICESEE User Manual</a> and
<a href="../applications/icesee/getting_started.html">Getting Started</a>.

ICESEE can wrap ISSM, Icepack, or a synthetic model such as Lorenz-96 as
its forecast model. Dependencies follow that choice: an ISSM-based
workflow requires MATLAB, Icepack and Lorenz-96 do not — ICESEE itself
does not generally require MATLAB.

## Frozen Legacies — historical radar catalog

Frozen Legacies discovers, catalogs, and interprets historical Antarctic
radar observations. It is not organized around Local/Remote/Cloud
execution modes — see its own
<a href="../applications/frozen_legacies/getting_started.html">Getting Started</a>
and <a href="../applications/frozen_legacies/user_manual.html">User Manual</a>.

## LIVIST — englacial temperature products

LIVIST explores Antarctic englacial-temperature products inferred from
radar and constrained by boreholes, through its own frontend served under
the CryoStack deployment registry. It does not use CryoLauncher/ICESEE
execution-mode concepts.

## Control Center — administrative infrastructure

Control Center is CryoStack's administrative/operations tooling (roles,
deployment status, account administration). It is not one of the
principal scientific applications above.
