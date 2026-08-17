document.addEventListener("DOMContentLoaded", async () => {

  // ============================================================
  // Map
  // ============================================================

  const map = new maplibregl.Map({
    container: "frozen-legacies-map",

    style: {
      version: 8,

      sources: {
        osm: {
          type: "raster",

          tiles: [
            "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          ],

          tileSize: 256,

          attribution:
            "© OpenStreetMap contributors"
        }
      },

      layers: [
        {
          id: "osm",
          type: "raster",
          source: "osm",
          paint: {
            "raster-opacity": 0.72,
            "raster-saturation": -0.4
          }
        }
      ]
    },

    center: [
      0,
      -90
    ],

    zoom: 2.2,
    bearing: 0,
    pitch: 0,
    minZoom: 1.4,
    maxZoom: 12,
    canvasContextAttributes: {antialias: true}
  });

  // ===========================================================
  // IMPORTANT: Use globe rather than web Mercator.
  // ==========================================================

  map.on(
    "style.load",
    () => {
      
      map.setProjection({
        type: "globe"
      });
    }
  );


  map.addControl(
    new maplibregl.NavigationControl(),
    "top-right"
  );

  map.addControl(
    new maplibregl.GlobeControl(),
    "top-right"
  );

  // map.addControl(
  //   new maplibregl.ScaleControl({
  //     maxWidth: 140,
  //     unit: "metric"
  //   }),
  //   "bottom-right"
  // );


  // ============================================================
  // Helpers
  // ============================================================

  /**
   * Make a LineString continuous across the ±180° antimeridian.
   *
   * Example:
   *
   *   179, -179
   *
   * becomes approximately:
   *
   *   179, 181
   *
   * rather than drawing a line across the entire world.
   */
  function unwrapCoordinates(coordinates) {

    if (!coordinates || coordinates.length === 0) {
      return [];
    }

    const result = [];

    let previousLon =
      Number(coordinates[0][0]);

    result.push([
      previousLon,
      Number(coordinates[0][1])
    ]);


    for (
      let i = 1;
      i < coordinates.length;
      i++
    ) {

      let lon =
        Number(coordinates[i][0]);

      const lat =
        Number(coordinates[i][1]);


      while (
        lon - previousLon > 180
      ) {
        lon -= 360;
      }


      while (
        lon - previousLon < -180
      ) {
        lon += 360;
      }


      result.push([
        lon,
        lat
      ]);


      previousLon = lon;
    }


    return result;
  }


  /**
   * Build a display copy of the flight GeoJSON with continuous
   * longitudes around the antimeridian.
   */
  function prepareFlightsForMap(flights) {

    return {
      type: "FeatureCollection",

      features:
        flights.features.map(
          feature => {

            if (
              feature.geometry?.type !==
              "LineString"
            ) {
              return feature;
            }


            return {
              ...feature,

              geometry: {
                ...feature.geometry,

                coordinates:
                  unwrapCoordinates(
                    feature.geometry.coordinates
                  )
              }
            };
          }
        )
    };
  }


  function fitToFlights(
    flights,
    {
      padding = 70,
      maxZoom = 5.5,
      duration = 800
    } = {}
  ) {

    const bounds =
      new maplibregl.LngLatBounds();


    flights.features.forEach(
      feature => {

        const geometry =
          feature.geometry;


        if (!geometry) {
          return;
        }


        if (
          geometry.type ===
          "LineString"
        ) {

          geometry.coordinates.forEach(
            coord => {

              if (
                Array.isArray(coord) &&
                coord.length >= 2
              ) {
                bounds.extend(coord);
              }

            }
          );

        }

      }
    );


    if (!bounds.isEmpty()) {

      map.fitBounds(
        bounds,
        {
          padding,
          maxZoom,
          duration
        }
      );

    }
  }


  function fitToFlight(
    flights,
    flightNumber
  ) {

    const feature =
      flights.features.find(
        item =>
          String(
            item.properties?.flight
          ) === String(flightNumber)
      );


    if (!feature) {
      return;
    }


    fitToFlights(
      {
        type: "FeatureCollection",
        features: [feature]
      },
      {
        padding: 100,
        maxZoom: 7,
        duration: 700
      }
    );
  }


  function flightFilter(
    flightNumber
  ) {

    return [
      "==",

      [
        "to-string",
        ["get", "flight"]
      ],

      String(flightNumber)
    ];
  }

  function resetAntarcticView() {

    map.easeTo({
      center: [
        0,
        -88
      ],

      zoom: 2.25,

      bearing: 0,

      pitch: 0,

      duration: 700
    });

  }

  function clearSelectedFlight() {

    if (
      map.getLayer(
        "frozen-flight-selected"
      )
    ) {

      map.setFilter(
        "frozen-flight-selected",
        [
          "==",
          [
            "to-string",
            ["get", "flight"]
          ],
          "__none__"
        ]
      );

    }


    if (
      map.getLayer(
        "frozen-flight-lines"
      )
    ) {

      map.setPaintProperty(
        "frozen-flight-lines",
        "line-opacity",
        0.72
      );

    }

  }


  // ============================================================
  // Data
  // ============================================================

  try {

    const [
      flightsResponse,
      observationsResponse
    ] = await Promise.all([

      fetch(
        "/frozen-legacies/data/flights.geojson"
      ),

      fetch(
        "/frozen-legacies/data/observations.geojson"
      )

    ]);


    if (!flightsResponse.ok) {

      throw new Error(
        `Flights HTTP ${flightsResponse.status}`
      );

    }


    if (!observationsResponse.ok) {

      throw new Error(
        `Observations HTTP ${observationsResponse.status}`
      );

    }


    const rawFlights =
      await flightsResponse.json();


    const observations =
      await observationsResponse.json();


    // Important:
    // use this version for displaying flight tracks.
    const flights =
      prepareFlightsForMap(
        rawFlights
      );


    console.log(
      "FrozenLegacies flights:",
      flights.features.length
    );


    console.log(
      "FrozenLegacies observations:",
      observations.features.length
    );


    // ==========================================================
    // Flight selector
    // ==========================================================

    const flightSelect =
      document.getElementById(
        "flight-select"
      );


    const flightNumbers = [
      ...new Set(
        observations.features.map(
          feature =>
            String(
              feature.properties.flight
            )
        )
      )
    ].sort(
      (a, b) =>
        Number(a) - Number(b)
    );


    for (
      const flight of flightNumbers
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
    // Map layers
    // ==========================================================

    map.on(
      "load",
      () => {

        // --------------------------------------------------------
        // Flight source
        // --------------------------------------------------------

        map.addSource(
          "frozen-flights",
          {
            type: "geojson",
            data: flights
          }
        );


        // Base flight tracks
        map.addLayer({
          id: "frozen-flight-lines",

          type: "line",

          source: "frozen-flights",

          layout: {
            "line-cap": "round",
            "line-join": "round"
          },

          paint: {

            "line-color":
              "#087ca9",

            "line-width": [
              "interpolate",
              ["linear"],
              ["zoom"],

              2,
              1.2,

              5,
              2.2,

              8,
              3.5
            ],

            "line-opacity":
              0.72
          }
        });


        // --------------------------------------------------------
        // Selected flight highlight
        // --------------------------------------------------------

        map.addLayer({
          id: "frozen-flight-selected",

          type: "line",

          source: "frozen-flights",

          filter: [
            "==",

            [
              "to-string",
              ["get", "flight"]
            ],

            "__none__"
          ],

          layout: {
            "line-cap": "round",
            "line-join": "round"
          },

          paint: {

            "line-color":
              "#ff8a1f",

            "line-width": [
              "interpolate",
              ["linear"],
              ["zoom"],

              2,
              3,

              5,
              5,

              8,
              8
            ],

            "line-opacity":
              1
          }
        });


        // --------------------------------------------------------
        // Observation source
        // --------------------------------------------------------

        map.addSource(
          "frozen-observations",
          {
            type: "geojson",
            data: observations
          }
        );


        map.addLayer({
          id: "frozen-observations",

          type: "circle",

          source:
            "frozen-observations",

          paint: {

            "circle-radius": [
              "interpolate",
              ["linear"],
              ["zoom"],

              2,
              2,

              5,
              3,

              7,
              5,

              10,
              8
            ],


            "circle-color": [
              "match",

              [
                "downcase",
                [
                  "to-string",
                  ["get", "echo_status"]
                ]
              ],

              "good",
              "#22c55e",

              "no_bed",
              "#ef4444",

              "weak_bed",
              "#f59e0b",

              "#8b5cf6"
            ],


            "circle-opacity":
              0.88,


            "circle-stroke-color":
              "#ffffff",


            "circle-stroke-width":
              0.8
          }
        });


        // ========================================================
        // Observation interactions
        // ========================================================

        map.on(
          "mouseenter",
          "frozen-observations",
          () => {

            map.getCanvas().style.cursor =
              "pointer";

          }
        );


        map.on(
          "mouseleave",
          "frozen-observations",
          () => {

            map.getCanvas().style.cursor =
              "";

          }
        );


        map.on(
          "click",
          "frozen-observations",
          event => {

            const feature =
              event.features?.[0];


            if (!feature) {
              return;
            }


            const p =
              feature.properties;


            const coordinates =
              feature.geometry.coordinates;


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
              ${Number(
                coordinates[1]
              ).toFixed(5)}

              <br>

              <strong>Longitude:</strong>
              ${Number(
                coordinates[0]
              ).toFixed(5)}

              <br><br>

              <strong>Ice thickness:</strong>
              ${
                p.h_ice_m ??
                "—"
              } m

              <br>

              <strong>Bed SNR:</strong>
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


            // Also select the corresponding flight.
            const flight =
              String(
                p.flight ?? ""
              );


            if (
              flight &&
              flightSelect.value !== flight
            ) {

              flightSelect.value =
                flight;


              flightSelect.dispatchEvent(
                new Event("change")
              );

            }

          }
        );


        // ========================================================
        // Flight-line interactions
        // ========================================================

        map.on(
          "mouseenter",
          "frozen-flight-lines",
          () => {

            map.getCanvas().style.cursor =
              "pointer";

          }
        );


        map.on(
          "mouseleave",
          "frozen-flight-lines",
          () => {

            map.getCanvas().style.cursor =
              "";

          }
        );


        map.on(
          "click",
          "frozen-flight-lines",
          event => {

            const feature =
              event.features?.[0];


            if (!feature) {
              return;
            }


            const flight =
              String(
                feature.properties?.flight ??
                ""
              );


            if (!flight) {
              return;
            }


            flightSelect.value =
              flight;


            flightSelect.dispatchEvent(
              new Event("change")
            );

          }
        );


        // ========================================================
        // Initial view
        // ========================================================

        fitToFlights(
          flights,
          {
            padding: 80,
            maxZoom: 5,
            duration: 700
          }
        );

      }
    );


    // ==========================================================
    // Flight dropdown
    // ==========================================================

    flightSelect.addEventListener(
      "change",
      () => {

        const value =
          flightSelect.value;


        if (
          !map.getLayer(
            "frozen-observations"
          )
        ) {
          return;
        }


        // --------------------------------------------------------
        // All flights
        // --------------------------------------------------------

        if (
          value === "all"
        ) {

          map.setFilter(
            "frozen-observations",
            null
          );


          map.setFilter(
            "frozen-flight-lines",
            null
          );


          clearSelectedFlight();


          fitToFlights(
            flights,
            {
              padding: 80,
              maxZoom: 5,
              duration: 700
            }
          );


          return;
        }


        // --------------------------------------------------------
        // Selected flight
        // --------------------------------------------------------

        const filter =
          flightFilter(value);


        // Keep only observations from selected flight.
        map.setFilter(
          "frozen-observations",
          filter
        );


        // Keep all flight lines visible,
        // but fade them into the background.
        map.setFilter(
          "frozen-flight-lines",
          null
        );


        map.setPaintProperty(
          "frozen-flight-lines",
          "line-opacity",
          0.12
        );


        // Highlight the selected flight.
        map.setFilter(
          "frozen-flight-selected",
          filter
        );


        // Zoom to selected flight.
        fitToFlight(
          flights,
          value
        );

      }
    );


  } catch (error) {

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

});