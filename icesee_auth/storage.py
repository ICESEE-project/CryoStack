"""SQLite persistence for CryoStack users and browser sessions."""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class User:
    id: str
    email: str
    display_name: str
    institution: str | None
    password_hash: str
    created_at: float

    research_role: str | None = None
    country: str | None = None
    default_application: str | None = None
    default_execution_mode: str | None = None
    updated_at: float | None = None


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: str
    user_id: str | None
    created_at: float
    last_seen_at: float
    expires_at: float


class AuthStorage:
    """Store users and sessions in a small SQLite database."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL,
                    institution TEXT,
                    password_hash TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    created_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    FOREIGN KEY (user_id)
                        REFERENCES users(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_expires_at
                    ON sessions(expires_at);

                CREATE INDEX IF NOT EXISTS idx_sessions_user_id
                    ON sessions(user_id);
                """
            )

            self._ensure_user_columns(connection)

    def create_user(
        self,
        *,
        email: str,
        display_name: str,
        institution: str | None,
        password_hash: str,
        now: float | None = None,
    ) -> User:
        timestamp = time.time() if now is None else now
        user = User(
            id=uuid.uuid4().hex,
            email=email.strip().lower(),
            display_name=display_name.strip(),
            institution=(institution or "").strip() or None,
            password_hash=password_hash,
            created_at=timestamp,
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users (
                    id,
                    email,
                    display_name,
                    institution,
                    password_hash,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user.id,
                    user.email,
                    user.display_name,
                    user.institution,
                    user.password_hash,
                    user.created_at,
                ),
            )

        return user

    def get_user_by_email(self, email: str) -> User | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM users
                WHERE email = ? COLLATE NOCASE
                """,
                (email.strip(),),
            ).fetchone()

        return self._user_from_row(row)

    def get_user_by_id(self, user_id: str) -> User | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

        return self._user_from_row(row)

    def create_session(
        self,
        *,
        ttl_seconds: int,
        user_id: str | None = None,
        now: float | None = None,
    ) -> SessionRecord:
        timestamp = time.time() if now is None else now
        session = SessionRecord(
            id=uuid.uuid4().hex + uuid.uuid4().hex,
            user_id=user_id,
            created_at=timestamp,
            last_seen_at=timestamp,
            expires_at=timestamp + ttl_seconds,
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (
                    id,
                    user_id,
                    created_at,
                    last_seen_at,
                    expires_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.user_id,
                    session.created_at,
                    session.last_seen_at,
                    session.expires_at,
                ),
            )

        return session

    def get_session(
        self,
        session_id: str,
        *,
        now: float | None = None,
    ) -> SessionRecord | None:
        timestamp = time.time() if now is None else now

        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()

            if row is None:
                return None

            if float(row["expires_at"]) <= timestamp:
                connection.execute(
                    "DELETE FROM sessions WHERE id = ?",
                    (session_id,),
                )
                return None

        return self._session_from_row(row)

    def refresh_session(
        self,
        session_id: str,
        *,
        ttl_seconds: int,
        now: float | None = None,
    ) -> SessionRecord | None:
        timestamp = time.time() if now is None else now
        expires_at = timestamp + ttl_seconds

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET last_seen_at = ?, expires_at = ?
                WHERE id = ?
                """,
                (timestamp, expires_at, session_id),
            )

        return self.get_session(session_id, now=timestamp)

    def authenticate_session(
        self,
        session_id: str,
        *,
        user_id: str,
        ttl_seconds: int,
        now: float | None = None,
    ) -> SessionRecord | None:
        timestamp = time.time() if now is None else now
        expires_at = timestamp + ttl_seconds

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET user_id = ?,
                    last_seen_at = ?,
                    expires_at = ?
                WHERE id = ?
                """,
                (user_id, timestamp, expires_at, session_id),
            )

        return self.get_session(session_id, now=timestamp)

    def delete_session(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE id = ?",
                (session_id,),
            )

    def delete_expired_sessions(self, now: float | None = None) -> None:
        timestamp = time.time() if now is None else now

        with self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE expires_at <= ?",
                (timestamp,),
            )

    def update_user_profile(
        self,
        *,
        user_id: str,
        display_name: str,
        institution: str | None,
        research_role: str | None,
        country: str | None,
        default_application: str | None,
        default_execution_mode: str | None,
        now: float | None = None,
    ) -> User | None:
        timestamp = time.time() if now is None else now

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE users
                SET
                    display_name = ?,
                    institution = ?,
                    research_role = ?,
                    country = ?,
                    default_application = ?,
                    default_execution_mode = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    display_name.strip(),
                    (institution or "").strip() or None,
                    (research_role or "").strip() or None,
                    (country or "").strip() or None,
                    (default_application or "").strip() or None,
                    (default_execution_mode or "").strip() or None,
                    timestamp,
                    user_id,
                ),
            )

        return self.get_user_by_id(user_id)

    @staticmethod
    def _user_from_row(
        row: sqlite3.Row | None,
    ) -> User | None:
        if row is None:
            return None

        keys = set(row.keys())

        return User(
            id=row["id"],
            email=row["email"],
            display_name=row["display_name"],
            institution=row["institution"],
            password_hash=row["password_hash"],
            created_at=float(row["created_at"]),
            research_role=(
                row["research_role"]
                if "research_role" in keys
                else None
            ),
            country=(
                row["country"]
                if "country" in keys
                else None
            ),
            default_application=(
                row["default_application"]
                if "default_application" in keys
                else None
            ),
            default_execution_mode=(
                row["default_execution_mode"]
                if "default_execution_mode" in keys
                else None
            ),
            updated_at=(
                float(row["updated_at"])
                if "updated_at" in keys
                and row["updated_at"] is not None
                else None
            ),
        )

    @staticmethod
    def _session_from_row(
        row: sqlite3.Row | None,
    ) -> SessionRecord | None:
        if row is None:
            return None

        return SessionRecord(
            id=row["id"],
            user_id=row["user_id"],
            created_at=float(row["created_at"]),
            last_seen_at=float(row["last_seen_at"]),
            expires_at=float(row["expires_at"]),
        )

    @staticmethod
    def _ensure_user_columns(
        connection: sqlite3.Connection,
    ) -> None:
        """Add newer profile columns to an existing database."""

        existing = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(users)"
            ).fetchall()
        }

        columns = {
            "research_role": "TEXT",
            "country": "TEXT",
            "default_application": "TEXT",
            "default_execution_mode": "TEXT",
            "updated_at": "REAL",
        }

        for column_name, column_type in columns.items():
            if column_name not in existing:
                connection.execute(
                    f"""
                    ALTER TABLE users
                    ADD COLUMN {column_name} {column_type}
                    """
                )
