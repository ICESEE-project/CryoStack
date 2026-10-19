"""CryoStack-wide workspace storage quotas.

Every user has one storage allowance for the persistent files of their
workspace (``<workspace-root>/users/<safe-id>``): uploaded raw radar and
processed products, LIVIST jobs, CryoLauncher/ICESEE runs and datasets, and
anything else chargeable that lives there. The default is 2 GiB; administrators can change
the default and set per-user overrides.

**What counts.** Regular files under the user's owner root, each physical
file once (``(st_dev, st_ino)``, so hard links are not double-counted), at
their apparent size. Not counted: symbolic links (shared radar is referenced,
never copied), files outside the owner root, partial uploads still in
progress (``*.part``, reserved instead -- see below), transient work areas
(``.automatic-work``) and caches (``.cache``, ``__pycache__``). External
catalog radar and the shared working cache live outside user workspaces and
never count.

**Enforcement** is server-side (:class:`QuotaGuard`, installed as an aiohttp
middleware in front of the chargeable Frozen Legacies requests):

* an upload is refused before its body is read when its declared size does
  not fit in the remaining allowance;
* other chargeable writes (saving picks, starting automatic picking) are
  refused while the user is at or above the quota;
* concurrent requests reserve their declared size for as long as they run,
  so two parallel uploads cannot together overshoot the allowance.

Users above their quota -- for example after the quota was lowered -- keep
reading, downloading and deleting their files; nothing is ever deleted to
enforce a quota. They cannot add chargeable data until their usage falls
below the limit or an administrator raises it.

Settings and overrides are authoritative configuration, so they are stored in
their own SQLite database (``$CRYOSTACK_FROZEN_LEGACIES_STORAGE_DB``, default
``var/frozen_legacies_storage.db``) rather than in the rebuildable radar
catalog. Changes are recorded in the Control Center audit log by the routes.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


GIB = 1024 ** 3
MIB = 1024 ** 2
DEFAULT_QUOTA_BYTES = 2 * GIB                    # 2,147,483,648
#: the per-file ceiling of the upload handlers; the setting can lower it only
HARD_MAX_UPLOAD_BYTES = 200 * MIB
DEFAULT_WARN_PERCENT = 80
DEFAULT_DISK_WARN_PERCENT = 90
DEFAULT_DISK_RESERVE_BYTES = 5 * GIB
MAX_QUOTA_BYTES = 10 * 1024 * GIB                # 10 TiB: a sanity bound for input
STORAGE_DB_ENV = "CRYOSTACK_FROZEN_LEGACIES_STORAGE_DB"
DEFAULT_STORAGE_DB = Path(__file__).resolve().parents[4] / "var" / "frozen_legacies_storage.db"
#: seconds a measured usage is reused before the workspace is walked again
USAGE_TTL_S = 30.0

#: directory names never charged (transient work areas and caches)
EXCLUDED_DIRS = frozenset({".automatic-work", ".cache", "__pycache__"})
PARTIAL_SUFFIX = ".part"

SETTINGS = {
    # name: (default, minimum, maximum)
    "default_quota_bytes": (DEFAULT_QUOTA_BYTES, 0, MAX_QUOTA_BYTES),
    "max_upload_bytes": (HARD_MAX_UPLOAD_BYTES, MIB, HARD_MAX_UPLOAD_BYTES),
    "warn_percent": (DEFAULT_WARN_PERCENT, 1, 100),
    "disk_warn_percent": (DEFAULT_DISK_WARN_PERCENT, 1, 100),
    "disk_reserve_bytes": (DEFAULT_DISK_RESERVE_BYTES, GIB, 1024 * GIB),
}


class QuotaError(ValueError):
    """A quota setting or override is invalid."""


class QuotaExceeded(Exception):
    """A chargeable write does not fit in the user's remaining allowance."""

    def __init__(self, message: str, usage: "Usage"):
        super().__init__(message)
        self.usage = usage


def format_bytes(value: int | float | None) -> str:
    """``1.2 GiB``-style sizes for messages (binary units)."""
    if value is None:
        return "?"
    value = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


# ── measuring ────────────────────────────────────────────────────────
def measure(root: Path) -> dict:
    """Chargeable bytes under ``root`` (see the module docstring)."""
    seen: set[tuple[int, int]] = set()
    total = files = 0
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        return {"bytes": 0, "files": 0}
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in EXCLUDED_DIRS:
                        stack.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False) or entry.name.endswith(PARTIAL_SUFFIX):
                    continue
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            key = (info.st_dev, info.st_ino)
            if key in seen:
                continue
            seen.add(key)
            total += info.st_size
            files += 1
    return {"bytes": total, "files": files}


def directory_bytes(path: Path) -> int:
    """Apparent size of everything under ``path`` (caches; no exclusions)."""
    total, seen = 0, set()
    path = Path(path)
    if not path.is_dir():
        return 0
    for base, _dirs, names in os.walk(path):
        for name in names:
            try:
                info = os.lstat(os.path.join(base, name))
            except OSError:
                continue
            if (info.st_dev, info.st_ino) not in seen:
                seen.add((info.st_dev, info.st_ino))
                total += info.st_size
    return total


@dataclass(frozen=True)
class Usage:
    used_bytes: int
    reserved_bytes: int
    quota_bytes: int
    override: bool
    warn_percent: int

    @property
    def available_bytes(self) -> int:
        return max(0, self.quota_bytes - self.used_bytes - self.reserved_bytes)

    @property
    def percent(self) -> float:
        if self.quota_bytes <= 0:
            return 100.0 if self.used_bytes else 0.0
        return round(100.0 * self.used_bytes / self.quota_bytes, 1)

    @property
    def status(self) -> str:
        """``ok`` | ``warning`` (at or above the warning threshold) | ``over``."""
        if self.used_bytes >= self.quota_bytes:
            return "over"
        if self.percent >= self.warn_percent:
            return "warning"
        return "ok"

    def public(self) -> dict:
        return {"used_bytes": self.used_bytes, "reserved_bytes": self.reserved_bytes,
                "quota_bytes": self.quota_bytes, "available_bytes": self.available_bytes,
                "percent": self.percent, "status": self.status, "override": self.override,
                "used": format_bytes(self.used_bytes), "quota": format_bytes(self.quota_bytes)}


# ── settings and overrides ───────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS storage_settings (
    name        TEXT PRIMARY KEY,
    value       INTEGER NOT NULL,
    updated_at  REAL NOT NULL,
    updated_by  TEXT
);
CREATE TABLE IF NOT EXISTS user_quotas (
    user_id     TEXT PRIMARY KEY,
    quota_bytes INTEGER NOT NULL,
    updated_at  REAL NOT NULL,
    updated_by  TEXT
);
"""


def storage_db_path() -> Path:
    configured = (os.environ.get(STORAGE_DB_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser()
    # The durable-storage layer is optional in older deployments.  When it is
    # installed, resolve this store through the shared data-root policy just
    # like the catalog; otherwise preserve the historical in-repository path.
    try:
        from cryostack_src.storage_layout import default_path
    except ImportError:
        return DEFAULT_STORAGE_DB
    return default_path("frozen-legacies-storage", DEFAULT_STORAGE_DB)


class QuotaStore:
    """Quota settings and per-user overrides (SQLite, WAL, one transaction
    per call -- the conventions of the auth database and radar catalog)."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else storage_db_path()
        self._lock = threading.Lock()
        self._ready = False

    @contextmanager
    def _connect(self):
        if not self._ready:
            with self._lock:
                if not self._ready:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    db = sqlite3.connect(self.path, timeout=30)
                    try:
                        db.execute("PRAGMA journal_mode=WAL")
                        db.executescript(_SCHEMA)
                        db.commit()
                    finally:
                        db.close()
                    self._ready = True
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def settings(self) -> dict:
        values = {name: spec[0] for name, spec in SETTINGS.items()}
        with self._connect() as db:
            for row in db.execute("SELECT name, value FROM storage_settings"):
                if row["name"] in SETTINGS:
                    values[row["name"]] = int(row["value"])
        return values

    def set_setting(self, name: str, value, *, actor: str | None = None) -> tuple[int, int]:
        """Validate and store one setting; returns ``(previous, new)``."""
        if name not in SETTINGS:
            raise QuotaError(f"Unknown storage setting {name!r}.")
        _default, low, high = SETTINGS[name]
        number = _integer(value, name)
        if not low <= number <= high:
            raise QuotaError(f"{name} must be between {low} and {high}.")
        previous = self.settings()[name]
        with self._connect() as db:
            db.execute("INSERT INTO storage_settings (name, value, updated_at, updated_by)"
                       " VALUES (?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET"
                       " value = excluded.value, updated_at = excluded.updated_at,"
                       " updated_by = excluded.updated_by",
                       (name, number, time.time(), actor))
        return previous, number

    def overrides(self) -> dict[str, int]:
        with self._connect() as db:
            return {r["user_id"]: int(r["quota_bytes"])
                    for r in db.execute("SELECT user_id, quota_bytes FROM user_quotas")}

    def override(self, user_id: str) -> int | None:
        with self._connect() as db:
            row = db.execute("SELECT quota_bytes FROM user_quotas WHERE user_id = ?",
                             (user_id,)).fetchone()
        return None if row is None else int(row["quota_bytes"])

    def set_override(self, user_id: str, quota_bytes, *, actor: str | None = None
                     ) -> tuple[int | None, int | None]:
        """Set (or, with ``None``, clear) a user's quota; ``(previous, new)``."""
        if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 200:
            raise QuotaError("A user ID is required.")
        previous = self.override(user_id)
        with self._connect() as db:
            if quota_bytes is None:
                db.execute("DELETE FROM user_quotas WHERE user_id = ?", (user_id,))
                return previous, None
            number = _integer(quota_bytes, "quota_bytes")
            if not 0 <= number <= MAX_QUOTA_BYTES:
                raise QuotaError(f"quota_bytes must be between 0 and {MAX_QUOTA_BYTES}.")
            db.execute("INSERT INTO user_quotas (user_id, quota_bytes, updated_at, updated_by)"
                       " VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET"
                       " quota_bytes = excluded.quota_bytes, updated_at = excluded.updated_at,"
                       " updated_by = excluded.updated_by",
                       (user_id, number, time.time(), actor))
        return previous, number

    def quota_for(self, user_id: str) -> tuple[int, bool]:
        """``(quota bytes, is an override)`` for one user."""
        override = self.override(user_id)
        if override is not None:
            return override, True
        return self.settings()["default_quota_bytes"], False


def _integer(value, name: str) -> int:
    if isinstance(value, bool):
        raise QuotaError(f"{name} must be a whole number of bytes.")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, int):
        raise QuotaError(f"{name} must be a whole number of bytes.")
    return value


# ── accounting ───────────────────────────────────────────────────────
class QuotaAccounts:
    """Measured usage per owner root (cached briefly) plus the bytes
    reserved by requests in flight. All bookkeeping happens on the event
    loop thread between awaits, so check-and-reserve is atomic there; the
    filesystem walk runs in a worker thread."""

    def __init__(self, store: QuotaStore):
        self.store = store
        self._usage: dict[str, tuple[float, int]] = {}
        self._reserved: dict[str, int] = {}
        self._lock = threading.Lock()

    def measured(self, root: Path, *, refresh: bool = False) -> int:
        key = str(root)
        cached = self._usage.get(key)
        if cached and not refresh and time.monotonic() - cached[0] < USAGE_TTL_S:
            return cached[1]
        used = measure(root)["bytes"]
        with self._lock:
            self._usage[key] = (time.monotonic(), used)
        return used

    def invalidate(self, root: Path) -> None:
        with self._lock:
            self._usage.pop(str(root), None)

    def reserved(self, root: Path) -> int:
        return self._reserved.get(str(root), 0)

    def usage(self, root: Path, user_id: str, *, refresh: bool = False) -> Usage:
        quota, override = self.store.quota_for(user_id)
        return Usage(self.measured(root, refresh=refresh), self.reserved(root), quota,
                     override, self.store.settings()["warn_percent"])

    def reserve(self, usage: Usage, root: Path, nbytes: int, *, what: str) -> int:
        """Reserve ``nbytes`` for a write or raise :class:`QuotaExceeded`.

        A write is accepted only while the user is below the quota and the
        reservation fits in what remains (``nbytes`` 0 still needs the user
        to be below the quota)."""
        key = str(root)
        with self._lock:
            reserved = self._reserved.get(key, 0)
            current = Usage(usage.used_bytes, reserved, usage.quota_bytes, usage.override,
                            usage.warn_percent)
            if current.used_bytes >= current.quota_bytes:
                raise QuotaExceeded(
                    f"Your workspace uses {format_bytes(current.used_bytes)} of its "
                    f"{format_bytes(current.quota_bytes)} storage quota, so {what} is not "
                    "possible. Your existing files remain available; remove files you no "
                    "longer need, or ask an administrator for more storage.", current)
            if nbytes > current.available_bytes:
                raise QuotaExceeded(
                    f"{what[:1].upper() + what[1:]} needs up to {format_bytes(nbytes)}, but "
                    f"only {format_bytes(current.available_bytes)} of your "
                    f"{format_bytes(current.quota_bytes)} storage quota is available.", current)
            disk = disk_status(root)
            reserve = self.store.settings()["disk_reserve_bytes"]
            if disk is None or disk["free_bytes"] - nbytes < reserve:
                free = None if disk is None else disk["free_bytes"]
                detail = "could not be verified" if free is None else (
                    f"is {format_bytes(free)}; CryoStack must keep "
                    f"{format_bytes(reserve)} free")
                raise QuotaExceeded(
                    f"The server's safe free-space reserve {detail}, so {what} is "
                    "temporarily unavailable. Remove files or contact an administrator.",
                    current)
            self._reserved[key] = reserved + nbytes
        return nbytes

    def release(self, root: Path, nbytes: int) -> None:
        key = str(root)
        with self._lock:
            left = self._reserved.get(key, 0) - nbytes
            if left > 0:
                self._reserved[key] = left
            else:
                self._reserved.pop(key, None)
            self._usage.pop(key, None)          # the write changed the usage


def disk_status(path: Path) -> dict | None:
    """Capacity of the filesystem holding ``path`` (no path in the result)."""
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        stats = os.statvfs(path)
    except OSError:
        return None
    total = stats.f_blocks * stats.f_frsize
    free = stats.f_bavail * stats.f_frsize
    used = total - stats.f_bfree * stats.f_frsize
    return {"total_bytes": total, "free_bytes": free, "used_bytes": used,
            "percent": round(100.0 * used / total, 1) if total else None}
