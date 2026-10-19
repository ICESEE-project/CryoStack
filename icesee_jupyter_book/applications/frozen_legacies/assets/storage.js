/* ============================================================
 * Frozen Legacies
 * storage.js
 *
 * Workspace storage beside the upload buttons ("Storage: 1.2 GiB
 * / 2 GiB") and a check before each upload: a file larger than
 * the per-file limit or the remaining allowance is not sent, and
 * the form says why. The server enforces the same limits
 * (storage_routes.py); this only saves a doomed upload.
 * ============================================================ */


(function () {

  "use strict";

  const API = "/frozen-legacies/api/storage/usage";
  const FORMS = {
    "fl-radar-upload": "fl-radar-upload-status",
    "fl-product-upload": "fl-product-upload-status"
  };

  const state = { usage: null, timer: null };


  function formatBytes(bytes) {
    let value = Number(bytes || 0);
    const units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let i = 0;
    while (Math.abs(value) >= 1024 && i < units.length - 1) {
      value /= 1024;
      i += 1;
    }
    return i ? `${value.toFixed(1)} ${units[i]}` : `${value} B`;
  }


  function render() {
    const badge = document.getElementById("fl-storage-usage");
    const usage = state.usage;
    if (!badge || !usage) {
      return;
    }
    badge.hidden = false;
    badge.className = `fl-storage-usage ${usage.status}`;
    badge.textContent = `Storage: ${formatBytes(usage.used_bytes)} / ${formatBytes(usage.quota_bytes)}`;
    badge.title = usage.status === "over"
      ? "Your workspace is over its storage quota: existing files stay available, but new uploads and results are blocked until you remove files or an administrator raises the quota."
      : `${formatBytes(usage.available_bytes)} available · uploads up to ${formatBytes(usage.max_upload_bytes)} per file`;
  }


  async function refresh() {
    try {
      const response = await fetch(API, { credentials: "same-origin", headers: { Accept: "application/json" } });
      if (!response.ok) {
        return;
      }
      state.usage = await response.json();
      render();
    } catch (error) {
      // the badge is informative only; uploads are checked by the server
    }
  }


  function refreshSoon() {
    window.clearTimeout(state.timer);
    state.timer = window.setTimeout(refresh, 500);
  }


  /* Runs before each form's own submit handler (capture phase on the
   * document): an upload that cannot fit is stopped here. */
  function checkUpload(event) {
    const statusId = FORMS[event.target?.id];
    const usage = state.usage;
    if (!statusId || !usage) {
      return;
    }
    const files = [...event.target.querySelectorAll('input[type="file"]')]
      .flatMap(input => [...(input.files || [])]);
    const largest = files.reduce((max, f) => Math.max(max, f.size), 0);
    const total = files.reduce((sum, f) => sum + f.size, 0);
    let message = null;
    if (usage.status === "over") {
      message = `Your workspace uses ${formatBytes(usage.used_bytes)} of its ${formatBytes(usage.quota_bytes)} quota, so new uploads are blocked. Your files remain available; remove files you no longer need, or ask an administrator for more storage.`;
    } else if (largest > usage.max_upload_bytes) {
      message = `This file is larger than the ${formatBytes(usage.max_upload_bytes)} upload limit.`;
    } else if (total > usage.available_bytes) {
      message = `This upload needs ${formatBytes(total)}, but only ${formatBytes(usage.available_bytes)} of your ${formatBytes(usage.quota_bytes)} storage is available.`;
    }
    if (message) {
      event.preventDefault();
      event.stopImmediatePropagation();
      const status = document.getElementById(statusId);
      if (status) {
        status.textContent = message;
      }
    }
  }


  function init() {
    document.addEventListener("submit", checkUpload, true);
    // an upload or a removal changes the usage: refresh after each one
    Object.values(FORMS).forEach(id => {
      const status = document.getElementById(id);
      if (status) {
        new MutationObserver(refreshSoon).observe(status, { childList: true, characterData: true, subtree: true });
      }
    });
    window.addEventListener("focus", refreshSoon);
    refresh();
  }


  window.FrozenLegaciesStorage = {
    refresh: refreshSoon,
    get usage() {
      return state.usage;
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
