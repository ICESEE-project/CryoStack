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
and **Retained** means a current value is intentionally unchanged (not a claim
that execution readiness has passed). **User workspace** identifies model
context derived from a named, authenticated user-owned example.
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

## Authenticated workspace context and validation

In CryoLauncher, a request such as “Run my example my-shelf with 4 CPUs”
can select a named example already registered in the authenticated user's
workspace. An implicit model comes from that example and is marked **User
workspace** with the example's display name. An explicit requested model must
match the example; it is not silently replaced. Canonical examples remain
separate, and ambiguous names require clarification. Model-only requests do
not automatically recommend private examples; an existing selection may be
retained.

This reuses only structured example/model identity. Extra settings in example
provenance are ignored: there is no scientific/resource-value import, run-history
search, result inspection, learning, embedding index, or cross-user corpus.
ICESEE continues to use its registered templates and supported controls; its
Auto-config adapter has no authenticated workspace-example selector, so this
extension does not import private examples into ICESEE.

`workspace_context.py` requires the trusted authenticated identity to match the
manager's owner. It checks the existing account/model namespace and example
ownership metadata before exposing context. Redirected directories, symbolic
links, hard-linked files, malformed provenance and CLI identity overrides are
excluded. Example names, not paths or account identifiers, appear in provenance.
The context is rebuilt per proposal and Apply; no shared context cache is added.
These checks protect the Auto-config path, not arbitrary code running with the
server's filesystem privileges or other workspace APIs.

Before Apply mutates controls, `proposal_validation.py` checks model/example and
execution compatibility, supported options, parameter types/bounds, widget
bounds, the existing pure scientific validators, and newly introduced scheduler
conflicts using shared Slurm validation. Apply also reconstructs the proposal
and checks its configuration/catalog snapshot and provenance. Current invalid
settings are not silently repaired or discarded. Unrelated incomplete identity
or scheduler fields remain visible through the normal review checks.

Some host checks still run after applying controls: callbacks may load an example
or synchronize ICESEE settings, and Cloud readiness uses the existing host
review path. Apply is not an atomic execution-preflight transaction and does
not certify runnable scientific content. SSH/backend connectivity, scientific
staging, licensing, credentials and Cloud readiness remain authoritative in the
existing workflow. No execution or submission callback is added.

## Composing requests and refining current controls

Multiple compatible clauses can be combined, for example:

- “Run my example my-shelf remotely with 8 CPUs and 32 GB of memory.”
- “Run SquareIceShelf with ISSM on PACE with 8 cores for 90 minutes.”
- “Configure ICESEE with Lorenz96 remotely, ensemble size 40, EnKF, and 8 CPUs.”
- “Change the ensemble size to 60 but keep the rest of my configuration.”
- “Keep my current model but increase CPUs from 4 to 8.”
- “Double the number of CPUs.”
- “Switch from local to remote execution without changing my scientific parameters.”

These forms use the current controls, not previous conversations. `from X to Y`
requires the stated old value to match the controls. Doubling requires a valid
current integer count. Normal bounds and application restrictions still apply.
Switching to Remote does not establish credentials or execution readiness.
Local/Cloud CPU requests are not substituted into Remote resource controls.

Resource units are normalized to the existing controls: GB/MB become G/M
scheduler suffixes; hours/minutes become HH:MM:SS. One through four are accepted
as spelled-out node counts. Negative/zero quantities are rejected. Separate,
different durations are conflicting requests, not implicitly summed. “Reset
walltime to the default” uses the selected profile's declared default; CPU
reset requires a registered CPU default, which current profiles do not supply.

Curated scientific fields accept “Set <label> to <value>”, “Increase <label> to
<value>”, and “Change <label> from <old> to <new>”. The last form requires an
existing explicit override confirming the old value; unchecked widget defaults
are not assumed to be the example's scientific values. Labels and aliases come
from the selected model/example metadata. Conflicting repeated assignments and
ambiguous aliases require clarification. Unknown fields remain unsupported.
ICESEE does not gain arbitrary scientific or observation parameter support.

General negation and alternatives remain blocked. The specific preservation
phrases “keep my current model”, “keep the current solver” and “without changing
my scientific parameters” are supported as constraints, not as solver editing.
A conflicting example/model/parameter change is refused. There is no independent
solver-selection control. Partial example names produce supported alternatives
rather than a guessed selection.

Read-only questions include “Why can't this configuration run?”, “What is wrong
with my current configuration?”, “Why is GPU unavailable?”, “Why can't I use
this solver?” and “Is this configuration compatible with remote execution?”.
Findings categorize messages from existing validators; no new scientific
validity rules are introduced. Remote compatibility uses a temporary in-memory
configuration and pure checks, without switching controls or resolving Cloud
credentials.

“Make this configuration valid for remote execution” may propose the explicitly
requested Remote location and a missing profile-defined walltime only when the
checked configuration has no remaining blockers. “Fix the resource settings but
keep my scientific parameters” retains the existing conservative resource
repair. Neither form clamps scientific values, chooses among competing resource
repairs, or certifies backend readiness.

“What did Auto-config change?”, “Why did Auto-config suggest 8 CPUs?”, “Where
did this model selection come from?”, “Why was this setting retained?” and “Why
is this option unsupported?” explain the current proposal's recorded provenance.
A question containing a CPU value absent from the proposal is identified as
such; it does not invent a justification. Stale proposals remain refused.

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
