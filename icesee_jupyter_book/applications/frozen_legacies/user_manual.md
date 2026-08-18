# Frozen Legacies User Manual

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

    <h1>Frozen Legacies User Manual</h1>

    <p>
      Explore registered Antarctic radar datasets, navigate survey flights,
      inspect individual observations, and review associated geophysical
      quantities and scientific products.
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
        href="developer.html"
      >
        Developer Guide
      </a>

    </div>

  </section>

  <div class="cryostack-app-doc-content">
:::

Frozen Legacies is the historical airborne radar exploration application within CryoStack. It provides a common interface for browsing Antarctic radar collections while preserving the scientific context, provenance, and products associated with each observation.

The application follows a simple hierarchy:

```text
Dataset
   ↓
Flight
   ↓
Observation
   ↓
Scientific Products
```

This manual describes the main interface and the expected workflow for scientific users.

## Application Layout

Frozen Legacies contains two primary working areas:

1. **Antarctic map** — displays survey tracks and observation locations.
2. **Dataset Explorer** — provides controls for selecting datasets and flights and displays the selected observation record.

A CryoStack navigation bar at the top provides access to the application, documentation, and account controls.

## Antarctic Map

The map presents the available radar observations in an Antarctic Polar Stereographic view.

The map is intended to provide spatial context for airborne radar campaigns and their individual records.

Depending on the available data, the map may display:

- Antarctic coastline and reference geometry,
- survey flight tracks,
- observation points,
- the South Pole,
- and selected-flight highlighting.

### Zooming

Use the **+** and **−** controls to zoom in and out.

### Panning

Click and drag the map to move across the Antarctic domain.

### Initial View

When the application is opened or the current flight selection is reset, the map returns to a broad Antarctic view.

## Dataset Selection

Use the **Dataset** selector to choose the collection you want to explore.

The selected dataset controls:

- available flights,
- visible survey tracks,
- visible observations,
- dataset metadata,
- and associated products.

The current deployment includes the **Frozen Legacies LYRA Radar Observations** collection.

Select **All datasets** when you want to display all currently registered collections.

## Flight Selection

The **Flight** selector lists the survey flights associated with the current dataset.

When a flight is selected:

- its survey track is emphasized,
- unrelated tracks are de-emphasized,
- observation points are filtered to that flight,
- and the map moves to the selected survey region.

Select **All flights** to restore the broader dataset view.

## Flight Tracks

Flight tracks represent the spatial path of the airborne radar survey.

Frozen Legacies generates these tracks from the georeferenced observation records.

Where discontinuities occur between survey passes, the generated track is split into separate segments rather than connecting distant observations with an artificial straight line.

## Observation Points

Observation markers represent individual georeferenced radar records.

Click an observation marker to display its information in the Dataset Explorer.

The exact metadata and scientific quantities shown depend on the selected dataset.

## Observation Status

Observation markers may be colored according to the quality or availability of the radar return.

For the current LYRA-derived dataset, statuses may include:

- **Good** — a usable bed return was identified.
- **Weak bed** — a bed return was detected but has lower confidence or signal quality.
- **No bed** — no reliable bed return was identified.

The selected observation panel also displays the corresponding status.

## Selected Observation

When an observation is selected, the Dataset Explorer expands to show the associated record.

The information may include:

- observation identifier,
- dataset,
- flight,
- CBD value,
- frame number,
- latitude,
- longitude,
- echo status,
- source file,
- and available scientific quantities.

Not every dataset is required to provide every field.

## Location

Frozen Legacies displays the geographic location of the selected observation.

The interface reports:

- latitude,
- longitude,
- and the location of the marker on the Antarctic map.

Source observations are typically stored using geographic coordinates and transformed into the Antarctic map projection for display.

## LYRA-Derived Quantities

For the current LYRA collection, an observation may include quantities such as:

### Ice Thickness

Estimated ice thickness at the observation location.

Displayed in meters when available.

### Bed SNR

The signal-to-noise ratio associated with the bed return.

Displayed in decibels.

### Surface Temperature

The estimated surface temperature associated with the observation.

Displayed in degrees Celsius.

### Reflectivity

The estimated radar reflectivity associated with the bed return.

Displayed in decibels when available.

### Attenuation

An attenuation-related quantity derived from the radar signal.

Displayed in decibels where available.

### Specularity

A quantity describing characteristics of the radar return associated with bed roughness or scattering behavior.

Not every observation contains all derived quantities.

## Dataset Information

The selected record also retains information about the parent dataset.

This may include:

- collection title,
- dataset identifier,
- campaign,
- institution,
- product family,
- version,
- coordinate system,
- citation,
- and DOI.

The available metadata depend on the dataset manifest.

## Observation Provenance

Frozen Legacies preserves provenance information so that displayed records can be traced back to their original sources.

Typical provenance fields include:

- dataset identifier,
- source file,
- flight,
- frame,
- and original observation identifier.

This information is important when matching the web visualization to the source scientific data.

## Radar Preview

The Dataset Explorer contains a radar preview area for the selected observation.

When an image product is associated with the record, it can be displayed here.

Until imagery is available, Frozen Legacies shows a placeholder while keeping the remainder of the observation information accessible.

## Scientific Products

Frozen Legacies uses a product framework that allows datasets to associate additional scientific files with observations.

A product may represent:

- a radargram,
- a processed echogram,
- an image,
- a source data record,
- a derived radar quantity,
- or another scientific file.

Available products are determined by the active dataset.

## Radargrams

A radargram may be associated with an observation through the dataset manifest.

When available, the radargram can be displayed in the observation panel or opened as an associated product.

## Processed Echograms

Processed echograms may also be associated with an observation.

The exact naming convention and storage location are dataset dependent.

## Downloads

Frozen Legacies supports downloadable products when the selected dataset exposes them.

Possible downloads include:

- source CSV records,
- observation data,
- observation GeoJSON,
- flight GeoJSON,
- radar imagery,
- processed echograms,
- and future scientific data products.

Not every dataset is required to support downloads.

## Dataset-Specific Products

The product system is intentionally dataset-aware.

One collection may expose:

```text
Radargram
Processed Echogram
Source CSV
```

while another may expose:

```text
Radargram
Bed Picks
NetCDF
GeoTIFF
```

The frontend can adapt to the products declared by the selected dataset.

## Current LYRA Dataset

The current registered collection is:

**Frozen Legacies LYRA Radar Observations**

Campaign
: Frozen Legacies

Institution
: Georgia Institute of Technology

Product family
: LYRA

Source coordinate system
: EPSG:4326

The collection contains restored Antarctic airborne radar observations and associated LYRA-derived quantities.

## Account Menu

Frozen Legacies uses the shared CryoStack account control.

When authenticated, the account menu may provide access to:

- My Account,
- Saved Configurations,
- My Experiments,
- and Sign Out.

Account services are shared across CryoStack applications.

## Typical Exploration Workflow

A normal session may follow these steps:

1. Open Frozen Legacies.
2. Select a dataset.
3. Select a flight or retain **All flights**.
4. Explore the survey geometry on the map.
5. Click an observation marker.
6. Review the observation status.
7. Inspect location information.
8. Review the available derived quantities.
9. Check dataset and provenance information.
10. Open available radar imagery or scientific products.
11. Download available products when required.

## Working with Multiple Datasets

Frozen Legacies is designed to support more than one radar collection.

When additional datasets are registered:

- they appear automatically in the Dataset selector,
- their flights become available in the Flight selector,
- their observations are loaded into the map,
- and their metadata and product definitions become available to the interface.

The core map interface does not need to be rewritten for each new dataset.

## Missing Values

A dash or missing field generally means that the corresponding value is not available for that observation.

This is expected when datasets contain different combinations of metadata and derived products.

## Missing Imagery

Observation metadata and radar imagery are managed separately.

An observation can therefore be available in Frozen Legacies even when its corresponding image product has not yet been added to the active storage backend.

## Troubleshooting

### No observations are visible

Check that:

- a dataset is registered,
- generated GeoJSON files are available,
- the dataset selector is set correctly,
- and the browser can access the Frozen Legacies data endpoint.

### A flight is missing

Confirm that the source dataset contains valid observations for that flight and that the generated flight geometry was successfully produced.

### An observation cannot be selected

Zoom closer to the observation points and try again.

### Radar imagery does not appear

The selected observation may not yet have an associated image product.

### Dataset metadata look incomplete

Some manifest fields are optional and may not yet be defined for the active dataset.

## Next Steps

For a shorter workflow introduction, return to [Getting Started](getting_started.html).

Developers extending the application with new datasets, adapters, scientific products, or storage backends should continue to the [Developer Guide](developer.html).

:::{raw} html
  </div>
</div>
:::