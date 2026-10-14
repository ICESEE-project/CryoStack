"""Frozen Legacies routes on the CryoStack aiohttp gateway.

Frozen Legacies is an authenticated CryoStack application, protected the same
way as CryoLauncher and ICESEE: every application route is wrapped in
``AuthManager.require_login``, so an anonymous request is redirected to
``/auth/login?return_to=...`` and an authenticated request carries
``request["cryostack_user"]``.

The application page, its assets, and the shared/reference data products are
served from this package directory. User-owned work lives in the per-user
workspace (:mod:`.workspace`) and is never served from the static tree.

Radar API (JSON, under ``/frozen-legacies/api/``). It uses the same CryoStack
session as the page but answers ``401`` instead of redirecting, like the
``/api/v1/*`` routes of :class:`icesee_auth.AuthManager`:

* ``GET  radar/sources``           shared radar sources (no server paths)
* ``GET  assets``                  the user's radar assets
* ``POST assets/shared``           ``{"source": key}`` -> reference a shared source
* ``POST assets/upload``           multipart ``tiff`` (+ optional ``nav``)
* ``GET  assets/<id>``             asset detail + navigation rows in its CBD range
* ``GET  assets/<id>/view``        ``?x=&width=&scale=`` -> PNG window
* ``GET  assets/<id>/manual``      ASTRA manual-picking session (state + trace)
* ``POST assets/<id>/manual``      one picker action ``{"action": ..., "revision": n}``
* ``GET  assets/<id>/manual/window`` ``?slider=`` -> ASTRA working-window PNG
* ``GET  assets/<id>/outputs/<product>``  ``astra-csv`` or ``astra-qc`` download
* ``GET  assets/<id>/products``    every product of the asset (no paths)
* ``POST assets/<id>/products``    upload a processed product (multipart ``kind``, ``file``)
* ``POST assets/products``         new product-only asset from a processed product
* ``GET  assets/<id>/products/<pid>``          download one product
* ``GET  assets/<id>/products/<pid>/preview``  bounded PNG preview of an image product
* ``DELETE assets/<id>/products/<pid>``        remove a user-provided product
* ``GET  assets/<id>/products.zip``            download the asset's products together
* ``GET  assets/<id>/automatic``   automatic-picking (URSA) availability, job and per-frame diagnostics
* ``POST assets/<id>/automatic``   ``{"action": "start" | "cancel"}``
* ``DELETE assets/<id>``           remove the asset from the user's workspace
* ``GET  datasets/<dataset_id>/downloads/<kind>``  shared dataset downloads

Asset IDs only ever come from the server; every asset is resolved inside the
authenticated user's workspace.
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from cryostack_src.workspace.identity import WorkspaceIdentityError
from cryostack_src.workspace.manager import WorkspacePermissionError

from .radar import automatic, products
from .radar.assets import (
    NoRadarImage,
    SharedSourceUnavailable,
    attach_navigation,
    create_products_asset,
    asset_image_paths,
    asset_nav_rows,
    create_shared_asset,
    finalize_upload,
    list_manifests,
    public_asset,
    read_manifest,
    remove_asset_dir,
    write_manifest,
)
from .pickers.astra import AstraError, AstraGeometry, AstraSession
from .radar import manual
from .radar.ingest import (
    MAX_NAV_BYTES,
    RadarValidationError,
    check_tiff_signature,
    safe_original_filename,
)
from .radar.render import (
    RadarImageCache,
    RenderedWindowCache,
    RenderRequestError,
    check_window,
    render_cached,
)
from .radar.catalog import CatalogError
from .radar import observations as observations_mod
from .radar.sources import is_valid_source_key, load_sources
from .radar.working_cache import working_cache
from .workspace import (
    ASSET_NAV_CSV,
    ASSET_SOURCE_TIFF,
    AssetNotFoundError,
    FrozenLegaciesWorkspace,
    workspace_user_for,
)


HERE = Path(__file__).resolve().parent

#: optional ``app[...]`` override of the CryoStack workspace root (tests);
#: otherwise ``owner_root`` resolves it ($CRYOSTACK_WORKSPACE_ROOT → cwd)
WORKSPACE_ROOT_KEY = "frozen_legacies_workspace_root"

#: ``request[...]`` key holding the current user's workspace
REQUEST_WORKSPACE_KEY = "frozen_legacies_workspace"

#: upload limit for one radar TIFF; matches nginx ``client_max_body_size 200M``
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
#: optional ``app[...]`` override of MAX_UPLOAD_BYTES (tests)
UPLOAD_LIMIT_KEY = "frozen_legacies_max_upload_bytes"

IMAGE_CACHE_KEY = "frozen_legacies_radar_images"
WINDOW_CACHE_KEY = "frozen_legacies_radar_windows"
#: per-workspace locks serializing "open shared source" (no duplicate assets)
SHARED_LOCKS_KEY = "frozen_legacies_shared_locks"
#: per-asset locks serializing manual-session updates (several tabs)
MANUAL_LOCKS_KEY = "frozen_legacies_manual_locks"
ASTRA_CACHE_KEY = "frozen_legacies_astra_views"
#: largest accepted manual action body
MAX_ACTION_BYTES = 16 * 1024

_UPLOAD_CHUNK = 1024 * 1024
_ASSET_ID_PATTERN = "{asset_id:[0-9a-f]{32}}"


def frozen_legacies_root() -> Path:
    return HERE


def frozen_legacies_assets_root() -> Path:
    return HERE / "assets"


def frozen_legacies_data_root() -> Path:
    return HERE / "data"


def workspace_for_request(request: web.Request) -> FrozenLegaciesWorkspace:
    """The authenticated user's Frozen Legacies workspace.

    Only valid inside a ``require_login``-protected handler: the identity is
    taken from ``request["cryostack_user"]``, never from the request body,
    query string, or headers.
    """
    workspace = request.get(REQUEST_WORKSPACE_KEY)
    if workspace is None:
        workspace = FrozenLegaciesWorkspace(
            workspace_user_for(request["cryostack_user"]),
            workspace_root=request.app.get(WORKSPACE_ROOT_KEY),
        )
        request[REQUEST_WORKSPACE_KEY] = workspace
    return workspace


def _private(response: web.StreamResponse) -> web.StreamResponse:
    # Authenticated content: never store in a shared cache.
    response.headers["Cache-Control"] = "private, no-cache"
    return response


def _file_under(root: Path, tail: str) -> Path:
    """Resolve ``tail`` to a regular file under ``root`` or raise 404."""
    parts = [p for p in tail.split("/") if p]
    if not parts or any(p.startswith(".") or "\\" in p for p in parts):
        raise web.HTTPNotFound()
    root = root.resolve()
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise web.HTTPNotFound()
    return path


async def frozen_legacies_redirect(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/frozen-legacies/")


async def frozen_legacies_index(request: web.Request) -> web.StreamResponse:
    index_file = frozen_legacies_root() / "index.html"
    if not index_file.exists():
        raise web.HTTPNotFound(
            text=(
                "FrozenLegacies frontend has not "
                "been created yet. Expected:\n"
                f"{index_file}"
            )
        )

    # Entering the application establishes the user's workspace.
    workspace_for_request(request).ensure()

    return _private(web.FileResponse(index_file))


async def frozen_legacies_asset(request: web.Request) -> web.StreamResponse:
    path = _file_under(frozen_legacies_assets_root(), request.match_info["tail"])
    return _private(web.FileResponse(path))


async def frozen_legacies_data(request: web.Request) -> web.StreamResponse:
    path = _file_under(frozen_legacies_data_root(), request.match_info["tail"])
    return _private(web.FileResponse(path))


# ── radar API ────────────────────────────────────────────────────────

def _json(data, *, status: int = 200) -> web.Response:
    response = web.json_response(data, status=status)
    response.headers["Cache-Control"] = "no-store"
    return response


def _error(status: int, message: str) -> web.Response:
    return _json({"error": message}, status=status)


def _api(auth, handler):
    """Require a CryoStack session (401 JSON when absent) and map workspace
    errors to responses that never reveal paths or other users' assets."""

    async def protected(request: web.Request) -> web.StreamResponse:
        user = auth.current_user(request)
        if user is None:
            return _error(401, "Authentication required.")
        request["cryostack_user"] = user
        try:
            return await handler(request)
        except (AssetNotFoundError, WorkspacePermissionError):
            return _error(404, "Radar asset not found.")
        except SharedSourceUnavailable:
            return _error(409, "The shared radar source for this asset is not available.")
        except NoRadarImage:
            return _error(409, "This asset holds processed products only; it has no raw radar TIFF.")
        except (RadarValidationError, RenderRequestError, AstraError, CatalogError) as error:
            return _error(400, str(error))
        except manual.SessionInvalid:
            return _json({
                "error": "This manual session cannot be read. Reset it to start again.",
                "session_invalid": True,
            }, status=409)
        except manual.SessionConflict as error:
            return _error(409, str(error))
        except PermissionError:
            return _error(404, "Radar asset not found.")
        except OSError:
            return _error(500, "The server could not write the files for this asset.")
        except WorkspaceIdentityError:
            return _error(401, "Authentication required.")

    return protected


def _require_same_origin(request: web.Request) -> None:
    """Refuse state-changing requests sent from another site."""
    origin = request.headers.get("Origin")
    if origin is not None and urlsplit(origin).netloc != request.host:
        raise web.HTTPForbidden(
            text=json.dumps({"error": "Cross-origin request refused."}),
            content_type="application/json",
        )


async def _blocking(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


async def api_list_sources(request: web.Request) -> web.Response:
    sources = load_sources()
    return _json({"sources": [s.public() for s in sources.values()]})


async def api_list_assets(request: web.Request) -> web.Response:
    workspace = workspace_for_request(request)
    sources = load_sources()
    manifests = await _blocking(list_manifests, workspace)
    return _json({"assets": [public_asset(m, sources) for m in manifests]})


async def api_create_shared_asset(request: web.Request) -> web.Response:
    _require_same_origin(request)
    workspace = workspace_for_request(request)
    if (request.content_length or 0) > 4096:
        return _error(413, "Request body is too large.")
    try:
        payload = await request.json()
    except ValueError:
        return _error(400, "A JSON body is required.")
    key = payload.get("source") if isinstance(payload, dict) else None
    if not is_valid_source_key(key):
        return _error(400, "A valid shared radar source key is required.")
    sources = load_sources()
    source = sources.get(key)
    if source is None:
        return _error(404, "Shared radar source not found.")
    lock = request.app[SHARED_LOCKS_KEY].setdefault(str(workspace.root), asyncio.Lock())
    async with lock:
        manifest = await _blocking(create_shared_asset, workspace, source)
    return _json(public_asset(manifest, sources), status=201)


class _UploadTooLarge(Exception):
    pass


async def _stream_part(part, target: Path, limit: int, *, digest=None, signature=False) -> int:
    """Stream one multipart part to ``target`` without buffering it in memory."""
    size = 0
    head = b""
    with target.open("xb") as out:
        while True:
            chunk = await part.read_chunk(_UPLOAD_CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise _UploadTooLarge()
            if signature and len(head) < 4:
                head += chunk[: 4 - len(head)]
                if len(head) == 4:
                    check_tiff_signature(head)
            if digest is not None:
                digest.update(chunk)
            out.write(chunk)
    if signature and size and len(head) < 4:
        check_tiff_signature(head)
    return size


async def api_upload_asset(request: web.Request) -> web.Response:
    _require_same_origin(request)
    workspace = workspace_for_request(request)
    limit = int(request.app.get(UPLOAD_LIMIT_KEY, MAX_UPLOAD_BYTES))
    if (request.content_length or 0) > limit + MAX_NAV_BYTES + 64 * 1024:
        return _error(413, f"Upload exceeds the {limit // (1024 * 1024)} MB limit.")
    try:
        reader = await request.multipart()
    except (AssertionError, ValueError, KeyError):
        return _error(400, "A multipart/form-data upload is required.")

    asset_id, directory = workspace.create_asset()
    tiff_part = directory / (ASSET_SOURCE_TIFF + ".part")
    nav_part = directory / (ASSET_NAV_CSV + ".part")
    try:
        original_filename = None
        digest = hashlib.sha256()
        has_nav = False
        while True:
            part = await reader.next()
            if part is None:
                break
            if not hasattr(part, "read_chunk"):
                raise RadarValidationError("Nested multipart uploads are not supported.")
            if part.name == "tiff":
                if original_filename is not None:
                    raise RadarValidationError("Upload one radar TIFF at a time.")
                original_filename = safe_original_filename(part.filename)
                size = await _stream_part(part, tiff_part, limit, digest=digest, signature=True)
                if size == 0:
                    raise RadarValidationError("The uploaded TIFF is empty.")
            elif part.name == "nav":
                if has_nav or nav_part.exists():
                    raise RadarValidationError("Upload one navigation file at a time.")
                size = await _stream_part(part, nav_part, MAX_NAV_BYTES)
                if size == 0:
                    nav_part.unlink()      # no navigation file was chosen
                else:
                    has_nav = True
            else:
                raise RadarValidationError(f"Unexpected upload field {part.name!r}.")
        if original_filename is None:
            raise RadarValidationError("No radar TIFF was uploaded (field 'tiff').")

        os.replace(tiff_part, workspace.asset_file(asset_id, ASSET_SOURCE_TIFF))
        if has_nav:
            os.replace(nav_part, workspace.asset_file(asset_id, ASSET_NAV_CSV))
        manifest = await _blocking(
            finalize_upload,
            workspace,
            asset_id,
            original_filename=original_filename,
            sha256=digest.hexdigest(),
            has_nav=has_nav,
        )
    except _UploadTooLarge:
        remove_asset_dir(workspace, directory)
        return _error(413, f"Upload exceeds the {limit // (1024 * 1024)} MB limit.")
    except BaseException:
        # validation errors, client disconnects, cancellation: no partial asset
        remove_asset_dir(workspace, directory)
        raise
    return _json(public_asset(manifest, load_sources()), status=201)


async def api_asset_detail(request: web.Request) -> web.Response:
    workspace = workspace_for_request(request)
    manifest = read_manifest(workspace, request.match_info["asset_id"])
    sources = load_sources()
    detail = public_asset(manifest, sources)
    try:
        _tiff, nav = asset_image_paths(workspace, manifest, sources)
    except (SharedSourceUnavailable, NoRadarImage):
        nav = None
    detail["nav_rows"] = await _blocking(asset_nav_rows, nav, manifest)
    return _json(detail)


def _int_query(request: web.Request, name: str) -> int:
    try:
        return int(request.query[name])
    except (KeyError, ValueError):
        raise RenderRequestError(f"query parameter {name!r} must be an integer")


async def api_asset_view(request: web.Request) -> web.Response:
    workspace = workspace_for_request(request)
    manifest = read_manifest(workspace, request.match_info["asset_id"])
    x = _int_query(request, "x")
    width = _int_query(request, "width")
    scale = _int_query(request, "scale")
    image = manifest.get("image") or {}
    check_window(
        int(image.get("width") or 0), int(image.get("height") or 0),
        x=x, width=width, scale=scale,
    )
    tiff, _nav = asset_image_paths(workspace, manifest, load_sources())
    png = await _blocking(
        render_cached,
        request.app[IMAGE_CACHE_KEY],
        request.app[WINDOW_CACHE_KEY],
        tiff,
        x=x, width=width, scale=scale,
    )
    response = web.Response(body=png, content_type="image/png")
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


# ── manual (ASTRA) picking ───────────────────────────────────────────

class _ManualContext:
    """Owned asset, its files, and its ASTRA geometry."""

    def __init__(self, request: web.Request):
        self.workspace = workspace_for_request(request)
        self.asset_id = request.match_info["asset_id"]
        self.manifest = read_manifest(self.workspace, self.asset_id)
        self.tiff, self.nav = asset_image_paths(self.workspace, self.manifest, load_sources())
        image = self.manifest.get("image") or {}
        self.geometry = AstraGeometry.for_image(int(image["width"]), int(image["height"]))
        self.filename = self.manifest.get("filename") or self.tiff.name
        self.cache = request.app[ASTRA_CACHE_KEY]

    def lock(self, request: web.Request) -> asyncio.Lock:
        key = f"{self.workspace.root}/{self.asset_id}"
        return request.app[MANUAL_LOCKS_KEY].setdefault(key, asyncio.Lock())

    def load(self):
        doc = manual.load_document(self.workspace, self.asset_id, self.geometry, self.filename)
        if doc is None:
            return None, AstraSession(self.geometry, self.filename)
        return doc, AstraSession.from_state(self.geometry, self.filename, doc["state"])

    def outputs(self) -> dict:
        found = {}
        for product in manual.PRODUCTS:
            path = manual.existing_output(self.workspace, self.asset_id, self.filename, product)
            if path is not None:
                found[product] = {
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    # one download route for every product (outputs/<product>
                    # remains as an equivalent alias)
                    "url": f"/frozen-legacies/api/assets/{self.asset_id}/products/{product}",
                }
        return found

    def trace(self, slider: int):
        return self.cache.trace(self.tiff, self.geometry, slider)

    def describe(self, doc, session):
        trace_y = self.trace(session.slider)
        return manual.describe(session, doc, trace_y, nav_path=self.nav, outputs=self.outputs())


async def api_manual_get(request: web.Request) -> web.Response:
    ctx = await _blocking(_ManualContext, request)

    def run():
        doc, session = ctx.load()
        return ctx.describe(doc, session)

    return _json(await _blocking(run))


def _run_manual_action(ctx: _ManualContext, payload: dict) -> dict:
    # a remote file's working copy stays in the cache while ASTRA uses it
    with working_cache().lease(ctx.tiff):
        return _manual_action(ctx, payload)


def _manual_action(ctx: _ManualContext, payload: dict) -> dict:
    action = payload.get("action")
    if action == "reset":
        if payload.get("confirm") is not True:
            raise AstraError("Reset needs confirmation.")
        session_file = ctx.workspace.asset_file(ctx.asset_id, "session.json")
        if os.path.lexists(session_file):
            session_file.unlink()
        manual.remove_outputs(ctx.workspace, ctx.asset_id, ctx.filename)
        observations_mod.remove(ctx.workspace, ctx.asset_id)
        _record_catalog_state(ctx)
        session = AstraSession(ctx.geometry, ctx.filename)
        session.messages.append("Manual session reset. The radar TIFF was kept.")
        return ctx.describe(None, session)

    doc, session = ctx.load()
    revision = doc["revision"] if doc else 0
    if payload.get("revision") != revision:
        raise manual.SessionConflict(
            "This session changed in another window. It has been reloaded."
        )
    if doc and doc["status"] == "completed":
        raise manual.SessionConflict("This session is complete. Reset it to pick again.")
    if doc is None:
        doc = manual.new_document(ctx.asset_id, session)

    if action == "done":
        session.done()
        manual.write_outputs(ctx.workspace, ctx.asset_id, ctx.filename,
                             session.state["data"], ctx.tiff, ctx.nav)
        doc["status"] = "completed"
        doc["completed_at"] = time.time()
        session.messages.append("Saved CSV and QC PNG.")
    else:
        kind = manual.apply_action(session, payload, ctx.trace)
        if kind == "next":
            # ASTRA's next_ascope ends with save_to_csv()
            manual.write_csv(ctx.workspace, ctx.asset_id, ctx.filename,
                             session.state["data"], ctx.nav)

    doc["state"] = session.to_state()
    doc["revision"] = revision + 1
    doc["updated_at"] = time.time()
    manual.save_document(ctx.workspace, ctx.asset_id, doc)
    # the user's live map layer: rebuilt from the session (same rows as the CSV)
    observations_mod.write(ctx.workspace, ctx.asset_id,
                           observations_mod.build(ctx.asset_id, ctx.manifest, doc, ctx.nav))
    _record_catalog_state(ctx)
    return ctx.describe(doc, session)


def _record_catalog_state(ctx) -> None:
    """Keep the radar catalog's index of this user's state current."""
    from .catalog_routes import record_state

    try:
        record_state(ctx.workspace, ctx.manifest)
    except Exception:          # advisory index; the session is already saved
        pass


async def api_manual_action(request: web.Request) -> web.Response:
    _require_same_origin(request)
    if (request.content_length or 0) > MAX_ACTION_BYTES:
        return _error(413, "Request body is too large.")
    body = await request.content.read(MAX_ACTION_BYTES + 1)
    if len(body) > MAX_ACTION_BYTES:
        return _error(413, "Request body is too large.")
    try:
        payload = json.loads(body or b"null")
    except ValueError:
        return _error(400, "A JSON body is required.")
    if not isinstance(payload, dict) or not isinstance(payload.get("action"), str):
        return _error(400, "An action is required.")

    ctx = await _blocking(_ManualContext, request)
    async with ctx.lock(request):
        result = await _blocking(_run_manual_action, ctx, payload)
    return _json(result)


async def api_manual_window(request: web.Request) -> web.Response:
    ctx = await _blocking(_ManualContext, request)
    slider = _int_query(request, "slider")
    if not 0 <= slider <= ctx.geometry.slider_max:
        raise RenderRequestError(f"slider must be in [0, {ctx.geometry.slider_max}]")
    png = await _blocking(ctx.cache.png, ctx.tiff, ctx.geometry, slider)
    response = web.Response(body=png, content_type="image/png")
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


async def api_output_download(request: web.Request) -> web.StreamResponse:
    ctx = await _blocking(_ManualContext, request)
    product = request.match_info["product"]
    path = await _blocking(manual.existing_output, ctx.workspace, ctx.asset_id,
                           ctx.filename, product)
    if path is None:
        return _error(404, "This product has not been generated.")
    response = web.FileResponse(path)
    response.headers["Content-Type"] = "text/csv" if product == "astra-csv" else "image/png"
    # names are restricted to [A-Za-z0-9._-] (manual.output_stem)
    response.headers["Content-Disposition"] = f'attachment; filename="{path.name}"'
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# ── products ─────────────────────────────────────────────────────────

AUTOMATIC_KEY = "frozen_legacies_automatic"
DATASETS_ROOT_KEY = "frozen_legacies_datasets_root"
PREVIEW_MAX_WIDTH = 2400
PREVIEW_MAX_HEIGHT = 1200
#: previews of large images decode the whole file; render one at a time
_PREVIEW_SLOTS = threading.BoundedSemaphore(1)


def _owned(request: web.Request):
    workspace = workspace_for_request(request)
    manifest = read_manifest(workspace, request.match_info["asset_id"])
    return workspace, manifest


async def api_list_products(request: web.Request) -> web.Response:
    workspace, manifest = await _blocking(_owned, request)
    listed = await _blocking(products.list_products, workspace, manifest, load_sources())
    return _json({"asset_id": manifest["asset_id"], "products": listed,
                  "upload_kinds": [
                      {"kind": k, "title": products.KINDS[k]["title"],
                       "extensions": list(products.KINDS[k]["upload"])}
                      for k in products.UPLOAD_KINDS]})


async def _receive_product(request: web.Request, *, workspace, asset_dir: Path, limit: int):
    """Stream a ``kind`` + ``file`` multipart upload into ``asset_dir/outputs``."""
    try:
        reader = await request.multipart()
    except (AssertionError, ValueError, KeyError):
        raise RadarValidationError("A multipart/form-data upload is required.")
    kind = title = None
    stored = display = extension = None
    digest = hashlib.sha256()
    token = products.new_product_id("upload")
    try:
        while True:
            part = await reader.next()
            if part is None:
                break
            if not hasattr(part, "read_chunk"):
                raise RadarValidationError("Nested multipart uploads are not supported.")
            if part.name in ("kind", "title"):
                raw = await part.read_chunk(512)
                if await part.read_chunk(1):
                    raise RadarValidationError(f"The {part.name!r} field is too long.")
                value = raw.decode("utf-8", "replace").strip()
                if part.name == "kind":
                    kind = value
                else:
                    title = value[:120] or None
            elif part.name == "file":
                if kind is None:
                    raise RadarValidationError("Send the product type ('kind') before the file.")
                if stored is not None:
                    raise RadarValidationError("Upload one product at a time.")
                display, extension = products.upload_extension(kind, part.filename)
                stored = asset_dir / "outputs" / f"{token}{extension}"
                size = await _stream_part(part, stored, limit, digest=digest)
                if size == 0:
                    raise RadarValidationError("The uploaded file is empty.")
            else:
                raise RadarValidationError(f"Unexpected upload field {part.name!r}.")
        if stored is None:
            raise RadarValidationError("No product file was uploaded (field 'file').")
    except BaseException:
        if stored is not None and stored.exists():
            stored.unlink()
        raise
    return {"kind": kind, "title": title, "stored": stored, "display": display,
            "extension": extension, "sha256": digest.hexdigest(), "product_id": token}


def _finish_product(workspace, asset_id: str, manifest: dict, received: dict) -> dict:
    """Validate a received product and register it (or attach navigation)."""
    kind, stored = received["kind"], received["stored"]
    try:
        validated = products.validate_upload(kind, stored, received["extension"])
        if kind == "navigation" and manifest["origin"] != "products":
            if manifest["origin"] == "shared":
                raise products.ProductValidationError(
                    "Shared radar uses the installation's navigation; it cannot be replaced.")
            nav_path = workspace.asset_file(asset_id, "nav.csv")
            busy = (workspace.asset_file(asset_id, "session.json").exists()
                    or automatic.read_job(workspace, asset_id) is not None)
            if nav_path.exists() or busy:
                raise products.ProductValidationError(
                    "This radar asset already has navigation or picking results; "
                    "navigation can only be added before picking starts.")
            os.replace(stored, nav_path)
            attach_navigation(workspace, asset_id, manifest)
            return {"attached": "navigation"}
        record = products.upload_record(
            kind, product_id=received["product_id"], stored_name=stored.name,
            display_name=received["display"], sha256=received["sha256"], validated=validated)
        if received.get("title"):
            record["title"] = received["title"]
        products.register(workspace, asset_id, record)
        return record
    except BaseException:
        if stored.exists():
            stored.unlink()
        raise


async def api_upload_product(request: web.Request) -> web.Response:
    _require_same_origin(request)
    workspace, manifest = await _blocking(_owned, request)
    asset_id = manifest["asset_id"]
    limit = products.MAX_IMAGE_BYTES
    if (request.content_length or 0) > limit + 64 * 1024:
        return _error(413, f"Upload exceeds the {limit // (1024 * 1024)} MB limit.")
    lock = request.app[MANUAL_LOCKS_KEY].setdefault(f"{workspace.root}/{asset_id}", asyncio.Lock())
    async with lock:
        try:
            received = await _receive_product(
                request, workspace=workspace, asset_dir=workspace.asset_dir(asset_id), limit=limit)
        except _UploadTooLarge:
            return _error(413, f"Upload exceeds the {limit // (1024 * 1024)} MB limit.")
        await _blocking(_finish_product, workspace, asset_id, manifest, received)
    listed = await _blocking(products.list_products, workspace,
                             read_manifest(workspace, asset_id), load_sources())
    return _json({"asset_id": asset_id, "products": listed}, status=201)


async def api_create_products_asset(request: web.Request) -> web.Response:
    _require_same_origin(request)
    workspace = workspace_for_request(request)
    limit = products.MAX_IMAGE_BYTES
    if (request.content_length or 0) > limit + 64 * 1024:
        return _error(413, f"Upload exceeds the {limit // (1024 * 1024)} MB limit.")
    asset_id, directory, manifest = await _blocking(
        create_products_asset, workspace, title="Processed products")
    try:
        received = await _receive_product(request, workspace=workspace, asset_dir=directory,
                                          limit=limit)
        await _blocking(_finish_product, workspace, asset_id, manifest, received)
        title = received.get("title") or Path(received["display"]).stem
        manifest = dict(manifest, title=title)
        await _blocking(write_manifest, workspace, asset_id, manifest)
    except _UploadTooLarge:
        remove_asset_dir(workspace, directory)
        return _error(413, f"Upload exceeds the {limit // (1024 * 1024)} MB limit.")
    except BaseException:
        remove_asset_dir(workspace, directory)
        raise
    return _json(public_asset(manifest, load_sources()), status=201)


def _content_disposition(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "product").strip("._") or "product"
    return f'attachment; filename="{safe[:180]}"'


async def api_download_product(request: web.Request) -> web.StreamResponse:
    workspace, manifest = await _blocking(_owned, request)
    record, path = await _blocking(products.resolve_product, workspace, manifest,
                                   load_sources(), request.match_info["product_id"])
    if not record["downloadable"]:
        return _error(403, "This product cannot be downloaded.")
    response = web.FileResponse(path)
    response.headers["Content-Type"] = record["mime"] or "application/octet-stream"
    response.headers["Content-Disposition"] = _content_disposition(record["filename"])
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _render_preview(path: Path) -> bytes:
    """A bounded PNG preview of an image product (the stored file is unchanged).

    Grayscale and 16-bit images are reduced with a block minimum on their
    original values, so thin dark marks -- the picks drawn on an ASTRA QC
    image, radar traces -- stay visible at preview scale; colour images are
    reduced with a block mean.
    """
    import io
    import warnings

    import numpy as np
    from PIL import Image

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        with Image.open(path) as image:
            image.draft("RGB", (PREVIEW_MAX_WIDTH, PREVIEW_MAX_HEIGHT))
            factor = max(1, -(-image.width // PREVIEW_MAX_WIDTH),
                         -(-image.height // PREVIEW_MAX_HEIGHT))
            if image.mode in ("I;16", "I;16L", "I;16B", "I", "F", "L"):
                array = np.asarray(image)
                if factor > 1:
                    h = array.shape[0] // factor * factor
                    w = array.shape[1] // factor * factor
                    array = array[:h, :w].reshape(h // factor, factor, w // factor, factor)
                    array = array.min(axis=(1, 3))
                if image.mode == "L":
                    out = Image.fromarray(np.ascontiguousarray(array, dtype=np.uint8), mode="L")
                else:
                    low, high = (float(v) for v in np.percentile(array, (0.5, 99.5)))
                    if high - low < 1:          # near-uniform: stretch over min..max
                        low, high = float(array.min()), float(array.max())
                    span = (high - low) or 1.0
                    scaled = (array.astype(np.float32) - float(low)) * (255.0 / span)
                    out = Image.fromarray(np.clip(scaled, 0, 255).astype(np.uint8), mode="L")
            else:
                out = image.convert("RGB")
                if factor > 1:
                    out = out.reduce(factor)
    buffer = io.BytesIO()
    out.save(buffer, format="PNG", compress_level=3)
    return buffer.getvalue()


def _render_preview_bounded(path: Path) -> bytes:
    with _PREVIEW_SLOTS:
        return _render_preview(path)


async def api_preview_product(request: web.Request) -> web.Response:
    workspace, manifest = await _blocking(_owned, request)
    record, path = await _blocking(products.resolve_product, workspace, manifest,
                                   load_sources(), request.match_info["product_id"])
    if not record["previewable"]:
        return _error(404, "This product has no preview.")
    stat = path.stat()
    key = ("preview", str(path), stat.st_mtime_ns, stat.st_size)
    cache = request.app[WINDOW_CACHE_KEY]
    png = cache.get(key)
    if png is None:
        png = await _blocking(_render_preview_bounded, path)
        cache.put(key, png)
    response = web.Response(body=png, content_type="image/png")
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


async def api_delete_product(request: web.Request) -> web.Response:
    _require_same_origin(request)
    workspace, manifest = await _blocking(_owned, request)
    asset_id = manifest["asset_id"]
    product_id = request.match_info["product_id"]
    record, _path = await _blocking(products.resolve_product, workspace, manifest,
                                    load_sources(), product_id)
    if record["producer"] != "user" or record["workflow"] != "upload" or product_id in (
            "raw-radar", "navigation"):
        return _error(403, "Only products you uploaded can be removed here.")
    lock = request.app[MANUAL_LOCKS_KEY].setdefault(f"{workspace.root}/{asset_id}", asyncio.Lock())
    async with lock:
        await _blocking(products.unregister, workspace, asset_id, product_id)
    listed = await _blocking(products.list_products, workspace, manifest, load_sources())
    return _json({"asset_id": asset_id, "products": listed})


def _build_bundle(workspace, manifest: dict, sources: dict) -> Path:
    """A ZIP of the asset's downloadable products (not the raw TIFF), with a
    PRODUCTS.json listing their public metadata. Never includes session or
    asset manifests or paths."""
    import tempfile
    import zipfile

    listed = products.list_products(workspace, manifest, sources)
    handle = tempfile.NamedTemporaryFile(prefix="fl-products-", suffix=".zip", delete=False)
    handle.close()
    bundle = Path(handle.name)
    used = set()
    index = []
    try:
        with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for record in listed:
                if not record["downloadable"] or record["kind"] == "raw-radar":
                    continue
                _rec, path = products.resolve_product(workspace, manifest, sources,
                                                      record["product_id"])
                name = re.sub(r"[^A-Za-z0-9._-]+", "_", record["filename"] or record["product_id"])
                while name in used:
                    name = f"{record['product_id']}-{name}"
                used.add(name)
                compress = (zipfile.ZIP_STORED if record["mime"] in ("image/png", "image/jpeg",
                            "application/zip", "application/octet-stream")
                            else zipfile.ZIP_DEFLATED)
                archive.write(path, arcname=name, compress_type=compress)
                index.append({k: record[k] for k in (
                    "product_id", "kind", "title", "producer", "workflow", "mime", "bytes",
                    "created_at", "provenance", "summary")} | {"file": name})
            archive.writestr("PRODUCTS.json", json.dumps({
                "asset": {k: manifest.get(k) for k in (
                    "asset_id", "title", "origin", "filename", "flight", "cbd_start", "cbd_end")},
                "products": index,
            }, indent=2))
    except BaseException:
        bundle.unlink(missing_ok=True)
        raise
    return bundle


async def api_download_bundle(request: web.Request) -> web.StreamResponse:
    workspace, manifest = await _blocking(_owned, request)
    bundle = await _blocking(_build_bundle, workspace, manifest, load_sources())
    try:
        response = web.StreamResponse()
        response.content_type = "application/zip"
        title = manifest.get("filename") or manifest.get("title") or "radar"
        response.headers["Content-Disposition"] = _content_disposition(
            f"{Path(title).stem}_products.zip")
        response.headers["Cache-Control"] = "private, no-store"
        response.content_length = bundle.stat().st_size
        await response.prepare(request)
        with bundle.open("rb") as handle:
            while True:
                chunk = await _blocking(handle.read, 1024 * 1024)
                if not chunk:
                    break
                await response.write(chunk)
        await response.write_eof()
        return response
    finally:
        bundle.unlink(missing_ok=True)


# ── automatic picking ────────────────────────────────────────────────

def _automatic_state(request, workspace, manifest) -> dict:
    runner = request.app[AUTOMATIC_KEY]
    asset_id = manifest["asset_id"]
    job = runner.current(workspace, asset_id)
    has_radar = manifest["origin"] != "products"
    sources = load_sources()
    listed = products.list_products(workspace, manifest, sources)
    return {
        "asset_id": asset_id,
        "availability": automatic.availability(),
        "has_radar": has_radar,
        "job": automatic.public_job(job),
        "warnings": automatic.warnings_for(manifest.get("filename") or "",
                                           bool((manifest.get("nav") or {}).get("present")))
        if has_radar else [],
        "products": [p for p in listed if p["workflow"] == "ursa-automatic"
                     and p["kind"] != "ursa-diagnostic"],
        "frames": automatic.frame_diagnostics(workspace, manifest, listed, sources),
        # operational availability is not scientific validation
        "scientific_status": automatic.SCIENTIFIC_STATUS,
        "scientific_note": automatic.SCIENTIFIC_NOTE,
        "publication_eligible": False,
    }


async def api_automatic_get(request: web.Request) -> web.Response:
    workspace, manifest = await _blocking(_owned, request)
    return _json(await _blocking(_automatic_state, request, workspace, manifest))


async def api_automatic_action(request: web.Request) -> web.Response:
    _require_same_origin(request)
    if (request.content_length or 0) > 4096:
        return _error(413, "Request body is too large.")
    try:
        payload = await request.json()
    except ValueError:
        return _error(400, "A JSON body is required.")
    action = payload.get("action") if isinstance(payload, dict) else None
    if action not in ("start", "cancel"):
        return _error(400, "action must be 'start' or 'cancel'.")
    workspace, manifest = await _blocking(_owned, request)
    asset_id = manifest["asset_id"]
    runner = request.app[AUTOMATIC_KEY]
    lock = request.app[MANUAL_LOCKS_KEY].setdefault(f"{workspace.root}/{asset_id}", asyncio.Lock())
    async with lock:
        if action == "cancel":
            if not runner.active(workspace, asset_id):
                return _error(409, "No automatic picking job is running for this asset.")
            await runner.cancel(workspace, asset_id)
        else:
            tiff, nav = asset_image_paths(workspace, manifest, load_sources())
            state = await _blocking(automatic.availability)
            if not state["available"]:
                return _json({"error": state["reason"], "available": False}, status=409)
            if runner.active(workspace, asset_id):
                return _error(409, "Automatic picking is already running for this asset.")
            runner.start(workspace, asset_id, tiff=tiff, nav=nav,
                         filename=manifest.get("filename") or tiff.name)
    return _json(await _blocking(_automatic_state, request, workspace, manifest))


# ── asset lifecycle ──────────────────────────────────────────────────

async def api_delete_asset(request: web.Request) -> web.Response:
    _require_same_origin(request)
    workspace, manifest = await _blocking(_owned, request)
    asset_id = manifest["asset_id"]
    runner = request.app[AUTOMATIC_KEY]
    lock = request.app[MANUAL_LOCKS_KEY].setdefault(f"{workspace.root}/{asset_id}", asyncio.Lock())
    async with lock:
        if runner.active(workspace, asset_id):
            return _error(409, "Cancel automatic picking before removing this asset.")
        # Shared radar is only referenced; removing the asset never touches it.
        from .catalog_routes import record_state
        await _blocking(record_state, workspace, manifest, forget=True)
        await _blocking(remove_asset_dir, workspace, workspace.asset_dir(asset_id))
    return _json({"deleted": asset_id})


# ── shared dataset downloads ─────────────────────────────────────────

def _dataset_download(dataset_id: str, kind: str, data_root: Path) -> tuple[bytes, str, str]:
    """Per-dataset GeoJSON cut from the generated explorer data."""
    catalog = json.loads((data_root / "catalog.json").read_text(encoding="utf-8"))
    dataset = next((d for d in catalog.get("datasets", []) if d.get("id") == dataset_id), None)
    if dataset is None:
        raise AssetNotFoundError(dataset_id)
    allowed = (dataset.get("capabilities") or {}).get("downloads", False)
    flags = ((dataset.get("build") or {}).get("downloads") or {})
    if not allowed or not flags.get(kind):
        raise AssetNotFoundError(kind)
    source = {"observations_geojson": "observations.geojson",
              "flights_geojson": "flights.geojson"}.get(kind)
    if source is None:
        raise AssetNotFoundError(kind)
    collection = json.loads((data_root / source).read_text(encoding="utf-8"))
    features = [f for f in collection.get("features", [])
                if (f.get("properties") or {}).get("dataset_id") == dataset_id
                or dataset_id in ((f.get("properties") or {}).get("dataset_ids") or [])]
    body = json.dumps({"type": "FeatureCollection", "features": features}).encode("utf-8")
    return body, "application/geo+json", f"{dataset_id}_{source}"


async def api_dataset_download(request: web.Request) -> web.Response:
    dataset_id = request.match_info["dataset_id"]
    kind = request.match_info["kind"]
    data_root = Path(request.app.get(DATASETS_ROOT_KEY) or frozen_legacies_data_root())
    body, mime, name = await _blocking(_dataset_download, dataset_id, kind, data_root)
    response = web.Response(body=body, content_type=mime.split(";")[0])
    response.headers["Content-Disposition"] = _content_disposition(name)
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


def install_frozen_legacies(app: web.Application, *, auth) -> None:
    """Register the authenticated Frozen Legacies routes on ``app``."""
    app[IMAGE_CACHE_KEY] = RadarImageCache()
    app[WINDOW_CACHE_KEY] = RenderedWindowCache()
    app[SHARED_LOCKS_KEY] = {}
    app[MANUAL_LOCKS_KEY] = {}
    app[ASTRA_CACHE_KEY] = manual.AstraViewCache(app[IMAGE_CACHE_KEY], app[WINDOW_CACHE_KEY])
    app[AUTOMATIC_KEY] = automatic.AutomaticRunner()

    async def stop_automatic_jobs(app: web.Application) -> None:
        tasks = [t for t in app[AUTOMATIC_KEY].tasks.values() if not t.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    app.on_cleanup.append(stop_automatic_jobs)

    from .catalog_routes import install_catalog_routes
    install_catalog_routes(app, auth=auth)

    app.router.add_get("/frozen-legacies", frozen_legacies_redirect)
    app.router.add_get(
        "/frozen-legacies/",
        auth.require_login(frozen_legacies_index),
    )
    app.router.add_get(
        "/frozen-legacies/assets/{tail:.+}",
        auth.require_login(frozen_legacies_asset),
    )
    app.router.add_get(
        "/frozen-legacies/data/{tail:.+}",
        auth.require_login(frozen_legacies_data),
    )

    api = "/frozen-legacies/api"
    app.router.add_get(f"{api}/radar/sources", _api(auth, api_list_sources))
    app.router.add_get(f"{api}/assets", _api(auth, api_list_assets))
    app.router.add_post(f"{api}/assets/shared", _api(auth, api_create_shared_asset))
    app.router.add_post(f"{api}/assets/upload", _api(auth, api_upload_asset))
    app.router.add_get(
        f"{api}/assets/{_ASSET_ID_PATTERN}", _api(auth, api_asset_detail),
    )
    app.router.add_get(
        f"{api}/assets/{_ASSET_ID_PATTERN}/view", _api(auth, api_asset_view),
    )
    app.router.add_get(
        f"{api}/assets/{_ASSET_ID_PATTERN}/manual", _api(auth, api_manual_get),
    )
    app.router.add_post(
        f"{api}/assets/{_ASSET_ID_PATTERN}/manual", _api(auth, api_manual_action),
    )
    app.router.add_get(
        f"{api}/assets/{_ASSET_ID_PATTERN}/manual/window", _api(auth, api_manual_window),
    )
    app.router.add_get(
        f"{api}/assets/{_ASSET_ID_PATTERN}/outputs/{{product:astra-csv|astra-qc}}",
        _api(auth, api_output_download),
    )
    app.router.add_post(f"{api}/assets/products", _api(auth, api_create_products_asset))
    app.router.add_delete(f"{api}/assets/{_ASSET_ID_PATTERN}", _api(auth, api_delete_asset))
    product = "{product_id:[a-z0-9][a-z0-9-]{0,63}}"
    app.router.add_get(f"{api}/assets/{_ASSET_ID_PATTERN}/products",
                       _api(auth, api_list_products))
    app.router.add_post(f"{api}/assets/{_ASSET_ID_PATTERN}/products",
                        _api(auth, api_upload_product))
    app.router.add_get(f"{api}/assets/{_ASSET_ID_PATTERN}/products.zip",
                       _api(auth, api_download_bundle))
    app.router.add_get(f"{api}/assets/{_ASSET_ID_PATTERN}/products/{product}",
                       _api(auth, api_download_product))
    app.router.add_delete(f"{api}/assets/{_ASSET_ID_PATTERN}/products/{product}",
                          _api(auth, api_delete_product))
    app.router.add_get(f"{api}/assets/{_ASSET_ID_PATTERN}/products/{product}/preview",
                       _api(auth, api_preview_product))
    app.router.add_get(f"{api}/assets/{_ASSET_ID_PATTERN}/automatic",
                       _api(auth, api_automatic_get))
    app.router.add_post(f"{api}/assets/{_ASSET_ID_PATTERN}/automatic",
                        _api(auth, api_automatic_action))
    app.router.add_get(
        f"{api}/datasets/{{dataset_id:[A-Za-z0-9][A-Za-z0-9._-]{{0,127}}}}/downloads/"
        f"{{kind:observations_geojson|flights_geojson}}",
        _api(auth, api_dataset_download),
    )
