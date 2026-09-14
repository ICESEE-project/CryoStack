# JOSS → NSF handoff

**Purpose.** The CryoStack JOSS paper is intended for submission first; the
NSF CSSI Elements proposal (Fall 2026) will then cite it as evidence of the
implemented foundation and move the funding argument to the remaining
scientific and cyberinfrastructure problems. This document classifies every
major capability by how firmly the JOSS paper can stand on it, and lists the
statements in the current proposal (`nsf-csi-proposal/`, read-only) that this
JOSS revision makes stale.

**Do not rewrite the proposal from this document.** It is input for that later
pass.

Repository HEAD: `a7e2790`. Proposal read: `sections/project_description.tex`,
`sections/project_summary.tex` (2 September 2026 state).

---

## 1. Capability classification

### A — Implemented and appropriate to establish in JOSS

These are stated in the paper as present, with code evidence, no qualifier
beyond normal research-software maturity.

| Capability | Evidence |
|---|---|
| Nginx + `aiohttp` gateway; unified routing of Jupyter Book, Voilà, React, static apps | `icesee_jupyter_book/ui/`, `deployment/applications.yaml` |
| Password (`scrypt`) + GitHub (PKCE) + ORCID auth behind a provider interface | `icesee_auth/` |
| SQLite persistence: users, sessions, identities, schema-versioned configs, workspaces, experiments, events; immutable config snapshot; timeline events | `icesee_auth/storage.py`, experiment bridges |
| Per-user workspace + run-directory isolation enforced by a containment check on a trusted identity | `cryostack_src/workspace/roots.py`, `workspace/files.py`; acceptance check |
| Role-based Control Center (developer/maintainer/administrator/owner) with assignment guardrails and audit events | `control_center/` |
| Dependency-aware deployment registry: order, cycle rejection, artifact/command checks, scoped restart, preflight + route health checks | `deployment/` + `applications.yaml` |
| CryoLauncher form-driven interface, strangler-migrated into panels + state objects; `ExecutionBackend` submit/status/logs/terminate contract | `cryostack_src/frontend/cryolauncher/`, `cryostack_src/execution/` |
| Model capability registry (ISSM, Icepack) with import-time consistency asserts against adapters, cloud runtime, visualization | `cryostack_src/models/capabilities.py` |
| ISSM + Icepack Basic-mode configuration into a per-run working copy; canonical examples read-only; non-finite values rejected | `cryostack_src/models/issm/md_config.py`, `cryostack_src/models/icepack/parameters.py` |
| Transport-neutral result packages (`cryostack.issm.results`, `cryostack.icepack.results`) with model-free readers and a shared reader/visualizer protocol; deterministic field/timeseries rendering | `cryostack_src/models/*/results.py`, `cryostack_src/models/results_common.py`, `cryostack_src/visualization/` |
| Connector + FastAPI relay (v2): outbound WebSocket, session bound to an authenticated CryoStack user, per-session pairing code + capability secrets, session supersession | `icesee_jupyter_book/core/connector_relay_server.py`, `icesee_hpc_connector/` |
| Typed connector operations: SSH, rsync up/down, archive stage/fetch, Slurm submit/query/cancel, log tail, public-key report | `icesee_hpc_connector/connector_core.py` |
| B3 remote-identity verification before a remote run; B4 Slurm-resource validation | `cryostack_src/remote/access_state.py`, `icesee_jupyter_book/ui/shared_validation.py` |
| Server-side SSH credentials namespaced by (user, resource, remote username) | `cryostack_src/remote/ssh_identity.py` |
| Remote Slurm execution: stage example, run dir, Spack or Apptainer env, batch script, `sbatch`, job-id parse, `squeue`/`sacct`/`scancel`, automatic log polling, result/figure bundles | `cryostack_src/remote/`, `cryostack_src/models/*/slurm.py` |
| LIVIST integrated as a first-class routed application with its own frontend + docs | `deployment/applications.yaml` |
| Frozen Legacies: manifest + adapter registration, catalog + GeoJSON build, flight segmentation, Antarctic map UI, LYRA adapter, ASTRA/ARIES/TERRA/URSA packaging | `icesee_jupyter_book/applications/frozen_legacies/` |
| No static cloud credentials; all AWS calls via the `aws` CLI | `cryostack_src/cloud/drivers/aws/auth.py`; acceptance check |
| Automated test suite over the shared layers (~1,280 Python tests + 208 agent tests + connector-page tests) and an offline read-only acceptance command | `pytest`, `cryostack_src/acceptance.py` |

**JOSS posture:** establish these plainly. The proposal can cite them as "prior
work / feasibility established" and must not describe them as future
deliverables.

### B — Implemented but requiring qualification / hardening

Stated in the paper as present **with an explicit qualifier**, and retained as
a named limitation.

| Capability | What works | Qualifier stated in JOSS |
|---|---|---|
| AWS Batch execution (ISSM) | config validation → MATLAB preflight → S3 staging → `submit-job` → job-id parse → run registration → status/logs/terminate | Not qualified on a controlled account: single account-wide bucket with no per-user object isolation; caller-supplied (not allow-listed) Batch job definition; no budget/quota/cleanup/failure-recovery; needs a MATLAB license the reference cloud profile lacks |
| Connector relay | session→user binding, capability secrets, supersession | Generic `shell` command type still exposed; state is process-local, not durable; sessions not bound to a registered resource policy with expiry/revocation; per-command replay/ownership/path checks incomplete; OTP key bootstrap passes a one-time secret through the hosted path |
| Icepack structured result exporter | schema-v2 package, model-free reader, visualization, graceful degradation | Container-side Firedrake exporter tested only against a mocked Firedrake; namespace scrape / first-order interpolation / connectivity not confirmed on a real run |
| Remote/cloud backend migration | `ExecutionBackend` contract, common result/status objects | Some paths delegate to legacy modules; remote logs not fully behind the contract; cloud lifecycle ops in a legacy AWS Batch module |
| Experiment persistence as provenance | immutable config snapshot, event timeline, job/cluster identifiers | Not archival: no environment digest, input/output checksums, transformation records, adapter versions, or exportable run manifest |
| Institutional HPC auth | connector reaches PACE | PACE rejects simple password auth; the multifactor/Duo path is not exercised; a real PACE run needs manual key registration today |
| Connector binaries | build/publish pipeline exists | Shipped binaries lag HEAD; must be rebuilt/republished before use behind the current relay |

**JOSS posture:** state the capability and the qualifier in the same breath (the
paper does). **NSF posture:** these are the natural O2/O3 hardening tasks —
the proposal should target the *qualifier*, not re-propose the capability.

### C — Prototype / experimental

Stated in the paper only in the "Experimental" section and the limitations, and
kept out of the abstract and Figure 1.

| Capability | State |
|---|---|
| Human-in-the-loop run assistant (agent layer) | `RunPlan` → validation → digest + input fingerprint → human approval → existing execution infra. Assistant hard-capped at PLAN; read-only tools only; no vendor SDK; deterministic `RuleBasedAdapter` ships. Opt-in Beta panel with no Submit button. |
| `RemoteSubmitBackend` (approved-plan → real remote submission) | Implemented, 15+ tests against fakes, composes the existing pipeline (B3/B4/preflight/stage/submit/register). **Not wired into the gateway.** |
| Agent cloud submission | Deliberately absent. Prerequisites documented: job-definition allow-list, re-derived MATLAB-license fact, per-user S3 prefix. |
| Additive experiment/sweep abstraction (`ExperimentPlan`/`SweepAxis`/`ManagedExperiment`) | In-memory only; no `ExperimentRepository`. |
| Provider adapter skeletons (Anthropic/OpenAI) | `NotImplementedError`, import no SDK, read no key. |

**JOSS posture:** one short section, explicitly experimental, "live
agent-driven submission is not enabled". **NSF posture:** if the proposal wants
to claim an agentic/assistant direction it can, but as *emerging* work building
on the digest-bound approval boundary that JOSS establishes — not as a shipped
feature.

### D — Not implemented; potentially appropriate NSF proposed work

Absent from the code; the paper mentions each only as future work / a
limitation, never as present.

| Item | Where JOSS acknowledges the gap |
|---|---|
| PISM (or any third) model adapter | Statement of Need cites PISM as external; capability registry has ISSM + Icepack only |
| Versioned, public application/model/dataset/observation-bundle SDK contracts with semantic versioning, deprecation rules, reference fixtures, templates | "formal adapter schemas" in the closing paragraph |
| CryoBench-style tiered scientific acceptance gate (analytic/restart/DA-diagnostic/scaling/SBOM tests as a promotion gate) | "scientific qualification tests"; offline acceptance is invariant checks, not science |
| `cryostack.icesee.results` schema + DA diagnostics (error/spread/innovations/increments/rank histograms) computed and persisted | explicit limitation "ICESEE result contract" |
| Allow-listed connector protocol replacing the generic shell channel; signed job envelopes; nonce/replay/ownership; per-experiment path canonicalization; resource-policy binding with expiry/revocation | "hardened connector … protocols"; connector-protocol-surface limitation |
| Least-privilege cloud: per-user S3 prefix + tightened IAM, job-definition allow-list, budgets/quotas/cleanup/cost attribution, failure recovery, bring-your-own-account path | "cloud qualification" limitation |
| Multi-node MPI cloud execution primitive for ICESEE ensembles (ParallelCluster / Batch-MNP / EKS-MPI) | "ICESEE … MPI ensembles … do not fit the current single-container Batch configuration" |
| Machine-readable archival provenance manifest binding code/adapter versions, image digests / Spack locks, input/output checksums, seeds, diagnostics; citation-ready exportable run bundle | Reproducible Experiment Lifecycle future-work paragraph |
| Transactional shared database + durable task/session store; versioned migrations | "persistence scale" limitation |
| Second Frozen Legacies dataset adapter; a browser-executable, provenance-captured radar-processing task | "expanded observational ingestion"; Frozen Legacies "does not yet execute every desktop workflow …" |
| Observation-bundle schema connecting a Frozen Legacies / LIVIST product to model initialization / assimilation | Frozen Legacies "practical path toward linking preserved observations …" (stated as a path, not done) |
| Real-account AWS qualification; independent security review; user-centered evaluation (SUS, WCAG); governance (contribution guide, code of conduct, maintainer rotation) | closing paragraph: "accessibility and user evaluation, documented operations, and community governance" |
| License reconciliation (MIT vs BSD-3-Clause) + SBOMs + license manifests | "This inconsistency should be reconciled before a formal platform release" |
| Container images republished under a project org account | "should be republished under a project account" |

**NSF posture:** this list is essentially the O1/O2/O3 task backlog. The
proposal is well aligned here; the adjustments below are about not
*understating* what JOSS now establishes.

---

## 2. NSF proposal statements that become stale once this JOSS revision is public

Section references are to `nsf-csi-proposal/sections/`. These are **flagged, not
edited.**

### `project_description.tex`

1. **§IM ¶2 — "CryoLauncher has working local and Slurm pathways"** — Slurm is
   right; a *local* execution pathway exists for ICESEE, not for CryoLauncher's
   ISSM/Icepack models. JOSS is precise about this; the proposal sentence
   should be tightened (e.g. "working Slurm and cloud pathways").

2. **§IM ¶2 — "modular AWS components" / "modularized AWS components" (also
   `project_summary.tex`)** — understates HEAD. There is an **end-to-end AWS
   Batch submission path for ISSM** (stage-to-S3, `submit-job`, job-id parse,
   run registration, status/logs/terminate). The proposal can still say it is
   not *qualified*, but "components" reads as less than what JOSS documents.

3. **§IM ¶3 / §SOK "Reproducibility, qualification, and proof of concept" —
   "shared platform tests are sparse"** — no longer accurate. ~1,280 tests
   cover the shared layers plus an offline acceptance command. The real gap is
   a *scientific* acceptance gate (CryoBench), not test sparsity. Reword to that
   effect.

4. **§SOK ¶ "Interfaces are not yet stable external SDKs; … the connector
   command channel is too broad for public use; credential, relay, and recovery
   semantics have not received external review; PISM is not integrated; AWS
   submission is not end-to-end qualified; provenance is not yet a stable
   cross-application schema"** — mostly still true, but:
   - "AWS submission is not end-to-end qualified" is fine; "AWS submission" full
     stop would be wrong — it exists.
   - "connector … too broad" — still true (generic `shell`), but the proposal
     should acknowledge relay v2 added user binding + capability secrets +
     supersession, so Task 2.1 starts from a higher baseline.
   - "credential … semantics have not received external review" — true; but B3
     namespaced SSH credentials and the no-static-AWS-credential design are
     implemented and should be named as the starting point.

5. **§SOK "Fragmented scientific software" — "CryoStack's new backend
   interfaces and frontend panels establish the code boundaries … but still
   wrap portions of the original monolithic implementations"** — accurate; keep.
   The capability registry is a further boundary worth naming.

6. **§SOK "Heterogeneous computing" — implies containers/Spack "do not supply
   job authorization, staging, monitoring, cancellation, recovery, or a
   portable record of execution"** — CryoStack *does* now supply staging,
   monitoring, cancellation, and (non-archival) execution records via the
   connector + experiment layer. The sentence is about containers/Spack in the
   abstract, so it is defensible, but the proposal should make clear CryoStack
   has already built the first version of that missing layer.

7. **§research "Task 1.1 — finish separating the current CryoLauncher panels,
   state objects, execution managers, remote drivers, cloud drivers, and
   container services from legacy gateway callbacks"** — still a real task; the
   proposal should note the panels/state-objects/`ExecutionBackend`/remote-
   driver split is largely done and the residual is legacy callback ownership +
   remote-log migration + cloud-lifecycle legacy module.

8. **§research "Task 2.2 — reconcile the present BSD/MIT metadata
   discrepancy"** — still open; JOSS now flags it explicitly, so it is public.

9. **§research "Task 3.1 — The current password/GitHub/ORCID identities, RBAC,
   saved configurations, workspaces, experiments, events, and Control Center
   demonstrate the service model in SQLite"** — accurate and well-phrased; keep.
   Add per-user isolation (containment check) as an established property.

10. **§research Figure 2 (proposed connector/relay architecture) —** the
    proposed diagram shows "outbound authenticated session, signed job
    envelopes, allow-listed stage/submit/query/cancel/recover operations". HEAD
    has the outbound authenticated session and the typed operations but **not**
    signed envelopes or a strict allow-list (generic `shell` remains). The
    figure is aspirational and labeled as such; no change needed, but the
    narrative should credit what exists.

11. **§"Results from prior NSF support" / §SOK — `\citep{cryostack2026}` and
    `\citep{kyanjo2026zenodo}`** — the proposal already cites a CryoStack
    artifact. Once the JOSS paper exists, the proposal should cite **the JOSS
    paper** as the primary description of the implemented platform and reserve
    the Zenodo DOI for the software artifact.

### `project_summary.tex`

12. **"advance CryoStack from a promising developer-operated stack" / "It is
    not yet a finished community service"** — framing is still correct. The
    enumerated feasibility list ("a modularized CryoLauncher interface, …
    a connector/relay path to Slurm, … and modular AWS components") should
    match the tightened JOSS wording: "an end-to-end AWS Batch path for one
    model (not yet qualified)".

13. **"end-to-end AWS runs … remain incomplete"** — keep, but pair with "the
    submission path is implemented; qualification on a controlled account
    remains".

### `delivery_mechanism_metrics.tex`, `facilities.tex`, `data_management_plan.tex`

14. Not re-audited line by line here. The metrics doc's Year-3 targets (5
    adapters, 100 users, 1,000 runs, etc.) are explicitly "targets for
    evaluation, not claims of current adoption" and are unaffected. The DMP's
    provenance-manifest description should be checked against the JOSS
    "Reproducible Experiment Lifecycle" future-work list for consistency when
    the proposal is revised.

---

## 3. The intended logic, restated for the proposal pass

```
implemented CryoStack (JOSS establishes: gateway, identity, per-user
    workspaces, experiments, Control Center, deployment registry, two model
    adapters + capability registry, structured results + visualization,
    connector relay v2 + B3 identities, remote Slurm execution, an ISSM AWS
    Batch path, an offline acceptance suite, an experimental approval-bound
    run assistant)
        │
        ▼
JOSS paper — feasibility + prior work, with every qualifier and limitation
    stated
        │
        ▼
remaining problems (this handoff, class B qualifiers + class D gaps):
    versioned SDK contracts · CryoBench scientific gate · PISM · ICESEE
    results schema + DA diagnostics · allow-listed hardened connector ·
    least-privilege qualified cloud + MPI cloud primitive · archival
    provenance + run bundles · shared transactional DB · second radar
    dataset + observation-bundle schema · security review · user evaluation ·
    governance
        │
        ▼
NSF CSSI Elements proposed work (O1 / O2 / O3)
```

**Rule for the proposal pass:** do not weaken a JOSS claim because the current
proposal calls something future work. Where JOSS now documents an
implementation (class A, or class B minus its qualifier), the proposal moves to
the *next* problem — the qualifier or the class-D gap — and cites JOSS for the
baseline.
