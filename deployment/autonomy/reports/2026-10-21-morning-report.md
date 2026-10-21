# CryoStack morning handoff — shift of 20 October 2026

Shift window: 21:00–03:00 America/New_York. Three coordinated workstreams
resumed from commit `cdc40c8` and the existing dirty candidate; edits froze
early after independent review. Target remains 10 November 2026 or earlier.
Recommendation: **NO-GO for deployment, restart, intake relocation or release
acceptance pending owner review and the P0 evidence below**.

No production write, deployment, restart, migration, deletion, mount/ACL/fstab
or external-permission change, secret change, commit, push, PR, or scientific
validation decision occurred. All pre-existing README, paper, workflow,
submodule, external ICESEE, cloud/UI and archive work was preserved.

## Material correction to daytime commit

Commit `cdc40c8` configured mutable resumable intake sessions, chunks, receipts
and their shared writer lock under
`/srv/cryostack/workspace/datasets/frozen-legacies/intakes`. That conflicts with
the 19 October SMB acceptance evidence: byte locking and SQLite WAL were not
accepted, so SMB is restricted to immutable releases while mutable state stays
on local durable XFS.

Read-only inspection tonight shows the dataset CIFS has since become `ro,hard`
with SMB 3.1.1. This is the desired immutable steady-state mode, but it makes
the committed CEDAR intake path unwritable. The proposed local-XFS intake path
does not yet exist. The candidate corrects source configuration and guidance;
it does not create a directory, inspect or move existing intake content, change
the running environment, or restart a service.

## Changes

### Frozen Legacies product/science

- Control Center guidance no longer claims resumable uploads write directly to
  CEDAR. Intake is described as private mutable staging on local durable XFS.
- Documentation uses
  `/home/bkyanjo3/cryostack-data/datasets/frozen-legacies/intakes` and separates
  intake from operator-controlled, manifest-verified promotion to immutable
  read-only CEDAR releases.
- The previous RIGGS provisional/citation-pending/publication-ineligible station
  disclosure remains intact. No scientific data, picker output or validation
  status changed.

Files:

- `icesee_jupyter_book/applications/frozen_legacies/catalog_routes.py`
- `icesee_jupyter_book/applications/frozen_legacies/data_intake.md`
- `icesee_jupyter_book/applications/frozen_legacies/developer.md`
- `icesee_jupyter_book/applications/frozen_legacies/tests/test_frozen_legacies_catalog.py`

### Storage/CEDAR/resilience

- Changed the source launcher default from the read-only CEDAR intake path to
  the local durable XFS path. This is undeployed and performs no migration.
- Extended schema-v2 dataset-only preflight with `--intake-root`.
- Dataset-only readiness now fails when intake is missing, non-XFS, or inside
  the dataset mount; workspace and transactional state retain the same rule.
- Updated tests and runbooks to state that intake chunks, session records,
  receipts and writer locks are mutable state excluded from SMB.

Files:

- `deployment/services.sh`
- `deployment/cedar_preflight.py`
- `deployment/tests/test_cedar_preflight.py`
- `deployment/tests/test_staging_data_promotion.py`
- `deployment/cedar_preflight.md`
- `deployment/storage_cedar_runbook.md`

### Integration/continuity

- Independently reviewed the final product/storage diff and the wider
  first-party ICESEE/cloud/UI candidate. No integration-owned edit was needed.
- Updated the shared work ledger and this report.

## Verification evidence

- Product RIGGS/frontend/intake/resumable/fault selection: **93 passed in
  4.07 seconds**. Python compile, JavaScript syntax and scoped diff checks passed.
- Storage preflight: **20 passed**. Adjacent storage/intake/backup selection:
  **76 passed, 4 GPG tests deselected**; the original four setup errors were
  solely sandbox GPG key-generation restrictions. Python compile and shell
  syntax passed.
- Coordinator combined product/storage rerun: **106 passed in 4.84 seconds**;
  Python compile, shell syntax and JavaScript syntax passed.
- Independent cross-stream rerun: **86 passed in 3.89 seconds**.
- Changed first-party core/UI/docs selection: **272 passed, 10
  environment-blocked** in 63.82 seconds. Seven require Bubblewrap network
  namespace access and three require loopback sockets; no assertion regression
  was identified.
- Configuration-agent intent: **32 passed**. The gateway WebSocket regression
  and exact catalog-page test were blocked at aiohttp socket setup.
- The prior canonical 3,989-test run remains environment-inconclusive. Tonight's
  aggregate attempt also hung after socket-oriented tests and was interrupted;
  neither is represented as a pass or application failure.
- Scoped nightly `git diff --check` passed. Repository-wide diff check remains
  non-clean solely in preserved work: two trailing-whitespace lines under
  `external/ICESEE` and one EOF blank line in the pre-existing ICESEE UI patch.
- No authenticated real browser/device, screen-reader, representative cloud
  container, external HPC or empty-target recovery session was performed.

## Interface notes, blockers and risks

1. The candidate reverses the intake default in committed `cdc40c8`. Deploying
   that commit alone would retain the broken read-only-CEDAR intake path.
2. Before activation, an authorized operator must inventory and back up any
   existing CEDAR intake, create and verify the local XFS root with the intended
   service ownership, and separately approve any reconciliation or migration.
3. Preflight JSON version 2 adds `storage_profile`; consumers require review.
4. The live dataset mount is now `ro,hard`, but complete service-identity read,
   release-count/fixity, capacity, snapshot and recovery evidence is outstanding.
5. The large pre-existing ICESEE/cloud candidate packages current
   `external/ICESEE` source. That tree is extensively dirty and must not become
   release evidence without a clean immutable revision, container digest and
   representative multi-rank cloud/runtime verification.
6. Loopback, Bubblewrap namespace, MPI/PMIx and GPG restrictions prevent a
   canonical release result here. Production health is unverified, not failed.
7. RIGGS and automatic picker outputs remain provisional/unvalidated and
   publication-ineligible.

## Priorities

- **P0:** review the entire candidate with `cdc40c8`; inventory/back up the
  current intake location; approve creation and verification of the local XFS
  intake root; run dataset-only preflight with backup/restore evidence; run all
  canonical, gateway, user-plot and docs-access tests in the supported
  environment; pin and verify the external ICESEE revision/container/cloud
  runtime; complete authenticated staging browser/access checks.
- **P1:** verify CEDAR service-identity reads, exact release IDs/catalog source
  IDs/counts/fixity, capacity, snapshots, monitoring, retention, off-host
  custody, recovery owner and RTO; rehearse empty-target intake restore and
  immutable promotion/rollback without publication escalation.
- **P2:** automate mount-mode/intake-boundary/backup-age/browser evidence and
  provide CI loopback, namespace, MPI and GPG facilities; review all preflight
  schema-v2 consumers; reduce warnings.
- **P3:** retention reporting, manifest linting and preserved diff hygiene.

Frozen Legacies implementation appears approximately **90–92%** complete;
platform-wide operational/scientific release evidence is approximately
**65–70%** complete because the new ICESEE/cloud candidate is not yet an
immutable, supported-environment release. The 10 November target remains
feasible with moderate confidence if P0 owner/admin work starts promptly.

## Morning owner checklist — deployment decision

Do not approve deployment or restart until every applicable item is evidenced:

1. Review HEAD `cdc40c8` plus the complete uncommitted candidate—not the commit
   alone—the work ledger, schema-v2 interface, and an immutable candidate ID.
2. Confirm the authoritative intake path, service ownership/mode, available
   capacity, backup coverage and recovery behavior. Inventory the CEDAR intake
   before authorizing creation, reconciliation or migration to local XFS.
3. Confirm CEDAR remains `ro,hard` for explicit immutable datasets only;
   verify service-identity reads, release IDs, catalog registrations, counts,
   fixity and rollback copies. Keep workspace/state/intake off SMB.
4. Require a supported-environment canonical result plus gateway WebSocket,
   user-plot sandbox, developer-doc access, six Node contracts and focused
   product/storage/authorization evidence.
5. Pin a clean external ICESEE revision and container digest; verify archive
   contents, supported examples, cloud vCPU/MPI limits, representative
   multi-rank execution, results/provenance and rollback.
6. Perform authenticated desktop/mobile/keyboard/screen-reader staging checks,
   including intake help, resume/unavailable states and positive/negative access.
7. Confirm RIGGS/citation and automatic-product labels remain provisional,
   unvalidated and publication-ineligible.
8. If approving an action, specify exact human operator, window, release,
   configuration/directory changes, rollback trigger and stop conditions.
   Afterwards require host-context health, authentication/authorization,
   workspace isolation, durable-store capacity, backup/audit and application
   smoke evidence before declaring completion.
