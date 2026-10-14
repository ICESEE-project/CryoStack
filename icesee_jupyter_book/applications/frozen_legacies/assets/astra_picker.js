/* ============================================================
 * Frozen Legacies
 * astra_picker.js
 *
 * Manual mode: the ASTRA A-scope picker.
 *
 * The server owns the ASTRA session (pickers/astra.py): every
 * button and plot click is sent as one action and the server
 * returns the updated session. The browser only displays the
 * working window, the trace and the picks, and converts a click
 * into ASTRA's matplotlib data coordinates for the window
 * (pixel i spans [i - 0.5, i + 0.5)).
 * ============================================================ */


(function () {

  "use strict";

  const API = "/frozen-legacies/api/assets";

  /* ASTRA's colours for each element (process_and_trace). */
  const COLORS = {
    trace: "#e11d2e",
    yReference: "#1d4ed8",
    xReference: "#7e22ce",
    yGrid: "#15803d",
    xGrid: "#ea8a00",
    surface: "#16a34a",
    bed: "#c026d3",
    noisefloor: "#7f1d1d",
    mainbang: "#1d4ed8"
  };

  const PICKS = [
    ["surface", "Surface"],
    ["bed", "Bed"],
    ["noisefloor", "Noise Floor"],
    ["mainbang", "Main Bang"]
  ];


  /* ----------------------------------------------------------
   * Helpers
   * ---------------------------------------------------------- */

  function $(id) {
    return document.getElementById(id);
  }


  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }


  function fmt(value, suffix = "") {
    return value === "" || value === null || value === undefined
      ? "—"
      : `${value}${suffix}`;
  }


  function formatBytes(bytes) {
    return bytes >= 1048576
      ? `${(bytes / 1048576).toFixed(1)} MB`
      : `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }


  const SVG_NS = "http://www.w3.org/2000/svg";

  function svg(tag, attributes = {}, text = null) {
    const element = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attributes)) {
      element.setAttribute(key, String(value));
    }
    if (text !== null) {
      element.textContent = text;
    }
    return element;
  }


  function toDataCoordinates(clientX, clientY, rect, geometry) {
    return window.FrozenLegaciesRadarGeometry.astraDataCoordinates(
      clientX, clientY, rect, geometry.zoom_width, geometry.zoom_height
    );
  }


  /* ----------------------------------------------------------
   * State
   * ---------------------------------------------------------- */

  const picker = {
    asset: null,
    session: null,
    busy: false,
    sliderTimer: null,
    onChange: () => {},
    api: null
  };


  async function request(path, options = {}) {
    return picker.api(path, options);
  }


  function base() {
    return `${API}/${encodeURIComponent(picker.asset.asset_id)}`;
  }


  /* ----------------------------------------------------------
   * Server round trips
   * ---------------------------------------------------------- */

  async function load() {
    try {
      const session = await request(`${base()}/manual`);
      apply(session);
    } catch (error) {
      showError(error);
    }
  }


  async function act(payload) {
    if (!picker.session || picker.busy) {
      return;
    }
    picker.busy = true;
    setBusy(true, payload.action === "done" ? "Generating the ASTRA CSV and QC image…" : null);
    try {
      const session = await request(`${base()}/manual`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision: picker.session.revision, ...payload })
      });
      apply(session);
    } catch (error) {
      showError(error);
      if (error.status === 409) {
        await load();          // another window changed the session
        showError(error);
      }
    } finally {
      picker.busy = false;
      setBusy(false);
    }
  }


  /* ----------------------------------------------------------
   * Rendering
   * ---------------------------------------------------------- */

  function apply(session) {
    picker.session = session;
    const completed = session.status === "completed";
    $("fl-astra").hidden = completed;
    $("fl-astra-result").hidden = !completed;
    if (completed) {
      renderResult();
    } else {
      renderPicker();
    }
    picker.onChange();
  }


  function setBusy(busy, message = null) {
    $("fl-astra").classList.toggle("busy", busy);
    if (message) {
      $("fl-astra-hint").textContent = message;
    }
  }


  function showError(error) {
    const message = error?.message || String(error);
    if (error?.sessionInvalid) {
      $("fl-astra").hidden = true;
      $("fl-astra-result").hidden = false;
      $("fl-astra-result").innerHTML = `
        <div class="fl-empty-selection">
          <div class="fl-empty-icon">!</div>
          <div><strong>Manual session unavailable</strong><span>${escapeHtml(message)}</span>
          <button type="button" class="fl-radar-button" data-astra-action="reset">Reset session</button></div>
        </div>`;
      bindResultButtons();
      return;
    }
    $("fl-astra-hint").textContent = message;
  }


  function hintFor(session) {
    const s = session.state;
    if (s.setting_x_reference_line) {
      return "Click the plot to place the X axis reference line.";
    }
    if (s.setting_reference_line) {
      return "Click the plot to place the Y axis reference line.";
    }
    if (s.setting_y_axis) {
      const warning = s.reference_line_y === null
        ? " ASTRA draws the Y grid only after the Y axis reference line is set."
        : "";
      return `Click Y-axis grid line ${s.y_axis_points.length + 1} of 4 (first click = −55 dB).${warning}`;
    }
    if (s.setting_x_axis) {
      return `Click X-axis grid line ${s.x_axis_points.length + 1} of 4 (first click = ${s.sweep_rate} µs).`;
    }
    if (s.feature_selected && s.current_feature) {
      return s.current_feature.startsWith("No ")
        ? `Click the plot to record ${s.current_feature}.`
        : `Click the plot to pick ${s.current_feature}; the pick snaps to the red trace.`;
    }
    return session.messages.length
      ? session.messages[session.messages.length - 1]
      : "Choose a calibration step or a feature to pick.";
  }


  /* Which of ASTRA's four calibration steps are set (display only). */
  function calibrationSteps(s) {
    return [
      s.x_reference_line !== null,
      s.reference_line_y !== null,
      s.y_axis_lines.length > 0,
      s.x_axis_lines.length > 0
    ];
  }


  /* Trace visibility is a per-browser display preference. */
  function traceVisible() {
    try {
      return window.localStorage.getItem("fl-astra-trace") !== "hidden";
    } catch (error) {
      return true;
    }
  }


  function renderPicker() {
    const session = picker.session;
    const s = session.state;
    const g = session.geometry;

    $("fl-astra-title").textContent = session.title;
    $("fl-astra-status").textContent =
      `${session.committed.rows.length} committed`;
    const calibration = calibrationSteps(s);
    const ready = calibration.filter(Boolean).length;
    const chip = $("fl-astra-calibration");
    chip.textContent = `Calibration ${ready}/4`;
    chip.classList.toggle("complete", ready === 4);
    chip.title = "X reference, Y reference, Y grid, X grid";
    // an instruction for the next click, or the result of the last action
    const armed = s.setting_x_reference_line || s.setting_reference_line ||
      s.setting_y_axis || s.setting_x_axis || (s.feature_selected && s.current_feature);
    const hint = hintFor(session);
    $("fl-astra-hint").textContent = armed || !session.messages.length ? `Next: ${hint}` : hint;

    const slider = $("fl-astra-slider");
    slider.max = String(g.slider_max);
    slider.value = String(s.slider);
    $("fl-astra-position").textContent =
      `X Position ${s.slider.toLocaleString("en-US")} / ${g.slider_max.toLocaleString("en-US")}`;

    const img = $("fl-astra-image");
    const src = `${base()}/manual/window?slider=${s.slider}`;
    if (img.getAttribute("src") !== src) {
      $("fl-astra-stage").classList.add("loading");
      img.onload = () => $("fl-astra-stage").classList.remove("loading");
      img.src = src;
    }

    document.querySelectorAll("[data-astra-setup]").forEach(button => {
      const target = button.dataset.astraSetup;
      const active = {
        x_reference: s.setting_x_reference_line,
        y_reference: s.setting_reference_line,
        y_axis: s.setting_y_axis,
        x_axis: s.setting_x_axis
      }[target];
      const done = {
        x_reference: s.x_reference_line !== null,
        y_reference: s.reference_line_y !== null,
        y_axis: s.y_axis_lines.length > 0,
        x_axis: s.x_axis_lines.length > 0
      }[target];
      button.classList.toggle("active", Boolean(active));
      button.classList.toggle("set", Boolean(done) && !active);
    });
    document.querySelectorAll("[data-astra-sweep]").forEach(button => {
      button.classList.toggle("active", Number(button.dataset.astraSweep) === s.sweep_rate);
    });
    document.querySelectorAll("[data-astra-feature]").forEach(button => {
      button.classList.toggle(
        "active", s.feature_selected && s.current_feature === button.dataset.astraFeature
      );
    });

    fitStage();
    renderOverlay();
  }


  /* Fit the window box (fixed aspect) inside the stage. */
  function fitStage() {
    const session = picker.session;
    if (!session) {
      return;
    }
    const stage = $("fl-astra-stage");
    const box = $("fl-astra-box");
    // exact aspect ratio at every stage size (radar_geometry.js fitBox)
    const space = stage.getBoundingClientRect();
    const fitted = window.FrozenLegaciesRadarGeometry.fitBox(
      space.width, space.height,
      session.geometry.zoom_width, session.geometry.zoom_height
    );
    box.style.width = `${fitted.width}px`;
    box.style.height = `${fitted.height}px`;
  }


  function renderOverlay() {
    const session = picker.session;
    const s = session.state;
    const g = session.geometry;
    const overlay = $("fl-astra-overlay");
    const W = g.zoom_width;
    const H = g.zoom_height;
    overlay.setAttribute("viewBox", `-0.5 -0.5 ${W} ${H}`);
    overlay.setAttribute("preserveAspectRatio", "none");
    overlay.replaceChildren();

    const boxWidth = $("fl-astra-box").clientWidth || 1000;
    const unit = W / boxWidth;                    // data units per CSS pixel
    const label = (x, y, text, color, anchor = "start") =>
      overlay.appendChild(svg("text", {
        x, y, fill: color, "font-size": 12 * unit, "font-weight": 700,
        "text-anchor": anchor, "dominant-baseline": "middle",
        "paint-order": "stroke", stroke: "#ffffff", "stroke-width": 3 * unit
      }, text));
    const hline = (y, color, dash) => overlay.appendChild(svg("line", {
      x1: -0.5, x2: W - 0.5, y1: y, y2: y, stroke: color,
      "stroke-width": 1.75, "stroke-dasharray": dash, "vector-effect": "non-scaling-stroke"
    }));
    const vline = (x, color, dash) => overlay.appendChild(svg("line", {
      x1: x, x2: x, y1: -0.5, y2: H - 0.5, stroke: color,
      "stroke-width": 1.75, "stroke-dasharray": dash, "vector-effect": "non-scaling-stroke"
    }));

    // detected trace (ASTRA's red line): drawn first and lighter, so picks
    // and calibration lines stay on top; its coordinates are unchanged
    if (traceVisible()) {
      overlay.appendChild(svg("polyline", {
        points: session.trace.map((y, x) => `${x},${y}`).join(" "),
        fill: "none", stroke: COLORS.trace, "stroke-width": 1, opacity: 0.55,
        class: "fl-astra-trace", "vector-effect": "non-scaling-stroke"
      }));
    }

    // calibration
    s.y_axis_lines.forEach((y, i) => {
      hline(y, COLORS.yGrid, "2 3");
      label(8 * unit, y, `${s.y_axis_labels[i]} dB`, COLORS.yGrid);
    });
    s.x_axis_lines.forEach((x, i) => {
      vline(x, COLORS.xGrid, "2 3");
      label(x, H - 12 * unit, `${s.x_axis_labels[i]} µs`, COLORS.xGrid, "middle");
    });
    if (s.reference_line_y !== null) {
      hline(s.reference_line_y, COLORS.yReference, "8 5");
      label(W - 8 * unit, s.reference_line_y, "−60 dB", COLORS.yReference, "end");
    }
    if (s.x_reference_line !== null) {
      vline(s.x_reference_line, COLORS.xReference, "8 5");
      label(s.x_reference_line, 12 * unit, "0 µs", COLORS.xReference, "middle");
    }
    if (s.setting_y_axis) {
      s.y_axis_points.forEach(y => hline(y, COLORS.yGrid, "6 4"));
    }
    if (s.setting_x_axis) {
      s.x_axis_points.forEach(x => vline(x, COLORS.xGrid, "6 4"));
    }

    // committed A-scopes falling inside this window (faded)
    (s.all_ascope_picks || []).forEach((picks, index) => {
      const number = s.data[index]?.[0];
      for (const [field] of PICKS) {
        const c = picks[field];
        if (!c) {
          continue;
        }
        const x = c[2] - s.slider;
        const y = c[3] - g.crop_start_y;
        if (x < 0 || x >= W) {
          continue;
        }
        overlay.appendChild(svg("circle", {
          cx: x, cy: y, r: 6 * unit, fill: "none", stroke: COLORS[field],
          "stroke-width": 1.5, opacity: 0.45, "vector-effect": "non-scaling-stroke"
        }));
        label(x + 9 * unit, y, `A${number}`, COLORS[field]).setAttribute("opacity", "0.6");
      }
    });

    // current A-scope picks
    for (const [field, name] of PICKS) {
      const pick = session.picks[field];
      if (!pick) {
        continue;
      }
      overlay.appendChild(svg("circle", {
        cx: pick.x_zoom, cy: pick.y_zoom, r: 7 * unit,
        fill: COLORS[field], stroke: "#0f172a", "stroke-width": 1.5,
        "stroke-dasharray": pick.source === "suggested" ? "3 2" : "none",
        "vector-effect": "non-scaling-stroke"
      }));
      label(pick.x_zoom + 11 * unit, pick.y_zoom - 12 * unit,
        `${name}${pick.source === "suggested" ? " (suggested)" : ""}`, COLORS[field]);
    }
  }


  function renderResult() {
    const session = picker.session;
    const asset = picker.asset;
    const outputs = session.outputs;
    const committed = session.committed;
    const completed = session.completed_at
      ? new Date(session.completed_at * 1000).toLocaleString()
      : "";

    const download = product => {
      const output = outputs[product];
      return output
        ? `<a class="fl-radar-button primary" href="${escapeHtml(output.url)}" download>
             ${escapeHtml(output.name)} · ${formatBytes(output.bytes)}</a>`
        : "";
    };

    const columns = ["A-scope Number", "CBD", "LAT", "LON", "surface_us", "bed_us", "h_ice_m"];
    const index = columns.map(c => committed.columns.indexOf(c));
    const rows = committed.rows.map(row => `<tr>${
      index.map(i => `<td>${escapeHtml(i >= 0 ? row[i] || "—" : "—")}</td>`).join("")}</tr>`).join("");

    $("fl-astra-result").innerHTML = `
      <div class="fl-astra-result-head">
        <span class="fl-astra-chip complete">Completed</span>
        <strong>${escapeHtml(asset.title || asset.filename)}</strong>
        <span>${escapeHtml(asset.filename)} · ${asset.origin === "shared" ? "Shared radar" : "My upload"}
          · ${committed.rows.length} A-scope${committed.rows.length === 1 ? "" : "s"} · ${escapeHtml(completed)}</span>
      </div>
      <div class="fl-astra-downloads">${download("astra-csv")}${download("astra-qc")}</div>
      <div class="fl-astra-qc">
        <div class="fl-astra-qc-label">QC preview — committed picks on the radar strip</div>
        <div class="fl-astra-qc-strip">
          <img id="fl-astra-qc-image" alt="Radar strip with committed picks">
          <svg id="fl-astra-qc-overlay"></svg>
        </div>
      </div>
      <div class="fl-astra-table-wrap">
        <table class="fl-astra-table">
          <thead><tr>${columns.map(c => `<th>${escapeHtml(c === "CBD" ? "CBD (ASTRA)" : c)}</th>`).join("")}</tr></thead>
          <tbody>${rows || `<tr><td colspan="${columns.length}">No A-scopes were committed.</td></tr>`}</tbody>
        </table>
      </div>
      <div class="fl-astra-result-actions">
        <button type="button" class="fl-radar-button" data-astra-action="reset">Reset session</button>
      </div>`;

    // QC preview: the whole strip (server-rendered) with every committed pick
    const G = window.FrozenLegaciesRadarGeometry;
    const width = asset.image.width;
    const height = asset.image.height;
    const scale = G.overviewScale(width, 1600);
    $("fl-astra-qc-image").src = G.viewUrl(asset.asset_id, 0, width, scale);
    const overlay = $("fl-astra-qc-overlay");
    overlay.setAttribute("viewBox", `0 0 ${width} ${height}`);
    overlay.setAttribute("preserveAspectRatio", "none");
    (session.state.all_ascope_picks || []).forEach(picks => {
      for (const [field] of PICKS) {
        const c = picks[field];
        if (c) {
          overlay.appendChild(svg("line", {
            x1: c[2], x2: c[2], y1: c[3] - 120, y2: c[3] + 120,
            stroke: COLORS[field], "stroke-width": 2, "vector-effect": "non-scaling-stroke"
          }));
        }
      }
    });
    bindResultButtons();
    // georeferencing of the committed A-scopes (separate from ASTRA's products)
    window.FrozenLegaciesGeoref?.mount($("fl-astra-result"), asset);
    // scientific review of this result (a frozen snapshot is reviewed)
    window.FrozenLegaciesReview?.mount($("fl-astra-result"), asset);
  }


  function bindResultButtons() {
    $("fl-astra-result").querySelectorAll("[data-astra-action='reset']").forEach(button => {
      button.addEventListener("click", reset);
    });
  }


  /* ----------------------------------------------------------
   * Panel (right side): session details
   * ---------------------------------------------------------- */

  function panelHtml() {
    const session = picker.session;
    if (!session || !picker.asset) {
      return "";
    }
    const s = session.state;
    const item = (name, value) =>
      `<div class="fl-record-item"><span>${escapeHtml(name)}</span><strong>${escapeHtml(value)}</strong></div>`;
    const pickRows = PICKS.map(([field, name]) => {
      const p = session.picks[field];
      return item(name, p
        ? `${fmt(p.us, " µs")} · ${fmt(p.db, " dB")}${p.source === "suggested" ? " · suggested" : ""}`
        : "—");
    }).join("");
    const status = session.status === "completed"
      ? "Completed"
      : session.status === "new" ? "Not started" : "In progress";
    return `
      <div class="fl-record-section">
        <div class="fl-record-section-title">Manual picking (ASTRA)</div>
        <div class="fl-record-grid">
          ${item("Session", status)}
          ${item("Current", session.title)}
          ${item("Committed", String(session.committed.rows.length))}
          ${item("Sweep rate", `${s.sweep_rate} µs/div`)}
          ${item("X reference", s.x_reference_line === null ? "not set" : `x = ${s.x_reference_line}`)}
          ${item("Y reference", s.reference_line_y === null ? "not set" : `y = ${s.reference_line_y}`)}
          ${item("Y grid", s.y_axis_lines.length ? `${s.y_axis_lines.length} lines` : "not set")}
          ${item("X grid", s.x_axis_lines.length ? `${s.x_axis_lines.length} lines` : "not set")}
          ${pickRows}
        </div>
      </div>`;
  }


  /* ----------------------------------------------------------
   * Controls
   * ---------------------------------------------------------- */

  async function reset() {
    const ok = window.confirm(
      "Reset this manual session? All picks and the generated CSV and QC image " +
      "for this radar asset are discarded. The radar TIFF is kept."
    );
    if (!ok) {
      return;
    }
    picker.busy = false;
    try {
      const session = await request(`${base()}/manual`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "reset", confirm: true })
      });
      apply(session);
    } catch (error) {
      showError(error);
    }
  }


  function bind() {
    document.querySelectorAll("[data-astra-setup]").forEach(button => {
      button.addEventListener("click", () => act({ action: "setup", target: button.dataset.astraSetup }));
    });
    document.querySelectorAll("[data-astra-sweep]").forEach(button => {
      button.addEventListener("click", () => act({ action: "sweep_rate", rate: Number(button.dataset.astraSweep) }));
    });
    document.querySelectorAll("[data-astra-feature]").forEach(button => {
      button.addEventListener("click", () => act({ action: "select", feature: button.dataset.astraFeature }));
    });
    document.querySelectorAll("[data-astra-step]").forEach(button => {
      button.addEventListener("click", () => act({ action: "step", step: button.dataset.astraStep }));
    });
    $("fl-astra-suggest").addEventListener("click", () => act({ action: "suggest" }));
    $("fl-astra-next").addEventListener("click", () => act({ action: "next" }));
    $("fl-astra-done").addEventListener("click", () => {
      if (window.confirm("Finish this radar TIFF and generate the ASTRA CSV and QC image?")) {
        act({ action: "done" });
      }
    });
    $("fl-astra-reset").addEventListener("click", reset);

    const toggle = $("fl-astra-trace-toggle");
    toggle.checked = traceVisible();
    toggle.addEventListener("change", () => {
      try {
        window.localStorage.setItem("fl-astra-trace", toggle.checked ? "shown" : "hidden");
      } catch (error) {
        // display preference only
      }
      if (picker.session && picker.session.status !== "completed") {
        renderOverlay();
      }
    });

    const slider = $("fl-astra-slider");
    slider.addEventListener("input", () => {
      const value = Number(slider.value);
      $("fl-astra-position").textContent =
        `X Position ${value.toLocaleString("en-US")} / ${Number(slider.max).toLocaleString("en-US")}`;
      window.clearTimeout(picker.sliderTimer);
      picker.sliderTimer = window.setTimeout(() => act({ action: "move", slider: value }), 250);
    });

    $("fl-astra-box").addEventListener("click", event => {
      const session = picker.session;
      if (!session || session.status === "completed") {
        return;
      }
      const s = session.state;
      const interactive =
        s.setting_x_reference_line || s.setting_reference_line ||
        s.setting_y_axis || s.setting_x_axis || s.feature_selected;
      if (!interactive) {
        $("fl-astra-hint").textContent = "Choose a calibration step or a feature to pick first.";
        return;
      }
      const point = toDataCoordinates(
        event.clientX, event.clientY,
        $("fl-astra-box").getBoundingClientRect(), session.geometry
      );
      if (point) {
        act({ action: "click", x: point.x, y: point.y });
      }
    });

    if (window.ResizeObserver) {
      new ResizeObserver(() => {
        if (picker.session && picker.session.status !== "completed") {
          fitStage();
          renderOverlay();
        }
      }).observe($("fl-astra-stage"));
    }
  }


  /* ----------------------------------------------------------
   * Public API (used by radar.js)
   * ---------------------------------------------------------- */

  let bound = false;

  window.FrozenLegaciesAstra = {

    /* Open (or continue) the manual session of a radar asset. */
    open(asset, { api, onChange, focusSlider = null }) {
      if (!bound) {
        bind();
        bound = true;
      }
      picker.api = api;
      picker.onChange = onChange || (() => {});
      if (picker.asset?.asset_id !== asset.asset_id) {
        picker.session = null;
        $("fl-astra-image").removeAttribute("src");
        $("fl-astra-overlay").replaceChildren();
      }
      picker.asset = asset;
      return load().then(() => {
        // return to the window a picked A-scope was committed in (an ordinary
        // ASTRA move; only while the session is still being picked)
        const session = picker.session;
        if (Number.isInteger(focusSlider) && session && session.status === "in_progress" &&
            focusSlider >= 0 && focusSlider <= session.geometry.slider_max &&
            session.state.slider !== focusSlider) {
          return act({ action: "move", slider: focusSlider });
        }
        return undefined;
      });
    },

    close() {
      picker.asset = null;
      picker.session = null;
      $("fl-astra").hidden = true;
      $("fl-astra-result").hidden = true;
    },

    panelHtml,

    toDataCoordinates,

    get session() {
      return picker.session;
    }
  };

})();
