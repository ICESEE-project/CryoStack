# CryoStack overnight integration report — 2026-10-16

## Outcome

Three parallel work streams completed and were integrated locally:

1. Frozen Legacies scientific-product intake manifests and resumable indexing.
2. Owner-controlled Developer Guide delegation and operations documentation.
3. Fail-closed CEDAR storage readiness and restore verification.

No commit, push, production deployment, service restart, mount, ACL change, or
production/scientific data mutation was performed during this integration.

## Scientific intake

- Added strict, versioned manifests for raw TIFFs, radargrams, digitized radar,
  navigation, automatic-picker output, and PDF derivatives.
- Added explicit product relationships and dataset-level provenance.
- Automatic-picker products are always marked scientifically `unvalidated`.
- Missing products remain explicit non-scientific placeholders and cannot claim
  a file path, size, or checksum.
- Added atomic, fingerprinted checkpoints for resumable and idempotent indexing.
- Rejected unsafe paths, invalid hashes, duplicate IDs, self/dangling
  relationships, and misleading product declarations.
- No coordinates, picks, calibration data, or observations are inferred.

Primary documentation: `icesee_jupyter_book/applications/frozen_legacies/intake_manifests.md`.

## Developer documentation access

- Owners retain Developer Guide access.
- Owners can grant/revoke access for maintainers and admins in Control Center.
- Both the eligible role and owner-issued capability are checked on every
  request; demotion revokes access and stale grants fail closed.
- Grant/revoke changes are atomic and audited.
- LIVIST developer API pages, inventory, search data, and sitemap are protected;
  its user manual remains available to ordinary users.
- Added service operations and owner-continuity guidance covering topology,
  durable state, secrets, staging, releases, rollback, delegation, daily
  evidence, recovery, and return from extended leave.

Primary documentation: `icesee_jupyter_book/docs/service_operations.md` and
`icesee_jupyter_book/docs/owner_continuity.md`.

## CEDAR readiness

- Added a fail-closed preflight for the exact `sec=sys` NFS exports, required
  mount options, source/mode checks, `_netdev`, UID:GID `978:977`, free bytes,
  inode capacity, the 5 GiB local reserve, scratch separation, durable-volume
  attestation, verified backup, and restore evidence.
- Added an opt-in service-user probe for locking, atomic rename, `fsync`, and
  SQLite WAL semantics; its isolated test data is removed after the probe.
- Verified backup `20261016T183425Z`: 93 files and all checksums valid.
- Completed an isolated restore drill successfully in 1.7 seconds.
- Current cutover is blocked correctly: proposed `/srv/cryostack` paths are
  local XFS and are not yet the two CEDAR mounts.

Primary documentation: `deployment/cedar_preflight.md` and
`deployment/storage_cedar_runbook.md`.

## Validation

- Integrated focused suite: 237 passed, 1 skipped after resolving one stale
  structural assertion that expected the superseded role-only documentation
  wrapper.
- Documentation/access rerun: 87 passed.
- CEDAR preflight unit suite: 11 passed.
- Supported repository suite (`external/` excluded): **3,835 passed, 5 skipped**
  in 7m58s.
- The raw repository sweep also collected independently managed vendored
  projects and stopped at missing project-specific environments (`URSA_Angelo`,
  Firedrake, and standalone LIVIST). These are outside the established
  CryoStack supported-suite boundary; no CryoStack assertion failed.
- Patch integrity checks passed.

## Runtime health

Read-only checks after validation:

- `cryostack-staging.service`: active, running for approximately six hours.
- Staging gateway `127.0.0.1:18080`: HTTP 302 to authentication (expected).
- Production gateway `127.0.0.1:8080`: HTTP 302 to authentication (expected).
- Root filesystem: 32 GiB free, 70% used.
- Scratch filesystem: 249 GiB free, 1% used.

## Deployment decision

The integrated code is regression-clean but was **not deployed**. A safe release
still requires browser validation on isolated staging with the new build. CEDAR
cutover must wait for the administrator-provided mounts/ACLs and a successful
service-user preflight. Production should not be restarted merely to expose
placeholder interfaces or unvalidated scientific outputs.

## Next actions

1. Publish the tested source tree as a new immutable staging release.
2. Run authenticated desktop/mobile browser checks for owner documentation
   delegation, LIVIST restrictions, Frozen Legacies placeholders, RIGGS context,
   navigation, LYRA/URSA history, and upload/product workflows.
3. After CEDAR mounts are present, run the preflight first in read-only mode,
   then the opt-in semantic probe as `cryostack-app`.
4. Perform a rehearsed migration and rollback on staging before production
   storage cutover.
5. Promote application changes only after the staging evidence is reviewed.
