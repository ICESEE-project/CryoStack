# Extending CryoStack

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
    <h1>Extending CryoStack</h1>
    <p>
      Concrete recipes — the actual files/functions involved, not a general
      description.
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

Each recipe links back to the fuller explanation elsewhere in this guide.

## Add a CryoStack application

Give it its own gateway (`icesee_jupyter_book/ui/<app>_gateway.py`, a single
`build_*_ui()` returning one `ipywidgets` tree), a proxy/health entry in
`deployment/applications.yaml`, and application pages under
`icesee_jupyter_book/applications/<app>/`. Reuse the shared application-shell
components (see [Shared UI](dev_frontend.md)) rather than building
a parallel visual system, and reuse `WorkspaceManager` for persistence rather
than inventing a second per-user storage scheme. An application is free to
choose its own configuration-experience shape (CryoLauncher:
Basic/Advanced/Auto-config·Beta; ICESEE: Local/Remote/Cloud + Auto-config·
Beta) — nothing in the shared layer requires the two to match.

## Add a model/workflow adapter

Implement the interface `cryostack_src/models/<new_model>/` exposes to the
gateway: discover runnable examples, resolve an entrypoint, and (where
relevant) a curated parameter schema — see
[Models and adapters](dev_models_results.md) for the
existing ISSM/Icepack shape. Add a result reader/visualizer only if the
model produces its own result format; otherwise reuse the existing
transport-neutral `outputs/{metadata.json, mesh, fields, model, figures}`
contract so `discover_results()`/`cryostack_src/visualization/` need no
model-specific branch. Register the model with
`cryostack_src.models.workflow_capabilities` (`uses_<model>`,
`requires_matlab_license`, `supports_ec2`, `supports_gpu`,
`supports_multinode`) so UI visibility and preflight gating stay
consistent — never re-derive a capability ad hoc from the model name.

## Add a Remote example

For ISSM/Icepack, canonical examples are discovered from the resolved
ISSM/Icepack installation root by `discover_issm_examples()` /
`discover_icepack_examples()` (`icesee_jupyter_book/core/icesheet_examples.py`);
dropping a new example directory under that root and re-running discovery is
normally sufficient — `WorkspaceManager.stage_example_for_run` (see
[Models and adapters](dev_models_results.md)) works on
any directory-shaped example without a per-example code change. If the
example needs Basic-mode curated parameters, extend
`cryostack_src/models/issm/md_config.py`'s validated schema. Confirm it
against both the ICESEE-Spack and ICESEE-Container backends (see
[Remote execution backends](dev_execution.md))
before calling it Remote-verified — the two have different
single-node/multi-node MPI constraints.

## Add a Cloud example

The same canonical example directory Remote uses is staged by the identical
`stage_example_for_run` call in `icesee_jupyter_book/ui/icesheets_gateway.py`'s
`_submit_cloud_run`, so no new staging code is normally needed. What differs
per model is the allow-list/guard at Review: ICESEE's cloud path explicitly
refuses an unverified example or process count with a stated reason (see
**Verified runtime contracts** in the Cloud Run Guide); CryoLauncher's
Icepack/ISSM paths are model-neutral and do not hard-refuse an unlisted
example, but an example is only "AWS-validated" once an actual run has
completed against the real container image and the Cloud Run Guide's
worked-examples table is updated to say so — do not mark something
validated from local testing alone.

## Extend supported execution capabilities safely

(e.g. a new EC2 shape, a new compute mode.) Add the capability behind its
own gate in `cryostack_src.models.workflow_capabilities` and
`cryostack_src/cloud/` (mirror how
`compute_mode`/`ec2_capacity`/`ec2_accelerator`/`ec2_topology` are each
independently gated in
`cryostack_src/frontend/cryolauncher/cloud_environment.py` — see
[Compute mode: Fargate vs. EC2](dev_execution.md)),
keep it submission-guarded rather than silently permitted until it has an
actual live-validated run, and update the Cloud Run Guide's **Verified
runtime contracts** section in the same change that flips the guard — a
capability must never read as validated in documentation before it is
validated in evidence.

## Add or modify Auto-config · Beta behavior

The mounted configuration layer lives in
`icesee_jupyter_book/ui/configuration_agent.py` (`build_configuration_agent`,
`build_icesheets_configuration_agent`, `build_icesee_configuration_agent`)
and `cryostack_src/agents/` (`intent.py`'s `infer_request`/`Proposal` for
deterministic request parsing, `diagnosis.py`'s
`diagnose_configuration`/`RepairProposal` for bounded repairs, `policy.py`
for the safety invariants — `assert_same_user`, `assert_within_workspace`,
and the source-guard `assert_tool_modules_are_clean` that keeps the agent's
tool modules free of side-effecting calls). Metadata/capability inputs come
from the same catalog/example/profile metadata the manual UI already uses —
never a second, agent-only data source. The proposal/apply flow is: infer or
diagnose a `Proposal` → render a change preview (From request / Suggested /
Retained provenance, never silently dropping unrelated settings) → `Apply`
writes only to the existing manual controls, through the existing
validation path, with a freshness/digest check against the proposal so a
stale or tampered proposal cannot apply. Tests to accompany a change here:
`icesee_jupyter_book/ui/tests/test_agent_interaction.py`,
`test_agent_diagnosis.py`, `test_agent_explanation.py`,
`test_agent_refinement.py`, `test_configuration_agent.py`,
`test_agent_panel_gateway_mount.py`, `test_shared_agent_panel.py`. See
[Auto-config · Beta](building_agents.md) for the full behavioral contract
(provenance meanings, diagnosis scope, refinement, read-only explanations) —
this guide only maps behavior to files; it does not restate that contract.

See [Testing](dev_testing.md) for the full test suites to run after any of
these changes.
