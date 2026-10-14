"""Markup and script of the Control Center page ``/control/livist``.

Static: everything user-specific is loaded from ``/api/livist/`` and
rendered with escaping. Maintainer-only sections are hidden for other roles
(the API enforces the same rules).
"""
from icesee_jupyter_book.applications.frozen_legacies.control_style import STYLE

_SCRIPT = r"""
(function () {
  const api = "/api/livist";
  const $ = id => document.getElementById(id);
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"})[c]);
  const when = t => t ? new Date(t * 1000).toLocaleString() : "—";
  const bytes = n => n == null ? "—" : n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB";
  const short = s => s ? String(s).slice(0, 12) : "—";
  const PILL = {completed: "ok", passed: "ok", ready: "ok", approved: "ok", published: "ok",
    running: "info", queued: "info", pending: "info", warnings: "warn", cancelled: "muted",
    rejected: "muted", interrupted: "warn", timed_out: "bad", failed: "bad"};
  const pill = (s, label) => `<span class="status-pill ${PILL[s] || "muted"}">${esc(label || String(s || "—").replace("_", " "))}</span>`;
  let state = {status: null, scope: "mine", open: new Set(), timer: null, pick: new Set()};
  const VPILL = {passed: "passed", warnings: "warnings", failed: "failed", "not-checked": "cancelled", unvalidated: "cancelled", partial: "warnings"};
  const VLABEL = {passed: "Validated", warnings: "Validated, warnings", failed: "Failed validation", "not-checked": "Not checked", unvalidated: "Unvalidated", partial: "Partial, not a product"};
  const upstream = d => !d || !d.recorded ? "ETag, Last-Modified not recorded" : `ETag ${d.etag || "—"} · Last-Modified ${d.last_modified || "—"}${d.upstream_checked ? "" : " (source.coop not rechecked)"}`;
  const IDPILL = {identical: ["passed", "Identical"], differ: ["failed", "Differs"], missing: ["warnings", "Missing"], unknown: ["cancelled", "No checksum"]};
  const PUBLABEL = {"not-requested": "Not published", pending: "Not published · request pending", rejected: "Not published · request rejected",
    failed: "Not published · request failed", "dry-run-approved": "Not published · approved as a dry run", approved: "Upload in progress", published: "Published"};
  const shaCell = sha => sha ? `<span class="fl-mono" title="${esc(sha)}">${esc(short(sha))}</span> <button class="fl-btn quiet" type="button" data-copy="${esc(sha)}" aria-label="Copy full SHA-256">Copy</button>` : "—";
  const num = (v, unit) => v == null ? "—" : unit === "bytes" ? bytes(v) : `${v} ${unit}`;

  async function get(url) {
    const r = await fetch(url, {credentials: "same-origin"});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
    return j;
  }
  async function post(url, body) {
    const r = await fetch(url, {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(j.error || ("HTTP " + r.status)); e.plan = j.plan; throw e; }
    return j;
  }
  function notice(id, kind, html) {
    $(id).innerHTML = html ? `<p class="fl-notice ${kind}" role="${kind === "bad" ? "alert" : "status"}">${html}</p>` : "";
  }

  function renderMetrics(s) {
    const t = s.toolchain, active = (state.jobs || []).filter(j => j.status === "running" || j.status === "queued").length;
    const pub = s.settings.publication;
    $("lv-metrics").innerHTML = [
      ["Environment", t.ready ? "Ready" : "Not ready", t.record ? "LIVIST " + short(t.record.livist_commit) : "not built"],
      ["Approved inputs", s.sources.length, "enabled for generation"],
      ["Active jobs", active, state.scope === "all" ? "all users" : "yours"],
      ["Publication", pub.enabled ? "Enabled" : "Dry run", pub.enabled ? "approved requests upload" : "nothing is uploaded"],
    ].map(([l, v, d]) => `<div class="metric-card"><div class="metric-label">${esc(l)}</div><div class="metric-value">${esc(v)}</div><div class="metric-detail">${esc(d)}</div></div>`).join("");
  }

  function renderToolchain(s) {
    const t = s.toolchain;
    $("lv-tool-state").innerHTML = t.ready ? pill("ready", "Ready") : pill("failed", "Not ready");
    $("lv-tools").innerHTML = t.checks.map(c => `<tr><td>${esc(c.label)}</td><td>${c.ok ? pill("ok", "OK") : pill(c.level === "warn" ? "warnings" : "failed", c.level === "warn" ? "Warning" : "Missing")}</td><td class="fl-mono">${esc(c.detail)}</td></tr>`).join("");
    const st = s.settings;
    $("lv-settings").innerHTML = [
      ["Environment", st.environment], ["Job outputs", st.output],
      ["Time limit", Math.round(st.timeout_s / 60) + " min"], ["Concurrent jobs", st.max_active],
      ["Approved input directories", st.input_roots], ["Publication target", st.publication.target],
    ].map(([k, v]) => `<div class="fl-kv"><span>${esc(k)}</span><strong class="fl-mono">${esc(v)}</strong></div>`).join("");
    $("lv-refresh").hidden = !s.viewer.maintainer;
  }

  function renderGenerate(s) {
    const box = $("lv-gen-sources");
    if (!s.sources.length) {
      box.innerHTML = `<p class="fl-help">No input is approved yet.${s.viewer.maintainer ? " Approve one under Inputs." : " Ask a maintainer to approve one."}</p>`;
    } else {
      const keep = new Set([...box.querySelectorAll("input:checked")].map(i => i.value));
      box.innerHTML = s.sources.map(src => `<label class="fl-check"><input type="checkbox" name="source" value="${esc(src.name)}" ${keep.has(src.name) ? "checked" : ""}>
        <span><strong>${esc(src.name)}</strong> · ${esc(src.kind)} · <span class="fl-mono">${esc(src.location)}</span>${src.description ? "<br><small>" + esc(src.description) + "</small>" : ""}</span></label>`).join("");
    }
    $("lv-gen-start").disabled = !s.viewer.can_generate || !s.toolchain.ready || !s.sources.length;
    $("lv-gen-why").textContent = !s.viewer.can_generate
      ? "Starting a generation is limited to maintainers, admins and owners."
      : !s.toolchain.ready ? "The LIVIST environment is not ready (see Toolchain)." : "";
  }

  async function loadSources() {
    if (!state.status.viewer.maintainer) return;
    const d = await get(api + "/sources");
    $("lv-sources").innerHTML = d.sources.length ? d.sources.map(src => `<tr>
      <td><strong>${esc(src.name)}</strong>${src.description ? "<br><small>" + esc(src.description) + "</small>" : ""}</td>
      <td>${esc(src.kind)}</td><td class="fl-mono">${esc(src.location)}</td>
      <td>${src.enabled ? pill("ok", "Enabled") : pill("cancelled", "Disabled")}</td>
      <td><button class="fl-btn" data-toggle="${esc(src.name)}" data-enabled="${src.enabled ? 0 : 1}">${src.enabled ? "Disable" : "Enable"}</button></td></tr>`).join("")
      : `<tr><td colspan="5" class="panel-empty">No approved inputs.</td></tr>`;
    const sel = $("lv-candidate");
    sel.innerHTML = `<option value="">Choose an input…</option>` + d.candidates.map(c =>
      `<option value="${esc(c.id)}" data-name="${esc(c.suggested_name)}">${esc(c.kind)} · ${esc(c.location)}${c.size != null ? " (" + bytes(c.size) + ")" : ""}</option>`).join("");
    $("lv-candidates-note").textContent = d.candidates.length ? "" :
      (d.input_roots ? "Every available input is already approved." : "No approved input directory is configured (CRYOSTACK_LIVIST_INPUT_ROOTS); only LIVIST's own source.coop inputs are offered.");
  }

  function jobRow(j) {
    const dur = j.started_at ? Math.round(((j.finished_at || Date.now() / 1000) - j.started_at)) + " s" : "—";
    const pick = j.status === "completed" ? `<input type="checkbox" data-pick="${esc(j.job_id)}" ${state.pick.has(j.job_id) ? "checked" : ""} aria-label="Select job ${esc(short(j.job_id))} for comparison">` : "";
    return `<tr data-job="${esc(j.job_id)}">
      <td>${pick}</td><td class="fl-mono">${esc(short(j.job_id))}</td>${state.scope === "all" ? `<td>${esc(j.owner)}</td>` : ""}
      <td>${esc(j.sources.join(", "))}</td><td>${pill(j.status)}${j.cancel_requested && j.status === "running" ? " <small>cancelling…</small>" : ""}</td>
      <td>${j.validation_status ? pill(j.validation_status) : "—"}</td><td>${esc(when(j.created_at))}</td><td class="num">${esc(dur)}</td>
      <td><button class="fl-btn quiet" data-open="${esc(j.job_id)}" aria-expanded="${state.open.has(j.job_id)}">${state.open.has(j.job_id) ? "Hide" : "Details"}</button></td></tr>
      <tr class="lv-detail" data-detail="${esc(j.job_id)}" ${state.open.has(j.job_id) ? "" : "hidden"}><td colspan="${state.scope === "all" ? 9 : 8}"><div id="lv-d-${esc(j.job_id)}">Loading…</div></td></tr>`;
  }

  async function loadJobs() {
    const d = await get(api + "/jobs" + (state.scope === "all" ? "?scope=all" : ""));
    state.jobs = d.jobs;
    $("lv-jobs-head").innerHTML = `<tr><th><span class="lv-sr">Compare</span></th><th>Job</th>${state.scope === "all" ? "<th>Owner</th>" : ""}<th>Inputs</th><th>Status</th><th>Validation</th><th>Started</th><th class="num">Duration</th><th></th></tr>`;
    $("lv-jobs").innerHTML = d.jobs.length ? d.jobs.map(jobRow).join("") :
      `<tr><td colspan="9" class="panel-empty">No generation jobs yet.</td></tr>`;
    const visible = new Set(d.jobs.filter(j => j.status === "completed").map(j => j.job_id));
    for (const id of [...state.pick]) if (!visible.has(id)) state.pick.delete(id);
    renderPick();
    for (const id of state.open) if (d.jobs.some(j => j.job_id === id)) loadDetail(id);
    renderMetrics(state.status);
    const active = d.jobs.some(j => j.status === "running" || j.status === "queued");
    clearTimeout(state.timer);
    if (active) state.timer = setTimeout(() => loadJobs().catch(() => {}), 5000);
  }

  async function loadDetail(id) {
    const box = $("lv-d-" + id);
    if (!box) return;
    try {
      const [j, log] = await Promise.all([get(`${api}/jobs/${id}`), get(`${api}/jobs/${id}/log`)]);
      const m = j.manifest || {};
      const v = m.validation;
      const files = productsHtml(j, id);
      const checks = v ? v.checks.filter(c => c.level !== "ok").map(c => `<li><strong>${esc(c.artifact)}</strong> · ${esc(c.check)}: ${esc(c.detail)}</li>`).join("") : "";
      const cacheNote = c => !c ? "" : c.cache === "hit" ? (c.upstream_checked ? " · from shared cache" : " · from shared cache (source.coop not rechecked)") : c.cache === "stored" ? " · added to shared cache" : "";
      const inputs = (m.inputs || []).map(i => `<span class="fl-chip" title="${esc(i.identity && i.identity.recorded ? "Observed: " + i.identity.observed : "Recorded before input identity was kept")}"><strong>${esc(i.name)}</strong> ${esc(i.kind)} ${esc(i.location)}${i.sha256 ? " · sha256 " + esc(short(i.sha256)) : ""}${esc(cacheNote(i.cache))}${i.kind === "source-coop" ? " · " + esc(upstream(i.identity)) : ""}</span>`).join("");
      const r = m.resources;
      const used = r && r.measured ? `<div class="fl-kv"><span>Measured use</span><strong>${esc(String(r.wall_s))} s wall · ${esc(String(Math.round((r.cpu_user_s + r.cpu_system_s) * 10) / 10))} s CPU · peak ${esc(String(r.peak_rss_mb))} MB RAM · ${bytes(r.workdir_bytes)} on disk</strong></div>` : "";
      const active = j.status === "running" || j.status === "queued";
      box.innerHTML = `<div class="fl-stack">
        ${j.error ? `<p class="fl-notice ${j.status === "cancelled" ? "info" : "bad"}"><strong>${j.status === "cancelled" ? "Cancelled" : "Reason"}:</strong> ${esc(j.error)}</p>` : ""}
        ${j.retry_of ? `<p class="fl-help">Retry of job <span class="fl-mono">${esc(short(j.retry_of))}</span> (a new run; nothing of that job was reused).</p>` : ""}
        ${j.manifest_missing ? `<p class="fl-notice warn">This job completed but its manifest was not written, so no products are listed; start a new generation.</p>` : ""}
        <div class="fl-kv-grid lv-tight">
          <div class="fl-kv"><span>Job</span><strong class="fl-mono">${esc(j.job_id)}</strong></div>
          <div class="fl-kv"><span>LIVIST commit</span><strong class="fl-mono">${esc(short(m.livist && m.livist.commit))}</strong></div>
          <div class="fl-kv"><span>Config SHA-256</span><strong class="fl-mono">${esc(short(j.config_sha256))}</strong></div>
          <div class="fl-kv"><span>Validation</span><strong>${v ? pill(v.status) + (v.deep ? "" : " <small>byte-level only</small>") : "—"}</strong></div>
          ${used}
        </div>
        ${inputs ? `<div class="fl-chips">${inputs}</div>` : ""}
        ${v ? (checks ? `<ul class="fl-list">${checks}</ul>` : `<p class="fl-help">All ${v.checks.length} checks passed (schema, rows, CRS, PMTiles header, FlatGeobuf, sources manifest).</p>`) : ""}
        ${files}
        <div class="fl-actions">
          ${active ? `<button class="fl-btn danger" data-cancel="${esc(id)}">Cancel</button>` : ""}
          ${j.mine && j.retryable && state.status.viewer.can_generate ? `<button class="fl-btn" data-retry="${esc(id)}">Retry as a new job</button>` : ""}
          ${j.mine && j.status === "completed" ? `<button class="fl-btn" data-validate="${esc(id)}">Validate again</button>` : ""}
          ${j.mine && m.artifacts ? `<a class="fl-btn" href="${api}/jobs/${id}/files/manifest.json">Manifest</a>` : ""}
          ${state.status.viewer.maintainer && j.status === "completed" ? `<button class="fl-btn" data-publish="${esc(id)}">Request publication…</button>` : ""}
        </div>
        <div data-job-notice="${esc(id)}"></div>
        <details ${active ? "open" : ""}><summary class="fl-help">Log${log.truncated ? " (last 64 KB)" : ""}</summary><pre class="lv-log">${esc(log.log || "No output yet.")}</pre></details>
      </div>`;
    } catch (e) { box.innerHTML = `<p class="fl-notice bad">${esc(e.message)}</p>`; }
  }

  function productsHtml(j, id) {
    const t = j.products;
    if (!t || !t.products.length) return t && t.complete === false ? `<p class="fl-notice warn">${esc(t.note)}</p>` : "";
    if (t.complete === false) return `<div class="fl-stack"><p class="fl-notice warn">${esc(t.note)}</p>
      <div class="fl-table-wrap"><table class="lv-files"><thead><tr><th>Partial file</th><th>Mode</th><th>Format</th><th class="num">Size</th></tr></thead><tbody>${t.products.map(p => `<tr><td class="fl-mono">${esc(p.name)} ${pill("warnings", "Partial")}</td><td>${esc(p.mode || "—")}</td><td>${esc(p.format)}</td><td class="num">${bytes(p.size)}</td></tr>`).join("")}</tbody></table></div></div>`;
    const n = t.products.length, c = t.counts || {};
    const ok = (c.passed || 0) + (c.warnings || 0);
    const pub = t.publication || {state: "not-requested"};
    const rows = t.products.map(p => `<tr>
      <td class="fl-mono">${esc(p.name)}${p.on_disk ? "" : ' <small class="lv-warn">no longer on disk at the recorded size</small>'}</td>
      <td>${esc(p.mode || "—")}</td><td>${esc(p.format)}</td><td class="num">${bytes(p.size)}</td><td>${shaCell(p.sha256)}</td>
      <td>${pill(VPILL[p.validation] || "cancelled", VLABEL[p.validation] || p.validation)}${p.findings.length ? `<br><small>${esc(p.findings.join("; "))}</small>` : ""}</td>
      <td>${p.published ? pill("published", "Published") : p.publishable ? "Not published" : "<small>not uploaded by LIVIST</small>"}</td>
      <td>${t.downloadable && p.on_disk ? `<a class="fl-btn quiet" href="${api}/jobs/${id}/files/${encodeURIComponent(p.name)}" download>Download</a>` : "—"}</td></tr>`).join("");
    const summary = !t.validation ? `<p class="fl-notice warn">These products are <strong>unvalidated</strong>: no validation result is recorded.</p>`
      : `<p class="fl-notice ${ok === n ? (t.validation.status === "passed" ? "ok" : "warn") : "bad"}">${ok} of ${n} products validated${t.validation.deep ? "" : " (byte-level checks only)"}${c.failed ? `; <strong>${c.failed} failed validation</strong>` : ""}${c["not-checked"] ? `; ${c["not-checked"]} not covered by a check` : ""}.</p>`;
    return `<div class="fl-stack">${summary}
      <p class="fl-help">Publication: <strong>${esc(PUBLABEL[pub.state] || pub.state)}</strong>. ${esc(pub.note || "")}${t.downloadable ? "" : " Downloads are available to the job's owner only."}</p>
      <div class="fl-table-wrap"><table class="lv-files"><thead><tr><th>Product</th><th>Mode</th><th>Format</th><th class="num">Size</th><th>SHA-256</th><th>Validation</th><th>Publication</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
  }

  function renderPick() {
    const n = state.pick.size;
    $("lv-compare-go").disabled = n < 2 || n > 6;
    $("lv-compare-count").textContent = n ? `${n} selected` + (n > 6 ? " (at most 6)" : "") : "Select 2-6 completed jobs";
  }

  async function runCompare() {
    const ids = [...state.pick];
    const box = $("lv-compare");
    $("lv-compare-panel").hidden = false;
    box.innerHTML = `<p class="fl-help lv-pad">Comparing…</p>`;
    try {
      const c = await get(`${api}/compare?jobs=${ids.map(encodeURIComponent).join(",")}`);
      const head = `<th></th>` + c.jobs.map((j, i) => `<th><span class="fl-mono">${esc(short(j.job_id))}</span>${i === 0 ? " <small>(reference)</small>" : ""}<br><small>${esc(j.owner || "")} · ${esc(when(j.finished_at))}</small></th>`).join("");
      const idCell = k => pill(...(IDPILL[k] || ["cancelled", k]));
      const inputs = c.inputs.map(i => `<tr><td><strong>${esc(i.name)}</strong><br>${idCell(i.identity)}</td>${i.jobs.map(x => x ? `<td><small>${esc(x.kind)} · <span class="fl-mono">${esc(x.location)}</span><br>${bytes(x.size)} · sha256 ${shaCell(x.sha256)}<br>${esc(upstream({recorded: x.identity_recorded, etag: x.etag, last_modified: x.last_modified, upstream_checked: x.upstream_checked}))} · ${esc(x.cache === "hit" ? "shared cache hit" + (x.upstream_checked === false ? " (source.coop not rechecked)" : "") : x.cache === "stored" ? "downloaded, stored in cache" : x.cache)}</small></td>` : `<td>${pill("warnings", "not used")}</td>`).join("")}</tr>`).join("");
      const envRows = c.environment.map(e => `<tr${e.same ? "" : ' class="lv-diff"'}><td>${esc(e.label)}${e.same ? "" : " " + pill("failed", "Differs")}</td>${e.values.map(v => `<td class="fl-mono">${esc(v == null ? "—" : String(v).length > 16 ? short(v) : v)}</td>`).join("")}</tr>`).join("");
      const prodRows = c.products.map(p => `<tr${p.identity === "identical" ? "" : ' class="lv-diff"'}><td class="fl-mono">${esc(p.name)}<br>${idCell(p.identity)}</td>${p.jobs.map(x => x ? `<td>${shaCell(x.sha256)}<br><small>${bytes(x.size)} · ${esc(VLABEL[x.validation] || "unvalidated")}</small></td>` : `<td>${pill("warnings", "missing")}</td>`).join("")}</tr>`).join("");
      const valRow = `<tr><td>Validation</td>${c.jobs.map(j => `<td>${j.validation ? pill(j.validation.status) + (j.validation.deep ? "" : " <small>byte-level only</small>") : pill("cancelled", "Unvalidated")}</td>`).join("")}</tr>`;
      const resRows = c.resources.map(r => `<tr><td>${esc(r.label)}</td>${r.values.map((v, i) => { const d = r.difference[i]; return `<td class="num">${esc(num(v, r.unit))}${i && d && d.delta ? `<br><small>${d.delta > 0 ? "+" : ""}${esc(r.unit === "bytes" ? bytes(Math.abs(d.delta)).replace(/^/, d.delta < 0 ? "-" : "") : d.delta + " " + r.unit)}${d.percent != null ? ` (${d.percent > 0 ? "+" : ""}${d.percent}%)` : ""}</small>` : ""}</td>`; }).join("")}</tr>`).join("");
      const s = c.product_summary;
      box.innerHTML = `<div class="fl-card-section fl-stack">
        <p class="fl-notice ${c.products_identical ? "ok" : "warn"}"><strong>${c.products_identical ? "Products are byte-identical." : "Products differ."}</strong> ${s.identical} identical · ${s.differ} differ · ${s.missing} missing.</p>
        <p class="fl-notice ${c.inputs_identical ? "ok" : "warn"}"><strong>${c.inputs_identical ? "Inputs are identical." : "Inputs differ."}</strong></p>
        <ul class="fl-list">${c.statements.map(t => `<li>${esc(t)}</li>`).join("")}</ul></div>
        <h3 class="lv-h">Inputs</h3><div class="fl-table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${inputs || `<tr><td class="panel-empty">No inputs recorded.</td></tr>`}</tbody></table></div>
        <h3 class="lv-h">LIVIST, toolchain and configuration</h3><div class="fl-table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${envRows}</tbody></table></div>
        <h3 class="lv-h">Products (SHA-256)</h3><div class="fl-table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${valRow}${prodRows}</tbody></table></div>
        <h3 class="lv-h">Measured resources</h3><div class="fl-table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${resRows}</tbody></table></div>
        <p class="fl-help lv-pad">Differences are relative to the reference (first) job.</p>`;
    } catch (e) { box.innerHTML = `<p class="fl-notice bad">${esc(e.message)}</p>`; }
  }

  async function loadCache() {
    if (!state.status.viewer.maintainer) return;
    const d = await get(api + "/cache");
    const pct = d.limit_bytes ? Math.round(100 * d.total_bytes / d.limit_bytes) : null;
    $("lv-cache-summary").innerHTML = [
      ["Cached", bytes(d.total_bytes), `${d.entries.length} input${d.entries.length === 1 ? "" : "s"}`],
      ["Cap", d.limit_bytes ? bytes(d.limit_bytes) : "unbounded", pct != null ? `${pct}% used${d.over_limit ? " (over the cap)" : ""}` : ""],
      ["Free disk", bytes(d.free_bytes), `reserve ${bytes(d.reserve_bytes)}${d.below_reserve ? " · below reserve" : ""}`],
    ].map(([k, v, x]) => `<div class="fl-kv"><span>${esc(k)}</span><strong>${esc(v)}</strong><small>${esc(x)}</small></div>`).join("");
    $("lv-cache").innerHTML = d.entries.length ? d.entries.map(e => `<tr>
      <td><small>${esc(e.host)}</small><br><span class="fl-mono">${esc(e.path)}</span></td>
      <td class="num">${bytes(e.size)}</td><td>${shaCell(e.sha256)}<br><small>ETag ${esc(e.etag || "—")}</small></td>
      <td><small>stored ${esc(when(e.stored_at))}<br>last used ${esc(when(e.used_at))}</small></td>
      <td>${e.blob_present && e.blob_size_matches ? pill("passed", "Present") : pill("failed", e.blob_present ? "Size mismatch" : "Missing")}<br><small>${esc(e.provenance.upstream_at_store)}</small></td>
      <td><small>${e.jobs.length ? e.jobs.map(u => `<span class="fl-mono">${esc(short(u.job_id))}</span> ${esc(u.owner || "")} · ${esc(u.cache)}${u.same_content ? "" : " (other version)"}`).join("<br>") : "none recorded"}</small></td></tr>`).join("")
      : `<tr><td colspan="6" class="panel-empty">The input cache is empty.</td></tr>`;
    $("lv-cache-note").textContent = `${d.eviction}. ${d.jobs_scanned} most recent jobs scanned for usage.`;
  }

  function planHtml(p) {
    if (!p) return "";
    const rows = p.files.map(f => `<tr><td class="fl-mono">${esc(f.name)}</td><td class="num">${bytes(f.size)}</td><td class="fl-mono">${esc(short(f.sha256))}</td><td>${pill(f.action === "create" ? "ok" : f.action === "overwrite" ? "warnings" : "failed", f.action)}</td></tr>`).join("");
    return `<div class="fl-table-wrap"><table><thead><tr><th>File → ${esc(p.target)}</th><th class="num">Size</th><th>SHA-256</th><th>Action</th></tr></thead><tbody>${rows}</tbody></table></div>
      ${p.not_uploaded && p.not_uploaded.length ? `<p class="fl-help">Not uploaded (as in LIVIST's scripts/upload): ${esc(p.not_uploaded.join(", "))}</p>` : ""}
      ${p.blocking && p.blocking.length ? `<p class="fl-notice bad">${esc(p.blocking.join(" "))}</p>` : ""}`;
  }

  async function loadPublications() {
    if (!state.status.viewer.maintainer) return;
    const d = await get(api + "/publications");
    $("lv-pub-mode").innerHTML = d.enabled ? pill("warnings", "Uploads enabled") : pill("muted", "Dry run only");
    $("lv-pubs").innerHTML = d.requests.length ? d.requests.map(r => `<div class="lv-pub">
      <div class="fl-card-head"><div class="fl-card-title"><h2>Job ${esc(short(r.job_id))}</h2>${pill(r.status)}${r.allow_overwrite ? pill("warnings", "overwrite allowed") : ""}
        <small>requested by ${esc(r.requested_by)} · ${esc(when(r.requested_at))}${r.decided_by ? " · decided by " + esc(r.decided_by) : ""}</small></div>
        ${r.status === "pending" ? `<div class="fl-actions">${r.mine ? `<span class="fl-help">Awaiting another maintainer</span>` : `<button class="fl-btn primary" data-decide="approve" data-req="${esc(r.request_id)}">Approve</button>`}<button class="fl-btn danger" data-decide="reject" data-req="${esc(r.request_id)}">Reject</button></div>` : ""}
      </div><div class="fl-card-section">${planHtml(r.plan)}
        ${r.result && r.result.message ? `<p class="fl-notice info">${esc(r.result.message)}</p>` : ""}
        ${r.result && r.result.problems ? `<p class="fl-notice bad">${esc(r.result.problems.join(" "))}</p>` : ""}
        ${r.result && r.result.error ? `<p class="fl-notice bad">${esc(r.result.error)}</p>` : ""}</div></div>`).join("")
      : `<p class="panel-empty">No publication requests.</p>`;
  }

  async function load(refresh) {
    try {
      state.status = await get(api + "/status" + (refresh ? "?refresh=1" : ""));
      const s = state.status;
      for (const el of document.querySelectorAll("[data-maintainer]")) el.hidden = !s.viewer.maintainer;
      renderToolchain(s); renderGenerate(s); renderMetrics(s);
      await Promise.all([loadJobs(), loadSources(), loadPublications(), loadCache()]);
      notice("lv-page-notice", "", "");
    } catch (e) { notice("lv-page-notice", "bad", esc(e.message)); }
  }

  document.addEventListener("click", async ev => {
    const t = ev.target.closest("button");
    if (!t) return;
    try {
      if (t.dataset.copy) {
        try { await navigator.clipboard.writeText(t.dataset.copy); t.textContent = "Copied"; }
        catch (_e) { window.prompt("SHA-256", t.dataset.copy); }
        setTimeout(() => { t.textContent = "Copy"; }, 1500);
      }
      else if (t.id === "lv-compare-go") await runCompare();
      else if (t.id === "lv-cache-refresh") await loadCache();
      else if (t.id === "lv-refresh") { t.disabled = true; await load(true); t.disabled = false; }
      else if (t.dataset.open) {
        const id = t.dataset.open;
        state.open.has(id) ? state.open.delete(id) : state.open.add(id);
        await loadJobs();
      } else if (t.dataset.scope) {
        state.scope = t.dataset.scope;
        for (const b of document.querySelectorAll("[data-scope]")) b.classList.toggle("active", b.dataset.scope === state.scope);
        await loadJobs();
      } else if (t.dataset.cancel) {
        if (!confirm("Cancel this generation?")) return;
        await post(`${api}/jobs/${t.dataset.cancel}/cancel`); await loadJobs();
      } else if (t.dataset.retry) {
        if (!confirm("Start a new generation with this job's inputs? The interrupted job is kept as it is; nothing of it is reused.")) return;
        t.disabled = true;
        try { await post(`${api}/jobs/${t.dataset.retry}/retry`, {}); }
        catch (e) {
          const box = document.querySelector(`[data-job-notice="${t.dataset.retry}"]`);
          if (box) box.innerHTML = `<p class="fl-notice bad">${esc(e.message)}</p>`;
          t.disabled = false; return;
        }
        await loadJobs();
      } else if (t.dataset.validate) {
        t.disabled = true; await post(`${api}/jobs/${t.dataset.validate}/validate`); await loadJobs();
      } else if (t.dataset.publish) {
        const id = t.dataset.publish;
        const overwrite = confirm("Plan publication of this job's products to source.coop?\n\nOK = allow overwriting files that are already published\nCancel = plan without overwriting");
        try {
          await post(api + "/publications", {job_id: id, allow_overwrite: overwrite});
          await loadPublications();
          $("lv-pub-panel").scrollIntoView({behavior: "smooth"});
        } catch (e) {
          const box = document.querySelector(`[data-job-notice="${id}"]`);
          if (box) box.innerHTML = `<p class="fl-notice bad">${esc(e.message)}</p>` + planHtml(e.plan);
        }
      } else if (t.dataset.decide) {
        const approve = t.dataset.decide === "approve";
        if (!confirm(approve ? "Approve this publication request?" : "Reject this publication request?")) return;
        try { await post(`${api}/publications/${t.dataset.req}/${t.dataset.decide}`, {}); notice("lv-pub-notice", "", ""); }
        catch (e) { notice("lv-pub-notice", "bad", esc(e.message)); }
        await loadPublications();
      } else if (t.dataset.toggle) {
        await post(`${api}/sources/${t.dataset.toggle}/status`, {enabled: t.dataset.enabled === "1"});
        await load();
      }
    } catch (e) { notice("lv-page-notice", "bad", esc(e.message)); }
  });

  document.addEventListener("change", ev => {
    const box = ev.target.closest("input[data-pick]");
    if (!box) return;
    box.checked ? state.pick.add(box.dataset.pick) : state.pick.delete(box.dataset.pick);
    renderPick();
  });
  $("lv-candidate").addEventListener("change", ev => {
    const opt = ev.target.selectedOptions[0];
    if (opt && opt.dataset.name && !$("lv-src-name").value) $("lv-src-name").value = opt.dataset.name;
  });
  $("lv-add-source").addEventListener("submit", async ev => {
    ev.preventDefault();
    const f = ev.target;
    try {
      await post(api + "/sources", {candidate_id: $("lv-candidate").value, name: $("lv-src-name").value.trim(), description: f.elements.namedItem("description").value.trim()});
      f.reset(); notice("lv-src-notice", "ok", "Input approved.");
      await load();
    } catch (e) { notice("lv-src-notice", "bad", esc(e.message)); }
  });
  $("lv-generate").addEventListener("submit", async ev => {
    ev.preventDefault();
    const names = [...ev.target.querySelectorAll("input[name=source]:checked")].map(i => i.value);
    if (!names.length) { notice("lv-gen-notice", "bad", "Choose at least one input."); return; }
    $("lv-gen-start").disabled = true;
    try {
      const j = await post(api + "/jobs", {sources: names});
      notice("lv-gen-notice", "ok", `Generation <span class="fl-mono">${esc(short(j.job_id))}</span> started in your workspace.`);
      state.open.add(j.job_id);
      await loadJobs();
    } catch (e) { notice("lv-gen-notice", "bad", esc(e.message)); }
    $("lv-gen-start").disabled = !state.status.toolchain.ready;
  });
  load();
})();
"""

CONTENT = """
<div class="page-heading-row">
  <div>
    <h1>LIVIST</h1>
    <p class="page-subtitle">Living Ice Sheet Temperature: radar-attenuation inputs, the isolated
      processing environment, generation jobs in each user's workspace, and publication to
      source.coop.</p>
  </div>
  <div class="fl-actions">
    <a class="small-button" href="/livist/">Open LIVIST →</a>
    <a class="small-button" href="/livist/docs/">Documentation</a>
  </div>
</div>
<div id="lv-page-notice"></div>
<div class="metric-grid" id="lv-metrics"></div>

<section class="panel">
  <div class="fl-card-head"><div class="fl-card-title"><h2>Toolchain</h2><span id="lv-tool-state"></span></div>
    <button class="fl-btn" id="lv-refresh" hidden>Check again</button></div>
  <div class="fl-table-wrap"><table class="lv-tools"><thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead>
    <tbody id="lv-tools"><tr><td colspan="3" class="panel-empty">Checking…</td></tr></tbody></table></div>
  <div class="fl-kv-grid" id="lv-settings"></div>
  <p class="fl-help lv-pad">Environment: LIVIST's own <code>uv.lock</code> plus conda-forge GDAL, tippecanoe and uv,
    built by <code>icesee_jupyter_book/applications/livist/environment/build_env.sh</code>. Settings come from the
    server's <code>CRYOSTACK_LIVIST_*</code> environment variables.</p>
</section>

<section class="panel" data-maintainer hidden>
  <div class="panel-header">Inputs</div>
  <div class="fl-table-wrap"><table><thead><tr><th>Name</th><th>Kind</th><th>Location</th><th>Status</th><th></th></tr></thead>
    <tbody id="lv-sources"></tbody></table></div>
  <form id="lv-add-source" class="fl-form" novalidate>
    <fieldset class="fl-fieldset"><legend>Approve an input</legend>
      <div class="fl-fields three">
        <label class="fl-field">Input
          <select name="candidate_id" id="lv-candidate" required></select>
          <span class="fl-help" id="lv-candidates-note"></span></label>
        <label class="fl-field">Name
          <input name="name" id="lv-src-name" required maxlength="32" autocomplete="off" placeholder="ase">
          <span class="fl-help">Lowercase letters, digits, hyphens; becomes part of product file names.</span></label>
        <label class="fl-field">Description
          <input name="description" maxlength="200" autocomplete="off" placeholder="Amundsen Sea Embayment"></label>
      </div>
      <p class="fl-help">Only LIVIST's own source.coop inputs and files inside the operator's approved input
        directories are offered; paths cannot be typed.</p>
    </fieldset>
    <div class="fl-actions"><button class="fl-btn primary" type="submit">Approve input</button></div>
    <div id="lv-src-notice"></div>
  </form>
</section>

<section class="panel">
  <div class="panel-header">Generate</div>
  <form id="lv-generate" class="fl-form" novalidate>
    <fieldset class="fl-fieldset"><legend>Approved inputs</legend><div id="lv-gen-sources" class="fl-stack"></div></fieldset>
    <p class="fl-help">Runs LIVIST's <code>scripts/generate</code> unmodified (both temperature modes, GeoParquet,
      FlatGeobuf and PMTiles) in a new directory of <strong>your</strong> workspace. One generation per user at a time.</p>
    <div class="fl-actions"><button class="fl-btn primary" id="lv-gen-start" type="submit" disabled>Start generation</button>
      <span class="fl-help" id="lv-gen-why"></span></div>
    <div id="lv-gen-notice"></div>
  </form>
</section>

<section class="panel">
  <div class="fl-card-head"><div class="fl-card-title"><h2>Jobs</h2></div>
    <div class="fl-actions" data-maintainer hidden>
      <button class="fl-tab active" data-scope="mine">Mine</button><button class="fl-tab" data-scope="all">All users</button></div></div>
  <div class="fl-table-wrap"><table class="lv-jobs"><thead id="lv-jobs-head"></thead><tbody id="lv-jobs"></tbody></table></div>
  <div class="fl-actions lv-pad lv-compare-bar"><button class="fl-btn" id="lv-compare-go" disabled>Compare selected</button>
    <span class="fl-help" id="lv-compare-count">Select 2-6 completed jobs</span></div>
</section>

<section class="panel" id="lv-compare-panel" hidden>
  <div class="fl-card-head"><div class="fl-card-title"><h2>Compare runs</h2></div></div>
  <div class="fl-card-section"><p class="fl-help">Read-only comparison of the selected jobs' manifests: inputs, LIVIST and
    toolchain versions, configuration, products (identity by SHA-256 only; contents are not opened), validation and
    measured resources.</p></div>
  <div id="lv-compare"></div>
</section>

<section class="panel" id="lv-pub-panel" data-maintainer hidden>
  <div class="fl-card-head"><div class="fl-card-title"><h2>Publication to source.coop</h2><span id="lv-pub-mode"></span></div></div>
  <div class="fl-card-section">
    <p class="fl-notice info">Two steps: a maintainer requests publication of a completed, validated job (a dry-run
      plan with checksums, destinations and overwrite checks), and a <strong>different</strong> maintainer approves
      or rejects it. Unless the server enables uploads, approval only records the plan. Upload credentials are the
      server's own; they are never entered or shown here.</p>
    <div id="lv-pub-notice"></div>
  </div>
  <div id="lv-pubs"></div>
</section>

<section class="panel" data-maintainer hidden>
  <div class="fl-card-head"><div class="fl-card-title"><h2>Input cache</h2></div>
    <button class="fl-btn" id="lv-cache-refresh">Refresh</button></div>
  <div class="fl-kv-grid" id="lv-cache-summary"></div>
  <div class="fl-table-wrap"><table class="lv-cache"><thead><tr><th>Source</th><th class="num">Size</th><th>SHA-256 / ETag</th>
    <th>Stored / used</th><th>Verification</th><th>Jobs</th></tr></thead><tbody id="lv-cache"></tbody></table></div>
  <p class="fl-help lv-pad">Read-only. Each entry is a verified copy of a file a completed job downloaded from
    source.coop; it is re-hashed before every reuse and checked against source.coop's size/ETag when reachable.
    <span id="lv-cache-note"></span></p>
</section>

<section class="panel">
  <div class="panel-header">Attribution</div>
  <div class="fl-card-section"><p class="fl-help">LIVIST © 2026 Development Seed, MIT License
    (<a href="https://github.com/ICESEE-project/living-ice-sheet-temperature">source</a>). Inputs: radar attenuation
    and borehole data on <a href="https://source.coop/englacial/ice-sheet-temperature">source.coop</a>; cite the
    original publications listed with the data. Every job's manifest records the LIVIST commit, configuration hash,
    input checksums and this attribution.</p></div>
</section>
<style>""" + STYLE + """
  .lv-log { max-height: 320px; overflow: auto; margin: 0.5rem 0 0; padding: 0.75rem; border-radius: 8px;
    background: #0f172a; color: #e2e8f0; font-size: 0.7rem; white-space: pre-wrap; overflow-wrap: anywhere; }
  .lv-pad { padding: 0 1.1rem 1rem; margin: 0; }
  .lv-tight { padding: 0; }
  .lv-pub + .lv-pub { border-top: 1px solid #e2e8f0; }
  tr.lv-detail > td { background: #f8fafc; }
  .lv-jobs { min-width: 720px; }
  .lv-tools { min-width: 0 !important; }
  .lv-files { min-width: 760px; }
  .lv-files td { vertical-align: top; }
  tr.lv-diff > td { background: #fffbeb; }
  .lv-h { margin: 0.75rem 1.1rem 0.25rem; font-size: 0.85rem; }
  .lv-warn { color: #b45309; }
  .lv-compare-bar { padding-top: 0.75rem; }
  .lv-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .page-heading-row .fl-actions .small-button { white-space: nowrap; }
  @media (max-width: 760px) {
    .control-content { padding: 1rem; }
    .lv-tools td:nth-child(3) { min-width: 9rem; }
    .lv-pad code { overflow-wrap: anywhere; }
    /* job rows become stacked cards so a row's details are never clipped */
    .fl-table-wrap table.lv-jobs { min-width: 0; }
    .lv-jobs > thead { display: none; }
    .lv-jobs > tbody, .lv-jobs > tbody > tr, .lv-jobs > tbody > tr > td { display: block; }
    .lv-jobs > tbody > tr[data-job] { padding: 0.6rem 0; border-top: 1px solid #e2e8f0; }
    .lv-jobs > tbody > tr[data-job] > td { display: inline-block; padding: 0.2rem 0.5rem; border: 0; }
    .lv-jobs > tbody > tr[data-job] > td.num::before { content: "· "; }
    .lv-jobs .fl-table-wrap table { min-width: 0; }
    .lv-jobs .lv-files td, .lv-jobs .lv-files th { padding: 0.5rem; }
    .lv-jobs .fl-table-wrap table.lv-files { min-width: 680px; }
    .lv-jobs > tbody > tr.lv-detail[hidden] { display: none; }
  }
</style>
<script>""" + _SCRIPT + """</script>"""
