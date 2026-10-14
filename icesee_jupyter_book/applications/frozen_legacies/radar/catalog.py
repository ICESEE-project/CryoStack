"""The Frozen Legacies radar catalog.

An **index** of the radar files available from installation data sources,
for collections far larger than a dropdown (10,000-100,000+ TIFFs). It holds
metadata only: the files stay in external storage, which remains
authoritative, and are never copied into the repository or into user
workspaces. The catalog can be rebuilt from its data sources at any time
(re-register the sources and index them); catalog IDs are derived from
source and storage key, so a rebuilt catalog gives every file the same ID
and user work referencing it resolves again.

Persistence follows the CryoStack auth database (``icesee_auth.storage``):
SQLite in ``var/`` (``$CRYOSTACK_FROZEN_LEGACIES_CATALOG``), WAL journal (many
readers alongside one writer), a 30 s busy timeout, ``CREATE TABLE IF NOT
EXISTS`` plus additive column migrations. Every public method is one
transaction; the indexer writes in batches of 500 rows.

Tables
------
``data_sources``      external storage locations registered by maintainers;
                      ``config`` is non-secret (for ``local``: the root).
``radar_assets``      one row per file: identity, metadata, navigation
                      geometry, index status. ``storage_key`` and ``nav_key``
                      never leave the server.
``index_runs``        one row per indexing run.
``user_asset_state``  per-user processing state of catalog files (a derived,
                      rebuildable index of the users' workspaces -- the
                      sessions themselves stay in the workspaces).
``user_observations`` per-user index of picked observations for the map
                      (derived from each asset's ``observations.json``;
                      rebuildable; queried by owner and bounding box).
``submissions``       scientific review: one row per submitted snapshot
                      (see :mod:`radar.review`); authoritative.
``published_observations``  observations of published submissions -- the
                      shared, reviewed dataset product (no personal data).

Identity
--------
``catalog_id = "cat-" + sha256(source_id + NUL + storage_key)[:24]``: two
files with the same name in different sources or folders are different
assets. A file that moves within its source (same name, size and version)
gets a new ID; the old row is kept and points to it (``moved_to``), so user
work on the old ID keeps opening the file.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


CATALOG_ENV = "CRYOSTACK_FROZEN_LEGACIES_CATALOG"
DEFAULT_CATALOG = Path(__file__).resolve().parents[4] / "var" / "frozen_legacies_catalog.db"

CATALOG_KEY_PREFIX = "cat-"
_CATALOG_KEY = re.compile(r"cat-[0-9a-f]{24}")
_SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9-]{1,62}")
_DATASET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")

#: index status of a file
#:   indexed     -- listed and readable
#:   changed     -- (transitional) content changed since the last run
#:   invalid     -- listed, but not a usable radar TIFF
#:   unavailable -- listed, but could not be read this time (transient)
#:   missing     -- no longer listed; the row and user work are kept
#:   moved       -- the same file now has another key (see moved_to)
ASSET_STATUSES = ("indexed", "changed", "invalid", "unavailable", "missing", "moved")
AVAILABLE = ("indexed", "changed")
SOURCE_STATUSES = ("enabled", "disabled")

#: per-user processing states
PROCESSING_STATES = (
    "unprocessed", "manual_in_progress", "manual_completed",
    "automatic_pending", "automatic_running", "automatic_completed", "automatic_failed",
)
#: the user's review states of catalog files (from ``submissions``)
REVIEW_STATES = ("needs_review", "returned", "published")
_REVIEW_STATUS = {"needs_review": "submitted", "returned": "returned", "published": "published"}

MAX_PAGE_SIZE = 100
BUSY_TIMEOUT_S = 30


class CatalogError(ValueError):
    """A catalog request or registration was rejected."""


def catalog_path() -> Path:
    configured = (os.environ.get(CATALOG_ENV) or "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_CATALOG


def asset_key(source_id: str, storage_key: str) -> str:
    """Stable catalog ID of a file in a source (independent of its content)."""
    digest = hashlib.sha256(f"{source_id}\0{storage_key}".encode("utf-8")).hexdigest()
    return CATALOG_KEY_PREFIX + digest[:24]


def is_catalog_key(value: object) -> bool:
    return isinstance(value, str) and _CATALOG_KEY.fullmatch(value) is not None


def is_valid_source_id(value: object) -> bool:
    return isinstance(value, str) and _SOURCE_ID.fullmatch(value) is not None


def is_valid_dataset_id(value: object) -> bool:
    return isinstance(value, str) and _DATASET_ID.fullmatch(value) is not None


def flight_number(flight) -> int | None:
    try:
        return int(str(flight))
    except (TypeError, ValueError):
        return None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS data_sources (
    source_id         TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    provider          TEXT NOT NULL,
    dataset_id        TEXT NOT NULL,
    config            TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'enabled',
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL,
    last_index_at     REAL,
    last_index_status TEXT,
    last_index_error  TEXT
);
CREATE TABLE IF NOT EXISTS radar_assets (
    catalog_id       TEXT PRIMARY KEY,
    source_id        TEXT NOT NULL REFERENCES data_sources(source_id),
    dataset_id       TEXT NOT NULL,
    storage_key      TEXT NOT NULL,
    filename         TEXT NOT NULL,
    flight           TEXT,
    cbd_start        INTEGER,
    cbd_end          INTEGER,
    width            INTEGER,
    height           INTEGER,
    mode             TEXT,
    bytes            INTEGER NOT NULL,
    mtime_ns         INTEGER NOT NULL,
    etag             TEXT,
    nav_key          TEXT,
    has_nav          INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL,
    error            TEXT,
    duplicate        INTEGER NOT NULL DEFAULT 0,
    first_indexed_at REAL NOT NULL,
    indexed_at       REAL NOT NULL,
    UNIQUE (source_id, storage_key)
);
CREATE TABLE IF NOT EXISTS index_runs (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL REFERENCES data_sources(source_id),
    started_at  REAL NOT NULL,
    finished_at REAL,
    status      TEXT NOT NULL,
    discovered  INTEGER NOT NULL DEFAULT 0,
    added       INTEGER NOT NULL DEFAULT 0,
    changed     INTEGER NOT NULL DEFAULT 0,
    unchanged   INTEGER NOT NULL DEFAULT 0,
    missing     INTEGER NOT NULL DEFAULT 0,
    invalid     INTEGER NOT NULL DEFAULT 0,
    error       TEXT
);
CREATE TABLE IF NOT EXISTS user_observations (
    owner          TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    asset_id       TEXT NOT NULL,
    catalog_id     TEXT,
    status         TEXT NOT NULL,
    lon            REAL,
    lat            REAL,
    feature        TEXT NOT NULL,
    PRIMARY KEY (owner, observation_id)
);
CREATE TABLE IF NOT EXISTS submissions (
    submission_id     TEXT PRIMARY KEY,
    owner             TEXT NOT NULL,
    submitter_user_id TEXT NOT NULL,
    asset_id          TEXT NOT NULL,
    source_key        TEXT NOT NULL,
    catalog_id        TEXT,
    dataset_id        TEXT,
    filename          TEXT NOT NULL,
    flight            TEXT,
    cbd_start         INTEGER,
    cbd_end           INTEGER,
    workflow          TEXT NOT NULL,
    producer          TEXT NOT NULL,
    producer_version  TEXT NOT NULL,
    session_revision  INTEGER NOT NULL,
    completed_at      REAL,
    source_version    TEXT,
    navigation        TEXT,
    observation_count INTEGER NOT NULL,
    positioned_count  INTEGER NOT NULL,
    products          TEXT NOT NULL,
    note              TEXT,
    status            TEXT NOT NULL,
    submitted_at      REAL NOT NULL,
    reviewer_user_id  TEXT,
    decided_at        REAL,
    decision_note     TEXT,
    accepted_unverified INTEGER NOT NULL DEFAULT 0,
    published_at      REAL,
    supersedes        TEXT,
    superseded_by     TEXT,
    withdrawn_at      REAL,
    withdrawn_by      TEXT,
    withdraw_reason   TEXT
);
CREATE TABLE IF NOT EXISTS published_observations (
    observation_id TEXT PRIMARY KEY,
    submission_id  TEXT NOT NULL REFERENCES submissions(submission_id),
    dataset_id     TEXT,
    catalog_id     TEXT,
    flight         TEXT,
    cbd            INTEGER,
    lon            REAL,
    lat            REAL,
    feature        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_asset_state (
    owner       TEXT NOT NULL,
    catalog_id  TEXT NOT NULL,
    asset_id    TEXT NOT NULL,
    manual      TEXT,
    automatic   TEXT,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (owner, catalog_id)
);
"""

#: columns added after the first schema (additive migrations)
_ADDED_COLUMNS = {
    "radar_assets": {
        "flight_num": "INTEGER",
        "missing_since": "REAL",
        "moved_to": "TEXT",
        "track": "TEXT",
        "min_lat": "REAL", "max_lat": "REAL", "min_lon": "REAL", "max_lon": "REAL",
    },
    "data_sources": {
        "last_success_at": "REAL",
        "last_check_at": "REAL",
        "last_check_ok": "INTEGER",
        "last_check_message": "TEXT",
    },
    "index_runs": {
        "unavailable": "INTEGER NOT NULL DEFAULT 0",
        "moved": "INTEGER NOT NULL DEFAULT 0",
        "full": "INTEGER NOT NULL DEFAULT 0",
        "allow_mass_missing": "INTEGER NOT NULL DEFAULT 0",
        "retry_invalid": "INTEGER NOT NULL DEFAULT 0",
        "requested_by": "TEXT",
        "pid": "INTEGER",
        "heartbeat_at": "REAL",
        "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
    },
}

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_radar_assets_order
    ON radar_assets(dataset_id, flight_num, flight, cbd_start, filename);
CREATE INDEX IF NOT EXISTS idx_radar_assets_flight
    ON radar_assets(flight, cbd_start);
CREATE INDEX IF NOT EXISTS idx_radar_assets_status ON radar_assets(status);
CREATE INDEX IF NOT EXISTS idx_radar_assets_filename ON radar_assets(filename);
CREATE INDEX IF NOT EXISTS idx_radar_assets_source ON radar_assets(source_id, status);
CREATE INDEX IF NOT EXISTS idx_radar_assets_lat ON radar_assets(min_lat, max_lat);
CREATE INDEX IF NOT EXISTS idx_index_runs_source ON index_runs(source_id, started_at);
CREATE INDEX IF NOT EXISTS idx_user_asset_state_catalog ON user_asset_state(catalog_id);
CREATE INDEX IF NOT EXISTS idx_user_observations_asset ON user_observations(owner, asset_id);
CREATE INDEX IF NOT EXISTS idx_user_observations_lat ON user_observations(owner, lat);
CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status, submitted_at);
CREATE INDEX IF NOT EXISTS idx_submissions_owner ON submissions(owner, asset_id);
CREATE INDEX IF NOT EXISTS idx_submissions_catalog ON submissions(catalog_id, status);
CREATE INDEX IF NOT EXISTS idx_published_observations_flight
    ON published_observations(dataset_id, flight);
CREATE INDEX IF NOT EXISTS idx_published_observations_lat ON published_observations(lat, lon);
CREATE INDEX IF NOT EXISTS idx_published_observations_submission
    ON published_observations(submission_id);
"""

#: columns of an asset that may be shown to users (no storage keys)
PUBLIC_ASSET_COLUMNS = (
    "catalog_id", "source_id", "dataset_id", "filename", "flight", "cbd_start",
    "cbd_end", "width", "height", "mode", "bytes", "has_nav", "status", "duplicate",
    "first_indexed_at", "indexed_at",
)

_RUN_COUNTS = ("discovered", "added", "changed", "unchanged", "missing",
               "invalid", "unavailable", "moved")

_ORDER = "a.dataset_id, a.flight_num, a.flight, a.cbd_start, a.filename"


class RadarCatalog:
    """SQLite-backed radar catalog (one connection per call)."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else catalog_path()
        self._version = 0
        self._summary_cache: dict = {}
        self._cache_lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        with self._connect() as db:
            db.executescript(_SCHEMA)
            for table, columns in _ADDED_COLUMNS.items():
                present = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
                for column, kind in columns.items():
                    if column not in present:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            db.execute("UPDATE radar_assets SET flight_num = CAST(flight AS INTEGER)"
                       " WHERE flight_num IS NULL AND flight GLOB '[0-9]*'")
            db.executescript(_INDEXES)
        if new:
            try:
                os.chmod(self.path, 0o640)       # installation data: not world-readable
            except OSError:
                pass

    def _changed(self) -> None:
        with self._cache_lock:
            self._version += 1
            self._summary_cache.clear()

    def _signature(self, db) -> tuple:
        """Changes made by this or another process (sources and runs)."""
        row = db.execute("SELECT COUNT(*), MAX(updated_at), MAX(last_index_at),"
                         " GROUP_CONCAT(status) FROM data_sources").fetchone()
        return (self._version, tuple(row))

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_S)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        db.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_S * 1000}")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    # ── data sources ───────────────────────────────────────────────────
    def add_source(self, *, source_id: str, name: str, provider: str, dataset_id: str,
                   config: dict) -> dict:
        if not is_valid_source_id(source_id):
            raise CatalogError("Source IDs are 2-63 lowercase letters, digits and hyphens.")
        if not is_valid_dataset_id(dataset_id):
            raise CatalogError("Invalid dataset ID.")
        name = str(name or "").strip()[:120]
        if not name:
            raise CatalogError("A data source needs a name.")
        now = time.time()
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO data_sources (source_id, name, provider, dataset_id, config,"
                    " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (source_id, name, provider, dataset_id,
                     json.dumps(config, sort_keys=True), now, now))
        except sqlite3.IntegrityError:
            raise CatalogError("A data source with this ID already exists.")
        return self.get_source(source_id)

    def get_source(self, source_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM data_sources WHERE source_id = ?",
                             (source_id,)).fetchone()
        if row is None:
            return None
        source = dict(row)
        source["config"] = json.loads(source["config"])
        return source

    def list_sources(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM data_sources ORDER BY name").fetchall()
            counts = {
                (r["source_id"], r["status"]): r["n"]
                for r in db.execute(
                    "SELECT source_id, status, COUNT(*) AS n FROM radar_assets"
                    " GROUP BY source_id, status")
            }
            duplicates = dict(db.execute(
                "SELECT source_id, COUNT(*) FROM radar_assets WHERE duplicate = 1"
                " GROUP BY source_id").fetchall())
            processed = dict(db.execute(
                "SELECT a.source_id, COUNT(DISTINCT a.catalog_id) FROM radar_assets a"
                " JOIN user_asset_state u ON u.catalog_id = a.catalog_id"
                " WHERE u.manual = 'manual_completed' OR u.automatic = 'automatic_completed'"
                " GROUP BY a.source_id").fetchall())
        out = []
        for row in rows:
            source = dict(row)
            source["config"] = json.loads(source["config"])
            sid = source["source_id"]
            source["counts"] = {s: counts.get((sid, s), 0) for s in ASSET_STATUSES}
            source["counts"]["total"] = sum(source["counts"].values())
            source["counts"]["duplicates"] = duplicates.get(sid, 0)
            source["counts"]["processed_by_anyone"] = processed.get(sid, 0)
            out.append(source)
        return out

    def set_source_status(self, source_id: str, status: str) -> None:
        if status not in SOURCE_STATUSES:
            raise CatalogError("Unknown source status.")
        with self._connect() as db:
            db.execute("UPDATE data_sources SET status = ?, updated_at = ? WHERE source_id = ?",
                       (status, time.time(), source_id))
        self._changed()


    def record_check(self, source_id: str, result: dict) -> None:
        with self._connect() as db:
            db.execute("UPDATE data_sources SET last_check_at = ?, last_check_ok = ?,"
                       " last_check_message = ? WHERE source_id = ?",
                       (time.time(), 1 if result.get("ok") else 0,
                        str(result.get("message") or "")[:300], source_id))

    # ── indexing support ───────────────────────────────────────────────
    def start_run(self, source_id: str) -> int:
        with self._connect() as db:
            cur = db.execute("INSERT INTO index_runs (source_id, started_at, status, heartbeat_at)"
                             " VALUES (?, ?, 'running', ?)", (source_id, time.time(), time.time()))
            return int(cur.lastrowid)

    def queue_run(self, source_id: str, *, full: bool = False, allow_mass_missing: bool = False,
                  retry_invalid: bool = False, requested_by: str | None = None) -> int | None:
        """A new ``queued`` run, or ``None`` when the source already has an
        active (queued/running) run -- at most one run per source."""
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute("SELECT 1 FROM index_runs WHERE source_id = ? AND status IN"
                                " ('queued', 'running')", (source_id,)).fetchone()
            if active is not None:
                db.execute("ROLLBACK")
                return None
            cur = db.execute(
                "INSERT INTO index_runs (source_id, started_at, status, heartbeat_at, full,"
                " allow_mass_missing, retry_invalid, requested_by)"
                " VALUES (?, ?, 'queued', ?, ?, ?, ?, ?)",
                (source_id, now, now, int(full), int(allow_mass_missing), int(retry_invalid),
                 requested_by))
            run_id = int(cur.lastrowid)
            db.execute("COMMIT")
        return run_id

    def get_run(self, run_id: int) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM index_runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row is not None else None

    def active_run(self, source_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM index_runs WHERE source_id = ? AND status IN"
                             " ('queued', 'running') ORDER BY run_id DESC LIMIT 1",
                             (source_id,)).fetchone()
        return dict(row) if row is not None else None

    def claim_run(self, run_id: int, pid: int) -> bool:
        """The worker takes a queued run; false if it is no longer queued."""
        with self._connect() as db:
            cur = db.execute("UPDATE index_runs SET status = 'running', pid = ?, heartbeat_at = ?"
                             " WHERE run_id = ? AND status = 'queued'", (pid, time.time(), run_id))
            return cur.rowcount == 1

    def update_progress(self, run_id: int, counts: dict) -> bool:
        """Store progress and the heartbeat; returns whether cancellation was requested."""
        with self._connect() as db:
            db.execute(
                "UPDATE index_runs SET heartbeat_at = ?, discovered = ?, added = ?, changed = ?,"
                " unchanged = ?, missing = ?, invalid = ?, unavailable = ?, moved = ?"
                " WHERE run_id = ? AND status = 'running'",
                (time.time(), *(int(counts.get(k, 0)) for k in _RUN_COUNTS), run_id))
            row = db.execute("SELECT cancel_requested FROM index_runs WHERE run_id = ?",
                             (run_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def request_cancel(self, run_id: int) -> dict | None:
        """Ask a run to stop. A queued run is cancelled at once; a running one
        stops at its next batch."""
        now = time.time()
        with self._connect() as db:
            db.execute("UPDATE index_runs SET cancel_requested = 1 WHERE run_id = ?"
                       " AND status IN ('queued', 'running')", (run_id,))
            row = db.execute("SELECT * FROM index_runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is not None and row["status"] == "queued":
                self._end_run(db, row["run_id"], row["source_id"], "cancelled",
                              "Cancelled before it started.", now)
                row = db.execute("SELECT * FROM index_runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row is not None else None

    def cancel_requested(self, run_id: int) -> bool:
        with self._connect() as db:
            row = db.execute("SELECT cancel_requested FROM index_runs WHERE run_id = ?",
                             (run_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def reconcile_runs(self, *, stale_after_s: float = 90.0, is_alive=None) -> list[int]:
        """Mark runs whose worker is gone as ``interrupted`` (after a restart
        or crash): no heartbeat for ``stale_after_s``, or ``is_alive(pid)``
        false. Interrupted runs mark nothing missing; a retry re-indexes
        incrementally from what was already stored."""
        now = time.time()
        ended = []
        with self._connect() as db:
            rows = db.execute("SELECT run_id, source_id, pid, heartbeat_at, started_at, status"
                              " FROM index_runs WHERE status IN ('queued', 'running')").fetchall()
            for row in rows:
                beat = row["heartbeat_at"] or row["started_at"]
                dead = now - beat > stale_after_s
                if (not dead and row["status"] == "running" and row["pid"]
                        and is_alive is not None and not is_alive(row["pid"])):
                    dead = True
                if dead:
                    self._end_run(db, row["run_id"], row["source_id"], "interrupted",
                                  "The indexing worker stopped unexpectedly (server restart or "
                                  "crash). Files indexed so far are kept; retry to continue.", now)
                    ended.append(row["run_id"])
        if ended:
            self._changed()
        return ended

    @staticmethod
    def _end_run(db, run_id, source_id, status, error, now) -> None:
        db.execute("UPDATE index_runs SET finished_at = ?, status = ?, error = ?"
                   " WHERE run_id = ?", (now, status, error, run_id))
        db.execute("UPDATE data_sources SET last_index_at = ?, last_index_status = ?,"
                   " last_index_error = ? WHERE source_id = ?", (now, status, error, source_id))

    def finish_run(self, run_id: int, source_id: str, *, status: str, counts: dict,
                   error: str | None = None) -> None:
        now = time.time()
        with self._connect() as db:
            db.execute(
                "UPDATE index_runs SET finished_at = ?, status = ?, heartbeat_at = ?,"
                " discovered = ?, added = ?, changed = ?, unchanged = ?, missing = ?,"
                " invalid = ?, unavailable = ?, moved = ?, error = ? WHERE run_id = ?",
                (now, status, now, *(int(counts.get(k, 0)) for k in _RUN_COUNTS), error, run_id))
            db.execute(
                "UPDATE data_sources SET last_index_at = ?, last_index_status = ?,"
                " last_index_error = ? WHERE source_id = ?", (now, status, error, source_id))
            if status == "completed":
                db.execute("UPDATE data_sources SET last_success_at = ? WHERE source_id = ?",
                           (now, source_id))
        self._changed()

    def runs(self, source_id: str, limit: int = 10) -> list[dict]:
        with self._connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM index_runs WHERE source_id = ? ORDER BY run_id DESC LIMIT ?",
                (source_id, limit))]

    def recent_errors(self, source_id: str, limit: int = 5) -> list[dict]:
        """Latest file-level problems of a source (file names only, no keys)."""
        with self._connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT filename, status, error, indexed_at FROM radar_assets"
                " WHERE source_id = ? AND status IN ('invalid', 'unavailable')"
                " ORDER BY indexed_at DESC LIMIT ?", (source_id, limit))]

    def known_objects(self, source_id: str) -> dict[str, dict]:
        """storage_key -> identity/version fields, for incremental indexing."""
        with self._connect() as db:
            return {r["storage_key"]: dict(r) for r in db.execute(
                "SELECT catalog_id, storage_key, filename, bytes, mtime_ns, etag, status"
                " FROM radar_assets WHERE source_id = ?", (source_id,))}

    _COLUMNS = ("catalog_id", "source_id", "dataset_id", "storage_key", "filename",
                "flight", "flight_num", "cbd_start", "cbd_end", "width", "height", "mode",
                "bytes", "mtime_ns", "etag", "nav_key", "has_nav", "status", "error",
                "track", "min_lat", "max_lat", "min_lon", "max_lon",
                "first_indexed_at", "indexed_at")

    def upsert_assets(self, rows: list[dict]) -> None:
        if not rows:
            return
        columns = self._COLUMNS
        placeholders = ", ".join("?" for _ in columns)
        update = ", ".join(f"{c} = excluded.{c}" for c in columns
                           if c not in ("catalog_id", "first_indexed_at"))
        with self._connect() as db:
            db.executemany(
                f"INSERT INTO radar_assets ({', '.join(columns)}) VALUES ({placeholders})"
                f" ON CONFLICT(source_id, storage_key) DO UPDATE SET {update},"
                f" missing_since = NULL, moved_to = NULL",
                [tuple(r.get(c) for c in columns) for r in rows])
        self._changed()


    def mark_missing(self, source_id: str, storage_keys: list[str]) -> None:
        now = time.time()
        with self._connect() as db:
            db.executemany(
                "UPDATE radar_assets SET status = 'missing', indexed_at = ?,"
                " missing_since = COALESCE(missing_since, ?)"
                " WHERE source_id = ? AND storage_key = ?",
                [(now, now, source_id, k) for k in storage_keys])
        self._changed()


    def mark_moved(self, moves: list[tuple[str, str]]) -> None:
        """(old catalog_id, new catalog_id) pairs."""
        with self._connect() as db:
            db.executemany(
                "UPDATE radar_assets SET status = 'moved', moved_to = ?, indexed_at = ?"
                " WHERE catalog_id = ?", [(new, time.time(), old) for old, new in moves])
        self._changed()


    def refresh_duplicates(self, dataset_id: str) -> None:
        """Flag files whose name occurs more than once among a dataset's
        present files (they remain distinct assets)."""
        with self._connect() as db:
            db.execute("UPDATE radar_assets SET duplicate = 0 WHERE dataset_id = ?", (dataset_id,))
            db.execute(
                "UPDATE radar_assets SET duplicate = 1 WHERE dataset_id = ?"
                " AND status IN ('indexed', 'changed', 'invalid', 'unavailable')"
                " AND lower(filename) IN (SELECT lower(filename) FROM radar_assets"
                "  WHERE dataset_id = ? AND status IN ('indexed', 'changed', 'invalid', 'unavailable')"
                "  GROUP BY lower(filename) HAVING COUNT(*) > 1)", (dataset_id, dataset_id))

    # ── lookups ────────────────────────────────────────────────────────
    def resolve(self, catalog_id: str, *, follow_moves: bool = True) -> dict | None:
        """Internal record of an asset (server use only), following moves."""
        if not is_catalog_key(catalog_id):
            return None
        with self._connect() as db:
            for _ in range(8):                       # bounded move chain
                row = db.execute(
                    "SELECT a.*, s.provider, s.config, s.status AS source_status,"
                    " s.name AS source_name FROM radar_assets a JOIN data_sources s"
                    " USING (source_id) WHERE a.catalog_id = ?", (catalog_id,)).fetchone()
                if row is None:
                    return None
                if not (follow_moves and row["status"] == "moved" and row["moved_to"]):
                    break
                catalog_id = row["moved_to"]
        record = dict(row)
        record["config"] = json.loads(record["config"])
        return record

    def get_public(self, catalog_id: str) -> dict | None:
        if not is_catalog_key(catalog_id):
            return None
        cols = ", ".join(f"a.{c}" for c in PUBLIC_ASSET_COLUMNS)
        with self._connect() as db:
            row = db.execute(f"SELECT {cols} FROM radar_assets a WHERE a.catalog_id = ?",
                             (catalog_id,)).fetchone()
        return _public(dict(row)) if row else None

    # ── search ─────────────────────────────────────────────────────────
    def _filters(self, *, dataset_id=None, flight=None, status=None, q=None, cbd=None,
                 owner=None, state=None, catalog_id=None):
        where = ["a.source_id IN (SELECT source_id FROM data_sources WHERE status = 'enabled')"]
        args: list = []
        if catalog_id:
            where.append("a.catalog_id = ?")
            args.append(catalog_id)
        if dataset_id:
            where.append("a.dataset_id = ?")
            args.append(dataset_id)
        if flight:
            where.append("a.flight = ?")
            args.append(str(flight))
        if status:
            where.append("a.status = ?")
            args.append(status)
        else:
            where.append("a.status IN ('indexed', 'changed')")
        if q:
            where.append("a.filename LIKE ? ESCAPE '\\'")
            escaped = str(q).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            args.append(f"%{escaped}%")
        if cbd is not None:
            where.append("a.cbd_start IS NOT NULL AND ? BETWEEN min(a.cbd_start, a.cbd_end)"
                         " AND max(a.cbd_start, a.cbd_end)")
            args.append(int(cbd))
        if state in REVIEW_STATES:
            if owner is None:
                raise CatalogError("A processing-state filter needs a user.")
            where.append("a.catalog_id IN (SELECT catalog_id FROM submissions"
                         " WHERE owner = ? AND status = ?)")
            args += [owner, _REVIEW_STATUS[state]]
        elif state is not None:
            if owner is None:
                raise CatalogError("A processing-state filter needs a user.")
            # driven from the user's (small) state rows via their primary key
            if state == "unprocessed":
                where.append("a.catalog_id NOT IN (SELECT catalog_id FROM user_asset_state"
                             " WHERE owner = ? AND (manual IS NOT NULL OR automatic IS NOT NULL))")
                args.append(owner)
            else:
                column = "manual" if state.startswith("manual") else "automatic"
                where.append(f"a.catalog_id IN (SELECT catalog_id FROM user_asset_state"
                             f" WHERE owner = ? AND {column} = ?)")
                args += [owner, state]
        return " AND ".join(where), args

    def search(self, *, page: int = 1, page_size: int = 25, owner=None, **filters) -> dict:
        """Server-side filtered, paginated search (public columns only).

        Pagination is LIMIT/OFFSET over an index-ordered scan; ``page_size``
        is capped at :data:`MAX_PAGE_SIZE`. ``owner`` (a workspace safe ID)
        adds the user's processing state to each item and enables ``state``.
        """
        page = max(1, int(page))
        page_size = max(1, min(MAX_PAGE_SIZE, int(page_size)))
        clause, args = self._filters(owner=owner, **filters)
        cols = ", ".join(f"a.{c}" for c in PUBLIC_ASSET_COLUMNS)
        with self._connect() as db:
            total = db.execute(f"SELECT COUNT(*) FROM radar_assets a WHERE {clause}",
                               args).fetchone()[0]
            rows = db.execute(
                f"SELECT {cols} FROM radar_assets a"
                f" WHERE {clause} ORDER BY {_ORDER} LIMIT ? OFFSET ?",
                args + [page_size, (page - 1) * page_size]).fetchall()
            items = [_public(dict(r)) for r in rows]
            if owner is not None and items:
                ids = [i["catalog_id"] for i in items]
                states = {r["catalog_id"]: r for r in db.execute(
                    f"SELECT catalog_id, manual, automatic FROM user_asset_state"
                    f" WHERE owner = ? AND catalog_id IN ({', '.join('?' for _ in ids)})",
                    [owner] + ids)}
                reviews = {}
                for r in db.execute(
                        f"SELECT catalog_id, status FROM submissions WHERE owner = ?"
                        f" AND status IN ('submitted', 'returned', 'published')"
                        f" AND catalog_id IN ({', '.join('?' for _ in ids)})", [owner] + ids):
                    reviews.setdefault(r["catalog_id"], set()).add(r["status"])
                for item in items:
                    row = states.get(item["catalog_id"])
                    found = [s for s in ((row["manual"], row["automatic"]) if row else ()) if s]
                    found += [state for state, status in _REVIEW_STATUS.items()
                              if status in reviews.get(item["catalog_id"], ())]
                    item["processing"] = found or ["unprocessed"]
        return {"items": items, "total": total, "page": page, "page_size": page_size,
                "pages": max(1, -(-total // page_size))}

    def summary(self, *, dataset_id=None, owner=None) -> dict:
        """Datasets and flights with file counts and, for ``owner``, the user's
        processing progress per flight -- from indexed state, not a scan.

        The per-flight aggregates are cached until the catalog changes; the
        user's progress is computed from their own state rows."""
        clause, args = self._filters(dataset_id=dataset_id)
        with self._connect() as db:
            key = (dataset_id, self._signature(db))
            with self._cache_lock:
                base = self._summary_cache.get(key)
            if base is None:
                datasets = [dict(r) for r in db.execute(
                    f"SELECT a.dataset_id, COUNT(*) AS assets FROM radar_assets a WHERE {clause}"
                    f" GROUP BY a.dataset_id ORDER BY a.dataset_id", args)]
                flights = [dict(r) for r in db.execute(
                    f"SELECT a.dataset_id, a.flight, COUNT(*) AS assets,"
                    f" MIN(a.cbd_start) AS cbd_min, MAX(a.cbd_end) AS cbd_max,"
                    f" SUM(a.has_nav) AS with_nav, SUM(a.track IS NOT NULL) AS with_track"
                    f" FROM radar_assets a WHERE {clause}"
                    f" GROUP BY a.dataset_id, a.flight ORDER BY a.dataset_id, a.flight_num, a.flight",
                    args)]
                base = {"datasets": datasets, "flights": flights}
                with self._cache_lock:
                    self._summary_cache[key] = base
            progress = {}
            if owner is not None:
                for r in db.execute(
                        f"SELECT a.dataset_id, a.flight, u.manual, u.automatic, COUNT(*) AS n"
                        f" FROM user_asset_state u JOIN radar_assets a"
                        f" ON a.catalog_id = u.catalog_id"
                        f" WHERE u.owner = ? AND {clause}"
                        f" GROUP BY a.dataset_id, a.flight, u.manual, u.automatic",
                        [owner] + args):
                    counts = progress.setdefault((r["dataset_id"], r["flight"]), {})
                    for state in (r["manual"], r["automatic"]):
                        if state:
                            counts[state] = counts.get(state, 0) + r["n"]
                    if r["manual"] or r["automatic"]:
                        counts["touched"] = counts.get("touched", 0) + r["n"]
            # review progress: everyone's published files, the user's own review states
            published = {(r["dataset_id"], r["flight"]): r["n"] for r in db.execute(
                f"SELECT a.dataset_id, a.flight, COUNT(DISTINCT a.catalog_id) AS n"
                f" FROM submissions s JOIN radar_assets a ON a.catalog_id = s.catalog_id"
                f" WHERE s.status = 'published' AND {clause}"
                f" GROUP BY a.dataset_id, a.flight", args)}
            awaiting = {(r["dataset_id"], r["flight"]): r["n"] for r in db.execute(
                f"SELECT a.dataset_id, a.flight, COUNT(DISTINCT a.catalog_id) AS n"
                f" FROM submissions s JOIN radar_assets a ON a.catalog_id = s.catalog_id"
                f" WHERE s.status = 'submitted' AND {clause}"
                f" GROUP BY a.dataset_id, a.flight", args)}
            mine_review = {}
            if owner is not None:
                for r in db.execute(
                        f"SELECT a.dataset_id, a.flight, s.status, COUNT(DISTINCT a.catalog_id) AS n"
                        f" FROM submissions s JOIN radar_assets a ON a.catalog_id = s.catalog_id"
                        f" WHERE s.owner = ? AND s.status IN ('submitted', 'returned', 'published')"
                        f" AND {clause} GROUP BY a.dataset_id, a.flight, s.status",
                        [owner] + args):
                    mine_review.setdefault((r["dataset_id"], r["flight"]), {})[r["status"]] = r["n"]
        flights = [dict(f) for f in base["flights"]]
        for flight in flights:
            key = (flight["dataset_id"], flight["flight"])
            flight["published"] = published.get(key, 0)
            flight["awaiting_review"] = awaiting.get(key, 0)
        if owner is not None:
            for flight in flights:
                key = (flight["dataset_id"], flight["flight"])
                counts = progress.get(key, {})
                flight["mine"] = {s: counts.get(s, 0) for s in PROCESSING_STATES[1:]}
                flight["mine"]["unprocessed"] = flight["assets"] - counts.get("touched", 0)
                review = mine_review.get(key, {})
                flight["mine"]["needs_review"] = review.get("submitted", 0)
                flight["mine"]["returned"] = review.get("returned", 0)
                flight["mine"]["published"] = review.get("published", 0)
        total = sum(d["assets"] for d in base["datasets"])
        return {"total": total, "datasets": [dict(d) for d in base["datasets"]],
                "flights": flights}

    def segments(self, *, dataset_id=None, flight=None, bbox=None, limit: int = 5000) -> dict:
        """Files with real navigation tracks, as GeoJSON (no positions are
        invented for files without navigation)."""
        clause, args = self._filters(dataset_id=dataset_id, flight=flight)
        unplaced_clause, unplaced_args = clause + " AND a.track IS NULL", list(args)
        clause += " AND a.track IS NOT NULL"
        if bbox is not None:
            min_lon, min_lat, max_lon, max_lat = bbox
            clause += " AND a.max_lat >= ? AND a.min_lat <= ?"
            args += [min_lat, max_lat]
            if min_lon <= max_lon:
                clause += " AND a.max_lon >= ? AND a.min_lon <= ?"
                args += [min_lon, max_lon]
        with self._connect() as db:
            rows = db.execute(
                f"SELECT a.catalog_id, a.dataset_id, a.flight, a.filename, a.cbd_start,"
                f" a.cbd_end, a.track FROM radar_assets a WHERE {clause}"
                f" ORDER BY {_ORDER} LIMIT ?", args + [int(limit) + 1]).fetchall()
            # files without navigation: counted, never placed on the map
            unplaced = db.execute(
                f"SELECT COUNT(*) FROM radar_assets a WHERE {unplaced_clause}",
                unplaced_args).fetchone()[0]
        truncated = len(rows) > limit
        features = []
        for r in rows[:limit]:
            coords = json.loads(r["track"])
            geometry = ({"type": "Point", "coordinates": coords[0]} if len(coords) == 1
                        else {"type": "LineString", "coordinates": coords})
            features.append({"type": "Feature", "id": r["catalog_id"], "geometry": geometry,
                             "properties": {"catalog_id": r["catalog_id"],
                                            "dataset_id": r["dataset_id"], "flight": r["flight"],
                                            "filename": r["filename"], "cbd_start": r["cbd_start"],
                                            "cbd_end": r["cbd_end"], "scope": "catalog"}})
        return {"type": "FeatureCollection", "features": features,
                "summary": {"returned": len(features), "truncated": truncated,
                            "unplaced": int(unplaced)}}

    def total(self) -> int:
        clause, args = self._filters()
        with self._connect() as db:
            return db.execute(f"SELECT COUNT(*) FROM radar_assets a WHERE {clause}",
                              args).fetchone()[0]

    # ── per-user processing state (derived index of user workspaces) ───
    def set_user_state(self, owner: str, catalog_id: str, asset_id: str, *,
                       manual: str | None, automatic: str | None) -> None:
        with self._connect() as db:
            if manual is None and automatic is None:
                db.execute("DELETE FROM user_asset_state WHERE owner = ? AND catalog_id = ?",
                           (owner, catalog_id))
                return
            db.execute(
                "INSERT INTO user_asset_state (owner, catalog_id, asset_id, manual, automatic,"
                " updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(owner, catalog_id) DO UPDATE"
                " SET asset_id = excluded.asset_id, manual = excluded.manual,"
                " automatic = excluded.automatic, updated_at = excluded.updated_at",
                (owner, catalog_id, asset_id, manual, automatic, time.time()))

    # ── per-user observation index (My picks) ──────────────────────────
    def replace_user_observations(self, owner: str, asset_id: str, features: list[dict]) -> None:
        """Replace one asset's rows in the user's observation index."""
        rows = []
        for f in features:
            coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
            props = f["properties"]
            rows.append((owner, f["id"], asset_id, props.get("catalog_id"), props["status"],
                         coords[0], coords[1], json.dumps(f, sort_keys=True, allow_nan=False)))
        with self._connect() as db:
            db.execute("DELETE FROM user_observations WHERE owner = ? AND asset_id = ?",
                       (owner, asset_id))
            db.executemany("INSERT OR REPLACE INTO user_observations (owner, observation_id,"
                           " asset_id, catalog_id, status, lon, lat, feature)"
                           " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)

    def clear_user_observations(self, owner: str, asset_ids=None) -> None:
        with self._connect() as db:
            if asset_ids is None:
                db.execute("DELETE FROM user_observations WHERE owner = ?", (owner,))
            else:
                db.executemany("DELETE FROM user_observations WHERE owner = ? AND asset_id = ?",
                               [(owner, a) for a in asset_ids])

    def user_observation_assets(self, owner: str) -> set[str]:
        with self._connect() as db:
            return {r[0] for r in db.execute(
                "SELECT DISTINCT asset_id FROM user_observations WHERE owner = ?", (owner,))}

    def query_user_observations(self, owner: str, *, bbox=None, status=None, asset_id=None,
                                limit: int = 20_000) -> dict:
        """The user's observations as GeoJSON, filtered in SQL (owner first)."""
        where, args = ["owner = ?"], [owner]
        if asset_id:
            where.append("asset_id = ?")
            args.append(asset_id)
        if status:
            where.append("status = ?")
            args.append(status)
        base_where, base_args = " AND ".join(where), list(args)
        where.append("lat IS NOT NULL")
        where, args = _bbox_where(where, args, bbox)
        with self._connect() as db:
            counts = dict(db.execute(f"SELECT status, COUNT(*) FROM user_observations"
                                     f" WHERE {base_where} GROUP BY status", base_args).fetchall())
            without = db.execute(f"SELECT COUNT(*) FROM user_observations"
                                 f" WHERE {base_where} AND lat IS NULL", base_args).fetchone()[0]
            rows = db.execute(f"SELECT feature FROM user_observations WHERE {' AND '.join(where)}"
                              f" ORDER BY asset_id, observation_id LIMIT ?",
                              args + [limit + 1]).fetchall()
        features = [json.loads(r[0]) for r in rows[:limit]]
        return {"type": "FeatureCollection", "features": features,
                "summary": {"returned": len(features), "without_position": without,
                            "truncated": len(rows) > limit,
                            "by_status": {"draft": counts.get("draft", 0),
                                          "completed": counts.get("completed", 0)}}}

    def user_states(self, owner: str) -> dict[str, dict]:
        with self._connect() as db:
            return {r["catalog_id"]: dict(r) for r in db.execute(
                "SELECT * FROM user_asset_state WHERE owner = ?", (owner,))}


def _public(item: dict) -> dict:
    item["has_nav"] = bool(item.get("has_nav"))
    item["duplicate"] = bool(item.get("duplicate"))
    return item


_shared: dict[str, RadarCatalog] = {}
_shared_lock = threading.Lock()


def _bbox_where(where: list, args: list, bbox) -> tuple[list, list]:
    """Add a WGS84 bounding box (``min_lon,min_lat,max_lon,max_lat``; the
    antimeridian is handled) to a WHERE clause over ``lat``/``lon``."""
    if bbox is None:
        return where, args
    min_lon, min_lat, max_lon, max_lat = bbox
    where = where + ["lat BETWEEN ? AND ?"]
    args = args + [min_lat, max_lat]
    if min_lon <= max_lon:
        where.append("lon BETWEEN ? AND ?")
        args += [min_lon, max_lon]
    else:
        where.append("(lon >= ? OR lon <= ?)")
        args += [min_lon, max_lon]
    return where, args


def open_catalog() -> RadarCatalog | None:
    """The installation catalog, or ``None`` when none has been created.

    A missing catalog file means "no data sources"; it is created only by
    maintainer actions, never by an ordinary page load.
    """
    path = catalog_path()
    if not path.is_file():
        return None
    key = str(path.resolve())
    with _shared_lock:
        if key not in _shared:
            _shared[key] = RadarCatalog(path)
        return _shared[key]


def create_catalog() -> RadarCatalog:
    """The installation catalog, creating it if needed (maintainer actions)."""
    path = catalog_path()
    catalog = RadarCatalog(path)
    with _shared_lock:
        _shared[str(path.resolve())] = catalog
    return catalog
