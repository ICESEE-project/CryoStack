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
    ) -> list[dict]:

        with self._connect() as connection:

            rows = connection.execute(
                """
                SELECT
                    u.id,
                    u.email,
                    u.display_name,
                    u.institution,
                    u.created_at,

                    COUNT(
                        DISTINCT e.id
                    ) AS experiment_count,

                    COUNT(
                        DISTINCT c.id
                    ) AS configuration_count,

                    COUNT(
                        DISTINCT s.id
                    ) AS session_count

                FROM users u

                LEFT JOIN experiments e
                    ON e.user_id = u.id

                LEFT JOIN saved_configurations c
                    ON c.user_id = u.id

                LEFT JOIN sessions s
                    ON s.user_id = u.id

                GROUP BY
                    u.id,
                    u.email,
                    u.display_name,
                    u.institution,
                    u.created_at

                ORDER BY
                    u.created_at DESC
                """
            ).fetchall()

        users = []

        for row in rows:

            users.append(
                {
                    "id": row["id"],
                    "email": row["email"],
                    "display_name": (
                        row["display_name"]
                    ),
                    "institution": (
                        row["institution"]
                    ),
                    "created_at": (
                        row["created_at"]
                    ),
                    "experiments": int(
                        row[
                            "experiment_count"
                        ]
                    ),
                    "configurations": int(
                        row[
                            "configuration_count"
                        ]
                    ),
                    "sessions": int(
                        row[
                            "session_count"
                        ]
                    ),
                }
            )

        return users

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