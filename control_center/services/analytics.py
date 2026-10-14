# control_center/services/analytics.py

"""Control Center analytics: aggregate platform activity.

Sources, in this order of preference -- existing records first:

* **experiments** (auth database, read-only): job counts and states per day,
  per application and backend, failure rates, recorded wall time;
* **Frozen Legacies index runs** (radar catalog, opened read-only): runs,
  files indexed, failures;
* **storage** (measured live): working-cache usage against its limit,
  workspace totals (aggregate only, bounded scan);
* **application opens** -- the one metric with no existing source. The
  :class:`UsageCounter` middleware counts successful page loads of each
  application's entry page per UTC day: ``(day, application, opens)``, no
  user id, no IP, no path beyond the entry page. Requests from the health
  checkers are not counted.

Nothing here returns per-user rows.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiohttp import web

from ..ops_store import OpsStore


#: application entry pages counted by UsageCounter (exact paths)
APPLICATION_ENTRIES = {
    "/icesheets/": "cryolauncher",
    "/icesee-gui/": "icesee",
    "/livist/": "livist",
    "/frozen-legacies/": "frozen-legacies",
}
APPLICATION_TITLES = {
    "cryolauncher": "CryoLauncher",
    "icesee": "ICESEE",
    "livist": "LIVIST",
    "frozen-legacies": "Frozen Legacies",
}
#: user agents of CryoStack's own probes (deployment/health_check.py and
#: the Diagnostics page) -- not application usage
PROBE_AGENTS = ("CryoStack-HealthCheck", "CryoStack-Diagnostics")

FLUSH_INTERVAL_S = 60.0
WORKSPACE_SCAN_FILES = 200_000
WORKSPACE_SCAN_S = 5.0
WORKSPACE_CACHE_S = 600.0
FINAL_STATES = ("completed", "failed", "cancelled")


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def read_only(path: Path) -> sqlite3.Connection:
    """A read-only connection (never creates the file or its schema)."""
    connection = sqlite3.connect(
        f"file:{Path(path).resolve()}?mode=ro", uri=True, timeout=2
    )
    connection.row_factory = sqlite3.Row
    return connection


# ── application opens ───────────────────────────────────────────────
class UsageCounter:
    """In-memory per-(day, application) counts, flushed to the ops store at
    most once a minute (and at shutdown) off the event loop."""

    def __init__(self, store: OpsStore, *, clock=time.time) -> None:
        self.store = store
        self.clock = clock
        self._pending: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()
        self._last_flush = clock()

    def record(self, application: str) -> bool:
        with self._lock:
            key = (_day(self.clock()), application)
            self._pending[key] = self._pending.get(key, 0) + 1
            due = self.clock() - self._last_flush >= FLUSH_INTERVAL_S
            if due:
                self._last_flush = self.clock()
        return due

    def pending(self) -> dict[tuple[str, str], int]:
        with self._lock:
            return dict(self._pending)

    def flush(self) -> None:
        with self._lock:
            counts, self._pending = self._pending, {}
        try:
            self.store.add_usage(counts)
        except Exception:
            with self._lock:                # keep the counts for the next flush
                for key, value in counts.items():
                    self._pending[key] = self._pending.get(key, 0) + value

    def middleware(self):
        counter = self

        @web.middleware
        async def usage_middleware(request: web.Request, handler):
            response = await handler(request)
            application = APPLICATION_ENTRIES.get(request.path)
            if (
                application
                and request.method == "GET"
                and getattr(response, "status", 0) == 200
                and not request.headers.get("User-Agent", "").startswith(PROBE_AGENTS)
            ):
                if counter.record(application):
                    asyncio.get_running_loop().run_in_executor(None, counter.flush)
            return response

        return usage_middleware


# ── analytics ───────────────────────────────────────────────────────
class AnalyticsService:

    def __init__(
        self,
        *,
        auth_database: Path,
        store: OpsStore,
        counter: UsageCounter | None = None,
        catalog_path=None,
        working_cache=None,
        workspace_root=None,
        clock=time.time,
    ) -> None:
        self.auth_database = Path(auth_database)
        self.store = store
        self.counter = counter
        self._catalog_path = catalog_path
        self._working_cache = working_cache
        self._workspace_root = workspace_root
        self.clock = clock
        self._workspace_cache: tuple[float, dict] | None = None
        self._workspace_lock = threading.Lock()

    # sources resolved lazily, so tests and deployments can point elsewhere
    def catalog_path(self) -> Path:
        if self._catalog_path is not None:
            return Path(self._catalog_path)
        from icesee_jupyter_book.applications.frozen_legacies.radar.catalog import catalog_path
        return catalog_path()

    def working_cache(self):
        if self._working_cache is not None:
            return self._working_cache
        from icesee_jupyter_book.applications.frozen_legacies.radar.working_cache import working_cache
        return working_cache()

    def workspace_root(self) -> Path:
        if self._workspace_root is not None:
            return Path(self._workspace_root)
        from cryostack_src.workspace.roots import resolve_workspace_root
        return resolve_workspace_root()

    # ── public ──────────────────────────────────────────────────────
    def get_analytics(self, *, days: int = 30) -> dict:
        now = self.clock()
        days = max(1, min(int(days), 365))
        return {
            "generated_at": now,
            "window_days": days,
            "usage": self.application_usage(days=min(days, 14), now=now),
            "jobs": self.jobs(days=days, now=now),
            "indexing": self.indexing(days=days, now=now),
            "storage": self.storage(now=now),
        }

    def _days(self, days: int, now: float) -> list[str]:
        today = datetime.fromtimestamp(now, tz=timezone.utc).date()
        return [
            (today - timedelta(days=offset)).isoformat()
            for offset in range(days - 1, -1, -1)
        ]

    def application_usage(self, *, days: int, now: float) -> dict:
        series = self._days(days, now)
        table = {day: {app: 0 for app in APPLICATION_TITLES} for day in series}
        error = None
        try:
            rows = self.store.usage(since_day=series[0])
        except Exception as exc:
            rows, error = [], type(exc).__name__
        for row in rows:
            if row["day"] in table:
                table[row["day"]][row["application"]] = (
                    table[row["day"]].get(row["application"], 0) + int(row["opens"])
                )
        if self.counter is not None:
            for (day, app), count in self.counter.pending().items():
                if day in table:
                    table[day][app] = table[day].get(app, 0) + count
        totals = {app: sum(table[d].get(app, 0) for d in series) for app in APPLICATION_TITLES}
        try:
            first = self.store.first_usage_day()
        except Exception:
            first = None
        return {
            "kind": "historical",
            "days": [{"day": d, "counts": table[d]} for d in series],
            "totals": totals,
            "applications": APPLICATION_TITLES,
            "counting_since": first,
            "error": error,
        }

    def jobs(self, *, days: int, now: float) -> dict:
        series = self._days(days, now)
        since = now - days * 86400
        result = {
            "kind": "historical",
            "available": False,
            "per_day": [],
            "by_status": {},
            "by_application": [],
            "by_backend": [],
            "wall_time": [],
            "error": None,
        }
        if not self.auth_database.is_file():
            result["error"] = "The experiment database has not been created yet."
            return result
        try:
            with read_only(self.auth_database) as db:
                rows = db.execute(
                    "SELECT application, backend, status, created_at,"
                    " started_at, finished_at FROM experiments WHERE created_at >= ?",
                    (since,),
                ).fetchall()
        except sqlite3.Error as exc:
            result["error"] = f"Experiment records could not be read ({type(exc).__name__})."
            return result
        result["available"] = True
        per_day = {day: {} for day in series}
        by_status: dict[str, int] = {}
        groups = {"application": {}, "backend": {}}
        wall: dict[str, dict] = {}
        for row in rows:
            status = str(row["status"] or "unknown").strip().lower()
            day = _day(row["created_at"])
            if day in per_day:
                per_day[day][status] = per_day[day].get(status, 0) + 1
            by_status[status] = by_status.get(status, 0) + 1
            for field in ("application", "backend"):
                name = str(row[field] or "unknown").strip().lower() or "unknown"
                bucket = groups[field].setdefault(name, {"total": 0, "completed": 0,
                                                         "failed": 0, "cancelled": 0})
                bucket["total"] += 1
                if status in FINAL_STATES:
                    bucket[status] += 1
            if row["started_at"] and row["finished_at"] and row["finished_at"] >= row["started_at"]:
                backend = str(row["backend"] or "unknown").strip().lower() or "unknown"
                item = wall.setdefault(backend, {"backend": backend, "jobs": 0, "seconds": 0.0})
                item["jobs"] += 1
                item["seconds"] += float(row["finished_at"] - row["started_at"])

        def rates(group: dict) -> list[dict]:
            out = []
            for name, bucket in sorted(group.items()):
                finished = bucket["completed"] + bucket["failed"] + bucket["cancelled"]
                out.append({
                    "name": name, **bucket, "finished": finished,
                    "failure_rate": (bucket["failed"] / finished) if finished else None,
                })
            return out

        result["per_day"] = [{"day": d, "counts": per_day[d]} for d in series]
        result["by_status"] = by_status
        result["by_application"] = rates(groups["application"])
        result["by_backend"] = rates(groups["backend"])
        result["wall_time"] = sorted(wall.values(), key=lambda i: i["backend"])
        result["total"] = len(rows)
        return result

    def indexing(self, *, days: int, now: float) -> dict:
        since = now - days * 86400
        result = {"kind": "historical", "available": False, "runs_by_status": {},
                  "files": {}, "sources": [], "recent_failures": [], "error": None}
        path = self.catalog_path()
        if not path.is_file():
            result["error"] = "No Frozen Legacies catalog has been created on this server."
            return result
        try:
            with read_only(path) as db:
                runs = db.execute(
                    "SELECT source_id, status, started_at, finished_at, discovered,"
                    " added, changed, missing, invalid, error FROM index_runs"
                    " WHERE started_at >= ? ORDER BY run_id DESC", (since,),
                ).fetchall()
                assets = db.execute(
                    "SELECT status, COUNT(*) AS n FROM radar_assets GROUP BY status"
                ).fetchall()
                sources = db.execute(
                    "SELECT source_id, name, status, last_index_at, last_index_status"
                    " FROM data_sources ORDER BY source_id"
                ).fetchall()
        except sqlite3.Error as exc:
            result["error"] = f"The catalog could not be read ({type(exc).__name__})."
            return result
        result["available"] = True
        by_status: dict[str, int] = {}
        totals = {"discovered": 0, "added": 0, "changed": 0, "missing": 0, "invalid": 0}
        for run in runs:
            by_status[run["status"]] = by_status.get(run["status"], 0) + 1
            for key in totals:
                totals[key] += int(run[key] or 0)
        result["runs_by_status"] = by_status
        result["runs"] = len(runs)
        result["run_totals"] = totals
        result["files"] = {row["status"]: int(row["n"]) for row in assets}
        result["sources"] = [dict(row) for row in sources]
        result["recent_failures"] = [
            {"source_id": run["source_id"], "status": run["status"],
             "started_at": run["started_at"], "error": (run["error"] or "")[:300]}
            for run in runs
            if run["status"] in ("failed", "interrupted", "unavailable")
        ][:10]
        return result

    def storage(self, *, now: float) -> dict:
        result = {"kind": "live", "measured_at": now}
        try:
            cache = self.working_cache()
            result["working_cache"] = {
                "usage_bytes": int(cache.usage()),
                "limit_bytes": int(cache.max_bytes),
                "exists": cache.directory.is_dir(),
            }
        except Exception as exc:
            result["working_cache"] = {"error": type(exc).__name__}
        result["workspaces"] = self.workspace_totals()
        sizes = {}
        for label, path in (("auth_database", self.auth_database),
                            ("catalog", self.catalog_path()),
                            ("operations", self.store.path)):
            try:
                total = 0
                for suffix in ("", "-wal"):
                    candidate = Path(str(path) + suffix)
                    if candidate.is_file():
                        total += candidate.stat().st_size
                sizes[label] = total if Path(path).is_file() else None
            except OSError:
                sizes[label] = None
        result["databases"] = sizes
        return result

    def workspace_totals(self) -> dict:
        """Users and bytes under ``<workspace-root>/users`` -- aggregate only.
        The walk is bounded (files and seconds) and cached for ten minutes."""
        with self._workspace_lock:
            cached = self._workspace_cache
            if cached and self.clock() - cached[0] < WORKSPACE_CACHE_S:
                return cached[1]
        root = self.workspace_root() / "users"
        started = time.monotonic()
        users = files = total = 0
        partial = False
        if root.is_dir():
            try:
                entries = list(os.scandir(root))
            except OSError:
                entries = []
            for entry in entries:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                users += 1
                if partial:
                    continue
                for dirpath, _dirnames, filenames in os.walk(entry.path):
                    for name in filenames:
                        try:
                            total += os.lstat(os.path.join(dirpath, name)).st_size
                        except OSError:
                            continue
                        files += 1
                    if files >= WORKSPACE_SCAN_FILES or time.monotonic() - started > WORKSPACE_SCAN_S:
                        partial = True
                        break
        data = {"exists": root.is_dir(), "users": users, "files": files, "bytes": total,
                "partial": partial, "measured_at": self.clock()}
        with self._workspace_lock:
            self._workspace_cache = (self.clock(), data)
        return data
