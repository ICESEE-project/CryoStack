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

The architecture is being kept storage-independent so that other backends can be added later. (Radar files for the picker workspace already come from local/mounted directories or read-only Amazon S3; see *Data Sources, Catalog and User Work* below.)

Possible future backends include:

- Georgia Tech CIDAR,
- HTTPS resources,
- and other remote scientific data services.

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

Frozen Legacies documentation is built through the same CryoStack Jupyter Book process used by the other applications.

This preserves:

- common CryoStack styling,
- navigation,
- account integration,
- documentation sidebars,
- search,
- and page structure.

The application documentation should therefore use the shared CryoStack documentation classes rather than defining a Frozen Legacies-specific documentation theme.

## Validation Status

- **Validated:** authentication and workspace isolation; the explorer; the radar viewer; the ASTRA manual picker (byte-identical CSV and QC against the unmodified ASTRA script, plus committed goldens in `tests/astra_golden.json` derived from it, so CI checks parity without the script); product downloads.
- **Implemented, not validated with real URSA:** Automatic (see below).
- **Configuration-dependent:** shared radar sources (`radar_sources` registry).

The browser's ASTRA display (trace opacity, the Show trace toggle, panel layout) is presentation only; the ASTRA computations, click mapping and outputs are server-side and unchanged. Product previews are bounded derivatives (block minimum for grayscale, so thin dark marks survive); the stored products are never modified.

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

**Configuration.** `CRYOSTACK_FROZEN_LEGACIES_LYRA_ROOT` (directory holding `codes/`; default `Pickers/Automatic_picker/LYRA`), `CRYOSTACK_FROZEN_LEGACIES_LYRA_PYTHON` (default: the gateway's Python; dependencies in `env/lyra-requirements.txt`), `CRYOSTACK_FROZEN_LEGACIES_LYRA_RENAME_LOGS` (extra rename-log directory; `<LYRA root>/rename_logs` is always read), `CRYOSTACK_FROZEN_LEGACIES_LYRA_TIMEOUT` (30–86,400 seconds, default 3600). `CRYOSTACK_FROZEN_LEGACIES_URSA_CONCURRENCY` limits automatic jobs of both pickers together (1–4, default 1); invalid or unsafe values fall back to the default and are logged. A LYRA phase-1 run on a 117 MB strip peaks near 2.6 GB. Each asset also holds an advisory OS lease while its job runs, preventing duplicate work across gateway workers; the lease is released automatically if a worker exits.

**Runner.** `pickers/lyra_runner.py` runs LYRA unmodified, as its guide does, from a private copy of `codes/` (LYRA writes next to its own source) with the TIFF linked under its canonical name in `tiff/<flight>/`: `detect_frames.py --method segment` (phase 1), then -- only with an uploaded `lyra-guidance` file -- `calibrate.py` (phase 3) and `echoes.py` (phase 4). LYRA's phase 2 is its interactive desktop picker; phase 3 refuses to run without a human −60 dB reference pick, and CryoStack never supplies one. The runner writes `lyra-run.json` (phases, exit codes, where it stopped, outputs). It runs in its own process group (Cancel stops the group) and stops LYRA when the server that started it dies, so a killed gateway leaves no LYRA running for a job it later reports as interrupted. `--check` is the health check: it imports `lyra`, `segment_ocr` and `build_digit_templates` and reports package versions.

**Canonical name.** LYRA needs `<reel>_<start>_<end>-reel_begin_end.tiff`. It is taken from the file name (with the asset's recorded flight) or from a LYRA rename log whose entry for the file agrees with the asset's flight; conflicting or ambiguous logs make LYRA unavailable for that asset with the reason. Nothing is guessed. The catalog derives flights only from `F<flight>-C…` names, so archive files under their reel names need a flight recorded (radar sources `flight:`) before LYRA can run.

**Results.** Products `lyra-frame-index`, `lyra-calibration`, `lyra-run-echoes` (no positions: LYRA's navigation alignment needs reference files that are not part of the handoff) and `lyra-diagnostic` images (contact sheet, OCR diagnostic, per-frame calibration/echo/waveform/publication figures, bounded like URSA's). Each run replaces them all, so outputs a later run did not produce disappear. The frame table shows LYRA's values as written, with display-only flags: CBD inferred by LYRA's sequence constraint where the OCR read disagrees or is empty, main bang more than 100 px from the strip median, and LYRA's echo status other than `good`. Figure-to-frame keys follow `calibrate.py`'s `file_id` (`CBD<n>`, `CBD<n>_f<frame>` for duplicated CBDs, `fr<nn>` without a CBD).

**Validation (2026-10-14).** Phase 1 on real F127 film: reel `47_0004650_0004674` -- 14 frames, 12 complete, CBD 0551–0562; the 5 flagged frames are raw OCR misreads where the sequence agrees with the labels visible in LYRA's OCR diagnostic. Reel `47_0004800_0004824` (`F127-C0471_C0483`) -- LYRA assigns 0473–0484, but the film labels read 471–475, 478–484 (*film CBD* below): its sequence constraint assumes no skipped CBD numbers, so frames 1–5 are 2 too high. LYRA's rename log maps reel `47_0004650_0004674` to `F327-C0551_C0562`, while the film prints flight 127 and LYRA's handoff files it under F127; the flight attribution of that reel needs confirming. The frame index is byte-identical under numpy 1.26/pandas 2.2 and numpy 2.4/pandas 3.0. Phases 3–4 have not run on real data: no human calibration picks exist in the handoff or anywhere on the server. LYRA's results are scientifically unvalidated and never eligible for review or publication.

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
      ↓  working cache (in place for local files; bounded copy otherwise)
Picker                  Manual (ASTRA) / Automatic (URSA)
      ↓  every committed A-scope
Observation             structured record in the user's workspace (observations.json)
      ↓
Product                 ASTRA CSV / QC (canonical, downloadable), URSA outputs, uploads
      ↓
Map (My picks) · Review · Download
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

**Implemented:** `cedar` -- Georgia Tech CEDAR ("Cost-Effective Data Access for Research") research storage. CEDAR is campus network storage mounted on the server, not an object-storage API. Production uses the managed SMB proxy for immutable datasets; NFS remains supported by the provider but is not the active deployment. `CedarProvider` is `LocalProvider` (approved storage roots, path containment, files read in place) plus one rule: the directory must be on a mounted network filesystem (`nfs`, `nfs4`, `cifs`, `smb3`; from `/proc/self/mountinfo`). A local folder cannot pose as CEDAR, and an unmounted CEDAR path is reported as a failed connection instead of being indexed as empty. The application CEDAR mount is read-only in steady state. The SQLite catalog, resumable intake sessions, and private workspaces remain on local durable XFS; a separately authorized operator copies only complete, manifest-verified immutable releases to CEDAR.

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

Map layers: the shared **published observations** (dataset build, including LYRA), the user's **My picks** (`assets/user_layer.js`, owner-scoped `GET observations`), **Reviewed results** (`assets/published_layer.js`, `GET published/observations`, loaded for the visible map area only), and an optional **Radar coverage** layer (`GET radar/catalog/segments`) drawing catalog files that have real navigation tracks, for discovery. Selecting a coverage segment shows its dataset, flight, file-name CBD range, image size and the user's status (`GET radar/catalog?id=<catalog_id>`), and **Open radar** opens it in Manual. User picks are never written to `data/observations.geojson`.

**Where markers are drawn** (`observations.map_position`): at the verified position when the A-scope's CBD was confirmed against the film (see *CBD provenance and georeferencing*), nowhere when the frame label was unreadable or the confirmed CBD has no navigation, and otherwise at ASTRA's own position, labelled unverified. The record's ASTRA values (`cbd`, `lat`, `lon`) are never changed.

**Indexed My picks.** `observations.json` stays authoritative; every write or removal also updates the user's rows in the catalog database's `user_observations` table (`observations.on_change`), and `GET observations` is answered by a bounded SQL query on `(owner, …)` with an optional bounding box -- no workspace scan per request. The index is rebuilt from the user's workspace once per server process (work done before it existed), and an asset's rows are removed with the asset. Installations without a catalog database fall back to reading the workspace.

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

LYRA `*_echoes.csv` is an existing derived, published product, read by its adapter into shared map observations. The manual workflow is radar → ASTRA → ASTRA result → structured draft observations → My picks. ASTRA results are not LYRA: the repository has no code that derives LYRA quantities (attenuation, reflectivity, temperature, bed SNR) from ASTRA picks, and if that processing exists it remains a separate stage after ASTRA.

### Scientific review and publication

`radar/review.py` (routes in `review_routes.py`, user side in `assets/review.js`, Control Center page `/control/frozen-legacies/review`) implements the smallest reliable review workflow:

```text
draft ── Done ──► completed ── Submit ──► submitted ──► published ──► withdrawn
                     ▲                      │   │           └──► superseded (newer version published)
                     └────── returned ◄─────┘   └──► rejected
```

- **Submit (owner):** only a *completed* manual (ASTRA) session on *shared* radar (catalog or registry file) can be submitted; uploaded radar is private. One submission per asset can await review at a time, and an already-published version cannot be resubmitted unchanged. The owner can cancel a pending submission.
- **Immutable snapshot:** the server copies the canonical ASTRA CSV and QC image byte for byte (with SHA-256), the structured observations (with georeferencing fields when present), the session state, the georeferencing files (`georef/`), and `provenance.json` into `frozen_legacies_reviews/<submission_id>/` next to the catalog database (`$CRYOSTACK_FROZEN_LEGACIES_REVIEW_ROOT`), written to a temporary directory and renamed, files read-only. The user's workspace is never modified by a review; later edits, resets or deletions do not affect the snapshot.
- **Review (maintainer, admin, owner; never one's own submission):** the reviewer sees the snapshot's observations (ASTRA and verified CBD/position, geolocation status), the QC image (the radar strip with the submitted picks), the CSV, the navigation reference (file name, SHA-256, lookup method), the source file version and the submitter's note, and can open the same radar in Frozen Legacies (`/frozen-legacies/?open=<catalog_id>`). Decisions: **approve**, **return for correction** or **reject**, the last two with a reason the submitter sees. Approving observations that are not all `verified` requires the explicit `accept_unverified_geolocation` flag (the review page's checkbox), which is recorded. The observation table shows ASTRA's CBD, the confirmed film CBD and the **published** CBD and position side by side; rows where they differ are highlighted. When approval would supersede a published version, the page says so (`supersedes_on_approval` in the detail response, with that version's observation and verified counts).
- **Publication:** approval copies the snapshot's observations into `published_observations` -- an explicit, shared dataset product served by `GET published/observations` (bounded, by dataset, flight and bounding box), with downloads of the published CSV and provenance. It is never a view into a private workspace. Publishing a newer submission of the same user and radar file marks the older one `superseded` (with `supersedes` / `superseded_by`) and replaces its observations. **Withdrawal** (reviewers, with a reason) removes a result from the shared product; the snapshot and its history are kept.
- **Provenance** of each result: dataset, radar asset (catalog ID or source key, file name, source version), flight, CBD range (from the file name, as ASTRA), per-observation CBD (ASTRA and verified), processing method (`astra-manual`), producer and version (`astra.py` SHA-256), session revision and completion time, navigation reference, product identities and hashes, review state and times. Submitter and reviewer account IDs are stored only for authorization and audit; they are not part of published records, downloads or provenance files.
- **Progress:** `GET radar/catalog/summary` reports per flight `published` and `awaiting_review` (all users) and, in `mine`, `needs_review`, `returned` and `published`; `state=needs_review|returned|published` filters the catalog. All are indexed queries on `submissions` (indexed by status, owner, catalog ID), never workspace scans.

Not included: review of automatic (URSA) results (see *Automatic Picker*), reviewer edits of a submission (reviewers return it instead), and multi-reviewer sign-off.

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
| My picks and progress indexes | catalog `user_observations`, `user_asset_state` | rebuilt from the workspaces automatically |

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

## Future Storage Integration

Future radar imagery and derived products are expected to be stored outside the current local observation metadata.

The storage abstraction is intended to support systems such as Georgia Tech CIDAR while keeping the frontend independent of the storage provider.

The intended flow is:

```text
Observation
    ↓
Product Metadata
    ↓
Storage Resolver
    ↓
CIDAR / Local / Remote Storage
    ↓
Frontend
```

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

## Next Steps

Return to the [User Manual](user_manual) for the scientific-user workflow.

Use [Getting Started](getting_started) for a shorter introduction to the application.

Return to <a href="/frozen-legacies/">Frozen Legacies</a> to inspect the current deployment.

:::{raw} html
  </div>
</div>
:::
