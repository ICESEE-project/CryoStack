/* ============================================================
 * Frozen Legacies
 * map.js
 *
 * Owns:
 *   - EPSG:3031 registration
 *   - OpenLayers map creation
 *   - Antarctic overview
 *   - zoom-to-feature behavior
 *
 * Nothing else should manipulate the camera directly.
 * ============================================================ */


/* ------------------------------------------------------------
 * Antarctic map constants
 * ------------------------------------------------------------ */

const ANTARCTIC_PROJECTION_CODE =
  "EPSG:3031";


const ANTARCTIC_PROJ4 =
  "+proj=stere " +
  "+lat_0=-90 " +
  "+lat_ts=-71 " +
  "+lon_0=0 " +
  "+x_0=0 " +
  "+y_0=0 " +
  "+datum=WGS84 " +
  "+units=m " +
  "+no_defs";


/*
 * Useful working extent for Antarctica.
 *
 * We deliberately keep this slightly larger than
 * the continent so the map has breathing room.
 */
const ANTARCTIC_EXTENT = [
  -3333134,
  -3333134,
   3333134,
   3333134
];


const ANTARCTIC_VIEW_EXTENT = [
  -3900000,
  -3900000,
   3900000,
   3900000
];


/* ------------------------------------------------------------
 * Projection
 * ------------------------------------------------------------ */

function registerAntarcticProjection() {

  if (
    typeof proj4 === "undefined"
  ) {
    throw new Error(
      "Proj4 is not available."
    );
  }


  if (
    typeof ol === "undefined"
  ) {
    throw new Error(
      "OpenLayers is not available."
    );
  }


  proj4.defs(
    ANTARCTIC_PROJECTION_CODE,
    ANTARCTIC_PROJ4
  );


  ol.proj.proj4.register(
    proj4
  );


  const projection =
    ol.proj.get(
      ANTARCTIC_PROJECTION_CODE
    );


  if (!projection) {
    throw new Error(
      "Could not register EPSG:3031."
    );
  }


  projection.setExtent(
    ANTARCTIC_EXTENT
  );


  console.log(
    "[FrozenLegacies] projection:",
    projection.getCode()
  );


  return projection;
}


/* ------------------------------------------------------------
 * Map creation
 * ------------------------------------------------------------ */

function createFrozenLegaciesMap({
  target,
  layers = []
}) {

  const projection =
    registerAntarcticProjection();


  const view =
    new ol.View({

      projection,

      /*
       * South Pole in EPSG:3031.
       */
      center: [
        0,
        0
      ],

      /*
       * Only a fallback.
       *
       * resetAntarcticView() establishes the
       * actual application overview.
       */
      zoom: 1,

      minZoom: 0,

      maxZoom: 12,

      extent: [
        -5000000,
        -5000000,
         5000000,
         5000000
      ],

      /*
       * Prevent accidental rotation of the
       * scientific polar map.
       */
      // rotation: 0
      constrainOnlyCenter: true,
    });


  const map =
    new ol.Map({

      target,

      layers,

      view,

      controls:
        ol.control.defaults.defaults({
          rotate: false
        }).extend([

          new ol.control.ScaleLine({
            units: "metric"
          })

        ])
    });


  /*
   * Stabilize size after the page layout
   * has completed.
   */
  window.setTimeout(
    () => {
      map.updateSize();
    },
    0
  );


  return {
    map,
    view,
    projection
  };
}


/* ------------------------------------------------------------
 * Default Antarctic overview
 * ------------------------------------------------------------ */

function resetAntarcticView(
  map,
  {
    duration = 500
  } = {}
) {

  const view =
    map.getView();

  const size =
    map.getSize();


  if (
    !size ||
    size[0] <= 0 ||
    size[1] <= 0
  ) {
    return;
  }


  /*
   * Polar ocean disc radius is ~3.4 Mm.
   *
   * Give it additional geographic space so the entire
   * circle remains visible inside the rectangular viewport.
   */
  const overviewExtent = [
    -3900000,
    -3900000,
     3900000,
     3900000
  ];


  view.fit(
    overviewExtent,
    {
      size,

      padding: [
        45,
        45,
        45,
        45
      ],

      duration,

      nearest:
        false
    }
  );

}

/* ------------------------------------------------------------
 * Zoom to one OpenLayers feature
 * ------------------------------------------------------------ */

function fitToFeature(
  map,
  feature,
  {
    padding = 90,
    maxZoom = 8,
    duration = 500
  } = {}
) {

  if (
    !map ||
    !feature
  ) {
    return;
  }


  const geometry =
    feature.getGeometry();


  if (!geometry) {
    return;
  }


  const extent =
    geometry.getExtent();


  if (
    !extent ||
    ol.extent.isEmpty(
      extent
    )
  ) {
    return;
  }


  map
    .getView()
    .fit(
      extent,
      {
        padding: [
          padding,
          padding,
          padding,
          padding
        ],

        maxZoom,

        duration
      }
    );
}


/* ------------------------------------------------------------
 * Coordinate conversion helpers
 * ------------------------------------------------------------ */

function antarcticToLonLat(
  coordinate
) {

  return ol.proj.transform(
    coordinate,

    ANTARCTIC_PROJECTION_CODE,

    "EPSG:4326"
  );
}


function lonLatToAntarctic(
  coordinate
) {

  return ol.proj.transform(
    coordinate,

    "EPSG:4326",

    ANTARCTIC_PROJECTION_CODE
  );
}


/* ------------------------------------------------------------
 * Public FrozenLegacies map API
 * ------------------------------------------------------------ */

window.FrozenLegaciesMap = {

  PROJECTION_CODE:
    ANTARCTIC_PROJECTION_CODE,

  ANTARCTIC_EXTENT,

  ANTARCTIC_VIEW_EXTENT,

  registerAntarcticProjection,

  create:
    createFrozenLegaciesMap,

  resetView:
    resetAntarcticView,

  fitToFeature,

  toLonLat:
    antarcticToLonLat,

  fromLonLat:
    lonLatToAntarctic
};