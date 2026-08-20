from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from ..storage import ControlStorage


class DiagnosticsService:

    def __init__(
        self,
        storage: ControlStorage,
    ) -> None:
        self.storage = storage

    def get_diagnostics(
        self,
    ) -> dict:

        checks = []

        # ----------------------------------------------------
        # Python
        # ----------------------------------------------------

        checks.append({
            "name": "Python",
            "status": "healthy",
            "detail": sys.version.split()[0],
        })

        # ----------------------------------------------------
        # SQLite database
        # ----------------------------------------------------

        try:
            with self.storage._connect() as connection:
                connection.execute(
                    "SELECT 1"
                ).fetchone()

            database_status = "healthy"
            database_detail = "Database responding"

        except Exception as error:
            database_status = "failed"
            database_detail = str(error)

        checks.append({
            "name": "SQLite",
            "status": database_status,
            "detail": database_detail,
        })

        # ----------------------------------------------------
        # Experiment tables
        # ----------------------------------------------------

        try:
            counts = (
                self.storage.table_counts()
            )

            checks.append({
                "name": "Experiment storage",
                "status": "healthy",
                "detail": (
                    f'{counts.get("experiments", 0)} '
                    f'experiments, '
                    f'{counts.get("experiment_events", 0)} '
                    f'events'
                ),
            })

        except Exception as error:
            checks.append({
                "name": "Experiment storage",
                "status": "failed",
                "detail": str(error),
            })

        # ----------------------------------------------------
        # GitHub
        # ----------------------------------------------------

        github = all([
            os.environ.get(
                "CRYOSTACK_GITHUB_CLIENT_ID"
            ),
            os.environ.get(
                "CRYOSTACK_GITHUB_CLIENT_SECRET"
            ),
            os.environ.get(
                "CRYOSTACK_GITHUB_REDIRECT_URI"
            ),
        ])

        checks.append({
            "name": "GitHub OAuth",
            "status": (
                "healthy"
                if github
                else "disabled"
            ),
            "detail": (
                "Configured"
                if github
                else "Not configured"
            ),
        })

        # ----------------------------------------------------
        # ORCID
        # ----------------------------------------------------

        orcid = all([
            os.environ.get(
                "CRYOSTACK_ORCID_CLIENT_ID"
            ),
            os.environ.get(
                "CRYOSTACK_ORCID_CLIENT_SECRET"
            ),
            os.environ.get(
                "CRYOSTACK_ORCID_REDIRECT_URI"
            ),
        ])

        checks.append({
            "name": "ORCID",
            "status": (
                "healthy"
                if orcid
                else "disabled"
            ),
            "detail": (
                os.environ.get(
                    "CRYOSTACK_ORCID_BASE_URL",
                    "Configured",
                )
                if orcid
                else "Not configured"
            ),
        })

        # ----------------------------------------------------
        # PACE
        #
        # We deliberately don't claim it is healthy while
        # maintenance prevents us from checking it.
        # ----------------------------------------------------

        checks.append({
            "name": "PACE",
            "status": "unknown",
            "detail": (
                "Not actively probed by "
                "Control Center yet"
            ),
        })

        # ----------------------------------------------------
        # AWS
        # ----------------------------------------------------

        aws_configured = bool(
            os.environ.get(
                "AWS_DEFAULT_REGION"
            )
            or os.environ.get(
                "AWS_REGION"
            )
        )

        checks.append({
            "name": "AWS",
            "status": (
                "configured"
                if aws_configured
                else "disabled"
            ),
            "detail": (
                "Environment configured"
                if aws_configured
                else "Cloud diagnostics not configured"
            ),
        })

        return {
            "checks": checks,
        }