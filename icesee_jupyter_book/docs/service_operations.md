# Service operations and release runbook

This owner-controlled runbook is the canonical map from source change to a
recoverable CryoStack release. It records procedures and configuration names,
never passwords, tokens, private keys, service-account JSON, recovery codes,
or real secret values.

## Platform topology

| Component | Responsibility | Public boundary | Authoritative state |
|---|---|---|---|
| nginx | TLS termination and reverse proxy | HTTPS 443, HTTP redirect | system configuration and certificates |
| gateway (`bin/icesee_app.py`) | authentication, book, Control Center, app routing | proxied by nginx; localhost 8080 by default | auth and operations databases |
| Run Center Voilà | ICESEE configuration and runs | gateway `/icesee-gui/` | user workspace and result records |
| IceSheets Voilà | CryoLauncher application | gateway `/icesheets/` | user workspace and result records |
| Frozen Legacies | catalogs, imagery, products, reviews and picker jobs | gateway `/frozen-legacies/` | catalog DB, review store, workspaces and approved datasets |
| LIVIST | temperature product generation and publication workflow | gateway `/livist/` | LIVIST workspace and manifests |
| Connector relay | owner-bound remote/HPC connector sessions | gateway relay routes; localhost 8899 | relay token and transient sessions |
| Control Center | users, roles, quotas, diagnostics, audit and resources | gateway `/control/` | auth and operations databases |

The current development launcher is `deployment/services.sh`. The target
production model is independently supervised systemd failure domains as
documented in `deployment/system_service_and_staging_guide.md`. Do not confuse
a process started by the development launcher with proof that a production
unit will survive logout, reboot, mount loss, or host restart.

## Durable storage contract

`CRYOSTACK_DATA_ROOT` is the parent of authoritative application state. In a
durable production deployment set `CRYOSTACK_REQUIRE_DURABLE_STORAGE=1`; the
gateway must refuse startup if the marked volume or required stores are not in
place. Never allow a missing CEDAR/NFS mount to expose an ordinary local
directory at the same mount point.

Before a release or restart, record the resolved paths reported by the storage
layout tooling and verify all of the following are on approved durable storage:

- authentication, operations, catalog and quota metadata databases;
- user workspaces, uploads, generated products and publication records;
- configured data-source metadata and approved shared dataset releases;
- review snapshots, audit records and autonomous-work reports;
- any persistent connector artifact store or application-specific manifest.

Rebuildable caches and partial working files may use `/scratch/cryostack` only
when their loss is tolerated. Source checkouts, `/tmp`, the web root and an
unmounted local directory are not durable stores. See
`deployment/storage_cedar_runbook.md` for mount, identity, ACL, capacity,
snapshot, backup, outage and migration acceptance criteria.

## Configuration and secrets

Keep production and staging environment files separate and readable only by
their service identity. Documentation may name an environment variable and
its custodian, but must not contain its value. At minimum inventory:

- data root, durable-storage enforcement, workspace root and approved mounts;
- gateway, Voilà and relay ports and public route map;
- OAuth provider identifiers and secret *locations*;
- relay-control token location and rotation procedure;
- AWS profile/region and approved operator identities, never static keys;
- scientific executable, model and picker configuration;
- quotas, disk reserve, upload limits and retention policy;
- backup destination, encryption custody, schedule and restore owner.

The gateway forwards only the explicit `VOILA_ENV_ALLOWLIST` into notebook
services. A new variable does not reach a kernel until reviewed and added; do
not broaden the allow-list to pass secrets for convenience.

`CRYOSTACK_CLOUD_OPERATOR_USER_IDS` is the deployment-controlled exception
that permits named CryoStack users to run cloud operations with the host's
ambient AWS credentials. Its value is a comma-separated list of stable,
authenticated CryoStack user IDs (not email addresses, roles, or AWS account
IDs); an unset or empty list fails closed. Ordinary users must connect and use
their own verified BYO-AWS role. Keep production and staging lists separate,
have the owner review every addition and removal, and verify both an allowed
operator and a denied ordinary account before release. The list is not a
secret, but it is authorization-sensitive configuration: record its custodian
and change reason without copying credentials into documentation or reports.

## Development-to-staging workflow

1. Reserve affected files/components in the shared work ledger and identify
   schema, API, authorization, storage and navigation interfaces.
2. Make the smallest change in an isolated branch/worktree. Preserve unrelated
   work and do not use production state for tests.
3. Update architecture, user/developer guidance, configuration inventory,
   failure behavior and rollback instructions with the code.
4. Run focused unit/integration tests, then the canonical first-party suite in
   `owner_continuity.md`. Record revision, command, totals, duration and skips.
5. Build an immutable candidate with `deployment/cryostack_build.py`; run the
   applicable `deployment/preflight.py` checks.
6. Install only to isolated staging state and ports. Staging must not share
   production sessions, writable workspaces, SQLite files, queues or cloud
   resources.
7. Validate authentication, negative authorization, owner isolation, desktop
   and narrow/mobile navigation, representative data size, restart persistence,
   mount loss, backup/restore and application health.
8. Produce release evidence and request owner approval. A successful staging
   run is not permission to deploy production.

## Production release gate

Do not begin production mutation until the owner approves the exact candidate,
window and rollback operator. The evidence package must include:

- immutable release identifier and complete reviewed diff;
- dependency/configuration/schema changes and compatibility assessment;
- focused and full test results plus browser/performance evidence;
- durable-store and free-space/inode checks;
- verified backup manifest and a restore rehearsal in an empty target;
- service-specific smoke checks and explicit rollback trigger;
- scientific provenance and validation limitations;
- known issues, monitoring plan and named responders.

Install beside the current immutable release. Run preflight against the real
service identity and configuration without exposing values. Switch the release
pointer atomically, restart only affected supervised units, and immediately
run health, login, role, workspace-isolation, storage-location, representative
application and audit-log checks.

## Rollback

Rollback is a release operation, not an improvised Git command.

1. Stop accepting new writes if continuing could make state incompatible.
2. Preserve logs, release identifier, health output and the failed candidate;
   do not erase evidence.
3. Switch the release pointer to the last verified compatible release.
4. Restore configuration from its versioned non-secret record.
5. Restore data only when the migration plan requires it, using the verified
   backup and documented ordering. Never overwrite the only good copy.
6. Restart affected units in dependency order and repeat all post-release
   checks.
7. Record incident times, operator, trigger, state handling, verification and
   follow-up work in the audit/release report.

If a database migration is not backward-compatible, code rollback alone is
unsafe. Its release plan must define forward repair or a rehearsed database
restore before approval.

## Routine operation and evidence

Use `deployment/services.sh status` only for the current development launcher.
For managed units use `systemctl status` and `journalctl -u`, and confirm the
public route through nginx. Monitor root and durable-volume capacity, inodes,
mount identity, failed units, certificate expiry, backup age/verification,
job failures, audit anomalies and external dependency health.

Daily or release reports should state outcomes, tests, current work, blockers,
risks, suggested improvements, approvals needed, next reservations and a clear
deployment recommendation. Store them on the durable autonomy/report root,
outside the source checkout.

## Service-specific handoff index

- Core architecture and frontend: `dev_architecture.md`, `dev_frontend.md`
- Execution, models and results: `dev_execution.md`, `dev_models_results.md`
- Connector and relay: `dev_connector.md`
- Testing and deployment: `dev_testing.md`, `dev_deployment.md`
- Owner continuity and leave plan: `owner_continuity.md`
- Frozen Legacies internals/API: application Developer Guide and API Reference
- Deployment framework: `deployment/README.md`
- System services/staging: `deployment/system_service_and_staging_guide.md`
- CEDAR/durable storage: `deployment/storage_cedar_runbook.md`

Each service guide must eventually state ownership, process/unit, dependencies,
ports/routes, configuration, secret references, authoritative data, normal
operation, health checks, logs, common failures, backup/restore, deployment,
rollback, tests and known limitations. Missing items remain documentation debt,
not assumed knowledge.

## First day back after extended leave

1. Read `owner_continuity.md`, this runbook, the latest release report and open
   risk register before changing production.
2. Identify the running release and compare all intervening releases and
   migrations with their evidence.
3. Verify service units, public routes, authentication, owner/delegated access,
   workspace isolation, mount identity/capacity, backups and audit records.
4. Review scientific validation state, failed/incomplete jobs, dependency and
   security notices, certificate status and pending owner decisions.
5. Rehearse restore and rollback in a non-production target before rotating
   credentials or changing durable storage.
