# Production navigation deployment — 2026-10-16

## Outcome

The verified SPRI navigation-only release was deployed to the Frozen Legacies
production application. The release adds flights 125, 126, 127, 128, 137,
138, 139, 141, 143, and 149 without creating radar-image assets or changing
scientific observations.

The TIFF archive and CEDAR storage were not changed. Radar imagery remains a
separate intake milestone.

## Release and rollback evidence

- Source archive SHA-256:
  `177c92df4cc0f690db666217bb0c7982ebb419fe5bd1d6c1c385abcb23f7ab8d`
- Production release:
  `/home/bkyanjo3/cryostack-data/datasets/spri/navigation-releases/nav-177c92df4cc0f690`
- Atomic current link:
  `/home/bkyanjo3/cryostack-data/datasets/spri/navigation-current`
- Pre-deployment backup:
  `/home/bkyanjo3/cryostack-backups/20261016T183425Z`
- Backup verification: 93 files, all declared components present, no problems.

## Validation

- Supported repository suite before deployment: 3,625 passed, 6 skipped.
- Focused navigation tests after the runtime-launcher change: 4 passed.
- Persistence crash/restart test: 1 passed.
- Published navigation: 10 files, 10 flights, 11,655 positioned records,
  zero invalid files.
- Local gateway: HTTP 302 to authentication, as expected.
- Anonymous navigation API: HTTP 401, as expected.
- Public HTTPS gateway: HTTP 302 to authentication, as expected.
- Ports 8080, 8866, 8870, and 8899 are listening on localhost only.
- Post-start application and relay logs contained no errors.

The authenticated workflow and exact ten-flight payload were validated in the
isolated staging gateway before production. Production authentication was not
bypassed to manufacture a test session.

## Deployment incident and correction

The legacy `deployment/services.sh restart` selector matched the SSH control
command because that command contained the application's absolute path. It
stopped the old application and then terminated its own control session before
starting the replacement. No data operation was in progress. Production was
started immediately from the already validated candidate with its protected
login environment; all required authentication and relay settings were
confirmed present without printing their values.

The lifecycle selector now excludes the manager process and all ancestors.
Navigation defaults were also added to the launcher so a future operator
restart cannot silently remove the new map coverage.

## Current limits

- Production still uses the legacy user-owned process manager. Migration to
  the reviewed `cryostack-app` system service remains pending.
- Production navigation currently resides on durable local XFS. It should move
  to CEDAR only after the new `sec=sys` mounts, static UID/GID mapping, ACL
  inheritance, atomic rename, locking, and `fsync` behavior are verified.
- Navigation-only flights do not imply that matching radar TIFFs, digitized
  radar products, or automatic-picker outputs are installed.
