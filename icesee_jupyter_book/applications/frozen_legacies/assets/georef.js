/* ============================================================
 * Frozen Legacies
 * georef.js
 *
 * Manual result view: georeferencing of the committed A-scopes.
 *
 * ASTRA assigns CBDs by spreading the file name's CBD range over
 * the committed rows; when a film is missing frames this differs
 * from the CBD printed on the frame. Here the user reads the label
 * of each A-scope's frame and confirms it (or marks it unreadable).
 * The ASTRA CSV/QC are unchanged; the georeferenced CSV is a
 * separate product. Nothing is guessed: unconfirmed A-scopes stay
 * "unverified".
 * ============================================================ */


(function () {

  "use strict";

  const API = "/frozen-legacies/api/assets";

  const STATUS = {
    unverified: ["Unverified · ASTRA-assigned", "pending"],
    verified: ["Verified", "published"],
    verified_no_navigation: ["Confirmed · no navigation", "returned"],
    label_unreadable: ["Label unreadable", "rejected"]
  };

  function chip(status) {
    const [label, kind] = STATUS[status] || [status, "pending"];
    return `<span class="fl-review-chip ${kind}">${escapeHtml(label)}</span>`;
  }


  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }


  function position(p) {
    return p ? `${p[1].toFixed(4)}, ${p[0].toFixed(4)}` : "—";
  }


  async function request(url, body) {
    const response = await fetch(url, body === undefined
      ? { credentials: "same-origin" }
      : {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
        });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    return data;
  }


  function frameUrl(asset, windowX) {
    const width = asset.image.width;
    const x = Math.max(0, Math.min((windowX ?? 0) - 1500, width - 1));
    const span = Math.min(4500, width - x);
    return window.FrozenLegaciesRadarGeometry.viewUrl(asset.asset_id, x, span, 4);
  }


  // the georeferenced (and, once approved, published) CBD and position:
  // the confirmed film CBD where verified, nothing for unreadable or
  // unnavigated frames, otherwise ASTRA's own -- labelled unverified
  function georeferenced(o) {
    if (o.geolocation_status === "verified") {
      return `<strong>${escapeHtml(o.verified_cbd)}</strong><br><small>${position(o.verified_position)}</small>`;
    }
    if (o.geolocation_status === "verified_no_navigation") {
      return `<strong>${escapeHtml(o.verified_cbd)}</strong><br><small>no navigation record · not mapped</small>`;
    }
    if (o.geolocation_status === "label_unreadable") {
      return `—<br><small>not mapped</small>`;
    }
    return `${escapeHtml(o.astra_cbd ?? "—")}<br><small>ASTRA's position, unverified</small>`;
  }


  function rowHtml(asset, o) {
    const confirmed = o.verified_cbd !== null;
    return `<tr data-ascope="${o.a_scope}" class="fl-georef-${escapeHtml(o.geolocation_status)}${o.cbd_differs ? " fl-georef-differs" : ""}">
      <td>${o.a_scope}</td>
      <td>${escapeHtml(o.astra_cbd ?? "—")}<br><small>${position(o.astra_position)}</small></td>
      <td class="fl-georef-entry">
        <div class="fl-georef-entry-row">
          <input type="number" min="0" max="99999" step="1" inputmode="numeric"
                 aria-label="Film CBD printed on the frame of A-scope ${o.a_scope}"
                 placeholder="label" value="${confirmed ? o.verified_cbd : ""}">
          <button type="button" class="fl-radar-button primary" data-georef="confirm">Confirm</button>
        </div>
        <div class="fl-georef-entry-row">
          <button type="button" class="fl-radar-button" data-georef="frame" aria-expanded="false">Show frame</button>
          <button type="button" class="fl-radar-button subtle" data-georef="unreadable">Unreadable</button>
          ${o.geolocation_status !== "unverified"
            ? `<button type="button" class="fl-radar-button subtle" data-georef="clear">Clear</button>` : ""}
        </div>
      </td>
      <td>${georeferenced(o)}</td>
      <td>${chip(o.geolocation_status)}${o.cbd_differs ? `<br><small>differs from ASTRA</small>` : ""}</td>
    </tr>
    <tr class="fl-georef-frame" data-frame="${o.a_scope}" hidden>
      <td colspan="5"><img alt="Radar frame around A-scope ${o.a_scope}; the film CBD is printed on the frame" loading="lazy"
        data-src="${escapeHtml(frameUrl(asset, o.window_x))}"></td>
    </tr>`;
  }


  function calloutHtml(s) {
    if (!s.total) {
      return "";
    }
    const done = s.unverified === 0;
    const parts = [`<strong>${s.verified}</strong> of ${s.total} verified`];
    if (s.verified_no_navigation) parts.push(`${s.verified_no_navigation} without navigation`);
    if (s.label_unreadable) parts.push(`${s.label_unreadable} unreadable`);
    if (s.unverified) parts.push(`<strong>${s.unverified}</strong> unconfirmed`);
    return `<div class="fl-georef-callout ${done ? "done" : ""}">
      <div><div class="fl-georef-callout-title">Film CBD ${done ? "confirmed" : "not yet confirmed"}</div>
        <div class="fl-georef-callout-text">${parts.join(" · ")}. ${done
          ? "Positions use the CBD printed on each frame where verified."
          : "ASTRA's CBDs come from the file name; confirm the CBD printed on each frame to verify positions."}</div></div>
      <button type="button" class="fl-radar-button ${done ? "" : "primary"}" data-georef-open>
        ${done ? "Review confirmations" : "Confirm film CBDs"}</button>
    </div>`;
  }


  function render(box, asset, state) {
    const s = state.summary;
    const rows = state.observations.map(o => rowHtml(asset, o)).join("");
    box.querySelector(".fl-georef-body").innerHTML = `
      <p class="fl-georef-intro">ASTRA assigns CBDs from the file name's range
        (${escapeHtml(state.cbd_range[0] ?? "?")}–${escapeHtml(state.cbd_range[1] ?? "?")})
        in the order A-scopes were committed. If the film skips frames, that differs from
        the CBD printed on the frame. Select <strong>Show frame</strong>, read the label
        (for example <span class="fl-georef-label">127 0478</span> is CBD 478) and confirm it.
        Positions are verified only for confirmed CBDs. Your ASTRA CSV and QC are not changed.</p>
      ${state.has_navigation ? "" : `<p class="fl-georef-warning">This radar has no navigation file:
        confirmed CBDs cannot be positioned.</p>`}

      ${state.warnings.map(w => `<p class="fl-georef-warning">${escapeHtml(w)}</p>`).join("")}
      <div class="fl-astra-table-wrap">
        <table class="fl-astra-table fl-georef-table">
          <thead><tr><th>A-scope</th><th>ASTRA-assigned CBD · position</th><th>Film CBD (printed on the frame)</th>
            <th>Georeferenced CBD · position</th><th>Geolocation</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="5">No A-scopes were committed.</td></tr>`}</tbody>
        </table>
      </div>
      <p class="fl-georef-error" role="alert"></p>
      <div class="fl-astra-downloads">
        <a class="fl-radar-button" href="${escapeHtml(state.product.url)}" download>
          ${escapeHtml(state.product.name)}</a>
        <a class="fl-radar-button" href="${escapeHtml(state.product.provenance_url)}" download>
          Provenance (JSON)</a>
      </div>`;
    box.querySelector(".fl-georef-status").textContent =
      `${s.verified} of ${s.total} verified`;
    const callout = box.parentElement.querySelector(".fl-georef-callout-host");
    if (callout) {
      callout.innerHTML = calloutHtml(s);
      callout.querySelector("[data-georef-open]")?.addEventListener("click", () => {
        box.open = true;
        box.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
    bind(box, asset);
  }


  function bind(box, asset) {
    box.querySelectorAll("[data-georef]").forEach(button => {
      button.addEventListener("click", async () => {
        const row = button.closest("tr");
        const aScope = Number(row.dataset.ascope);
        const action = button.dataset.georef;
        if (action === "frame") {
          const frame = box.querySelector(`[data-frame="${aScope}"]`);
          const img = frame.querySelector("img");
          if (!img.src) {
            img.src = img.dataset.src;
          }
          frame.hidden = !frame.hidden;
          button.setAttribute("aria-expanded", String(!frame.hidden));
          button.textContent = frame.hidden ? "Show frame" : "Hide frame";
          return;
        }
        const body = { action, a_scope: aScope };
        if (action === "confirm") {
          const value = row.querySelector("input").value.trim();
          if (!/^\d{1,5}$/.test(value)) {
            box.querySelector(".fl-georef-error").textContent =
              "Enter the CBD printed on the frame (a whole number).";
            return;
          }
          body.film_cbd = Number(value);
        }
        try {
          render(box, asset, await request(`${API}/${asset.asset_id}/georef`, body));
        } catch (error) {
          box.querySelector(".fl-georef-error").textContent = error.message;
        }
      });
    });
  }


  async function mount(container, asset) {
    if (!container || !asset) {
      return;
    }
    let box = container.querySelector(".fl-georef");
    let first = false;
    if (!box) {
      first = true;
      box = document.createElement("details");
      box.className = "fl-georef";
      box.id = "fl-georef";
      box.innerHTML = `<summary>Georeferencing — film CBD
        <span class="fl-georef-status"></span></summary><div class="fl-georef-body">Loading…</div>`;
      // after the ASTRA table, before the review and the session actions
      const actions = container.querySelector(".fl-review-host, .fl-astra-result-actions");
      container.insertBefore(box, actions || null);
      // a short status line near the top of the result, so it is found
      const host = document.createElement("div");
      host.className = "fl-georef-callout-host";
      const downloads = container.querySelector(".fl-astra-downloads");
      container.insertBefore(host, downloads ? downloads.nextSibling : container.firstChild);
    }
    try {
      const state = await request(`${API}/${asset.asset_id}/georef`);
      if (first && state.summary.unverified > 0) {
        box.open = true;                  // unconfirmed CBDs: show the table
      }
      render(box, asset, state);
    } catch (error) {
      box.querySelector(".fl-georef-body").textContent = error.message;
    }
  }


  window.FrozenLegaciesGeoref = { mount };

})();
