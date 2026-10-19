/* ============================================================
 * Frozen Legacies
 * automatic.js
 *
 * Automatic mode: automatic picking on the open radar asset with
 * the picker the server is configured for (LYRA, or URSA as the
 * rollback); every label names the picker the server reports.
 *
 * The server reports whether the picker can run here; when it
 * cannot, the reason is shown and nothing is started. Jobs run on
 * the server (radar/automatic.py); this module starts, cancels and
 * polls them, and shows their products and a per-frame view of the
 * picker's values, the frame QC flags and the picker's own
 * diagnostic images (display only: nothing is corrected here).
 * ============================================================ */


(function () {

  "use strict";

  const API = "/frozen-legacies/api/assets";
  const POLL_MS = 2000;

  const INTROS = {
    LYRA: "LYRA detects the A-scope frames and reads their CBDs. With LYRA's calibration picks uploaded (Products), it also calibrates each frame and extracts the surface and bed echoes and ice thickness. It can take several minutes for a full strip.",
    URSA: "URSA detects A-scope frames, calibrates the time and power grids, and picks the transmitter pulse, surface and bed automatically. It can take several minutes for a full strip."
  };

  const ENVIRONMENT_PACKAGES = {
    LYRA: [["NumPy", "numpy"], ["pandas", "pandas"], ["Matplotlib", "matplotlib"], ["Pillow", "PIL"]],
    URSA: [["OpenCV", "cv2"], ["NumPy", "numpy"], ["scikit-image", "skimage"]]
  };

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
    diagnostic: null,
    frameFilter: "all"
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


  function diagnosticButton(image) {
    return `<button type="button" class="fl-automatic-diag-link${state.diagnostic === image.product_id ? " active" : ""}"
          data-diagnostic="${escapeHtml(image.product_id)}"
          title="${escapeHtml(`${image.title} · ${formatBytes(image.bytes)} · SHA-256 ${image.sha256 || "?"}`)}">${escapeHtml(image.label || "image")}</button>`;
  }


  function phaseHtml(info, products, picker) {
    if (picker !== "LYRA") {
      return "";
    }
    const kinds = new Set(products.map(product => product.kind));
    const running = active();
    const livePhase = info.job?.progress?.phase;
    const guidance = info.lyra?.guidance?.picks;
    const phases = [
      { number: 1, title: "Frames & CBDs", note: "Detect frames and read film labels",
        state: kinds.has("lyra-frame-index") || ["phase3", "phase4"].includes(livePhase) ? "complete" : running && livePhase === "phase1" ? "active" : "ready" },
      { number: 2, title: "Guidance", note: guidance ? "Calibration picks uploaded" : "Human −60 dB reference picks required",
        state: guidance ? "complete" : "waiting" },
      { number: 3, title: "Calibration", note: "Calibrate time and power axes",
        state: kinds.has("lyra-calibration") || livePhase === "phase4" ? "complete" : guidance && running && livePhase === "phase3" ? "active" : "waiting" },
      { number: 4, title: "Echoes", note: "Measure surface, bed and thickness",
        state: kinds.has("lyra-run-echoes") || kinds.has("lyra-echoes-csv") ? "complete" : running && livePhase === "phase4" ? "active" : "waiting" }
    ];
    const workflow = `<ol class="fl-automatic-phases" aria-label="LYRA processing phases">${phases.map(phase => `
      <li class="${phase.state}">
        <span class="fl-automatic-phase-number">${phase.state === "complete" ? "✓" : phase.number}</span>
        <span><strong>${escapeHtml(phase.title)}</strong><small>${escapeHtml(phase.note)}</small></span>
      </li>`).join("")}</ol>`;
    if (guidance) return workflow;
    return `${workflow}<div class="fl-automatic-guidance required" role="status">
      <div><strong>Step 2 needs a scientist’s guidance</strong><span>Mark the main bang, −60 dB reference line, and X-grid lines in LYRA’s calibration picker. Upload its JSON here; the next run will automatically execute Calibration and Echoes.</span></div>
      <span class="fl-automatic-guidance-actions"><button type="button" class="fl-radar-button primary" data-upload-guidance>Upload LYRA calibration picks</button><a href="/applications/frozen_legacies/user_manual.html#automatic-picking-lyra">Calibration instructions</a></span>
    </div>`;
  }


  // The picker's per-frame values (as written in its CSV), the heuristic
  // frame QC flags with their reasons, and links to its own diagnostic images.
  function framesHtml(frames, picker) {
    if (!frames?.rows?.length) {
      return "";
    }
    // Frame and CBD lead, then the flags and images (visible without
    // scrolling on narrow screens), then the picker's remaining values
    const lead = 2;
    const header = c => `<th scope="col">${escapeHtml(c.replaceAll("_", " "))}</th>`;
    const head = frames.columns.slice(0, lead).map(header).join("")
      + `<th scope="col">QC flags (heuristic)</th><th scope="col">${escapeHtml(picker)} diagnostic images</th>`
      + frames.columns.slice(lead).map(header).join("");
    const visibleRows = state.frameFilter === "flagged"
      ? frames.rows.filter(row => row.flags?.length > 0)
      : frames.rows;
    const rows = visibleRows.map(row => {
      const flagged = row.flags?.length > 0;
      const flags = flagged
        ? `<span class="fl-astra-chip fl-automatic-flag">Inspect</span> ${row.flags.map(f => escapeHtml(f)).join("; ")}`
        : `<span class="fl-automatic-none">—</span>`;
      const images = (row.images || []).map(diagnosticButton).join("");
      return `
        <tr class="${flagged ? "flagged" : ""}">
          ${row.values.slice(0, lead).map(v => `<td>${escapeHtml(v)}</td>`).join("")}
          <td class="fl-automatic-flags">${flags}</td>
          <td class="fl-automatic-diags">${images || `<span class="fl-automatic-none">not kept</span>`}</td>
          ${row.values.slice(lead).map(v => `<td>${escapeHtml(v)}</td>`).join("")}
        </tr>`;
    }).join("");
    let viewer = "";
    const strip = frames.strip_images || [];
    const selected = frames.rows.flatMap(r => r.images || []).concat(strip)
      .find(i => i.product_id === state.diagnostic);
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
      <details class="fl-automatic-frames">
        <summary>Frame diagnostics (${escapeHtml(picker)}) · ${frames.rows.length} frame${frames.rows.length === 1 ? "" : "s"}${
          frames.flagged ? ` · ${frames.flagged} flagged for inspection` : ""}
          <span class="fl-astra-chip fl-unvalidated">${escapeHtml(frames.label)}</span></summary>
        <p class="fl-automatic-note">${escapeHtml(frames.note)}</p>
        ${frames.diagnostic_images ? "" : `<p class="fl-automatic-note">${escapeHtml(picker)}'s diagnostic images were not kept for this run; run automatic picking again to keep them.</p>`}
        <div class="fl-automatic-diagnostics-toolbar">
          <span class="fl-automatic-strip">${strip.length ? `Whole strip: ${strip.map(diagnosticButton).join("")}` : ""}</span>
          ${frames.flagged ? `<span class="fl-automatic-filter" role="group" aria-label="Filter diagnostic frames">
            <button type="button" class="${state.frameFilter === "all" ? "active" : ""}" data-frame-filter="all">All ${frames.rows.length}</button>
            <button type="button" class="${state.frameFilter === "flagged" ? "active" : ""}" data-frame-filter="flagged">Needs review ${frames.flagged}</button>
          </span>` : ""}
        </div>
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
    // the configured picker (new runs) and the one whose results are shown
    const picker = info.picker_label || "URSA";
    const shown = job?.picker_label || picker;
    const running = active();
    const lines = [];
    const products = info.products || [];

    if (!info.has_radar) {
      lines.push(`<p class="fl-automatic-note">This asset holds processed products only; there is no raw radar to pick.</p>`);
    } else if (!availability.available) {
      lines.push(`
        <div class="fl-automatic-unavailable" role="status">
          <span class="fl-automatic-unavailable-icon" aria-hidden="true">!</span>
          <div>
            <strong>Automatic picking (${escapeHtml(picker)}) is not available on this server.</strong>
            <span>${escapeHtml(availability.reason || "")}</span>
            <span>No automatic results have been produced. Manual picking is available in <strong>Manual</strong>.</span>
          </div>
        </div>`);
    } else {
      lines.push(`<div class="fl-automatic-intro"><span class="fl-automatic-kicker">${escapeHtml(picker)} workflow</span><p>${escapeHtml(INTROS[picker] || "")}</p></div>`);
      const env = availability.environment;
      if (env) {
        const v = env.packages || {};
        const packages = (ENVIRONMENT_PACKAGES[picker] || [])
          .map(([label, key]) => ` · ${label} ${escapeHtml(v[key] || "?")}`).join("");
        lines.push(`<details class="fl-automatic-runtime"><summary>Runtime details</summary><p>${escapeHtml(picker)} environment checked: Python ${escapeHtml(env.python)}${packages}</p></details>`);
      }
      const lyra = info.lyra;
      if (lyra?.runnable) {
        const picks = lyra.guidance?.picks;
        if (!picks) {
          lines.push(`<div class="fl-automatic-guidance"><div><strong>Frame detection is ready</strong><span>Run now for frames and CBDs. To also calibrate and extract echoes, add LYRA's human calibration guidance first.</span></div><span class="fl-automatic-guidance-actions"><button type="button" class="fl-radar-button" data-upload-guidance>Upload calibration picks</button><a href="/applications/frozen_legacies/user_manual.html#automatic-picking-lyra">How to create them</a></span></div>`);
        } else {
          lines.push(`<div class="fl-automatic-guidance ready"><strong>Calibration guidance ready</strong><span>${escapeHtml(picks.name)} · ${escapeHtml(String(picks.summary?.rows ?? "?"))} frames with guidance</span></div>`);
        }
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
    if (info.warnings?.length) {
      lines.push(`<details class="fl-automatic-warnings"><summary>${info.warnings.length} item${info.warnings.length === 1 ? "" : "s"} to review before running</summary><ul>${info.warnings.map(w => `<li>${escapeHtml(w)}</li>`).join("")}</ul></details>`);
    }

    const canRun = info.has_radar && availability.available && info.lyra?.runnable !== false
      && !running && !state.busy;
    const action = running
      ? `<button type="button" class="fl-radar-button" data-automatic="cancel" ${state.busy ? "disabled" : ""}>Cancel</button>`
      : `<button type="button" class="fl-radar-button primary" data-automatic="start" ${canRun ? "" : "disabled"}>${
          !availability.available && info.has_radar
            ? "Run automatic picking (unavailable)"
            : job && job.status === "completed" ? "Run automatic picking again" : "Run automatic picking"}</button>`;

    let status = "";
    if (job) {
      const guidanceRequired = job.picker === "lyra" && job.summary?.stopped === "calibration-guidance-required";
      status = `
        <div class="fl-automatic-status ${escapeHtml(job.status)}">
          <span class="fl-astra-chip ${job.status === "completed" && !guidanceRequired ? "complete" : ""}">${escapeHtml(guidanceRequired ? "Guidance required" : (STATUS_LABELS[job.status] || job.status))}</span>
          <span>${escapeHtml(job.message || "")}${job.started_at ? ` · ${escapeHtml(elapsed(job))}` : ""}</span>
        </div>
        ${job.log_tail?.length ? `<details class="fl-automatic-log"><summary>${escapeHtml(shown)} log</summary><pre>${escapeHtml(job.log_tail.join("\n"))}</pre></details>` : ""}`;
    }

    let results = "";
    if (products.length) {
      const verification = products.find(p => p.kind === "ursa-verification" && p.preview_url);
      const picks = products.find(p => ["ursa-csv", "lyra-run-echoes"].includes(p.kind))
        || products.find(p => p.kind === "lyra-frame-index");
      results = `
        <section class="fl-automatic-results" aria-labelledby="fl-automatic-results-title">
          <div class="fl-automatic-section-heading"><div><span class="fl-automatic-kicker">Latest run</span><h3 id="fl-automatic-results-title">${escapeHtml(shown)} results</h3></div><span class="fl-astra-chip fl-unvalidated">Scientifically unvalidated</span></div>
          ${picks ? `<p class="fl-automatic-note">${escapeHtml(window.FrozenLegaciesProducts?.summaryText(picks) || "")}</p>` : ""}
          ${picks ? (window.FrozenLegaciesProducts?.qcWarnings?.(picks) || []).map(w =>
            `<p class="fl-automatic-warning">${escapeHtml(w)}</p>`).join("") : ""}
          <div class="fl-astra-downloads">${products.filter(p => p.download_url).map(p =>
            `<a class="fl-radar-button" href="${escapeHtml(p.download_url)}" download>${escapeHtml(p.title)}</a>`).join("")}</div>
          ${verification ? `<img class="fl-automatic-preview" src="${escapeHtml(verification.preview_url)}" alt="URSA frame verification">` : ""}
          ${framesHtml(info.frames, shown)}
        </section>`;
    }

    root.innerHTML = `
      <section class="fl-automatic-run-card" aria-label="Automatic picking setup">
        ${lines.join("")}
        ${phaseHtml(info, products, picker)}
        <div class="fl-automatic-run-row"><div class="fl-automatic-actions">${action}</div>${status}</div>
        ${state.error ? `<p class="fl-automatic-warning">${escapeHtml(state.error)}</p>` : ""}
      </section>
      ${results}`;
    root.querySelectorAll("[data-automatic]").forEach(button => {
      button.addEventListener("click", () => act(button.dataset.automatic));
    });
    root.querySelectorAll("[data-upload-guidance]").forEach(button => button.addEventListener("click", () => {
      window.FrozenLegaciesProducts?.openUpload?.("lyra-guidance");
    }));
    root.querySelectorAll("[data-diagnostic]").forEach(button => {
      button.addEventListener("click", () => {
        state.diagnostic = state.diagnostic === button.dataset.diagnostic ? null : button.dataset.diagnostic;
        render();
      });
    });
    root.querySelectorAll("[data-frame-filter]").forEach(button => {
      button.addEventListener("click", () => {
        state.frameFilter = button.dataset.frameFilter;
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
        state.frameFilter = "all";
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
      state.frameFilter = "all";
      const root = $("fl-automatic");
      if (root) {
        root.hidden = true;
        root.innerHTML = "";
      }
    },

    refresh() {
      return load();
    },

    get info() {
      return state.info;
    }
  };

})();
