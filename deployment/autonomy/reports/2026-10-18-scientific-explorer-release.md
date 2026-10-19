# CryoStack scientific explorer release — 18 October 2026

## Outcome

The tested Frozen Legacies update was deployed to the CryoStack GUI runtime.
The release advances the platform toward RadarFilm Studio and ArcGIS-class
discovery while preserving CryoStack's stronger scientific workflow controls.

## Delivered

- Map observations now open an anchored scientific quicklook. It includes a
  bounded radar/film image, flight, CBD, coordinates, ice thickness, bed SNR,
  lineage, scientific-use warning, and actions for the radar workspace and
  persistent details. On narrow screens it becomes a bottom sheet.
- Quicklooks now provide deterministic previous/next navigation within a
  flight, boundary states, and an observation position. Dataset, flight, and
  observation selection are shareable in the URL and restored after reload.
- Product previews cover source radar, radargram/echogram, digitized/QC output,
  and automatic-picker diagnostics. Preview cache keys follow the current
  source bytes and preview generation is bounded.
- Maintainers can start a scientific intake from the Control Center using TIFF,
  CSV, or ZIP input. Archive extraction is bounded and rejects traversal,
  symlinks, unsupported entries, duplicate paths, and suspicious expansion.
- Intake staging and receipts live on the explicitly configured intake volume.
  A missing/unwritable mount fails closed. New intake remains unpublished and
  cannot be made user-visible until a later publication workflow approves it.
- Catalog indexing has bounded batches, durable per-item failures, retry,
  cancellation checks, duplicate detection, and restart-safe manifests.
- A first resumable-intake backend supports maintainer-only create, status,
  fixed-size verified chunk upload, cancel, and finalize operations. Sessions
  and chunks remain on the configured intake volume; owner isolation,
  idempotent retry, checksums, capacity limits, and free-space reserve checks
  fail closed. The Control Center now supplies its browser client: file
  selection, chunk hashing, visible progress, safe cancellation, and recovery
  after reload by re-selecting the same files.
- Competitive acceptance gates now cover ArcGIS-class filtering, feature
  details, time/imagery behavior, accessibility, performance, sharing, STAC,
  and OGC interoperability, plus radar-specific lineage and synchronization.

## Verification

- Focused ingestion/preview security: 122 passed.
- Map quicklook frontend: 57 passed.
- Integrated quicklook/intake checks: 98 passed, 1 skipped.
- Frozen Legacies after the second increment: 664 passed, 4 skipped.
- Frozen Legacies after the GUI uploader: 666 passed, 4 skipped.
- Complete supported repository: 3,853 passed, 7 skipped.
- Pre-deployment backup: `20261018T152125Z`, 79 files, 309,727,135 bytes.
- Backup checksum verification and isolated restore drill: passed.
- Post-deployment health: all six services returned HTTP 200.
- Second pre-deployment backup: `20261018T154148Z`, verified with an isolated
  restore drill; second post-deployment health check also passed all services.
- GUI-uploader backup: `20261018T155549Z`, verified and restore-drilled; all six
  services returned HTTP 200 after deployment.
- Intake hardening adds volume-backed cross-process locks, durable crash states,
  atomic/fsynced assembly, startup reconciliation, two-phase expiry, protected
  cleanup, and persistent cleanup auditing. Fault, concurrency, recovery, and
  janitor tests passed; the complete Frozen Legacies suite reached 677 passed,
  4 skipped. Backup `20261018T163313Z` verified and restore-drilled; all six
  services were healthy after deployment.
- The unified ExplorerQueryV1 release adds one canonical filter store and an
  authorized same-snapshot endpoint for map features, catalog items, exact
  count, facets, and pagination. Dataset, flight, CBD range, review state, and
  text filters are shareable, Back/Forward-safe, and synchronized across map
  and catalog. Restricted source identifiers are excluded from results and
  facets. The integrated explorer suite passed 115 tests; the complete Frozen
  Legacies suite passed 694 with 4 skipped. Backup `20261018T211813Z` verified
  and restore-drilled; all six services were healthy after deployment.

## Safety and scientific status

- No production scientific data, CEDAR mount, or numerical LYRA algorithm was
  changed.
- Preview derivatives never replace canonical source objects.
- New intake and automatic results remain scientifically unvalidated and
  unpublished by default.
- Staging systemd processes were not restarted by the production GUI restart.

## Next competitive milestones

1. Bind popup content to live product/review APIs rather than catalog fields
   alone, and add previous/next observation navigation.
2. Add one composable URL query for dataset, flight, frame/CBD, extent, time,
   product availability, picker/calibration, and review state.
3. Add pre-ingest mapping/preview and resumable multipart browser uploads for
   very large TIFF and film batches.
4. Implement deterministic film-segment stitching with visible gaps/overlaps
   and a constituent manifest.
5. Publish validated STAC plus OGC API Features and test consumption in ArcGIS
   Pro and an independent STAC client.
6. Run keyboard, screen-reader, phone/tablet, cold-cache, and concurrent-user
   acceptance tests against representative CEDAR-scale data.
