/* ============================================================
 * Frozen Legacies
 * user_layer.js
 *
 * "My picks": the signed-in user's own picked observations on the
 * Antarctic map, read from the owner-scoped observations API
 * (/frozen-legacies/api/observations). It is a separate layer from
 * the shared dataset observations and never changes them: draft
 * picks stay private user work.
 * ============================================================ */


(function () {

  "use strict";

  const API = "/frozen-legacies/api/observations";

  const state = {
    map: null,
    layer: null,
    visible: true,
    summary: null,
    selected: null,
    onChange: () => {},
    loading: false
  };


  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }


  function fmt(value, digits, unit = "") {
    return Number.isFinite(value) ? `${value.toFixed(digits)}${unit}` : "—";
  }


  /* Where a result stands in review (radar/review.py result_stage) and who
     can see its current version. Shared with the Manual review block. */
  const STAGES = {
    draft: ["Private draft", "draft"],
    completed: ["Completed · not submitted", "draft"],
    in_review: ["Submitted · awaiting review", "pending"],
    returned: ["Returned for correction", "returned"],
    rejected: ["Rejected", "rejected"],
    published: ["Reviewed · published", "published"],
    withdrawn: ["Withdrawn after publication", "rejected"],
    superseded: ["Superseded by a newer version", "returned"]
  };
  const VISIBILITY = {
    private: "Visible only to you",
    reviewers: "Visible to you and reviewers",
    public: "Published to all signed-in users"
  };


  function stageChip(review) {
    const [label, kind] = STAGES[review?.stage] || STAGES.draft;
    return `<span class="fl-review-chip ${kind}">${escapeHtml(label)}</span>`;
  }


  /* What the stage does not say by itself: edits made after a version was
     submitted or published are not part of that version. */
  function stageNote(review) {
    if (!review) {
      return "";
    }
    const notes = [VISIBILITY[review.visibility] || VISIBILITY.private];
    // revision numbers restart after a reset, so the notes do not quote them
    if (review.stage === "in_review" && review.changed_since_submission) {
      notes.push("changed since it was submitted; the reviewer sees the submitted version");
    }
    if (review.published_submission_id && review.stage !== "published") {
      notes.push("an earlier version is published; your current result is not");
    }
    return notes.join(" · ");
  }


  /* Draft picks: hollow; completed sessions: filled. A position verified
     against the film CBD is drawn in a darker tone; other picks sit at
     ASTRA's own (unverified) position. The outline follows the review
     stage: dashed while awaiting review, teal once published (the colour of
     the Reviewed results layer), red when returned or rejected. */
  function style(feature) {
    const completed = feature.get("status") === "completed";
    const verified = feature.get("geolocation_status") === "verified";
    const stage = feature.get("review")?.stage;
    const selected = state.selected && feature.getId() === state.selected.getId();
    const colour = verified ? "#7c2d12" : "#c2410c";
    const outline = stage === "published" ? "#0f766e"
      : stage === "returned" || stage === "rejected" ? "#b91c1c" : colour;
    return new ol.style.Style({
      image: new ol.style.RegularShape({
        points: 4,
        radius: selected ? 8 : 6,
        angle: Math.PI / 4,
        fill: completed || verified ? new ol.style.Fill({ color: colour }) : new ol.style.Fill({ color: "rgba(255,255,255,0.85)" }),
        stroke: new ol.style.Stroke({ color: outline, width: selected ? 3 : 2,
                                      lineDash: stage === "in_review" ? [3, 2] : undefined })
      }),
      zIndex: 10
    });
  }


  async function reload() {
    if (!state.layer || state.loading) {
      return;
    }
    state.loading = true;
    try {
      const response = await fetch(API, { credentials: "same-origin", cache: "no-store",
                                          headers: { Accept: "application/json" } });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const collection = await response.json();
      const projection = state.map.getView().getProjection();
      const features = new ol.format.GeoJSON().readFeatures(collection, {
        dataProjection: "EPSG:4326", featureProjection: projection
      });
      const source = state.layer.getSource();
      source.clear();
      source.addFeatures(features);
      state.summary = collection.summary || null;
      if (state.selected && !source.getFeatureById(state.selected.getId())) {
        state.selected = null;
      }
    } catch (error) {
      state.summary = { error: "Your picks could not be loaded." };
    } finally {
      state.loading = false;
      state.onChange();
    }
  }


  function panelHtml() {
    const s = state.summary;
    if (!s) {
      return "";
    }
    if (s.error) {
      return `<div class="fl-record-section"><div class="fl-record-section-title">My picks</div>
        <p class="fl-radar-panel-note">${escapeHtml(s.error)}</p></div>`;
    }
    const total = (s.by_status?.draft || 0) + (s.by_status?.completed || 0);
    let selected = "";
    if (state.selected) {
      const p = state.selected.getProperties();
      selected = `
        <div class="fl-record-grid fl-pick-detail">
          <div class="fl-record-item"><span>A-scope</span><strong>${escapeHtml(p.a_scope)} · ${escapeHtml(p.filename)}</strong></div>
          <div class="fl-record-item"><span>Review</span><strong>${stageChip(p.review || { stage: p.status })}</strong></div>
          <div class="fl-record-item"><span>CBD</span><strong>${
            p.cbd_differs && Number.isFinite(p.verified_cbd)
              ? `ASTRA CBD ${escapeHtml(p.cbd)} · film CBD ${escapeHtml(p.verified_cbd)} (confirmed)`
              : escapeHtml(p.cbd ?? "—")}</strong></div>
          <div class="fl-record-item"><span>Position</span><strong>${fmt(p.lat, 4, "°")}, ${fmt(p.lon, 4, "°")}</strong></div>
          <div class="fl-record-item"><span>Surface / bed</span><strong>${fmt(p.surface_us, 2, " µs")} / ${fmt(p.bed_us, 2, " µs")}</strong></div>
          <div class="fl-record-item"><span>Ice thickness</span><strong>${fmt(p.h_ice_m, 1, " m")}</strong></div>
        </div>
        <p class="fl-radar-panel-note">${escapeHtml(p.workflow === "astra-manual" ? "ASTRA manual pick" : p.workflow)}${
          p.dataset_id ? ` · ${escapeHtml(p.dataset_id)}` : ""}${
          p.picks && Object.values(p.picks).includes("suggested") ? " · includes suggested picks" : ""}${
          p.geolocation_status === "verified" ? " · position verified against the film" : " · position unverified (ASTRA-assigned CBD)"} · ${
          escapeHtml(stageNote(p.review || { stage: p.status, visibility: "private" }))}</p>
        <button type="button" class="fl-radar-button" data-open-pick="${escapeHtml(p.asset_id)}"
          data-focus="${Number.isInteger(p.window_x) ? p.window_x : ""}">Open in Manual at this A-scope</button>`;
    }
    return `
      <div class="fl-record-section">
        <div class="fl-record-section-title">My picks</div>
        <label class="fl-astra-toggle">
          <input type="checkbox" data-my-picks ${state.visible ? "checked" : ""}>
          Show my picks on the map
        </label>
        <p class="fl-radar-panel-note">${total
          ? `${total} picked A-scope${total === 1 ? "" : "s"} (${s.by_status.draft || 0} draft, ${s.by_status.completed || 0} completed)${
              s.without_position ? ` · ${s.without_position} without a navigation position` : ""}.`
          : "A-scopes you commit in Manual appear here and on the map."}</p>
        ${stagesHtml(s.results_by_stage)}
        ${selected}
      </div>`;
  }


  /* Results (radar files) per review stage, in workflow order. */
  function stagesHtml(counts) {
    const entries = Object.keys(STAGES).filter(stage => counts?.[stage]);
    if (!entries.length) {
      return "";
    }
    return `<p class="fl-radar-panel-note fl-stage-counts">${entries.map(stage =>
      `${stageChip({ stage })}${counts[stage]} radar file${counts[stage] === 1 ? "" : "s"}`).join(" ")}</p>
      <p class="fl-radar-panel-note">Private work stays visible only to you; a submitted
        version is visible to reviewers; only approved versions are published.</p>`;
  }


  function bindPanel(root, { openAsset }) {
    root.querySelector("[data-my-picks]")?.addEventListener("change", event => {
      state.visible = event.target.checked;
      state.layer?.setVisible(state.visible);
    });
    root.querySelector("[data-open-pick]")?.addEventListener("click", event => {
      const focus = event.target.dataset.focus;
      openAsset(event.target.dataset.openPick, focus === "" ? null : Number(focus));
    });
  }


  function initialize({ map, onChange }) {
    if (!map || !window.ol || state.layer) {
      return;
    }
    state.map = map;
    state.onChange = onChange || (() => {});
    state.layer = new ol.layer.Vector({
      source: new ol.source.Vector(),
      style,
      properties: { id: "frozen-my-picks", label: "My picks" },
      zIndex: 20
    });
    map.addLayer(state.layer);
    map.on("singleclick", event => {
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
    reload();
  }


  window.FrozenLegaciesUserLayer = {
    initialize,
    reload,
    panelHtml,
    bindPanel,
    stageChip,
    stageNote,
    get summary() {
      return state.summary;
    }
  };

})();
