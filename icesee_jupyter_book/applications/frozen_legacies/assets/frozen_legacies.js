 /* ============================================================
 * Frozen Legacies
 * frozen_legacies.js
 *
 * Application entry point.
 *
 * This file only orchestrates:
 *
 *   1. layers
 *   2. map
 *   3. data
 *   4. UI
 *
 * No projection definitions.
 * No OpenLayers styles.
 * No fetch implementation.
 * No camera implementation.
 * ============================================================ */


document.addEventListener(
  "DOMContentLoaded",
  async () => {

    const makeLegendDraggable = () => {
      const legend = document.querySelector(".fl-map-legend");
      const frame = document.querySelector(".fl-map-shell");
      if (!legend || !frame) return;
      legend.setAttribute("aria-label", "Map legend. Drag to reposition.");
      let state = null;
      legend.addEventListener("pointerdown", event => {
        if (event.button !== 0 || event.target.closest("input, button, a")) return;
        const legendRect = legend.getBoundingClientRect();
        state = {x: event.clientX - legendRect.left, y: event.clientY - legendRect.top};
        legend.setPointerCapture(event.pointerId);
        event.preventDefault();
      });
      legend.addEventListener("pointermove", event => {
        if (!state) return;
        const frameRect = frame.getBoundingClientRect();
        const x = Math.max(0, Math.min(frameRect.width - legend.offsetWidth,
          event.clientX - frameRect.left - state.x));
        const y = Math.max(0, Math.min(frameRect.height - legend.offsetHeight,
          event.clientY - frameRect.top - state.y));
        Object.assign(legend.style, {left: `${x}px`, top: `${y}px`, right: "auto", bottom: "auto"});
      });
      const finish = event => {
        if (!state) return;
        state = null;
        if (legend.hasPointerCapture(event.pointerId)) legend.releasePointerCapture(event.pointerId);
      };
      legend.addEventListener("pointerup", finish);
      legend.addEventListener("pointercancel", finish);
    };

    makeLegendDraggable();

    const logPrefix =
      "[FrozenLegacies]";


    try {

      console.log(
        `${logPrefix} starting...`
      );


      // ========================================================
      // 1. Create sources and layers
      // ========================================================

      const layerBundle =
        FrozenLegaciesLayers.create();


      console.log(
        `${logPrefix} layers created`
      );


      // ========================================================
      // 2. Create EPSG:3031 map
      // ========================================================

      const mapState =
        FrozenLegaciesMap.create({

          target:
            "frozen-legacies-map",

          layers:
            layerBundle.mapLayers

        });


      const map =
        mapState.map;


      const projection =
        mapState.projection;


      console.log(
        `${logPrefix} map created`,
        projection.getCode()
      );


      // ========================================================
      // 3. Attach map overlays
      // ========================================================

      FrozenLegaciesLayers
        .attachOverlays(
          map,
          layerBundle
        );


      // ========================================================
      // 4. Load Frozen Legacies data
      // ========================================================

      const data =
        await FrozenLegaciesData.load({

          projection,

          sources:
            layerBundle
              .sources
              .frozen

        });


      console.log(
        `${logPrefix} data loaded`
      );


      console.log(
        `${logPrefix} datasets:`,
        data.catalog?.datasets?.length ?? 0
      );


      console.log(
        `${logPrefix} flights:`,
        data.flightFeatures.length
      );


      console.log(
        `${logPrefix} observations:`,
        data.observationFeatures.length
      );

      const riggsToggleRow = document.getElementById("fl-riggs-toggle-row");
      const riggsToggle = document.getElementById("fl-riggs-toggle");
      const riggsProvenance = document.getElementById("fl-riggs-provenance");
      if (data.riggs?.available && data.riggsFeatures.length) {
        riggsToggleRow.hidden = false;
        riggsToggle.addEventListener("change", () => {
          FrozenLegaciesLayers.setVisible(layerBundle.layers.riggs, riggsToggle.checked);
        });
        const summary = data.riggs.summary;
        const provenance = data.riggs.metadata.citation_pending
          ? "citation pending · provisional context only · not publication eligible"
          : data.riggs.metadata.citation;
        riggsProvenance.textContent =
          `${summary.stations} independent stations · ${summary.seismic} seismic · ` +
          `${summary.radar} radar · ${provenance}`;
        riggsProvenance.hidden = false;
      }

      const mapSummary = document.getElementById("fl-map-summary");
      if (mapSummary) {
        const datasetCount = data.catalog?.datasets?.length ?? 0;
        mapSummary.textContent =
          `${data.flightFeatures.length.toLocaleString()} flights · ` +
          `${data.observationFeatures.length.toLocaleString()} observations · ` +
          `${datasetCount.toLocaleString()} datasets`;
      }

      const coordinateReadout = document.getElementById("fl-map-coordinate");
      if (coordinateReadout) {
        map.on("pointermove", event => {
          const lonLat = FrozenLegaciesMap.toLonLat(event.coordinate);
          const longitude = Number(lonLat[0]);
          const latitude = Number(lonLat[1]);
          if (!Number.isFinite(longitude) || !Number.isFinite(latitude) || latitude > -55) {
            coordinateReadout.textContent = "Outside Antarctic polar domain";
            return;
          }
          const latHemisphere = latitude < 0 ? "S" : "N";
          const lonHemisphere = longitude < 0 ? "W" : "E";
          coordinateReadout.textContent =
            `${Math.abs(latitude).toFixed(3)}° ${latHemisphere} · ` +
            `${Math.abs(longitude).toFixed(3)}° ${lonHemisphere}`;
        });
      }


      // ========================================================
      // 5. Initialize application UI
      // ========================================================

      const ui =
        FrozenLegaciesUI.initialize({

          map,

          data,

          layers:
            layerBundle

        });


      // ========================================================
      // 6. Establish initial state
      // ========================================================

      if (!ui.restoreObservationSelection()) {
        ui.showAllFlights();
      }


      // ========================================================
      // 6b. Radar workspace (Map / Manual / Automatic)
      // ========================================================

      if (
        window.FrozenLegaciesRadar
      ) {

        window.FrozenLegaciesRadar.initialize({

          map,

          ui,

          data

        });

      }


      // ========================================================
      // 7. Expose useful state for development/debugging
      // ========================================================

      window.FrozenLegaciesApp = {

        map,

        view:
          mapState.view,

        projection,

        layers:
          layerBundle,

        data,

        ui

      };

      if (
        window.CryoStackAccount
      ) {

        window.CryoStackAccount.mount(
          "#cryostack-account-slot"
        );

      }

      console.log(
        `${logPrefix} ready.`
      );

    }


    catch (
      error
    ) {

      console.error(
        `${logPrefix} initialization failed:`,
        error
      );


      const panel =
        document.getElementById(
          "selected-record"
        );


      if (
        panel
      ) {

        panel.innerHTML = `

          <div
            class="fl-app-error"
          >

            <strong>
              Frozen Legacies failed to initialize.
            </strong>

            <span>
              ${escapeHtml(
                error?.message ||
                String(error)
              )}
            </span>

            <small>
              Open the browser developer console for details.
            </small>

          </div>
        `;

      }

    }

  }
);


/* ============================================================
 * Small safe HTML helper
 * ============================================================ */

function escapeHtml(
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
