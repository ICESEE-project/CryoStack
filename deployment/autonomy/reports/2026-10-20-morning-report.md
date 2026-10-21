# CryoStack morning handoff — shift of 19 October 2026

Shift window: 21:00–03:00 America/New_York. Three coordinated workstreams
continued from owner/daytime commits `7072164` and `c4b7cb0`; edits froze early
after independent review. Target remains 10 November 2026 or earlier.
Recommendation: **NO-GO for another deployment or storage-boundary acceptance
pending the P0 evidence and explicit owner approval below**.

No deployment, restart, production write, migration, deletion, mount/ACL/fstab
or external-permission change, secret change, commit, push, PR, or scientific
validation decision occurred. The existing README, paper, workflow, submodule,
and LYRA archive changes were outside this shift and were preserved.

## Starting point and material finding

Daytime evidence records 432 A-scope files, 2,114 Z-scope files, navigation,
and 177 provisional RIGGS stations promoted to explicit immutable CEDAR release
paths, with production reads updated and health checks reported. It also records
that SMB byte locking and SQLite WAL failed, so workspaces and all transactional
state remained on XFS.

Tonight found that the dataset CIFS mount still presents `rw,soft`. That is
compatible with an ingestion window but not with the intended steady-state
immutable read path. The new dataset-only preflight therefore fails closed.
This does not assert that the already promoted content is corrupt or unavailable;
it means the storage boundary is not yet accepted.

## Changes

### Frozen Legacies product/science

- RIGGS station details now repeat the recorded provisional, citation-pending,
  publication-ineligible status already shown in the layer legend.
- The disclosure derives only from existing metadata, is escaped before render,
  and does not modify observations, picker values, or scientific status.
- The getting-started guide distinguishes independent RIGGS context from Frozen
  Legacies manual/automatic picks and states that it does not validate LYRA.

Files:

- `icesee_jupyter_book/applications/frozen_legacies/assets/ui.js`
- `icesee_jupyter_book/applications/frozen_legacies/tests/test_frozen_legacies_radar_frontend.py`
- `icesee_jupyter_book/applications/frozen_legacies/getting_started.md`

### Storage/CEDAR/resilience

- Added an explicit `dataset-only` preflight profile while retaining the
  backward-compatible `full-network` default.
- Dataset-only requires the requested and actual dataset mount to be read-only,
  and requires workspace and state roots to resolve to XFS outside that mount.
- It refuses the transactional write probe so a successful SMB file write
  cannot be misconstrued as approval for databases or private workspaces.
- Backup and restore-drill evidence remain mandatory for readiness.
- The runbooks now state that the mounted users share is not an approved
  workspace destination and that current `rw` dataset mode is a blocker.
- Preflight JSON advances to schema version 2 and records `storage_profile`.

Files:

- `deployment/cedar_preflight.py`
- `deployment/tests/test_cedar_preflight.py`
- `deployment/cedar_preflight.md`
- `deployment/storage_cedar_runbook.md`

### Integration/continuity

- Independently reviewed both product and storage patches and the committed
  CEDAR path/configuration interfaces; no integration-owned code edit was needed.
- Updated the shared ledger and this handoff report.

## Verification

- Product RIGGS/navigation/frontend/explorer selection: **88 passed**.
- Catalog non-HTTP cases: **34 passed**. Nine HTTP-fixture cases were not
  completed because loopback sockets are denied/hang in this sandbox.
- Independent product/frontend review: **73 passed**.
- CEDAR preflight: **16 passed**; Python compile and scoped diff checks passed.
- Adjacent storage/layout/backup/promotion: **56 passed, 4 GPG tests deselected**.
  An initial attempt's four setup errors were solely sandbox GPG key generation.
- Sanitized live read-only preflight: **25 pass, 1 warning, 3 fail, 2 not run**;
  it correctly rejected the actual writable dataset mount, could not perform
  sandbox-denied dataset capacity stats, and lacked supplied backup/drill proof.
- Authorization/workspace isolation: **99 passed** with existing warnings.
- All **6** available Node contracts passed with zero skips/failures.
- Deployment launcher contract: **4 passed**.
- The exact canonical scope collected **3,989 tests**, emitted sandbox
  OPAL/PMIx/socket denials, reached about 25%, and reproducibly stopped emitting
  in the runtime-feedback region. It was interrupted after about 91 seconds and
  is environment-inconclusive, not a pass or an application failure.
- Repository `git diff --check` passed.
- No authenticated desktop/mobile/browser, screen-reader, or host-context
  production health session was performed. Service/listener visibility was
  sandbox-blocked, so production health is unverified here, not reported down.

## Blockers and risks

1. Current dataset CIFS is `rw,soft`; accepted steady state requires an
   owner-authorized read-only mount and a passing dataset-only preflight.
2. This sandbox identity cannot stat the live release directories or collect
   capacity/file-count evidence. Administrator/host evidence is required.
3. Fresh verified backup plus empty-target recovery/rollback evidence was not
   supplied to the live preflight.
4. The full canonical run needs loopback, MPI/PMIx, and disposable GPG support.
5. Exact A-/Z-scope catalog registrations, release IDs, rollback-root lifetime,
   monitoring, snapshots, retention, off-host custody, and RTO need owner review.
6. RIGGS remains provisional and citation-pending. Automatic picker outputs
   remain scientifically unvalidated and publication-ineligible.

## Priorities

- **P0:** form an immutable candidate; run all 3,989 canonical tests in the
  supported environment; complete authenticated staging desktop/mobile/access
  checks; have an authorized operator make the application dataset mount
  read-only; pass dataset-only preflight with verified backup and empty-target
  recovery/rollback evidence; verify host-context health.
- **P1:** verify exact release/catalog source IDs and object counts; decide
  local/scratch rollback-root retirement; obtain capacity, snapshots, ACL,
  monitoring, recovery-owner, custody, and RTO evidence; close provenance,
  licensing, and representative performance thresholds.
- **P2:** provide CI loopback/MPI/GPG facilities; automate browser, backup-age,
  mount-mode, and recovery evidence; reduce warnings; decide whether to
  disconnect the unused users SMB share.
- **P3:** retention reporting, manifest linting, and inherited EOF cleanup.

Implementation appears approximately **90–92%** complete; operational and
scientific release evidence approximately **70–75%** complete. The 10 November
target remains feasible with moderate confidence if P0 owner/admin work is
scheduled promptly.

## Owner deployment-review checklist

Do not approve another deployment or storage acceptance until applicable items
are evidenced:

1. Review `c4b7cb0`, the complete uncommitted nightly diff, ledger, schema-v2
   interface note, and an immutable candidate identifier.
2. Require a clean supported-environment result for all 3,989 canonical tests,
   the six Node contracts, and focused product/storage/authorization checks.
3. Confirm exact A-/Z-scope, navigation, and RIGGS release IDs, catalog source
   IDs, object counts, retained rollback copies, and rollback trigger.
4. Confirm the SMB boundary: explicit immutable datasets only, application
   mount read-only, workspaces and all transactional state on XFS, and no use of
   the mounted users share as an application workspace.
5. Review fresh administrator evidence for mount/export/options, capacity/file
   counts, ACL/identity mapping, snapshots, monitoring, retention, encrypted
   off-host custody, recovery owner, RTO, and an empty-target recovery drill.
6. Confirm RIGGS/citation and automatic-product labels remain provisional,
   unvalidated, and publication-ineligible; approve no scientific claim by
   implication.
7. If approving an action, specify the exact human operator, window, immutable
   release, commands/change scope, rollback trigger, and stop conditions.
8. After any separately authorized action, require host-context health,
   authentication/authorization, workspace isolation, durable-store location
   and capacity, backup/audit evidence, and representative application smoke
   checks before declaring completion.
