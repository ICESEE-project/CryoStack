/* ============================================================
 * Frozen Legacies
 * catalog.js
 *
 * Radar catalog browser for large collections (thousands of TIFFs).
 * Filtering and pagination happen on the server
 * (/frozen-legacies/api/radar/catalog); the browser holds one page
 * at a time. Opening an entry references the catalog file in the
 * user's workspace -- nothing is copied.
 * ============================================================ */


(function () {

  "use strict";

  const API = "/frozen-legacies/api/radar/catalog";
  const PAGE_SIZE = 25;

  const STATE_LABELS = {
    unprocessed: "Unprocessed",
    manual_in_progress: "Manual · in progress",
    manual_completed: "Manual · completed",
    automatic_pending: "Automatic · queued",
    automatic_running: "Automatic · running",
    automatic_completed: "Automatic · completed",
    automatic_failed: "Automatic · failed",
    needs_review: "Awaiting review",
    returned: "Returned for correction",
    published: "Published"
  };

  const state = {
    summary: null,
    filters: { dataset: "", flight: "", state: "", cbd: "", q: "" },
    page: 1,
    result: null,
    open: null,
    error: null,
    timer: null,
    map: null,
    layer: null,
    coverage: false,
    selected: null,
    onChange: () => {}
  };


  function $(id) {
    return document.getElementById(id);
  }


  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }


  async function get(url) {
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store",
                                        headers: { Accept: "application/json" } });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(body?.error || `Request failed (HTTP ${response.status}).`);
    }
    return body;
  }


  function query() {
    const params = new URLSearchParams({ page: String(state.page), page_size: String(PAGE_SIZE) });
    for (const [key, value] of Object.entries(state.filters)) {
      if (value) {
        params.set(key, value);
      }
    }
    return params.toString();
  }


  async function search() {
    try {
      state.result = await get(`${API}?${query()}`);
      state.error = null;
    } catch (error) {
      state.error = error.message;
    }
    renderResults();
  }


  /* The user's progress for the selected flight (or all flights), from the
     server's indexed state. */
  function progressText() {
    const flights = (state.summary?.flights || []).filter(f =>
      (!state.filters.dataset || f.dataset_id === state.filters.dataset) &&
      (!state.filters.flight || String(f.flight) === state.filters.flight));
    if (!flights.length || !flights[0].mine) {
      return "";
    }
    const sum = key => flights.reduce((n, f) => n + (f.mine[key] || 0), 0);
    const total = flights.reduce((n, f) => n + f.assets, 0);
    const label = state.filters.flight ? `Flight ${escapeHtml(state.filters.flight)}` : "All flights";
    const all = key => flights.reduce((n, f) => n + (f[key] || 0), 0);
    return `${label}: ${total.toLocaleString("en-US")} radar segments · ` +
      `${sum("manual_in_progress")} manual in progress · ${sum("manual_completed")} manual completed · ` +
      `${sum("automatic_completed")} automatic completed · ${sum("needs_review")} awaiting review · ` +
      `${sum("published")} published · ${sum("unprocessed").toLocaleString("en-US")} unprocessed (your work)` +
      ` <span class="fl-catalog-shared">· all users: ${all("published")} published, ${all("awaiting_review")} awaiting review</span>`;
  }


  function renderFilters() {
    const summary = state.summary;
    const datasets = summary.datasets.map(d =>
      `<option value="${escapeHtml(d.dataset_id)}">${escapeHtml(d.dataset_id)} (${d.assets})</option>`).join("");
    const flights = summary.flights
      .filter(f => !state.filters.dataset || f.dataset_id === state.filters.dataset)
      .map(f => `<option value="${escapeHtml(f.flight ?? "")}">F${escapeHtml(f.flight ?? "?")} · ${f.assets} segments${
        f.cbd_min !== null ? ` · CBD ${f.cbd_min}–${f.cbd_max}` : ""}</option>`).join("");
    const states = Object.entries(STATE_LABELS).map(([k, v]) =>
      `<option value="${k}">${escapeHtml(v)}</option>`).join("");
    $("fl-catalog-browser").innerHTML = `
      <div class="fl-catalog-filters">
        <label>Dataset <select data-filter="dataset"><option value="">All datasets</option>${datasets}</select></label>
        <label>Flight <select data-filter="flight"><option value="">All flights</option>${flights}</select></label>
        <label>My status <select data-filter="state"><option value="">All</option>${states}</select></label>
        <label>CBD <input type="number" data-filter="cbd" min="0" step="1" placeholder="e.g. 475"></label>
        <label class="fl-catalog-search">Search <input type="search" data-filter="q" placeholder="File name" maxlength="100"></label>
      </div>
      <div class="fl-catalog-progress">${progressText()}</div>
      <div id="fl-catalog-results" class="fl-catalog-results"></div>`;
    $("fl-catalog-browser").querySelectorAll("[data-filter]").forEach(control => {
      control.value = state.filters[control.dataset.filter] || "";
      control.addEventListener(control.tagName === "INPUT" ? "input" : "change", () => {
        state.filters[control.dataset.filter] = control.value.trim();
        if (control.dataset.filter === "dataset") {
          state.filters.flight = "";
          renderFilters();
        } else {
          $("fl-catalog-browser").querySelector(".fl-catalog-progress").innerHTML = progressText();
        }
        state.page = 1;
        window.clearTimeout(state.timer);
        state.timer = window.setTimeout(search, control.tagName === "INPUT" ? 300 : 0);
      });
    });
  }


  function renderResults() {
    const root = $("fl-catalog-results");
    if (!root) {
      return;
    }
    if (state.error) {
      root.innerHTML = `<p class="fl-radar-panel-note">${escapeHtml(state.error)}</p>`;
      return;
    }
    const result = state.result;
    if (!result) {
      root.innerHTML = `<p class="fl-radar-panel-note">Loading…</p>`;
      return;
    }
    const rows = result.items.map(item => `
      <tr>
        <td><strong>${escapeHtml(item.filename)}</strong>${item.duplicate ? ` <span class="fl-catalog-flag" title="Another file in this dataset has the same name">duplicate name</span>` : ""}</td>
        <td>F${escapeHtml(item.flight ?? "?")}</td>
        <td>${item.cbd_start !== null ? `${item.cbd_start}–${item.cbd_end}` : "—"}</td>
        <td>${item.has_nav ? "yes" : `<span title="No navigation records: this segment is not placed on the map">none · unplaced</span>`}</td>
        <td>${escapeHtml((item.processing || []).map(s => STATE_LABELS[s] || s).join(", "))}</td>
        <td><button type="button" class="fl-radar-button primary" data-catalog-open="${escapeHtml(item.catalog_id)}">Open</button></td>
      </tr>`).join("");
    root.innerHTML = `
      <div class="fl-catalog-count">${result.total.toLocaleString("en-US")} radar file${result.total === 1 ? "" : "s"}</div>
      <div class="fl-astra-table-wrap">
        <table class="fl-astra-table">
          <thead><tr><th>File</th><th>Flight</th><th>CBD</th><th>Navigation</th><th>My status</th><th></th></tr></thead>
          <tbody>${rows || `<tr><td colspan="6">No radar files match these filters.</td></tr>`}</tbody>
        </table>
      </div>
      <div class="fl-catalog-pages">
        <button type="button" class="fl-radar-button" data-page="-1" ${result.page <= 1 ? "disabled" : ""}>‹ Previous</button>
        <span>Page ${result.page} of ${result.pages}</span>
        <button type="button" class="fl-radar-button" data-page="1" ${result.page >= result.pages ? "disabled" : ""}>Next ›</button>
      </div>`;
    root.querySelectorAll("[data-page]").forEach(button => {
      button.addEventListener("click", () => {
        state.page = Math.max(1, state.page + Number(button.dataset.page));
        search();
      });
    });
    root.querySelectorAll("[data-catalog-open]").forEach(button => {
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await state.open(button.dataset.catalogOpen);
          toggle(false);
        } catch (error) {
          state.error = error.message;
          renderResults();
        }
      });
    });
  }


  async function refreshSummary() {
    try {
      state.summary = await get(`${API}/summary`);
    } catch (error) {
      // keep the previous summary
    }
  }


  async function toggle(show) {
    const browser = $("fl-catalog-browser");
    const visible = show ?? browser.hidden;
    browser.hidden = !visible;
    if (visible) {
      await refreshSummary();                  // progress reflects recent work
      renderFilters();
      search();
    }
  }


  /* ----------------------------------------------------------
   * Map: radar coverage from real navigation tracks
   * ---------------------------------------------------------- */

  function coverageStyle(feature) {
    const selected = state.selected && feature.getId() === state.selected.getId();
    return new ol.style.Style({
      stroke: new ol.style.Stroke({ color: selected ? "#0b6f98" : "rgba(11,111,152,0.55)",
                                    width: selected ? 4 : 2 }),
      image: new ol.style.Circle({ radius: 3, fill: new ol.style.Fill({ color: "#0b6f98" }) }),
      zIndex: 5
    });
  }


  async function loadCoverage() {
    if (!state.layer) {
      return;
    }
    const params = new URLSearchParams();
    if (state.filters.dataset) {
      params.set("dataset", state.filters.dataset);
    }
    if (state.filters.flight) {
      params.set("flight", state.filters.flight);
    }
    try {
      const collection = await get(`${API}/segments?${params}`);
      const features = new ol.format.GeoJSON().readFeatures(collection, {
        dataProjection: "EPSG:4326", featureProjection: state.map.getView().getProjection()
      });
      state.layer.getSource().clear();
      state.layer.getSource().addFeatures(features);
      state.coverageSummary = collection.summary;
    } catch (error) {
      state.coverageSummary = { error: error.message };
    }
    state.onChange();
  }


  function initializeMap({ map, onChange, onSelection }) {
    if (!map || !window.ol || state.layer) {
      return;
    }
    state.map = map;
    state.onChange = onChange || (() => {});
    state.onSelection = onSelection || (() => {});
    state.layer = new ol.layer.Vector({
      source: new ol.source.Vector(), style: coverageStyle, visible: false,
      properties: { id: "frozen-radar-coverage", label: "Radar coverage" }, zIndex: 15
    });
    map.addLayer(state.layer);
    map.on("singleclick", event => {
      if (!state.coverage) {
        return;
      }
      let hit = null;
      map.forEachFeatureAtPixel(event.pixel, (feature, layer) => {
        if (layer === state.layer) {
          hit = feature;
          return true;
        }
        return false;
      }, { hitTolerance: 6 });
      if (hit || state.selected) {
        state.selected = hit;
        state.selectedItem = null;
        state.layer.changed();
        state.onChange();
        state.onSelection();
        if (hit) {
          loadSelected(hit.getId());
        }
      }
    });
  }


  /* The coverage toggle and selected segment, for the page URL. */
  function selection() {
    return { coverage: Boolean(state.coverage && state.layer),
             segment: state.coverage && state.selected ? String(state.selected.getId()) : null };
  }


  /* Restores selection() from the URL: coverage is reloaded, and a segment
     is selected only when the loaded coverage contains it (an unknown or
     filtered-out ID is dropped, never guessed). */
  async function restore({ coverage, segment }) {
    if (!state.layer) {
      return;
    }
    if (!coverage) {
      if (state.coverage) {
        state.coverage = false;
        state.layer.setVisible(false);
        state.selected = null;
        state.selectedItem = null;
        state.onChange();
      }
      return;
    }
    if (!state.coverage) {
      state.coverage = true;
      state.layer.setVisible(true);
      await loadCoverage();
    }
    const feature = segment ? state.layer.getSource().getFeatureById(segment) : null;
    if ((feature || null) !== (state.selected || null)) {
      state.selected = feature;
      state.selectedItem = null;
      state.layer.changed();
      state.onChange();
      if (feature) {
        loadSelected(feature.getId());
      }
    }
  }


  /* The selected segment's catalog entry: navigation and the user's state. */
  async function loadSelected(catalogId) {
    try {
      const result = await get(`${API}?id=${encodeURIComponent(catalogId)}&page_size=1`);
      if (state.selected && state.selected.getId() === catalogId) {
        state.selectedItem = result.items[0] || null;
        state.onChange();
      }
    } catch (error) {
      // the segment's own properties are still shown
    }
  }


  function panelHtml() {
    if (!state.summary || !state.summary.total) {
      return "";
    }
    const s = state.coverageSummary;
    let selected = "";
    if (state.selected) {
      const p = state.selected.getProperties();
      const item = state.selectedItem;
      const status = item ? (item.processing || []).map(s => STATE_LABELS[s] || s).join(", ") : "";
      selected = `
        <div class="fl-radar-link">
          <div><strong>${escapeHtml(p.filename)}</strong>
            <span>${escapeHtml(p.dataset_id)} · Flight ${escapeHtml(p.flight ?? "?")} · CBD ${escapeHtml(p.cbd_start)}–${escapeHtml(p.cbd_end)} (file name)</span>
            ${item ? `<span>${item.width?.toLocaleString("en-US") ?? "?"} × ${item.height?.toLocaleString("en-US") ?? "?"} px · navigation track drawn from its records · my status: ${escapeHtml(status)}</span>` : ""}</div>
          <button type="button" class="fl-radar-button primary" data-coverage-open="${escapeHtml(p.catalog_id)}">Open radar</button>
        </div>`;
    }
    return `
      <div class="fl-record-section">
        <div class="fl-record-section-title">Radar catalog</div>
        <label class="fl-astra-toggle">
          <input type="checkbox" data-coverage ${state.coverage ? "checked" : ""}>
          Show radar coverage on the map
        </label>
        <p class="fl-radar-panel-note">${state.coverage && s && !s.error
          ? `${s.returned.toLocaleString("en-US")} radar segments placed from their navigation records${s.truncated ? " (first shown; filter by flight in the catalog browser)" : ""}. ${
              s.unplaced
                ? `${s.unplaced.toLocaleString("en-US")} segment${s.unplaced === 1 ? "" : "s"} without navigation ${s.unplaced === 1 ? "is" : "are"} not placed on the map; open ${s.unplaced === 1 ? "it" : "them"} from the catalog browser.`
                : "Segments without navigation are never placed on the map."}`
          : `${state.summary.total.toLocaleString("en-US")} radar files in this installation's catalog.`}</p>
        ${selected}
      </div>`;
  }


  function bindPanel(root) {
    root.querySelector("[data-coverage]")?.addEventListener("change", event => {
      state.coverage = event.target.checked;
      state.layer?.setVisible(state.coverage);
      if (state.coverage) {
        loadCoverage();
      } else {
        state.selected = null;
        state.onChange();
      }
      state.onSelection?.();
    });
    root.querySelector("[data-coverage-open]")?.addEventListener("click", async event => {
      event.target.disabled = true;
      try {
        await state.open(event.target.dataset.coverageOpen);
      } catch (error) {
        event.target.disabled = false;
      }
    });
  }


  async function initialize({ open }) {
    state.open = open;
    const button = $("fl-catalog-toggle");
    await refreshSummary();
    // small installations keep using the asset selector alone
    if (!state.summary || !state.summary.total) {
      button.hidden = true;
      return;
    }
    button.hidden = false;
    button.textContent = `Browse radar catalog (${state.summary.total.toLocaleString("en-US")})`;
    button.addEventListener("click", () => toggle());
    state.onChange();
  }


  /* Back on the map: the selected segment's status reflects recent work. */
  function refreshSelected() {
    if (state.selected) {
      loadSelected(state.selected.getId());
    }
  }


  window.FrozenLegaciesCatalog = {
    initialize, initializeMap, toggle, panelHtml, bindPanel, refreshSelected, selection, restore
  };

})();
