# Frozen Legacies delivery roadmap — October to December 2026

This roadmap records the action items agreed on 15 October 2026 and turns them
into testable deliveries. Scientific source data must remain immutable;
derivatives, catalog metadata, and user results must record provenance.

## Product goal

Frozen Legacies will discover, preview, process, and serve three related classes
of material without forcing users to download large files before inspection:

1. source radar imagery (film scans and radargrams),
2. digitized radar observations and navigation data, and
3. automatic-picker output, including diagnostics and provenance.

The map, the observation panel, and the Manual and Automatic workspaces must
all resolve these materials through the same asset and product identifiers.

The repository-quality metadata, versioning, fixity, placeholder, and
STAC-interchange direction is specified in `scientific_data_platform.md`.

## Competitive outcome and release gates

The immediate domain benchmark is RadarFilm Studio’s documented public workflow:
map/track/CBD discovery, linked flight and film-segment views, multi-image
selection, stitched preview, per-image metadata and derivative download. See
<https://www.radarfilm.studio/docs/start> and its citation/license contract at
<https://www.radarfilm.studio/docs/citation>. Frozen Legacies should match
that discovery fluency while exceeding it in reproducible provenance, private
work, scientific review/publication and operational recovery.

ArcGIS Online, ArcGIS Enterprise, and the ArcGIS Maps SDK establish the broader
web-data-explorer benchmark: attribute/spatial/time filtering, configured
pop-ups, time animation, scalable imagery and tiles, audience-aware sharing,
and OGC/STAC interoperability. The comparison is against documented behavior,
not against every licensed ArcGIS product or deployment. Frozen Legacies must
meet those interaction conventions where they help researchers, without
becoming a generic GIS clone, and lead on film-aware radar inspection,
flight/CBD linkage, calibration, observation provenance, and scientific
publication controls. Official-source evidence and the expanded scorecard are
in `scientific_data_platform.md`.

The detailed, numbered pass/fail scorecard is in
`scientific_data_platform.md`. Milestones below are complete only with retained
test or drill evidence; placeholders and unmeasured “works on my machine”
demonstrations do not count.

## October: visible scientific context and previews

- Add RIGGS stations as a separately switchable scientific-context layer.
  Preserve the station identifier, observation method (seismic or radar),
  coordinates, thickness/value fields, citation, and source-file checksum.
- Use distinct but accessible symbols for RIGGS seismic and radar stations.
  RIGGS observations are reference observations, not Frozen Legacies picks.
- Make an anchored scientific quicklook the primary map interaction: radar or
  film preview, flight/CBD/location, derived quantities, review state, lineage,
  and authorized next actions in one keyboard-accessible popup. On narrow
  screens the same surface becomes a bottom sheet. Keep the right-hand panel
  for persistent filters, product inventory, and deeper details.
- Keep original downloads byte-for-byte unchanged. Preview derivatives are
  display products and must never replace the scientific source.
- Retain an “open full preview” action for detailed inspection.

Acceptance: a user can select an observation, inspect both its source radar
image and associated radargram without leaving the page, and identify the
origin and scientific status of every displayed layer and product.

## November: CEDAR storage and bulk ingestion

- Mount the `cos-lab-nuiaq` CEDAR allocation on the CryoStack VM with a
  service identity that has only the permissions required by the application.
- Place shared source datasets, user workspaces, uploaded files, catalog and
  quota databases, and generated products in explicitly configured durable
  roots. Keep rebuildable preview/cache data separate.
- Decide with PACE administrators whether the VM receives controlled write
  access. Do not expose a writable CEDAR mount directly to browser clients.
- Perform a dry-run inventory and checksum manifest before migration, then a
  copy/verify/cutover. Preserve the existing volume as rollback until backup
  and restore drills pass.
- Add resumable, idempotent TIFF/dataset indexing with progress, failure
  reporting, duplicate detection, and no source-file mutation.
- Load-test catalog browsing and preview generation against representative
  large TIFF batches. Enforce cache bounds, global quotas, per-user overrides,
  upload limits, and the local free-space reserve.
- Make routine intake GUI-first: an authorized curator can upload TIFFs,
  navigation CSVs, or bounded ZIP film archives into an operator-approved
  managed intake root. Every new intake starts unpublished and
  maintainers-only; the existing Data Sources page supplies connection tests,
  resumable progress, file-level failures, cancellation, retry, inspection,
  and an explicit publish action. CLI entry points remain recovery tooling.
- Replace the bounded single-request intake before bulk film import with the
  durable session/chunk/finalize protocol in `data_intake.md`. It must resume
  after browser, proxy and service interruption; reserve CEDAR bytes and inodes;
  verify per-chunk and whole-file SHA-256; reconcile rename/database failures;
  and clean abandoned sessions through an audited, lease-protected janitor.
  Mount-attestation failure, quota exhaustion or CEDAR unavailability must fail
  closed without spilling bytes onto the VM root filesystem.
- The first GUI resumable-upload slice is implemented: fixed verified chunks,
  progress, cancellation, same-file recovery after reload, server-computed
  whole-file SHA-256, and fail-closed durable staging. Do not raise its 4 GiB
  session limit until cross-process locking, startup reconciliation, expiry,
  and janitor evidence are complete.

Acceptance: a restart and redeployment preserve catalog entries, quotas,
uploads, connections, products, and user work; a restore drill reconstructs
them; ingestion can resume safely after interruption. A maintainer can stage a
TIFF plus navigation (directly or from a safe ZIP), index it, inspect invalid
or unavailable files, cancel and retry the job, and only then deliberately
make the source visible to users. No uploaded item is published by default and
no flight, CBD, coordinate, or observation is fabricated.

Bulk-upload acceptance additionally requires a 1 TiB/10,000-file fault-injected
test: resume transfers only missing chunks after restart; duplicate chunks and
finalize calls are idempotent; concurrent reservations cannot exceed quota;
cross-user access is denied; partial data never reaches the index or map; and a
backup/restore drill preserves upload state without escalating publication.

## December: integrated dataset delivery and release validation

- Publish coherent dataset manifests linking radar images, digitized records,
  navigation, RIGGS context, and automatic-picker outputs.
- Provide filters and clear legends for source dataset, flight, product type,
  review state, picker/version, and RIGGS observation method.
- Expose picker outputs with immutable provenance and retain the scientific
  validation and publication restrictions already enforced for LYRA/URSA.
- Complete desktop/mobile browser validation, authorization/isolation tests,
  performance testing, operational runbooks, backup/restore evidence, and a
  deployment rollback rehearsal.

Acceptance: the three target data classes are searchable, previewable,
downloadable where authorized, provenance-linked, restart-safe, and usable on
desktop and mobile without leaking private results.

## Sequenced parity-to-advantage plan

### Gate 1 — public discovery parity

- Add a flight segment/timeline view keyed by immutable asset/version IDs and
  CBD/frame ranges; expose scope and frequency where known.
- Make map, segment selection, preview focus and URL state bidirectional.
  Enumerate one-to-many matches instead of guessing.
- Add dataset, flight, scope/frequency, product availability, review state and
  spatial filters; published-release browsing must not require account state.

Exit evidence: scorecard **P-D1**, **P-D2**, and stable deep-link browser tests
pass against at least one A-scope and one Z-scope flight with known gaps.

### Gate 2 — trustworthy stitched inspection

- Build ordered, bounded multi-segment previews with explicit gap, overlap and
  ordering markers; preserve original aspect/scale metadata.
- Emit a constituent/provenance manifest and deterministic output digest for
  every stitch. Never treat a stitch as the canonical source.
- Keep the single-product right-panel previews and full-preview action as the
  lightweight path.

Exit evidence: **P-S1**, **P-S2**, **P-M1**, and **P-P1** pass, including the
100-segment/concurrency benchmark and byte-identical rerun.

### Gate 3 — repository-grade release

- Ship validated STAC Collection/Item/Asset representations plus version,
  fixity, supersession, withdrawal/tombstone, citation and rights pages.
- Require license URI, rights holder, requested citation and authoritative
  source before publication; use repository-issued PIDs only.
- Offer original, preview, product and bulk-manifest downloads with declared
  media types and hashes, limited by release visibility and authorization.

Exit evidence: **P-C1**, **P-F1**, **A-R1**, and **A-R2** pass; an independent
validator accepts the STAC documents and a clean-room consumer verifies every
download hash.

### Gate 4 — inclusive and resilient scientific service

- Complete keyboard/screen-reader and desktop/phone/tablet acceptance across
  discovery, selection, stitching, metadata and download—not only structural
  markup checks.
- Run the deny-matrix with two ordinary users, reviewer, maintainer and
  anonymous client across every asset/product/preview/review/public route.
- Rehearse worker interruption, storage loss, backup/restore and rollback on
  representative durable storage; retain timings and checksum evidence.

Exit evidence: **P-X1**, **P-X2**, **A-A1**, **A-O1**, and **A-O2** all pass.
Only then describe the product as exceeding the benchmark rather than merely
having a broader feature list.

### Gate 5 — ArcGIS-class explorer behavior, radar-specific advantage

- Make filters composable across attributes, map extent/geometry, acquisition
  time, dataset, flight, CBD/frame range, product availability, review state,
  picker/version and calibration status. Show active filters, result counts,
  clear-all, and shareable URL state.
- Replace generic hover-only detail with an accessible feature details surface
  that presents selected metadata, related products, preview media, provenance,
  citation, and domain actions. Map, flight timeline, film frame, observation,
  and details selection must remain synchronized.
- Add acquisition-time and processing/release-history controls. Never imply
  that film CBD order or picker run order is acquisition time; unknown dates
  remain explicitly unknown.
- Serve large imagery through bounded windows/tiles and cached derivatives,
  while preserving byte-identical originals. Establish an overview-to-source
  inspection path that keeps scale, frame/CBD, gaps, and source identity visible.
- Validate public STAC Items in ArcGIS Pro and at least one independent STAC
  client. Add standards-based vector/raster delivery only where it preserves
  visibility and scientific-status rules; never expose private work merely to
  satisfy an interoperability checkbox.
- Treat published maps, layers, assets, and downloads as one sharing graph:
  automated release checks must fail when a public page references a private,
  missing, withdrawn, or unauthorized dependency.

Exit evidence: ArcGIS-comparison gates **E-F1**, **E-P1**, **E-T1**, **E-I1**,
**E-S1**, **E-X1**, and radar-advantage gates **R-L1**, **R-I1**, and **R-V1**
in `scientific_data_platform.md` pass on the declared benchmark corpus. Generic
feature parity alone does not satisfy this gate.

## Release evidence register

For each gate, store the release commit, dataset manifest and hashes, test
command/results, browser/viewport matrix, benchmark corpus/hardware/load, audit
deny-matrix, accessibility report, and restore/rollback record. Link those
artifacts from the release manifest. Do not place credentials, private paths,
account identifiers, unpublished data or reviewer identities in public
evidence.

## Decision needed: PDF

The meeting note “downgrade preview to PDF” is ambiguous. The recommended
design is to keep interactive in-panel previews as bounded PNG/JPEG derivatives
because radar imagery is raster data and browsers render these efficiently.
If the intended action was **download preview as PDF**, add PDF as an optional
report/export containing the preview, metadata, citation, scale, provenance,
and a prominent “preview only” label. A PDF must not replace the TIFF or become
the canonical scientific product.

## External dependency

CEDAR cutover remains contingent on confirmation that the CryoStack VM can
mount `/projects/cos-lab-nuiaq` with appropriate write access. VPN is relevant
to administrator or PACE access; the production service itself needs stable
server-side network and mount access independent of an individual user's VPN
session.
