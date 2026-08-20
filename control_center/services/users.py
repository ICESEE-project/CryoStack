from __future__ import annotations

import time

from ..storage import ControlStorage

from .access import AccessService

class UserService:

    def __init__(
        self,
        storage: ControlStorage,
        access: AccessService,
    ) -> None:
        self.storage = storage
        self.access = access

    def list_users(
        self,
        *,
        now: float,
    ) -> list[dict]:

        users = self.storage.list_users(
            now=now,
        )

        for user in users:
            user["control_role"] = (
                self.access.effective_role(
                    user_id=user["id"],
                )
                or "user"
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

        user["control_role"] = (
            self.access.effective_role(
                user_id=user["id"],
            )
            or "user"
        )

        return user