"""Provision an approved account's private workspace.

Runs in the gateway, under CryoStack's own service identity: no CEDAR or
operating-system account is created for the participant, and nothing is
written to reserve space. Provisioning creates the owner directory
``<workspace-root>/users/<safe-id>`` -- the same directory every application
resolves for that account -- and reads the allowance that applies to it
(the Control Center default, currently targeted at 5 GiB, or the account's
explicit override). The allowance is a limit enforced on writes, not a
physical reservation; an existing override is never changed.

The workspace root is resolved exactly as for every other workspace write.
When a service-managed workspace mount is configured, its mountpoint and
volume marker are verified before provisioning succeeds, so an unavailable
mount never falls back to local VM storage. Owner and ``users`` symlinks are
also rejected. Running it again for an existing workspace changes nothing.
"""
from __future__ import annotations

from pathlib import Path


def provision_owner_workspace(user_id: str, *, workspace_root: str | Path | None = None) -> dict:
    from cryostack_src.workspace.identity import WorkspaceUser
    from cryostack_src.workspace.roots import resolve_workspace_root
    from cryostack_src.workspace.storage_mount import require_workspace_storage
    from cryostack_src.workspace import storage_policy

    user = WorkspaceUser(user_id=user_id, source="cryostack-auth")
    root = resolve_workspace_root(workspace_root)        # fails closed
    users = root / "users"
    if users.is_symlink() or (users / user.safe_id).is_symlink():
        raise RuntimeError("workspace owner and users directories may not be a symbolic link")
    owner = (users / user.safe_id).resolve()
    if not owner.is_relative_to(users.resolve()):
        raise RuntimeError("workspace path escaped the users directory")
    if owner.is_symlink():
        raise RuntimeError("workspace path is a symbolic link")
    # Refuse an absent/replaced configured mount before creating local paths.
    require_workspace_storage(owner)
    users.mkdir(parents=True, exist_ok=True)
    owner.mkdir(mode=0o700, exist_ok=True)
    # Recheck after creation in case the mount changed during provisioning.
    require_workspace_storage(owner)
    store, _accounts = storage_policy.policy()
    allowance, overridden = store.quota_for(user_id)
    return {
        "owner_key": user.safe_id,
        "allowance_bytes": int(allowance),
        "allowance_source": "override" if overridden else "default",
    }
