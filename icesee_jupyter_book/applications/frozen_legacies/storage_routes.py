"""Workspace storage: quota enforcement, usage, and administrator settings.

User API (signed in):

* ``GET  /frozen-legacies/api/storage/usage`` -- the caller's usage, quota,
  available bytes, status (``ok`` | ``warning`` | ``over``) and the current
  per-file upload limit.

Administrator API (Control Center ``admin`` or ``owner``, checked against the
role store on every request; maintainers manage data sources, not quotas):

* ``GET  /frozen-legacies/api/admin/storage`` -- settings, totals (workspace
  usage, shared cache usage, server disk), every user's usage and quota, and
  a summary of the registered data sources;
* ``POST /frozen-legacies/api/admin/storage/settings`` -- default quota,
  maximum upload size, warning thresholds;
* ``POST /frozen-legacies/api/admin/storage/users/<user_id>`` -- set or clear
  (``"quota_bytes": null``) a per-user quota.

Every change is written to the Control Center audit log
(``access_audit_log``) with the previous and new value. Responses never carry
filesystem paths or provider credentials.

Enforcement: :func:`quota_middleware` sits in front of the chargeable Frozen
Legacies requests (see :data:`CHARGEABLE`); the handlers themselves are
unchanged. The platform Data page ``/control/storage`` presents the
administrator API.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path

from aiohttp import web

from cryostack_src.workspace import owner_root

from . import server as S
from .radar import quota as Q
from .workspace import workspace_user_for


ADMIN_ROLES = frozenset({"admin", "owner"})
STORE_KEY = "frozen_legacies_quota_store"
ACCOUNTS_KEY = "frozen_legacies_quota_accounts"
_API = "/frozen-legacies/api"
_ASSET = r"[0-9a-f]{32}"
#: an automatic run's outputs are bounded (diagnostics 128 MiB + products);
#: this much must be free to start one
AUTOMATIC_RESERVE_BYTES = 160 * Q.MIB
#: the user-facing description of each chargeable request
CHARGEABLE = [
    (re.compile(rf"^{_API}/assets/upload$"), "upload", "this upload"),
    (re.compile(rf"^{_API}/assets/products$"), "upload", "this upload"),
    (re.compile(rf"^{_API}/assets/{_ASSET}/products$"), "upload", "this upload"),
    (re.compile(rf"^{_API}/assets/{_ASSET}/manual$"), "write", "saving picking results"),
    (re.compile(rf"^{_API}/assets/{_ASSET}/georef$"), "write", "saving georeferencing"),
    (re.compile(rf"^{_API}/assets/{_ASSET}/automatic$"), "automatic", "automatic picking"),
]
_USER_ID = re.compile(r"[A-Za-z0-9._:@-]{1,200}")


def _store(app) -> Q.QuotaStore:
    return app[STORE_KEY]


def _accounts(app) -> Q.QuotaAccounts:
    return app[ACCOUNTS_KEY]


def _workspace_root(app):
    return app.get(S.WORKSPACE_ROOT_KEY)


def user_root(app, user) -> Path:
    return owner_root(workspace_user_for(user), workspace_root=_workspace_root(app))


def max_upload_bytes(app) -> int:
    return min(Q.HARD_MAX_UPLOAD_BYTES, _store(app).settings()["max_upload_bytes"])


async def usage_for(app, user, *, refresh: bool = False) -> Q.Usage:
    root = user_root(app, user)
    return await S._blocking(_accounts(app).usage, root, str(user.id), refresh=refresh)


def _quota_error(error: Q.QuotaExceeded) -> web.Response:
    return web.json_response({"error": str(error), "quota": error.usage.public()},
                             status=413, headers={"Cache-Control": "no-store"})


# ── enforcement ──────────────────────────────────────────────────────
def make_quota_middleware(auth):
    @web.middleware
    async def quota_middleware(request: web.Request, handler):
        if request.method != "POST" or not request.path.startswith(_API + "/"):
            return await handler(request)
        match = next(((kind, what) for pattern, kind, what in CHARGEABLE
                      if pattern.match(request.path)), None)
        if match is None:
            return await handler(request)
        user = auth.current_user(request)
        if user is None:                     # the handler answers 401 itself
            return await handler(request)
        kind, what = match
        app = request.app
        if kind == "automatic":
            try:
                payload = json.loads((await request.read())[:4096] or b"{}")
            except ValueError:
                payload = {}
            if not isinstance(payload, dict) or payload.get("action") != "start":
                return await handler(request)       # cancelling is never blocked
            nbytes = AUTOMATIC_RESERVE_BYTES
        elif kind == "upload":
            declared = request.content_length
            if declared is None:
                # the declared length bounds what is written (aiohttp stops a
                # body at Content-Length), so the reservation is exact
                return S._error(411, "Uploads must declare their size (Content-Length).")
            limit = max_upload_bytes(app)
            if declared > limit + 512 * 1024:
                return S._error(413, f"Uploads are limited to {Q.format_bytes(limit)} per file.")
            nbytes = int(declared)
        else:
            nbytes = 0
        root = user_root(app, user)
        accounts = _accounts(app)
        usage = await S._blocking(accounts.usage, root, str(user.id))
        try:
            # reserve on the event loop thread: check and reserve are atomic
            reserved = accounts.reserve(usage, root, nbytes, what=what)
        except Q.QuotaExceeded as error:
            return _quota_error(error)
        try:
            return await handler(request)
        finally:
            accounts.release(root, reserved)

    return quota_middleware


# ── user API ─────────────────────────────────────────────────────────
async def api_storage_usage(request: web.Request) -> web.Response:
    user = request["cryostack_user"]
    usage = await usage_for(request.app, user, refresh=request.query.get("refresh") == "1")
    return S._json({**usage.public(), "max_upload_bytes": max_upload_bytes(request.app),
                    "max_upload": Q.format_bytes(max_upload_bytes(request.app))})


def _scope_label(name: str) -> str:
    return {"frozen_legacies": "Frozen Legacies", "livist": "LIVIST",
            "datasets": "Shared datasets", "examples": "Editable examples",
            ".cryostack": "CryoLauncher and ICESEE runs"}.get(name, name.replace("_", " ").title())


def _path_usage(path: Path) -> dict:
    if path.is_file() and not path.is_symlink():
        return {"bytes": path.stat().st_size, "files": 1}
    return Q.measure(path)


def _storage_scopes(app, user) -> list[dict]:
    root = user_root(app, user)
    if not root.is_dir():
        return []
    scopes = []
    for path in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if path.name.startswith(".cryostack-trash-"):
            continue
        try:
            info = _path_usage(path)
        except OSError:
            continue
        scopes.append({"id": path.name, "label": _scope_label(path.name),
                       "bytes": info["bytes"], "files": info["files"]})
    return scopes


async def api_global_storage(request: web.Request) -> web.Response:
    user = request["cryostack_user"]
    usage = await usage_for(request.app, user, refresh=request.query.get("refresh") == "1")
    scopes = await S._blocking(_storage_scopes, request.app, user)
    settings = await S._blocking(_store(request.app).settings)
    disk = await S._blocking(Q.disk_status, user_root(request.app, user))
    return S._json({**usage.public(), "scopes": scopes, "disk": disk,
                    "disk_reserve_bytes": settings["disk_reserve_bytes"]})


def _delete_scopes(app, user, requested: list[str]) -> dict:
    root = user_root(app, user)
    root.mkdir(parents=True, exist_ok=True)
    available = {p.name: p for p in root.iterdir()
                 if not p.name.startswith(".cryostack-trash-")}
    if not requested or any(name not in available for name in requested):
        raise Q.QuotaError("The selected workspace files changed; refresh and try again.")
    stage = root.parent / f".{root.name}.cryostack-trash-{uuid.uuid4().hex}"
    stage.mkdir(mode=0o700)
    moved = []
    try:
        for name in requested:
            source = available[name]
            if source.parent.resolve() != root.resolve():
                raise Q.QuotaError("Invalid storage selection.")
            destination = stage / name
            source.rename(destination)
            moved.append((source, destination))
    except Exception:
        for source, destination in reversed(moved):
            if destination.exists() and not source.exists():
                destination.rename(source)
        stage.rmdir()
        raise
    before = Q.measure(stage)
    shutil.rmtree(stage)
    _accounts(app).invalidate(root)
    return {"deleted_bytes": before["bytes"], "deleted_files": before["files"],
            "deleted_scopes": requested}


async def api_global_storage_delete(request: web.Request) -> web.Response:
    try:
        S._require_same_origin(request)
        user = request["cryostack_user"]
        payload = await _payload(request)
        scopes = payload.get("scopes")
        if not isinstance(scopes, list) or not all(isinstance(v, str) for v in scopes):
            raise Q.QuotaError("Select one or more application storage groups.")
        if payload.get("confirmation") != "DELETE MY FILES":
            raise Q.QuotaError('Type "DELETE MY FILES" to confirm permanent deletion.')
        result = await S._blocking(_delete_scopes, request.app, user,
                                   list(dict.fromkeys(scopes)))
    except Q.QuotaError as error:
        return S._error(400, str(error))
    await S._blocking(_audit, request.app[_AUTH_KEY], user,
                      action="cryostack.storage.user_bulk_delete",
                      previous=result["deleted_bytes"], new=0,
                      reason="user permanently deleted workspace files",
                      metadata={"scopes": result["deleted_scopes"],
                                "files": result["deleted_files"]})
    usage = await usage_for(request.app, user, refresh=True)
    return S._json({**result, "usage": usage.public()})


# ── administrator API ────────────────────────────────────────────────
def _admin(auth, handler):
    async def protected(request: web.Request) -> web.StreamResponse:
        user = auth.current_user(request)
        if user is None:
            return S._error(401, "Authentication required.")
        if not set(auth.storage.get_user_roles(user_id=user.id)) & ADMIN_ROLES:
            return S._error(403, "Managing workspace storage requires an administrator role.")
        request["cryostack_user"] = user
        try:
            return await handler(request)
        except Q.QuotaError as error:
            return S._error(400, str(error))

    return protected


def _list_users(auth) -> list[dict]:
    with auth.storage._connect() as db:
        rows = db.execute("SELECT id, email, display_name FROM users ORDER BY email").fetchall()
    return [{"user_id": r[0], "email": r[1], "display_name": r[2]} for r in rows]


class _AuditUser:
    def __init__(self, user_id: str):
        self.id = user_id


def _storage_overview(app, auth) -> dict:
    store, accounts = _store(app), _accounts(app)
    settings = store.settings()
    overrides = store.overrides()
    users, total = [], 0
    for item in _list_users(auth):
        root = user_root(app, _AuditUser(item["user_id"]))
        used = accounts.measured(root, refresh=True)
        quota = overrides.get(item["user_id"], settings["default_quota_bytes"])
        usage = Q.Usage(used, accounts.reserved(root), quota,
                        item["user_id"] in overrides, settings["warn_percent"])
        total += used
        users.append({**item, **usage.public()})
    from .radar.working_cache import working_cache
    cache = working_cache()
    cache_bytes = cache.usage()
    workspace_base = Path(_workspace_root(app) or ".").resolve()
    disk = Q.disk_status(workspace_base)
    disk_status = None
    if disk and disk.get("percent") is not None:
        disk_status = "warning" if disk["percent"] >= settings["disk_warn_percent"] else "ok"
    return {
        "settings": settings,
        "limits": {name: {"min": spec[1], "max": spec[2], "default": spec[0]}
                   for name, spec in Q.SETTINGS.items()},
        "totals": {"workspace_bytes": total, "users": len(users),
                   "over_quota": sum(1 for u in users if u["status"] == "over"),
                   "warning": sum(1 for u in users if u["status"] == "warning"),
                   "cache_bytes": cache_bytes,
                   "cache_limit_bytes": getattr(cache, "max_bytes", None),
                   "disk": disk, "disk_status": disk_status},
        "users": users,
        "sources": _source_summary(),
    }


def _source_summary() -> list[dict]:
    from .catalog_routes import _admin_listing
    from .radar.catalog import open_catalog
    catalog = open_catalog()
    if catalog is None:
        return []
    out = []
    for source in _admin_listing(catalog):
        out.append({k: source.get(k) for k in (
            "source_id", "name", "provider", "dataset_id", "status", "visibility",
            "last_index_at", "last_index_status")}
            | {"files": (source.get("counts") or {}).get("total", 0),
               "connection_ok": source["connection"]["ok"],
               "connection_checked_at": source["connection"]["checked_at"]})
    return out


async def api_admin_storage(request: web.Request) -> web.Response:
    return S._json(await S._blocking(_storage_overview, request.app, request.app[_AUTH_KEY]))


def _audit(auth, actor, *, action, target_user_id=None, target_label=None, previous, new,
           reason, metadata=None) -> None:
    auth.storage.record_access_audit(
        actor_user_id=actor.id, actor_label=getattr(actor, "email", None) or actor.id,
        target_user_id=target_user_id, target_label=target_label, action=action,
        previous_value=None if previous is None else str(previous),
        new_value=None if new is None else str(new), reason=reason, metadata=metadata)


async def _payload(request) -> dict:
    S._require_same_origin(request)
    if (request.content_length or 0) > 4096:
        raise Q.QuotaError("Request body is too large.")
    try:
        payload = await request.json()
    except ValueError:
        raise Q.QuotaError("A JSON body is required.")
    if not isinstance(payload, dict):
        raise Q.QuotaError("A JSON object is required.")
    return payload


async def api_admin_storage_settings(request: web.Request) -> web.Response:
    payload = await _payload(request)
    reason = str(payload.pop("reason", "") or "").strip()[:500] or "storage settings changed"
    unknown = set(payload) - set(Q.SETTINGS)
    if unknown:
        raise Q.QuotaError(f"Unknown storage settings: {', '.join(sorted(unknown))}.")
    store, auth, actor = _store(request.app), request.app[_AUTH_KEY], request["cryostack_user"]
    previous_settings = await S._blocking(store.settings)
    for name, value in payload.items():          # all validated before any is stored
        _d, low, high = Q.SETTINGS[name]
        number = Q._integer(value, name)
        if not low <= number <= high:
            raise Q.QuotaError(f"{name} must be between {low} and {high}.")
    for name, value in payload.items():
        previous, new = await S._blocking(store.set_setting, name, value, actor=actor.id)
        if previous != new:
            await S._blocking(_audit, auth, actor, action=f"cryostack.storage.{name}",
                              previous=previous, new=new, reason=reason)
    settings = await S._blocking(store.settings)
    overrides = await S._blocking(store.overrides)
    users = await S._blocking(_list_users, auth)
    default_users = [item for item in users if item["user_id"] not in overrides]
    return S._json({"settings": settings, "impact": {
        "default_changed": previous_settings["default_quota_bytes"] != settings["default_quota_bytes"],
        "users_using_default": len(default_users),
        "users_with_overrides": len(overrides),
    }})


async def api_admin_user_quota(request: web.Request) -> web.Response:
    user_id = request.match_info["user_id"]
    if not _USER_ID.fullmatch(user_id):
        raise Q.QuotaError("Invalid user ID.")
    auth = request.app[_AUTH_KEY]
    target = await S._blocking(auth.storage.get_user_by_id, user_id)
    if target is None:
        return S._error(404, "User not found.")
    payload = await _payload(request)
    if "quota_bytes" not in payload:
        raise Q.QuotaError("quota_bytes is required (null clears the override).")
    reason = str(payload.get("reason") or "").strip()[:500] or "workspace quota changed"
    store, actor = _store(request.app), request["cryostack_user"]
    previous, new = await S._blocking(store.set_override, user_id, payload["quota_bytes"],
                                      actor=actor.id)
    if previous != new:
        await S._blocking(_audit, auth, actor, action="cryostack.storage.user_quota",
                          target_user_id=user_id, target_label=target.email,
                          previous=previous if previous is not None else "default",
                          new=new if new is not None else "default", reason=reason)
    usage = await usage_for(request.app, target, refresh=True)
    return S._json({"user_id": user_id, **usage.public()})


# ── Control Center page ──────────────────────────────────────────────
_PAGE_SCRIPT = r"""
(function () {
  "use strict";
  const API = "/frozen-legacies/api/admin/storage";
  const $ = id => document.getElementById(id);
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"}[c]));
  const GIB = 1024 ** 3, MIB = 1024 ** 2;
  function fmt(b) {
    if (b === null || b === undefined) return "—";
    const u = ["B", "KiB", "MiB", "GiB", "TiB"]; let i = 0, v = Number(b);
    while (Math.abs(v) >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return i ? `${v.toFixed(1)} ${u[i]}` : `${v} B`;
  }
  const when = t => t ? new Date(t * 1000).toLocaleString() : "never";
  const chip = s => `<span class="fl-chip ${s === "over" ? "bad" : s === "warning" ? "warn" : "ok"}">${esc({ok: "OK", warning: "Near quota", over: "Over quota"}[s] || s)}</span>`;
  async function call(url, opts) {
    const r = await fetch(url, Object.assign({credentials: "same-origin", headers: {"Content-Type": "application/json"}}, opts || {}));
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
    return body;
  }
  function metric(label, value, note) {
    return `<div class="metric-card"><div class="metric-label">${esc(label)}</div>
      <div class="metric-value">${esc(value)}</div><div class="metric-detail">${esc(note || "")}</div></div>`;
  }
  let data = null;
  function render() {
    const t = data.totals, s = data.settings;
    $("st-metrics").innerHTML =
      metric("Workspace usage", fmt(t.workspace_bytes), `${t.users} users · ${t.over_quota} over quota · ${t.warning} near quota`) +
      metric("Shared radar cache", fmt(t.cache_bytes), t.cache_limit_bytes ? `limit ${fmt(t.cache_limit_bytes)}` : "") +
      metric("Server storage free", t.disk ? fmt(t.disk.free_bytes) : "—", t.disk ? `${t.disk.percent}% used of ${fmt(t.disk.total_bytes)}${t.disk_status === "warning" ? " · above warning threshold" : ""}` : "") +
      metric("Default quota", fmt(s.default_quota_bytes), `max upload ${fmt(s.max_upload_bytes)}`);
    $("st-default").value = (s.default_quota_bytes / GIB).toString();
    $("st-upload").value = Math.round(s.max_upload_bytes / MIB).toString();
    $("st-upload").max = Math.round(data.limits.max_upload_bytes.max / MIB);
    $("st-warn").value = s.warn_percent;
    $("st-disk-warn").value = s.disk_warn_percent;
    $("st-disk-reserve").value = (s.disk_reserve_bytes / GIB).toString();
    $("st-users").innerHTML = data.users.length ? data.users.map(u => `
      <tr data-user="${esc(u.user_id)}">
        <td><strong>${esc(u.display_name || u.email)}</strong><br><span class="fl-help">${esc(u.email)}</span></td>
        <td>${esc(fmt(u.used_bytes))}</td>
        <td>${esc(fmt(u.quota_bytes))}${u.override ? ' <span class="fl-chip">override</span>' : ""}</td>
        <td>${esc(fmt(u.available_bytes))}</td>
        <td>${chip(u.status)} <span class="fl-help">${esc(u.percent)}%</span></td>
        <td class="st-override"><input type="number" min="0" step="0.1" aria-label="Quota in GiB for ${esc(u.email)}" placeholder="GiB" value="${u.override ? (u.quota_bytes / GIB) : ""}">
          <button type="button" class="small-button" data-set>Set</button>
          ${u.override ? '<button type="button" class="small-button" data-clear>Use default</button>' : ""}</td>
      </tr>`).join("") : `<tr><td colspan="6" class="panel-empty">No users.</td></tr>`;
    $("st-sources").innerHTML = data.sources.length ? data.sources.map(src => `
      <tr><td><strong>${esc(src.name)}</strong><br><span class="fl-help">${esc(src.source_id)} · ${esc(src.dataset_id)}</span></td>
        <td>${esc(src.provider)}</td>
        <td>${src.connection_ok === null ? "not tested" : src.connection_ok ? chip("ok").replace("OK", "Connected") : '<span class="fl-chip bad">Failed</span>'}<br><span class="fl-help">${esc(when(src.connection_checked_at))}</span></td>
        <td>${esc(when(src.last_index_at))}<br><span class="fl-help">${esc(src.last_index_status || "")}</span></td>
        <td>${esc(src.files)}</td>
        <td>${esc(src.status)}${src.visibility === "maintainers" ? " · maintainers only" : ""}</td></tr>`).join("")
      : `<tr><td colspan="6" class="panel-empty">No data sources registered. Add them under <a href="/control/frozen-legacies">Data sources</a>.</td></tr>`;
    document.querySelectorAll("#st-users [data-set], #st-users [data-clear]").forEach(b => b.addEventListener("click", async () => {
      const row = b.closest("tr"), id = row.dataset.user;
      const gib = row.querySelector("input").value;
      const quota = b.hasAttribute("data-clear") ? null : Math.round(Number(gib) * GIB);
      if (quota !== null && !(gib !== "" && Number.isFinite(quota) && quota >= 0)) { status("Enter a quota in GiB.", true); return; }
      const reason = prompt("Reason for this change (recorded in the audit log):", "") ;
      if (reason === null) return;
      try { await call(`${API}/users/${encodeURIComponent(id)}`, {method: "POST", body: JSON.stringify({quota_bytes: quota, reason})}); status("Quota updated."); load(); }
      catch (e) { status(e.message, true); }
    }));
  }
  function status(text, bad) { const el = $("st-status"); el.textContent = text; el.className = "fl-notice " + (bad ? "error" : "info"); el.hidden = false; }
  async function load() {
    try { data = await call(API); render(); } catch (e) { status(e.message, true); }
  }
  $("st-settings").addEventListener("submit", async ev => {
    ev.preventDefault();
    const body = {
      default_quota_bytes: Math.round(Number($("st-default").value) * GIB),
      max_upload_bytes: Math.round(Number($("st-upload").value) * MIB),
      warn_percent: Number($("st-warn").value), disk_warn_percent: Number($("st-disk-warn").value),
      disk_reserve_bytes: Math.round(Number($("st-disk-reserve").value) * GIB),
      reason: $("st-reason").value };
    try { const saved = await call(`${API}/settings`, {method: "POST", body: JSON.stringify(body)});
      const impact = saved.impact || {}; const quota = fmt(saved.settings.default_quota_bytes);
      status(impact.default_changed
        ? `Default quota changed to ${quota} for ${impact.users_using_default} user${impact.users_using_default === 1 ? "" : "s"}. ${impact.users_with_overrides} per-user override${impact.users_with_overrides === 1 ? "" : "s"} unchanged.`
        : `Storage and quota settings saved. Default remains ${quota} for ${impact.users_using_default} user${impact.users_using_default === 1 ? "" : "s"}.`);
      $("st-reason").value = ""; load(); }
    catch (e) { status(e.message, true); }
  });
  load();
})();
"""


async def control_storage_page(request: web.Request) -> web.Response:
    from control_center.templates import control_layout
    from .catalog_routes import _control_heading
    from .control_style import STYLE

    content = _control_heading(
        "Storage & quotas",
        "Account-wide workspace quotas, upload limits and storage use across every application. "
        "External shared datasets and rebuildable caches never count. Nothing is deleted "
        "to enforce a quota: users above it keep their files but cannot add new ones.",
        '<a class="small-button" href="/control/">← Control Center</a>') + """
    <div class="metric-grid" id="st-metrics"></div>
    <p id="st-status" class="fl-notice" hidden role="status"></p>
    <section class="panel">
      <div class="panel-header">Global settings</div>
      <form id="st-settings" class="fl-form">
        <div class="fl-fields">
          <label class="fl-field">Default workspace quota (GiB)
            <input id="st-default" type="number" min="0" step="0.1" required></label>
          <label class="fl-field">Maximum upload size (MiB per file)
            <input id="st-upload" type="number" min="1" step="1" required>
            <span class="fl-help">At most 200 MiB, the limit of the upload service.</span></label>
          <label class="fl-field">User warning threshold (%)
            <input id="st-warn" type="number" min="1" max="100" required></label>
          <label class="fl-field">Server storage warning threshold (%)
            <input id="st-disk-warn" type="number" min="1" max="100" required></label>
          <label class="fl-field">Minimum server free-space reserve (GiB)
            <input id="st-disk-reserve" type="number" min="1" step="0.1" required>
            <span class="fl-help">New writes are refused before local storage falls below this reserve.</span></label>
          <label class="fl-field wide">Reason (recorded in the audit log)
            <input id="st-reason" maxlength="500" placeholder="Why the settings change"></label>
        </div>
        <div class="fl-actions"><button type="submit" class="fl-btn primary">Save settings</button></div>
      </form>
    </section>
    <section class="panel">
      <div class="panel-header">Users</div>
      <div class="st-scroll"><table class="data-table">
        <thead><tr><th>User</th><th>Used</th><th>Quota</th><th>Remaining</th><th>Status</th><th>Override</th></tr></thead>
        <tbody id="st-users"><tr><td colspan="6" class="panel-empty">Loading…</td></tr></tbody>
      </table></div>
    </section>
    <section class="panel">
      <div class="panel-header">Data sources</div>
      <div class="st-scroll"><table class="data-table">
        <thead><tr><th>Source</th><th>Provider</th><th>Connection</th><th>Last indexed</th><th>Files</th><th>Status</th></tr></thead>
        <tbody id="st-sources"></tbody>
      </table></div>
    </section>
    <style>""" + STYLE + """
      .st-scroll { overflow-x: auto; }
      .st-override input { width: 6rem; }
      .fl-chip.ok { background: #e7f6ec; color: #17673a; }
      .fl-chip.warn { background: #fff4d6; color: #7a5600; }
      .fl-chip.bad { background: #fde8e8; color: #a12222; }
    </style>
    <script>""" + _PAGE_SCRIPT + """</script>"""
    return web.Response(text=control_layout(title="Storage & quotas",
                                            active="storage", content=content),
                        content_type="text/html")


async def legacy_storage_redirect(request: web.Request) -> web.StreamResponse:
    raise web.HTTPMovedPermanently(location="/control/storage")


async def user_storage_page(request: web.Request) -> web.Response:
    """Account-wide storage manager; every operation remains owner scoped."""
    page = r'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>My storage | CryoStack</title><link rel="stylesheet" href="/_static/icesee.css">
<style>
body{margin:0;background:#f4f7fa;color:#14263d;font:14px system-ui,sans-serif}.bar{height:64px;background:#fff;border-bottom:1px solid #dce5ed;display:flex;align-items:center;justify-content:space-between;padding:0 28px}.brand{font-weight:800;color:#135f9b;text-decoration:none}.wrap{max-width:1000px;margin:32px auto;padding:0 20px}.hero,.card{background:#fff;border:1px solid #dce5ed;border-radius:16px;box-shadow:0 6px 24px rgba(20,48,66,.05)}.hero{padding:25px 28px;margin-bottom:18px}.hero h1{margin:0 0 7px;font-size:27px}.hero p{margin:0;color:#5b7088}.meter{height:12px;background:#e8eef3;border-radius:99px;overflow:hidden;margin:22px 0 8px}.meter i{display:block;height:100%;background:#2279bd;border-radius:99px}.usage{display:flex;justify-content:space-between;color:#526a82;font-size:13px}.card{padding:0 24px 22px}.head{display:flex;justify-content:space-between;align-items:center;padding:20px 0 13px;border-bottom:1px solid #e3eaf0}.head h2{margin:0;font-size:17px}.row{display:grid;grid-template-columns:28px 1fr auto auto;gap:14px;align-items:center;padding:15px 2px;border-bottom:1px solid #edf1f4}.row strong{display:block}.row small{color:#6a7e92}.size{font-variant-numeric:tabular-nums;color:#34536c}.danger{margin-top:20px;padding:16px;border:1px solid #f0c6c6;background:#fff8f8;border-radius:12px}.danger button{background:#b42318;color:#fff;border:0;border-radius:8px;padding:10px 14px;font-weight:700}.danger button:disabled{opacity:.45}.confirm{display:flex;gap:8px;align-items:end;flex-wrap:wrap;margin-top:12px}.confirm label{display:flex;flex-direction:column;gap:5px;color:#6a3b3b}.confirm input{padding:9px;border:1px solid #d7a9a9;border-radius:7px}.notice{padding:11px;border-radius:8px;margin:14px 0;background:#eaf4fc}.reserve{margin-top:16px;color:#687d90;font-size:12px}@media(max-width:600px){.row{grid-template-columns:25px 1fr auto}.row .files{display:none}.bar{padding:0 14px}}
</style></head><body><header class="bar"><a class="brand" href="/">CryoStack</a><div id="cryostack-account-slot"></div></header>
<main class="wrap"><section class="hero"><h1>My storage</h1><p>One allowance covers your files across every CryoStack application.</p><div class="meter"><i id="meter" style="width:0"></i></div><div class="usage"><strong id="used">Loading…</strong><span id="remaining"></span></div><div class="reserve" id="reserve"></div></section>
<section class="card"><div class="head"><h2>Application files</h2><label><input type="checkbox" id="all"> Select all</label></div><div id="rows"></div><div class="danger"><strong>Permanently delete selected files</strong><p>This cannot be undone. Stop active jobs and close application sessions first.</p><div class="confirm"><label>Type DELETE MY FILES<input id="confirm" autocomplete="off"></label><button id="delete" disabled>Delete selected</button></div></div><div id="notice" hidden class="notice" role="status"></div></section></main>
<script src="/_static/cryostack_account.js"></script><script>
const API="/api/storage";const $=id=>document.getElementById(id);let data;
function fmt(n){const u=["B","KiB","MiB","GiB","TiB"];let i=0,v=Number(n||0);while(v>=1024&&i<u.length-1){v/=1024;i++}return `${v.toFixed(i?1:0)} ${u[i]}`}
function selected(){return [...document.querySelectorAll("[data-scope]:checked")].map(e=>e.dataset.scope)}
function sync(){const boxes=[...document.querySelectorAll("[data-scope]")];$("all").checked=boxes.length>0&&boxes.every(b=>b.checked);$("delete").disabled=!selected().length||$("confirm").value!=="DELETE MY FILES"}
function render(){const pct=data.quota_bytes?Math.min(100,100*data.used_bytes/data.quota_bytes):100;$("meter").style.width=`${pct}%`;$("used").textContent=`${fmt(data.used_bytes)} used of ${fmt(data.quota_bytes)}`;$("remaining").textContent=`${fmt(data.available_bytes)} available`;$("reserve").textContent=`Server safety reserve: ${fmt(data.disk_reserve_bytes)} must remain free${data.disk?` · ${fmt(data.disk.free_bytes)} currently free`:""}.`;$("rows").innerHTML=data.scopes.length?data.scopes.map(s=>`<label class="row"><input type="checkbox" data-scope="${s.id}"><span><strong>${s.label}</strong><small>${s.files} file${s.files===1?"":"s"}</small></span><span class="files">${s.id}</span><span class="size">${fmt(s.bytes)}</span></label>`).join(""):"<p>No stored application files.</p>";document.querySelectorAll("[data-scope]").forEach(e=>e.onchange=sync);sync()}
async function load(){const r=await fetch(`${API}?refresh=1`,{credentials:"same-origin",headers:{Accept:"application/json"}});data=await r.json();if(!r.ok)throw Error(data.error||`HTTP ${r.status}`);render()}
$("all").onchange=e=>{document.querySelectorAll("[data-scope]").forEach(b=>b.checked=e.target.checked);sync()};$("confirm").oninput=sync;
$("delete").onclick=async()=>{const scopes=selected();if(!scopes.length)return;$("delete").disabled=true;try{const r=await fetch(`${API}/delete`,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-Requested-With":"CryoStack"},body:JSON.stringify({scopes,confirmation:$("confirm").value})});const body=await r.json();if(!r.ok)throw Error(body.error||`HTTP ${r.status}`);$("notice").hidden=false;$("notice").textContent=`Deleted ${body.deleted_files} files and recovered ${fmt(body.deleted_bytes)}.`;$("confirm").value="";await load()}catch(e){$("notice").hidden=false;$("notice").textContent=e.message}finally{sync()}};
load().catch(e=>{$("notice").hidden=false;$("notice").textContent=e.message});
</script></body></html>'''
    return web.Response(text=page, content_type="text/html")


_AUTH_KEY = "frozen_legacies_storage_auth"


def install_storage_routes(app: web.Application, *, auth) -> None:
    app[STORE_KEY] = Q.QuotaStore()
    app[ACCOUNTS_KEY] = Q.QuotaAccounts(app[STORE_KEY])
    app[_AUTH_KEY] = auth
    app.middlewares.append(make_quota_middleware(auth))
    app.router.add_get(f"{_API}/storage/usage", S._api(auth, api_storage_usage))
    app.router.add_get("/api/storage", S._api(auth, api_global_storage))
    app.router.add_post("/api/storage/delete", S._api(auth, api_global_storage_delete))
    app.router.add_get("/storage", auth.require_login(user_storage_page))
    app.router.add_get("/storage/", auth.require_login(user_storage_page))
    app.router.add_get(f"{_API}/admin/storage", _admin(auth, api_admin_storage))
    app.router.add_post(f"{_API}/admin/storage/settings", _admin(auth, api_admin_storage_settings))
    app.router.add_post(f"{_API}/admin/storage/users/{{user_id}}",
                        _admin(auth, api_admin_user_quota))
    admin_access = auth.require_roles("admin", "owner")
    app.router.add_get("/control/frozen-legacies/storage",
                       admin_access(legacy_storage_redirect))
    app.router.add_get("/control/storage", admin_access(control_storage_page))
    app.router.add_get("/control/storage/", admin_access(control_storage_page))
