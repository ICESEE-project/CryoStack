# control_center/services/users.py

from __future__ import annotations

from ..storage import ControlStorage


class UserService:

    def __init__(
        self,
        storage: ControlStorage,
    ) -> None:
        self.storage = storage

    def list_users(
        self,
    ) -> list[dict]:

        users = (
            self.storage.list_users()
        )

        identities = (
            self.storage
            .user_identities()
        )

        identity_map: dict[
            str,
            dict[str, dict],
        ] = {}

        for identity in identities:

            user_id = identity[
                "user_id"
            ]

            provider = identity[
                "provider"
            ]

            identity_map.setdefault(
                user_id,
                {},
            )[provider] = identity

        for user in users:
            user["identities"] = (
                identity_map.get(
                    user["id"],
                    {},
                )
            )

        return users