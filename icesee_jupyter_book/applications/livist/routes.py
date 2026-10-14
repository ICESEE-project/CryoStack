"""LIVIST routes: the Control Center page ``/control/livist`` and ``/api/livist/``.

Roles (checked against the role store on every request):

* **developer, maintainer, admin, owner** (the Control Center roles) may
  open the page and follow, cancel, re-validate and download their own jobs.
* **maintainer, admin, owner** may start LIVIST generations *into their own
  workspace* (``START_ROLES``; developers are excluded for the initial
  production deployment because generation runs on the gateway host).
  They additionally approve inputs, see every job
  (status and log; downloads stay owner-only), and request / approve / reject
  publication to source.coop.

``GET  status``                          toolchain health, settings, inputs
``GET  sources``              (maint.)   approved inputs and candidates
``POST sources``              (maint.)   approve a candidate under a name
``POST sources/<name>/status`` (maint.)  enable / disable an input
``GET  jobs``                            own jobs (``?scope=all`` maint.)
``POST jobs``                 (maint.)   start a generation
``GET  jobs/<id>``                       job, manifest, validation and product table
``GET  jobs/<id>/log``                   tail of the bounded log
``POST jobs/<id>/cancel``                cancel (owner or maint.)
``POST jobs/<id>/retry``      (maint.)   start a new job with a failed or
                                         interrupted job's inputs (owner)
``POST jobs/<id>/validate``              re-run product validation (owner)
``GET  jobs/<id>/files/<name>``          download a product (owner)
``GET  compare?jobs=<id>,<id>[,...]``    compare completed jobs the viewer may see
``GET  cache``                (maint.)   shared input cache diagnostics (read-only)
``GET  publications``         (maint.)   publication requests
``POST publications``         (maint.)   request: computes a dry-run plan
``POST publications/<id>/approve`` (maint., not the requester)
``POST publications/<id>/reject``  (maint.)

Every state change is same-origin, JSON-only and recorded in the Control
Center audit log. No response contains server paths of inputs (masked),
workspace paths, credentials or session data.
"""
from __future__ import annotations

import asyncio
import functools
import json
import os
import signal
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from cryostack_src.workspace.identity import WorkspaceIdentityError
from cryostack_src.workspace.manager import WorkspacePermissionError

from . import (input_cache, manifest, products, publication, settings, sources, toolchain,
               validation, worker)
from .store import JobLimitError, LivistStore
from .workspace import LivistWorkspace, is_valid_job_id, new_job_id, workspace_user_for

#: who may open LIVIST and follow, cancel, validate and download their own jobs
GENERATE_ROLES = frozenset({"developer", "maintainer", "admin", "owner"})
MAINTAINER_ROLES = frozenset({"maintainer", "admin", "owner"})
#: who may start a generation; generation runs on the gateway host
START_ROLES = MAINTAINER_ROLES
STORE_KEY = "livist_store"
SPAWN_KEY = "livist_spawn"
PROBE_KEY = "livist_probe"
WORKERS_KEY = "livist_workers"
WORKER_MODULE = f"{__package__}.worker"
STALE_JOB_S = 90.0
MAX_SOURCES_PER_JOB = 8
LOG_VIEW_BYTES = 64 << 10
#: statuses a job can be retried from (a new job; nothing is resumed)
RETRYABLE = ("failed", "interrupted", "timed_out")
LEFTOVER_GRACE_S = 5.0
MAX_COMPARE = 6
CACHE_REPORT_JOBS = 500
API = "/api/livist"


# ── helpers ──────────────────────────────────────────────────────────
def _json(data, *, status: int = 200) -> web.Response:
    response = web.json_response(data, status=status)
    response.headers["Cache-Control"] = "no-store"
    return response


def _error(status: int, message: str, **extra) -> web.Response:
    return _json({"error": message, **extra}, status=status)


async def _blocking(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


def _same_origin(request: web.Request) -> web.Response | None:
    """Refuse cross-site state changes; only JSON bodies are accepted, which a
    plain HTML form on another site cannot send."""
    origin = request.headers.get("Origin")
    if origin is not None and urlsplit(origin).netloc != request.host:
        return _error(403, "Cross-origin request refused.")
    if request.content_type != "application/json":
        return _error(415, "A JSON request body is required.")
    return None


async def _body(request: web.Request) -> dict:
    if (request.content_length or 0) > 16 << 10:
        raise web.HTTPRequestEntityTooLarge(max_size=16 << 10, actual_size=request.content_length)
    try:
        payload = await request.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _store(app: web.Application) -> LivistStore:
    store = app.get(STORE_KEY)
    if store is None:
        store = app[STORE_KEY] = LivistStore(settings.database_path())
    return store


def _guard(auth, handler, roles: frozenset, *, mutating: bool = False):
    async def protected(request: web.Request) -> web.StreamResponse:
        user = auth.current_user(request)
        if user is None:
            return _error(401, "Authentication required.")
        held = set(auth.storage.get_user_roles(user_id=user.id))
        if not held & roles:
            return _error(403, "Your CryoStack role does not allow this LIVIST action.")
        if mutating:
            refused = _same_origin(request)
            if refused is not None:
                return refused
        request["cryostack_user"] = user
        request["livist_maintainer"] = bool(held & MAINTAINER_ROLES)
        request["livist_can_start"] = bool(held & START_ROLES)
        try:
            return await handler(request)
        except (sources.SourceError, ValueError) as error:
            return _error(400, str(error))
        except (WorkspaceIdentityError, WorkspacePermissionError):
            return _error(404, "Job not found.")

    return protected


def _audit(auth, request: web.Request, action: str, **meta) -> None:
    auth.storage.add_control_audit_event(
        actor_user_id=request["cryostack_user"].id, action=f"livist.{action}",
        metadata_json=json.dumps(meta, sort_keys=True))


def _workspace(user) -> LivistWorkspace:
    return LivistWorkspace(workspace_user_for(user))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError, ValueError):
        return True
    return True


def _proc_cwd(pid: int) -> str | None:
    try:
        return os.path.realpath(os.readlink(f"/proc/{int(pid)}/cwd"))
    except (OSError, ValueError):
        return None


def _proc_args(pid: int) -> list[str]:
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as handle:
            return handle.read().decode("utf-8", "replace").split("\0")
    except (OSError, ValueError):
        return []


def _stop_leftovers(row: dict) -> None:
    """Stop what an interrupted job left running. A PID is only signalled
    when it is provably this job's: the generator's process group leader
    must still run in the job directory, the worker's command line must name
    this job (PIDs are reused)."""
    gpid = row.get("generator_pid")
    workdir = os.path.realpath(row.get("workdir") or "/nonexistent")
    if gpid and _proc_cwd(gpid) == workdir:
        try:
            if os.getpgid(gpid) == gpid:
                os.killpg(gpid, signal.SIGTERM)
                deadline = time.monotonic() + LEFTOVER_GRACE_S
                while _pid_alive(gpid) and _proc_cwd(gpid) == workdir \
                        and time.monotonic() < deadline:
                    time.sleep(0.1)
                if _proc_cwd(gpid) == workdir:
                    os.killpg(gpid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    pid = row.get("pid")
    if pid and pid != os.getpid():
        args = _proc_args(pid)
        if WORKER_MODULE in args and row["job_id"] in args:
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass


def reconcile(store: LivistStore) -> list[str]:
    return store.reconcile_jobs(stale_after_s=STALE_JOB_S, is_alive=_pid_alive,
                                on_interrupted=_stop_leftovers)


def _names(auth, user_ids) -> dict[str, str]:
    out = {}
    for user_id in set(user_ids):
        try:
            user = auth.storage.get_user_by_id(user_id)
        except Exception:                   # a deleted account: show it as such
            user = None
        out[user_id] = (getattr(user, "display_name", None) or "Unknown user") if user else \
            "Deleted account"
    return out


def public_job(job: dict, *, viewer_id: str, names: dict | None = None) -> dict:
    return {
        "job_id": job["job_id"],
        "mine": job["owner_id"] == viewer_id,
        "owner": (names or {}).get(job["owner_id"]) if job["owner_id"] != viewer_id else "You",
        "status": job["status"],
        "sources": [s["name"] for s in job["sources"]],
        "created_at": job["created_at"], "started_at": job["started_at"],
        "finished_at": job["finished_at"], "heartbeat_at": job["heartbeat_at"],
        "cancel_requested": bool(job["cancel_requested"]),
        "timeout_s": job["timeout_s"], "exit_code": job["exit_code"], "error": job["error"],
        "config_sha256": job["config_sha256"], "validation_status": job["validation_status"],
        "retry_of": job.get("retry_of"),
        "retryable": job["status"] in RETRYABLE,
    }


def _job_for(request: web.Request, *, owner_only: bool = False) -> tuple[dict, Path]:
    """The job and its directory, if the viewer may see it (404 otherwise --
    another user's job is indistinguishable from a missing one)."""
    return _visible_job(request, request.match_info["job_id"], owner_only=owner_only)


def _visible_job(request: web.Request, job_id: object, *,
                 owner_only: bool = False) -> tuple[dict, Path]:
    if not is_valid_job_id(job_id):
        raise web.HTTPNotFound(text="Job not found.")
    job = _store(request.app).get_job(job_id)
    user = request["cryostack_user"]
    if job is None:
        raise web.HTTPNotFound(text="Job not found.")
    mine = job["owner_id"] == user.id
    if not mine and (owner_only or not request["livist_maintainer"]):
        raise web.HTTPNotFound(text="Job not found.")
    workdir = Path(job["workdir"])
    if mine:
        workdir = _workspace(user).job_dir(job_id)
    return job, workdir


def _http_error(handler):
    @functools.wraps(handler)
    async def wrapped(request):
        try:
            return await handler(request)
        except web.HTTPNotFound as error:
            return _error(404, error.text or "Not found.")
    return wrapped


# ── status and inputs ────────────────────────────────────────────────
async def api_status(request: web.Request) -> web.Response:
    refresh = request.query.get("refresh") == "1" and request["livist_maintainer"]
    health = await _blocking(toolchain.health, refresh=refresh)
    store = _store(request.app)
    enabled = await _blocking(store.list_sources, enabled_only=True)
    return _json({
        "viewer": {"can_generate": request["livist_can_start"], "maintainer": request["livist_maintainer"]},
        "toolchain": health,
        "settings": {
            "environment": sources.mask_location(str(settings.env_dir())),
            "input_roots": len(settings.input_roots()),
            "timeout_s": settings.job_timeout_s(),
            "max_active": settings.max_active_jobs(),
            "output": "<your workspace>/livist/jobs/<job>/",
            "publication": {"target": settings.publication_target(),
                            "enabled": settings.publication_enabled()},
        },
        "sources": [sources.public_source(s) for s in enabled],
        "attribution": manifest.ATTRIBUTION,
    })


async def api_sources(request: web.Request) -> web.Response:
    store = _store(request.app)
    approved = await _blocking(store.list_sources)
    taken = {(s["kind"], s["location"]) for s in approved}
    found = await _blocking(sources.candidates)
    return _json({
        "sources": [sources.public_source(s) for s in approved],
        "candidates": [sources.public_candidate(c) for c in found
                       if (c["kind"], c["location"]) not in taken],
        "input_roots": len(settings.input_roots()),
    })


def _auth(request):
    return request.app["livist_auth"]


async def api_add_source(request: web.Request) -> web.Response:
    payload = await _body(request)
    for key in payload:
        if key not in ("candidate_id", "name", "description"):
            return _error(400, f"Unexpected field {key!r}. Inputs are chosen from the approved "
                               "candidates; paths cannot be entered.")
    name = payload.get("name")
    if not sources.is_valid_name(name):
        return _error(400, "Names are 1-32 lowercase letters, digits and hyphens "
                           "(they become part of product file names).")
    found = {c["id"]: c for c in await _blocking(sources.candidates)}
    candidate = found.get(payload.get("candidate_id"))
    if candidate is None:
        return _error(400, "Choose one of the offered inputs.")
    if candidate["kind"] == "local":
        sources.resolve_local(candidate["location"])
    description = str(payload.get("description") or "").strip()
    store = _store(request.app)
    try:
        row = await _blocking(store.add_source, name=name, kind=candidate["kind"],
                              location=candidate["location"], description=description,
                              created_by=request["cryostack_user"].id)
    except ValueError as error:
        return _error(409, str(error))
    _audit(_auth(request), request, "source.approve", name=name, kind=candidate["kind"],
           location=sources.public_candidate(candidate)["location"])
    return _json(sources.public_source(row), status=201)


async def api_source_status(request: web.Request) -> web.Response:
    payload = await _body(request)
    if not isinstance(payload.get("enabled"), bool):
        return _error(400, '{"enabled": true | false} is required.')
    store = _store(request.app)
    name = request.match_info["name"]
    if await _blocking(store.get_source, name) is None:
        return _error(404, "Input not found.")
    row = await _blocking(store.set_source_enabled, name, payload["enabled"])
    _audit(_auth(request), request, "source.enable" if payload["enabled"] else "source.disable",
           name=name)
    return _json(sources.public_source(row))


# ── jobs ─────────────────────────────────────────────────────────────
async def api_jobs(request: web.Request) -> web.Response:
    store = _store(request.app)
    await _blocking(reconcile, store)
    user = request["cryostack_user"]
    every = request.query.get("scope") == "all"
    if every and not request["livist_maintainer"]:
        return _error(403, "Only maintainers can list every user's jobs.")
    jobs = await _blocking(store.list_jobs, owner_id=None if every else user.id)
    names = _names(_auth(request), [j["owner_id"] for j in jobs]) if every else {}
    return _json({"jobs": [public_job(j, viewer_id=user.id, names=names) for j in jobs],
                  "scope": "all" if every else "mine"})


async def spawn_worker(app: web.Application, store: LivistStore, job_id: str):
    """Start the worker of a queued job in its own session (a gateway restart
    does not take it down; the heartbeat tells whether it still runs)."""
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", WORKER_MODULE, "--db", str(store.path), "--job", job_id,
        cwd=str(settings.REPO_ROOT), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        start_new_session=True)

    async def reap():
        try:
            _out, err = await process.communicate()
            if process.returncode not in (0, None):
                tail = (err or b"").decode("utf-8", "replace").strip().splitlines()[-10:]
                print(f"[LIVIST] job {job_id} worker exited with {process.returncode}:\n  "
                      + "\n  ".join(tail), file=sys.stderr)
        finally:
            app[WORKERS_KEY].pop(job_id, None)

    app[WORKERS_KEY][job_id] = (process, asyncio.ensure_future(reap()))
    return process


async def _start_job(request: web.Request, names: object, *,
                     retry_of: dict | None = None) -> web.Response:
    """The one start path (new jobs and retries): approved, enabled inputs
    only, a ready toolchain, the free-space reserve and the job limits."""
    if (not isinstance(names, list) or not names or len(names) > MAX_SOURCES_PER_JOB
            or len(set(map(str, names))) != len(names)):
        return _error(400, f"Choose 1-{MAX_SOURCES_PER_JOB} approved inputs.")
    store = _store(request.app)
    rows = []
    for name in names:
        row = await _blocking(store.get_source, name) if sources.is_valid_name(name) else None
        if row is None or not row["enabled"]:
            return _error(400, f"{name!s:.40} is not an enabled LIVIST input.")
        if row["kind"] == "local":
            sources.resolve_local(row["location"])
        rows.append({"name": row["name"], "kind": row["kind"], "location": row["location"]})
    if retry_of is not None:
        before = {(s["name"], s["kind"], s["location"]) for s in retry_of["sources"]}
        if before != {(r["name"], r["kind"], r["location"]) for r in rows}:
            return _error(409, "An input of this job was approved again with a different "
                               "location since it ran; start a new generation instead.")
    health = await _blocking(toolchain.health)
    if not health["ready"]:
        return _error(409, "The LIVIST environment is not ready; see Toolchain.")
    await _blocking(reconcile, store)
    user = request["cryostack_user"]
    workspace = _workspace(user)
    job_id = new_job_id()
    workdir = workspace.job_dir(job_id)
    short = await _blocking(worker.space_problem, workdir, settings.job_reserve_bytes())
    if short:
        return _error(409, short)
    try:
        job = await _blocking(store.queue_job, job_id=job_id, owner_id=user.id,
                              workdir=str(workdir), sources=rows,
                              timeout_s=settings.job_timeout_s(),
                              max_active=settings.max_active_jobs(),
                              retry_of=retry_of["job_id"] if retry_of else None)
    except JobLimitError as error:
        return _error(409, str(error))
    try:
        await _blocking(workspace.create_job_dir, job_id)
        await request.app[SPAWN_KEY](request.app, store, job_id)
    except OSError as error:
        await _blocking(store.finish_job, job_id, status="failed",
                        error=f"The generation worker could not start ({error.strerror}).")
        return _error(500, "The generation worker could not be started.")
    if retry_of is not None:
        _audit(_auth(request), request, "job.retry", job_id=job_id, retry_of=retry_of["job_id"],
               sources=names)
    else:
        _audit(_auth(request), request, "job.start", job_id=job_id, sources=names)
    return _json(public_job(job, viewer_id=user.id), status=202)


async def api_start_job(request: web.Request) -> web.Response:
    payload = await _body(request)
    return await _start_job(request, payload.get("sources"))


@_http_error
async def api_retry_job(request: web.Request) -> web.Response:
    """A new job with the stored inputs of a failed, interrupted or timed-out
    job of the caller's. Same role, origin, input and limit checks as a new
    generation; the earlier job directory is not touched or resumed."""
    await _body(request)
    store = _store(request.app)
    await _blocking(reconcile, store)
    job, _workdir = _job_for(request, owner_only=True)
    if job["status"] not in RETRYABLE:
        return _error(409, "Only a failed, interrupted or timed-out job can be retried.")
    return await _start_job(request, [s["name"] for s in job["sources"]], retry_of=job)


@_http_error
async def api_job(request: web.Request) -> web.Response:
    store = _store(request.app)
    await _blocking(reconcile, store)
    job, workdir = _job_for(request)
    data = await _blocking(manifest.read, workdir) if workdir.is_dir() else None
    item = public_job(job, viewer_id=request["cryostack_user"].id,
                      names=_names(_auth(request), [job["owner_id"]]))
    if data:
        item["manifest"] = {k: data.get(k) for k in (
            "artifacts", "inputs", "livist", "config_sha256", "validation", "attribution",
            "cryostack_commit", "written_at", "resources", "schema", "complete")}
        for record in item["manifest"]["inputs"] or []:
            record["identity"] = products.recorded_identity(record)
        requests = await _blocking(store.requests_for_job, job["job_id"])
        table = await _blocking(products.product_table, workdir, data,
                                products.publication_state(requests), status=job["status"])
        table["downloadable"] = item["mine"] and table["complete"]
        item["products"] = table
    elif job["status"] == "completed":
        item["manifest_missing"] = True
    return _json(item)


def _compare_ids(request: web.Request) -> list[str]:
    raw = ",".join(request.query.getall("jobs", []) + request.query.getall("job", []))
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    if len(ids) < 2 or len(ids) > MAX_COMPARE:
        raise ValueError(f"Choose 2-{MAX_COMPARE} jobs to compare.")
    if len(set(ids)) != len(ids):
        raise ValueError("A job is listed twice.")
    return ids


async def api_compare(request: web.Request) -> web.Response:
    """Side-by-side comparison of completed jobs. Every job must be one the
    viewer could already open (own jobs; every job for maintainers); any other
    job makes the whole request 404, like a missing one."""
    ids = _compare_ids(request)
    store = _store(request.app)
    await _blocking(reconcile, store)
    found = []
    for job_id in ids:
        try:
            found.append(await _blocking(_visible_job, request, job_id))
        except web.HTTPNotFound:
            return _error(404, "Job not found.")
    if any(job["status"] != "completed" for job, _w in found):
        return _error(409, "Only completed jobs can be compared.")
    viewer = request["cryostack_user"].id
    names = _names(_auth(request), [job["owner_id"] for job, _w in found])
    runs = []
    for job, workdir in found:
        data = await _blocking(manifest.read, workdir) if workdir.is_dir() else None
        runs.append({"job": public_job(job, viewer_id=viewer, names=names), "manifest": data})
    return _json(await _blocking(products.compare, runs))


async def api_cache(request: web.Request) -> web.Response:
    store = _store(request.app)
    jobs = await _blocking(store.list_jobs, limit=CACHE_REPORT_JOBS)

    def load() -> list[dict]:
        out = []
        for job in jobs:
            workdir = Path(job["workdir"])
            out.append({"job": job,
                        "manifest": manifest.read(workdir) if workdir.is_dir() else None})
        return out

    loaded = await _blocking(load)
    names = _names(_auth(request), [j["owner_id"] for j in jobs])
    report = await _blocking(products.cache_report, input_cache.InputCache(), loaded,
                             names=names, viewer_id=request["cryostack_user"].id)
    return _json(report)


@_http_error
async def api_job_log(request: web.Request) -> web.Response:
    job, workdir = _job_for(request)
    path = workdir / "logs" / "generate.log"

    def tail() -> tuple[str, bool]:
        try:
            with path.open("rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                handle.seek(max(0, size - LOG_VIEW_BYTES))
                return handle.read().decode("utf-8", "replace"), size > LOG_VIEW_BYTES
        except OSError:
            return "", False

    text, truncated = await _blocking(tail)
    return _json({"job_id": job["job_id"], "log": text, "truncated": truncated})


@_http_error
async def api_cancel_job(request: web.Request) -> web.Response:
    job, _workdir = _job_for(request)
    if job["status"] not in ("queued", "running"):
        return _error(409, "This job is not running.")
    store = _store(request.app)
    updated = await _blocking(store.request_cancel, job["job_id"])
    worker = request.app[WORKERS_KEY].get(job["job_id"])
    if worker is not None and worker[0].returncode is None:
        try:
            worker[0].terminate()
        except ProcessLookupError:
            pass
    _audit(_auth(request), request, "job.cancel", job_id=job["job_id"])
    return _json(public_job(updated, viewer_id=request["cryostack_user"].id), status=202)


@_http_error
async def api_validate_job(request: web.Request) -> web.Response:
    job, workdir = _job_for(request, owner_only=True)
    if job["status"] != "completed":
        return _error(409, "Only completed jobs can be validated.")
    data = await _blocking(manifest.read, workdir)
    if data is None:
        return _error(409, "This job has no manifest.")
    names = [s["name"] for s in job["sources"]]
    check = await _blocking(validation.validate, workdir, names)
    data["validation"] = check
    data["artifacts"] = await _blocking(manifest.artifacts, workdir)
    await _blocking(manifest.write, workdir, data)
    await _blocking(_store(request.app).set_validation, job["job_id"], check["status"])
    return _json({"job_id": job["job_id"], "validation": check})


@_http_error
async def api_job_file(request: web.Request) -> web.StreamResponse:
    job, workdir = _job_for(request, owner_only=True)
    name = request.match_info["name"]
    if name == manifest.MANIFEST:
        path = workdir / manifest.MANIFEST
    else:
        # only a completed job's recorded products; partial files are never served
        data = await _blocking(manifest.read, workdir) if job["status"] == "completed" else None
        recorded = {a.get("name") for a in (data or {}).get("artifacts") or []}
        path = ((await _blocking(validation.product_paths, workdir)).get(name)
                if name in recorded else None)
    if path is None or not path.is_file():
        return _error(404, "File not found.")
    response = web.FileResponse(path)
    response.headers["Content-Disposition"] = f'attachment; filename="{name}"'
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# ── publication ──────────────────────────────────────────────────────
def public_request(item: dict, names: dict, viewer_id: str) -> dict:
    return {
        "request_id": item["request_id"], "job_id": item["job_id"], "status": item["status"],
        "plan": item["plan"], "plan_sha256": item["plan_sha256"],
        "allow_overwrite": bool(item["allow_overwrite"]),
        "requested_by": names.get(item["requested_by"]), "requested_at": item["requested_at"],
        "mine": item["requested_by"] == viewer_id,
        "decided_by": names.get(item["decided_by"]) if item["decided_by"] else None,
        "decided_at": item["decided_at"], "note": item["note"], "result": item["result"],
    }


async def api_publications(request: web.Request) -> web.Response:
    items = await _blocking(_store(request.app).list_requests)
    names = _names(_auth(request), [i["requested_by"] for i in items]
                   + [i["decided_by"] for i in items if i["decided_by"]])
    return _json({
        "requests": [public_request(i, names, request["cryostack_user"].id) for i in items],
        "target": settings.publication_target(),
        "enabled": settings.publication_enabled(),
    })


def _job_and_dir(store: LivistStore, job_id: object) -> tuple[dict, Path]:
    job = store.get_job(job_id) if is_valid_job_id(job_id) else None
    if job is None:
        raise web.HTTPNotFound(text="Job not found.")
    return job, Path(job["workdir"])


@_http_error
async def api_request_publication(request: web.Request) -> web.Response:
    payload = await _body(request)
    store = _store(request.app)
    job, workdir = await _blocking(_job_and_dir, store, payload.get("job_id"))
    allow_overwrite = payload.get("allow_overwrite") is True
    data = await _blocking(manifest.read, workdir)
    item = await _blocking(publication.plan, job, workdir, data, probe=request.app[PROBE_KEY])
    if item["blocking"]:
        return _error(409, "This job cannot be published: " + " ".join(item["blocking"]),
                      plan=item)
    if item["overwrites"] and not allow_overwrite:
        return _error(409, "Published files would be overwritten; request again with "
                           "overwriting allowed if that is intended.", plan=item)
    digest = publication.plan_digest(item)
    request_id = uuid.uuid4().hex
    row = await _blocking(store.create_request, request_id=request_id, job_id=job["job_id"],
                          plan=item, plan_sha256=digest, allow_overwrite=allow_overwrite,
                          requested_by=request["cryostack_user"].id)
    _audit(_auth(request), request, "publication.request", request_id=request_id,
           job_id=job["job_id"], plan_sha256=digest, files=len(item["files"]),
           overwrites=item["overwrites"], target=item["target"])
    names = _names(_auth(request), [row["requested_by"]])
    return _json(public_request(row, names, request["cryostack_user"].id), status=201)


@_http_error
async def api_decide_publication(request: web.Request) -> web.Response:
    approve = request.match_info["decision"] == "approve"
    payload = await _body(request)
    note = str(payload.get("note") or "").strip()[:500]
    store = _store(request.app)
    item = await _blocking(store.get_request, request.match_info["request_id"])
    if item is None:
        return _error(404, "Publication request not found.")
    if item["status"] != "pending":
        return _error(409, "This request has already been decided.")
    actor = request["cryostack_user"].id
    auth = _auth(request)
    if not approve:
        if not await _blocking(store.decide_request, item["request_id"], status="rejected",
                               decided_by=actor, note=note):
            return _error(409, "This request has already been decided.")
        _audit(auth, request, "publication.reject", request_id=item["request_id"],
               job_id=item["job_id"])
        return _json({"request_id": item["request_id"], "status": "rejected"})

    if item["requested_by"] == actor:
        return _error(403, "A publication request must be approved by a different maintainer.")
    job, workdir = await _blocking(_job_and_dir, store, item["job_id"])
    data = await _blocking(manifest.read, workdir)
    fresh = await _blocking(publication.plan, job, workdir, data, probe=request.app[PROBE_KEY])
    digest = publication.plan_digest(fresh)
    problems = list(fresh["blocking"])
    if digest != item["plan_sha256"]:
        problems.append("The products changed since the request; request publication again.")
    new_overwrites = set(fresh["overwrites"]) - set(item["plan"].get("overwrites") or [])
    if new_overwrites and not item["allow_overwrite"]:
        problems.append("Files were published at the destination since the request: "
                        + ", ".join(sorted(new_overwrites)) + ".")
    if problems:
        await _blocking(store.decide_request, item["request_id"], status="failed",
                        decided_by=actor, note=note, result={"problems": problems, "plan": fresh})
        _audit(auth, request, "publication.fail", request_id=item["request_id"],
               job_id=item["job_id"], problems=problems)
        return _error(409, " ".join(problems))

    if not settings.publication_enabled():
        result = {"dry_run": True, "uploaded": [], "plan": fresh,
                  "message": "Approved as a dry run: publication is disabled on this server, "
                             "nothing was uploaded."}
        if not await _blocking(store.decide_request, item["request_id"], status="approved",
                               decided_by=actor, note=note, result=result):
            return _error(409, "This request has already been decided.")
        _audit(auth, request, "publication.approve", request_id=item["request_id"],
               job_id=item["job_id"], plan_sha256=digest, dry_run=True)
        return _json({"request_id": item["request_id"], "status": "approved", "result": result})

    # real upload: claim the request first so it can only run once
    if not await _blocking(store.decide_request, item["request_id"], status="approved",
                           decided_by=actor, note=note, result={"dry_run": False,
                                                                "uploading": True}):
        return _error(409, "This request has already been decided.")
    _audit(auth, request, "publication.approve", request_id=item["request_id"],
           job_id=item["job_id"], plan_sha256=digest, dry_run=False)
    try:
        uploaded = await _blocking(publication.execute, fresh, workdir,
                                   allow_overwrite=bool(item["allow_overwrite"]),
                                   client_factory=request.app["livist_s3_client"])
    except Exception as error:              # never echo SDK errors (they can carry account data)
        message = (str(error) if isinstance(error, publication.PublicationError)
                   else "The upload failed.")
        await _blocking(store.decide_request, item["request_id"], status="failed",
                        decided_by=actor, result={"dry_run": False, "error": message},
                        expect="approved")
        _audit(auth, request, "publication.fail", request_id=item["request_id"],
               job_id=item["job_id"], error=message)
        return _error(502, message)
    result = {"dry_run": False, **uploaded}
    await _blocking(store.decide_request, item["request_id"], status="published",
                    decided_by=actor, result=result, expect="approved")
    _audit(auth, request, "publication.published", request_id=item["request_id"],
           job_id=item["job_id"], files=[u["name"] for u in uploaded["uploaded"]])
    return _json({"request_id": item["request_id"], "status": "published", "result": result})


# ── page ─────────────────────────────────────────────────────────────
async def control_page(request: web.Request) -> web.Response:
    from control_center.templates import control_layout

    from .page import CONTENT

    return web.Response(text=control_layout(title="LIVIST", active="livist", content=CONTENT),
                        content_type="text/html")


async def _recover(app: web.Application) -> None:
    try:
        ended = await _blocking(reconcile, _store(app))
    except Exception as error:              # a missing database must not stop the gateway
        print(f"[LIVIST] job reconciliation skipped: {error}", file=sys.stderr)
        return
    if ended:
        print(f"[LIVIST] marked interrupted jobs: {ended}")


def install_livist(app: web.Application, *, auth) -> None:
    """Install the LIVIST Control Center page and API (``/livist/`` and
    ``/livist/docs/`` static serving stays in ``bin/icesee_app.py``)."""
    app["livist_auth"] = auth
    app.setdefault(WORKERS_KEY, {})
    app.setdefault(SPAWN_KEY, spawn_worker)
    app.setdefault(PROBE_KEY, publication.http_probe)
    app.setdefault("livist_s3_client", publication.default_client)
    app.on_startup.append(_recover)

    def user(handler, mutating=False):
        return _guard(auth, handler, GENERATE_ROLES, mutating=mutating)

    def maintainer(handler, mutating=False):
        return _guard(auth, handler, MAINTAINER_ROLES, mutating=mutating)

    job = "{job_id:[0-9a-f]{32}}"
    app.router.add_get(f"{API}/status", user(api_status))
    app.router.add_get(f"{API}/sources", maintainer(api_sources))
    app.router.add_post(f"{API}/sources", maintainer(api_add_source, True))
    app.router.add_post(f"{API}/sources/{{name:[a-z0-9][a-z0-9-]{{0,31}}}}/status",
                        maintainer(api_source_status, True))
    app.router.add_get(f"{API}/jobs", user(api_jobs))
    app.router.add_post(f"{API}/jobs", _guard(auth, api_start_job, START_ROLES, mutating=True))
    app.router.add_get(f"{API}/jobs/{job}", user(api_job))
    app.router.add_get(f"{API}/jobs/{job}/log", user(api_job_log))
    app.router.add_post(f"{API}/jobs/{job}/cancel", user(api_cancel_job, True))
    app.router.add_post(f"{API}/jobs/{job}/retry",
                        _guard(auth, api_retry_job, START_ROLES, mutating=True))
    app.router.add_post(f"{API}/jobs/{job}/validate", user(api_validate_job, True))
    app.router.add_get(f"{API}/jobs/{job}/files/{{name:[A-Za-z0-9][A-Za-z0-9._-]{{0,199}}}}",
                       user(api_job_file))
    app.router.add_get(f"{API}/compare", user(api_compare))
    app.router.add_get(f"{API}/cache", maintainer(api_cache))
    app.router.add_get(f"{API}/publications", maintainer(api_publications))
    app.router.add_post(f"{API}/publications", maintainer(api_request_publication, True))
    app.router.add_post(f"{API}/publications/{{request_id:[0-9a-f]{{32}}}}/{{decision:approve|reject}}",
                        maintainer(api_decide_publication, True))

    control_access = auth.require_roles(*sorted(GENERATE_ROLES))
    app.router.add_get("/control/livist", control_access(control_page))
