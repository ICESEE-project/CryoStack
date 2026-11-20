"""Fail closed on a missing/replaced service-managed workspace mount.

This protects bulk files only. SQLite and control state use local storage.
The operator pins both the mountpoint and a volume identifier before cutover.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

MOUNT_ENV = "CRYOSTACK_WORKSPACE_MOUNT"
VOLUME_ENV = "CRYOSTACK_WORKSPACE_VOLUME_ID"
MARKER = ".cryostack-workspace-volume.json"
SCHEMA = "cryostack.workspace.volume.v1"


class WorkspaceStorageUnavailable(OSError):
    """Do not accept a write onto an absent or unverified workspace volume."""


def require_workspace_storage(path: str | Path, *, environment=None) -> None:
    settings = os.environ if environment is None else environment
    configured = settings.get(MOUNT_ENV, "").strip()
    if not configured:
        return  # Existing local deployments remain supported until cutover.
    mount = Path(configured).expanduser().absolute()
    expected = settings.get(VOLUME_ENV, "").strip()
    try:
        if not expected or mount.is_symlink() or not os.path.ismount(mount):
            raise ValueError("required workspace mount is unavailable")
        target = Path(path).resolve()
        if not target.is_relative_to(mount.resolve()):
            raise ValueError("workspace destination is outside the configured mount")
        marker = mount / MARKER
        if marker.is_symlink():
            raise ValueError("workspace volume marker must not be a symlink")
        data = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("volume_id") != expected:
            raise ValueError("workspace volume identity does not match")
    except (OSError, ValueError, TypeError) as error:
        raise WorkspaceStorageUnavailable(
            "Workspace storage is temporarily unavailable. No files were saved. "
            "Please retry later or contact the organizer."
        ) from error
