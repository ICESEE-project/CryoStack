# control_center/storage.py

from __future__ import annotations

import sqlite3
from pathlib import Path


class ControlStorage:
    """
    Read-only operational queries for the CryoStack
    Control Center.

    This layer contains SQL only. It does not render
    HTML and does not depend on aiohttp.
    """

    def __init__(
        self,
        database_path: Path,
    ) -> None:
        self.database_path = Path(
            database_path
        )

    def _connect(
        self,
    ) -> sqlite3.Connection:

        connection = sqlite3.connect(
            self.database_path
        )

        connection.row_factory = (
            sqlite3.Row
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        return connection

    # ========================================================
    # Basic counts
    # ========================================================

    def user_count(
        self,
    ) -> int:

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM users
                """
            ).fetchone()

        return int(row["count"])

    def active_session_count(
        self,
        *,
        now: float,
    ) -> int:

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM sessions
                WHERE user_id IS NOT NULL
                  AND expires_at > ?
                """,
                (now,),
            ).fetchone()

        return int(row["count"])

    def configuration_count(
        self,
    ) -> int:

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM saved_configurations
                """
            ).fetchone()

        return int(row["count"])

    def workspace_count(
        self,
    ) -> int:

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM workspaces
                """
            ).fetchone()

        return int(row["count"])

    def experiment_event_count(
        self,
    ) -> int:

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM experiment_events
                """
            ).fetchone()

        return int(row["count"])

    # ========================================================
    # OAuth / identities
    # ========================================================

    def identity_count(
        self,
        provider: str,
    ) -> int:

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM user_identities
                WHERE provider = ?
                """,
                (
                    provider.strip().lower(),
                ),
            ).fetchone()

        return int(row["count"])

    # ========================================================
    # Experiments
    # ========================================================

    def experiment_count(
        self,
    ) -> int:

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM experiments
                """
            ).fetchone()

        return int(row["count"])

    def experiment_status_counts(
        self,
    ) -> dict[str, int]:

        statuses = {
            "queued": 0,
            "preparing": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
        }

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    status,
                    COUNT(*) AS count
                FROM experiments
                GROUP BY status
                """
            ).fetchall()

        for row in rows:
            status = str(
                row["status"]
            ).strip().lower()

            statuses[status] = int(
                row["count"]
            )

        return statuses

    def application_counts(
        self,
    ) -> dict[str, int]:

        applications = {
            "cryolauncher": 0,
            "icesee": 0,
            "livist": 0,
        }

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    application,
                    COUNT(*) AS count
                FROM experiments
                GROUP BY application
                """
            ).fetchall()

        for row in rows:
            application = str(
                row["application"]
            ).strip().lower()

            applications[application] = int(
                row["count"]
            )

        return applications

    # ========================================================
    # Users
    # ========================================================

    def list_users(
        self,
        *,
        now: float,
    ) -> list[dict]:

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    u.id,
                    u.email,
                    u.display_name,
                    u.institution,
                    u.research_role,
                    u.country,
                    u.created_at,
                    u.updated_at,

                    (
                        SELECT COUNT(*)
                        FROM experiments e
                        WHERE e.user_id = u.id
                    ) AS experiment_count,

                    (
                        SELECT COUNT(*)
                        FROM saved_configurations c
                        WHERE c.user_id = u.id
                    ) AS configuration_count,

                    (
                        SELECT COUNT(*)
                        FROM sessions s
                        WHERE s.user_id = u.id
                    ) AS session_count,

                    (
                        SELECT COUNT(*)
                        FROM sessions s
                        WHERE s.user_id = u.id
                        AND s.expires_at > ?
                    ) AS active_session_count,

                    (
                        SELECT MAX(s.last_seen_at)
                        FROM sessions s
                        WHERE s.user_id = u.id
                    ) AS last_seen_at

                FROM users u
                ORDER BY u.created_at DESC
                """,
                (now,),
            ).fetchall()

        return [
            {
                **dict(row),

                "experiments": int(
                    row["experiment_count"]
                ),

                "configurations": int(
                    row["configuration_count"]
                ),

                "sessions": int(
                    row["session_count"]
                ),

                "active_sessions": int(
                    row["active_session_count"]
                ),
            }
            for row in rows
        ]

    def user_identities(
        self,
    ) -> list[dict]:

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    ui.user_id,
                    ui.provider,
                    ui.provider_subject,
                    ui.provider_username,
                    ui.provider_email,
                    ui.provider_profile_url
                FROM user_identities ui
                ORDER BY ui.created_at DESC
                """
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    # ========================================================
    # Experiment table
    # ========================================================

    def list_experiments(
        self,
        *,
        limit: int = 100,
    ) -> list[dict]:

        with self._connect() as connection:

            rows = connection.execute(
                """
                SELECT
                    e.id,
                    e.application,
                    e.name,
                    e.backend,
                    e.status,
                    e.job_id,
                    e.cluster,
                    e.created_at,
                    e.updated_at,
                    e.finished_at,

                    u.email AS user_email,
                    u.display_name AS user_name

                FROM experiments e

                JOIN users u
                    ON u.id = e.user_id

                ORDER BY e.created_at DESC

                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    # ========================================================
    # Database diagnostics
    # ========================================================

    def table_counts(
        self,
    ) -> dict[str, int]:

        tables = [
            "users",
            "sessions",
            "saved_configurations",
            "workspaces",
            "experiments",
            "experiment_events",
            "user_identities",
            "oauth_flows",
        ]

        result = {}

        with self._connect() as connection:

            for table in tables:

                row = connection.execute(
                    f"""
                    SELECT COUNT(*) AS count
                    FROM {table}
                    """
                ).fetchone()

                result[table] = int(
                    row["count"]
                )

        return result

    def get_user(
        self,
        *,
        user_id: str,
    ) -> dict | None:

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    u.id,
                    u.email,
                    u.display_name,
                    u.institution,
                    u.research_role,
                    u.country,
                    u.default_application,
                    u.default_execution_mode,
                    u.created_at,
                    u.updated_at,

                    (
                        SELECT COUNT(*)
                        FROM experiments e
                        WHERE e.user_id = u.id
                    ) AS experiment_count,

                    (
                        SELECT COUNT(*)
                        FROM saved_configurations c
                        WHERE c.user_id = u.id
                    ) AS configuration_count,

                    (
                        SELECT COUNT(*)
                        FROM workspaces w
                        WHERE w.user_id = u.id
                    ) AS workspace_count,

                    (
                        SELECT COUNT(*)
                        FROM sessions s
                        WHERE s.user_id = u.id
                    ) AS session_count

                FROM users u
                WHERE u.id = ?
                """,
                (user_id,),
            ).fetchone()

        if row is None:
            return None

        return dict(row)


    def list_user_identities_for_user(
        self,
        *,
        user_id: str,
    ) -> list[dict]:

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    provider,
                    provider_subject,
                    provider_username,
                    provider_email,
                    provider_profile_url,
                    created_at,
                    updated_at
                FROM user_identities
                WHERE user_id = ?
                ORDER BY provider
                """,
                (user_id,),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]


    def list_user_sessions(
        self,
        *,
        user_id: str,
        now: float,
        limit: int = 20,
    ) -> list[dict]:

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    created_at,
                    last_seen_at,
                    expires_at,

                    CASE
                        WHEN expires_at > ?
                        THEN 1
                        ELSE 0
                    END AS active

                FROM sessions
                WHERE user_id = ?
                ORDER BY last_seen_at DESC
                LIMIT ?
                """,
                (
                    now,
                    user_id,
                    int(limit),
                ),
            ).fetchall()

        return [
            {
                **dict(row),
                "active": bool(row["active"]),
            }
            for row in rows
        ]


    def list_user_experiments(
        self,
        *,
        user_id: str,
        limit: int = 10,
    ) -> list[dict]:

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    application,
                    name,
                    backend,
                    status,
                    job_id,
                    cluster,
                    created_at,
                    started_at,
                    finished_at,
                    updated_at

                FROM experiments
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (
                    user_id,
                    int(limit),
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]


    def list_user_configurations(
        self,
        *,
        user_id: str,
        limit: int = 10,
    ) -> list[dict]:

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    application,
                    name,
                    description,
                    schema_version,
                    created_at,
                    updated_at

                FROM saved_configurations
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (
                    user_id,
                    int(limit),
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def authentication_provider_counts(
        self,
    ) -> dict[str, int]:

        providers = {
            "github": 0,
            "orcid": 0,
        }

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    provider,
                    COUNT(*) AS count
                FROM user_identities
                GROUP BY provider
                """
            ).fetchall()

        for row in rows:
            provider = str(
                row["provider"]
            ).strip().lower()

            providers[provider] = int(
                row["count"]
            )

        return providers


    def password_account_count(
        self,
    ) -> int:

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM users
                WHERE password_hash IS NOT NULL
                AND password_hash != ''
                """
            ).fetchone()

        return int(row["count"])


    def oauth_flow_count(
        self,
    ) -> int:

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM oauth_flows
                """
            ).fetchone()

        return int(row["count"])


    def list_linked_identities(
        self,
        *,
        limit: int = 100,
    ) -> list[dict]:

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    ui.id,
                    ui.provider,
                    ui.provider_subject,
                    ui.provider_username,
                    ui.provider_email,
                    ui.provider_profile_url,
                    ui.created_at,

                    u.id AS user_id,
                    u.display_name AS user_name,
                    u.email AS user_email

                FROM user_identities ui

                JOIN users u
                    ON u.id = ui.user_id

                ORDER BY ui.created_at DESC

                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]