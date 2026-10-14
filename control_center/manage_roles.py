from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

from icesee_auth.storage import (
    AuthStorage,
    CONTROL_ROLE_RANK,
)


def _audit(
    storage: AuthStorage,
    *,
    user,
    action: str,
    previous: list[str],
    new: list[str],
    reason: str,
) -> None:

    storage.record_access_audit(
        actor_user_id=None,
        actor_label=f"local-cli:{getpass.getuser()}",
        target_user_id=user.id,
        target_label=user.email,
        action=action,
        previous_value=",".join(previous) or "user",
        new_value=",".join(new) or "user",
        reason=reason,
    )


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Manage CryoStack "
            "Control Center roles."
        )
    )

    parser.add_argument(
        "action",
        choices=[
            "add",
            "remove",
            "list",
        ],
    )

    parser.add_argument(
        "email",
    )

    parser.add_argument(
        "role",
        nargs="?",
        choices=sorted(
            CONTROL_ROLE_RANK,
            key=CONTROL_ROLE_RANK.get,
        ),
    )

    parser.add_argument(
        "--reason",
        default="",
        help=(
            "Why the access is changing "
            "(recorded in the access audit trail)."
        ),
    )

    args = parser.parse_args()

    database = Path(
        os.environ.get(
            "CRYOSTACK_AUTH_DATABASE",
            Path(__file__)
            .resolve()
            .parent
            .parent
            / "var"
            / "cryostack_auth.db",
        )
    )

    storage = AuthStorage(
        database
    )

    user = storage.get_user_by_email(
        args.email.strip().lower()
    )

    if user is None:
        raise SystemExit(
            f"User not found: {args.email}"
        )

    if args.action == "list":

        roles = storage.get_user_roles(
            user_id=user.id
        )

        print(
            f"{user.email}: "
            + (
                ", ".join(roles)
                if roles
                else "no roles"
            )
        )

        return

    if not args.role:
        raise SystemExit(
            "A role is required."
        )

    reason = " ".join(
        args.reason.split()
    )

    if len(reason) < 4:
        raise SystemExit(
            "A --reason of at least 4 "
            "characters is required."
        )

    previous = storage.get_user_roles(
        user_id=user.id
    )

    if args.action == "add":

        storage.add_user_role(
            user_id=user.id,
            role=args.role,
        )

        _audit(
            storage,
            user=user,
            action="role_granted",
            previous=previous,
            new=storage.get_user_roles(
                user_id=user.id
            ),
            reason=reason,
        )

        print(
            f"Added {args.role} "
            f"to {user.email}"
        )

    elif args.action == "remove":

        if args.role == "owner" and "owner" in previous:
            with storage._connect() as connection:
                owners = connection.execute(
                    """
                    SELECT COUNT(DISTINCT user_id)
                    FROM user_roles
                    WHERE role = 'owner'
                    """
                ).fetchone()[0]

            if owners <= 1:
                raise SystemExit(
                    "CryoStack must retain at "
                    "least one owner."
                )

        removed = (
            storage.remove_user_role(
                user_id=user.id,
                role=args.role,
            )
        )

        if removed:
            _audit(
                storage,
                user=user,
                action="role_revoked",
                previous=previous,
                new=storage.get_user_roles(
                    user_id=user.id
                ),
                reason=reason,
            )

        print(
            "Removed."
            if removed
            else "Role was not assigned."
        )


if __name__ == "__main__":
    main()