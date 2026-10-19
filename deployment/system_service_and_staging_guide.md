# CryoStack services and staging environment guide

This guide teaches the service model and defines a non-production environment
for validating releases without interrupting production. Commands labelled
"production" require an approved change window and rollback plan.

## Who must do what

An individual person called "the administrator" is not inherently required.
The required authority depends on the action:

| Action | Required authority |
| --- | --- |
| Create a user-level practice service | CryoStack owner's normal account |
| Create a non-login OS account or system service | approved `sudo`/root access |
| Create local directories and assign ownership | approved `sudo`/root access |
| Change NFS mounts in `/etc/fstab` | approved `sudo`/root access |
| Create CEDAR exports or NAS-side NFSv4 ACL mappings | CEDAR/storage team |
| Deploy an application build into an already-approved release directory | release operator |

If the CryoStack owner has approved `sudo`, the owner can perform the VM-side
steps. The CEDAR team is still required for export policy, client allowlisting,
snapshots, and NAS identity mapping.

## What a service is

A systemd service is a declaration of how one long-running process starts,
stops, restarts, receives configuration, writes logs, and depends on other
resources. It replaces detached shell processes and process-name matching with
a supervised lifecycle.

Important fields are:

```ini
[Unit]
Description=What this process does
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=cryostack-app
Group=cryostack-app
WorkingDirectory=/opt/cryostack/current
EnvironmentFile=/etc/cryostack/production.env
ExecStart=/opt/cryostack/venv/bin/python /opt/cryostack/current/bin/example.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`ExecStart` must remain in the foreground. Systemd, not `nohup`, owns the
process. Never put passwords or tokens directly in a unit file.

## Safe learning exercise

Learn the lifecycle using a harmless user service before touching production:

1. Put a practice unit in `~/.config/systemd/user/`.
2. Run `systemctl --user daemon-reload`.
3. Start it with `systemctl --user start <name>`.
4. Inspect it with `systemctl --user status <name>` and
   `journalctl --user -u <name>`.
5. Stop and restart it.
6. Enable it only after its behavior is understood.

User services are useful for learning and development, but they do not create
the independent production identity required for CryoStack.

## Production service identity

Use a locked, non-login account such as `cryostack-app`, with a static UID/GID
allocated by the VM/storage administrators. Do not guess 1000 or 1001 and do
not permanently run production as the owner's personal account.

Keep roles separate:

- `cryostack-app`: gateway, relay, metadata, controlled workspace operations;
- `cryostack-kernel`: constrained notebook execution;
- release operator: installs immutable releases but does not serve requests;
- data curator: writes authoritative shared datasets from an approved host.

The final account-creation syntax depends on Georgia Tech identity policy and
must be approved before use. Record the selected username, UID, GID, NFSv4
principal mapping, home/shell policy, and owner in the deployment inventory.

### Current VM inventory (2026-10-16)

- service account: `cryostack-app`
- UID: `978`
- primary group: `cryostack-app`
- GID: `977`
- home: `/var/lib/cryostack`
- shell: `/sbin/nologin`
- validated staging unit: `cryostack-staging.service`
- staging ports: gateway `18080`, Run Center `18866`, IceSheets `18870`

The UID/GID are confirmed locally, but CEDAR `sec=sys` mapping and NFSv4 ACL
behavior remain a storage-team acceptance test before production use.

## Recommended service units

Supervise each failure domain independently:

- `cryostack-gateway.service` (localhost port 8080)
- `cryostack-relay.service` (localhost port 8899)
- `cryostack-voila@icesheets.service` (localhost port 8870)
- `cryostack-voila@run-center.service` (localhost port 8866)
- nginx remains the public TLS reverse proxy

The repository's `deployment/kernel-account/cryostack-voila@.service` is a
starting point, not a production installation instruction without review.

Every writer must fail closed when storage is absent. Use systemd mount
dependencies and application storage validation together. Never allow a
missing NFS mount to expose an ordinary local directory at the same path.

## Staging architecture

Staging is a complete independent deployment, not an admin page connected to
production data. Use a private owner/maintainer-only hostname such as
`staging.cryostack.eas.gatech.edu` (subject to DNS and certificate approval).

| Concern | Production | Staging |
| --- | --- | --- |
| Release | `/opt/cryostack/releases/<id>` | separate release directory or host |
| Configuration | `/etc/cryostack/production.env` | `/etc/cryostack/staging.env` |
| Database/state | production data root | independent staging data root |
| Workspaces | production CEDAR workspace | staging/test workspace export |
| Datasets | authoritative, read-only | read-only fixtures or approved sample |
| Hostname | `cryostack.eas.gatech.edu` | restricted staging hostname |
| Authentication | production | production-equivalent configuration, isolated sessions |
| Cloud account/resources | production | separate test resources and limits |

Staging must never use production SQLite files, writable production
workspaces, production sessions, or production job queues. Prefer sanitized
fixtures. If production-like data is essential, use an explicitly approved,
access-restricted copy and document its retention.

Verified SPRI navigation intake can be promoted without serving scratch
directly:

```bash
sudo deployment/systemd/promote_staging_navigation.sh
sudo deployment/systemd/install_staging_service.sh /home/bkyanjo3/CryoLauncher
```

The promotion validates the ten approved flight CSVs against the intake
manifest, installs a versioned read-only dataset owned by
`root:cryostack-app`, and atomically changes the staging-only `navigation-current`
symlink. The installer then deploys application code and restarts only
`cryostack-staging.service`. Neither command changes production data or nginx.

An approved RIGGS table uses the same immutable promotion model:

```bash
sudo deployment/systemd/promote_staging_riggs.sh \
  /approved/intake/riggs_stations.csv \
  /approved/intake/riggs.manifest.json
sudo deployment/systemd/install_staging_service.sh /home/bkyanjo3/CryoLauncher
```

The first command reuses the application's strict provenance and scientific
field validation before changing the staging-only `riggs/current` symlink.
The installer configures the layer only when that link exists. An absent RIGGS
release therefore remains an empty optional layer rather than a startup error.

Access to the staging/admin frontend should be owner-only by default and then
grantable to selected maintainers through CryoStack roles. Network restriction
or an identity-aware proxy should protect the hostname in addition to
application authorization.

## Scratch storage policy

The VM has a separate `/scratch` filesystem intended for disposable,
rebuildable work. Create `/scratch/cryostack` as a service-owned top-level
directory and keep its purpose explicit:

- `/scratch/cryostack/build-cache`: container and application build caches;
- `/scratch/cryostack/test-runs`: isolated test outputs;
- `/scratch/cryostack/working`: temporary scientific-processing working data;
- `/scratch/cryostack/staging-cache`: rebuildable staging caches.

Scratch must never be the only copy of user uploads, published results,
databases, authentication state, quota settings, catalog metadata, source
datasets, service secrets, or audit records. Jobs must tolerate scratch being
cleared. Apply age-based cleanup only inside named cache/run directories, and
publish required results to durable workspace storage before cleanup.

Point rootless Docker's data root or BuildKit cache at scratch only through a
documented configuration change and restart; do not move its live directory by
hand. Record cache limits and periodically report both root and scratch usage.

## Release flow without production interruption

1. Build an immutable candidate from a recorded commit.
2. Run repository tests in isolation.
3. Deploy the candidate to staging with staging-only state.
4. Run browser, authorization, workspace-isolation, scientific restriction,
   persistence, and restart tests.
5. Record the candidate identifier and evidence.
6. Back up production and verify rollback readiness.
7. Install the candidate as a new production release directory.
8. Switch the `current` symlink or equivalent release pointer atomically.
9. Restart managed services and run health checks.
10. If checks fail, point back to the previous immutable release and restart.

For genuinely zero-downtime releases, run blue and green gateway instances on
different local ports, validate the inactive instance, and switch nginx only
after it is healthy. Database migrations must remain backward-compatible while
both versions can run; otherwise use a documented short maintenance window.

## Required documentation and evidence

Maintain these records without secrets:

- service account and UID/GID ownership record;
- unit-file inventory and purpose of each service;
- configuration-variable inventory with secret locations redacted;
- port and nginx routing map;
- storage mount and ACL inventory;
- staging-to-production release checklist;
- backup, restore, rollback, and outage procedures;
- test results and release identifier for every production promotion;
- named owners and maintainers authorized for staging access.

Do not treat `systemctl start` as deployment approval. Production promotion is
a separate, auditable decision after staging evidence is complete.
