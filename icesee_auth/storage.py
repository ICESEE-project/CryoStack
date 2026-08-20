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

@dataclass(frozen=True, slots=True)
class SavedConfiguration:
    id: str
    user_id: str
    application: str
    name: str
    description: str | None
    configuration_json: str
    schema_version: str
    created_at: float
    updated_at: float

@dataclass(frozen=True, slots=True)
class Experiment:
    id: str
    user_id: str
    configuration_id: str | None
    application: str
    name: str
    backend: str
    status: str
    configuration_snapshot_json: str
    job_id: str | None
    cluster: str | None
    working_directory: str | None
    output_directory: str | None
    log_path: str | None
    exit_code: int | None
    error_message: str | None
    metadata_json: str
    created_at: float
    started_at: float | None
    finished_at: float | None
    updated_at: float

@dataclass(frozen=True, slots=True)
class Workspace:
    id: str
    user_id: str
    application: str
    state_json: str
    created_at: float
    updated_at: float

@dataclass(frozen=True, slots=True)
class UserIdentity:
    id: str
    user_id: str
    provider: str
    provider_subject: str
    provider_username: str | None
    provider_email: str | None
    provider_profile_url: str | None
    created_at: float
    updated_at: float

@dataclass(frozen=True, slots=True)
class OAuthFlow:
    state: str
    session_id: str
    provider: str
    code_verifier: str
    return_to: str
    created_at: float
    expires_at: float

@dataclass(frozen=True, slots=True)
class ExperimentEvent:
    id: str
    experiment_id: str
    user_id: str
    event_type: str
    message: str | None
    metadata_json: str
    created_at: float

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

                CREATE TABLE IF NOT EXISTS saved_configurations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    application TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    configuration_json TEXT NOT NULL,
                    schema_version TEXT NOT NULL DEFAULT '1.0',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,

                    FOREIGN KEY (user_id)
                        REFERENCES users(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_saved_configurations_user
                    ON saved_configurations(user_id);

                CREATE INDEX IF NOT EXISTS idx_saved_configurations_application
                    ON saved_configurations(user_id, application);

                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    configuration_id TEXT,

                    application TEXT NOT NULL,
                    name TEXT NOT NULL,
                    backend TEXT NOT NULL,
                    status TEXT NOT NULL,

                    configuration_snapshot_json TEXT NOT NULL,

                    job_id TEXT,
                    cluster TEXT,
                    working_directory TEXT,
                    output_directory TEXT,
                    log_path TEXT,

                    exit_code INTEGER,
                    error_message TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',

                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    updated_at REAL NOT NULL,

                    FOREIGN KEY (user_id)
                        REFERENCES users(id)
                        ON DELETE CASCADE,

                    FOREIGN KEY (configuration_id)
                        REFERENCES saved_configurations(id)
                        ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_experiments_user
                    ON experiments(user_id);

                CREATE INDEX IF NOT EXISTS idx_experiments_status
                    ON experiments(user_id, status);

                CREATE INDEX IF NOT EXISTS idx_experiments_application
                    ON experiments(user_id, application);

                CREATE INDEX IF NOT EXISTS idx_experiments_created
                    ON experiments(user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    application TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,

                    FOREIGN KEY (user_id)
                        REFERENCES users(id)
                        ON DELETE CASCADE,

                    UNIQUE(user_id, application)
                );

                CREATE INDEX IF NOT EXISTS idx_workspaces_user
                    ON workspaces(user_id);

                CREATE TABLE IF NOT EXISTS user_identities (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,

                    provider TEXT NOT NULL,
                    provider_subject TEXT NOT NULL,

                    provider_username TEXT,
                    provider_email TEXT,
                    provider_profile_url TEXT,

                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,

                    FOREIGN KEY (user_id)
                        REFERENCES users(id)
                        ON DELETE CASCADE,

                    UNIQUE(provider, provider_subject)
                );

                CREATE INDEX IF NOT EXISTS idx_user_identities_user
                    ON user_identities(user_id);

                CREATE INDEX IF NOT EXISTS idx_user_identities_provider
                    ON user_identities(provider, provider_subject);

                CREATE TABLE IF NOT EXISTS oauth_flows (
                    state TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    code_verifier TEXT NOT NULL,
                    return_to TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,

                    FOREIGN KEY (session_id)
                        REFERENCES sessions(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_oauth_flows_expires
                    ON oauth_flows(expires_at);

                CREATE INDEX IF NOT EXISTS idx_oauth_flows_session
                    ON oauth_flows(session_id);

                CREATE TABLE IF NOT EXISTS experiment_events (
                    id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,

                    event_type TEXT NOT NULL,
                    message TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,

                    FOREIGN KEY (experiment_id)
                        REFERENCES experiments(id)
                        ON DELETE CASCADE,

                    FOREIGN KEY (user_id)
                        REFERENCES users(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_experiment_events_experiment
                    ON experiment_events(experiment_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_experiment_events_user
                    ON experiment_events(user_id, created_at);

                CREATE TABLE IF NOT EXISTS user_roles (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    created_by TEXT,

                    FOREIGN KEY (user_id)
                        REFERENCES users(id)
                        ON DELETE CASCADE,

                    FOREIGN KEY (created_by)
                        REFERENCES users(id)
                        ON DELETE SET NULL,

                    UNIQUE(user_id, role)
                );

                CREATE INDEX IF NOT EXISTS idx_user_roles_user
                    ON user_roles(user_id);

                CREATE INDEX IF NOT EXISTS idx_user_roles_role
                    ON user_roles(role);
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

    def save_workspace(
        self,
        *,
        user_id: str,
        application: str,
        state_json: str,
        now: float | None = None,
    ) -> Workspace:
        timestamp = time.time() if now is None else now
        application = application.strip().lower()

        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT *
                FROM workspaces
                WHERE user_id = ? AND application = ?
                """,
                (user_id, application),
            ).fetchone()

            if existing is None:
                workspace_id = uuid.uuid4().hex

                connection.execute(
                    """
                    INSERT INTO workspaces (
                        id,
                        user_id,
                        application,
                        state_json,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workspace_id,
                        user_id,
                        application,
                        state_json,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                workspace_id = existing["id"]

                connection.execute(
                    """
                    UPDATE workspaces
                    SET
                        state_json = ?,
                        updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (
                        state_json,
                        timestamp,
                        workspace_id,
                        user_id,
                    ),
                )

        return self.get_workspace(
            user_id=user_id,
            application=application,
        )

    def get_workspace(
        self,
        *,
        user_id: str,
        application: str,
    ) -> Workspace | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM workspaces
                WHERE user_id = ? AND application = ?
                """,
                (
                    user_id,
                    application.strip().lower(),
                ),
            ).fetchone()

        return self._workspace_from_row(row)

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

    def create_oauth_flow(
        self,
        *,
        state: str,
        session_id: str,
        provider: str,
        code_verifier: str,
        return_to: str,
        ttl_seconds: int = 600,
        now: float | None = None,
    ) -> OAuthFlow:
        timestamp = time.time() if now is None else now

        flow = OAuthFlow(
            state=state,
            session_id=session_id,
            provider=provider.strip().lower(),
            code_verifier=code_verifier,
            return_to=return_to,
            created_at=timestamp,
            expires_at=timestamp + ttl_seconds,
        )

        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM oauth_flows
                WHERE expires_at <= ?
                """,
                (timestamp,),
            )

            connection.execute(
                """
                INSERT INTO oauth_flows (
                    state,
                    session_id,
                    provider,
                    code_verifier,
                    return_to,
                    created_at,
                    expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    flow.state,
                    flow.session_id,
                    flow.provider,
                    flow.code_verifier,
                    flow.return_to,
                    flow.created_at,
                    flow.expires_at,
                ),
            )

        return flow


    def consume_oauth_flow(
        self,
        *,
        state: str,
        provider: str,
        now: float | None = None,
    ) -> OAuthFlow | None:
        timestamp = time.time() if now is None else now

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM oauth_flows
                WHERE state = ?
                AND provider = ?
                AND expires_at > ?
                """,
                (
                    state,
                    provider.strip().lower(),
                    timestamp,
                ),
            ).fetchone()

            if row is None:
                return None

            connection.execute(
                """
                DELETE FROM oauth_flows
                WHERE state = ?
                """,
                (state,),
            )

        return OAuthFlow(
            state=row["state"],
            session_id=row["session_id"],
            provider=row["provider"],
            code_verifier=row["code_verifier"],
            return_to=row["return_to"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
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

    def create_user_identity(
        self,
        *,
        user_id: str,
        provider: str,
        provider_subject: str,
        provider_username: str | None = None,
        provider_email: str | None = None,
        provider_profile_url: str | None = None,
        now: float | None = None,
    ) -> UserIdentity:
        timestamp = time.time() if now is None else now

        identity = UserIdentity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            provider=provider.strip().lower(),
            provider_subject=str(provider_subject).strip(),
            provider_username=(
                provider_username.strip()
                if provider_username
                else None
            ),
            provider_email=(
                provider_email.strip().lower()
                if provider_email
                else None
            ),
            provider_profile_url=(
                provider_profile_url.strip()
                if provider_profile_url
                else None
            ),
            created_at=timestamp,
            updated_at=timestamp,
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_identities (
                    id,
                    user_id,
                    provider,
                    provider_subject,
                    provider_username,
                    provider_email,
                    provider_profile_url,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identity.id,
                    identity.user_id,
                    identity.provider,
                    identity.provider_subject,
                    identity.provider_username,
                    identity.provider_email,
                    identity.provider_profile_url,
                    identity.created_at,
                    identity.updated_at,
                ),
            )

        return identity

    def get_user_identity(
        self,
        *,
        provider: str,
        provider_subject: str,
    ) -> UserIdentity | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM user_identities
                WHERE provider = ?
                AND provider_subject = ?
                LIMIT 1
                """,
                (
                    provider.strip().lower(),
                    str(provider_subject).strip(),
                ),
            ).fetchone()

        return self._user_identity_from_row(row)

    def list_user_identities(
        self,
        *,
        user_id: str,
    ) -> list[UserIdentity]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM user_identities
                WHERE user_id = ?
                ORDER BY created_at ASC
                """,
                (user_id,),
            ).fetchall()

        return [
            self._user_identity_from_row(row)
            for row in rows
        ]

    @staticmethod
    def _user_identity_from_row(
        row: sqlite3.Row | None,
    ) -> UserIdentity | None:
        if row is None:
            return None

        return UserIdentity(
            id=row["id"],
            user_id=row["user_id"],
            provider=row["provider"],
            provider_subject=row["provider_subject"],
            provider_username=row["provider_username"],
            provider_email=row["provider_email"],
            provider_profile_url=row["provider_profile_url"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create_configuration(
        self,
        *,
        user_id: str,
        application: str,
        name: str,
        description: str | None,
        configuration_json: str,
        schema_version: str = "1.0",
        now: float | None = None,
    ) -> SavedConfiguration:
        timestamp = time.time() if now is None else now

        configuration = SavedConfiguration(
            id=uuid.uuid4().hex,
            user_id=user_id,
            application=application.strip().lower(),
            name=name.strip(),
            description=(description or "").strip() or None,
            configuration_json=configuration_json,
            schema_version=schema_version.strip() or "1.0",
            created_at=timestamp,
            updated_at=timestamp,
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO saved_configurations (
                    id,
                    user_id,
                    application,
                    name,
                    description,
                    configuration_json,
                    schema_version,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    configuration.id,
                    configuration.user_id,
                    configuration.application,
                    configuration.name,
                    configuration.description,
                    configuration.configuration_json,
                    configuration.schema_version,
                    configuration.created_at,
                    configuration.updated_at,
                ),
            )

        return configuration


    def list_configurations(
        self,
        *,
        user_id: str,
        application: str | None = None,
    ) -> list[SavedConfiguration]:
        query = """
            SELECT *
            FROM saved_configurations
            WHERE user_id = ?
        """

        params: list[object] = [user_id]

        if application:
            query += " AND application = ?"
            params.append(application.strip().lower())

        query += " ORDER BY updated_at DESC"

        with self._connect() as connection:
            rows = connection.execute(
                query,
                params,
            ).fetchall()

        return [
            self._configuration_from_row(row)
            for row in rows
        ]


    def get_configuration(
        self,
        *,
        configuration_id: str,
        user_id: str,
    ) -> SavedConfiguration | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM saved_configurations
                WHERE id = ? AND user_id = ?
                """,
                (
                    configuration_id,
                    user_id,
                ),
            ).fetchone()

        return self._configuration_from_row(row)


    def delete_configuration(
        self,
        *,
        configuration_id: str,
        user_id: str,
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM saved_configurations
                WHERE id = ? AND user_id = ?
                """,
                (
                    configuration_id,
                    user_id,
                ),
            )

        return cursor.rowcount > 0


    def update_configuration(
        self,
        *,
        configuration_id: str,
        user_id: str,
        application: str,
        name: str,
        description: str | None,
        configuration_json: str,
        schema_version: str = "1.0",
        now: float | None = None,
    ) -> SavedConfiguration | None:
        timestamp = time.time() if now is None else now

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE saved_configurations
                SET
                    application = ?,
                    name = ?,
                    description = ?,
                    configuration_json = ?,
                    schema_version = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    application.strip().lower(),
                    name.strip(),
                    (description or "").strip() or None,
                    configuration_json,
                    schema_version.strip() or "1.0",
                    timestamp,
                    configuration_id,
                    user_id,
                ),
            )

        return self.get_configuration(
            configuration_id=configuration_id,
            user_id=user_id,
        )

    def create_experiment(
        self,
        *,
        user_id: str,
        application: str,
        name: str,
        backend: str,
        configuration_snapshot_json: str,
        configuration_id: str | None = None,
        status: str = "queued",
        job_id: str | None = None,
        cluster: str | None = None,
        working_directory: str | None = None,
        output_directory: str | None = None,
        log_path: str | None = None,
        metadata_json: str = "{}",
        now: float | None = None,
    ) -> Experiment:
        timestamp = time.time() if now is None else now

        experiment = Experiment(
            id=uuid.uuid4().hex,
            user_id=user_id,
            configuration_id=configuration_id,
            application=application.strip().lower(),
            name=name.strip(),
            backend=backend.strip().lower(),
            status=status.strip().lower(),
            configuration_snapshot_json=configuration_snapshot_json,
            job_id=(job_id or "").strip() or None,
            cluster=(cluster or "").strip() or None,
            working_directory=(working_directory or "").strip() or None,
            output_directory=(output_directory or "").strip() or None,
            log_path=(log_path or "").strip() or None,
            exit_code=None,
            error_message=None,
            metadata_json=metadata_json or "{}",
            created_at=timestamp,
            started_at=None,
            finished_at=None,
            updated_at=timestamp,
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO experiments (
                    id,
                    user_id,
                    configuration_id,
                    application,
                    name,
                    backend,
                    status,
                    configuration_snapshot_json,
                    job_id,
                    cluster,
                    working_directory,
                    output_directory,
                    log_path,
                    exit_code,
                    error_message,
                    metadata_json,
                    created_at,
                    started_at,
                    finished_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    experiment.id,
                    experiment.user_id,
                    experiment.configuration_id,
                    experiment.application,
                    experiment.name,
                    experiment.backend,
                    experiment.status,
                    experiment.configuration_snapshot_json,
                    experiment.job_id,
                    experiment.cluster,
                    experiment.working_directory,
                    experiment.output_directory,
                    experiment.log_path,
                    experiment.exit_code,
                    experiment.error_message,
                    experiment.metadata_json,
                    experiment.created_at,
                    experiment.started_at,
                    experiment.finished_at,
                    experiment.updated_at,
                ),
            )

        return experiment

    def get_experiment_by_job_id(
        self,
        *,
        user_id: str,
        job_id: str,
    ) -> Experiment | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM experiments
                WHERE user_id = ?
                AND job_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (
                    user_id,
                    str(job_id),
                ),
            ).fetchone()

        return self._experiment_from_row(row)

    def list_experiments(
        self,
        *,
        user_id: str,
        application: str | None = None,
        status: str | None = None,
    ) -> list[Experiment]:
        query = """
            SELECT *
            FROM experiments
            WHERE user_id = ?
        """

        params: list[object] = [user_id]

        if application:
            query += " AND application = ?"
            params.append(application.strip().lower())

        if status:
            query += " AND status = ?"
            params.append(status.strip().lower())

        query += " ORDER BY created_at DESC"

        with self._connect() as connection:
            rows = connection.execute(
                query,
                params,
            ).fetchall()

        return [
            self._experiment_from_row(row)
            for row in rows
        ]

    
    def get_experiment(
        self,
        *,
        experiment_id: str,
        user_id: str,
    ) -> Experiment | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM experiments
                WHERE id = ? AND user_id = ?
                """,
                (
                    experiment_id,
                    user_id,
                ),
            ).fetchone()

        return self._experiment_from_row(row)

    def update_experiment(
        self,
        *,
        experiment_id: str,
        user_id: str,
        status: str | None = None,
        job_id: str | None = None,
        cluster: str | None = None,
        working_directory: str | None = None,
        output_directory: str | None = None,
        log_path: str | None = None,
        exit_code: int | None = None,
        error_message: str | None = None,
        metadata_json: str | None = None,
        now: float | None = None,
    ) -> Experiment | None:
        timestamp = time.time() if now is None else now

        current = self.get_experiment(
            experiment_id=experiment_id,
            user_id=user_id,
        )

        if current is None:
            return None

        next_status = (
            status.strip().lower()
            if status is not None
            else current.status
        )

        started_at = current.started_at
        finished_at = current.finished_at

        if next_status == "running" and started_at is None:
            started_at = timestamp

        if next_status in {
            "completed",
            "failed",
            "cancelled",
        }:
            finished_at = timestamp

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE experiments
                SET
                    status = ?,
                    job_id = ?,
                    cluster = ?,
                    working_directory = ?,
                    output_directory = ?,
                    log_path = ?,
                    exit_code = ?,
                    error_message = ?,
                    metadata_json = ?,
                    started_at = ?,
                    finished_at = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    next_status,
                    job_id if job_id is not None else current.job_id,
                    cluster if cluster is not None else current.cluster,
                    (
                        working_directory
                        if working_directory is not None
                        else current.working_directory
                    ),
                    (
                        output_directory
                        if output_directory is not None
                        else current.output_directory
                    ),
                    (
                        log_path
                        if log_path is not None
                        else current.log_path
                    ),
                    (
                        exit_code
                        if exit_code is not None
                        else current.exit_code
                    ),
                    (
                        error_message
                        if error_message is not None
                        else current.error_message
                    ),
                    (
                        metadata_json
                        if metadata_json is not None
                        else current.metadata_json
                    ),
                    started_at,
                    finished_at,
                    timestamp,
                    experiment_id,
                    user_id,
                ),
            )

        return self.get_experiment(
            experiment_id=experiment_id,
            user_id=user_id,
        )

    def delete_experiment(
        self,
        *,
        experiment_id: str,
        user_id: str,
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM experiments
                WHERE id = ? AND user_id = ?
                """,
                (
                    experiment_id,
                    user_id,
                ),
            )

        return cursor.rowcount > 0

    @staticmethod
    def _experiment_from_row(
        row: sqlite3.Row | None,
    ) -> Experiment | None:
        if row is None:
            return None

        return Experiment(
            id=row["id"],
            user_id=row["user_id"],
            configuration_id=row["configuration_id"],
            application=row["application"],
            name=row["name"],
            backend=row["backend"],
            status=row["status"],
            configuration_snapshot_json=(
                row["configuration_snapshot_json"]
            ),
            job_id=row["job_id"],
            cluster=row["cluster"],
            working_directory=row["working_directory"],
            output_directory=row["output_directory"],
            log_path=row["log_path"],
            exit_code=row["exit_code"],
            error_message=row["error_message"],
            metadata_json=row["metadata_json"],
            created_at=float(row["created_at"]),
            started_at=(
                float(row["started_at"])
                if row["started_at"] is not None
                else None
            ),
            finished_at=(
                float(row["finished_at"])
                if row["finished_at"] is not None
                else None
            ),
            updated_at=float(row["updated_at"]),
        )


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
    def _configuration_from_row(
        row: sqlite3.Row | None,
    ) -> SavedConfiguration | None:
        if row is None:
            return None

        return SavedConfiguration(
            id=row["id"],
            user_id=row["user_id"],
            application=row["application"],
            name=row["name"],
            description=row["description"],
            configuration_json=row["configuration_json"],
            schema_version=row["schema_version"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
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

    @staticmethod
    def _workspace_from_row(
        row: sqlite3.Row | None,
    ) -> Workspace | None:
        if row is None:
            return None

        return Workspace(
            id=row["id"],
            user_id=row["user_id"],
            application=row["application"],
            state_json=row["state_json"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def create_experiment_event(
        self,
        *,
        experiment_id: str,
        user_id: str,
        event_type: str,
        message: str | None = None,
        metadata_json: str = "{}",
        now: float | None = None,
    ) -> ExperimentEvent:
        timestamp = time.time() if now is None else now

        event = ExperimentEvent(
            id=str(uuid.uuid4()),
            experiment_id=experiment_id,
            user_id=user_id,
            event_type=event_type.strip().lower(),
            message=message,
            metadata_json=metadata_json,
            created_at=timestamp,
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO experiment_events (
                    id,
                    experiment_id,
                    user_id,
                    event_type,
                    message,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.experiment_id,
                    event.user_id,
                    event.event_type,
                    event.message,
                    event.metadata_json,
                    event.created_at,
                ),
            )

        return event


    def list_experiment_events(
        self,
        *,
        experiment_id: str,
        user_id: str,
    ) -> list[ExperimentEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM experiment_events
                WHERE experiment_id = ?
                AND user_id = ?
                ORDER BY created_at ASC
                """,
                (
                    experiment_id,
                    user_id,
                ),
            ).fetchall()

        return [
            self._experiment_event_from_row(row)
            for row in rows
        ]


    @staticmethod
    def _experiment_event_from_row(
        row: sqlite3.Row | None,
    ) -> ExperimentEvent | None:
        if row is None:
            return None

        return ExperimentEvent(
            id=row["id"],
            experiment_id=row["experiment_id"],
            user_id=row["user_id"],
            event_type=row["event_type"],
            message=row["message"],
            metadata_json=row["metadata_json"],
            created_at=row["created_at"],
        )

    def add_user_role(
        self,
        *,
        user_id: str,
        role: str,
        created_by: str | None = None,
        now: float | None = None,
    ) -> None:

        allowed_roles = {
            "developer",
            "administrator",
            "owner",
        }

        role = role.strip().lower()

        if role not in allowed_roles:
            raise ValueError(
                f"Invalid CryoStack role: {role}"
            )

        timestamp = (
            time.time()
            if now is None
            else now
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO user_roles (
                    id,
                    user_id,
                    role,
                    created_at,
                    created_by
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    user_id,
                    role,
                    timestamp,
                    created_by,
                ),
            )


    def remove_user_role(
        self,
        *,
        user_id: str,
        role: str,
    ) -> bool:

        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM user_roles
                WHERE user_id = ?
                AND role = ?
                """,
                (
                    user_id,
                    role.strip().lower(),
                ),
            )

        return cursor.rowcount > 0


    def get_user_roles(
        self,
        *,
        user_id: str,
    ) -> list[str]:

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role
                FROM user_roles
                WHERE user_id = ?
                ORDER BY role
                """,
                (user_id,),
            ).fetchall()

        return [
            str(row["role"])
            for row in rows
        ]


    def user_has_role(
        self,
        *,
        user_id: str,
        roles: set[str],
    ) -> bool:

        current_roles = set(
            self.get_user_roles(
                user_id=user_id
            )
        )

        return bool(
            current_roles.intersection(
                roles
            )
        )