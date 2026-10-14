/* ============================================================
 * Frozen Legacies
 * radar.js
 *
 * Radar workspace: Map / Manual / Automatic modes, the user's
 * radar assets (uploaded or referencing shared radar), and the
 * server-rendered radar viewer.
 *
 * The browser never receives a full TIFF: it requests windows of
 * source columns from /frozen-legacies/api/assets/<id>/view.
 * Viewing geometry lives in radar_geometry.js; scientific
 * processing stays on the server.
 * ============================================================ */


(function () {

  "use strict";

  const G = window.FrozenLegaciesRadarGeometry;
  const API = "/frozen-legacies/api";
  const MODES = ["map", "manual", "automatic"];



  /* ----------------------------------------------------------
   * Small helpers
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


  function formatInt(value) {
    return Number.isFinite(value) ? value.toLocaleString("en-US") : "—";
  }


  function formatCoord(value, positive, negative) {
    if (!Number.isFinite(value)) {
      return "unavailable";
    }
    return `${Math.abs(value).toFixed(4)}° ${value >= 0 ? positive : negative}`;
  }


  function formatBytes(bytes) {
    if (!Number.isFinite(bytes)) {
      return "—";
    }
    return bytes >= 1048576
      ? `${(bytes / 1048576).toFixed(1)} MB`
      : `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }


  function cbdRange(asset) {
    return Number.isFinite(asset?.cbd_start) && Number.isFinite(asset?.cbd_end)
      ? `${asset.cbd_start}–${asset.cbd_end}`
      : "not in filename";
  }


  class SessionEnded extends Error {}


  async function api(path, options = {}) {
    const url = path.startsWith("/frozen-legacies/") ? path : `${API}${path}`;
    const response = await fetch(url, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json", ...(options.headers || {}) },
      ...options
    });
    if (response.status === 401) {
      throw new SessionEnded();
    }
    let body = null;
    try {
      body = await response.json();
    } catch (error) {
      body = null;
    }
    if (!response.ok) {
      const error = new Error(body?.error || `Request failed (HTTP ${response.status}).`);
      error.status = response.status;
      error.sessionInvalid = Boolean(body?.session_invalid);
      throw error;
    }
    return body;
  }


  function errorMessage(error) {
    return error instanceof SessionEnded
      ? "Your CryoStack session has ended. Reload the page to sign in again."
      : (error?.message || String(error));
  }


  /* ----------------------------------------------------------
   * State
   * ---------------------------------------------------------- */

  const state = {
    mode: "map",
    sources: [],
    assets: [],
    asset: null,          // detail of the open asset
    scale: 8,
    x: 0,
    selection: null,      // { datasetId, flight, tiff, observationId }
    map: null,
    ui: null,
    renderTimer: null,
    openSections: {},      // panel section key -> open (per page)
    explorerFolded: null,  // user's choice in Manual/Automatic
    layout: { panel: "shown", focus: false },
    urlReady: false,      // URL state is written only after initialization
    applyingUrl: false    // true while the URL is being applied (no new entries)
  };


  /* ----------------------------------------------------------
   * Modes
   * ---------------------------------------------------------- */

  function setMode(mode) {
    if (!MODES.includes(mode)) {
      return;
    }
    state.mode = mode;

    document.querySelectorAll(".fl-mode-button").forEach(button => {
      const active = button.dataset.mode === mode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });

    const workspace = $("fl-radar-workspace");
    workspace.hidden = mode === "map";
    document.body.dataset.flMode = mode;
    applyLayout();
    arrangePanel();

    if (mode === "map") {
      // The map stayed mounted underneath; its selection is untouched.
      state.map?.updateSize();
      // picks committed in Manual appear on the map right away
      window.FrozenLegaciesUserLayer?.reload();
      window.FrozenLegaciesReview?.reload();
      window.FrozenLegaciesCatalog?.refreshSelected?.();
    } else {
      renderModeNote();
      syncWorkspace();
    }
    renderPanel();
    syncUrl({ push: true });
  }


  /*
   * URL state: the mode, the open radar asset, the selected dataset and
   * flight, and the map view are kept in the URL hash
   * (#mode=manual&asset=<id>&ds=<dataset>&flight=<n>&view=<zoom>/<x>/<y>,
   * map centre in EPSG:3031 metres; cov=1&seg=<catalog id> for the radar
   * coverage layer and its selected segment), so back/forward and reload return to
   * the same place and an open asset resumes its saved session. The
   * view is only the map camera; no radar position is derived from it.
   */
  const ASSET_ID = /^[0-9a-f]{32}$/;
  const SELECTION_VALUE = /^[A-Za-z0-9._-]{1,64}$/;
  const SEGMENT_ID = /^cat-[0-9a-f]{24}$/;

  function readUrlState() {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const mode = MODES.includes(params.get("mode")) ? params.get("mode") : "map";
    const asset = ASSET_ID.test(params.get("asset") || "") ? params.get("asset") : null;
    const dataset = SELECTION_VALUE.test(params.get("ds") || "") ? params.get("ds") : null;
    const flight = dataset && SELECTION_VALUE.test(params.get("flight") || "") ? params.get("flight") : null;
    const view = (params.get("view") || "").split("/").map(Number);
    const validView = view.length === 3 && view.every(Number.isFinite);
    const coverage = params.get("cov") === "1";
    const segment = coverage && SEGMENT_ID.test(params.get("seg") || "") ? params.get("seg") : null;
    return { mode, asset, dataset, flight, view: validView ? view : null, coverage, segment };
  }


  function selectedDatasetAndFlight() {
    const ui = state.ui?.state;
    const dataset = ui && ui.datasetId !== "all" && SELECTION_VALUE.test(String(ui.datasetId))
      ? String(ui.datasetId) : null;
    const flight = dataset && ui.flightNumber !== "all" && SELECTION_VALUE.test(String(ui.flightNumber))
      ? String(ui.flightNumber) : null;
    return { dataset, flight };
  }


  function urlHash() {
    const parts = [];
    if (state.mode !== "map") {
      parts.push(`mode=${state.mode}`);
    }
    if (state.asset && ASSET_ID.test(state.asset.asset_id)) {
      parts.push(`asset=${state.asset.asset_id}`);
    }
    const { dataset, flight } = selectedDatasetAndFlight();
    if (dataset) {
      parts.push(`ds=${encodeURIComponent(dataset)}`);
    }
    if (flight) {
      parts.push(`flight=${encodeURIComponent(flight)}`);
    }
    const coverage = window.FrozenLegaciesCatalog?.selection?.();
    if (coverage?.coverage) {
      parts.push("cov=1");
      if (coverage.segment && SEGMENT_ID.test(coverage.segment)) {
        parts.push(`seg=${coverage.segment}`);
      }
    }
    const view = state.map?.getView?.();
    const center = view?.getCenter();
    const zoom = view?.getZoom();
    if (center && Number.isFinite(zoom)) {
      parts.push(`view=${zoom.toFixed(2)}/${Math.round(center[0])}/${Math.round(center[1])}`);
    }
    return parts.length ? `#${parts.join("&")}` : "";
  }


  function syncUrl({ push = false } = {}) {
    if (state.applyingUrl || !state.urlReady) {
      return;
    }
    const hash = urlHash();
    if (hash === window.location.hash) {
      return;
    }
    // an empty workspace entry is replaced by the asset opened in it
    const current = readUrlState();
    const replace = !push || (current.mode !== "map" && !current.asset &&
                              current.mode === state.mode && state.asset);
    const url = `${window.location.pathname}${window.location.search}${hash}`;
    try {
      if (replace) {
        window.history.replaceState(null, "", url);
      } else {
        window.history.pushState(null, "", url);
      }
    } catch (error) {
      // history unavailable (sandboxed frame): the page still works
    }
  }


  async function applyUrlState(target) {
    state.applyingUrl = true;
    try {
      if (target.mode !== state.mode) {
        setMode(target.mode);
      }
      restoreDatasetAndFlight(target);
      // after the selection: selecting a dataset fits the map to its
      // flights, which would otherwise replace the camera from the URL
      if (target.view && state.map) {
        const view = state.map.getView();
        view.cancelAnimations();
        view.setZoom(target.view[0]);
        view.setCenter([target.view[1], target.view[2]]);
      }
      // the coverage layer and segment never move the camera
      await window.FrozenLegaciesCatalog?.restore?.({ coverage: Boolean(target.coverage),
                                                      segment: target.segment || null });
      if (target.asset && target.asset !== state.asset?.asset_id) {
        // only the viewer's own, available assets; anything else is dropped
        if (state.assets.some(a => a.asset_id === target.asset && a.available)) {
          await openAsset(target.asset);
        }
      } else if (!target.asset && state.asset) {
        await closeAsset();
      }
    } catch (error) {
      setViewerMessage(errorMessage(error));
    } finally {
      state.applyingUrl = false;
    }
    syncUrl();
  }


  // Selects the dataset/flight named in the URL when the catalog knows them;
  // an unknown value is dropped rather than guessed. The map camera from the
  // URL (if any) wins over the flight's own extent.
  function restoreDatasetAndFlight(target) {
    const ui = state.ui;
    if (!ui?.selectDataset) {
      return;
    }
    const current = selectedDatasetAndFlight();
    const knownDataset = target.dataset &&
      Array.from($("dataset-select")?.options || []).some(o => o.value === target.dataset);
    if (!knownDataset) {
      if (!target.dataset && current.dataset) {
        ui.selectDataset("all");
      }
      return;
    }
    if (target.dataset !== current.dataset) {
      ui.selectDataset(target.dataset);
    }
    const knownFlight = target.flight &&
      Array.from($("flight-select")?.options || []).some(o => o.value === target.flight);
    if (knownFlight && target.flight !== selectedDatasetAndFlight().flight) {
      ui.selectFlight(target.flight, { datasetId: target.dataset, zoom: !target.view });
    } else if (!target.flight && current.flight) {
      ui.showAllFlights();
    }
    state.selection = currentSelection(null);
    renderPanel();
  }


  function bindUrlState() {
    window.addEventListener("popstate", () => applyUrlState(readUrlState()));
    state.map?.on?.("moveend", () => syncUrl());
  }


  /*
   * Workspace layout (Manual / Automatic only): the side panel can be
   * hidden and a focus view shows only the radar workspace. Display
   * preference per browser; the picker refits its window box at the
   * exact aspect ratio (radar_geometry.js fitBox), so image coordinates
   * and click mapping do not depend on the layout.
   */
  const LAYOUT_KEY = "fl-radar-layout";

  function loadLayout() {
    try {
      const saved = JSON.parse(window.localStorage.getItem(LAYOUT_KEY) || "{}");
      return { panel: saved.panel === "hidden" ? "hidden" : "shown", focus: saved.focus === true };
    } catch (error) {
      return { panel: "shown", focus: false };
    }
  }


  function saveLayout() {
    try {
      window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(state.layout));
    } catch (error) {
      // display preference only
    }
  }


  function applyLayout() {
    const radar = state.mode !== "map";
    const panelHidden = radar && state.layout.panel === "hidden";
    const focus = radar && state.layout.focus;
    document.body.classList.toggle("fl-panel-hidden", panelHidden);
    document.body.classList.toggle("fl-focus", focus);
    const panelButton = $("fl-layout-panel");
    if (panelButton) {
      panelButton.textContent = state.layout.panel === "hidden" ? "Show panel" : "Hide panel";
      panelButton.setAttribute("aria-pressed", String(state.layout.panel === "hidden"));
      panelButton.hidden = focus;
    }
    const focusButton = $("fl-layout-focus");
    if (focusButton) {
      focusButton.textContent = focus ? "Exit focus" : "Focus";
      focusButton.setAttribute("aria-pressed", String(focus));
    }
    // the Automatic viewer requests a window as wide as its frame
    if (radar) {
      scheduleRender(150);
    }
  }


  function setLayout(change) {
    state.layout = { ...state.layout, ...change };
    saveLayout();
    applyLayout();
  }


  function bindLayout() {
    $("fl-layout-panel")?.addEventListener("click", () =>
      setLayout({ panel: state.layout.panel === "hidden" ? "shown" : "hidden" }));
    $("fl-layout-focus")?.addEventListener("click", () =>
      setLayout({ focus: !state.layout.focus }));
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && state.layout.focus && state.mode !== "map") {
        setLayout({ focus: false });
      }
    });
  }


  /*
   * One right panel, ordered by mode: in Map the explorer comes first; in
   * Manual and Automatic the radar sections come first and the explorer is
   * one section that can be folded (it is never removed).
   */
  function arrangePanel() {
    const explorer = $("fl-explorer-section");
    const radar = $("fl-radar-panel");
    if (!explorer || !radar) {
      return;
    }
    if (state.mode === "map") {
      explorer.open = true;
      explorer.after(radar);
    } else {
      explorer.before(radar);
      explorer.open = state.explorerFolded === null ? false : !state.explorerFolded;
    }
  }


  /*
   * Turn each panel section into a collapsible one, keeping the user's
   * open/closed choice across re-renders. Sections are moved, not copied,
   * so their event handlers are kept.
   */
  const FOLDED_BY_DEFAULT = { "Raw radar": mode => mode !== "map" };

  function makeCollapsible(panel) {
    panel.querySelectorAll(":scope > .fl-record-section").forEach(section => {
      const title = section.querySelector(":scope > .fl-record-section-title");
      if (!title) {
        return;
      }
      const key = title.textContent.trim();
      const details = document.createElement("details");
      details.className = "fl-record-section fl-panel-section";
      const remembered = state.openSections[`${state.mode}:${key}`];
      const folded = FOLDED_BY_DEFAULT[key]?.(state.mode) ?? false;
      details.open = remembered ?? !folded;
      const summary = document.createElement("summary");
      summary.className = "fl-record-section-title";
      summary.textContent = key;
      title.remove();
      details.appendChild(summary);
      while (section.firstChild) {
        details.appendChild(section.firstChild);
      }
      section.replaceWith(details);
      details.addEventListener("toggle", () => {
        state.openSections[`${state.mode}:${key}`] = details.open;
      });
    });
  }


  /*
   * Manual shows the ASTRA picker for the open asset; Automatic shows
   * the radar viewer. Both work on the same open radar asset.
   */
  function syncWorkspace() {
    const picker = window.FrozenLegaciesAstra;
    const automatic = window.FrozenLegaciesAutomatic;
    if (!state.asset) {
      picker?.close();
      automatic?.close();
      return;
    }
    if (!state.asset.image) {
      // processed products only: nothing to view or pick
      setViewerMessage(
        "This asset holds processed products only; there is no raw radar to view or pick. " +
        "Its products are listed in the Dataset Explorer panel."
      );
      if (state.mode === "automatic") {
        automatic?.open(state.asset, { api, onChange: onAutomaticChange });
      } else {
        automatic?.close();
      }
      return;
    }
    if (state.mode === "manual" && picker) {
      automatic?.close();
      $("fl-radar-viewer").hidden = true;
      $("fl-radar-empty").hidden = true;
      const focusSlider = state.pendingFocus ?? null;
      state.pendingFocus = null;
      picker.open(state.asset, { api, onChange: renderPanel, focusSlider });
    } else if (state.mode === "automatic") {
      picker?.close();
      automatic?.open(state.asset, { api, onChange: onAutomaticChange });
      showViewer(true);
      loadOverview();
      scheduleRender(0);
    }
  }


  function onAutomaticChange(change) {
    if (change?.productsChanged) {
      window.FrozenLegaciesProducts?.reload();
    }
  }


  function renderModeNote() {
    // Manual mode is the ASTRA picker (astra_picker.js); Automatic mode is
    // URSA (automatic.js). The note line is used only for workspace messages.
    const note = $("fl-radar-mode-note");
    if (note) {
      note.hidden = true;
      note.innerHTML = "";
    }
  }


  /* ----------------------------------------------------------
   * Assets and shared sources
   * ---------------------------------------------------------- */

  async function refreshLibrary() {
    const [sources, assets] = await Promise.all([
      api("/radar/sources"),
      api("/assets")
    ]);
    state.sources = sources.sources || [];
    state.assets = assets.assets || [];
    renderAssetSelect();
    renderPanel();
  }


  function assetLabel(asset) {
    const origin = { shared: "Shared", upload: "Uploaded", products: "Products" }[asset.origin] || asset.origin;
    const flight = asset.flight ? `F${asset.flight} · ` : "";
    return `${asset.title || asset.filename} — ${flight}${origin}`;
  }


  function renderAssetSelect() {
    const select = $("fl-radar-asset");
    if (!select) {
      return;
    }
    const openedKeys = new Set(
      state.assets
        .filter(a => a.origin === "shared")
        .map(a => a.shared_source)
    );
    const unopened = state.sources.filter(s => !openedKeys.has(s.key));

    let html = `<option value="">Choose a radar asset…</option>`;
    if (state.assets.length) {
      html += `<optgroup label="My radar assets">`;
      for (const asset of state.assets) {
        html += `<option value="asset:${escapeHtml(asset.asset_id)}"
          ${asset.available ? "" : "disabled"}>${escapeHtml(assetLabel(asset))}</option>`;
      }
      html += `</optgroup>`;
    }
    if (unopened.length) {
      html += `<optgroup label="Shared radar">`;
      for (const source of unopened) {
        html += `<option value="source:${escapeHtml(source.key)}">${escapeHtml(source.title)}${
          source.status === "development" ? " (development)" : ""}</option>`;
      }
      html += `</optgroup>`;
    }
    select.innerHTML = html;
    select.value = state.asset ? `asset:${state.asset.asset_id}` : "";
  }


  async function openSharedSource(key) {
    const asset = await api("/assets/shared", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: key })
    });
    await refreshLibrary();
    await openAsset(asset.asset_id);
  }


  async function openAsset(assetId, { focusSlider = null } = {}) {
    state.pendingFocus = focusSlider;
    setViewerMessage("Opening radar asset…");
    const detail = await api(`/assets/${encodeURIComponent(assetId)}`);
    state.asset = detail;
    // fit the strip's full height into the space the viewer can use in the
    // workspace (the frame itself follows the image, not the reverse)
    const workspace = $("fl-radar-workspace");
    const height = Math.max(200, (workspace?.clientHeight || 640) - 260);
    state.scale = detail.image ? G.fitScale(detail.image.height, height) : 1;
    state.x = 0;
    renderAssetSelect();
    syncWorkspace();
    window.FrozenLegaciesProducts?.open(detail);
    renderPanel();
    syncUrl({ push: true });
  }


  async function closeAsset() {
    state.asset = null;
    window.FrozenLegaciesAstra?.close();
    window.FrozenLegaciesAutomatic?.close();
    window.FrozenLegaciesProducts?.clear();
    setViewerMessage("Choose a radar asset above, or upload raw radar or a processed product.");
    syncUrl({ push: true });
    await refreshLibrary();
  }


  async function onAssetSelected(event) {
    const value = event.target.value || "";
    try {
      if (value.startsWith("asset:")) {
        await openAsset(value.slice(6));
      } else if (value.startsWith("source:")) {
        await openSharedSource(value.slice(7));
      }
    } catch (error) {
      setViewerMessage(errorMessage(error));
    }
  }


  /* ----------------------------------------------------------
   * Upload
   * ---------------------------------------------------------- */

  function bindUpload() {
    const toggle = $("fl-radar-upload-toggle");
    const form = $("fl-radar-upload");
    const status = $("fl-radar-upload-status");

    toggle.addEventListener("click", () => {
      form.hidden = !form.hidden;
      const products = $("fl-product-upload");
      if (products) {
        products.hidden = true;
      }
    });

    form.addEventListener("submit", event => {
      event.preventDefault();
      const data = new FormData(form);
      const tiff = data.get("tiff");
      if (!tiff || !tiff.name) {
        status.textContent = "Choose a radar TIFF first.";
        return;
      }

      const request = new XMLHttpRequest();
      request.open("POST", `${API}/assets/upload`);
      request.withCredentials = true;
      request.responseType = "json";
      request.setRequestHeader("Accept", "application/json");

      request.upload.addEventListener("progress", e => {
        if (e.lengthComputable) {
          status.textContent = `Uploading… ${Math.round((100 * e.loaded) / e.total)}%`;
        }
      });
      request.upload.addEventListener("load", () => {
        status.textContent = "Validating radar TIFF…";
      });
      request.addEventListener("error", () => {
        status.textContent = "Upload failed. Check your connection and try again.";
      });
      request.addEventListener("load", async () => {
        if (request.status === 401) {
          status.textContent = errorMessage(new SessionEnded());
          return;
        }
        if (request.status !== 201) {
          status.textContent =
            request.response?.error ||
            (request.status === 413
              ? "The file is larger than the upload limit."
              : `Upload failed (HTTP ${request.status}).`);
          return;
        }
        status.textContent = "Uploaded.";
        form.reset();
        form.hidden = true;
        try {
          await refreshLibrary();
          await openAsset(request.response.asset_id);
        } catch (error) {
          status.textContent = errorMessage(error);
        }
      });

      status.textContent = "Uploading…";
      request.send(data);
    });
  }


  /* ----------------------------------------------------------
   * Viewer
   * ---------------------------------------------------------- */

  function showViewer(visible) {
    $("fl-radar-viewer").hidden = !visible;
    $("fl-radar-empty").hidden = visible;
  }


  function setViewerMessage(message) {
    window.FrozenLegaciesAstra?.close();
    showViewer(false);
    $("fl-radar-empty").innerHTML = `
      <div class="fl-empty-icon">◫</div>
      <div><strong>Radar workspace</strong><span>${escapeHtml(message)}</span></div>`;
  }


  function viewGeometry() {
    const asset = state.asset;
    const frame = $("fl-radar-image-frame");
    const viewWidth = Math.max(100, (frame?.clientWidth || 800) - 2);
    const scale = G.clampScale(state.scale, viewWidth, asset.image.height);
    const width = G.windowWidth(viewWidth, scale, asset.image.width);
    const x = G.clampX(state.x, width, asset.image.width);
    return { scale, width, x, viewWidth };
  }


  function loadOverview() {
    const asset = state.asset;
    const img = $("fl-radar-overview-img");
    const scale = G.overviewScale(asset.image.width, 1600);
    img.src = G.viewUrl(asset.asset_id, 0, asset.image.width, scale);
  }


  function scheduleRender(delay = 120) {
    window.clearTimeout(state.renderTimer);
    state.renderTimer = window.setTimeout(renderView, delay);
  }


  function renderView() {
    // the radar viewer is the Automatic-mode view; Manual uses the picker
    if (state.mode !== "automatic" || !state.asset) {
      return;
    }
    const asset = state.asset;
    const { scale, width, x } = viewGeometry();
    state.scale = scale;
    state.x = x;

    const img = $("fl-radar-image");
    const frame = $("fl-radar-image-frame");
    frame.classList.add("loading");
    img.onload = () => frame.classList.remove("loading");
    img.onerror = () => {
      frame.classList.remove("loading");
      $("fl-radar-readout").textContent =
        "This radar window could not be loaded. Reload the page if your session has ended.";
    };
    img.style.width = `${Math.ceil(width / scale)}px`;
    img.style.height = `${Math.ceil(asset.image.height / scale)}px`;
    img.src = G.viewUrl(asset.asset_id, x, width, scale);

    const slider = $("fl-radar-position");
    slider.max = String(Math.max(0, asset.image.width - width));
    slider.value = String(x);
    slider.disabled = asset.image.width <= width;

    const box = $("fl-radar-overview-window");
    box.style.left = `${(100 * x) / asset.image.width}%`;
    box.style.width = `${Math.max(0.4, (100 * width) / asset.image.width)}%`;

    $("fl-radar-scale").textContent = `1:${scale}`;
    $("fl-radar-zoom-in").disabled =
      scale <= G.minScale(viewGeometry().viewWidth, asset.image.height);
    $("fl-radar-zoom-out").disabled = scale >= G.SCALES[G.SCALES.length - 1];

    renderReadout({ x, width, scale });
  }


  function renderReadout({ x, width, scale }) {
    const asset = state.asset;
    const centre = x + Math.floor(width / 2);
    const cbd = G.estimateViewCbd(centre, asset.image.width, asset.cbd_start, asset.cbd_end);
    const nav = G.navForCbd(asset.nav_rows, cbd);

    let text =
      `Columns ${formatInt(x)}–${formatInt(x + width)} of ${formatInt(asset.image.width)}` +
      ` · 1 screen px = ${scale} source px`;
    if (cbd !== null) {
      text += ` · Estimated CBD ≈ ${cbd} (visual estimate from the filename range)`;
      if (nav) {
        text +=
          ` · Navigation at CBD ${cbd}: ` +
          `${formatCoord(nav.lat, "N", "S")}, ${formatCoord(nav.lon, "E", "W")}`;
      } else if (asset.nav?.present) {
        text += ` · No navigation record for CBD ${cbd}`;
      }
    }
    $("fl-radar-readout").textContent = text;
  }


  function bindViewer() {
    $("fl-radar-asset").addEventListener("change", onAssetSelected);

    $("fl-radar-position").addEventListener("input", event => {
      state.x = Number(event.target.value) || 0;
      scheduleRender();
    });

    document.querySelectorAll("[data-radar-step]").forEach(button => {
      button.addEventListener("click", () => {
        if (!state.asset) {
          return;
        }
        const { x, width } = viewGeometry();
        state.x = G.shiftX(x, Number(button.dataset.radarStep), width, state.asset.image.width);
        scheduleRender(0);
      });
    });

    const zoom = direction => {
      if (!state.asset) {
        return;
      }
      const before = viewGeometry();
      const scale = G.clampScale(
        G.nextScale(before.scale, direction), before.viewWidth, state.asset.image.height
      );
      const width = G.windowWidth(before.viewWidth, scale, state.asset.image.width);
      state.x = G.zoomAround(before.x, before.width, width, state.asset.image.width);
      state.scale = scale;
      scheduleRender(0);
    };
    $("fl-radar-zoom-in").addEventListener("click", () => zoom(-1));
    $("fl-radar-zoom-out").addEventListener("click", () => zoom(1));

    $("fl-radar-overview").addEventListener("click", event => {
      if (!state.asset) {
        return;
      }
      const rect = event.currentTarget.getBoundingClientRect();
      const fraction = (event.clientX - rect.left) / Math.max(1, rect.width);
      const { width } = viewGeometry();
      state.x = G.clampX(
        fraction * state.asset.image.width - width / 2, width, state.asset.image.width
      );
      scheduleRender(0);
    });

    $("fl-radar-image-frame").addEventListener("keydown", event => {
      if (!state.asset || !["ArrowLeft", "ArrowRight"].includes(event.key)) {
        return;
      }
      event.preventDefault();
      const { x, width } = viewGeometry();
      const step = (event.key === "ArrowLeft" ? -1 : 1) * (event.shiftKey ? 1 : 0.1);
      state.x = G.shiftX(x, step, width, state.asset.image.width);
      scheduleRender(0);
    });

    window.addEventListener("resize", () => scheduleRender(200));
  }


  /* ----------------------------------------------------------
   * Right-hand panel: raw radar for the selection / open asset
   * ---------------------------------------------------------- */

  function currentSelection(properties) {
    const ui = state.ui;
    const flight = properties?.flight ?? (
      ui?.state?.flightNumber && ui.state.flightNumber !== "all"
        ? ui.state.flightNumber
        : null
    );
    const datasetId = properties?.dataset_id ?? (
      ui?.state?.datasetId && ui.state.datasetId !== "all" ? ui.state.datasetId : null
    );
    if (flight === null && !properties) {
      return null;
    }
    return {
      datasetId,
      flight,
      tiff: properties?.tiff ?? null,
      observationId: properties?.observation_id ?? null
    };
  }


  function renderPanel() {
    const panel = $("fl-radar-panel");
    if (!panel) {
      return;
    }

    const sections = [];
    const asset = state.asset;

    if (asset && state.mode === "manual" && window.FrozenLegaciesAstra) {
      sections.push(window.FrozenLegaciesAstra.panelHtml());
    }

    if (asset && state.mode !== "map" && !asset.image) {
      sections.push(`
        <div class="fl-record-section">
          <div class="fl-record-section-title">Open asset</div>
          <div class="fl-record-grid">
            <div class="fl-record-item"><span>Asset</span><strong>${escapeHtml(asset.title)}</strong></div>
            <div class="fl-record-item"><span>Source</span><strong>Processed products (no raw radar)</strong></div>
          </div>
        </div>`);
    } else if (asset && state.mode !== "map") {
      const nav = asset.nav || {};
      sections.push(`
        <div class="fl-record-section">
          <div class="fl-record-section-title">Open radar asset</div>
          <div class="fl-record-grid">
            <div class="fl-record-item"><span>Asset</span><strong>${escapeHtml(asset.title || asset.filename)}</strong></div>
            <div class="fl-record-item"><span>Source</span><strong>${asset.origin === "shared" ? "Shared radar" : "My upload"}</strong></div>
            <div class="fl-record-item"><span>Dataset</span><strong>${escapeHtml(asset.dataset_id || "—")}</strong></div>
            <div class="fl-record-item"><span>Flight</span><strong>${escapeHtml(asset.flight ?? "—")}</strong></div>
            <div class="fl-record-item"><span>CBD range</span><strong>${escapeHtml(cbdRange(asset))}</strong></div>
            <div class="fl-record-item"><span>Image</span><strong>${formatInt(asset.image?.width)} × ${formatInt(asset.image?.height)} px</strong></div>
            <div class="fl-record-item"><span>Format</span><strong>${escapeHtml(asset.image?.mode)} · ${formatBytes(asset.image?.bytes)}</strong></div>
            <div class="fl-record-item"><span>Navigation</span><strong>${
              nav.present
                ? `${formatInt(nav.cbd_range_rows)} of ${formatInt(nav.cbd_range_size)} CBDs in range`
                : "not provided"
            }</strong></div>
            <div class="fl-record-item"><span>Thickness / surface</span><strong>${
              nav.present
                ? (nav.thk_available || nav.srf_available
                    ? `${formatInt(nav.thk_available)} / ${formatInt(nav.srf_available)} rows`
                    : "unavailable (9999)")
                : "—"
            }</strong></div>
          </div>
        </div>`);
    }

    if (asset && state.mode !== "map" && window.FrozenLegaciesProducts) {
      sections.push(window.FrozenLegaciesProducts.panelHtml());
    }

    if (state.mode === "map" && window.FrozenLegaciesUserLayer) {
      sections.push(window.FrozenLegaciesUserLayer.panelHtml());
    }
    if (state.mode === "map" && window.FrozenLegaciesReview) {
      sections.push(window.FrozenLegaciesReview.panelHtml());
    }
    if (state.mode === "map" && window.FrozenLegaciesPublishedLayer) {
      sections.push(window.FrozenLegaciesPublishedLayer.panelHtml());
    }
    if (state.mode === "map" && window.FrozenLegaciesCatalog) {
      sections.push(window.FrozenLegaciesCatalog.panelHtml());
    }

    const selection = state.selection;
    let body;
    if (!selection) {
      body = `<p class="fl-radar-panel-note">Select a flight or observation to find its raw radar imagery, or open the radar workspace with <strong>Manual</strong>.</p>`;
    } else {
      const matches = G.matchSources(state.sources, selection);
      if (matches.length) {
        body = matches.map(source => `
          <div class="fl-radar-link">
            <div><strong>${escapeHtml(source.title)}</strong>
              <span>${escapeHtml(source.filename)}</span></div>
            <button type="button" class="fl-radar-button primary"
              data-open-source="${escapeHtml(source.key)}">Open radar</button>
          </div>`).join("");
      } else {
        const what = selection.observationId ? "this observation" : `flight ${escapeHtml(selection.flight)}`;
        const dataset = datasetFor(selection.datasetId);
        body = dataset && dataset.capabilities && dataset.capabilities.raw_radar === false
          ? `<p class="fl-radar-panel-note">${escapeHtml(dataset.title)} does not provide raw radar imagery.</p>`
          : `<p class="fl-radar-panel-note">No raw radar imagery is available for ${what} in this installation.</p>`;
      }
      body += datasetDownloads(selection.datasetId);
    }
    sections.push(`
      <div class="fl-record-section">
        <div class="fl-record-section-title">Raw radar</div>
        ${body}
      </div>`);

    panel.innerHTML = sections.join("");
    window.FrozenLegaciesProducts?.bindPanel(panel);
    window.FrozenLegaciesUserLayer?.bindPanel(panel, {
      openAsset: async (assetId, focusSlider) => {
        setMode("manual");
        await openAsset(assetId, { focusSlider });
      }
    });
    window.FrozenLegaciesCatalog?.bindPanel(panel);
    window.FrozenLegaciesReview?.bindPanel(panel, {
      openAsset: async assetId => {
        setMode("manual");
        await openAsset(assetId);
      }
    });
    window.FrozenLegaciesPublishedLayer?.bindPanel(panel);
    makeCollapsible(panel);
    panel.querySelectorAll("[data-open-source]").forEach(button => {
      button.addEventListener("click", async () => {
        try {
          setMode("manual");
          await openSharedSource(button.dataset.openSource);
        } catch (error) {
          setViewerMessage(errorMessage(error));
        }
      });
    });
  }


  /* Dataset capabilities from the catalog (dataset manifests). */
  function datasetFor(datasetId) {
    if (!datasetId) {
      return null;
    }
    return (state.catalog?.datasets || []).find(d => d.id === datasetId) || null;
  }


  function datasetDownloads(datasetId) {
    const dataset = datasetFor(datasetId);
    if (!dataset || !dataset.capabilities?.downloads) {
      return "";
    }
    const flags = dataset.build?.downloads || {};
    const links = [
      ["observations_geojson", "Observations (GeoJSON)"],
      ["flights_geojson", "Flight tracks (GeoJSON)"]
    ].filter(([kind]) => flags[kind]).map(([kind, label]) =>
      `<a class="fl-radar-button" href="/frozen-legacies/api/datasets/${encodeURIComponent(dataset.id)}/downloads/${kind}" download>${escapeHtml(label)}</a>`);
    return links.length
      ? `<div class="fl-record-section-title fl-dataset-downloads-title">Dataset downloads</div><div class="fl-astra-downloads">${links.join("")}</div>`
      : "";
  }


  function bindSelection() {
    document.addEventListener("frozen-legacies:observation", event => {
      const properties = event.detail?.properties || null;
      // Read the explorer state after the current selection handler finishes.
      window.setTimeout(() => {
        state.selection = currentSelection(properties);
        renderPanel();
        syncUrl({ push: true });
      }, 0);
    });
    ["dataset-select", "flight-select"].forEach(id => {
      $(id)?.addEventListener("change", () => {
        window.setTimeout(() => {
          state.selection = currentSelection(null);
          renderPanel();
          syncUrl({ push: true });
        }, 0);
      });
    });
  }


  /* ----------------------------------------------------------
   * Entry point
   * ---------------------------------------------------------- */

  async function initialize({ map, ui, data }) {
    state.map = map;
    state.ui = ui;
    state.catalog = data?.catalog || null;

    window.FrozenLegaciesProducts?.configure({
      api,
      onChange: renderPanel,
      onAssetCreated: async assetId => {
        await refreshLibrary();
        await openAsset(assetId);
      },
      onAssetRemoved: closeAsset
    });

    document.querySelectorAll(".fl-mode-button").forEach(button => {
      button.addEventListener("click", () => setMode(button.dataset.mode));
    });
    $("fl-explorer-section")?.addEventListener("toggle", event => {
      if (state.mode !== "map") {
        state.explorerFolded = !event.target.open;
      } else if (!event.target.open) {
        event.target.open = true;          // the explorer is always open in Map
      }
    });

    state.layout = loadLayout();
    bindLayout();
    bindUpload();
    bindViewer();
    bindSelection();
    setViewerMessage("Choose a radar asset above, or upload raw radar or a processed product.");
    renderPanel();

    window.FrozenLegaciesUserLayer?.initialize({ map, onChange: renderPanel });
    window.FrozenLegaciesPublishedLayer?.initialize({ map, onChange: renderPanel });
    window.FrozenLegaciesReview?.initialize({ onChange: renderPanel });
    window.FrozenLegaciesCatalog?.initializeMap({ map, onChange: renderPanel,
                                                onSelection: () => syncUrl({ push: true }) });
    window.FrozenLegaciesCatalog?.initialize({
      open: async key => {
        if (state.mode === "map") {
          setMode("manual");
        }
        await openSharedSource(key);
      }
    });

    try {
      await refreshLibrary();
    } catch (error) {
      setViewerMessage(errorMessage(error));
    }

    // deep link (for example from the Control Center review page):
    // /frozen-legacies/?open=<catalog ID> opens that radar in Manual;
    // otherwise the URL hash restores the mode, open asset and map view
    const initial = readUrlState();
    const query = new URLSearchParams(window.location.search);
    const deepLink = query.get("open");
    state.urlReady = true;
    bindUrlState();
    if (deepLink && /^cat-[0-9a-f]{24}$/.test(deepLink)) {
      state.applyingUrl = true;
      try {
        if (initial.view) {
          await applyUrlState({ mode: state.mode, asset: null, view: initial.view });
          state.applyingUrl = true;
        }
        setMode("manual");
        await openSharedSource(deepLink);
      } catch (error) {
        setViewerMessage(errorMessage(error));
      } finally {
        state.applyingUrl = false;
      }
      // the link has been followed: keep the state in the hash only
      query.delete("open");
      const search = query.toString();
      try {
        window.history.replaceState(null, "",
          `${window.location.pathname}${search ? `?${search}` : ""}${urlHash()}`);
      } catch (error) {
        // history unavailable
      }
    } else if (initial.mode !== "map" || initial.asset || initial.view || initial.dataset
               || initial.coverage) {
      await applyUrlState(initial);
    } else {
      syncUrl();
    }
  }


  window.FrozenLegaciesRadar = {
    initialize,
    setMode,
    openSharedSource,
    get state() {
      return state;
    }
  };

})();
