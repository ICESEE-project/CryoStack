# CryoStack durable storage and CEDAR runbook

This runbook is an operator procedure, not evidence that CEDAR is configured.

## Current CryoStack deployment decision (2026-10-19)

The CryoStack VM currently mounts the CEDAR exports through the storage team's
authless SMB proxy:

- `//cos-smb01.cos.gatech.edu/cryostack-users` at
  `/srv/cryostack/workspace/users`;
- `//cos-smb01.cos.gatech.edu/cryostack-datasets` at
  `/srv/cryostack/workspace/datasets`.

Both mounts force the `cryostack-app` identity (`uid=978`, `gid=977`). The
accepted production boundary currently uses only explicit immutable scientific
dataset releases on SMB. Private workspaces, SQLite, authentication, quota,
catalog, intake chunks/session records/writer locks, audit and job-coordination
state remain on the VM's
marked durable XFS volume and must be backed up to CEDAR: the real SMB
acceptance probe passes atomic rename and fsync but its lock/WAL behavior is not
accepted for mutable state. The mounted users share is therefore acceptance
evidence only; it is not an approved CryoStack workspace destination.

After publication, the application dataset mount must be read-only. Until the
current read/write mount is changed by an authorized operator and the
read-only dataset-only preflight passes, treat the storage boundary as an open
release blocker. Do not move workspaces, resumable intake, or transactional
state to SMB to make the preflight green. Supply the active intake path with
`--intake-root`; a dataset-only preflight fails if it is omitted or resolves to
the dataset mount.

The SMB proxy does not support application-created symbolic links. Dataset
releases therefore use immutable explicit directories and a plain `CURRENT`
marker containing the relative active release path. Runtime configuration must
use the explicit immutable path; it must not assume `current` is a symlink.
Do not put credentials, tokens, private keys, or recovery codes in this file or
in command output attached to a release report.

## Readiness gate

Before migration or deployment, obtain the authoritative CEDAR mount path,
filesystem/service type, capacity allocation, snapshot/backup policy,
retention, recovery owner, and tested recovery objective from the storage
administrator. Confirm that the intended service account can traverse and
write the mount while other accounts cannot read private workspace content.
Record evidence outside this repository.

Use [`cedar_preflight.py`](cedar_preflight.py) and the companion
[`cedar_preflight.md`](cedar_preflight.md) to collect this evidence. Its
default mode is read-only; its explicit service-identity write probe validates
byte-range locking, atomic rename, file/directory fsync and SQLite WAL in one
private temporary directory that it removes. A result with `ok: true` is not
enough for cutover when `ready_for_cutover` is false: every mandatory
`not_run` check must also be completed.

The default acceptance floors are 5 GiB and 100,000 available inodes on each
persistent filesystem. Record administrator-approved byte and inode thresholds
in the release plan and pass them as `--minimum-free-gib` and
`--minimum-free-inodes`. Alert from the preflight's numeric JSON fields before
either floor is reached; a successful one-time check is not ongoing capacity
monitoring, and thresholds must not be reduced just to clear a release gate.

### Proposed CEDAR layout (pending storage-team approval)

The preferred design is a system-authenticated NFSv4 mount on the CryoStack
VM.  Do not depend on a human Kerberos ticket: it expires and makes service
availability depend on an interactive login.  Mount either the approved
`cos-lab-nuiaq/cryostack` subtree at a stable host path (for example
`/srv/cryostack-data`) or mount its approved subdirectories there with systemd
ordering that starts CryoStack only after the mounts are present.

The storage team has proposed NFS 4.1 exports restricted to the CryoStack VM
and PACE, using `sec=sys`, `hard`, `timeo=600`, 256-KiB read/write sizes,
`noatime`, and `_netdev`.  The user export should be mounted `rw`.  The shared
dataset export should normally be mounted `ro` on the CryoStack VM; approved
curators may retain write access from PACE.  Add `nofail` only if every
CryoStack writer independently fails closed when the mount is absent; otherwise
make service startup require the mount explicitly.

Do **not** make `cryostack/users` mode `0777`.  Use a dedicated, non-login
CryoStack service identity and inheritable NFSv4 ACLs instead:

- service identity: traverse and read/write the application data root;
- storage administrators: administrative access required by policy;
- `users/<opaque-user-id>`: no access for unrelated OS accounts (normally
  `0700`, plus the explicit service/admin ACLs);
- shared scientific datasets: read-only to the application, with write access
  limited to approved data curators;
- rebuildable cache: separate from authoritative storage and safe to clear.

Do not infer a service identity from common numeric IDs such as 1000 or 1001.
Create or confirm a dedicated non-login application account with an explicitly
reserved static UID/GID, then record that mapping on both the VM and storage
system.  Notebook kernels may use a separate constrained account; that account
must not automatically receive broad application-storage access.

As of 2026-10-16 the VM service identity is `cryostack-app`, UID `978`, primary
GID `977`, home `/var/lib/cryostack`, shell `/sbin/nologin`. An isolated staging
gateway and its two Voilà children have been verified running under that
identity. CEDAR mapping of UID 978/GID 977 remains an explicit acceptance test.

Keep the server export paths proposed by the storage team, but avoid nesting
the new `sec=sys` mounts below the existing Kerberos-dependent
`/projects/cos-lab-nuiaq` mount. Recommended client targets are:

- `.../cryostack/users` -> `/srv/cryostack/workspace/users` (`rw`);
- `.../cryostack/dataset` -> `/srv/cryostack/datasets` (`rw` only when the
  authorized ingestion service must write; otherwise `ro`).

Set `CRYOSTACK_WORKSPACE_ROOT=/srv/cryostack/workspace`. Restrict dataset
writes to `cryostack-app` and approved curators; ordinary application users do
not receive filesystem identities or direct NFS access.

The web application's user checks remain required, but they are not a
substitute for filesystem isolation.  A world-writable parent also permits
untrusted local processes to consume capacity or manipulate names even if
individual files are protected.

CryoStack's single data root contains SQLite databases for authentication,
Control Center settings and quotas, LIVIST, and Frozen Legacies catalog and
storage metadata.  Before putting `db/` on CEDAR, the storage team must confirm
supported POSIX byte-range locking, rename/fsync durability, NFS version and
mount options, UID/GID or NFSv4 identity mapping, and the behavior of SQLite
journals under concurrent access.  Prove these with a non-production
concurrency, abrupt-restart, and integrity rehearsal.  If CEDAR cannot provide
those semantics, keep databases on approved durable block storage (backed up
to CEDAR) or migrate them to a supported database service; do not silently
place SQLite WAL files on an unverified network filesystem.

On the target host, while the services are still pointed at their existing
storage:

```bash
findmnt --target /approved/cryostack/data
df -h /approved/cryostack/data
df -i /approved/cryostack/data
python deployment/cryostack_storage.py init-volume /approved/cryostack/data \
  --attest "<durability basis and retention; no secrets>" --operator "<operator>"
CRYOSTACK_DATA_ROOT=/approved/cryostack/data \
  python deployment/cryostack_storage.py check
```

`check` must report no problems for any durable store. A marker copied from a
different directory is invalid: create it only with `init-volume` on the
mounted target. Keep `CRYOSTACK_REQUIRE_DURABLE_STORAGE=1` in the service
environment so a missing/replaced mount fails closed instead of filling the
host filesystem. Capacity checks and application quotas are complementary:
the filesystem must have enough free bytes and inodes, and Control Center
workspace quotas must remain enabled for per-user limits.

## Backup and restore rehearsal

Create backups outside the source checkout and outside all workspace roots.
The backup contains password hashes, session identifiers, and private user
content; restrict its directory and use encrypted off-host export.

```bash
python deployment/cryostack_backup.py create --dest /approved/backup/location
python deployment/cryostack_backup.py verify /approved/backup/location/<stamp>
python deployment/cryostack_backup.py drill /approved/backup/location/<stamp> \
  --scratch /approved/empty/scratch
python deployment/cryostack_backup.py export /approved/backup/location/<stamp> \
  --recipient-key /approved/recovery-public-key.asc \
  --dest /approved/off-host-staging
```

For release evidence, retain the command status, backup stamp, component
counts, checksum result, encrypted archive checksum, and drill result. Do not
copy database or workspace contents into the report. Recovery is not proven by
backup creation alone; an authorized operator must decrypt the off-host copy
on a recovery host and complete `unpack`, `verify`, and `drill`.
When `CRYOSTACK_FROZEN_LEGACIES_INTAKE_ROOT` is configured, the backup also
records the entire intake root as `frozen-legacies-intake`: open session
manifests and chunks, janitor audit state, commit receipts, and finalized
releases. The copy holds the intake volume lock, refuses symbolic links, and
therefore represents one writer-consistent point in time. A restore places it
at `<data-root>/frozen_legacies/intakes` and reports the exact intake-root
environment setting to use; do not redirect a service to it until the separate
non-production reconciliation rehearsal and owner review are complete.
Current backups authenticate both regular-file contents and workspace symlink
target text without following links. Backups created before manifest version 2
remain readable, but lack authenticated symlink targets; replace them under the
approved retention policy rather than treating them as equivalent evidence.

## Planned cutover

Production cutover requires owner approval and an approved backup, migration,
verification, rollback, and recovery plan. Stop writers before migration; do
not restart or redirect production as part of a dry run.

```bash
python deployment/cryostack_storage.py migrate \
  --installation /path/to/CryoLauncher \
  --data-root /approved/cryostack/data --dry-run
```

Review conflicts, absent stores, and links into the installation. After an
approved final backup and service stop, run the same command without
`--dry-run`. It copies and verifies state without deleting the source. Review
`MIGRATION.json`, run `cryostack_storage.py check` with the intended service
environment, then start services only under the release operator's approved
procedure. Verify authentication, one authorized workspace, one negative
cross-user access case, catalog access, quota enforcement, and durable state
after a controlled restart.

## Restore and rollback

Restore only to a new, empty, mounted and marked volume. Never restore over an
active data root.

```bash
python deployment/cryostack_backup.py restore /approved/backup/location/<stamp> \
  --data-root /approved/empty/marked-volume
CRYOSTACK_DATA_ROOT=/approved/empty/marked-volume \
  CRYOSTACK_REQUIRE_DURABLE_STORAGE=1 \
  python deployment/cryostack_storage.py check
```

Review `RESTORE.json` and repeat the authorization and application smoke tests
before any approved service redirection. Rollback means stopping writers and
pointing the service environment back to the previously verified, unchanged
root; it does not mean copying files over either root.

## Mount or storage outage

1. Stop new writes and leave the durable-storage requirement enabled. Do not
   create a replacement marker on the host filesystem beneath a missing mount.
2. Capture `findmnt`, `df -h`, `df -i`, and `cryostack_storage.py show` output;
   avoid commands that enumerate private filenames or file contents.
3. Escalate to the storage administrator with mount path, time, host, volume
   marker ID, and sanitized errors. Do not change external permissions.
4. After storage returns, run `cryostack_storage.py check`, verify the newest
   backup, and check filesystem capacity. If the marker path/device check
   fails, keep services stopped and treat the mount as unverified.
5. Resume only with release-operator approval. Verify state from before the
   outage, then perform a controlled write/read and restart persistence check.

If the original volume cannot be recovered, restore the latest verified backup
to a separate approved volume. Preserve the failed volume for investigation;
do not delete, reformat, or merge it during incident response.

## Current external blocker

Repository checks can prove path resolution, copied/replaced-marker rejection,
atomic writes, checksums, and restore behavior. They cannot prove the actual
CEDAR mount, capacity, access controls, locking semantics, off-host custody, or
recovery time. The storage administrator reports that CEDAR has daily on-disk
snapshots retained for 30 days and is considering system-authenticated VM
mounts for `cryostack/users` and `cryostack/dataset`; these facts remain pending
operator verification. The share currently has a 10-TB quota and the wider
CEDAR service reports substantial spare inode capacity; verify the quota and
free capacity at the mounted subtree during acceptance rather than relying on
cluster-wide totals. Snapshots are exposed through the share's inherited-access
`.snapshot` directory. They improve short-term recovery but do not replace
an encrypted off-host backup or a restore drill. Final approval still requires
the exact export and mount paths/options, service identity mapping, ACL and
inheritance listing, capacity/quota/inode limits, snapshot restore procedure,
and a non-production rehearsal on the deployment host.
