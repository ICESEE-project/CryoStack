from __future__ import annotations

import time

from ..storage import ControlStorage

from .access import AccessService

PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

ROLE_FILTERS = (
    "",
    "user",
    "developer",
    "maintainer",
    "admin",
    "owner",
)


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
        now: float | None = None,
    ) -> list[dict]:

        users = self.storage.list_users(
            now=time.time() if now is None else now,
        )

        for user in users:
            user["control_role"] = (
                self.access.effective_role(
                    user_id=user["id"],
                )
                or "user"
            )

        return users

    def search_users(
        self,
        *,
        query: str = "",
        role: str = "",
        page: int = 1,
        per_page: int = PAGE_SIZE,
        now: float | None = None,
    ) -> dict:

        role = (role or "").strip().lower()

        if role not in ROLE_FILTERS:
            role = ""

        per_page = min(
            max(int(per_page), 1),
            MAX_PAGE_SIZE,
        )

        page = max(int(page), 1)

        query = (query or "").strip()[:200]

        users, total = self.storage.search_users(
            now=time.time() if now is None else now,
            query=query,
            role=role,
            limit=per_page,
            offset=(page - 1) * per_page,
        )

        return {
            "users": users,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(
                (total + per_page - 1) // per_page,
                1,
            ),
            "query": query,
            "role": role,
        }

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

        user["login"] = (
            self.storage
            .login_summary(
                user_id=user_id,
                now=now,
            )
        )

        user["control_role"] = (
            self.access.effective_role(
                user_id=user["id"],
            )
            or "user"
        )

        return user
