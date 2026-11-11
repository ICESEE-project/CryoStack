# Frozen Legacies Developer Guide

Dataset operators should also follow the [dataset intake runbook](data_intake.md)
for checksum, scratch, CEDAR promotion, and TIFF-association requirements.
Repository and interoperability decisions are recorded in the
[scientific data platform architecture](scientific_data_platform.md).

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>

<div class="cryostack-app-doc-page">

  <section class="cryostack-app-doc-hero">

    <div class="cryostack-section-label">
      Frozen Legacies Documentation
    </div>

    <h1>Frozen Legacies Developer Guide</h1>

    <p>
      Extend Frozen Legacies with additional radar datasets,
      dataset adapters, scientific products, storage backends,
      and frontend capabilities while preserving a common
      CryoStack data model.
    </p>

    <div class="cryostack-docs-actions">

      <a
        class="cryostack-btn primary"
        href="/frozen-legacies/"
      >
        Open Frozen Legacies
      </a>

      <a
        class="cryostack-btn secondary"
        href="getting_started.html"
      >
        Getting Started
      </a>

      <a
        class="cryostack-btn secondary"
        href="user_manual.html"
      >
        User Manual
      </a>

    </div>

  </section>

  <div class="cryostack-app-doc-content">
:::

Frozen Legacies is designed as a modular data application within CryoStack. Dataset-specific ingestion is separated from the web interface so that additional radar campaigns can be incorporated without adding collection-specific logic to the frontend.

The primary data flow is:

```text
Dataset Manifest
       ↓
Dataset Registry
       ↓
Dataset Adapter
       ↓
Normalized Observation
       ↓
GeoJSON Builder
       ↓
catalog.json
observations.geojson
flights.geojson
       ↓
Frozen Legacies Frontend
```

:::{note}
**Source preview · 10 November 2026.** This documentation is built from HEAD `1f6743e912da422680fa273a7d94c329fb51003b` plus explicitly hashed, uncommitted public WIP; it is not labelled as a future release commit. The approved public baseline is the 29-path union overlay including the 15-file picker deployment. Root has recorded normal-SSH82 HTTP/native cases and core review-browser workflow passes; the latest key/title presentation CUA, actual commit and qualified documentation rebuild remain later steps. Scanner naming remains OFF, including after a code installation unless separately activated.
:::

## Application Structure

The Frozen Legacies application is located under:

```text
icesee_jupyter_book/
└── applications/
    └── frozen_legacies/
```

The application contains the data-ingestion framework, generated frontend data, the interactive map, the authenticated radar workspace (server, pickers, products), and documentation.

```text
frozen_legacies/
├── adapters/               dataset adapters (LYRA)
├── assets/                 browser modules and CSS
├── data/                   generated catalog/GeoJSON (build output)
├── datasets/               dataset manifests (YAML)
├── pickers/
│   ├── astra.py            ASTRA manual picker port
│   └── ursa_runner.py      URSA subprocess entry point
├── radar/
│   ├── ingest.py           TIFF / navigation validation
│   ├── sources.py          shared radar source registry
│   ├── assets.py           per-user radar assets (asset.json)
│   ├── render.py           decode cache and window rendering
│   ├── manual.py           ASTRA sessions and outputs
│   ├── automatic.py        URSA jobs
│   └── products.py         product model, uploads, validation
├── tests/
├── build_antarctica.py
├── build_geojson.py
├── dataset_registry.py
├── server.py               gateway routes and the application API
├── workspace.py            per-user workspace and path containment
├── index.html
├── getting_started.md
├── user_manual.md
├── developer.md
└── api_reference.md
```

`Pickers/` holds the ASTRA reference script (`ASTRA_MAC.py`) and local test data; it is not imported by the application.

**The picker implementations are not in the public repository.** `pickers/`, `Pickers/` and the ASTRA reference/golden tests are distributed separately and are gitignored; a deployment that holds them installs them at those paths. Application code imports ASTRA through `optional_pickers.py`, so without them the gateway still starts: manual-picking requests return `503` ("not installed on this server"), automatic picking reports LYRA/URSA as unavailable, and the picker tests skip.

## Dataset Registry

Frozen Legacies discovers datasets through its dataset registry.

Dataset manifests are stored under:

```text
applications/frozen_legacies/datasets/
```

For example:

```text
datasets/
└── lyra.yaml
```

The registry loads each manifest, validates the dataset definition, identifies the requested adapter, and returns the configured dataset and adapter to the build pipeline.

Dataset `id` values must be unique across all `.yaml` and `.yml` manifests in the directory. The registry stops before ingestion and reports both manifest paths when it finds a duplicate; this prevents one collection from silently replacing another in generated catalog indexes.

## Dataset Manifests

A manifest describes the scientific collection independently of the frontend.

A current manifest may contain:

```yaml
id: frozen-legacies-lyra

title: Frozen Legacies LYRA Radar Observations

adapter: lyra

campaign: Frozen Legacies

institution: Georgia Tech

description: >
  Restored Antarctic airborne radar observations and
  LYRA-derived geophysical products.
```

Additional sections can describe metadata, storage, build behavior, products, and capabilities.

## Metadata

Dataset metadata may include:

```yaml
metadata:

  project: Frozen Legacies

  product_family: LYRA

  coordinate_system: EPSG:4326

  version: 1.0

  citation: null

  doi: null
```

These fields provide scientific context for the collection.

## Storage Configuration

The current LYRA dataset reads files from local CryoStack storage.

A storage configuration can be represented as:

```yaml
storage:

  type: local

  root: external/FrozenLegacies/Frozen Legacy Tools/LYRA Output
```

The architecture is being kept storage-independent so that other backends can be added later. Radar files for the picker workspace already come from local/mounted directories, the Georgia Tech CEDAR shares (implemented `cedar` provider) or read-only Amazon S3; see *Data Sources, Catalog and User Work* and *Storage layout* below. HTTPS resources and other remote scientific data services remain possible future backends.

## Adapter Architecture

Adapters translate native datasets into the common Frozen Legacies observation representation.

The frontend should never need to know the original CSV column names or native file structure.

Instead:

```text
Native Dataset
      ↓
Dataset Adapter
      ↓
Normalized Observation
```

## Base Adapter

Common adapter functionality belongs in the shared adapter base class.

This may include:

- dataset configuration,
- file discovery,
- observation loading,
- normalization hooks,
- and validation.

Dataset-specific parsing belongs in the concrete adapter.

## LYRA Adapter

The current LYRA adapter reads restored `*_echoes.csv` files.

A typical discovery pattern identifies files such as:

```text
F125_echoes.csv
F141_echoes.csv
```

The adapter normalizes each valid record into the common observation model used by the rest of Frozen Legacies.

## Normalized Observation Model

The normalized observation model provides the contract between dataset adapters and the build pipeline.

A normalized observation may contain:

- observation identifier,
- dataset identifier,
- longitude,
- latitude,
- flight,
- frame index,
- source file,
- echo status,
- ice thickness,
- bed SNR,
- surface temperature,
- reflectivity,
- attenuation,
- specularity,
- and additional dataset metadata.

Not every field is required for every dataset.

## Coordinate Handling

Source observations are currently represented using geographic longitude and latitude.

Generated GeoJSON uses:

```text
EPSG:4326
```

The frontend transforms those observations into:

```text
EPSG:3031
```

for Antarctic Polar Stereographic visualization.

Dataset adapters should provide geographic coordinates in the normalized representation unless a future adapter explicitly documents another input convention.

## GeoJSON Build Pipeline

Generated frontend datasets are produced by:

```text
build_geojson.py
```

Run:

```bash
python -m \
  icesee_jupyter_book.applications.frozen_legacies.build_geojson
```

The builder:

1. loads registered dataset manifests,
2. creates the configured adapters,
3. loads normalized observations,
4. combines observations across datasets,
5. generates flight geometry,
6. builds the dataset catalog,
7. and writes the frontend data products.

## Generated Data

The current build produces:

```text
data/
├── catalog.json
├── observations.geojson
└── flights.geojson
```

## `observations.geojson`

Contains the individual georeferenced radar observations.

Each feature is represented as a GeoJSON point with normalized properties.

## `flights.geojson`

Contains generated flight geometry.

Flight tracks are represented as `MultiLineString` geometry so that spatial discontinuities between survey passes can be preserved.

## Flight Segmentation

Sequential observations are compared spatially during track generation.

When the distance between neighboring observations exceeds the configured threshold, the builder starts a new flight segment.

This prevents unrelated survey passes from being connected by artificial straight lines.

## `catalog.json`

The catalog contains dataset-level information required by the frontend.

It may include:

- dataset identifier,
- title,
- adapter,
- campaign,
- institution,
- description,
- observation count,
- available flights,
- scientific products,
- downloads,
- and other metadata.

## Products

Scientific products are declared at the dataset level.

For example:

```yaml
products:

  radargram:

    title: Radargram

    type: image

    path:

      field: radar_image

    downloadable: true
```

A second product may use a path template:

```yaml
echogram:

  title: Processed Echogram

  type: image

  path:

    template: media/{flight}/{file_id}.png

  downloadable: true
```

## Product Resolution

Product locations can be derived from:

- an observation field,
- a path template,
- or a future storage-provider resolver.

The frontend should receive normalized product metadata and should not depend on the physical storage implementation.

## Build Configuration

Dataset manifests can control which generated products should be built.

For example:

```yaml
build:

  observations: true

  flights: true

  include_products: true
```

Download-related build settings may also be declared.

## Capabilities

Dataset capabilities describe functionality that can be exposed to the frontend.

For example:

```yaml
capabilities:

  observations: true

  flight_lines: true

  imagery: false

  downloads: true

  citations: true

  search: false
```

Capabilities allow the interface to react to dataset features without hardcoding dataset identifiers.

`dataset_registry.py` merges a manifest's `capabilities` with defaults (`observations` and `flight_lines` true; `imagery`, `raw_radar`, `downloads`, `citations`, `search` false) and keeps its `build` block; `build_geojson.py` writes both into each `catalog.json` dataset. The frontend uses them:

- `downloads: true` with `build.downloads.observations_geojson` / `flights_geojson` enables **Dataset downloads** (`/frozen-legacies/api/datasets/<id>/downloads/<kind>`), cut per dataset from the generated GeoJSON;
- `raw_radar: false` makes the Dataset Explorer state that the dataset provides no raw radar.

Manifests stay declarative: they state what exists, never how the application behaves.

## Frontend Architecture

The Frozen Legacies frontend is separated into focused JavaScript modules.

## `map.js`

Owns:

- EPSG:3031 registration,
- map creation,
- OpenLayers view configuration,
- map camera behavior,
- reset behavior,
- and coordinate transformation.

## `layers.js`

Owns:

- vector sources,
- flight layers,
- selected-flight layers,
- observation layers,
- Antarctic reference layers,
- South Pole layer,
- and overlays.

## `styles.js`

Owns visual styling for:

- default flights,
- faded flights,
- selected flights,
- observations,
- and observation status colors.

## `data.js`

Owns:

- loading generated JSON and GeoJSON,
- response validation,
- EPSG:4326 to EPSG:3031 transformation,
- source population,
- dataset indexing,
- flight indexing,
- observation indexing,
- and data lookup.

## `ui.js`

Owns:

- dataset selector behavior,
- flight selector behavior,
- selected-flight state,
- observation inspection,
- filtering,
- map click handling,
- pointer behavior,
- and selected-record rendering.

## `frozen_legacies.js`

Acts as the application entry point.

It coordinates:

```text
layers
  ↓
map
  ↓
data
  ↓
UI
```

The entry point should remain orchestration-focused rather than accumulating map, styling, or data-processing logic. After the explorer UI, it initializes the radar workspace (`FrozenLegaciesRadar.initialize({map, ui, data})`).

## Orientation, caption identity and map eligibility

Four pure modules are the single authorities; no other code may contain a
direction formula or a separate eligibility rule.

* `orientation.py` — `resolve(record, anchors=, segment=)` returns a
  `SegmentOrientation` (direction, left/right/min/max CBD, basis, evidence).
  A: increasing; Z: decreasing; ESM: unresolved unless verified captions or a
  reviewed segment. `cbd_at_x`, `x_at_cbd`, `frame_cell`, `contains`,
  `ordered_cbds`; `check_direction` / `upstream_signed` validate evidence files
  and upstream signed pairs instead of trusting them. Catalog `cbd_start` /
  `cbd_end` are an unordered range; for `radarfilm-*` datasets their order is
  upstream's screen-left/right reading, and a reading that contradicts the
  A/Z rule makes the film `unresolved` (basis `conflict`) on every surface
  until a reviewer confirms it (`screen_claim_conflicts`). Legacy SPRI fields
  are a min/max pair and make no claim. The browser mirror is
  `assets/radar_geometry.js` (`estimateViewCbd(column, width, orientation)`),
  tested against `tests/orientation_parity_cases.json`.
* `caption_grammar.py` — raw printed caption → rows, grammar, fields and
  status (`verified` > `documented` > `strongly_inferred` > `inferred` >
  `unresolved`); caption classes; `MAP_MINIMUM = documented`.
* `film_segments.py` — append-only `film_segment_revisions` (SQLite file
  beside the catalog, created on first reviewer write): x range, source and
  reviewed scope, caption class/format, raw caption, interpretations,
  orientation, evidence status, reviewer, reason, supersession, retraction.
  Reviewer writes are gated by `CRYOSTACK_SCANNER_SEGMENT_REVIEW` (off by
  default; the Scanner route answers 409). `reviewed_film_orientation`
  lets a confirmed whole-film segment restore an estimate window.
* `film_estimates.py` — an unresolved or contradicted orientation returns
  the explicit state `unavailable-pending-metadata-review` ("Location window
  unavailable pending metadata review"), never a mirrored window.
* Printed-caption evidence (`data/printed_caption_evidence.json`, schema
  `cryostack.printed-caption-evidence.v1`; override with
  `CRYOSTACK_FROZEN_LEGACIES_PRINTED_EVIDENCE`) stores raw captions read on
  originals with their reader and status. `map_eligibility.evidence_conflict`
  interprets each with `caption_grammar` and reports a `flight`, `cbd_bounds`
  or `both` conflict against the catalog; evidence at `strongly_inferred` or
  better adds the reason `printed_caption_conflict` (identity unusable, so map,
  availability, SQL spatial filter and observations all drop it), and
  `film_estimates` / `scope_previews` / observation previews withhold the
  window (`EvidenceConflict`). Evidence never sets an identity; a Verified
  review supersedes it.
* `map_eligibility.py` — `assess(record, review=, registry=, evidence=)` and
  `Context.for_catalog(catalog)` (reviewed segments + identity registry);
  `sql_identity_clause()` is the SQL form, tested for equivalence. Used by
  `map_coverage.coverage_bundle`, `RadarCatalog.segments`,
  `RadarCatalog.explorer_snapshot` (features, spatial filter, per-item
  `map` decision), published observations and workspace observation exports.

The identity registry (`cache/frozen-legacies/identity-registry.json`) is
built offline by `deployment/radarfilm_identity_registry.py` from the pinned
upstream manifest and optional audited readings; it never edits the catalog.

## Map Inspection and Optional Context

`assets/map_explorer.js` supplies inspection/source rows, finite supplied quantities, `segmentMatches`, `manifest`, and `mountLayers`/`finishLayers`. The existing `#fl-map-data-controls` visibility UI is mounted once; Data and result-layer proxies keep their original stores. The original legend and RIGGS nodes are retained in a compact persistent Map-only key outside the collapsed Layers disclosure, preserving listeners/state rather than cloning controls. The legend follows visible scientific layers. One first-row search uses the existing query/chip/history store. Loaded matches, hidden-by-layer counts and catalogue snapshot counts are separate. Catalogue rows expose flight/CBD data attributes and link selections on **this page only**.

`openQuicklookWorkspace` keeps the selected exact accessible source route. If absent, it dispatches `frozen-legacies:browse-source`; `radar.js` switches the requested picker and `catalog.browseMatch` searches actual flight/CBD with authenticated `context=picker`, `scope=a|z`. Multiple or zero candidates remain explicit. Picker filtering never overwrites the Map query; scope display flags do not bypass catalogue authorization. No engine-derived identity or neighbouring caption is substituted.

Save selection remains the existing JSON download: `cryostack.frozen-legacies.selection-manifest.v1`, selected record plus up to5,000 loaded matching visible observations, with truncation, canonical query, source units/coordinates, dataset version/citation/licence and whitelisted provenance/local product links. It excludes hidden records, private paths, signed URLs/tokens and engine aliases. It is not a full catalogue snapshot/export; authenticated GeoJSON routes are unchanged.

The NASA default context is `BlueMarble_ShadedRelief_Bathymetry`, JPEG/default, EPSG:3031 `500m`. The same-day official capabilities receipt identifies origin `[-4194304,4194304]`, extent ±4194304, 512px tiles, resolutions `8192/4096/2048/1024/512` m/px, and square matrix sizes `2/4/8/16/32`. URL: `https://gibs.earthdata.nasa.gov/wmts/epsg3031/best/BlueMarble_ShadedRelief_Bathymetry/default/500m/{z}/{y}/{x}.jpeg`. There is no grid reprojection or guessed origin. The test fixture `tests/gibs_3031_metadata.json` records the official capabilities SHA and native metadata. [NASA access basics](https://nasa-gibs.github.io/gibs-api-docs/access-basics/) and [advanced topics](https://nasa-gibs.github.io/gibs-api-docs/access-advanced-topics/) describe access and resolutions.

`prepareImagery()` runs immediately after map creation, before the observation archive await. It is synchronous and independent of data/filter/UI readiness; `finishLayers()` attaches controls to that same controller. A WeakMap keeps one controller/source/layer per map. The unchanged session preference key preserves explicit OFF and suppresses creation of a NASA source on that path. The original Quantarctica source is shared by a solid fallback below the imagery and unfilled boundary context above it. The existing geography toggle controls both; no second geometry fetch is added. Imagery opacity is 1. Where supported, an owned sRGB SVG component-transfer filter applies `out = base + (1-base) × in^1.5` to the isolated `fl-nasa-context` canvas, using the local ocean RGB as `base` and leaving alpha unchanged. It changes display colors only; unsupported filtering leaves the unmodified imagery available. Scientific vector layers and their colors remain above and outside the filter. Label/category/basin style objects are reused while panning; overview place names use a smaller set and halo text without boxes.

A separate canvas clips imagery to the existing 3.4Mm polar display domain, using OpenLayers render transforms so DPR and map rotation are respected. This prevents a rectangular tile footprint outside the polar frame; it is not a geographic mask or inferred coastline. Native tile URLs reject invalid matrix coordinates and tiles wholly outside the frame. The local ocean background is coherent before any image arrives. One parent level is preloaded for progressive detail; the renderer cache target is 128 tiles (not a disk cache or a strict memory ceiling). OpenLayers may retain additional viewport tiles. Map tile queue concurrency is 8; explicit retries submit at most 6 failed tiles per click and are disabled while tracked requests are pending. No automatic refresh/retry loop or cache-busting URLs are used. The finest existing 512m context remains available on zoom.

`tileloadstart/end/error` drive waiting/loading/received/partial-error state. Failures do not disappear when another tile succeeds. A 20s image timeout releases a hung tile into retryable ERROR state. Retry calls the failed `ImageTile.load()` API, preserving successful tiles and source identity instead of `source.refresh()`. See pinned [OpenLayers ImageTile](https://github.com/openlayers/openlayers/blob/v10.6.1/src/ol/ImageTile.js), [tile renderer cache](https://github.com/openlayers/openlayers/blob/v10.6.1/src/ol/renderer/canvas/TileLayer.js) and [preload/cache options](https://github.com/openlayers/openlayers/blob/v10.6.1/src/ol/layer/BaseTile.js). The normal map notice disappears after completed successful requests; source details retain a truthful session receive count. Requests use anonymous CORS and no-referrer. NASA acknowledgement and policy links remain available while enabled.

No first-party tile cache, service worker, tile proxy, bulk mosaic or bundled raster is added. Browser HTTP caching follows NASA's response headers; the prior same-day original-layer receipt reports `public,max-age=259200`, ETag and HTTP/2. This is not a measured cache lifetime for the new bathymetry layer. NASA's advanced docs still describe HTTP/1.1 sharding; the observed HTTP/2 receipt argues against adding aliases without a current protocol/latency benefit measurement. This sandbox cannot resolve the direct endpoint, so new bathymetry pixel inspection, cold/warm timing, cache headers and actual browser request counts remain for Root's bounded API and visual qualification. The report includes exact retrieval commands and the no-browser regression results; unit tests do not establish all-feature or live visual acceptance.

`mountGlobeButton()` lazily loads the same-origin `globe_view.js`/`.css` only after an explicit **3D globe** request; the module loads its pinned Cesium assets with integrity checks on enable. The optional SCENE3D view uses a WGS84 ellipsoid without a terrain service or Ion account. It converts current visible OpenLayers feature geometries from EPSG:3031 to longitude/latitude, keeps original feature references for selection callbacks, and shares imagery preference, filters, Layers and the existing key/RIGGS DOM. Resolution-dependent label choices use the preserved 2D view resolution. Globe controls, popup anchoring and active reset/fit/zoom are routed to its own camera; disabling saves the globe camera, destroys the Viewer and restores 2D interactions and presentation without writing the 2D camera/URL. Loading, WebGL/context and rendering failures keep a usable 2D fallback.

Wheel input owns only the native WHEEL zoom path, retaining native drag, pinch and keyboard paths. Pixel/line/page deltas normalize to bounded work in short steps. Wheel translation follows the actual ellipsoid-pick ray through public `worldToCameraCoordinatesVector` and `camera.move`, preserving its screen anchor and camera basis; off-globe input follows the camera direction without inventing coordinates. OFF/ON restores world position and the direction/up/right basis through public Camera vectors. The custom wheel path constrains ellipsoid height to 1 km–40,000 km on the same ray; navigation buttons bound their zoom amount. Native drag and pinch retain separately configured zoom-distance, collision and tilt limits with lower inertia. New pointer/touch/key input cancels pending wheel work; OFF/error/disposal cancel its timer and restore native ownership.

One CPU snapshot may survive OFF, bounded to 50,000 rows and 500,000 converted coordinate pairs; exceeding the bound disables retention without truncating rendered data. Geometry/source, layer/style/property/visibility, filter/selection/store, view/resolution and collection replacement changes invalidate or rebind it, including while OFF. NASA progress updates status without repeating full projection. Loading and ready suppress only fallback land/shelf fills; outlines, drainage-basin fills and all data remain. Explicit imagery OFF or failure restores filled vector context. Loading→ready keeps the same fill policy; a true fallback-policy change can reuse projection. GPU resources are never retained: OFF, hidden tab, error and disposal still destroy the Viewer, primitives and imagery. Adaptive quality bounds active scale to `min(DPR,1,sqrt(3000000/(width×height)))` and idle scale to `min(1.5,max(DPR,1.25),sqrt(4500000/(width×height)))`, using CSS-pixel dimensions and DPR 1 for invalid density. Builds and motion use active quality. Idle refinement waits for vector preparation, the held-input gate to clear and a stable public camera pose over 240 ms, with Viewer/epoch/visibility checks and upscale hysteresis. Public-pose checks recover a settled view even if a movement-end notification was missed. Each quality resize restores the camera frustum aspect from CSS client dimensions, rather than rounded drawing-buffer dimensions. This permits modest supersampling even at DPR 1 within the pixel cap; scientific values and coordinates do not change. Engine/vector readiness is separate from NASA tile readiness. Synthetic timing/work-count checks do not establish real cold startup, GPU/FPS performance or 1,000-user capacity.

Whole-layer preparation prioritizes observations, own results, reviewed results, RIGGS and the selected flight before context. Original layer ordinals, within-layer row/style order and five primitive-kind × layer buckets preserve drawing order. The first descriptor window is 128 rows; later windows are bounded at 3,584 and stop at layer boundaries. Conversion yields after approximately 5 ms or 8,192 steps through guarded `scheduler.yield()` with a task fallback. A per-build `WeakMap` reuses converted geometry objects shared by styles/layers without changing source coordinates. Immutable contiguous collections have soft budgets of 3,584 rows, 1,024 point coordinates, 8,192 input stroke/fill vertices and 4,096 glyph units. A single oversized row stays intact and is flagged to preserve joins/holes; these are input-work budgets, not hard GPU tessellation or latency bounds. The first usable frame is not a fully prepared view. Loading feedback remains active until all required vector stages finish; NASA tile readiness stays separate. A generation token invalidates pending work on newer filters, selection, RIGGS/visibility, source/layer or view changes. OFF, hidden tab, failure and disposal cancel remaining work; superseded results cannot repaint or recreate the Viewer. Resource limits and cancellation apply to the whole preparation lifecycle, with all original feature identities and data retained.

The globe NASA provider uses the separate EPSG:4326/CRS84 `500m` endpoint with a 10×5 root geographic grid and matrix labels `3`–`7` (512px JPEG tiles, client levels0–4), avoiding a guessed 2×1 grid. An explicit shared imagery OFF suppresses its provider. The globe uses its own loading/failure/retry state, independent of 2D tile counters; no automatic retry loop is added. App queries, credentials and source paths are not copied to provider URLs or headers. NASA credits remain visible. Globe image requests inherit the document/browser referrer policy (normally origin-only for cross-origin requests); no per-image no-referrer option is claimed for Cesium `Resource`. Shaded imagery is visual context, not measured terrain elevation or a scientific geolocation check.

## LYRA View Contract

`lyra_calibration.js` uses a fixed viewport with fit/stepped/1:1 zoom, pointer-anchored Ctrl/⌘-wheel, overview jump and explicit pan. Clicks follow the actual displayed image extent (`shownScale`), including the scale1 preload/swap. Marks stay frame-column/image-row values through zoom, resize and frame changes; no calibration values are sent by the caller. The body-level editor keeps unsaved picks across workspace repaint. Plain wheel and browser zoom shortcuts are not intercepted.

`lyra_workspace.js` observes the actual nested `#fl-automatic` height and sets `--lyra-console-room`; the sticky title/Follow header stays separate from the independently scrolling log, whose boundaries can chain outward. Source-film range/ARIA/endpoints clamp synchronously with viewport changes in `radar.js`; Home/End/arrows/Page keys use source columns. Generic panel/details/focus toggles share visibility state and do not repaint away drafts. Root CUA passed the desktop last-line/Follow/outer-wheel correction at1440×900 and1280×720, separately from the accepted pixel-mapping/zoom and source-slider Home/End/max/ARIA checks.

## Radar Workspace Modules

| Module | Responsibility |
|---|---|
| `radar_geometry.js` | Pure viewing geometry (windows, scales, click → ASTRA data coordinates, the ASTRA window box `fitBox`, explicit radar-source matching). Unit-tested under Node. |
| `radar.js` | Mode bar, radar asset list, raw-radar upload, Automatic-mode viewer, Dataset Explorer radar panel, workspace layout (side panel, focus view) and URL state. |
| `astra_picker.js` | Manual mode: sends ASTRA actions, draws the working window, trace and picks; result state after Done. |
| `automatic.js` | Automatic mode: URSA availability, run/cancel, status polling, results. |
| `products.js` | Products list, processed-product upload, bundle download, asset/product removal. |

`ui.js` announces the selected observation with a `frozen-legacies:observation` DOM event; the radar modules never reach into the explorer's rendering. No scientific computation runs in the browser.

**Workspace layout.** In Manual and Automatic the side panel can be hidden (`body.fl-panel-hidden`) and a focus view shows only the workspace (`body.fl-focus`; Esc leaves it). The preference is per browser (`localStorage["fl-radar-layout"]`, read and written in `try`/`catch`). The radar workspace is a CSS size container: when it is clearly wider than the 2300 × 1550 working window, the three ASTRA steps move into a column beside the window. Below 1050 px the workspace flows with the page and the stage takes the window's aspect ratio. None of this touches the click mapping: `fitBox` sizes the window box with the exact aspect ratio (integer CSS width, height = width × 1550 / 2300), the box has no border (its outline is a `box-shadow`) so the image covers exactly the rectangle `astraDataCoordinates` maps against, and the box is never shrunk by flex layout. Before this, the box had a 1 px border: the image was drawn 1 px inside the rectangle used for mapping, so clicks near the window's left and right edges were off by up to W/box-width data pixels (about 3.6 px at a 642 px box), towards the centre. `tests/frozen_legacies_radar_geometry.test.mjs` checks `fitBox` and that the mapping is independent of the box size; a browser check clicked known window pixels at 1440 × 900, 1920 × 1080, 2560 × 1440 and 390 × 844, each with the panel shown, hidden and in focus view (36 clicks), and the server recorded the pixel displayed under each click every time.

**URL state.** The hash holds `mode`, the open `asset` (a 32-hex asset ID) and the map `view` (`zoom/x/y`, EPSG:3031 metres): `#mode=manual&asset=<id>&view=5.50/-280000/-900000`. Mode and asset changes add a history entry (an empty-workspace entry is replaced by the asset opened in it); map moves replace the current one. `popstate` and reload apply the hash: the camera is restored, and an asset opens only if it is one of the viewer's own available assets (anything else is dropped from the URL). `?open=<catalog ID>` (Control Center review links) still opens that radar in Manual and is then rewritten into the hash. Nothing about the radar is derived from the map view.

## Adding a Dataset

A typical new-dataset workflow is:

1. Create a dataset manifest.
2. Select or implement an adapter.
3. Normalize the source records.
4. Register the adapter if required.
5. Build the generated data.
6. Inspect the dataset in Frozen Legacies.
7. Add product definitions when applicable.

## Step 1 — Add the Manifest

Create:

```text
applications/frozen_legacies/datasets/my_dataset.yaml
```

Define at minimum:

- dataset identifier,
- title,
- adapter,
- campaign,
- institution,
- source or storage location.

## Step 2 — Implement an Adapter

If the source format is not already supported, add an adapter under:

```text
applications/frozen_legacies/adapters/
```

The adapter should translate native records into normalized observations.

## Step 3 — Build the Dataset

Run:

```bash
python -m \
  icesee_jupyter_book.applications.frozen_legacies.build_geojson
```

Verify that the dataset appears in the build summary.

## Step 4 — Update Frozen Legacies

Using the CryoStack selective deployment framework:

```bash
./update_gui.sh frozen-legacies
```

This allows Frozen Legacies to be updated without unnecessarily stopping unrelated applications when the deployment registry indicates that a runtime restart is not required.

## Deployment

Frozen Legacies participates in the common CryoStack deployment framework.

Relevant components include:

```text
deployment/
├── applications.yaml
├── cryostack_build.py
├── preflight.py
├── health_check.py
└── services.sh
```

The application-specific build process should remain declarative through the deployment registry.

## Selective Updates

For catalog, GeoJSON, or frontend changes:

```bash
./update_gui.sh frozen-legacies
```

This rebuilds the generated data without restarting anything: the gateway reads those files on every request. Changes to the Frozen Legacies server code (`server.py`, `workspace.py`, `radar/`, `pickers/`) run inside the GUI gateway and need `deployment/services.sh restart-gui`.

**Enabling the radar catalog, S3 sources and review on an installation.** No new service, port or nginx route is needed: everything runs inside the GUI gateway (behind the existing `location /` proxy to `127.0.0.1:8080`), and background indexing starts worker processes of the gateway's own Python from the repository root.

1. Set the variables in the environment that starts the GUI services (`deployment/services.sh` inherits the operator's shell environment): `CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS` for local/mounted archives and/or `CRYOSTACK_FROZEN_LEGACIES_S3_ALLOWED` (plus `..._S3_ENDPOINTS` for non-AWS endpoints); optionally `..._CATALOG`, `..._WORKING_CACHE`, `..._WORKING_CACHE_MB` and `..._REVIEW_ROOT` (see *Runtime Configuration*). Without them nothing changes: no catalog is created and the pages show no data sources.
2. For S3: give the host's workload the read-only IAM policy of *S3 data sources* (instance profile/role preferred); `boto3` must be importable by the gateway's Python. Do not use a personal AWS profile for the archive.
3. Directories are created on first use under `var/` (catalog `0640`, cache, review snapshots `0440` files) and must be writable by the gateway's service user; plan disk space for the working cache (default limit 20 GB).
4. `deployment/services.sh restart-gui`; the health check (`deployment/applications.yaml`) expects `200`/`302`.
5. In the Control Center, a maintainer registers and indexes the sources (*Frozen Legacies*); reviewers use *Frozen Legacies → Review*.
6. Schedule backups (*Backup and recovery*) together with the `users/` workspace backup.

## Runtime Configuration

| Variable | Purpose |
|---|---|
| `CRYOSTACK_WORKSPACE_ROOT` | Root of `users/<safe_id>/` (default: the gateway's working directory). |
| `CRYOSTACK_FROZEN_LEGACIES_RADAR_SOURCES` | YAML registry of shared radar (default: untracked `radar_sources.local.yaml`; none when absent). |
| `CRYOSTACK_FROZEN_LEGACIES_RADAR_CACHE_MB` | Decoded-image cache budget (default 768). |
| `CRYOSTACK_FROZEN_LEGACIES_RADAR_DECODES` | Concurrent TIFF decodes (default 1). |
| `CRYOSTACK_FROZEN_LEGACIES_URSA_ROOT` | URSA source directory (default: the FrozenLegacies submodule). |
| `CRYOSTACK_FROZEN_LEGACIES_URSA_PYTHON` | Python with URSA's dependencies: the separate environment built by `env/build_ursa_env.sh`, e.g. `~/.cryostack-envs/ursa/bin/python` (default: the gateway's Python, which lacks OpenCV, so Automatic is unavailable). |
| `CRYOSTACK_FROZEN_LEGACIES_URSA_TIMEOUT` | Seconds per automatic job (default 3600). |
| `CRYOSTACK_FROZEN_LEGACIES_URSA_CONCURRENCY` | Concurrent automatic jobs (default 1). |
| `CRYOSTACK_FROZEN_LEGACIES_CATALOG` | Radar catalog database (default `var/frozen_legacies_catalog.db`). |
| `CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS` | Approved roots for local/mounted data sources (`:`-separated; none set: none allowed). |
| `CRYOSTACK_FROZEN_LEGACIES_INTAKE_ROOT` | Local durable XFS root for resumable Control Center curator uploads; must be inside an approved storage root and separate from the read-only CEDAR dataset mount. |
| `CRYOSTACK_FROZEN_LEGACIES_S3_ALLOWED` | Approved S3 `bucket` or `bucket/prefix` entries (none set: no S3 sources). |
| `CRYOSTACK_FROZEN_LEGACIES_S3_ENDPOINTS` | Optional approved S3-compatible endpoints, `name=https://host`. |
| `CRYOSTACK_FROZEN_LEGACIES_WORKING_CACHE` | Working-copy directory for remote files (default `var/frozen_legacies_cache`). |
| `CRYOSTACK_FROZEN_LEGACIES_WORKING_CACHE_MB` | Working-cache size limit (default 20480). |
| `CRYOSTACK_FROZEN_LEGACIES_REVIEW_ROOT` | Review snapshots (default `frozen_legacies_reviews/` next to the catalog database). |
| `CRYOSTACK_FROZEN_LEGACIES_REVIEW_ROOT` | Review snapshots (default `frozen_legacies_reviews/` next to the catalog database). |

AWS credentials for S3 sources are not Frozen Legacies settings: the AWS SDK resolves them from the gateway's workload (IAM role) or default credential chain.

Uploads are limited to 200 MB, matching nginx `client_max_body_size 200M`.

The deployment system:

1. runs preflight validation,
2. resolves dependencies,
3. determines whether a runtime restart is required,
4. builds the application,
5. and runs the application health check.

## Full CryoStack Deployment

For a complete platform rebuild and restart:

```bash
./reboot_gui.sh
```

Use the full deployment only when changes affect shared platform components or multiple applications.

## Documentation Build

Use the established selective Jupyter Book build with an **absolute** application TOC (`icesee_jupyter_book/toc/frozen_legacies.yml`), the normal shared theme/assets, and notebook execution disabled in an output-local config. The local `cryostack_assets` extension must resolve from the real book's `_ext` directory when the config is outside the book. Build to a separate report directory; do not run `bin/build_application_docs.sh` for a bounded update because it clears/copies other application output.

The current TOC contains Overview, Getting Started, User Manual, Developer Guide and API Reference. Only changed approved HTML and matching `_sources` artifacts belong in a documentation delivery; a partial build must not replace shared `_static`, search indexes, `objects.inv` or other applications. `scanner_naming.md` is a source-only operator supplement, outside this TOC; its public operational facts are included below, with no dead page link or application-index change.

A source preview manifest records actual HEAD, dirty input hashes, absolute config/TOC, tool versions, commands, warnings and output hashes. It never claims a later commit. After root's final QA and commit, rebuild from that reviewed commit and record the new exact input/artifact manifest; qualify the served asset dependencies and prior documentation baseline before release. Exact preview and post-commit commands are supplied in the dated documentation handoff.

## Validation Status

The integrated source has 354 distinct focused Python cases and 152 Node assertions passing, including source lifetimes, permissions/metadata/naming recovery, native Map identity/review, TERRA reference selection and LYRA view contracts. These are bounded checks, not a full repository suite. Private/native hashes remain pinned. The new small synthetic TERRA reference-transfer proof requires byte-identical CSV/PNG and all numeric fields, with no tolerance; deterministic integration picks reproduce spacing 136.66668681627175. Such fixtures establish implementation invariance, not scientific calibration accuracy.

Root's normal-SSH isolated HTTP/native suite now passes all82 cases in28.15s; it retains actual run_worker/spawn_owned attestation and lower subprocess doubles. Earlier CLI async stalls were tooling/namespace limitations, not pending root HTTP acceptance. Root review-CUA preserves exact LYRA source column600/reference row1737 through zoom/frame/resize, console last-line/Follow/outer wheel and source-slider endpoints. TERRA A→B calibration-only→A result passed with13 CBD marks, surface[5], bed[2,3], transmitted[5], native spacing136.66666263794346px/11lines; B's saved revision4 API state remained semantically exact. Those physical fractional picks are distinct from fixed-input exact native goldens and establish no scientific accuracy. Map F141/CBD140 offers three explicit A-file variants and returns with record/query/flight/camera retained. NASA default ON tiles/outlines/labels and explicit OFF→reload OFF→restore ON passed in the isolated review browser. Save-selection download is user-confirmed, contents unit-tested, with no file-inspection claim. The new persistent-key/return-title presentation still needs final root CUA. No production release, global source-reader adoption or real archive pilot is claimed.

The browser's ASTRA display and LYRA/TERRA view controls are presentation only; coordinate mapping and native output values remain unchanged. Source identity hashes are not scientific validation.

## Authentication

Frozen Legacies uses the common CryoStack account component.

The shared account client is located under:

```text
icesee_jupyter_book/_static/cryostack_account.js
```

Standalone applications can mount the component into a specific target using:

```javascript
window.CryoStackAccount.mount(
  "#cryostack-account-slot"
);
```

The account component communicates with the common CryoStack authentication service.

Access is enforced on the server, not in the browser. `server.py` registers
the application page, `assets/`, and `data/` on the CryoStack gateway
(`bin/icesee_app.py`) through `install_frozen_legacies(app, auth=auth)`, and
wraps every route in the same `auth.require_login(...)` used for CryoLauncher
and ICESEE. Anonymous requests are redirected to
`/auth/login?return_to=...`; there is no Frozen Legacies-specific
authentication.

## User Workspace

Shared Frozen Legacies data (manifests, catalog, observations, flight tracks)
is served from the application directory and is the same for every user.
User-owned work is kept separately, inside the standard CryoStack per-user
workspace, in an application-scoped directory:

```text
<owner_root>/frozen_legacies/
└── radar/
    └── <asset_id>/
        ├── asset.json
        ├── source.tiff
        ├── nav.csv
        ├── session.json
        └── outputs/
```

`<owner_root>` is `owner_root(user)` from `cryostack_src.workspace` — the
same `users/<safe_id>` directory CryoLauncher and ICESEE use for the same
account. `workspace.py` provides `FrozenLegaciesWorkspace`:

- the owner is always the authenticated gateway user
  (`request["cryostack_user"]`, via `workspace_for_request(request)`);
- asset IDs are generated on the server (`uuid4().hex`) and validated before
  any filesystem access;
- the browser never supplies filesystem paths;
- every returned path is resolved (following symlinks) and must remain
  inside the user's `frozen_legacies/` directory.

The workspace is created when an authenticated user opens the application.
User files are never served from the static application tree.

A radar asset is either an **upload** (the user's `source.tiff` and optional
`nav.csv`, streamed into the asset directory) or a **shared** reference: its
`asset.json` names a shared radar source by key and the TIFF is never copied.
Shared radar sources are installation configuration, read from the YAML file
named by `$CRYOSTACK_FROZEN_LEGACIES_RADAR_SOURCES` (or a local, untracked
`radar_sources.local.yaml`); see `radar/sources.py` for the format. A source
is linked to explorer observations only when it explicitly names their
`dataset_id`.

The radar API is served under `/frozen-legacies/api/` (see the `server.py`
module docstring). The browser requests server-rendered windows of the radar
strip (`assets/<id>/view?x=&width=&scale=`); it never receives the full TIFF
or any server path.

## Manual Picker (ASTRA)

Manual mode is a port of the ASTRA manual A-scope picker,
`Pickers/ASTRA_MAC.py`, which remains the scientific reference and is not
modified.

- `pickers/astra.py` holds ASTRA's functions with ASTRA's expressions and
  constants (crop rows 250–1800, 2300-column window, 2100 columns of
  dtype-maximum padding, σ = 4 smoothing on the original integer dtype,
  10th-percentile trace, −55 dB / +10 dB Y grid, one-division X grid,
  168 m/µs, CBDs by committed-row order, exact-CBD LAT/LON). Its
  `AstraSession` methods correspond one-to-one to ASTRA's GUI callbacks.
- `radar/manual.py` persists the session, validates it, writes outputs
  atomically, and caches working-window traces cut from the decoded-image
  cache.
- `tests/frozen_legacies_astra_reference.py` executes the unmodified ASTRA
  functions headlessly; `tests/test_frozen_legacies_astra_parity.py` compares
  the port with them step by step (window, padding, trace, state, title) and
  requires byte-identical CSV and QC output.

Endpoints (all owner-scoped; POST requires same origin):

- `GET  assets/<id>/manual` — session state, ASTRA geometry, current trace;
- `POST assets/<id>/manual` — one action `{"action", "revision", ...}`:
  `setup`, `sweep_rate`, `select`, `click` (window data coordinates),
  `move`, `step`, `suggest`, `next`, `done`, or `reset` (with
  `"confirm": true`). A stale `revision` returns 409;
- `GET  assets/<id>/manual/window?slider=` — the smoothed working window;
- `GET  assets/<id>/outputs/astra-csv` and `.../astra-qc` — downloads.

`session.json` (`cryostack.frozen_legacies.astra_session`, version 1) stores
the status (`in_progress` / `completed`), a revision counter, timestamps, and
ASTRA's per-TIFF state plus pick provenance (`manual` / `suggested`). It holds
no identities or paths. Outputs are `outputs/<TIFF stem>.csv` (rewritten on
**Next A-scope** and **Done**, as ASTRA does) and `outputs/<TIFF stem>_QC.png`
(on **Done**). For the CSV, navigation is read as ASTRA reads it, so raw
values such as `9999` are written unchanged; the viewer's normalized
navigation summary is separate.

## Automatic Picker (LYRA)

LYRA (Layered-echo Yield from Radiometric Archives; handoff `Pickers/Automatic_picker/LYRA.zip` and guide of 13 October 2026) is the default automatic picker. URSA (next section) stays available as the fallback.

**Selection.** `CRYOSTACK_FROZEN_LEGACIES_AUTOMATIC_PICKER` = `lyra` (default) | `ursa`. Set it explicitly in deployment configuration; an unrecognised value is logged and LYRA is used. Every job records `picker` and `picker_version` (`source_sha256` of the picker's code, file count, commit when determinable) when it is created, so failed and interrupted jobs carry them too; every LYRA product records `"picker": "LYRA (automatic)"` and `lyra_source_sha256` in its provenance. The Automatic view shows the results of the picker of the asset's latest job, so earlier URSA results stay readable after a switch; all automatic products stay listed under Products.

**Configuration.** `CRYOSTACK_FROZEN_LEGACIES_LYRA_ROOT` (directory holding `codes/`; default `Pickers/Automatic_picker/LYRA`), `CRYOSTACK_FROZEN_LEGACIES_LYRA_PYTHON` (default: the gateway's Python; dependencies in `env/lyra-requirements.txt`), `CRYOSTACK_FROZEN_LEGACIES_LYRA_RENAME_LOGS` (extra rename-log directory; `<LYRA root>/rename_logs` is always read), `CRYOSTACK_FROZEN_LEGACIES_LYRA_TIMEOUT` (30–86,400 seconds, default 3600). `CRYOSTACK_FROZEN_LEGACIES_LYRA_STAGING` (local directory for per-job staging; default `$CRYOSTACK_DATA_ROOT/cache/frozen_legacies_lyra_staging`, else `<tmp>/cryostack-frozen-legacies-lyra-<uid>`; a network file system makes LYRA unavailable with the reason). `CRYOSTACK_FROZEN_LEGACIES_URSA_CONCURRENCY` limits automatic jobs of both pickers together (1–4, default 1); invalid or unsafe values fall back to the default and are logged. A LYRA phase-1 run on a 117 MB strip peaks near 2.6 GB. Each asset also holds an advisory OS lease while its job runs, preventing duplicate work across gateway workers; the lease is released automatically if a worker exits.

**Runner.** `pickers/lyra_runner.py` runs LYRA unmodified, as its guide does, from a private copy of `codes/` (LYRA writes next to its own source) with the TIFF staged as a bounded stream copy under a declared internal name (see *Source identity* below): `detect_frames.py --method segment` (phase 1), then -- only with a `lyra-guidance` file -- `calibrate.py` (phase 3) and `echoes.py` (phase 4). Phase 3 refuses to run without a human −60 dB reference pick, and CryoStack never supplies one. Without a derived file the runner first calls LYRA's own `pick_calibration.save_picks_and_derive` on the picks (recorded as `phase2`; it imports matplotlib with the Qt backend name but opens no window, so it runs headless), as LYRA's picker does when it saves; if that fails, phase 3 runs on the picks alone. The runner writes `lyra-run.json` (phases, exit codes, where it stopped, outputs). It runs in its own process group (Cancel stops the group) and stops LYRA when the server that started it dies, so a killed gateway leaves no LYRA running for a job it later reports as interrupted. `--check` is the health check: it imports `lyra`, `segment_ocr` and `build_digit_templates` and reports package versions.

**Calibration step (LYRA's phase 2 in the browser).** `radar/lyra_calibration.py`, `assets/lyra_calibration.js`. After a run has stored `lyra-frame-index`, the step lists its complete frames and serves each as LYRA's picker displays it (rows 100–1950, the frame's columns, 2nd–98th percentile stretch of the crop; `scale` 1, 2 or 4, block mean). A person marks `ref`, `mb`, up to eight `x_grid` and four `y_grid` per frame (`MAX_X_GRID`/`MAX_Y_GRID`, from `lyra_engine.REQUIRED`): eight consecutive major time lines (2 µs) and four consecutive major power lines (10 dB). Marks must be finite and on the frame, and each line is marked once (duplicate rounded positions are refused on save). A draft saved earlier with a repeated line still opens (`build_picks(strict=False)`). `guide_state()` classifies each frame as complete (M, R, 8 X, 4 Y), partial, empty or excluded. `coverage()` requires `TARGET_FRAMES` = 5 complete frames, or every usable complete frame of a shorter film, and **no partial frame**.

**One calibration gate.** `lyra_workflow.calibration_gate` refuses a pending draft and then applies `lyra_calibration.readiness()`. Every path that calibrates uses it: `api_calibration_save` with `run`, `phase_inputs("calibration")`, and `phase_inputs("all")` whenever guidance exists (a full rerun calibrates with saved marks; *Detect frames* (`phase=frames`) never does). For browser-made guidance, readiness needs the coverage above and a verified 8 X / 4 Y engine. For an uploaded desktop-picker file it needs LYRA's own contract checked strictly: finite numbers, distinct lines, 0, 2 or 4 Y lines (4 only on a verified engine), and R on one frame. This matters because LYRA's own upload validator accepts NaN, repeated lines and three Y lines, and the original runner continues to phase 3 after a failed derivation. `workflow.calibration_blocked` carries the plain reason to the workspace. Marks are always saved first, so a refusal loses nothing. LYRA's default dB guide rows are drawn only on request (G); columns are relative to the frame's `left_px`, rows are image rows, as in `pick_calibration.py`. The server checks every mark against the frame, requires one non-excluded frame with `ref` (`calibrate.py`'s only hard requirement), writes LYRA's `F<flight>_cal_picks.json` format, validates it with the runner's validator, and registers it as `lyra-guidance` (workflow `lyra-calibration-step`, provenance with the frame index digest), replacing the previous browser-made file. Frame keys are `calibrate.py`'s (`CBD473`, `CBD473_f3`, `fr3`): for duplicated CBDs LYRA's desktop picker writes zero-padded keys (`CBD0473_f3`) that `calibrate.py` does not look up, so desktop picks on such frames are ignored by LYRA itself. An uploaded derived file is not paired with browser-made picks. The step marks nothing itself and changes no LYRA value.

**Validation of the calibration step (2026-10-23).** Real LYRA on reel `47_0004800_0004824` with a picks file built by `build_picks` (one frame: `mb`, `ref`, four `x_grid`, values from an existing test picks file in a LYRA run directory, not a scientist's marks): phases 1–4 exit 0; `calibrate.py` reports the file, the derived spacing (205.6 / 205.0 px) and `Tiff anchor: CBD473 ref=1507` propagated to all 12 complete frames; `echoes.py` writes 12 rows. This checks the plumbing only; those values are not results.

**CEDAR storage (2026-11-09).** User workspaces and the archive are on CEDAR (SMB/CIFS, `//cos-smb01`). There `symlink`, `mkfifo` and reflinks fail with `EOPNOTSUPP` (errno 95), `chmod`/`utime`/`chown`/`copystat` (`shutil.copy2`, `copytree`, cross-device `move`) fail with `EPERM`, unlinking an open file fails with `EIO`, `rmtree` right after a process wrote many files fails intermittently with `EIO`, and names are case-insensitive. LYRA's live work directory therefore stays on local POSIX storage, while the original archive and persistent workspace remain on CEDAR: each job gets a private, owner-locked directory under the local staging root (`radar/lyra_staging.py`, `tempfile.mkdtemp`, `flock` on `.owner.lock`); the runner streams the TIFF into it under the internal engine name (no symlink, hard link or reflink; free-space check first; size and SHA-256 measured during the copy; the source is opened read-only and checked unchanged), LYRA runs there unmodified, the products are copied back into the workspace with the usual atomic replace, and the directory is removed on success, failure, timeout and cancellation. The gateway removes directories no live job owns at start-up. Runner exit 5 = not enough staging space, 6 = the TIFF could not be read completely or changed while copied.

**Source identity (exact-file processing).** Missing or ambiguous historical reel provenance no longer blocks processing: LYRA processes the exact stored file the user opened. Native LYRA requires a reel-style basename and derives output IDs and a forced three-digit OCR prefix from it, so exact canonical/unambiguous rename-log names retain their supported native identity. When that provenance is missing or ambiguous, the runner streams the exact source into the job's staging directory under the declared internal basename `0_0000000_0000000-reel_begin_end.tiff`, using the known positive source flight or reserved three-digit technical code999 for unknown flight. That fallback does not assert an original reel or independently verify a source flight. Every job and every produced product's provenance carries a server-created `source_identity` record (`cryostack.lyra.source_identity.v1`; never accepted from the caller):

| Field | Meaning |
|---|---|
| `display_filename`, `source_key`, `catalog_id`, `dataset_id`, `asset_id` | the exact source reference; `source_segment_id` is the literal `-S<id>` filename token only |
| `input_sha256` | measured while copying the exact source bytes; later phases and resumes reuse it and the same engine namespace, and a mismatch or missing input is refused (runner exit 6) before any native phase runs |
| `verified_original_name` | the canonical reel name, or an unambiguous rename-log entry; otherwise `null` (conflicting logs never select one), with `original_name_evidence`, `rename_logs`, `original_name_candidates`, `reason` |
| `actual_flight` | the source metadata's positive flight, or `null` for F0/unknown; `flight_evidence` states it is not independently verified |
| `engine_alias`, `engine_flight`, `engine_flight_kind`, `kind` | private native I/O labels; they never update archive filenames, catalogue flight or map positions |
| `publication_eligible` | `false`; normal review and position requirements still apply |

Native CSVs and figures are stored unchanged, so their `flight`, `tiff`, `tiff_id` and `file_id` columns, figure titles and OCR diagnostic annotations can show the internal namespace (including the forced OCR prefix). They are technical labels, not flight or location evidence, and must be interpreted through `source_identity`; nothing redraws or rewrites them. Unknown producer flight yields a null native public identity; a derived Map identity can be attached only through the separate exact-input authoritative proof described below, never just because a CBD matches navigation. Catalogue metadata changes after a run starts do not change the pinned input or namespace.

**LYRA engine and runner selection (operator).** `radar/lyra_engine.py`. Two trusted settings, both server-process environment (no request can choose them):
- `CRYOSTACK_FROZEN_LEGACIES_LYRA_ROOT` selects the engine directory.
- `CRYOSTACK_FROZEN_LEGACIES_LYRA_RUNNER` optionally selects a private runner; unset, the runner shipped with the application (`pickers/lyra_runner.py`) is used. The path must be absolute and normalised, with no `..` and no symbolic link in any component, and must name a regular file. Anything else is refused, never silently replaced.

`automatic.lyra_runner()` is the one selector used by availability (an unusable path makes LYRA unavailable with a plain message), the `--check` health check, job launch and job provenance (`picker_version.runner_sha256`).

Browser calibration with 8 X / 4 Y needs `automatic.lyra_calibration_engine()` to report ready (cached 60 s). That requires `<LYRA root>/calibration-contract.json`, owner-made, ≤ 64 KiB, regular file, strict JSON (no NaN), with:
- `schema` `cryostack.lyra.calibration-contract.v1`;
- exactly `x_grid_marks` 8, `y_grid_marks` 4, `min_guidance_frames` 5, `time_grid_step_us` 2, `power_grid_step_db` 10, `adjacent_marks_required` true (types checked);
- `engine.file_sha256` pinning exactly the nine `codes/<name>.py` files, all matching on disk;
- `engine.identity` equal to `lyra_identity()` (source digest incl. digit templates, file count, OCR method);
- `selected_runner_name` `runner/lyra_runner.py`, and the configured runner must be exactly that file of the root, its SHA-256 equal to `selected_runner_sha256`.

Without a contract the step reports *not supported*; any mismatch reports *could not be verified*. Neither message carries paths or engine detail (the operator detail goes to the server log). The module hashes files only; it never reads or reports engine source.

**Deployment and rollback.**
- To enable 8 X / 4 Y calibration, the operator installs the Root-reviewed private engine directory (nine `codes/` files, `runner/lyra_runner.py`, `calibration-contract.json`), points both settings at it and restarts.
- Rollback: unset both settings (or point them at the previous engine) and restart.
- Existing guidance, drafts, calibrations and results are untouched in both directions. On the original engine browser calibration is refused (marks can still be made and saved), and uploaded two-line desktop files still calibrate.
- The public warning and drift list do not fix the original engine's main-bang refinement. The corrected engine is a separate Root-managed dependency.

**Main-bang drift review (2026-11-10).** `lyra_workflow.main_bang_drift` compares each current calibration row's `mb_x` with the person's `mb` mark (both frame-relative columns; LYRA's figures draw `guide_mb` and `MB t=0` on the same axis) and lists frames moved more than `MAIN_BANG_DRIFT_PX` = 20 as `main_bang_drift` in the workflow state; step 3 shows them before confirmation. It reports LYRA's values and never changes them. Black-box runs of the unchanged runner on `F125-C0822_C0834` (SHA-256 `2c5a1350…aa7f`, Angelo's picks `cdca2417…b688`) reproduce production exactly and show the move is LYRA's refinement, not CryoStack's coordinates: marks on the leading edge (729) give `mb_x` 821 (+92); the same marks 92 px to the left give 737; no M mark gives 722; grids, 8 X / 4 Y or no X do not change `mb_x`. `calibrate.py` exposes no option to anchor the main bang, so the remedy is a LYRA change (proposal in the 2026-11-10 report), not an adapter offset.

**Results.** Products `lyra-frame-index`, `lyra-calibration`, `lyra-run-echoes` (no positions: LYRA's navigation alignment needs reference files that are not part of the handoff) and `lyra-diagnostic` images (contact sheet, OCR diagnostic, per-frame calibration/echo/waveform/publication figures, bounded like URSA's). Each run replaces them all, so outputs a later run did not produce disappear. The frame table shows LYRA's values as written, with display-only flags: CBD inferred by LYRA's sequence constraint where the OCR read disagrees or is empty, main bang more than 100 px from the strip median, and LYRA's echo status other than `good`. Figure-to-frame keys follow `calibrate.py`'s `file_id` (`CBD<n>`, `CBD<n>_f<frame>` for duplicated CBDs, `fr<nn>` without a CBD).

**Validation (2026-10-14).** Phase 1 on real F127 film: reel `47_0004650_0004674` -- 14 frames, 12 complete, CBD 0551–0562; the 5 flagged frames are raw OCR misreads where the sequence agrees with the labels visible in LYRA's OCR diagnostic. Reel `47_0004800_0004824` (`F127-C0471_C0483`) -- LYRA assigns 0473–0484, but the film labels read 471–475, 478–484 (*film CBD* below): its sequence constraint assumes no skipped CBD numbers, so frames 1–5 are 2 too high. LYRA's rename log maps reel `47_0004650_0004674` to `F327-C0551_C0562`, while the film prints flight 127 and LYRA's handoff files it under F127; the flight attribution of that reel needs confirming. The frame index is byte-identical under numpy 1.26/pandas 2.2 and numpy 2.4/pandas 3.0.

**Native exact-file proof (2026-11-10).** On SPRI `F126-C0039_C0050.tiff` (SHA-256 `27baaa2b…3d130c`) all four phases ran unchanged in four control runs: original reel basename, a repeat (all three CSVs and all 50 PNGs byte-identical), the internal alias with the real flight and the internal alias with technical flight 999. Across runs every frame type, boundary, CBD, raw OCR reading, calibration value, echo status and thickness was exactly equal; the only CSV differences (`flight`, `tiff`, `tiff_id`, `file_id`) were each audited as the declared namespace substitution. PNG dimensions are equal; titles and diagnostic annotations differ only by the namespace labels and are kept as written. Resuming calibration and echoes from saved phases reproduced byte-identical CSVs; a same-size changed input and a missing input were refused before detection. Two reported real files reached human frame review in isolated QA workspaces, and on the public site phase 1 of `F125-C0120_C0131-S8781` completed (14 frames, 12 complete, CBD 0120–0131) and awaits human review. The fixture calibration pick was an existing integration fixture, so these runs prove that CryoStack executes LYRA faithfully and refuses mixed inputs; they are **not** scientific validation of LYRA's frames, calibration, echoes or thicknesses, which remain scientifically unvalidated and labelled so to reviewers.

## Automatic Picker (URSA)

URSA (`external/FrozenLegacies/Frozen Legacy Tools/Unsupervised Retrieval of Signal for A-scopes (U.R.S.A.)`) is the existing automatic A-scope processor. Frozen Legacies runs it unmodified:

- **Input:** one A-scope TIFF, read by URSA with OpenCV as 8-bit grayscale and CLAHE-enhanced; CBDs come from `C<start>_C<end>` in the file name, positions from a navigation CSV (`CBD,LAT,LON`, exact CBD match).
- **Processing:** sprocket-hole masking, A-scope frame detection, signal-trace extraction, grid and reference-line detection with calibration to µs and dB, transmitter-pulse (including double-pulse), surface and bed detection, ice thickness at 168 m/µs. Parameters come from URSA's `config/default_config.json`.
- **Outputs:** `<stem>_pick.csv` and `<stem>_pick.npz` (`Frame, CBD, LAT, LON, Surface_Time_us, Bed_Time_us, Ice_Thickness_m, Surface/Bed/Transmitter power and time ...`), `<stem>_frame_verification.png`, and `<stem>_frameNN_picked.png` per frame.
- **Requirements:** OpenCV, scikit-image (`functions/grid_detection.py`), NumPy, SciPy, pandas, matplotlib; minutes and 1–3 GB of memory per strip (URSA's documentation). PyQt5 is imported only by URSA's interactive viewers and is not needed.

`radar/automatic.py` checks availability (URSA sources present, the URSA Python importing its dependencies, and the health check `ursa_runner.py --check` importing URSA itself in the job environment), then runs `pickers/ursa_runner.py` in a subprocess with the TIFF presented under its original name (a link in a private work directory) and the asset's navigation. A job is recorded in `automatic.json` (`queued`, `running`, `completed`, `failed`, `cancelled`, or `interrupted` after a server restart) with a path-free log tail. Outputs are copied into `outputs/` and registered as `ursa-*` products; the work directory is removed. When URSA cannot run, the API returns `available: false` with the reason and no job is created.

URSA's picks are in µs, not in ASTRA's working-window pixels, so automatic results are not loaded into the ASTRA picker for correction.

**URSA environment.** URSA runs in its own Python environment, never the gateway's. `env/ursa-requirements.txt` pins the direct dependencies, `env/ursa-requirements.lock` the complete resolved set, and `env/build_ursa_env.sh [PREFIX]` builds it (default `~/.cryostack-envs/ursa`: CPython 3.11 from conda-forge, then the lock installed with `--no-deps`, `pip check`, and the health check). `opencv-python-headless` replaces the `opencv-python` of URSA's README (same `cv2`, no GUI libraries). The gateway is pointed at it with `CRYOSTACK_FROZEN_LEGACIES_URSA_PYTHON=<PREFIX>/bin/python`. The subprocess runs with `PYTHONNOUSERSITE=1`, so the service user's `~/.local` packages can neither satisfy nor shadow URSA's. Automatic mode is offered only while the health check passes; the check's interpreter and package versions (no paths) are returned as `availability.environment` and shown in the UI.

**Scientific status.** Operational availability is not validation. Every URSA result is `scientific_status: "unvalidated"` -- in the automatic API state, the job, each URSA product and its provenance, and the UI ("Scientifically unvalidated"). Review snapshots hold only ASTRA's products (`radar/review.py` `SNAPSHOT_PRODUCTS`, workflow `astra-manual`) and submission requires a completed manual session, so URSA output can never enter the review and publication workflow (`test_automatic_results_are_unvalidated_and_never_publishable`).

#### URSA validation on the F127 reference strip

Run on 2026-10-09 with the environment above (Python 3.11.17; OpenCV 4.10.0, scikit-image 0.24.0, NumPy 1.26.4, SciPy 1.13.1, pandas 2.2.3, matplotlib 3.9.2) on `Pickers/Ascope/tiff/F127-C0471_C0483.tiff` (37,943 × 2,400, 16-bit, 110.6 MB) with `Pickers/Ascope/nav/127.csv`, URSA's `default_config.json`, unmodified URSA sources.

| Check | Result |
|---|---|
| Output schema | `_pick.csv` with `Frame, CBD, LAT, LON, Surface_Time_us, Bed_Time_us, Ice_Thickness_m, Surface_Power_dB, Bed_Power_dB, Transmitter_Time_us, Transmitter_Power_dB, Transmitter_X_pixel, Noise_Floor_Time_us, Noise_Floor_Power_dB` (14 columns); `_pick.npz` with the same fields plus `meta`; 12 `_frameNN_picked.png`; `_frame_verification.png`. |
| Frames | 12 detected (URSA warns: 12 frames vs 13 CBDs in the file-name range). |
| Determinism | Two runs: CSV byte-identical, all 12 frame PNGs and the verification PNG byte-identical, every numeric NPZ array identical; only the NPZ `meta` timestamps differ. |
| Through the gateway | A real job (`AutomaticRunner`, real URSA environment) completed; its CSV is byte-identical to the direct run; 4 products registered (CSV, NPZ, verification image, frame ZIP), all labelled unvalidated; review submission refused (`409`). |
| Wall time / memory | 2 min 37 s and 2 min 42 s direct (8-core host shared with production, `nice 10`), 152 s through the gateway; peak RSS 1.23 GB. |
| Navigation mapping | LAT/LON of all 12 rows equal the navigation record of the row's CBD exactly (no interpolation). |
| CBD assignment | URSA assigns CBDs 471–482 in frame order from the file name. The CBDs printed on the film for these 12 frames are 471–475 and 478–484, so URSA's CBD agrees with the film for frames 1–5 only (5 of 12), off by 2 from frame 6 on -- the same limitation as ASTRA's row-order assignment (see *CBD assignment and the CBD printed on the film*). Automatic positions are therefore not verified. |
| Numerical behaviour | Frames 1–11: surface 9.02 ± 0.10 µs, bed 16.94 ± 0.16 µs, ice thickness 664.8 ± 14.6 m (647.6–699.3 m), transmitter pulse at x = 725–742 px of each frame. Frame 12: transmitter detected at x = 1301 px, thickness 1140.6 m -- an outlier that is most likely a transmitter misdetection, not checked further. Navigation thickness is `9999` (unavailable) for F127, so there is no independent thickness to compare with. |
| Agreement with ASTRA | **Not measured.** The only ASTRA outputs for F127 on this host come from scripted parity sessions with arbitrary click positions, not scientific picks, so no URSA–ASTRA agreement statistic can honestly be given. A comparison needs reviewed ASTRA picks on the same frames and an agreed frame correspondence (below). |
| Failure handling | Gateway Python (no OpenCV): unavailable, reason names `cv2`. Broken URSA install: unavailable ("URSA could not be imported"). Corrupt TIFF: URSA prints "Could not load image", runner exits 3, job fails "finished without producing picks". Timeout 20 s: job failed "URSA did not finish within 20 s", process killed. Concurrency 1: a second user's job stays `queued` while the first runs, and can be cancelled while queued. |

#### Frame 12 of F127: what the evidence shows

URSA's own frame-12 debug image and the CSV point the same way. The point marked *transmitter* is the strip's surface echo, the *surface* is the bed echo, and the *bed* lies in noise past the end of the film signal:

- Frame 12 "surface" time is 7.94 µs. That equals the bed − surface interval of frames 1–11 (16.94 − 9.02 = 7.92 µs).
- Frame 12 "transmitter" power is −11.3 dB, the surface-echo power of frame 11 (−11.3 dB), not a transmitter power (frames 1–11: −34.1 to −35.3 dB).
- The real transmitter pulse is visible at the left of the frame-12 crop, where frames 1–11 have it.

The frame-12 thickness (1140.6 m) is therefore not a measurement. URSA's output is not corrected; instead, the URSA picks summary flags any frame whose transmitter position or power departs from the strip median (more than 100 px or 10 dB; `products.ursa_frame_qc`). On F127 it flags frame 12 only. The flag is a display-only warning in the Automatic view and changes nothing in the CSV. Root-causing the misdetection inside URSA (frame-edge cropping vs. peak selection) is for URSA's maintainers.

The film labels printed in URSA's crops agree with the ASTRA finding under *film CBD* below: frame 11 reads **127 0483** and frame 12 **127 0484**, while URSA assigns 481 and 482 from the file-name range. URSA's CBDs, and the navigation positions looked up from them, are off by 2 from frame 6 onward (labels 471–475, 478–484). This is recorded, not corrected; the verified-label workflow stays the only route to a corrected position.

URSA writes `<stem>_frame_verification.png` to `output/` in its working directory, not to the output directory it is given; the job now moves it into the outputs, so the verification product is registered (it was silently missing before). URSA also writes its own diagnostic images: a picks plot per frame (`<stem>_frameNN_picked.png`) and, in `ref_line_qa/`, the reference-line QA images of each frame (`_01_search_region`, `_02_blackhat`, `_03_threshold_raw`, `_04_threshold_filtered`). Before the work area is removed, the job copies them into `outputs/` as `ursa-diagnostic` products (`<stem>_ursa_diag_frameNN_<what>.png`, product id `ursa-diag-fNN-<what>`), each with its frame, size and SHA-256 and the label *URSA diagnostic (unvalidated)*. Only regular PNG files whose names follow URSA's pattern are taken, from `out/`, `out/ref_line_qa/`, `output/` and `output/ref_line_qa/` of the work area; links (files or directories) are never followed, and the copy opens the file with `O_NOFOLLOW`. The set is bounded (`MAX_DIAGNOSTIC_FILES` 400, `MAX_DIAGNOSTIC_FILE_BYTES` 16 MB, `MAX_DIAGNOSTIC_TOTAL_BYTES` 128 MB; every frame's picks plot is taken before any reference-line image); what is skipped is counted in the provenance. F127 keeps 60 images, 24.3 MB. A new completed run replaces the previous run's diagnostics. They are served through the owner-scoped product routes (download and preview), are listed as one line in the Products panel, and appear per frame in the Automatic view.

The Automatic view's *Frame diagnostics* table (`GET assets/<id>/automatic` → `frames`, `automatic.frame_diagnostics`) shows, per frame, URSA's CSV values as text exactly as URSA wrote them, the `ursa_frame_qc` flags with their reasons, and buttons that open the frame's URSA diagnostic images (with size and SHA-256). The flags are heuristic consistency checks; nothing is corrected. On F127 the table flags frame 12 and its picks plot shows the transmitter misidentification described below.

A completed job records its provenance in `automatic.json` (`job.provenance`): URSA's commit when its source is a git checkout of its own (a source tree copied inside the CryoStack repository has none), `source_sha256` (a digest of URSA's `*.py` and `config/default_config.json`), `config_sha256` and the parsed parameters, the runner settings, the environment versions, name/size/SHA-256 of the input TIFF and navigation, the output hashes and every kept diagnostic image's hash. Each product of the run also carries `job_id`, `ursa_commit`, `ursa_source_sha256`, `config_sha256` and `input_sha256` in its provenance. Names and hashes only, never server paths.

The job lifecycle, availability check, product registration and isolation are also tested against a stand-in package exposing URSA's entry points (`tests/test_frozen_legacies_automatic.py`); `test_the_separate_ursa_environment_passes_the_health_check` runs the real health check where the environment exists. The URSA subprocess receives only a minimal environment (`ursa_environment()`), never the gateway's credentials.

**Planned workflow (not implemented):**

```text
URSA result ──► manual inspection in the picker ──► correction ──► submission ──► reviewed product
```

Loading URSA picks into the ASTRA picker for correction needs a conversion between URSA's per-frame times (µs) and ASTRA's working-window pixels, which is not implemented because it has not been verified. Missing requirements before it can be:

- **Reference runs:** URSA on agreed films with stored expected outputs (CSV, NPZ, frame images), run in the CryoStack URSA environment, to show the integration reproduces URSA.
- **Frame correspondence:** a verified mapping from URSA's detected frame index and its pixel columns to the ASTRA A-scope window (`window_x`) on the same TIFF.
- **Shared calibration:** URSA calibrates each frame automatically (grid and reference-line detection, sweep rate and dB scale from `config/default_config.json`); ASTRA uses the user's grid and reference-line clicks and the selected sweep rate. A tolerance-based comparison of URSA and ASTRA surface/bed times on the same frames, and agreement on which calibration is authoritative.
- **CBD per frame:** URSA also takes the CBD range from the file name, so its CBDs have the same limitation as ASTRA's; automatic results need the same film-label confirmation before their positions can be called verified.

## Products

`radar/products.py` is the product model of a radar asset. A product has a controlled `product_id`, `kind`, `title`, `type`, `producer` (`frozen-legacies` or `user`), `workflow` (`astra-manual`, `ursa-automatic`, `upload`, `radar-source`), `mime`, `bytes`, `created_at`, `provenance`, `summary`, and download/preview URLs. It is assembled from:

- the asset itself: `raw-radar` (downloadable for uploads; shared installation radar is listed but not downloadable) and `navigation`;
- ASTRA outputs discovered from `radar/manual.py` (`astra-csv`, `astra-qc`, with session provenance);
- `products.json` records: URSA outputs and user uploads, stored under `outputs/`.

Uploaded products are validated by kind: ASTRA CSV must have exactly ASTRA's columns; URSA and LYRA CSVs must have the columns their consumers read; numeric columns must parse; images are checked by signature, decoded header, dimensions (≤ 160 Mpx), and size (≤ 200 MB). Navigation uploads attach to an uploaded-radar asset only before picking starts and never replace existing navigation. An upload with no asset open creates a `products` asset with no radar metadata.

## Data Sources, Catalog and User Work

### Data flow

```text
Storage provider        external storage (authoritative); files are never copied into the catalog
      ↓  index (metadata only)
Radar catalog           SQLite index: data sources, radar files, index runs, per-user state
      ↓  open by catalog ID (reference, not copy)
Radar asset             the user's workspace asset referencing the catalog file
      ↓  working cache (in place for local files; bounded copy otherwise; LYRA: per-job staging copy)
Picker                  ASTRA / TERRA (manual) · LYRA (automatic; URSA legacy)
      ↓  every committed A-scope / saved result
Observation             structured record in the user's workspace (observations.json)
      ↓
Product                 ASTRA CSV / QC, TERRA CSV / figure, LYRA native outputs, uploads
      ↓
Map (My work) · Review · Download
```

Frozen Legacies keeps five things apart:

| Concept | What it is | Owner | Where |
|---|---|---|---|
| **Data source** | An external storage location holding radar files | Maintainers | `data_sources` table |
| **Dataset** | A scientific collection: metadata, capabilities, adapters | Maintainers (manifests) | `datasets/*.yaml` → `data/catalog.json` |
| **Radar asset** | One radar file: a shared catalog entry, referenced by a user's workspace asset | Entry: installation; workspace asset: the user | `radar_assets`; `users/<safe_id>/frozen_legacies/radar/<asset_id>/` |
| **Product** | A file derived from or attached to an asset | Its producer (user or workflow) | the asset's `outputs/` and `products.json` |
| **Observation** | A geolocated record shown on the map | Published: the dataset. Picked: the user | `data/observations.geojson`; the asset's `observations.json` |

### Storage providers

`radar/storage.py` defines `RadarStorageProvider`. Files are addressed by relative storage keys (`tiff/F127/F127-C0471_C0483.tiff`), which never leave the server.

| Method | Capability | Purpose |
|---|---|---|
| `list(prefix, suffixes)` | `list` | All objects under a prefix (providers page internally) |
| `stat(key)`, `exists(key)` | `stat` | Size, modification time, ETag; `version` = ETag or size+mtime |
| `open_stream(key)` | `stream` | The whole object as a stream |
| `read_range(key, offset, length)` | `range_read` | Part of an object; `RangeReader` makes it a seekable stream so TIFF headers are read without downloading the image |
| `check()`, `describe()` | -- | Connection test; non-sensitive description (location masked) |
| `local_file(key)` | `local_files` | The object is already a file on this server (used only by the working cache) |

`change_tracking` (changes since a token) is part of the vocabulary; no provider implements it yet. Application code checks capabilities, not provider names.

**Implemented:** `local` -- a directory on the server or a mounted archive inside an operator-approved root (`$CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS`, `:`-separated; with none set, nothing can be registered). It is the reference implementation of the contract.

**Implemented:** `s3` -- read-only Amazon S3 (or an operator-approved S3-compatible endpoint), described in *S3 data sources* below.

**Implemented:** `cedar` -- Georgia Tech CEDAR ("Cost-Effective Data Access for Research") research storage. CEDAR is campus network storage mounted on the server, not an object-storage API. Production uses the managed SMB proxy for immutable datasets; NFS remains supported by the provider but is not the active deployment. `CedarProvider` is `LocalProvider` (approved storage roots, path containment, files read in place) plus one rule: the directory must be on a mounted network filesystem (`nfs`, `nfs4`, `cifs`, `smb3`; from `/proc/self/mountinfo`). A local folder cannot pose as CEDAR, and an unmounted CEDAR path is reported as a failed connection instead of being indexed as empty. The datasets share is read-only to the application in steady state; a separately authorized operator copies only complete, manifest-verified immutable releases to it. Per-user workspaces are on the separate CEDAR users share (see *Storage layout*). The SQLite catalog, resumable intake sessions, the working cache and LYRA staging remain on local VM disk.

**Not implemented:** Google Drive, OneDrive/SharePoint, Dropbox. None can be used. `radar/storage.py` only reserves their names (`PLANNED_PROVIDERS = ("gdrive", "onedrive", "dropbox")`, not in `PROVIDERS`, so the Control Center refuses them; `PLANNED_REQUIREMENTS` lists what each needs and the Control Center shows it) and defines the rules a future provider must follow in `validate_drive_config`: a shared drive (`drive_id`) and folder (`folder_id` / `folder`), an operator allow-list (`CRYOSTACK_FROZEN_LEGACIES_GDRIVE_ALLOWED` / `CRYOSTACK_FROZEN_LEGACIES_ONEDRIVE_ALLOWED`), and no credentials or client settings in a data source. `GoogleDriveProvider` / `OneDriveProvider` are placeholders that refuse construction; no API client, credentials model or workload identity exists for them.

### S3 data sources

`radar/storage.py` `S3Provider` reads one bucket prefix (`s3://<bucket>/<prefix>`) with three S3 operations only:

| Operation | Used for |
|---|---|
| `ListObjectsV2` (paginated, 1,000 keys per page, under the prefix) | indexing; the connection test (`MaxKeys=1`) |
| `HeadObject` | metadata of one object (size, ETag, last modified) when a user opens a file |
| `GetObject` with `Range` | TIFF headers while indexing (a few KiB per file, never the image) |
| `GetObject` | the working copy streamed into the working cache when a user opens a file |

Keys outside the prefix, folder markers and hidden names are ignored. Nothing is ever written to S3.

**Configuration.** Two operator settings in the gateway's environment decide what maintainers may register:

| Variable | Meaning |
|---|---|
| `CRYOSTACK_FROZEN_LEGACIES_S3_ALLOWED` | Approved `bucket` or `bucket/prefix` entries (comma- or space-separated). A source's prefix must equal or lie below an approved prefix. With nothing set, no S3 source can be registered. |
| `CRYOSTACK_FROZEN_LEGACIES_S3_ENDPOINTS` | Optional approved S3-compatible endpoints, `name=https://host` (comma-separated). A source names one (`endpoint`); without it, AWS S3 is used. Path-style addressing is used for these endpoints. |

A maintainer then registers the source in the Control Center (**Frozen Legacies → Add a data source → Amazon S3**) or with `POST admin/sources`:

```json
{"source_id": "fl-archive", "name": "Frozen Legacies archive", "dataset_id": "frozen-legacies-ascope",
 "provider": "s3", "bucket": "example-radar-archive", "prefix": "frozen-legacies",
 "region": "us-east-1", "tiff_prefix": "tiff", "nav_template": "nav/{flight}.csv"}
```

The stored configuration is exactly `{bucket, prefix, region, endpoint, tiff_prefix, nav_template}`. A request carrying anything that looks like a credential (`secret`, `token`, `password`, `credential`, `session`, `access_key`, …) is refused, and the server re-validates the approvals every time it builds a provider, so removing an approval disables the source's use immediately.

**Credentials.** The server uses AWS *workload* credentials resolved by the AWS SDK's default credential chain -- in order of preference an IAM role attached to the workload (EC2 instance profile, ECS/EKS task role, IRSA/web identity), otherwise the standard environment variables or the service account's shared configuration. Frozen Legacies stores no AWS credentials anywhere: not in Git, manifests, workspaces, the SQLite catalog, browser responses, logs it writes, or products. A researcher's own AWS connection (the CryoStack Cloud "bring your own account" feature) is never used to read maintainer-managed archives. There is no installation-wide secret store; adding one is out of scope.

**Least-privilege IAM policy** for the gateway's role, read-only and limited to the approved prefix:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "ListApprovedPrefix", "Effect": "Allow", "Action": "s3:ListBucket",
     "Resource": "arn:aws:s3:::example-radar-archive",
     "Condition": {"StringLike": {"s3:prefix": ["frozen-legacies", "frozen-legacies/*"]}}},
    {"Sid": "ReadApprovedObjects", "Effect": "Allow", "Action": "s3:GetObject",
     "Resource": "arn:aws:s3:::example-radar-archive/frozen-legacies/*"}
  ]
}
```

`HeadObject` and ranged reads are covered by `s3:GetObject`. Without `s3:ListBucket`, S3 answers a missing object with 403 instead of 404; Frozen Legacies reports that as *access denied*, never as a deleted file. For an SSE-KMS bucket, add `kms:Decrypt` on the key. Grant no `Put*`/`Delete*` actions.

**Failure handling.** The SDK client uses standard retries (5 attempts, with backoff) and 10 s connect / 60 s read timeouts. Errors are mapped to clear, non-sensitive messages: missing object (404/`NoSuchKey`) → the file is no longer in the source; 403/`AccessDenied`/expired token → access denied (check IAM); 5xx/throttling/network errors → temporarily unavailable; no credentials → the server has no usable AWS credentials. During indexing an unreadable file becomes `unavailable` (retried by the next run) and a source that cannot be listed stops the run as `unavailable` without marking anything missing. An interrupted download is retried once and never leaves a partial working copy.

**Requirements.** `boto3` must be installed in the gateway's Python environment; it is imported only when an S3 source is used. The local and test setups do not need AWS: `tests/frozen_legacies_fake_s3.py` is a small S3-compatible HTTP server used through the real SDK with dummy credentials.

### Working cache

The pickers need random access. `radar/working_cache.py` materializes an object as a local file: in place for `local_files` providers (no copy), otherwise streamed into `var/frozen_legacies_cache/` (`$CRYOSTACK_FROZEN_LEGACIES_WORKING_CACHE`, size limit `$CRYOSTACK_FROZEN_LEGACIES_WORKING_CACHE_MB`, default 20 GB) as `<entry>/<original file name>`, where the entry is a digest of source, key and version. The original name is kept on purpose: ASTRA and URSA read flight and CBD range from it and ASTRA writes it into its CSV, so a working copy gives byte-identical products to the same file read in place. Copies are written to a temporary file, checked against the object's size and renamed (an interrupted download is retried once and leaves nothing); downloaded once under concurrency, also when several users open the same file; evicted least-recently-used except while leased -- manual ASTRA actions and URSA jobs hold a lease on their file. A file larger than the whole cache limit is refused before any download, and a copy is started only while the cache's file system keeps at least 512 MB free after it (`FREE_SPACE_RESERVE`); both give the user a clear message instead of filling the disk. The cache is disposable and is never a permanent copy: user workspaces only reference catalog files. Catalog files are resolved through it on every open (the catalog state is checked every time; storage round trips are reused for 30 s), so no code assumes a catalog file is permanently a local path.

### Workspace storage quotas

`radar/quota.py` and `storage_routes.py`. Each user's quota covers the persistent files of their whole workspace (`<workspace-root>/users/<safe-id>`): uploads, generated outputs and other applications' files. Usage is measured by walking that tree (each `(st_dev, st_ino)` once, so hard links are not double-counted; symbolic links, `*.part`, `.automatic-work`, `.cache` and `__pycache__` excluded), cached 30 s per user and invalidated after each chargeable request. External catalog radar and the shared working cache live outside workspaces and never count.

Settings (`default_quota_bytes` 2 GiB, `max_upload_bytes` ≤ the 200 MiB handler limit, `warn_percent` 80, `disk_warn_percent` 90) and per-user overrides are authoritative configuration in their own SQLite database (`$CRYOSTACK_FROZEN_LEGACIES_STORAGE_DB`, default `var/frozen_legacies_storage.db`; WAL, created on first use), not in the rebuildable catalog. Changes are written to the Control Center `access_audit_log`.

Enforcement is an aiohttp middleware (`make_quota_middleware`) in front of the chargeable routes (`CHARGEABLE`); the handlers only read the per-file limit (`server._upload_limit`). Check and reservation happen on the event-loop thread with no await between them, so parallel requests cannot jointly overshoot: each request reserves its declared `Content-Length` (required for uploads; aiohttp stops a body at it) until it finishes. Starting automatic picking needs `AUTOMATIC_RESERVE_BYTES` (160 MiB, the bound of an automatic run's outputs) free; the job then writes asynchronously, so a run started just under the quota can finish above it -- bounded by that size. **Contract for the automatic pickers:** `QuotaAccounts.usage(root, user_id)` / `reserve()` / `release()` are the API a picker should call before collecting large outputs if per-file finalization checks are wanted; the current runners are not modified. Users above their quota keep read, download and delete access; nothing is deleted automatically. The guard assumes one gateway process (as deployed); several processes would need the reservations in the database.

### Data-source visibility and removal

`data_sources.visibility` (`users` default, `maintainers`) is an additive column. Catalog search, summaries and segments exclude maintainers-only sources unless the caller is a maintainer (`include_restricted`), and `make_visibility_middleware` refuses opening a `cat-` key of such a source (`404`) for others; assets already in a workspace keep resolving. `RadarCatalog.remove_source` deletes the source row, its `radar_assets` rows and index runs in one transaction (refused while a run is active); user state, submissions and published observations are kept, and because catalog IDs are derived from source and key, re-registering the same source ID and indexing restores every ID. Storage is never touched.

### Radar catalog (SQLite)

- **Location and owner:** `var/frozen_legacies_catalog.db` (`$CRYOSTACK_FROZEN_LEGACIES_CATALOG`), created by the first maintainer action with mode `0640`, owned by the gateway's service user. `/var/*.db` is not version-controlled.
- **Mode:** WAL journal (concurrent readers alongside the single indexing writer), 30 s busy timeout, foreign keys on. Every catalog method is one transaction; the indexer commits in batches of 500 rows.
- **An index, not a store:** source files stay authoritative and irreplaceable scientific products are never kept only in the catalog. Rebuild by deleting the file, re-registering the sources (same IDs) and indexing: catalog IDs come out identical, so user work referencing them resolves again. Back up the file only to save re-indexing time.
- **Migrations:** `CREATE TABLE IF NOT EXISTS` plus additive `ALTER TABLE ADD COLUMN`, as in the auth database.

**Schema.**

- `data_sources(source_id PK, name, provider, dataset_id, config, status, created_at, updated_at, last_index_at, last_index_status, last_index_error, last_success_at, last_check_at, last_check_ok, last_check_message)` -- `config` is non-secret (for `local`: root, `tiff_prefix`, `nav_template`).
- `radar_assets(catalog_id PK, source_id FK, dataset_id, storage_key, filename, flight, flight_num, cbd_start, cbd_end, width, height, mode, bytes, mtime_ns, etag, nav_key, has_nav, status, error, duplicate, missing_since, moved_to, track, min_lat, max_lat, min_lon, max_lon, first_indexed_at, indexed_at)`, `UNIQUE(source_id, storage_key)`.
- `index_runs(run_id PK, source_id FK, started_at, finished_at, status, discovered, added, changed, unchanged, missing, invalid, unavailable, moved, full, allow_mass_missing, retry_invalid, requested_by, pid, heartbeat_at, cancel_requested, error)` -- `status` is `queued`, `running`, `completed`, `cancelled`, `interrupted`, `unavailable`, `needs_confirmation` or `failed`.
- `user_asset_state(owner, catalog_id, asset_id, manual, automatic, updated_at)`, `PK(owner, catalog_id)` -- a derived index of users' workspaces (`owner` is the workspace safe ID).
- `user_observations(owner, observation_id, asset_id, catalog_id, status, lon, lat, feature)`, `PK(owner, observation_id)` -- derived index of the users' picked observations.
- `submissions(submission_id PK, owner, submitter_user_id, asset_id, source_key, catalog_id, dataset_id, filename, flight, cbd_start, cbd_end, workflow, producer, producer_version, session_revision, completed_at, source_version, navigation, observation_count, positioned_count, products, note, status, submitted_at, reviewer_user_id, decided_at, decision_note, accepted_unverified, published_at, supersedes, superseded_by, withdrawn_at, withdrawn_by, withdraw_reason)` -- authoritative review records (back up with the snapshots).
- `published_observations(observation_id PK, submission_id FK, dataset_id, catalog_id, flight, cbd, lon, lat, feature)` -- the shared, reviewed product.
- Indexes: `(dataset_id, flight_num, flight, cbd_start, filename)` (ordering and dataset browsing), `(flight, cbd_start)`, `(status)`, `(filename)`, `(source_id, status)`, `(min_lat, max_lat)`, `index_runs(source_id, started_at)`, `user_asset_state(catalog_id)`.

**Identity.** `catalog_id = "cat-" + sha256(source_id + NUL + storage_key)[:24]`. Identical file names in different sources or folders are different assets (and are flagged `duplicate`); the ID does not depend on the file's content, so changes keep it.

### Indexing

`radar/indexer.py` lists the source and reads headers only for new or changed files (size, mtime, ETag); flight and CBD come from ASTRA's file-name parser, navigation from the source's `nav_template` (e.g. `nav/{flight}.csv`), and the file's track from the navigation records of its CBD range (exact records only -- files without navigation get no position).

| Case | Result |
|---|---|
| new | `indexed` (or `invalid` when not a usable TIFF) |
| unchanged | not read again |
| changed | re-read, same catalog ID |
| moved / renamed (same name, size, version) | new ID; old row `moved` with `moved_to`, which `resolve()` follows |
| read error this run | `unavailable`, retried next run |
| no longer listed | `missing` with `missing_since`; row and all user work kept; restored when it reappears |
| duplicate name | distinct assets, `duplicate` flag |

A source that cannot be listed, lists nothing while files are known, or would lose more than half its files in one run stops as `unavailable` or `needs_confirmation` and marks nothing missing; a maintainer confirms real removals (`allow_mass_missing`). A temporary outage therefore never looks like mass deletion.

For remote providers, header reads run in parallel (`header_concurrency`, 16 for S3) within each batch of 500 files; rows are committed per batch.

### Background indexing

Indexing never runs inside the gateway's request handling. The smallest reliable mechanism consistent with CryoStack's existing job handling (URSA jobs, Slurm submissions) is used: **one subprocess per run, with its state in the catalog database** -- no queue service, no new daemon.

```text
Control Center ── POST admin/sources/<id>/index ──► gateway
                                                     │ queue_run: index_runs row "queued"
                                                     │   (refused while the source has an active run)
                                                     │ spawn: python -m …frozen_legacies.radar.index_worker --catalog … --run N
                                                     ▼
                                            index worker process
                                                     │ claim_run: "running", pid
                                                     │ index_source(…) — progress after every batch (≤ 1/s)
                                                     │ heartbeat every 5 s (also during slow listing pages)
                                                     │ checks cancel_requested / SIGTERM
                                                     ▼
                                            finish_run: completed | cancelled | unavailable |
                                                        needs_confirmation | failed
```

- **One active run per source**, enforced by an `IMMEDIATE` transaction when the run is queued; a second request gets `409`.
- **Progress**: the listing (`GET admin/sources`) returns the active run (`progress`: counts so far, heartbeat, and the catalog's current file count as the best available estimate of the total). The Control Center refreshes every 3 s while a run is active.
- **Cancellation** (`POST …/cancel`): a queued run ends at once; a running worker stops after its current batch. Everything indexed so far is kept, nothing is marked missing, and the run ends `cancelled`.
- **Restart and crash recovery**: the worker runs in its own session, so restarting the gateway does not stop a healthy run; the new gateway process keeps showing it from the database. A run whose worker died (killed, crashed, host restart) is marked `interrupted` when its PID is gone or its heartbeat is older than 90 s -- checked when the gateway starts and on every maintainer listing. Interrupted runs mark nothing missing.
- **Retry**: indexing is incremental, so any new run continues from what is stored -- unchanged files are skipped, `unavailable` files are always re-read. **Retry failures** (`POST …/retry`) additionally re-reads files recorded as `invalid`.
- **Failures** are recorded on the run and on the source (`last_index_status`, `last_index_error`); the latest file-level problems are listed per source (file name, status, message -- never keys or paths). A worker that exits abnormally has its last output written to the gateway log.
- The worker reads only the data source and the catalog; it has no access to user workspaces.

Measured with the local S3-compatible test server through the real AWS SDK (`tests/test_frozen_legacies_s3.py::test_gateway_stays_responsive_while_a_worker_indexes`; set `FROZEN_LEGACIES_S3_BENCHMARK_N` for the size), while the test polled catalog search, the user summary and the maintainer listing:

| Remote objects | Worker indexing time | Gateway requests during indexing | p50 | p95 | max |
|---|---|---|---|---|---|
| 3,005 | 9.4 s | 432 | 5.0 ms | 8.1 ms | 15.8 ms |
| 100,005 | 296 s | 9,084 | 12.7 ms | 38.9 ms | 241 ms |

On real S3 the indexing time is dominated by one ranged request per new file (about 10--50 ms each from within the region, 16 in parallel), so a fresh 100,000-file index takes minutes; incremental runs are a listing only (100 pages).

### Search, pagination and progress

`GET radar/catalog` filters on the server (dataset, flight, index status, CBD, file name, and the user's processing state) and pages with LIMIT/OFFSET; the page size is capped at 100 and there is no "all". Progress per dataset and flight (`GET radar/catalog/summary`) and state filters come from `user_asset_state`, which the server updates when a manual session is saved or reset, an automatic job changes status, or an asset is removed, and reconciles with a user's workspace once per server process.

Measured with generated metadata (`tests/test_frozen_legacies_catalog_benchmark.py`):

| | 10,000 files | 100,000 files |
|---|---|---|
| index (fresh) | 1.5 s | 18.5 s (with allocation tracing) |
| incremental update (1% changed, 0.5% removed) | 0.09 s | 0.6 s |
| database | 4.5 MB | 45 MB |
| lookup by ID | 0.5 ms | 0.5 ms |
| first / middle / last page, unfiltered | 4 / 7 / 9 ms | 31 / 67 / 105 ms |
| flight filter, first / last page | 1.3 / 1.4 ms | 1.4 / 1.5 ms |
| CBD lookup in a flight | 0.9 ms | 0.8 ms |
| file-name substring search | 6 ms | 54 ms |
| my state "in progress" | -- | 1.4 ms |
| my state "unprocessed" (unfiltered) | 12 ms | 85 ms |
| summary with my progress (cached between catalog changes) | 1 ms | 1.3 ms |

SQLite remains appropriate at this scale. Unfiltered late pages and substring search grow linearly; browsing is scoped by dataset and flight, which stays in milliseconds. Keyset pagination or a full-text index are the next steps if unfiltered browsing of 100,000+ files becomes common.

### User observations and the map

Every Next A-scope, Done and Reset rewrites the asset's `observations.json` from the session, using ASTRA's own CSV construction, so the map, the CSV and the download agree. One record per committed A-scope (`<asset_id>-a<n>`); Done changes its status from `draft` to `completed` without duplicating it; Reset removes them. Each carries `scope: user`, `workflow`, `status`, `dataset_id`, `catalog_id`, pick provenance and `window_x` -- the picker window it was committed in, which **Open in Manual at this A-scope** returns to. Because ASTRA assigns CBDs by committed-row order, earlier observations move when more are committed. A LAT/LON outside the valid range (for example the raw `9999` marker) is kept but not mapped.

Map layers: the shared **published observations** (dataset build, including LYRA), the user's **My work** (`assets/user_layer.js`, owner-scoped `GET observations`), **Reviewed results** (`assets/published_layer.js`, `GET published/observations`, loaded for the visible map area only), and an optional **Radar coverage** layer (`GET radar/catalog/segments`) drawing catalog files that have real navigation tracks, for discovery. Selecting a coverage segment shows its dataset, flight, file-name CBD range, image size and the user's status (`GET radar/catalog?id=<catalog_id>`), and **Open radar** opens it in Manual. User picks are never written to `data/observations.geojson`.

**Where markers are drawn** (`observations.map_position`): at the verified position when the A-scope's CBD was confirmed against the film (see *CBD provenance and georeferencing*), nowhere when the frame label was unreadable or the confirmed CBD has no navigation, and otherwise at ASTRA's own position, labelled unverified. The record's ASTRA values (`cbd`, `lat`, `lon`) are never changed.

**Indexed My work.** `observations.json` stays authoritative; every write or removal also updates the user's rows in the catalog database's `user_observations` table (`observations.on_change`), and `GET observations` is answered by a bounded SQL query on `(owner, …)` with an optional bounding box -- no workspace scan per request. The index is reconciled from the owner workspace at read time, including current catalogue lineage and binding versions, and an asset's rows are removed with the asset. Installations without a catalog database fall back to reading the workspace.

**Native products and map binding (integrated source; joint release pending).** `radar/map_products.py` supplies the common `Binding` gate for `astra-manual`, `terra-manual` and `lyra-automatic`. It consumes committed TERRA CSVs through `committed_export` and completed LYRA frame-index/echo products with matching job/product hashes. It never runs a picker, recalculates values or rewrites native CSV/PNG. Native strings remain under `native_values`. Readable unlocated results remain counted/listed; invalid, uncommitted or tampered products are withheld.

The direct LYRA identity path requires a nonempty supported `source_identity`, actual positive flight agreeing with the exact source/catalogue binding, and consistent input identity. Missing/empty/null identity cannot reuse manifest flight. Reserved999, engine aliases, OCR prefixes and edited filenames are never actual-flight evidence.

**Implemented authoritative rebinding.** When direct identity is absent/unknown, `derived_lyra_identity` may consume `RadarCatalog.identity_binding(stored_catalog_id,input_sha256)` (`cryostack.derived-source-identity.v1`). The latest accepted transactional identity event must bind the same native input SHA/current catalogue version, canonical/source IDs, actual positive non999 flight and exact CBD range, with binding/evidence digests. Both native products must agree; a supplied producer identity must agree on input/asset/source/dataset, and a different known producer flight fails closed. Legacy absent/empty/null producer records can bind only through this proof. An edited catalogue flight alone is insufficient. TERRA native unknown FLT is not silently rebound by this LYRA-specific path.

Only derived display records acquire `cryostack.map-derived-identity-binding.v1`: actual flight/range, canonical/original/source catalogue IDs, input SHA, proof version/evidence/journal/method, and unchanged producer flight. Normal access, exact-CBD finite navigation, range, conflicting-nav and `map_eligibility` checks still apply. Without proof/navigation, results stay private and unlocated. Native files, job namespace and original provenance remain byte-unchanged.

Live bindings are disposable and reconciled at read time through catalogue redirects/current source metadata and navigation content hashes. The proof participates in the result version/fingerprint and is reverified at submission. A changed binding can produce a new private version; a frozen approved snapshot never moves. Every response rechecks current source access.

After saves, completion or review decisions, applied frontend callbacks dispatch `fl-map-products-changed` and the opaque cross-tab key `fl-map-products-change.v1`, including TERRA onSaved. My work/Reviewed results serialize requests with one trailing refresh, poll every45s only while enabled/visible, retain feature-ID selection/camera/toggles and remove stale points on access/fetch failure. These bridges are applied in source; loaded production adoption is a separate release check.

### CBD assignment and the CBD printed on the film (findings)

ASTRA is ported unchanged and its outputs stay byte-identical. While validating it against the development film F127 (`F127-C0471_C0483.tiff`), the CBD that ASTRA reports was compared with the CBD printed on each frame of the scan and with the navigation file.

**What ASTRA does.** The CBD range comes only from the file name (471--483). The window title counts `471 + (number of Next A-scope)`; the CSV assigns CBDs to the committed rows in order, spread over the range (`int(start + (end - start) · i / (n - 1))`); LAT/LON are the navigation record with exactly that CBD.

**What the film shows.** The strip has 12 complete frames (pitch about 3,000 px) plus an unlabelled partial frame at the left edge. The CBD labels printed on the frames read **471, 472, 473, 474, 475, 478, 479, 480, 481, 482, 483, 484**: CBDs 476 and 477 are not on this strip, and 484 is, although the file name says `C0471_C0483`.

**Consequences.**

- With one A-scope per frame, the title counter and the CSV both give 476--482 (483) for frames 6--12: **two CBDs lower than printed**, which with this flight's navigation spacing (1.96--2.48 km per CBD) puts those observations 4.1--4.4 km from the position of the printed CBD.
- When fewer A-scopes than frames are committed, row-order spreading moves CBDs further: three commits on frames 1--3 get CBDs 471, 477 and 483, i.e. 0, 11.0 and 21.5 km from the frames' true positions.
- The catalog's CBD range and coverage track inherit the file-name range (they include 476--477 and omit 484).

**Conclusion.** This is not a display, indexing or port error: the displayed title, the CSV and the catalog all follow ASTRA's model faithfully. The model's assumptions -- the file name gives a complete, consecutive CBD range, and committed rows map evenly onto it -- do not hold for this film. Nothing was changed: the CSV/QC algorithm, the CBD assignment and the geolocation are as in ASTRA.

**What the metadata provides.** Neither source carries a frame-to-CBD mapping. The radar TIFFs have only baseline TIFF tags (size, bit depth, compression, strips); there is no image description, time, frame or CBD tag. The navigation files are CBD-indexed records (`CBD,LAT,LON,THK,SRF`); for F127 they are complete and consecutive (CBDs 476 and 477 exist), with no relation to image columns. The only reliable evidence of an A-scope's CBD is the label printed on its film frame.

### CBD provenance and georeferencing

`radar/georef.py` (routes in `georef_routes.py`, panel in `assets/georef.js`) adds the missing mapping as **explicit, user-confirmed provenance**, without changing ASTRA:

- In the Manual result view, **Georeferencing — film CBD** lists every committed A-scope with ASTRA's CBD and position. **Show frame** displays the radar around the A-scope's window so the printed label can be read. The user then selects **Confirm** for the CBD read from the label, or **Unreadable**. Nothing is prefilled or inferred: CBDs are never assumed sequential and a missing label is never filled in.
- Confirmations are stored per asset in the user's workspace (`radar/<asset_id>/georef.json`). Each is bound to the A-scope number, its picker window (`window_x`) and the session it was made in (the session's creation time), so re-picking an A-scope or resetting the session never inherits an old confirmation. Writes are atomic; a linked `georef.json` is refused.
- Every observation is then described by separate fields. `cbd`, `lat`, `lon` and `position` stay exactly ASTRA's.

| Field | Meaning |
|---|---|
| `astra_cbd`, `astra_position` | ASTRA's CBD (file-name range spread by committed-row order) and its exact-CBD navigation position |
| `film_cbd`, `film_cbd_source` | the CBD read from the frame label (`user_reading`) |
| `verified_cbd`, `verified_position` | the confirmed CBD and the navigation record with exactly that CBD (ASTRA's own lookup; the `9999` marker is not a position) |
| `cbd_source` | `astra_row_order` or `film_label_confirmed` |
| `georef_method` | `astra_row_order_nav_exact` (unverified) or `film_label_nav_exact` (verified) |
| `geolocation_status` | `unverified`, `verified`, `verified_no_navigation` (confirmed, but the navigation has no position for that CBD) or `label_unreadable` |
| `cbd_differs` | the confirmed CBD differs from ASTRA's |

- Plausibility notes, never corrections, are shown to the user and reviewers: a confirmed CBD far outside the file name's range, a confirmed CBD without navigation, or confirmed CBDs that do not change monotonically along the image.
- **Separate, reproducible product:** `GET assets/<id>/georef/product` returns `<stem>_georef.csv` with ASTRA's and the verified CBD/position side by side, plus the georeferencing status, method and ASTRA's ice quantities. Its content is deterministic (no timestamps). `…/georef/provenance` records its SHA-256, the SHA-256 of the canonical ASTRA CSV, the navigation file and the confirmations, and the asset, catalog file, dataset and session revision; it contains no personal data. The canonical ASTRA CSV and QC, and the user's `observations.json`, are never modified.
- **Review and publication** (`radar/review.py`): a submission's immutable snapshot includes `georef/` (`georef.json`, the georeferenced CSV and its provenance), and its records carry the georeferencing fields. Approving a submission whose observations are not all `verified` needs an explicit reviewer flag (`accept_unverified_geolocation`). That acceptance is recorded, and such observations are published labelled as ASTRA-assigned and unverified. Inferred (ASTRA) positions are never presented as verified.

**Still open (needs scientific sign-off):** automatic frame-label detection (OCR or frame detection) to *prefill* readings for the user to confirm. A reviewer-side confirmation step for film CBDs. Whether the catalog's CBD range (from the file name) should be widened when confirmed labels fall outside it.

### LYRA

Two different things are called LYRA. The **supplied published LYRA dataset** (`*_echoes.csv` delivered with the collection) is read by its adapter into shared map observations, unchanged. **New LYRA jobs** run by users are private workspace products: they appear only in that user's My work (with an exact-CBD navigation position) and never write into the supplied dataset. ASTRA results are not LYRA: the repository has no code that derives LYRA quantities from ASTRA picks.

### Scientific review and publication

`radar/review.py` (routes in `review_routes.py`, user side in `assets/review.js`, Control Center page `/control/frozen-legacies/review`) implements the smallest reliable review workflow:

```text
draft ── Done ──► completed ── Submit ──► submitted ──► published ──► withdrawn
                     ▲                      │   │           └──► superseded (newer version published)
                     └────── returned ◄─────┘   └──► rejected
```

- **Submit (owner):** the integrated source accepts completed ASTRA sessions and eligible committed TERRA/LYRA results on shared radar (catalogue or registry), with an explicit workflow; uploaded radar stays private. The deployed c9 release includes this native submission support; actual public native-product approval/publication and two-tab lifecycle acceptance remain pending. One submission per asset can await review at a time, and an already-published version cannot be resubmitted unchanged. The owner can cancel a pending submission.
- **Immutable snapshot:** the server copies the canonical ASTRA CSV and QC image byte for byte (with SHA-256), the structured observations (with georeferencing fields when present), the session state, the georeferencing files (`georef/`), and `provenance.json` into `frozen_legacies_reviews/<submission_id>/` next to the catalog database (`$CRYOSTACK_FROZEN_LEGACIES_REVIEW_ROOT`), written to a temporary directory and renamed, files read-only. The user's workspace is never modified by a review; later edits, resets or deletions do not affect the snapshot.
- **Review (maintainer, admin, owner; never one's own submission):** the reviewer sees the snapshot's observations (ASTRA and verified CBD/position, geolocation status), the QC image (the radar strip with the submitted picks), the CSV, the navigation reference (file name, SHA-256, lookup method), the source file version and the submitter's note, and can open the same radar in Frozen Legacies (`/frozen-legacies/?open=<catalog_id>`). Decisions: **approve**, **return for correction** or **reject**, the last two with a reason the submitter sees. Approving observations that are not all `verified` requires the explicit `accept_unverified_geolocation` flag (the review page's checkbox), which is recorded. The observation table shows ASTRA's CBD, the confirmed film CBD and the **published** CBD and position side by side; rows where they differ are highlighted. When approval would supersede a published version, the page says so (`supersedes_on_approval` in the detail response, with that version's observation and verified counts).
- **Publication:** approval copies the snapshot's observations into `published_observations` -- an explicit, shared dataset product served by `GET published/observations` (bounded, by dataset, flight and bounding box), with downloads of the published CSV and provenance. It is never a view into a private workspace. Publishing a newer submission of the same user, radar file and workflow marks the older one `superseded` (with `supersedes` / `superseded_by`) and replaces its observations. **Withdrawal** (reviewers, with a reason) removes a result from the shared product; the snapshot and its history are kept.
- **Provenance** of each result: dataset, radar asset (catalog ID or source key, file name, source version), flight, CBD range (from the file name, as ASTRA), per-observation CBD (ASTRA and verified), processing method (`astra-manual`), producer and version (`astra.py` SHA-256), session revision and completion time, navigation reference, product identities and hashes, review state and times. Submitter and reviewer account IDs are stored only for authorization and audit; they are not part of published records, downloads or provenance files.
- **Progress:** `GET radar/catalog/summary` reports per flight `published` and `awaiting_review` (all users) and, in `mine`, `needs_review`, `returned` and `published`; `state=needs_review|returned|published` filters the catalog. All are indexed queries on `submissions` (indexed by status, owner, catalog ID), never workspace scans.

**Released behaviour.** Approval and publication are one transaction: approving a submission copies its snapshot observations into `published_observations` and marks it `published`; there is no separate publish step. The deployed review API accepts completed ASTRA sessions and eligible committed TERRA/LYRA results on shared radar, subject to the workflow, source-binding, snapshot-integrity and reviewer requirements below; uploaded radar stays private.

**Native workflows (deployed; public lifecycle acceptance pending).** The deployed release extends the same store and API to TERRA and LYRA: `GET assets/<id>/review?workflow=terra-manual|lyra-automatic|astra-manual` and `POST assets/<id>/review {"action":"submit","workflow":…}` (omitting `workflow` keeps ASTRA). Snapshot products are `terra-csv`, or `lyra-frame-index` + `lyra-run-echoes`, frozen with their hashes (a product that changes during submission is refused). Owner-only submission, reviewer roles, no self-review, snapshot integrity, explicit `accept_unverified_geolocation` for native CBD positions (never verified against film labels) and withdrawal are unchanged. Supersession is limited to the same owner, source-or-asset **and** workflow. Published products and points obey current source accessibility while historical snapshot bytes are kept. A later binding change makes the live result private and eligible for a new normal submission; it never moves published geometry. Save or completion never approves anything.

Not included: review of URSA results, reviewer edits of a submission (reviewers return it instead), and multi-reviewer sign-off.

### Snapshot integrity

Each snapshot carries `SNAPSHOT.json` with the SHA-256 of every file in it (CSV, QC, observations, session, georeferencing files, provenance). `ReviewStore.verify_snapshot` checks it, and the product hashes in the `submissions` row against it. Approval requires an intact snapshot whose observation count matches the submission record; a damaged, incomplete or missing snapshot is reported on the review page ("Snapshot integrity") and blocks a decision (`409`) -- nothing is published from it, and it stays awaiting review until it is restored. The reviewer detail never fails because of a missing snapshot; it shows what is missing.

A published result does not change after publication: its observations are copied into `published_observations` at approval, and its downloads come from the read-only snapshot. Tests (`tests/test_frozen_legacies_integrity.py`) confirm that editing or resetting the session afterwards, changing and re-indexing the source radar, the source being unavailable, and a restart leave the published records, CSV, QC and provenance byte-identical.

### Backup and recovery

The authoritative state is split between the SQLite catalog and files:

| Data | Where | If lost |
|---|---|---|
| Data-source configuration | catalog `data_sources` | re-enter |
| Radar file index | catalog `radar_assets`, `index_runs` | re-index the sources |
| Submissions and decisions | catalog `submissions` | **lost** |
| Published observations | catalog `published_observations` | re-derivable from the snapshots, but only with their `submissions` rows |
| Review snapshots | `frozen_legacies_reviews/<id>/` | **lost** |
| Sessions, picks, products, georeferencing | user workspaces `users/<id>/frozen_legacies/` | **lost** -- back up `users/` |
| My work and progress indexes | catalog `user_observations`, `user_asset_state` | rebuilt from the workspaces automatically |

Neither SQLite nor the snapshot folder alone is a backup: a submission row without its snapshot cannot be reviewed or downloaded, and a snapshot without its row is unreachable. `radar/backup.py` copies them together and consistently:

```bash
# as the gateway's service user; the gateway may keep running
python -m icesee_jupyter_book.applications.frozen_legacies.radar.backup create --out /backups/frozen-legacies
python -m icesee_jupyter_book.applications.frozen_legacies.radar.backup verify /backups/frozen-legacies/frozen-legacies-<UTC time>
```

`create` takes a consistent copy of the live catalog with SQLite's online backup API, then copies every snapshot that copy references (snapshots are immutable and written before their row is committed, so each referenced snapshot is complete), verifies the copy (SQLite integrity check, snapshot hashes, published observations belonging to published submissions) and writes `MANIFEST.json` with the hash of every file and the table counts. It exits non-zero and lists the problem when anything is missing or damaged -- for example a snapshot missing on the server. `verify` re-checks a backup against its manifest and itself.

Restore (GUI services stopped):

```bash
deployment/services.sh stop-gui
python -m icesee_jupyter_book.applications.frozen_legacies.radar.backup restore /backups/frozen-legacies/frozen-legacies-<UTC time>   # --force to replace existing data
deployment/services.sh start-gui
```

`restore` refuses a backup that does not verify, refuses to replace existing data without `--force`, and then moves the existing catalog (with its `-wal`/`-shm` files) and review store aside (`*.pre-restore-<time>`) instead of deleting them. After the restart, My picks and progress indexes are rebuilt from the workspaces on first use.

Back up user workspaces (`users/`, the gateway's workspace root) at the same time, with the installation's normal file backup. Schedule `create` (for example daily) with retention managed by the backup system; backups contain account IDs of submitters and reviewers, so keep them as private as the catalog (directories `0750`, catalog `0640`).

### End-to-end validation on the original F127 film

The whole path was exercised with the original F127 TIFF and navigation through the real gateway code, from a local source and from an S3 copy (a local S3-compatible server), with one A-scope per printed frame and the unmodified ASTRA running the same actions:

- The CSV and QC from the gateway are byte-identical to the unmodified ASTRA's, and identical between the local and S3 sources.
- ASTRA assigns CBDs 471--481 and 483 to the 12 frames; the labels read 471--475, 478--484. With the labels confirmed, every verified position equals the navigation record of the printed CBD; ASTRA's positions are 4.11--4.35 km away for frames 6--11 and 2.21 km for frame 12.
- Confirming CBDs does not change the ASTRA CSV; the georeferenced product is reproducible byte for byte; an unreadable label removes the observation from the map; My picks are drawn at the verified positions.
- A fully verified submission is approved without the unverified flag; the published records carry the printed CBD, the navigation position and ASTRA's CBD alongside, and contain no account data. The LYRA dataset files are unchanged.

In a real browser (headless Chrome for Testing, desktop and phone sizes) the map, catalog, Manual picking with calibration clicks, resume by deep link, film-CBD confirmation with the frame preview (the printed label "127 0478" is legible for the frame ASTRA calls 476), submission, the reviewer page, approval, the published layer for another user, supersession, withdrawal and the Automatic mode were exercised without page errors.

### Ready-product ingestion at scale (design; not implemented)

A maintainer registers a data source whose layout or manifest states the relationships (for example `tiff/{flight}/{name}.tiff`, `astra/{flight}/{name}.csv`, `qc/{flight}/{name}_QC.png`, `nav/{flight}.csv`). The indexer then associates a product with a radar file only through those declared rules -- the same flight and the same TIFF stem in the declared folders, validated by the product's schema (exact ASTRA columns, image signatures) -- never by vague name similarity, and records the products as installation (published) products of the catalog file. No archive extraction is involved.

Navigation-only flights deliberately show empty product slots for the source
TIFF, radargram/echogram, digitized radar data, and automatic output. Those
slots are UI contracts, not catalog objects. They must not acquire identifiers,
URLs, checksums, dimensions, or measurements until verified files are indexed.

## Security

- Every route requires a CryoStack session: the page and its files redirect anonymous users to sign-in; the API answers `401`.
- Identity comes only from the gateway session (`request["cryostack_user"]`); asset IDs, product IDs, and source keys are validated before any filesystem access.
- All paths resolve (following links) inside the user's `frozen_legacies/` directory; links out of it, linked outputs directories, and linked product files are refused.
- State-changing requests from another origin are refused (`403`).
- Downloads use fixed product IDs and sanitized `Content-Disposition` names; there is no generic file route. Responses never contain server paths.
- Session, job, and product manifests are written atomically; uploads are streamed with size limits and removed on any failure.
- Data-source management requires a Control Center `maintainer`/`admin`/`owner` role checked against the role store on every request, plus same-origin checks on every change.
- Review: only the owner can submit or cancel their result (another user's asset or submission answers `404`); only reviewer roles can list, inspect and decide submissions (`403` otherwise), and never their own (`403`); unpublished snapshots are not downloadable from the public routes (`404`); users cannot publish directly or change the shared product. Submission IDs are validated (`sub-` + 24 hex) before any file access, and snapshot files resolve only inside the review store.
- Data sources are read-only and limited by operator approvals (storage roots; S3 bucket/prefix and endpoint allowlists) that are re-checked whenever a provider is built. S3 uses the server's workload credentials (IAM role or default chain) and least-privilege read-only IAM; source configurations never contain credentials, and none appear in the catalog, responses, workspaces or products. A 403 is never treated as a deleted file.
- Users reach catalog files only by catalog ID through the working cache; storage keys, bucket paths and endpoint URLs are never returned to users. Picks made on catalog files stay in the user's workspace (`scope: user`) and are never published automatically.

## Tests

`tests/` covers authentication and workspace isolation, ingestion, rendering, shared sources, the radar, manual, product, and automatic APIs, the frontend structure (with Node unit tests for `radar_geometry.js`), and ASTRA parity. `tests/frozen_legacies_astra_reference.py` executes the unmodified ASTRA functions headlessly; parity tests require byte-identical CSV and QC output. Automatic-job tests run the real runner against a stand-in package with URSA's entry points, because URSA itself needs OpenCV. `tests/test_frozen_legacies_catalog.py` covers the provider contract, working cache, indexing cases and catalog APIs; `tests/test_frozen_legacies_s3.py` covers S3 sources (configuration approvals, credential rejection, pagination, ranged reads, missing vs denied vs unavailable, interrupted transfers), the background worker (progress, cancellation, a killed worker, restart recovery, retry), and the S3 → working cache → Manual ASTRA → My picks → product path with byte parity against a local source. They run without AWS. `tests/test_frozen_legacies_review.py` covers resuming a session after signing in again, the indexed My picks (owner isolation, bounding box, removal), submission, authorization, approval with explicit acceptance of unverified geolocation, return, rejection, supersession, cancellation, withdrawal, publication without personal data, the immutability of the snapshot and of the canonical ASTRA CSV, review progress in the catalog, and the frontend wiring.

## Extension Points

- **Another dataset:** add a manifest (with `capabilities`) and, if needed, an adapter; rebuild with `build_geojson`.
- **Shared radar for a dataset:** add a registry entry with `dataset_id` and `flight` or `observation_tiff`; the Dataset Explorer then offers **Open radar** for those observations.
- **Another product kind:** add it to `KINDS` (and `UPLOAD_KINDS` validation if users may upload it) in `radar/products.py`, and to `DEFAULT_UPLOAD_KINDS` in `products.js`.
- **Another picker:** add a module under `pickers/`, a job or session module under `radar/`, and register its outputs as products with their own `workflow`.

See the [API Reference](api_reference) for every endpoint.

## Storage layout

| Data | Where | Lifetime |
|---|---|---|
| Original radar archive (TIFFs, navigation) | GT CEDAR datasets share (SMB/CIFS), registered as `cedar` data sources inside `CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS` | authoritative and immutable to the application; never renamed unless a validated naming policy is explicitly enabled by an operator (see *Scanner film identity and naming*) |
| Per-user workspaces (sessions, picks, products, uploads, LYRA/TERRA results) | GT CEDAR users share (SMB/CIFS), `CRYOSTACK_WORKSPACE_ROOT` | persistent; counted against the user's quota |
| Working cache of catalogue files | local VM disk (`var/frozen_legacies_cache/` or `$CRYOSTACK_FROZEN_LEGACIES_WORKING_CACHE`) | transient and bounded (size limit, free-space reserve, LRU with leases) |
| LYRA job staging | local VM disk (`$CRYOSTACK_DATA_ROOT/cache/frozen_legacies_lyra_staging`) | transient, one owner-locked directory per job, removed on every exit path |
| Catalogue, storage settings, review store | local VM disk (SQLite; `frozen_legacies_reviews/`) | persistent; back up with `radar/backup.py` |
| Scanner evidence/journals | admitted durable CEDAR identity namespace; scratch/model work stays local XFS | persistent evidence, bounded disposable scratch |

Users never supply arbitrary filesystem paths: readers use admitted catalogue IDs or supported legacy registry references through CryoStack (direct mounted reads where supported, working cache or staging copy as required) and workspace files only through the owner-scoped `FrozenLegaciesWorkspace` (`workspace.py`); no route trusts an arbitrary path. Products in the workspace keep the original display identity and provenance. Scanner journals and identity metadata locations are listed in *Scanner film identity and naming*. Keep the 8GiB free-space reserve; Scanner also requires its 2GiB startup margin and per-worker headroom. Do not relocate storage, lower guards or clean another task’s files to admit a run. CEDAR persistence is not a claim that every native reader works directly there.

## Scanner film identity and naming

**Integrated in source; global naming policy absent/OFF.** The public v3 reader, legacy loader and typed-intake bridges are now applied in source, not proof of loaded adoption. No real archive rename/pilot is claimed. Root's complete reader inventory, actual runtime heartbeats, filesystem/no-replace acceptance and separately authorized pilot remain prerequisites. The source-only `scanner_naming.md` supplement is outside the book TOC; the operative public contract is summarized here.

Identity targets `F<actual-flight>-C<actual-start>_C<actual-end>-S<source-id>.tiff`, retaining printed CBD order (including descending Z-scopes). Existing RadarFilm IDs require exact acquisition-receipt bytes/scope; names such as `F123-C0120_C0131-S8781.tiff` illustrate syntax, not that segment's identity. Where no upstream ID is proven, a persistent exclusive internal content/source namespace may supply a distinctly recorded internal ID; it never claims RadarFilm provenance or proves Flight/CBD. Placeholder flight/CBD, equal TIFF size, inferred sequences and technical engine aliases are not evidence. S8781 metadata corroborates125/120–131; S2138 remains unknown, not flight1111.

**Verified metadata before OCR.** The existing coordinator performs bounded official metadata queries (exact segment match, ≤32rows/64KiB, ≤5s/call, max4calls/job), with immutable cache claims, one-hour positive cache and bounded failure backoff. Only an original stitched-object HEAD is permitted; no TIFF download. Actual local SHA must match the acquisition receipt, with matching scope/year, ID, reel/frame endpoints, path and object ETag/length/generation where pinned. Current nonempty revision, junk/review flags and conflicts are checked. Opaque ETag and JSON response SHA are not TIFF SHA. A fully verified already-correct identity can skip naming OCR (`reader_executions:0`); a changed name is a proposal, not metadata-only autonomous renaming. Conflicting/missing evidence goes to existing caption readers/review. Prior bounded live probes were unavailable, so real service verification remains an activation gate.

Autonomous reader rules require≥99% fit and held-out precision with≥30 held-out cases. Both endpoints must be observed; caption-only unqualified rules remain disabled. Four prior real CPU pilots yielded one dry-run rename candidate, one unchanged source and two review cases; no archive-wide result is claimed. Naming review never approves science.

**Trusted permission/reason contract.** `auth.principal` supplies existing project roles/capabilities. Source-admitted ordinary/student reviewers with `scanner.review` may propose a reviewed basename; a parent/path change additionally needs trusted developer/maintainer/admin/owner plus `app.develop` and `scanner.review`. File/workspace ownership or client role flags confer none. Retry requires `scanner.administer`; global/source configuration keeps its distinct authority. Targets stay in an existing admitted same-root/source-prefix directory, with no symlink/traversal/cross-root move. The source ID is immutable. UI/API require **Reason for this change *** (identity8–500 trimmed characters; film/position/segment/settings minimum4, caption8). CLI configure/apply/rollback also require the actual human reason; automated audit reasons are explicitly system-generated rules/evidence, not fabricated human decisions.

**Movement, recovery and leases.** Only `renameat2(RENAME_NOREPLACE)` may move an archive input; collisions/unsupported capability fail closed, with no placeholder/hardlink workaround. Policy/config/live adoption are rechecked after full hashing immediately before every physical forward/rollback/recovery move. Descriptor/path identity, source stability and planned sidecar hashes remain checked. `commit_identity_move` transactionally records row/redirect, TIFF/NAV aliases and exact-SHA evidence; the registry loader resolves committed TIFF and NAV aliases before existence checks, including reload/rollback. Native products and published snapshots remain immutable.

`source_guards` retains actual request, blocking executor, FileResponse open-file/close, queued job and native child lifetimes. Automatic jobs acquire independent resolved TIFF+NAV scopes **before enqueue**, including legacy keys; disconnect, cancellation, a returned response or kill request does not prove real reader exit. The runtime adoption digest pins actual loaded functions, not a declared constant. The protocol is `source-read-lifetimes.v2` and inventory schema is `cryostack.source-reader-inventory.v2`, with an explicitly pinned complete inventory and fresh≤30s PID/start/runtime heartbeats.

An optional operator `pilot_scope` guard now restricts mutation to one exact file/path/SHA and target basename, dataset/scope and hash-pinned single-entry journal, with an expiring writer-bound nonce, and suppresses automatic naming scheduling while present. It does not activate naming or solve shared cross-catalogue leases; naming remains OFF until the existing shared-reader, actual dataset no-replace and protected pilot/rollback gates pass.

**Per-database constraint:** leases and adoption live in the configured local catalogue SQLite DB. Review and production DBs can reference the same CEDAR TIFF while holding independent lease tables. A complete inventory rejects missing adoption in the applying DB, but omitted overlapping readers are not automatically discovered. Root must account for or quiesce all such readers before activation; copying heartbeat rows does not create shared coordination. This is not a global lock service. Keep naming OFF until these live gates and the real dataset pilot pass.

Journals/events/claims/receipts live under the admitted durable identity namespace; uncertain interrupted state blocks for evidence-checked recovery. Do not manually rename/delete a disputed source/target. Recovery/rollback uses the same exact hashes, no-replace, sidecar/config/adoption fences and genuine human reason. Preserve journal IDs and root-reviewed policy/inventory/receipt digests for support; frozen publication history and original logs remain intact.

## Development Principles

When extending Frozen Legacies:

- Keep dataset-specific parsing inside adapters.
- Keep dataset configuration inside manifests.
- Keep map behavior inside `map.js`.
- Keep visual styles inside `styles.js`.
- Keep data loading and indexing inside `data.js`.
- Keep interface interactions inside `ui.js`.
- Keep `frozen_legacies.js` focused on application orchestration.
- Avoid hardcoding dataset identifiers in the frontend.
- Prefer capability and metadata discovery over special-case logic.
- Reuse shared CryoStack authentication, documentation, and deployment components.

## Supplied corrected measurements and TERRA

The October 26, 2026 source manifests are maintained in
`datasets/corrected-20261026/`. They deliberately live below a separate directory:
the legacy top-level LYRA registry remains available for rollback. Each manifest
pins the original CSV SHA-256 and selects the `corrected-product` adapter.
Never combine both LYRA manifests in one registry: they share the dataset ID.

The supplier-designated final thickness field used for ingestion is
`h_ice_firn_corrected_m`; that selection is not scientific validation.
For LYRA, its base is `fixed_h_ice`, not raw `h_ice_m`. A missing final value
stays missing. Correction availability, original base values, source QC and
original row coordinates remain in observation properties. The supplied products
are not independently validated. Cross-workflow coordinates are retained exactly
as supplied but are not independently verified or harmonized; do not align or
average them without reference navigation. A source fingerprint proves file
identity, not scientific accuracy.

To reproduce collections without overwriting live data, use a fresh **CEDAR
staging directory**, after verifying that the datasets share is mounted:

```bash
python -m icesee_jupyter_book.applications.frozen_legacies.build_geojson \
  --manifests-dir icesee_jupyter_book/applications/frozen_legacies/datasets/corrected-20261026 \
  --output-dir /srv/cryostack/workspace/datasets/frozen-legacies/measurements/REPLACE_WITH_FRESH_STAGING_DIRECTORY --compact
```

The `--compact` option omits formatting whitespace without changing records or provenance.
The explicit output option refuses existing collections or a release manifest.
It does not publish, activate or overwrite a measurement release. The no-argument
command retains the legacy build behavior and must not be used to replace a live
release. Preserve the original CSVs and supplier README.

`measurement_releases.py` serves one content-addressed five-file snapshot,
including the existing Antarctica reference resources. Configure
`CRYOSTACK_FROZEN_LEGACIES_RELEASE_ROOT` and
`CRYOSTACK_FROZEN_LEGACIES_RELEASE_ID` together. The ID is the SHA-256 of the exact
manifest bytes. Validate the complete snapshot with `ReleaseStore` before changing
startup selection. A browser fetches the descriptor once and pins all collection
URLs to that version. Missing or modified configured data fails closed, without
silently loading legacy measurements. Old complete releases remain rollback
candidates. Do not edit files inside a published release directory.

TERRA is the operator-guided **Z-scope** workflow; ASTRA is the **A-scope** workflow
and LYRA is the automatic **A-scope** workflow. TERRA numerical code is distributed
privately and never belongs in public assets or this documentation. The public
`terra_routes.py` calls the private worker in a separate OpenCV-capable runtime.
Keep the private source and integration outside the published payload, and retain
the pinned original source fingerprint. Public-only installations can start
without the optional numerical runtime; attempting a new TERRA trace then reports
that the runtime is unavailable.

TERRA browser sessions are owner-scoped and revision checked. The original TIFF
coordinates, explicit CBD markers, disconnected anchor groups and average adjacent
calpip spacing feed the supplied native numerical methods. No calpip calibration
means missing thickness. Newly generated TERRA exports are **not firn corrected**;
the separately supplied corrected CSV is a distinct product. Immutable generated
CSV filenames bind revision and content hash, and only the committed session
pointer exposes a product. Product lists and ZIP indexes preserve the unvalidated,
non-firn status. A failed state write may retain quota-accounted output but cannot
replace the prior export or prevent an exact retry.

### Private nearest-file calpip references

`terra_calpips.py` stores owner-private `cryostack.terra.calpip-evidence.v1` observations in the workspace, keyed by asset/stable catalogue source, exact TIFF SHA/version, verified flight evidence and source/image/crop compatibility. States are confirmed/absent/not-checked; cadence/catalogue hints are candidates only. The nearest compatible completed native grid is chosen by interval CBD distance and stable ID tie break; unknown/F0 flights never pool and another owner's calibration is inaccessible. Current application force-rehashes the reference and validates it server-side. Absence/new input invalidates an older grid. A genuine prior session can be adopted only with exact input hash and committed intact native export/figure.

`GET/POST assets/<id>/terra/references` offers discovery/observations and calibration-only saving. The request contains action, input SHA and (for calibration) four row picks/end bound; client spacing/distance is rejected. The existing unchanged native worker's `action=calpip` calculates the grid without tracing B. `calpip_from` accepts an owner reference ID, revalidates it and forwards only native-computed spacing/lines to the same trace worker. No alternative math/constants or caller calibration values are introduced by this layer.

`assets/terra_picker.js` holds A's exact state object while visiting B; return restores anchors, CBDs, trace, session revision, current draft and film/examination view. Cancel/error/stale input never silently overwrites A. Four picks enable an explicit Calculate, then spacing/lines are visible before Continue saves the native reference and returns. Calibration-only records do not call scientific onSaved/publication. The chosen source/provenance and change/retry/manual/defer paths remain visible. The normal bound-first four-pick workflow is unchanged. TERRA native output remains non-firn-corrected and operator-guided/unverified.

Keep bulk workspace data and shared measurement snapshots on CEDAR. Database,
locking and coordination state remain on the VM's local filesystem. A release
rollout must preserve runtime environment privately, check for active notebook
kernels/jobs, signal only the intended gateway and retain exact rollback files.
Do not stop unrelated Voila or Scanner services. Automated API/component acceptance
does not establish visual browser validation or independent scientific validation.

## Next Steps

Return to the [User Manual](user_manual) for the scientific-user workflow.

Use [Getting Started](getting_started) for a shorter introduction to the application.

Return to <a href="/frozen-legacies/">Frozen Legacies</a> to inspect the current deployment.

:::{raw} html
  </div>
</div>
:::
