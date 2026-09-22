# Auto-config · Beta

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
    <h1>Auto-config · Beta</h1>
    <p>
      The deterministic configuration layer mounted in CryoLauncher and
      ICESEE, and the files/tests that implement it.
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

Auto-config · Beta is the deterministic configuration layer mounted in
CryoLauncher and ICESEE. It prepares changes to current manual controls rather
than an executable plan. It uses no LLM backend, conversational history, or
persistent planning memory. See
[Add or modify Auto-config · Beta behavior](dev_extending.md)
for the recipe view of the same subsystem.

## Scientist-facing workflow

Describe a configuration or change → Create plan → review the change preview →
Apply to configuration → inspect the ordinary controls → use existing validation
and execution controls.

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

## Implementation and integration

The deployment flag remains `CRYOSTACK_AGENT_PANEL`; the internal name is not a
user-facing mode label. The active implementation uses
`cryostack_src/agents/intent.py`, `cryostack_src/agents/diagnosis.py`, and
`icesee_jupyter_book/ui/configuration_agent.py`, mounted by the two gateway
modules. Catalogs use existing model/example metadata, compute profiles,
curated parameter definitions, and workflow capability resolvers. They are not
a second source of truth for scientific or backend validity.

Diagnosis combines configuration metadata with available validation findings.
Repairs are deliberately bounded: a missing value with a deterministic profile
default can be suggested, while materially different valid choices require
clarification. Explanations use structured provenance and existing capability
findings; they must not invent scientific reasons or expose raw configuration
JSON, paths, or policy internals.

Before Apply, configuration and catalog freshness and the independently
recomputed proposal are checked. Only supported manual controls are updated.
Normal manual review and submission retain fresh identity, resource, staging,
and backend checks. Applying a configuration is not execution authorization.

**Integration boundary to review:** ordinary Cloud proposal validation currently
reuses gateway callbacks that can resolve the connected cloud execution context;
ICESEE's callback also synchronizes its quick controls. Diagnosis/refinement and
explanation use the separate read-only validation path. Therefore the current
implementation must not be described as having zero credential-resolution or
control-synchronization effects for every validation callback. No new credential,
licensing, provisioning, or execution capability is provided by Auto-config.

## Tests and older interfaces

Focused gateway tests cover inference, proposals, diagnosis, repair, refinement,
explanations, stale/tampered proposals, and manual-control authority. Relevant
suites are `test_agent_interaction.py`, `test_agent_panel_gateway_mount.py`,
`test_agent_diagnosis.py`, `test_agent_refinement.py`, and
`test_agent_explanation.py` under `icesee_jupyter_book/ui/tests/`.

Older RunAssistant, RunPlan, and tool-loop APIs remain in the repository for
existing integrations. Their approval/dispatch interfaces are not the mounted
Auto-config workflow and should not be used to describe its UI. Auto-config
capability development is frozen pending review; documentation changes do not
authorize expanding its execution boundary.
