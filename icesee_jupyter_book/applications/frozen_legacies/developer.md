# Frozen Legacies Developer Guide

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

The application contains the data-ingestion framework, generated frontend data, interactive map, and documentation.

A representative structure is:

```text
frozen_legacies/
├── adapters/
├── assets/
├── data/
├── datasets/
├── build_antarctica.py
├── build_geojson.py
├── dataset_registry.py
├── index.html
├── getting_started.md
├── user_manual.md
└── developer.md
```

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

The architecture is being kept storage-independent so that other backends can be added later.

Possible future backends include:

- Georgia Tech CIDAR,
- object storage,
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

The entry point should remain orchestration-focused rather than accumulating map, styling, or data-processing logic.

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

For application-only changes:

```bash
./update_gui.sh frozen-legacies
```

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

Return to the [User Manual](user_manual.html) for the scientific-user workflow.

Use [Getting Started](getting_started.html) for a shorter introduction to the application.

Return to [Frozen Legacies](/frozen-legacies/) to inspect the current deployment.

:::{raw} html
  </div>
</div>
:::