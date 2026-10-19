# CEDAR SMB acceptance checkpoint — 19 October 2026

## Scope

Read-only inspection and one isolated write-semantics probe were run against:

- `//cos-smb01.cos.gatech.edu/cryostack-users` mounted at
  `/srv/cryostack/workspace/users`;
- `//cos-smb01.cos.gatech.edu/cryostack-datasets` mounted at
  `/srv/cryostack/workspace/datasets`.

No CryoStack service was pointed at these paths, and no production or user
data was migrated. The write probe used one randomly named directory under the
workspace share. Its delayed empty directory was inspected and removed after
the probe.

## Passed evidence

- Both configured paths are exact CIFS mount points backed by the expected
  `cos-smb01` shares.
- Runtime protocol is SMB 3.1.1 with `sec=none`, `cache=strict`, `forceuid`,
  and `forcegid`.
- Runtime ownership is forced to `978:977` (`cryostack-app`).
- Both matching `fstab` entries contain `_netdev` and `nofail`.
- Workspace and dataset shares are read/write for the acceptance phase.
- Each share reports 10 TiB available.
- Scratch remains local XFS and is on a different filesystem.
- File fsync, directory fsync, and atomic rename passed on the workspace share.

SMB does not report inode capacity through `statvfs` on this client (`0/0`).
The preflight records that as a warning and requires server-side file/object
count monitoring instead of treating it as exhausted capacity.

## Blocking evidence

- The cross-process POSIX byte-range-lock probe failed while the parent held
  the lock; the child process exited instead of observing a clean `blocked`
  result.
- SQLite WAL validation failed with `OperationalError: database is locked`.
- Immediate cleanup reported a non-empty directory because SMB had not yet
  released all entries. A later inspection found it empty, and it was removed.
- Runtime CIFS reports `soft` timeout behavior. The active semantics failures
  mean this warning cannot yet be waived.

## Decision

**No workspace or database cutover.** The dataset share remains a plausible
target for large immutable TIFF/navigation products, subject to ingestion and
read-back validation. SQLite databases, account data, quotas, catalogs, and
other transactional state must remain on durable block storage unless the SMB
locking failure is resolved and the complete probe passes.

Before cutover, rerun the active probe as the exact `cryostack-app` service
identity after the storage team changes locking-related server or mount
configuration. After ingestion is complete, make the dataset mount read-only
for the application if that remains the agreed operating model.
