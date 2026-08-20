/* ============================================================
 * Frozen Legacies
 * ui.js
 *
 * Owns:
 *   - dataset dropdown
 *   - flight dropdown
 *   - selected-dataset state
 *   - selected-flight state
 *   - observation detail panel
 *   - map click interaction
 *   - map hover cursor
 *   - filtering/highlighting
 *
 * Does NOT own:
 *   - projection
 *   - map construction
 *   - data fetching
 *   - layer construction
 * ============================================================ */


/* ------------------------------------------------------------
 * DOM helpers
 * ------------------------------------------------------------ */

function getDatasetSelectElement() {

  return document.getElementById(
    "dataset-select"
  );

}


function getFlightSelectElement() {

  return document.getElementById(
    "flight-select"
  );

}


function getSelectedRecordElement() {

  return document.getElementById(
    "selected-record"
  );

}


/* ------------------------------------------------------------
 * Dataset helpers
 * ------------------------------------------------------------ */

function normalizeDatasetValue(
  value
) {

  return FrozenLegaciesData
    .normalizeDatasetValue(
      value
    );

}


function datasetForFeature(
  feature
) {

  if (!feature) {
    return "";
  }


  return normalizeDatasetValue(
    feature.get(
      "dataset_id"
    )
  );

}


function datasetMatches(
  feature,
  datasetId
) {

  const normalizedDataset =
    normalizeDatasetValue(
      datasetId
    );


  if (
    !normalizedDataset ||
    normalizedDataset === "all"
  ) {
    return true;
  }


  return (
    datasetForFeature(
      feature
    ) === normalizedDataset
  );

}


/* ------------------------------------------------------------
 * Empty observation state
 * ------------------------------------------------------------ */

function renderEmptyObservation(
  dataset = null
) {

  const container =
    getSelectedRecordElement();


  if (!container) {
    return;
  }


  const datasetTitle =
    dataset?.title ||
    dataset?.name ||
    null;


  container.innerHTML = `
    <div class="fl-empty-selection">

      <div class="fl-empty-icon">
        ⌖
      </div>

      <div>

        <strong>
          Select a radar observation
        </strong>

        <span>
          ${
            datasetTitle
              ? `Click a point from ${escapeHtmlUI(datasetTitle)} to inspect the radar record.`
              : "Click a point on the Antarctic map to inspect a radar record."
          }
        </span>

      </div>

    </div>
  `;

}


/* ------------------------------------------------------------
 * Formatting helpers
 * ------------------------------------------------------------ */

function formatNumber(
  value,
  {
    digits = 2,
    suffix = ""
  } = {}
) {

  if (
    value === null ||
    value === undefined ||
    value === ""
  ) {
    return "—";
  }


  const number =
    Number(value);


  if (
    !Number.isFinite(number)
  ) {
    return String(value);
  }


  return (
    number.toFixed(
      digits
    ) +
    suffix
  );

}


function formatLatitude(
  value
) {

  const number =
    Number(value);


  if (
    !Number.isFinite(number)
  ) {
    return "—";
  }


  return (
    `${Math.abs(number).toFixed(5)}°` +
    (
      number < 0
        ? "S"
        : "N"
    )
  );

}


function formatLongitude(
  value
) {

  const number =
    Number(value);


  if (
    !Number.isFinite(number)
  ) {
    return "—";
  }


  return (
    `${Math.abs(number).toFixed(5)}°` +
    (
      number < 0
        ? "W"
        : "E"
    )
  );

}


/* ------------------------------------------------------------
 * Safe HTML helper
 * ------------------------------------------------------------ */

function escapeHtmlUI(
  value
) {

  return String(
    value ?? ""
  )
    .replaceAll(
      "&",
      "&amp;"
    )
    .replaceAll(
      "<",
      "&lt;"
    )
    .replaceAll(
      ">",
      "&gt;"
    )
    .replaceAll(
      '"',
      "&quot;"
    )
    .replaceAll(
      "'",
      "&#039;"
    );

}


/* ------------------------------------------------------------
 * Observation media
 * ------------------------------------------------------------ */

function observationImageUrl(
  properties
) {

  const candidates = [

    properties.image_url,

    properties.image_path,

    properties.radar_image,

    properties.echogram,

    properties.radargram

  ];


  for (
    const value
    of candidates
  ) {

    if (
      value !== null &&
      value !== undefined &&
      String(value).trim()
    ) {

      return String(
        value
      ).trim();

    }

  }


  return null;

}


function renderObservationMedia(
  properties
) {

  const imageUrl =
    observationImageUrl(
      properties
    );


  if (!imageUrl) {

    return `

      <div class="fl-radar-preview fl-radar-preview-empty">

        <div class="fl-radar-preview-icon">
          ◫
        </div>

        <div>

          <strong>
            Radar preview
          </strong>

          <span>
            Radar imagery for this observation
            will appear here.
          </span>

        </div>

      </div>
    `;

  }


  return `

    <div class="fl-radar-preview">

      <img
        src="${escapeHtmlUI(imageUrl)}"
        alt="Radar observation"
        class="fl-radar-image"
        loading="lazy"
      >

      <div class="fl-radar-image-caption">
        Radar observation
      </div>

    </div>
  `;

}


/* ------------------------------------------------------------
 * Observation panel
 * ------------------------------------------------------------ */

function renderObservation(
  feature,
  data = null
) {

  const container =
    getSelectedRecordElement();


  if (
    !container ||
    !feature
  ) {
    return;
  }


  const properties =
    feature.getProperties();


  const geometry =
    feature.getGeometry();


  let longitude =
    null;

  let latitude =
    null;


  if (
    geometry &&
    geometry.getType() === "Point"
  ) {

    const coordinate =
      FrozenLegaciesMap.toLonLat(
        geometry.getCoordinates()
      );


    longitude =
      coordinate[0];

    latitude =
      coordinate[1];

  }


  const datasetId =
    normalizeDatasetValue(
      properties.dataset_id
    );


  const dataset =
    data?.datasetIndex?.get(
      datasetId
    ) || null;


  const datasetTitle =
    dataset?.title ||
    dataset?.name ||
    datasetId ||
    "Frozen Legacies";


  const title =
    properties.file_id ||
    (
      properties.flight
        ? `Flight ${properties.flight}`
        : "Radar observation"
    );


  const echo =
    properties.echo_status ||
    "unknown";


  const echoColor =
    FrozenLegaciesStyles
      .observationStatusColor(
        echo
      );


  container.innerHTML = `

    <div class="fl-record">

      <div class="fl-record-header">

        <div>

          <div class="fl-record-eyebrow">
            SELECTED OBSERVATION
          </div>

          <div class="fl-record-title">
            ${escapeHtmlUI(title)}
          </div>

          <div class="fl-record-subtitle">
            Flight ${escapeHtmlUI(properties.flight ?? "—")}
            ·
            CBD ${escapeHtmlUI(properties.cbd ?? "—")}
          </div>

        </div>


        <div
          class="fl-record-status"
          style="
            --fl-record-status-color:
            ${echoColor};
          "
        >
          ${escapeHtmlUI(echo)}
        </div>

      </div>


      ${
        renderObservationMedia(
          properties
        )
      }


      <div class="fl-record-section">

        <div class="fl-record-section-title">
          Dataset
        </div>


        <div class="fl-record-provenance">

          <div>

            <span>
              Collection
            </span>

            <strong>
              ${escapeHtmlUI(datasetTitle)}
            </strong>

          </div>


          <div>

            <span>
              Dataset ID
            </span>

            <strong>
              ${escapeHtmlUI(datasetId || "—")}
            </strong>

          </div>

        </div>

      </div>


      <div class="fl-record-section">

        <div class="fl-record-section-title">
          Location
        </div>


        <div class="fl-record-grid">

          <div class="fl-record-item">

            <span>
              Latitude
            </span>

            <strong>
              ${formatLatitude(latitude)}
            </strong>

          </div>


          <div class="fl-record-item">

            <span>
              Longitude
            </span>

            <strong>
              ${formatLongitude(longitude)}
            </strong>

          </div>

        </div>

      </div>


      <div class="fl-record-section">

        <div class="fl-record-section-title">
          LYRA-derived quantities
        </div>


        <div class="fl-record-metrics">

          <div class="fl-record-metric">

            <span>
              Ice thickness
            </span>

            <strong>
              ${
                formatNumber(
                  properties.h_ice_m,
                  {
                    digits: 1,
                    suffix: " m"
                  }
                )
              }
            </strong>

          </div>


          <div class="fl-record-metric">

            <span>
              Bed SNR
            </span>

            <strong>
              ${
                formatNumber(
                  properties.bed_snr_dB,
                  {
                    digits: 2,
                    suffix: " dB"
                  }
                )
              }
            </strong>

          </div>


          <div class="fl-record-metric">

            <span>
              Surface temperature
            </span>

            <strong>
              ${
                formatNumber(
                  properties.T_surface_C,
                  {
                    digits: 2,
                    suffix: " °C"
                  }
                )
              }
            </strong>

          </div>


          <div class="fl-record-metric">

            <span>
              Reflectivity
            </span>

            <strong>
              ${
                formatNumber(
                  properties.R0_dB,
                  {
                    digits: 2,
                    suffix: " dB"
                  }
                )
              }
            </strong>

          </div>


          <div class="fl-record-metric">

            <span>
              Attenuation
            </span>

            <strong>
              ${
                formatNumber(
                  properties.L_atten_dB,
                  {
                    digits: 2,
                    suffix: " dB"
                  }
                )
              }
            </strong>

          </div>


          <div class="fl-record-metric">

            <span>
              Specularity
            </span>

            <strong>
              ${
                formatNumber(
                  properties.specularity,
                  {
                    digits: 3
                  }
                )
              }
            </strong>

          </div>

        </div>

      </div>


      <div class="fl-record-section">

        <div class="fl-record-section-title">
          Record provenance
        </div>


        <div class="fl-record-provenance">

          <div>

            <span>
              Source
            </span>

            <strong>
              ${
                escapeHtmlUI(
                  properties._source_file ??
                  "Frozen Legacies"
                )
              }
            </strong>

          </div>


          <div>

            <span>
              Frame
            </span>

            <strong>
              ${
                escapeHtmlUI(
                  properties.frame_idx ??
                  "—"
                )
              }
            </strong>

          </div>

        </div>

      </div>

    </div>
  `;

}


/* ------------------------------------------------------------
 * Dataset dropdown
 * ------------------------------------------------------------ */

function populateDatasetSelector(
  catalog
) {

  const select =
    getDatasetSelectElement();


  if (!select) {
    return;
  }


  select.innerHTML = `
    <option value="all">
      All datasets
    </option>
  `;


  for (
    const dataset
    of catalog?.datasets || []
  ) {

    if (!dataset?.id) {
      continue;
    }


    const option =
      document.createElement(
        "option"
      );


    option.value =
      String(
        dataset.id
      );


    option.textContent =
      dataset.title ||
      dataset.name ||
      dataset.id;


    select.appendChild(
      option
    );

  }

}


/* ------------------------------------------------------------
 * Flight dropdown
 * ------------------------------------------------------------ */

function populateFlightSelector(
  flightNumbers
) {

  const select =
    getFlightSelectElement();


  if (!select) {
    return;
  }


  select.innerHTML = `
    <option value="all">
      All flights
    </option>
  `;


  for (
    const flight
    of flightNumbers
  ) {

    const option =
      document.createElement(
        "option"
      );


    option.value =
      flight;


    option.textContent =
      `Flight ${flight}`;


    select.appendChild(
      option
    );

  }

}


/* ------------------------------------------------------------
 * Refresh flights for selected dataset
 * ------------------------------------------------------------ */

function refreshFlightSelectorForDataset({
  data,
  datasetId
}) {

  const normalizedDataset =
    normalizeDatasetValue(
      datasetId
    );


  const flights =
    FrozenLegaciesData
      .flightNumbersForDataset(
        data.raw.observations,

        normalizedDataset === "all"
          ? null
          : normalizedDataset
      );


  populateFlightSelector(
    flights
  );


  return flights;

}


/* ------------------------------------------------------------
 * Show all flights for current dataset
 * ------------------------------------------------------------ */

function showAllFlights({
  map,
  data,
  layers,
  state
}) {

  if (
    !map ||
    !data ||
    !layers
  ) {
    return;
  }


  const datasetId =
    normalizeDatasetValue(
      state?.datasetId ||
      "all"
    );


  layers
    .sources
    .frozen
    .selectedFlight
    .clear(
      true
    );


  layers
    .layers
    .flights
    .setStyle(
      feature => {

        if (
          !datasetMatches(
            feature,
            datasetId
          )
        ) {
          return null;
        }


        return FrozenLegaciesStyles
          .defaultFlight();

      }
    );


  layers
    .layers
    .observations
    .setStyle(
      feature => {

        if (
          !datasetMatches(
            feature,
            datasetId
          )
        ) {
          return null;
        }


        return FrozenLegaciesStyles
          .observation(
            feature
          );

      }
    );


  state.flightNumber =
    "all";


  const flightSelect =
    getFlightSelectElement();


  if (flightSelect) {

    flightSelect.value =
      "all";

  }


  FrozenLegaciesMap.resetView(
    map,
    {
      duration:
        400
    }
  );


  const dataset =
    datasetId !== "all"
      ? data.datasetIndex?.get(
          datasetId
        )
      : null;


  renderEmptyObservation(
    dataset
  );

}


/* ------------------------------------------------------------
 * Select one flight
 * ------------------------------------------------------------ */

function selectFlight({
  map,
  data,
  layers,
  state,
  flightNumber,
  datasetId = null,
  zoom = true
}) {

  if (
    !map ||
    !data ||
    !layers
  ) {
    return;
  }


  const normalizedFlight =
    FrozenLegaciesData
      .normalizeFlightValue(
        flightNumber
      );


  const normalizedDataset =
    normalizeDatasetValue(
      datasetId ??
      state?.datasetId ??
      "all"
    );


  if (
    !normalizedFlight ||
    normalizedFlight === "all"
  ) {

    showAllFlights({
      map,
      data,
      layers,
      state
    });


    return;

  }


  const lookupDataset =
    normalizedDataset === "all"
      ? ""
      : normalizedDataset;


  const selectedFeature =
    FrozenLegaciesData
      .getFlight(
        data,
        normalizedFlight,
        lookupDataset
      );


  if (
    !selectedFeature
  ) {

    console.warn(
      "[FrozenLegacies] flight not found:",
      normalizedDataset,
      normalizedFlight
    );


    return;

  }


  const selectedFeatureDataset =
    datasetForFeature(
      selectedFeature
    );


  /*
   * If all datasets were active and the selected flight came
   * from a particular dataset, retain that dataset identity for
   * filtering comparisons without forcing the dataset dropdown.
   */

  const effectiveDataset =
    normalizedDataset === "all"
      ? selectedFeatureDataset
      : normalizedDataset;


  const selectedSource =
    layers
      .sources
      .frozen
      .selectedFlight;


  selectedSource.clear(
    true
  );


  selectedSource.addFeature(
    selectedFeature.clone()
  );


  layers
    .layers
    .flights
    .setStyle(
      feature => {

        const featureDataset =
          datasetForFeature(
            feature
          );


        const featureFlight =
          FrozenLegaciesData
            .normalizeFlightValue(
              feature.get(
                "flight"
              )
            );


        const sameDataset =
          !effectiveDataset ||
          featureDataset ===
            effectiveDataset;


        if (
          sameDataset &&
          featureFlight ===
            normalizedFlight
        ) {
          return null;
        }


        if (
          normalizedDataset !== "all" &&
          featureDataset !==
            normalizedDataset
        ) {
          return null;
        }


        return FrozenLegaciesStyles
          .fadedFlight();

      }
    );


  layers
    .layers
    .observations
    .setStyle(
      feature => {

        const featureDataset =
          datasetForFeature(
            feature
          );


        const featureFlight =
          FrozenLegaciesData
            .normalizeFlightValue(
              feature.get(
                "flight"
              )
            );


        if (
          effectiveDataset &&
          featureDataset !==
            effectiveDataset
        ) {
          return null;
        }


        if (
          featureFlight !==
          normalizedFlight
        ) {
          return null;
        }


        return FrozenLegaciesStyles
          .observation(
            feature
          );

      }
    );


  if (state) {

    state.flightNumber =
      normalizedFlight;

  }


  const select =
    getFlightSelectElement();


  if (
    select &&
    select.value !==
      normalizedFlight
  ) {

    select.value =
      normalizedFlight;

  }


  if (zoom) {

    FrozenLegaciesMap
      .fitToFeature(
        map,
        selectedFeature,
        {
          padding:
            90,

          maxZoom:
            8,

          duration:
            500
        }
      );

  }

}


/* ------------------------------------------------------------
 * Select dataset
 * ------------------------------------------------------------ */

function selectDataset({
  map,
  data,
  layers,
  state,
  datasetId
}) {

  const normalized =
    normalizeDatasetValue(
      datasetId
    ) || "all";


  state.datasetId =
    normalized;


  state.flightNumber =
    "all";


  const datasetSelect =
    getDatasetSelectElement();


  if (
    datasetSelect &&
    datasetSelect.value !== normalized
  ) {

    datasetSelect.value =
      normalized;

  }


  refreshFlightSelectorForDataset({
    data,

    datasetId:
      normalized
  });


  showAllFlights({
    map,
    data,
    layers,
    state
  });

}


/* ------------------------------------------------------------
 * Determine observation under pixel
 * ------------------------------------------------------------ */

function observationAtPixel(
  map,
  observationLayer,
  pixel
) {

  let selectedFeature =
    null;


  map.forEachFeatureAtPixel(
    pixel,

    (
      feature,
      layer
    ) => {

      if (
        layer ===
        observationLayer
      ) {

        selectedFeature =
          feature;


        return true;

      }


      return false;

    },
    {
      hitTolerance:
        6
    }
  );


  return selectedFeature;

}


/* ------------------------------------------------------------
 * Determine flight under pixel
 * ------------------------------------------------------------ */

function flightAtPixel(
  map,
  flightLayer,
  pixel
) {

  let selectedFeature =
    null;


  map.forEachFeatureAtPixel(
    pixel,

    (
      feature,
      layer
    ) => {

      if (
        layer ===
        flightLayer
      ) {

        selectedFeature =
          feature;


        return true;

      }


      return false;

    },
    {
      hitTolerance:
        6
    }
  );


  return selectedFeature;

}


/* ------------------------------------------------------------
 * Bind dataset dropdown
 * ------------------------------------------------------------ */

function bindDatasetSelector({
  map,
  data,
  layers,
  state
}) {

  const select =
    getDatasetSelectElement();


  if (!select) {
    return;
  }


  select.addEventListener(
    "change",
    () => {

      selectDataset({
        map,
        data,
        layers,
        state,

        datasetId:
          select.value
      });

    }
  );

}


/* ------------------------------------------------------------
 * Bind flight dropdown
 * ------------------------------------------------------------ */

function bindFlightSelector({
  map,
  data,
  layers,
  state
}) {

  const select =
    getFlightSelectElement();


  if (!select) {
    return;
  }


  select.addEventListener(
    "change",
    () => {

      const value =
        select.value;


      if (
        value === "all"
      ) {

        showAllFlights({
          map,
          data,
          layers,
          state
        });

      }

      else {

        selectFlight({
          map,
          data,
          layers,
          state,

          datasetId:
            state.datasetId,

          flightNumber:
            value,

          zoom:
            true
        });

      }

    }
  );

}


/* ------------------------------------------------------------
 * Bind map click
 * ------------------------------------------------------------ */

function bindMapClick({
  map,
  data,
  layers,
  state
}) {

  map.on(
    "singleclick",
    event => {

      const observation =
        observationAtPixel(
          map,

          layers
            .layers
            .observations,

          event.pixel
        );


      if (observation) {

        const datasetId =
          datasetForFeature(
            observation
          );


        const flight =
          FrozenLegaciesData
            .normalizeFlightValue(
              observation.get(
                "flight"
              )
            );


        /*
         * Clicking a point should synchronize the explorer with
         * the observation's dataset.
         */

        if (
          datasetId &&
          state.datasetId !==
            datasetId
        ) {

          state.datasetId =
            datasetId;


          const datasetSelect =
            getDatasetSelectElement();


          if (datasetSelect) {

            datasetSelect.value =
              datasetId;

          }


          refreshFlightSelectorForDataset({
            data,
            datasetId
          });

        }


        renderObservation(
          observation,
          data
        );


        if (flight) {

          selectFlight({
            map,
            data,
            layers,
            state,

            datasetId,

            flightNumber:
              flight,

            zoom:
              false
          });

        }


        return;

      }


      const flightFeature =
        flightAtPixel(
          map,

          layers
            .layers
            .flights,

          event.pixel
        );


      if (
        flightFeature
      ) {

        const datasetId =
          datasetForFeature(
            flightFeature
          );


        const flight =
          FrozenLegaciesData
            .normalizeFlightValue(
              flightFeature.get(
                "flight"
              )
            );


        if (
          datasetId &&
          state.datasetId !==
            datasetId
        ) {

          state.datasetId =
            datasetId;


          const datasetSelect =
            getDatasetSelectElement();


          if (datasetSelect) {

            datasetSelect.value =
              datasetId;

          }


          refreshFlightSelectorForDataset({
            data,
            datasetId
          });

        }


        if (flight) {

          selectFlight({
            map,
            data,
            layers,
            state,

            datasetId,

            flightNumber:
              flight,

            zoom:
              true
          });

        }

      }

    }
  );

}


/* ------------------------------------------------------------
 * Bind pointer cursor
 * ------------------------------------------------------------ */

function bindPointerCursor({
  map,
  layers
}) {

  map.on(
    "pointermove",
    event => {

      if (
        event.dragging
      ) {
        return;
      }


      const hit =
        map.hasFeatureAtPixel(
          event.pixel,
          {
            hitTolerance:
              5,

            layerFilter:
              layer =>
                layer ===
                  layers.layers.observations ||
                layer ===
                  layers.layers.flights ||
                layer ===
                  layers.layers.selectedFlight
          }
        );


      map
        .getTargetElement()
        .style
        .cursor =
          hit
            ? "pointer"
            : "";

    }
  );

}


/* ------------------------------------------------------------
 * Complete UI initialization
 * ------------------------------------------------------------ */

function initializeFrozenLegaciesUI({
  map,
  data,
  layers
}) {

  if (
    !map ||
    !data ||
    !layers
  ) {

    throw new Error(
      "FrozenLegacies UI initialization is missing required state."
    );

  }


  const state = {

    datasetId:
      "all",

    flightNumber:
      "all"

  };


  populateDatasetSelector(
    data.catalog
  );


  refreshFlightSelectorForDataset({
    data,

    datasetId:
      state.datasetId
  });


  renderEmptyObservation();


  bindDatasetSelector({
    map,
    data,
    layers,
    state
  });


  bindFlightSelector({
    map,
    data,
    layers,
    state
  });


  bindMapClick({
    map,
    data,
    layers,
    state
  });


  bindPointerCursor({
    map,
    layers
  });


  return {

    state,


    showAllFlights:
      () =>
        showAllFlights({
          map,
          data,
          layers,
          state
        }),


    selectDataset:
      datasetId =>
        selectDataset({
          map,
          data,
          layers,
          state,
          datasetId
        }),


    selectFlight:
      (
        flightNumber,
        options = {}
      ) =>
        selectFlight({
          map,
          data,
          layers,
          state,

          datasetId:
            options.datasetId ??
            state.datasetId,

          flightNumber,

          zoom:
            options.zoom !== false
        }),


    showObservation:
      feature =>
        renderObservation(
          feature,
          data
        )

  };

}


/* ------------------------------------------------------------
 * Public API
 * ------------------------------------------------------------ */

window.FrozenLegaciesUI = {

  initialize:
    initializeFrozenLegaciesUI,

  populateDatasetSelector,

  populateFlightSelector,

  renderObservation,

  renderEmptyObservation

};