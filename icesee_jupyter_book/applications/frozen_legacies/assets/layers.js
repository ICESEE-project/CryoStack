/* ============================================================
 * Frozen Legacies
 * layers.js
 *
 * Owns:
 *   - all OpenLayers sources
 *   - all OpenLayers layers
 *   - Antarctic reference layers
 *   - FrozenLegacies flight/observation layers
 *   - South Pole marker
 *   - graticule
 *
 * No camera logic.
 * No UI logic.
 * No fetch logic for LYRA data.
 * ============================================================ */


/* ------------------------------------------------------------
 * Source factory
 * ------------------------------------------------------------ */

function createVectorSource() {

  return new ol.source.Vector();

}


/* ------------------------------------------------------------
 * Antarctic reference sources
 * ------------------------------------------------------------ */

function createAntarcticReferenceSources() {

  const coastline =
    new ol.source.Vector({
      url:
        "/frozen-legacies/data/antarctica/coastline.geojson",

      format:
        new ol.format.GeoJSON({
          dataProjection:
            "EPSG:3031",

          featureProjection:
            "EPSG:3031"
        })
    });


  const groundingLine =
    new ol.source.Vector({
      url:
        "/frozen-legacies/data/antarctica/grounding_line.geojson",

      format:
        new ol.format.GeoJSON({
          dataProjection:
            "EPSG:3031",

          featureProjection:
            "EPSG:3031"
        })
    });


  const iceShelfFront =
    new ol.source.Vector({
      url:
        "/frozen-legacies/data/antarctica/ice_shelf_front.geojson",

      format:
        new ol.format.GeoJSON({
          dataProjection:
            "EPSG:3031",

          featureProjection:
            "EPSG:3031"
        })
    });


  return {
    coastline,
    groundingLine,
    iceShelfFront
  };
}


/* ------------------------------------------------------------
 * FrozenLegacies data sources
 * ------------------------------------------------------------ */

function createFrozenLegaciesSources() {

  return {

    flights:
      createVectorSource(),

    selectedFlight:
      createVectorSource(),

    observations:
      createVectorSource()

  };

}


/* ------------------------------------------------------------
 * Background layer
 * ------------------------------------------------------------ */

function createBackgroundLayer() {

  /*
   * This is intentionally empty for now.
   *
   * The actual background color is supplied by CSS.
   * Later this slot can hold:
   *
   *   - hillshade
   *   - bathymetry
   *   - REMA
   *   - BedMachine
   *
   * without changing the application architecture.
   */

  return new ol.layer.Vector({
    source:
      new ol.source.Vector()
  });

}


/* ------------------------------------------------------------
 * Antarctic reference layers
 * ------------------------------------------------------------ */

function createAntarcticReferenceLayers(
  sources
) {

  const coastline =
    new ol.layer.Vector({

      source:
        sources.coastline,

      style:
        FrozenLegaciesStyles.coastline(),

      properties: {
        id:
          "antarctic-coastline",

        label:
          "Coastline"
      }

    });


  const groundingLine =
    new ol.layer.Vector({

      source:
        sources.groundingLine,

      style:
        FrozenLegaciesStyles.groundingLine(),

      properties: {
        id:
          "antarctic-grounding-line",

        label:
          "Grounding line"
      }

    });


  const iceShelfFront =
    new ol.layer.Vector({

      source:
        sources.iceShelfFront,

      style:
        FrozenLegaciesStyles.iceShelfFront(),

      properties: {
        id:
          "antarctic-ice-shelf-front",

        label:
          "Ice-shelf front"
      }

    });


  return {
    coastline,
    groundingLine,
    iceShelfFront
  };
}


/* ------------------------------------------------------------
 * Flight layers
 * ------------------------------------------------------------ */

function createFlightLayers(
  sources
) {

  const flights =
    new ol.layer.Vector({

      source:
        sources.flights,

      style:
        FrozenLegaciesStyles.defaultFlight(),

      properties: {
        id:
          "frozen-flights",

        label:
          "Flight tracks"
      }

    });


  const selectedFlight =
    new ol.layer.Vector({

      source:
        sources.selectedFlight,

      style:
        FrozenLegaciesStyles.selectedFlight(),

      properties: {
        id:
          "frozen-selected-flight",

        label:
          "Selected flight"
      }

    });


  return {
    flights,
    selectedFlight
  };
}


/* ------------------------------------------------------------
 * Observation layer
 * ------------------------------------------------------------ */

function createObservationLayer(
  sources
) {

  return new ol.layer.Vector({

    source:
      sources.observations,

    style:
      feature =>
        FrozenLegaciesStyles.observation(
          feature
        ),

    properties: {
      id:
        "frozen-observations",

      label:
        "Radar observations"
    }

  });

}


/* ------------------------------------------------------------
 * South Pole layer
 * ------------------------------------------------------------ */

function createSouthPoleLayer() {

  const feature =
    new ol.Feature({

      geometry:
        new ol.geom.Point([
          0,
          0
        ]),

      name:
        "South Pole"

    });


  const source =
    new ol.source.Vector({

      features: [
        feature
      ]

    });


  const layer =
    new ol.layer.Vector({

      source,

      style:
        FrozenLegaciesStyles.southPole(),

      properties: {
        id:
          "south-pole",

        label:
          "South Pole"
      }

    });


  return {
    source,
    layer,
    feature
  };
}


/* ------------------------------------------------------------
 * Graticule
 * ------------------------------------------------------------ */

function createGraticule() {

  return new ol.layer.Graticule({

    strokeStyle:
      FrozenLegaciesStyles.graticuleStroke(),

    showLabels:
      true,

    wrapX:
      false,

    lonLabelStyle:
      new ol.style.Text({

        font:
          "600 10px system-ui",

        fill:
          new ol.style.Fill({
            color:
              "rgba(52, 77, 91, 0.78)"
          }),

        stroke:
          new ol.style.Stroke({
            color:
              "rgba(255,255,255,0.92)",

            width:
              3
          })

      }),

    latLabelStyle:
      new ol.style.Text({

        font:
          "600 10px system-ui",

        fill:
          new ol.style.Fill({
            color:
              "rgba(52, 77, 91, 0.78)"
          }),

        stroke:
          new ol.style.Stroke({
            color:
              "rgba(255,255,255,0.92)",

            width:
              3
          })

      })

  });

}


/* ------------------------------------------------------------
 * Complete layer bundle
 * ------------------------------------------------------------ */

function createFrozenLegaciesLayers() {

  const background =
    createBackgroundLayer();


  const frozenSources =
    createFrozenLegaciesSources();


  const flightLayers =
    createFlightLayers(
      frozenSources
    );


  const observationLayer =
    createObservationLayer(
      frozenSources
    );


  const southPole =
    createSouthPoleLayer();

  const antarcticLand =
    createAntarcticLandLayer();

  const polarOcean =
  createPolarOceanLayer();


  /*
   * Stable baseline.
   *
   * Do NOT include:
   *
   *   - graticule
   *   - coastline
   *   - grounding line
   *   - ice-shelf front
   *
   * until those datasets actually exist and
   * the polar graticule is implemented manually.
   */

  const mapLayers = [

    background,

    polarOcean.layer,

    antarcticLand.layer,

    flightLayers.flights,

    flightLayers.selectedFlight,

    southPole.layer,

    observationLayer

  ];


  return {

    sources: {

      frozen:
        frozenSources

    },


    layers: {

      background,

      polarOcean:
        polarOcean.layer,

      antarcticLand:
        antarcticLand.layer,

      flights:
        flightLayers.flights,

      selectedFlight:
        flightLayers.selectedFlight,

      southPole:
        southPole.layer,

      observations:
        observationLayer

    },


    mapLayers

  };

}


/* ------------------------------------------------------------
 * Attach layers that are not part of map.layers[]
 * ------------------------------------------------------------ */

function attachFrozenLegaciesOverlayLayers(
  map,
  bundle
) {

  /*
   * Nothing to attach yet.
   *
   * Kept as part of the public API so we can add
   * polar-specific overlays later without changing
   * frozen_legacies.js.
   */

  return;

}


/* ------------------------------------------------------------
 * Layer visibility helper
 * ------------------------------------------------------------ */

function setLayerVisible(
  layer,
  visible
) {

  if (!layer) {
    return;
  }


  layer.setVisible(
    Boolean(
      visible
    )
  );

}


/* ------------------------------------------------------------
 * Public API
 * ------------------------------------------------------------ */

window.FrozenLegaciesLayers = {

  create:
    createFrozenLegaciesLayers,

  attachOverlays:
    attachFrozenLegaciesOverlayLayers,

  setVisible:
    setLayerVisible

};

function createAntarcticLandLayer() {

  const source =
    new ol.source.Vector({

      url:
        "/frozen-legacies/data/antarctica/antarctica_land.geojson",

      format:
        new ol.format.GeoJSON({

          dataProjection:
            "EPSG:4326",

          featureProjection:
            "EPSG:3031"

        })

    });


  const layer =
    new ol.layer.Vector({

      source,

      style:
        FrozenLegaciesStyles
          .antarcticLand(),

      properties: {

        id:
          "antarctic-land",

        label:
          "Antarctica"

      }

    });


  return {
    source,
    layer
  };

}

/* ------------------------------------------------------------
 * Antarctic polar-domain disc
 * ------------------------------------------------------------ */

function createPolarOceanLayer() {

  /*
   * EPSG:3031 is measured in metres.
   *
   * 3.35–3.45 million metres gives us a domain
   * covering roughly the Antarctic polar region
   * out toward approximately 60°S.
   */

  const radius =
    3400000;


  const circle =
    new ol.geom.Circle(
      [
        0,
        0
      ],
      radius
    );


  const feature =
    new ol.Feature({
      geometry:
        circle,

      name:
        "Antarctic polar domain"
    });


  const source =
    new ol.source.Vector({
      features: [
        feature
      ]
    });


  const layer =
    new ol.layer.Vector({

      source,

      style:
        FrozenLegaciesStyles
          .polarOcean(),

      properties: {

        id:
          "antarctic-polar-ocean",

        label:
          "Antarctic polar domain"

      }

    });


  return {

    layer,

    source,

    feature,

    radius

  };

}