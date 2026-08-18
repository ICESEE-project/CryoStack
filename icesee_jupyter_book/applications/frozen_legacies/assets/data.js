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

const FROZEN_DATA_ROOT =
  "/frozen-legacies/data";


const CATALOG_DATA_URL =
  `${FROZEN_DATA_ROOT}/catalog.json`;


const FLIGHTS_DATA_URL =
  `${FROZEN_DATA_ROOT}/flights.geojson`;


const OBSERVATIONS_DATA_URL =
  `${FROZEN_DATA_ROOT}/observations.geojson`;


function buildDatasetIndex(
  catalog
) {

  const index =
    new Map();


  for (
    const dataset
    of catalog.datasets || []
  ) {

    if (!dataset?.id) {
      continue;
    }


    index.set(
      String(
        dataset.id
      ),
      dataset
    );

  }


  return index;
}

function datasetIdsFromObservations(
  observations
) {

  return [
    ...new Set(

      (
        observations.features
        || []
      )

        .map(
          feature =>
            feature
              .properties
              ?.dataset_id
        )

        .filter(
          Boolean
        )

        .map(
          String
        )

    )
  ];
}


function observationsForDataset(
  observations,
  datasetId
) {

  if (!datasetId) {

    return observations;

  }


  return {
    type:
      "FeatureCollection",

    features:
      (
        observations.features
        || []
      ).filter(
        feature =>

          String(
            feature
              .properties
              ?.dataset_id
              ?? ""
          )
          ===
          String(
            datasetId
          )
      )
  };
}


function flightsForDataset(
  flights,
  datasetId
) {

  if (!datasetId) {

    return flights;

  }


  return {
    type:
      "FeatureCollection",

    features:
      (
        flights.features
        || []
      ).filter(
        feature =>

          String(
            feature
              .properties
              ?.dataset_id
              ?? ""
          )
          ===
          String(
            datasetId
          )
      )
  };
}

function flightNumbersForDataset(
  observations,
  datasetId = null
) {

  const source =
    observationsForDataset(
      observations,
      datasetId
    );


  return [
    ...new Set(

      (
        source.features
        || []
      )

        .map(
          feature =>
            feature
              .properties
              ?.flight
        )

        .filter(
          value =>
            value !== null
            &&
            value !== undefined
            &&
            value !== ""
        )

        .map(
          String
        )

    )
  ].sort(
    (a, b) => {

      const na =
        Number(a);

      const nb =
        Number(b);


      if (
        Number.isFinite(na)
        &&
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

    catalog,

    flights,

    observations

  ] = await Promise.all([

    loadJson(
      CATALOG_DATA_URL,
      "Catalog"
    ),

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
    !catalog ||
    !Array.isArray(
      catalog.datasets
    )
  ) {

    throw new Error(
      "Frozen Legacies catalog is invalid."
    );

  }


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

    catalog,

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

function normalizeDatasetValue(
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

function datasetFlightKey(
  datasetId,
  flightNumber
) {

  return (
    `${normalizeDatasetValue(datasetId)}::` +
    `${normalizeFlightValue(flightNumber)}`
  );

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

    const datasetId =
      normalizeDatasetValue(
        feature.get(
          "dataset_id"
        )
      );


    const flight =
      normalizeFlightValue(
        feature.get(
          "flight"
        )
      );


    if (!flight) {
      continue;
    }


    const key =
      datasetFlightKey(
        datasetId,
        flight
      );


    if (
      !index.has(
        key
      )
    ) {

      index.set(
        key,
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

    const datasetId =
      normalizeDatasetValue(
        feature.get(
          "dataset_id"
        )
      );


    const flight =
      normalizeFlightValue(
        feature.get(
          "flight"
        )
      );


    if (!flight) {
      continue;
    }


    const key =
      datasetFlightKey(
        datasetId,
        flight
      );


    if (
      !index.has(
        key
      )
    ) {

      index.set(
        key,
        []
      );

    }


    index
      .get(
        key
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

  const datasetIndex =
    buildDatasetIndex(
      raw.catalog
    );

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

  const datasetIds =
    datasetIdsFromObservations(
      raw.observations
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

      catalog:
        raw.catalog,

      datasetIndex,

      datasetIds,

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
  flightNumber,
  datasetId = ""
) {

  if (!data?.flightIndex) {
    return null;
  }


  if (datasetId) {

    return (
      data.flightIndex.get(
        datasetFlightKey(
          datasetId,
          flightNumber
        )
      )
      || null
    );

  }


  const flight =
    normalizeFlightValue(
      flightNumber
    );


  return (
    data.flightFeatures.find(
      feature =>
        normalizeFlightValue(
          feature.get(
            "flight"
          )
        ) === flight
    )
    || null
  );

}


/* ------------------------------------------------------------
 * Utility: get observations for one flight
 * ------------------------------------------------------------ */

function getFlightObservations(
  data,
  flightNumber,
  datasetId = ""
) {

  if (!data) {
    return [];
  }


  if (datasetId) {

    return (
      data.observationIndex.get(
        datasetFlightKey(
          datasetId,
          flightNumber
        )
      )
      || []
    );

  }


  const flight =
    normalizeFlightValue(
      flightNumber
    );


  return (
    data.observationFeatures
    || []
  ).filter(
    feature =>
      normalizeFlightValue(
        feature.get(
          "flight"
        )
      ) === flight
  );

}


/* ------------------------------------------------------------
 * Public API
 * ------------------------------------------------------------ */

window.FrozenLegaciesData = {

  URLS: {

    catalog:
      CATALOG_DATA_URL,

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

  normalizeFlightValue,

  normalizeDatasetValue,

  datasetFlightKey,

  buildDatasetIndex,

  datasetIdsFromObservations,

  observationsForDataset,

  flightsForDataset,

  flightNumbersForDataset

};