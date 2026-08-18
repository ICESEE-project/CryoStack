/* ============================================================
 * Frozen Legacies
 * ui.js
 *
 * Owns:
 *   - flight dropdown
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
 * Empty observation state
 * ------------------------------------------------------------ */

function renderEmptyObservation() {

  const container =
    getSelectedRecordElement();


  if (!container) {
    return;
  }


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
          Click a point on the Antarctic map to inspect
          the LYRA-derived radar record.
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
 * Observation media
 * ------------------------------------------------------------ */

function observationImageUrl(
  properties
) {

  /*
   * Keep this flexible because the final LYRA/radar image
   * metadata may use a different field name.
   */

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


  /*
   * Until images are available, keep a deliberate placeholder.
   * This prevents the panel from looking unfinished.
   */

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
        src="${imageUrl}"
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
  feature
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

      <!-- ================================================
           Observation identity
           ================================================ -->

      <div class="fl-record-header">

        <div>

          <div class="fl-record-eyebrow">
            SELECTED OBSERVATION
          </div>

          <div class="fl-record-title">
            ${title}
          </div>

          <div class="fl-record-subtitle">
            Flight ${properties.flight ?? "—"}
            ·
            CBD ${properties.cbd ?? "—"}
          </div>

        </div>


        <div
          class="fl-record-status"
          style="
            --fl-record-status-color:
            ${echoColor};
          "
        >
          ${echo}
        </div>

      </div>


      <!-- ================================================
           Radar media
           ================================================ -->

      ${
        renderObservationMedia(
          properties
        )
      }


      <!-- ================================================
           Location
           ================================================ -->

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


      <!-- ================================================
           LYRA-derived quantities
           ================================================ -->

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


      <!-- ================================================
           Provenance
           ================================================ -->

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
                properties._source_file ??
                "Frozen Legacies"
              }
            </strong>

          </div>


          <div>

            <span>
              Frame
            </span>

            <strong>
              ${
                properties.frame_idx ??
                "—"
              }
            </strong>

          </div>

        </div>

      </div>

    </div>
  `;

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


  /*
   * Preserve the first "All flights" option.
   */

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
 * Show all flights
 * ------------------------------------------------------------ */

function showAllFlights({
  map,
  data,
  layers
}) {

  if (
    !map ||
    !data ||
    !layers
  ) {
    return;
  }


  /*
   * Remove highlighted-flight clone.
   */

  layers
    .sources
    .frozen
    .selectedFlight
    .clear(
      true
    );


  /*
   * Restore normal flight style.
   */

  layers
    .layers
    .flights
    .setStyle(
      FrozenLegaciesStyles
        .defaultFlight()
    );


  /*
   * Restore all observations.
   */

  layers
    .layers
    .observations
    .setStyle(
      feature =>
        FrozenLegaciesStyles
          .observation(
            feature
          )
    );


  FrozenLegaciesMap.resetView(
    map,
    {
      duration:
        400
    }
  );


  renderEmptyObservation();

}


/* ------------------------------------------------------------
 * Select one flight
 * ------------------------------------------------------------ */

function selectFlight({
  map,
  data,
  layers,
  flightNumber,
  zoom = true
}) {

  if (
    !map ||
    !data ||
    !layers
  ) {
    return;
  }


  const normalized =
    FrozenLegaciesData
      .normalizeFlightValue(
        flightNumber
      );


  if (
    !normalized ||
    normalized === "all"
  ) {

    showAllFlights({
      map,
      data,
      layers
    });


    return;

  }


  const selectedFeature =
    FrozenLegaciesData
      .getFlight(
        data,
        normalized
      );


  if (
    !selectedFeature
  ) {

    console.warn(
      "[FrozenLegacies] flight not found:",
      normalized
    );


    return;

  }


  /*
   * Highlight source gets its own clone.
   *
   * This avoids moving the real feature between sources.
   */

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


  /*
   * Fade all base flight tracks.
   */

  layers
    .layers
    .flights
    .setStyle(
      feature => {

        const featureFlight =
          FrozenLegaciesData
            .normalizeFlightValue(
              feature.get(
                "flight"
              )
            );


        /*
         * Selected track is already drawn
         * in the highlight layer.
         */

        if (
          featureFlight ===
          normalized
        ) {
          return null;
        }


        return FrozenLegaciesStyles
          .fadedFlight();

      }
    );


  /*
   * Show observations only for the selected flight.
   */

  layers
    .layers
    .observations
    .setStyle(
      feature => {

        const featureFlight =
          FrozenLegaciesData
            .normalizeFlightValue(
              feature.get(
                "flight"
              )
            );


        if (
          featureFlight !==
          normalized
        ) {
          return null;
        }


        return FrozenLegaciesStyles
          .observation(
            feature
          );

      }
    );


  /*
   * Synchronize dropdown.
   */

  const select =
    getFlightSelectElement();


  if (
    select &&
    select.value !==
    normalized
  ) {

    select.value =
      normalized;

  }


  /*
   * Camera belongs to map.js.
   */

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
 * Bind flight dropdown
 * ------------------------------------------------------------ */

function bindFlightSelector({
  map,
  data,
  layers
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
          layers
        });

      }

      else {

        selectFlight({
          map,
          data,
          layers,

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
  layers
}) {

  map.on(
    "singleclick",
    event => {

      /*
       * Observations take precedence over
       * flight-line selection.
       */

      const observation =
        observationAtPixel(
          map,

          layers
            .layers
            .observations,

          event.pixel
        );


      if (observation) {

        renderObservation(
          observation
        );


        const flight =
          FrozenLegaciesData
            .normalizeFlightValue(
              observation.get(
                "flight"
              )
            );


        if (flight) {

          selectFlight({
            map,
            data,
            layers,

            flightNumber:
              flight,

            /*
             * Do not zoom again merely because
             * the user clicked an observation.
             */
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

        const flight =
          FrozenLegaciesData
            .normalizeFlightValue(
              flightFeature.get(
                "flight"
              )
            );


        if (flight) {

          selectFlight({
            map,
            data,
            layers,

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


  populateFlightSelector(
    data.flightNumbers
  );


  renderEmptyObservation();


  bindFlightSelector({
    map,
    data,
    layers
  });


  bindMapClick({
    map,
    data,
    layers
  });


  bindPointerCursor({
    map,
    layers
  });


  return {

    showAllFlights:
      () =>
        showAllFlights({
          map,
          data,
          layers
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

          flightNumber,

          zoom:
            options.zoom !== false
        }),

    showObservation:
      renderObservation

  };

}


/* ------------------------------------------------------------
 * Public API
 * ------------------------------------------------------------ */

window.FrozenLegaciesUI = {

  initialize:
    initializeFrozenLegaciesUI,

  populateFlightSelector,

  renderObservation,

  renderEmptyObservation

};