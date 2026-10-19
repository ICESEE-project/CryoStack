# control_center/ops_store.py

"""Control Center operations store: settings, their audit trail and
aggregate application-usage counters.

A small SQLite file of its own (``$CRYOSTACK_CONTROL_OPS_DATABASE``, default
``control_center_ops.db`` next to the auth database) rather than new tables
in the auth database:

* the auth schema belongs to ``icesee_auth``; operational settings are not
  identity data and must stay readable when the auth schema changes;
* usage counters are written on page loads -- a separate file keeps those
  writes away from the session/login write path (no lock contention);
* the file is created ``0600`` and holds no secrets and no per-user browsing
  data (usage rows are ``(day, application, opens)`` only).

Same conventions as the other CryoStack SQLite stores: WAL, a busy timeout,
``CREATE TABLE IF NOT EXISTS`` plus additive migrations tracked with
``PRAGMA user_version``. Every public method is one transaction.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


OPS_DATABASE_ENV = "CRYOSTACK_CONTROL_OPS_DATABASE"
BUSY_TIMEOUT_S = 5
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    updated_at  REAL NOT NULL,
    updated_by  TEXT
);
CREATE TABLE IF NOT EXISTS settings_audit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key          TEXT NOT NULL,
    action       TEXT NOT NULL,
    old_json     TEXT,
    new_json     TEXT,
    actor_id     TEXT NOT NULL,
    actor_label  TEXT,
    reason       TEXT NOT NULL,
    rollback_of  INTEGER,
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_settings_audit_key
    ON settings_audit(key, id);
CREATE TABLE IF NOT EXISTS app_usage_daily (
    day          TEXT NOT NULL,
    application  TEXT NOT NULL,
    opens        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, application)
);
"""


def default_ops_database(auth_database: Path | None = None) -> Path:
    from cryostack_src.storage_layout import resolve

    path, how = resolve("control-center-ops")
    if how != "legacy":         # its own variable, or $CRYOSTACK_DATA_ROOT
        return path
    if auth_database is not None:
        return Path(auth_database).parent / "control_center_ops.db"
    return (
        Path(__file__).resolve().parent.parent
        / "var"
        / "control_center_ops.db"
    )


def _dump(value) -> str | None:
    return None if value is None else json.dumps(value)


def _load(text):
    return None if text is None else json.loads(text)


class OpsStore:

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        with self._connect() as db:
            db.executescript(_SCHEMA)
            if db.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        if new:
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_S)
        db.row_factory = sqlite3.Row
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

    # ── settings ────────────────────────────────────────────────────
    def stored_settings(self) -> dict[str, dict]:
        with self._connect() as db:
            return {
                row["key"]: {
                    "value": _load(row["value_json"]),
                    "updated_at": row["updated_at"],
                    "updated_by": row["updated_by"],
                }
                for row in db.execute("SELECT * FROM settings")
            }

    def change_setting(
        self,
        *,
        key: str,
        new_value,
        actor_id: str,
        actor_label: str | None,
        reason: str,
        action: str,
        rollback_of: int | None = None,
    ) -> int:
        """Store (or, with ``new_value`` None, remove) a setting and audit
        the change in the same transaction. Returns the audit id."""
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT value_json FROM settings WHERE key = ?", (key,)
            ).fetchone()
            old_json = row["value_json"] if row else None
            if new_value is None:
                db.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                db.execute(
                    "INSERT INTO settings (key, value_json, updated_at, updated_by)"
                    " VALUES (?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET"
                    " value_json = excluded.value_json,"
                    " updated_at = excluded.updated_at,"
                    " updated_by = excluded.updated_by",
                    (key, _dump(new_value), now, actor_id),
                )
            cursor = db.execute(
                "INSERT INTO settings_audit (key, action, old_json, new_json,"
                " actor_id, actor_label, reason, rollback_of, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (key, action, old_json, _dump(new_value), actor_id,
                 actor_label, reason, rollback_of, now),
            )
            return int(cursor.lastrowid)

    def audit(self, *, limit: int = 50) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM settings_audit ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [self._audit_row(row) for row in rows]

    def audit_entry(self, audit_id: int) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM settings_audit WHERE id = ?", (int(audit_id),)
            ).fetchone()
        return self._audit_row(row) if row else None

    @staticmethod
    def _audit_row(row) -> dict:
        item = dict(row)
        item["old_value"] = _load(item.pop("old_json"))
        item["new_value"] = _load(item.pop("new_json"))
        return item

    # ── usage counters ──────────────────────────────────────────────
    def add_usage(self, counts: dict[tuple[str, str], int]) -> None:
        if not counts:
            return
        with self._connect() as db:
            db.executemany(
                "INSERT INTO app_usage_daily (day, application, opens)"
                " VALUES (?, ?, ?) ON CONFLICT(day, application)"
                " DO UPDATE SET opens = opens + excluded.opens",
                [(day, app, int(n)) for (day, app), n in counts.items()],
            )

    def usage(self, *, since_day: str) -> list[dict]:
        with self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT day, application, opens FROM app_usage_daily"
                    " WHERE day >= ? ORDER BY day, application",
                    (since_day,),
                )
            ]

    def first_usage_day(self) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT MIN(day) FROM app_usage_daily").fetchone()
        return row[0] if row else None
