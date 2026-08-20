from __future__ import annotations

import argparse
import os
from pathlib import Path

from icesee_auth.storage import (
    AuthStorage,
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
        choices=[
            "developer",
            "administrator",
            "owner",
        ],
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

    if args.action == "add":

        storage.add_user_role(
            user_id=user.id,
            role=args.role,
        )

        print(
            f"Added {args.role} "
            f"to {user.email}"
        )

    elif args.action == "remove":

        removed = (
            storage.remove_user_role(
                user_id=user.id,
                role=args.role,
            )
        )

        print(
            "Removed."
            if removed
            else "Role was not assigned."
        )


if __name__ == "__main__":
    main()