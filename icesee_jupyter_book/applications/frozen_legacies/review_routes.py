"""Scientific review and publication routes (see :mod:`radar.review`).

Installed by :func:`catalog_routes.install_catalog_routes` under
``/frozen-legacies/api/``:

Owners (signed in; their own assets only)

* ``GET  assets/<id>/review``        whether the result can be submitted, and its
                                      submissions
* ``POST assets/<id>/review``        ``{"action": "submit", "note"?}`` or
                                      ``{"action": "cancel", "submission_id"}``
* ``GET  reviews/mine``              the user's submissions (all assets)

Everyone signed in (the shared, published product)

* ``GET  published/observations``    published observations, GeoJSON (bounded)
* ``GET  published/<sid>/products/<astra-csv|astra-qc|provenance>``

Reviewers (Control Center maintainer, admin, owner -- checked per request)

* ``GET  admin/reviews``                     the review queue
* ``GET  admin/reviews/<sid>``               snapshot: observations, provenance,
                                              geolocation check
* ``GET  admin/reviews/<sid>/products/<kind>``
* ``POST admin/reviews/<sid>/decision``      approve / return / reject
* ``POST admin/reviews/<sid>/withdraw``      withdraw a published result

The Control Center page ``/control/frozen-legacies/review`` uses these.
"""
from __future__ import annotations

import asyncio
import json
import re

from aiohttp import web

from . import server as S
from .radar import manual
from .radar import observations as obs
from .radar.assets import asset_image_paths
from .radar.catalog import create_catalog, is_catalog_key, open_catalog
from .radar.review import (
    SNAPSHOT_PRODUCTS,
    ReviewError,
    ReviewForbidden,
    ReviewStore,
    SnapshotUnavailable,
    public_submission,
    result_stage,
    session_version,
)


_SUBMISSION = re.compile(r"sub-[0-9a-f]{24}")
PUBLISHED_LIMIT = 5_000
_PRODUCT_TYPES = {"astra-csv": "text/csv", "astra-qc": "image/png",
                  "provenance": "application/json"}


def _store(*, create: bool = False) -> ReviewStore | None:
    catalog = open_catalog() or (create_catalog() if create else None)
    return ReviewStore(catalog) if catalog is not None else None


def _submission_id(request) -> str:
    value = request.match_info["submission_id"]
    if not _SUBMISSION.fullmatch(value):
        raise web.HTTPNotFound(text=json.dumps({"error": "Submission not found."}),
                               content_type="application/json")
    return value


def _guard(handler):
    async def run(request):
        try:
            return await handler(request)
        except ReviewForbidden as error:
            return S._error(403, str(error))
        except ReviewError as error:
            return S._error(409, str(error))
        except LookupError:
            return S._error(404, "Submission not found.")
    return run


async def _body(request) -> dict:
    if (request.content_length or 0) > 16 * 1024:
        raise ReviewError("Request body is too large.")
    try:
        payload = await request.json()
    except ValueError:
        raise ReviewError("A JSON body is required.")
    if not isinstance(payload, dict):
        raise ReviewError("A JSON object is required.")
    return payload


# ── owners ───────────────────────────────────────────────────────────
def _eligibility(workspace, manifest) -> tuple[bool, str]:
    if manifest.get("origin") != "shared":
        return False, "Only results on shared radar can be submitted; uploaded radar is private."
    from .optional_pickers import AstraGeometry

    image = manifest.get("image") or {}
    geometry = AstraGeometry.for_image(int(image["width"]), int(image["height"]))
    doc = manual.load_document(workspace, manifest["asset_id"], geometry,
                               manifest.get("filename") or "")
    if doc is None or doc.get("status") != "completed":
        return False, "Finish the manual session (Done) to submit it for review."
    return True, ""


def _review_state(request) -> dict:
    workspace, manifest = S._owned(request)
    store = _store()
    submissions = store.for_asset(workspace.user.safe_id, manifest["asset_id"]) if store else []
    eligible, reason = (False, "No results on processed-products assets.") \
        if not manifest.get("image") else _eligibility(workspace, manifest)
    if eligible and any(s["status"] == "submitted" for s in submissions):
        eligible, reason = False, "This result is awaiting review."
    session = session_version(workspace, manifest["asset_id"])
    return {"asset_id": manifest["asset_id"], "can_submit": eligible, "reason": reason,
            "session_revision": session.get("revision"),
            "stage": result_stage(session, submissions),
            "submissions": [public_submission(s) for s in submissions]}


async def api_review_state(request: web.Request) -> web.Response:
    return S._json(await S._blocking(_review_state, request))


def _source_version(manifest) -> str | None:
    key = manifest.get("shared_source") or ""
    if is_catalog_key(key):
        catalog = open_catalog()
        record = catalog.resolve(key) if catalog else None
        if record:
            return record.get("etag") or f"{record['bytes']}-{record['mtime_ns']}"
        return None
    source = S.load_sources().get(key)
    if source is not None and source.tiff_path.is_file():
        stat = source.tiff_path.stat()
        return f"{stat.st_size}-{stat.st_mtime_ns}"
    return None


def _submit(request, user_id: str, note) -> dict:
    workspace, manifest = S._owned(request)
    asset_id = manifest["asset_id"]
    if not manifest.get("image"):
        raise ReviewError("This asset has no manual result.")
    from .optional_pickers import AstraGeometry

    image = manifest["image"]
    geometry = AstraGeometry.for_image(int(image["width"]), int(image["height"]))
    filename = manifest.get("filename") or ""
    doc = manual.load_document(workspace, asset_id, geometry, filename)
    outputs = {}
    for product in SNAPSHOT_PRODUCTS:
        path = manual.existing_output(workspace, asset_id, filename, product)
        if path is not None:
            outputs[product] = path
    try:
        _tiff, nav = asset_image_paths(workspace, manifest, S.load_sources())
    except Exception:
        nav = None
    document = obs.read(workspace, asset_id)
    if doc is not None and (document is None or document.get("session_revision") != doc["revision"]):
        document = obs.build(asset_id, manifest, doc, nav)
        obs.write(workspace, asset_id, document)
    store = _store(create=True)
    submission = store.submit(workspace=workspace, user_id=user_id, manifest=manifest, doc=doc,
                              outputs=outputs, observations=document,
                              source_version=_source_version(manifest), nav_path=nav,
                              note=note)
    _changed(workspace, manifest)
    return public_submission(submission)


def _changed(workspace, manifest) -> None:
    from .catalog_routes import record_state

    try:
        record_state(workspace, manifest)
    except Exception:
        pass


async def api_review_action(request: web.Request) -> web.Response:
    S._require_same_origin(request)
    payload = await _body(request)
    action = payload.get("action")
    if action == "submit":
        workspace = S.workspace_for_request(request)
        lock = request.app[S.MANUAL_LOCKS_KEY].setdefault(
            f"{workspace.root}/{request.match_info['asset_id']}", asyncio.Lock())
        async with lock:
            result = await S._blocking(_submit, request, request["cryostack_user"].id,
                                       payload.get("note"))
        return S._json(result, status=201)
    if action == "cancel":
        sid = str(payload.get("submission_id") or "")
        if not _SUBMISSION.fullmatch(sid):
            raise LookupError(sid)

        def cancel():
            workspace, manifest = S._owned(request)
            store = _store()
            if store is None:
                raise LookupError(sid)
            submission = store.get(sid)
            if submission is None or submission["asset_id"] != manifest["asset_id"]:
                raise LookupError(sid)
            return public_submission(store.cancel(sid, workspace.user.safe_id))

        return S._json(await S._blocking(cancel))
    raise ReviewError("action must be submit or cancel.")


async def api_my_reviews(request: web.Request) -> web.Response:
    workspace = S.workspace_for_request(request)
    store = _store()
    items = await S._blocking(store.for_owner, workspace.user.safe_id) if store else []
    return S._json({"submissions": [public_submission(s) for s in items]})


# ── published product (all signed-in users) ──────────────────────────
async def api_published_observations(request: web.Request) -> web.Response:
    from .catalog_routes import _bbox, _dataset, _flight, _int

    store = _store()
    limit = min(PUBLISHED_LIMIT, max(1, _int(request.query.get("limit"), PUBLISHED_LIMIT,
                                             name="limit")))
    dataset = _dataset(request.query.get("dataset"))
    flight = _flight(request.query.get("flight"))
    bbox = _bbox(request.query.get("bbox"))
    if store is None:
        return S._json({"type": "FeatureCollection", "features": [],
                        "summary": {"returned": 0, "truncated": False, "published_total": 0}})
    return S._json(await S._blocking(store.published, dataset_id=dataset, flight=flight,
                                     bbox=bbox, limit=limit))


def _product_response(store, submission, kind) -> web.StreamResponse:
    if kind not in _PRODUCT_TYPES:
        raise LookupError(kind)
    if kind == "provenance":
        body = json.dumps(store.provenance(submission), indent=2, sort_keys=True).encode()
        name = f"{submission['submission_id']}_provenance.json"
    else:
        path = store.snapshot_file(submission, kind)
        if path is None:
            raise LookupError(kind)
        body, name = path.read_bytes(), path.name
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return web.Response(body=body, content_type=_PRODUCT_TYPES[kind], headers={
        "Content-Disposition": f'attachment; filename="{safe}"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@_guard
async def api_published_product(request: web.Request) -> web.StreamResponse:
    sid = _submission_id(request)
    store = _store()
    submission = await S._blocking(store.get, sid) if store else None
    if submission is None or submission["status"] != "published":
        raise LookupError(sid)                   # unpublished snapshots stay private
    return await S._blocking(_product_response, store, submission, request.match_info["kind"])


# ── reviewers ────────────────────────────────────────────────────────
@_guard
async def api_admin_reviews(request: web.Request) -> web.Response:
    status = request.query.get("status") or None
    from .radar.review import STATUSES

    if status is not None and status not in STATUSES:
        raise ReviewError("Unknown status.")
    store = _store()
    if store is None:
        return S._json({"items": [], "total": 0, "page": 1, "page_size": 50, "counts": {}})
    try:
        page = int(request.query.get("page") or 1)
    except ValueError:
        page = 1
    user = request["cryostack_user"]
    result = await S._blocking(store.queue, status, page=page)
    result["items"] = [dict(public_submission(s, reviewer=True),
                            own=s["submitter_user_id"] == str(user.id)) for s in result["items"]]
    return S._json(result)


@_guard
async def api_admin_review_detail(request: web.Request) -> web.Response:
    sid = _submission_id(request)
    store = _store()
    submission = await S._blocking(store.get, sid) if store else None
    if submission is None:
        raise LookupError(sid)
    user = request["cryostack_user"]

    def detail():
        integrity = store.verify_snapshot(submission)
        out = {
            "submission": public_submission(submission, reviewer=True),
            "own": submission["submitter_user_id"] == str(user.id),
            "integrity": integrity,
            "observations": [], "provenance": None,
            "geolocation": {"verified": False, "message": "The snapshot is not available."},
        }
        replaced = store.would_supersede(submission) if submission["status"] == "submitted" else None
        if replaced is not None:
            verified = None
            try:
                verified = sum(1 for r in store.snapshot_observations(replaced)
                               if r.get("geolocation_status") == "verified")
            except SnapshotUnavailable:
                pass
            out["supersedes_on_approval"] = {
                "submission_id": replaced["submission_id"],
                "observation_count": replaced["observation_count"],
                "verified_count": verified, "published_at": replaced["published_at"]}
        try:
            ok, reason = store.geolocation_check(submission)
            out.update(observations=store.snapshot_observations(submission),
                       provenance=store.provenance(submission),
                       geolocation={"verified": ok, "message": reason})
        except SnapshotUnavailable:
            pass
        return out

    return S._json(await S._blocking(detail))


@_guard
async def api_admin_review_product(request: web.Request) -> web.StreamResponse:
    sid = _submission_id(request)
    store = _store()
    submission = await S._blocking(store.get, sid) if store else None
    if submission is None:
        raise LookupError(sid)
    return await S._blocking(_product_response, store, submission, request.match_info["kind"])


@_guard
async def api_admin_review_decision(request: web.Request) -> web.Response:
    S._require_same_origin(request)
    sid = _submission_id(request)
    payload = await _body(request)
    store = _store()
    if store is None:
        raise LookupError(sid)
    result = await S._blocking(
        store.decide, sid, reviewer_user_id=request["cryostack_user"].id,
        decision=payload.get("decision"), note=payload.get("note"),
        accept_unverified_geolocation=payload.get("accept_unverified_geolocation") is True)
    return S._json(public_submission(result, reviewer=True))


@_guard
async def api_admin_review_withdraw(request: web.Request) -> web.Response:
    S._require_same_origin(request)
    sid = _submission_id(request)
    payload = await _body(request)
    store = _store()
    if store is None:
        raise LookupError(sid)
    result = await S._blocking(store.withdraw, sid, user_id=request["cryostack_user"].id,
                               reason=payload.get("reason"))
    return S._json(public_submission(result, reviewer=True))


# ── Control Center page ──────────────────────────────────────────────
_REVIEW_SCRIPT = r"""
(function () {
  const api = "/frozen-legacies/api/admin/reviews";
  const $ = id => document.getElementById(id);
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"})[c]);
  const when = t => t ? new Date(t * 1000).toLocaleString() : "—";
  const num = (v, d) => Number.isFinite(v) ? v.toFixed(d) : "—";
  const pill = (label, kind) => `<span class="status-pill ${kind}">${esc(label)}</span>`;
  const STATUS = {
    submitted: ["Awaiting review", "warn"], published: ["Published", "ok"], returned: ["Returned for correction", "info"],
    rejected: ["Rejected", "bad"], withdrawn: ["Withdrawn", "muted"], superseded: ["Superseded", "muted"],
    cancelled: ["Cancelled by submitter", "muted"]
  };
  const statusPill = s => pill(...(STATUS[s] || [s, "muted"]));
  const GEO = {
    verified: ["Verified", "ok"], unverified: ["Unverified · ASTRA-assigned", "warn"],
    label_unreadable: ["Label unreadable · not mapped", "bad"], verified_no_navigation: ["Confirmed · no navigation · not mapped", "muted"]
  };
  const TABS = [["submitted", "Awaiting review"], ["published", "Published"], ["returned", "Returned"],
                ["rejected", "Rejected"], ["withdrawn", "Withdrawn"], ["superseded", "Superseded"], ["", "All"]];
  const EMPTY = {
    submitted: "Nothing is awaiting review.", published: "No results are published.",
    returned: "No results were returned for correction.", rejected: "No results were rejected.",
    withdrawn: "No publications were withdrawn.", superseded: "No publications were superseded.", "": "No submissions yet."
  };
  let filter = "submitted", selected = null;

  async function call(url, body) {
    const r = await fetch(url, {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || ("The request failed (HTTP " + r.status + ")."));
    return j;
  }
  function notice(kind, html) {
    return `<p class="fl-notice ${kind}" role="${kind === "bad" ? "alert" : "status"}">${html}</p>`;
  }

  async function load() {
    let j;
    try {
      const r = await fetch(`${api}?${filter ? "status=" + filter : ""}`, {credentials: "same-origin"});
      j = await r.json();
      if (!r.ok) throw new Error(j.error || "HTTP " + r.status);
    } catch (e) {
      $("fl-review-list").innerHTML = `<div class="fl-card-section">${notice("bad", "The review queue could not be loaded: " + esc(e.message))}</div>`;
      return;
    }
    const c = j.counts || {};
    const total = Object.values(c).reduce((a, b) => a + b, 0);
    $("fl-review-metrics").innerHTML = [
      ["Awaiting review", c.submitted || 0, "submitted snapshots"],
      ["Published", c.published || 0, "in the shared dataset product"],
      ["Returned for correction", c.returned || 0, "waiting for the submitter"],
      ["Closed", (c.rejected || 0) + (c.withdrawn || 0) + (c.superseded || 0) + (c.cancelled || 0), "rejected, withdrawn, superseded or cancelled"]
    ].map(([label, value, detail]) => `<div class="metric-card"><div class="metric-label">${label}</div>
      <div class="metric-value">${value}</div><div class="metric-detail">${detail}</div></div>`).join("");
    $("fl-review-tabs").innerHTML = TABS.map(([s, label]) =>
      `<button type="button" class="fl-tab ${s === filter ? "active" : ""}" data-filter="${s}" aria-pressed="${s === filter}">
        ${label}<span class="count">${s ? (c[s] || 0) : total}</span></button>`).join("");
    document.querySelectorAll("[data-filter]").forEach(b => b.addEventListener("click", () => { filter = b.dataset.filter; load(); }));
    $("fl-review-list").innerHTML = j.items.length ? `<div class="fl-table-wrap"><table><thead><tr>
      <th>Result</th><th>Dataset · flight</th><th class="num">Observations</th><th>Status</th><th>Submitted</th><th></th></tr></thead><tbody>${
      j.items.map(s => `<tr class="${s.submission_id === selected ? "fl-row-active" : ""}">
        <td><div class="detail-primary">${esc(s.filename)}</div><div class="detail-secondary fl-mono">${esc(s.submission_id)}${s.own ? " · your own submission" : ""}</div></td>
        <td>${esc(s.dataset_id)}<div class="detail-secondary">flight ${esc(s.flight)} · CBD ${esc(s.cbd_start)}–${esc(s.cbd_end)}</div></td>
        <td class="num">${s.observation_count}<div class="detail-secondary">${s.positioned_count} positioned</div></td>
        <td>${statusPill(s.status)}</td><td>${esc(when(s.submitted_at))}</td>
        <td><button type="button" class="small-button" data-open="${esc(s.submission_id)}">Inspect</button></td></tr>`).join("")}</tbody></table></div>`
      : `<p class="panel-empty">${EMPTY[filter]}</p>`;
    document.querySelectorAll("[data-open]").forEach(b => b.addEventListener("click", () => inspect(b.dataset.open)));
  }

  // the CBD and position approval publishes -- the rule of observations.map_position
  function published(o) {
    const status = o.geolocation_status || "unverified";
    if (status === "verified") return {cbd: o.verified_cbd, pos: o.verified_position, status};
    if (status === "label_unreadable" || status === "verified_no_navigation") return {cbd: o.verified_cbd ?? null, pos: null, status};
    return {cbd: o.cbd, pos: o.position || (Number.isFinite(o.lon) && Number.isFinite(o.lat) ? [o.lon, o.lat] : null), status: "unverified"};
  }

  function comparison(observations) {
    if (!observations.length) return `<p class="panel-empty">No observations are available for this snapshot.</p>`;
    const rows = observations.map(o => {
      const out = published(o), astra = o.astra_cbd ?? o.cbd;
      const differs = out.cbd !== null && out.cbd !== undefined && out.cbd !== astra;
      return `<tr class="${differs ? "fl-row-differs" : ""}"><td class="num">${o.a_scope}</td><td class="num">${esc(astra)}</td>
        <td class="num">${esc(o.film_cbd ?? "—")}</td>
        <td class="num"><strong>${esc(out.cbd ?? "—")}</strong>${out.status === "unverified" ? '<div class="detail-secondary">ASTRA</div>' : ""}</td>
        <td class="num">${out.pos ? num(out.pos[1], 5) + ", " + num(out.pos[0], 5) : "not mapped"}</td>
        <td class="num">${num(o.surface_us, 2)}</td><td class="num">${num(o.bed_us, 2)}</td><td class="num">${num(o.h_ice_m, 1)}</td>
        <td>${pill(...(GEO[out.status] || [out.status, "muted"]))}</td></tr>`;
    }).join("");
    return `<div class="fl-table-wrap"><table class="fl-review-obs"><thead><tr>
      <th class="num">A-scope</th><th class="num">ASTRA-assigned CBD</th><th class="num">Film CBD</th><th class="num">Published CBD</th>
      <th class="num">Published lat, lon</th><th class="num unit">Surface (µs)</th><th class="num unit">Bed (µs)</th><th class="num unit">Ice (m)</th><th>Geolocation</th>
      </tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function counts(observations) {
    const c = {};
    observations.forEach(o => { const k = published(o).status; c[k] = (c[k] || 0) + 1; });
    return c;
  }

  function decision(d, intact) {
    const s = d.submission;
    if (s.status === "submitted") {
      if (!intact) return notice("bad", "<strong>The snapshot is damaged or incomplete.</strong> It cannot be decided until it is restored from a backup.");
      if (d.own) return notice("info", "<strong>This is your own submission.</strong> Another reviewer must decide it.");
      const unverified = d.observations.filter(o => (o.geolocation_status || "unverified") !== "verified").length;
      return `<div class="fl-stack">
        <label class="fl-field">Note to the submitter
          <textarea id="fl-review-note" rows="3" maxlength="2000" placeholder="Required to return or reject; optional when approving"></textarea></label>
        ${unverified ? `<label class="fl-check"><input type="checkbox" id="fl-review-unverified">
          <span>Publish ${unverified} observation${unverified === 1 ? "" : "s"} without verified geolocation, labelled as <strong>unverified</strong>
          (ASTRA-assigned CBD and position; unreadable or unnavigated frames are not mapped).</span></label>` : ""}
        <div class="fl-actions">
          <button type="button" class="fl-btn primary" data-decide="approve">Approve and publish</button>
          <button type="button" class="fl-btn" data-decide="return">Return for correction</button>
          <button type="button" class="fl-btn danger" data-decide="reject">Reject</button>
        </div><div id="fl-review-message"></div></div>`;
    }
    if (s.status === "published") {
      return `<div class="fl-stack">
        <label class="fl-field">Reason for withdrawal
          <textarea id="fl-review-note" rows="2" maxlength="2000" placeholder="Required; recorded with the result's history"></textarea></label>
        <div class="fl-actions"><button type="button" class="fl-btn danger" data-withdraw>Withdraw publication</button></div>
        <div id="fl-review-message"></div></div>`;
    }
    return `<p class="fl-help">No further decisions: this submission is ${esc((STATUS[s.status] || [s.status])[0].toLowerCase())}.</p>`;
  }

  async function inspect(id) {
    selected = id;
    document.querySelectorAll(".fl-row-active").forEach(r => r.classList.remove("fl-row-active"));
    document.querySelector(`[data-open="${CSS.escape(id)}"]`)?.closest("tr")?.classList.add("fl-row-active");
    const host = $("fl-review-detail");
    host.innerHTML = `<section class="panel"><p class="panel-empty">Loading the snapshot…</p></section>`;
    let d;
    try {
      const r = await fetch(`${api}/${id}`, {credentials: "same-origin"});
      d = await r.json();
      if (!r.ok) throw new Error(d.error || "HTTP " + r.status);
    } catch (e) {
      host.innerHTML = `<section class="panel"><div class="fl-card-section">${notice("bad", esc(e.message))}</div></section>`;
      return;
    }
    const s = d.submission, p = d.provenance || {};
    const intact = !d.integrity || d.integrity.ok;
    const geo = counts(d.observations);
    const nav = p.navigation || s.navigation;
    const sup = d.supersedes_on_approval;
    const radar = s.catalog_id ? `<a class="small-button" href="/frozen-legacies/?open=${encodeURIComponent(s.catalog_id)}" target="_blank" rel="noopener">Open the radar</a>` : "";
    const row = (label, value) => `<div class="detail-row"><span>${label}</span><strong>${value}</strong></div>`;
    host.innerHTML = `
      <section class="panel">
        <div class="fl-card-head">
          <div class="fl-card-title"><h2>${esc(s.filename)}</h2>${statusPill(s.status)}
            ${d.own ? pill("Your own submission", "info") : ""}
            <small class="fl-mono">${esc(s.submission_id)}</small></div>
          <div class="fl-actions">${radar}</div>
        </div>
        <div class="fl-card-section fl-stack">
          ${sup ? notice("warn", `<strong>Approving replaces the published version</strong> <span class="fl-mono">${esc(sup.submission_id)}</span>
            of this radar file by the same submitter (${sup.observation_count} observations${sup.verified_count === null ? "" : ", " + sup.verified_count + " with verified geolocation"};
            published ${esc(when(sup.published_at))}). It will be marked superseded and leave the shared map.`) : ""}
          ${intact ? notice("ok", `<strong>Snapshot intact.</strong> All ${d.integrity ? d.integrity.files : ""} files match the hashes recorded at submission.`)
                   : notice("bad", `<strong>Snapshot damaged or incomplete:</strong> ${esc((d.integrity.problems || []).join("; "))}`)}
          ${notice(d.geolocation.verified ? "ok" : "warn", `<strong>Geolocation.</strong> ${esc(d.geolocation.message)}`)}
          ${s.note ? notice("info", `<strong>Submitter's note:</strong> ${esc(s.note)}`) : ""}
        </div>
        <div class="detail-grid fl-review-grid">
          <div>
            <div class="fl-card-section"><div class="fl-section-label">Scientific details</div></div>
            <div class="detail-list">
              ${row("Dataset", esc(s.dataset_id))}
              ${row("Flight · CBD range", `F${esc(s.flight)} · ${esc(s.cbd_start)}–${esc(s.cbd_end)} <small>(file name)</small>`)}
              ${row("Processing", `${esc(s.workflow)} · ${esc(s.producer_version)}`)}
              ${row("Session", `revision ${s.session_revision} · completed ${esc(when(s.completed_at))}`)}
              ${row("Source version", `<span class="fl-mono">${esc(s.source_version || "—")}</span>`)}
              ${row("Navigation", nav ? `${esc(nav.filename)} · ${esc(nav.lookup)} · <span class="fl-mono">${esc((nav.sha256 || "").slice(0, 12))}</span>` : "none")}
              ${row("Geolocation", Object.entries(geo).map(([k, v]) => `${v} ${esc((GEO[k] || [k])[0].split(" · ")[0].toLowerCase())}`).join(" · ") || "—")}
            </div>
          </div>
          <div>
            <div class="fl-card-section"><div class="fl-section-label">Publication</div></div>
            <div class="detail-list">
              ${row("Submitted", esc(when(s.submitted_at)))}
              ${row("Decided", esc(when(s.decided_at)))}
              ${s.published_at ? row("Published", esc(when(s.published_at))) : ""}
              ${s.accepted_unverified ? row("Unverified positions", "accepted by the reviewer") : ""}
              ${s.supersedes ? row("Supersedes", `<span class="fl-mono">${esc(s.supersedes)}</span>`) : ""}
              ${s.superseded_by ? row("Superseded by", `<span class="fl-mono">${esc(s.superseded_by)}</span>`) : ""}
              ${s.withdrawn_at ? row("Withdrawn", `${esc(when(s.withdrawn_at))} · ${esc(s.withdraw_reason || "")}`) : ""}
              ${s.decision_note ? row("Decision note", esc(s.decision_note)) : ""}
            </div>
            <div class="fl-card-section fl-actions">
              <a class="small-button" href="${api}/${id}/products/astra-csv">ASTRA CSV</a>
              <a class="small-button" href="${api}/${id}/products/astra-qc" target="_blank" rel="noopener">QC image</a>
              <a class="small-button" href="${api}/${id}/products/provenance">Provenance</a>
            </div>
          </div>
        </div>
        <div class="fl-card-section"><div class="fl-section-label">QC image — submitted picks on the radar strip</div>
          ${intact ? `<img class="fl-review-qc" src="${api}/${id}/products/astra-qc" alt="ASTRA QC image of the submitted picks" loading="lazy">` : '<p class="fl-help">Not available.</p>'}</div>
        <div class="fl-card-section"><div class="fl-section-label">Georeferencing comparison</div>
          <p class="fl-help">Approval publishes the <strong>Published</strong> CBD and position: the confirmed film CBD and its navigation
            record where geolocation is verified; ASTRA's own CBD and position, labelled unverified, otherwise. Highlighted rows differ from
            ASTRA's CBD. The ASTRA CSV and QC are unchanged.</p></div>
        ${comparison(d.observations)}
        <div class="fl-card-section"><div class="fl-section-label">Decision</div>${decision(d, intact)}</div>
      </section>`;
    const message = (kind, html) => { const m = $("fl-review-message"); if (m) m.innerHTML = notice(kind, html); };
    host.querySelectorAll("[data-decide]").forEach(b => b.addEventListener("click", async () => {
      const note = $("fl-review-note").value;
      if (b.dataset.decide !== "approve" && !note.trim()) { message("bad", "Give the submitter a reason."); return; }
      host.querySelectorAll("[data-decide]").forEach(x => { x.disabled = true; });
      try {
        await call(`${api}/${id}/decision`, {decision: b.dataset.decide, note,
          accept_unverified_geolocation: !!$("fl-review-unverified")?.checked});
        await load(); await inspect(id);
      } catch (e) {
        message("bad", esc(e.message));
        host.querySelectorAll("[data-decide]").forEach(x => { x.disabled = false; });
      }
    }));
    host.querySelector("[data-withdraw]")?.addEventListener("click", async () => {
      const reason = $("fl-review-note").value;
      if (!reason.trim()) { message("bad", "Give a reason for withdrawing the publication."); return; }
      if (!confirm("Withdraw this publication from the shared dataset product? Its snapshot and history are kept.")) return;
      try { await call(`${api}/${id}/withdraw`, {reason}); await load(); await inspect(id); }
      catch (e) { message("bad", esc(e.message)); }
    });
  }
  load();
})();
"""


async def control_review_page(request: web.Request) -> web.Response:
    from control_center.templates import control_layout
    from .control_style import STYLE

    content = """
    <div class="page-heading-row">
      <div>
        <h1>Frozen Legacies scientific review</h1>
        <p class="page-subtitle">Each submission is a frozen snapshot: the ASTRA CSV and QC image byte for byte,
        the observations, their georeferencing and provenance. Approval publishes the observations as a shared,
        reviewed dataset product; withdrawal removes them again. You cannot decide your own submissions.</p>
      </div>
      <a class="small-button" href="/control/frozen-legacies">← Data sources</a>
    </div>
    <div class="metric-grid" id="fl-review-metrics"></div>
    <section class="panel">
      <div class="fl-tabs" id="fl-review-tabs" role="toolbar" aria-label="Filter submissions"></div>
      <div id="fl-review-list"><p class="panel-empty">Loading…</p></div>
    </section>
    <div id="fl-review-detail">
      <section class="panel"><div class="placeholder-state"><div>
        <div class="placeholder-icon">⌕</div><h2>Select a submission</h2>
        <p>Inspect a submission to see its snapshot, the georeferencing comparison and the decision options.</p>
      </div></div></section>
    </div>
    <style>""" + STYLE + """
      .fl-review-grid { gap: 0; border-top: 1px solid #f1f5f9; }
      .fl-review-grid > div + div { border-left: 1px solid #f1f5f9; }
      .fl-review-grid .detail-row strong { text-align: right; overflow-wrap: anywhere; }
      .fl-review-qc { display: block; max-width: 100%; margin-top: 0.5rem; border: 1px solid #e2e8f0; border-radius: 8px; }
      .fl-review-obs { min-width: 900px; }
      .fl-section-label { margin-bottom: 0.35rem; }
      @media (max-width: 760px) { .fl-review-grid > div + div { border-left: 0; border-top: 1px solid #f1f5f9; } }
    </style>
    <script>""" + _REVIEW_SCRIPT + """</script>
    """
    return web.Response(text=control_layout(title="Frozen Legacies review",
                                            active="frozen-legacies", content=content),
                        content_type="text/html")


def install_review_routes(app: web.Application, *, auth, maintainer) -> None:
    api = "/frozen-legacies/api"
    asset = "{asset_id:[0-9a-f]{32}}"
    sid = "{submission_id:[^/]+}"
    kind = "{kind:[a-z-]+}"
    app.router.add_get(f"{api}/assets/{asset}/review", S._api(auth, _guard(api_review_state)))
    app.router.add_post(f"{api}/assets/{asset}/review", S._api(auth, _guard(api_review_action)))
    app.router.add_get(f"{api}/reviews/mine", S._api(auth, api_my_reviews))
    app.router.add_get(f"{api}/published/observations",
                       S._api(auth, api_published_observations))
    app.router.add_get(f"{api}/published/{sid}/products/{kind}",
                       S._api(auth, api_published_product))
    app.router.add_get(f"{api}/admin/reviews", maintainer(auth, api_admin_reviews))
    app.router.add_get(f"{api}/admin/reviews/{sid}", maintainer(auth, api_admin_review_detail))
    app.router.add_get(f"{api}/admin/reviews/{sid}/products/{kind}",
                       maintainer(auth, api_admin_review_product))
    app.router.add_post(f"{api}/admin/reviews/{sid}/decision",
                        maintainer(auth, api_admin_review_decision))
    app.router.add_post(f"{api}/admin/reviews/{sid}/withdraw",
                        maintainer(auth, api_admin_review_withdraw))
    control_access = auth.require_roles("maintainer", "admin", "owner")
    app.router.add_get("/control/frozen-legacies/review", control_access(control_review_page))
