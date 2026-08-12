from __future__ import annotations

import time

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

        now = time.time()

        users = self.storage.list_users(
            now=now,
        )

        identities = (
            self.storage.user_identities()
        )

        identity_map: dict[
            str,
            dict[str, dict],
        ] = {}

        for identity in identities:

            user_id = identity["user_id"]
            provider = identity["provider"]

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

    def get_user(
        self,
        *,
        user_id: str,
    ) -> dict | None:

        user = self.storage.get_user(
            user_id=user_id,
        )

        if user is None:
            return None

        now = time.time()

        user["identities"] = (
            self.storage
            .list_user_identities_for_user(
                user_id=user_id,
            )
        )

        user["sessions_detail"] = (
            self.storage
            .list_user_sessions(
                user_id=user_id,
                now=now,
            )
        )

        user["recent_experiments"] = (
            self.storage
            .list_user_experiments(
                user_id=user_id,
            )
        )

        user["recent_configurations"] = (
            self.storage
            .list_user_configurations(
                user_id=user_id,
            )
        )

        return user