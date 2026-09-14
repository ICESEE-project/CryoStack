# AUDIT — CryoStack JOSS paper vs. repository at HEAD

**Repository HEAD:** `a7e2790` (branch `gatech_vm_backend`)
**Paper audited:** `paper/paper.md` as of the same date (dated 27 August 2026)
**Sources cross-checked:** `cryostack_src/`, `icesee_jupyter_book/ui/`,
`icesee_hpc_connector/`, `deployment/`, `control_center/`, `icesee_auth/`, and
the overnight reports/audits under `overnight/` (PASS 1–4).

This is an evidence audit. Every "current / outdated / new" call below is tied
to a file in the tree, not to a report. Reports were used to locate code, then
the code was read.

---

## 1. Method

1. Read the whole paper section by section.
2. For each factual claim, located the implementing code and confirmed it
   exists, does what the sentence says, and is not superseded.
3. Read the overnight PASS 1–4 morning reports, checkpoints, and the twelve
   `AUDIT_*.md` files; treated their conclusions as leads and re-verified in
   code (`cryostack_src.acceptance --offline`, direct file reads, `pytest
   --collect-only`, a full `pytest` run).
4. Classified each claim and recorded what the paper should say instead.

Full test/build state at audit time: **1278 passed, 1 skipped** across
`cryostack_src icesee_jupyter_book bin icesee_hpc_connector deployment`;
**18/18** on `deployment/tests/connect_page.test.mjs`;
`python -m cryostack_src.acceptance --offline` = **15 PASS / 0 FAIL / 2
MANUAL**. The LaTeX toolchain is not installed in the audit environment, so the
`paper/build_paper.sh` PDF build could not be executed here (see §7).

---

## 2. Claim-by-claim classification

Legend: **C** current · **O** outdated · **P** partially outdated ·
**N** newly implemented, not in paper · **X** experimental · **F** future work
(correctly stated as such).

### Summary / Abstract

| Claim | Class | Evidence / correction |
|---|---|---|
| "shared gateway rather than a single scientific code" | C | `icesee_jupyter_book/ui/`, `deployment/applications.yaml` |
| four applications: CryoLauncher, ICESEE, LIVIST, Frozen Legacies | C | `deployment/applications.yaml`, gateways |
| "persistent workspaces and experiments" | C | `icesee_auth/`, `cryostack_src/workspace/` |
| "evolving provider-independent cloud layer" | P | AWS Batch is now an implemented end-to-end path for ISSM (`icesheets_gateway.py:633–736`), not just "evolving". Reworded. |
| "A dependency-aware deployment registry builds … validates … restart scope … health checks" | C | `deployment/` engine + `applications.yaml` |
| abstract: "integration and production-hardening work that remains" | C | still the right framing |
| capability registry / structured results / acceptance suite | N | not mentioned at all; added |

### Statement of Need

Entirely **current**. ISSM/Icepack/DART/PDAF/ICESEE framing matches
`paper.bib` and the code. One nuance: "Model development may occur on a
workstation" is true in general but CryoLauncher itself has no local execution
mode for ISSM/Icepack (`run_settings_state.py:69` — Remote/Cloud only); local
execution is an ICESEE mode (`icesee_gateway.py:314`). Left the sentence as a
general statement of the research landscape, not a CryoLauncher claim.

### Software Architecture (intro + Figure 1)

| Claim | Class | Evidence / correction |
|---|---|---|
| "identity and experiment persistence live outside the applications" | C | `icesee_auth/`, bridges in gateways |
| "Control Center reads shared operational state" | C | `control_center/` |
| "CryoLauncher is being decomposed into frontend panels and backend managers" | C | `cryostack_src/frontend/cryolauncher/panels/`, `cryostack_src/execution/` |
| "cloud-provider code implements abstract driver contracts" | C | `cryostack_src/cloud/drivers/`, `cryostack_src/execution/cloud.py` |
| "deployable applications are declared in a registry" | C | `deployment/applications.yaml` |
| per-user workspace isolation via containment check | N | `cryostack_src/workspace/roots.py` (`owner_root`), `workspace/files.py` containment; not in paper — added |
| model capability registry | N | `cryostack_src/models/capabilities.py` with import-time `_verify_against_adapters()`; not in paper — added a subsection |
| Figure 1 caption: "AWS execution path is modularized but remains under active end-to-end integration with CryoLauncher" | O | The launch callback now performs a full submit + run registration. Caption reworded to "implemented for ISSM and awaits qualification on a controlled account". |
| Figure 1 image content "ISSM · Icepack · flowline · L96" | O | The model registry is ISSM + Icepack only (`cryostack_src/models/__init__.py`, `capabilities.py`). **Figure image must be corrected — see §5.** |

### Gateway, routing, process composition

**Current.** `deployment/applications.yaml` matches the described fields
(dependencies, working_directory, build, artifacts, routes, health, restart
scope). Preflight/health tooling present in `deployment/`.

### Identity, workspaces, experiment persistence

| Claim | Class | Evidence / correction |
|---|---|---|
| scrypt passwords; GitHub PKCE; ORCID state-bound flow; provider interface; HTTP-only cookies; same-site redirects | C | `icesee_auth/` |
| SQLite, FK enforcement, WAL; users/sessions/identities/configs/workspaces/experiments/events; immutable config snapshot; timeline events; application bridges | C | `icesee_auth/storage.py`, experiment bridge modules |
| per-user isolation of workspace + run directories | N | `cryostack_src/workspace/roots.py`; ICESEE per-user run roots (`user_run_root`, PASS-1); acceptance check `workspace: distinct users get distinct roots`. Added a paragraph. |
| "does not yet capture every environment digest, input checksum, or scientific diagnostic" | C/F | correct and retained |

### Control Center and RBAC

**Current.** `control_center/` dashboard, user/experiment/diagnostic views,
role hierarchy (developer/maintainer/administrator/owner), assignment
guardrails, audit events all present. "AWS environment information is present"
diagnostic confirmed. Future-work sentence retained.

### CryoLauncher

| Claim | Class | Evidence / correction |
|---|---|---|
| "registry includes ISSM, Icepack, a one-dimensional flowline model, and Lorenz-96" | **O** | The registry is **ISSM and Icepack** (`run_settings_state.py:91`, `models/__init__.py`, `capabilities.py`). No flowline adapter exists (`grep` finds only a comment). Lorenz-96 is an ICESEE tutorial (`icesheets_gateway.py:302` links `run_lorenz96_da`). Rewritten. |
| form-driven selection of model/example/target/environment/mode/resources; command preview; status; logs; output+figure packaging | C | gateway + `cryostack_src/frontend/cryolauncher/` |
| strangler migration into panels + state objects | C | `panels/`, `run_settings_state.py`, `runtime_state.py` |
| `ExecutionBackend` contract (submit/status/logs/terminate); remote+cloud wrappers; connector vs direct SSH drivers; provider-independent container metadata; "some paths still delegate to legacy modules"; "remote log handling has not yet fully migrated" | C | `cryostack_src/execution/`, `cryostack_src/remote/drivers/`, `cryostack_src/models/stack/` |

### ICESEE

**Current**, with one addition: the paper did not say ICESEE lacks a structured
result contract. `overnight/AUDIT_icesee_results_contract.md` + a direct read
of `external/ICESEE/` confirm: no manifest, no run-directory abstraction, no
provenance record, DA diagnostics not persisted. Added a sentence; also a
retained limitation.

### LIVIST

**Current.** React/TS frontend + docs built via `deployment/applications.yaml`
(`livist`, `livist-docs`). "Not a LiDAR application" clarification retained.

### Frozen Legacies

**Current.** `icesee_jupyter_book/applications/frozen_legacies/` build steps
(`build_antarctica`, `build_geojson`), manifest+adapter registration, catalog +
GeoJSON + flight segmentation, map UI, LYRA adapter, ASTRA/ARIES/TERRA/URSA
tool packaging. "does not yet execute every desktop workflow as a
browser-native, provenance-captured service" retained.

### HPC Connector and Remote Execution

| Claim | Class | Evidence / correction |
|---|---|---|
| local + direct + connector + automatic modes; institution keeps auth/policy | C | `cryostack_src/remote/` |
| "receives a random session identifier and WebSocket path" | P | Relay v2 also issues a `pairing_code`, a `control_secret`, and a `session_secret`, and binds the session to `owner_user_id` (`icesee_jupyter_book/core/connector_relay_server.py:57,74–77,125–167,264–270`). Rewritten steps 1–4. |
| Nginx → FastAPI/Uvicorn relay; tracks online connectors + pending futures | C | `connector_relay_server.py`, `deployment/applications.yaml` connector runtime |
| connector operations: host checks / SSH / rsync / archive / Slurm submit / squeue-sacct-scancel / log tail / public-key / key bootstrap | C | `icesee_hpc_connector/connector_core.py:142–172` |
| remote launchers: stage example, run dir, Spack or Apptainer, batch script, sbatch, parse job id, lifecycle | C | `cryostack_src/remote/`, `cryostack_src/models/*/slurm.py` |
| "Recent CryoLauncher changes add automatic log polling, experiment-status updates, and result/figure bundles" | C→C | true; reworded to present tense (no longer "recent") |
| B3 namespaced SSH identities (user × resource × hpc-username) | N | `cryostack_src/remote/ssh_identity.py::credential_namespace`; not in paper — added a sentence |
| "The relay never opens SSH connections itself. Private keys remain on the workstation" | C | `connector_relay_server.py` has no SSH; keys are workstation-side |
| "Generic shell execution is still present" | C | `icesee_hpc_connector/connector_core.py:143` (`shell` command type), `connector.py:151` (`/shell`) |
| "connector sessions are not yet durably bound to authenticated user and resource policy" | **P** | Now bound to an authenticated CryoStack user + capability secrets, but **in-memory** and **not** bound to a registered resource policy with expiry/revocation. Reworded precisely. |
| "pending commands live in one relay process" | C | in-memory dict in `connector_relay_server.py` |
| one-time password bootstrap passes a secret through the hosted path | C | connector bootstrap flow; retained |
| Figure 2 caption "correlates session-scoped requests in memory" | P | Add that it now binds to an authenticated user + issues per-session capability secrets; still single-process. Caption updated. |

### Cloud and Container Architecture

| Claim | Class | Evidence / correction |
|---|---|---|
| abstract cloud/execution interfaces; AWS driver: identity+capability, VPC/subnet/SG/IAM/S3/ECR/Batch discovery+prep, submit/status/log/terminate, URI storage/registry metadata | C | `cryostack_src/cloud/drivers/aws/`, `cryostack_src/cloud/` |
| S3 default encryption + block public access; ECR discover/prepare; Docker build/tag/push separated from AWS | C | `cryostack_src/cloud/drivers/aws/storage.py`, `.../ecr*`, `cryostack_src/models/stack/` |
| "the current CryoLauncher launch callback still marks end-to-end model-only AWS submission as the next integration step" | **O** | No such marker remains. `_submit_cloud_run` (`icesheets_gateway.py:633`) validates config, runs `cloud_run_preflight` (MATLAB gate), stages a working copy to S3, calls `current_cloud_bridge().submit(...)` (→ `AWSDriver.submit` → `stage_run_inputs` + `submit_batch_job` via the `aws` CLI), parses `jobId`, and registers a `RunInfo` (`backend="aws"`, `execution_mode="cloud"`). Rewritten. |
| "not a fully qualified one-click cloud service" | C | still true; reframed as the specific qualification gaps (per-user S3, job-def allow-list, budget/quota/cleanup/recovery) — from `overnight/AUDIT_agent_cloud.md` §S3/§job-definition, re-verified in `cryostack_src/cloud/drivers/aws/staging.py`, `submit.py`, `iam_policies.py` |
| no static credentials / `aws` CLI only | N | acceptance check `cloud: execution is ISSM-only and no static credentials`; `cryostack_src/cloud/drivers/aws/auth.py` — added |
| cloud is ISSM-only (ICESEE MPI ensemble does not fit) | N | `cryostack_src/cloud/runtime.py:50` `SUPPORTED_CLOUD_MODELS=("issm",)`; `capabilities.py` import assert; added |
| Spack + Apptainer strategies; `[@gamblin2015spack]`, `[@kurtzer2017singularity]`; container publication; "Apptainer runtime path remains partly in the legacy remote runner" | C | `cryostack_src/models/stack/`, `cryostack_src/remote/` |
| container images under a personal Docker Hub namespace | N | acceptance MANUAL check; `cryostack_src/models/stack/container.py:22`, `images.py:52` — added a clause |

### Reproducible Experiment Lifecycle

**Current.** Steps 1–6 match the gateway + bridges. Added that ISSM/Icepack
step 6 now yields the structured result package + visualizations. Future-work
paragraph (immutable digests, checksums, manifests) retained verbatim in intent.

### Availability, Verification, and Limitations

| Claim | Class | Evidence / correction |
|---|---|---|
| MIT + BSD-3-Clause identifiers in modularized files; "reconcile before a formal release" | C | `run_settings_state.py:20` SPDX BSD-3-Clause; retained |
| "application-level tests in ICESEE, LIVIST, and parts of the Frozen Legacies tools, but the new shared … layers do not yet have a complete automated integration suite" | **P** | Understated. ~1,280 Python tests now cover the gateway, auth, Control Center, frontend panels, adapters, connector, cloud, deployment; 208 agent tests; 18 connector-page node tests; plus the offline acceptance command. Rewritten to describe the suite and what it does *not* cover (scientific correctness, live infra). |
| offline acceptance command | N | `cryostack_src/acceptance.py` — added |
| "remote backend still delegates … legacy modules; remote logs have not fully moved …; execution manager migration is incomplete" | C | retained; added "cloud lifecycle operations delegate to a legacy AWS Batch module" (`cryostack_src/cloud/legacy/aws_batch.py`) |
| "AWS implementation requires an end-to-end qualified CryoLauncher workflow, failure-recovery tests, cost and quota controls, and cleanup policy" | P | The workflow now exists; the qualification items remain. Reworded as a limitation about qualification on a controlled account. |
| connector security limitations (broad shell ops; process-local state; OTP bootstrap; ownership/policy/path/replay/audit/redaction) | C | retained; trimmed the ones now partly addressed (session→user binding) |
| SQLite → transactional shared DB + durable store for scale | C | retained |
| closing paragraph (formal schemas, qualification tests, hardened protocols, provenance, ingestion, accessibility, operations, governance) | C | retained |
| PACE / Duo / institutional auth | **missing** | The paper did not carry this limitation explicitly; PASS 1–4 all mark it OWNER_CHECKPOINT and `acceptance` marks it MANUAL. Added. |
| connector binaries need rebuild/publish when behind HEAD | **missing** | `overnight/MORNING_REPORT*` (“no Connector publish”), memory `connector-packaging`. Added. |
| Icepack Firedrake exporter needs real HPC/container validation | **missing in Limitations** | Mentioned indirectly; PASS 2/4 OWNER_CHECKPOINT. Added explicitly. |

### Not in the paper at all — the agent layer

`cryostack_src/agents/` (17 modules) + `cryostack_src/agent_execution/`
(`RemoteSubmitBackend`, `DryRunSubmitBackend`). **Experimental (X).** Added a
short "Human-in-the-Loop Run Assistance (Experimental)" section and two
limitation bullets. It is deliberately *not* made a headline capability and is
absent from Figure 1. See §4.

---

## 3. Summary of classifications

- **Outdated (must change):** CryoLauncher model list (flowline/L96); cloud
  "next integration step" language; Figure 1 caption + Figure 1 image model
  list; "cloud layer is evolving" framing.
- **Partially outdated (nuance/expand):** connector session-to-user binding;
  Figure 2 caption; test-coverage description; AWS "requires … qualified
  workflow".
- **Newly implemented (add):** capability registry; per-user workspace/run
  isolation via containment; structured result packages + shared reader/
  visualizer protocol; Icepack Basic mode + exporter + reader + visualization;
  B3 namespaced SSH identities; connector relay v2 capability secrets +
  ownership; end-to-end ISSM AWS Batch path; `aws`-CLI/no-static-creds;
  cloud ISSM-only restriction; offline acceptance command; the agent layer
  (experimental).
- **Correctly future/limitation (keep):** archival provenance fields; ICESEE
  results contract; connector hardening; SQLite scale; MATLAB licensing;
  license reconciliation; scientific qualification.

---

## 4. The agent layer — how it was evaluated and what the paper says

Inspected `cryostack_src/agents/{planning,approval,execution,assistant,
permissions,policy,registry,readonly_tools,planning_tools,fingerprint,store,
llm,llm_adapters,trace,trace_store,experiment,eval,inspect}.py` and
`cryostack_src/agent_execution/remote_backend.py`, their 208 tests, and the
overnight documents `AGENT_SAFETY_MODEL.md`, `AGENT_LLM_PROVIDER_CONTRACT.md`,
`AUDIT_agent_*.md`, `AUDIT_pass4_adversarial_review.md`.

Confirmed in code:

- The architecture is exactly: request → `RunPlan` → `validate_run_plan`
  (B3 `enforce_remote_access`, B4 `validate_slurm_resources`, model Basic-mode
  validator, model/backend preflight) → `RunPlan.digest()` over scientific +
  resource fields + optional `RunInputFingerprint` over input *content* →
  human `approve()` → `DryRunExecutionCoordinator` / `RemoteSubmitBackend`
  composing the existing remote pipeline.
- The assistant is hard-capped at `Permission.PLAN` (`assistant.py:31,91`);
  `AssistantResult.submitted` is always `False`.
- Shipped tools are all OBSERVE/PLAN and read-only; acceptance checks
  `no shipped tool takes a user_id/owner argument`, `every shipped tool is
  OBSERVE/PLAN and read-only`, `no SubmitBackend implementation inside
  cryostack_src/agents` (AST), `provider adapters import no vendor SDK / key /
  network`.
- No LLM vendor SDK anywhere in `cryostack_src`; `RuleBasedAdapter` is the
  shipped deterministic implementation.
- The gateway panel is opt-in behind `CRYOSTACK_AGENT_PANEL`
  (`icesheets_gateway.py:3019`), collapsed, with no Submit button, and any
  build failure is swallowed so the gateway still renders.
- `RemoteSubmitBackend` exists and is tested against fakes but is **not**
  imported or constructed anywhere in `icesee_jupyter_book/` — not wired.

Paper treatment: one section, ~200 words, explicitly "Experimental";
"Live agent-driven submission is therefore not enabled"; two limitation
bullets. Not in Figure 1. Not in the abstract. This matches the task
constraint that the agent layer must not dominate.

---

## 5. Figure audit

**No committed, reproducible figure-generation mechanism exists.** `paper/`
contains hand-authored SVG sources (`cryostack_architecture.svg`,
`cryostack_hpc_bridge.svg`) and PNGs, but `build_paper.sh` only builds the PDF
from `paper.md`; there is no SVG→PNG step, Makefile target, or script. Per the
task, the figures are **left for Brian's review** and the required changes are
documented here. (`rsvg-convert` happens to be installed in this environment,
and the architecture PNG is pixel-for-pixel the SVG viewBox at scale 1, so a
`rsvg-convert -w 1400 cryostack_architecture.svg -o cryostack_architecture.png`
would regenerate it — but that is not a repository mechanism and was not run.)

### Figure 1 — `cryostack_architecture.svg` / `.png`

Required (factual):
- **CryoLauncher box, line 43:** `ISSM · Icepack · flowline · L96` →
  `ISSM · Icepack`. The registry no longer has a flowline model or Lorenz-96.

Recommended (accuracy / completeness), Brian's call:
- **Execution row, AWS box (lines 86–88):** `AWS (integration in progress)` /
  `Discovery/provisioning/lifecycle modules` → e.g. `AWS Batch (ISSM)` /
  `S3 staging · submit-job · lifecycle · qualification pending`.
- **Shared services box (lines 69–71):** add "capability registry · result
  packages · visualization" alongside the existing "backend-independent
  results/status".
- The agent layer is correctly **absent**; keep it out of this figure. If it
  is ever shown, it belongs as a thin advisory box feeding the run-planning
  input of CryoLauncher, never as a peer of the execution backends.

### Figure 2 — `cryostack_hpc_bridge.svg` / `.png`

Recommended (nuance), Brian's call:
- **FastAPI relay box (lines 53–57):** `session registry` → `session registry
  (per-user, capability secrets)`; the "pending futures / internal port 8899 /
  Uvicorn" content is still accurate.
- Everything else (zones, steps 1–6, "No inbound connection" footer) is
  accurate at HEAD.

The paper's Figure 1 and Figure 2 **captions** in `paper.md` have been updated
to match HEAD; the **images** have not been modified.

---

## 6. References audit

- All eight `\@cite` keys used in `paper.md` resolve to entries in `paper.bib`;
  no unused entries; no invented entries.
- `kyanjo2026icesee` is a preprint (EGUsphere, `doi:10.5194/egusphere-2026-2037`,
  `note = {Preprint}`). **Flag for Brian:** update to the final published
  reference (journal, volume, pages) once available. It is consistent with the
  same citation in `nsf-csi-proposal/references.bib`.
- No new references were added. If the capability-registry / result-contract
  design is later written up, a self-citation to the CryoStack archival release
  (Zenodo DOI) would be appropriate — **left for Brian**, not added.
- `[@kluyver2016jupyter]`, `[@gamblin2015spack]`, `[@kurtzer2017singularity]`
  are used exactly where the corresponding technology is described; retained.

---

## 7. Build / verification status

| Check | Result |
|---|---|
| `paper.md` front matter parses (YAML) | OK; `date` bumped to 2 September 2026 |
| All citations resolve to `paper.bib` | OK (8/8) |
| Both figure files referenced exist | OK |
| Markdown structure (headings, lists, image syntax) | OK; single `# References` trailer preserved for the JOSS/Pandoc path |
| `paper/build_paper.sh` PDF build | **NOT RUN** — no `pdflatex`/`xelatex`/`tectonic`/`pandoc` in the audit environment. The wrapper (`paper_wrapper.tex`) and script are unchanged in structure; the last committed intermediate build artifacts are under `paper/output/`. Brian must run `bash paper/build_paper.sh` on a machine with TeX Live. |
| Full Python test suite | 1278 passed, 1 skipped |
| `deployment/tests/connect_page.test.mjs` | 18/18 |
| `python -m cryostack_src.acceptance --offline` | 15 PASS / 0 FAIL / 2 MANUAL |
| Repository code modified for the paper? | **No.** Paper-only pass. |

---

## 8. OWNER_CHECKPOINT items surfaced by this audit

1. **Figure 1 image** still says "flowline · L96" — must be corrected before
   submission (text edit to `cryostack_architecture.svg` + re-render).
2. **Figure captions vs images** — captions in `paper.md` now describe HEAD;
   the SVG/PNG images are unchanged. Reconcile.
3. **`kyanjo2026icesee`** preprint → final reference when published.
4. **License reconciliation** (MIT vs BSD-3-Clause) is still an open repo task
   the paper now flags twice; resolve in the repo, not the paper.
5. **PDF build** must be run by Brian on a TeX-capable machine and the result
   reviewed for overfull boxes / figure placement / bibliography rendering.
6. The paper says "approximately 1,280 Python tests" — if Brian prefers an
   exact number, it is **1278 passed, 1 skipped** at `a7e2790`; this will drift,
   so the approximate phrasing is intentional.
