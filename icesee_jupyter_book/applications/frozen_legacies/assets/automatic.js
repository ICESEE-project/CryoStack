/* ============================================================
 * Frozen Legacies
 * automatic.js
 *
 * Automatic mode: URSA automatic picking on the open radar asset.
 *
 * The server reports whether URSA can run here; when it cannot,
 * the reason is shown and nothing is started. Jobs run on the
 * server (radar/automatic.py); this module starts, cancels and
 * polls them, and shows their products and a per-frame view of
 * URSA's values, the frame QC flags and URSA's own diagnostic
 * images (display only: nothing is corrected here).
 * ============================================================ */


(function () {

  "use strict";

  const API = "/frozen-legacies/api/assets";
  const POLL_MS = 2000;

  const STATUS_LABELS = {
    queued: "Queued",
    running: "Running",
    completed: "Completed",
    failed: "Failed",
    cancelled: "Cancelled",
    interrupted: "Interrupted"
  };


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


  const state = {
    asset: null,
    info: null,
    api: null,
    onChange: () => {},
    timer: null,
    busy: false,
    error: null,
    diagnostic: null
  };


  function active() {
    return ["queued", "running"].includes(state.info?.job?.status);
  }


  function schedule() {
    window.clearTimeout(state.timer);
    if (state.asset && active()) {
      state.timer = window.setTimeout(load, POLL_MS);
    }
  }


  async function load() {
    if (!state.asset) {
      return;
    }
    const assetId = state.asset.asset_id;
    try {
      const info = await state.api(`${API}/${encodeURIComponent(assetId)}/automatic`);
      if (state.asset?.asset_id !== assetId) {
        return;
      }
      const finished = active() && !["queued", "running"].includes(info.job?.status);
      state.info = info;
      state.error = null;
      render();
      if (finished) {
        state.onChange({ productsChanged: true });
      }
    } catch (error) {
      state.error = error.message || String(error);
      render();
    }
    schedule();
  }


  async function act(action) {
    if (state.busy || !state.asset) {
      return;
    }
    state.busy = true;
    render();
    try {
      state.info = await state.api(`${API}/${encodeURIComponent(state.asset.asset_id)}/automatic`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action })
      });
      state.error = null;
    } catch (error) {
      state.error = error.message || String(error);
    } finally {
      state.busy = false;
    }
    render();
    schedule();
  }


  function elapsed(job) {
    if (!job?.started_at) {
      return "";
    }
    const end = job.finished_at || Date.now() / 1000;
    const seconds = Math.max(0, Math.round(end - job.started_at));
    return seconds >= 60 ? `${Math.floor(seconds / 60)} min ${seconds % 60} s` : `${seconds} s`;
  }


  function formatBytes(bytes) {
    if (!Number.isFinite(bytes)) {
      return "";
    }
    return bytes >= 1048576
      ? `${(bytes / 1048576).toFixed(1)} MB`
      : `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }


  // URSA's per-frame values (as written in its CSV), the heuristic frame QC
  // flags with their reasons, and links to URSA's own diagnostic images.
  function framesHtml(frames) {
    if (!frames?.rows?.length) {
      return "";
    }
    // Frame and CBD lead, then the flags and images (visible without
    // scrolling on narrow screens), then URSA's remaining values
    const lead = 2;
    const header = c => `<th scope="col">${escapeHtml(c.replaceAll("_", " "))}</th>`;
    const head = frames.columns.slice(0, lead).map(header).join("")
      + `<th scope="col">QC flags (heuristic)</th><th scope="col">URSA diagnostic images</th>`
      + frames.columns.slice(lead).map(header).join("");
    const rows = frames.rows.map(row => {
      const flagged = row.flags?.length > 0;
      const flags = flagged
        ? `<span class="fl-astra-chip fl-automatic-flag">Inspect</span> ${row.flags.map(f => escapeHtml(f)).join("; ")}`
        : `<span class="fl-automatic-none">—</span>`;
      const images = (row.images || []).map(image =>
        `<button type="button" class="fl-automatic-diag-link${state.diagnostic === image.product_id ? " active" : ""}"
          data-diagnostic="${escapeHtml(image.product_id)}"
          title="${escapeHtml(`${image.title} · ${formatBytes(image.bytes)} · SHA-256 ${image.sha256 || "?"}`)}">${escapeHtml(image.label || "image")}</button>`
      ).join("");
      return `
        <tr class="${flagged ? "flagged" : ""}">
          ${row.values.slice(0, lead).map(v => `<td>${escapeHtml(v)}</td>`).join("")}
          <td class="fl-automatic-flags">${flags}</td>
          <td class="fl-automatic-diags">${images || `<span class="fl-automatic-none">not kept</span>`}</td>
          ${row.values.slice(lead).map(v => `<td>${escapeHtml(v)}</td>`).join("")}
        </tr>`;
    }).join("");
    let viewer = "";
    const selected = frames.rows.flatMap(r => r.images || []).find(i => i.product_id === state.diagnostic);
    if (selected) {
      viewer = `
        <figure class="fl-automatic-diag-viewer">
          <img class="fl-automatic-preview" src="${escapeHtml(selected.preview_url)}" alt="${escapeHtml(selected.title)}">
          <figcaption>
            <span class="fl-astra-chip fl-unvalidated">${escapeHtml(frames.label)}</span>
            <span>${escapeHtml(selected.title)} · ${escapeHtml(formatBytes(selected.bytes))}</span>
            <code>SHA-256 ${escapeHtml(selected.sha256 || "?")}</code>
            <span class="fl-automatic-diag-actions">
              <a class="fl-radar-button" href="${escapeHtml(selected.preview_url)}" target="_blank" rel="noopener">Open</a>
              ${selected.download_url ? `<a class="fl-radar-button" href="${escapeHtml(selected.download_url)}" download>Download</a>` : ""}
              <button type="button" class="fl-radar-button subtle" data-diagnostic-close>Close</button>
            </span>
          </figcaption>
        </figure>`;
    }
    return `
      <details class="fl-automatic-frames" open>
        <summary>Frame diagnostics (URSA) · ${frames.rows.length} frame${frames.rows.length === 1 ? "" : "s"}${
          frames.flagged ? ` · ${frames.flagged} flagged for inspection` : ""}
          <span class="fl-astra-chip fl-unvalidated">${escapeHtml(frames.label)}</span></summary>
        <p class="fl-automatic-note">${escapeHtml(frames.note)}</p>
        ${frames.diagnostic_images ? "" : `<p class="fl-automatic-note">URSA's diagnostic images were not kept for this run (it predates their preservation); run automatic picking again to keep them.</p>`}
        <div class="fl-automatic-frames-scroll">
          <table class="fl-automatic-frames-table">
            <thead><tr>${head}</tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        ${frames.truncated ? `<p class="fl-automatic-note">Only the first ${frames.rows.length} frames are listed.</p>` : ""}
        ${viewer}
      </details>`;
  }


  function render() {
    const root = $("fl-automatic");
    if (!root || !state.asset) {
      return;
    }
    const info = state.info;
    if (!info) {
      root.innerHTML = `<span class="fl-radar-status">Checking automatic picking…</span>`;
      return;
    }
    const availability = info.availability || {};
    const job = info.job;
    const running = active();
    const lines = [];

    if (!info.has_radar) {
      lines.push(`<p class="fl-automatic-note">This asset holds processed products only; there is no raw radar to pick.</p>`);
    } else if (!availability.available) {
      lines.push(`
        <div class="fl-automatic-unavailable" role="status">
          <span class="fl-automatic-unavailable-icon" aria-hidden="true">!</span>
          <div>
            <strong>Automatic picking (URSA) is not available on this server.</strong>
            <span>${escapeHtml(availability.reason || "")}</span>
            <span>No automatic results have been produced. Manual picking is available in <strong>Manual</strong>.</span>
          </div>
        </div>`);
    } else {
      lines.push(`<p class="fl-automatic-note">URSA detects A-scope frames, calibrates the time and power grids, and picks the transmitter pulse, surface and bed automatically. It can take several minutes for a full strip.</p>`);
      const env = availability.environment;
      if (env) {
        const v = env.packages || {};
        lines.push(`<p class="fl-automatic-note fl-automatic-env">URSA environment checked: Python ${escapeHtml(env.python)} · OpenCV ${escapeHtml(v.cv2 || "?")} · NumPy ${escapeHtml(v.numpy || "?")} · scikit-image ${escapeHtml(v.skimage || "?")}</p>`);
      }
    }
    if (info.has_radar) {
      // operational availability is not scientific validation
      lines.push(`
        <div class="fl-automatic-unvalidated" role="note">
          <span class="fl-astra-chip fl-unvalidated">Scientifically unvalidated</span>
          <span>${escapeHtml(info.scientific_note || "Automatic results are scientifically unvalidated and cannot be submitted for review or publication.")}</span>
        </div>`);
    }
    (info.warnings || []).forEach(w => lines.push(`<p class="fl-automatic-warning">${escapeHtml(w)}</p>`));

    const canRun = info.has_radar && availability.available && !running && !state.busy;
    const action = running
      ? `<button type="button" class="fl-radar-button" data-automatic="cancel" ${state.busy ? "disabled" : ""}>Cancel</button>`
      : `<button type="button" class="fl-radar-button primary" data-automatic="start" ${canRun ? "" : "disabled"}>${
          !availability.available && info.has_radar
            ? "Run automatic picking (unavailable)"
            : job && job.status === "completed" ? "Run automatic picking again" : "Run automatic picking"}</button>`;

    let status = "";
    if (job) {
      status = `
        <div class="fl-automatic-status ${escapeHtml(job.status)}">
          <span class="fl-astra-chip ${job.status === "completed" ? "complete" : ""}">${escapeHtml(STATUS_LABELS[job.status] || job.status)}</span>
          <span>${escapeHtml(job.message || "")}${job.started_at ? ` · ${escapeHtml(elapsed(job))}` : ""}</span>
        </div>
        ${job.log_tail?.length ? `<details class="fl-automatic-log"><summary>URSA log</summary><pre>${escapeHtml(job.log_tail.join("\n"))}</pre></details>` : ""}`;
    }

    const products = info.products || [];
    let results = "";
    if (products.length) {
      const verification = products.find(p => p.kind === "ursa-verification" && p.preview_url);
      const picks = products.find(p => p.kind === "ursa-csv");
      results = `
        <div class="fl-automatic-results">
          <div class="fl-astra-qc-label">Automatic results (URSA) <span class="fl-astra-chip fl-unvalidated">Scientifically unvalidated</span></div>
          ${picks ? `<p class="fl-automatic-note">${escapeHtml(window.FrozenLegaciesProducts?.summaryText(picks) || "")}</p>` : ""}
          ${picks ? (window.FrozenLegaciesProducts?.qcWarnings?.(picks) || []).map(w =>
            `<p class="fl-automatic-warning">${escapeHtml(w)}</p>`).join("") : ""}
          <div class="fl-astra-downloads">${products.filter(p => p.download_url).map(p =>
            `<a class="fl-radar-button" href="${escapeHtml(p.download_url)}" download>${escapeHtml(p.title)}</a>`).join("")}</div>
          ${verification ? `<img class="fl-automatic-preview" src="${escapeHtml(verification.preview_url)}" alt="URSA frame verification">` : ""}
          ${framesHtml(info.frames)}
        </div>`;
    }

    root.innerHTML = `
      ${lines.join("")}
      <div class="fl-automatic-actions">${action}</div>
      ${status}
      ${state.error ? `<p class="fl-automatic-warning">${escapeHtml(state.error)}</p>` : ""}
      ${results}`;
    root.querySelectorAll("[data-automatic]").forEach(button => {
      button.addEventListener("click", () => act(button.dataset.automatic));
    });
    root.querySelectorAll("[data-diagnostic]").forEach(button => {
      button.addEventListener("click", () => {
        state.diagnostic = state.diagnostic === button.dataset.diagnostic ? null : button.dataset.diagnostic;
        render();
      });
    });
    root.querySelector("[data-diagnostic-close]")?.addEventListener("click", () => {
      state.diagnostic = null;
      render();
    });
  }


  window.FrozenLegaciesAutomatic = {

    open(asset, { api, onChange }) {
      state.api = api;
      state.onChange = onChange || (() => {});
      if (state.asset?.asset_id !== asset.asset_id) {
        state.info = null;
        state.error = null;
        state.diagnostic = null;
      }
      state.asset = asset;
      $("fl-automatic").hidden = false;
      render();
      return load();
    },

    close() {
      window.clearTimeout(state.timer);
      state.asset = null;
      state.info = null;
      state.diagnostic = null;
      const root = $("fl-automatic");
      if (root) {
        root.hidden = true;
        root.innerHTML = "";
      }
    },

    get info() {
      return state.info;
    }
  };

})();
