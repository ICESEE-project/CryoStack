# CryoStack morning handoff — shift of 18 October 2026

Shift window: 21:00–03:00 America/New_York. Work completed and edits froze
early after three coordinated workstreams and coordinator verification. Target
remains 10 November 2026 or earlier. Recommendation: **NO-GO for deployment or
CEDAR cutover pending owner review and the P0 evidence below**.

This shift resumed from the 18 October scientific-explorer release and current
uncommitted tree. No deployment, restart, production backup/restore, CEDAR
probe, mount, ACL/fstab or external-permission change, migration, deletion,
secret change, commit, push, PR, or scientific-validation decision occurred.
The concurrently modified `deployment/dropbox_shared_folder_ingest.py` was not
owned, edited, tested, or claimed by this shift.

## Material correction to prior release evidence

The 18 October scientific-explorer report overstated the deployed frontend
integration. The deployed source contained and tested the authorized
`/frozen-legacies/api/radar/explorer` endpoint, but the browser still filtered
the already-loaded historical observation layer locally and fetched catalog
rows/coverage through older paths. The source user manual's compatibility
wording was accurate.

Tonight's **uncommitted, undeployed** candidate now consumes one ExplorerQueryV1
response for radar catalog rows and radar-coverage geometry. Historical public
observation points remain locally filtered and are documented as such. Do not
attribute tonight's integration to the earlier production release.

The earlier 18 October fault-scale report also lists cross-process locking,
reconciliation, and janitor work as future gates; the later scientific-explorer
report records those items as subsequently implemented. Both reports remain
historical evidence in their original sequence.

## Outcomes and files changed this shift

### Frozen Legacies product/science

- The catalog browser and radar-coverage layer now fetch
  `/frozen-legacies/api/radar/explorer` with the canonical shared query.
- Catalog items, exact total, cursor pagination, coverage features, truncation
  state, and snapshot identifier are consumed from that single authorized
  response. The obsolete independent coverage fetch is removed.
- Monotonic request IDs prevent a slow older response from replacing newer
  filter results.
- The scientific quicklook closes with Escape, navigates with Left/Right,
  restores focus, and honors reduced-motion preferences.
- The manual distinguishes same-snapshot catalog/coverage data from locally
  filtered, already-loaded historical public observation points.
- A runtime-style Node test proves the exact endpoint is called and that a
  stale reply cannot overwrite the newer coverage snapshot.
- No coordinates, observations, picker values, review states, or scientific
  validation status were invented or changed.

Files touched:

- `icesee_jupyter_book/applications/frozen_legacies/assets/catalog.js`
- `icesee_jupyter_book/applications/frozen_legacies/assets/ui.js`
- `icesee_jupyter_book/applications/frozen_legacies/index.html`
- `icesee_jupyter_book/applications/frozen_legacies/radar/catalog.py`
- `icesee_jupyter_book/applications/frozen_legacies/tests/test_frozen_legacies_catalog.py`
- `icesee_jupyter_book/applications/frozen_legacies/tests/test_frozen_legacies_radar_frontend.py`
- `icesee_jupyter_book/applications/frozen_legacies/tests/frozen_legacies_catalog_snapshot.test.cjs`
- `icesee_jupyter_book/applications/frozen_legacies/user_manual.md`

### Storage/CEDAR/resilience

- Confirmed a real recovery gap: the configured resumable-intake volume was
  durable but absent from one-command backup/restore.
- Backup now copies open manifests/chunks, janitor audit state, receipts, and
  finalized releases while holding the same volume lock as intake writers.
- Backup is read-only: it requires the existing regular lock and never creates
  it. It refuses any intake symlink.
- Independent review closed a lock-path TOCTOU issue: open uses `O_NOFOLLOW`
  where available and validates the opened descriptor with `fstat` before
  locking. A replaced symlink fails closed.
- Verification/drill compare restored file identity. Restore targets
  `<data-root>/frozen_legacies/intakes` and reports the required
  `CRYOSTACK_FROZEN_LEGACIES_INTAKE_ROOT` setting without changing a service.
- Destination, recursion, and overwrite guards include the intake root.

Files touched:

- `deployment/cryostack_backup.py`
- `deployment/tests/test_cryostack_backup.py`
- `deployment/storage_cedar_runbook.md`
- `icesee_jupyter_book/applications/frozen_legacies/data_intake.md`

### Integration/continuity

- `dev_testing.md` now matches the owner handbook's canonical clean-environment
  scope, including Control Center and required release-evidence fields.
- Integration independently identified the ExplorerQueryV1 release-report
  contradiction and defined closure criteria: one normalized query; one
  authorized response for catalog/coverage/count/facets; multi-value/range
  semantics; stale-response safety; URL history; positive/negative access; and
  behavioral browser evidence.
- The shared work ledger records ownership, interfaces, evidence, status, and
  the absence of an immutable commit/candidate identifier.

Files touched:

- `icesee_jupyter_book/docs/dev_testing.md`
- `deployment/autonomy/work_ledger.md`
- `deployment/autonomy/reports/2026-10-18-morning-report.md`

## Verification evidence

- Product/query focused Python selection: **74 passed in 3.49 seconds**.
- New catalog-snapshot and existing query-store Node files: **2/2 passed**;
  the new test exercises the endpoint and out-of-order response behavior.
- JavaScript syntax and scoped patch-integrity checks passed.
- Storage backup/resumable/janitor selection after TOCTOU hardening: **27
  passed, 4 deselected in 5.31 seconds**. The deselections are sandbox-dependent
  GPG/export cases. Python compilation and scoped diff checks passed.
- Integration authorization/isolation selection: **109 passed**, 2 warnings,
  with 1 kernel end-to-end fixture blocked at setup by sandbox `socket()`
  `EPERM`.
- All four previously available Node/browser contracts passed in 193.6 ms.
- The canonical clean-environment run again emitted OPAL/PMIx/UCX socket
  errors, reached about 25% with environment-originating failures/errors, and
  reproducibly stalled in the runtime-feedback region. It was stopped as
  environment-inconclusive, not represented as a product pass or failure.
- The latest complete pre-shift evidence remains **3,853 passed, 7 skipped**
  repository-wide and **694 passed, 4 skipped** for Frozen Legacies. It does
  not cover tonight's uncommitted changes.
- Socket-backed Explorer authorization tests could not be rerun here; their
  pre-shift integrated evidence remains current for the server endpoint.
- No authenticated real desktop/phone/tablet, screen-reader, or independent
  ArcGIS/STAC client session was performed.

## Interface notes and risks

1. ExplorerQueryV1 now replaces separate catalog/coverage browser requests.
   Any external frontend assumption about `/api/radar/catalog/segments` must be
   reviewed. Historical observation points intentionally remain a separate
   already-loaded public layer.
2. The browser query model recognizes future fields such as `product`, while
   the V1 server deliberately rejects not-yet-indexed fields rather than
   broadening a query. UI documentation currently promises only implemented
   dataset, flight, CBD, review, and text filters.
3. Intake backups can be large and hold the shared writer lock for the copy
   duration. Measure representative CEDAR duration and ingestion pause before
   production scheduling.
4. Restore results now include the intake-root environment setting. This is
   evidence for an operator; it does not authorize redirecting services.
5. The large shared tree has no immutable candidate identifier. HEAD alone
   does not identify the tested contents.

## Blockers and approval requests

- Owner approval is required for an isolated empty-target CEDAR restore of an
  intake-containing backup, followed by resume, reconciliation, catalog
  registration/rebuild, janitor, and proof that publication state cannot
  escalate. This is not production approval.
- Storage administrator evidence is still required for exact CEDAR mounts,
  UID/GID and ACL inheritance, capacity/inodes, snapshots, monitoring,
  retention, encrypted off-host custody, recovery owner, and RTO.
- Owner must review the prior release-report correction and require the new
  browser integration to pass an authenticated staging session before any
  deployment.
- Full post-edit canonical regression must run where test-only loopback,
  MPI/PMIx, and disposable GPG key generation are permitted.
- TIFF/LYRA provenance, licensing, packaging, representative corpus, and
  concurrency/RSS budgets remain owner/science decisions. Automatic outputs
  remain scientifically unvalidated and ineligible for publication.

## Priorities

- **P0:** create an immutable candidate; rerun all canonical tests in the
  supported environment; perform authenticated desktop/mobile/keyboard/screen-
  reader staging checks for the unified explorer; verify positive/negative
  restricted-source behavior; conduct the separately approved intake-bearing
  CEDAR restore/resume/reconciliation/no-publication-escalation rehearsal; and
  verify host-context runtime health.
- **P1:** benchmark backup lock duration and temporary amplification on a
  representative intake volume; decide provenance/licensing and TIFF
  concurrency/RSS thresholds; complete live product/review quicklook binding
  where catalog fields alone are insufficient.
- **P2:** add automated browser coverage for cursor history/facets/focus;
  provide CI test-only loopback/MPI/GPG facilities; automate backup age and
  intake-component monitoring; reduce warnings.
- **P3:** retention reporting, manifest linting, and inherited EOF cleanup.

Implementation appears roughly **90%** complete; operational/scientific release
evidence is approximately **65–75%** complete. The 10 November target remains
feasible with moderate confidence, but the external and browser/recovery gates
remain schedule-critical.

## Morning owner checklist — deployment decision

Do not approve deployment or CEDAR cutover until every applicable item is
evidenced:

1. Review the complete diff, this correction, work ledger, interface notes,
   immutable candidate ID, and exact canonical/focused test results.
2. In authenticated isolated staging, prove one URL/filter action drives the
   intended catalog rows and radar coverage from one snapshot; test cursor
   paging, stale responses, Back/Forward/Copy link, restricted-source
   positive/negative cases, quicklook keyboard/focus, and narrow layouts.
3. Confirm the distinction between historical public observations and
   authorized radar catalog/coverage is scientifically and operationally
   acceptable.
4. Confirm provenance/licensing and that automatic products remain labelled
   unvalidated and ineligible for publication.
5. Verify CEDAR mount/export/mode, UID/GID and ACLs, capacity/inodes, snapshots,
   monitoring, retention, off-host encrypted backup custody, recovery owner,
   and RTO from administrator evidence.
6. Review a verified intake-containing v2 backup and successful empty-target
   restore/resume/reconciliation/catalog/janitor/no-escalation rehearsal.
   Approve any production action separately with exact window, operator,
   immutable release, and rollback trigger.
7. After an authorized release, require host-context health, authentication,
   authorization, workspace isolation, durable-store location/capacity,
   backup, audit-log, and representative application smoke checks before
   declaring completion.
