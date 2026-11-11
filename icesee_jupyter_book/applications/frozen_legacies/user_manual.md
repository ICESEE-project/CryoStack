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

:::{note}
**Documentation preview · 10 November 2026.** This revision describes the source integration with root's normal-SSH HTTP/native and review-browser workflow acceptance recorded; the latest persistent-key/title presentation changes still need final root CUA, commit and release qualification. The public site still has the separately approved picker-only release (29-path union overlay, including the 15-file picker deployment); the new Map, reference-selection and Scanner integration must be released together with these pages. Scanner archive naming remains **OFF**. A source implementation or a documentation build is not a production activation.
:::

## Application Layout

Frozen Legacies contains two primary working areas:

1. **Antarctic map** — displays survey tracks and observation locations.
2. **Dataset Explorer** — provides controls for selecting datasets and flights and displays the selected observation record.

The **Map**, **ASTRA · A-scope**, **TERRA · Z-scope** and **LYRA · A-scope** tabs above these areas switch the main area between the Antarctic map and the radar workspace. The radar workspace opens raw radar imagery provided by the installation, or a radar TIFF (with an optional navigation CSV) that you upload to your own workspace. An exact selected source can open in its picker; when only flight/CBD metadata is available, the same action opens a prefiltered compatible catalogue for explicit source choice. It never silently substitutes another caption or file. The **Feature Status** section below lists what is validated.

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

The first-row search and expandable **Scientific filters** apply dataset, flight, CBD, review-state and text criteria to the Map explorer state. The picker catalogue keeps its own compatible file search, so selecting a source does not overwrite the Map query. Active filters appear as individually removable chips;
**Clear all** resets them. The live result message announces how many loaded
map observations match without moving keyboard focus.

Choose **Copy link** to copy the canonical `ExplorerQueryV1` URL. Opening the
link restores the permitted filters, and browser Back/Forward restores the
whole filter state rather than a partly updated map. Radar catalog rows,
coverage geometry, exact count, facets, and pagination are authorized and
returned together from one snapshot. The historical observation point layer
is filtered locally from its already-loaded public records.

Use the **Dataset** selector to choose the collection you want to explore.

The selected dataset controls:

- available flights,
- visible survey tracks,
- visible observations,
- dataset metadata,
- and associated products.

The current deployment includes supplied **ASTRA A-scope**, **LYRA A-scope**, and
**TERRA Z-scope** measurement collections. These remain separate datasets with
their original coordinates and source quality flags.

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

### Selected Record, Source and Picker

The inspection card shows Collection, Flight, CBD, Image type, Position, Navigation, Source QC and Review/owner. **Not supplied** means absent information, not a zero. Supplied quantities retain their units. Expand **Source and quality** for version, DOI/citation, source file/row, frame, coordinate statement and available SHA-256. An internal engine flight or alias is never presented as actual flight.

**Open in ASTRA / TERRA / LYRA** opens the exact selected mapped source through normal access checks. With no exact mapped source, a known actual flight and CBD open the matching A-scope (ASTRA/LYRA) or Z-scope (TERRA) catalogue. Choose among variants explicitly; file-range metadata is not caption mapping. No matching files yields an honest empty result and editable filters, not a neighbouring source. Missing actual identity needs source review. Returning to Map keeps its query, camera and selected observation.

With the catalogue segment strip open, matching flight/CBD rows are outlined. This means **this result page only**, and several variants may match; highlighting never opens a file.

### Layers, Context and Selection Downloads

**Layers** is a collapsed disclosure at the map's top right. Its body scrolls independently. **Data** controls image families, tracks, points, coverage and collections; **My work & reviewed results** controls those result layers; **Reference** controls geographic context. The original legend/key and RIGGS control remain in a compact persistent **Map key**, visible on Map even when Layers is collapsed. The original nodes, listeners and RIGGS selection/state are retained; the legend still describes the visible scientific layers. The key is hidden in picker tabs and fits narrow screens. Escape/outside-click closes the disclosure. Hidden records remain in the data and retain their permissions; the count line separates loaded matching observations, hidden-by-layer records and catalogue file counts.

**NASA Blue Marble bathymetry (GIBS)** under Reference is on by default. It combines NASA's static MODIS mosaic with shaded relief and bathymetric context. Where supported, the 2D view adjusts only the imagery's display colors to join the local ocean background; the original tiles, coordinates and scientific overlays are unchanged. Real coastline and ice-shelf outlines, drainage basins, place names, tracks and observations remain above it. Overview labels are limited to broad regions, seas and major shelves; zoom in for smaller places. The vector map appears while imagery loads or fails. Untick imagery for vector context alone; an explicit OFF choice survives reload in the browser session. Turning imagery back on reuses the layer and received tiles.

Imagery starts independently of the observation archive and never blocks the map controls or data. A map notice reports waiting/loading or failed tiles even with **Layers** closed; **Retry imagery** retries a small batch of failed tiles without reloading successful tiles. Partial failure remains visible after other tiles succeed. A slow request can fail after 20 seconds and be retried. The source panel reports received tile counts for this session, which do not imply that every area or resolution is loaded. The polar display domain is a viewing frame, not a coastline or an ice boundary.

This is rendered geographic context, not a measurement, navigation correction, geolocation validation, live ocean view or survey-date imagery. It has no acquisition-date selector. Requests send tile coordinates to NASA without the page URL, filters, selections or credentials. The source panel retains NASA's GIBS/ESDIS acknowledgement and policy links. Other **External sources** entries (including NSIDC, Open Polar Radar/CReSIS, RadarFilm, BAS, REMA and SCAR) remain provider links.

**3D globe** switches the Map to a rotatable, tiltable WGS84 ellipsoid. Its first use loads the optional engine; 2D stays available during loading. The same Layers, filters, selected records, Map key and RIGGS stations remain available, with existing catalogue, picker and selection-download actions. Turn **3D globe** off to restore the preserved 2D camera. Point at a place on the globe and use the mouse wheel to zoom toward it. Wheel and trackpad zoom move in controlled steps; drag to rotate, or use **+ / −**. Drag movement settles sooner after release. **Reset view** resets the active globe camera. Turning the globe back on restores its own last camera; the separate 2D camera remains preserved. Changing picker tabs or hiding the page turns the globe off.

The shared NASA OFF choice also applies in 3D. While NASA tiles load, outlines and data stay visible; filled vector land appears when imagery is off or unavailable. Observation and result layers get priority, followed by RIGGS references and remaining context. More records can appear during preparation. Loading status remains until preparation is complete; NASA imagery and **Retry globe** feedback stay separate. The view uses less drawing work while moving and can sharpen when still, within device limits. Staged display does not remove or change map data, and the normal ready state does not repeat the toggle label. Returning can reuse unchanged map data; completion time still depends on graphics, overlays and imagery. An unavailable engine or graphics context returns to 2D. Shaded relief and bathymetry are visual context on an ellipsoid, not measured terrain or ice elevation. The globe does not turn thickness or travel time into height, validate positions, or change scientific data.

**Save selection** downloads `cryostack.frozen-legacies.selection-manifest.v1` JSON: the selected record plus loaded matching visible observations, capped at 5,000 with truncation flagged. It includes the canonical query, supplied units/coordinates and available dataset/source provenance. Hidden layers are excluded; this is not every catalogue result, a scientific comparison or a raw-film download. Dataset GeoJSON and your product CSV/PNG downloads remain separate.

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

The available quantities depend on the selected source collection. The supplied
ASTRA, LYRA and TERRA collections display their final supplied thickness,
correction availability and provenance. Other LYRA products may also provide:

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

Selecting an observation opens a scientific quicklook on the map (a bottom
sheet on small screens). It combines the radar or film preview with flight,
CBD, coordinates, key derived quantities, lineage, and actions to open the
radar workspace or persistent details. The right-hand Dataset Explorer remains
available for filters and deeper product information.

Use **Previous** and **Next** in the quicklook to step through the current
flight in CBD order. The address bar records the dataset, flight, and stable
observation identifier, so copying the URL or reloading the page returns to
the same observation. Closing the quicklook removes only the observation from
the URL; the dataset and flight context remain available.

Keyboard users can use the Left and Right Arrow keys as well as the visible
buttons to move between observations. Press **Escape** to close the quicklook
and return focus to the map control that opened it. Scrolling to full details
honors the browser's reduced-motion preference.

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

## Supplied ASTRA, LYRA and TERRA Measurements

The October 26, 2026 release preserves these separate supplied products:

| Collection | Rows | Available final thickness | Final values with a firn correction |
| --- | ---: | ---: | ---: |
| ASTRA · A-scope | 4,272 | 3,909 | 3,614 |
| LYRA · A-scope | 3,819 | 3,370 | 3,134 |
| TERRA · Z-scope | 5,485 | 5,003 | 4,678 |

The final supplied thickness is used as supplied. Missing final values stay
missing; a number without an available firn correction is labeled accordingly.
For LYRA, the correction starts from its supplied fixed thickness rather than
its raw thickness. Source quality flags are retained even when a thickness
number is present. These results have not been independently validated.

Original source coordinates are retained. At shared flight/CBD references,
cross-workflow coordinates are not independently verified or harmonized. The
interface warns about this limitation. Do not interpret cross-workflow spatial
differences as physical changes or align the datasets without checking reference
navigation and the source coordinate datum.

The selected-record panel provides correction status, base and final values,
source row/file and fingerprint. A fingerprint identifies a source file;
it does not certify scientific accuracy.

## Picker assets and GT CEDAR collections

**ASTRA** and **LYRA** list A-scope assets only. **TERRA** lists Z-scope assets
only. This applies to the Radar asset selector, filename search, collection
filter, saved workspace references and full radar catalog. Tab changes retain
compatible selections for each picker; an incompatible saved URL cannot open
an image in the wrong picker. Unclassified assets remain available on Map
until their scope is identified. Map browsing retains all permitted families,
including ESM and navigation collections where applicable.

The archive is stored on **GT CEDAR**. **All collections · GT CEDAR** combines
compatible archive collections; individual entries preserve RadarFilm/SPRI,
survey and acquisition-year provenance. These are collections on the same
storage service, not separate storage destinations. Empty and incompatible
collections are omitted from the picker filter. Search and counts follow the
active picker; your current open asset stays available while searching.

TERRA's progress strip tracks CBD references, surface/bed/transmitted-pulse
anchors and calibration. Its marking hints follow the supplied README's
operator workflow. Four calpips represent adjacent 2 µs intervals. The browser
calibrates the current image only when you calculate it there, and reuses
another film's spacing only when you press **No Calpips**; it never backfills
measurements silently. New web exports remain
separate from Angelo's supplied firn-corrected compilation.

## TERRA Z-scope Picking

The Result view fits the complete native graph, including its axes, into the available height. **Fit figure** adjusts it after a layout change; **Open full figure** opens the original image for a larger view. The CSV remains accessible below the graph. The collapsible console stays on the left on wide screens and scrolls its messages independently, with **Follow** kept visible.

TERRA gives the film the main workspace. The numbered stage bar keeps the current task prominent and marks completed steps. **Show console** opens processing messages when needed; hiding it returns the full width to the radar image. Status and elapsed processing time remain visible through tracing, calibration and result generation. The Calpip workspace shows the current bound/pick/calculation step beside a larger film view.

Choose **TERRA · Z-scope** for a raw Z-scope TIFF. **ASTRA · A-scope** and
**LYRA · A-scope** remain separate workflows. Known A-scope and ESM assets show compatibility guidance in TERRA; use the data-source filter to choose a Z-scope collection. Assets with unknown scope metadata need an operator check. A processed-product-only asset
has no raw image to trace.

TERRA in the browser follows the desktop `TERRA.py` workflow step for step
(as recorded with the program's authors on 31 October 2026): CBD marks →
surface, bed and transmitted-pulse anchors → trace preview → *Examine
Radargram for Calpips* → calpip picker (or a selected compatible completed native reference) →
TERRA's figure and CSV. The phase strip above the window shows where you are.

**The TERRA window.** The large image is TERRA's own window: the whole film,
rows 300–2050 as TERRA crops them, resized to TERRA's fixed 1200 × 800 display
by TERRA's own code. Every pick is made here, exactly as on the desktop, and is
stored in original TIFF pixels (TERRA's `x × scale_x`). The **TERRA console**
beside it prints the same messages as the desktop program's terminal (phase
prompts, every point added, groups closed, traces generated).

1. **Phase 0 · CBD marks.** Left-click each CBD mark (the tick marks along the
   bottom of the film), then right-click (or **Done with CBD marks**). As in
   TERRA, the CBD numbers come from the file name (`F141-C0443_C0456` → 456 at
   the left-most mark … 443 at the right-most, spread evenly over the marks); if
   you click more marks than there are CBDs, TERRA repeats a number and the
   console says so.
2. **Phase 1 · Surface, Bed, Transmitted.** Left-click anchors along the echo
   (use inflection points). **Right-click closes the current group**; start
   another group across a gap, so disconnected bed sections stay separate
   traces. **Enter** finishes the feature. Keys as in TERRA: **u** undo, **d**
   dark / **b** bright polarity, **s** skip this file, **r** reset all picks.
3. **Phase 2 · Trace preview.** Finishing the transmitted pulse starts TERRA's
   anchor-guided tracing at once (about 10–15 s for a whole film); a progress
   badge counts the seconds and the film stays usable. Review the traces drawn
   on the film, then press **a** (Approve). **[ / ]** narrow or widen TERRA's
   search window and **- / =** change the tracking step; each re-traces. If a
   trace fails, the status says why; **Back to anchors** keeps your groups.
4. **Examine Radargram for Calpips.** Scroll the enhanced radargram (800
   original columns at a time, as in TERRA) with the slider, the arrows or by
   dragging, and choose **Has Calpips** or **No Calpips**. Calpips were
   recorded only about every 32nd CBD (advice from TERRA's authors), so many
   films have none; choose **Has Calpips** only when you can see them. The
   panel shows its saved revision or unsaved draft and the selected reference's provenance. Presence alone and a 32-CBD cadence do not provide a calibration (see *Calibrating from a nearby film* below).
5. **Calpip Picker.** **Select End Bound** and click where the y-axis ends;
   **Pick Calpips** stays disabled until the bound is set. Then select
   **Pick Calpips** and click four calpips; the checklist counts
   **Calibration picks: n / 4** and keeps every pick while you zoom and pan.
   The fourth pick does not calculate anything by itself. With the end bound
   and **4/4** picks set, **Calculate calibration** becomes available. Select
   it to draw the repeated cyan lines at the average spacing (2 µs per
   calpip), then select **Continue to Result** to save the calibrated result.
   **No Calpips** applies only the selected compatible completed native reference. If none is safe, check another candidate or explicitly select **Save without calibration (time/depth empty)**.
6. **Result.** TERRA's own final figure (mirrored radargram, CBD axis, depth in
   m on the left, two-way travel time in µs on the right, dashed calpip lines,
   surface/bed/transmitted traces) and the CSV table are shown together;
   download either. The CSV is TERRA's native output and is **not firn
   corrected**. **Next file →** takes you to the file search; reopening a file
   restores its saved result.

**Calibrating from a nearby film.** A file A without calpips can use a private, completed native calibration from compatible file B on the **same verified flight**:

1. At Examine, inspect the groups **Confirmed calpips**, **Marked no calpips**, and **Not checked**. TERRA recommends the nearest completed compatible reference by CBD interval distance, with a deterministic tie break. The named source, verified flight and CBD distance are shown; change the selection if needed. A filename or 32-CBD cadence is only a candidate hint. **Find / retry references** refreshes the evidence.
2. If B is already calibrated, inspect its source, then choose **No Calpips** on A. The server rechecks reference ownership/access, actual TIFF SHA/version, verified flight and image/crop compatibility before applying B's native spacing. Another user's private calibration, unknown/F0 flight pooling, a stale TIFF or a mismatched source is refused. The resulting record names B; its spacing is reused, not re-measured on A.
3. If B is confirmed but uncalibrated, or an unchecked candidate needs inspection, select **Check / calibrate selected film and return**. This opens **calibration only**: no B surface/bed/transmitted tracing is required. Inspect the film, select the end bound, pick four marks, choose **Calculate calibration**, inspect spacing/lines, then **Continue to Result**. Only the completed native calculation supplies spacing. Mark **No Calpips** on B if absent and try another candidate.
4. Continue returns to the same A draft with its CBDs, anchors, trace, revision and film/examination view retained. **Cancel / return** or a B loading/calculation/stale-input error leaves A unchanged; use the return control if an error leaves B open. A's unsaved draft stays in memory during this visit. Do not replace the main source or reload the page during it.
5. Back on A, check/change the reference and select **No Calpips** to save A's result. When no compatible confirmed reference is known, the panel says so: search/check a candidate, calibrate A directly if calpips are visible, or explicitly save with time/depth empty. Reference loading/API errors keep the work and offer retry; they do not silently choose a last-used spacing.

Root exercised this reference workflow in the isolated review browser: A retained13 CBD marks, surface anchors, two disconnected bed groups and transmitted anchors; B was calibrated through four manual picks and returned to A’s native CSV/PNG result. B’s pre-existing saved revision remained unchanged. The subsequent blank-return-title fix restores A’s filename and metadata chips; final CUA for that presentation fix remains root-owned. Fractional mouse input is not a fixed scientific calibration fixture.

Presence is a recorded operator observation, not autonomous scientific verification. Existing completed calibrations are offered only when their exact input and committed outputs can be checked; old unbound spacing is not reused blindly. Saved revisions remain available. Neither the visit nor saving a calibration approves or publishes any scientific result.

**Zoom and pan.** Desktop TERRA has a fixed view; the browser adds zoom on the
same film. Use the mouse wheel, **＋ / −**, or (outside the trace preview) the
**+** and **-** keys; **Fit** or **0** returns to the whole film. Drag to pan, or
use the arrow keys. A sharper image of the visible part appears when the view
rests. Picking works at every zoom, at once, and every pick is stored in original
TIFF pixels: a click adds a point even if the hand moves a few pixels; a
longer drag only pans (and says so). TERRA's keys (Enter, u, a, …) work after
using the toolbar buttons too, not only with the film focused. A CBD mark
cannot be placed twice in the same column. The Examine and Calpip Picker panels
zoom and pan the same way, and their **Fit** returns to TERRA's own view of 800
columns.

**Asset details** in the title bar shows the asset panel; TERRA otherwise uses
the full width. The film fills the space beside the console and grows with the
window (only its on-screen size changes; picks are always stored in original
TIFF pixels). **Show console** opens the processing messages; **Hide console** returns the full width to the film. The panel above the film lists what each click and key does in the current
step; **? Shortcuts** shows every key. The step bar marks finished steps ✓, the
current step ● and later steps ○; from the trace preview the Transmitted step
returns to the anchors, and from the result the Trace preview step reopens your
picks. **Reset…** asks before clearing the picks (the **r** key too). In the
Calpip Picker a checklist shows the end bound, **Calibration picks: n / 4** and
the accepted average spacing.

Switching to another workspace tab hides TERRA and retains unsaved anchors for
the same open asset. Returning restores them. Unsaved edits do not survive a
page reload or replacing/closing the asset; save and review a revision first.
The map quicklook hides in picker tabs and returns to its selected observation
on Map. Explicitly closing the quicklook keeps it dismissed.

Changing the crop clears current anchors, markers and calibration after a
confirmation; existing saved CSV revisions remain. An invalid crop keeps
current points. Wait for the current image preview to load before adding
points. If another window changed the saved session, reload before retrying.
Generated results remain scientifically unvalidated until independently reviewed.

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

A flight may also appear from an operator-installed navigation collection
before any matching radar TIFF is available. The map and flight selector show
its verified track, while the right panel states **Navigation available** and
that imagery has not been installed. Navigation-only coverage cannot be opened
in a picker and is not counted as a radar asset.

## Feature Status

What is validated in this release, and what is not yet:

- **Technically verified:** signing in and per-user workspaces; the Antarctic map, datasets, flights and observations; the radar viewer; **ASTRA** picking, whose CSV and QC image are byte-identical to the ASTRA reference script on synthetic strips and on a real A-scope strip; the **TERRA** workflow, whose CSV and figure were reproduced byte for byte from the same fixed inputs in release testing (TERRA results themselves are not firn corrected and not independently validated); product downloads.
- **Implemented, scientifically unvalidated:** **LYRA** (URSA remains readable as an earlier automatic picker). All four native LYRA phases — frame detection, calibration and echo extraction, including resumed runs — have run in CryoStack on real film, with outputs identical to the unchanged native scripts, and an input that changed or went missing is refused before processing. These are technical integration checks that CryoStack runs LYRA faithfully; they are **not** independent scientific validation of LYRA's frames, calibration, echoes or thicknesses. The workspace shows **Scientifically unvalidated** on every LYRA result. Review every automatic result before using it.
- **Depends on the installation:** which shared radar and radar catalog are offered. Each CryoStack installation configures its own shared radar sources; an installation may offer none.

## Signing In

Frozen Legacies requires a CryoStack account. If you are not signed in, opening Frozen Legacies takes you to the CryoStack sign-in page and back. Everything you upload, pick, or generate is kept in your own CryoStack workspace; other users cannot see it.

## Radar Workspace: Map, ASTRA, TERRA, LYRA

The tabs above the map switch the main area:

- **Map** — the Antarctic explorer. Your dataset, flight, observation selection and map position are kept while you use the pickers.
- **ASTRA · A-scope** — the manual A-scope picker.
- **TERRA · Z-scope** — the Z-scope picker (see *TERRA Z-scope Picking*).
- **LYRA · A-scope** — the automatic A-scope picker (see *Automatic Picking (LYRA)*).

Each picker keeps its own compatible open asset, chosen from **Radar asset** or the radar catalogue.

**More room for the radar.** **Hide panel** / **Show panel** hides or shows the side panel; in TERRA and LYRA it is the same panel as their **Asset details** button, so both always show the same state. **Focus** shows only the radar workspace (the page header, tabs and upload controls are hidden; **Exit focus** or **Esc** returns, restoring the panel state you had). Your choice is remembered in this browser. TERRA and LYRA keep a collapsible console on the left on wide screens. On wide screens the three ASTRA steps move into a column beside the working window. Fit, zoom and pan work as before; the working window keeps its exact proportions at every size, so a click selects the same image pixel whatever the layout. On smaller screens, scroll the page to reach the stacked console and work area; the console keeps its own message scrollbar.

**Links, back and reload.** The address bar keeps the tab, the open radar asset and the map position. **Back** and **Forward** move between them, and reloading the page returns to the same radar asset with its saved session. The map keeps its position when you switch to a picker and back. A link to a radar asset opens only for its owner.

## Radar Assets

A radar asset is one radar image (or one set of processed products) in your workspace. The **Radar asset** list, filtered to the films the current picker can open, groups:

- **External datasets** — radar provided by this Frozen Legacies installation that you have not opened yet: its shared radar and the files of its registered data sources (for example an S3 archive or Georgia Tech CEDAR storage). Each file shows its name, flight, dataset and size. Opening one adds a reference to your workspace; the radar itself is not copied, does not count toward your storage, and your picks stay private.
- **My workspace** — assets in your workspace, labelled **Shared**, **Uploaded**, or **Products**.

When the installation has data sources, **Search radar files** (by file name) and a source filter appear beside the list. Results come from the server a page at a time; **Show more** loads the next page. Flight and CBD range shown for a file are read from its name and are not verified against the film.

When an explorer observation has raw radar declared by the installation, the Dataset Explorer shows **Open radar** for it. Otherwise it states that no raw radar is available. Radar is only linked to observations through explicit dataset metadata.

## Uploading Raw Radar

Select **Upload raw radar**, choose the radar TIFF (`.tif`/`.tiff`) and, optionally, its navigation CSV (`CBD,LAT,LON`, with optional `THK,SRF`; `9999` marks an unavailable value). Files are checked before they are kept: the TIFF must be a single-page 8- or 16-bit grayscale image that decodes completely, and is limited to 200 MB. The flight and CBD range are read from names such as `F127-C0471_C0483.tiff`.

If you upload a TIFF without navigation, you can add its navigation CSV later as a processed product (before you start picking).

### Storage quota

Your workspace has a storage quota — 2 GiB unless an administrator set another — shown beside the upload buttons as **Storage: used / quota**. It counts the files you keep: uploaded radar and products, and the results you generate. Radar opened from **External datasets** does not count. An upload that would not fit is refused before it is sent, with how much space remains; the server applies the same check. When your workspace is over its quota (for example after the quota was lowered), your files stay available to open, download and remove, but new uploads, picking results and automatic runs are refused until you remove files or an administrator raises your quota. Nothing is ever deleted to enforce a quota.

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

**ASTRA · A-scope** is the ASTRA manual A-scope picker. It reproduces ASTRA's behaviour, including its calibration and output file, inside Frozen Legacies.

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

## Automatic Picking (LYRA)

**LYRA · A-scope** runs the unchanged native LYRA scripts in four stages (*Frames & CBDs*, *Calibration marks*, *Review calibration*, *Echoes & review*), with the same review pauses as the desktop workflow. The main workspace shows the current stage and LYRA's own figures. **Show / hide source film**, **Show asset details** and **Show console** (the collapsible processing console) keep supporting information available.

1. **Detect and review frames.** Wait for source/capability preflight, then select **Detect frames & CBDs**. A blocked/loading/unavailable state explains the actual reason; **Recheck availability and source** retries it. Switching to a supported film starts a fresh check. Inspect both the contact sheet and OCR diagnostic, including complete/partial frame boundaries and every CBD. Sequence consistency does not prove the labels are correct. Enter explicit CBD corrections in the table and select **Apply edited CBDs** to rerun frame detection, then tick *I checked frame boundaries and CBDs* and select **Confirm frames & mark calibration →**. Nothing is confirmed for you.
2. **Mark calibration guidance.** Fully mark five complete frames with LYRA's M/R/X/Y controls below (every usable frame when the film has fewer than five), and finish, clear or exclude any frame you only partly marked. Save your marks, then select **Save and calibrate** or **Calibrate using saved marks**. If calibration cannot start, the step says why in plain words (marks still missing, or a server that does not have the updated calibration engine yet); your marks are kept.
3. **Review calibration.** Inspect each native calibration figure against the film: main bang, −60 dB reference and grid spacing. When LYRA moved a main bang more than 20 px from your M mark, the step lists those frames (your column → LYRA's column); open each figure and do not confirm a calibration whose red line is not on the main bang. Return to your marks and recalibrate anything incorrect. Confirm the current calibration before extracting echoes.
4. **Extract and review echoes.** Inspect surface/bed picks, TWT, ice thickness, waveform and publication figures per frame. Weak or missing echoes are called out for manual review. Use **Review / correct echoes** to change them, then **Save & apply with LYRA** to run native echo extraction with those choices.

Changing frame labels or calibration marks makes downstream results out of date. Review confirmations belong to the exact saved phase outputs. A server job continues if you leave the page; **Cancel processing** stops it. The console shows native progress and errors.

### Marking calibration frames

| Key | Mark | Colour | Guidance |
|---|---|---|---|
| **M** | Main bang: the sharp leading edge of the first spike, where time is zero | red | Required on each calibration frame |
| **R** | −60 dB reference line below the trace | cyan | Required on each calibration frame |
| **X** | Eight **consecutive** major vertical time-grid lines — neighbours, each 2 µs after the last, none skipped — across the scope | orange | Required on each calibration frame |
| **Y** | Four **consecutive** major horizontal power-grid lines — neighbours, each 10 dB from the last, none skipped | green | Required on each calibration frame |

**Five calibration frames.** **Save and calibrate** is enabled once five different complete frames are *fully marked* (M, R, 8 X and 4 Y; marked as **✓ complete** in the frame list) and no other frame is only partly marked. LYRA's own picker code combines the grid spacing of all marked frames and applies it to the frames you did not mark; CryoStack adds no calculation of its own. A film with fewer than five usable complete frames needs **all** of them, and the dialog says the calibration rests on that smaller number. A frame excluded as a film defect does not count. With no usable complete frame LYRA cannot calibrate the film.

**Partly marked frames.** A frame with some marks but not all (for example three of four power-grid lines) is listed with what it still needs; finish it, **Clear frame**, or exclude it. LYRA never receives an incomplete line set, because it would silently ignore it. Incomplete marks can still be saved (with R on one frame) or kept as a draft; nothing is discarded. Each line is marked once: a second click on a line selects it, and a line stored twice by an older draft must be removed before saving.

**Earlier guidance.** Marks saved before this change (four X and two Y lines) open and save unchanged and stay editable; the frame shows as partly marked until you add the remaining lines. Existing calibrations and results are not changed.

**Updated calibration engine.** Calibrating with four power-grid lines needs the updated LYRA calibration engine on the server. The original engine uses exactly two power-grid lines and would silently ignore four. Until the administrator installs the updated engine, the step shows *"This server's LYRA calibration engine does not support eight time-grid and four power-grid marks yet"* and calibration stays off; marking and saving work as usual. An uploaded LYRA desktop-picker file keeps LYRA's own rules (R on one frame, zero or two power-grid lines, or four with the updated engine). Files with any other count, a repeated line or a non-numeric value are refused with the reason.

**Grey dashed rows.** LYRA's default dB guide rows are hidden by default because they can cover the faint reference dots in the noise. **G** or **dB guides** shows them while you need them. They are a display aid only; your marks and the film are unchanged.

**Main bang refinement.** LYRA refines each M mark on the film itself. With the original engine, on `F125-C0822_C0834` an M placed exactly on the leading edge was moved +92 to +98 px onto the falling tail of the same pulse. A corrected LYRA engine is a separate server dependency installed by the administrator; CryoStack does not move your marks or change LYRA's numbers. Whatever engine runs, step 3 lists frames where LYRA's main bang is more than 20 px from your mark: always check the red line there.

- **Fit** shows the whole frame at its original proportions; unused space may remain beside it. **− / zoom level / + / Fit / 1:1** changes the view; **+ / −** keys zoom, **0** fits and **Z** toggles fit/1:1. Ctrl/⌘+wheel zooms about the pointer. Browser Ctrl/⌘+/−/0 shortcuts retain their normal meaning.
- Shift-drag or middle-drag pans; when zoomed, click/drag the overview strip to jump along the frame. Arrow keys move a selected mark by one source pixel (Shift ×10); with no mark selected they pan. A touch tap marks and a drag pans. Zoom is kept when changing frames.
- Marks remain frame-relative columns and original image rows through zoom, pan, resize and frame changes. The sharper source image loads when needed without changing picks. Expand **Keys, zoom and navigation** for the controls; plain wheel scrolling is not trapped by the frame.
- The mode buttons count marks per frame (**X 8/8**, **Y 4/4**); a ninth X or fifth Y is refused with a message (drag a line or press **U**).
- **U** undoes the last mark of the current kind; **N / B** move forward/back; **S** clears the current frame's marks and skips to the next frame. **Exclude this frame** explicitly excludes a film defect.
- **Q / Esc** saves and closes. Incomplete marks can be saved as a draft and resumed. A draft without R cannot start calibration, and older saved guidance cannot silently replace that draft.
- Complete marks are stored as native `F<flight>_cal_picks.json`; LYRA's own picker code derives calibration spacing. Existing native picks/derived JSON files can also be uploaded under **Products**.

### Correcting surface and bed echoes

Manual review starts with weak or missing echoes; select **All frames** to inspect every calibrated frame. The film appears beside the last extracted native waveform. Dashed lines show the previous automatic positions; solid lines show pending choices.

- **s / b** selects surface/bed; click the echo at or after the red main-bang line.
- **Shift+S / Shift+B** marks surface/bed absent. **d** clears the current frame's overrides.
- **n / p** or right/left arrows moves between frames. **q / Esc** saves and closes. **Save & apply with LYRA** reruns echo extraction without repeating frame detection or calibration.
- Choices use native `F<flight>_echo_overrides.json` keys and coordinate conversion. Download that file and the native CSV/figures under **Products / Downloads**.

**Check CBDs carefully.** Where OCR is unsure, LYRA can infer CBDs from neighbours assuming no skipped labels. On F127, CBDs 476–477 are absent from the film, so the first five frame labels of `F127-C0471_C0483` need inspection against the OCR diagnostic.

**Which file LYRA processes.** LYRA processes the exact file you opened, whatever its name. Native LYRA expects reel-style names, so CryoStack hands it a private copy under a declared internal name; when the real flight is unknown it also passes LYRA a reserved technical flight code (999). These internal labels can appear in LYRA's own CSV columns, figure titles and OCR diagnostics (including a forced flight prefix in front of OCR readings). They are processing labels only, **not** evidence of the film's flight or location, and they never rename the archive file or place anything on the map. The native CSVs and figures are kept exactly as LYRA wrote them, not redrawn. The workspace header shows the original display name, the verified original reel name (or *Original reel name unresolved*) and the source flight (or *unknown*), and each product's **Provenance** records the source identity. A film with an unknown flight stays unknown: CryoStack does not guess it from CBDs, the internal code or OCR prefixes.

The input is pinned once processing starts: later phases and resumed runs use the same source fingerprint (SHA-256) and internal name. If the stored file changes or disappears, LYRA refuses to continue rather than mixing inputs; renaming or correcting catalogue metadata does not rewrite a run already in progress. Start a new run to process the changed file.

**Console and source film.** **Show console** exposes a separate scrolling log with title and **Follow latest message** above it. The source implementation bounds it by the actual workspace height and lets boundary scrolling reach the outer page; it stacks on narrow screens. Root verified the last log line, Follow header and outer-wheel reachability at1440×900 and1280×720. **Show / hide source film** exposes the source strip with its own position slider and readout. Its endpoints clamp when viewport width/zoom changes; Home/End jump to the ends, arrows move one source column and Page keys move by most of a window. These controls do not alter calibration marks. Generic **Hide/Show Panel**, the asset-details button, Focus/Exit focus and catalogue Back keep their state together without discarding drafts.

**LYRA outputs remain scientifically unvalidated.** Native good/weak_bed/no_bed/no_surface labels are heuristic checks. Saving/completing never approves or publishes. The integrated review path for completed LYRA/TERRA products is described below; it is source-built pending the joint release. Map position requires actual identity and exact finite navigation, never frame order or internal labels.

Earlier URSA jobs remain readable, with their producing picker named on their results. An installation selecting URSA retains the workflow below.

### URSA (fallback)

URSA, the earlier automatic A-scope processor of the Frozen Legacies tools, detects the frames, calibrates the time and power grids, and picks the transmitter pulse, surface and bed. It needs its own software environment (OpenCV, scikit-image), reads CBDs from names such as `F103-C0467_C0479.tiff`, and positions from the navigation file. Its products are URSA picks (CSV and NPZ), the frame verification image and the per-frame plots (ZIP). On F127, URSA assigns CBDs in frame order across the file-name range, which does not match the CBDs printed on the film.

## Radar Catalog

Installations with large radar archives offer **Browse A-scope catalog (N)** in ASTRA and LYRA and **Browse Z-scope catalog (N)** in TERRA; N counts the films that picker can open. Filter by dataset, flight, your own processing status (for example *Unprocessed* or *Manual · in progress*), CBD, or file name, and page through the results with **‹ Previous** / **Next ›**; then select **Open**. A progress line shows how many radar segments of the selected flight you have in progress or completed. The radar file stays in the installation's archive; your picks and products are kept in your workspace.

The catalogue opens above the picker inside the workspace. Its results scroll in their own region and the pager stays visible at the bottom, so a long list never pushes the picker out of reach. To return without opening anything, select **← Back to picker**, the toolbar button (now **Close … catalog**), or press **Esc** while focus is in the catalogue. Closing only hides the catalogue: the open film, its stage and your picks are unchanged, and reopening shows the same filters and page. **Esc** pressed on the film or elsewhere keeps its usual meaning in the picker.

Catalog files may be stored outside CryoStack, for example in the installation's Amazon S3 archive. The first time anyone opens such a file, the server prepares a temporary working copy, which can take a moment for large files; your workspace keeps only a reference to the file, never a copy.

On the **Map**, the **Radar catalog** section can show **radar coverage**: radar files whose navigation places them on the map. Select a segment and **Open radar**. Files without navigation are never placed on the map; the section says how many there are, and the catalog browser lists them with navigation *none · unplaced*.

## My Work on the Map

**My work** shows only your own current results; **Reviewed results** shows normally approved frozen products. In the integrated source, saved ASTRA picks, committed TERRA markers and completed LYRA frame results refresh after saves/completion/review decisions, including other tabs. Enabled visible layers also refresh at most every 45 seconds, retaining camera, selection and visibility choices. This integration is pending the joint runtime release described at the top of this page.

Readable unlocated results stay private, listed and downloadable. Actual known flight, compatible source/CBD and an exact finite navigation record are required to draw a point. An internal engine code cannot locate it. A previously unknown LYRA flight can acquire a **derived** location only through an accepted authoritative identity event tied to the same input SHA/current catalogue version, followed by the normal CBD/navigation/access checks. That does not rewrite native CSVs, figures or job identity; an edited filename/catalogue hint alone is insufficient. Conflicting known flight stays blocked. Review and publication still require explicit submission/approval.

Saving or completing a result never publishes it. Source or navigation changes may update the live private binding and make it a new version; already approved snapshots keep their frozen geometry and provenance.

### ASTRA picks

A-scopes you commit in **ASTRA** appear on the Antarctic map under **My work** as soon as you return to **Map** -- hollow markers while the session is in progress, filled after **Done**. They are visible only to you and are not added to the shared datasets. Select one to see its CBD, position, thickness and provenance; **Open in Manual at this A-scope** returns the picker to the window where you committed it. Their CBDs and positions follow ASTRA: CBDs are spread across the file's CBD range in the order A-scopes are committed, so earlier picks can move as you commit more. ASTRA takes the CBD range from the file name; when a scan is missing frames (the CBD printed on the film skips numbers), the CBDs and positions ASTRA assigns can differ from the printed ones -- compare with the labels on the film before relying on a position. A-scopes without a navigation position are counted but not shown.

**Review stage of your picks.** Each radar file's picks carry the stage of their result in the review workflow, shown on the selected pick, as counts under **My work**, and in the ASTRA result view:

| Stage | Who can see the current version |
|---|---|
| Private draft · Completed · not submitted | only you |
| Submitted · awaiting review | you and reviewers (they review the frozen copy you submitted) |
| Returned for correction · Rejected · Withdrawn after publication · Superseded | only you |
| Reviewed · published | all signed-in users, on **Reviewed results** |

On the map, a dashed outline marks picks awaiting review, a teal outline published picks, and a red outline returned or rejected ones. If you change or reset a result after submitting or publishing it, your current picks are **not** that version: the stage then says so (for example *an earlier version is published; your current result is not*), and only a new submission and approval publishes the change.


**Georeferencing your picks.** After **Done**, open **Georeferencing — film CBD** below the results. For each A-scope, select **Show frame**, read the CBD printed on that film frame, enter it and select **Confirm**, or select **Unreadable** if the label cannot be read. Confirmed A-scopes get the navigation position of the printed CBD and are marked **Verified**. The others stay **Unverified**: their CBD and position are ASTRA's assignment. Your ASTRA CSV and QC are not changed. **Download** `<TIFF name>_georef.csv` for ASTRA's and the verified CBD and position side by side. Re-picking an A-scope or resetting the session clears its confirmation.

**Coming back to your work.** Your manual sessions are saved after every step. Open the same radar again later -- from the catalog, the map, or **My work** -- and ASTRA continues where you stopped, with the A-scopes you committed; they are never duplicated.

## Review and Publication

When a result on shared radar is finished (**Done**), the result view shows **Scientific review**. Select **Submit for review**, optionally with a note for the reviewer. The reviewer receives a frozen copy of the result -- the ASTRA CSV and QC image exactly as you downloaded them, your observations and their provenance -- so later changes to your session do not affect what is reviewed, and the review never changes your own result.

A reviewer (an installation maintainer, not yourself) then **approves** it, **returns it for correction** with a note, or **rejects** it with a reason. Returned results can be corrected and submitted again. Approval itself publishes the result in one step -- there is no separate Publish action. Approved results are **published**: they appear on the map for every user under **Reviewed results** and can be downloaded with their provenance. Published observations whose CBD was not confirmed against the film are labelled *unverified*. A newer approved version replaces the older one, and a reviewer can withdraw a published result. Published results never include your account details.

On the **Map**, **My results** lists what is awaiting review, returned to you, or published. Results on your own uploaded radar stay private and cannot be submitted. The public picker-only release still lacks the integrated LYRA/TERRA submission path below; URSA remains outside it.

**Integrated source (pending joint release):** completed TERRA and LYRA results get **Submit for review** in **My work** and use the same review: the reviewer sees a frozen snapshot of the native CSV (TERRA) or frame index and echoes (LYRA) with their hashes, must explicitly accept CBD positions that were not confirmed against film labels, cannot review their own submission, and only sees sources they can access. Approval publishes the snapshot; it replaces only an earlier published result of the same workflow for the same film, so a TERRA approval never replaces an ASTRA or LYRA result. If the film's identity or navigation later changes, the published snapshot does not move; your live result becomes private again and can be submitted anew. LYRA remains labelled scientifically unvalidated after publication.

## Products and Downloads

When a radar asset is open, the right panel begins with four bounded preview
slots: source radar, radargram/echogram, QC image, and picker diagnostics. A
slot is populated only when the authenticated product listing reports an
available preview URL. Otherwise it is explicitly a placeholder and not
scientific data. Each populated card states its provenance/scientific status
and offers **Open full preview** for detailed inspection. A preview is a
display derivative; the original file and recorded provenance remain
authoritative. Automatic-picker diagnostics remain scientifically unvalidated.

For navigation-only flights, the right panel shows the scientific products the
platform is prepared to receive. **Awaiting verified source** and **Requires
source TIFF** cards are interface placeholders only; they contain no radar
image, digitized measurement, or automatic result. They are replaced by real
preview and download controls only after the installation validates and indexes
the corresponding file.

The **Products** list in the Dataset Explorer shows everything belonging to the open asset, with its origin:

- **ASTRA manual result** / **LYRA automatic result** / **URSA automatic result** — produced by Frozen Legacies (automatic results are marked *scientifically unvalidated*);
- **User-provided** — your uploads (raw radar, navigation, processed products);
- **Shared installation radar** — shown for reference; it is not downloadable here.

Open **Provenance** on a product to inspect the source identifiers that the
server recorded for it, such as its picker, source or original file name,
shared-source ID, and SHA-256 checksum. Only recorded fields are shown; Frozen
Legacies does not infer missing provenance. Image products also offer an
inline preview whose expanded state is announced to assistive technology.

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

The server cannot run the automatic picker it is configured with (LYRA or URSA); the LYRA tab gives the reason and nothing is run. Use **ASTRA · A-scope**, or upload results you already have as processed products.

### LYRA stops after reading the CBDs

Calibration and echo extraction need the −60 dB reference line marked on one frame. Select **Calibrate frames**, mark it (R), and choose **Save and run LYRA**.

### Dataset metadata look incomplete

Some manifest fields are optional and may not yet be defined for the active dataset.

## Next Steps

For a shorter workflow introduction, return to [Getting Started](getting_started).

Developers extending the application with new datasets, adapters, scientific products, or storage backends should continue to the [Developer Guide](developer).

:::{raw} html
  </div>
</div>
:::

## RadarFilm scope images and flight navigation

The RadarFilm intake adds original A-scope, Z-scope and ESM-scope images and
archival flight navigation. Availability is determined by completed, registered
sources; a transfer still in progress is not a published dataset.

The observation popup and right panel show only scope types that cover the
selected survey, flight and CBD. Greenland also requires its acquisition year.
One available type produces one image, two produce two, and all three produce
three. If more than one distinct scan covers the same selection, choose a
source explicitly. Missing or failed previews never substitute a nearby scan.
Both surfaces use the same selection identity. A range-based crop is labelled
approximate: inspect the printed CBD before scientific use, and report disputed
metadata rather than assuming that a preview proves frame calibration.

Maintainers can use Control Center → Settings → **Frozen Legacies · RadarFilm
map layers** to turn A-scopes, Z-scopes, ESM-scopes and flight tracks on or off.
Changes require an audit reason and survive restart. Reload an already-open map
after changing a setting. Display switches do not publish an intake or expose
restricted sources. New RadarFilm sources start unpublished, maintainer-only,
and off on the map. Ordinary users see only approved sources they may access.

Observation points and RIGGS station symbols use solid fills without white
outlines. RIGGS reference observations retain their separate scientific status.

The exact acquisition, integration, deployment and acceptance state is recorded
in `deployment/autonomy/reports/2026-10-23-radarfilm-handoff.md`; the operator
procedure is `deployment/radarfilm_intake_runbook.md`.


### Downloading scope previews

Each available A, Z or ESM image in the observation popup and right panel has a small **PNG** download button. It saves the displayed preview, with survey, year when known, flight, CBD, scope and catalog identity in its filename. For multiple matching scans, choose the source first; the download follows that selection. Downloads use the same authenticated image access as viewing. These are preview PNGs; the original scans are TIFFs. The existing approximate-window/printed-CBD scientific caution still applies.


### Flight segments and larger scope previews

In **Browse radar catalog**, expand **Flight segments · CBD order** to inspect the current page of segments. Selecting a segment highlights its available navigation track; clicking a mapped segment highlights the matching row when it is on the page. The view uses CBD order, not time, and labels page-local gaps, overlaps, descending CBD ranges and missing navigation. It does not infer tracks for unplaced files. It shows up to 50 files; use existing filters and page controls for more. Northern RadarFilm records remain accessible in the authorized catalog/API but are not drawn on the Antarctic EPSG:3031 map. A north-polar view is still pending.

Each scope card has **Enlarge** for the selected PNG at full display size, **PNG** to download it, and **Image source details** for its file/catalog identity and alignment status. Enlarge opens a new browser tab; it does not open the original TIFF or establish exact frame/CBD calibration. If the candidate list is truncated, a notice directs you to the catalog for the remaining scans.


### Source-directed film frames

Some legacy filenames list CBD bounds in ascending order even when the film runs backward. Supported source strips now use exact-original matches and observed caption positions to select a centered frame in the original direction. These cards say **Source-directed frame window**; source details include the original SHA-256. Missing mapped captions are reported as unavailable without substituting a neighbor. Other strips continue to say **Approximate window** until separately mapped. Source-directed framing does not establish independently reviewed scientific calibration.


### Adaptive film previews

A, Z and ESM share source-bound frame alignment when the original and its caption layout can be confirmed. The map popup and right panel display the available scope types. After an unsuccessful alignment attempt, “CBD alignment needs review” replaces the uncertain frame and download link; supported full scans remain in the image catalog. This is display alignment, not scientific calibration. Flights and stations use their own navigation behavior. Some Greenland originals are RGB TIFFs and require a dedicated display adapter before preview support. Collection-wide alignment and copying run independently and may still be in progress.


### Checked and sequence-inferred film captions

Scope previews now distinguish directly checked printed flight/CBD labels from sequence-inferred positions. Stable interpolation or bounded extrapolation requires at least four checked captions in the same original. Inferred previews identify their method and anchors, and their PNG names include`-inferred`. A numbering conflict or insufficient anchors leaves the preview unavailable for review; the image catalog retains full supported scans. Automatic neural/OCR readings remain research proposals until checked. Display inference is not scientific calibration.


## CryoStack Scanner previews and learning (2026-10-23)

Select an observation to compare the available A-scope, Z-scope and ESM images at that observation's CBD. There is one card per available scope, with Enlarge and PNG controls. The short label distinguishes checked captions, inference, machine reads and approximate windows. Approximate windows remain useful quicklooks but do not certify the printed CBD. Full strips, alternatives and original caption details are collapsed under image source details. Visible previews check for improved map evidence every 45 seconds and retain your selected source. Known missing physical frames cannot be replaced by machine predictions. Scientific calibration remains a separate step.

The Control Center's Scanner page (/control/scanner) is grouped immediately under Frozen Legacies in the Applications navigation. Its overview shows verified archive objects, available collections, pending reviews and scan-batch progress. Review captions, Learning workspace, Evaluation and Processing links lead to the relevant section. Benchmark detail is expandable; review forms open within each crop card. Who can do what follows Frozen Legacies access: `scanner.view` (assigned developers and maintainers, admins, owners) opens the page and film context; `scanner.review` (maintainers, admins, owners, and any account — for example a student — granted it in Roles & access) records reviews and film metadata; `scanner.administer` (maintainers, admins, owners) refreshes the review set and changes review settings; only owners control Scanner runs. More images are potential training examples; only checked, source-bound captions enter the supervised corpus. The current candidate scored 19/20 heldout captions on two Flight 138 strips, which does not establish accuracy for other flights, ESM or Greenland.

The **Source-bound review queue** on that page shows unresolved printed-caption crops without displaying the Scanner's guesses. Maintainers, admins and owners can save a checked seven-digit A/Z caption after reading the pixels, or mark a case for specialist review. A checked caption is refused when its flight or CBD disagrees with the exact source. ESM examples are specialist-only while their longer and irregular field formats remain unvalidated. Saving a review records evidence and an audit reason; it does not retrain a model, publish a map, or certify scientific calibration.

Popup image requests now start after the popup is revealed and positioned. Primary preview images load eagerly in both views. Opening the second view within ten seconds can reuse the exact flight/CBD metadata from the first; the 45-second evidence refresh remains active. A refreshed browser loads the revised scripts through versioned asset URLs.

### Data layers on the map

Open **Layers → Data** at the top right to show or hide A-scope, Z-scope and ESM images, observation points, flight tracks, catalog image coverage, or an individual collection. Image-type switches update both popup and right-panel cards immediately and retain your chosen source. Shared observation points remain separate from image types. Catalog image coverage appears only where navigation exists; switching a layer on cannot create a location or bypass a dataset filter.

The switches change your view only. They preserve scientific filters, are remembered within the tab and are included when you copy the view link. **Show all** restores local visibility; your dataset/flight/CBD filters still apply. Control Center continues to manage shared dataset availability and publication. Press Escape or click outside to close the menu.

### Browse Scanner review cases

In Control Center → Frozen Legacies → CryoStack Scanner, choose a **Source family** and use **Next cases / Previous** to inspect later crops without first labeling earlier ones. The balanced view shows up to four pending crops per family; a specific family shows up to eight per page. Saving a review returns to that family/page. Page numbers adjust as the queue changes.

Checked and specialist totals include only decisions that still match the current source, crop and queue report. A changed crop returns to pending while its older review remains in the audit history. Neither paging nor saving reviews retrains the model or publishes a map.

### Collection switches while browsing the radar catalog

The map's **Layers → Data → Collections in this map** list follows the coverage currently loaded from the catalog. Its counts describe loaded map records, rather than the whole archive. A hidden collection stays hidden when you return to it after changing catalog pages or filters. **Show all** restores your local visibility choices; shared dataset access and scientific filters still apply. Northern collections remain in catalog results but are not placed on the Antarctic map. Reload an existing page to receive the updated controls.

### Independent Scanner evaluation

In **Control Center → Frozen Legacies Scanner**, choose **Review set → Independent evaluation · Flight141 A**, then **View cases**. This sample contains46 A-scope crops from23 Flight141 originals; it does not represent Z-scopes, ESM or Greenland. Read the printed digits without seeing machine guesses. Maintainers can record checked captions or flag a specialist case; developers have read-only access. Evaluation decisions are stored separately and cannot be exported as training candidates. The family filter, page links and Refresh retain your selected set. Switch back to **Learning review** for the existing A/Z/ESM correction queue. Neither review action trains a model or updates the map automatically.


### Image and regional controls

The new **Image type** filter in Scientific filters offers A-scopes, Z-scopes or ESM independently of Review state. It filters available source images and observations whose flight/CBD intervals have that image family; it does not confirm the printed CBD. Clearing it restores all available image types.

Regional visibility moves from the map to **Control Center → Frozen Legacies → Map regions**. Ross Ice Shelf is the initial enabled region. Maintainers, administrators and developers can enable All Antarctica or add geographic windows and record a reason. Reload an open map after saving. Image tracks come from source navigation; files without coordinates remain available in the catalog. ESM has 242 located Antarctic records, including 32 within the Ross display boundary in the checked snapshot, and 1,065 unlocated records.

The Image type filter and regional controls are available in the deployed application. The map reports the active region and filters; data outside that region remain in their source collections.


## Complete frames and crop alignment

A strip can start or end with an incomplete frame. Dividing its total width by
its CBD count can produce half of two frames. Where source-bound complete-frame
geometry is available, display estimates use those detected bounds and exclude
partial edge frames. This changes the preview crop only, not measurements,
coordinates or the original TIFF. Geometry and source-order matching do not
independently verify a printed CBD or scientific calibration.

The Flight 143 source strip covering CBDs 635–646 now has such geometry; CBD 635
was checked visually against its printed label. Other strips may still use
approximate windows. Read the caption before scientific use, expand **Image
source details** to inspect the full strip, and report the flight/CBD/source if
a preview crosses a frame boundary. Missing physical frames are never replaced
with a neighbouring frame. A collection-wide crop audit is not implied by this
source-specific correction.


### Whole film and film metadata (Film review)

**Full film context** (the *2. Film context* tab of a review case) and the
**Film review** page (*Film review: whole film & metadata · Priority flights*)
open the complete source film of any cataloged Frozen Legacies TIFF, not only
review crops:

* **Fit film** shows the whole film from its first to its last column. Like
  TERRA's compressed view, a long film is compressed along its length but still
  fills the viewer's height; zoom in and it returns to its true aspect.
* Drag to pan; scroll (or pinch) to zoom at the pointer; shift-scroll or a
  horizontal swipe pans; **＋ / −**, **Reset view** and the arrow keys work too.
  The strip above the viewer is the whole film with the visible window in blue;
  click or drag it to move. **Review position** returns to the caption under
  review (outlined in amber).
* Only the visible part is loaded, as image tiles at the resolution the zoom
  needs; the TIFF itself is never downloaded.

The **source family** (A Scope, Z Scope, ESM) is evidence, not a constraint: an
ESM stretch inside an "A-scope" collection opens like any other film, so it can
be corrected.

**CBD direction.** The film header shows how printed CBD numbers run across
the screen, from one orientation rule used everywhere (viewer, previews, maps):

* **A scope — CBD direction: Left → Right.** CBD increases as you move right.
* **Z scope — CBD direction: Right → Left.** CBD increases toward the left; the
  sequence starts at the right edge.
* **ESM — Unresolved** until printed captions are verified for the film or a
  reviewed segment records its edge CBDs.

The order of the catalog's two CBD fields never decides direction (the older
SPRI catalog stores the smaller number first). Both rules were verified against
54 operator-read printed captions on A and Z originals. When the direction or
location cannot be established — ESM without a reviewed direction, or an
upstream left/right reading that contradicts the A/Z rule (in an audit these
were almost always ESM film labelled A, or a misread CBD range) — the film
shows **Location window unavailable pending metadata review**: no CBD is derived
and no approximate window is drawn, never a mirrored one. A reviewer's
confirmed segment restores it.

When a printed caption read on the film **conflicts with the catalog
Flight/CBD** — a different Flight, or a printed CBD outside the catalog range —
the film shows **Location withheld: printed caption conflicts with catalog
metadata** and the printed readings that conflict. Its map track, availability
interval and approximate windows are withheld; the catalog record, its
metadata, its stored navigation and the raw printed evidence are all kept, and
the film stays open for review. Nothing is corrected automatically. A *Verified*
film review (Flight and left/right edge CBDs read on the film) resolves the
conflict: if it confirms the catalog values the map location returns; if it
records different values the location stays withheld until navigation is
rebuilt for the reviewed identity. The review is audited like every metadata
field, so the earlier state stays in the history.

With `scanner.review` you can record **reviewed metadata** beside the film:
first/last frame, scope type (A Scope, Z Scope, ESM, Unknown / Needs Review),
frequency, flight, date, the CBD printed at the film's **left edge** and at its
**right edge**, status (Verified, Needs Review, Junk or No usable Flight/CBD information — one at a time;
*Verified* needs a known scope, the flight and the edge CBDs) and notes. Edge
CBDs that reverse the A/Z direction are refused: check the scope, or record a
mixed segment. Click a caption marker (or turn on *Add a CBD position by
clicking the film*) to record the **reviewed CBD** of one position. Each field
shows its source value; the CBD of a position is derived from the film's
direction only when the number of captions matches the range — machine
readings stay hidden.

**Caption & identity.** Record what is printed, as stretches of the film
(segments; the whole film by default, or *Use visible columns* for part of a
film that mixes scopes or caption layouts):

* **Raw caption** — type one caption exactly as printed. It is always kept.
  A recognized layout (grammar) is only a *proposed reading*; it becomes a
  verified record only when you record it as *Valid Flight / CBD*. The
  interpretation is shown beside it with its evidence status:
  `FFF CCCC` (Flight, CBD); `MMMM FFF CCCC` (mode, Flight, CBD);
  `MMMMF FCCCC`, printed as two five-digit groups such as `32003 13042`
  (mode 3200, Flight 31, CBD 3042 — the same row with the Flight's leading zero
  dropped, confirmed against another reel of the same flight); and
  `DDMMYY HHMMSS` (date and time; no Flight/CBD).
* **Caption class** — *Valid Flight / CBD* (enter the Flight and the left- and
  right-edge CBDs; the raw caption must agree), *Raw fields, interpretation
  unresolved* (shown as “Possible mode / Flight / CBD structure — not yet
  verified”), *Mixed / transition segment*, or **No usable Flight/CBD
  information**, a one-click reviewer state.
* Recording segments is **not enabled in this release**; the panel shows any
  existing segments read-only until the segment store's migration is approved.
  Film-level review works now through **Film metadata**: *Status → No usable
  Flight/CBD information* (also a one-click button in the panel), or
  *Status → Verified* with the Flight and the left/right edge CBDs read on the
  film. A Verified review confirms the film's direction and restores its
  location window; both are audited and reversible like every metadata field.
* Segments of one film cannot overlap. Every change is a new audited revision
  (reviewer, time, reason, the revision it supersedes); **Retract** undoes a
  segment, itself as an audited revision. The film's source metadata is never
  rewritten.

**Map eligibility.** The header shows *Map: eligible* or *Map: withheld* with
the reasons. A film is drawn on maps, spatial search and exports only with a
real Flight, a usable CBD range (not collapsed to one value, not wider than a
film segment can carry), navigation built from that identity, and no
unresolved or “No usable Flight/CBD” review. Scope is not a criterion: an ESM
film with a valid Flight/CBD and navigation is eligible. Withheld films stay in
the catalog and reviewable.

Source files and catalog values are never changed. Every correction is stored as
its own audited event (source value, reviewed value, reviewer, time, reason) and
is reversible: **revert** returns a field to its source value. Corrections other
than notes need a short reason. *Source says A Scope · Review says ESM* marks a
reviewed scope change in the film header and the film list.

**Priority flights** — F125, F126, F127, F128, F137, F138, F141, F143, F103,
F107, F114 and F115 — lead the Film review page and can be selected in caption
review with *Priority flights only*. This is a review-priority layer; source
order is unchanged. Caption-review items exist only where the Scanner reader has
run (currently Flights 138 and 141); every cataloged film of the other priority
flights can be reviewed at film level.

**Greenland** is excluded from the active review workflow by default. With
`scanner.administer`, *Review dataset availability → Include Greenland dataset*
(with a reason, audited) brings Greenland films and review items back. Turning
it off hides them from the queue and film selection; no Greenland data is
changed or deleted.


## Scanner Identity Review and Naming Status

Scanner can use verified RadarFilm metadata and the existing bounded caption readers to identify actual flight/CBD endpoints. The uniform target is `F<actual-flight>-C<actual-start>_C<actual-end>-S<source-id>.tiff`, for example `F123-C0120_C0131-S8781.tiff` (format illustration, not an identity assertion for S8781). Printed CBD order is retained. A cadence, equal file size, an engine prefix or a placeholder name is not evidence. S8781 metadata corroborates actual flight125/CBD120–131; S2138 remains unresolved and must not be called flight1111.

**Naming is OFF.** No real archive rename is claimed. Exact-file picker processing does not require an invented old reel name; unresolved actual identity remains unknown and unlocated. Metadata conflicts/missing endpoints go to OCR/review. Only an exact-byte, current-version, fully verified already-correct metadata identity may skip naming OCR; that does not claim OCR ran or approve science.

In **Control Center → Frozen Legacies → CryoStack Scanner**, identity acceptance/correction requires source access and `scanner.review`. An authorized ordinary/student reviewer can change a reviewed basename; changing its parent/path additionally requires a trusted project developer/maintainer/admin/owner role plus `app.develop` and `scanner.review`. Ownership of a file/workspace alone grants no path privilege. Retry requires `scanner.administer`. The server derives roles; request flags cannot grant them. **Reason for this change *** is required (8–500 trimmed characters for identity actions), including privileged changes; the human reason and exact source evidence remain in the audit history. Film metadata/position/segment/settings retain their own four-character reason minimum; caption review requires eight.

Changes enter the journaled pipeline; reviewing metadata never directly renames a TIFF or publishes scientific products. Before activation, root must qualify all overlapping source readers, their actual live adoption and the dataset filesystem, then conduct a separately authorized real rename pilot. Review and production catalogues may lease the same CEDAR files through different databases; this implementation is not a global lease service. For a blocked or interrupted operation, preserve the evidence and report the source/catalogue ID, displayed reason and job/journal ID; do not manually rename archive files. Operator recovery details are in the Developer Guide.
