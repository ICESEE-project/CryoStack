"""Read-only per-user workspace status for the Control Center.

Reports metadata only: whether a user's ``<workspace-root>/users/<safe-id>``
directory exists, an approximate bounded size, the newest modification time
seen, and which known application areas are present. File names, file
contents and paths below the owner root are never returned. Symlinks are
never followed.
"""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

from cryostack_src.workspace.identity import WorkspaceUser
from cryostack_src.workspace.roots import resolve_workspace_root

#: ``app[...]`` override of the workspace root (tests, deployments)
WORKSPACE_ROOT_KEY = "control_workspace_root"
_FROZEN_LEGACIES_ROOT_KEY = "frozen_legacies_workspace_root"

#: known application areas inside an owner root (label -> relative path)
APP_AREAS = {
    "Examples": "examples",
    "Datasets": "datasets",
    "Frozen Legacies": "frozen_legacies",
    "Run history": ".cryostack/runs",
    "Working copies": ".cryostack/working",
    "ICESEE runs": ".cryostack/icesee_runs",
    "Agents": ".cryostack/agents",
    "Cloud connection": ".cryostack/cloud",
}

DETAIL_ENTRY_LIMIT = 20_000
LIST_ENTRY_LIMIT = 2_000
DIRECTORY_SCAN_LIMIT = 5_000
_CACHE_SECONDS = 120


def safe_id_for(user_id: str) -> str:
    """The owner-root directory name the applications use for an account."""
    return WorkspaceUser(user_id=user_id, source="cryostack-auth").safe_id


_ANONYMOUS_SAFE_ID = WorkspaceUser(user_id="anonymous").safe_id


def _scan(root: Path, *, entry_limit: int, time_budget: float) -> dict:
    """Bounded, symlink-free walk returning totals only."""
    size = 0
    files = 0
    dirs = 0
    newest = 0.0
    truncated = False
    deadline = time.monotonic() + time_budget
    stack = [root]
    seen = 0

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    seen += 1
                    if seen > entry_limit or time.monotonic() > deadline:
                        truncated = True
                        break
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    newest = max(newest, info.st_mtime)
                    if stat.S_ISDIR(info.st_mode):
                        dirs += 1
                        stack.append(Path(entry.path))
                    elif stat.S_ISREG(info.st_mode):
                        files += 1
                        size += info.st_size
        except OSError:
            continue
        if truncated:
            break

    return {
        "size_bytes": size,
        "files": files,
        "directories": dirs,
        "newest_mtime": newest or None,
        "approximate": truncated,
    }


class WorkspaceInspector:
    """Workspace metadata for accounts; never exposes file names or data."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.workspace_root = resolve_workspace_root(workspace_root)
        self.users_root = self.workspace_root / "users"
        self._cache: dict[tuple[str, int], tuple[float, dict]] = {}

    @classmethod
    def for_app(cls, app) -> "WorkspaceInspector":
        inspector = app.get("control_workspace_inspector")
        if inspector is None:
            inspector = cls(
                app.get(WORKSPACE_ROOT_KEY)
                or app.get(_FROZEN_LEGACIES_ROOT_KEY)
            )
        return inspector

    def owner_root(self, user_id: str) -> Path:
        return self.users_root / safe_id_for(user_id)

    def status(
        self,
        user_id: str,
        *,
        entry_limit: int = DETAIL_ENTRY_LIMIT,
        time_budget: float = 1.5,
    ) -> dict:
        key = (user_id, entry_limit)
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < _CACHE_SECONDS:
            return cached[1]

        root = self.owner_root(user_id)
        result = {
            "safe_id": root.name,
            "exists": False,
            "symlink": False,
            "areas": [],
            "other_entries": 0,
            "size_bytes": 0,
            "files": 0,
            "directories": 0,
            "last_activity": None,
            "approximate": False,
        }

        try:
            info = os.lstat(root)
        except OSError:
            self._cache[key] = (now, result)
            return result

        if stat.S_ISLNK(info.st_mode):
            # A symlinked owner root is never followed or measured.
            result["symlink"] = True
            self._cache[key] = (now, result)
            return result

        if not stat.S_ISDIR(info.st_mode):
            self._cache[key] = (now, result)
            return result

        result["exists"] = True
        newest = info.st_mtime

        known_top = {path.split("/", 1)[0] for path in APP_AREAS.values()}
        for label, relative in APP_AREAS.items():
            try:
                area = os.lstat(root / relative)
            except OSError:
                continue
            if stat.S_ISDIR(area.st_mode):
                result["areas"].append(label)
                newest = max(newest, area.st_mtime)

        try:
            with os.scandir(root) as entries:
                result["other_entries"] = sum(
                    1 for entry in entries if entry.name not in known_top
                )
        except OSError:
            pass

        totals = _scan(root, entry_limit=entry_limit, time_budget=time_budget)
        result.update(
            size_bytes=totals["size_bytes"],
            files=totals["files"],
            directories=totals["directories"],
            approximate=totals["approximate"],
        )
        result["last_activity"] = max(newest, totals["newest_mtime"] or 0) or None

        self._cache[key] = (now, result)
        return result

    def ownership(self, accounts: list[dict]) -> dict:
        """Map owner-root directories to accounts (read-only).

        Returns accounts with/without a workspace, and directory names under
        ``users/`` that match no account (orphaned), the unauthenticated
        development namespace, or are not plain directories.
        """
        by_safe_id = {safe_id_for(a["id"]): a for a in accounts}
        present: dict[str, str] = {}
        truncated = False

        try:
            with os.scandir(self.users_root) as entries:
                for count, entry in enumerate(entries):
                    if count >= DIRECTORY_SCAN_LIMIT:
                        truncated = True
                        break
                    try:
                        mode = entry.stat(follow_symlinks=False).st_mode
                    except OSError:
                        continue
                    if stat.S_ISLNK(mode):
                        present[entry.name] = "symlink"
                    elif stat.S_ISDIR(mode):
                        present[entry.name] = "directory"
                    else:
                        present[entry.name] = "file"
        except OSError:
            pass

        mapped = []
        without = []
        for safe_id, account in by_safe_id.items():
            kind = present.get(safe_id)
            row = {
                "user_id": account["id"],
                "email": account["email"],
                "display_name": account["display_name"],
                "safe_id": safe_id,
            }
            if kind == "directory":
                mapped.append(row)
            elif kind is None:
                without.append(row)
            else:
                mapped.append({**row, "unexpected": kind})

        orphaned = []
        for name, kind in sorted(present.items()):
            if name in by_safe_id:
                continue
            if name == _ANONYMOUS_SAFE_ID:
                category = "unauthenticated namespace"
            elif kind != "directory":
                category = f"unexpected {kind}"
            else:
                category = "no matching account"
            orphaned.append({"name": name, "kind": kind, "category": category})

        return {
            "users_root_exists": self.users_root.is_dir(),
            "mapped": mapped,
            "without_workspace": without,
            "orphaned": orphaned,
            "truncated": truncated,
        }
