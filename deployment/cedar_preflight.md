# CEDAR acceptance preflight

`deployment/cedar_preflight.py` produces sanitized, machine-readable evidence
for the CryoStack CEDAR decision. It is an acceptance gate, not a mount or
deployment script. It cannot edit `/etc/fstab`, mount an export, create ACLs,
migrate data, restart a service, or alter production configuration.

## Intended storage boundary

Keep the three classes of storage explicit:

| Storage | Purpose | Persistence | Access |
|---|---|---|---|
| workspace CEDAR export | all private user work across applications | authoritative, snapshotted | `cryostack-app` read/write; no unrelated local users |
| dataset CEDAR export | shared scientific TIFFs, navigation, picker products | authoritative, snapshotted | application read-only by default; narrowly authorized ingestion may write |
| scratch filesystem | build cache, test runs, processing intermediates | disposable and rebuildable | service-only; never databases, accounts, quotas, catalogs or sole copies |

Authoritative databases and metadata need a fourth decision. Do not put the
SQLite files on CEDAR until the isolated WAL/locking/fsync probe passes on the
real export. Until then, use an explicitly durable block-backed state volume,
back it up to CEDAR, and keep an encrypted off-host backup. Ordinary VM XFS is
not durable merely because it survives a process restart.

Recommended client paths avoid nesting new `sec=sys` mounts under the existing
Kerberos-dependent `/projects/cos-lab-nuiaq` mount:

- workspace export -> `/srv/cryostack/workspace/users`;
- dataset export -> `/srv/cryostack/datasets`;
- local rebuildable work -> `/scratch/cryostack`.

With that layout, set `CRYOSTACK_WORKSPACE_ROOT=/srv/cryostack/workspace`.
`CRYOSTACK_DATA_ROOT` should point to the separately approved state volume.
`CRYOSTACK_REQUIRE_DURABLE_STORAGE=1` must stay enabled so a missing mount or
replaced volume fails closed instead of filling the root disk.

## Read-only inspection

Run this first as an ordinary operator. It reads account records, mount tables,
capacity, the CryoStack volume marker and (when supplied) backup checksums. It
does not enumerate user files or write to either export.

```bash
python deployment/cedar_preflight.py \
  --workspace /srv/cryostack/workspace/users \
  --workspace-source cedar-cos.nas.gatech.edu:/cedar_cos/cos-lab-nuiaq/cryostack/users \
  --dataset /srv/cryostack/datasets \
  --dataset-source cedar-cos.nas.gatech.edu:/cedar_cos/cos-lab-nuiaq/cryostack/dataset \
  --dataset-mode ro \
  --state-root /approved/cryostack-state \
  --scratch /scratch/cryostack \
  --backup /approved/backups/<stamp>
```

Use `--dataset-mode rw` only if this gateway is the approved ingestion writer.
That makes the mount writable, but the CEDAR ACL must still restrict writes to
UID/GID `978:977` and approved curators. A general web user never receives an
NFS identity.

The command exits nonzero until all acceptance evidence is present. `ok` means
no inspected condition failed; `ready_for_cutover` additionally requires that
no mandatory check remains `not_run`. Warnings do not hide failures.

By default each persistent filesystem must retain at least 5 GiB and 100,000
free inodes. Set site-approved acceptance floors with `--minimum-free-gib` and
`--minimum-free-inodes`; do not lower either merely to make a preflight pass.
The JSON records the measured totals, available capacity, and applied floors so
the same fields can feed monitoring and release evidence without listing data.

## Isolated filesystem semantics probe

After the storage administrator has installed the exact mount and ACL, run the
active probe as `cryostack-app` using the site's approved service-execution
procedure:

```bash
python deployment/cedar_preflight.py \
  --workspace /srv/cryostack/workspace/users \
  --workspace-source cedar-cos.nas.gatech.edu:/cedar_cos/cos-lab-nuiaq/cryostack/users \
  --dataset /srv/cryostack/datasets \
  --dataset-source cedar-cos.nas.gatech.edu:/cedar_cos/cos-lab-nuiaq/cryostack/dataset \
  --dataset-mode ro \
  --state-root /approved/cryostack-state \
  --scratch /scratch/cryostack \
  --backup /approved/backups/<stamp> \
  --drill-scratch /scratch/cryostack/restore-drill \
  --write-probe
```

The probe refuses to run unless the caller is UID/GID `978:977` and the
workspace path is itself an NFS mount. It uses one private random directory and
tests:

- file fsync, directory fsync and atomic rename;
- a POSIX byte-range lock observed by a second process;
- SQLite WAL, an excluded concurrent writer, a later successful writer and
  `PRAGMA integrity_check`;
- cleanup followed by a parent-directory fsync.

Failure to remove the isolated directory is reported as a hard failure. The
tool never opens, lists or modifies application workspaces.

The restore drill is also isolated. It verifies the backup before restoring to
the explicitly supplied empty scratch directory and removes the restored copy
when finished.

## What must pass

- `cryostack-app` resolves exactly to UID 978 and primary GID 977.
- Both paths are exact NFS mount points, not local directories beneath a
  missing mount.
- The source exports match the approved CEDAR exports.
- Runtime options include `sec=sys`, `hard`, `noatime`, NFS 4.1 or newer, and
  the requested read/write mode. The matching fstab entries include `_netdev`.
- Workspace, dataset and state filesystems retain the configured free-byte and
  free-inode reserves.
- Scratch is local, outside every persistent root, and on a separate device.
- The state root has a valid on-device CryoStack durable-volume marker.
- A current backup verifies and a restore drill opens every component.
- The active lock, rename, fsync and SQLite checks pass on the real export.

Keep the JSON output with the change record. It contains paths and capacity but
not account emails, workspace names, file names, file contents or credentials.

## Quota and free-space behavior

CryoStack has one workspace allowance per user across applications. The
default and per-user overrides are persisted in the storage database. Changing
the default immediately affects accounts without an override; explicit
overrides remain unchanged. Existing files are never deleted when a quota is
lowered. Reads and deletions continue, while new writes are blocked.

The write guard checks both the user allowance and `disk_reserve_bytes`
(currently 5 GiB by default). Frozen Legacies uploads, shared workspace-manager
writes and LIVIST starts use this policy; LIVIST also keeps its separate job
reserve and stops a running generator before exhausting it. Reservations are
process-local, so the currently supported topology remains one writer gateway.
A multi-gateway deployment needs a database-backed reservation/lease before it
is safe.

Once workspaces move to CEDAR, their `statvfs` guard protects the CEDAR
filesystem, not the VM root or scratch. The preflight therefore checks each
filesystem independently. Production monitoring must do the same; a CEDAR
quota does not protect local logs, databases, caches or scratch.

## Cutover remains manual

After a clean preflight, use the dry-run migration and backup procedure in
`storage_cedar_runbook.md`. Review the plan before stopping writers. Do not use
the preflight result as authorization to mount, migrate, deploy, or delete the
old root. Rollback is a service configuration change back to the unchanged,
verified old root—not a merge of old and new data.
