from __future__ import annotations

import json

from icesee_auth.storage import AuthStorage


CONTROL_ROLES = {
    "developer",
    "maintainer",
    "admin",
    "owner",
}


ROLE_LEVEL = {
    "developer": 10,
    "maintainer": 20,
    "admin": 30,
    "owner": 40,
}


class AccessService:
    """
    CryoStack Control Center authorization service.

    Authentication answers:
        Who is the user?

    This service answers:
        What is the user allowed to do?
    """

    def __init__(
        self,
        storage: AuthStorage,
    ) -> None:
        self.storage = storage


    # ---------------------------------------------------------
    # Role lookup
    # ---------------------------------------------------------

    def roles(
        self,
        *,
        user_id: str,
    ) -> list[str]:

        return self.storage.list_user_roles(
            user_id=user_id,
        )


    def effective_role(
        self,
        *,
        user_id: str,
    ) -> str | None:

        roles = [
            role
            for role in self.roles(
                user_id=user_id,
            )
            if role in CONTROL_ROLES
        ]

        if not roles:
            return None

        return max(
            roles,
            key=lambda role:
                ROLE_LEVEL[role],
        )


    def has_role(
        self,
        *,
        user_id: str,
        role: str,
    ) -> bool:

        role = role.strip().lower()

        if role not in CONTROL_ROLES:
            return False

        return self.storage.has_role(
            user_id=user_id,
            role=role,
        )


    # ---------------------------------------------------------
    # Control Center access
    # ---------------------------------------------------------

    def can_access_control_center(
        self,
        *,
        user_id: str,
    ) -> bool:

        return (
            self.effective_role(
                user_id=user_id,
            )
            is not None
        )


    def can_manage_roles(
        self,
        *,
        user_id: str,
    ) -> bool:

        return self.effective_role(
            user_id=user_id,
        ) in {
            "admin",
            "owner",
        }


    def can_manage_platform(
        self,
        *,
        user_id: str,
    ) -> bool:

        return self.effective_role(
            user_id=user_id,
        ) == "owner"


    def can_operate_compute(
        self,
        *,
        user_id: str,
    ) -> bool:

        return self.effective_role(
            user_id=user_id,
        ) in {
            "maintainer",
            "admin",
            "owner",
        }


    # ---------------------------------------------------------
    # Role assignment policy
    # ---------------------------------------------------------

    def allowed_role_assignments(
        self,
        *,
        actor_user_id: str,
    ) -> list[str]:

        actor_role = self.effective_role(
            user_id=actor_user_id,
        )

        if actor_role == "owner":
            return [
                "",
                "developer",
                "maintainer",
                "admin",
                "owner",
            ]

        if actor_role == "admin":
            return [
                "",
                "developer",
                "maintainer",
            ]

        return []


    def can_change_role(
        self,
        *,
        actor_user_id: str,
        target_user_id: str,
        new_role: str | None,
    ) -> bool:

        actor_role = self.effective_role(
            user_id=actor_user_id,
        )

        target_role = self.effective_role(
            user_id=target_user_id,
        )

        new_role = (
            new_role or ""
        ).strip().lower()

        if actor_role == "owner":
            return new_role in {
                "",
                "developer",
                "maintainer",
                "admin",
                "owner",
            }

        if actor_role == "admin":

            #
            # Admins cannot modify admins or owners.
            #
            if target_role in {
                "admin",
                "owner",
            }:
                return False

            return new_role in {
                "",
                "developer",
                "maintainer",
            }

        return False


    # ---------------------------------------------------------
    # Owner safety
    # ---------------------------------------------------------

    def owner_count(
        self,
    ) -> int:

        with self.storage._connect() as connection:

            row = connection.execute(
                """
                SELECT
                    COUNT(
                        DISTINCT user_id
                    ) AS count

                FROM user_roles

                WHERE role = 'owner'
                """
            ).fetchone()

        return int(
            row["count"]
        )


    # ---------------------------------------------------------
    # Change effective Control Center role
    # ---------------------------------------------------------

    def set_control_role(
        self,
        *,
        actor_user_id: str,
        target_user_id: str,
        new_role: str | None,
    ) -> str | None:

        new_role = (
            new_role or ""
        ).strip().lower()

        if new_role and new_role not in CONTROL_ROLES:
            raise ValueError(
                "Invalid CryoStack role."
            )

        current_role = self.effective_role(
            user_id=target_user_id,
        )

        if not self.can_change_role(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            new_role=new_role,
        ):
            raise PermissionError(
                "You do not have permission "
                "to make this role change."
            )

        #
        # Never remove or demote the last Owner.
        #
        if (
            current_role == "owner"
            and new_role != "owner"
            and self.owner_count() <= 1
        ):
            raise ValueError(
                "CryoStack must retain at "
                "least one owner."
            )

        #
        # For now each person gets one effective
        # Control Center role.
        #
        # The table still supports multiple roles
        # for future permission extensions.
        #
        for role in CONTROL_ROLES:

            self.storage.revoke_role(
                user_id=target_user_id,
                role=role,
            )

        if new_role:

            self.storage.grant_role(
                user_id=target_user_id,
                role=new_role,
                created_by=actor_user_id,
            )

        #
        # Audit every role change.
        #
        self.storage.add_control_audit_event(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            action="control_role_changed",
            metadata_json=json.dumps(
                {
                    "previous_role":
                        current_role,

                    "new_role":
                        new_role or None,
                },
                sort_keys=True,
            ),
        )

        return (
            new_role
            if new_role
            else None
        )