# JOSS revision notes

Revision of `paper/paper.md` (and `paper/paper_wrapper.tex`) to the CryoStack
implementation at HEAD `a7e2790`. Paper-only pass: no runtime, scientific, or
deployment code was changed. Companion documents:
`paper/AUDIT_JOSS_CURRENT_STATE.md`, `paper/JOSS_TO_NSF_HANDOFF.md`.

---

## 1. Old paper structure

```
Summary
Statement of Need
Software Architecture
  Gateway, routing, and process composition
  Identity, workspaces, and experiment persistence
  Control Center and role-based administration
Scientific Applications
  CryoLauncher
  ICESEE
  LIVIST
  Frozen Legacies
HPC Connector and Remote Execution
Cloud and Container Architecture
Reproducible Experiment Lifecycle
Availability, Verification, and Limitations
Acknowledgements
```

## 2. New paper structure

```
Summary                                     (updated)
Statement of Need                           (unchanged in substance)
Software Architecture
  Gateway, routing, and process composition (unchanged in substance)
  Identity, workspaces, and experiment persistence
                                            (+ per-user isolation paragraph)
  Model capability registry                 (NEW subsection)
  Control Center and role-based administration (unchanged in substance)
Scientific Applications
  CryoLauncher                              (model list corrected; strangler kept)
  Ice-sheet models: ISSM and Icepack        (NEW subsection)
  ICESEE                                    (+ "no shared results contract" sentence)
  LIVIST                                    (unchanged)
  Frozen Legacies                           (unchanged in substance)
Results, Packaging, and Visualization       (NEW section)
HPC Connector and Remote Execution          (relay v2, B3 identities, tighter limits)
Cloud and Container Architecture            (ISSM AWS Batch path is implemented)
Reproducible Experiment Lifecycle           (step 6 mentions result packages)
Human-in-the-Loop Run Assistance (Experimental)  (NEW section, ~200 words)
Availability, Verification, and Limitations (test suite + acceptance; limits list)
Acknowledgements                            (unchanged)
```

Word count: ~3,900 → ~5,000. Section count 11 → 14 (three new: capability
registry subsection, results section, experimental agent section; plus an ISSM/
Icepack subsection).

## 3. Major factual updates

1. **CryoLauncher model registry.** "ISSM, Icepack, a one-dimensional flowline
   model, and Lorenz-96" → **ISSM and Icepack**, per
   `cryostack_src/models/capabilities.py` / `models/__init__.py` /
   `run_settings_state.py:91`. Lorenz-96 is attributed to ICESEE (where it
   already was in the ICESEE paragraph). No flowline adapter exists in the tree.

2. **AWS cloud.** The paper said the launch callback "still marks end-to-end
   model-only AWS submission as the next integration step." That marker is gone.
   The Cloud section now describes the implemented path: validate config → MATLAB
   preflight → stage a user-owned working copy to S3 → `aws batch submit-job` →
   parse job id → register the run; status/logs/termination via the common
   result. Restricted to ISSM. Not qualified (per-user S3 isolation,
   job-definition allow-list, budget/quota/cleanup/recovery all absent).

3. **No static cloud credentials.** New sentence: all AWS calls go through the
   `aws` CLI with ambient credentials; no static keys, no long-lived credential
   created (`cryostack_src/cloud/drivers/aws/auth.py`; acceptance check).

4. **Cloud is ISSM-only.** New: ICESEE's multi-node MPI ensembles do not fit the
   single-container Batch configuration (`cloud/runtime.py:50`).

5. **Connector relay v2.** Session now bound to an authenticated CryoStack user
   (`owner_user_id`), with a one-time pairing code plus per-session
   `control_secret` / `session_secret`, and supersession of a user's earlier
   session. The four-role walkthrough and Figure 2 caption were rewritten.

6. **B3 namespaced SSH identities.** New sentence: server-side SSH credentials
   for a resource are namespaced by (CryoStack user, resource, remote username)
   (`cryostack_src/remote/ssh_identity.py`).

7. **Connector limitation, tightened.** "connector sessions are not yet durably
   bound to authenticated user and resource policy" → sessions **are** bound to
   an authenticated user with capability secrets, but the binding is in-memory
   and not tied to a registered resource policy with expiry/revocation. Generic
   `shell` command type still present — retained.

8. **Per-user workspace/run isolation.** New paragraph in Identity/workspaces:
   trusted identity from the session (never client-supplied); owner root per
   user; containment check on file operations; canonical examples read-only;
   per-user remote and local run directories.

9. **Model capability registry.** New subsection: one authoritative statement
   per model (Basic-mode subset, structured-results contract, offline reader,
   visualization, MATLAB requirement, execution modes/backends), with
   import-time asserts against the adapters, cloud runtime, and visualization.

10. **Structured results + visualization.** New section. `outputs/` package with
    schema id + version; graceful degradation; model-free readers (no MATLAB for
    ISSM, no Firedrake for Icepack); shared reader/visualizer protocol;
    deterministic rendering; results panel dispatches through the protocol.
    Icepack exporter linearizes Firedrake fields to first order and records it;
    still needs real-run confirmation.

11. **ISSM / Icepack Basic mode.** New subsection. ISSM: solver-aware `md`
    parameters appended to a working-copy MATLAB step. Icepack: ice temperature
    + timestep count via exact fail-closed literal substitution; derived-value
    examples refused pre-submission. Non-finite values rejected by both.

12. **Verification.** "application-level tests in ICESEE, LIVIST, and parts of
    the Frozen Legacies tools" → the shared layers are covered by ~1,280 Python
    tests + 208 agent tests + a browser connector-page test set, all passing at
    HEAD, plus `python -m cryostack_src.acceptance --offline` (read-only
    invariant checks; 15 PASS / 0 FAIL / 2 MANUAL). What is *not* covered:
    scientific correctness, live infrastructure paths.

13. **Reproducible lifecycle.** Step 6 now notes ISSM/Icepack outputs include
    the structured result package and its visualizations.

14. **Abstract / Summary.** Reworked to name per-user workspaces, the capability
    registry / result contract, connector capability secrets, and the ISSM AWS
    Batch path; dropped "evolving provider-independent cloud layer" as the
    headline phrasing.

## 4. Newly documented capabilities (were absent from the paper)

- Model capability registry with consistency asserts.
- Per-user workspace + run-directory isolation via a containment check.
- Transport-neutral result packages + model-free readers + shared
  reader/visualizer protocol + deterministic visualization.
- Icepack Basic-mode configuration, container-side exporter, offline reader,
  visualization.
- B3 namespaced SSH credentials.
- Connector relay v2: session→user binding, pairing code, per-session
  capability secrets, supersession.
- End-to-end ISSM AWS Batch submission path; `aws`-CLI-only / no static creds;
  cloud ISSM-only restriction.
- Offline acceptance command.
- Experimental human-in-the-loop run assistant (its own section + limitations).

## 5. Claims removed or softened

- **Removed:** CryoLauncher "one-dimensional flowline model, and Lorenz-96" from
  the model registry.
- **Removed:** the "AWS submission … next integration step" framing.
- **Softened → strengthened:** cloud "evolving / modularized" → "implemented for
  ISSM, awaits qualification".
- **Softened → precise:** connector "not durably bound to authenticated user and
  resource policy" → bound to a user with capability secrets, but in-memory and
  not to a resource policy.
- **Softened → precise:** "the new shared … layers do not yet have a complete
  automated integration suite" → they have a substantial suite; scientific
  correctness and live paths are what remain unverified.
- **Figure 1 caption:** "modularized but remains under active end-to-end
  integration" → "implemented for ISSM and awaits qualification on a controlled
  account".
- **Figure 2 caption:** "correlates session-scoped requests in memory" → "binds
  each session to an authenticated CryoStack user and issues per-session
  capability secrets; still holds that state in a single process".

## 6. Limitations retained (verified against code, not just reports)

- Archival provenance fields not captured (env digests, checksums,
  transformation records, adapter versions, exportable manifests).
- ICESEE has no CryoStack result-package schema / run directory / provenance;
  DA diagnostics not persisted (`overnight/AUDIT_icesee_results_contract.md`
  + `external/ICESEE/` read).
- Icepack Firedrake exporter tested only against a mock; needs real
  HPC/container validation.
- Connector generic `shell` command type; process-local relay state; unbound
  one-time password bootstrap; missing per-command replay/ownership/path/audit
  enforcement.
- Remote backend delegates to legacy modules; remote logs not fully behind the
  contract; cloud lifecycle ops in a legacy module.
- AWS path not qualified on a real account (per-user S3, job-def allow-list,
  budget/quota/cleanup/recovery, cost attribution).
- MATLAB licensing blocks ISSM container + cloud where no license is
  configured; reference cloud profile has none.
- SQLite adequate for single-node; scale needs a transactional shared DB +
  durable task/session store.
- MIT vs BSD-3-Clause license identifiers disagree; reconcile before release.

Limitations **added** (were missing or only implicit):

- PACE institutional authentication / multifactor (Duo) not exercised;
  a real PACE run needs manual key registration today.
- Packaged connector binaries lag HEAD and must be rebuilt/republished before
  use behind the current relay.
- Agent execution: `RemoteSubmitBackend` implemented but not wired; direct-SSH
  agent submit blocked (shared service identity); agent cloud submission
  deliberately absent.
- Container images under a personal registry namespace; republish under a
  project account.

## 7. Figure changes

**No figure image was modified.** There is no committed, reproducible
figure-build mechanism in the repository (`build_paper.sh` builds only the PDF
from `paper.md`; the SVGs are hand-authored and there is no SVG→PNG step). Per
the task, figure edits are left for Brian's review. Only the **captions** in
`paper.md` were updated (see §5).

Required and recommended image edits are enumerated in
`AUDIT_JOSS_CURRENT_STATE.md` §5. The one **required** change:

- `cryostack_architecture.svg` line 43: `ISSM · Icepack · flowline · L96` →
  `ISSM · Icepack`, then re-render the PNG.

`rsvg-convert` is available in the current environment and the architecture PNG
is the SVG viewBox at scale 1 (`rsvg-convert -w 1400 cryostack_architecture.svg
-o cryostack_architecture.png`), but this is not a repository-provided
mechanism and was not run.

## 8. Bibliography changes

**None.** All eight citation keys in `paper.md` resolve to existing
`paper.bib` entries; no entries added, removed, or altered.

Flag for Brian: `kyanjo2026icesee` is a preprint (`note = {Preprint}`,
`doi:10.5194/egusphere-2026-2037`). Update to the final published reference when
available. It matches the same key in `nsf-csi-proposal/references.bib`.

## 9. Items requiring Brian's judgment

1. **Figure 1 image** — apply the required `flowline · L96` → `ISSM · Icepack`
   edit and the recommended AWS-box / shared-services-box updates; re-render.
2. **Figure 2 image** — optional "session registry (per-user, capability
   secrets)" wording tweak.
3. **PDF build** — run `bash paper/build_paper.sh` on a TeX-capable machine;
   review overfull boxes, figure sizing/placement (both figures are wide),
   bibliography rendering, and the new sections' page breaks. The build could
   not be run in the revision environment (no `pdflatex`/`xelatex`/`tectonic`/
   `pandoc`).
4. **Test count phrasing** — the paper says "approximately 1,280". Exact at
   `a7e2790` is 1278 passed, 1 skipped. Keep approximate (it will drift) or pin
   with a commit hash.
5. **Agent section length/placement** — currently one ~200-word section before
   Limitations. Confirm this is the right prominence, or move to a single
   paragraph inside Limitations if a reviewer reads it as over-featured.
6. **"Ice-sheet models: ISSM and Icepack" subsection** — new; confirm it does
   not over-duplicate the CryoLauncher and Results sections. It was added
   because Icepack's Basic mode / exporter / reader / visualization are new and
   were previously invisible (Icepack appeared only as a registry name).
7. **`kyanjo2026icesee` preprint → published** reference update.
8. **Self-citation** — if a CryoStack Zenodo archival DOI exists, Brian may want
   to cite it in Availability; not added here.
9. **Overall length** — ~5,000 words, long for a JOSS paper (the prior draft
   was ~3,900). The growth is in the capability registry, results, ISSM/Icepack,
   and experimental sections. If a JOSS editor asks for cuts, the ISSM/Icepack
   subsection can fold into CryoLauncher + Results, and the lifecycle section can
   shorten.
10. **Author/contributor list and Acknowledgements** — unchanged; confirm Frozen
   Legacies tool and dataset attributions are complete enough for JOSS or
   explicitly deferred to the archival release (the paper says the latter).

## 10. What I deliberately did NOT claim

- **Not** that the AWS Batch path is qualified, production-ready, "one-click",
  or tested on a real account. Only that the submission path is implemented for
  ISSM and what remains.
- **Not** that CryoLauncher supports local execution of ISSM/Icepack (it does
  not; local is an ICESEE mode).
- **Not** that the agent layer can submit runs. Explicitly: "live agent-driven
  submission is not enabled"; `RemoteSubmitBackend` "is not wired into the
  gateway".
- **Not** that the agent layer is a headline feature — kept out of the abstract
  and Figure 1, one short "Experimental" section, two limitation bullets.
- **Not** that any LLM/provider is integrated — the shipped adapter is
  deterministic and rule-based; skeletons raise `NotImplementedError`.
- **Not** that ICESEE emits a structured result package — it does not; stated
  as a limitation.
- **Not** that the connector protocol is production-safe — the generic `shell`
  channel, process-local state, and OTP bootstrap are all retained as
  limitations.
- **Not** that the relay binding is durable — explicitly "in-memory".
- **Not** that provenance is archival — the immutable-config-snapshot + event
  timeline are described as a *basis* for provenance, with the missing fields
  listed.
- **Not** that the Icepack exporter is validated on real Firedrake output —
  stated as still needing confirmation.
- **Not** any test/coverage number I did not run: 1278/1 from a full `pytest`
  run, 18/18 from the node tests, 15/0/2 from the acceptance command, all at
  `a7e2790`.
- **Not** any new reference, DOI, author, affiliation, funding number, or
  metadata field.
- **Not** any figure regeneration without a repository mechanism.
