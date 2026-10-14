"""Read-only, authenticated example context; no run/history/result discovery."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat

from cryostack_src.workspace.identity import resolve_workspace_user

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _plain_tree(path):
    """Reject links before model adapters inspect a research example's files."""
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            item = Path(root) / name
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode):
                return False
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                return False
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                return False
    return True


def workspace_examples(manager, model):
    """Use the existing example namespace, never a user-selected owner or path.

    Explicit CLI identity overrides are not authenticated workspace context.
    Only existing model/example identity is reused: arbitrary provenance keys,
    saved run settings, scripts and results are not configuration suggestions.
    """
    user = resolve_workspace_user()
    if not user.is_authenticated or user != manager.owner or not _NAME.fullmatch(model):
        return []
    # Check the lexical namespace as well as resolved ownership: an owner or
    # model directory must not redirect discovery into another account.
    owner = manager._workspace_root / "users" / user.safe_id
    root = owner / "examples" / model
    try:
        if owner.resolve() != owner or root.resolve() != root or manager._owner_root != owner:
            return []
        if not root.is_dir():
            return []
        examples = []
        for directory in sorted(root.iterdir()):
            if not _NAME.fullmatch(directory.name) or directory.is_symlink() or not directory.is_dir():
                continue
            marker = directory / ".cryostack-example.json"
            if not _plain_tree(directory) or not marker.is_file() or marker.stat().st_size > 65536:
                continue
            record = json.loads(marker.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or record.get("owner") != user.safe_id or record.get("model") != model:
                continue
            if record.get("kind") != "cryostack-user-example" or record.get("name") != directory.name:
                continue
            # Only display a safe local example name, never source paths or IDs.
            examples.append(dict(name=directory.name, path=str(directory), model=model,
                                 source_type="user-example", source_name=None))
        return examples
    except (OSError, ValueError, RuntimeError):
        return []  # Unreadable/untrusted context is never used as a fallback.


def require_workspace_scope(manager):
    """A panel cannot outlive its authenticated owner and reuse their controls."""
    user = resolve_workspace_user()
    if user.is_authenticated and user != manager.owner:
        raise ValueError("The account changed. Reopen Auto-config for the current account.")
    if manager.owner.is_authenticated and not user.is_authenticated:
        raise ValueError("Authenticated workspace context is no longer available.")
    return user.safe_id
