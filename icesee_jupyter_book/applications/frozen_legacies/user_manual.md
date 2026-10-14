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

The **Map**, **Manual**, and **Automatic** controls above these areas switch the main area between the Antarctic map and the radar workspace. The radar workspace opens raw radar imagery provided by the installation, or a radar TIFF (with an optional navigation CSV) that you upload to your own workspace. When an observation has raw radar imagery, the Dataset Explorer offers to open it; otherwise it states that none is available. The **Feature Status** section below lists what is validated.

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

A dataset offers downloads only when its manifest declares them. When you select a flight or observation of such a dataset, **Dataset downloads** in the Dataset Explorer provides that dataset's observations and flight tracks as GeoJSON.

Products of your own radar assets (picks, QC images, uploaded products) are downloaded from the **Products** list (see **Products and Downloads** below).

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

## Feature Status

What is validated in this release, and what is not yet:

- **Validated:** signing in and per-user workspaces; the Antarctic map, datasets, flights and observations; the radar viewer; **Manual** (ASTRA) picking, whose CSV and QC image are byte-identical to the ASTRA reference script on synthetic strips and on a real A-scope strip; product downloads.
- **Implemented, not yet validated with real URSA runs:** **Automatic** (URSA). The integration runs URSA unmodified, but URSA has not yet been run and checked on a CryoStack server. Even where URSA's software is installed, review its results before using them.
- **Depends on the installation:** which shared radar and radar catalog are offered. Each CryoStack installation configures its own shared radar sources; an installation may offer none.

## Signing In

Frozen Legacies requires a CryoStack account. If you are not signed in, opening Frozen Legacies takes you to the CryoStack sign-in page and back. Everything you upload, pick, or generate is kept in your own CryoStack workspace; other users cannot see it.

## Radar Workspace: Map, Manual, Automatic

The controls above the map switch the main area:

- **Map** — the Antarctic explorer. Your dataset, flight, and observation selection is kept while you use the other modes.
- **Manual** — the ASTRA A-scope picker for the open radar asset.
- **Automatic** — automatic picking (URSA) for the open radar asset, with the radar viewer.

All three work on the same open radar asset, chosen from **Radar asset** at the top of the workspace.

**More room for the radar.** In Manual and Automatic, **Hide panel** hides the side panel and **Focus** shows only the radar workspace (the page header, mode buttons and upload controls are hidden; **Exit focus** or **Esc** returns). Your choice is remembered in this browser. On wide screens the three ASTRA steps move into a column beside the working window. The working window keeps its exact proportions at every size, so a click selects the same image pixel whatever the layout.

**Links, back and reload.** The address bar keeps the mode, the open radar asset and the map position. **Back** and **Forward** move between them, and reloading the page returns to the same radar asset with its saved session. The map keeps its position when you switch to Manual or Automatic and back, and your committed picks appear on it. A link to a radar asset opens only for its owner.

## Radar Assets

A radar asset is one radar image (or one set of processed products) in your workspace. The **Radar asset** list groups:

- **My radar assets** — assets in your workspace, labelled **Shared**, **Uploaded**, or **Products**;
- **Shared radar** — radar provided by this Frozen Legacies installation that you have not opened yet. Opening it adds a reference to your workspace; the radar itself is not copied, and your picks stay private.

When an explorer observation has raw radar declared by the installation, the Dataset Explorer shows **Open radar** for it. Otherwise it states that no raw radar is available. Radar is only linked to observations through explicit dataset metadata.

## Uploading Raw Radar

Select **Upload raw radar**, choose the radar TIFF (`.tif`/`.tiff`) and, optionally, its navigation CSV (`CBD,LAT,LON`, with optional `THK,SRF`; `9999` marks an unavailable value). Files are checked before they are kept: the TIFF must be a single-page 8- or 16-bit grayscale image that decodes completely, and is limited to 200 MB. The flight and CBD range are read from names such as `F127-C0471_C0483.tiff`.

If you upload a TIFF without navigation, you can add its navigation CSV later as a processed product (before you start picking).

## Uploading Processed Products

If you already have results, you do not have to pick again. Select **Upload processed product**, choose the product type, and choose the file:

| Product type | File |
|---|---|
| ASTRA picks (CSV) | an ASTRA output CSV (exactly ASTRA's columns) |
| ASTRA QC image | PNG |
| URSA picks (CSV) | a URSA `_pick.csv` |
| LYRA echoes (CSV) | a LYRA `*_echoes.csv` |
| Processed echogram, Radargram image | PNG, JPEG, or TIFF |
| Navigation CSV | `CBD,LAT,LON[,THK,SRF]` |

With a radar asset open, the product is added to that asset. With no asset open, it creates a **Products** asset that holds processed products without raw radar; no radar metadata is invented for it.

Each file is validated for its type: CSV columns and values, and for images the actual image format and dimensions (an image renamed to another extension is rejected). Uploaded products are always labelled **User-provided**, never as generated by Frozen Legacies.

## Manual Picking (ASTRA)

**Manual** mode is the ASTRA A-scope picker. It reproduces ASTRA's behaviour, including its calibration and output file, inside Frozen Legacies.

- **Workflow.** The controls follow ASTRA's three steps: **1 Calibration**, **2 Picks**, and **3 A-scope** (Next A-scope, Done, Reset session). Above the plot, the title shows the current A-scope and its CBD, with the number of committed A-scopes, calibration progress (*Calibration k/4*), and what the next click will do.
- **Working window.** The plot shows a 2300-pixel-wide window of image rows 250–1800, smoothed and traced exactly as ASTRA does. Move it with the X Position slider, **←**/**→** (10 px), and **Move 1000 px**. **Show trace** hides or shows the red trace on screen only; picks still snap to it.
- **Calibration.** Set the X and Y axis reference lines, select four Y-axis grid lines (the first is −55 dB, each line above adds 10 dB), choose the sweep rate (1, 2, or 5 µs/div; changing it clears the X grid), and select four X-axis grid lines (the first is one division). The reference lines can be set once per session; use **Reset session** to start again.
- **Picks.** Select a feature, then click the plot. Surface, Bed, Noise Floor, and Main Bang snap to the red trace. Suggested picks are drawn with a dashed outline until you replace them.
- **Next A-scope** saves the current A-scope when it has a Noise Floor and a Main Bang (Surface and Bed may be absent) and updates the CSV.
- **Done** saves the current A-scope and writes the ASTRA CSV and QC image. The radar TIFF is not moved or changed.

### Results and downloads

After **Done**, the workspace shows the completed result: the source radar, the committed A-scopes, a QC preview, and downloads of `<TIFF name>.csv` and `<TIFF name>_QC.png`. The CSV has ASTRA's columns. CBD values are assigned across the TIFF's CBD range in the order A-scopes were saved, as ASTRA does, and LAT/LON come from the navigation record with that exact CBD (empty when there is none).

The QC image is ASTRA's: the full-resolution TIFF with every pick marked, which is large (about 100 MB for a 38,000-pixel strip). **Preview** shows a reduced copy that keeps the pick marks visible; **Download** always gives the original QC image.

### Sessions

Your picking session is saved in your workspace after every step, so you can reload the page or return later. **Reset session** discards the picks and generated files for that radar asset; the radar TIFF itself is kept.

## Automatic Picking (URSA)

**Automatic** runs URSA, the automatic A-scope processor of the Frozen Legacies tools, on the open radar asset. URSA detects the A-scope frames on the film, calibrates the time and power grids, and picks the transmitter pulse, surface, and bed of each frame.

- URSA needs its own software environment (OpenCV, scikit-image and others). The server checks that environment before offering Automatic; when the check fails, Automatic says so and gives the reason; nothing is run and no results are shown. When it passes, Automatic shows the checked software versions.
- **URSA's results are scientifically unvalidated.** They are labelled so wherever they appear, and they cannot be submitted for review or publication; only Manual (ASTRA) results can.
- Select **Run automatic picking**. The job runs on the server; you can leave the page and come back. **Cancel** stops it.
- URSA reads CBDs from names such as `F103-C0467_C0479.tiff` and positions from the navigation file; Automatic warns when either is missing.
- When the job finishes, its products appear: URSA picks (CSV and NPZ), the frame verification image, and the per-frame plots (ZIP). Running it again replaces the previous automatic results. A full strip such as F127 takes about two and a half minutes. Review URSA's picks before using them: on F127, for example, URSA assigns CBDs in frame order across the file-name range, the same limitation as ASTRA's, which does not match the CBDs printed on the film.

## Radar Catalog

Installations with large radar archives offer **Browse radar catalog** in the radar workspace. Filter by dataset, flight, your own processing status (for example *Unprocessed* or *Manual · in progress*), CBD, or file name, and page through the results; then select **Open**. A progress line shows how many radar segments of the selected flight you have in progress or completed. The radar file stays in the installation's archive; your picks and products are kept in your workspace.

Catalog files may be stored outside CryoStack, for example in the installation's Amazon S3 archive. The first time anyone opens such a file, the server prepares a temporary working copy, which can take a moment for large files; your workspace keeps only a reference to the file, never a copy.

On the **Map**, the **Radar catalog** section can show **radar coverage**: radar files whose navigation places them on the map. Select a segment and **Open radar**. Files without navigation are never placed on the map; the section says how many there are, and the catalog browser lists them with navigation *none · unplaced*.

## My Picks on the Map

A-scopes you commit in **Manual** appear on the Antarctic map as **My picks** as soon as you return to **Map** -- hollow markers while the session is in progress, filled after **Done**. They are visible only to you and are not added to the shared datasets. Select one to see its CBD, position, thickness and provenance; **Open in Manual at this A-scope** returns the picker to the window where you committed it. Their CBDs and positions follow ASTRA: CBDs are spread across the file's CBD range in the order A-scopes are committed, so earlier picks can move as you commit more. ASTRA takes the CBD range from the file name; when a scan is missing frames (the CBD printed on the film skips numbers), the CBDs and positions ASTRA assigns can differ from the printed ones -- compare with the labels on the film before relying on a position. A-scopes without a navigation position are counted but not shown.

**Review stage of your picks.** Each radar file's picks carry the stage of their result in the review workflow, shown on the selected pick, as counts under **My picks**, and in the Manual result view:

| Stage | Who can see the current version |
|---|---|
| Private draft · Completed · not submitted | only you |
| Submitted · awaiting review | you and reviewers (they review the frozen copy you submitted) |
| Returned for correction · Rejected · Withdrawn after publication · Superseded | only you |
| Reviewed · published | all signed-in users, on **Reviewed results** |

On the map, a dashed outline marks picks awaiting review, a teal outline published picks, and a red outline returned or rejected ones. If you change or reset a result after submitting or publishing it, your current picks are **not** that version: the stage then says so (for example *an earlier version is published; your current result is not*), and only a new submission and approval publishes the change.


**Georeferencing your picks.** After **Done**, open **Georeferencing — film CBD** below the results. For each A-scope, select **Show frame**, read the CBD printed on that film frame, enter it and select **Confirm**, or select **Unreadable** if the label cannot be read. Confirmed A-scopes get the navigation position of the printed CBD and are marked **Verified**. The others stay **Unverified**: their CBD and position are ASTRA's assignment. Your ASTRA CSV and QC are not changed. **Download** `<TIFF name>_georef.csv` for ASTRA's and the verified CBD and position side by side. Re-picking an A-scope or resetting the session clears its confirmation.

**Coming back to your work.** Your manual sessions are saved after every step. Open the same radar again later -- from the catalog, the map, or **My picks** -- and Manual continues where you stopped, with the A-scopes you committed; they are never duplicated.

## Review and Publication

When a result on shared radar is finished (**Done**), the result view shows **Scientific review**. Select **Submit for review**, optionally with a note for the reviewer. The reviewer receives a frozen copy of the result -- the ASTRA CSV and QC image exactly as you downloaded them, your observations and their provenance -- so later changes to your session do not affect what is reviewed, and the review never changes your own result.

A reviewer (an installation maintainer, not yourself) then **approves** it, **returns it for correction** with a note, or **rejects** it with a reason. Returned results can be corrected and submitted again. Approved results are **published**: they appear on the map for every user under **Reviewed results** and can be downloaded with their provenance. Published observations whose CBD was not confirmed against the film are labelled *unverified*. A newer approved version replaces the older one, and a reviewer can withdraw a published result. Published results never include your account details.

On the **Map**, **My results** lists what is awaiting review, returned to you, or published. Results on your own uploaded radar and automatic (URSA) results cannot be submitted.

## Products and Downloads

The **Products** list in the Dataset Explorer shows everything belonging to the open asset, with its origin:

- **Generated · ASTRA manual picking** / **Generated · URSA automatic picking** — produced by Frozen Legacies;
- **User-provided** — your uploads (raw radar, navigation, processed products);
- **Shared installation radar** — shown for reference; it is not downloadable here.

Each product shows a short summary (for picks: rows, CBD range, positions, thickness values) and **Download**; images also have **Preview**. **Download products (ZIP)** downloads the asset's products together (without the raw TIFF), with a `PRODUCTS.json` index.

## Your Workspace

**Remove asset** removes the open asset and everything you created for it from your workspace. For shared radar it removes only your reference, picks, and products; the shared radar is not affected. An asset cannot be removed while automatic picking is running for it. Uploaded processed products can also be removed individually.

## Errors and Recovery

- **Session ended** — if your CryoStack session expires, the workspace says so; reload the page to sign in again. Your work is saved on the server.
- **Manual session cannot be read** — if a saved manual session is unusable, Frozen Legacies offers **Reset session** instead of discarding it silently.
- **Automatic job interrupted** — a job running when the server restarted is shown as **Interrupted**; run it again.
- **Shared radar unavailable** — if the installation no longer provides a shared radar, its asset is listed as unavailable; your products remain downloadable.
- **Upload rejected** — the message states what failed (type, columns, image format, size); nothing is kept from a rejected upload.

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

The selected observation may not have raw radar in this installation. Open radar from **Radar asset**, or upload your own.

### Automatic picking is unavailable

The server does not have URSA's software installed. Use **Manual**, or upload results you already have as processed products.

### Dataset metadata look incomplete

Some manifest fields are optional and may not yet be defined for the active dataset.

## Next Steps

For a shorter workflow introduction, return to [Getting Started](getting_started).

Developers extending the application with new datasets, adapters, scientific products, or storage backends should continue to the [Developer Guide](developer).

:::{raw} html
  </div>
</div>
:::