"""SQLite state of LIVIST: approved inputs, generation jobs and publication
requests (one connection per call, WAL, like the Frozen Legacies catalog).

Jobs follow the Frozen Legacies indexing-run lifecycle: the gateway queues a
job and starts one worker process for it; the worker claims it with its PID,
writes a heartbeat, and finishes it. A job whose worker disappeared is marked
``interrupted`` by :meth:`LivistStore.reconcile_jobs`, with a reason. A retry
is a new job that records the job it repeats (``retry_of``); nothing of the
earlier job directory is reused.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from . import settings

BUSY_TIMEOUT_S = 10
ACTIVE = ("queued", "running")
JOB_STATUSES = ("queued", "running", "completed", "failed", "cancelled", "timed_out",
                "interrupted")
REQUEST_STATUSES = ("pending", "approved", "rejected", "published", "failed")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS livist_sources (
    name TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    location TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_by TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE (kind, location)
);
CREATE TABLE IF NOT EXISTS livist_jobs (
    job_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    workdir TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    heartbeat_at REAL,
    pid INTEGER,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    timeout_s INTEGER NOT NULL,
    exit_code INTEGER,
    error TEXT,
    config_sha256 TEXT,
    validation_status TEXT,
    generator_pid INTEGER,
    retry_of TEXT
);
CREATE INDEX IF NOT EXISTS idx_livist_jobs_owner ON livist_jobs (owner_id, created_at);
CREATE INDEX IF NOT EXISTS idx_livist_jobs_status ON livist_jobs (status);
CREATE TABLE IF NOT EXISTS livist_publications (
    request_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    status TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    plan_sha256 TEXT NOT NULL,
    allow_overwrite INTEGER NOT NULL DEFAULT 0,
    requested_by TEXT NOT NULL,
    requested_at REAL NOT NULL,
    decided_by TEXT,
    decided_at REAL,
    note TEXT,
    result_json TEXT
);
"""
#: columns added after the first release, created on older databases
_ADDED_COLUMNS = (("livist_jobs", "generator_pid", "INTEGER"),
                  ("livist_jobs", "retry_of", "TEXT"))

NEVER_STARTED = ("The generation worker never started (the server restarted or the worker "
                 "could not run before it began). Nothing was generated; retry to start a "
                 "new job.")
WORKER_GONE = ("The generation worker stopped unexpectedly (it was killed, crashed or the "
               "server restarted while it ran). Files it left are partial and are not "
               "products; retry to start a new job.")
WORKER_SILENT = ("The generation worker stopped responding (no heartbeat for {seconds} s) and "
                 "was stopped. Files it left are partial and are not products; retry to start "
                 "a new job.")


class JobLimitError(RuntimeError):
    """The owner or the host already runs as many jobs as allowed."""


class LivistStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else settings.database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        with self._connect() as db:
            db.executescript(_SCHEMA)
            for table, column, kind in _ADDED_COLUMNS:
                have = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
                if column not in have:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        if new:
            try:
                os.chmod(self.path, 0o640)
            except OSError:
                pass

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_S, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode = WAL")
        db.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_S * 1000}")
        try:
            yield db
        finally:
            db.close()

    # ── approved inputs ─────────────────────────────────────────────
    def add_source(self, *, name: str, kind: str, location: str, description: str,
                   created_by: str) -> dict:
        now = time.time()
        with self._connect() as db:
            try:
                db.execute("INSERT INTO livist_sources (name, kind, location, description,"
                           " enabled, created_by, created_at, updated_at)"
                           " VALUES (?, ?, ?, ?, 1, ?, ?, ?)",
                           (name, kind, location, description[:200], created_by, now, now))
            except sqlite3.IntegrityError:
                raise ValueError("That name or input is already approved.")
        return self.get_source(name)

    def get_source(self, name: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM livist_sources WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None

    def list_sources(self, *, enabled_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM livist_sources"
        if enabled_only:
            sql += " WHERE enabled = 1"
        with self._connect() as db:
            return [dict(r) for r in db.execute(sql + " ORDER BY name")]

    def set_source_enabled(self, name: str, enabled: bool) -> dict | None:
        with self._connect() as db:
            db.execute("UPDATE livist_sources SET enabled = ?, updated_at = ? WHERE name = ?",
                       (int(enabled), time.time(), name))
        return self.get_source(name)

    # ── jobs ────────────────────────────────────────────────────────
    def queue_job(self, *, job_id: str, owner_id: str, workdir: str, sources: list[dict],
                  timeout_s: int, max_active: int, per_owner: int = 1,
                  retry_of: str | None = None) -> dict:
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                mine = db.execute("SELECT COUNT(*) FROM livist_jobs WHERE owner_id = ? AND"
                                  " status IN ('queued', 'running')", (owner_id,)).fetchone()[0]
                if mine >= per_owner:
                    raise JobLimitError("You already have a LIVIST generation running.")
                total = db.execute("SELECT COUNT(*) FROM livist_jobs WHERE"
                                   " status IN ('queued', 'running')").fetchone()[0]
                if total >= max_active:
                    raise JobLimitError("The server is running as many LIVIST generations as "
                                        "it allows; try again when one finishes.")
                db.execute("INSERT INTO livist_jobs (job_id, owner_id, workdir, sources_json,"
                           " status, created_at, heartbeat_at, timeout_s, retry_of)"
                           " VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?)",
                           (job_id, owner_id, workdir, json.dumps(sources), now, now, timeout_s,
                            retry_of))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM livist_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return _job(row)

    def list_jobs(self, *, owner_id: str | None = None, limit: int = 50) -> list[dict]:
        sql, args = "SELECT * FROM livist_jobs", []
        if owner_id is not None:
            sql += " WHERE owner_id = ?"
            args.append(owner_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(int(limit))
        with self._connect() as db:
            return [_job(r) for r in db.execute(sql, args)]

    def claim_job(self, job_id: str, pid: int) -> bool:
        now = time.time()
        with self._connect() as db:
            cur = db.execute("UPDATE livist_jobs SET status = 'running', pid = ?, started_at = ?,"
                             " heartbeat_at = ? WHERE job_id = ? AND status = 'queued'",
                             (pid, now, now, job_id))
            return cur.rowcount == 1

    def set_generator_pid(self, job_id: str, pid: int | None) -> None:
        """The process (and process group) running LIVIST's ``scripts/generate``,
        so a generator orphaned by a killed worker can be stopped."""
        with self._connect() as db:
            db.execute("UPDATE livist_jobs SET generator_pid = ? WHERE job_id = ?", (pid, job_id))

    def heartbeat(self, job_id: str) -> bool:
        """Record liveness; returns whether cancellation was requested."""
        with self._connect() as db:
            db.execute("UPDATE livist_jobs SET heartbeat_at = ? WHERE job_id = ?"
                       " AND status = 'running'", (time.time(), job_id))
            row = db.execute("SELECT cancel_requested FROM livist_jobs WHERE job_id = ?",
                             (job_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def request_cancel(self, job_id: str) -> dict | None:
        now = time.time()
        with self._connect() as db:
            db.execute("UPDATE livist_jobs SET cancel_requested = 1 WHERE job_id = ?"
                       " AND status IN ('queued', 'running')", (job_id,))
            db.execute("UPDATE livist_jobs SET status = 'cancelled', finished_at = ?,"
                       " error = 'Cancelled before it started.'"
                       " WHERE job_id = ? AND status = 'queued'", (now, job_id))
        return self.get_job(job_id)

    def finish_job(self, job_id: str, *, status: str, exit_code: int | None = None,
                   error: str | None = None, config_sha256: str | None = None,
                   validation_status: str | None = None) -> None:
        if status not in JOB_STATUSES or status in ACTIVE:
            raise ValueError(f"invalid final status {status!r}")
        with self._connect() as db:
            db.execute("UPDATE livist_jobs SET status = ?, finished_at = ?, heartbeat_at = ?,"
                       " exit_code = ?, error = ?, config_sha256 = COALESCE(?, config_sha256),"
                       " validation_status = COALESCE(?, validation_status)"
                       " WHERE job_id = ? AND status IN ('queued', 'running')",
                       (status, time.time(), time.time(), exit_code, (error or None) and error[:2000],
                        config_sha256, validation_status, job_id))

    def set_config_hash(self, job_id: str, sha256: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE livist_jobs SET config_sha256 = ? WHERE job_id = ?",
                       (sha256, job_id))

    def set_validation(self, job_id: str, status: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE livist_jobs SET validation_status = ? WHERE job_id = ?",
                       (status, job_id))

    def reconcile_jobs(self, *, stale_after_s: float = 90.0, is_alive=None,
                       on_interrupted=None) -> list[str]:
        """Mark jobs whose worker is gone ``interrupted`` with the reason;
        ``on_interrupted(row)`` is then called for each (to stop what is left
        of it), and its failure never undoes the marking."""
        now = time.time()
        ended = []
        with self._connect() as db:
            rows = db.execute("SELECT job_id, pid, generator_pid, workdir, status, heartbeat_at,"
                              " created_at FROM livist_jobs"
                              " WHERE status IN ('queued', 'running')").fetchall()
            for row in rows:
                beat = row["heartbeat_at"] or row["created_at"]
                reason = None
                if row["status"] == "queued":
                    if now - beat > stale_after_s:
                        reason = NEVER_STARTED
                elif row["pid"] and is_alive is not None and not is_alive(row["pid"]):
                    reason = WORKER_GONE
                elif now - beat > stale_after_s:
                    reason = WORKER_SILENT.format(seconds=int(stale_after_s))
                if reason is None:
                    continue
                cur = db.execute("UPDATE livist_jobs SET status = 'interrupted', finished_at = ?,"
                                 " error = ? WHERE job_id = ? AND status IN ('queued', 'running')",
                                 (now, reason, row["job_id"]))
                if cur.rowcount == 1:
                    ended.append(dict(row))
        for row in ended:
            if on_interrupted is not None:
                try:
                    on_interrupted(row)
                except Exception:               # best effort; the job stays interrupted
                    pass
        return [row["job_id"] for row in ended]

    # ── publication requests ────────────────────────────────────────
    def create_request(self, *, request_id: str, job_id: str, plan: dict, plan_sha256: str,
                       allow_overwrite: bool, requested_by: str) -> dict:
        with self._connect() as db:
            db.execute("INSERT INTO livist_publications (request_id, job_id, status, plan_json,"
                       " plan_sha256, allow_overwrite, requested_by, requested_at)"
                       " VALUES (?, ?, 'pending', ?, ?, ?, ?, ?)",
                       (request_id, job_id, json.dumps(plan), plan_sha256, int(allow_overwrite),
                        requested_by, time.time()))
        return self.get_request(request_id)

    def get_request(self, request_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM livist_publications WHERE request_id = ?",
                             (request_id,)).fetchone()
        return _request(row)

    def list_requests(self, limit: int = 50) -> list[dict]:
        with self._connect() as db:
            return [_request(r) for r in db.execute(
                "SELECT * FROM livist_publications ORDER BY requested_at DESC LIMIT ?",
                (int(limit),))]

    def requests_for_job(self, job_id: str) -> list[dict]:
        with self._connect() as db:
            return [_request(r) for r in db.execute(
                "SELECT * FROM livist_publications WHERE job_id = ? ORDER BY requested_at DESC",
                (job_id,))]

    def decide_request(self, request_id: str, *, status: str, decided_by: str,
                       note: str = "", result: dict | None = None,
                       expect: str = "pending") -> bool:
        """Move a request out of ``expect``; false if it already moved."""
        if status not in REQUEST_STATUSES:
            raise ValueError(f"invalid request status {status!r}")
        with self._connect() as db:
            cur = db.execute("UPDATE livist_publications SET status = ?, decided_by ="
                             " COALESCE(decided_by, ?), decided_at = COALESCE(decided_at, ?),"
                             " note = COALESCE(note, ?), result_json = ?"
                             " WHERE request_id = ? AND status = ?",
                             (status, decided_by, time.time(), note[:500] or None,
                              json.dumps(result) if result is not None else None,
                              request_id, expect))
            return cur.rowcount == 1


def _job(row) -> dict | None:
    if row is None:
        return None
    job = dict(row)
    job["sources"] = json.loads(job.pop("sources_json") or "[]")
    return job


def _request(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    item["plan"] = json.loads(item.pop("plan_json") or "{}")
    item["result"] = json.loads(item.pop("result_json") or "null")
    return item
