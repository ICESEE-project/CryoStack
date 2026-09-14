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


def resolve_workspace_root(workspace_root: str | Path | None = None) -> Path:
    """The shared workspace root: explicit arg → ``$CRYOSTACK_WORKSPACE_ROOT`` →
    process cwd. Same precedence as :class:`WorkspaceManager`."""
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    env_root = (os.environ.get(WORKSPACE_ROOT_ENV) or "").strip()
    return Path(env_root).resolve() if env_root else Path.cwd().resolve()


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
