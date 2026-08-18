from __future__ import annotations

import os

from ..storage import ControlStorage


class AuthenticationService:

    def __init__(
        self,
        storage: ControlStorage,
    ) -> None:
        self.storage = storage

    @staticmethod
    def _configured(
        *names: str,
    ) -> bool:

        return all(
            bool(
                os.environ.get(
                    name,
                    "",
                ).strip()
            )
            for name in names
        )

    def get_overview(
        self,
    ) -> dict:

        counts = (
            self.storage
            .authentication_provider_counts()
        )

        github_configured = (
            self._configured(
                "CRYOSTACK_GITHUB_CLIENT_ID",
                "CRYOSTACK_GITHUB_CLIENT_SECRET",
                "CRYOSTACK_GITHUB_REDIRECT_URI",
            )
        )

        orcid_configured = (
            self._configured(
                "CRYOSTACK_ORCID_CLIENT_ID",
                "CRYOSTACK_ORCID_CLIENT_SECRET",
                "CRYOSTACK_ORCID_REDIRECT_URI",
            )
        )

        return {
            "providers": {
                "password": {
                    "configured": True,
                    "linked": (
                        self.storage
                        .password_account_count()
                    ),
                },

                "github": {
                    "configured": (
                        github_configured
                    ),
                    "linked": counts.get(
                        "github",
                        0,
                    ),
                },

                "orcid": {
                    "configured": (
                        orcid_configured
                    ),
                    "linked": counts.get(
                        "orcid",
                        0,
                    ),
                    "sandbox": (
                        "sandbox.orcid.org"
                        in os.environ.get(
                            "CRYOSTACK_ORCID_BASE_URL",
                            "",
                        )
                    ),
                },

                "google": {
                    "configured": False,
                    "linked": 0,
                },

                "university_sso": {
                    "configured": False,
                    "linked": 0,
                },
            },

            "oauth_flows": (
                self.storage
                .oauth_flow_count()
            ),

            "identities": (
                self.storage
                .list_linked_identities()
            ),
        }