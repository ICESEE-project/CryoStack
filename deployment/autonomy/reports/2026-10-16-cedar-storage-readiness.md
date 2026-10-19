# CEDAR storage-readiness advancement — 2026-10-16

## Outcome

CryoStack now has a fail-closed, non-destructive CEDAR acceptance gate. No
CEDAR mount, ACL, service, production configuration, source data or production
workspace was changed.

Current recommendation: **do not cut over yet**. The CryoStack service identity
and backup/restore path are verified, but the proposed `/srv/cryostack` CEDAR
exports are not mounted and the real-export write-semantics probe cannot run
until the storage administrator completes the `sec=sys` mounts and ACL mapping.

## Added

- `deployment/cedar_preflight.py`
  - verifies the exact mount points and approved export names;
  - requires NFS 4.1+, `sec=sys`, `hard`, `noatime`, the intended access mode,
    and matching `_netdev` fstab entries;
  - verifies `cryostack-app` is UID/GID `978:977` with login disabled;
  - reports free bytes and inodes against the 5-GiB reserve;
  - rejects scratch overlap, network-backed scratch and shared devices;
  - verifies the durable state-volume marker;
  - verifies a backup and can run a disposable restore drill;
  - has an explicit service-identity-only probe for POSIX locks, atomic rename,
    file/directory fsync and SQLite WAL integrity;
  - emits sanitized JSON and never lists workspace contents.
- `deployment/cedar_preflight.md`: architecture boundary, exact operator
  commands, evidence interpretation and cutover restrictions.
- `deployment/tests/test_cedar_preflight.py`: parser, mount, mode, safety,
  capacity, scratch, identity refusal, semantic-probe cleanup and error-path
  coverage.
- `deployment/storage_cedar_runbook.md` now makes the preflight result part of
  the formal readiness gate.

## Current-host evidence

Read-only inspection using the proposed exports and client paths found:

- **pass:** `cryostack-app` resolves to UID 978 / GID 977, home
  `/var/lib/cryostack`, shell `/sbin/nologin`;
- **pass:** current production state root has a valid on-device volume marker;
- **pass:** state volume had about 34.8 GB available, above the 5-GiB reserve,
  with more than 52 million available inodes at inspection time;
- **pass:** `/scratch/cryostack` is local XFS and is on a separate device from
  the current production state root;
- **pass:** production backup `20261016T183425Z` verified all 93 files;
- **pass:** that backup restored into disposable scratch, every component
  opened successfully in 1.7 seconds, and the drill directory was removed;
- **fail:** `/srv/cryostack/workspace/users` is not an exact NFS mount;
- **fail:** `/srv/cryostack/datasets` is not an exact NFS mount;
- **fail:** neither proposed path currently resolves to its CEDAR export or a
  matching `_netdev` fstab entry;
- **not run:** real CEDAR byte-range lock, rename/fsync and SQLite WAL probe,
  because no approved export is mounted and the probe correctly refuses a
  local directory.

The current host result was 14 pass, 6 warning, 17 fail and 1 not run. The
warnings are the proposed tuning values (`timeo`, `rsize`, `wsize`) being absent
because the paths are not NFS mounts; the hard failures already block cutover.

## Quota and capacity audit

The shared storage policy is already substantially implemented:

- one owner-root allowance covers Frozen Legacies, LIVIST, uploaded datasets,
  CryoLauncher and ICESEE workspace files;
- the default quota is globally configurable and individual overrides remain
  explicit;
- lowering a quota never deletes existing files; reads and deletion remain
  available while new writes are refused;
- users can select application scopes and permanently delete them to recover
  space, with confirmation and an audit record;
- writes are checked against both the user quota and the global
  `disk_reserve_bytes` (5 GiB by default);
- LIVIST additionally requires its job reserve and stops a running generator
  if free space falls below half that reserve.

Two topology constraints remain important:

1. In-flight quota reservations are process-local. Keep one writer gateway
   until reservations become database-backed leases.
2. After workspaces move to CEDAR, their `statvfs` guard protects CEDAR, not
   local root, state or scratch. Monitor and reserve each filesystem separately.

## Tests

- New preflight tests: **11 passed**.
- Combined storage, migration, backup, quota and workspace suite:
  **211 passed** after rerunning outside the restricted localhost/GPG sandbox.
- Python compilation, lint (when installed), and `git diff --check`: passed.

The first combined run inside the restricted tool sandbox could not open
localhost test sockets or create a disposable GPG key. The identical suite
passed when granted those test-only capabilities; this was not an application
failure.

## Administrator dependencies and next sequence

1. Storage administrator maps CEDAR `sec=sys` ACLs to UID/GID `978:977` and
   confirms inherited private-workspace permissions.
2. Install the two exact mounts at `/srv/cryostack/workspace/users` and
   `/srv/cryostack/datasets`, with systemd network ordering. Keep datasets
   read-only unless this service is explicitly approved to ingest.
3. Run the read-only preflight, then the active probe as `cryostack-app`.
4. Decide database placement from the real SQLite result. A failed or
   unavailable result means databases remain on approved durable block storage
   and are backed up to CEDAR.
5. Create and verify a fresh backup, repeat the restore drill, then run
   `cryostack_storage.py migrate --dry-run` under the intended environment.
6. Review conflicts and rollback before any separately approved cutover.

Snapshots retained for 30 days remain valuable short-term recovery, but they
do not replace the encrypted off-host backup or restore rehearsal.
