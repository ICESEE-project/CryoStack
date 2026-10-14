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
import sys
import threading
from pathlib import Path

from aiohttp import web

from . import server as S
from .radar import automatic
from .radar import observations as obs
from .radar.assets import list_manifests, read_manifest
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
)
from .radar.storage import (
    PROVIDERS,
    StorageError,
    StorageKeyError,
    approved_roots,
    mask_location,
    normalize_key,
    provider_for,
    s3_approvals,
    s3_endpoint_names,
    validate_s3_config,
)


MAINTAINER_ROLES = frozenset({"maintainer", "admin", "owner"})
INDEX_WORKERS_KEY = "frozen_legacies_index_workers"
WORKER_MODULE = f"{__package__}.radar.index_worker"
REPO_ROOT = Path(__file__).resolve().parents[3]
#: a running worker writes a heartbeat every few seconds
STALE_RUN_S = 90.0
_CREDENTIAL_WORDS = ("secret", "token", "password", "credential", "session", "access_key",
                     "accesskey", "api_key", "apikey")
OBSERVATION_LIMIT = 20_000
SEGMENT_LIMIT = 5_000


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
    }
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
        return annotate_stages(workspace, query_observations(
            workspace, S.load_sources(), bbox=bbox, status=status, asset_id=asset_id,
            limit=limit))

    return S._json(await S._blocking(query))


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
    return mask_location(config.get("root") or "")


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
    return {
        "source_id": source["source_id"], "name": source["name"],
        "provider": source["provider"], "dataset_id": source["dataset_id"],
        "status": source["status"],
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
    return S._json({
        "sources": sources, "providers": list(PROVIDERS),
        "storage_roots_configured": bool(approved_roots()),
        "storage_root_count": len(approved_roots()),
        # approved S3 locations and endpoint *names* (never their URLs)
        "s3": {"configured": bool(allowed),
               "approved": [f"s3://{b}/{p}".rstrip("/") for b, p in allowed],
               "endpoints": sorted(s3_endpoint_names())},
        "datasets": _dataset_choices(sources),
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
    return S._json(public_source(source), status=201)


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
    await S._blocking(catalog.set_source_status, source["source_id"],
                      (payload or {}).get("status"))
    return S._json(public_source(catalog.get_source(source["source_id"])))


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

  async function call(url, body) {
    const r = await fetch(url, {method: "POST", credentials: "same-origin",
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
      b(enabled ? "disable" : "enable", enabled ? "Disable" : "Enable", enabled ? "quiet" : "")
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
          ${pill(s.provider === "s3" ? "Amazon S3 · read-only" : "Local directory", "info")}
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
    const ready = j.storage_roots_configured || j.s3.configured;
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
      if (what !== "test") load();
    } catch (e) {
      sourceNotice(id, box, "bad", esc(e.message));
    } finally {
      button.disabled = false;
    }
  }

  // ── add-source form ───────────────────────────────────────────
  const form = $("fl-add-source");
  let formReady = false;
  function setupForm(j) {
    const s3 = form.querySelector('input[name="provider"][value="s3"]');
    s3.disabled = !j.s3.configured;
    $("fl-s3-note").innerHTML = j.s3.configured
      ? `Approved locations: ${j.s3.approved.map(a => `<code>${esc(a)}</code>`).join(" ")}`
      : "No S3 locations are approved on this server (<code>CRYOSTACK_FROZEN_LEGACIES_S3_ALLOWED</code>).";
    const local = form.querySelector('input[name="provider"][value="local"]');
    local.disabled = !j.storage_roots_configured;
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
      const first = [local, s3].find(i => !i.disabled);
      if (first) first.checked = true;
      showProvider();
    }
    $("fl-add-panel").hidden = !(j.storage_roots_configured || j.s3.configured);
  }
  function provider() { return (form.querySelector('input[name="provider"]:checked') || {}).value; }
  function showProvider() {
    const p = provider();
    form.querySelectorAll("[data-provider]").forEach(el => {
      const on = el.dataset.provider === p;
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
        '<a class="small-button" href="/control/frozen-legacies/review">Scientific review →</a>') + """
    <div class="metric-grid" id="fl-metrics"></div>
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
            <label><input type="radio" name="provider" value="s3">
              <strong>Amazon S3 · read-only</strong>
              <span>A bucket prefix read with the server's own AWS credentials.</span></label>
          </div>
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
    </style>
    <script>""" + _CONTROL_SCRIPT + """</script>"""
    return web.Response(text=control_layout(title="Frozen Legacies", active="frozen-legacies",
                                            content=content),
                        content_type="text/html")


def install_catalog_routes(app: web.Application, *, auth) -> None:
    app[INDEX_WORKERS_KEY] = {}
    app.on_startup.append(_recover_runs)
    # automatic-job status changes update the user's state index
    app[S.AUTOMATIC_KEY].on_change = record_state_by_id
    # observation writes keep the indexed My picks current
    obs.on_change = index_observations
    api = "/frozen-legacies/api"
    app.router.add_get(f"{api}/radar/catalog", S._api(auth, api_catalog_search))
    app.router.add_get(f"{api}/radar/catalog/summary", S._api(auth, api_catalog_summary))
    app.router.add_get(f"{api}/radar/catalog/segments", S._api(auth, api_catalog_segments))
    app.router.add_get(f"{api}/observations", S._api(auth, api_observations))
    source = "{source_id:[a-z0-9][a-z0-9-]{1,62}}"
    app.router.add_get(f"{api}/admin/sources", _maintainer(auth, api_admin_sources))
    app.router.add_post(f"{api}/admin/sources", _maintainer(auth, api_admin_add_source))
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
    control_access = auth.require_roles("maintainer", "admin", "owner")
    app.router.add_get("/control/frozen-legacies", control_access(control_page))

    from .review_routes import install_review_routes
    install_review_routes(app, auth=auth, maintainer=_maintainer)

    # CBD provenance / georeferencing of the user's A-scopes (owner-scoped)
    from .georef_routes import install_georef_routes
    install_georef_routes(app, auth=auth)
