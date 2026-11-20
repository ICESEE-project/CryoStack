"""Per-user workspace-root resolution, usable without a full ``WorkspaceManager``.

``WorkspaceManager`` confines every user's runs/examples/datasets to
``<workspace-root>/users/<safe-id>/…``. An app that only needs the *run
directory* location (e.g. ICESEE routing ``local_runner.run_dir``) can compute
the same path here without constructing the manager.

Kept deliberately tiny; ``test_roots.py`` asserts it stays consistent with what
``WorkspaceManager`` produces.
"""
from __future__ import annotations

import os
from pathlib import Path

from .identity import WorkspaceUser, resolve_workspace_user

#: deploy-time pin for the workspace root, independent of process cwd
WORKSPACE_ROOT_ENV = "CRYOSTACK_WORKSPACE_ROOT"
LOCAL_CONTROL_SCOPES = ("cloud", "session", "agents", "home", "identity", "coordination")


def resolve_workspace_root(workspace_root: str | Path | None = None) -> Path:
    """The shared workspace root: explicit arg → ``$CRYOSTACK_WORKSPACE_ROOT`` →
    process cwd. Same precedence as :class:`WorkspaceManager`."""
    if workspace_root is not None:
        root = Path(workspace_root).resolve()
        from .storage_mount import require_workspace_storage
        require_workspace_storage(root / "users")
        return root
    from cryostack_src.storage_layout import resolve

    # $CRYOSTACK_WORKSPACE_ROOT → $CRYOSTACK_DATA_ROOT/workspace → process cwd
    root = resolve("workspaces")[0].resolve()
    from .storage_mount import require_workspace_storage
    require_workspace_storage(root / "users")
    return root


def owner_root(user: WorkspaceUser, *, workspace_root: str | Path | None = None) -> Path:
    """``<workspace-root>/users/<safe-id>`` -- the per-user boundary."""
    return (resolve_workspace_root(workspace_root) / "users" / user.safe_id).resolve()


def user_run_root(
    *,
    app: str,
    user: WorkspaceUser | None = None,
    workspace_root: str | Path | None = None,
    require_authenticated: bool = False,
) -> Path:
    """``<owner-root>/.cryostack/<app>_runs`` -- a per-user, per-app run root.

    Two authenticated CryoStack users never share it (the safe-id segment
    differs), which is the property ICESEE's process-global
    ``BOOK/icesee_runs/`` lacked.
    """
    u = user or resolve_workspace_user(require_authenticated=require_authenticated)
    seg = "".join(c if c.isalnum() or c in "-_" else "-" for c in (app or "app")).strip("-") or "app"
    root = (owner_root(u, workspace_root=workspace_root) / ".cryostack" / f"{seg}_runs").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def state_owner_root(user: WorkspaceUser, *, workspace_root: str | Path | None = None) -> Path:
    """Small control state stays local when bulk workspaces move to CEDAR.

    Pin CRYOSTACK_WORKSPACE_STATE_ROOT to the original local workspace root
    during cutover. This preserves existing connection/session state in place.
    Without that setting the historical single-root layout is unchanged.
    """
    configured = os.environ.get("CRYOSTACK_WORKSPACE_STATE_ROOT", "").strip()
    if not configured:
        return owner_root(user, workspace_root=workspace_root)
    root = Path(configured).expanduser().resolve()
    mount = os.environ.get("CRYOSTACK_WORKSPACE_MOUNT", "").strip()
    owner = (root / "users" / user.safe_id).resolve()
    if mount and owner.is_relative_to(Path(mount).expanduser().resolve()):
        raise RuntimeError("Control state must be outside the workspace mount.")
    return owner


def coordination_path(user: WorkspaceUser, *, scope: str, key: str) -> Path:
    """A local per-owner lock path; never place advisory locks on bulk SMB."""
    import re
    if not re.fullmatch(r"[a-z0-9_-]{1,80}", scope) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", key) or key in {".", ".."}:
        raise ValueError("Invalid coordination namespace.")
    if os.environ.get("CRYOSTACK_WORKSPACE_MOUNT", "").strip() and not os.environ.get("CRYOSTACK_WORKSPACE_STATE_ROOT", "").strip():
        raise RuntimeError("Local workspace control storage must be configured before bulk storage cutover.")
    owner = state_owner_root(user)
    target = owner / ".cryostack" / "coordination" / scope / key
    if not target.resolve().is_relative_to(owner):
        raise RuntimeError("Coordination path escaped its owner.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise RuntimeError("Coordination lock may not be a symbolic link.")
    return target
