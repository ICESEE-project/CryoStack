/* ============================================================
 * Frozen Legacies
 * published_layer.js
 *
 * "Reviewed results": observations of results approved by a
 * reviewer and published as a shared dataset product
 * (/frozen-legacies/api/published/observations). Loaded for the
 * visible map area only, with a server-side limit. Separate from
 * the LYRA dataset layers and from the user's own "My picks".
 * ============================================================ */


(function () {

  "use strict";

  const API = "/frozen-legacies/api/published";
  const LIMIT = 5000;

  const state = {
    map: null, layer: null, visible: false, summary: null, selected: null,
    onChange: () => {}, timer: null, seq: 0
  };


  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }


  function fmt(value, digits, unit = "") {
    return Number.isFinite(value) ? `${value.toFixed(digits)}${unit}` : "—";
  }


  /* Verified positions: solid; ASTRA-assigned (accepted as unverified): hollow. */
  function style(feature) {
    const verified = feature.get("geolocation_status") === "verified";
    const selected = state.selected && feature.getId() === state.selected.getId();
    return new ol.style.Style({
      image: new ol.style.Circle({
        radius: selected ? 7 : 5,
        fill: new ol.style.Fill({ color: verified ? "#0f766e" : "rgba(255,255,255,0.9)" }),
        stroke: new ol.style.Stroke({ color: "#0f766e", width: selected ? 3 : 2 })
      }),
      zIndex: 12
    });
  }


  /* WGS84 box of the view; the whole south polar cap when the pole is visible. */
  function viewBbox() {
    const view = state.map.getView();
    const extent = view.calculateExtent(state.map.getSize());
    const projection = view.getProjection();
    if (ol.extent.containsCoordinate(extent, ol.proj.fromLonLat([0, -90], projection))) {
      const corners = [ol.extent.getTopLeft(extent), ol.extent.getTopRight(extent),
                       ol.extent.getBottomLeft(extent), ol.extent.getBottomRight(extent)];
      const top = Math.max(...corners.map(c => ol.proj.toLonLat(c, projection)[1]));
      return [-180, -90, 180, Math.min(90, top)];
    }
    const box = ol.proj.transformExtent(extent, projection, "EPSG:4326");
    return box.every(Number.isFinite) ? box : null;
  }


  async function reload() {
    if (!state.layer || !state.visible) {
      return;
    }
    const seq = ++state.seq;
    const params = new URLSearchParams({ limit: String(LIMIT) });
    const box = viewBbox();
    if (box) {
      params.set("bbox", box.map(v => v.toFixed(4)).join(","));
    }
    try {
      const response = await fetch(`${API}/observations?${params}`, {
        credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" }
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const collection = await response.json();
      if (seq !== state.seq) {
        return;                                  // a newer view is loading
      }
      const features = new ol.format.GeoJSON().readFeatures(collection, {
        dataProjection: "EPSG:4326", featureProjection: state.map.getView().getProjection()
      });
      state.layer.getSource().clear();
      state.layer.getSource().addFeatures(features);
      state.summary = collection.summary;
    } catch (error) {
      state.summary = { error: "Reviewed results could not be loaded." };
    }
    state.onChange();
  }


  function panelHtml() {
    const s = state.summary;
    let note = "Results approved by a reviewer and published as a shared dataset product.";
    if (state.visible && s && !s.error) {
      note = `${s.returned.toLocaleString("en-US")} reviewed observation${s.returned === 1 ? "" : "s"} in view${
        s.truncated ? " (first shown; zoom in for more)" : ""} · ${s.published_total.toLocaleString("en-US")} published in total.`;
    } else if (s?.error) {
      note = s.error;
    }
    let selected = "";
    if (state.selected) {
      const p = state.selected.getProperties();
      const verified = p.geolocation_status === "verified";
      selected = `
        <div class="fl-record-grid fl-pick-detail">
          <div class="fl-record-item"><span>A-scope</span><strong>${escapeHtml(p.a_scope)} · ${escapeHtml(p.filename)}</strong></div>
          <div class="fl-record-item"><span>CBD</span><strong>${escapeHtml(p.cbd ?? "—")}${
            p.astra_cbd !== undefined && p.astra_cbd !== p.cbd ? ` (ASTRA ${escapeHtml(p.astra_cbd)})` : ""}</strong></div>
          <div class="fl-record-item"><span>Position</span><strong>${fmt(p.lat, 4, "°")}, ${fmt(p.lon, 4, "°")}</strong></div>
          <div class="fl-record-item"><span>Ice thickness</span><strong>${fmt(p.h_ice_m, 1, " m")}</strong></div>
        </div>
        <p class="fl-radar-panel-note">${verified ? "Position verified against the film" : "Position unverified (ASTRA-assigned CBD), accepted by the reviewer"}
          · ${escapeHtml(p.producer)} · ${escapeHtml(p.dataset_id)} · published ${p.published_at ? new Date(p.published_at * 1000).toLocaleDateString() : ""}</p>
        <div class="fl-astra-downloads">
          <a class="fl-radar-button" href="${API}/${encodeURIComponent(p.submission_id)}/products/astra-csv" download>ASTRA CSV</a>
          <a class="fl-radar-button" href="${API}/${encodeURIComponent(p.submission_id)}/products/provenance" download>Provenance</a>
        </div>`;
    }
    return `
      <div class="fl-record-section">
        <div class="fl-record-section-title">Reviewed results</div>
        <label class="fl-astra-toggle">
          <input type="checkbox" data-published ${state.visible ? "checked" : ""}>
          Show reviewed results on the map
        </label>
        <p class="fl-radar-panel-note">${escapeHtml(note)}</p>
        ${selected}
      </div>`;
  }


  function bindPanel(root) {
    root.querySelector("[data-published]")?.addEventListener("change", event => {
      state.visible = event.target.checked;
      state.layer?.setVisible(state.visible);
      if (state.visible) {
        reload();
      } else {
        state.selected = null;
        state.onChange();
      }
    });
  }


  function initialize({ map, onChange }) {
    if (!map || !window.ol || state.layer) {
      return;
    }
    state.map = map;
    state.onChange = onChange || (() => {});
    state.layer = new ol.layer.Vector({
      source: new ol.source.Vector(), style, visible: false,
      properties: { id: "frozen-reviewed-results", label: "Reviewed results" }, zIndex: 18
    });
    map.addLayer(state.layer);
    map.on("moveend", () => {
      window.clearTimeout(state.timer);
      state.timer = window.setTimeout(reload, 250);
    });
    map.on("singleclick", event => {
      if (!state.visible) {
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
        state.layer.changed();
        state.onChange();
      }
    });
  }


  window.FrozenLegaciesPublishedLayer = { initialize, reload, panelHtml, bindPanel };

})();
