"""Access events and the append-only access audit trail.

Two additive tables live next to the existing auth schema:

``access_events``
    Operational sign-in and access events (logins, failures, logouts, denied
    Control Center requests, role changes, session revocations). Rows carry a
    category, never a credential, token, session id, password or provider
    message. The table is bounded by a retention window and a row cap.

``access_audit_log``
    Who changed whose access, what changed, when and why. Rows are never
    updated or deleted: triggers abort any UPDATE or DELETE, and there are no
    foreign keys, so deleting an account cannot cascade into the trail.

Both tables are created with ``CREATE ... IF NOT EXISTS`` so an existing
database opens unchanged and gains them on first use.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid

#: event_type values written by the platform
LOGIN_SUCCESS = "login_success"
LOGIN_FAILURE = "login_failure"
LOGIN_RATE_LIMITED = "login_rate_limited"
LOGOUT = "logout"
REGISTER = "register"
CONTROL_DENIED = "control_denied"
ROLE_CHANGED = "role_changed"
ROLE_CHANGE_DENIED = "role_change_denied"
SESSIONS_REVOKED = "sessions_revoked"

EVENT_TYPES = (
    LOGIN_SUCCESS,
    LOGIN_FAILURE,
    LOGIN_RATE_LIMITED,
    LOGOUT,
    REGISTER,
    CONTROL_DENIED,
    ROLE_CHANGED,
    ROLE_CHANGE_DENIED,
    SESSIONS_REVOKED,
)

#: failure categories (stable, non-sensitive labels)
FAILURE_CATEGORIES = (
    "unknown_account",
    "wrong_password",
    "rate_limited",
    "invalid_request",
    "expired_or_invalid_state",
    "session_mismatch",
    "provider_error",
    "provider_not_configured",
    "identity_not_linked",
    "identity_conflict",
    "missing_email",
    "internal_error",
    "registration_invalid",
    "registration_conflict",
)

RETENTION_DAYS_ENV = "CRYOSTACK_ACCESS_EVENT_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 90
MAX_EVENT_ROWS = 100_000

#: metadata values are short labels; anything else is dropped
_METADATA_VALUE_LIMIT = 200
_REASON_LIMIT = 500

SCHEMA = """
CREATE TABLE IF NOT EXISTS access_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    event_type TEXT NOT NULL,
    outcome TEXT NOT NULL,
    category TEXT,
    user_id TEXT,
    actor_user_id TEXT,
    provider TEXT,
    path TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_access_events_created
    ON access_events(created_at);

CREATE INDEX IF NOT EXISTS idx_access_events_user
    ON access_events(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_access_events_type
    ON access_events(event_type, created_at);

CREATE TABLE IF NOT EXISTS access_audit_log (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    actor_user_id TEXT,
    actor_label TEXT NOT NULL,
    target_user_id TEXT,
    target_label TEXT,
    action TEXT NOT NULL,
    previous_value TEXT,
    new_value TEXT,
    reason TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_access_audit_created
    ON access_audit_log(created_at);

CREATE INDEX IF NOT EXISTS idx_access_audit_target
    ON access_audit_log(target_user_id, created_at);

CREATE TRIGGER IF NOT EXISTS access_audit_log_no_update
    BEFORE UPDATE ON access_audit_log
BEGIN
    SELECT RAISE(ABORT, 'access_audit_log is append-only');
END;

CREATE TRIGGER IF NOT EXISTS access_audit_log_no_delete
    BEFORE DELETE ON access_audit_log
BEGIN
    SELECT RAISE(ABORT, 'access_audit_log is append-only');
END;
"""


def ensure_access_schema(connection: sqlite3.Connection) -> None:
    """Create the access tables if they are missing (additive only)."""
    connection.executescript(SCHEMA)


def retention_days() -> int:
    try:
        value = int(os.environ.get(RETENTION_DAYS_ENV, DEFAULT_RETENTION_DAYS))
    except ValueError:
        return DEFAULT_RETENTION_DAYS
    return min(max(value, 1), 3650)


def _clean_label(value, limit: int = _METADATA_VALUE_LIMIT) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def _clean_metadata(metadata: dict | None) -> str:
    clean = {}
    for key, value in (metadata or {}).items():
        if isinstance(value, (int, float, bool)) or value is None:
            clean[str(key)[:60]] = value
        else:
            clean[str(key)[:60]] = _clean_label(value)
    return json.dumps(clean, sort_keys=True)


def record_event(
    connection: sqlite3.Connection,
    *,
    event_type: str,
    outcome: str,
    category: str | None = None,
    user_id: str | None = None,
    actor_user_id: str | None = None,
    provider: str | None = None,
    path: str | None = None,
    metadata: dict | None = None,
    now: float | None = None,
) -> None:
    timestamp = time.time() if now is None else now
    connection.execute(
        """
        INSERT INTO access_events (
            created_at, event_type, outcome, category, user_id,
            actor_user_id, provider, path, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            timestamp,
            event_type,
            outcome,
            _clean_label(category, 60),
            user_id,
            actor_user_id,
            _clean_label(provider, 40),
            _clean_label(path, 200),
            _clean_metadata(metadata),
        ),
    )
    prune_events(connection, now=timestamp)


def prune_events(connection: sqlite3.Connection, *, now: float | None = None) -> None:
    """Apply the retention window and the row cap to ``access_events``."""
    timestamp = time.time() if now is None else now
    connection.execute(
        "DELETE FROM access_events WHERE created_at < ?",
        (timestamp - retention_days() * 86400,),
    )
    row = connection.execute("SELECT MAX(id) AS top FROM access_events").fetchone()
    top = row[0] if row is not None else None
    if top is not None and top > MAX_EVENT_ROWS:
        connection.execute(
            "DELETE FROM access_events WHERE id <= ?",
            (top - MAX_EVENT_ROWS,),
        )


def record_audit(
    connection: sqlite3.Connection,
    *,
    actor_user_id: str | None,
    actor_label: str,
    target_user_id: str | None,
    target_label: str | None,
    action: str,
    previous_value: str | None,
    new_value: str | None,
    reason: str,
    metadata: dict | None = None,
    now: float | None = None,
) -> str:
    audit_id = uuid.uuid4().hex
    connection.execute(
        """
        INSERT INTO access_audit_log (
            id, created_at, actor_user_id, actor_label, target_user_id,
            target_label, action, previous_value, new_value, reason,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            audit_id,
            time.time() if now is None else now,
            actor_user_id,
            _clean_label(actor_label) or "unknown",
            target_user_id,
            _clean_label(target_label),
            action,
            _clean_label(previous_value, 60),
            _clean_label(new_value, 60),
            _clean_label(reason, _REASON_LIMIT) or "",
            _clean_metadata(metadata),
        ),
    )
    return audit_id
