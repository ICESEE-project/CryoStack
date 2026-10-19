"""Fail-closed expiry and reclamation for resumable scientific intake."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from cryostack_src.storage_layout import atomic_write

from . import resumable_intake as RI
from .storage import StorageError

DEFAULT_MAX_IDLE_SECONDS = 7 * 24 * 60 * 60
DEFAULT_RECOVERY_GRACE_SECONDS = 24 * 60 * 60
AUDIT_NAME = ".upload-session-cleanup.jsonl"


def _seconds(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        raise StorageError(f"{name} must be a non-negative integer.")
    if value < 0:
        raise StorageError(f"{name} must be a non-negative integer.")
    return value


def _recognized(root: Path, path: Path) -> dict | None:
    try:
        if path.is_symlink() or not path.is_dir() or path.parent != root:
            return None
        manifest = path / "session.json"
        if manifest.is_symlink() or not manifest.is_file():
            return None
        document = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if (document.get("schema") != RI.SCHEMA or document.get("session_id") != path.name
            or not path.name.startswith("in-")):
        return None
    return document


def _contains_symlink(path: Path) -> bool:
    try:
        return any(item.is_symlink() for item in path.rglob("*"))
    except OSError:
        return True


def _tree_bytes(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file() and not item.is_symlink():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def _audit(root: Path, event: dict) -> None:
    event = {**event, "schema": "cryostack.frozen-legacies.intake-cleanup-audit"}
    descriptor = os.open(root / AUDIT_NAME, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, (json.dumps(event, sort_keys=True) + "\n").encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def inventory(actor_id: str, *, administrator: bool = False, now: int | None = None) -> list[dict]:
    """List only sessions visible to an owner or privileged operator."""
    now = int(time.time()) if now is None else int(now)
    maximum = _seconds("CRYOSTACK_FROZEN_LEGACIES_UPLOAD_MAX_IDLE_SECONDS", DEFAULT_MAX_IDLE_SECONDS)
    with RI._volume_lock():
        root, result = RI._root(), []
        for path in sorted(root.glob("in-*")):
            document = _recognized(root, path)
            if not document or (not administrator and document.get("owner_id") != actor_id):
                continue
            state = document.get("state")
            eligible = state == "expired" or (state == "open" and now - int(document.get("updated_at", 0)) >= maximum)
            result.append({**RI._public(document), "cleanup_eligible": eligible,
                           "reclaimable_bytes": _tree_bytes(path) if eligible else 0})
        return result


def expire(actor_id: str, *, administrator: bool = False, now: int | None = None,
           dry_run: bool = True) -> dict:
    """Find stale open sessions and optionally mark them expired."""
    now = int(time.time()) if now is None else int(now)
    maximum = _seconds("CRYOSTACK_FROZEN_LEGACIES_UPLOAD_MAX_IDLE_SECONDS", DEFAULT_MAX_IDLE_SECONDS)
    summary = {"dry_run": dry_run, "eligible": 0, "marked_expired": 0, "reclaimable_bytes": 0}
    with RI._volume_lock():
        root = RI._root()
        for path in sorted(root.glob("in-*")):
            document = _recognized(root, path)
            if not document or document.get("state") != "open":
                continue
            if not administrator and document.get("owner_id") != actor_id:
                continue
            if now - int(document.get("updated_at", 0)) < maximum:
                continue
            summary["eligible"] += 1
            summary["reclaimable_bytes"] += _tree_bytes(path)
            if not dry_run:
                document["state"], document["expired_at"], document["updated_at"] = "expired", now, now
                atomic_write(path / "session.json", json.dumps(document, sort_keys=True, indent=2).encode())
                summary["marked_expired"] += 1
                _audit(root, {"at": now, "actor_id": actor_id, "action": "expire",
                              "session_id": path.name, "owner_id": document.get("owner_id")})
    return summary


def cleanup(session_id: str, actor_id: str, *, administrator: bool = False,
            now: int | None = None, dry_run: bool = True) -> dict:
    """Remove one expired session after grace; finalized sessions are immutable."""
    now = int(time.time()) if now is None else int(now)
    grace = _seconds("CRYOSTACK_FROZEN_LEGACIES_UPLOAD_RECOVERY_GRACE_SECONDS", DEFAULT_RECOVERY_GRACE_SECONDS)
    with RI._volume_lock():
        root, path = RI._root(), RI._root() / session_id
        document = _recognized(root, path)
        if not document or (not administrator and document.get("owner_id") != actor_id):
            raise StorageError("Upload session not found.")
        if document.get("state") == "finalized":
            raise StorageError("Finalized upload sessions and source data cannot be cleaned.")
        if document.get("state") != "expired":
            raise StorageError("Only an expired upload session can be cleaned.")
        if now - int(document.get("expired_at", now)) < grace:
            raise StorageError("The upload session is still in its recovery grace period.")
        if _contains_symlink(path):
            raise StorageError("The upload session contains an unsafe link and was not cleaned.")
        reclaimed = _tree_bytes(path)
        result = {"session_id": session_id, "dry_run": dry_run,
                  "reclaimed_bytes": reclaimed, "removed": False}
        if not dry_run:
            _audit(root, {"at": now, "actor_id": actor_id, "action": "cleanup",
                          "session_id": session_id, "owner_id": document.get("owner_id"),
                          "reclaimed_bytes": reclaimed})
            shutil.rmtree(path)
            result["removed"] = True
        return result
