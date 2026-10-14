/* ============================================================
 * Frozen Legacies
 * radar_geometry.js
 *
 * Pure viewing geometry for the radar workspace: which window of
 * source columns to request, at which integer scale, and how to
 * label it. No DOM access and no scientific processing — the
 * server renders the pixels and will own all picker calculations.
 *
 * Loaded as a browser script (window.FrozenLegaciesRadarGeometry)
 * and as a CommonJS module by the Node unit tests.
 * ============================================================ */

(function (root) {

  "use strict";

  /* Server-supported integer downsampling factors (radar/render.py). */
  const SCALES = [1, 2, 4, 8, 16, 32, 64];

  /* Largest PNG one request may produce (radar/render.py). */
  const MAX_OUTPUT_PIXELS = 6000000;


  function ceilDiv(a, b) {
    return Math.ceil(a / b);
  }


  /* Smallest scale whose full-height output fits the viewer. */
  function fitScale(imageHeight, viewHeight) {
    for (const scale of SCALES) {
      if (ceilDiv(imageHeight, scale) <= viewHeight) {
        return scale;
      }
    }
    return SCALES[SCALES.length - 1];
  }


  /* Smallest scale whose output for a full-width view stays in limits. */
  function minScale(viewWidth, imageHeight) {
    for (const scale of SCALES) {
      if (Math.max(1, viewWidth) * ceilDiv(imageHeight, scale) <= MAX_OUTPUT_PIXELS) {
        return scale;
      }
    }
    return SCALES[SCALES.length - 1];
  }


  function clampScale(scale, viewWidth, imageHeight) {
    const lowest = minScale(viewWidth, imageHeight);
    const valid = SCALES.includes(scale) ? scale : lowest;
    return Math.max(valid, lowest);
  }


  /* Neighbouring scale: direction > 0 zooms out, < 0 zooms in. */
  function nextScale(scale, direction) {
    const index = SCALES.indexOf(scale);
    const at = index < 0 ? 0 : index;
    const next = Math.min(SCALES.length - 1, Math.max(0, at + Math.sign(direction)));
    return SCALES[next];
  }


  /* Source columns shown at this scale in a viewer `viewWidth` CSS px wide. */
  function windowWidth(viewWidth, scale, imageWidth) {
    return Math.max(1, Math.min(imageWidth, Math.floor(viewWidth) * scale));
  }


  function clampX(x, width, imageWidth) {
    return Math.max(0, Math.min(Math.round(x), imageWidth - width));
  }


  /* Move by a fraction of the current window (±0.1 step, ±1 page). */
  function shiftX(x, fraction, width, imageWidth) {
    return clampX(x + fraction * width, width, imageWidth);
  }


  /* Re-centre the same source column after a scale change. */
  function zoomAround(x, oldWidth, newWidth, imageWidth) {
    const centre = x + oldWidth / 2;
    return clampX(centre - newWidth / 2, newWidth, imageWidth);
  }


  /* Scale for a full-strip overview about `targetWidth` px wide. */
  function overviewScale(imageWidth, targetWidth) {
    for (const scale of SCALES) {
      if (ceilDiv(imageWidth, scale) <= targetWidth) {
        return scale;
      }
    }
    return SCALES[SCALES.length - 1];
  }


  /*
   * VISUAL NAVIGATION ESTIMATE ONLY.
   *
   * Linear position of a source column within the CBD range parsed
   * from the TIFF filename. It labels the viewer; it is NOT a CBD
   * assignment. ASTRA assigns CBDs to picked A-scopes differently
   * (by committed row order) and that scientific behaviour will be
   * reproduced server-side in the picker port.
   */
  function estimateViewCbd(column, imageWidth, cbdStart, cbdEnd) {
    if (
      !Number.isFinite(cbdStart) ||
      !Number.isFinite(cbdEnd) ||
      !Number.isFinite(column)
    ) {
      return null;
    }
    if (imageWidth <= 1) {
      return cbdStart;
    }
    const ratio = Math.min(1, Math.max(0, column / (imageWidth - 1)));
    return Math.round(cbdStart + (cbdEnd - cbdStart) * ratio);
  }


  /* Exact navigation record for a CBD (no interpolation). */
  function navForCbd(rows, cbd) {
    if (!Array.isArray(rows) || cbd === null || cbd === undefined) {
      return null;
    }
    return rows.find(row => row.cbd === cbd) || null;
  }


  /*
   * Shared radar sources explicitly linked to a selection. A source
   * is linked only when it names the selection's dataset, and then
   * its observation TIFF (if declared) or flight. Nothing inferred.
   */
  function matchSources(sources, selection) {
    if (!Array.isArray(sources) || !selection) {
      return [];
    }
    const datasetId = selection.datasetId ?? null;
    const flight = selection.flight === null || selection.flight === undefined
      ? null
      : String(selection.flight);
    const tiff = selection.tiff ?? null;

    return sources.filter(source => {
      if (!source.dataset_id || source.dataset_id !== datasetId) {
        return false;
      }
      if (source.observation_tiff) {
        return tiff !== null && source.observation_tiff === tiff;
      }
      return flight !== null && source.flight !== null && String(source.flight) === flight;
    });
  }


  /*
   * ASTRA picker: a click in the displayed working window -> matplotlib
   * data coordinates (imshow: pixel i is centred on i and spans
   * [i - 0.5, i + 0.5)). The server applies ASTRA's int() conversion.
   * Returns null outside the window (matplotlib's xdata/ydata = None).
   */
  function astraDataCoordinates(clientX, clientY, rect, zoomWidth, zoomHeight) {
    if (!rect || rect.width <= 0 || rect.height <= 0) {
      return null;
    }
    const x = ((clientX - rect.left) / rect.width) * zoomWidth - 0.5;
    const y = ((clientY - rect.top) / rect.height) * zoomHeight - 0.5;
    const inside =
      x >= -0.5 && x < zoomWidth - 0.5 &&
      y >= -0.5 && y < zoomHeight - 0.5;
    return inside ? { x, y } : null;
  }


  /*
   * ASTRA picker: the largest box with the working window's exact
   * aspect ratio that fits the stage. The width is a whole number of
   * CSS px and the height follows it exactly (it may be fractional),
   * so the window is never stretched in one direction only, at any
   * stage size. Clicks are mapped against this box
   * (astraDataCoordinates), so the mapping does not depend on its size.
   */
  function fitBox(stageWidth, stageHeight, zoomWidth, zoomHeight) {
    if (!(zoomWidth > 0) || !(zoomHeight > 0)) {
      return null;
    }
    const availableWidth = Math.max(100, Math.floor(stageWidth || 0));
    const availableHeight = Math.max(80, stageHeight || 0);
    const width = Math.max(1, Math.floor(
      Math.min(availableWidth, (availableHeight * zoomWidth) / zoomHeight)
    ));
    return { width, height: (width * zoomHeight) / zoomWidth };
  }


  function viewUrl(assetId, x, width, scale) {
    return (
      `/frozen-legacies/api/assets/${encodeURIComponent(assetId)}/view` +
      `?x=${x}&width=${width}&scale=${scale}`
    );
  }


  const api = {
    SCALES,
    MAX_OUTPUT_PIXELS,
    fitScale,
    minScale,
    clampScale,
    nextScale,
    windowWidth,
    clampX,
    shiftX,
    zoomAround,
    overviewScale,
    estimateViewCbd,
    navForCbd,
    matchSources,
    astraDataCoordinates,
    fitBox,
    viewUrl
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }

  root.FrozenLegaciesRadarGeometry = api;

})(typeof window !== "undefined" ? window : globalThis);
