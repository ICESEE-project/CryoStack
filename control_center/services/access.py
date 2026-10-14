from __future__ import annotations

import json
import secrets
import time

from icesee_auth import access_log
from icesee_auth.storage import AuthStorage


CONTROL_ROLES = {
    "developer",
    "maintainer",
    "admin",
    "owner",
}


MIN_REASON_LENGTH = 4
MAX_REASON_LENGTH = 500


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
    #
    #   * developers change nothing;
    #   * a maintainer or admin may assign only roles below their own,
    #     and only to accounts whose current role is below their own;
    #   * an owner may assign any role to anyone, so admin and owner
    #     are only ever granted by an owner;
    #   * nobody changes their own role (no self-escalation, no
    #     accidental self-lockout);
    #   * the last owner can never be removed or demoted.
    # ---------------------------------------------------------

    def _rank(
        self,
        role: str | None,
    ) -> int:

        return ROLE_LEVEL.get(
            role or "",
            0,
        )

    def can_change_roles(
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

    def allowed_role_assignments(
        self,
        *,
        actor_user_id: str,
        target_user_id: str | None = None,
    ) -> list[str]:

        actor_role = self.effective_role(
            user_id=actor_user_id,
        )

        if actor_role not in {
            "maintainer",
            "admin",
            "owner",
        }:
            return []

        if target_user_id is not None:

            if target_user_id == actor_user_id:
                return []

            target_role = self.effective_role(
                user_id=target_user_id,
            )

            if (
                actor_role != "owner"
                and self._rank(target_role)
                >= self._rank(actor_role)
            ):
                return []

        if actor_role == "owner":
            return [
                "",
                "developer",
                "maintainer",
                "admin",
                "owner",
            ]

        return [""] + [
            role
            for role in (
                "developer",
                "maintainer",
                "admin",
            )
            if self._rank(role)
            < self._rank(actor_role)
        ]

    def can_change_role(
        self,
        *,
        actor_user_id: str,
        target_user_id: str,
        new_role: str | None,
    ) -> bool:

        new_role = (
            new_role or ""
        ).strip().lower()

        return new_role in self.allowed_role_assignments(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
        )

    def can_revoke_sessions(
        self,
        *,
        actor_user_id: str,
        target_user_id: str,
    ) -> bool:

        actor_role = self.effective_role(
            user_id=actor_user_id,
        )

        if actor_role not in {
            "maintainer",
            "admin",
            "owner",
        }:
            return False

        if (
            actor_role == "owner"
            or actor_user_id == target_user_id
        ):
            return True

        return self._rank(
            self.effective_role(
                user_id=target_user_id,
            )
        ) < self._rank(actor_role)


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

    @staticmethod
    def _clean_reason(
        reason: str | None,
    ) -> str:

        reason = " ".join(
            str(reason or "").split()
        )

        if len(reason) < MIN_REASON_LENGTH:
            raise ValueError(
                "A reason of at least "
                f"{MIN_REASON_LENGTH} characters "
                "is required."
            )

        return reason[:MAX_REASON_LENGTH]

    def _label(
        self,
        user_id: str | None,
    ) -> str | None:

        if not user_id:
            return None

        user = self.storage.get_user_by_id(
            user_id
        )

        return (
            user.email
            if user is not None
            else user_id
        )

    def _deny(
        self,
        *,
        actor_user_id: str,
        target_user_id: str,
        event_type: str,
        category: str,
    ) -> None:

        try:
            self.storage.record_access_event(
                event_type=event_type,
                outcome="denied",
                category=category,
                user_id=target_user_id,
                actor_user_id=actor_user_id,
            )
        except Exception:
            pass

    def _deny_role_change(
        self,
        *,
        actor_user_id: str,
        target_user_id: str,
    ) -> None:

        self._deny(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            event_type=access_log.ROLE_CHANGE_DENIED,
            category=(
                "self_change"
                if actor_user_id == target_user_id
                else "not_permitted"
            ),
        )

        raise PermissionError(
            "You do not have permission "
            "to make this role change."
        )

    def set_control_role(
        self,
        *,
        actor_user_id: str,
        target_user_id: str,
        new_role: str | None,
        reason: str | None = None,
    ) -> str | None:

        new_role = (
            new_role or ""
        ).strip().lower()

        if new_role and new_role not in CONTROL_ROLES:
            raise ValueError(
                "Invalid CryoStack role."
            )

        if self.storage.get_user_by_id(
            target_user_id
        ) is None:
            raise LookupError(
                "User not found."
            )

        if not self.can_change_role(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            new_role=new_role,
        ):
            self._deny_role_change(
                actor_user_id=actor_user_id,
                target_user_id=target_user_id,
            )

        reason = self._clean_reason(
            reason
        )

        actor_label = self._label(
            actor_user_id
        )

        target_label = self._label(
            target_user_id
        )

        connection = self.storage._connect()

        try:
            # One write transaction: the last-owner check, the role
            # rows and the audit entry commit together or not at all.
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            # Re-check under the write lock: a concurrent change may
            # have altered either role since the first check.
            permitted = self.can_change_role(
                actor_user_id=actor_user_id,
                target_user_id=target_user_id,
                new_role=new_role,
            )

            if not permitted:
                connection.rollback()

                self._deny_role_change(
                    actor_user_id=actor_user_id,
                    target_user_id=target_user_id,
                )

            rows = connection.execute(
                """
                SELECT role
                FROM user_roles
                WHERE user_id = ?
                """,
                (target_user_id,),
            ).fetchall()

            current = [
                row["role"]
                for row in rows
                if row["role"] in CONTROL_ROLES
            ]

            current_role = (
                max(
                    current,
                    key=lambda role:
                        ROLE_LEVEL[role],
                )
                if current
                else None
            )

            if "owner" in current and new_role != "owner":

                owners = connection.execute(
                    """
                    SELECT COUNT(DISTINCT user_id)
                    FROM user_roles
                    WHERE role = 'owner'
                    """
                ).fetchone()[0]

                if owners <= 1:
                    raise ValueError(
                        "CryoStack must retain at "
                        "least one owner."
                    )

            #
            # Each person has one effective Control Center
            # role. The table still supports multiple roles
            # for future permission extensions.
            #
            connection.execute(
                f"""
                DELETE FROM user_roles
                WHERE user_id = ?
                AND role IN ({",".join("?" * len(CONTROL_ROLES))})
                """,
                (
                    target_user_id,
                    *sorted(CONTROL_ROLES),
                ),
            )

            now = time.time()

            if new_role:
                connection.execute(
                    """
                    INSERT INTO user_roles (
                        id,
                        user_id,
                        role,
                        created_at,
                        created_by
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        secrets.token_hex(16),
                        target_user_id,
                        new_role,
                        now,
                        actor_user_id,
                    ),
                )

            access_log.record_audit(
                connection,
                actor_user_id=actor_user_id,
                actor_label=actor_label or actor_user_id,
                target_user_id=target_user_id,
                target_label=target_label,
                action="role_changed",
                previous_value=current_role or "user",
                new_value=new_role or "user",
                reason=reason,
                now=now,
            )

            access_log.record_event(
                connection,
                event_type=access_log.ROLE_CHANGED,
                outcome="success",
                user_id=target_user_id,
                actor_user_id=actor_user_id,
                metadata={
                    "previous_role":
                        current_role or "user",
                    "new_role":
                        new_role or "user",
                },
                now=now,
            )

            connection.execute(
                """
                INSERT INTO control_audit_log (
                    id,
                    actor_user_id,
                    target_user_id,
                    action,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    secrets.token_hex(16),
                    actor_user_id,
                    target_user_id,
                    "control_role_changed",
                    json.dumps(
                        {
                            "previous_role":
                                current_role,

                            "new_role":
                                new_role or None,
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )

            connection.commit()

        except BaseException:
            connection.rollback()
            raise

        finally:
            connection.close()

        return (
            new_role
            if new_role
            else None
        )


    # ---------------------------------------------------------
    # Session revocation
    # ---------------------------------------------------------

    def revoke_sessions(
        self,
        *,
        actor_user_id: str,
        target_user_id: str,
        reason: str | None = None,
    ) -> int:

        if self.storage.get_user_by_id(
            target_user_id
        ) is None:
            raise LookupError(
                "User not found."
            )

        if not self.can_revoke_sessions(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
        ):
            self._deny(
                actor_user_id=actor_user_id,
                target_user_id=target_user_id,
                event_type=access_log.SESSIONS_REVOKED,
                category="not_permitted",
            )
            raise PermissionError(
                "You do not have permission to "
                "revoke this user's sessions."
            )

        reason = self._clean_reason(
            reason
        )

        connection = self.storage._connect()

        try:
            connection.execute(
                "BEGIN IMMEDIATE"
            )

            removed = connection.execute(
                "DELETE FROM sessions WHERE user_id = ?",
                (target_user_id,),
            ).rowcount

            now = time.time()

            access_log.record_audit(
                connection,
                actor_user_id=actor_user_id,
                actor_label=(
                    self._label(actor_user_id)
                    or actor_user_id
                ),
                target_user_id=target_user_id,
                target_label=self._label(
                    target_user_id
                ),
                action="sessions_revoked",
                previous_value=str(removed),
                new_value="0",
                reason=reason,
                now=now,
            )

            access_log.record_event(
                connection,
                event_type=access_log.SESSIONS_REVOKED,
                outcome="success",
                user_id=target_user_id,
                actor_user_id=actor_user_id,
                metadata={
                    "sessions_removed": removed,
                },
                now=now,
            )

            connection.commit()

        except BaseException:
            connection.rollback()
            raise

        finally:
            connection.close()

        return removed
