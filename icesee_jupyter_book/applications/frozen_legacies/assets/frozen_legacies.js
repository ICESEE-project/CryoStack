document.addEventListener(
  "DOMContentLoaded",
  async () => {

    // ============================================================
    // Antarctic Polar Stereographic
    // ============================================================

    proj4.defs(
      "EPSG:3031",
      "+proj=stere " +
      "+lat_0=-90 " +
      "+lat_ts=-71 " +
      "+lon_0=0 " +
      "+x_0=0 " +
      "+y_0=0 " +
      "+datum=WGS84 " +
      "+units=m " +
      "+no_defs"
    );

    ol.proj.proj4.register(proj4);


    const antarcticProjection =
      ol.proj.get("EPSG:3031");


    antarcticProjection.setExtent([
      -3333134,
      -3333134,
       3333134,
       3333134
    ]);


    // ============================================================
    // Styles
    // ============================================================

    const defaultFlightStyle =
      new ol.style.Style({
        stroke:
          new ol.style.Stroke({
            color:
              "rgba(8, 108, 153, 0.72)",

            width: 2
          })
      });


    const selectedFlightStyle =
      new ol.style.Style({
        stroke:
          new ol.style.Stroke({
            color:
              "#ff8a1f",

            width: 5
          })
      });


    function observationStyle(
      feature
    ) {

      const status =
        String(
          feature.get(
            "echo_status"
          ) || ""
        ).toLowerCase();


      let color =
        "#8b5cf6";


      if (
        status === "good"
      ) {
        color =
          "#22c55e";
      }

      else if (
        status === "no_bed"
      ) {
        color =
          "#ef4444";
      }

      else if (
        status === "weak_bed"
      ) {
        color =
          "#f59e0b";
      }


      return new ol.style.Style({
        image:
          new ol.style.Circle({
            radius: 4,

            fill:
              new ol.style.Fill({
                color
              }),

            stroke:
              new ol.style.Stroke({
                color:
                  "#ffffff",

                width:
                  1
              })
          })
      });
    }


    // ============================================================
    // Base map
    // ============================================================

    /*
     * Start simple.
     *
     * We deliberately DO NOT use OSM here because OSM tiles
     * are Web Mercator and are not appropriate as our Antarctic
     * polar base layer.
     *
     * Next we can add an EPSG:3031 Antarctic raster/WMS layer.
     */

    const backgroundLayer =
      new ol.layer.Vector({
        source:
          new ol.source.Vector(),

        style:
          new ol.style.Style({
            fill:
              new ol.style.Fill({
                color:
                  "#d7eef5"
              })
          })
      });


    // ============================================================
    // Flight layers
    // ============================================================

    const flightSource =
      new ol.source.Vector();


    const flightLayer =
      new ol.layer.Vector({
        source:
          flightSource,

        style:
          defaultFlightStyle
      });


    const selectedFlightSource =
      new ol.source.Vector();


    const selectedFlightLayer =
      new ol.layer.Vector({
        source:
          selectedFlightSource,

        style:
          selectedFlightStyle
      });


    // ============================================================
    // Observation layer
    // ============================================================

    const observationSource =
      new ol.source.Vector();


    const observationLayer =
      new ol.layer.Vector({
        source:
          observationSource,

        style:
          observationStyle
      });


    // ============================================================
    // Map
    // ============================================================

    const map =
      new ol.Map({

        target:
          "frozen-legacies-map",

        layers: [
          backgroundLayer,
          flightLayer,
          selectedFlightLayer,
          observationLayer
        ],

        view:
          new ol.View({

            projection:
              antarcticProjection,

            center: [
              0,
              0
            ],

            zoom:
              1.9,

            minZoom:
              1,

            maxZoom:
              12,

            extent: [
              -3500000,
              -3500000,
               3500000,
               3500000
            ]
          }),

        controls:
          ol.control.defaults.defaults({
            rotate:
              false
          }).extend([
            new ol.control.ScaleLine({
              units:
                "metric"
            })
          ])
      });


    // ============================================================
    // Data
    // ============================================================

    try {

      const [
        flightsResponse,
        observationsResponse
      ] =
        await Promise.all([

          fetch(
            "/frozen-legacies/data/flights.geojson"
          ),

          fetch(
            "/frozen-legacies/data/observations.geojson"
          )

        ]);


      if (
        !flightsResponse.ok
      ) {

        throw new Error(
          `Flights HTTP ${
            flightsResponse.status
          }`
        );

      }


      if (
        !observationsResponse.ok
      ) {

        throw new Error(
          `Observations HTTP ${
            observationsResponse.status
          }`
        );

      }


      const flights =
        await flightsResponse.json();


      const observations =
        await observationsResponse.json();


      // ==========================================================
      // Read WGS84 GeoJSON and project automatically to EPSG:3031
      // ==========================================================

      const geojsonFormat =
        new ol.format.GeoJSON();


      const flightFeatures =
        geojsonFormat.readFeatures(
          flights,
          {
            dataProjection:
              "EPSG:4326",

            featureProjection:
              "EPSG:3031"
          }
        );


      const observationFeatures =
        geojsonFormat.readFeatures(
          observations,
          {
            dataProjection:
              "EPSG:4326",

            featureProjection:
              "EPSG:3031"
          }
        );


      flightSource.addFeatures(
        flightFeatures
      );


      observationSource.addFeatures(
        observationFeatures
      );


      console.log(
        "FrozenLegacies flights:",
        flightFeatures.length
      );


      console.log(
        "FrozenLegacies observations:",
        observationFeatures.length
      );


      // ==========================================================
      // Initial Antarctic view
      // ==========================================================

      map
        .getView()
        .fit(
          [
            -3100000,
            -3100000,
             3100000,
             3100000
          ],
          {
            padding: [
              30,
              30,
              30,
              30
            ],

            duration:
              500
          }
        );


      // ==========================================================
      // Flight selector
      // ==========================================================

      const flightSelect =
        document.getElementById(
          "flight-select"
        );


      const flightNumbers =
        [
          ...new Set(
            observationFeatures.map(
              feature =>
                String(
                  feature.get(
                    "flight"
                  )
                )
            )
          )
        ].sort(
          (a, b) =>
            Number(a) -
            Number(b)
        );


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


        flightSelect.appendChild(
          option
        );

      }


      // ==========================================================
      // Filtering
      // ==========================================================

      function showAllFlights() {

        selectedFlightSource.clear();


        flightLayer.setStyle(
          defaultFlightStyle
        );


        observationLayer.setStyle(
          observationStyle
        );


        flightSource
          .getFeatures()
          .forEach(
            feature => {
              feature.set(
                "_hidden",
                false
              );
            }
          );


        observationSource
          .getFeatures()
          .forEach(
            feature => {
              feature.set(
                "_hidden",
                false
              );
            }
          );


        flightLayer.setStyle(
          feature => {

            if (
              feature.get(
                "_hidden"
              )
            ) {
              return null;
            }


            return defaultFlightStyle;
          }
        );


        observationLayer.setStyle(
          feature => {

            if (
              feature.get(
                "_hidden"
              )
            ) {
              return null;
            }


            return observationStyle(
              feature
            );
          }
        );


        map
          .getView()
          .fit(
            [
              -3100000,
              -3100000,
               3100000,
               3100000
            ],
            {
              padding: [
                30,
                30,
                30,
                30
              ],

              duration:
                500
            }
          );

      }


      function selectFlight(
        flightNumber
      ) {

        selectedFlightSource.clear();


        let selectedFeature =
          null;


        flightSource
          .getFeatures()
          .forEach(
            feature => {

              const selected =
                String(
                  feature.get(
                    "flight"
                  )
                ) ===
                String(
                  flightNumber
                );


              feature.set(
                "_hidden",
                false
              );


              if (
                selected
              ) {
                selectedFeature =
                  feature;
              }

            }
          );


        if (
          selectedFeature
        ) {

          selectedFlightSource.addFeature(
            selectedFeature.clone()
          );

        }


        flightLayer.setStyle(
          feature => {

            const selected =
              String(
                feature.get(
                  "flight"
                )
              ) ===
              String(
                flightNumber
              );


            if (
              selected
            ) {
              return null;
            }


            return new ol.style.Style({
              stroke:
                new ol.style.Stroke({
                  color:
                    "rgba(8,108,153,0.12)",

                  width:
                    1.5
                })
            });

          }
        );


        observationLayer.setStyle(
          feature => {

            const selected =
              String(
                feature.get(
                  "flight"
                )
              ) ===
              String(
                flightNumber
              );


            if (
              !selected
            ) {
              return null;
            }


            return observationStyle(
              feature
            );

          }
        );


        if (
          selectedFeature
        ) {

          map
            .getView()
            .fit(
              selectedFeature
                .getGeometry()
                .getExtent(),

              {
                padding: [
                  80,
                  80,
                  80,
                  80
                ],

                maxZoom:
                  8,

                duration:
                  600
              }
            );

        }

      }


      flightSelect.addEventListener(
        "change",
        () => {

          const value =
            flightSelect.value;


          if (
            value === "all"
          ) {

            showAllFlights();

          }

          else {

            selectFlight(
              value
            );

          }

        }
      );


      // ==========================================================
      // Observation click
      // ==========================================================

      map.on(
        "singleclick",
        event => {

          let selected =
            null;


          map.forEachFeatureAtPixel(
            event.pixel,

            (
              feature,
              layer
            ) => {

              if (
                layer ===
                observationLayer
              ) {

                selected =
                  feature;


                return true;
              }

            }
          );


          if (
            !selected
          ) {
            return;
          }


          const p =
            selected.getProperties();


          /*
           * Feature geometry is EPSG:3031 now.
           * Convert back to longitude/latitude for display.
           */

          const coordinate =
            ol.proj.transform(
              selected
                .getGeometry()
                .getCoordinates(),

              "EPSG:3031",

              "EPSG:4326"
            );


          document.getElementById(
            "selected-record"
          ).innerHTML = `

            <strong
              style="
                font-size:15px;
                color:#17384d;
              "
            >
              ${
                p.file_id ||
                "Radar observation"
              }
            </strong>

            <br><br>

            <strong>Flight:</strong>
            ${p.flight ?? "—"}

            <br>

            <strong>CBD:</strong>
            ${p.cbd ?? "—"}

            <br>

            <strong>Echo:</strong>
            ${p.echo_status ?? "—"}

            <br><br>

            <strong>Latitude:</strong>
            ${
              Number(
                coordinate[1]
              ).toFixed(5)
            }

            <br>

            <strong>Longitude:</strong>
            ${
              Number(
                coordinate[0]
              ).toFixed(5)
            }

            <br><br>

            <strong>
              Ice thickness:
            </strong>
            ${
              p.h_ice_m ??
              "—"
            } m

            <br>

            <strong>
              Bed SNR:
            </strong>
            ${
              p.bed_snr_dB ??
              "—"
            } dB

            <br>

            <strong>
              Surface temperature:
            </strong>
            ${
              p.T_surface_C ??
              "—"
            } °C

            <br>

            <strong>
              Reflectivity:
            </strong>
            ${
              p.R0_dB ??
              "—"
            } dB
          `;


          const flight =
            String(
              p.flight ??
              ""
            );


          if (
            flight
          ) {

            flightSelect.value =
              flight;


            selectFlight(
              flight
            );

          }

        }
      );


      // ==========================================================
      // Cursor
      // ==========================================================

      map.on(
        "pointermove",
        event => {

          const hit =
            map.hasFeatureAtPixel(
              event.pixel,
              {
                layerFilter:
                  layer =>
                    layer ===
                    observationLayer ||
                    layer ===
                    flightLayer
              }
            );


          map
            .getTargetElement()
            .style.cursor =
              hit
                ? "pointer"
                : "";

        }
      );


    }

    catch (
      error
    ) {

      console.error(
        "FrozenLegacies data load failed:",
        error
      );


      document.getElementById(
        "selected-record"
      ).innerHTML =
        `
        <strong>
          Data loading failed:
        </strong>
        <br>
        ${error.message}
        `;

    }

  }
);