"""Where CryoStack keeps persistent state, and whether that place is durable.

Every persistent store is listed in :data:`STORES`. Its location is, in order:

1. its own environment variable (e.g. ``CRYOSTACK_AUTH_DATABASE``);
2. ``$CRYOSTACK_DATA_ROOT/<relative path>`` -- the one setting a deployment
   needs to put all state on a dedicated volume;
3. the historical default inside the repository (``var/``, ``users/``),
   kept so existing installations behave exactly as before.

Surviving a process restart says nothing about durability: a directory in
the repository is lost with a fresh checkout or ``git clean``, a temporary
directory with a reboot, a tmpfs with power, and an empty mount point
silently fills the root disk when the real volume is not mounted. So a
location counts as durable only when the operator has said so explicitly:
``deployment/cryostack_storage.py init-volume`` writes a volume marker
(:data:`MARKER`) recording the volume and the stated basis of its durability
(snapshots, backups, replication). :func:`check` reports, for every store,
whether it is outside the source tree and temporary directories, on a
persistent file system, and on a marked volume that is actually mounted
(same device as the marker). With ``CRYOSTACK_REQUIRE_DURABLE_STORAGE=1`` the
gateway refuses to start until every store passes (:func:`enforce`).

Caches (``durable=False``) may live anywhere outside the source tree; they
are rebuildable and are never backed up.

:func:`durable_replace` / :func:`atomic_write` are the write path for small
state files: write a temporary sibling, ``fsync`` it, ``os.replace`` it into
place and ``fsync`` the directory, so a crash leaves either the old or the new
file -- never an empty one.
"""
from __future__ import annotations

import json
import os
import socket
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA_ROOT_ENV = "CRYOSTACK_DATA_ROOT"
REQUIRE_ENV = "CRYOSTACK_REQUIRE_DURABLE_STORAGE"
MARKER = ".cryostack-volume.json"
MARKER_SCHEMA = "cryostack.storage.volume"
#: file systems whose contents do not survive a reboot or are not storage
VOLATILE_FS = frozenset({"tmpfs", "ramfs", "devtmpfs", "proc", "sysfs", "squashfs", "overlay",
                         "aufs", "zram"})


@dataclass(frozen=True)
class Store:
    name: str
    kind: str                 # "sqlite" | "dir" | "file"
    env: str
    relative: str             # under $CRYOSTACK_DATA_ROOT
    legacy: str               # historical default, relative to the repository
    description: str
    durable: bool = True      # False: rebuildable cache, never backed up


STORES: tuple[Store, ...] = (
    Store("auth", "sqlite", "CRYOSTACK_AUTH_DATABASE", "db/cryostack_auth.db",
          "var/cryostack_auth.db", "accounts, roles, sessions"),
    Store("control-center-ops", "sqlite", "CRYOSTACK_CONTROL_OPS_DATABASE",
          "db/control_center_ops.db", "var/control_center_ops.db",
          "Control Center settings (including storage quotas) and their audit trail"),
    Store("livist", "sqlite", "CRYOSTACK_LIVIST_DATABASE", "db/livist.db", "var/livist.db",
          "LIVIST jobs and publications"),
    Store("frozen-legacies-catalog", "sqlite", "CRYOSTACK_FROZEN_LEGACIES_CATALOG",
          "db/frozen_legacies_catalog.db", "var/frozen_legacies_catalog.db",
          "radar catalog: data sources, indexed files, index runs, review records"),
    Store("frozen-legacies-storage", "sqlite", "CRYOSTACK_FROZEN_LEGACIES_STORAGE_DB",
          "db/frozen_legacies_storage.db", "var/frozen_legacies_storage.db",
          "CryoStack-wide workspace quota settings and per-user overrides"),
    Store("frozen-legacies-reviews", "dir", "CRYOSTACK_FROZEN_LEGACIES_REVIEW_ROOT",
          "frozen_legacies/reviews", "var/frozen_legacies_reviews",
          "immutable snapshots of results submitted for review"),
    Store("frozen-legacies-radar-sources", "file", "CRYOSTACK_FROZEN_LEGACIES_RADAR_SOURCES",
          "config/radar_sources.yaml",
          "icesee_jupyter_book/applications/frozen_legacies/radar_sources.local.yaml",
          "shared radar source registry"),
    Store("workspaces", "dir", "CRYOSTACK_WORKSPACE_ROOT", "workspace", ".",
          "per-user workspaces (<root>/users/<id>): uploads, products, sessions, runs"),
    Store("frozen-legacies-working-cache", "dir", "CRYOSTACK_FROZEN_LEGACIES_WORKING_CACHE",
          "cache/frozen_legacies", "var/frozen_legacies_cache",
          "working copies of external radar (rebuildable)", durable=False),
)
_BY_NAME = {store.name: store for store in STORES}


class StorageLayoutError(RuntimeError):
    """Persistent state is not on durable storage (``CRYOSTACK_REQUIRE_DURABLE_STORAGE``)."""


def store(name: str) -> Store:
    return _BY_NAME[name]


def data_root() -> Path | None:
    value = (os.environ.get(DATA_ROOT_ENV) or "").strip()
    return Path(value).expanduser() if value else None


def resolve(name: str, legacy: Path | None = None) -> tuple[Path, str]:
    """``(path, how)`` of a store; ``how`` is ``"env"``, ``"data-root"`` or
    ``"legacy"``. ``legacy`` overrides the registry's historical default
    (callers that compute it relative to their own module)."""
    item = _BY_NAME[name]
    configured = (os.environ.get(item.env) or "").strip()
    if configured:
        return Path(configured).expanduser(), "env"
    root = data_root()
    if root is not None:
        return root / item.relative, "data-root"
    if item.name == "workspaces" and legacy is None:
        # historical behaviour: the process's working directory
        return Path.cwd(), "legacy"
    return (Path(legacy) if legacy is not None else REPO / item.legacy), "legacy"


def default_path(name: str, legacy: Path) -> Path:
    """The location a module uses when its own variable is unset."""
    return resolve(name, legacy)[0]


def export_environment(environ=os.environ) -> dict[str, str]:
    """With ``$CRYOSTACK_DATA_ROOT`` set, pin every store's own variable to its
    resolved path, so child processes (Voila, kernels, workers) that read only
    the per-store variables use the same locations. Returns what was set."""
    if data_root() is None:
        return {}
    exported = {}
    for item in STORES:
        if not (environ.get(item.env) or "").strip():
            path, _how = resolve(item.name)
            environ[item.env] = str(path)
            exported[item.env] = str(path)
    return exported


# ── durability ───────────────────────────────────────────────────────

def _existing(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def _inside(path: Path, parent: Path) -> bool:
    try:
        path, parent = Path(os.path.realpath(path)), Path(os.path.realpath(parent))
    except OSError:
        return False
    return path == parent or parent in path.parents


def _temporary_roots() -> list[Path]:
    roots = {Path("/tmp"), Path("/var/tmp"), Path("/dev/shm"), Path("/run"),
             Path(tempfile.gettempdir())}
    for name in ("TMPDIR", "TEMP", "TMP"):
        if os.environ.get(name):
            roots.add(Path(os.environ[name]))
    return sorted(roots)


def _mounts() -> list[tuple[Path, str]]:
    """``(mount point, fs type)``, longest first (``/proc/self/mountinfo``)."""
    found = []
    try:
        lines = Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError:
        return []
    for line in lines:
        left, _sep, right = line.partition(" - ")
        fields = left.split()
        if len(fields) < 5 or not right:
            continue
        point = fields[4].replace("\\040", " ")
        found.append((Path(point), right.split()[0]))
    return sorted(found, key=lambda m: len(str(m[0])), reverse=True)


def filesystem_type(path: Path) -> str | None:
    real = Path(os.path.realpath(_existing(path)))
    for point, fstype in _mounts():
        if real == point or point in real.parents:
            return fstype
    return None


def find_marker(path: Path) -> Path | None:
    """The nearest volume marker at or above ``path``."""
    current = Path(os.path.realpath(_existing(path)))
    for candidate in (current, *current.parents):
        marker = candidate / MARKER
        if marker.is_file() and not marker.is_symlink():
            return marker
    return None


def read_marker(marker: Path) -> dict | None:
    try:
        doc = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("schema") == MARKER_SCHEMA else None


def init_volume(directory: Path, *, attestation: str, operator: str) -> dict:
    """Mark ``directory`` as a durable CryoStack volume. ``attestation`` states
    why it is durable (e.g. "NFS project storage, nightly snapshots, 30 days")."""
    directory = Path(directory)
    if not attestation.strip():
        raise StorageLayoutError("State why this volume is durable (--attest).")
    directory.mkdir(parents=True, exist_ok=True)
    problems = location_problems(directory, durable=True, need_marker=False)
    if problems:
        raise StorageLayoutError(f"{directory} cannot hold durable state: " + "; ".join(problems))
    marker = directory / MARKER
    if marker.exists():
        raise StorageLayoutError(f"{marker} already exists (volume {read_marker(marker)}).")
    doc = {"schema": MARKER_SCHEMA, "version": 1, "volume_id": uuid.uuid4().hex,
           "created_at": time.time(), "host": socket.gethostname(),
           "device": os.stat(directory).st_dev, "path": str(Path(os.path.realpath(directory))),
           "filesystem": filesystem_type(directory), "attestation": attestation.strip(),
           "operator": operator.strip()}
    atomic_write(marker, json.dumps(doc, indent=1, sort_keys=True).encode())
    return doc


def location_problems(path: Path, *, durable: bool = True, need_marker: bool = True) -> list[str]:
    """Why ``path`` is not suitable for persistent (or, ``durable=False``,
    cache) state; empty when it is."""
    problems = []
    if not Path(path).is_absolute():
        problems.append("is a relative path (depends on the process's working directory)")
    if _inside(path, REPO):
        problems.append("is inside the application source tree (lost with a fresh "
                        "checkout, git clean or redeploy)")
    if not durable:
        return problems
    for root in _temporary_roots():
        if _inside(path, root):
            problems.append(f"is inside the temporary directory {root}")
            break
    fstype = filesystem_type(path)
    if fstype in VOLATILE_FS:
        problems.append(f"is on a {fstype} file system, which does not keep data")
    if need_marker:
        marker = find_marker(path)
        doc = read_marker(marker) if marker else None
        if doc is None:
            problems.append(f"is not on a volume marked durable ({MARKER}; run "
                            "deployment/cryostack_storage.py init-volume)")
        else:
            device = os.stat(_existing(path)).st_dev
            if device != os.stat(marker.parent).st_dev:
                problems.append(f"is on another device than its volume marker {marker} "
                                "(a volume may not be mounted)")
            elif doc.get("device") != device:
                problems.append(f"the volume at {marker.parent} is not the device it was "
                                "marked on (mounted elsewhere or replaced)")
            marked_path = doc.get("path")
            actual_path = str(Path(os.path.realpath(marker.parent)))
            if not isinstance(marked_path, str) or marked_path != actual_path:
                problems.append(f"the volume marker records {marked_path!r}, not its current "
                                f"location {actual_path} (the marker may have been copied)")
    return problems


def check() -> list[dict]:
    """One report per store: where it is, how that was decided, and problems."""
    report = []
    for item in STORES:
        path, how = resolve(item.name)
        problems = location_problems(path, durable=item.durable, need_marker=item.durable)
        if how == "legacy" and item.durable:
            problems.insert(0, f"uses the built-in default; set {DATA_ROOT_ENV} "
                               f"(or {item.env})")
        marker = find_marker(path) if item.durable else None
        report.append({"store": item.name, "kind": item.kind, "durable": item.durable,
                       "path": str(path), "resolved_by": how,
                       "volume": (read_marker(marker) or {}).get("volume_id") if marker else None,
                       "exists": Path(path).exists(), "problems": problems})
    return report


def required() -> bool:
    return (os.environ.get(REQUIRE_ENV) or "").strip().lower() in ("1", "true", "yes")


def enforce() -> list[dict]:
    """Raise :class:`StorageLayoutError` when durable storage is required and
    any store fails; otherwise return the report (callers log its problems)."""
    report = check()
    failing = [r for r in report if r["problems"]]
    if required() and failing:
        lines = [f"  {r['store']}: {r['path']} -- " + "; ".join(r["problems"]) for r in failing]
        raise StorageLayoutError("Persistent state is not on durable storage "
                                 f"({REQUIRE_ENV}=1):\n" + "\n".join(lines))
    return report


# ── durable writes ───────────────────────────────────────────────────

def fsync_directory(directory: Path) -> None:
    try:
        fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_replace(tmp: Path, target: Path) -> None:
    """``os.replace`` a fully written ``tmp`` onto ``target`` so that after a
    crash either the old or the new content is there, never an empty file."""
    fsync_file(tmp)
    os.replace(tmp, target)
    fsync_directory(Path(target).parent)


def atomic_write(path: Path, data: bytes) -> None:
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
        durable_replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
