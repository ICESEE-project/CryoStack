/* ============================================================
 * Frozen Legacies
 * ui.js
 *
 * Owns:
 *   - dataset dropdown
 *   - flight dropdown
 *   - selected-dataset state
 *   - selected-flight state
 *   - observation detail panel
 *   - map click interaction
 *   - map hover cursor
 *   - filtering/highlighting
 *
 * Does NOT own:
 *   - projection
 *   - map construction
 *   - data fetching
 *   - layer construction
 * ============================================================ */


/* ------------------------------------------------------------
 * DOM helpers
 * ------------------------------------------------------------ */

function getDatasetSelectElement() {

  return document.getElementById(
    "dataset-select"
  );

}


function getFlightSelectElement() {

  return document.getElementById(
    "flight-select"
  );

}


function getSelectedRecordElement() {

  return document.getElementById(
    "selected-record"
  );

}


/* ------------------------------------------------------------
 * Dataset helpers
 * ------------------------------------------------------------ */

function normalizeDatasetValue(
  value
) {

  return FrozenLegaciesData
    .normalizeDatasetValue(
      value
    );

}


function datasetForFeature(
  feature
) {

  if (!feature) {
    return "";
  }


  return normalizeDatasetValue(
    feature.get(
      "dataset_id"
    )
  );

}


function datasetMatches(
  feature,
  datasetId
) {

  const normalizedDataset =
    normalizeDatasetValue(
      datasetId
    );


  if (
    !normalizedDataset ||
    normalizedDataset === "all"
  ) {
    return true;
  }


  return (
    datasetForFeature(
      feature
    ) === normalizedDataset
  );

}


/* Stable, shareable observation selection. */
function observationSelectionId(feature) {
  if (!feature) return "";
  const properties = feature.getProperties?.() || {};
  const id = properties.asset_id || properties.observation_id ||
    properties.file_id || feature.getId?.();
  return id === null || id === undefined ? "" : String(id);
}


function orderedFlightObservations(data, datasetId, flightNumber) {
  const observations = FrozenLegaciesData.getFlightObservations(data, flightNumber, datasetId);
  return [...observations].sort((left, right) => {
    const aCbd = Number(left.get("cbd"));
    const bCbd = Number(right.get("cbd"));
    if (Number.isFinite(aCbd) && Number.isFinite(bCbd) && aCbd !== bCbd) return aCbd - bCbd;
    if (Number.isFinite(aCbd) !== Number.isFinite(bCbd)) return Number.isFinite(aCbd) ? -1 : 1;
    return observationSelectionId(left).localeCompare(
      observationSelectionId(right), "en", {numeric: true, sensitivity: "base"}
    );
  });
}


function orderedDatasetFlights(data, datasetId) {
  const seen = new Map();
  for (const feature of data.flightFeatures || []) {
    const flight = FrozenLegaciesData.normalizeFlightValue(feature.get("flight"));
    if (flight && datasetForFeature(feature) === datasetId && !seen.has(flight)) {
      seen.set(flight, feature);
    }
  }
  return [...seen.entries()].sort(([left], [right]) =>
    String(left).localeCompare(String(right), "en", {numeric: true, sensitivity: "base"}));
}


function writeObservationSelectionUrl(feature) {
  if (!window.history?.replaceState || !window.location) return;
  const properties = feature?.getProperties?.() || {};
  const datasetId = normalizeDatasetValue(properties.dataset_id);
  const flight = FrozenLegaciesData.normalizeFlightValue(properties.flight);
  const observation = observationSelectionId(feature);
  if (!datasetId || !flight || !observation) return;
  const url = new URL(window.location.href);
  url.searchParams.set("dataset", datasetId);
  url.searchParams.set("flight", flight);
  url.searchParams.set("observation", observation);
  window.history.replaceState(window.history.state, "", url);
}


function clearObservationSelectionUrl() {
  if (!window.history?.replaceState || !window.location) return;
  const url = new URL(window.location.href);
  url.searchParams.delete("observation");
  window.history.replaceState(window.history.state, "", url);
}


function writeExplorerContextUrl(datasetId, flightNumber = "all") {
  if (window.FrozenLegaciesExplorerStore) {
    window.FrozenLegaciesExplorerStore.set({
      dataset: datasetId && datasetId !== "all" ? [datasetId] : [],
      flight: flightNumber && flightNumber !== "all" ? [String(flightNumber)] : []
    });
    return;
  }
  if (!window.history?.replaceState || !window.location) return;
  const url = new URL(window.location.href);
  const dataset = normalizeDatasetValue(datasetId);
  const flight = FrozenLegaciesData.normalizeFlightValue(flightNumber);
  if (dataset && dataset !== "all") url.searchParams.set("dataset", dataset);
  else url.searchParams.delete("dataset");
  if (flight && flight !== "all") url.searchParams.set("flight", flight);
  else url.searchParams.delete("flight");
  url.searchParams.delete("observation");
  window.history.replaceState(window.history.state, "", url);
}


function bindScientificExplorer({map, data, layers, state}) {
  const queryApi = window.FrozenLegaciesExplorerQuery;
  if (!queryApi) return null;
  const store = queryApi.createStore(queryApi.parse(window.location));
  window.FrozenLegaciesExplorerStore = store;
  const byId = id => document.getElementById(id);
  const controls = {
    cbd_min: byId("fl-filter-cbd-min"), cbd_max: byId("fl-filter-cbd-max"),
    review: byId("fl-filter-review"), q: byId("fl-filter-query")
  };
  const queryKeys = ["qv", "audience", "dataset", "ds", "flight", "source", "product", "review",
    "cbd_min", "cbd_max", "q", "sort"];

  function writeUrl(query, push = false) {
    const current = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    queryKeys.forEach(key => current.delete(key));
    const canonical = new URLSearchParams(queryApi.serialize(query));
    canonical.forEach((value, key) => current.append(key, value));
    const url = new URL(window.location.href);
    url.hash = current.toString();
    window.history[push ? "pushState" : "replaceState"](window.history.state, "", url);
  }

  function matches(feature, query) {
    const dataset = datasetForFeature(feature);
    const flight = FrozenLegaciesData.normalizeFlightValue(feature.get("flight"));
    const cbd = Number(feature.get("cbd"));
    if (query.dataset?.length && !query.dataset.includes(dataset)) return false;
    if (query.flight?.length && !query.flight.includes(flight)) return false;
    if (query.cbd_min && (!Number.isFinite(cbd) || cbd < Number(query.cbd_min))) return false;
    if (query.cbd_max && (!Number.isFinite(cbd) || cbd > Number(query.cbd_max))) return false;
    if (query.q) {
      const haystack = Object.values(feature.getProperties?.() || {}).join(" ").toLowerCase();
      if (!haystack.includes(query.q.toLowerCase())) return false;
    }
    return true;
  }

  function identityMatches(feature, query) {
    const dataset = datasetForFeature(feature);
    const flight = FrozenLegaciesData.normalizeFlightValue(feature.get("flight"));
    return (!query.dataset?.length || query.dataset.includes(dataset)) &&
      (!query.flight?.length || query.flight.includes(flight));
  }

  function render(query, {write = true, push = false} = {}) {
    const selectedDataset = query.dataset?.[0] || "all";
    const selectedFlight = query.flight?.[0] || "all";
    state.datasetId = selectedDataset;
    state.flightNumber = selectedFlight;
    const datasetSelect = getDatasetSelectElement();
    if (datasetSelect) datasetSelect.value = selectedDataset;
    refreshFlightSelectorForDataset({data, datasetId: selectedDataset});
    const flightSelect = getFlightSelectElement();
    if (flightSelect) flightSelect.value = selectedFlight;
    for (const [key, control] of Object.entries(controls)) {
      if (control) control.value = key === "review" ? (query.review?.[0] || "") : (query[key] || "");
    }
    const chips = [];
    const labels = {dataset: "Dataset", flight: "Flight", review: "Review", cbd_min: "CBD from", cbd_max: "CBD to", q: "Search"};
    for (const key of Object.keys(labels)) {
      const raw = query[key];
      for (const value of (Array.isArray(raw) ? raw : (raw ? [raw] : []))) {
        chips.push(`<button type="button" data-remove-filter="${escapeHtmlUI(key)}" aria-label="Remove ${escapeHtmlUI(labels[key])} ${escapeHtmlUI(value)}">${escapeHtmlUI(labels[key])}: ${escapeHtmlUI(value)} ×</button>`);
      }
    }
    const chipRoot = byId("fl-active-filters");
    if (chipRoot) chipRoot.innerHTML = chips.join("");
    chipRoot?.querySelectorAll("[data-remove-filter]").forEach(button => button.addEventListener("click", () => {
      const key = button.dataset.removeFilter;
      store.set({[key]: Array.isArray(store.get()[key]) ? [] : ""});
    }));

    const observations = layers.layers.observations.getSource().getFeatures();
    const visible = observations.filter(feature => matches(feature, query));
    layers.sources.frozen.selectedFlight.clear(true);
    layers.layers.flights.setStyle(feature => identityMatches(feature, query)
      ? FrozenLegaciesStyles.defaultFlight() : null);
    layers.layers.observations.setStyle(feature => matches(feature, query)
      ? FrozenLegaciesStyles.observation(feature) : null);
    const status = byId("fl-filter-status");
    if (status) status.textContent = `${visible.length.toLocaleString("en-US")} observation${visible.length === 1 ? "" : "s"} match the active map filters.`;
    window.FrozenLegaciesCatalog?.applyExplorerQuery?.(query);
    if (write) writeUrl(query, push);
  }

  let pushNext = false;
  store.subscribe(query => { render(query, {push: pushNext}); pushNext = false; });
  for (const [key, control] of Object.entries(controls)) {
    control?.addEventListener(key === "q" ? "input" : "change", () => {
      pushNext = key !== "q";
      store.set({[key]: key === "review" ? (control.value ? [control.value] : []) : control.value});
    });
  }
  byId("fl-filter-clear")?.addEventListener("click", () => { pushNext = true; store.clear(); });
  byId("fl-filter-copy")?.addEventListener("click", async event => {
    writeUrl(store.get());
    try {
      await navigator.clipboard.writeText(window.location.href);
      event.currentTarget.textContent = "Link copied";
      window.setTimeout(() => { event.currentTarget.textContent = "Copy link"; }, 1500);
    } catch (_error) {
      event.currentTarget.textContent = "Copy unavailable";
    }
  });
  window.addEventListener("popstate", () => store.replace(queryApi.parse(window.location)));
  render(store.get(), {write: false});
  return store;
}


/* ------------------------------------------------------------
 * Empty observation state
 * ------------------------------------------------------------ */

/* ------------------------------------------------------------
 * Selection event
 *
 * Other Frozen Legacies modules (the radar workspace) follow the
 * selected observation through this event instead of reaching into
 * the explorer's rendering.
 * ------------------------------------------------------------ */

function announceObservationSelection(
  properties
) {

  document.dispatchEvent(
    new CustomEvent(
      "frozen-legacies:observation",
      {
        detail: {
          properties:
            properties || null
        }
      }
    )
  );

}


function renderEmptyObservation(
  dataset = null
) {

  const container =
    getSelectedRecordElement();


  if (!container) {
    return;
  }


  const datasetTitle =
    dataset?.title ||
    dataset?.name ||
    null;


  container.innerHTML = `
    <div class="fl-empty-selection">

      <div class="fl-empty-icon">
        ⌖
      </div>

      <div>

        <strong>
          Select a radar observation
        </strong>

        <span>
          ${
            datasetTitle
              ? `Click a point from ${escapeHtmlUI(datasetTitle)} to inspect the radar record.`
              : "Click a point on the Antarctic map to inspect a radar record."
          }
        </span>

      </div>

    </div>
  `;


  announceObservationSelection(
    null
  );

}


/* ------------------------------------------------------------
 * Formatting helpers
 * ------------------------------------------------------------ */

function formatNumber(
  value,
  {
    digits = 2,
    suffix = ""
  } = {}
) {

  if (
    value === null ||
    value === undefined ||
    value === ""
  ) {
    return "—";
  }


  const number =
    Number(value);


  if (
    !Number.isFinite(number)
  ) {
    return String(value);
  }


  return (
    number.toFixed(
      digits
    ) +
    suffix
  );

}


function formatLatitude(
  value
) {

  const number =
    Number(value);


  if (
    !Number.isFinite(number)
  ) {
    return "—";
  }


  return (
    `${Math.abs(number).toFixed(5)}°` +
    (
      number < 0
        ? "S"
        : "N"
    )
  );

}


function formatLongitude(
  value
) {

  const number =
    Number(value);


  if (
    !Number.isFinite(number)
  ) {
    return "—";
  }


  return (
    `${Math.abs(number).toFixed(5)}°` +
    (
      number < 0
        ? "W"
        : "E"
    )
  );

}


/* ------------------------------------------------------------
 * Safe HTML helper
 * ------------------------------------------------------------ */

function escapeHtmlUI(
  value
) {

  return String(
    value ?? ""
  )
    .replaceAll(
      "&",
      "&amp;"
    )
    .replaceAll(
      "<",
      "&lt;"
    )
    .replaceAll(
      ">",
      "&gt;"
    )
    .replaceAll(
      '"',
      "&quot;"
    )
    .replaceAll(
      "'",
      "&#039;"
    );

}


/* ------------------------------------------------------------
 * Observation media
 * ------------------------------------------------------------ */

function observationImageUrl(
  properties
) {

  const candidates = [

    properties.image_url,

    properties.image_path,

    properties.radar_image,

    properties.echogram,

    properties.radargram

  ];


  for (
    const value
    of candidates
  ) {

    if (
      value !== null &&
      value !== undefined &&
      String(value).trim()
    ) {

      return String(
        value
      ).trim();

    }

  }


  return null;

}


function observationMediaUrls(properties) {
  const first = values => values.find(value =>
    value !== null && value !== undefined && String(value).trim());
  const flight = FrozenLegaciesData.normalizeFlightValue(properties.flight);
  const cbd = Number(properties.cbd);
  const temporaryPreview = scope => (flight && Number.isFinite(cbd))
    ? `/frozen-legacies/api/radar/catalog/observation-preview?v=2&scope=${encodeURIComponent(scope)}&flight=${encodeURIComponent(flight)}&cbd=${encodeURIComponent(cbd)}`
    : null;
  return {
    film: first([properties.image_url, properties.image_path,
      properties.radar_image, properties.film_image]) || temporaryPreview("ascope"),
    radargram: first([properties.echogram, properties.radargram,
      properties.processed_image_url]) || temporaryPreview("zscope")
  };
}


function bindPreviewFallbacks(container) {
  container?.querySelectorAll("img[data-fl-preview]").forEach(image => image.addEventListener("error", () => {
    const fallback = document.createElement("div");
    fallback.className = image.classList.contains("fl-popup-preview")
      ? "fl-popup-preview fl-popup-preview-empty"
      : "fl-radar-preview-empty";
    fallback.textContent = image.dataset.empty || "Preview is not available.";
    image.replaceWith(fallback);
  }, {once: true}));
}


function renderObservationMedia(
  properties
) {
  const media = observationMediaUrls(properties);
  const card = (label, value, absent) => `
    <figure class="fl-radar-preview">
      <figcaption>${escapeHtmlUI(label)}</figcaption>
      ${value ? `<img src="${escapeHtmlUI(value)}" alt="${escapeHtmlUI(label)}" class="fl-radar-image" data-fl-preview data-empty="${escapeHtmlUI(absent)}" loading="lazy">`
        : `<div class="fl-radar-preview-empty"><div class="fl-radar-preview-icon">◫</div><div><strong>${escapeHtmlUI(label)}</strong><span>${escapeHtmlUI(absent)}</span></div></div>`}
    </figure>`;
  return `<div class="fl-radar-preview-grid">
    ${card("A-scope film scan", media.film, "A-scope film scan not indexed yet.")}
    ${card("Z-scope radar image", media.radargram, "Z-scope radar image not indexed yet.")}
  </div>`;

}


function observationPopupHtml(feature, data = null, navigation = null) {
  const properties = feature.getProperties();
  const datasetId = normalizeDatasetValue(properties.dataset_id);
  const dataset = data?.datasetIndex?.get(datasetId) || null;
  const datasetTitle = dataset?.title || dataset?.name || datasetId || "Frozen Legacies";
  const echo = properties.echo_status || "unknown";
  const media = observationMediaUrls(properties);
  const title = properties.file_id || `Flight ${properties.flight ?? "—"}`;
  const preview = (label, value, absent) => `<figure class="fl-popup-media-card">
    <figcaption>${escapeHtmlUI(label)}</figcaption>
    ${value ? `<img class="fl-popup-preview" src="${escapeHtmlUI(value)}" data-fl-preview data-empty="${escapeHtmlUI(absent)}"
      alt="${escapeHtmlUI(label)} quicklook for ${escapeHtmlUI(title)}" loading="lazy">`
      : `<div class="fl-popup-preview fl-popup-preview-empty"><span>${escapeHtmlUI(absent)}</span></div>`}
  </figure>`;

  return `
    <button type="button" class="fl-popup-close" aria-label="Close observation quicklook">×</button>
    <div class="fl-popup-drag-handle" data-fl-popup-drag tabindex="0"
      aria-label="Move quicklook panel. Use arrow keys to reposition.">
      <span class="fl-popup-kicker">SCIENTIFIC QUICKLOOK · Quicklook only</span><span aria-hidden="true">⠿</span>
    </div>
    <div class="fl-popup-title-row">
      <div>
        <strong>${escapeHtmlUI(title)}</strong>
        <span>Flight ${escapeHtmlUI(properties.flight ?? "—")} · CBD ${escapeHtmlUI(properties.cbd ?? "—")} · ${escapeHtmlUI(datasetTitle)}</span>
      </div>
      <span class="fl-popup-status">${escapeHtmlUI(echo)}</span>
    </div>
    <div class="fl-popup-media-grid">
    ${preview("A-scope film scan", media.film, "A-scope film scan not indexed yet.")}
    ${preview("Z-scope radar image", media.radargram, "Z-scope radar image not indexed yet.")}
    </div>
    <div class="fl-popup-actions">
      <span class="fl-popup-workspace-actions">
        <button type="button" class="fl-radar-button primary" data-fl-popup-action="manual">Open radar workspace</button>
        <button type="button" class="fl-radar-button" data-fl-popup-action="details">Full details</button>
      </span>
      <span class="fl-popup-navigation" role="group" aria-label="Flights in this dataset">
        <button type="button" class="fl-radar-button" data-fl-popup-action="previous-flight"
          ${navigation?.hasPreviousFlight ? "" : "disabled"} aria-label="Previous flight">← Flight</button>
        <span aria-live="polite">${escapeHtmlUI(navigation?.flightPosition || "")}</span>
        <button type="button" class="fl-radar-button" data-fl-popup-action="next-flight"
          ${navigation?.hasNextFlight ? "" : "disabled"} aria-label="Next flight">Flight →</button>
      </span>
      <span class="fl-popup-navigation fl-popup-observation-navigation" role="group" aria-label="Observations in this flight">
        <button type="button" class="fl-radar-button quiet" data-fl-popup-action="previous-observation"
          ${navigation?.hasPreviousObservation ? "" : "disabled"} aria-label="Previous observation">← Obs</button>
        <span aria-live="polite">${escapeHtmlUI(navigation?.observationPosition || "")}</span>
        <button type="button" class="fl-radar-button quiet" data-fl-popup-action="next-observation"
          ${navigation?.hasNextObservation ? "" : "disabled"} aria-label="Next observation">Obs →</button>
      </span>
    </div>`;
}


function quicklookScrollBehavior() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches
    ? "auto"
    : "smooth";
}


function closeObservationPopup(element, {restoreFocus = true} = {}) {
  if (!element) return;
  element._flOverlay?.setPosition(undefined);
  element.hidden = true;
  clearObservationSelectionUrl();
  if (restoreFocus) {
    const target = element._flReturnFocus;
    if (target?.isConnected && typeof target.focus === "function") {
      target.focus({preventScroll: true});
    } else {
      element._flMapTarget?.focus?.({preventScroll: true});
    }
  }
}


function popupInteractiveTarget(target) {
  return target.closest("button, a, input, select, textarea, label, summary, [role='button'], [contenteditable='true']");
}


function ensureObservationPopup(map) {
  const element = document.getElementById("fl-observation-popup");
  if (!element) return null;
  if (!element._flOverlay) {
    element._flOverlay = new ol.Overlay({
      element,
      positioning: "bottom-center",
      offset: [0, -14],
      stopEvent: true,
      autoPan: { animation: { duration: 180 }, margin: 24 }
    });
    map.addOverlay(element._flOverlay);
    element._flDragOffset = [0, -14];
    element._flMapTarget = map.getTargetElement?.() || null;
    element.addEventListener("click", event => {
      if (event.target.closest(".fl-popup-close")) {
        closeObservationPopup(element);
      }
      if (event.target.closest('[data-fl-popup-action="previous-flight"]')) element._flNavigateFlight?.(-1);
      if (event.target.closest('[data-fl-popup-action="next-flight"]')) element._flNavigateFlight?.(1);
      if (event.target.closest('[data-fl-popup-action="previous-observation"]')) element._flNavigateObservation?.(-1);
      if (event.target.closest('[data-fl-popup-action="next-observation"]')) element._flNavigateObservation?.(1);
      if (event.target.closest('[data-fl-popup-action="manual"]')) {
        document.querySelector('[data-mode="manual"]')?.click();
      }
      if (event.target.closest('[data-fl-popup-action="details"]')) {
        document.getElementById("selected-record")?.scrollIntoView({
          behavior: quicklookScrollBehavior(), block: "nearest"
        });
      }
    });
    element.addEventListener("keydown", event => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeObservationPopup(element);
      } else if (event.target.closest("[data-fl-popup-drag]") && event.key.startsWith("Arrow")) {
        event.preventDefault();
        const step = event.shiftKey ? 40 : 12;
        const delta = {ArrowLeft: [-step, 0], ArrowRight: [step, 0],
          ArrowUp: [0, -step], ArrowDown: [0, step]}[event.key];
        if (delta) {
          element._flDragOffset = [element._flDragOffset[0] + delta[0],
            element._flDragOffset[1] + delta[1]];
          element._flOverlay.setOffset(element._flDragOffset);
        }
      } else if (event.key === "ArrowLeft" && !event.target.closest("input, select, textarea")) {
        event.preventDefault();
        element._flNavigateFlight?.(-1);
      } else if (event.key === "ArrowRight" && !event.target.closest("input, select, textarea")) {
        event.preventDefault();
        element._flNavigateFlight?.(1);
      }
    });
    element.addEventListener("pointerdown", event => {
      if (event.button !== 0 || popupInteractiveTarget(event.target) ||
          window.matchMedia("(max-width: 680px)").matches) return;
      event.preventDefault();
      const start = [event.clientX, event.clientY];
      const original = [...element._flDragOffset];
      element.setPointerCapture(event.pointerId);
      const move = moveEvent => {
        if (moveEvent.pointerId !== event.pointerId) return;
        element._flDragOffset = [original[0] + moveEvent.clientX - start[0],
          original[1] + moveEvent.clientY - start[1]];
        element._flOverlay.setOffset(element._flDragOffset);
      };
      const finish = finishEvent => {
        if (finishEvent.pointerId !== event.pointerId) return;
        element.removeEventListener("pointermove", move);
        element.removeEventListener("pointerup", finish);
        element.removeEventListener("pointercancel", finish);
      };
      element.addEventListener("pointermove", move);
      element.addEventListener("pointerup", finish);
      element.addEventListener("pointercancel", finish);
    });
  }
  return element;
}


function showObservationPopup(map, feature, data, coordinate, navigation = null) {
  const element = ensureObservationPopup(map);
  if (!element) return;
  const wasHidden = element.hidden;
  if (wasHidden) {
    const active = document.activeElement;
    element._flReturnFocus = active && active !== document.body && active !== document.documentElement
      ? active
      : element._flMapTarget;
    element._flDragOffset = [0, -14];
    element._flOverlay.setOffset(element._flDragOffset);
  }
  element.innerHTML = observationPopupHtml(feature, data, navigation);
  bindPreviewFallbacks(element);
  element._flNavigateFlight = navigation?.navigateFlight || null;
  element._flNavigateObservation = navigation?.navigateObservation || null;
  element.hidden = false;
  element._flOverlay.setPosition(coordinate || feature.getGeometry()?.getCoordinates());
  if (wasHidden) {
    element.querySelector(".fl-popup-close")?.focus({preventScroll: true});
  }
}


/* ------------------------------------------------------------
 * Observation panel
 * ------------------------------------------------------------ */

function renderObservation(
  feature,
  data = null
) {

  const container =
    getSelectedRecordElement();


  if (
    !container ||
    !feature
  ) {
    return;
  }


  const properties =
    feature.getProperties();


  const geometry =
    feature.getGeometry();


  let longitude =
    null;

  let latitude =
    null;


  if (
    geometry &&
    geometry.getType() === "Point"
  ) {

    const coordinate =
      FrozenLegaciesMap.toLonLat(
        geometry.getCoordinates()
      );


    longitude =
      coordinate[0];

    latitude =
      coordinate[1];

  }


  const datasetId =
    normalizeDatasetValue(
      properties.dataset_id
    );


  const dataset =
    data?.datasetIndex?.get(
      datasetId
    ) || null;


  const datasetTitle =
    dataset?.title ||
    dataset?.name ||
    datasetId ||
    "Frozen Legacies";


  const title =
    properties.file_id ||
    (
      properties.flight
        ? `Flight ${properties.flight}`
        : "Radar observation"
    );


  const echo =
    properties.echo_status ||
    "unknown";


  const echoColor =
    FrozenLegaciesStyles
      .observationStatusColor(
        echo
      );


  container.innerHTML = `

    <div class="fl-record">

      <div class="fl-record-header">

        <div>

          <div class="fl-record-eyebrow">
            SELECTED OBSERVATION
          </div>

          <div class="fl-record-title">
            ${escapeHtmlUI(title)}
          </div>

          <div class="fl-record-subtitle">
            Flight ${escapeHtmlUI(properties.flight ?? "—")}
            ·
            CBD ${escapeHtmlUI(properties.cbd ?? "—")}
          </div>

        </div>


        <div
          class="fl-record-status"
          style="
            --fl-record-status-color:
            ${echoColor};
          "
        >
          ${escapeHtmlUI(echo)}
        </div>

      </div>


      ${
        renderObservationMedia(
          properties
        )
      }


      <div class="fl-record-section">

        <div class="fl-record-section-title">
          Dataset
        </div>


        <div class="fl-record-provenance">

          <div>

            <span>
              Collection
            </span>

            <strong>
              ${escapeHtmlUI(datasetTitle)}
            </strong>

          </div>


          <div>

            <span>
              Dataset ID
            </span>

            <strong>
              ${escapeHtmlUI(datasetId || "—")}
            </strong>

          </div>

        </div>

      </div>


      <div class="fl-record-section">

        <div class="fl-record-section-title">
          Location
        </div>


        <div class="fl-record-grid">

          <div class="fl-record-item">

            <span>
              Latitude
            </span>

            <strong>
              ${formatLatitude(latitude)}
            </strong>

          </div>


          <div class="fl-record-item">

            <span>
              Longitude
            </span>

            <strong>
              ${formatLongitude(longitude)}
            </strong>

          </div>

        </div>

      </div>


      <div class="fl-record-section">

        <div class="fl-record-section-title">
          LYRA-derived quantities
        </div>


        <div class="fl-record-metrics">

          <div class="fl-record-metric">

            <span>
              Ice thickness
            </span>

            <strong>
              ${
                formatNumber(
                  properties.h_ice_m,
                  {
                    digits: 1,
                    suffix: " m"
                  }
                )
              }
            </strong>

          </div>


          <div class="fl-record-metric">

            <span>
              Bed SNR
            </span>

            <strong>
              ${
                formatNumber(
                  properties.bed_snr_dB,
                  {
                    digits: 2,
                    suffix: " dB"
                  }
                )
              }
            </strong>

          </div>


          <div class="fl-record-metric">

            <span>
              Surface temperature
            </span>

            <strong>
              ${
                formatNumber(
                  properties.T_surface_C,
                  {
                    digits: 2,
                    suffix: " °C"
                  }
                )
              }
            </strong>

          </div>


          <div class="fl-record-metric">

            <span>
              Reflectivity
            </span>

            <strong>
              ${
                formatNumber(
                  properties.R0_dB,
                  {
                    digits: 2,
                    suffix: " dB"
                  }
                )
              }
            </strong>

          </div>


          <div class="fl-record-metric">

            <span>
              Attenuation
            </span>

            <strong>
              ${
                formatNumber(
                  properties.L_atten_dB,
                  {
                    digits: 2,
                    suffix: " dB"
                  }
                )
              }
            </strong>

          </div>


          <div class="fl-record-metric">

            <span>
              Specularity
            </span>

            <strong>
              ${
                formatNumber(
                  properties.specularity,
                  {
                    digits: 3
                  }
                )
              }
            </strong>

          </div>

        </div>

      </div>


      <div class="fl-record-section">

        <div class="fl-record-section-title">
          Record provenance
        </div>


        <div class="fl-record-provenance">

          <div>

            <span>
              Source
            </span>

            <strong>
              ${
                escapeHtmlUI(
                  properties._source_file ??
                  "Frozen Legacies"
                )
              }
            </strong>

          </div>


          <div>

            <span>
              Frame
            </span>

            <strong>
              ${
                escapeHtmlUI(
                  properties.frame_idx ??
                  "—"
                )
              }
            </strong>

          </div>

        </div>

      </div>

    </div>
  `;

  bindPreviewFallbacks(container);


  announceObservationSelection(
    properties
  );

}


/* ------------------------------------------------------------
 * Dataset dropdown
 * ------------------------------------------------------------ */

function populateDatasetSelector(
  catalog
) {

  const select =
    getDatasetSelectElement();


  if (!select) {
    return;
  }


  select.innerHTML = `
    <option value="all">
      All datasets
    </option>
  `;


  for (
    const dataset
    of catalog?.datasets || []
  ) {

    if (!dataset?.id) {
      continue;
    }


    const option =
      document.createElement(
        "option"
      );


    option.value =
      String(
        dataset.id
      );


    option.textContent =
      dataset.title ||
      dataset.name ||
      dataset.id;


    select.appendChild(
      option
    );

  }

}


/* ------------------------------------------------------------
 * Flight dropdown
 * ------------------------------------------------------------ */

function populateFlightSelector(
  flightNumbers
) {

  const select =
    getFlightSelectElement();


  if (!select) {
    return;
  }


  select.innerHTML = `
    <option value="all">
      All flights
    </option>
  `;


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


    select.appendChild(
      option
    );

  }

}


/* ------------------------------------------------------------
 * Refresh flights for selected dataset
 * ------------------------------------------------------------ */

function refreshFlightSelectorForDataset({
  data,
  datasetId
}) {

  const normalizedDataset =
    normalizeDatasetValue(
      datasetId
    );


  const flights =
    FrozenLegaciesData
      .flightNumbersForDataset(
        data.raw.observations,

        normalizedDataset === "all"
          ? null
          : normalizedDataset,

        data.raw.flights
      );


  populateFlightSelector(
    flights
  );


  return flights;

}


/* ------------------------------------------------------------
 * Show all flights for current dataset
 * ------------------------------------------------------------ */

function showAllFlights({
  map,
  data,
  layers,
  state
}) {

  if (
    !map ||
    !data ||
    !layers
  ) {
    return;
  }


  const datasetId =
    normalizeDatasetValue(
      state?.datasetId ||
      "all"
    );


  layers
    .sources
    .frozen
    .selectedFlight
    .clear(
      true
    );


  layers
    .layers
    .flights
    .setStyle(
      feature => {

        if (
          !datasetMatches(
            feature,
            datasetId
          )
        ) {
          return null;
        }


        return FrozenLegaciesStyles
          .defaultFlight();

      }
    );


  layers
    .layers
    .observations
    .setStyle(
      feature => {

        if (
          !datasetMatches(
            feature,
            datasetId
          )
        ) {
          return null;
        }


        return FrozenLegaciesStyles
          .observation(
            feature
          );

      }
    );


  state.flightNumber =
    "all";

  state.selectedObservation = "";

  writeExplorerContextUrl(datasetId, "all");


  const flightSelect =
    getFlightSelectElement();


  if (flightSelect) {

    flightSelect.value =
      "all";

  }


  FrozenLegaciesMap.resetView(
    map,
    {
      duration:
        400
    }
  );


  const dataset =
    datasetId !== "all"
      ? data.datasetIndex?.get(
          datasetId
        )
      : null;


  renderEmptyObservation(
    dataset
  );

}


/* ------------------------------------------------------------
 * Select one flight
 * ------------------------------------------------------------ */

function selectFlight({
  map,
  data,
  layers,
  state,
  flightNumber,
  datasetId = null,
  zoom = true
}) {

  if (
    !map ||
    !data ||
    !layers
  ) {
    return;
  }


  const normalizedFlight =
    FrozenLegaciesData
      .normalizeFlightValue(
        flightNumber
      );


  const normalizedDataset =
    normalizeDatasetValue(
      datasetId ??
      state?.datasetId ??
      "all"
    );


  if (
    !normalizedFlight ||
    normalizedFlight === "all"
  ) {

    showAllFlights({
      map,
      data,
      layers,
      state
    });


    return;

  }


  const lookupDataset =
    normalizedDataset === "all"
      ? ""
      : normalizedDataset;


  const selectedFeature =
    FrozenLegaciesData
      .getFlight(
        data,
        normalizedFlight,
        lookupDataset
      );


  if (
    !selectedFeature
  ) {

    console.warn(
      "[FrozenLegacies] flight not found:",
      normalizedDataset,
      normalizedFlight
    );


    return;

  }


  const selectedFeatureDataset =
    datasetForFeature(
      selectedFeature
    );


  /*
   * If all datasets were active and the selected flight came
   * from a particular dataset, retain that dataset identity for
   * filtering comparisons without forcing the dataset dropdown.
   */

  const effectiveDataset =
    normalizedDataset === "all"
      ? selectedFeatureDataset
      : normalizedDataset;


  const selectedSource =
    layers
      .sources
      .frozen
      .selectedFlight;


  selectedSource.clear(
    true
  );


  selectedSource.addFeature(
    selectedFeature.clone()
  );


  layers
    .layers
    .flights
    .setStyle(
      feature => {

        const featureDataset =
          datasetForFeature(
            feature
          );


        const featureFlight =
          FrozenLegaciesData
            .normalizeFlightValue(
              feature.get(
                "flight"
              )
            );


        const sameDataset =
          !effectiveDataset ||
          featureDataset ===
            effectiveDataset;


        if (
          sameDataset &&
          featureFlight ===
            normalizedFlight
        ) {
          return null;
        }


        if (
          normalizedDataset !== "all" &&
          featureDataset !==
            normalizedDataset
        ) {
          return null;
        }


        return FrozenLegaciesStyles
          .fadedFlight();

      }
    );


  layers
    .layers
    .observations
    .setStyle(
      feature => {

        const featureDataset =
          datasetForFeature(
            feature
          );


        const featureFlight =
          FrozenLegaciesData
            .normalizeFlightValue(
              feature.get(
                "flight"
              )
            );


        if (
          effectiveDataset &&
          featureDataset !==
            effectiveDataset
        ) {
          return null;
        }


        if (
          featureFlight !==
          normalizedFlight
        ) {
          return null;
        }


        return FrozenLegaciesStyles
          .observation(
            feature
          );

      }
    );


  if (state) {

    state.flightNumber =
      normalizedFlight;

    state.selectedObservation = "";

  }


  const select =
    getFlightSelectElement();


  if (
    select &&
    select.value !==
      normalizedFlight
  ) {

    select.value =
      normalizedFlight;

  }


  if (zoom) {

    FrozenLegaciesMap
      .fitToFeature(
        map,
        selectedFeature,
        {
          padding:
            90,

          maxZoom:
            8,

          duration:
            500
        }
      );

  }


  // Map selection and camera movement must complete even if a secondary
  // explorer consumer fails while reacting to the URL/filter update.
  writeExplorerContextUrl(normalizedDataset, normalizedFlight);

}


/* ------------------------------------------------------------
 * Select dataset
 * ------------------------------------------------------------ */

function selectDataset({
  map,
  data,
  layers,
  state,
  datasetId
}) {

  const normalized =
    normalizeDatasetValue(
      datasetId
    ) || "all";


  state.datasetId =
    normalized;


  state.flightNumber =
    "all";


  const datasetSelect =
    getDatasetSelectElement();


  if (
    datasetSelect &&
    datasetSelect.value !== normalized
  ) {

    datasetSelect.value =
      normalized;

  }


  refreshFlightSelectorForDataset({
    data,

    datasetId:
      normalized
  });


  showAllFlights({
    map,
    data,
    layers,
    state
  });

}


/* ------------------------------------------------------------
 * Determine observation under pixel
 * ------------------------------------------------------------ */

function observationAtPixel(
  map,
  observationLayer,
  pixel
) {

  let selectedFeature =
    null;


  map.forEachFeatureAtPixel(
    pixel,

    (
      feature,
      layer
    ) => {

      if (
        layer ===
        observationLayer
      ) {

        selectedFeature =
          feature;


        return true;

      }


      return false;

    },
    {
      hitTolerance:
        6
    }
  );


  return selectedFeature;

}

function riggsAtPixel(map, riggsLayer, pixel) {
  if (!riggsLayer?.getVisible()) return null;
  let selectedFeature = null;
  map.forEachFeatureAtPixel(pixel, (feature, layer) => {
    if (layer === riggsLayer) {
      selectedFeature = feature;
      return true;
    }
    return false;
  }, { hitTolerance: 6 });
  return selectedFeature;
}

function renderRiggsStation(feature, metadata) {
  const panel = getSelectedRecordElement();
  if (!panel) return;
  const properties = feature.getProperties();
  const method = properties.measurement_method === "seismic" ? "Seismic" : "Radar";
  const scientificStatus = metadata?.citation_pending
    ? "Provisional reference · citation pending · not publication eligible"
    : (metadata?.note || "Independent reference observation; not a Frozen Legacies pick.");
  panel.innerHTML = `
    <div class="fl-record-card">
      <div class="fl-record-eyebrow">Independent scientific context</div>
      <h3>RIGGS station ${escapeHtmlUI(properties.station || "—")}</h3>
      <p class="fl-record-description">
        This is a historical reference observation, not a Frozen Legacies manual or automatic pick.
      </p>
      <div class="fl-record-metrics">
        <div class="fl-record-metric"><span>Measurement</span><strong>${method}</strong></div>
        <div class="fl-record-metric"><span>Ice thickness</span><strong>${formatNumber(properties.ice_thickness_m, { digits: 1, suffix: " m" })}</strong></div>
        <div class="fl-record-metric"><span>Seismic value</span><strong>${formatNumber(properties.seismic_ice_thickness_m, { digits: 1, suffix: " m" })}</strong></div>
        <div class="fl-record-metric"><span>Radar value</span><strong>${formatNumber(properties.radar_ice_thickness_m, { digits: 1, suffix: " m" })}</strong></div>
      </div>
      <div class="fl-record-section">
        <div class="fl-record-section-title">Source and scientific status</div>
        <p class="fl-record-description"><strong>${escapeHtmlUI(scientificStatus)}</strong></p>
        <p class="fl-record-description">${escapeHtmlUI(metadata?.citation || "Citation unavailable")}</p>
        ${metadata?.source_url ? `<a class="fl-radar-button" href="${escapeHtmlUI(metadata.source_url)}" target="_blank" rel="noopener">Authoritative dataset record</a>` : ""}
      </div>
    </div>`;
}


/* ------------------------------------------------------------
 * Determine flight under pixel
 * ------------------------------------------------------------ */

function flightAtPixel(
  map,
  flightLayer,
  pixel
) {

  let selectedFeature =
    null;


  map.forEachFeatureAtPixel(
    pixel,

    (
      feature,
      layer
    ) => {

      if (
        layer ===
        flightLayer
      ) {

        selectedFeature =
          feature;


        return true;

      }


      return false;

    },
    {
      hitTolerance:
        6
    }
  );


  return selectedFeature;

}


/* ------------------------------------------------------------
 * Bind dataset dropdown
 * ------------------------------------------------------------ */

function bindDatasetSelector({
  map,
  data,
  layers,
  state
}) {

  const select =
    getDatasetSelectElement();


  if (!select) {
    return;
  }


  select.addEventListener(
    "change",
    () => {

      selectDataset({
        map,
        data,
        layers,
        state,

        datasetId:
          select.value
      });

    }
  );

}


/* ------------------------------------------------------------
 * Bind flight dropdown
 * ------------------------------------------------------------ */

function bindFlightSelector({
  map,
  data,
  layers,
  state
}) {

  const select =
    getFlightSelectElement();


  if (!select) {
    return;
  }


  select.addEventListener(
    "change",
    () => {

      const value =
        select.value;


      closeObservationPopup(document.getElementById("fl-observation-popup"));
      renderEmptyObservation(data.datasetIndex?.get(state.datasetId) || null);


      if (
        value === "all"
      ) {

        showAllFlights({
          map,
          data,
          layers,
          state
        });

      }

      else {

        // A flight choice is a map-navigation action, not an implicit
        // observation choice.  Dismiss any old quicklook and fit the map to
        // the newly selected track; the user can then choose its observation.
        selectFlight({
          map,
          data,
          layers,
          state,

          datasetId:
            state.datasetId,

          flightNumber:
            value,

          zoom:
            true
        });

      }

    }
  );

}


/* ------------------------------------------------------------
 * Bind map click
 * ------------------------------------------------------------ */

function bindMapClick({
  map,
  data,
  layers,
  state
}) {

  map.on(
    "singleclick",
    event => {

      const riggs =
        riggsAtPixel(map, layers.layers.riggs, event.pixel);

      if (riggs) {
        renderRiggsStation(riggs, data.riggs?.metadata);
        return;
      }

      const observation =
        observationAtPixel(
          map,

          layers
            .layers
            .observations,

          event.pixel
        );


      if (observation) {

        const datasetId =
          datasetForFeature(
            observation
          );


        const flight =
          FrozenLegaciesData
            .normalizeFlightValue(
              observation.get(
                "flight"
              )
            );


        /*
         * Clicking a point should synchronize the explorer with
         * the observation's dataset.
         */

        if (
          datasetId &&
          state.datasetId !==
            datasetId
        ) {

          state.datasetId =
            datasetId;


          const datasetSelect =
            getDatasetSelectElement();


          if (datasetSelect) {

            datasetSelect.value =
              datasetId;

          }


          refreshFlightSelectorForDataset({
            data,
            datasetId
          });

        }


        selectObservation({
          map,
          data,
          layers,
          state,
          feature: observation,
          coordinate: event.coordinate,
          zoomFlight: false
        });


        return;

      }


      const flightFeature =
        flightAtPixel(
          map,

          layers
            .layers
            .flights,

          event.pixel
        );


      if (
        flightFeature
      ) {

        const datasetId =
          datasetForFeature(
            flightFeature
          );


        const flight =
          FrozenLegaciesData
            .normalizeFlightValue(
              flightFeature.get(
                "flight"
              )
            );


        if (
          datasetId &&
          state.datasetId !==
            datasetId
        ) {

          state.datasetId =
            datasetId;


          const datasetSelect =
            getDatasetSelectElement();


          if (datasetSelect) {

            datasetSelect.value =
              datasetId;

          }


          refreshFlightSelectorForDataset({
            data,
            datasetId
          });

        }


        if (flight) {

          selectFlight({
            map,
            data,
            layers,
            state,

            datasetId,

            flightNumber:
              flight,

            zoom:
              true
          });

        }

      }

    }
  );

}


function selectObservation({map, data, layers, state, feature, coordinate = null, zoomFlight = false}) {
  if (!feature) return false;
  const properties = feature.getProperties();
  const datasetId = datasetForFeature(feature);
  const flight = FrozenLegaciesData.normalizeFlightValue(properties.flight);
  if (!datasetId || !flight) return false;

  state.datasetId = datasetId;
  const datasetSelect = getDatasetSelectElement();
  if (datasetSelect) datasetSelect.value = datasetId;
  refreshFlightSelectorForDataset({data, datasetId});
  selectFlight({map, data, layers, state, datasetId, flightNumber: flight, zoom: zoomFlight});
  state.selectedObservation = observationSelectionId(feature);

  const ordered = orderedFlightObservations(data, datasetId, flight);
  const index = ordered.findIndex(item => observationSelectionId(item) === state.selectedObservation);
  const navigateObservation = delta => {
    const target = ordered[index + delta];
    if (target) selectObservation({map, data, layers, state, feature: target, zoomFlight: false});
  };
  const flights = orderedDatasetFlights(data, datasetId);
  const flightIndex = flights.findIndex(([value]) => value === flight);
  const navigateFlight = delta => {
    const targetFlight = flights[flightIndex + delta]?.[0];
    const target = targetFlight && orderedFlightObservations(data, datasetId, targetFlight)[0];
    if (target) selectObservation({map, data, layers, state, feature: target, zoomFlight: true});
  };
  const navigation = {
    hasPreviousFlight: flightIndex > 0,
    hasNextFlight: flightIndex >= 0 && flightIndex < flights.length - 1,
    flightPosition: flightIndex >= 0 ? `Flight ${flight} · ${flightIndex + 1} of ${flights.length}` : "",
    hasPreviousObservation: index > 0,
    hasNextObservation: index >= 0 && index < ordered.length - 1,
    observationPosition: index >= 0 ? `Observation ${index + 1} of ${ordered.length}` : "",
    navigateFlight,
    navigateObservation
  };
  renderObservation(feature, data);
  showObservationPopup(map, feature, data, coordinate, navigation);
  writeObservationSelectionUrl(feature);
  return true;
}


function restoreObservationSelection({map, data, layers, state}) {
  const params = new URLSearchParams(window.location.search);
  const datasetId = normalizeDatasetValue(params.get("dataset"));
  const flight = FrozenLegaciesData.normalizeFlightValue(params.get("flight"));
  const observation = params.get("observation") || "";
  if (!datasetId || !flight || !observation) return false;
  const feature = orderedFlightObservations(data, datasetId, flight)
    .find(item => observationSelectionId(item) === observation);
  if (!feature) return false;
  return selectObservation({map, data, layers, state, feature, zoomFlight: true});
}


/* ------------------------------------------------------------
 * Bind pointer cursor
 * ------------------------------------------------------------ */

function bindPointerCursor({
  map,
  layers
}) {

  map.on(
    "pointermove",
    event => {

      if (
        event.dragging
      ) {
        return;
      }


      const hit =
        map.hasFeatureAtPixel(
          event.pixel,
          {
            hitTolerance:
              5,

            layerFilter:
              layer =>
                layer ===
                  layers.layers.observations ||
                layer ===
                  layers.layers.riggs ||
                layer ===
                  layers.layers.flights ||
                layer ===
                  layers.layers.selectedFlight
          }
        );


      map
        .getTargetElement()
        .style
        .cursor =
          hit
            ? "pointer"
            : "";

    }
  );

}


/* ------------------------------------------------------------
 * Complete UI initialization
 * ------------------------------------------------------------ */

function initializeFrozenLegaciesUI({
  map,
  data,
  layers
}) {

  if (
    !map ||
    !data ||
    !layers
  ) {

    throw new Error(
      "FrozenLegacies UI initialization is missing required state."
    );

  }


  const state = {

    datasetId:
      "all",

    flightNumber:
      "all",

    selectedObservation:
      ""

  };


  populateDatasetSelector(
    data.catalog
  );


  refreshFlightSelectorForDataset({
    data,

    datasetId:
      state.datasetId
  });


  renderEmptyObservation();


  bindDatasetSelector({
    map,
    data,
    layers,
    state
  });


  bindFlightSelector({
    map,
    data,
    layers,
    state
  });


  bindMapClick({
    map,
    data,
    layers,
    state
  });


  bindPointerCursor({
    map,
    layers
  });

  bindScientificExplorer({map, data, layers, state});


  return {

    state,


    showAllFlights:
      () =>
        showAllFlights({
          map,
          data,
          layers,
          state
        }),


    selectDataset:
      datasetId =>
        selectDataset({
          map,
          data,
          layers,
          state,
          datasetId
        }),


    selectFlight:
      (
        flightNumber,
        options = {}
      ) =>
        selectFlight({
          map,
          data,
          layers,
          state,

          datasetId:
            options.datasetId ??
            state.datasetId,

          flightNumber,

          zoom:
            options.zoom !== false
        }),


    showObservation:
      feature =>
        selectObservation({map, data, layers, state, feature}),


    restoreObservationSelection:
      () => restoreObservationSelection({map, data, layers, state})

  };

}


/* ------------------------------------------------------------
 * Public API
 * ------------------------------------------------------------ */

window.FrozenLegaciesUI = {

  initialize:
    initializeFrozenLegaciesUI,

  populateDatasetSelector,

  populateFlightSelector,

  renderObservation,

  renderEmptyObservation

};
