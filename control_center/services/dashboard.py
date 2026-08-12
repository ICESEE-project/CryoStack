# control_center/services/dashboard.py

from __future__ import annotations

import time

from ..storage import ControlStorage


class DashboardService:
    """
    Assemble Control Center dashboard data.
    """

    def __init__(
        self,
        storage: ControlStorage,
    ) -> None:
        self.storage = storage

    def get_dashboard(
        self,
    ) -> dict:

        now = time.time()

        experiment_status = (
            self.storage
            .experiment_status_counts()
        )

        return {
            "users": {
                "total": (
                    self.storage.user_count()
                ),
                "active_sessions": (
                    self.storage
                    .active_session_count(
                        now=now
                    )
                ),
                "github": (
                    self.storage
                    .identity_count(
                        "github"
                    )
                ),
                "orcid": (
                    self.storage
                    .identity_count(
                        "orcid"
                    )
                ),
            },

            "experiments": {
                "total": (
                    self.storage
                    .experiment_count()
                ),
                **experiment_status,
            },

            "resources": {
                "configurations": (
                    self.storage
                    .configuration_count()
                ),
                "workspaces": (
                    self.storage
                    .workspace_count()
                ),
                "events": (
                    self.storage
                    .experiment_event_count()
                ),
            },

            "applications": (
                self.storage
                .application_counts()
            ),

            "database": (
                self.storage
                .table_counts()
            ),
        }