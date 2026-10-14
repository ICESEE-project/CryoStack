# control_center/pages/ops.py

"""Analytics, Diagnostics and Settings pages and their JSON APIs.

Viewing requires a Control Center role (developer, maintainer, admin,
owner -- enforced by the route wrapper). Changing a setting additionally
requires maintainer, admin or owner, checked against the role store on
every request, and is refused when the request comes from another origin.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from aiohttp import web

from ..services.settings import SETTINGS_WRITE_ROLES, SettingsError
from ..templates_ops import analytics_page, diagnostics_page, settings_page


ANALYTICS_KEY = "control_analytics_service"
DIAGNOSTICS_KEY = "control_diagnostics_service"
SETTINGS_KEY = "control_settings_service"
AUTH_KEY = "control_ops_auth"

_DONE = {
    "saved": "Setting saved.",
    "reset": "Stored value removed; the default (or environment) value applies.",
    "rollback": "Change rolled back.",
}
MAX_FORM_BYTES = 8 * 1024


def _base_url(request: web.Request) -> str:
    """Loopback URL of this gateway (the port this request arrived on)."""
    port = None
    transport = request.transport
    if transport is not None:
        sockname = transport.get_extra_info("sockname")
        if isinstance(sockname, tuple) and len(sockname) >= 2:
            port = sockname[1]
    return f"http://127.0.0.1:{port or 8080}"


def _roles(request: web.Request) -> set[str]:
    auth = request.app[AUTH_KEY]
    user = request.get("cryostack_user") or auth.current_user(request)
    if user is None:
        return set()
    return {str(role).lower() for role in auth.storage.get_user_roles(user_id=user.id)}


def _can_write(request: web.Request) -> bool:
    return bool(_roles(request) & SETTINGS_WRITE_ROLES)


def _same_origin(request: web.Request) -> bool:
    """State-changing requests must come from this site's own pages."""
    origin = request.headers.get("Origin")
    if origin is None or origin == "null":
        referer = request.headers.get("Referer")
        if not referer:
            return False
        origin = referer
    return urlsplit(origin).netloc == request.host


# ── Analytics ───────────────────────────────────────────────────────
async def _analytics(request: web.Request) -> dict:
    try:
        days = int(request.query.get("days", "30"))
    except ValueError:
        days = 30
    service = request.app[ANALYTICS_KEY]
    return await asyncio.to_thread(service.get_analytics, days=days)


async def analytics_page_handler(request: web.Request) -> web.Response:
    return web.Response(text=analytics_page(data=await _analytics(request)),
                        content_type="text/html")


async def analytics_api(request: web.Request) -> web.Response:
    return web.json_response(await _analytics(request))


# ── Diagnostics ─────────────────────────────────────────────────────
async def _diagnostics(request: web.Request) -> dict:
    service = request.app[DIAGNOSTICS_KEY]
    return await service.collect(app=request.app, base_url=_base_url(request),
                                 refresh=request.query.get("refresh") == "1")


async def diagnostics_page_handler(request: web.Request) -> web.Response:
    return web.Response(text=diagnostics_page(data=await _diagnostics(request)),
                        content_type="text/html")


async def diagnostics_api(request: web.Request) -> web.Response:
    return web.json_response(await _diagnostics(request))


# ── Settings ────────────────────────────────────────────────────────
def _applications() -> list[dict]:
    from ..services.diagnostics import _health_module
    try:
        registry = _health_module().load_registry()
    except Exception:
        return []
    out = []
    for name, app in (registry.get("applications") or {}).items():
        out.append({
            "name": name,
            "title": app.get("title") or name,
            "type": app.get("type") or "",
            "routes": [str(r) for r in app.get("routes") or []],
            "health": (app.get("health") or {}).get("target"),
        })
    return out


def _storage_sources() -> dict:
    try:
        from icesee_jupyter_book.applications.frozen_legacies.radar.storage import (
            approved_roots, s3_approvals)
        return {"local_roots": len(approved_roots()), "s3_approvals": len(s3_approvals())}
    except Exception:
        return {"local_roots": 0, "s3_approvals": 0}


def _settings_payload(request: web.Request) -> dict:
    service = request.app[SETTINGS_KEY]
    return {
        "settings": service.describe(),
        "audit": service.audit(limit=50),
        "applications": _applications(),
        "storage_sources": _storage_sources(),
        "can_write": _can_write(request),
        "precedence": ["environment", "stored", "default"],
    }


async def settings_page_handler(request: web.Request, *, error: str | None = None,
                                status: int = 200) -> web.Response:
    payload = await asyncio.to_thread(_settings_payload, request)
    payload.pop("precedence")
    message = _DONE.get(request.query.get("done", "")) if error is None else None
    return web.Response(
        text=settings_page(**payload, message=message, error=error),
        content_type="text/html", status=status)


async def settings_api(request: web.Request) -> web.Response:
    payload = await asyncio.to_thread(_settings_payload, request)
    for entry in payload["audit"]:
        entry.pop("actor_id", None)
    return web.json_response(payload)


async def settings_update_handler(request: web.Request) -> web.StreamResponse:
    if not _same_origin(request):
        raise web.HTTPForbidden(text="Cross-origin request refused.")
    if not _can_write(request):
        raise web.HTTPForbidden(
            text="Changing settings requires the maintainer, admin or owner role.")
    if (request.content_length or 0) > MAX_FORM_BYTES:
        raise web.HTTPRequestEntityTooLarge(max_size=MAX_FORM_BYTES,
                                            actual_size=request.content_length)
    form = await request.post()
    user = request["cryostack_user"]
    actor_label = getattr(user, "email", None) or getattr(user, "display_name", None)
    service = request.app[SETTINGS_KEY]
    op = str(form.get("op", "save"))
    try:
        if op == "save":
            result = await asyncio.to_thread(
                service.change, key=form.get("key"), value=form.get("value", ""),
                actor_id=user.id, actor_label=actor_label, reason=form.get("reason"))
            done = "saved"
        elif op == "reset":
            result = await asyncio.to_thread(
                service.reset, key=form.get("key"), actor_id=user.id,
                actor_label=actor_label, reason=form.get("reason"))
            done = "reset"
        elif op == "rollback":
            result = await asyncio.to_thread(
                service.rollback, audit_id=form.get("audit_id"), actor_id=user.id,
                actor_label=actor_label, reason=form.get("reason"))
            done = "rollback"
        else:
            raise SettingsError("Unknown operation.")
    except SettingsError as error:
        return await settings_page_handler(request, error=str(error), status=400)
    raise web.HTTPSeeOther(f"/control/settings?done={done}#setting-{result['key']}")
