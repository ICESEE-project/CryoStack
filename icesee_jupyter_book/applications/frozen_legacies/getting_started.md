# Getting Started

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

    <h1>Getting Started with Frozen Legacies</h1>

    <p>
      Explore restored Antarctic airborne radar observations,
      survey flight tracks, and LYRA-derived geophysical products
      through the CryoStack platform.
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
        href="user_manual.html"
      >
        User Manual
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

Frozen Legacies is the historical airborne radar exploration application within CryoStack. It provides a map-based interface for browsing registered Antarctic radar datasets, selecting survey flights, inspecting individual observations, and reviewing associated geophysical quantities.

The application is organized around a simple hierarchy:

```text
Dataset
   ↓
Flight
   ↓
Observation
```

This guide introduces the standard workflow for opening Frozen Legacies, selecting a dataset, exploring flights, and inspecting radar observations.

## Before You Begin

To use Frozen Legacies, you need:

- A modern web browser.
- Access to the CryoStack platform.
- At least one Frozen Legacies dataset registered in the deployment.
- Network access to any external data or image storage required by the selected dataset.

The currently registered dataset contains restored Antarctic airborne radar observations and LYRA-derived quantities.

## Open Frozen Legacies

Open:

[https://cryostack.eas.gatech.edu/frozen-legacies/](https://cryostack.eas.gatech.edu/frozen-legacies/)

The Frozen Legacies interface is organized into two principal areas:

1. **Antarctic map** — displays survey flight tracks and georeferenced radar observations.
2. **Dataset Explorer** — provides dataset and flight controls and displays information for the selected observation.

Above them, **Map**, **Manual**, and **Automatic** switch the main area between the Antarctic map and the radar workspace, where you can open raw radar imagery or upload your own radar TIFF. Returning to **Map** keeps your current selection. **Manual** is the ASTRA A-scope picker; **Automatic** runs the URSA automatic picker where the server supports it (its results are scientifically unvalidated and cannot be submitted for review).

The navigation bar at the top provides access to:

- Frozen Legacies,
- Getting Started,
- User Manual,
- Developer Guide,
- and your CryoStack account.

## Explore the Antarctic Map

The main application area displays Antarctica using an Antarctic Polar Stereographic map.

The map provides spatial context for:

- airborne survey tracks,
- radar observation locations,
- the South Pole,
- and available geographic reference features.

Use the map controls to zoom in and out.

You can also pan across the map to inspect other regions.

## Select a Dataset

Use the **Dataset** menu in the Dataset Explorer to choose a registered radar collection.

Selecting a dataset updates:

- the available flight list,
- the displayed flight tracks,
- the visible radar observations,
- and the associated dataset metadata.

The current release includes:

**Frozen Legacies LYRA Radar Observations**

Additional datasets can be incorporated through the Frozen Legacies dataset registry.

## Select a Flight

Use the **Flight** menu to choose a survey flight.

When a flight is selected:

- the selected flight track is emphasized,
- unrelated flight tracks are de-emphasized,
- observations are filtered to the selected flight,
- and the map moves to the selected survey area.

Select **All flights** to return to the complete dataset view.

## Inspect an Observation

Click an observation point on the Antarctic map.

The Dataset Explorer will display the available record information.

Depending on the dataset, the selected observation may include:

- observation identifier,
- dataset,
- flight number,
- CBD value,
- frame number,
- latitude,
- longitude,
- echo status,
- ice thickness,
- bed signal-to-noise ratio,
- surface temperature,
- reflectivity,
- attenuation,
- specularity,
- source-file provenance,
- and associated scientific products.

## Observation Status

Observation markers may use different colors to indicate the quality of the radar return.

For the current LYRA-derived observations, statuses may include:

- **Good** — a usable bed return was identified.
- **Weak bed** — the bed return is present but weak.
- **No bed** — no reliable bed return was identified.

The selected observation panel reports the corresponding status.

## Review Dataset Metadata

When an observation is selected, the Dataset Explorer also exposes information about the parent dataset.

This may include:

- collection title,
- dataset identifier,
- campaign,
- institution,
- product family,
- source information,
- and future citation or DOI metadata.

This keeps the observation connected to its scientific provenance.

## Review LYRA-Derived Quantities

The current LYRA dataset may provide derived quantities including:

- ice thickness,
- bed SNR,
- surface temperature,
- reflectivity,
- attenuation,
- and specularity.

These values are displayed when available for the selected observation.

Not every dataset is required to provide the same quantities.

## Radar Preview

The observation panel includes a radar preview area.

When radar imagery becomes available for an observation, the corresponding radar product can be displayed directly in this section.

Until imagery is available, Frozen Legacies displays a placeholder while preserving the rest of the observation metadata.

## RIGGS Reference Stations

When the optional **RIGGS reference stations** layer is available, its points
are independent historical context rather than Frozen Legacies manual or
automatic picks. Select a station to see its measurement method, thickness,
source, and scientific status. If its citation is still pending, both the map
legend and station details label it provisional and not publication eligible;
it does not validate LYRA or any other picker output.

## Scientific Products

Frozen Legacies is designed to associate scientific products directly with observations.

A dataset may expose products such as:

- radargrams,
- processed echograms,
- source CSV records,
- derived radar products,
- image products,
- and future scientific data formats.

Available products depend on the dataset manifest and storage backend.

## Downloads

Datasets that declare downloads offer them under **Dataset downloads** in the Dataset Explorer (for the LYRA collection: observations and flight tracks as GeoJSON). Products of your own radar work are downloaded from the **Products** list.

## Dataset Provenance

Each observation retains provenance information connecting it to its original source.

This may include:

- source file,
- flight,
- frame,
- dataset identifier,
- and campaign metadata.

This information is useful when tracing a displayed radar record back to the original processed dataset.

## Current Dataset

The current Frozen Legacies deployment includes the **Frozen Legacies LYRA Radar Observations** collection.

It contains restored Antarctic airborne radar observations and LYRA-derived geophysical quantities.

The frontend itself is dataset-independent. Additional radar collections can be registered without rewriting the core map interface.

## Typical Workflow

A typical Frozen Legacies session follows these steps:

1. Open Frozen Legacies.
2. Select a dataset.
3. Choose a flight or retain **All flights**.
4. Explore the survey area on the Antarctic map.
5. Click an observation marker.
6. Review the observation status.
7. Inspect geographic and LYRA-derived quantities.
8. Review the source provenance.
9. Open raw radar in **Manual** or **Automatic**, or upload your own.
10. Download products from the **Products** list or **Dataset downloads**.

## Open or Upload Radar

1. Select **Manual** (or **Automatic**).
2. In **Radar asset**, open radar from **External datasets** (search by file name when the installation has data sources), or select **Upload raw radar** to add a radar TIFF (with its navigation CSV) to your workspace. Uploads count toward your workspace storage (2 GiB by default), shown beside the upload buttons.
3. If you already have processed results (ASTRA or URSA picks, QC images, echograms), select **Upload processed product** instead — you do not need to pick again.

## Pick a Radar TIFF Manually

1. Select **Manual** and choose a radar asset.
2. Calibrate as in ASTRA: **Set Up X Axis Reference Line**, **Set Up Y Axis Reference Line**, **Set Up Y Axis** (four grid lines), the **Sweep Rate**, then **Set Up X Axis** (four grid lines).
3. Pick **Surface**, **Bed**, **Noise Floor**, and **Main Bang** by selecting the feature and clicking the plot; picks snap to the red trace. **No Surface** / **No Bed** record absent reflections, and **Suggest Picks** proposes picks for you to check.
4. Select **Next A-scope** to save the A-scope and continue along the strip.
5. Select **Done** when the TIFF is finished, then download the CSV and QC image.

Your session is saved as you work; you can leave and continue later.

## Pick Automatically

Select **Automatic** and **Run automatic picking** to run URSA on the open radar asset. If this server cannot run URSA, Automatic tells you why and nothing is run. When the job finishes, its picks and QC images appear in the **Products** list, labelled *scientifically unvalidated*.

## Map Reset

Selecting **All flights** returns the application to the broader Antarctic dataset view.

Selecting an individual flight automatically focuses the map on the corresponding survey geometry.

## Authentication

Frozen Legacies requires a CryoStack account, like CryoLauncher and ICESEE.
If you are not signed in, opening Frozen Legacies takes you to the CryoStack
sign-in page and returns you to the application afterwards.

Each signed-in user has a private Frozen Legacies workspace in their
CryoStack workspace. Other users cannot see its contents. The shared
Frozen Legacies datasets remain the same for every user.

## Next Steps

After becoming familiar with the application:

- Read the [Frozen Legacies User Manual](user_manual) for a more complete description of the interface and available scientific information.
- Read the [Developer Guide](developer) if you need to add datasets, adapters, products, or storage backends.
- Return to <a href="/frozen-legacies/">Frozen Legacies</a> to continue exploring the available radar observations.

:::{raw} html
  </div>
</div>
:::
