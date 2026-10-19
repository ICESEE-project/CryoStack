# CryoStack morning handoff — shift of 17 October 2026

Shift window: 21:00–03:00 America/New_York. Work completed and edits froze
early after the three bounded workstreams finished. Target remains 10 November
2026 or earlier. Recommendation: **NO-GO for another production deployment or
storage cutover**.

The shift resumed from the current uncommitted tree and the latest reports,
including the 16 October application deployment performed before this shift.
That deployment was not repeated or extended. No production deployment,
restart, mount, ACL/fstab or external-permission change, migration, deletion,
production restore, secret change, commit, push, PR, or scientific-validation
decision occurred during this shift.

## Outcomes and files changed this shift

### Frozen Legacies product/science

- Product cards now expose only recorded, API-whitelisted provenance: picker,
  writer, source/original filename, shared-source ID, and SHA-256. Missing
  fields are not inferred.
- Inline image previews now have linked controls/regions and synchronized
  `aria-expanded` state, including sibling reset. Long provenance values wrap
  at narrow widths.
- User guidance documents provenance and preview behavior. No product schema,
  backend, storage, navigation, authorization, coordinate, picker value, or
  scientific status changed.

Files:

- `icesee_jupyter_book/applications/frozen_legacies/assets/products.js`
- `icesee_jupyter_book/applications/frozen_legacies/assets/frozen_legacies.css`
- `icesee_jupyter_book/applications/frozen_legacies/tests/test_frozen_legacies_radar_frontend.py`
- `icesee_jupyter_book/applications/frozen_legacies/user_manual.md`

### Storage/CEDAR/resilience

- CEDAR preflight now enforces a configurable minimum free-inode reserve,
  defaulting to 100,000 per persistent filesystem, instead of accepting any
  positive free-inode count.
- `--minimum-free-inodes` rejects negative values. Sanitized JSON records free,
  total, and required inodes. Documentation states that site owners must
  approve thresholds and that one-time preflight is not monitoring.

Files:

- `deployment/cedar_preflight.py`
- `deployment/tests/test_cedar_preflight.py`
- `deployment/cedar_preflight.md`
- `deployment/storage_cedar_runbook.md`

### Integration/continuity

- Operations guidance now documents `CRYOSTACK_CLOUD_OPERATOR_USER_IDS` as a
  comma-separated list of stable authenticated CryoStack user IDs, empty by
  default and fail-closed. It requires separate staging/production review and
  positive/negative release checks. No identifier values were recorded.
- The shared work ledger records reservations, interfaces, evidence, status,
  and the absence of a commit identifier for this uncommitted candidate.

Files:

- `icesee_jupyter_book/docs/service_operations.md`
- `deployment/autonomy/work_ledger.md`
- `deployment/autonomy/reports/2026-10-17-morning-report.md`

## Interface notes requiring review

1. CEDAR's machine-readable check name changes from `<role> free inodes` to
   `<role> free-inode reserve`; the new default can correctly fail a filesystem
   below 100,000 free inodes. Review any external parser and approve the site
   threshold before release.
2. Cloud host-credential authorization crosses gateway-to-Voilà environment
   forwarding and the proxy/environment-derived workspace user identity.
   Missing IDs deny intended operators and legacy host-credential status
   access; an overbroad list grants host AWS authority. Review exact stable IDs
   in isolated staging and test both allowed and denied accounts.
3. Frozen Legacies changes consume existing provenance fields only and do not
   change a shared schema or scientific status.

## Verification evidence

- Coordinator rerun: Frozen Legacies frontend contracts **55 passed in 3.27
  seconds**; `node --check` passed.
- Coordinator rerun: CEDAR preflight **12 passed in 0.35 seconds**.
- Storage workstream: combined CEDAR/storage-layout/backup selection **43
  passed, 5 deselected in 5.64 seconds**. Four GPG fixture setups remain blocked
  by sandbox key-generation restrictions.
- Integration focused clean environment: cloud execution/connect isolation,
  user isolation, and multi-user workspace/files **63 passed in 0.88 seconds**.
- Broader integration selection: **74 passed**; 42 Control Center cases were
  blocked before HTTP assertions because aiohttp could not create loopback
  sockets (`EPERM`).
- Available Node browser contracts: **3/3 passed** in 198.5 ms (connect page,
  workspace viewer, Frozen Legacies radar geometry).
- Scoped JavaScript syntax and patch-integrity checks passed.
- Exact canonical scope collected **3,842 tests**. A diagnostic run reached
  **781 passed, 1 skipped** before an MPI/PMIx socket restriction. A subsequent
  supported-scope run reached 26% without test failures, then reproducibly
  stalled in the runtime-feedback test after the same socket initialization
  failures. It was stopped as environment-inconclusive; it does not supersede
  the prior full **3,835 passed, 5 skipped** supported-suite evidence.
- No authenticated real desktop/mobile browser session was performed.
- The prior representative 115.98 MB TIFF evidence remains current: header
  0.005 s, validation 0.943 s, cold preview 1.324 s, cached preview 0.000130 s,
  peak process RSS about 598 MiB. No concurrency threshold has been approved.

## Read-only operational evidence

Fresh sanitized storage inventory returned 12 pass, 6 warning, 17 fail, and 3
not-run checks. The service identity and durable marker passed. State had about
35.1 GB and 52.3 million inodes free, above the 5 GiB and 100,000-inode floors;
scratch was local and on a separate device. Both proposed CEDAR targets remain
local paths rather than exact NFS mounts, lack matching fstab entries, and were
not eligible for the write-semantics probe.

This sandbox could not see service listeners, reach localhost health endpoints,
or access the user systemd bus. Production health is therefore **unverified,
not declared unhealthy**. No corrective service action was taken.

## Blockers, risks, and approval requests

- Storage administrator must supply/verify the two exact CEDAR NFS mounts,
  `sec=sys` UID/GID mapping and inherited private ACLs, capacity/quota/inode
  thresholds, snapshots, monitoring, retention, off-host custody, recovery
  owner, and RTO. Then the service-user semantic probe may run.
- Owner approval is required for an empty-target non-production restore,
  cutover, outage, and rollback rehearsal; it is not production approval.
- Owner must review the exact cloud-operator user IDs and positive/negative
  staging evidence. Production service configuration is currently unverified.
- Authenticated desktop and narrow/mobile browser evidence remains missing.
- TIFF/LYRA provenance, licensing, packaging, representative corpus, and
  concurrency/RSS budgets remain owner/science decisions. All automatic-picker
  results remain scientifically unvalidated and ineligible for publication.
- The 148-entry tree (92 tracked diff paths at shift start) lacks an immutable
  candidate identifier. HEAD alone does not identify the tested release.
- Canonical post-edit regression must be rerun where test-only loopback,
  MPI/PMIx, and disposable GPG key generation are permitted.

## Priorities

- **P0:** create an immutable candidate; review the complete diff/interfaces;
  rerun all 3,842 canonical tests in the supported environment; perform
  authenticated desktop/mobile staging checks; review cloud-operator IDs;
  verify host-context health; obtain CEDAR administrator evidence and complete
  the separately approved non-production recovery/cutover/outage/rollback
  rehearsal.
- **P1:** decide TIFF/LYRA provenance, licensing and packaging; approve TIFF
  concurrency/RSS and filesystem reserve thresholds; wire numeric capacity and
  inode evidence into monitoring; review provenance disclosure in a browser.
- **P2:** provide CI with test-only loopback/MPI/GPG facilities; automate
  release evidence, backup age/verification, and browser disclosure-state/focus
  coverage; reduce warning volume.
- **P3:** retention reporting, manifest linting, and inherited EOF cleanup.

Implementation is advanced and 10 November remains feasible, but operational
and validation confidence is moderate because P0 evidence is incomplete.

## Morning owner checklist — deployment decision

Do not approve another production deployment or CEDAR cutover until applicable
items are complete:

1. Review the entire diff, ledger/interface notes, immutable candidate ID, and
   exact canonical/focused test evidence.
2. Review authenticated desktop and narrow/mobile staging behavior, including
   product provenance/previews, owner-doc delegation, navigation/RIGGS/LYRA
   labels, and positive/negative authorization.
3. Approve exact `CRYOSTACK_CLOUD_OPERATOR_USER_IDS` identities separately for
   staging and production; prove one intended operator is allowed and one
   ordinary user is denied. Do not put credentials in the report.
4. Confirm scientific provenance/licensing and that all unapproved automatic
   outputs remain labelled unvalidated and ineligible for publication.
5. Verify CEDAR mounts/export/mode, service UID/GID and ACLs, capacity/inodes,
   snapshots, monitoring, retention, off-host encrypted backup custody,
   recovery owner, and RTO from administrator evidence.
6. Review a verified v2 backup and successful empty-target restore, cutover,
   outage, and rollback rehearsals. Approve production separately, with an exact
   window, operator, rollback trigger, and immutable release.
7. After any authorized release, require host-context health, authentication,
   authorization, workspace isolation, durable-store location/capacity,
   backup, audit-log, and representative application smoke checks before
   declaring completion.
