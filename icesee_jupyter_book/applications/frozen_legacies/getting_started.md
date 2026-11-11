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

:::{note}
**Documentation preview · 10 November 2026.** This revision describes the source integration with root's normal-SSH HTTP/native and review-browser workflow acceptance recorded; the latest persistent-key/title presentation changes still need final root CUA, commit and release qualification. The public site still has the separately approved picker-only release (29-path union overlay, including the 15-file picker deployment); the new Map, reference-selection and Scanner integration must be released together with these pages. Scanner archive naming remains **OFF**. A source implementation or a documentation build is not a production activation.
:::

## Before You Begin

To use Frozen Legacies, you need:

- A modern web browser.
- Access to the CryoStack platform.
- At least one Frozen Legacies dataset registered in the deployment.
- Network access to any external data or image storage required by the selected dataset.

Registered collections include restored Antarctic radar observations and supplied ASTRA, LYRA and TERRA measurements; the available collections depend on this installation.

## Open Frozen Legacies

Open:

[https://cryostack.eas.gatech.edu/frozen-legacies/](https://cryostack.eas.gatech.edu/frozen-legacies/)

The Frozen Legacies interface is organized into two principal areas:

1. **Antarctic map** — displays survey flight tracks and georeferenced radar observations.
2. **Dataset Explorer** — provides dataset and flight controls and displays information for the selected observation.

Above them, four tabs switch the main area:

- **Map** — the Antarctic explorer. Returning to it keeps your dataset, flight, selection and map position.
- **ASTRA · A-scope** — the manual A-scope picker.
- **TERRA · Z-scope** — the Z-scope picker (CBD marks, anchors, trace, calpip calibration, result).
- **LYRA · A-scope** — the automatic A-scope picker. It runs the unchanged native LYRA scripts and stops for human review at four stages: *Frames & CBDs*, *Calibration marks*, *Review calibration* and *Echoes & review*.

ASTRA and LYRA list only A-scope films; TERRA lists only Z-scope films. LYRA results are labelled **Scientifically unvalidated**.

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

**Supplied ASTRA A-scope, LYRA A-scope and TERRA Z-scope measurements**

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

## Radar Preview and Source Choice

The selected-record card shows collection, actual flight, CBD, image type, position, navigation, source QC and review/owner status. Missing information says **not supplied**. Expand **Source and quality** for source files, fingerprints, versions and citation details. Preview images are display copies; the original scan is authoritative.

**Open in ASTRA / TERRA / LYRA** opens a selected exact mapped source. If no exact mapping is available, it opens the appropriate A- or Z-scope catalogue filtered to the record's actual flight and CBD. Choose a file explicitly when several variants match. A catalogue range match does not establish that the printed caption is mapped, and a missing caption never selects a neighbouring frame. Unknown identity stays explicit.

The first-row search, dataset and flight controls and **Scientific filters** define your Map query. Chips and **Copy link** retain it. The count line distinguishes loaded matching observations, records hidden by Layers and catalogue matches. Picker searches do not replace that Map query; returning to **Map** keeps camera and selected record.

## Layers and Save Selection

Open **Layers** for Data, My work & reviewed results, Reference and External sources. The original legend and RIGGS control remain in a compact persistent **Map key**, outside the collapsed Layers menu and visible only on Map. Visibility changes your view, not file access or scientific review. Other external portals are links, not imported datasets.

**NASA Blue Marble imagery (GIBS)** is the default background. The 2D view blends its display colors with the local ocean background while keeping tracks, ice outlines, labels and observations above it; source imagery and scientific values are unchanged. Turn it off in **Layers → Reference** to use the vector map alone; that explicit OFF choice is retained for the browser session, including reload. Turn it back on there to restore imagery. It is a static MODIS mosaic from NASA, not a time-varying measurement. It provides visual context only, with no navigation or measurement correction. Provider failure leaves the local map usable; toggle it off/on to retry.

**3D globe** is an optional view of the same Map data. Select it to load the globe engine. Drag to rotate, point at a place and use the mouse wheel to zoom toward it, or use **+ / −** and **Reset view**. Wheel movement uses controlled steps. Select **3D globe** again to return to your preserved 2D camera; the globe also remembers its own camera for a later return. Layers, filters, selection and the Map key, including RIGGS, stay shared. NASA imagery follows the same ON/OFF choice. While its tiles load, the globe shows outlines and data; filled vector land is available when imagery is off or unavailable. Observations and visible results get priority while the remaining overlays are prepared. Loading status stays visible until preparation is complete, with NASA imagery reported separately. The view can sharpen after you stop moving, within device limits. Map data are unchanged; the ready status does not repeat the toggle label. If the globe cannot load or render, continue in 2D. The globe shows an ellipsoid with shaded imagery, not measured terrain elevation.

**Save selection** downloads a JSON manifest of the selected observation and loaded, matching, visible observations (up to 5,000, with truncation flagged). It records query, units and available provenance; it is not an archive-wide export or a download of the TIFFs. **Dataset downloads** and **Products** retain their separate purposes.

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

It includes restored Antarctic radar observations and separately identified supplied measurement collections. Their source quality, units and provenance remain attached to each record.

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
9. Open raw radar in **ASTRA**, **TERRA** or **LYRA**, or upload your own.
10. Download products from the **Products** list or **Dataset downloads**.

## Open or Upload Radar

1. Select **ASTRA · A-scope**, **TERRA · Z-scope** or **LYRA · A-scope**.
2. Select **Browse A-scope catalog** (or **Browse Z-scope catalog** in TERRA) to search the archive by file name, flight, CBD or collection, then **Open**. The catalogue opens above the picker and scrolls on its own; **← Back to picker**, the same toolbar button (now **Close …**) or **Esc** inside the catalogue returns you to the open film with its picks. Reopening keeps your filters and page.
3. Or select **Upload raw radar** to add your own radar TIFF (with its navigation CSV). Uploads are private and count toward your workspace storage (2 GiB by default), shown beside the upload buttons.
4. If you already have processed results (ASTRA, URSA or LYRA picks, QC images, echograms), select **Upload processed product** instead — you do not need to pick again.

The picker processes the exact file you opened. A film whose name carries no known flight (for example `F0-…` or an unresolved reel name) can still be processed; its flight stays *unknown* and its results stay private and unplaced on the map until its identity and navigation are established.

## Pick an A-scope with ASTRA

1. Select **ASTRA · A-scope** and choose a radar asset.
2. Calibrate as in ASTRA: **Set Up X Axis Reference Line**, **Set Up Y Axis Reference Line**, **Set Up Y Axis** (four grid lines), the **Sweep Rate**, then **Set Up X Axis** (four grid lines).
3. Pick **Surface**, **Bed**, **Noise Floor**, and **Main Bang** by selecting the feature and clicking the plot; picks snap to the red trace. **No Surface** / **No Bed** record absent reflections, and **Suggest Picks** proposes picks for you to check.
4. Select **Next A-scope** to save the A-scope and continue along the strip.
5. Select **Done** when the TIFF is finished, then download the CSV and QC image.

Your session is saved as you work; you can leave and continue later.

## Pick a Z-scope with TERRA

1. Select **TERRA · Z-scope** and open a Z-scope film.
2. Click the CBD marks, then the surface, bed and transmitted-pulse anchors; TERRA traces them. Review the trace and press **Accept trace (a)**.
3. At *Examine Radargram for Calpips* choose **Has Calpips** only if you can see them. Calpips were recorded only about every 32nd CBD, so many films have none.
4. With calpips: **Select End Bound**, then **Pick Calpips** four times. The fourth pick enables **Calculate calibration**; it does not calculate automatically. Inspect spacing and lines, then **Continue to Result**.
5. Without them, use the grouped reference selector: **Confirmed calpips**, **Marked no calpips**, **Not checked**. TERRA selects the nearest compatible completed private calibration on the same verified flight; check its named source or change it. **No Calpips** applies that reference after server validation. If B needs calibration, **Check / calibrate selected film and return** opens B for calibration only, then restores A's draft, anchors, trace, revision and view. Cancel returns A unchanged. Unknown flights cannot be pooled; without a safe reference, check a candidate or explicitly save without calibration (see the [User Manual](user_manual)).
6. Download TERRA's native figure and CSV (not firn corrected).

## Pick Automatically with LYRA

1. Select **LYRA · A-scope** and open an A-scope film.
2. **Frames & CBDs:** select **Detect frames & CBDs**. Compare every CBD with the label printed on the film, correct labels if needed, tick *I checked frame boundaries and CBDs* and select **Confirm frames & mark calibration →**.
3. **Calibration marks:** on five complete frames (all of them on a shorter film), mark the main bang (M), the −60 dB reference (R), eight consecutive time-grid (X, 2 µs apart) and four consecutive power-grid (Y, 10 dB apart) lines, then calibrate. Finish or clear partly marked frames first; marks are always saved. **G** shows LYRA's grey dB guide rows, hidden by default.
4. **Review calibration:** check LYRA's calibration figures against the film and confirm.
5. **Echoes & review:** inspect the surface/bed picks and correct weak or missing echoes.

A server job keeps running if you leave the page. LYRA results are scientifically unvalidated; nothing is approved or published automatically.

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
