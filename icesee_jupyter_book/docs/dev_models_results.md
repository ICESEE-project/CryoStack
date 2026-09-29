# Models, Examples & Results

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
    <h1>Models, Examples &amp; Results</h1>
    <p>
      The model-adapter contract, WorkspaceManager boundaries, and the
      transport-neutral result package and its visualization.
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

## Models and adapters

**Model adapters** (`cryostack_src/models/`) present a uniform interface to
the gateway: discover runnable examples, resolve an entrypoint, describe
templates, and — where relevant — expose a curated parameter schema. A new
model is added by implementing that interface; the gateway code stays
model-neutral.

**Workflow capability resolution** (`cryostack_src/models/workflow_capabilities.py`).
`resolve_workflow_capabilities(model, forecast_model=...)` is the single
authoritative answer to "what does this SELECTED workflow need and support"
— `uses_issm`, `uses_icepack`, `requires_matlab_license` (true exactly when
`uses_issm`), `supports_ec2`, `supports_gpu`, `supports_multinode` — never
re-derived ad hoc from the top-level `model` name. This matters because
ICESEE is a data-assimilation framework that can wrap ISSM, Icepack, or (in
principle) both as its forward model: an ICESEE run whose forecast model is
ISSM needs a MATLAB license exactly like a direct ISSM run does, while an
ICESEE run on Lorenz-96 or Icepack does not — keying the check on
`model == "issm"` alone would silently miss that. UI visibility (the MATLAB
license field), preflight gating, and review rendering all call this one
resolver, so the answer is always consistent across CryoLauncher and ICESEE.

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

See [Execution Backends](dev_execution.md) for the Remote/Cloud backends a
model runs on, and
[Extending CryoStack](dev_extending.md) for how
to add a new model adapter.

## Results and visualization

**Scope: CryoLauncher only.** Everything in this section — the result
package, `discover_results()`/`ResultPackage`, and the Remote↔Cloud parity
work below — is CryoLauncher's (ISSM/Icepack) result path. ICESEE has its
own, separate results implementation (`ExperimentBridge`, a raw file-tree
listing and inline image display, not this package) — see
[Execution Backends](dev_execution.md) for exactly where the two diverge.

**Result package.** A completed run exports a transport-neutral package —
`outputs/{metadata.json, mesh, fields, model, figures}` — that can be read
without the original modelling stack. `discover_results()` and
`ResultPackage` present it to the gateway.

**Visualization.** Rendering is deterministic and operates only on the
neutral package. Given the same package and selection, the output is
identical.

- **Registry.** `cryostack_src/models/capabilities.py` holds
  `MODEL_CAPABILITIES`, one `ModelCapabilities` record per model
  (`basic_mode_config`, `structured_results`, `result_contract`,
  `visualization`, `requires_matlab`, `execution_modes`, `cloud_supported`,
  …). It only *describes* what the adapters implement; import-time asserts
  keep it consistent with them (for example `cloud_supported` against
  `cloud.runtime.SUPPORTED_CLOUD_MODELS`).
- **Dispatch.** `results_common.resolve_visualizer(model)` returns
  `cryostack_src.visualization.<model>` when the model's record has
  `visualization=True`, else `None`. `WorkspaceManager.recommended_plots_for_run`
  and `render_run_plot` call it with the run's recorded model, so ISSM and
  Icepack share one Results panel; a model without a visualizer gets an
  `unsupported` result with a reason, never an exception.
- **Renderer contract.** Each module exposes `recommended_plots(pkg,
  solution=None)`, `render_field(pkg, solution, field, timestep=None,
  outdir=None)`, `render_timeseries(pkg, solution, field, outdir=None)`, and
  `render_recommended(pkg, max_plots=6, outdir=None)`, returning the shared
  `RenderResult` from `visualization/issm.py`; figures are cached inside the
  run's owned directory under a deterministic `figure_name(...)`.
- **ISSM** (`visualization/issm.py`) renders nodal and elemental fields on the
  triangular mesh, resolves transient timesteps, and draws scalar transient
  diagnostics as time series.
- **Icepack** (`visualization/icepack.py`) is a thin `matplotlib.tri` layer
  over the package the container-side exporter wrote
  (`models/icepack/_export_core.py`, schema `cryostack.icepack.results`): the
  allow-listed fields (thickness, velocity, surface, bed, accumulation,
  log_fluidity, damage) are interpolated to CG1 and stored as plain
  `/x /y /elements` + `/values` HDF5 in the ISSM on-disk shape, so no
  Firedrake is needed to render. Scalars render with `tripcolor`, vectors as
  a speed map with a light quiver overlay. Only 2-D triangular meshes are
  supported, there is no timestep axis, and `render_timeseries` always
  returns `unsupported` (tier 1).

**Icepack Remote↔Cloud parity.** Icepack has one shared scientific entrypoint
regardless of backend: `cryostack_icepack_runner.py <script> <run-dir>`
(generated from `cryostack_src/models/icepack/export.py`). It forces a headless
`Agg` backend, executes the example **once** with `runpy.run_path`, captures
every live Matplotlib figure plus figure metadata to
`outputs/figures/_captured.json`, and runs the tier-1 allow-list structured
export from that same namespace. Cloud stages it via
`stage_example_for_run(extra_files=...)`; Remote stages it through the sbatch
heredoc — byte-identical helper text (`test_icepack_remote_cloud_parity.py`
asserts this). The stdlib collector `cryostack_icepack_postprocess.py` then
reports an honest status (`ok` / `artifacts` / `empty`). Provider-specific
execution (Slurm vs AWS Batch) differs; scientific and result behaviour do not.
`00-meshes-functions` correctly yields figures but no recognised tier-1 fields,
so the Solution / Field controls stay hidden — that is not a failure.

**ISSM Remote↔Cloud parity.** ISSM's own postprocessor
(`cryostack_src/models/issm/postprocess.py`'s `build_postprocess()`) is the
single generator both backends stage: Remote writes it to the remote run
directory over SSH before its own unconditional `run(...)` invocation; Cloud
stages the identical text as `postprocess_icesee.m`
(`cryostack_src/cloud/runtime.py`'s `issm_postprocess_extra_files()`)
alongside `runme.m` before its own equally unconditional invocation. Both
produce the same `outputs/{metadata.json, mesh, fields, model}` shape
`discover_results()` reads — see
`cryostack_src/cloud/tests/test_cloud_runtime_issm_postprocess.py` and
`cryostack_src/workspace/tests/test_run_results.py` for the byte-identity and
end-to-end sync→discovery→render regression coverage.

**Execution-provider vocabulary.** CryoLauncher distinguishes: *execution mode*
(Remote / Cloud — CryoLauncher has no Local mode; ICESEE's own interface adds
Local separately, see [Execution Backends](dev_execution.md)), *compute
backend* (Remote → Slurm/HPC; Cloud → AWS Batch, with a *compute mode* of
Fargate (default) or EC2 (Advanced)),
*model environment* (ICESEE-Spack or ICESEE-Container),
*model* (Icepack / ISSM), *container* (tag + immutable digest + provenance), and
*experiment* (selected example + source + run target). History cards, the Run
Plan, and manifests render these as separate rows and derive a historical run's
identity from its **persisted metadata**, never the current UI defaults — a
legacy widget such as `backend_dd` never determines cloud semantics.
