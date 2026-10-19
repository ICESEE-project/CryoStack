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
          "rgba(10, 103, 145, 0.62)",

        width:
          1.65

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
  return [
    new ol.style.Style({
      stroke: new ol.style.Stroke({
        color: "rgba(255,255,255,0.94)",
        width: 6.5
      })
    }),
    new ol.style.Style({
      stroke: new ol.style.Stroke({
        color: FL_COLORS.selectedFlight,
        width: 3.4
      })
    })
  ];

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
          4.5,

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
              1.5

          })

      })

  });
}

function riggsStationStyle(feature) {
  const seismic = feature.get("measurement_method") === "seismic";
  return new ol.style.Style({
    image: new ol.style.RegularShape({
      points: seismic ? 4 : 3,
      radius: 4.5,
      angle: seismic ? Math.PI / 4 : 0,
      fill: new ol.style.Fill({ color: seismic ? "#9b3653" : "#7a4fb3" }),
      stroke: new ol.style.Stroke({ color: "#ffffff", width: 1.5 })
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
  return [
    new ol.style.Style({
      stroke: new ol.style.Stroke({ color: "rgba(34, 80, 105, 0.20)", width: 6 })
    }),
    new ol.style.Style({
      fill: new ol.style.Fill({ color: "#f6f8f8" }),
      stroke: new ol.style.Stroke({ color: "rgba(255,255,255,0.98)", width: 2.2 })
    })
  ];

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
          "#9dbdd1"
      }),

    stroke:
      new ol.style.Stroke({
        color:
          "rgba(46, 91, 117, 0.55)",

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

function polarReferenceStyle(feature) {
  const kind = feature.get("kind");
  const label = feature.get("label") || "";
  const isLabel = kind === "label";

  return new ol.style.Style({
    stroke: isLabel ? undefined : new ol.style.Stroke({
      color: kind === "latitude"
        ? "rgba(255,255,255,0.46)"
        : "rgba(255,255,255,0.30)",
      width: kind === "latitude" ? 1 : 0.8,
      lineDash: kind === "latitude" ? [4, 5] : [2, 7]
    }),
    text: isLabel ? new ol.style.Text({
      text: label,
      font: "600 10px system-ui, sans-serif",
      fill: new ol.style.Fill({ color: "rgba(29,66,87,0.82)" }),
      stroke: new ol.style.Stroke({ color: "rgba(255,255,255,0.88)", width: 3 }),
      offsetX: 4,
      textAlign: "left"
    }) : undefined
  });
}

window.FrozenLegaciesStyles.polarReference = polarReferenceStyle;

/* ------------------------------------------------------------
 * Shared LIVIST / Quantarctica scientific geography
 * ------------------------------------------------------------ */

function scientificBasemapStyle(feature) {
  const category = String(feature.get("Category") || "");
  const colors = {
    "Ice shelf": "#d8e9f1",
    "Ice tongue": "#cce3ee",
    "Land": "#f3f4f2",
    "Rumple": "#e4e7e3",
    "Sub-antarctic_G": "#e7e7df",
    "Sub-antarctic_L": "#e7e7df"
  };

  if (category === "Ocean") {
    return null;
  }

  // The Quantarctica bundle also contains distant sub-Antarctic and
  // continental context. Frozen Legacies is a polar-domain instrument, so
  // do not draw those polygons outside the circular scientific frame.
  if (category.startsWith("Sub-antarctic_")) {
    return null;
  }

  return new ol.style.Style({
    fill: new ol.style.Fill({ color: colors[category] || "#ecece7" }),
    stroke: new ol.style.Stroke({
      color: category === "Ice shelf" || category === "Ice tongue"
        ? "rgba(255,255,255,0.88)"
        : "rgba(255,255,255,0.98)",
      width: category === "Land" ? 1.7 : 1.1
    })
  });
}

function drainageBasinStyle(feature) {
  const name = String(feature.get("name") || "");
  let hash = 0;
  for (let index = 0; index < name.length; index += 1) {
    hash = ((hash << 5) - hash + name.charCodeAt(index)) | 0;
  }
  const fills = [
    "rgba(38, 115, 151, 0.035)",
    "rgba(40, 145, 132, 0.045)",
    "rgba(102, 112, 154, 0.038)"
  ];
  return new ol.style.Style({
    fill: new ol.style.Fill({ color: fills[Math.abs(hash) % fills.length] }),
    stroke: new ol.style.Stroke({ color: "rgba(77, 112, 128, 0.36)", width: 1.05 })
  });
}

function antarcticPlaceNameStyle(feature, resolution) {
  const labelClass = String(feature.get("LabelClass") || "");
  const rawName = String(feature.get("Place_Name") || "");
  const name = rawName.replaceAll("#", "\n").replaceAll("-\n", "\n");
  const overviewClasses = new Set(["IceShelf", "Region", "IceSheet", "Sea"]);

  if (!overviewClasses.has(labelClass) && resolution > 6500) {
    return null;
  }
  if (labelClass === "Island" && resolution > 3500) {
    return null;
  }

  const isRegion = labelClass === "Region" || labelClass === "IceSheet";
  const isWater = labelClass === "Sea" || labelClass === "IceShelf";
  const isIceShelf = labelClass === "IceShelf";
  return new ol.style.Style({
    text: new ol.style.Text({
      text: name,
      font: isRegion
        ? "700 11px system-ui, sans-serif"
        : "600 10px system-ui, sans-serif",
      fill: new ol.style.Fill({
        color: isWater ? "rgba(31,91,119,0.82)" : "rgba(55,72,80,0.80)"
      }),
      stroke: new ol.style.Stroke({ color: "rgba(255,255,255,0.94)", width: 3.5 }),
      backgroundFill: new ol.style.Fill({ color: "rgba(248,252,253,0.58)" }),
      backgroundStroke: new ol.style.Stroke({ color: "rgba(255,255,255,0.52)", width: 1 }),
      textAlign: "center",
      overflow: false,
      offsetY: isIceShelf ? -9 : 0,
      padding: [2, 3, 2, 3]
    })
  });
}

window.FrozenLegaciesStyles.scientificBasemap = scientificBasemapStyle;
window.FrozenLegaciesStyles.drainageBasin = drainageBasinStyle;
window.FrozenLegaciesStyles.antarcticPlaceName = antarcticPlaceNameStyle;
window.FrozenLegaciesStyles.riggsStation = riggsStationStyle;
