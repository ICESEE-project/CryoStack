# CryoStack Nightly Program kickoff — 16 October 2026

Target: complete the 10 November 2026 delivery objective or finish earlier.
Deployment recommendation at kickoff: **NO-GO**.

This kickoff continued from the runtime day and night reports, the source day
report, owner continuity handbook, nightly prompt, current working tree, and
current diff. Exactly three coordinated workstreams ran. The pre-existing dirty
tree was preserved; no deployment, production restart, production migration or
deletion, secret or external-permission change, commit, push, PR, or scientific
validation decision occurred.

## Verified outcomes

### Frozen Legacies product and science workflow

- Added an opt-in production-path large-TIFF benchmark covering header checks,
  complete decode validation, cold preview generation, cached preview reuse,
  PNG geometry, decoded bytes, and peak RSS.
- On the repository's 115,975,576-byte, 37,943 x 2,400, 16-bit TIFF: header
  0.005 s; complete validation 0.943 s; cold preview 1.324 s; warm preview
  0.000130 s; decoded bytes 182,126,400; peak process RSS 612,900 KiB.
- Suppressed Pillow's generic decompression warning only after CryoStack's
  explicit, stricter image bounds have passed; added a regression test.
- This is local single-file performance evidence only. It is not CEDAR,
  concurrent-user, browser, provenance, or scientific-validation evidence.

Files changed by this workstream:

- `icesee_jupyter_book/applications/frozen_legacies/radar/ingest.py`
- `icesee_jupyter_book/applications/frozen_legacies/tests/test_frozen_legacies_radar_ingest.py`
- `icesee_jupyter_book/applications/frozen_legacies/tests/test_frozen_legacies_large_tiff_benchmark.py`

### Storage, CEDAR, and resilience

- Confirmed that regular-file hashes and link counts did not authenticate
  symlink target text.
- New backup manifests are version 2 and hash raw `os.readlink()` target text
  without following links. Verification rejects missing, added, or retargeted
  links, and restore drills compare link digests.
- Version-1 backups remain readable; their legacy limitation is documented.

Files changed by this workstream:

- `deployment/cryostack_backup.py`
- `deployment/tests/test_cryostack_backup.py`
- `deployment/README.md`
- `deployment/storage_cedar_runbook.md`

### Integration, validation, and continuity

- Documented the canonical clean-environment first-party Python regression,
  including `control_center`, and the evidence fields that a release record
  must capture.
- Added the owner deployment-review checklist below to the continuity handbook.
- Independently verified that Developer Guide access revocation on demotion is
  transactional, audited, and covered by positive and negative tests.
- Identified `CRYOSTACK_CLOUD_OPERATOR_USER_IDS` as deployment-critical but not
  yet present in operator documentation. Missing or incorrect configuration
  changes host-credential cloud behavior; owner review is required.

File changed by this workstream:

- `icesee_jupyter_book/docs/owner_continuity.md`

## Test and review evidence

- Prior clean first-party regression: **3,697 passed, 4 skipped** in 8m05s.
  The newly documented canonical scope adds Control Center and has not yet been
  rerun end-to-end after this kickoff's edits.
- Integration selection with loopback available: **423 passed** in 75.77 s;
  16,250 existing warnings.
- Parent verification, large-TIFF plus ingest: **55 passed, 1 warning** in
  3.04 s, including the benchmark figures above.
- Parent verification, new backup integrity/compatibility and access-revocation
  regressions: **4 passed**, 30 existing aiohttp key warnings.
- Storage workstream: non-GPG backup selection **12 passed, 4 deselected**;
  combined backup/storage selection reached **31 passed, 5 deselected** before
  a socket-restricted persistence test was blocked.
- Full GPG backup tests could not create temporary keys in the sandbox. Local
  aiohttp tests requiring loopback also fail in the sandbox with `EPERM`; the
  integration workstream reran its selection with loopback and passed.
- Scoped diff checks pass. Repository-wide `git diff --check` retains five
  inherited extra-EOF-line warnings.

## Blockers and risks

- No administrator evidence yet confirms real CEDAR mount type/path/device,
  ACLs, capacity, inode headroom, snapshots, retention, monitoring, off-host
  encrypted custody, recovery owner, or RTO. The current data root was earlier
  observed on root XFS at 90% utilization with about 11 GB free.
- No owner-approved non-production restore, cutover, outage, or rollback
  rehearsal has been performed against CEDAR.
- No real desktop/mobile browser authorization and usability session exists.
- The representative TIFF has a measured ~598 MiB process peak; concurrency
  limits and performance budgets are not agreed. Fixture provenance, licensing,
  and repository treatment remain owner decisions.
- The untracked LYRA archive is about 118 MB and still needs provenance,
  licensing, and packaging review. Picker outputs remain unvalidated.
- The cloud-operator allowlist needs operator documentation and explicit owner
  review before deployment.
- The 124-entry dirty tree raises integration and release-identification risk.

## Priorities

- **P0:** document/review the cloud-operator allowlist; obtain CEDAR
  administrator evidence; approve and run an empty-target non-production
  restore/cutover/outage/rollback rehearsal; run the expanded canonical suite;
  capture real desktop/mobile authorization evidence; repeat TIFF testing on an
  owner-approved corpus with concurrency and thresholds.
- **P1:** decide LYRA/TIFF provenance, licensing, and packaging; add
  capacity/inode alerting; set performance budgets; align CI and README with
  the canonical first-party scope; replace retained version-1 backups under the
  approved retention policy.
- **P2:** automate backup-age/verification and release-evidence capture; reduce
  aiohttp/traitlets warning volume; trend the opt-in TIFF benchmark.
- **P3:** add retention reporting, manifest linting, and clean the five inherited
  EOF whitespace warnings.

The 10 November target remains feasible, but confidence is moderate until the
external CEDAR, recovery, browser, provenance, and owner-review gates close.

## Morning owner deployment-review checklist

Do not authorize deployment until every applicable item is evidenced:

1. Review the complete diff and release identifier plus the expanded canonical
   regression, focused authorization/isolation tests, real desktop/mobile
   checks, and representative TIFF results against agreed thresholds.
2. Confirm dataset/model provenance, LYRA/TIFF licensing and packaging, and the
   scientific status of every picker output; unapproved output stays marked
   unvalidated and ineligible for publication.
3. Review service inventory and boot order, configuration changes including
   `CRYOSTACK_CLOUD_OPERATOR_USER_IDS`, secret references (not values),
   dependency changes, known limitations, and named release/rollback operators.
4. Verify CEDAR mount/device, ACLs, capacity/inodes, snapshots, retention,
   monitoring, off-host encrypted backup custody, recovery owner, and RTO from
   administrator evidence.
5. Review a verified v2 backup manifest/checksums and successful restore,
   cutover, outage, and rollback rehearsals in an empty non-production target.
6. If satisfied, explicitly approve the exact production migration/deployment/
   restart window and rollback trigger. Rehearsal approval is not production
   approval.
7. After an authorized release, require health, authentication, authorization,
   workspace isolation, durable-store location/capacity, backup, audit-log, and
   representative application smoke checks before declaring completion.
