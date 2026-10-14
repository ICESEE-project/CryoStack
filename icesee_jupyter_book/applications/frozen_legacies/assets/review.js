/* ============================================================
 * Frozen Legacies
 * review.js
 *
 * Scientific review from the user's side:
 *
 *   - in the Manual result view: the result's review status and
 *     "Submit for review" (a frozen snapshot is reviewed; the
 *     canonical ASTRA CSV/QC are never changed by a review);
 *   - on the Map: "My results" -- what is awaiting review, returned
 *     for correction, or published, with a way back to each asset.
 *
 * Decisions are made by reviewers in the Control Center.
 * ============================================================ */


(function () {

  "use strict";

  const API = "/frozen-legacies/api";

  const STATUS = {
    submitted: ["Awaiting review", "pending"],
    returned: ["Returned for correction", "returned"],
    rejected: ["Rejected", "rejected"],
    published: ["Published", "published"],
    withdrawn: ["Withdrawn", "rejected"],
    superseded: ["Superseded by a newer version", "returned"],
    cancelled: ["Submission cancelled", "returned"]
  };

  const state = { mine: null, onChange: () => {}, openAsset: null };


  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }


  function when(t) {
    return t ? new Date(t * 1000).toLocaleString() : "";
  }


  async function request(path, body) {
    const response = await fetch(`${API}${path}`, {
      method: body ? "POST" : "GET", credentials: "same-origin", cache: "no-store",
      headers: body ? { "Content-Type": "application/json", Accept: "application/json" }
                    : { Accept: "application/json" },
      body: body ? JSON.stringify(body) : undefined
    });
    const json = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(json?.error || `Request failed (HTTP ${response.status}).`);
    }
    return json;
  }


  /* ----------------------------------------------------------
   * Manual result view
   * ---------------------------------------------------------- */

  function chip(status) {
    const [label, kind] = STATUS[status] || [status, "pending"];
    return `<span class="fl-review-chip ${kind}">${escapeHtml(label)}</span>`;
  }


  function blockHtml(review) {
    const latest = review.submissions[0];
    let body = "";
    if (latest) {
      body += `<p class="fl-radar-panel-note">${chip(latest.status)}
        Version ${latest.session_revision} · ${latest.observation_count} observation${latest.observation_count === 1 ? "" : "s"}
        · submitted ${escapeHtml(when(latest.submitted_at))}</p>`;
      // edits after a submission or publication are not part of that version
      const stage = review.stage;
      const layer = window.FrozenLegaciesUserLayer;
      if (stage && layer && (stage.changed_since_submission
          || (stage.published_submission_id && stage.stage !== "published"))) {
        body += `<p class="fl-review-note" data-review-stage="${escapeHtml(stage.stage)}">${
          layer.stageChip(stage)}Your current result: ${escapeHtml(layer.stageNote(stage))}.</p>`;
      }
      if (latest.decision_note) {
        body += `<p class="fl-review-note"><strong>Reviewer:</strong> ${escapeHtml(latest.decision_note)}</p>`;
      }
      if (latest.status === "withdrawn" && latest.withdraw_reason) {
        body += `<p class="fl-review-note"><strong>Withdrawn:</strong> ${escapeHtml(latest.withdraw_reason)}</p>`;
      }
      if (latest.status === "published") {
        body += `<p class="fl-radar-panel-note">Published as a shared dataset product
          (<a href="${API}/published/${encodeURIComponent(latest.submission_id)}/products/provenance">provenance</a>).
          Your own result here stays unchanged.</p>`;
      }
      if (latest.status === "submitted") {
        body += `<button type="button" class="fl-radar-button" data-review-cancel="${escapeHtml(latest.submission_id)}">Cancel submission</button>`;
      }
    } else {
      body += `<p class="fl-radar-panel-note">Not submitted. A reviewer checks a frozen copy of this
        result; approved results are published to the shared map with their provenance.</p>`;
    }
    if (review.can_submit) {
      body += `
        <details class="fl-review-submit">
          <summary>${latest ? "Submit this version for review" : "Submit for review"}</summary>
          <p class="fl-radar-panel-note">A-scopes without a confirmed film CBD are submitted with
            ASTRA's CBD and position, marked <strong>unverified</strong>; a reviewer must accept that explicitly.</p>
          <textarea data-review-note rows="3" maxlength="2000"
            placeholder="Optional note to the reviewer (for example, which A-scopes need attention)"></textarea>
          <button type="button" class="fl-radar-button primary" data-review-submit>Submit for review</button>
        </details>`;
    } else if (review.reason && !latest) {
      body += `<p class="fl-radar-panel-note">${escapeHtml(review.reason)}</p>`;
    }
    return `<div class="fl-review-block"><div class="fl-review-title">Scientific review</div>${body}
      <p class="fl-review-error" data-review-error hidden></p></div>`;
  }


  async function mount(container, asset) {
    if (!container || !asset) {
      return;
    }
    let host = container.querySelector(".fl-review-host");
    if (!host) {
      host = document.createElement("div");
      host.className = "fl-review-host";
      const actions = container.querySelector(".fl-astra-result-actions");
      container.insertBefore(host, actions || null);
    }
    let review;
    try {
      review = await request(`/assets/${encodeURIComponent(asset.asset_id)}/review`);
    } catch (error) {
      host.innerHTML = "";
      return;
    }
    host.innerHTML = blockHtml(review);
    const fail = error => {
      const line = host.querySelector("[data-review-error]");
      line.textContent = error.message;
      line.hidden = false;
    };
    host.querySelector("[data-review-submit]")?.addEventListener("click", async event => {
      event.target.disabled = true;
      try {
        await request(`/assets/${encodeURIComponent(asset.asset_id)}/review`, {
          action: "submit", note: host.querySelector("[data-review-note]").value
        });
        await mount(container, asset);
        reload();
      } catch (error) {
        event.target.disabled = false;
        fail(error);
      }
    });
    host.querySelector("[data-review-cancel]")?.addEventListener("click", async event => {
      if (!window.confirm("Cancel this submission? You can submit again later.")) {
        return;
      }
      try {
        await request(`/assets/${encodeURIComponent(asset.asset_id)}/review`, {
          action: "cancel", submission_id: event.target.dataset.reviewCancel
        });
        await mount(container, asset);
        reload();
      } catch (error) {
        fail(error);
      }
    });
  }


  /* ----------------------------------------------------------
   * Map panel: My results
   * ---------------------------------------------------------- */

  async function reload() {
    try {
      state.mine = (await request("/reviews/mine")).submissions || [];
    } catch (error) {
      state.mine = null;
    }
    state.onChange();
  }


  function panelHtml() {
    const items = state.mine;
    if (!items || !items.length) {
      return "";
    }
    // the latest submission of each asset is its current review state
    const latest = new Map();
    items.forEach(s => {
      if (!latest.has(s.asset_id)) {
        latest.set(s.asset_id, s);
      }
    });
    const current = [...latest.values()];
    const count = status => current.filter(s => s.status === status).length;
    const rows = current.slice(0, 8).map(s => `
      <div class="fl-radar-link">
        <div><strong>${escapeHtml(s.filename)}</strong>
          <span>${chip(s.status)} F${escapeHtml(s.flight ?? "?")} · ${s.observation_count} obs.</span></div>
        <button type="button" class="fl-radar-button" data-review-open="${escapeHtml(s.asset_id)}">Open</button>
      </div>`).join("");
    return `
      <div class="fl-record-section">
        <div class="fl-record-section-title">My results</div>
        <p class="fl-radar-panel-note">${count("submitted")} awaiting review · ${count("returned")} returned for correction
          · ${count("published")} published</p>
        ${rows}
        ${current.length > 8 ? `<p class="fl-radar-panel-note">and ${current.length - 8} more.</p>` : ""}
      </div>`;
  }


  function bindPanel(root, { openAsset }) {
    root.querySelectorAll("[data-review-open]").forEach(button => {
      button.addEventListener("click", () => openAsset(button.dataset.reviewOpen));
    });
  }


  function initialize({ onChange }) {
    state.onChange = onChange || (() => {});
    reload();
  }


  window.FrozenLegaciesReview = { mount, initialize, reload, panelHtml, bindPanel };

})();
