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

      ui.showAllFlights();


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