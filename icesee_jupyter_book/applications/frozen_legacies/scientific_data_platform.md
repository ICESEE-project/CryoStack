# Frozen Legacies scientific data platform architecture

This design turns Frozen Legacies from a file viewer into a reproducible
scientific data service. It does not treat placeholder records, previews, or
automatic output as observations.

## Repository-quality principles

The platform should combine interactive radar inspection with the properties
expected from a durable research repository:

- stable public identifiers and versioned dataset releases;
- original files preserved byte-for-byte with recurring fixity checks;
- machine-readable discovery metadata and spatial search;
- explicit origin, custody, software, picker, and calibration provenance;
- review, embargo, visibility, citation, and withdrawal/tombstone states;
- independently restorable metadata, files, permissions, and audit history;
- bounded previews that never replace the canonical scientific object.

Stanford Digital Repository documents persistent identifiers, version history,
checksums, provenance, authenticated depositors, review workflows, and
geo-diverse preservation as desirable repository behavior. Frozen Legacies
should add domain-specific map, radar-frame, navigation, calibration, echo,
and picker workflows while retaining those fundamentals.

## Interoperable catalog direction

Use the SpatioTemporal Asset Catalog (STAC) model as the public interchange
shape, rather than making every downstream user learn a CryoStack-only format.
A flight/CBD radar asset maps naturally to a STAC Item (GeoJSON geometry plus
metadata and links), and its files map to named STAC Assets:

| Asset role | Canonical object | Derived display object |
| --- | --- | --- |
| `source-radar` | original TIFF scan | bounded PNG/JPEG preview |
| `navigation` | source CSV | simplified flight geometry |
| `radargram` / `echogram` | approved processed image/data | bounded preview |
| `digitized-radar` | approved tabular/array product | summary/plot |
| `manual-picks` | reviewed ASTRA CSV | QC overlay |
| `automatic-picks` | LYRA/URSA result with version | unvalidated diagnostic |
| `calibration` | human reference-line picks | calibration summary |

STAC is an index: it references scientific files but does not replace them.
Adopt its Collection/Item/Asset/link vocabulary incrementally and add a
documented Frozen Legacies extension for flight, CBD range, film scope,
scientific review state, picker version, and calibration status.

References:

- STAC overview and specification: <https://stacspec.org/en/>
- STAC Item Search API: <https://api.stacspec.org/v1.0.0/item-search/>
- Stanford repository characteristics:
  <https://sdr.library.stanford.edu/desirable-characteristics-data-repositories>
- NASA Data Product Development Guide:
  <https://www.earthdata.nasa.gov/s3fs-public/2024-07/ESDS-RFC-041%20DPDG%20V2.0.pdf>

## Placeholder contract

Before source files arrive, the UI may show an expected product slot only when
all of the following are true:

1. `availability` is `awaiting-source` or `navigation-only`;
2. no fabricated URL, dimensions, byte size, checksum, measurement, or
   thumbnail is supplied;
3. the card explicitly says it is an interface placeholder and not scientific
   data;
4. processing and publication actions remain disabled;
5. a real object replaces the slot only after checksum validation and catalog
   indexing succeeds.

The four initial slots are source radar TIFF, radargram/echogram, digitized
radar data, and automatic-picker output. They let the interaction design and
metadata contract stabilize before bulk transfer without creating false
observations.

## Release and preservation model

Each dataset release receives an immutable release ID and manifest containing:

- collection and item identifiers;
- source filename, size, media type, SHA-256, and storage key;
- spatial geometry and bounding box derived from approved navigation;
- flight, CBD range, scope type, and acquisition/source description;
- provider, rights/use statement, citation, and authoritative source record;
- relationships among source, derived, calibration, and result assets;
- generator name/version/configuration and parent checksums for derivatives;
- scientific status, reviewer decision, and publication eligibility;
- creation, supersession, and withdrawal timestamps.

Publishing a changed file creates a new version. Older public versions remain
addressable, while a withdrawn version retains a metadata tombstone. Mutable
workspace jobs are not releases.

## Delivery sequence

1. Finish strict intake manifests, resumable indexing, and placeholder states.
2. Install representative A-scope and Z-scope TIFFs in isolated staging.
3. Validate embedded previews, range reads, large-image memory bounds, and
   source-download parity.
4. Expose a read-only STAC-compatible Collection/Item representation alongside
   the existing authenticated APIs.
5. Add dataset version pages, citations, fixity history, and tombstones.
6. Complete CEDAR copy/verify/cutover and backup/restore drills.
7. Add DOI/PID integration only after ownership, review, and preservation
   policy are approved; do not manufacture persistent identifiers locally.

## Competitive benchmark (17 October 2026)

RadarFilm Studio is the closest public interaction benchmark, not a contract
to copy. Its tutorial documents public map discovery, track/CBD hover, a flight
page linking a map and film-segment plot, box/lasso selection, immediate
multi-image stitched previews, per-image pan/zoom, metadata, and JPEG download.
It also clearly explains A-, Z-, and ESM-scope records and warns that its site
is not optimized for mobile. Its citation page publishes contributor,
copyright, CC BY 3.0, requested-citation, DOI, and map-source information.

Sources:

- RadarFilm Studio tutorial: <https://www.radarfilm.studio/docs/start>
- RadarFilm Studio licensing and citation: <https://www.radarfilm.studio/docs/citation>
- Teisberg and Schroeder, *Digital Tools for Analog Data*:
  <https://doi.org/10.1109/IGARSS52108.2023.10281876>

The comparison below is based on those public descriptions and the Frozen
Legacies application contracts/tests in this repository. “Implemented” means
there is code and automated coverage; it does not mean production data are
installed or that a browser acceptance run has passed for every target.

| Capability | RadarFilm Studio public baseline | Frozen Legacies evidence today | Target advantage / gap |
| --- | --- | --- | --- |
| Discovery and map | Public Antarctic/Greenland tracks, CBD hover, alternate scientific basemaps | Dataset/flight filters, polar map, observations, catalog search, optional RIGGS context | Add public release discovery, spatial/bbox and product/review filters, stable deep links |
| Cross-linked selection | Map, film-segment plot, selected map line and image list are linked; one-to-many ambiguity is explained | Map observation opens related radar by shared identifiers; Manual/Automatic and panel share an asset | Add a flight timeline/segment view and bidirectional, deterministic map ↔ segment ↔ preview focus |
| Stitched preview | Box/lasso multiple film images and receive a stitched strip | Bounded previews exist per server product; radar window/overview exists | Add ordered multi-segment stitching with gaps/overlaps disclosed and a manifest of constituents |
| Metadata/history | Per-image metadata; permitted users may correct it | Catalog versions, source version/checksum, immutable review snapshots, supersession and withdrawal | Add user-visible dataset/item version pages, change reasons, fixity history and tombstones |
| Provenance/citation/license | Dedicated contributor, CC BY 3.0, citation and DOI page | Product/picker/source hashes and review provenance exist; release citation/rights schema is planned | Require rights, license URI, citation and source record on every publishable release and export |
| Formats/download/API | JPEG derivative download; originals referred to repository/contact | Original/product downloads, ZIP, bounded preview, CSV/PNG/TIFF inputs, authenticated APIs | Publish documented STAC/GeoJSON/CSV contracts and checksummed bulk manifests without exposing private IDs |
| Accessibility/mobile | Publicly states mobile is not optimized | Responsive panel and structural accessibility checks exist | Meet WCAG 2.2 AA for the complete discovery/preview workflow and pass phone/tablet browser tests |
| Performance | Stitched preview may take seconds; page exposes generation time | Paginated indexed catalog, bounded previews/cache/quota/free-space controls and benchmark tests | Publish service-level budgets measured on representative CEDAR-scale data and concurrent users |
| Authorization/private work | Browsing is public; metadata editing requires an account/permission | Owner-isolated workspaces/results, authenticated assets, role-controlled review, audit records | Retain strict isolation while providing intentionally public, immutable releases |
| Review/publication | Metadata correction by permitted users is documented | Submit/return/reject/approve, no self-review, immutable snapshots, supersession/withdrawal | Add release-level scientific sign-off policy, visible decision history, licensing gate and optional dual review |
| Operational resilience | Not specified by public user documentation | Resumable indexing, working cache, integrity checks, backup/verify/restore and rollback design | Demonstrate scheduled restore, failover and source-unavailable behavior with retained public metadata |

### Competitive acceptance scorecard

The release is “RadarFilm-parity for discovery” only when all **P** gates pass;
it is “Frozen Legacies advantage” only when all **A** gates pass as well. A
demo, screenshot, or placeholder cannot satisfy a gate.

| ID | Verifiable acceptance criterion |
| --- | --- |
| P-D1 | From the collection map, a keyboard or pointer user can filter by dataset, flight, scope/frequency and product availability, select a track/CBD range, and reach the matching segments with a stable shareable URL. |
| P-D2 | Selecting map geometry highlights every corresponding segment; selecting one or many segments highlights the exact mapped extent. One-to-many matches are enumerated rather than silently choosing one. |
| P-S1 | Box/lasso or equivalent range selection of at least 100 ordered segments produces a bounded stitched preview without downloading originals; missing, overlap and out-of-order boundaries are visibly marked. |
| P-S2 | Every stitch has a machine-readable constituent manifest with ordered asset/version IDs, source SHA-256 values, transforms, generator version and output SHA-256; rerunning identical inputs is byte-identical. |
| P-M1 | Each public item shows scope, frequency, flight, CBD/frame range, acquisition/source notes, spatial coverage, file format/size, release/version and last fixity result; unknown values say “unknown.” |
| P-C1 | Every public page and downloaded manifest exposes license URI, rights holder, requested citation, contributors, authoritative-source link and release PID/DOI when assigned. Publication fails closed when required rights are absent. |
| P-F1 | Authorized users can obtain originals unchanged, display previews, per-item products and a bulk manifest; advertised media types and hashes match bytes. Public STAC Items validate against the declared STAC version. |
| P-X1 | The map → segments → stitched preview → item metadata → download path has no critical/serious automated accessibility violations, is keyboard complete with visible focus, and meets WCAG 2.2 AA contrast and name/role/value checks. |
| P-X2 | The same path passes current supported desktop browsers at 1280×720 and phone viewport 390×844 with no horizontal page overflow, obscured controls or pointer-only action. |
| P-P1 | On a declared representative corpus, p95 map/search responses are ≤1 s, p95 cached preview responses ≤1 s, and p95 uncached 100-segment stitches ≤10 s under 20 concurrent users; errors and cache-hit rate are recorded. |
| A-A1 | Anonymous users receive only published releases; user A cannot list, infer, fetch or mutate user B’s assets, previews, jobs, submissions or identifiers. A deny-matrix integration suite covers every route. |
| A-R1 | Publication requires an intact immutable snapshot, authorized non-self reviewer, recorded decision, complete provenance and rights fields. Automatic results remain ineligible until an explicit validated workflow exists. |
| A-R2 | Superseded and withdrawn releases retain addressable metadata/history; withdrawals remove scientific payload access as policy requires and show reason/time without exposing personal account identifiers. |
| A-O1 | A killed index/stitch worker resumes or safely restarts without source mutation or duplicate release records; unavailable storage returns a bounded error while existing release metadata remains readable. |
| A-O2 | A backup restore drill reconstructs catalogs, snapshots, workspaces, permissions and audit linkage within the declared RTO, with zero checksum mismatches; the drill date and evidence are retained outside the restored system. |

These thresholds are initial product SLOs, not retrospective claims. Before a
release, record the corpus size, hardware, browser versions, concurrency,
measurement method, failures and raw result artifact so the numbers can be
reproduced and revised deliberately.

## ArcGIS web-data-explorer benchmark (17 October 2026)

ArcGIS is the broad platform benchmark; RadarFilm Studio remains the closest
domain benchmark. This comparison uses current official Esri documentation and
does not assume that every ArcGIS capability is enabled in every deployment.
It also distinguishes ArcGIS Online/Enterprise web delivery from ArcGIS Pro
desktop consumption of STAC.

Official ArcGIS baseline:

- `FeatureFilter` supports attribute, time, geometry, and distance filters;
  feature effects can retain context by styling included and excluded features:
  <https://developers.arcgis.com/javascript/latest/api-reference/esri-views-layers-support-FeatureFilter.html>
  and
  <https://developers.arcgis.com/javascript/latest/references/core/layers/support/FeatureEffect/>.
- Pop-up templates can format selected fields and dates/numbers, use Arcade
  expressions, include media, charts, tables, attachments and related records,
  and expose contextual actions:
  <https://doc.arcgis.com/en/arcgis-online/create-maps/configure-pop-ups.htm>
  and
  <https://developers.arcgis.com/javascript/latest/references/core/PopupTemplate/>.
- Time-aware maps can filter or animate time-enabled feature and imagery layers
  with configured extents, intervals, time zones and play/pause/step controls:
  <https://doc.arcgis.com/en/arcgis-online/create-maps/configure-time-mv.htm>.
- `ImageryLayer` supports server-rendered imagery, raster functions, raw LERC
  pixels and multidimensional subsets; `ImageryTileLayer` provides scalable
  tiled access and can reference COG and CoverageJSON sources:
  <https://developers.arcgis.com/javascript/latest/references/core/layers/ImageryLayer/>
  and
  <https://developers.arcgis.com/javascript/latest/references/core/layers/ImageryTileLayer/>.
- ArcGIS Online recommends indexes and optimized geometry for hosted feature
  layers; hosted tiles provide fast large-dataset visualization, are generated
  on demand and then cached:
  <https://doc.arcgis.com/en/arcgis-online/manage-data/manage-hosted-feature-layers.htm>
  and
  <https://doc.arcgis.com/en/arcgis-online/manage-data/publish-tiles-from-features.htm>.
- ArcGIS Enterprise can publish WMS, WMTS, WFS/OGC API Features, WCS and WPS,
  with authorization applying across REST and OGC interfaces:
  <https://enterprise.arcgis.com/en/server/11.5/publish-services/windows/ogc-support-in-arcgis-server.htm>.
- ArcGIS Pro can connect to a STAC API, filter by collection, date/time, extent,
  ID and attributes, inspect item assets, and add results to a map, scene, or
  mosaic dataset:
  <https://pro.arcgis.com/en/pro-app/3.3/help/data/imagery/explore-stac.htm>
  and
  <https://doc.esri.com/en/arcgis-pro/latest/help/data/imagery/introduction-to-stac.html>.
- ArcGIS items can be private, group-, organization-, or publicly shared;
  public maps require compatible sharing of their dependent layers. Esri
  recommends a private editable layer plus a wider read-only hosted view where
  appropriate:
  <https://doc.arcgis.com/en/arcgis-online/reference/best-practices-share.htm>
  and
  <https://doc.arcgis.com/en/arcgis-online/reference/share-maps.htm>.
- The Maps SDK documents keyboard navigation, alternative text, contrast,
  reduced motion, and semantic structure, while explicitly requiring app
  authors to complete additional accessibility work:
  <https://developers.arcgis.com/javascript/latest/accessibility/>.

### ArcGIS comparison and Frozen Legacies advantage

| Capability | ArcGIS documented benchmark | Frozen Legacies position | Required outcome |
| --- | --- | --- | --- |
| Compound filtering | Attribute, time, geometry and distance filters; effects can dim rather than remove context | Dataset/flight/catalog/status filters and bbox APIs exist, but the interaction is split and filter state is incomplete | One composable, URL-addressable query state spanning dataset, flight, CBD/frame, extent, time, product, picker/calibration and review status |
| Feature details | Configurable pop-ups with formatted fields, expressions, rich media, related records and actions | The map now opens an anchored scientific quicklook (mobile bottom sheet) with radar media, location, flight/CBD, derived quantities, lineage and workspace actions; product cards remain the persistent inventory | Complete keyboard/focus testing and bind the quicklook to review state, relationships, citation, product availability and stable unknown-value semantics across map/catalog/published records |
| Time exploration | Time-aware feature/imagery layers and slider animation | Flight/CBD ordering and review/run timestamps exist; acquisition time is not yet a first-class explorer dimension | Separate acquisition time from processing/publication history; animate only scientifically meaningful time and expose unknown dates honestly |
| Large raster exploration | Server imagery rendering, raster functions, multidimensional subsets, tiled imagery and COG access | Bounded TIFF windows, overview, cached product previews and planned stitching suit long film strips | Preserve the radar-specific strip viewer while adding tile/window SLOs, deterministic overview levels and visible source pixel/CBD/frame context |
| Interoperability | GeoServices plus OGC map/feature/coverage interfaces; ArcGIS Pro consumes searchable STAC APIs | GeoJSON and downloads exist; STAC is planned | Valid STAC API/Items first; prove ArcGIS Pro and independent-client consumption. Add OGC API Features for published vector observations and flight tracks; evaluate WMS/WMTS/WCS only against real consumers |
| Sharing | Private/group/organization/public audiences; dependent layers must share compatibly; read-only views protect editable sources | Owner workspaces and review snapshots are stronger domain controls; public release discovery is incomplete | Atomic release visibility across page, layers and assets; immutable public views; automated dependency and deny-matrix checks |
| Accessibility | SDK primitives support keyboard, alt text, contrast, reduced motion and semantics, but applications retain responsibility | Structural accessibility and responsive layout exist | End-to-end keyboard/screen-reader/reduced-motion/contrast testing for filter → map → details → radar preview → download |
| Performance | Indexes, geometry optimization and cached tiles are documented strategies for large layers | Paginated catalog, ranged reads, bounded rendering and caches exist | Publish reproducible SLOs for searches, map interaction, previews, large strips and concurrent users, including cold-cache behavior |
| Scientific governance | Generic roles, sharing and editing controls | Immutable review snapshots, non-self review, automatic-result publication block, supersession and withdrawal are domain advantages | Retain fail-closed scientific gates across every interoperable representation and download |
| Radar-film science | No documented ArcGIS web workflow binds film frames, CBD labels, flight navigation, calibration and radar picks | ASTRA/LYRA/URSA, frame diagnostics, CBD navigation and georeferencing are the core differentiator | Make the entire source film → flight/frame → calibrated observation → reviewed release lineage visible and machine-verifiable |

### Measurable ArcGIS-parity and radar-advantage gates

These gates extend, rather than replace, the RadarFilm **P** and repository
advantage **A** gates above.

| ID | Verifiable acceptance criterion |
| --- | --- |
| E-F1 | A user can combine at least five filter dimensions, including one spatial and one scientific-status dimension; result count, map, segment list and URL update consistently within 250 ms after each already-loaded facet change and within the **P-P1** server budget otherwise. Reload and shared URL reproduce the exact query. |
| E-P1 | Every published flight, segment and observation opens the same accessible details schema: identifier, dataset/version, flight, CBD/frame range, acquisition time or `unknown`, geometry provenance, scientific status, products, citation and actions. Automated contract tests reject missing required fields and fabricated defaults. |
| E-T1 | Acquisition-time filtering and processing/release-history filtering are separate controls. A fixture with known, partial and unknown dates returns exact expected sets; unknown acquisition dates never enter an animated interval, and CBD order is never presented as time. |
| E-I1 | A 100,000-pixel-wide reference TIFF opens an overview without transferring the original; pan/zoom requests remain bounded, show source column/CBD/frame context, and meet p95 cached ≤1 s and uncached ≤3 s under 20 concurrent viewers on declared hardware. Peak worker memory stays below the documented limit. |
| E-S1 | A release visibility transaction checks the web page, STAC Item/Assets, GeoJSON/OGC collections, previews and downloads as one dependency graph. Tests prove that private, returned, withdrawn and missing dependencies cannot be reached anonymously, while every public dependency returns successfully. |
| E-X1 | Filter, map selection, details, time/history, radar pan/zoom and download are keyboard complete and screen-reader understandable; automated checks find zero critical/serious issues, manual testing covers reduced motion and 200% zoom, and focus never becomes trapped or lost. |
| E-O1 | Published observations and flight tracks pass an OGC API Features conformance check; STAC Collections/Items pass the declared validator and are opened successfully in current ArcGIS Pro plus one independent STAC client. Identifiers, geometry, timestamps, media types and hashes agree across representations. |
| R-L1 | From any published observation, one action reveals the exact immutable source asset/version, flight, film segment, A-scope frame/window, CBD assignment and navigation record, calibration record, picker/version/configuration, review decision and derived products. Every edge is backed by IDs and hashes; no relationship is inferred from display names alone. |
| R-I1 | A curator can compare source film, bounded radar window, frame diagnostic, navigation position, manual picks and automatic suggestions in one synchronized inspection state. Selecting any representation highlights the same frame/CBD and enumerates ambiguity or missing links instead of choosing silently. |
| R-V1 | Publication fails when source fixity, flight/CBD identity, required calibration, navigation provenance, product hashes, rights, or independent review is absent. Automatic picks remain visibly unvalidated and unpublished until a versioned validation protocol and threshold pass; OGC/STAC endpoints cannot bypass this rule. |

ArcGIS parity is achieved only when all **E** gates pass. Competitive advantage
requires the RadarFilm **P** gates, repository **A** gates, and radar-specific
**R** gates as well. This prevents a polished generic map from being mistaken
for a trustworthy radar-film scientific service.

## E-F1 implementation contract: one explorer query

This section is the implementation design for **E-F1**. It records the
October 18, 2026 audit of the current application; it is not a claim that the
gate already passes.

### Current-state audit

| Surface | Implemented now | E-F1 gap |
| --- | --- | --- |
| Workspace URL | `radar.js` reads and writes the fragment fields `mode`, `asset`, `ds`, `flight`, `view`, `cov`, and `seg`; reload and browser history restore those validated values. | Catalog filters, result page, scientific status, product/picker/calibration facets, and spatial-filter intent are absent. The camera is stored, but moving it does not mean “filter to this extent.” |
| Catalog browser | `catalog.js` sends server-side `dataset`, `flight`, `state`, `cbd`, and `q` filters with pagination. It debounces text input and shows a server result count. | Its state is private to the JavaScript object: it does not update the URL, the map segment query, or the observation layers. It supports an exact CBD, not a range. |
| Catalog API | `GET /api/radar/catalog` validates dataset, flight, asset/source IDs, catalog status and per-user processing/review state. SQL is parameterized, page size is bounded, and restricted sources are maintainer-only. | There is no common query object or facet response. Scope/frequency, product availability, picker/version, calibration, acquisition/history range and geometry are not composable here. |
| Map APIs | Segment and observation endpoints accept bounded `bbox` queries; segment queries also accept dataset and flight. Published and private/user observations are deliberately separate authorization surfaces. | Each layer builds its own request, so map, count, list, and facets can represent different sets. Bbox does not cross the antimeridian and has no explicit CRS/version field. |
| Selection | A catalog segment and radar asset can be restored by opaque validated IDs, and the scientific quicklook is linked to map selection. | Selection is mixed with filtering and does not have a shared flight/segment/observation details identity contract. |

The existing code is therefore a sound compatibility base, not an E-F1
implementation. E-F1 requires one normalized query to drive the count, map,
segment list, facets, and canonical URL.

### Canonical query model

Use an immutable `ExplorerQueryV1` value in the browser and server. Absence
means “all values visible to this caller”; an empty result is never silently
broadened. Multi-valued fields use repeated query keys, sorted and deduplicated
when serialized.

| Group | Canonical fields | Rules |
| --- | --- | --- |
| Version/audience | `qv=1`, `audience=workspace|published` | `workspace` requires authentication. `published` is the only anonymous value. A URL never upgrades the caller's audience. |
| Identity | `dataset`, `flight`, `source` | Repeated values are OR within the field and AND across fields. Values retain the existing strict identifier validation. Restricted source IDs are ignored as matches unless authorized, never disclosed as errors or facets. |
| Radar science | `cbd_min`, `cbd_max`, `frame_min`, `frame_max`, `scope`, `frequency` | Inclusive ranges; min must be no greater than max. Unknown metadata matches only an explicit repeated `metadata=unknown`, never a fabricated value. CBD/frame order is not time. |
| Products | `product`, `picker`, `picker_version`, `calibration=present|missing|not_required` | `product` means an authorized, non-withdrawn product is available. Picker fields describe recorded provenance, not filename inference. |
| Scientific state | `review=unprocessed|in_progress|needs_review|returned|published|withdrawn`, `validation=unvalidated|validated` | Workspace state is evaluated for the authenticated owner. Published audience accepts only public release states. Automatic output remains `unvalidated` unless the scientific validation gate has passed. |
| Time | `acquired_from`, `acquired_to`, `history_from`, `history_to` | RFC 3339 UTC bounds. Acquisition and processing/release history remain separate per **E-T1**. Unknown acquisition time is excluded whenever an acquisition bound is active. |
| Spatial | `bbox=minx,miny,maxx,maxy`, `crs=EPSG:4326`, `spatial=intersects|within` | V1 accepts WGS84 only and rejects non-finite/out-of-range coordinates. Antimeridian-crossing boxes use `minx > maxx` explicitly; they are not reordered. Camera state alone is not a filter. |
| Text/order/page | `q`, `sort=flight_cbd|acquired|released|relevance`, `cursor` | Text is length-bounded and escaped by the database layer. Cursor is opaque, signed/versioned and bound to the normalized query; it contains no path or credential. Offset/page remain compatibility-only. |

The browser URL fragment is the shareable UI representation because Frozen
Legacies already uses fragments for workspace navigation:

```text
#qv=1&audience=workspace&mode=map&dataset=spri&flight=127&cbd_min=471&cbd_max=483&product=radargram&review=needs_review&bbox=-171.2,-79.1,-166.0,-77.0&crs=EPSG%3A4326&spatial=intersects&sel=cat-…&view=5.25%2F-240000%2F-1320000
```

`mode`, `sel`, `view`, popup tab, and panel openness are presentation state and
must not affect result membership. The query serializer emits fields in the
table order, sorts repeated values, omits defaults, rounds only camera values,
and never rounds scientific bounds. Updating text input uses `replaceState`;
committed facet/extent/selection changes use `pushState`. Back/forward applies
one complete state without intermediate requests. A “Copy link” action uses
the canonical URL, not the browser's incidental parameter order.

### API contract

Add `GET /frozen-legacies/api/radar/explorer` for the authenticated workspace
and `GET /frozen-legacies/api/radar/published/explorer` for public releases.
Both accept the canonical fields above and return one permission-trimmed
snapshot:

```json
{
  "query_version": 1,
  "query": {},
  "snapshot": "opaque-revision",
  "total": 0,
  "items": [],
  "features": {"type": "FeatureCollection", "features": []},
  "facets": {},
  "page": {"next_cursor": null},
  "limits": {"items": 50, "features": 5000, "features_truncated": false}
}
```

`query` is the normalized effective query and is safe to place back in the
URL. `items`, `features`, `facets`, and `total` must be computed from the same
database snapshot and authorization predicate. Facet counts apply all active
filters except their own field so users can see alternatives. Every feature
contains an immutable public/catalog identifier that joins to exactly one
item; no filesystem path, storage key, owner identifier, email, token,
unsigned preview URL, or private product metadata is returned. When feature
limits truncate geometry, `total` remains exact and the response says so.

Invalid syntax is `400`; unsupported `qv` or CRS is `422`; an unauthenticated
workspace query is `401`. A specific inaccessible selection is represented as
`selection: {"available": false}` only after the result query succeeds, so
private existence cannot be probed through status-code differences. Responses
use `Cache-Control: private, no-store` for workspace queries. Published
responses may use revision-keyed ETags and public caching only after the
release dependency gate **E-S1** succeeds.

The implementation should compile `ExplorerQueryV1` once into a parameterized
SQL predicate reused by count, items, geometry, and facets. Expensive geometry
and relationship work must be bounded after indexed candidate selection. A
request deadline, complexity budget, maximum repeated-value count, text length,
date span, and geometry result limit prevent filter-based denial of service.

### UI state and interaction

One store owns `query`, `presentation`, `selection`, request generation, and
the last accepted `snapshot`. Dataset/flight controls, filter drawer, active
filter chips, map extent toggle, result count, segment/timeline list, and popup
subscribe to that store. No layer may construct an independent scientific
query. Changes abort the preceding request; responses whose generation is not
current are discarded. During a request the previous consistent snapshot may
remain visible with a clear “updating” state, but the count, map, and list are
replaced atomically when the response arrives.

Desktop uses a compact filter bar plus expandable scientific facets. Mobile
uses a focus-trapped, labelled filter sheet and preserves the ArcGIS-inspired
observation bottom sheet. Active filters are always visible as removable chips,
with “Clear all” and a result count announced through an `aria-live=polite`
region. “Filter to map extent” is opt-in and visibly active; ordinary pan/zoom
does not unexpectedly remove records. Popup selection may highlight an item
outside the current page but never outside the query. If a shared selection is
not visible to the viewer, focus returns to the result heading and a neutral
message explains that it is unavailable.

### Compatibility and rollout

1. Parse the current fragment first, mapping legacy `ds` to canonical
   `dataset`; retain `mode`, `asset`, `cov`, `seg`, and `view`. On the first
   user change, write the canonical `qv=1` form. Old bookmarked links continue
   to open throughout the V1 lifecycle.
2. Keep `/api/radar/catalog`, `/segments`, and `/observations` during migration.
   Implement them through the same query compiler where fields overlap, and
   add response deprecation headers only after all in-repository clients move.
3. Ship the store behind an operator flag, run old and new query paths against
   fixtures in shadow comparison, then enable for maintainers, authenticated
   users, and public releases in that order.
4. Persist only harmless presentation preferences locally. The URL and server
   response remain authoritative; no query, selection, or authorization state
   depends on local storage.

### Security and verification matrix

| Test class | Required evidence |
| --- | --- |
| Parser/property | Round-trip arbitrary valid queries to one canonical URL; reject duplicate scalar conflicts, NaN/infinity, oversized repeats/text, invalid dates/ranges/CRS, malformed cursors and ambiguous percent encoding. Legacy links produce the documented V1 state. |
| Query contract | A fixed fixture exercises at least dataset + flight + CBD range + product + review + bbox. `total`, IDs in `items`, feature IDs, facet counts and URL-derived query agree exactly; unknown values obey explicit semantics. |
| Authorization | Owner A's private/manual/automatic records never appear to B or anonymously through items, features, totals, facets, timing-distinguishable errors, selection, or cursor replay. Maintainer-only sources remain absent for ordinary users. Public endpoints expose only complete, non-withdrawn releases. |
| Consistency/races | Rapid filter changes, aborted requests, delayed out-of-order responses, back/forward, reload, expired cursor, and release withdrawal cannot mix snapshots. Count, map and list update atomically. |
| Spatial/time | Boundary-inclusive WGS84 boxes, antimeridian crossing, polar fixtures, known/partial/unknown acquisition dates, and separate history dates return exact sets. Camera-only movement does not filter. |
| Accessibility | Every filter is labelled and keyboard operable; chips expose removal names; sheet/popup focus returns correctly; results and errors are announced without stealing focus; 200% zoom, reduced motion and 390×844 layout pass. |
| Performance | Warm, already-loaded facet changes update visible state within 250 ms. Server p50/p95/p99 and cold/warm results are recorded for 5-, 8-, and 12-dimension queries at representative catalog size and 20 concurrent users; the run also records SQL plans and confirms intended indexes. |
| Compatibility | Existing `#mode=…&ds=…&flight=…` bookmarks, catalog pagination, map segments, private observations, published observations and scientific quicklook tests remain green until their documented removal release. |

E-F1 is complete only when this matrix is automated in CI/browser tests and a
saved shared URL independently reproduces the same permitted result identifiers
and normalized query—not merely the same visible camera.
