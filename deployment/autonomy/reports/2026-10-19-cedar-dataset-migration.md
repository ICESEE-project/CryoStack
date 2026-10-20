# CEDAR dataset migration — 19 October 2026

## Outcome

Frozen Legacies' verified scientific imagery and context releases were copied
to the CEDAR dataset mount without deleting or modifying their local/scratch
sources. Production now reads navigation, RIGGS, A-scope and Z-scope data from
explicit immutable CEDAR release paths. Transactional databases remain on the
VM's durable XFS storage.

## Promoted releases

| Dataset | CEDAR release | Verification |
|---|---|---|
| A-scope film scans | `frozen-legacies/spri/ascope/releases/ascope-a0c9c6a4fc178767` | 432/432 manifest files; 46,106,662,537 bytes; Dropbox hashes match |
| Z-scope radargrams | `frozen-legacies/spri/zscope/releases/zscope-5da8e00c1e21e8d3` | 2,114/2,114 manifest files; 128,847,392,353 bytes; Dropbox hashes match |
| SPRI navigation | `frozen-legacies/spri/navigation/releases/nav-177c92df4cc0f690` | recursive source/destination comparison passed |
| RIGGS context | `frozen-legacies/riggs/releases/riggs-e83879057daf36a0` | recursive source/destination comparison passed |

Ten navigation CSVs stored beside the Z-scope intake are documented additions
outside the original 2,114-file Dropbox manifest. They remain duplicated in the
independently versioned navigation release; no synthetic scientific data was
created.

## Catalog cutover

The existing source IDs were retained so catalog IDs and user references remain
stable. Their provider, names, dataset IDs, roots and visibility were updated in
one local SQLite transaction, then both sources were fully reindexed from
CEDAR:

- A-scope: 415 indexed radar assets; zero missing, invalid or unavailable;
- Z-scope: 1,003 indexed radar assets; zero missing, invalid or unavailable.

The Z-scope catalog reports 124 duplicate filenames. These are distinct storage
keys already handled by the catalog; no files were discarded or conflated.

Pre-migration catalog backup:

`/home/bkyanjo3/cryostack-data/backups/frozen-legacies-catalog-before-cedar-20261020T003154Z.db`

## SMB-specific behavior

- Atomic rename and fsync passed.
- SQLite WAL remains unsupported and stays local.
- Hidden rsync temporary files and preserved directory timestamps were rejected.
  The successful copy used in-place writes inside unpublished `.incoming-*`
  release directories, followed by full destination hash verification and an
  atomic directory rename.
- SMB symbolic-link creation returned `Operation not supported`; releases use
  plain `CURRENT` markers and runtime configuration uses explicit paths.

## Validation and deployment

- Focused storage/catalog suite: 92 passed, 1 skipped.
- A-scope and Z-scope CEDAR reindex: completed.
- Production GUI restarted with primary group `cryostack-app` (`gid=977`).
- Frozen Legacies health endpoint: HTTP 200.
- CEDAR usage after migration: approximately 164 GiB of 10 TiB (2%).
- Staging remained online; no source intake or local rollback copy was deleted.

## Rollback

1. Stop only the production GUI.
2. Restore the catalog backup above, or transactionally restore the two source
   configurations to their scratch roots.
3. Restore the previous navigation and RIGGS paths in `deployment/services.sh`.
4. Restart the GUI and run `deployment/health_check.py`.
5. Keep the CEDAR releases for investigation; do not delete them during rollback.
