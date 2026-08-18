/* ============================================================
 * Frozen Legacies
 * data.js
 *
 * Owns:
 *   - loading FrozenLegacies GeoJSON
 *   - validating responses
 *   - transforming EPSG:4326 -> EPSG:3031
 *   - populating OpenLayers vector sources
 *   - deriving available flight numbers
 *
 * No UI logic.
 * No camera logic.
 * No styling.
 * ============================================================ */


/* ------------------------------------------------------------
 * Data URLs
 * ------------------------------------------------------------ */

const FLIGHTS_DATA_URL =
  "/frozen-legacies/data/flights.geojson";


const OBSERVATIONS_DATA_URL =
  "/frozen-legacies/data/observations.geojson";


/* ------------------------------------------------------------
 * Generic JSON loader
 * ------------------------------------------------------------ */

async function loadJson(
  url,
  label
) {

  const response =
    await fetch(
      url,
      {
        cache:
          "no-store"
      }
    );


  if (!response.ok) {

    throw new Error(
      `${label} HTTP ${response.status}`
    );

  }


  try {

    return await response.json();

  }

  catch (error) {

    throw new Error(
      `${label} could not be parsed as JSON: ${error.message}`
    );

  }

}


/* ------------------------------------------------------------
 * Raw FrozenLegacies datasets
 * ------------------------------------------------------------ */

async function loadFrozenLegaciesGeoJSON() {

  const [
    flights,
    observations
  ] =
    await Promise.all([

      loadJson(
        FLIGHTS_DATA_URL,
        "Flights"
      ),

      loadJson(
        OBSERVATIONS_DATA_URL,
        "Observations"
      )

    ]);


  if (
    flights?.type !==
    "FeatureCollection"
  ) {

    throw new Error(
      "Flights GeoJSON is not a FeatureCollection."
    );

  }


  if (
    observations?.type !==
    "FeatureCollection"
  ) {

    throw new Error(
      "Observations GeoJSON is not a FeatureCollection."
    );

  }


  return {
    flights,
    observations
  };

}


/* ------------------------------------------------------------
 * GeoJSON -> OpenLayers features
 * ------------------------------------------------------------ */

function readProjectedFeatures(
  geojson,
  projection
) {

  const format =
    new ol.format.GeoJSON();


  return format.readFeatures(
    geojson,
    {
      dataProjection:
        "EPSG:4326",

      featureProjection:
        projection
    }
  );

}


/* ------------------------------------------------------------
 * Flight normalization
 * ------------------------------------------------------------ */

function normalizeFlightValue(
  value
) {

  if (
    value === null ||
    value === undefined
  ) {
    return "";
  }


  return String(
    value
  ).trim();

}


/* ------------------------------------------------------------
 * Extract available flights
 * ------------------------------------------------------------ */

function getFlightNumbers(
  observationFeatures,
  flightFeatures = []
) {

  const values =
    new Set();


  for (
    const feature
    of observationFeatures
  ) {

    const value =
      normalizeFlightValue(
        feature.get(
          "flight"
        )
      );


    if (value) {
      values.add(
        value
      );
    }

  }


  /*
   * Use flight features as a fallback in case a flight has no
   * valid observations but still exists in the track dataset.
   */

  for (
    const feature
    of flightFeatures
  ) {

    const value =
      normalizeFlightValue(
        feature.get(
          "flight"
        )
      );


    if (value) {
      values.add(
        value
      );
    }

  }


  return [
    ...values
  ].sort(
    (a, b) => {

      const na =
        Number(a);

      const nb =
        Number(b);


      if (
        Number.isFinite(na) &&
        Number.isFinite(nb)
      ) {

        return na - nb;

      }


      return a.localeCompare(
        b
      );

    }
  );

}


/* ------------------------------------------------------------
 * Index flights by flight number
 * ------------------------------------------------------------ */

function buildFlightIndex(
  flightFeatures
) {

  const index =
    new Map();


  for (
    const feature
    of flightFeatures
  ) {

    const flight =
      normalizeFlightValue(
        feature.get(
          "flight"
        )
      );


    if (!flight) {
      continue;
    }


    /*
     * Current generated flights.geojson should have one feature
     * per flight. If that changes later, keep the first feature
     * rather than silently replacing it.
     */

    if (
      !index.has(
        flight
      )
    ) {

      index.set(
        flight,
        feature
      );

    }

  }


  return index;

}


/* ------------------------------------------------------------
 * Index observations by flight
 * ------------------------------------------------------------ */

function buildObservationIndex(
  observationFeatures
) {

  const index =
    new Map();


  for (
    const feature
    of observationFeatures
  ) {

    const flight =
      normalizeFlightValue(
        feature.get(
          "flight"
        )
      );


    if (!flight) {
      continue;
    }


    if (
      !index.has(
        flight
      )
    ) {

      index.set(
        flight,
        []
      );

    }


    index
      .get(
        flight
      )
      .push(
        feature
      );

  }


  return index;

}


/* ------------------------------------------------------------
 * Populate vector sources
 * ------------------------------------------------------------ */

function populateFrozenSources(
  sources,
  flightFeatures,
  observationFeatures
) {

  if (
    !sources?.flights ||
    !sources?.observations ||
    !sources?.selectedFlight
  ) {

    throw new Error(
      "FrozenLegacies vector sources are incomplete."
    );

  }


  /*
   * Clear first so reloads during development do not duplicate
   * every feature.
   */

  sources.flights.clear(
    true
  );


  sources.selectedFlight.clear(
    true
  );


  sources.observations.clear(
    true
  );


  sources.flights.addFeatures(
    flightFeatures
  );


  sources.observations.addFeatures(
    observationFeatures
  );

}


/* ------------------------------------------------------------
 * Complete data load
 * ------------------------------------------------------------ */

async function loadFrozenLegaciesData({
  projection,
  sources
}) {

  if (!projection) {

    throw new Error(
      "FrozenLegacies projection was not supplied."
    );

  }


  if (!sources) {

    throw new Error(
      "FrozenLegacies sources were not supplied."
    );

  }


  const raw =
    await loadFrozenLegaciesGeoJSON();


  const flightFeatures =
    readProjectedFeatures(
      raw.flights,
      projection
    );


  const observationFeatures =
    readProjectedFeatures(
      raw.observations,
      projection
    );


  populateFrozenSources(
    sources,
    flightFeatures,
    observationFeatures
  );


  const flightNumbers =
    getFlightNumbers(
      observationFeatures,
      flightFeatures
    );


  const flightIndex =
    buildFlightIndex(
      flightFeatures
    );


  const observationIndex =
    buildObservationIndex(
      observationFeatures
    );


  console.log(
    "[FrozenLegacies] flights:",
    flightFeatures.length
  );


  console.log(
    "[FrozenLegacies] observations:",
    observationFeatures.length
  );


  console.log(
    "[FrozenLegacies] flight numbers:",
    flightNumbers
  );


  return {

    raw,

    flightFeatures,

    observationFeatures,

    flightNumbers,

    flightIndex,

    observationIndex

  };

}


/* ------------------------------------------------------------
 * Utility: get one flight
 * ------------------------------------------------------------ */

function getFlightFeature(
  data,
  flightNumber
) {

  if (!data?.flightIndex) {
    return null;
  }


  return (
    data.flightIndex.get(
      normalizeFlightValue(
        flightNumber
      )
    ) || null
  );

}


/* ------------------------------------------------------------
 * Utility: get observations for one flight
 * ------------------------------------------------------------ */

function getFlightObservations(
  data,
  flightNumber
) {

  if (
    !data?.observationIndex
  ) {
    return [];
  }


  return (
    data.observationIndex.get(
      normalizeFlightValue(
        flightNumber
      )
    ) || []
  );

}


/* ------------------------------------------------------------
 * Public API
 * ------------------------------------------------------------ */

window.FrozenLegaciesData = {

  URLS: {
    flights:
      FLIGHTS_DATA_URL,

    observations:
      OBSERVATIONS_DATA_URL
  },

  load:
    loadFrozenLegaciesData,

  getFlight:
    getFlightFeature,

  getFlightObservations,

  normalizeFlightValue

};