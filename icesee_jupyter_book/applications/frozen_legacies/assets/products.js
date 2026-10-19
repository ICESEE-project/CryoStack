/* ============================================================
 * Frozen Legacies
 * products.js
 *
 * Products of the open radar asset (Dataset Explorer panel), the
 * "Upload processed product" form, and asset removal.
 *
 * Products are addressed by product IDs from the server
 * (radar/products.py); the browser never sees file paths.
 * ============================================================ */


(function () {

  "use strict";

  const API = "/frozen-legacies/api/assets";

  /* Upload kinds offered before an asset is open (radar/products.py UPLOAD_KINDS). */
  const DEFAULT_UPLOAD_KINDS = [
    { kind: "astra-csv", title: "ASTRA picks (CSV)", extensions: [".csv"] },
    { kind: "astra-qc", title: "ASTRA QC image", extensions: [".png"] },
    { kind: "ursa-csv", title: "URSA picks (CSV)", extensions: [".csv"] },
    { kind: "lyra-echoes-csv", title: "LYRA echoes (CSV)", extensions: [".csv"] },
    { kind: "lyra-guidance", title: "LYRA calibration picks (JSON)", extensions: [".json"] },
    { kind: "lyra-guidance-derived", title: "LYRA derived calibration (JSON)", extensions: [".json"] },
    { kind: "echogram", title: "Processed echogram", extensions: [".png", ".jpg", ".jpeg", ".tif", ".tiff"] },
    { kind: "radargram", title: "Radargram image", extensions: [".png", ".jpg", ".jpeg", ".tif", ".tiff"] },
    { kind: "navigation", title: "Navigation CSV", extensions: [".csv"] }
  ];

  const WORKFLOW_LABELS = {
    "astra-manual": "ASTRA manual result",
    "lyra-automatic": "LYRA automatic result",
    "ursa-automatic": "URSA automatic result",
    "upload": "User-provided product",
    "radar-source": "Shared installation radar"
  };

  const PREVIEW_SLOTS = [
    { key: "source", title: "Source radar image", kinds: ["raw-radar"],
      absent: "No source radar preview is available for this asset." },
    { key: "radargram", title: "Radargram / echogram", kinds: ["radargram", "echogram"],
      absent: "No radargram or echogram has been linked to this asset." },
    { key: "qc", title: "QC image", kinds: ["astra-qc", "ursa-verification"],
      absent: "No QC image has been produced or uploaded." },
    { key: "diagnostic", title: "Picker diagnostics", kinds: ["lyra-diagnostic", "ursa-diagnostic"],
      absent: "No picker diagnostic image is available." }
  ];


  /* Where a product came from, in the terms users see. */
  function originLabel(product) {
    if (product.workflow === "upload" &&
        (product.kind === "raw-radar" || product.product_id === "navigation")) {
      return "My upload";
    }
    const label = WORKFLOW_LABELS[product.workflow] || product.producer;
    return product.scientific_status === "unvalidated"
      ? `${label} · scientifically unvalidated`
      : label;
  }


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


  function formatBytes(bytes) {
    if (!Number.isFinite(bytes)) {
      return "";
    }
    return bytes >= 1048576
      ? `${(bytes / 1048576).toFixed(1)} MB`
      : `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }


  function summaryText(product) {
    const s = product.summary || {};
    const parts = [];
    if (Number.isFinite(s.rows)) {
      parts.push(`${s.rows.toLocaleString("en-US")} ${s.row_label || "rows"}`);
    }
    if (Number.isFinite(s.cbd_min) && Number.isFinite(s.cbd_max)) {
      parts.push(`CBD ${s.cbd_min}–${s.cbd_max}`);
    }
    if (Number.isFinite(s.positions) && Number.isFinite(s.rows)) {
      parts.push(`${s.positions} with position`);
    }
    if (Number.isFinite(s.thickness_values) && s.thickness_values > 0) {
      parts.push(`${s.thickness_values} thickness value${s.thickness_values === 1 ? "" : "s"}`
        + (Number.isFinite(s.thickness_min_m) ? ` (${s.thickness_min_m}–${s.thickness_max_m} m)` : ""));
    }
    if (Number.isFinite(s.width) && Number.isFinite(s.height)) {
      parts.push(`${s.width.toLocaleString("en-US")} × ${s.height.toLocaleString("en-US")} px`);
    }
    if (s.echo_status && typeof s.echo_status === "object") {
      const counts = Object.entries(s.echo_status).filter(([k]) => k)
        .map(([k, n]) => `${n} ${k.replaceAll("_", " ")}`);
      if (counts.length) {
        parts.push(`LYRA echo status: ${counts.join(", ")}`);
      }
    }
    if (Number.isFinite(s.frames_with_reference)) {
      parts.push(`${s.frames_with_reference} with a reference-line pick`);
    }
    if (Array.isArray(s.qc_flags) && s.qc_flags.length) {
      parts.push(`${s.qc_flags.length} frame${s.qc_flags.length === 1 ? "" : "s"} flagged for inspection`);
    }
    return parts.join(" · ");
  }


  /* Render only provenance fields whose meaning is part of the product API.
   * Arbitrary metadata is intentionally not surfaced: it may be operational,
   * path-like, or unsuitable for the user-facing scientific record. */
  function provenanceHtml(product) {
    const provenance = product.provenance || {};
    const fields = [
      ["Picker", provenance.picker],
      ["Written by", provenance.written_by],
      ["Source file", provenance.source_filename],
      ["Original file", provenance.original_filename],
      ["Shared source", provenance.shared_source],
      ["SHA-256", provenance.sha256]
    ].filter(([_label, value]) => typeof value === "string" && value.trim());
    if (!fields.length) {
      return "";
    }
    return `
      <details class="fl-product-provenance">
        <summary>Provenance</summary>
        <dl>${fields.map(([label, value]) => `
          <div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}
        </dl>
      </details>`;
  }

  function scientificStatus(product) {
    if (product.kind === "raw-radar") return "Source material · not a scientific interpretation";
    if (product.scientific_status === "unvalidated" || product.diagnostic) return "Scientifically unvalidated";
    if (product.workflow === "upload") return "User provided · validation not established";
    return "Review status not established";
  }

  function previewShelfHtml() {
    const cards = PREVIEW_SLOTS.map(slot => {
      const matches = state.products.filter(product =>
        slot.kinds.includes(product.kind) && product.available && product.preview_url
      );
      const product = matches[0];
      if (!product) {
        return `<article class="fl-preview-card is-empty" data-preview-slot="${slot.key}">
          <div class="fl-preview-card-head"><strong>${slot.title}</strong><span>Not available</span></div>
          <div class="fl-preview-placeholder" role="status"><span aria-hidden="true">◫</span>
            <p>${slot.absent}<small>Placeholder only · no scientific data shown</small></p></div>
        </article>`;
      }
      const extra = matches.length > 1 ? ` · ${matches.length} images available` : "";
      return `<article class="fl-preview-card" data-preview-slot="${slot.key}">
        <div class="fl-preview-card-head"><strong>${slot.title}</strong><span>${escapeHtml(scientificStatus(product))}</span></div>
        <div class="fl-preview-media is-loading" data-preview-media>
          <span class="fl-preview-message" role="status">Loading preview…</span>
          <img src="${escapeHtml(product.preview_url)}" alt="${escapeHtml(product.title)} preview" loading="lazy" data-preview-image>
        </div>
        <div class="fl-preview-card-foot"><span>${escapeHtml(originLabel(product))}${escapeHtml(extra)}</span>
          <a href="${escapeHtml(product.preview_url)}" target="_blank" rel="noopener">Open full preview<span class="fl-visually-hidden"> of ${escapeHtml(product.title)}</span></a></div>
      </article>`;
    }).join("");
    return `<section class="fl-preview-shelf" aria-labelledby="fl-preview-shelf-title">
      <div class="fl-preview-shelf-head"><strong id="fl-preview-shelf-title">Scientific previews</strong>
        <span>Display derivatives; original files and provenance remain authoritative.</span></div>
      <div class="fl-preview-grid">${cards}</div>
    </section>`;
  }


  // Frames whose automatic detection departs from the rest of the strip
  // (display only: the picks themselves are not changed).
  function qcWarnings(product) {
    const flags = product?.summary?.qc_flags;
    if (!Array.isArray(flags)) {
      return [];
    }
    return flags.map(f => `Frame ${f.frame}${Number.isFinite(f.cbd) ? ` (CBD ${f.cbd})` : ""}: `
      + `${(f.checks || []).join("; ")}. Inspect this frame before using its surface and bed picks.`);
  }


  const state = {
    asset: null,
    products: [],
    uploadKinds: DEFAULT_UPLOAD_KINDS,
    api: null,
    onChange: () => {},
    onAssetCreated: async () => {},
    onAssetRemoved: async () => {},
    error: null
  };


  async function load() {
    if (!state.asset) {
      return;
    }
    try {
      const body = await state.api(`${API}/${encodeURIComponent(state.asset.asset_id)}/products`);
      state.products = body.products || [];
      state.uploadKinds = body.upload_kinds?.length ? body.upload_kinds : DEFAULT_UPLOAD_KINDS;
      state.error = null;
    } catch (error) {
      state.products = [];
      state.error = error.message || String(error);
    }
    renderKinds();
    state.onChange();
  }


  function panelHtml() {
    if (!state.asset) {
      return "";
    }
    // The automatic pickers' diagnostic images are listed in the Automatic
    // view; here they are one line per picker, so they never crowd out the results
    const DIAGNOSTICS = [["ursa-diagnostic", "URSA"], ["lyra-diagnostic", "LYRA"]];
    const listed = state.products.filter(p => !DIAGNOSTICS.some(([kind]) => kind === p.kind));
    const items = listed.map(product => {
      const actions = [];
      const previewId = `fl-product-preview-${product.product_id}`;
      if (product.download_url) {
        actions.push(`<a class="fl-radar-button" href="${escapeHtml(product.download_url)}" download>Download</a>`);
      }
      if (product.preview_url) {
        actions.push(`<button type="button" class="fl-radar-button" data-product-preview="${escapeHtml(product.product_id)}" aria-expanded="false" aria-controls="${escapeHtml(previewId)}">Preview here</button>`);
      }
      if (product.workflow === "upload" && product.product_id.startsWith("upload-")) {
        actions.push(`<button type="button" class="fl-radar-button subtle" data-remove-product="${escapeHtml(product.product_id)}">Remove</button>`);
      }
      const detail = [summaryText(product), formatBytes(product.bytes)].filter(Boolean).join(" · ");
      return `
        <div class="fl-product">
          <div class="fl-product-main">
            <strong>${escapeHtml(product.title)}</strong>
            <span class="fl-product-origin ${escapeHtml(product.producer)}">${escapeHtml(
              originLabel(product))}</span>
            ${detail ? `<span class="fl-product-detail">${escapeHtml(detail)}</span>` : ""}
            ${product.available ? "" : `<span class="fl-product-detail">Not available</span>`}
            ${product.workflow === "radar-source" && product.available
              ? `<span class="fl-product-detail">Used for processing; not downloadable</span>` : ""}
            ${provenanceHtml(product)}
          </div>
          <div class="fl-product-actions">${actions.join("")}</div>
          ${product.preview_url ? `
            <div id="${escapeHtml(previewId)}" class="fl-product-preview" data-product-preview-panel="${escapeHtml(product.product_id)}" role="region" aria-label="Preview of ${escapeHtml(product.title)}" hidden>
              <img src="${escapeHtml(product.preview_url)}" alt="Preview of ${escapeHtml(product.title)}" loading="lazy">
              <a href="${escapeHtml(product.preview_url)}" target="_blank" rel="noopener">Open full preview</a>
            </div>` : ""}
        </div>`;
    }).join("") + DIAGNOSTICS.map(([kind, picker]) => {
      const diagnostics = state.products.filter(p => p.kind === kind);
      return diagnostics.length ? `
        <div class="fl-product">
          <div class="fl-product-main">
            <strong>${picker} diagnostic images</strong>
            <span class="fl-product-origin frozen-legacies">${picker} diagnostic (unvalidated)</span>
            <span class="fl-product-detail">${diagnostics.length} image${diagnostics.length === 1 ? "" : "s"} · ${escapeHtml(
              formatBytes(diagnostics.reduce((sum, p) => sum + (p.bytes || 0), 0)))} · inspect them per frame in <strong>Automatic</strong></span>
          </div>
        </div>` : "";
    }).join("");
    const downloadable = state.products.some(p => p.downloadable && p.kind !== "raw-radar");
    const removeLabel = state.asset.origin === "shared"
      ? "Remove from my workspace (the shared radar is not affected)"
      : "Remove this asset and its products from my workspace";
    return `
      ${previewShelfHtml()}
      <div class="fl-record-section">
        <div class="fl-record-section-title">Products</div>
        ${state.error ? `<p class="fl-radar-panel-note">${escapeHtml(state.error)}</p>` : ""}
        <div class="fl-product-list">${items || `<p class="fl-radar-panel-note">No products yet.</p>`}</div>
        <div class="fl-product-footer">
          ${downloadable ? `<a class="fl-radar-button" href="${API}/${escapeHtml(state.asset.asset_id)}/products.zip" download>Download products (ZIP)</a>` : ""}
          <button type="button" class="fl-radar-button subtle" data-remove-asset title="${escapeHtml(removeLabel)}">Remove asset</button>
        </div>
      </div>`;
  }


  function bindPanel(root) {
    root.querySelectorAll("[data-preview-image]").forEach(image => {
      const media = image.closest("[data-preview-media]");
      const message = media?.querySelector(".fl-preview-message");
      const loaded = () => {
        media?.classList.remove("is-loading", "is-error");
        if (message) message.textContent = "";
      };
      const failed = () => {
        media?.classList.remove("is-loading");
        media?.classList.add("is-error");
        if (message) message.textContent = "Preview could not be loaded. Open the full preview to retry.";
      };
      image.addEventListener("load", loaded, { once: true });
      image.addEventListener("error", failed, { once: true });
      if (image.complete) image.naturalWidth ? loaded() : failed();
    });
    root.querySelectorAll("[data-product-preview]").forEach(button => {
      button.addEventListener("click", () => {
        const id = button.dataset.productPreview;
        const preview = root.querySelector(`[data-product-preview-panel="${CSS.escape(id)}"]`);
        if (!preview) return;
        const opening = preview.hidden;
        root.querySelectorAll("[data-product-preview-panel]").forEach(item => { item.hidden = true; });
        root.querySelectorAll("[data-product-preview]").forEach(item => {
          item.textContent = "Preview here";
          item.setAttribute("aria-expanded", "false");
        });
        preview.hidden = !opening;
        button.textContent = opening ? "Hide preview" : "Preview here";
        button.setAttribute("aria-expanded", String(opening));
      });
    });
    root.querySelectorAll("[data-remove-product]").forEach(button => {
      button.addEventListener("click", async () => {
        if (!window.confirm("Remove this uploaded product from your workspace?")) {
          return;
        }
        try {
          await state.api(`${API}/${encodeURIComponent(state.asset.asset_id)}/products/${encodeURIComponent(button.dataset.removeProduct)}`, { method: "DELETE" });
        } catch (error) {
          state.error = error.message || String(error);
        }
        await load();
      });
    });
    root.querySelectorAll("[data-remove-asset]").forEach(button => {
      button.addEventListener("click", async () => {
        const asset = state.asset;
        const message = asset.origin === "shared"
          ? "Remove this radar asset from your workspace? Your picks and products for it are deleted. The shared radar itself is not affected."
          : "Remove this radar asset from your workspace? Its TIFF, navigation, picks and products are deleted.";
        if (!window.confirm(message)) {
          return;
        }
        try {
          await state.api(`${API}/${encodeURIComponent(asset.asset_id)}`, { method: "DELETE" });
          state.asset = null;
          state.products = [];
          await state.onAssetRemoved(asset.asset_id);
        } catch (error) {
          state.error = error.message || String(error);
          state.onChange();
        }
      });
    });
  }


  /* ----------------------------------------------------------
   * Upload processed product
   * ---------------------------------------------------------- */

  function renderKinds() {
    const select = $("fl-product-kind");
    if (!select) {
      return;
    }
    const current = select.value;
    select.innerHTML = state.uploadKinds.map(k =>
      `<option value="${escapeHtml(k.kind)}">${escapeHtml(k.title)} (${escapeHtml(k.extensions.join(", "))})</option>`
    ).join("");
    if (state.uploadKinds.some(k => k.kind === current)) {
      select.value = current;
    }
    const target = $("fl-product-target");
    if (target) {
      target.textContent = state.asset
        ? `Adds the product to “${state.asset.title || state.asset.filename}”.`
        : "Creates a new products-only asset (no raw radar).";
    }
    const file = $("fl-product-file");
    const kind = state.uploadKinds.find(k => k.kind === select.value);
    if (file && kind) {
      file.accept = kind.extensions.join(",");
    }
  }


  function bindUpload() {
    const toggle = $("fl-product-upload-toggle");
    const form = $("fl-product-upload");
    const status = $("fl-product-upload-status");
    toggle.addEventListener("click", () => {
      form.hidden = !form.hidden;
      $("fl-radar-upload").hidden = true;
      renderKinds();
    });
    $("fl-product-kind").addEventListener("change", renderKinds);

    form.addEventListener("submit", event => {
      event.preventDefault();
      const kind = $("fl-product-kind").value;
      const file = $("fl-product-file").files?.[0];
      if (!file) {
        status.textContent = "Choose a product file first.";
        return;
      }
      const data = new FormData();
      data.append("kind", kind);
      data.append("file", file, file.name);
      const assetId = state.asset?.asset_id;
      const url = assetId
        ? `${API}/${encodeURIComponent(assetId)}/products`
        : `${API}/products`;

      const request = new XMLHttpRequest();
      request.open("POST", url);
      request.withCredentials = true;
      request.responseType = "json";
      request.setRequestHeader("Accept", "application/json");
      request.upload.addEventListener("progress", e => {
        if (e.lengthComputable) {
          status.textContent = `Uploading… ${Math.round((100 * e.loaded) / e.total)}%`;
        }
      });
      request.upload.addEventListener("load", () => {
        status.textContent = "Validating product…";
      });
      request.addEventListener("error", () => {
        status.textContent = "Upload failed. Check your connection and try again.";
      });
      request.addEventListener("load", async () => {
        if (request.status === 401) {
          status.textContent = "Your CryoStack session has ended. Reload the page to sign in again.";
          return;
        }
        if (request.status !== 201) {
          status.textContent = request.response?.error ||
            (request.status === 413 ? "The file is larger than the upload limit." :
              `Upload failed (HTTP ${request.status}).`);
          return;
        }
        status.textContent = "Uploaded.";
        form.reset();
        form.hidden = true;
        if (assetId) {
          await load();
        } else {
          await state.onAssetCreated(request.response.asset_id);
        }
      });
      status.textContent = "Uploading…";
      request.send(data);
    });
  }


  function openUpload(kind) {
    const form = $("fl-product-upload");
    const select = $("fl-product-kind");
    const file = $("fl-product-file");
    if (!form || !select || !file) {
      return false;
    }
    $("fl-radar-upload").hidden = true;
    form.hidden = false;
    renderKinds();
    if (state.uploadKinds.some(item => item.kind === kind)) {
      select.value = kind;
      renderKinds();
    }
    form.scrollIntoView({ behavior: "smooth", block: "nearest" });
    file.focus({ preventScroll: true });
    return true;
  }


  let bound = false;

  window.FrozenLegaciesProducts = {

    configure({ api, onChange, onAssetCreated, onAssetRemoved }) {
      state.api = api;
      state.onChange = onChange || (() => {});
      state.onAssetCreated = onAssetCreated || (async () => {});
      state.onAssetRemoved = onAssetRemoved || (async () => {});
      if (!bound) {
        bindUpload();
        bound = true;
      }
      renderKinds();
    },

    open(asset) {
      state.asset = asset;
      state.products = [];
      renderKinds();
      return load();
    },

    clear() {
      state.asset = null;
      state.products = [];
      renderKinds();
    },

    reload: load,
    panelHtml,
    bindPanel,
    summaryText,
    qcWarnings,
    openUpload,
    DEFAULT_UPLOAD_KINDS,

    get products() {
      return state.products;
    }
  };

})();
