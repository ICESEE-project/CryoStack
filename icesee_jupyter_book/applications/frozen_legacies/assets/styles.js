/* ============================================================
 * Frozen Legacies
 * styles.js
 *
 * Owns all OpenLayers visual styles.
 * No map movement, no data loading, no UI logic.
 * ============================================================ */


/* ------------------------------------------------------------
 * Shared colors
 * ------------------------------------------------------------ */

const FL_COLORS = {
  flight: "#0b6f98",

  flightMuted:
    "rgba(21, 113, 151, 0.30)",

  flightVeryMuted:
    "rgba(21, 113, 151, 0.10)",

  selectedFlight:
    "#ff8a1f",

  good:
    "#22c55e",

  noBed:
    "#ef4444",

  weakBed:
    "#f59e0b",

  other:
    "#8b5cf6",

  coastline:
    "#567786",

  groundingLine:
    "#8f6c43",

  iceShelfFront:
    "#4f9eb9",

  southPole:
    "#274e63",

  white:
    "#ffffff"
};


/* ------------------------------------------------------------
 * Flight styles
 * ------------------------------------------------------------ */

function defaultFlightStyle() {

  return new ol.style.Style({

    stroke:
      new ol.style.Stroke({

        color:
          "rgba(23, 108, 150, 0.50)",

        width:
          1.4

      })

  });

}


function fadedFlightStyle() {

  return new ol.style.Style({

    stroke:
      new ol.style.Stroke({

        color:
          FL_COLORS.flightVeryMuted,

        width:
          1.4

      })

  });
}


function selectedFlightStyle() {

  return new ol.style.Style({

    stroke:
      new ol.style.Stroke({

        color:
          "#f47f20",

        width:
          3.5

      })

  });

}


/* ------------------------------------------------------------
 * Observation styles
 * ------------------------------------------------------------ */

function observationStatusColor(
  status
) {

  const normalized =
    String(
      status || ""
    ).toLowerCase();


  if (
    normalized === "good"
  ) {
    return FL_COLORS.good;
  }


  if (
    normalized === "no_bed"
  ) {
    return FL_COLORS.noBed;
  }


  if (
    normalized === "weak_bed"
  ) {
    return FL_COLORS.weakBed;
  }


  return FL_COLORS.other;
}


function observationStyle(
  feature
) {

  const status =
    feature.get(
      "echo_status"
    );


  return new ol.style.Style({

    image:
      new ol.style.Circle({

        radius:
          4,

        fill:
          new ol.style.Fill({

            color:
              observationStatusColor(
                status
              )

          }),

        stroke:
          new ol.style.Stroke({

            color:
              FL_COLORS.white,

            width:
              1

          })

      })

  });
}


/* ------------------------------------------------------------
 * Antarctic reference styles
 * ------------------------------------------------------------ */

function coastlineStyle() {

  return new ol.style.Style({

    stroke:
      new ol.style.Stroke({

        color:
          FL_COLORS.coastline,

        width:
          1.4

      })

  });
}


function groundingLineStyle() {

  return new ol.style.Style({

    stroke:
      new ol.style.Stroke({

        color:
          FL_COLORS.groundingLine,

        width:
          1.1,

        lineDash:
          [6, 4]

      })

  });
}


function iceShelfFrontStyle() {

  return new ol.style.Style({

    stroke:
      new ol.style.Stroke({

        color:
          FL_COLORS.iceShelfFront,

        width:
          1.2

      })

  });
}


/* ------------------------------------------------------------
 * South Pole style
 * ------------------------------------------------------------ */

function southPoleStyle() {

  return new ol.style.Style({

    image:
      new ol.style.Circle({

        radius:
          3.5,

        fill:
          new ol.style.Fill({
            color:
              "#ffffff"
          }),

        stroke:
          new ol.style.Stroke({
            color:
              "#567786",

            width:
              1.4
          })

      })

  });

}


/* ------------------------------------------------------------
 * Graticule style
 * ------------------------------------------------------------ */

function graticuleStrokeStyle() {

  return new ol.style.Stroke({

    color:
      "rgba(73, 99, 112, 0.28)",

    width:
      1

  });
}


/* ------------------------------------------------------------
 * Public API
 * ------------------------------------------------------------ */

window.FrozenLegaciesStyles = {

  COLORS:
    FL_COLORS,

  defaultFlight:
    defaultFlightStyle,

  fadedFlight:
    fadedFlightStyle,

  selectedFlight:
    selectedFlightStyle,

  observation:
    observationStyle,

  observationStatusColor,

  coastline:
    coastlineStyle,

  groundingLine:
    groundingLineStyle,

  iceShelfFront:
    iceShelfFrontStyle,

  southPole:
    southPoleStyle,

  graticuleStroke:
    graticuleStrokeStyle

};

function antarcticLandStyle() {

  return new ol.style.Style({

    fill:
      new ol.style.Fill({
        color:
          "#efefed"
      }),

    stroke:
      new ol.style.Stroke({
        color:
          "#ffffff",

        width:
          2
      })

  });

}

window.FrozenLegaciesStyles = {

  COLORS:
    FL_COLORS,

  antarcticLand:
    antarcticLandStyle,

  defaultFlight:
    defaultFlightStyle,

  fadedFlight:
    fadedFlightStyle,

  selectedFlight:
    selectedFlightStyle,

  observation:
    observationStyle,

  observationStatusColor,

  coastline:
    coastlineStyle,

  groundingLine:
    groundingLineStyle,

  iceShelfFront:
    iceShelfFrontStyle,

  southPole:
    southPoleStyle,

  graticuleStroke:
    graticuleStrokeStyle

};

/* ------------------------------------------------------------
 * Antarctic polar domain
 * ------------------------------------------------------------ */

function polarOceanStyle() {

  return new ol.style.Style({

    fill:
      new ol.style.Fill({
        color:
          "#a9c3d4"
      }),

    stroke:
      new ol.style.Stroke({
        color:
          "rgba(72, 117, 144, 0.45)",

        width:
          1.2
      })

  });

}

window.FrozenLegaciesStyles = {

  COLORS:
    FL_COLORS,

  polarOcean:
    polarOceanStyle,

  antarcticLand:
    antarcticLandStyle,

  defaultFlight:
    defaultFlightStyle,

  fadedFlight:
    fadedFlightStyle,

  selectedFlight:
    selectedFlightStyle,

  observation:
    observationStyle,

  observationStatusColor,

  coastline:
    coastlineStyle,

  groundingLine:
    groundingLineStyle,

  iceShelfFront:
    iceShelfFrontStyle,

  southPole:
    southPoleStyle,

  graticuleStroke:
    graticuleStrokeStyle

};