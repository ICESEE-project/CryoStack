"""Georeferencing routes (owner-scoped), under ``/frozen-legacies/api/``:

* ``GET  assets/<asset_id>/georef``             each committed A-scope with
                                                ASTRA's CBD/position, the
                                                confirmed film CBD and the
                                                resulting geolocation status
* ``POST assets/<asset_id>/georef``             ``{"action": "confirm",
                                                "a_scope", "film_cbd"}``,
                                                ``{"action": "unreadable",
                                                "a_scope"}`` or ``{"action":
                                                "clear", "a_scope"}``
* ``GET  assets/<asset_id>/georef/product``     the georeferenced CSV
* ``GET  assets/<asset_id>/georef/provenance``  how it was made (JSON)

The canonical ASTRA products and ``observations.json`` are not changed;
see :mod:`radar.georef`.
"""
from __future__ import annotations

import asyncio

from aiohttp import web

from . import server as S
from .radar import georef
from .radar import observations as obs
from .radar.assets import asset_image_paths
from .radar.sources import load_sources


def _state(workspace, manifest) -> dict:
    asset_id = manifest["asset_id"]
    _tiff, nav = asset_image_paths(workspace, manifest, load_sources())
    doc = obs.read(workspace, asset_id)
    records = (doc or {}).get("observations") or []
    annotated = georef.annotate_asset(workspace, asset_id, records, nav)
    keys = ("a_scope", "window_x", "astra_cbd", "astra_position", "film_cbd",
            "film_cbd_source", "verified_cbd", "verified_position", "cbd_source",
            "georef_method", "geolocation_status", "cbd_differs")
    base = f"/frozen-legacies/api/assets/{asset_id}/georef"
    return {
        "asset_id": asset_id, "filename": manifest.get("filename"),
        "cbd_range": [manifest.get("cbd_start"), manifest.get("cbd_end")],
        "has_navigation": nav is not None,
        "session_status": (doc or {}).get("status"),
        "session_revision": (doc or {}).get("session_revision"),
        "observations": [{k: r.get(k) for k in keys} for r in annotated],
        "summary": georef.summary(annotated),
        "warnings": georef.warnings_for(annotated, manifest),
        "publication": dict(zip(("ok", "reason"), georef.publication_check(annotated))),
        "product": {"name": georef.product_name(manifest.get("filename") or ""),
                    "url": f"{base}/product", "provenance_url": f"{base}/provenance"},
    }


async def api_georef_get(request: web.Request) -> web.Response:
    workspace, manifest = await S._blocking(S._owned, request)
    return S._json(await S._blocking(_state, workspace, manifest))


async def api_georef_post(request: web.Request) -> web.Response:
    S._require_same_origin(request)
    try:
        payload = await request.json()
    except ValueError:
        return S._error(400, "A JSON body is required.")
    if not isinstance(payload, dict):
        return S._error(400, "A JSON object is required.")
    workspace, manifest = await S._blocking(S._owned, request)
    asset_id = manifest["asset_id"]
    lock = request.app[S.MANUAL_LOCKS_KEY].setdefault(f"{workspace.root}/{asset_id}",
                                                      asyncio.Lock())

    def run():
        doc = obs.read(workspace, asset_id)
        if doc is None or obs.is_stale(workspace, asset_id, doc):
            raise georef.GeorefError("Commit A-scopes in Manual first.")
        georef.record_label(workspace, asset_id, doc["observations"],
                            a_scope=payload.get("a_scope"), action=payload.get("action"),
                            film_cbd=payload.get("film_cbd"), note=payload.get("note"))
        obs._notify(workspace, asset_id, doc)        # re-index the user's map layer
        return _state(workspace, manifest)

    async with lock:
        try:
            return S._json(await S._blocking(run))
        except georef.GeorefError as error:
            return S._error(409 if "first" in str(error) else 400, str(error))


def _product(workspace, manifest):
    asset_id = manifest["asset_id"]
    _tiff, nav = asset_image_paths(workspace, manifest, load_sources())
    doc = obs.read(workspace, asset_id)
    if doc is None:
        return None
    return georef.snapshot_files(workspace, asset_id, manifest, nav, doc)


async def _download(request: web.Request, which: str) -> web.Response:
    workspace, manifest = await S._blocking(S._owned, request)
    files = await S._blocking(_product, workspace, manifest)
    if files is None:
        return S._error(404, "This asset has no committed A-scopes.")
    if which == "product":
        name = georef.product_name(manifest.get("filename") or "")
        body, ctype = files[name], "text/csv"
    else:
        name, ctype = "georef_provenance.json", "application/json"
        body = files[name]
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:200]
    return web.Response(body=body, content_type=ctype, headers={
        "Content-Disposition": f'attachment; filename="{safe}"',
        "Cache-Control": "private, no-store"})


async def api_georef_product(request: web.Request) -> web.Response:
    return await _download(request, "product")


async def api_georef_provenance(request: web.Request) -> web.Response:
    return await _download(request, "provenance")


def install_georef_routes(app: web.Application, *, auth) -> None:
    base = f"/frozen-legacies/api/assets/{S._ASSET_ID_PATTERN}/georef"
    app.router.add_get(base, S._api(auth, api_georef_get))
    app.router.add_post(base, S._api(auth, api_georef_post))
    app.router.add_get(f"{base}/product", S._api(auth, api_georef_product))
    app.router.add_get(f"{base}/provenance", S._api(auth, api_georef_provenance))

