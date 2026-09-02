# Agent trail — overnight autonomous session (2026-09-01 → 2026-09-02)

This document is the decomposition record the operator asked for: objective,
inspection, reasoning, delegation, discoveries, decisions, tests, results,
open questions, and next action — per phase.

The coordinating agent (main session) owns architectural consistency. Subagents
are used only for bounded, read-mostly audits and always report back here.

---

## Phase A — Connector / password-bootstrap: finish the investigation

### A.objective
The operator states the *old* Connector successfully injected its public key
into PACE with one-time password auth, and the *new* (B3-era) path no longer
completes. Commit `52d8edb` already added structured failure reasons, moved the
work off the connector event loop, fixed a 120 s/300 s timeout mismatch, wired
UI feedback to the B4 panel, and added a macOS Paste button. This phase must:
(1) prove — from git history — the exact regression vs. the proven mechanism;
(2) confirm the proven mechanism is genuinely restored on the B3 namespaced key
with an end-to-end offline test of the *whole* chain; (3) harden pairing paste
beyond the single AppKit menu path; (4) commit separately.

### A.files_inspected
- `git show 76cd0c8` (B3.2 namespace) — connector-side diff in full.
- `icesee_hpc_connector/connector_core.py` @ `76cd0c8^`, `76cd0c8`, HEAD —
  `bootstrap_passwordless_ssh_local`, `ensure_local_ssh_key`,
  `ssh_identity_args`, `handle_command`, `main()` ws loop.
- `icesee_jupyter_book/core/remote_runner.py` — `bootstrap_passwordless_ssh`
  (connector branch), history at `98e0a45` (the May 2026 refactor that replaced
  `install-pubkey` + server key with `bootstrap-passwordless-ssh` +
  connector-local key).
- `icesee_jupyter_book/core/connector_relay_server.py` — `send_command`
  endpoint (no command allowlist, forwards `payload` verbatim, no redaction),
  `COMMAND_TIMEOUT_SECONDS=900`.
- `icesee_jupyter_book/core/connector_relay_client.py` — `send_command`
  (HTTP `timeout`, now parametrised).
- `icesee_jupyter_book/ui/icesheets_gateway.py` / `icesee_gateway.py` —
  `current_remote_bridge()`, `on_bootstrap_keys`.
- `build_connector.sh` — installs `paramiko` directly; `requirements.txt` did
  not list it.

### A.reasoning / discoveries

**The B3 namespace change is internally consistent.** At `76cd0c8` the *only*
functional change to `bootstrap_passwordless_ssh_local` is
`ensure_local_ssh_key(cluster_name=…)` → `ensure_local_ssh_key(cluster_name=…,
hpc_user=user, host=host)`. `ssh_identity_args` moved to the same `payload`
dict. So bootstrap and Check-SSH still resolve the *same* key
(`~/.ssh/cryostack/id_ed25519_pace-a6505fbb04b5` for this identity). The
namespace is **not** the thing that stops the workflow — bootstrap installs the
namespaced public key and Check-SSH reads the matching private key.

**The regression is the surrounding machinery, layered:**

1. **UI (B4, `ffd0295`)** — `on_bootstrap_keys` delivered its result *only* to
   the now-collapsed Workspace-logs `Output` and the legacy status pill, never
   to the B4 `RemoteConnectionPanel`. The panel stayed on "SSH key not
   registered" regardless of outcome → "produces no visible progress/result".

2. **Connector event loop** — `bootstrap_passwordless_ssh_local` ran paramiko
   connect (15 s) + auth (15 s) + `exec_command` + a 20 s verify `subprocess`
   **synchronously on the asyncio loop**. `websockets.connect(ping_interval=20)`:
   a bootstrap that exceeds ~20 s starves the keepalive, the socket is closed
   under the connector, and the connector's `await ws.send({...result...})`
   then throws — **the relay never receives the result**, even when the key was
   already appended in the first ~5 s. Gateway `send_command` (120 s) later errors.

3. **HTTP timeout** — gateway `send_command` capped at 120 s while the payload
   asked the connector for 300 s.

4. **`requirements.txt`** — omitted `paramiko` (+ `cryptography/bcrypt/pynacl`,
   `websockets`, `requests`). `build_connector.sh` `pip install`s paramiko
   explicitly, so *shipped* DMGs likely have it, but any build/venv driven off
   the manifest ships a connector that fails at `import paramiko`.

5. **Not decidable here** — whether PACE still accepts *password* SSH auth
   (Duo / policy change since the operator last used it). `52d8edb` now surfaces
   this as `BOOTSTRAP_PASSWORD_AUTH_FAILED` instead of a silent generic
   exception. This is a **morning checkpoint** (needs Duo).

Items 1–4 are fixed by `52d8edb`. Item 5 is now diagnosable but needs the operator.

**Extra hardening identified for this phase:**
- The connector-machine direct `ssh -i` verify is a false-negative source
  (host-key prompt, VPN path differences). `52d8edb` returns
  `key_installed=True` + `reason=verify_failed` and the gateway then runs the
  real relay Check-SSH — good, but there is no end-to-end test proving the
  *whole* chain (gateway → relay envelope → connector → append → re-check →
  Verified) and the namespace match across it.
- Pairing paste: `52d8edb` added the AppKit Edit menu (re-installed on first
  tick) + an explicit **Paste** button. The `rumps.Window` modal used by the
  menu-bar "Pair with CryoStack…" item and the Linux/Windows tkinter dialog
  were not touched.

### A.delegation
None for Phase A — the coordinating agent has full context from the two prior
commits this session. Subagents begin at Phase B.

### A.decisions
- **D-A1:** Do **not** revert to the pre-`98e0a45` `install-pubkey` design
  (server key + `pubkey_text` in the payload). The connector-local namespaced
  key is the correct B3 model — the private key never leaves the workstation.
  "Restore the proven mechanism" = the *steps* (local key → one-time password
  auth → append PUBLIC key → verify), which `52d8edb` already implements on the
  namespaced key.
- **D-A2:** Keep the connector-side quick verify but treat any
  key-installed-but-verify-failed as `installed` and let the authoritative
  relay Check-SSH decide (already in `52d8edb`); add the missing end-to-end
  test.
- **D-A3:** Extend paste robustness to the `rumps.Window` pairing modal
  (pre-fill from the clipboard) and normalise in the tkinter path.

### A.tests_added
- `icesee_hpc_connector/tests/test_bootstrap_end_to_end.py` (2) — full offline
  chain; password reaches paramiko unmodified; the appended public key is the
  exact key `ssh_identity_args()` would use with `-i`; namespaced dir, never the
  legacy key; only the public key crosses the wire; relay HTTP timeout > the
  connector-side op budget; gateway connector-branch payload carries
  `host/user/hpc_user/cluster_name/password`.
- `test_connector_window.py` (+3) — `normalize_pairing_code` trims transfer
  noise; `looks_like_pairing_code` matches only the `XXXXX-XXXXX` shape over the
  unambiguous alphabet; every pairing entry point pre-fills only a code-shaped
  clipboard.

### A.results
- `52d8edb` (prior) + `416da3d` (this phase). Full suite **928 passed, 1
  skipped** (+15 this phase). `node --test` 18/18. jupyter-book clean.
- Root cause: **not** the B3 namespace (bootstrap and Check-SSH resolve the same
  key). The workflow stopped because of 4 layered machinery regressions around
  it — see A.reasoning items 1–4 — plus a diagnosability gap (item 5). All are
  fixed; `416da3d` adds the end-to-end proof and pairing-paste hardening.

### A.open_questions
- Does `login-phoenix-rh9.pace.gatech.edu` still accept password auth without an
  interactive Duo prompt from a VPN-connected workstation? (MORNING CHECKPOINT —
  needs the operator + Duo.)
- Is the relay currently deployed in production new enough to forward
  `bootstrap-passwordless-ssh` and honour a 180 s command timeout? (Deployment
  audit flagged the running services as stale; not connector-publishable
  tonight anyway.)
- **P2 robustness (noted, not fixed):** the connector's verify step and
  `run_ssh` invoke the workstation's system `ssh` with `-o IdentitiesOnly=yes
  -i <newkey>` but do NOT pass `-F none` / `-o IdentityAgent=none`. A user
  `~/.ssh/config` with an `IdentityFile` for the PACE host (e.g. still pointing
  at the legacy key) would be added to the identity list and could satisfy auth
  via the legacy key, masking whether the new key itself works. Changing the
  connector's ssh flags risks breaking working setups — leave for a reviewed
  connector change, not an autonomous one.

### A.next_action
DONE (`416da3d`). Phase A complete. Proceed to Phase B.

---

## Phase B — Icepack ↔ ISSM parity in CryoLauncher / IceSheets

### B.objective
Bring Icepack to the same user-facing + architectural level as ISSM across the
15-area workflow, reusing the shared CryoStack components, generalising the ISSM
abstraction rather than forking a parallel Icepack stack. Never fabricate an
Icepack field / parameter / solver option / output / visualization to fake
parity. Small green commits.

### B.plan
1. **Audit first (delegate).** One `general-purpose` subagent produces the
   ISSM↔Icepack parity matrix from the actual code: for every area, what ISSM
   has, what Icepack has, what the shared layer offers, and where the models
   genuinely differ scientifically. Coordinating agent reviews for
   architectural consistency and turns it into a Before→After→Remaining matrix.
2. Implement the highest-value, lowest-risk, scientifically-safe items in small
   commits (discovery/metadata, structured-results wiring, run-history, docs/
   tests) — stopping before anything needing a scientific decision (new solver
   options, field semantics, Local-exec support claims).
3. Everything requiring a scientific/design call → morning checkpoint.

### B.files_inspected
Coordinating agent (post-audit implementation reads): `cryostack_src/models/
issm/results.py` (full), `workspace/manager.py` (`_result_reader_for`,
`_visualizer_for`, `result_package_for_run`), `frontend/cryolauncher/workspace/
visualization.py`, `models/submission.py` (both submit functions, run-block
assembly, sbatch template), `models/tests/test_container_source_modes.py`
(render harness). Subagent B-1 report: see `overnight/AUDIT_icepack_parity.md`
(saved below) — 15-area matrix with file:line evidence.

### B.discoveries (from Agent B-1, condensed)
- **At parity already (no work):** advanced editor/clone, dataset staging,
  Slurm config+validation, downloads, provenance/run-history. The shared layer
  (`workspace/*`, `stack/*`, `remote/spack_env.py`, `execution/*`,
  `shared_validation`, `shared_slurm_resources_panel`) is genuinely
  model-neutral and already Icepack-aware.
- **Real user-facing gap:** an Icepack run produced **no `outputs/` at all**
  (`submission.py` wrote a postprocess only for ISSM) → Results tab stuck on
  "not fetched" forever. `_visualizer_for("icepack")` → `None`.
- **Genuine scientific differences (preserve):** `md` struct vs Firedrake
  functions; MATLAB+license vs pure Python; ISSM solution families vs
  Icepack diagnostic/prognostic; ISSM triangular mesh + `md_final.mat` vs
  Firedrake mesh + `CheckpointFile`; notebook examples vs `runme.m`; ISSM
  `COMPILED`/`OVERRIDE_NONE` vs Icepack `gated_by=firedrake`.
- **Needs a scientific decision (→ morning checkpoints):** Icepack Basic-mode
  parameter set + injection mechanism; "local execution" meaning for Firedrake;
  Icepack release/solver-option policy; the neutral Firedrake field-export
  format; the Icepack `FieldInfo.location` taxonomy; `recommended_plots`
  ordering; Cloud enablement (`SUPPORTED_CLOUD_MODELS=("issm",)`).
- **Cloud:** Icepack deliberately blocked at C3 preflight; infra provisioning
  is Icepack-ready but opt-in (`prepare_batch(include_icepack=False)`). Leave.

### B.decisions
- **D-B1:** Do NOT reskin `cryostack.issm.results` for Icepack. New neutral
  primitives (`models/results_common.py`) + a dedicated
  `cryostack.icepack.results` schema whose reader is HONEST: `is_readable()`
  is `False`, `available_solutions()` is `[]`, no invented fields.
- **D-B2:** The Icepack postprocess collects *artifacts the example emitted*
  (figures + native files) into the standard `outputs/` shape. That is pure
  plumbing, not science. A model-aware Firedrake field exporter is deferred.
- **D-B3:** Wire the collector into `submission.py` at the single shared point
  after `body` assembly (one guarded line per function), non-fatal, backend-
  agnostic. ISSM path untouched (test-asserted).
- **D-B4:** Gateway `if model == "issm"` UI toggles → adapter capability
  queries (declarative), so a future Icepack Basic-mode panel is a drop-in.

### B.tests_added
- `models/tests/test_icepack_results.py` (7), `test_icepack_postprocess.py` (5),
  `test_icepack_submission.py` (3), `frontend/.../test_visualization_controller.py`
  (+2 Icepack cases).

### B.results
- `132b8b1` — icepack structured result package + honest collector + neutral
  `results_common.py` + Results-panel `artifacts`/`empty` handling.
- `a234078` — collector wired into both remote-submit paths, non-fatal.
- Full suite 943 passed / 1 skipped (+15 across B). Node 18. Book clean. ISSM
  results + submission paths byte-identical (guarded by existing tests).

### B.delegation
- **Agent B-1** (`general-purpose`): "ISSM vs Icepack parity audit" — read-only,
  produces the 15-area matrix + a list of shared abstractions that already
  generalise vs. those hard-coded to ISSM. Prompt scoped to inspection only,
  no edits.

### B.next_action
Agent B-1 (`aa66a8ef02d414872`) SPAWNED and running. Await its report, then:
build the Before→After→Remaining matrix, review for architectural consistency,
and implement the safe subset.

### B.coordinating-agent notes while B-1 runs (independent reads)
- `cryostack_src/models/__init__.py::get_model_adapter(name)` — accepts only
  `{"issm","icepack"}`, returns the module. This is the generalisation seam.
- `cryostack_src/models/icepack/` is a **skeleton**: `execution.py` (53 L,
  real: run-command builder for spack/apptainer, `.py`/`.ipynb`/`.m` targets,
  `import icepack` activation check), `configuration.py` (23 L, reuses ISSM's
  `_container_check`; firedrake import probe), `slurm.py` (6 L, passthrough +
  a `with-icepack` apptainer fragment), `postprocess.py` (2 L, **passthrough
  stub**). **Absent:** `results.py`, `md_config.py` analogue, any
  visualization, any dedicated test file, `EXAMPLE_ENTRYPOINTS` (empty tuple).
- `cryostack_src/models/issm/results.py` (read in full): `SCHEMA =
  "cryostack.issm.results"`; `PREFERRED_FIELDS` keyed by ISSM *solution* names
  (`StressbalanceSolution` …); mesh = ISSM `x/y/z/elements`; `model_mat()` →
  `md_final.mat`; the field/solution/timestep model mirrors
  `md.results.<Solution>[i].<Field>`. The *container* shape
  (`outputs/{metadata.json,mesh,fields,model,figures}` + a schema string +
  a metadata-authoritative field list) is model-neutral; the *reader* and the
  field/solution vocabulary are ISSM science.
- Icepack science that has **no ISSM equivalent**: Firedrake function spaces
  (no `md` struct), `icepack.models.{IceStream,IceShelf,HybridModel}` +
  `icepack.solvers.FlowSolver` (`diagnostic_solve`/`prognostic_solve`), mesh
  from gmsh/Firedrake not ISSM triangulation, `CheckpointFile`/`.pvd` output.
  → a `cryostack.icepack.results` schema + its own reader is the correct shape,
  NOT reusing `cryostack.issm.results`.
- ICESEE (Phase C preview): already uses `build_icesee_app_menu()` (shared
  header from `a20ffd2`), `build_remote_connection_panel`,
  `build_slurm_resources_panel`, `shared_validation`, `UIRefreshCoordinator`.
  **Missing:** WorkspaceManager / per-user isolation / run-history /
  `ResultPackage` — ICESEE still writes `params.yaml` + uses the legacy
  `icesee_jupyter_book/core/cloud_runner.py`.

### B.status: SAFE SUBSET COMPLETE
Commits `132b8b1`, `a234078`, `1513267`, `e4cf471` (+ execution.py run-target
order). Icepack now: produces a structured `outputs/` package on every remote
run; the Results tab shows its figures/artifacts honestly; has a dedicated
adapter+results+postprocess+submission test suite (34 new tests); accurate
docs. Everything beyond this needs a scientific decision (see §B.discoveries
"Needs a scientific decision") and is left as a morning checkpoint. Deferred
low-risk-but-low-parity-value item: the gateway `if model=="issm"` UI toggle
cleanup (P2, exact line numbers in `AUDIT_icepack_parity.md`).

### B.next_action → Phase C.

### B.anticipated commit sequence (historical — superseded by B.status)
1. `models/icepack`: real `postprocess.py` + `EXAMPLE_ENTRYPOINTS`/discovery
   metadata parity with ISSM where model-neutral (no science invented).
2. `cryostack.results` dispatch: `discover_results` / result-package factory
   picks the reader by `metadata.json:schema`; ISSM path byte-for-byte
   unchanged; Icepack path returns a clear "not yet a structured package"
   until #3.
3. `models/icepack/results.py`: reader for whatever the curated Icepack
   examples actually emit — **gated on B-1 confirming the real output form**;
   if that needs a scientific call it becomes a morning checkpoint, not a guess.
4. run-history / provenance: confirm model-neutral; add Icepack coverage +
   tests.
5. docs + capability matrix: an honest Icepack section (what works, what is
   ISSM-only and why).

---

## Phase C — ICESEE toward the IceSheets platform standard

### C.objective
Audit ICESEE (`icesee_jupyter_book/ui/icesee_gateway.py`, the data-assimilation
app) against the now-mature IceSheets shell and adopt the reusable pieces
(WorkspaceManager isolation, run history, structured results, downloads,
validation) WITHOUT disturbing ICESEE's DA science (`params.yaml`,
`cloud_runner.py`, filter algorithms). Small green commits; stop before any DA
semantics change.

### C.known from coordinating-agent recon (pre-audit)
- ICESEE ALREADY uses: `build_icesee_app_menu()` (shared header, `a20ffd2`),
  `build_remote_connection_panel`, `build_slurm_resources_panel`,
  `shared_validation.validate_slurm_resources`, `shared_observer_guard
  .UIRefreshCoordinator`, `shared_ssh_widgets`, `shared_app_styles`. So B4 UI +
  B1–B3 access UX are already adopted.
- ICESEE does NOT use: `WorkspaceManager` (no per-user workspace isolation, no
  `_owner_root`), run history / `RunInfo` / manifest, `ResultPackage`,
  deterministic visualization, the download helpers. It writes `params.yaml`
  into a run dir and shells `cloud_runner.py`.
- ICESEE B2 (authenticated user × resource persistence) IS present
  (`resolve_workspace_user`, per-user settings at `icesee_gateway.py:1009`).

### C.delegation
- **Agent C-1** (`general-purpose`, read-only): audit ICESEE's execution /
  results / persistence path in depth and produce a "safe to adopt now" vs
  "needs DA-science care" split, mirroring the B-1 format.

### C.discoveries (Agent C-1, condensed — full report `AUDIT_icesee_platform.md`)
- **Already shared:** B4 UI panels, B1–B3 access UX, B2 settings persistence,
  remote transport / connector / identity gate / SSH-key mgr.
- **Biggest gap = B2-class:** ICESEE has **no per-user isolation for run
  artifacts**. `local_runner.run_dir()` → process-global
  `BOOK/icesee_runs/<second-ts>` + `mkdir(exist_ok=True)`. Two authenticated
  users in the same second **share the dir and overwrite each other**, and can
  read/delete each other's local runs. Remote-fetch cache is the same tree.
- **`RunInfo` / manifest / `RunHistory` accept `model="icesee"` + a stackless
  run with ZERO changes** (schema v2, `container`/`software` default `{}`,
  `manifest.py` comment already anticipates the ICESEE-Spack backend).
- **`WorkspaceManager` needs a ~5-line shim** — its `model` arg was expected to
  be a widget; ICESEE has no model dropdown.
- **Needs a design decision (agent must NOT decide):** what a "run" is for DA
  (one ensemble = one RunInfo?); the canonical ICESEE `outputs/` schema
  (forecast/analysis ensembles, mean/spread, RMSE/rank-histogram — nothing like
  the ISSM `ResultPackage`); whether local runs may keep writing into the
  canonical example `base`; a `cryostack-icesee` Batch image vs the
  user-supplied-image contract; EnKF params validation UI.
- **Genuinely ICESEE-specific (keep separate):** filter algorithm / `Nens` /
  seed / `params.yaml` auto-form / `run_da_*.py -F` / papermill report / the
  legacy `cloud_runner.py` user-image contract.

### C.decisions
- **D-C1:** `run_dir(base, name)` — parameterise, default unchanged.
- **D-C2:** `WorkspaceManager` `model: str | widget` via inert `_FixedChoice`.
- **D-C3:** Close the **security gap only** tonight — route ICESEE's
  `run_dir()` through `user_run_root(app="icesee")` (a new lightweight
  `workspace/roots.py`, no full manager). The full `WorkspaceManager` +
  `WorkspaceBridge.start_run` + `build_workspace_history_panel` adoption is a
  **reviewed follow-up** (needs the "what is a DA run" decision + touches the
  2877-line gateway too much for autonomous overnight work).

### C.tests_added
- `icesee_jupyter_book/core/tests/test_icesee_run_dir_isolation.py` (5)
- `cryostack_src/workspace/tests/test_manager_fixed_model.py` (4)
- `cryostack_src/workspace/tests/test_roots.py` (5)
- `icesee_jupyter_book/ui/tests/test_icesee_run_isolation.py` (3)

### C.results
- `3a7705f` (C-1 run_dir param), `1e68ae8` (C-2 fixed model), `c342f4f` (C-3
  per-user run dirs + `workspace/roots.py`).
- Full suite 980 passed / 1 skipped (+17 across C). Node 18. Book clean.
- ICESEE local/cloud/remote-fetch runs are now per-authenticated-user; two
  users can no longer collide or read each other's local runs.

### C.open_questions / next_action
- Full run-history adoption for ICESEE is the next reviewed step — needs the
  operator's call on "what is a DA run" and a defined DA `outputs/` schema.
- The remote-submit path (`submit_remote_example*`, 6 variants) still writes to
  a user-typed `remote_base_dir` — platform-unenforced. The B3 identity gate
  limits the blast radius (SSH login must match the configured HPC username)
  but two CryoStack users on one HPC account can still collide. Documented, not
  changed (touching 6 bespoke submit variants autonomously is out of risk
  budget).

---

# PASS 2 — deeper evidence-based Icepack + ICESEE (from HEAD 4c43040)

Operator brief: push Icepack toward real ISSM-level support using *repository
evidence* (canonical examples, adapters, Firedrake/Icepack APIs present,
container behaviour, output conventions) — do not stop merely because a
feature needs scientific understanding. Then continue ICESEE. Safe pieces only;
science/design checkpoints documented, not guessed.

## PASS 2 environment facts (coordinator recon)
- `/home/bkyanjo3/icepack` = upstream Icepack v1.1.0-ish. `notebooks/tutorials`
  (00-meshes-functions … 07-rgi-meshing, + solver-fail-debugging) and
  `notebooks/how-to` (01-performance … 04-sparse-data) are what
  `discover_icepack_examples` walks.
- `icepack`/`firedrake` NOT importable here → all Icepack code is mocked/tested
  structurally. Runtime lives only in `icesee-combined:v1.0.0` (firedrake
  2025.10.2).
- Tutorial notebooks are pedagogical: they build a gmsh mesh, define initial
  `h0`/`u0`, create `icepack.models.{IceShelf,IceStream,HybridModel}` +
  `icepack.solvers.FlowSolver`, then loop `prognostic_solve`/`diagnostic_solve`.
  Consistent scalar knobs seen: `T = firedrake.Constant(255.15)` (ice temp K)
  → `A = icepack.rate_factor(T)`; `final_time` / `num_timesteps` / `dt`;
  `a = firedrake.Constant(0.0)` (accumulation m/yr); friction `C` (ice-stream).
  **No params.yaml / no parameter-exposure convention** — knobs are cell
  literals.
- Outputs in the notebooks: `h` (thickness, CG2 scalar), `u` (velocity,
  vector CG2), `ε`/`ε_e` (strain, DG1 tensor/scalar), `D` (damage, DG1).
  Viz: `firedrake.tripcolor`, `firedrake.streamplot`.

## PASS 2 delegation
- **Agent I-Results** (`general-purpose`, read-only) → `AUDIT_icepack_results.md`
  (I2): per-field source-variable / Firedrake type / location / units /
  rank / static-vs-time / meaningful viz, from the actual notebooks + any
  output files + Firedrake's stable serialisation (`CheckpointFile`).
- **Agent C-Run** (`general-purpose`, read-only) → `AUDIT_icesee_run_contract.md`
  (C1): DA lifecycle boundaries already in the ICESEE code
  (`run_da_icepack.py`, `_icepack_enkf.py`, `params.yaml`, checkpoints, logs).
- **Agent C-Platform** (`general-purpose`, read-only) → appended to
  `AUDIT_icesee_platform.md` (C4/C5): remaining ICESEE↔IceSheets shell gaps +
  the exact legacy-`cloud_runner`→`CloudBridge` migration plan.
- **Coordinator** owns I1 (parameter spec — needs judgment already informed by
  reading the notebooks), all implementation, reconciliation, commits, tests.

## I1 — Icepack Basic-mode parameter architecture
### I1.objective
Typed, model-aware Icepack parameter spec (NOT a copy of ISSM `md` controls) +
a conservative override mechanism for the per-run working copy + validation +
provenance + docs. Implement only "safe Basic-mode override" params with
sufficient repo evidence.
### I1.next_action
Read `models/issm/md_config.py` for the spec *shape* to mirror (not content);
read `discover_icepack_examples` + `stage_example_for_run`; sample 3–4 tutorial
notebooks for the exact assignment patterns; build
`cryostack_src/models/icepack/parameters.py`.

### I1.results
- `8252c52` (adapter: `parameters.py`, classify/validate/apply_overrides, 23
  tests, docs) + `a1709f1` (gateway: `icepack_basic_panel.py` + second Basic
  accordion + fail-closed staging branch, 8 tests).
- Evidence: read notebooks 01/02/04-xy directly. `T = firedrake.Constant(<lit>)`
  and `num_timesteps = <int>` are the only cross-example scalar literals.
  Everything else (accumulation, friction C, fluidity A, dt, mesh res) is a
  spatial field / derived / stability-coupled -> classified, NOT exposed.
- Full suite 980 -> 1011 (+31). Node 18. Book clean.

## Delegation round 2 (PASS 2 audits — all returned)
- **I-Results** (`aa41b24be3b73e690`) -> `AUDIT_icepack_results.md`. HEADLINE:
  upstream tutorial notebooks write NOTHING to disk headless (inline figures
  thrown away). A structured package needs a **container-side Firedrake
  exporter**. Recommends plain-HDF5 (DOF + coords + connectivity) in the EXACT
  ISSM on-disk shape so `visualization/issm.py` triangulation code is reusable.
  Tier-1 = thickness/velocity/surface/bed, 2-D triangular, final state, CG1.
  8 owner decisions D-1..D-8.
- **C-Run** (`a3e2613e90d7cc092`) -> `AUDIT_icesee_run_contract.md`. A DA run =
  one `run_da_*.py -F params.yaml`. One ensemble = one run. `RunInfo`/manifest
  take `model="icesee"` + rich metadata with zero changes. Result hierarchy:
  `experiment -> series(ensemble|ensemble_mean|true_state|background_state|
  observations) -> variable_block -> spatial_index -> time_index [-> member]`.
  NO diagnostics exist. Hazard: default-mode ensemble lives in
  `_modelrun_datasets/`, not `results/`.
- **C-Platform** (`aa633909ea8faa9ac`) -> `AUDIT_icesee_platform_pass2.md`.
  Shell parity mostly done; delete bespoke CSS overlay + dead `build_sidebar`.
  **AWS Batch here is Fargate-only, single-container, NO multi-node MPI** —
  ICESEE MPI ensemble genuinely doesn't fit; OWNER ARCHITECTURE DECISION
  (ParallelCluster vs Batch-MNP-EC2 vs single-node small-ensemble vs EKS).
  Safe now: adopt `CloudBridge` as the interface with an injected submitter.
  Q1: 11 duplicated gateway helpers identified.

### PASS 2 decisions
- **D-I2/I3:** implement the container-side exporter (Firedrake code, mocked
  tests since no firedrake here) + `cryostack.icepack.results` schema v2 reader
  + `.msh` capture, using the conservative tier-1 reading of D-1..D-8. Flag for
  HPC validation. Collector stays non-fatal.
- **D-I4:** `visualization/icepack.py` as a thin adapter over
  `visualization/issm.py`; `_visualizer_for("icepack")` wired; flat field list
  (no synthetic solution) — D-1 resolved conservatively as "flat list".
- **D-I5:** local Icepack execution — Firedrake cannot be guaranteed outside
  the container on this box; document the unsupported state + requirements,
  ensure the UI never advertises it.
- **D-C:** ICESEE — implement the "safe now" C-Platform items (delete dead
  CSS/sidebar; adopt run history via `WorkspaceBridge.start_run` for
  local/remote/cloud with one `RunInfo` per run + the metadata from the
  run-contract audit). Do NOT touch the Results reader (needs the DA schema
  decision) or Cloud compute primitive (OWNER DECISION).

### I2/I3/I4.results
- `9fc38f2` (exporter `_export_core.py` + wiring + schema-v2 reader + `.msh`
  capture, 17 tests) + `b7b7488` (`visualization/icepack.py` +
  `_visualizer_for` wiring, 9 tests).
- Firedrake is not on this box -> the exporter is structurally tested with a
  mocked firedrake; the reader + visualizer are tested with real h5py fixtures.
  **The exporter needs an HPC/container validation pass** (morning) — its
  `runpy` namespace-scrape + CG1 interpolation + `cell_node_map().values`
  connectivity extraction are from the I-Results audit, not run here.
- D-1 resolved: flat field list under a single synthetic solution `"icepack"`
  (no panel change; `FieldInfo`-compatible metadata object).
- D-3 resolved conservatively: final-state only, tier-1 field allow-list.
- D-4/D-5/D-6/D-7/D-8 remain morning checkpoints (1-D/extruded meshes; tensor
  fields; inverse loss history; re-run vs fold-in; Firedrake version pin).

### I5 — Icepack local execution: EXPLICIT UNSUPPORTED STATE
- The IceSheets `execution_mode` dropdown offers **Remote** and **Cloud** only
  (`cryostack_src/frontend/cryolauncher/run_settings_state.py:70-72`);
  `cryostack_src/execution/manager.py` registers only `RemoteBackend` +
  `CloudBackend`. There is **no local execution backend for either model**.
- Firedrake/icepack are **not importable outside the tested container** (true on
  this dev box; true on a generic Voila host). Local Icepack would require
  `apptainer exec "$sif" with-icepack python …` on the workstation, i.e.:
  (a) a local execution backend in `cryostack_src/execution/`;
  (b) a guaranteed local apptainer + the `icesee-combined` SIF (or a local
      Firedrake+icepack install);
  (c) local per-user run isolation (already exists via `WorkspaceManager`);
  (d) the same structured-export step this PASS added, run locally.
- **The UI does not and must not advertise local Icepack execution.** Decision:
  do NOT implement it tonight — the Firedrake environment cannot be guaranteed
  and a local execution backend is a cross-cutting design change. Documented as
  a P1 (see MORNING_REPORT).
