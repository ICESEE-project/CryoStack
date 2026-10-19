# CryoStack production application deployment — 2026-10-16

## Scope

Deployed the regression-tested application tree by restarting only the
production gateway and the two production Voilà processes. The connector
relay, nginx, staging service, mounts, ACLs, CEDAR configuration, and all
scientific and user data were left unchanged.

Included application-level changes:

- Frozen Legacies RIGGS-ready optional context layer (empty until approved
  source data is configured);
- honest radar/product placeholder panels for products not yet ingested;
- strict scientific intake manifests and resumable indexing checkpoints;
- owner-controlled Developer Guide delegation and LIVIST developer-doc gates;
- operations, continuity, scientific platform, and storage documentation;
- previously regression-tested navigation, LYRA, storage/quota, and UI work in
  the current application tree.

Excluded:

- CEDAR cutover or migration;
- RIGGS data promotion;
- TIFF or other scientific dataset ingestion;
- staging system-service update, because the root installer requires an
  interactive VM sudo authorization;
- commits, pushes, and repository staging.

## Release gates

- Supported repository suite: 3,835 passed, 5 skipped.
- Frozen Legacies deployment preflight: passed.
- Pre-deployment health check: passed.
- Backup: `/home/bkyanjo3/cryostack-backups/20261017T010944Z`.
- Backup contents: 93 files, 211,385,967 bytes; every component and checksum
  verified.
- Isolated restore drill: passed in 1.58 seconds; restored copy removed.

## Deployment

Command: `deployment/services.sh restart-gui`

New production processes started at approximately 21:11 America/New_York:

- gateway PID 3942875, port 8080;
- IceSheets Voilà PID 3942888, port 8870;
- Run Center Voilà PID 3942889, port 8866.

The existing connector relay PID 3802602 on port 8899 remained running.

## Post-deployment validation

- CryoStack root: HTTP 200 through the authenticated health probe.
- CryoLauncher / IceSheets: HTTP 200.
- ICESEE Run Center: HTTP 200.
- Frozen Legacies: HTTP 200.
- LIVIST: HTTP 200.
- LIVIST documentation: HTTP 200.
- Public root: HTTP 302 to authentication, as expected.
- Frozen Legacies protected asset: HTTP 302 to authentication when anonymous.
- Maintainer guide: HTTP 302 to authentication when anonymous.
- LIVIST Python API guide: HTTP 302 to authentication when anonymous.
- No startup traceback or critical error was observed in the gateway log.

## Remaining validation

The owner should perform an authenticated browser smoke test, including a hard
refresh, for Frozen Legacies Map/Manual/Automatic, product placeholders,
Control Center documentation delegation, and mobile layout. Real RIGGS and
TIFF data remain intentionally absent until approved inputs are promoted.

CEDAR cutover remains blocked until the administrator supplies the two NFS
mounts/ACLs and the `cryostack-app` preflight succeeds.
