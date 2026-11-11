/* ============================================================
 * Frozen Legacies · map_explorer.js
 *
 * Map presentation helpers (2026-11-10):
 *  - inspection facts for the selected record ("not supplied" when absent;
 *    no inferred values; an engine/processing alias is never a flight),
 *  - one compact "Layers" disclosure: it mounts the controls that
 *    map_visibility.js already owns (Data), then My work / Reviewed
 *    (proxies of the existing toggles, no second state), Reference layers,
 *    an External sources list (links only), plus a persistent original map key,
 *  - "Save selection": a reproducible JSON manifest of exactly the selected
 *    and loaded records in this browser view (never all catalogue results).
 *
 * NASA GIBS static imagery is the default background; an explicit browser
 * session choice can turn it off to show the vector map. No scientific
 * values are created anywhere in this module.
 * ============================================================ */
(function (root) {
  "use strict";

  const NOT_SUPPLIED = "not supplied";
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c =>
    ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const present = value => value !== null && value !== undefined && value !== "" &&
    !(typeof value === "number" && !Number.isFinite(value));
  const show = value => (present(value) ? String(value) : NOT_SUPPLIED);

  /* Units of the supplied quantities, exactly as named in the source data. */
  const UNITS = Object.freeze({
    h_ice_m: "m", h_ice_firn_corrected_m: "m", thickness_base_m: "m", firn_correction_values_m: "m",
    bed_snr_dB: "dB", R0_dB: "dB", L_atten_dB: "dB", T_surface_C: "°C", specularity: "dimensionless",
    surface_twt_us: "µs", bed_twt_us: "µs", cbd: "CBD number (count)"
  });

  const QUANTITIES = [
    ["h_ice_m", "Ice thickness", 1], ["bed_snr_dB", "Bed SNR", 2], ["T_surface_C", "Surface temperature", 2],
    ["R0_dB", "Reflectivity", 2], ["L_atten_dB", "Attenuation", 2], ["specularity", "Specularity", 3]
  ];

  const SCOPE_LABEL = {a: "A-scope", z: "Z-scope", esm: "ESM"};

  /* Official provider pages only (2026-11-10 research). Links, not integrations. */
  const EXTERNAL_SOURCES = Object.freeze([
    {name: "NASA Earthdata Search", url: "https://search.earthdata.nasa.gov/",
     note: "NASA EOSDIS collections; data access may need a free Earthdata Login."},
    {name: "NSIDC · IceBridge MCoRDS L2 ice thickness (IRMCR2)", url: "https://nsidc.org/data/irmcr2/versions/1",
     note: "Airborne radar CSV; versioned DOI and citation required."},
    {name: "NSIDC · UTIG/ICECAP HiCARS (IR2HI2)", url: "https://nsidc.org/data/ir2hi2/versions/1",
     note: "Versioned DOI and citation; survey identity is distinct from processing IDs."},
    {name: "Open Polar Radar / CReSIS", url: "https://data.cresis.ku.edu/",
     note: "Radar products, KML flight lines; follow each product's citation and terms."},
    {name: "RadarFilm Studio", url: "https://www.radarfilm.studio/docs/start",
     note: "Film tracks, CBD segments and previews.", terms: "https://www.radarfilm.studio/docs/citation"},
    {name: "BAS Bedmap", url: "https://www.bas.ac.uk/project/bedmap/",
     note: "Bed, surface and thickness compilations; Bedmap3 grid is CC BY 4.0 with citation.",
     terms: "https://data.bas.ac.uk/full-record.php?id=GB%2FNERC%2FBAS%2FPDC%2F01615"},
    {name: "PGC REMA", url: "https://www.pgc.umn.edu/data/rema/",
     note: "Reference Elevation Model of Antarctica; acknowledgement policy applies.",
     terms: "https://www.pgc.umn.edu/guides/user-services/acknowledgement-policy/"},
    {name: "NASA GIBS (EPSG:3031 imagery)", url: "https://nasa-gibs.github.io/gibs-api-docs/access-basics/",
     note: "Rendered satellite imagery services; context only, never a measurement."},
    {name: "SCAR Composite Gazetteer of Antarctica", url: "https://placenames.aq/information/data-services",
     note: "Official Antarctic place names."},
    {name: "Quantarctica (NPI)", url: "https://sites.npolar.no/quantarctica/",
     note: "Source of this map's geographic context layers."}
  ]);

  /* ── optional NASA GIBS Antarctic imagery (verified 2026-11-10) ──
   * Official EPSG:3031 capabilities (GIBS "best" endpoint): layer
   * BlueMarble_ShadedRelief_Bathymetry "Blue Marble Shaded Relief and Bathymetry (MODIS)", style default, tile
   * matrix set 500m (5 levels, 8192..512 m/px, 512 px JPEG tiles, top-left
   * -4194304,4194304), no time dimension, Fees/AccessConstraints none,
   * Rendered context only, never a measurement or a geolocation.
   * Bathymetry pixels/current cache headers require live qualification. */
  const GIBS = Object.freeze({
    layer: "BlueMarble_ShadedRelief_Bathymetry",
    title: "Blue Marble Shaded Relief and Bathymetry (MODIS)",
    base: "https://gibs.earthdata.nasa.gov/wmts/epsg3031/best/BlueMarble_ShadedRelief_Bathymetry/default/500m",
    halfExtent: 4194304,
    resolutions: Object.freeze([8192, 4096, 2048, 1024, 512]),
    tileSize: 512,
    date: "Static mosaic (no date dimension in the GIBS capabilities)",
    provider: "NASA Global Imagery Browse Services (GIBS)",
    acknowledgement: "We acknowledge the use of imagery provided by services from NASA's Global Imagery Browse " +
      "Services (GIBS), part of NASA's Earth Science Data and Information System (ESDIS).",
    docs: "https://nasa-gibs.github.io/gibs-api-docs/",
    policy: "https://www.earthdata.nasa.gov/engage/open-data-services-software-policies",
    // Full tile opacity; presentation RGB is adjusted only on the NASA canvas.
    // Raw tiles/coordinates stay unchanged; vector boundaries/data render above.
    opacity: 1,
    domainRadius: 3400000, // existing polar display domain, not a coastline
    timeoutMs: 20000,
    cacheSize: 128
  });

  const GIBS_CONTEXT_CLASS = "fl-nasa-context";
  // Match #frozen-legacies-map and polarOceanStyle. Ocean-anchored gamma in sRGB:
  // out = base + (1 - base) * in^1.5. No backdrop sampling or alpha adjustment.
  const GIBS_OCEAN_RGB = Object.freeze([71, 127, 155]); // #477f9b
  let gibsPresentationId = 0;

  function gibsPresentation() {
    let canvas = null, svg = null, previousFilter = "", appliedFilter = "";
    const release = () => {
      // Restore only our own style; do not overwrite a later owner's changes.
      if (canvas?.style.filter === appliedFilter) canvas.style.filter = previousFilter;
      svg?.remove();
      canvas = svg = null;
    };
    return candidate => {
      const host = candidate?.parentElement;
      // OL 10.6.1 reuses canvases only for matching layer className. Also verify
      // the actual render target: never style the map, a shared canvas or globe.
      const isolated = candidate?.tagName === "CANVAS" && candidate.style &&
        host?.className === GIBS_CONTEXT_CLASS && host.firstElementChild === candidate &&
        host.querySelectorAll("canvas").length === 1;
      if (!isolated) { release(); return; }
      if (canvas === candidate && svg?.parentElement === host) return;
      release();
      const doc = candidate.ownerDocument;
      if (!doc?.createElementNS || !root.SVGFEComponentTransferElement ||
          !root.CSS?.supports?.("filter", 'url("#fl-nasa-presentation")')) return;
      try {
        const ns = "http://www.w3.org/2000/svg";
        const node = (tag, attributes) => {
          const el = doc.createElementNS(ns, tag);
          for (const [key, value] of Object.entries(attributes)) el.setAttribute(key, String(value));
          return el;
        };
        // Definition lives with this renderer container, not in the document
        // head/body. Renderer removal also removes it; replacement releases it.
        const id = `fl-nasa-ocean-${++gibsPresentationId}`;
        svg = node("svg", {class: "fl-nasa-presentation-defs", width: 0, height: 0,
          "aria-hidden": "true", focusable: "false"});
        const defs = node("defs", {});
        const filter = node("filter", {id, x: "0%", y: "0%", width: "100%", height: "100%",
          "color-interpolation-filters": "sRGB"});
        const transfer = node("feComponentTransfer", {in: "SourceGraphic",
          "color-interpolation-filters": "sRGB"});
        GIBS_OCEAN_RGB.forEach((channel, i) => transfer.append(node(`feFunc${"RGB"[i]}`,
          {type: "gamma", amplitude: 1 - channel / 255, exponent: 1.5, offset: channel / 255})));
        transfer.append(node("feFuncA", {type: "identity"}));
        filter.append(transfer); defs.append(filter); svg.append(defs); host.append(svg);
        canvas = candidate;
        previousFilter = canvas.style.filter;
        appliedFilter = `url("#${id}")`;
        canvas.style.filter = appliedFilter;
      } catch (_) {
        // Unsupported/blocked SVG setup must not prevent ordinary tile rendering.
        release();
      }
    };
  }

  // OpenLayers tile coordinate [z, x, y] (y downward from the top-left
  // origin) → the documented REST template .../{TileMatrix}/{TileRow}/{TileCol}.jpeg
  function gibsTileUrl(coord) {
    const [z, x, y] = Array.isArray(coord) ? coord : [];
    if (!Number.isInteger(z) || z < 0 || z >= GIBS.resolutions.length) return undefined;
    const n = 2 ** (z + 1);
    if (!Number.isInteger(x) || !Number.isInteger(y) || x < 0 || y < 0 || x >= n || y >= n) return undefined;
    // Skip tiles wholly outside the display disc, retaining the native WMTS grid.
    const span = GIBS.resolutions[z] * GIBS.tileSize;
    const left = -GIBS.halfExtent + x * span, top = GIBS.halfExtent - y * span;
    const dx = Math.max(left, 0, -(left + span));
    const dy = Math.max(top - span, 0, -top);
    if (dx * dx + dy * dy >= GIBS.domainRadius ** 2) return undefined;
    return `${GIBS.base}/${z}/${y}/${x}.jpeg`;
  }

  // Tiles are requested without a referrer: only z/x/y reach NASA, never the
  // page address, filters, selections or file names.
  function gibsLoadTile(tile, src) {
    const image = tile.getImage();
    image.referrerPolicy = "no-referrer";
    // A hung provider request must release the tile queue and expose Retry.
    if (image.addEventListener && root.setTimeout) {
      const cleanup = () => {
        root.clearTimeout(timer);
        image.removeEventListener("load", cleanup);
        image.removeEventListener("error", cleanup);
        tile.removeEventListener?.("change", terminal);
      };
      // A discarded tile reaches EMPTY without a source load-end/error event.
      const terminal = () => {
        if (tile.getState?.() >= 2) cleanup();
      };
      const timer = root.setTimeout(() => {
        cleanup();
        image.src = "";
        tile.setState(3); // OpenLayers TileState.ERROR; ImageTile.load() can retry it.
      }, GIBS.timeoutMs);
      image.addEventListener("load", cleanup);
      image.addEventListener("error", cleanup);
      tile.addEventListener?.("change", terminal);
    }
    image.src = src;
  }

  // Clip this layer's own canvas, in render pixels (including DPR/rotation).
  // This is the existing presentation domain; it does not modify geography.
  function clipGibsDomain(layer) {
    const presentGibs = gibsPresentation();
    const transform = (m, p) => [m[0] * p[0] + m[2] * p[1] + m[4],
                                m[1] * p[0] + m[3] * p[1] + m[5]];
    layer.on?.("prerender", event => {
      const {context, frameState, inversePixelTransform} = event;
      presentGibs(context.canvas);
      const pixel = p => transform(inversePixelTransform, transform(frameState.coordinateToPixelTransform, p));
      const center = pixel([0, 0]), edge = pixel([GIBS.domainRadius, 0]);
      context.save();
      context.beginPath();
      context.arc(center[0], center[1], Math.hypot(edge[0] - center[0], edge[1] - center[1]), 0, 2 * Math.PI);
      context.clip();
    });
    layer.on?.("postrender", event => event.context.restore());
    return layer;
  }

  function createGibsLayer(ol, projection) {
    const e = GIBS.halfExtent;
    const tileGrid = new ol.tilegrid.TileGrid({extent: [-e, -e, e, e], origin: [-e, e],
      resolutions: [...GIBS.resolutions], tileSize: GIBS.tileSize});
    const source = new ol.source.TileImage({projection, tileGrid, crossOrigin: "anonymous", wrapX: false,
      tileUrlFunction: gibsTileUrl, tileLoadFunction: gibsLoadTile,
      attributions: "Imagery: NASA GIBS · Blue Marble Shaded Relief and Bathymetry (MODIS)"});
    const r = GIBS.domainRadius;
    return clipGibsDomain(new ol.layer.Tile({source, opacity: GIBS.opacity, visible: true,
      className: GIBS_CONTEXT_CLASS, extent: [-r, -r, r, r],
      preload: 1, cacheSize: GIBS.cacheSize,
      properties: {id: "nasa-gibs-blue-marble", label: "NASA Blue Marble bathymetry (GIBS)"}}));
  }

  /* ── inspection card facts ─────────────────────────────────── */
  function scopeOf(properties, scopeForDataset) {
    const own = String(properties?.scope || "").toLowerCase();
    if (SCOPE_LABEL[own]) return own;
    const derived = typeof scopeForDataset === "function" ? scopeForDataset(properties?.dataset_id) : null;
    return SCOPE_LABEL[derived] ? derived : null;
  }

  function reviewState(dataset) {
    const status = dataset?.metadata?.scientific_status;
    if (status === "supplied-unverified") return "Supplied dataset record · scientifically unvalidated";
    if (present(status)) return `Supplied dataset record · ${status}`;
    return "Supplied dataset record · review status not supplied";
  }

  /**
   * Concise facts for the selected record. `position` is [lon, lat] of the
   * drawn point or null. Flight is ONLY the record's own `flight` field;
   * processing/engine aliases (engine_flight, engine_alias, tiff names) are
   * never consulted.
   */
  function inspection(properties = {}, {dataset = null, position = null, scopeForDataset = null} = {}) {
    const scope = scopeOf(properties, scopeForDataset);
    const echo = properties.echo_status;
    const qc = present(echo) && !["not-supplied", "unknown"].includes(echo) ? String(echo) : NOT_SUPPLIED;
    const hasPosition = Array.isArray(position) && position.length === 2 && position.every(Number.isFinite);
    return [
      ["Collection", dataset?.title || dataset?.name || show(properties.dataset_id)],
      ["Flight", show(properties.flight)],
      ["CBD", show(properties.cbd)],
      ["Image type", scope ? SCOPE_LABEL[scope] : NOT_SUPPLIED],
      ["Position", hasPosition ? `${position[1].toFixed(4)}°, ${position[0].toFixed(4)}°` : "no navigation position"],
      ["Navigation", hasPosition ? (properties.navigation_provenance || "coordinates as supplied (not harmonized across workflows)") : "not placed on the map"],
      ["Source QC", qc],
      ["Review / owner", reviewState(dataset)]
    ];
  }

  function suppliedQuantities(properties = {}) {
    return QUANTITIES.filter(([key]) => present(properties[key]) && Number.isFinite(Number(properties[key])))
      .map(([key, label, digits]) => ({key, label, unit: UNITS[key], value: Number(properties[key]).toFixed(digits)}));
  }

  /* Folded source/version/citation/terms details. */
  function sourceRows(properties = {}, dataset = null) {
    const meta = dataset?.metadata || {};
    return [
      ["Dataset ID", show(properties.dataset_id)],
      ["Dataset version", show(meta.version)],
      ["DOI", show(meta.doi)],
      ["Citation", show(meta.citation)],
      ["Licence / terms", show(meta.license || meta.licence || meta.terms)],
      ["Coordinate system", show(meta.coordinate_system)],
      ["Source file", show(properties._source_file ?? properties.source_file)],
      ["Source row", show(properties.source_row)],
      ["Frame", show(properties.frame_idx)],
      ["Source SHA-256", show(properties.source_sha256)]
    ];
  }

  /* ── Save selection manifest ───────────────────────────────── */
  const RECORD_KEYS = ["observation_id", "dataset_id", "flight", "cbd", "frame_idx", "file_id", "workflow",
    "echo_status", "scope", "source_row", "source_sha256", "thickness_field", "firn_correction_applied",
    "scientific_status", ...Object.keys(UNITS).filter(k => k !== "cbd")];
  const LOCAL_LINK = /^(?:\/frozen-legacies\/|downloads\/)[A-Za-z0-9._\/-]+$/;

  function manifestRecord(properties = {}, {id, position = null} = {}) {
    const record = {id: present(id) ? String(id) : null};
    for (const key of RECORD_KEYS) {
      if (present(properties[key]) && typeof properties[key] !== "object") record[key] = properties[key];
    }
    if (present(properties._source_file)) record.source_file = properties._source_file;
    if (Array.isArray(position) && position.length === 2 && position.every(Number.isFinite)) {
      record.position = {longitude: Number(position[0].toFixed(7)), latitude: Number(position[1].toFixed(7))};
    }
    const products = (Array.isArray(properties.products) ? properties.products : [])
      .filter(p => p && typeof p === "object")
      .map(p => ({id: present(p.id) ? String(p.id) : null, title: present(p.title) ? String(p.title) : null,
                  type: present(p.type) ? String(p.type) : null,
                  ...(typeof p.url === "string" && LOCAL_LINK.test(p.url) ? {link: p.url} : {})}));
    if (products.length) record.products = products;
    return record;
  }

  /**
   * selected: {id, properties, position} | null
   * loaded:   [{id, properties, position}] — records loaded in this view that
   *           match the active filters and visible layers.
   */
  function manifest({selected = null, loaded = [], query = {}, canonicalQuery = "", catalog = null,
                     now = new Date(), limit = 5000} = {}) {
    const records = loaded.slice(0, limit).map(r => manifestRecord(r.properties, r));
    const referenced = new Set([selected?.properties?.dataset_id, ...loaded.map(r => r.properties?.dataset_id)].filter(present));
    const datasets = (catalog?.datasets || []).filter(d => referenced.has(d.id)).map(d => {
      const meta = d.metadata || {};
      const value = v => (present(v) ? v : null);
      return {id: d.id, title: value(d.title), institution: value(d.institution), campaign: value(d.campaign),
              version: value(meta.version), doi: value(meta.doi), citation: value(meta.citation),
              license: value(meta.license || meta.licence || meta.terms), coordinate_system: value(meta.coordinate_system),
              scientific_status: value(meta.scientific_status), product_family: value(meta.product_family)};
    });
    return {
      schema: "cryostack.frozen-legacies.selection-manifest.v1",
      created_at: now.toISOString(),
      scope: {
        description: "The selected record and the records loaded in this browser view that match the active filters " +
          "and visible layers. It is not every catalogue result, and hidden layers are excluded.",
        selected_record: Boolean(selected),
        loaded_records_matching: loaded.length,
        records_included: records.length,
        truncated: loaded.length > records.length
      },
      query: {canonical: String(canonicalQuery || ""), parameters: query},
      snapshot: {catalog_version: catalog?.version ?? null},
      coordinates: {
        values: "longitude/latitude in degrees from each drawn map feature (the dataset's supplied coordinates, " +
          "reprojected for display and back; rounded to 7 decimals). Not a navigation correction.",
        map_display: "EPSG:3031 (display only)"
      },
      units: UNITS,
      review: "Supplied records keep their dataset review status; private work and reviewed results are not included.",
      datasets,
      selected: selected ? manifestRecord(selected.properties, selected) : null,
      records,
      sources: EXTERNAL_SOURCES.filter(s => s.name.startsWith("Quantarctica"))
        .map(s => ({name: s.name, url: s.url, role: "map geography (display context)"}))
    };
  }

  function downloadManifest(content, documentRef = root.document) {
    const blob = new Blob([JSON.stringify(content, null, 2) + "\n"], {type: "application/json"});
    const url = URL.createObjectURL(blob);
    const link = documentRef.createElement("a");
    link.href = url;
    link.download = `frozen-legacies-selection-${content.created_at.replace(/[:.]/g, "-")}.json`;
    documentRef.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  /* ── Layers disclosure ─────────────────────────────────────── */
  // Legend entries shown only while the layer they describe is visible.
  const LEGEND_KEYS = [
    ["fl-key-flight", "kind:flights"], ["fl-key-selected", "kind:flights"],
    ["fl-key-good", "kind:observations"], ["fl-key-weak", "kind:observations"], ["fl-key-none", "kind:observations"],
    ["fl-key-basin", "layer:drainageBasins"], ["fl-key-shelf", "layer:drainageBasins"]
  ];
  const REFERENCE_LAYERS = [
    ["drainageBasins", "Drainage basins and ice shelves", "Quantarctica"],
    ["placeNames", "Place names", "Quantarctica"],
    ["polarReference", "Latitude reference rings", "60°S · 70°S · 80°S"]
  ];

  function legendVisible(item, enabled, layerVisible) {
    for (const [cls, key] of LEGEND_KEYS) {
      if (!item.querySelector?.(`.${cls}`)) continue;
      return key.startsWith("layer:") ? layerVisible(key.slice(6)) !== false : enabled(key) !== false;
    }
    return true;
  }

  function mountLayers({documentRef = root.document} = {}) {
    if (documentRef.getElementById("fl-map-data-controls")) return documentRef.getElementById("fl-map-data-controls");
    const legend = documentRef.querySelector(".fl-map-legend");
    const host = legend?.parentElement || documentRef.querySelector(".fl-map-shell");
    if (!host) return null;
    const details = documentRef.createElement("details");
    details.id = "fl-map-data-controls";
    details.className = "fl-map-data-controls fl-layers";
    details.innerHTML = `<summary aria-label="Map layers"><span>Layers</span><small data-map-visibility-count>All shown</small></summary>
      <div class="fl-map-data-controls-body" data-map-control-body></div>
      <p class="fl-layers-status" data-map-visibility-status role="status"></p>
      <div class="fl-map-data-controls-footer"><button type="button" data-map-show-all>Show all data</button></div>`;
    host.append(details);
    return details;
  }

  function finishLayers({map, layers, documentRef = root.document} = {}) {
    const details = documentRef.getElementById("fl-map-data-controls");
    const body = details?.querySelector("[data-map-control-body]");
    if (!body || body.dataset.layersExtended) return;
    body.dataset.layersExtended = "true";
    const group = (title, cls) => {
      const fieldset = documentRef.createElement("fieldset");
      fieldset.className = cls;
      const legend = documentRef.createElement("legend");
      legend.textContent = title;
      fieldset.append(legend);
      body.append(fieldset);
      return fieldset;
    };
    const row = (parent, label, note, checked, onChange) => {
      const wrapper = documentRef.createElement("label");
      wrapper.className = "fl-data-layer-row";
      const input = documentRef.createElement("input");
      input.type = "checkbox";
      input.checked = checked;
      input.addEventListener("change", () => onChange(input.checked));
      const text = documentRef.createElement("span");
      text.textContent = label;
      if (note) { const small = documentRef.createElement("small"); small.textContent = note; text.append(small); }
      wrapper.append(input, text);
      parent.append(wrapper);
      return {wrapper, input};
    };

    // My work / Reviewed: mirror the existing toggles (they keep the state).
    const work = group("My work & reviewed results", "fl-layers-work");
    const proxies = [["[data-my-picks]", "My work", "Your private results"],
                     ["[data-published]", "Reviewed results", "Published after review"]].map(([selector, label, note]) => {
      const item = row(work, label, note, false, checked => {
        const original = documentRef.querySelector(selector);
        if (!original || original.checked === checked) return;
        original.checked = checked;
        original.dispatchEvent(new Event("change", {bubbles: true}));
      });
      return {selector, ...item};
    });
    const workNote = documentRef.createElement("small");
    workNote.className = "fl-layers-note";
    workNote.textContent = "Shown when available for your account.";
    work.append(workNote);
    const syncWork = () => {
      let any = false;
      for (const proxy of proxies) {
        const original = documentRef.querySelector(proxy.selector);
        proxy.wrapper.hidden = !original;
        if (original) { proxy.input.checked = original.checked; any = true; }
      }
      workNote.hidden = any;
    };

    // Reference layers: the OpenLayers layer visibility is the only state.
    const reference = group("Reference", "fl-layers-reference");
    const layerRows = REFERENCE_LAYERS.map(([key, label, note]) => {
      const layer = layers?.layers?.[key];
      if (!layer) return null;
      return {layer, ...row(reference, label, note, layer.getVisible() !== false, checked => {
        layer.setVisible(checked);
        syncLegend();
      })};
    }).filter(Boolean);
    const imagery = mountGibs({map, layers, reference, row, documentRef});
    // Keep the original key and RIGGS control visible even with Layers closed.
    // Moving the existing nodes preserves their IDs, station listener and state.
    const riggs = documentRef.getElementById("fl-riggs-toggle-row");
    const riggsNote = documentRef.getElementById("fl-riggs-provenance");
    const legend = documentRef.querySelector(".fl-map-legend");
    if (legend) {
      legend.classList.remove("fl-legend-docked");
      legend.classList.add("fl-map-key");
      legend.removeAttribute("style");
      const title = legend.querySelector(".fl-map-legend-title > span");
      if (title) title.textContent = "Map key";
      legend.setAttribute("aria-label", "Map key and RIGGS reference stations");
      legend.setAttribute("tabindex", "0");
      details.parentElement?.append(legend);
      if (riggs && !legend.contains(riggs)) legend.append(riggs);
      if (riggsNote && !legend.contains(riggsNote)) legend.append(riggsNote);
    }
    const syncLegend = () => {
      const visibility = root.FrozenLegaciesMapVisibility;
      const enabled = key => visibility?.enabled ? visibility.enabled(key) : true;
      const layerVisible = key => layers?.layers?.[key]?.getVisible?.();
      legend?.querySelectorAll(".fl-map-legend-item").forEach(item => {
        if (item.id === "fl-riggs-toggle-row") return;
        item.hidden = !legendVisible(item, enabled, layerVisible);
      });
      layerRows.forEach(r => { r.input.checked = r.layer.getVisible() !== false; });
    };

    // External sources: links only.
    const external = documentRef.createElement("details");
    external.className = "fl-layers-external";
    external.innerHTML = `<summary>External sources</summary>
      <p class="fl-layers-note">Official provider pages for related Antarctic radar, elevation, imagery and place-name data.
      They are not loaded into this map; follow each provider's citation and terms.</p>
      <ul>${EXTERNAL_SOURCES.map(s => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.name)}</a>
        <small>${esc(s.note)}${s.terms ? ` <a href="${esc(s.terms)}" target="_blank" rel="noopener noreferrer">Terms / citation</a>` : ""}</small></li>`).join("")}</ul>`;
    body.append(external);

    details.addEventListener("toggle", () => { if (details.open) { syncWork(); syncLegend(); } });
    documentRef.addEventListener("fl-map-visibility-change", syncLegend);
    documentRef.addEventListener("fl-map-products-changed", syncWork);
    syncWork();
    syncLegend();
    return {syncWork, syncLegend, imagery};
  }

  const GIBS_VISIBILITY_KEY = "cryostack.frozen-legacies.nasa-gibs.v1";
  const imageryByMap = new WeakMap();

  // Called before the archive await. Nothing here waits for imagery or data.
  function prepareImagery({map, layers, documentRef = root.document} = {}) {
    if (imageryByMap.has(map)) return imageryByMap.get(map);
    const ol = root.ol;
    if (!map?.getLayers || !ol?.source?.TileImage || !ol?.tilegrid?.TileGrid || !ol?.layer?.Tile) return null;
    let enabled = true;
    try { enabled = root.sessionStorage?.getItem(GIBS_VISIBILITY_KEY) !== "false"; } catch (_) {}
    const state = {layer: null, loaded: 0, failed: 0, pending: 0, enabled, error: null};
    const pending = new Set(), failed = new Set(), observers = new Set();
    const watched = new Map();
    const unwatch = tile => {
      const listener = watched.get(tile);
      if (listener) tile.removeEventListener("change", listener);
      watched.delete(tile);
    };
    const watch = tile => {
      if (!tile.addEventListener || watched.has(tile)) return;
      const listener = () => {
        if (tile.getState?.() !== 4) return; // OpenLayers TileState.EMPTY
        pending.delete(tile); failed.delete(tile); unwatch(tile); report();
      };
      watched.set(tile, listener);
      tile.addEventListener("change", listener);
    };
    const report = () => {
      state.pending = pending.size;
      state.failed = failed.size;
      for (const observer of observers) observer(state);
    };
    const retry = () => {
      if (!state.enabled || pending.size) return;
      if (!state.layer) { apply(true); return; }
      // At most six explicit retries per click; never invalidate good tiles.
      for (const tile of [...failed].slice(0, 6)) tile.load();
    };
    const apply = checked => {
      const wasEnabled = state.enabled;
      state.enabled = checked;
      if (checked && !state.layer) {
        state.error = null;
        try {
          const layer = createGibsLayer(ol, map.getView?.().getProjection?.());
          const source = layer.getSource();
          source.on("tileloadstart", ({tile}) => { pending.add(tile); watch(tile); report(); });
          source.on("tileloadend", ({tile}) => {
            pending.delete(tile); failed.delete(tile); unwatch(tile); state.loaded++; report();
          });
          source.on("tileloaderror", ({tile}) => {
            pending.delete(tile); failed.add(tile); watch(tile);
            // Do not retain failed tile objects/listeners beyond the cache budget.
            if (failed.size > GIBS.cacheSize) {
              const oldest = failed.values().next().value;
              failed.delete(oldest); unwatch(oldest);
            }
            report();
          });
          const list = map.getLayers(), array = list.getArray?.() || [];
          const gridAt = array.indexOf(layers?.layers?.polarReference);
          const at = gridAt >= 0 ? gridAt : array.indexOf(layers?.layers?.scientificBasemap);
          list.insertAt(at >= 0 ? at : Math.min(1, array.length), layer);
          state.layer = layer;
        } catch (error) {
          state.error = "NASA imagery could not start. Vector context remains available.";
          root.console?.warn?.("[FrozenLegacies] NASA context initialization failed", error);
        }
      }
      state.layer?.setVisible(checked);
      if (checked && !wasEnabled) retry();
      report();
    };
    const controller = {state, retry, subscribe(fn) { observers.add(fn); fn(state); return () => observers.delete(fn); },
      setEnabled(checked) {
        try { root.sessionStorage?.setItem(GIBS_VISIBILITY_KEY, String(checked)); } catch (_) {}
        apply(checked);
      }};
    imageryByMap.set(map, controller);
    apply(enabled);

    // Visible with Layers closed, and while the archive is still loading.
    const host = documentRef?.querySelector(".fl-map-legend")?.parentElement ||
      documentRef?.querySelector(".fl-map-card");
    if (host) {
      const badge = documentRef.createElement("div");
      badge.className = "fl-map-imagery-status";
      const text = documentRef.createElement("span");
      text.setAttribute("role", "status");
      const button = documentRef.createElement("button");
      button.type = "button"; button.textContent = "Retry imagery";
      button.addEventListener("click", retry);
      badge.append(text, button); host.append(badge);
      controller.subscribe(s => {
        badge.hidden = !s.enabled || (!!s.loaded && !s.pending && !s.failed && !s.error);
        text.textContent = imageryStatus(s);
        button.hidden = !s.failed && !s.error;
        button.disabled = !!s.pending;
      });
    }
    return controller;
  }

  function imageryStatus(state) {
    if (!state.enabled) return "NASA imagery off · vector context";
    if (state.error) return state.error;
    if (state.failed) return `NASA imagery: ${state.failed} tile(s) failed` +
      (state.pending ? ` · ${state.pending} loading` : "") + ". Vector context remains available.";
    if (state.pending) return `NASA imagery loading · ${state.pending} tile request(s). Vector context remains available.`;
    return state.loaded ? `NASA imagery: ${state.loaded} tile(s) received this session.`
      : "NASA imagery waiting for tiles. Vector context remains available.";
  }

  function mountGibs({map, layers, reference, row, documentRef}) {
    const controller = prepareImagery({map, layers, documentRef});
    if (!controller) return null;
    const info = documentRef.createElement("div");
    info.className = "fl-layers-imagery";
    info.innerHTML = `<p class="fl-layers-note"><strong>${esc(GIBS.title)}</strong> · ${esc(GIBS.provider)} · ${esc(GIBS.date)}.
      Rendered satellite and shaded bathymetric context only, not a measurement or geolocation correction.
      Where supported, display colors use a gamma curve that keeps dark tones nearer the local ocean color and preserves white; raw imagery tiles and coordinates are unchanged.</p>
      <p class="fl-layers-note">${esc(GIBS.acknowledgement)}
      <a href="${esc(GIBS.docs)}" target="_blank" rel="noopener noreferrer">GIBS documentation</a> ·
      <a href="${esc(GIBS.policy)}" target="_blank" rel="noopener noreferrer">NASA data policy</a></p>`;
    const statusNode = documentRef.createElement("p");
    statusNode.className = "fl-layers-note";
    statusNode.setAttribute("role", "status");
    const retryButton = documentRef.createElement("button");
    retryButton.type = "button"; retryButton.textContent = "Retry failed imagery";
    retryButton.addEventListener("click", controller.retry);
    info.append(statusNode, retryButton);
    const control = row(reference, "NASA Blue Marble bathymetry (GIBS)",
      "On by default; turn off for vector context", controller.state.enabled, controller.setEnabled);
    reference.append(info);
    controller.subscribe(state => {
      info.hidden = !state.enabled;
      control.input.checked = state.enabled;
      statusNode.textContent = imageryStatus(state);
      retryButton.hidden = !state.failed && !state.error;
      retryButton.disabled = !!state.pending;
    });
    return {...controller, control, info, status: statusNode, retryButton};
  }

  /* Plain-text record scope line for the explorer status. */
  function countSummary({loaded = 0, matching = 0, visible = 0} = {}) {
    const n = value => Number(value || 0).toLocaleString("en-US");
    const hidden = matching - visible;
    return `${n(visible)} of ${n(loaded)} loaded map observations shown` +
      (matching !== loaded ? ` · ${n(matching)} match the filters` : "") +
      (hidden > 0 ? ` · ${n(hidden)} hidden by Layers (still in the data)` : "") +
      ". Catalogue file matches are counted separately in the radar catalogue.";
  }

  /* ── map selection ↔ catalogue segment rows (this page only) ─── */
  // A row is linked when its flight equals the selected record's flight and
  // its CBD range contains the record's CBD. Several image variants may match;
  // all are marked and none is opened automatically.
  function segmentMatches({flight, cbd} = {}, selection = {}) {
    const wanted = String(selection.flight ?? "").replace(/^F/i, "").trim();
    const number = Number(selection.cbd);
    const match = String(cbd || "").match(/^(\d+)-(\d+)$/);
    if (!wanted || !Number.isFinite(number) || !match) return false;
    return String(flight ?? "").replace(/^F/i, "").trim() === wanted &&
      number >= Number(match[1]) && number <= Number(match[2]);
  }

  let linkedSelection = null;
  function linkSegments(documentRef = root.document) {
    const rows = [...(documentRef.querySelectorAll?.("[data-segment-flight][data-segment-cbd]") || [])];
    let count = 0;
    for (const row of rows) {
      const on = Boolean(linkedSelection) && segmentMatches(
        {flight: row.dataset.segmentFlight, cbd: row.dataset.segmentCbd}, linkedSelection);
      row.classList.toggle("fl-segment-linked", on);
      if (on) { row.setAttribute("aria-current", "true"); row.title = "Contains the selected map observation's flight and CBD"; count++; }
      else { row.removeAttribute("aria-current"); row.removeAttribute("title"); }
    }
    return count;
  }

  function bindSegmentLinks(documentRef = root.document) {
    if (!documentRef?.addEventListener) return;
    documentRef.addEventListener("frozen-legacies:observation", event => {
      const p = event.detail?.properties;
      linkedSelection = p ? {flight: p.flight, cbd: p.cbd} : null;
      linkSegments(documentRef);
    });
    // The catalogue re-renders its page; relink when its strip is opened.
    documentRef.addEventListener("toggle", event => {
      if (event.target?.classList?.contains("fl-segment-browser")) linkSegments(documentRef);
    }, true);
  }
  bindSegmentLinks();


  // Optional globe: no index tags and no dependency traffic before this button.
  let globeAssets;
  const globeLaunchers = new WeakMap();
  // Owned globe controls follow the existing controls' measured boxes. This is
  // shared by the lazy launcher and active toolbar; existing controls never move.
  function positionGlobeControls(node, host, documentRef = root.document) {
    const controls = ['.fl-empty-flight-control', '.ol-zoom', '.fl-map-data-controls',
      '.fl-map-legend', '.fl-map-readout'].map(selector => host.querySelector?.(selector)).filter(Boolean);
    const visible = element => !element.hidden && element.getBoundingClientRect().width > 0;
    function layout() {
      const box = host.getBoundingClientRect(), left = 8;
      const empty = controls.find(element => element.classList.contains('fl-empty-flight-control'));
      const top = empty && visible(empty) ? Math.max(8, empty.getBoundingClientRect().bottom - box.top + 8) : 8;
      let right = box.width - 8, bottom = box.height - 8;
      for (const element of controls) {
        if (element === empty || !visible(element)) continue;
        const rect = element.getBoundingClientRect();
        if (element.classList.contains('ol-zoom') || element.classList.contains('fl-map-data-controls')) {
          if (rect.bottom - box.top > top) right = Math.min(right, rect.left - box.left - 8);
        } else if (rect.top - box.top > top) bottom = Math.min(bottom, rect.top - box.top - 8);
      }
      Object.assign(node.style, {position:'absolute', zIndex:'24', left:left+'px', top:top+'px',
        width:'max-content', maxWidth:Math.max(32, right-left)+'px',
        maxHeight:Math.max(32, bottom-top)+'px', overflow:'auto', boxSizing:'border-box'});
    }
    layout();
    const resize = root.ResizeObserver ? new root.ResizeObserver(layout) : null;
    resize?.observe(host); controls.forEach(element => resize?.observe(element));
    root.addEventListener('resize', layout);
    host.addEventListener('toggle', layout, true);
    return () => { resize?.disconnect(); root.removeEventListener('resize', layout); host.removeEventListener('toggle', layout, true); };
  }
  function mountGlobeButton(app, {documentRef = root.document} = {}) {
    if (globeLaunchers.has(app.map)) return globeLaunchers.get(app.map);
    const host = app.map.getTargetElement().parentElement;
    const button = documentRef.createElement('button');
    button.type = 'button'; button.className = 'fl-radar-button';
    button.textContent = '3D globe'; button.setAttribute('aria-pressed', 'false');
    host.append(button);
    const stopPositioning = positionGlobeControls(button, host, documentRef);
    let wanted = false, dead = false, controller = null;
    const modeIsMap = () => !documentRef.body.dataset.flMode || documentRef.body.dataset.flMode === 'map';
    function loadAssets() {
      if (globeAssets) return globeAssets;
      globeAssets = new Promise((resolve, reject) => {
        const js = documentRef.createElement('script'), css = documentRef.createElement('link');
        // Exact known app mount, same origin; no application query or auth copied.
        js.src = '/frozen-legacies/assets/globe_view.js?v=sha256-e4340c24938a'; js.integrity = 'sha256-5DQMJJOKtyt0vlkE/n+LdO8mFQCn8PrtTYtQd11ac/A=';
        css.rel = 'stylesheet'; css.href = '/frozen-legacies/assets/globe_view.css'; css.integrity = 'sha256-lIdwUUOZgzWhi/BM+ZOM1QIGXoZTneAF1oXfosntcXo=';
        for (const n of [js, css]) { n.crossOrigin = 'anonymous'; n.referrerPolicy = 'no-referrer'; }
        let count = 0, settled = false;
        const timer = root.setTimeout(fail, 15000);
        function clear() { root.clearTimeout(timer); js.onload = js.onerror = css.onload = css.onerror = null; }
        function fail() { if (settled) return; settled = true; clear(); js.remove(); css.remove(); reject(new Error('Globe module unavailable')); }
        function loaded() { if (++count !== 2 || settled) return; if (!root.FrozenLegaciesGlobe) { fail(); return; } settled = true; clear(); resolve(); }
        js.onload = css.onload = loaded; js.onerror = css.onerror = fail; documentRef.head.append(css, js);
      }).catch(error => { globeAssets = null; throw error; });
      return globeAssets;
    }
    async function click() {
      wanted = !wanted; button.setAttribute('aria-pressed', String(wanted));
      if (!wanted) { await controller?.setEnabled(false); button.textContent = '3D globe'; return; }
      button.textContent = 'Cancel 3D loading';
      try {
        await loadAssets();
        if (!wanted || dead || !modeIsMap() || documentRef.hidden) return;
        controller = root.FrozenLegaciesGlobe.mount({app, ol:root.ol, documentRef, positionControls:positionGlobeControls,
          imagery:prepareImagery({map:app.map, layers:app.layers, documentRef}),
          visibility:root.FrozenLegaciesMapVisibility, store:root.FrozenLegaciesExplorerStore,
          select:{observation:feature => app.ui.showObservation(feature),
            flight:feature => app.ui.selectFlight(feature.get('flight'), {datasetId:feature.get('dataset_id'), zoom:false}),
            riggs:feature => root.FrozenLegaciesUI.showRiggsStation(feature, app.data.riggs?.metadata),
            coverage:feature => root.FrozenLegaciesCatalog.selectMapAsset(feature),
            user:feature => root.FrozenLegaciesUserLayer.selectFeature(feature),
            reviewed:feature => root.FrozenLegaciesPublishedLayer.selectFeature(feature),
            radarCoverage:feature => root.FrozenLegaciesCatalog.selectFeature(feature)}});
        // Creation is zero-load; only this explicit enable loads Cesium.
        stopPositioning(); button.remove(); observer?.disconnect();
        documentRef.removeEventListener('visibilitychange', cancelHidden);
        await controller.setEnabled(true);
      } catch (_) {
        wanted = false; button.setAttribute('aria-pressed', 'false');
        button.textContent = '3D unavailable · retry';
      }
    }
    function cancelHidden() { button.hidden = !modeIsMap(); if (documentRef.hidden || !modeIsMap()) { wanted = false; button.setAttribute('aria-pressed','false'); button.textContent = '3D globe'; } }
    cancelHidden();
    const observer = root.MutationObserver ? new root.MutationObserver(cancelHidden) : null;
    observer?.observe(documentRef.body, {attributes:true, attributeFilter:['data-fl-mode']});
    documentRef.addEventListener('visibilitychange', cancelHidden);
    button.addEventListener('click', click);
    const launcher = {dispose() { stopPositioning(); dead = true; wanted = false; observer?.disconnect(); controller?.dispose(); button.remove();
      documentRef.removeEventListener('visibilitychange', cancelHidden); button.removeEventListener('click',click);
      root.removeEventListener('pagehide', launcher.dispose); globeLaunchers.delete(app.map); }};
    root.addEventListener('pagehide', launcher.dispose); globeLaunchers.set(app.map, launcher); return launcher;
  }

  const api = Object.freeze({
    GIBS, gibsTileUrl, gibsLoadTile, createGibsLayer, prepareImagery, imageryStatus,
    segmentMatches, linkSegments,
    NOT_SUPPLIED, UNITS, EXTERNAL_SOURCES, inspection, suppliedQuantities, sourceRows, manifest, manifestRecord,
    downloadManifest, mountLayers, finishLayers, mountGlobeButton, positionGlobeControls, legendVisible, countSummary, escape: esc
  });
  root.FrozenLegaciesMapExplorer = api;
  if (typeof module !== "undefined") module.exports = api;
})(typeof window === "undefined" ? globalThis : window);
