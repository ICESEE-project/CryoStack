"""Administrator approval of CryoStack accounts.

Every account has one approval status:

``pending``    registered, waiting for an administrator (the default)
``approved``   may use applications, APIs, storage, compute and the Connector
``rejected``   the registration was declined
``suspended``  access withdrawn; existing sessions are revoked

Only ``approved`` grants access. A verified email address or a successful
Google sign-in proves who someone is; it never approves them.

The gate is switched on with ``CRYOSTACK_REGISTRATION_APPROVAL=1``. Before it
is switched on, ``deployment/auth_db_migrate.py approval-baseline`` records
every existing account as approved (one audit row each) and stores a baseline
marker; the gateway refuses to start with the gate on and no marker, so the
switch can never lock out the current users by accident. An account with no
status row while the gate is on is treated as pending.

Tables (all additive; the previous gateway code ignores them):

``account_status``          one row per account
``account_approval_meta``   the baseline marker
``email_tokens``            hashed one-time email verification / reset tokens
``notification_outbox``     durable, de-duplicated email queue (``mailer``)
``workspace_provisioning``  per-account CEDAR workspace provisioning state
``oauth_flow_nonces``       the OpenID Connect nonce of a pending Google sign-in

Every decision writes one row to the append-only ``access_audit_log`` in the
same transaction as the status change: actor, target, time, previous and new
status, reason.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass

from . import access_log

APPROVAL_ENV = "CRYOSTACK_REGISTRATION_APPROVAL"

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
SUSPENDED = "suspended"
STATUSES = (PENDING, APPROVED, REJECTED, SUSPENDED)

#: decision -> (statuses it may start from, resulting status)
DECISIONS = {
    "approve": ((PENDING, REJECTED), APPROVED),
    "reject": ((PENDING,), REJECTED),
    "suspend": ((PENDING, APPROVED), SUSPENDED),
    "reinstate": ((SUSPENDED,), APPROVED),
}

#: roles that may decide on accounts: every Control Center role, so whoever
#: reaches a registration first can review it
DECISION_ROLES = frozenset({"developer", "maintainer", "admin", "owner"})

def decision_roles() -> frozenset[str]:
    """Restrict the pilot to owners without granting or removing roles."""
    if os.environ.get("CRYOSTACK_APPROVAL_OWNER_ONLY", "0").lower() in {"1", "true", "yes"}:
        return frozenset({"owner"})
    return DECISION_ROLES


AUDIT_ACTION = "account_status_changed"
BASELINE_KEY = "baseline"

VERIFY_EMAIL = "verify_email"
PASSWORD_RESET = "password_reset"
TOKEN_TTL = {
    VERIFY_EMAIL: 3 * 24 * 3600,
    PASSWORD_RESET: 3600,
}

MIN_REASON_LENGTH = 4
MAX_REASON_LENGTH = 500

SCHEMA = """
CREATE TABLE IF NOT EXISTS account_status (
    user_id TEXT PRIMARY KEY,
    status TEXT NOT NULL
        CHECK (status IN ('pending', 'approved', 'rejected', 'suspended')),
    registration_method TEXT NOT NULL,
    email_verified_at REAL,
    requested_at REAL NOT NULL,
    decided_at REAL,
    decided_by TEXT,
    updated_at REAL NOT NULL,

    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_account_status_status
    ON account_status(status, requested_at);

CREATE TABLE IF NOT EXISTS account_approval_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS email_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    purpose TEXT NOT NULL
        CHECK (purpose IN ('verify_email', 'password_reset')),
    email TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used_at REAL,

    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_email_tokens_user
    ON email_tokens(user_id, purpose);

CREATE TABLE IF NOT EXISTS notification_outbox (
    id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    template TEXT NOT NULL,
    user_id TEXT,
    recipient TEXT NOT NULL,
    context_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL
        CHECK (status IN ('queued', 'sending', 'sent', 'failed', 'cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL,
    last_error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    sent_at REAL
);

CREATE INDEX IF NOT EXISTS idx_notification_outbox_due
    ON notification_outbox(status, next_attempt_at);

CREATE TABLE IF NOT EXISTS workspace_provisioning (
    user_id TEXT PRIMARY KEY,
    status TEXT NOT NULL
        CHECK (status IN ('queued', 'provisioning', 'ready', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL,
    last_error TEXT,
    owner_key TEXT,
    allowance_bytes INTEGER,
    allowance_source TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    ready_at REAL,

    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_workspace_provisioning_due
    ON workspace_provisioning(status, next_attempt_at);

CREATE TABLE IF NOT EXISTS oauth_flow_nonces (
    state TEXT PRIMARY KEY,
    nonce TEXT NOT NULL,
    expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS registration_approvers (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL COLLATE NOCASE,
    granted_at REAL NOT NULL,
    granted_by TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (granted_by) REFERENCES users(id)
);
"""

#: tables this release adds (for the migration tool)
TABLES = (
    "account_status",
    "account_approval_meta",
    "email_tokens",
    "notification_outbox",
    "workspace_provisioning",
    "oauth_flow_nonces",
    "registration_approvers",
)


class DecisionError(ValueError):
    """A decision is not valid for the account's current status."""


def approval_required_from_env() -> bool:
    return os.environ.get(APPROVAL_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


@dataclass(frozen=True, slots=True)
class AccountStatus:
    user_id: str
    status: str
    registration_method: str
    email_verified_at: float | None
    requested_at: float
    decided_at: float | None
    decided_by: str | None
    updated_at: float

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None


def _status_from_row(row) -> AccountStatus | None:
    if row is None:
        return None
    return AccountStatus(
        user_id=row["user_id"],
        status=row["status"],
        registration_method=row["registration_method"],
        email_verified_at=row["email_verified_at"],
        requested_at=float(row["requested_at"]),
        decided_at=row["decided_at"],
        decided_by=row["decided_by"],
        updated_at=float(row["updated_at"]),
    )


def clean_reason(reason: str | None, *, required: bool = True) -> str:
    reason = " ".join(str(reason or "").split())
    if required and len(reason) < MIN_REASON_LENGTH:
        raise ValueError(
            f"A reason of at least {MIN_REASON_LENGTH} characters is required."
        )
    return reason[:MAX_REASON_LENGTH]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ApprovalStore:
    """Account status, email tokens and provisioning state in the auth DB."""

    def __init__(self, storage, *, clock=time.time) -> None:
        self._storage = storage
        self._clock = clock
        with self._connect() as connection:
            ensure_schema(connection)

    def _connect(self) -> sqlite3.Connection:
        return self._storage._connect()

    # ── status ──────────────────────────────────────────────────────

    def status(self, user_id: str) -> AccountStatus | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM account_status WHERE user_id = ?", (user_id,)
            ).fetchone()
        return _status_from_row(row)

    def effective_status(self, user_id: str) -> str:
        """The status that governs access; no row means pending."""
        found = self.status(user_id)
        return found.status if found is not None else PENDING

    def register(self, *, user_id: str, method: str,
                 email_verified: bool = False) -> AccountStatus:
        """Record a new registration as pending (idempotent)."""
        now = self._clock()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO account_status (
                    user_id, status, registration_method, email_verified_at,
                    requested_at, updated_at
                )
                VALUES (?, 'pending', ?, ?, ?, ?)
                ON CONFLICT(user_id) DO NOTHING
                """,
                (user_id, method, now if email_verified else None, now, now),
            )
            access_log.record_event(
                connection, event_type=access_log.REGISTER, outcome="success",
                user_id=user_id, provider=method,
                metadata={"status": PENDING}, now=now,
            )
        return self.status(user_id)

    def mark_email_verified(self, user_id: str) -> bool:
        """``True`` when this call verified the address (first time)."""
        now = self._clock()
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE account_status
                SET email_verified_at = ?, updated_at = ?
                WHERE user_id = ? AND email_verified_at IS NULL
                """,
                (now, now, user_id),
            ).rowcount
        return bool(changed)

    def decide(
        self,
        *,
        actor_user_id: str,
        actor_label: str,
        target_user_id: str,
        target_label: str | None,
        decision: str,
        reason: str,
        authorization_check=None,
    ) -> tuple[str, str, str]:
        """Apply one decision atomically; ``(previous, new, audit id)``.

        Writes the status, the audit row and an access event in one
        transaction; suspension and rejection delete the account's sessions
        in the same transaction, so revocation cannot be half-applied.
        Authorization is the caller's job (``control_center`` service).
        """
        if decision not in DECISIONS:
            raise DecisionError("Unknown decision.")
        allowed_from, new_status = DECISIONS[decision]
        now = self._clock()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            # A delegated review permission may have been revoked since the
            # page loaded. Check again while concurrent grants/revokes are
            # excluded by this transaction's write lock.
            if authorization_check is not None:
                authorization_check()
            row = connection.execute(
                "SELECT * FROM account_status WHERE user_id = ?",
                (target_user_id,),
            ).fetchone()
            current = _status_from_row(row)
            previous = current.status if current is not None else PENDING
            if previous not in allowed_from:
                raise DecisionError(
                    f"A {previous} account cannot be given the decision "
                    f"'{decision}'."
                )
            if new_status == APPROVED and current is not None \
                    and not current.email_verified:
                raise DecisionError(
                    "The applicant has not verified their email address yet."
                )
            if current is None:
                connection.execute(
                    """
                    INSERT INTO account_status (
                        user_id, status, registration_method, email_verified_at,
                        requested_at, decided_at, decided_by, updated_at
                    )
                    VALUES (?, ?, 'unknown', NULL, ?, ?, ?, ?)
                    """,
                    (target_user_id, new_status, now, now, actor_user_id, now),
                )
            else:
                connection.execute(
                    """
                    UPDATE account_status
                    SET status = ?, decided_at = ?, decided_by = ?, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (new_status, now, actor_user_id, now, target_user_id),
                )
            removed = 0
            if new_status in (REJECTED, SUSPENDED):
                removed = connection.execute(
                    "DELETE FROM sessions WHERE user_id = ?", (target_user_id,)
                ).rowcount
            audit_id = access_log.record_audit(
                connection,
                actor_user_id=actor_user_id,
                actor_label=actor_label,
                target_user_id=target_user_id,
                target_label=target_label,
                action=AUDIT_ACTION,
                previous_value=previous,
                new_value=new_status,
                reason=reason,
                metadata={"decision": decision, "sessions_removed": removed},
                now=now,
            )
            access_log.record_event(
                connection,
                event_type=access_log.ACCOUNT_STATUS_CHANGED,
                outcome="success",
                user_id=target_user_id,
                actor_user_id=actor_user_id,
                metadata={"decision": decision, "status": new_status},
                now=now,
            )
            if new_status == APPROVED:
                queue_provisioning(connection, target_user_id, now=now)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        return previous, new_status, audit_id

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS n FROM account_status GROUP BY status"
            ).fetchall()
            unreviewed = connection.execute(
                """
                SELECT COUNT(*) FROM users
                WHERE id NOT IN (SELECT user_id FROM account_status)
                """
            ).fetchone()[0]
        counts = {status: 0 for status in STATUSES}
        counts.update({row["status"]: int(row["n"]) for row in rows})
        counts["no_record"] = int(unreviewed)
        return counts

    _ACCOUNT_SELECT = """
        SELECT u.id, u.email, u.display_name, u.institution,
               u.research_role, u.country, u.created_at,
               COALESCE(a.status, 'pending') AS status,
               COALESCE(a.registration_method, 'unknown') AS registration_method,
               a.email_verified_at,
               COALESCE(a.requested_at, u.created_at) AS requested_at,
               a.decided_at, a.decided_by, a.user_id IS NULL AS no_record,
               p.status AS provisioning_status
        FROM users u
        LEFT JOIN account_status a ON a.user_id = u.id
        LEFT JOIN workspace_provisioning p ON p.user_id = u.id
    """

    def list_accounts(self, *, status: str, limit: int = 200) -> list[dict]:
        """Accounts in one status, oldest request first, for the review page.

        After the baseline, an account without a status row is pending and
        listed with the pending ones; before it, such accounts are the
        existing users and are not listed.
        """
        if status not in STATUSES:
            raise ValueError("Unknown status.")
        include_unrecorded = status == PENDING and self.baseline() is not None
        with self._connect() as connection:
            rows = connection.execute(
                self._ACCOUNT_SELECT + """
                WHERE a.status = ? OR (? AND a.user_id IS NULL)
                ORDER BY (a.email_verified_at IS NULL), requested_at
                LIMIT ?
                """,
                (status, int(include_unrecorded), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def account(self, user_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                self._ACCOUNT_SELECT + " WHERE u.id = ?", (user_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    # ── baseline (explicit cutover) ─────────────────────────────────

    def baseline(self) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM account_approval_meta WHERE key = ?",
                (BASELINE_KEY,),
            ).fetchone()
        return json.loads(row["value"]) if row is not None else None

    def record_baseline(self, *, operator: str, reason: str) -> dict:
        """Approve every account that has no status row, once.

        Each account gets an audit row (actor: the named operator, recorded
        as a label because the migration runs outside a signed-in session).
        Running it again approves nothing new and keeps the first marker.
        """
        reason = clean_reason(reason)
        operator = " ".join(str(operator or "").split())[:120]
        if not operator:
            raise ValueError("An operator name is required.")
        now = self._clock()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT value FROM account_approval_meta WHERE key = ?",
                (BASELINE_KEY,),
            ).fetchone()
            rows = connection.execute(
                """
                SELECT id, email FROM users
                WHERE id NOT IN (SELECT user_id FROM account_status)
                ORDER BY created_at
                """
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    INSERT INTO account_status (
                        user_id, status, registration_method, email_verified_at,
                        requested_at, decided_at, decided_by, updated_at
                    )
                    VALUES (?, 'approved', 'baseline', ?, ?, ?, NULL, ?)
                    """,
                    (row["id"], now, now, now, now),
                )
                access_log.record_audit(
                    connection,
                    actor_user_id=None,
                    actor_label=f"migration: {operator}",
                    target_user_id=row["id"],
                    target_label=row["email"],
                    action=AUDIT_ACTION,
                    previous_value="no_record",
                    new_value=APPROVED,
                    reason=reason,
                    metadata={"decision": "baseline"},
                    now=now,
                )
                connection.execute(
                    """
                    INSERT INTO workspace_provisioning (
                        user_id, status, next_attempt_at, created_at, updated_at,
                        allowance_source
                    )
                    VALUES (?, 'ready', ?, ?, ?, 'existing')
                    ON CONFLICT(user_id) DO NOTHING
                    """,
                    (row["id"], now, now, now),
                )
            marker = json.loads(existing["value"]) if existing is not None else {
                "operator": operator,
                "reason": reason,
                "created_at": now,
            }
            marker = {**marker, "approved_last_run": len(rows),
                      "last_run_at": now}
            connection.execute(
                """
                INSERT INTO account_approval_meta (key, value, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (BASELINE_KEY, json.dumps(marker, sort_keys=True), now),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        return marker

    # ── one-time email tokens ───────────────────────────────────────

    def issue_token(self, *, user_id: str, email: str, purpose: str) -> str:
        """A new single-use token; earlier unused ones for the purpose end."""
        if purpose not in TOKEN_TTL:
            raise ValueError("Unknown token purpose.")
        token = secrets.token_urlsafe(32)
        now = self._clock()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE email_tokens SET used_at = ?
                WHERE user_id = ? AND purpose = ? AND used_at IS NULL
                """,
                (now, user_id, purpose),
            )
            connection.execute(
                "DELETE FROM email_tokens WHERE expires_at < ?",
                (now - 7 * 24 * 3600,),
            )
            connection.execute(
                """
                INSERT INTO email_tokens (
                    token_hash, user_id, purpose, email, created_at, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (hash_token(token), user_id, purpose, email.lower(), now,
                 now + TOKEN_TTL[purpose]),
            )
        return token

    def peek_token(self, token: str, purpose: str) -> str | None:
        """The user id behind a valid, unused token, without using it."""
        if not token or len(token) > 200:
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT t.user_id FROM email_tokens t
                JOIN users u ON u.id = t.user_id
                WHERE t.token_hash = ? AND t.purpose = ? AND t.used_at IS NULL
                  AND t.expires_at > ? AND t.email = u.email COLLATE NOCASE
                """,
                (hash_token(token), purpose, self._clock()),
            ).fetchone()
        return row["user_id"] if row is not None else None

    def consume_token(self, token: str, purpose: str) -> str | None:
        """Use a token once; the user id, or ``None`` if invalid/used/expired.

        A token is bound to the address it was sent to: if the account's
        email has changed since, the token no longer works.
        """
        if not token or len(token) > 200:
            return None
        now = self._clock()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT t.user_id FROM email_tokens t
                JOIN users u ON u.id = t.user_id
                WHERE t.token_hash = ? AND t.purpose = ? AND t.used_at IS NULL
                  AND t.expires_at > ? AND t.email = u.email COLLATE NOCASE
                """,
                (hash_token(token), purpose, now),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            connection.execute(
                "UPDATE email_tokens SET used_at = ? WHERE token_hash = ?",
                (now, hash_token(token)),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        return row["user_id"]

    def set_password_hash(self, user_id: str, password_hash: str) -> int:
        """Replace the password, end other reset links and every session."""
        now = self._clock()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (password_hash, now, user_id),
            )
            connection.execute(
                """
                UPDATE email_tokens SET used_at = ?
                WHERE user_id = ? AND purpose = ? AND used_at IS NULL
                """,
                (now, user_id, PASSWORD_RESET),
            )
            removed = connection.execute(
                "DELETE FROM sessions WHERE user_id = ?", (user_id,)
            ).rowcount
            access_log.record_event(
                connection, event_type=access_log.PASSWORD_RESET,
                outcome="success", user_id=user_id,
                metadata={"sessions_removed": removed}, now=now,
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        return removed

    # ── workspace provisioning state ────────────────────────────────

    def provisioning(self, user_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM workspace_provisioning WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def retry_provisioning(self, user_id: str) -> None:
        now = self._clock()
        with self._connect() as connection:
            queue_provisioning(connection, user_id, now=now, force=True)

    def due_provisioning(self, *, limit: int = 10) -> list[str]:
        now = self._clock()
        with self._connect() as connection:
            # a crashed attempt is retried after ten minutes
            connection.execute(
                """
                UPDATE workspace_provisioning SET status = 'queued', updated_at = ?
                WHERE status = 'provisioning' AND updated_at < ?
                """,
                (now, now - 600),
            )
            rows = connection.execute(
                """
                SELECT p.user_id FROM workspace_provisioning p
                JOIN account_status a ON a.user_id = p.user_id
                WHERE p.status = 'queued' AND p.next_attempt_at <= ?
                  AND a.status = 'approved'
                ORDER BY p.next_attempt_at
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        return [row["user_id"] for row in rows]

    def claim_provisioning(self, user_id: str) -> bool:
        now = self._clock()
        with self._connect() as connection:
            return bool(connection.execute(
                """
                UPDATE workspace_provisioning
                SET status = 'provisioning', attempts = attempts + 1, updated_at = ?
                WHERE user_id = ? AND status = 'queued'
                """,
                (now, user_id),
            ).rowcount)

    def finish_provisioning(self, user_id: str, *, owner_key: str,
                            allowance_bytes: int, allowance_source: str) -> None:
        now = self._clock()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE workspace_provisioning
                SET status = 'ready', last_error = NULL, owner_key = ?,
                    allowance_bytes = ?, allowance_source = ?, ready_at = ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (owner_key, int(allowance_bytes), allowance_source, now, now,
                 user_id),
            )

    def fail_provisioning(self, user_id: str, error: str, *,
                          max_attempts: int = 6) -> str:
        """Back off and retry; after ``max_attempts`` it waits for an admin."""
        now = self._clock()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT attempts FROM workspace_provisioning WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            attempts = int(row["attempts"]) if row is not None else 1
            status = "failed" if attempts >= max_attempts else "queued"
            delay = min(60 * 2 ** max(attempts - 1, 0), 3600)
            connection.execute(
                """
                UPDATE workspace_provisioning
                SET status = ?, last_error = ?, next_attempt_at = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (status, error[:300], now + delay, now, user_id),
            )
        return status


def queue_provisioning(connection: sqlite3.Connection, user_id: str, *,
                       now: float, force: bool = False) -> None:
    """Queue (or, with ``force``, re-queue) one account's workspace.

    Approving an account whose workspace is already ``ready`` leaves it
    alone; provisioning itself is idempotent either way.
    """
    connection.execute(
        """
        INSERT INTO workspace_provisioning (
            user_id, status, attempts, next_attempt_at, created_at, updated_at
        )
        VALUES (?, 'queued', 0, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            status = CASE
                WHEN ? OR workspace_provisioning.status = 'failed' THEN 'queued'
                ELSE workspace_provisioning.status END,
            attempts = CASE WHEN ? THEN 0 ELSE workspace_provisioning.attempts END,
            next_attempt_at = excluded.next_attempt_at,
            updated_at = excluded.updated_at
        """,
        (user_id, now, now, now, int(force), int(force)),
    )


def new_id() -> str:
    return uuid.uuid4().hex
