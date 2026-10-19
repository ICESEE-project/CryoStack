/* Display-only clipping for the Ross Ice Shelf focused collection. */
(function () {
  "use strict";

  function rings(geometry) {
    if (!geometry) return [];
    if (geometry.getType() === "Polygon") return geometry.getCoordinates();
    if (geometry.getType() === "MultiPolygon") {
      return geometry.getCoordinates().flatMap(polygon => polygon);
    }
    throw new Error("Ross Ice Shelf boundary must be a Polygon or MultiPolygon.");
  }

  function intersectionParameter(a, b, c, d) {
    const rx = b[0] - a[0];
    const ry = b[1] - a[1];
    const sx = d[0] - c[0];
    const sy = d[1] - c[1];
    const denominator = rx * sy - ry * sx;
    if (Math.abs(denominator) < 1e-10) return null;
    const qx = c[0] - a[0];
    const qy = c[1] - a[1];
    const t = (qx * sy - qy * sx) / denominator;
    const u = (qx * ry - qy * rx) / denominator;
    return t >= 0 && t <= 1 && u >= 0 && u <= 1 ? t : null;
  }

  function interpolate(a, b, t) {
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  }

  function sameCoordinate(a, b) {
    return Math.abs(a[0] - b[0]) < 1e-7 && Math.abs(a[1] - b[1]) < 1e-7;
  }

  function clipLine(line, boundary, boundaryRings) {
    const pieces = [];
    let active = null;
    for (let index = 1; index < line.length; index += 1) {
      const start = line[index - 1];
      const end = line[index];
      const parameters = [0, 1];
      for (const ring of boundaryRings) {
        for (let edge = 1; edge < ring.length; edge += 1) {
          const value = intersectionParameter(start, end, ring[edge - 1], ring[edge]);
          if (value !== null) parameters.push(value);
        }
      }
      parameters.sort((left, right) => left - right);
      const unique = parameters.filter((value, position) =>
        position === 0 || Math.abs(value - parameters[position - 1]) > 1e-10
      );
      for (let part = 1; part < unique.length; part += 1) {
        const lower = unique[part - 1];
        const upper = unique[part];
        const midpoint = interpolate(start, end, (lower + upper) / 2);
        if (!boundary.intersectsCoordinate(midpoint)) {
          active = null;
          continue;
        }
        const left = interpolate(start, end, lower);
        const right = interpolate(start, end, upper);
        if (active && sameCoordinate(active[active.length - 1], left)) {
          active.push(right);
        } else {
          active = [left, right];
          pieces.push(active);
        }
      }
    }
    return pieces;
  }

  function clipFlight(feature, boundary) {
    const geometry = feature.getGeometry();
    if (!geometry) return null;
    const type = geometry.getType();
    const lines = type === "LineString"
      ? [geometry.getCoordinates()]
      : type === "MultiLineString"
        ? geometry.getCoordinates()
        : [];
    const clipped = lines.flatMap(line => clipLine(line, boundary, rings(boundary)));
    if (!clipped.length) return null;
    const result = feature.clone();
    result.setGeometry(new ol.geom.MultiLineString(clipped));
    result.set("display_region", "Ross Ice Shelf", true);
    result.set("display_clipped", true, true);
    return result;
  }

  function focus({ flightFeatures, observationFeatures, boundaryFeature }) {
    const boundary = boundaryFeature?.getGeometry?.();
    if (!boundary) throw new Error("Ross Ice Shelf display boundary is unavailable.");
    const flights = flightFeatures
      .map(feature => clipFlight(feature, boundary))
      .filter(Boolean);
    const observations = observationFeatures.filter(feature => {
      const coordinate = feature.getGeometry()?.getCoordinates?.();
      return Array.isArray(coordinate) && boundary.intersectsCoordinate(coordinate);
    });
    for (const feature of observations) {
      feature.set("display_region", "Ross Ice Shelf", true);
    }
    return { flights, observations };
  }

  window.FrozenLegaciesRossFocus = { focus };
})();
