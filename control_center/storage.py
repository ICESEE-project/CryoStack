# control_center/storage.py

from __future__ import annotations

import sqlite3
from pathlib import Path


_ROLE_RANK_SQL = """
    (
        SELECT MAX(
            CASE r.role
                WHEN 'owner' THEN 40
                WHEN 'admin' THEN 30
                WHEN 'maintainer' THEN 20
                WHEN 'developer' THEN 10
                ELSE 0
            END
        )
        FROM user_roles r
        WHERE r.user_id = u.id
    )
"""

ROLE_FOR_RANK = {
    40: "owner",
    30: "admin",
    20: "maintainer",
    10: "developer",
}

RANK_FOR_ROLE = {
    role: rank
    for rank, role in ROLE_FOR_RANK.items()
}


def _like(
    value: str,
) -> str:

    escaped = (
        value
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )

    return f"%{escaped}%"


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
            # Session ids are bearer credentials: never selected here.
            rows = connection.execute(
                """
                SELECT
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


    def get_experiment(
        self,
        *,
        experiment_id: str,
    ) -> dict | None:

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    e.*,

                    u.display_name AS user_name,
                    u.email AS user_email

                FROM experiments e

                JOIN users u
                    ON u.id = e.user_id

                WHERE e.id = ?
                """,
                (experiment_id,),
            ).fetchone()

        if row is None:
            return None

        return dict(row)


    def list_experiment_events(
        self,
        *,
        experiment_id: str,
    ) -> list[dict]:

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    experiment_id,
                    user_id,
                    event_type,
                    message,
                    metadata_json,
                    created_at

                FROM experiment_events

                WHERE experiment_id = ?

                ORDER BY created_at ASC
                """,
                (experiment_id,),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    # ========================================================
    # Account directory (search / filter / pagination)
    # ========================================================

    def search_users(
        self,
        *,
        now: float,
        query: str = "",
        role: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:

        where = []
        params: list = []

        query = (query or "").strip()

        if query:
            where.append(
                """
                (
                    u.email LIKE ? ESCAPE '\\'
                    OR u.display_name LIKE ? ESCAPE '\\'
                    OR COALESCE(u.institution, '') LIKE ? ESCAPE '\\'
                    OR u.id = ?
                )
                """
            )
            pattern = _like(query)
            params += [pattern, pattern, pattern, query]

        role = (role or "").strip().lower()

        if role == "user":
            where.append(
                f"COALESCE({_ROLE_RANK_SQL}, 0) = 0"
            )

        elif role in RANK_FOR_ROLE:
            where.append(
                f"COALESCE({_ROLE_RANK_SQL}, 0) = ?"
            )
            params.append(RANK_FOR_ROLE[role])

        clause = (
            "WHERE " + " AND ".join(where)
            if where
            else ""
        )

        with self._connect() as connection:

            total = connection.execute(
                f"SELECT COUNT(*) FROM users u {clause}",
                params,
            ).fetchone()[0]

            rows = connection.execute(
                f"""
                SELECT
                    u.id,
                    u.email,
                    u.display_name,
                    u.institution,
                    u.created_at,

                    COALESCE({_ROLE_RANK_SQL}, 0) AS role_rank,

                    (
                        SELECT GROUP_CONCAT(provider)
                        FROM (
                            SELECT DISTINCT ui.provider AS provider
                            FROM user_identities ui
                            WHERE ui.user_id = u.id
                        )
                    ) AS providers,

                    (
                        SELECT COUNT(*)
                        FROM experiments e
                        WHERE e.user_id = u.id
                    ) AS experiments,

                    (
                        SELECT COUNT(*)
                        FROM saved_configurations c
                        WHERE c.user_id = u.id
                    ) AS configurations,

                    (
                        SELECT COUNT(*)
                        FROM sessions s
                        WHERE s.user_id = u.id
                        AND s.expires_at > ?
                    ) AS active_sessions,

                    (
                        SELECT MAX(s.last_seen_at)
                        FROM sessions s
                        WHERE s.user_id = u.id
                    ) AS last_seen_at

                FROM users u
                {clause}
                ORDER BY u.created_at DESC, u.id
                LIMIT ? OFFSET ?
                """,
                [now, *params, int(limit), int(offset)],
            ).fetchall()

        users = []

        for row in rows:
            user = dict(row)
            user["control_role"] = ROLE_FOR_RANK.get(
                int(user.pop("role_rank") or 0),
                "user",
            )
            user["providers"] = sorted(
                p
                for p in (user["providers"] or "").split(",")
                if p
            )
            users.append(user)

        return users, int(total)

    def account_index(
        self,
    ) -> list[dict]:
        """Every account id with its label, for workspace mapping."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    email,
                    display_name,
                    created_at
                FROM users
                ORDER BY created_at DESC, id
                """
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    # ========================================================
    # Sign-in diagnostics
    # ========================================================

    def _has_table(
        self,
        connection,
        name: str,
    ) -> bool:

        return connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (name,),
        ).fetchone() is not None

    def login_summary(
        self,
        *,
        user_id: str,
        now: float,
        failure_limit: int = 8,
    ) -> dict:

        with self._connect() as connection:

            sessions = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN expires_at > ? THEN 1 ELSE 0 END)
                        AS active,
                    MAX(created_at) AS newest,
                    MAX(last_seen_at) AS last_seen
                FROM sessions
                WHERE user_id = ?
                """,
                (now, user_id),
            ).fetchone()

            summary = {
                "sessions_total": int(sessions["total"] or 0),
                "sessions_active": int(sessions["active"] or 0),
                "newest_session_at": sessions["newest"],
                "last_seen_at": sessions["last_seen"],
                "last_login_at": None,
                "last_login_provider": None,
                "failures_24h": 0,
                "recent_failures": [],
                "last_revoked_at": None,
            }

            if not self._has_table(
                connection,
                "access_events",
            ):
                return summary

            row = connection.execute(
                """
                SELECT created_at, provider
                FROM access_events
                WHERE user_id = ?
                AND event_type IN ('login_success', 'register')
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()

            if row is not None:
                summary["last_login_at"] = row["created_at"]
                summary["last_login_provider"] = row["provider"]

            summary["failures_24h"] = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM access_events
                    WHERE user_id = ?
                    AND outcome IN ('failure', 'denied')
                    AND created_at > ?
                    """,
                    (user_id, now - 86400),
                ).fetchone()[0]
            )

            summary["recent_failures"] = [
                dict(r)
                for r in connection.execute(
                    """
                    SELECT
                        created_at,
                        event_type,
                        category,
                        provider,
                        path
                    FROM access_events
                    WHERE user_id = ?
                    AND outcome IN ('failure', 'denied')
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (user_id, int(failure_limit)),
                ).fetchall()
            ]

            row = connection.execute(
                """
                SELECT MAX(created_at)
                FROM access_events
                WHERE user_id = ?
                AND event_type = 'sessions_revoked'
                AND outcome = 'success'
                """,
                (user_id,),
            ).fetchone()

            summary["last_revoked_at"] = row[0]

        return summary

    def failure_category_counts(
        self,
        *,
        since: float,
    ) -> dict[str, int]:

        with self._connect() as connection:

            if not self._has_table(
                connection,
                "access_events",
            ):
                return {}

            rows = connection.execute(
                """
                SELECT
                    COALESCE(category, event_type) AS category,
                    COUNT(*) AS count
                FROM access_events
                WHERE outcome IN ('failure', 'denied')
                AND created_at > ?
                GROUP BY COALESCE(category, event_type)
                ORDER BY count DESC
                """,
                (since,),
            ).fetchall()

        return {
            row["category"]: int(row["count"])
            for row in rows
        }

    # ========================================================
    # Access events and audit trail
    # ========================================================

    def list_access_events(
        self,
        *,
        event_type: str = "",
        outcome: str = "",
        user_id: str = "",
        since: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:

        where = []
        params: list = []

        if event_type:
            where.append("e.event_type = ?")
            params.append(event_type)

        if outcome:
            where.append("e.outcome = ?")
            params.append(outcome)

        if user_id:
            where.append(
                "(e.user_id = ? OR e.actor_user_id = ?)"
            )
            params += [user_id, user_id]

        if since is not None:
            where.append("e.created_at > ?")
            params.append(since)

        clause = (
            "WHERE " + " AND ".join(where)
            if where
            else ""
        )

        with self._connect() as connection:

            if not self._has_table(
                connection,
                "access_events",
            ):
                return [], 0

            total = connection.execute(
                f"SELECT COUNT(*) FROM access_events e {clause}",
                params,
            ).fetchone()[0]

            rows = connection.execute(
                f"""
                SELECT
                    e.created_at,
                    e.event_type,
                    e.outcome,
                    e.category,
                    e.provider,
                    e.path,
                    e.metadata_json,
                    e.user_id,
                    e.actor_user_id,
                    tu.email AS user_email,
                    au.email AS actor_email
                FROM access_events e
                LEFT JOIN users tu ON tu.id = e.user_id
                LEFT JOIN users au ON au.id = e.actor_user_id
                {clause}
                ORDER BY e.created_at DESC, e.id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, int(limit), int(offset)],
            ).fetchall()

        return [dict(row) for row in rows], int(total)

    def list_access_audit(
        self,
        *,
        target_user_id: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:

        clause = ""
        params: list = []

        if target_user_id:
            clause = (
                "WHERE target_user_id = ? "
                "OR actor_user_id = ?"
            )
            params = [target_user_id, target_user_id]

        with self._connect() as connection:

            if not self._has_table(
                connection,
                "access_audit_log",
            ):
                return [], 0

            total = connection.execute(
                f"SELECT COUNT(*) FROM access_audit_log {clause}",
                params,
            ).fetchone()[0]

            rows = connection.execute(
                f"""
                SELECT
                    created_at,
                    actor_user_id,
                    actor_label,
                    target_user_id,
                    target_label,
                    action,
                    previous_value,
                    new_value,
                    reason
                FROM access_audit_log
                {clause}
                ORDER BY created_at DESC, id
                LIMIT ? OFFSET ?
                """,
                [*params, int(limit), int(offset)],
            ).fetchall()

        return [dict(row) for row in rows], int(total)
