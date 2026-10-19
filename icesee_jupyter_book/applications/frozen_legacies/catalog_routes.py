"""Radar catalog, data-source and user-observation routes.

Installed by :func:`server.install_frozen_legacies` under
``/frozen-legacies/api/``:

Users (signed in; owner-scoped where user work is involved)

* ``GET  radar/catalog``           paginated, filtered catalog search
* ``GET  radar/catalog/summary``   datasets and flights with counts and the
                                   user's processing progress
* ``GET  radar/catalog/segments``  catalog files with real navigation tracks
                                   (GeoJSON) for map discovery
* ``GET  observations``            the user's picked observations (GeoJSON),
                                   each with its result's review stage

A catalog file is opened like any shared radar: ``POST assets/shared`` with
its catalog ID (``cat-…``); the file is referenced, never copied.

Maintainers (Control Center roles maintainer, admin, owner -- checked on every
request)

* ``GET  admin/sources``                    data sources with index statistics
* ``POST admin/sources``                    register a data source
* ``POST admin/sources/<id>/test``          connection test (recorded)
* ``POST admin/sources/<id>/index``         queue a background index run
                                            (``full``, ``allow_mass_missing``)
* ``POST admin/sources/<id>/retry``         queue a run that also re-reads files
                                            recorded as invalid or unavailable
* ``POST admin/sources/<id>/cancel``        stop the active run after its batch
* ``POST admin/sources/<id>/status``        ``{"status": "enabled" | "disabled"}``

Indexing runs in a separate worker process (:mod:`radar.index_worker`), one
active run per source, so a large source never blocks gateway requests.
Runs whose worker died are marked ``interrupted`` when the gateway starts and
whenever maintainers list the sources.

No response contains storage keys, full storage locations or credentials.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import uuid
from pathlib import Path

from aiohttp import web

from . import server as S
from .radar import automatic
from .radar import observations as obs
from .radar.curator_intake import intake_root, stage_intake
from .radar import resumable_intake as RI
from .radar import resumable_janitor as RJ
from .radar.explorer_query import (FEATURE_LIMIT, ITEM_LIMIT, decode_cursor,
                                   encode_cursor, parse_explorer_query)
from .radar.assets import asset_image_paths, asset_nav_rows, list_manifests, read_manifest
from .radar.catalog import (
    ASSET_STATUSES,
    PROCESSING_STATES,
    REVIEW_STATES,
    CatalogError,
    create_catalog,
    is_catalog_key,
    is_valid_dataset_id,
    is_valid_source_id,
    open_catalog,
    SOURCE_VISIBILITIES,
)
from .radar.storage import (
    PLANNED_REQUIREMENTS,
    PROVIDERS,
    StorageError,
    StorageKeyError,
    approved_roots,
    cloud_provider_status,
    mask_location,
    normalize_key,
    provider_for,
    s3_approvals,
    s3_endpoint_names,
    validate_s3_config,
    validate_drive_config,
)


MAINTAINER_ROLES = frozenset({"maintainer", "admin", "owner"})
INDEX_WORKERS_KEY = "frozen_legacies_index_workers"
AUTH_KEY = "frozen_legacies_catalog_auth"
WORKER_MODULE = f"{__package__}.radar.index_worker"
REPO_ROOT = Path(__file__).resolve().parents[3]
#: a running worker writes a heartbeat every few seconds
STALE_RUN_S = 90.0
_CREDENTIAL_WORDS = ("secret", "token", "password", "credential", "session", "access_key",
                     "accesskey", "api_key", "apikey")
OBSERVATION_LIMIT = 20_000
SEGMENT_LIMIT = 5_000
CURATOR_UPLOAD_BYTES = 1024**3


# ── per-user processing state ────────────────────────────────────────
def processing_state(workspace, manifest: dict) -> dict:
    """The user's processing state of one asset (manual and automatic).

    ``needs_review``, ``reviewed`` and ``published`` belong to the later
    review workflow and are not assigned; a completed automatic run is not a
    reviewed result.
    """
    asset_id = manifest["asset_id"]
    manual_state = None
    session = workspace.asset_file(asset_id, "session.json")
    if session.is_file() and not session.is_symlink():
        try:
            status = json.loads(session.read_text(encoding="utf-8")).get("status")
            manual_state = "manual_completed" if status == "completed" else "manual_in_progress"
        except (OSError, ValueError):
            manual_state = None
    job = automatic.read_job(workspace, asset_id)
    automatic_state = None
    if job is not None:
        automatic_state = {
            "queued": "automatic_pending", "running": "automatic_running",
            "completed": "automatic_completed",
        }.get(job["status"], "automatic_failed")
    states = [s for s in (manual_state, automatic_state) if s]
    return {"manual": manual_state, "automatic": automatic_state,
            "states": states or ["unprocessed"]}


def record_state(workspace, manifest: dict, *, forget: bool = False) -> None:
    """Update the catalog's index of this user's state for a catalog asset.

    The workspace stays authoritative; this index lets progress and status
    filters be answered by queries instead of scanning workspaces."""
    if forget:
        catalog = open_catalog()
        if catalog is not None:
            catalog.clear_user_observations(workspace.user.safe_id, [manifest["asset_id"]])
    key = manifest.get("shared_source") or ""
    if manifest.get("origin") != "shared" or not is_catalog_key(key):
        return
    catalog = open_catalog()
    if catalog is None:
        return
    state = {"manual": None, "automatic": None} if forget else processing_state(workspace, manifest)
    catalog.set_user_state(workspace.user.safe_id, key, manifest["asset_id"],
                           manual=state["manual"], automatic=state["automatic"])


def record_state_by_id(workspace, asset_id: str) -> None:
    try:
        record_state(workspace, read_manifest(workspace, asset_id))
    except Exception:          # the index is advisory; never break the caller
        pass


_reconciled: set[tuple[str, str]] = set()
_reconcile_lock = threading.Lock()


def reconcile_user(workspace, catalog) -> None:
    """Bring the state index in line with this user's workspace, once per
    server process (covers work done before the index existed or while it
    was unavailable)."""
    marker = (str(catalog.path), workspace.user.safe_id)
    with _reconcile_lock:
        if marker in _reconciled:
            return
        _reconciled.add(marker)
    known = catalog.user_states(workspace.user.safe_id)
    seen = set()
    for manifest in list_manifests(workspace):
        key = manifest.get("shared_source") or ""
        if manifest.get("origin") == "shared" and is_catalog_key(key):
            seen.add(key)
            record_state(workspace, manifest)
    for key, row in known.items():
        if key not in seen:
            catalog.set_user_state(workspace.user.safe_id, key, row["asset_id"],
                                   manual=None, automatic=None)


# ── user catalog API ─────────────────────────────────────────────────
def _int(value, default=None, *, name):
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError:
        raise CatalogError(f"{name} must be an integer.")


def _dataset(value):
    if value and not is_valid_dataset_id(value):
        raise CatalogError("Invalid dataset.")
    return value or None


def _flight(value):
    if value and not re.fullmatch(r"[A-Za-z0-9._-]{1,32}", value):
        raise CatalogError("Invalid flight.")
    return value or None


async def api_catalog_search(request: web.Request) -> web.Response:
    catalog = open_catalog()
    query = request.query
    page = _int(query.get("page"), 1, name="page")
    page_size = _int(query.get("page_size"), 25, name="page_size")
    filters = {
        "dataset_id": _dataset(query.get("dataset")),
        "flight": _flight(query.get("flight")),
        "status": query.get("status") or None,
        "state": query.get("state") or None,
        "q": (query.get("q") or "").strip()[:100] or None,
        "cbd": _int(query.get("cbd"), None, name="cbd"),
        "catalog_id": query.get("id") or None,
        "source_id": query.get("source") or None,
        "include_restricted": await S._blocking(is_maintainer, request),
    }
    if filters["source_id"] is not None and not is_valid_source_id(filters["source_id"]):
        raise CatalogError("Invalid data source ID.")
    if filters["catalog_id"] is not None and not is_catalog_key(filters["catalog_id"]):
        raise CatalogError("Invalid catalog ID.")
    if filters["status"] is not None and filters["status"] not in ASSET_STATUSES:
        raise CatalogError("Unknown catalog status.")
    if (filters["state"] is not None and filters["state"] not in PROCESSING_STATES
            and filters["state"] not in REVIEW_STATES):
        raise CatalogError("Unknown processing state.")
    if catalog is None:
        return S._json({"items": [], "total": 0, "page": 1, "page_size": page_size, "pages": 1})
    workspace = S.workspace_for_request(request)

    def run():
        reconcile_user(workspace, catalog)
        return catalog.search(owner=workspace.user.safe_id, page=page, page_size=page_size,
                              **filters)

    return S._json(await S._blocking(run))


async def api_catalog_summary(request: web.Request) -> web.Response:
    catalog = open_catalog()
    if catalog is None:
        return S._json({"total": 0, "datasets": [], "flights": []})
    dataset = _dataset(request.query.get("dataset"))
    workspace = S.workspace_for_request(request)

    def run():
        reconcile_user(workspace, catalog)
        return catalog.summary(dataset_id=dataset, owner=workspace.user.safe_id)

    return S._json(await S._blocking(run))


async def api_catalog_segments(request: web.Request) -> web.Response:
    catalog = open_catalog()
    if catalog is None:
        return S._json({"type": "FeatureCollection", "features": [],
                        "summary": {"returned": 0, "truncated": False}})
    dataset = _dataset(request.query.get("dataset"))
    flight = _flight(request.query.get("flight"))
    bbox = _bbox(request.query.get("bbox"))
    limit = min(SEGMENT_LIMIT, max(1, _int(request.query.get("limit"), SEGMENT_LIMIT,
                                            name="limit")))
    return S._json(await S._blocking(catalog.segments, dataset_id=dataset, flight=flight,
                                     bbox=bbox, limit=limit))


async def api_catalog_explorer(request: web.Request) -> web.Response:
    """Return one consistent, authorization-trimmed ExplorerQueryV1 snapshot."""
    try:
        query = parse_explorer_query(request.query)
    except CatalogError as error:
        if str(error).startswith("Unsupported explorer"):
            return S._error(422, str(error))
        raise
    catalog = open_catalog()
    if catalog is None:
        return S._json({"query_version": 1, "query": query.canonical(), "snapshot": "empty",
                        "total": 0, "items": [],
                        "features": {"type": "FeatureCollection", "features": []},
                        "facets": {"dataset": [], "flight": [], "source": [], "review": []},
                        "page": {"next_cursor": None},
                        "limits": {"items": ITEM_LIMIT, "features": FEATURE_LIMIT,
                                   "features_truncated": False}})
    workspace = S.workspace_for_request(request)
    offset = decode_cursor(query.cursor, query.fingerprint())
    include_restricted = await S._blocking(is_maintainer, request)

    def run():
        reconcile_user(workspace, catalog)
        return catalog.explorer_snapshot(query, owner=workspace.user.safe_id,
                                         include_restricted=include_restricted, offset=offset,
                                         item_limit=ITEM_LIMIT, feature_limit=FEATURE_LIMIT)

    result = await S._blocking(run)
    next_offset = offset + len(result["items"])
    next_cursor = (encode_cursor(next_offset, query.fingerprint())
                   if next_offset < result["total"] else None)
    return S._json({"query_version": 1, "query": query.canonical(include_cursor=False),
                    "snapshot": result["snapshot"], "total": result["total"],
                    "items": result["items"], "features": result["features"],
                    "facets": result["facets"], "page": {"next_cursor": next_cursor},
                    "limits": {"items": ITEM_LIMIT, "features": FEATURE_LIMIT,
                               "features_truncated": result["features_truncated"]}})


def _observation_preview_window(record: dict, cbd: int) -> tuple[int, int, int]:
    """Return a useful, CBD-centred TIFF window and pyramid scale.

    The source TIFFs are whole-film strips (commonly about 38,000 columns).
    Rendering that entire width into a small quicklook turns the radar data
    into an unreadable horizontal line.  CBD labels divide the strip into
    consecutive film frames, so use that range to show the selected frame
    with a small amount of neighbouring context.
    """
    image_width = int(record.get("width") or 0)
    image_height = int(record.get("height") or 0)
    cbd_start = int(record.get("cbd_start"))
    cbd_end = int(record.get("cbd_end"))
    if image_width < 1 or cbd_end < cbd_start or not cbd_start <= cbd <= cbd_end:
        raise ValueError("The catalog record cannot locate this CBD.")

    frame_count = cbd_end - cbd_start + 1
    columns_per_frame = image_width / frame_count
    centre = round(((cbd - cbd_start) + 0.5) * columns_per_frame)
    window_width = min(image_width, max(512, round(columns_per_frame * 1.35)))
    x = max(0, min(image_width - window_width, centre - window_width // 2))

    # Aim for a roughly 1,200 x 800 response while using only supported
    # pyramid levels.  The browser then displays real frame detail rather
    # than a full-strip thumbnail.
    required_scale = max(1, (window_width + 1199) // 1200,
                         (image_height + 799) // 800)
    scale = next((level for level in (1, 2, 4, 8, 16, 32, 64)
                  if level >= required_scale), 64)
    return x, window_width, scale


async def api_catalog_observation_preview(request: web.Request) -> web.Response:
    """Render a bounded temporary A-/Z-scope TIFF preview for one flight/CBD."""
    scope = str(request.query.get("scope") or "").strip().lower()
    source_id = {"ascope": "ascope-temporary", "zscope": "zscope-temporary"}.get(scope)
    if source_id is None:
        return S._error(404, "Preview is not available.")
    flight = _flight(request.query.get("flight"))
    cbd = _int(request.query.get("cbd"), None, name="cbd")
    if not flight or cbd is None:
        raise CatalogError("A flight and CBD are required for an observation preview.")
    catalog = open_catalog()
    if catalog is None:
        return S._error(404, "Preview is not available.")
    result = await S._blocking(catalog.search, source_id=source_id, flight=flight, cbd=cbd,
                               include_restricted=True, page=1, page_size=1)
    if not result["items"]:
        return S._error(404, "No indexed TIFF covers this observation.")
    record = await S._blocking(catalog.resolve, result["items"][0]["catalog_id"])
    if record is None or record.get("source_id") != source_id:
        return S._error(404, "Preview is not available.")
    try:
        provider = provider_for(record["provider"], record["config"])
        path = provider.local_file(record["storage_key"])
    except (OSError, StorageError, StorageKeyError, ValueError):
        return S._error(404, "Preview is not available.")
    if path is None:
        return S._error(404, "Preview is not available.")
    try:
        x, width, scale = _observation_preview_window(record, cbd)
        png = await S._blocking(S.render_cached, request.app[S.IMAGE_CACHE_KEY],
                                request.app[S.WINDOW_CACHE_KEY], path,
                                x=x, width=width, scale=scale)
    except (OSError, ValueError, S.RenderRequestError):
        return S._error(404, "Preview is not available.")
    response = web.Response(body=png, content_type="image/png")
    response.headers["Cache-Control"] = "private, max-age=300"
    response.headers["X-Scientific-Status"] = "temporary-scratch-preview"
    response.headers["X-Catalog-Asset"] = record["catalog_id"]
    response.headers["X-Preview-Window"] = f"{x}:{width}:{scale}"
    return response


# ── user observations (live map layer) ───────────────────────────────
def _bbox(raw):
    if not raw:
        return None
    try:
        values = [float(v) for v in raw.split(",")]
    except ValueError:
        raise CatalogError("bbox must be min_lon,min_lat,max_lon,max_lat.")
    if len(values) != 4 or not (-90 <= values[1] <= values[3] <= 90):
        raise CatalogError("bbox must be min_lon,min_lat,max_lon,max_lat.")
    return values


def index_observations(workspace, asset_id: str, document: dict | None) -> None:
    """Mirror one asset's observations into the user's indexed copy."""
    catalog = open_catalog()
    if catalog is None:
        return
    records = document["observations"] if document else []
    if records:
        records = _georeferenced(workspace, asset_id, records)
    features = [obs.feature(r, document["source"]) for r in records]
    catalog.replace_user_observations(workspace.user.safe_id, asset_id, features)


def _georeferenced(workspace, asset_id: str, records: list[dict]) -> list[dict]:
    """Records with the verified-CBD fields of :mod:`radar.georef` (when
    installed); ASTRA's own fields are never changed."""
    try:
        from .radar import georef
    except ImportError:
        return records
    try:
        from .radar.assets import asset_image_paths
        try:
            _tiff, nav = asset_image_paths(workspace, read_manifest(workspace, asset_id),
                                           S.load_sources())
        except Exception:
            nav = None
        return georef.annotate_asset(workspace, asset_id, [dict(r) for r in records], nav)
    except Exception as error:
        # My picks then shows ASTRA's positions, which are unverified anyway;
        # submission (radar/review.py) fails instead of dropping georeferencing
        print(f"[FrozenLegacies] georeferencing of asset {asset_id} not applied to My picks: "
              f"{type(error).__name__}", file=sys.stderr)
        return records


def reconcile_observations(workspace, catalog, sources) -> None:
    """Rebuild the user's observation index from their workspace once per
    server process (work done before the index existed, or while it was not
    reachable); afterwards every write keeps it current."""
    marker = ("observations", str(catalog.path), workspace.user.safe_id)
    with _reconcile_lock:
        if marker in _reconciled:
            return
        _reconciled.add(marker)
    from .radar.assets import asset_image_paths
    from .radar import manual as manual_mod

    owner = workspace.user.safe_id
    present = set()
    for manifest in list_manifests(workspace):
        aid = manifest["asset_id"]
        document = obs.read(workspace, aid)
        if obs.is_stale(workspace, aid, document):
            document = rebuild_observations(workspace, manifest, sources, manual_mod,
                                            asset_image_paths)
        if document:
            present.add(aid)
            index_observations(workspace, aid, document)
    catalog.clear_user_observations(owner, catalog.user_observation_assets(owner) - present)


def query_observations(workspace, sources, *, bbox=None, status=None, asset_id=None,
                       limit=OBSERVATION_LIMIT) -> dict:
    """The user's observations: from the indexed copy when the installation
    has a catalog (bounded SQL query), otherwise read from the workspace."""
    catalog = open_catalog()
    if catalog is None:
        return collect_observations(workspace, sources, bbox=bbox, status=status,
                                    asset_id=asset_id, limit=limit)
    reconcile_observations(workspace, catalog, sources)
    return catalog.query_user_observations(workspace.user.safe_id, bbox=bbox, status=status,
                                           asset_id=asset_id, limit=limit)


def collect_observations(workspace, sources, *, bbox=None, status=None, asset_id=None,
                         limit=OBSERVATION_LIMIT) -> dict:
    """The user's observations as a GeoJSON FeatureCollection (WGS84),
    read from each asset's structured ``observations.json`` (no CSV parsing)."""
    from .radar.assets import asset_image_paths
    from .radar import manual as manual_mod

    features, without_position, truncated = [], 0, False
    counts = {"draft": 0, "completed": 0}
    for manifest in list_manifests(workspace):
        if asset_id and manifest["asset_id"] != asset_id:
            continue
        aid = manifest["asset_id"]
        document = obs.read(workspace, aid)
        if obs.is_stale(workspace, aid, document):
            document = rebuild_observations(workspace, manifest, sources, manual_mod,
                                            asset_image_paths)
        if not document:
            continue
        for record in document["observations"]:
            if status and record["status"] != status:
                continue
            counts[record["status"]] = counts.get(record["status"], 0) + 1
            position = obs.map_position(record)
            if position is None:
                without_position += 1
                continue
            if not obs.in_bbox(position, bbox):
                continue
            if len(features) >= limit:
                truncated = True
                continue
            features.append(obs.feature(record, document["source"]))
    return {"type": "FeatureCollection", "features": features,
            "summary": {"returned": len(features), "without_position": without_position,
                        "truncated": truncated, "by_status": counts}}


def rebuild_observations(workspace, manifest, sources, manual_mod, asset_image_paths):
    """Recompute an asset's observations from its session (or drop them).

    Used only when ``observations.json`` is missing or older than the session
    (for example sessions saved before observations existed)."""
    aid = manifest["asset_id"]
    try:
        image = manifest.get("image") or {}
        from .pickers.astra import AstraGeometry
        geometry = AstraGeometry.for_image(int(image["width"]), int(image["height"]))
        filename = manifest.get("filename") or ""
        doc = manual_mod.load_document(workspace, aid, geometry, filename)
    except Exception:
        return None
    if doc is None:
        obs.remove(workspace, aid)
        return None
    try:
        _tiff, nav = asset_image_paths(workspace, manifest, sources)
    except Exception:
        nav = None
    document = obs.build(aid, manifest, doc, nav)
    obs.write(workspace, aid, document)
    return document


async def api_observations(request: web.Request) -> web.Response:
    workspace = S.workspace_for_request(request)
    bbox = _bbox(request.query.get("bbox"))
    status = request.query.get("status") or None
    if status is not None and status not in ("draft", "completed"):
        raise CatalogError("status must be draft or completed.")
    asset_id = request.query.get("asset") or None
    if asset_id is not None and not re.fullmatch(r"[0-9a-f]{32}", asset_id):
        raise CatalogError("Invalid asset.")
    limit = min(OBSERVATION_LIMIT, max(1, _int(request.query.get("limit"),
                                               OBSERVATION_LIMIT, name="limit")))
    def query():
        result = annotate_stages(workspace, query_observations(
            workspace, S.load_sources(), bbox=bbox, status=status, asset_id=asset_id,
            limit=limit))
        return append_automatic_observations(workspace, result, S.load_sources(), bbox=bbox,
                                             status=status, asset_id=asset_id, limit=limit)

    return S._json(await S._blocking(query))


def append_automatic_observations(workspace, result: dict, sources: dict, *, bbox=None,
                                  status=None, asset_id=None, limit=OBSERVATION_LIMIT) -> dict:
    """Add private, unvalidated automatic results to the owner's map feed."""
    summary = {"total": 0, "positioned": 0, "without_position": 0}
    if status == "draft":
        result["summary"]["automatic"] = summary
        return result
    for manifest in list_manifests(workspace):
        if asset_id and manifest["asset_id"] != asset_id:
            continue
        job = automatic.read_job(workspace, manifest["asset_id"])
        if not job or job.get("picker") != "lyra" or job.get("status") != "completed":
            continue
        try:
            _tiff, nav = asset_image_paths(workspace, manifest, sources)
            mapped = automatic.lyra_map_observations(
                workspace, manifest, sources, asset_nav_rows(nav, manifest))
        except Exception:
            continue
        summary["total"] += mapped["total"]
        summary["positioned"] += mapped["positioned"]
        summary["without_position"] += mapped["total"] - mapped["positioned"]
        for record in mapped["records"]:
            position = record.pop("position")
            if position is None or not obs.in_bbox(position, bbox):
                continue
            if len(result["features"]) >= limit:
                result["summary"]["truncated"] = True
                continue
            result["features"].append({
                "type": "Feature", "id": record["observation_id"],
                "geometry": {"type": "Point", "coordinates": position},
                "properties": {**record, "filename": manifest.get("filename")},
            })
    result["summary"]["automatic"] = summary
    result["summary"]["returned"] = len(result["features"])
    return result


def annotate_stages(workspace, result: dict) -> dict:
    """Add each result's review stage (:func:`radar.review.result_stage`) to
    the user's observations and count the user's results per stage. Derived
    on every request, so a reviewer's decision or a later edit shows at once;
    the indexed observations themselves are not changed."""
    from .radar.review import ReviewStore, result_stage, session_version

    catalog = open_catalog()
    submissions = ReviewStore(catalog).by_asset(workspace.user.safe_id) if catalog else {}
    stages, counts = {}, {}
    for manifest in list_manifests(workspace):
        aid = manifest["asset_id"]
        document = obs.read(workspace, aid)
        if not document:
            continue
        # the session itself is read only when there is a version to compare
        session = session_version(workspace, aid) if aid in submissions else \
            {"status": document.get("status"), "revision": document.get("session_revision")}
        stage = result_stage(session, submissions.get(aid, []))
        stages[aid] = stage
        counts[stage["stage"]] = counts.get(stage["stage"], 0) + 1
    for feature in result["features"]:
        stage = stages.get(feature["properties"].get("asset_id"))
        if stage:
            feature["properties"]["review"] = stage
    result["summary"]["results_by_stage"] = counts
    return result


# ── maintainer: data sources ─────────────────────────────────────────
def _maintainer(auth, handler):
    """Signed-in Control Center maintainer, admin or owner, verified against
    the role store on every request (JSON errors)."""

    async def protected(request: web.Request) -> web.StreamResponse:
        user = auth.current_user(request)
        if user is None:
            return S._error(401, "Authentication required.")
        roles = set(auth.storage.get_user_roles(user_id=user.id))
        if not roles & MAINTAINER_ROLES:
            return S._error(403, "Managing Frozen Legacies data sources requires a "
                                 "maintainer role.")
        request["cryostack_user"] = user
        request["cryostack_roles"] = roles
        try:
            return await handler(request)
        except (CatalogError, StorageKeyError) as error:
            return S._error(400, str(error))
        except StorageError as error:
            return S._error(409, str(error))

    return protected


def _location(source: dict) -> str:
    config = source.get("config") or {}
    if source.get("provider") == "s3":
        where = "/".join(p for p in (config.get("bucket"), config.get("prefix")) if p)
        return "s3://" + mask_location(where)
    if source.get("provider") in ("gdrive", "onedrive", "dropbox"):
        folder = config.get("folder_id") or config.get("folder") or ""
        return mask_location("/".join(p for p in (config.get("drive_id"), folder) if p))
    return mask_location(config.get("root") or "")


def _managed_intake_status(source: dict) -> str | None:
    """Return a managed intake's publication state, failing closed on damage."""
    try:
        managed = intake_root()
        configured = Path((source.get("config") or {}).get("root") or "").resolve()
    except (OSError, StorageError):
        return None
    if managed is None or not (configured == managed or managed in configured.parents):
        return None
    receipt = configured / "intake-receipt.json"
    try:
        if receipt.is_symlink() or not receipt.is_file():
            return "invalid"
        document = json.loads(receipt.read_text(encoding="utf-8"))
        if document.get("schema") != "cryostack.frozen-legacies.curator-intake":
            return "invalid"
        return document.get("publication_status") or "invalid"
    except (OSError, ValueError, TypeError):
        return "invalid"


def _public_run(run: dict | None) -> dict | None:
    if run is None:
        return None
    keys = ("run_id", "status", "started_at", "finished_at", "heartbeat_at", "discovered",
            "added", "changed", "unchanged", "missing", "invalid", "unavailable", "moved",
            "full", "allow_mass_missing", "retry_invalid", "cancel_requested", "error")
    return {k: run.get(k) for k in keys}


def public_source(source: dict, runs: list | None = None, *, active: dict | None = None,
                  errors: list | None = None) -> dict:
    """A data source for maintainers: no credentials, location masked."""
    config = source.get("config") or {}
    counts = source.get("counts") or {}
    progress = None
    if active is not None:
        progress = _public_run(active)
        # incremental runs revisit every known file: the catalog size is the
        # best available estimate of the total
        progress["known_total"] = counts.get("total", 0)
    intake_status = _managed_intake_status(source)
    return {
        "source_id": source["source_id"], "name": source["name"],
        "provider": source["provider"], "dataset_id": source["dataset_id"],
        "status": source["status"],
        "visibility": source.get("visibility") or "users",
        "managed_intake": intake_status is not None,
        "publication_status": intake_status,
        "location": _location(source),
        "region": config.get("region") if source["provider"] == "s3" else None,
        "endpoint": (config.get("endpoint") or "aws") if source["provider"] == "s3" else None,
        "tiff_prefix": config.get("tiff_prefix") or "",
        "nav_template": config.get("nav_template") or "",
        "counts": counts,
        "connection": {
            "checked_at": source.get("last_check_at"),
            "ok": None if source.get("last_check_ok") is None else bool(source["last_check_ok"]),
            "message": source.get("last_check_message"),
        },
        "last_success_at": source.get("last_success_at"),
        "last_index_at": source.get("last_index_at"),
        "last_index_status": source.get("last_index_status"),
        "last_index_error": source.get("last_index_error"),
        "indexing": active is not None,
        "progress": progress,
        "runs": [_public_run(r) for r in runs or []],
        "recent_errors": errors or [],
    }


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError, ValueError):
        return True
    return True


def reconcile_runs(catalog) -> list[int]:
    """Runs whose worker is gone become ``interrupted``."""
    return catalog.reconcile_runs(stale_after_s=STALE_RUN_S, is_alive=_pid_alive)


def _admin_listing(catalog) -> list[dict]:
    reconcile_runs(catalog)
    out = []
    for source in catalog.list_sources():
        sid = source["source_id"]
        out.append(public_source(source, catalog.runs(sid, 5), active=catalog.active_run(sid),
                                 errors=catalog.recent_errors(sid, 5)))
    return out


def _dataset_choices(sources: list[dict]) -> list[dict]:
    """Dataset IDs to suggest: the published datasets and those already used."""
    choices = {}
    try:
        published = json.loads((S.frozen_legacies_root() / "data" / "catalog.json")
                               .read_text(encoding="utf-8")).get("datasets") or []
    except (OSError, ValueError):
        published = []
    for item in published:
        if isinstance(item, dict) and is_valid_dataset_id(item.get("id")):
            choices[item["id"]] = item.get("name") or item["id"]
    for source in sources:
        choices.setdefault(source["dataset_id"], source["dataset_id"])
    return [{"id": k, "name": v} for k, v in sorted(choices.items())]


async def api_admin_sources(request: web.Request) -> web.Response:
    catalog = open_catalog()
    sources = await S._blocking(_admin_listing, catalog) if catalog else []
    allowed = s3_approvals()
    try:
        managed_root = intake_root()
        managed_intake = bool(managed_root and managed_root.is_dir()
                              and os.access(managed_root, os.W_OK | os.X_OK))
    except StorageError:
        managed_intake = False
    return S._json({
        "sources": sources, "providers": list(PROVIDERS),
        "storage_roots_configured": bool(approved_roots()),
        "storage_root_count": len(approved_roots()),
        # approved S3 locations and endpoint *names* (never their URLs)
        "s3": {"configured": bool(allowed),
               "approved": [f"s3://{b}/{p}".rstrip("/") for b, p in allowed],
               "endpoints": sorted(s3_endpoint_names())},
        "datasets": _dataset_choices(sources),
        "cloud": cloud_provider_status(),
        "planned": [],
        "visibilities": list(SOURCE_VISIBILITIES),
        "managed_intake": {"configured": managed_intake,
                           "max_upload_bytes": CURATOR_UPLOAD_BYTES},
    })


def _validated_config(payload: dict) -> dict:
    for key in payload:
        if any(word in str(key).lower() for word in _CREDENTIAL_WORDS):
            raise CatalogError("Data sources never carry credentials. The server resolves "
                               "AWS credentials itself (IAM role or default credential chain).")
    provider = payload.get("provider")
    if provider not in PROVIDERS:
        raise CatalogError(f"provider must be one of: {', '.join(PROVIDERS)}.")
    prefix = str(payload.get("tiff_prefix") or "").strip().strip("/")
    if prefix:
        normalize_key(prefix)
    template = str(payload.get("nav_template") or "").strip()
    if template:
        if "{flight}" not in template:
            raise CatalogError("The navigation template must contain {flight}.")
        normalize_key(template.replace("{flight}", "1"))
    layout = {"tiff_prefix": prefix, "nav_template": template}
    if provider == "s3":
        config = validate_s3_config({
            "bucket": str(payload.get("bucket") or "").strip(),
            "prefix": str(payload.get("prefix") or "").strip(),
            "region": str(payload.get("region") or "").strip() or None,
            "endpoint": str(payload.get("endpoint") or "").strip() or None,
        })
        return {**config, **layout}
    if provider in ("gdrive", "onedrive", "dropbox"):
        config = validate_drive_config(provider, {
            "drive_id": str(payload.get("drive_id") or "").strip(),
            "folder_id": str(payload.get("folder_id") or "").strip(),
            "folder": str(payload.get("folder") or "").strip(),
        })
        return {**config, **layout}
    root = str(payload.get("root") or "").strip()
    if not root:
        raise CatalogError("A local data source needs a directory.")
    config = {"root": root, **layout}
    provider_for(provider, config)      # validates the root against approved roots
    return config


async def api_admin_add_source(request: web.Request) -> web.Response:
    S._require_same_origin(request)
    try:
        payload = await request.json()
    except ValueError:
        raise CatalogError("A JSON body is required.")
    if not isinstance(payload, dict):
        raise CatalogError("A JSON object is required.")
    config = _validated_config(payload)
    source_id = payload.get("source_id")
    if not is_valid_source_id(source_id):
        raise CatalogError("Source IDs are 2-63 lowercase letters, digits and hyphens.")
    catalog = open_catalog() or await S._blocking(create_catalog)
    source = await S._blocking(
        catalog.add_source, source_id=source_id, name=payload.get("name"),
        provider=payload["provider"], dataset_id=payload.get("dataset_id"), config=config)
    if payload.get("visibility") not in (None, "users"):
        await S._blocking(catalog.set_source_visibility, source_id, payload.get("visibility"))
        source = await S._blocking(catalog.get_source, source_id)
    await S._blocking(audit_source, request, source_id, "add", None,
                      f"{source['provider']} · {source['dataset_id']} · "
                      f"{source.get('visibility') or 'users'}")
    return S._json(public_source(source), status=201)


async def api_admin_create_intake(request: web.Request) -> web.Response:
    """Stage uploaded TIFF/CSV/ZIP material as an unpublished local source."""
    S._require_same_origin(request)
    root = intake_root()
    if root is None:
        return S._error(409, "Managed scientific intake is not configured on this server.")
    if not root.is_dir() or not os.access(root, os.W_OK | os.X_OK):
        return S._error(409, "The managed intake volume is not mounted and writable.")
    fields: dict[str, str] = {}
    uploads: list[tuple[str, Path]] = []
    # Large requests land on the configured intake volume, never /tmp or the
    # source checkout where they could exhaust the VM root filesystem.
    temporary = Path(tempfile.mkdtemp(prefix=".upload-", dir=root))
    total = 0
    try:
        reader = await request.multipart()
        async for part in reader:
            if part.filename:
                safe_name = Path(part.filename).name
                target = temporary / f"{len(uploads):05d}.upload"
                with target.open("xb") as output:
                    while True:
                        chunk = await part.read_chunk(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > CURATOR_UPLOAD_BYTES:
                            raise CatalogError("The intake upload exceeds the 1 GiB request limit.")
                        output.write(chunk)
                uploads.append((safe_name, target))
            elif part.name in {"source_id", "name", "dataset_id", "nav_template"}:
                fields[part.name] = (await part.text()).strip()
        source_id, dataset_id = fields.get("source_id"), fields.get("dataset_id")
        if not is_valid_source_id(source_id) or not is_valid_dataset_id(dataset_id):
            raise CatalogError("A valid source ID and dataset ID are required.")
        catalog = open_catalog() or await S._blocking(create_catalog)
        if await S._blocking(catalog.get_source, source_id) is not None:
            raise CatalogError("A data source with this ID already exists.")
        name = fields.get("name", "").strip()
        if not name:
            raise CatalogError("An intake name is required.")
        nav_template = fields.get("nav_template") or "nav/{flight}.csv"
        if "{flight}" not in nav_template:
            raise CatalogError("The navigation template must contain {flight}.")
        normalize_key(nav_template.replace("{flight}", "1"))
        final = root / source_id
        if final.exists():
            raise CatalogError("A managed intake with this source ID already exists.")
        staging = root / f".staging-{source_id}-{uuid.uuid4().hex}"
        receipt = await S._blocking(stage_intake, staging, uploads, dataset_id=dataset_id)
        staging.rename(final)
        try:
            source = await S._blocking(
                catalog.add_source, source_id=source_id, name=name, provider="local",
                dataset_id=dataset_id,
                config={"root": str(final), "tiff_prefix": "tiff", "nav_template": nav_template})
            await S._blocking(catalog.set_source_visibility, source_id, "maintainers")
        except BaseException:
            # If registration never committed, leave no untracked durable
            # upload. If it committed, preserve bytes for reconciliation.
            if await S._blocking(catalog.get_source, source_id) is None:
                await S._blocking(shutil.rmtree, final, True)
            raise
        source = await S._blocking(catalog.get_source, source_id)
        await S._blocking(audit_source, request, source_id, "curator intake", None,
                          f"{len(receipt['items'])} unverified files · unpublished")
        return S._json({"source": public_source(source), "receipt": receipt}, status=201)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _intake_owner(request: web.Request) -> str:
    return str(request["cryostack_user"].id)


async def api_admin_create_upload_session(request: web.Request) -> web.Response:
    """Create a durable, bounded session before any scientific bytes arrive."""
    S._require_same_origin(request)
    try:
        payload = await request.json()
    except ValueError:
        raise CatalogError("A JSON body is required.")
    if not isinstance(payload, dict):
        raise CatalogError("A JSON object is required.")
    if not is_valid_source_id(payload.get("source_id")):
        raise CatalogError("A valid source ID is required.")
    if not is_valid_dataset_id(payload.get("dataset_id")):
        raise CatalogError("A valid dataset ID is required.")
    if not str(payload.get("name") or "").strip():
        raise CatalogError("An intake name is required.")
    nav = str(payload.get("nav_template") or "nav/{flight}.csv")
    if "{flight}" not in nav:
        raise CatalogError("The navigation template must contain {flight}.")
    normalize_key(nav.replace("{flight}", "1"))
    catalog = open_catalog()
    if catalog and await S._blocking(catalog.get_source, payload["source_id"]):
        raise CatalogError("A data source with this ID already exists.")
    result = await S._blocking(RI.create, _intake_owner(request), payload)
    return S._json(result, status=201)


async def api_admin_upload_session_status(request: web.Request) -> web.Response:
    result = await S._blocking(RI.status, request.match_info["session_id"],
                               _intake_owner(request))
    return S._json(result)


async def api_admin_upload_session_chunk(request: web.Request) -> web.Response:
    S._require_same_origin(request)
    claimed = request.headers.get("X-Chunk-SHA256", "").strip().lower()
    if len(claimed) != 64:
        raise CatalogError("X-Chunk-SHA256 is required.")
    if request.content_length is None or request.content_length > RI.CHUNK_BYTES:
        raise CatalogError("A bounded Content-Length is required.")
    body = await request.read()
    result = await S._blocking(RI.put_chunk, request.match_info["session_id"],
                               _intake_owner(request), int(request.match_info["file_id"]),
                               int(request.match_info["chunk_index"]), body, claimed)
    return S._json(result)


async def api_admin_cancel_upload_session(request: web.Request) -> web.Response:
    S._require_same_origin(request)
    result = await S._blocking(RI.cancel, request.match_info["session_id"],
                               _intake_owner(request))
    return S._json(result)


def _intake_administrator(request: web.Request) -> bool:
    return bool(set(request.get("cryostack_roles") or ()) & {"admin", "owner"})


async def api_admin_upload_session_inventory(request: web.Request) -> web.Response:
    """Dry, owner-scoped reconciliation view; admins and owners see all."""
    result = await S._blocking(RJ.inventory, _intake_owner(request),
                               administrator=_intake_administrator(request))
    return S._json({"sessions": result})


async def api_admin_expire_upload_sessions(request: web.Request) -> web.Response:
    S._require_same_origin(request)
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    dry_run = not (isinstance(payload, dict) and payload.get("confirm") == "expire")
    result = await S._blocking(RJ.expire, _intake_owner(request),
                               administrator=_intake_administrator(request), dry_run=dry_run)
    return S._json(result)


async def api_admin_cleanup_upload_session(request: web.Request) -> web.Response:
    S._require_same_origin(request)
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    session_id = request.match_info["session_id"]
    dry_run = not (isinstance(payload, dict) and payload.get("confirm") == session_id)
    result = await S._blocking(RJ.cleanup, session_id, _intake_owner(request),
                               administrator=_intake_administrator(request), dry_run=dry_run)
    return S._json(result)


async def api_admin_finalize_upload_session(request: web.Request) -> web.Response:
    """Verify whole files, use the existing safe stager, then register privately."""
    S._require_same_origin(request)
    session_id, owner = request.match_info["session_id"], _intake_owner(request)
    current = await S._blocking(RI.status, session_id, owner)
    if current["state"] == "finalized":
        return S._json(current)
    if current["state"] in {"assembling", "committing"}:
        await _reconcile_intake_session(session_id)
        current = await S._blocking(RI.status, session_id, owner)
        if current["state"] == "finalized":
            return S._json(current)
        if current["state"] == "error":
            raise StorageError(current.get("error") or "Upload session recovery failed.")
    document, uploads = await S._blocking(RI.prepare_finalize, session_id, owner)
    root = intake_root()
    if root is None or not root.is_dir() or not os.access(root, os.W_OK | os.X_OK):
        raise StorageError("The managed intake volume is not mounted and writable.")
    source_id, dataset_id = document["source_id"], document["dataset_id"]
    if not is_valid_source_id(source_id) or not is_valid_dataset_id(dataset_id):
        raise StorageError("The upload session metadata is invalid.")
    catalog = open_catalog() or await S._blocking(create_catalog)
    existing = await S._blocking(catalog.get_source, source_id)
    final = root / source_id
    if existing and not _source_points_to(existing, final):
        await S._blocking(RI.mark_error, session_id,
                          "The source ID is registered to a different storage location.")
        raise CatalogError("A data source with this ID already exists.")
    if final.exists() and (not final.is_dir() or final.is_symlink()):
        await S._blocking(RI.mark_error, session_id,
                          "The final managed intake path is unsafe.")
        raise StorageError("The final managed intake path is unsafe.")
    if not final.exists():
        await S._blocking(RI.begin_commit, session_id, owner, uuid.uuid4().hex)
        staging = root / f".commit-{session_id}"
        await S._blocking(shutil.rmtree, staging, True)
        receipt = await S._blocking(stage_intake, staging, uploads, dataset_id=dataset_id)
        await S._blocking(os.replace, staging, final)
    else:
        # A prior attempt completed the atomic rename.  Trust only its durable
        # receipt; the safe stager is responsible for producing this document.
        try:
            receipt = json.loads((final / "intake-receipt.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            await S._blocking(RI.mark_error, session_id,
                              "The committed intake receipt is missing or damaged.")
            raise StorageError("The committed intake receipt is missing or damaged.")
    try:
        if existing is None:
            source = await S._blocking(
                catalog.add_source, source_id=source_id, name=document["name"], provider="local",
                dataset_id=dataset_id,
                config={"root": str(final), "tiff_prefix": "tiff",
                        "nav_template": document["nav_template"]})
            await S._blocking(catalog.set_source_visibility, source_id, "maintainers")
        else:
            source = existing
    except BaseException:
        if await S._blocking(catalog.get_source, source_id) is None:
            await S._blocking(shutil.rmtree, final, True)
        raise
    await S._blocking(RI.mark_finalized, session_id, owner, source_id)
    source = await S._blocking(catalog.get_source, source_id)
    await S._blocking(audit_source, request, source_id, "resumable curator intake", None,
                      f"{len(receipt['items'])} unverified files · unpublished")
    return S._json({"session": await S._blocking(RI.status, session_id, owner),
                    "source": public_source(source), "receipt": receipt}, status=201)


def _source_points_to(source: dict, final: Path) -> bool:
    try:
        configured = Path(source["config"]["root"]).resolve(strict=False)
        return configured == final.resolve(strict=False)
    except (KeyError, TypeError, ValueError, OSError):
        return False


async def _reconcile_intake_session(session_id: str) -> dict:
    """Compare durable filesystem and catalog facts, then repair session state."""
    candidates = {item["session_id"]: item
                  for item in await S._blocking(RI.recovery_candidates)}
    candidate = candidates.get(session_id)
    if candidate is None:
        return {}
    root = intake_root()
    if root is None or not root.is_dir():
        raise StorageError("The managed intake volume is not mounted.")
    final = root / str(candidate["source_id"])
    catalog = open_catalog() or await S._blocking(create_catalog)
    source = await S._blocking(catalog.get_source, candidate["source_id"])
    matches = bool(source and _source_points_to(source, final))
    return await S._blocking(
        RI.recover_commit, session_id, final_exists=final.is_dir() and not final.is_symlink(),
        catalog_matches=matches, catalog_conflict=bool(source and not matches))


async def _recover_intake_sessions(app: web.Application) -> None:
    """Reconcile interrupted resumable commits whenever the gateway starts."""
    try:
        candidates = await S._blocking(RI.recovery_candidates)
    except StorageError:
        return  # Intake is optional; a missing configured mount remains fail-closed.
    for candidate in candidates:
        try:
            await _reconcile_intake_session(candidate["session_id"])
        except Exception:
            # Preserve evidence and fail closed. A curator sees the durable
            # error on retry; startup of unrelated CryoStack services continues.
            continue


def _source_or_404(catalog, source_id: str) -> dict:
    source = catalog.get_source(source_id) if catalog else None
    if source is None:
        raise web.HTTPNotFound(text="Data source not found.")
    return source


async def api_admin_test_source(request: web.Request) -> web.Response:
    S._require_same_origin(request)
    catalog = open_catalog()
    source = _source_or_404(catalog, request.match_info["source_id"])
    try:
        provider = provider_for(source["provider"], source["config"])
        result = await S._blocking(provider.check)
    except (StorageError, StorageKeyError) as error:
        result = {"ok": False, "message": str(error)}
    await S._blocking(catalog.record_check, source["source_id"], result)
    return S._json(result)


async def _watch_worker(app, run_id: int, process) -> None:
    """Reap the worker; report a failing worker's last output in the server log."""
    try:
        _out, err = await process.communicate()
        if process.returncode not in (0, None):
            tail = (err or b"").decode("utf-8", "replace").strip().splitlines()[-15:]
            print(f"[FrozenLegacies] index run {run_id} exited with {process.returncode}:\n  "
                  + "\n  ".join(tail), file=sys.stderr)
    finally:
        app[INDEX_WORKERS_KEY].pop(run_id, None)


async def spawn_worker(app, catalog, run_id: int):
    """Start the worker process of a queued run (its own session, so a
    gateway restart does not take a healthy run down with it)."""
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", WORKER_MODULE, "--catalog", str(catalog.path), "--run",
        str(run_id), cwd=str(REPO_ROOT), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        start_new_session=True)
    app[INDEX_WORKERS_KEY][run_id] = (process, asyncio.ensure_future(
        _watch_worker(app, run_id, process)))
    return process


async def _queue(request: web.Request, *, full=False, allow_mass_missing=False,
                 retry_invalid=False) -> web.Response:
    catalog = open_catalog()
    source = _source_or_404(catalog, request.match_info["source_id"])
    if source["status"] != "enabled":
        return S._error(409, "Enable the data source before indexing it.")
    await S._blocking(reconcile_runs, catalog)
    user = request.get("cryostack_user")
    run_id = await S._blocking(
        catalog.queue_run, source["source_id"], full=full,
        allow_mass_missing=allow_mass_missing, retry_invalid=retry_invalid,
        requested_by=getattr(user, "id", None))
    if run_id is None:
        return S._error(409, "This data source is already being indexed.")
    try:
        await spawn_worker(request.app, catalog, run_id)
    except OSError as error:
        await S._blocking(catalog.finish_run, run_id, source["source_id"], status="failed",
                          counts={}, error=f"The indexing worker could not start ({error.strerror}).")
        return S._error(500, "The indexing worker could not be started.")
    return S._json({"source_id": source["source_id"], "indexing": True, "run_id": run_id,
                    "full": full, "retry_invalid": retry_invalid}, status=202)


async def _body(request: web.Request) -> dict:
    try:
        payload = await request.json() if request.can_read_body else {}
    except ValueError:
        payload = {}
    return payload if isinstance(payload, dict) else {}


async def api_admin_index_source(request: web.Request) -> web.Response:
    S._require_same_origin(request)
    payload = await _body(request)
    return await _queue(request, full=bool(payload.get("full")),
                        allow_mass_missing=bool(payload.get("allow_mass_missing")))


async def api_admin_retry_source(request: web.Request) -> web.Response:
    S._require_same_origin(request)
    return await _queue(request, retry_invalid=True)


async def api_admin_cancel_index(request: web.Request) -> web.Response:
    S._require_same_origin(request)
    catalog = open_catalog()
    source = _source_or_404(catalog, request.match_info["source_id"])
    active = await S._blocking(catalog.active_run, source["source_id"])
    if active is None:
        return S._error(409, "This data source is not being indexed.")
    run = await S._blocking(catalog.request_cancel, active["run_id"])
    worker = request.app[INDEX_WORKERS_KEY].get(active["run_id"])
    if worker is not None and worker[0].returncode is None:
        try:
            worker[0].terminate()        # our own child: the worker stops after its batch
        except ProcessLookupError:
            pass
    return S._json({"source_id": source["source_id"], "run": _public_run(run)}, status=202)


async def api_admin_source_status(request: web.Request) -> web.Response:
    S._require_same_origin(request)
    try:
        payload = await request.json()
    except ValueError:
        raise CatalogError("A JSON body is required.")
    catalog = open_catalog()
    source = _source_or_404(catalog, request.match_info["source_id"])
    status = (payload or {}).get("status")
    await S._blocking(catalog.set_source_status, source["source_id"], status)
    if status != source["status"]:
        await S._blocking(audit_source, request, source["source_id"], "status",
                          source["status"], status)
    return S._json(public_source(catalog.get_source(source["source_id"])))


async def api_admin_source_visibility(request: web.Request) -> web.Response:
    S._require_same_origin(request)
    try:
        payload = await request.json()
    except ValueError:
        raise CatalogError("A JSON body is required.")
    catalog = open_catalog()
    source = _source_or_404(catalog, request.match_info["source_id"])
    visibility = (payload or {}).get("visibility") if isinstance(payload, dict) else None
    intake_status = _managed_intake_status(source)
    if visibility == "users" and intake_status is not None and intake_status != "published":
        return S._error(409, "This scientific intake is unpublished and cannot be shown to users.")
    await S._blocking(catalog.set_source_visibility, source["source_id"], visibility)
    previous = source.get("visibility") or "users"
    if visibility != previous:
        await S._blocking(audit_source, request, source["source_id"], "visibility",
                          previous, visibility)
    return S._json(public_source(catalog.get_source(source["source_id"])))


async def api_admin_remove_source(request: web.Request) -> web.Response:
    """Remove a registration (catalog only; the storage is never touched).
    The body must repeat the source ID: ``{"confirm": "<source_id>"}``."""
    S._require_same_origin(request)
    try:
        payload = await request.json()
    except ValueError:
        raise CatalogError("A JSON body is required.")
    catalog = open_catalog()
    source = _source_or_404(catalog, request.match_info["source_id"])
    if not isinstance(payload, dict) or payload.get("confirm") != source["source_id"]:
        raise CatalogError("Confirm the removal by repeating the data source ID.")
    result = await S._blocking(catalog.remove_source, source["source_id"])
    await S._blocking(audit_source, request, source["source_id"], "remove",
                      f"{source['provider']} · {result['catalog_rows']} files", "removed",
                      reason=str(payload.get("reason") or "")[:500] or "data source removed")
    return S._json({"source_id": source["source_id"], **result,
                    "storage_untouched": True})


def _cache_state(provider, source_id: str, row: dict) -> str:
    """``in place`` (local files are read directly), ``cached`` or ``not cached``."""
    from .radar.storage import StorageObject
    from .radar.working_cache import working_cache
    if provider is not None and "local_files" in provider.capabilities:
        return "in place"
    cache = working_cache()
    obj = StorageObject(row["storage_key"], row["bytes"], row["mtime_ns"], row.get("etag"))
    target = cache.directory / cache._entry(source_id, obj) / Path(row["storage_key"]).name
    return "cached" if target.is_file() else "not cached"


async def api_admin_source_files(request: web.Request) -> web.Response:
    catalog = open_catalog()
    source = _source_or_404(catalog, request.match_info["source_id"])
    query = request.query
    page = _int(query.get("page"), 1, name="page")
    page_size = _int(query.get("page_size"), 50, name="page_size")

    def run():
        listing = catalog.source_files(source["source_id"], q=(query.get("q") or "").strip()[:100]
                                       or None, status=query.get("status") or None,
                                       page=page, page_size=page_size)
        try:
            provider = provider_for(source["provider"], source["config"])
        except (StorageError, StorageKeyError, CatalogError):
            provider = None
        for row in listing["items"]:
            row["cache"] = _cache_state(provider, source["source_id"], row)
            row["key"] = row.pop("storage_key")       # relative to the source; maintainers only
            row.pop("etag", None)
        return listing

    return S._json(await S._blocking(run))


async def api_catalog_sources(request: web.Request) -> web.Response:
    """Enabled data sources the caller may browse (for the asset selector)."""
    catalog = open_catalog()
    if catalog is None:
        return S._json({"sources": []})
    restricted = await S._blocking(is_maintainer, request)
    sources = await S._blocking(catalog.visible_sources, include_restricted=restricted)
    return S._json({"sources": sources})


def is_maintainer(request) -> bool:
    auth = request.app.get(AUTH_KEY)
    user = request.get("cryostack_user")
    if auth is None or user is None:
        return False
    return bool(set(auth.storage.get_user_roles(user_id=user.id)) & MAINTAINER_ROLES)


def audit_source(request, source_id: str, what: str, previous, new, *, reason=None) -> None:
    """One Control Center audit record for a data-source change (no
    locations or credentials: IDs, provider names and states only)."""
    auth = request.app.get(AUTH_KEY)
    actor = request.get("cryostack_user")
    if auth is None or actor is None:
        return
    auth.storage.record_access_audit(
        actor_user_id=actor.id, actor_label=getattr(actor, "email", None) or actor.id,
        target_user_id=None, target_label=f"data source {source_id}",
        action=f"frozen_legacies.source.{what}",
        previous_value=None if previous is None else str(previous),
        new_value=None if new is None else str(new),
        reason=reason or f"data source {what} changed")


def make_visibility_middleware(auth):
    """Opening a catalog file (``POST assets/shared`` with a ``cat-`` key)
    of a maintainers-only source requires a maintainer; others get 404, the
    same answer as for a file that does not exist."""

    @web.middleware
    async def catalog_visibility(request: web.Request, handler):
        if request.method != "POST" or request.path != "/frozen-legacies/api/assets/shared":
            return await handler(request)
        try:
            payload = json.loads((await request.read())[:4096] or b"{}")
        except ValueError:
            return await handler(request)
        key = payload.get("source") if isinstance(payload, dict) else None
        if not is_catalog_key(key):
            return await handler(request)
        catalog = open_catalog()
        record = await S._blocking(catalog.resolve, key) if catalog else None
        if record is not None and (record.get("source_visibility") or "users") != "users":
            user = auth.current_user(request)
            roles = set(auth.storage.get_user_roles(user_id=user.id)) if user else set()
            if not roles & MAINTAINER_ROLES:
                return S._error(404, "Shared radar source not found.")
        return await handler(request)

    return catalog_visibility


async def _recover_runs(app) -> None:
    catalog = open_catalog()
    if catalog is not None:
        ended = await S._blocking(reconcile_runs, catalog)
        if ended:
            print(f"[FrozenLegacies] marked interrupted index runs: {ended}")


# ── Control Center page ──────────────────────────────────────────────
_CONTROL_SCRIPT = r"""
(function () {
  const api = "/frozen-legacies/api/admin/sources";
  const $ = id => document.getElementById(id);
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"})[c]);
  const when = t => t ? new Date(t * 1000).toLocaleString() : "never";
  const n = v => Number(v || 0).toLocaleString();
  let config = null, timer = null;
  // Per-source messages and open problem lists survive the periodic card rebuild.
  const notices = {}, openProblems = new Set();

  const PROVIDER_LABELS = {s3: "Amazon S3 · read-only", local: "Local directory", cedar: "Georgia Tech CEDAR · NFS"};
  const fmtBytes = b => { let v = Number(b || 0), i = 0; const u = ["B", "KiB", "MiB", "GiB", "TiB"];
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; } return i ? `${v.toFixed(1)} ${u[i]}` : `${v} B`; };
  const openFiles = {};
  async function call(url, body, method = "POST") {
    const r = await fetch(url, {method, credentials: "same-origin",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || ("The request failed (HTTP " + r.status + ")."));
    return j;
  }
  const noticeHtml = (kind, html) => html ? `<p class="fl-notice ${kind}" role="${kind === "bad" ? "alert" : "status"}">${html}</p>` : "";
  function notice(target, kind, html) {
    const box = typeof target === "string" ? $(target) : target;
    box.innerHTML = noticeHtml(kind, html);
  }
  function sourceNotice(id, box, kind, html) {
    notices[id] = html ? [kind, html] : null;
    notice(box, kind, html);
  }

  const STATUS = {
    completed: ["Completed", "ok"], running: ["Indexing", "info"], queued: ["Queued", "info"],
    cancelled: ["Cancelled", "muted"], interrupted: ["Interrupted", "warn"],
    unavailable: ["Source unavailable", "bad"], needs_confirmation: ["Needs confirmation", "warn"],
    failed: ["Failed", "bad"]
  };
  const pill = (label, kind) => `<span class="status-pill ${kind}">${esc(label)}</span>`;
  const runPill = status => status ? pill(...(STATUS[status] || [status, "muted"])) : pill("Never indexed", "muted");

  function connection(s) {
    const c = s.connection || {};
    if (c.ok === null || c.ok === undefined) return `${pill("Not tested", "muted")}`;
    return `${c.ok ? pill("Connected", "ok") : pill("Failed", "bad")}<small>${esc(when(c.checked_at))}${c.message ? " · " + esc(c.message) : ""}</small>`;
  }

  function progress(s) {
    const p = s.progress;
    if (!p) return "";
    const done = p.discovered || 0, total = Math.max(p.known_total || 0, done);
    const pct = total && p.status === "running" ? Math.min(100, Math.round(100 * done / total)) : null;
    return `<div class="fl-card-section fl-progress" aria-live="polite">
      <div class="fl-progress-bar ${pct === null ? "indeterminate" : ""}"><span style="width:${pct ?? 0}%"></span></div>
      <small>${runPill(p.status)} ${p.cancel_requested ? " stopping after the current batch ·" : ""}
        ${n(done)} files listed${total ? " of about " + n(total) : ""} · ${n(p.added)} new · ${n(p.changed)} changed ·
        ${n(p.invalid)} invalid · ${n(p.unavailable)} unavailable · heartbeat ${esc(when(p.heartbeat_at))}</small></div>`;
  }

  function problems(s) {
    const items = [];
    if (s.last_index_error) items.push(`<li><strong>${esc((STATUS[s.last_index_status] || [s.last_index_status])[0])}:</strong> ${esc(s.last_index_error)}</li>`);
    (s.recent_errors || []).forEach(e => items.push(`<li><span class="fl-mono">${esc(e.filename)}</span> — ${esc(e.status)}: ${esc(e.error)}</li>`));
    if (!items.length) return "";
    return `<details class="fl-card-section" data-problems${openProblems.has(s.source_id) ? " open" : ""}><summary class="fl-section-label">Latest problems (${items.length})</summary>
      <ul class="fl-list">${items.join("")}</ul></details>`;
  }

  function actions(s) {
    const id = esc(s.source_id);
    const enabled = s.status === "enabled";
    const b = (act, label, kind = "") => `<button type="button" class="fl-btn ${kind}" data-act="${act}" data-id="${id}">${label}</button>`;
    if (s.indexing) return b("test", "Test connection") + b("cancel", "Cancel indexing", "danger");
    return [
      b("test", "Test connection"),
      enabled ? b("index", "Index changes", "primary") : "",
      enabled ? b("full", "Re-index all") : "",
      enabled && ((s.counts || {}).invalid || (s.counts || {}).unavailable) ? b("retry", "Retry failed files") : "",
      enabled && s.last_index_status === "needs_confirmation" ? b("confirm", "Confirm removals", "danger") : "",
      b(enabled ? "disable" : "enable", enabled ? "Disable" : "Enable", enabled ? "quiet" : ""),
      s.managed_intake && s.publication_status !== "published"
        ? ""
        : b("visibility", s.visibility === "maintainers" ? "Show to all users" : "Maintainers only", "quiet"),
      b("files", openFiles[s.source_id] ? "Hide files" : "Files"),
      b("remove", "Remove registration", "danger")
    ].join("");
  }

  function card(s) {
    const c = s.counts || {};
    const last = (s.runs || []).find(r => r.finished_at);
    const where = s.provider === "s3"
      ? `${esc(s.location)}<small>${esc(s.region || "default region")} · endpoint ${esc(s.endpoint)}</small>`
      : esc(s.location);
    return `<section class="panel fl-source" data-source="${esc(s.source_id)}">
      <div class="fl-card-head">
        <div class="fl-card-title"><h2>${esc(s.name)}</h2>
          ${s.status === "enabled" ? pill("Enabled", "ok") : pill("Disabled", "muted")}
          ${pill(PROVIDER_LABELS[s.provider] || s.provider, "info")}
          ${s.visibility === "maintainers" ? pill("Maintainers only", "warn") : pill("Visible to users", "muted")}
          ${s.managed_intake ? pill(s.publication_status === "published" ? "Published intake" : "Unpublished intake", "warn") : ""}
          <small class="fl-mono">${esc(s.source_id)}</small></div>
        <div class="fl-actions">${actions(s)}</div>
      </div>
      <div class="fl-kv-grid">
        <div class="fl-kv"><span>Dataset</span><strong>${esc(s.dataset_id)}</strong></div>
        <div class="fl-kv"><span>Location</span><strong>${where}</strong></div>
        <div class="fl-kv"><span>Connection</span><strong>${connection(s)}</strong></div>
        <div class="fl-kv"><span>Last successful index</span><strong>${esc(when(s.last_success_at))}</strong></div>
        <div class="fl-kv"><span>Last attempt</span><strong>${runPill(s.last_index_status)}</strong>
          <small>${esc(when(s.last_index_at))}${last ? ` · ${n(last.discovered)} listed, ${n(last.added)} added, ${n(last.changed)} changed, ${n(last.missing)} missing` : ""}</small></div>
      </div>
      <div class="fl-card-section"><div class="fl-chips">
        <span class="fl-chip"><strong>${n(c.indexed)}</strong> indexed</span>
        <span class="fl-chip"><strong>${n(c.invalid)}</strong> invalid</span>
        <span class="fl-chip"><strong>${n(c.unavailable)}</strong> unavailable</span>
        <span class="fl-chip"><strong>${n(c.missing)}</strong> missing</span>
        <span class="fl-chip"><strong>${n(c.moved)}</strong> moved</span>
        <span class="fl-chip"><strong>${n(c.duplicates)}</strong> duplicate names</span>
        <span class="fl-chip"><strong>${n(c.processed_by_anyone)}</strong> processed</span>
      </div></div>
      ${progress(s)}${problems(s)}
      <div class="fl-card-section" data-files="${esc(s.source_id)}" ${openFiles[s.source_id] ? "" : "hidden"}></div>
      <div class="fl-card-section" data-notice>${notices[s.source_id] ? noticeHtml(...notices[s.source_id]) : ""}</div>
    </section>`;
  }

  function metrics(sources) {
    const sum = k => sources.reduce((t, s) => t + ((s.counts || {})[k] || 0), 0);
    const running = sources.filter(s => s.indexing).length;
    const problem = sources.filter(s => ["failed", "unavailable", "interrupted", "needs_confirmation"].includes(s.last_index_status)
      || (s.connection || {}).ok === false).length;
    $("fl-metrics").innerHTML = [
      ["Data sources", n(sources.length), `${sources.filter(s => s.status === "enabled").length} enabled`],
      ["Indexed radar files", n(sum("indexed")), `${n(sum("invalid") + sum("unavailable"))} invalid or unavailable`],
      ["Indexing now", n(running), running ? "refreshing every 3 s" : "no active runs"],
      ["Needing attention", n(problem), problem ? "see the sources below" : "none"]
    ].map(([label, value, detail]) => `<div class="metric-card"><div class="metric-label">${label}</div>
      <div class="metric-value">${value}</div><div class="metric-detail">${detail}</div></div>`).join("");
  }

  function emptyState(j) {
    const ready = j.storage_roots_configured || j.s3.configured || (j.cloud || []).some(p => p.configured);
    return `<section class="panel"><div class="placeholder-state"><div>
      <div class="placeholder-icon">◎</div><h2>No data sources yet</h2>
      <p>${ready
        ? "Add a local directory or an approved S3 location below, test its connection, then index it. Indexing reads metadata only; files stay where they are."
        : "This server has no approved storage yet. An operator must set <code>CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS</code> (local or mounted directories) or <code>CRYOSTACK_FROZEN_LEGACIES_S3_ALLOWED</code> (read-only S3) before sources can be added."}</p>
    </div></div></section>`;
  }

  async function load() {
    clearTimeout(timer);
    let j;
    try {
      const r = await fetch(api, {credentials: "same-origin"});
      j = await r.json();
      if (!r.ok) throw new Error(j.error || "HTTP " + r.status);
    } catch (e) {
      notice("fl-sources", "bad", "The data sources could not be loaded: " + esc(e.message));
      timer = setTimeout(load, 15000);
      return;
    }
    config = j;
    metrics(j.sources);
    $("fl-sources").innerHTML = j.sources.length ? j.sources.map(card).join("") : emptyState(j);
    $("fl-sources").querySelectorAll("[data-act]").forEach(b => b.addEventListener("click", () => act(b)));
    $("fl-sources").querySelectorAll("details[data-problems]").forEach(d => d.addEventListener("toggle", () => {
      const id = d.closest(".fl-source").dataset.source;
      d.open ? openProblems.add(id) : openProblems.delete(id);
    }));
    setupForm(j);
    loadSessions();
    Object.keys(openFiles).forEach(id => showFiles(id));
    timer = setTimeout(load, j.sources.some(s => s.indexing) ? 3000 : 15000);
  }

  async function act(button) {
    const id = button.dataset.id, what = button.dataset.act;
    const box = button.closest(".fl-source").querySelector("[data-notice]");
    if (what === "confirm" && !confirm("Mark the files that are no longer listed as missing? Their catalog entries and all user work are kept."))
      return;
    if (what === "full" && !confirm("Re-read every file's header? This takes longer than indexing changes."))
      return;
    button.disabled = true;
    sourceNotice(id, box, "", "");
    try {
      if (what === "test") {
        const r = await call(`${api}/${id}/test`);
        sourceNotice(id, box, r.ok ? "ok" : "bad", esc(r.message));
      }
      if (what === "index" || what === "full") await call(`${api}/${id}/index`, {full: what === "full"});
      if (what === "retry") await call(`${api}/${id}/retry`);
      if (what === "cancel") await call(`${api}/${id}/cancel`);
      if (what === "confirm") await call(`${api}/${id}/index`, {allow_mass_missing: true});
      if (what === "disable" || what === "enable") await call(`${api}/${id}/status`, {status: what === "enable" ? "enabled" : "disabled"});
      if (what === "visibility") {
        const s = config.sources.find(x => x.source_id === id);
        await call(`${api}/${id}/visibility`, {visibility: s.visibility === "maintainers" ? "users" : "maintainers"});
      }
      if (what === "files") {
        if (openFiles[id]) delete openFiles[id]; else openFiles[id] = {page: 1, q: "", status: ""};
      }
      if (what === "remove") {
        const typed = prompt(`Remove the registration of "${id}"? Its catalog entries are removed; the files in the storage are NOT touched, and registering the same source ID again restores them. Type the source ID to confirm:`);
        if (typed === null) return;
        const reason = prompt("Reason (recorded in the audit log):", "") || "";
        const r = await call(`${api}/${id}`, {confirm: typed.trim(), reason}, "DELETE");
        delete openFiles[id];
        notice("fl-add-status", "ok", `Removed the registration of <code>${esc(id)}</code> (${n(r.catalog_rows)} catalog entries). The storage was not touched.`);
      }
      if (what !== "test") load();
    } catch (e) {
      sourceNotice(id, box, "bad", esc(e.message));
    } finally {
      button.disabled = false;
    }
  }

  // ── discovered files of one source ────────────────────────────
  async function showFiles(id) {
    const box = document.querySelector(`[data-files="${CSS.escape(id)}"]`);
    const st = openFiles[id];
    if (!box || !st) return;
    box.hidden = false;
    if (!box.dataset.ready) {
      box.dataset.ready = "1";
      box.innerHTML = `<div class="fl-files-bar"><input type="search" placeholder="Filter by file name" aria-label="Filter files of ${esc(id)}" value="${esc(st.q)}">
        <select aria-label="File status"><option value="">All statuses</option>${["indexed","invalid","unavailable","missing","moved","changed"].map(x => `<option value="${x}" ${st.status === x ? "selected" : ""}>${x}</option>`).join("")}</select></div>
        <div class="fl-files-table" aria-live="polite"><p class="panel-empty">Loading files…</p></div>
        <div class="fl-files-pager"></div>`;
      const [q, status] = [box.querySelector("input"), box.querySelector("select")];
      let t = null;
      q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { st.q = q.value.trim(); st.page = 1; showFiles(id); }, 300); });
      status.addEventListener("change", () => { st.status = status.value; st.page = 1; showFiles(id); });
    }
    const params = new URLSearchParams({page: st.page, page_size: 25});
    if (st.q) params.set("q", st.q);
    if (st.status) params.set("status", st.status);
    try {
      const r = await fetch(`${api}/${encodeURIComponent(id)}/files?${params}`, {credentials: "same-origin"});
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "HTTP " + r.status);
      box.querySelector(".fl-files-table").innerHTML = j.items.length ? `<div class="fl-scroll"><table class="data-table"><thead><tr>
        <th>File</th><th>Folder</th><th>Size</th><th>Modified</th><th>Flight · CBD (file name)</th><th>Status</th><th>Cache</th></tr></thead><tbody>${j.items.map(f => {
          const parts = f.key.split("/"); parts.pop();
          return `<tr><td class="fl-mono">${esc(f.filename)}</td><td class="fl-mono">${esc(parts.join("/") || "—")}</td><td>${esc(fmtBytes(f.bytes))}</td>
          <td>${esc(new Date(f.mtime_ns / 1e6).toLocaleString())}</td>
          <td>${f.flight ? "F" + esc(f.flight) : "—"}${f.cbd_start != null ? ` · ${esc(f.cbd_start)}–${esc(f.cbd_end)} <small>(from the name; not verified on the film)</small>` : ""}</td>
          <td>${esc(f.status)}${f.error ? `<br><small>${esc(f.error)}</small>` : ""}${f.duplicate ? " <small>(duplicate name)</small>" : ""}</td><td>${esc(f.cache)}</td></tr>`; }).join("")}</tbody></table></div>`
        : `<p class="panel-empty">No files match.</p>`;
      box.querySelector(".fl-files-pager").innerHTML = `<small>${n(j.total)} files · page ${j.page} of ${j.pages}</small>
        <button type="button" class="fl-btn" data-page="-1" ${j.page <= 1 ? "disabled" : ""}>Previous</button>
        <button type="button" class="fl-btn" data-page="1" ${j.page >= j.pages ? "disabled" : ""}>Next</button>`;
      box.querySelectorAll("[data-page]").forEach(b => b.addEventListener("click", () => { st.page += Number(b.dataset.page); showFiles(id); }));
    } catch (e) {
      box.querySelector(".fl-files-table").innerHTML = noticeHtml("bad", "The files could not be loaded: " + esc(e.message));
    }
  }

  // ── add-source form ───────────────────────────────────────────
  const intakeForm = $("fl-curator-intake");
  const intakeSessionKey = "cryostack:frozen-legacies:intake-session:v1";
  let intakeAbort = null;
  const hex = buffer => [...new Uint8Array(buffer)].map(byte => byte.toString(16).padStart(2, "0")).join("");
  async function chunkDigest(blob) {
    return hex(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()));
  }
  function savedIntake() {
    try { return JSON.parse(localStorage.getItem(intakeSessionKey) || "null"); }
    catch (_) { return null; }
  }
  function rememberIntake(value) {
    if (value) localStorage.setItem(intakeSessionKey, JSON.stringify(value));
    else localStorage.removeItem(intakeSessionKey);
  }
  async function resumableIntake(form, status) {
    const files = [...form.elements.files.files];
    if (!files.length) throw new Error("Select at least one TIFF, CSV, or ZIP file.");
    const signature = files.map(file => `${file.name}:${file.size}:${file.lastModified}`).join("|");
    const metadata = {
      source_id: form.elements.source_id.value.trim(), name: form.elements.name.value.trim(),
      dataset_id: form.elements.dataset_id.value.trim(),
      nav_template: form.elements.nav_template.value.trim(), signature
    };
    let saved = savedIntake(), session;
    if (saved && saved.signature === signature && saved.source_id === metadata.source_id) {
      const response = await fetch(`/frozen-legacies/api/admin/intake-sessions/${encodeURIComponent(saved.session_id)}`,
        {credentials: "same-origin"});
      if (response.ok) session = await response.json(); else rememberIntake(null);
    }
    if (!session || session.state !== "open") {
      session = await call("/frozen-legacies/api/admin/intake-sessions", {
        ...metadata, files: files.map(file => ({name: file.name, bytes: file.size}))
      });
      rememberIntake({...metadata, session_id: session.session_id});
    }
    intakeAbort = new AbortController();
    const total = files.reduce((sum, file) => sum + file.size, 0);
    let sent = Number(session.received_bytes || 0);
    status.innerHTML = `<div class="fl-progress"><div class="fl-progress-bar"><span></span></div>
      <small data-intake-progress role="status"></small>
      <button type="button" class="fl-btn danger" data-intake-cancel>Cancel upload</button></div>`;
    const bar = status.querySelector(".fl-progress-bar span"), label = status.querySelector("[data-intake-progress]");
    const update = () => { const pct = total ? Math.min(100, Math.round(100 * sent / total)) : 100;
      bar.style.width = `${pct}%`; label.textContent = `${pct}% · ${fmtBytes(sent)} of ${fmtBytes(total)} safely received`; };
    status.querySelector("[data-intake-cancel]").addEventListener("click", async () => {
      intakeAbort.abort();
      try { await call(`/frozen-legacies/api/admin/intake-sessions/${session.session_id}/cancel`); }
      finally { rememberIntake(null); }
    });
    update();
    const remoteFiles = new Map((session.files || []).map(file => [Number(file.file_id), file]));
    for (let fileId = 0; fileId < files.length; fileId++) {
      const file = files[fileId], already = Number(remoteFiles.get(fileId)?.received_bytes || 0);
      for (let offset = already, index = Math.floor(already / session.chunk_bytes); offset < file.size;
           offset += session.chunk_bytes, index++) {
        const blob = file.slice(offset, Math.min(file.size, offset + session.chunk_bytes));
        const digest = await chunkDigest(blob);
        const response = await fetch(`/frozen-legacies/api/admin/intake-sessions/${session.session_id}/files/${fileId}/chunks/${index}`,
          {method: "PUT", credentials: "same-origin", signal: intakeAbort.signal,
           headers: {"Content-Type": "application/octet-stream", "X-Chunk-SHA256": digest}, body: blob});
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || `Chunk upload failed (HTTP ${response.status}).`);
        sent = Number(result.received_bytes || sent + blob.size); update();
      }
    }
    label.textContent = "Checksums verified; safely staging the scientific intake…";
    const result = await call(`/frozen-legacies/api/admin/intake-sessions/${session.session_id}/finalize`);
    rememberIntake(null); intakeAbort = null;
    return result;
  }
  if (intakeForm) intakeForm.addEventListener("submit", async e => {
    e.preventDefault();
    const status = $("fl-intake-status"), submit = intakeForm.querySelector('button[type="submit"]');
    notice(status, "", ""); submit.disabled = true;
    try {
      const result = await resumableIntake(intakeForm, status);
      intakeForm.reset();
      notice(status, "ok", `<strong>${esc(result.source.name)}</strong> was staged with ${n(result.receipt.items.length)} unverified files. Test and index it below; publish only after review.`);
      await load();
    } catch (error) { notice(status, "bad", esc(error.message)); }
    finally { submit.disabled = false; }
  });

  // Durable upload-session recovery and reclamation. The server applies the
  // owner/admin boundary; every deletion follows a server dry run and an
  // explicit, session-specific confirmation.
  let expirePreview = null;
  const sessionApi = "/frozen-legacies/api/admin/intake-sessions";
  function sessionState(state) {
    const labels = {open: ["Active", "info"], expired: ["Expired", "warn"],
      cancelled: ["Cancelled", "muted"], assembling: ["Assembling", "info"],
      committing: ["Registering", "info"], finalized: ["Finalized", "ok"], failed: ["Failed", "bad"]};
    return pill(...(labels[state] || [state || "Unknown", "muted"]));
  }
  function renderSessions(sessions) {
    const box = $("fl-intake-sessions");
    if (!sessions.length) {
      box.innerHTML = '<p class="panel-empty">No recoverable upload sessions are visible to you.</p>';
      return;
    }
    box.innerHTML = `<div class="fl-scroll"><table class="data-table"><thead><tr>
      <th>Intake</th><th>Status</th><th>Progress</th><th>Last activity</th><th>Recovery</th></tr></thead><tbody>
      ${sessions.map(s => { const total = Number(s.expected_bytes || 0), received = Number(s.received_bytes || 0);
        const pct = total ? Math.min(100, Math.round(100 * received / total)) : 100;
        const action = s.state === "expired"
          ? `<button type="button" class="fl-btn danger" data-clean-session="${esc(s.session_id)}">Check reclaim</button>`
          : s.state === "open" ? "Re-select the same files above to resume." : "No cleanup action available.";
        return `<tr><td><strong>${esc(s.name || s.source_id)}</strong><br><small class="fl-mono">${esc(s.session_id)}</small></td>
          <td>${sessionState(s.state)}</td><td><strong>${pct}%</strong><br><small>${esc(fmtBytes(received))} of ${esc(fmtBytes(total))}</small></td>
          <td>${esc(when(s.updated_at))}</td><td>${action}</td></tr>`; }).join("")}</tbody></table></div>`;
    box.querySelectorAll("[data-clean-session]").forEach(button => button.addEventListener("click", () => previewCleanup(button)));
  }
  async function loadSessions() {
    const box = $("fl-intake-sessions");
    if (!box || $("fl-intake-panel").hidden) return;
    try {
      const response = await fetch(sessionApi, {credentials: "same-origin"});
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
      renderSessions(result.sessions || []);
    } catch (error) { box.innerHTML = noticeHtml("bad", "Upload sessions could not be loaded: " + esc(error.message)); }
  }
  async function previewExpiry() {
    const status = $("fl-session-status"), confirmButton = $("fl-confirm-expiry");
    confirmButton.hidden = true; expirePreview = null;
    try {
      const result = await call(`${sessionApi}/expire`, {});
      expirePreview = result;
      notice(status, result.eligible ? "warn" : "ok", result.eligible
        ? `<strong>${n(result.eligible)} stale active session(s)</strong> can be marked expired, reserving ${esc(fmtBytes(result.reclaimable_bytes))}. No bytes have been removed.`
        : "No stale active sessions are eligible for expiry.");
      confirmButton.textContent = `Mark ${n(result.eligible)} session(s) expired`;
      confirmButton.hidden = !result.eligible;
    } catch (error) { notice(status, "bad", esc(error.message)); }
  }
  async function confirmExpiry() {
    if (!expirePreview || !expirePreview.eligible || !confirm("Mark the stale upload sessions shown by the dry run as expired? They remain recoverable during the grace period; this does not delete bytes.")) return;
    const result = await call(`${sessionApi}/expire`, {confirm: "expire"});
    notice("fl-session-status", "ok", `${n(result.marked_expired)} session(s) were marked expired. No bytes were deleted.`);
    $("fl-confirm-expiry").hidden = true; expirePreview = null; await loadSessions();
  }
  async function previewCleanup(button) {
    const sid = button.dataset.cleanSession, status = $("fl-session-status");
    button.disabled = true;
    try {
      const preview = await call(`${sessionApi}/${encodeURIComponent(sid)}/cleanup`, {});
      notice(status, "warn", `<strong>Dry run only:</strong> ${esc(fmtBytes(preview.reclaimed_bytes))} can be reclaimed from <code>${esc(sid)}</code>. No files have been deleted.`);
      if (!confirm(`Permanently delete expired upload session ${sid} and reclaim ${fmtBytes(preview.reclaimed_bytes)}? Published or finalized source data is not affected.`)) return;
      const result = await call(`${sessionApi}/${encodeURIComponent(sid)}/cleanup`, {confirm: sid});
      notice(status, "ok", `${esc(fmtBytes(result.reclaimed_bytes))} was reclaimed from the expired upload session.`);
      await loadSessions();
    } catch (error) { notice(status, "bad", esc(error.message)); }
    finally { button.disabled = false; }
  }
  $("fl-refresh-sessions")?.addEventListener("click", loadSessions);
  $("fl-preview-expiry")?.addEventListener("click", previewExpiry);
  $("fl-confirm-expiry")?.addEventListener("click", confirmExpiry);

  const form = $("fl-add-source");
  let formReady = false;
  function setupForm(j) {
    $("fl-intake-panel").hidden = !(j.managed_intake || {}).configured;
    $("fl-intake-sessions-panel").hidden = !(j.managed_intake || {}).configured;
    const s3 = form.querySelector('input[name="provider"][value="s3"]');
    s3.disabled = !j.s3.configured;
    $("fl-s3-note").innerHTML = j.s3.configured
      ? `Approved locations: ${j.s3.approved.map(a => `<code>${esc(a)}</code>`).join(" ")}`
      : "No S3 locations are approved on this server (<code>CRYOSTACK_FROZEN_LEGACIES_S3_ALLOWED</code>).";
    const local = form.querySelector('input[name="provider"][value="local"]');
    local.disabled = !j.storage_roots_configured;
    form.querySelector('input[name="provider"][value="cedar"]').disabled = !j.storage_roots_configured;
    const labels = {gdrive: "Google Drive", onedrive: "OneDrive / SharePoint", dropbox: "Dropbox"};
    (j.cloud || []).forEach(p => {
      const input = form.querySelector(`input[name="provider"][value="${p.provider}"]`);
      if (input) input.disabled = !p.configured;
    });
    $("fl-planned-note").innerHTML = (j.cloud || []).map(p => p.configured
      ? `<strong>${labels[p.provider]}</strong>: ready · ${n(p.approved.length)} approved location${p.approved.length === 1 ? "" : "s"}`
      : `<strong>${labels[p.provider]}</strong>: connect once to enable (${esc(p.missing.join("; "))})`).join(" · ");
    $("fl-local-note").textContent = j.storage_roots_configured
      ? `The directory must be inside one of this server's ${j.storage_root_count} approved storage root${j.storage_root_count === 1 ? "" : "s"}.`
      : "No local storage roots are approved on this server (CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS).";
    const endpoint = form.elements.endpoint;
    const current = endpoint.value;
    endpoint.innerHTML = `<option value="">AWS S3 (default)</option>` + j.s3.endpoints.map(e => `<option value="${esc(e)}">${esc(e)}</option>`).join("");
    endpoint.value = current;
    $("fl-datasets").innerHTML = j.datasets.map(d => `<option value="${esc(d.id)}">${esc(d.name)}</option>`).join("");
    if (!formReady) {
      formReady = true;
      const first = [...form.querySelectorAll('input[name="provider"]')].find(i => !i.disabled);
      if (first) first.checked = true;
      showProvider();
    }
    $("fl-add-panel").hidden = !(j.storage_roots_configured || j.s3.configured || (j.cloud || []).some(p => p.configured));
  }
  function provider() { return (form.querySelector('input[name="provider"]:checked') || {}).value; }
  function showProvider() {
    const p = provider();
    form.querySelectorAll("[data-provider]").forEach(el => {
      // a CEDAR mount is configured like a local directory
      const on = el.dataset.provider === (p === "cedar" ? "local" : p);
      el.hidden = !on;
      el.querySelectorAll("input,select").forEach(i => { i.disabled = !on; });
    });
  }
  form.querySelectorAll('input[name="provider"]').forEach(i => i.addEventListener("change", showProvider));

  const RULES = {
    source_id: v => /^[a-z0-9][a-z0-9-]{1,62}$/.test(v) || "2–63 lowercase letters, digits and hyphens, starting with a letter or digit.",
    name: v => v.trim().length > 0 || "Give the source a name.",
    dataset_id: v => /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(v) || "A dataset ID such as frozen-legacies-ascope (letters, digits, '.', '_', '-').",
    root: v => v.trim().startsWith("/") || "An absolute directory on this server.",
    bucket: v => /^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/.test(v) || "A valid S3 bucket name (lowercase).",
    drive_id: v => /^[A-Za-z0-9!_-]{1,128}$/.test(v) || "Enter an approved drive or namespace ID.",
    folder_id: v => /^[A-Za-z0-9!_-]{1,128}$/.test(v) || "Enter the Google Drive folder ID.",
    region: v => !v || /^[a-z]{2}(-[a-z]+)+-\d$/.test(v) || "An AWS region such as us-east-1.",
    nav_template: v => !v || v.includes("{flight}") || "Must contain {flight}, e.g. nav/{flight}.csv."
  };
  function validate() {
    let ok = true;
    form.querySelectorAll("[data-rule]").forEach(input => {
      const error = input.closest(".fl-field").querySelector(".fl-field-error");
      const result = input.disabled ? true : RULES[input.dataset.rule](input.value.trim());
      const message = result === true ? "" : result;
      input.setAttribute("aria-invalid", message ? "true" : "false");
      error.textContent = message;
      error.hidden = !message;
      if (message) ok = false;
    });
    return ok;
  }
  form.addEventListener("input", e => { if (e.target.getAttribute("aria-invalid") === "true") validate(); });
  form.addEventListener("submit", async e => {
    e.preventDefault();
    notice("fl-add-status", "", "");
    if (!validate()) {
      notice("fl-add-status", "bad", "Check the highlighted fields.");
      return;
    }
    const data = Object.fromEntries([...new FormData(form).entries()].map(([k, v]) => [k, String(v).trim()]));
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      const added = await call(api, data);
      form.reset(); formReady = false;
      notice("fl-add-status", "ok", `<strong>${esc(added.name)}</strong> was added. Test its connection, then select <strong>Index changes</strong>.`);
      await load();
    } catch (err) {
      notice("fl-add-status", "bad", esc(err.message));
    } finally {
      submit.disabled = false;
    }
  });
  load();
})();
"""


def _control_heading(title: str, subtitle: str, link: str) -> str:
    return f"""
    <div class="page-heading-row">
      <div>
        <h1>{title}</h1>
        <p class="page-subtitle">{subtitle}</p>
      </div>
      {link}
    </div>"""


async def control_page(request: web.Request) -> web.Response:
    from control_center.templates import control_layout
    from .control_style import STYLE

    content = _control_heading(
        "Frozen Legacies data sources",
        "External radar storage indexed into the Frozen Legacies radar catalog. Files stay in "
        "their storage and are only read; the catalog holds metadata and can be rebuilt by "
        "indexing.",
        '<a class="small-button" href="/control/storage">Storage &amp; quotas →</a> '
        '<a class="small-button" href="/control/frozen-legacies/review">Scientific review →</a>') + """
    <div class="metric-grid" id="fl-metrics"></div>
    <section class="panel" id="fl-intake-panel">
      <div class="panel-header">New scientific intake</div>
      <form id="fl-curator-intake" class="fl-form" enctype="multipart/form-data">
        <p class="fl-notice info">Uploaded material starts <strong>unpublished and visible only to maintainers</strong>.
          TIFF headers and navigation associations are checked during indexing; inferred coordinates or observations are never created.</p>
        <div class="fl-fields three">
          <label class="fl-field">Source ID<input name="source_id" required pattern="[a-z0-9][a-z0-9-]{1,62}" placeholder="film-intake-127"></label>
          <label class="fl-field">Name<input name="name" required placeholder="Flight 127 film intake"></label>
          <label class="fl-field">Dataset<input name="dataset_id" required pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,127}" placeholder="frozen-legacies-ascope"></label>
          <label class="fl-field wide">TIFFs, navigation CSVs, or ZIP archives
            <input name="files" type="file" multiple required accept=".tif,.tiff,.csv,.zip">
            <span class="fl-help">Uploads are checksum-verified in resumable chunks. Re-select the same files after a network interruption or reload to continue. Archives are inspected for traversal, links, duplicate names and unsafe expansion.</span></label>
          <label class="fl-field">Navigation naming template
            <input name="nav_template" value="nav/{flight}.csv">
            <span class="fl-help">No coordinates are inferred when a matching file is absent.</span></label>
        </div>
        <div class="fl-actions"><button type="submit" class="fl-btn primary">Upload, validate, and stage intake</button>
          <span class="fl-help">After staging, use Test connection → Index changes → inspect failures. Indexing never publishes an intake.</span></div>
        <div id="fl-intake-status"></div>
      </form>
    </section>
    <section class="panel" id="fl-intake-sessions-panel" hidden>
      <div class="panel-header">Upload recovery and cleanup</div>
      <div class="fl-form">
        <p class="fl-notice info">Resume an active upload by re-selecting its original files above. You see only your sessions; CryoStack owners and administrators can inspect all sessions. Cleanup never removes a finalized intake or published source data.</p>
        <div class="fl-actions">
          <button type="button" class="fl-btn" id="fl-refresh-sessions">Refresh sessions</button>
          <button type="button" class="fl-btn" id="fl-preview-expiry">Find stale sessions</button>
          <button type="button" class="fl-btn danger" id="fl-confirm-expiry" hidden>Mark sessions expired</button>
          <span class="fl-help">Finding stale sessions is a dry run. Marking them expired preserves a recovery grace period before any bytes can be reclaimed.</span>
        </div>
        <div id="fl-session-status" aria-live="polite"></div>
        <div id="fl-intake-sessions" aria-live="polite"><p class="panel-empty">Loading upload sessions…</p></div>
      </div>
    </section>
    <div id="fl-sources"><section class="panel"><p class="panel-empty">Loading data sources…</p></section></div>
    <section class="panel" id="fl-add-panel" hidden>
      <div class="panel-header">Add a data source</div>
      <form id="fl-add-source" class="fl-form" novalidate>
        <fieldset class="fl-fieldset">
          <legend>Storage</legend>
          <div class="fl-choice" role="radiogroup" aria-label="Storage provider">
            <label><input type="radio" name="provider" value="local">
              <strong>Local or mounted directory</strong>
              <span>A directory on this server, for example a mounted archive.</span></label>
            <label><input type="radio" name="provider" value="cedar">
              <strong>Georgia Tech CEDAR · read-only</strong>
              <span>CEDAR research storage mounted on this server (NFS), inside an approved storage root.</span></label>
            <label><input type="radio" name="provider" value="s3">
              <strong>Amazon S3 · read-only</strong>
              <span>A bucket prefix read with the server's own AWS credentials, or an approved S3-compatible endpoint.</span></label>
            <label><input type="radio" name="provider" value="gdrive">
              <strong>Google Drive · read-only</strong>
              <span>An approved shared-drive folder read with the server workload identity.</span></label>
            <label><input type="radio" name="provider" value="onedrive">
              <strong>OneDrive / SharePoint · read-only</strong>
              <span>An approved Microsoft drive read with the server's Entra application.</span></label>
            <label><input type="radio" name="provider" value="dropbox">
              <strong>Dropbox · read-only</strong>
              <span>An approved team namespace read with the server-held refresh credential.</span></label>
          </div>
          <p class="fl-help" id="fl-planned-note"></p>
        </fieldset>
        <fieldset class="fl-fieldset">
          <legend>Identity</legend>
          <div class="fl-fields three">
            <label class="fl-field">Source ID
              <input name="source_id" data-rule="source_id" required autocomplete="off" placeholder="fl-archive">
              <span class="fl-help">Permanent; part of every catalog ID. Lowercase letters, digits, hyphens.</span>
              <span class="fl-field-error" hidden></span></label>
            <label class="fl-field">Name
              <input name="name" data-rule="name" required placeholder="Frozen Legacies film archive">
              <span class="fl-help">Shown to maintainers and in catalog listings.</span>
              <span class="fl-field-error" hidden></span></label>
            <label class="fl-field">Dataset
              <input name="dataset_id" data-rule="dataset_id" required list="fl-datasets" autocomplete="off" placeholder="frozen-legacies-ascope">
              <datalist id="fl-datasets"></datalist>
              <span class="fl-help">The scientific collection these radar files belong to.</span>
              <span class="fl-field-error" hidden></span></label>
            <label class="fl-field">Visibility
              <select name="visibility">
                <option value="users">All signed-in users</option>
                <option value="maintainers">Maintainers only</option>
              </select>
              <span class="fl-help">Who can find and open these files in the radar workspace.</span>
              <span class="fl-field-error" hidden></span></label>
          </div>
        </fieldset>
        <fieldset class="fl-fieldset" data-provider="local">
          <legend>Location</legend>
          <div class="fl-fields">
            <label class="fl-field wide">Directory
              <input name="root" data-rule="root" required placeholder="/data/frozen-legacies">
              <span class="fl-help" id="fl-local-note"></span>
              <span class="fl-field-error" hidden></span></label>
          </div>
        </fieldset>
        <fieldset class="fl-fieldset" data-provider="s3" hidden>
          <legend>Location</legend>
          <div class="fl-fields">
            <label class="fl-field">Bucket
              <input name="bucket" data-rule="bucket" required autocomplete="off" placeholder="example-radar-archive">
              <span class="fl-field-error" hidden></span></label>
            <label class="fl-field">Prefix
              <input name="prefix" autocomplete="off" placeholder="frozen-legacies">
              <span class="fl-help">Optional folder inside the bucket.</span></label>
            <label class="fl-field">Region
              <input name="region" data-rule="region" autocomplete="off" placeholder="us-east-1">
              <span class="fl-help">Optional; the server's default region otherwise.</span>
              <span class="fl-field-error" hidden></span></label>
            <label class="fl-field">Endpoint
              <select name="endpoint"><option value="">AWS S3 (default)</option></select>
              <span class="fl-help">Only endpoints approved by the operator are offered.</span></label>
            <p class="fl-help fl-field wide" id="fl-s3-note"></p>
            <p class="fl-notice info fl-field wide">The server reads S3 with its own AWS credentials (IAM role or the
              default credential chain) and read-only permissions. <strong>Never enter access keys here</strong>; requests
              containing credentials are refused.</p>
          </div>
        </fieldset>
        <fieldset class="fl-fieldset" data-provider="gdrive" hidden>
          <legend>Google Drive location</legend>
          <div class="fl-fields">
            <label class="fl-field">Shared drive ID
              <input name="drive_id" data-rule="drive_id" required autocomplete="off">
              <span class="fl-help">Must be present in the operator allow-list.</span><span class="fl-field-error" hidden></span></label>
            <label class="fl-field">Folder ID
              <input name="folder_id" data-rule="folder_id" required autocomplete="off">
              <span class="fl-field-error" hidden></span></label>
          </div>
        </fieldset>
        <fieldset class="fl-fieldset" data-provider="onedrive" hidden>
          <legend>OneDrive / SharePoint location</legend>
          <div class="fl-fields">
            <label class="fl-field">Drive ID
              <input name="drive_id" data-rule="drive_id" required autocomplete="off">
              <span class="fl-help">Must be present in the operator allow-list.</span><span class="fl-field-error" hidden></span></label>
            <label class="fl-field">Folder path
              <input name="folder" autocomplete="off" placeholder="radar/frozen-legacies"></label>
          </div>
        </fieldset>
        <fieldset class="fl-fieldset" data-provider="dropbox" hidden>
          <legend>Dropbox team location</legend>
          <div class="fl-fields">
            <label class="fl-field">Namespace ID
              <input name="drive_id" data-rule="drive_id" required autocomplete="off">
              <span class="fl-help">Must be present in the operator allow-list.</span><span class="fl-field-error" hidden></span></label>
            <label class="fl-field">Folder path
              <input name="folder" autocomplete="off" placeholder="radar/frozen-legacies"></label>
          </div>
        </fieldset>
        <fieldset class="fl-fieldset">
          <legend>Layout (optional)</legend>
          <div class="fl-fields">
            <label class="fl-field">TIFF folder
              <input name="tiff_prefix" autocomplete="off" placeholder="tiff">
              <span class="fl-help">Folder inside the location that holds the radar TIFFs; empty for the whole location.</span></label>
            <label class="fl-field">Navigation template
              <input name="nav_template" data-rule="nav_template" autocomplete="off" placeholder="nav/{flight}.csv">
              <span class="fl-help">Where each flight's navigation CSV is; <code>{flight}</code> is replaced by the flight number.</span>
              <span class="fl-field-error" hidden></span></label>
          </div>
        </fieldset>
        <div class="fl-actions">
          <button type="submit" class="fl-btn primary">Add data source</button>
          <span class="fl-help">Indexing starts only when you select it; it runs in the background.</span>
        </div>
        <div id="fl-add-status"></div>
      </form>
    </section>
    <style>""" + STYLE + """
      .fl-source .fl-kv > strong { display: flex; flex-wrap: wrap; gap: 0.35rem; align-items: center; }
      .fl-source details summary { cursor: pointer; margin: 0; }
      .fl-source [data-notice]:empty { display: none; }
      .fl-files-bar { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.5rem; }
      .fl-files-pager { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; margin-top: 0.5rem; }
      .fl-scroll { overflow-x: auto; }
    </style>
    <script>""" + _CONTROL_SCRIPT + """</script>"""
    return web.Response(text=control_layout(title="Frozen Legacies", active="frozen-legacies",
                                            content=content),
                        content_type="text/html")


def install_catalog_routes(app: web.Application, *, auth) -> None:
    app[INDEX_WORKERS_KEY] = {}
    app[AUTH_KEY] = auth
    app.middlewares.append(make_visibility_middleware(auth))
    app.on_startup.append(_recover_runs)
    app.on_startup.append(_recover_intake_sessions)
    # automatic-job status changes update the user's state index
    app[S.AUTOMATIC_KEY].on_change = record_state_by_id
    # observation writes keep the indexed My picks current
    obs.on_change = index_observations
    api = "/frozen-legacies/api"
    app.router.add_get(f"{api}/radar/explorer", S._api(auth, api_catalog_explorer))
    app.router.add_get(f"{api}/radar/catalog/observation-preview",
                       S._api(auth, api_catalog_observation_preview))
    app.router.add_get(f"{api}/radar/catalog", S._api(auth, api_catalog_search))
    app.router.add_get(f"{api}/radar/catalog/summary", S._api(auth, api_catalog_summary))
    app.router.add_get(f"{api}/radar/catalog/segments", S._api(auth, api_catalog_segments))
    app.router.add_get(f"{api}/observations", S._api(auth, api_observations))
    source = "{source_id:[a-z0-9][a-z0-9-]{1,62}}"
    app.router.add_get(f"{api}/admin/sources", _maintainer(auth, api_admin_sources))
    app.router.add_post(f"{api}/admin/sources", _maintainer(auth, api_admin_add_source))
    app.router.add_post(f"{api}/admin/intakes", _maintainer(auth, api_admin_create_intake))
    session = "{session_id:in-[a-f0-9]{32}}"
    app.router.add_post(f"{api}/admin/intake-sessions",
                        _maintainer(auth, api_admin_create_upload_session))
    app.router.add_get(f"{api}/admin/intake-sessions",
                       _maintainer(auth, api_admin_upload_session_inventory))
    app.router.add_post(f"{api}/admin/intake-sessions/expire",
                        _maintainer(auth, api_admin_expire_upload_sessions))
    app.router.add_get(f"{api}/admin/intake-sessions/{session}",
                       _maintainer(auth, api_admin_upload_session_status))
    app.router.add_put(
        f"{api}/admin/intake-sessions/{session}/files/{{file_id:[0-9]+}}/chunks/{{chunk_index:[0-9]+}}",
        _maintainer(auth, api_admin_upload_session_chunk))
    app.router.add_post(f"{api}/admin/intake-sessions/{session}/cancel",
                        _maintainer(auth, api_admin_cancel_upload_session))
    app.router.add_post(f"{api}/admin/intake-sessions/{session}/cleanup",
                        _maintainer(auth, api_admin_cleanup_upload_session))
    app.router.add_post(f"{api}/admin/intake-sessions/{session}/finalize",
                        _maintainer(auth, api_admin_finalize_upload_session))
    app.router.add_post(f"{api}/admin/sources/{source}/test",
                        _maintainer(auth, api_admin_test_source))
    app.router.add_post(f"{api}/admin/sources/{source}/index",
                        _maintainer(auth, api_admin_index_source))
    app.router.add_post(f"{api}/admin/sources/{source}/retry",
                        _maintainer(auth, api_admin_retry_source))
    app.router.add_post(f"{api}/admin/sources/{source}/cancel",
                        _maintainer(auth, api_admin_cancel_index))
    app.router.add_post(f"{api}/admin/sources/{source}/status",
                        _maintainer(auth, api_admin_source_status))
    app.router.add_post(f"{api}/admin/sources/{source}/visibility",
                        _maintainer(auth, api_admin_source_visibility))
    app.router.add_delete(f"{api}/admin/sources/{source}", _maintainer(auth, api_admin_remove_source))
    app.router.add_get(f"{api}/admin/sources/{source}/files",
                       _maintainer(auth, api_admin_source_files))
    app.router.add_get(f"{api}/radar/catalog/sources", S._api(auth, api_catalog_sources))
    control_access = auth.require_roles("maintainer", "admin", "owner")
    app.router.add_get("/control/frozen-legacies", control_access(control_page))

    from .review_routes import install_review_routes
    install_review_routes(app, auth=auth, maintainer=_maintainer)

    # CBD provenance / georeferencing of the user's A-scopes (owner-scoped)
    from .georef_routes import install_georef_routes
    install_georef_routes(app, auth=auth)

    # workspace quotas, usage and storage settings
    from .storage_routes import install_storage_routes
    install_storage_routes(app, auth=auth)
