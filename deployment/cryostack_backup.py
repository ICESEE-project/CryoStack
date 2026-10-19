#!/usr/bin/env python3
"""One-command backup, verification and restore drill of a CryoStack installation.

What is backed up (paths follow the same settings the services use):

=======================  ===========================================  ==========================
Component                Source                                        Method
=======================  ===========================================  ==========================
auth                     ``$CRYOSTACK_AUTH_DATABASE``                  read-only SQLite copy
                         (default ``var/cryostack_auth.db``)
frozen-legacies          catalog + review snapshots                    :mod:`...radar.backup`
                                                                       of a read-only copy
control-center-ops       ``$CRYOSTACK_CONTROL_OPS_DATABASE``           read-only SQLite copy
livist                   ``$CRYOSTACK_LIVIST_DATABASE``                read-only SQLite copy
frozen-legacies-radar-   ``$CRYOSTACK_FROZEN_LEGACIES_RADAR_SOURCES``  file copy (hash-checked)
sources                  (shared radar source registry)
frozen-legacies-intake   ``$CRYOSTACK_FROZEN_LEGACIES_INTAKE_ROOT``    locked file copy of open
                                                                       sessions and releases
workspaces/<label>       ``users/`` (gateway) and                      file copy (links kept as
                         ``icesee_jupyter_notebooks/users/`` (Voila)   links, never followed)
=======================  ===========================================  ==========================

Locations come from :mod:`cryostack_src.storage_layout` (each store's own
variable, then ``$CRYOSTACK_DATA_ROOT``, then the historical default in the
repository), the same resolution the services use. With a data root the one
workspace root ``<data root>/workspace/users`` is backed up as
``workspaces/data``.

Not included (rebuildable or large): the LIVIST input cache, LIVIST job
directories, the Frozen Legacies working cache, radar archives, conda
environments. ``BACKUP.json`` lists them.

Commands (all safe while the services run; nothing in the installation is
written)::

    cryostack_backup.py create --dest /home/<user>/cryostack-backups
    cryostack_backup.py verify <backup directory>
    cryostack_backup.py drill  <backup directory> --scratch <empty directory>
    cryostack_backup.py restore <backup directory> --data-root <empty marked volume dir>

Off-host copies are encrypted to a public key whose private half is kept
off this host::

    cryostack_backup.py export <backup directory> --recipient-key backup-pub.asc --dest <dir>
    cryostack_backup.py unpack <stamp>.tar.gpg --into <empty directory>   # recovery host

``export`` re-verifies the backup, streams ``tar`` straight into ``gpg
--encrypt`` (no plaintext archive is written) with a throw-away keyring that
holds only the recipient's public key, and writes ``<stamp>.tar.gpg`` and
``<stamp>.tar.gpg.sha256`` (0600). ``unpack`` checks the checksum, decrypts
with the recovery host's keyring, refuses unsafe archive members and runs
``verify``; follow it with ``drill``.

``--installation <repository>`` (create, drill) backs up or checks against
another checkout's data, e.g. the running installation from a review copy.

SQLite sources are only ever opened read-only. An idle WAL database (no
``-wal`` file: no open connection) is read as an immutable file and kept
only if its size, mtime and SHA-256 are unchanged afterwards, so no
``-wal``/``-shm`` companions are left beside it; a database in use is
copied with SQLite's online backup.

``create`` writes ``<dest>/<UTC stamp>/`` with ``umask 077`` (directories
0700, files 0600) through a ``.partial`` directory renamed at the end, then
``SHA256SUMS`` (``sha256sum -c`` compatible) and ``BACKUP.json``. The
destination may not be inside the repository or a workspace root: backups
hold password hashes and session ids.

``drill`` restores every component into the scratch directory -- never into
the installation -- and checks that it opens: SQLite ``integrity_check``,
the auth database opened by the current auth code, the Frozen Legacies
restore with its snapshot hashes, and every workspace file against its hash.
It is the evidence that a backup can actually be restored.

Output is limited to counts, sizes and check results: no user names, emails,
password hashes, session ids or file contents are printed.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SCHEMA = "cryostack.backup"
MANIFEST = "BACKUP.json"
SUMS = "SHA256SUMS"
NOT_INCLUDED = [
    "LIVIST input cache and job directories (rebuildable from source.coop / re-run)",
    "Frozen Legacies working cache and radar archives (copies of external data)",
    "conda/LIVIST environments, logs, Voila runtime files",
]


class BackupError(RuntimeError):
    pass


# ── locations ─────────────────────────────────────────────────────────

def _env_path(name: str, default: Path) -> Path:
    value = (os.environ.get(name) or "").strip()
    return Path(value).expanduser() if value else default


def sources(repo: Path = REPO) -> dict:
    """Where this installation keeps each component: the services' own
    resolution (:mod:`cryostack_src.storage_layout`), with the historical
    defaults taken relative to ``repo``."""
    from control_center.ops_store import default_ops_database
    from cryostack_src import storage_layout as layout

    def located(name: str) -> tuple[Path, str]:
        return layout.resolve(name, repo / layout.store(name).legacy)

    auth = located("auth")[0]
    workspace_root, how = layout.resolve("workspaces", repo)
    if how == "legacy":
        roots = {"gateway": repo / "users",
                 "voila": repo / "icesee_jupyter_book" / "icesee_jupyter_notebooks" / "users"}
    else:
        roots = {"data" if how == "data-root" else "configured": workspace_root / "users"}
    intake = (os.environ.get("CRYOSTACK_FROZEN_LEGACIES_INTAKE_ROOT") or "").strip()
    return {
        "auth": auth,
        "frozen_legacies_catalog": located("frozen-legacies-catalog")[0],
        "frozen_legacies_storage": located("frozen-legacies-storage")[0],
        "control_center_ops": default_ops_database(auth),
        "livist": located("livist")[0],
        "frozen_legacies_radar_sources": located("frozen-legacies-radar-sources")[0],
        "frozen_legacies_intake": Path(intake).expanduser() if intake else None,
        "workspaces": roots,
    }


def _inside(path: Path, parent: Path) -> bool:
    path, parent = path.resolve(), parent.resolve()
    return path == parent or parent in path.parents


def _check_destination(dest: Path, repo: Path, protected: list[Path], what: str) -> None:
    for root in [repo, *protected]:
        if _inside(dest, root):
            raise BackupError(f"The {what} may not be inside {root}: backups hold password "
                              f"hashes and session ids.")


# ── helpers ───────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_state(path: Path) -> tuple:
    st = path.stat()
    return st.st_size, st.st_mtime_ns, _sha256(path)


def _sqlite_snapshot(source: Path, target: Path, attempts: int = 5) -> str:
    """Copy a live SQLite file into one self-contained file, read-only.

    An idle WAL database is opened ``immutable`` (a ``mode=ro`` open would
    create ``-wal``/``-shm`` files beside it) and the copy is kept only if the
    file did not change meanwhile; otherwise, or for a database in use, the
    online backup API reads it.  Returns the method used."""
    for attempt in range(attempts):
        idle = not Path(f"{source}-wal").exists()
        before = _file_state(source) if idle else None
        uri = f"file:{source}?mode=ro&immutable=1" if idle else f"file:{source}?mode=ro"
        method = "immutable" if idle else "online"
        if target.exists():
            target.unlink()
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        src = sqlite3.connect(uri, uri=True, timeout=30)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode = DELETE")
        finally:
            dst.close()
            src.close()
        if not idle or _file_state(source) == before:
            return method
        time.sleep(0.2 * (attempt + 1))
    raise BackupError(f"{source.name} kept changing while it was copied; try again.")


def _sqlite_copy(source: Path, target: Path) -> dict:
    """Consistent copy of a live SQLite file, checked."""
    method = _sqlite_snapshot(source, target)
    return dict(_sqlite_check(target), method=method)


def _sqlite_check(path: Path) -> dict:
    """integrity_check and per-table row counts of a copy (opened immutable)."""
    with sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'"
                                           " AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {t: db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    return {"integrity": integrity, "rows": counts}


def _copy_tree(source: Path, target: Path) -> dict:
    """Copy a workspace root; links are copied as links (never followed)."""
    shutil.copytree(source, target, symlinks=True)
    files = links = size = 0
    for path in target.rglob("*"):
        if path.is_symlink():
            links += 1
        elif path.is_file():
            files += 1
            size += path.stat().st_size
    return {"files": files, "links": links, "bytes": size,
            "directories": sum(1 for p in target.iterdir() if p.is_dir() and not p.is_symlink())}


def _copy_intake(source: Path, target: Path) -> dict:
    """Copy all intake state while holding the same lock as its writers."""
    sessions = source / ".upload-sessions"
    if not sessions.is_dir():
        raise BackupError(f"Configured intake root has no session store: {sessions}")
    lock = sessions / ".intake.lock"
    try:
        descriptor = os.open(lock, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise BackupError(f"Configured intake root has no safe writer lock: {lock}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise BackupError(f"Configured intake root has no safe writer lock: {lock}")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        if any(path.is_symlink() for path in source.rglob("*")):
            raise BackupError("Configured intake root contains a symbolic link; refusing backup.")
        result = _copy_tree(source, target)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    result["lock"] = "volume"
    return result


def _revision(repo: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=10, check=True).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _hashed_files(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): _sha256(p) for p in sorted(root.rglob("*"))
            if p.is_file() and not p.is_symlink() and p.name not in (SUMS, MANIFEST)}


def _hashed_links(root: Path) -> dict[str, str]:
    """Digest symlink target text without following the links."""
    return {str(p.relative_to(root)): hashlib.sha256(os.fsencode(os.readlink(p))).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_symlink()}


def _read_sums(backup: Path) -> dict[str, str]:
    sums = {}
    for line in (backup / SUMS).read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        if name:
            sums[name[2:] if name.startswith("./") else name] = digest
    return sums


# ── create ────────────────────────────────────────────────────────────

def create(dest: Path, *, repo: Path = REPO, locations: dict | None = None) -> tuple[Path, dict]:
    """Write a new backup under ``dest``; returns (directory, manifest)."""
    from icesee_jupyter_book.applications.frozen_legacies.radar import backup as fl_backup
    from icesee_jupyter_book.applications.frozen_legacies.radar import review as fl_review

    locations = locations or sources(repo)
    roots = locations["workspaces"]
    dest = Path(dest)
    protected = list(roots.values())
    if locations.get("frozen_legacies_intake"):
        protected.append(Path(locations["frozen_legacies_intake"]))
    _check_destination(dest, repo, protected, "backup destination")
    auth = Path(locations["auth"])
    if not auth.is_file():
        raise BackupError(f"No authentication database at {auth}.")
    previous = os.umask(0o077)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = dest / stamp
    work = dest / f".{stamp}.partial"
    try:
        dest.mkdir(parents=True, exist_ok=True)
        os.chmod(dest, 0o700)
        if target.exists():
            raise BackupError(f"{target} already exists.")
        work.mkdir(mode=0o700)
        components: dict[str, dict] = {}

        (work / "auth").mkdir(mode=0o700)
        copy = work / "auth" / f"{auth.stem}.{stamp}.db"
        components["auth"] = dict(_sqlite_copy(auth, copy), file=str(copy.relative_to(work)))

        catalog = Path(locations["frozen_legacies_catalog"])
        if catalog.is_file():
            # radar.backup copies the catalog with a read-write connection, so it
            # is given a read-only snapshot; the review snapshots stay where the
            # installation keeps them
            snapshot = work / ".frozen-legacies-catalog.db"
            method = _sqlite_snapshot(catalog, snapshot)
            try:
                fl_dir, fl_manifest = fl_backup.create(work / "frozen-legacies", catalog=snapshot,
                                                       reviews=fl_review.review_root(catalog))
            finally:
                snapshot.unlink(missing_ok=True)
            components["frozen-legacies"] = {
                "directory": str(fl_dir.relative_to(work)), "rows": fl_manifest["counts"],
                "submissions": fl_manifest["submissions"], "problems": fl_manifest["problems"],
                "method": method}
        else:
            components["frozen-legacies"] = {"absent": True}

        registry = Path(locations.get("frozen_legacies_radar_sources") or "")
        if registry.name and registry.is_file():
            shutil.copy2(registry, work / "frozen-legacies-radar-sources.yaml")
            components["frozen-legacies-radar-sources"] = {
                "config_file": "frozen-legacies-radar-sources.yaml",
                "sha256": _sha256(work / "frozen-legacies-radar-sources.yaml"),
                "source_directory": str(registry.resolve().parent)}
        else:
            components["frozen-legacies-radar-sources"] = {"absent": True}

        intake = locations.get("frozen_legacies_intake")
        if intake and Path(intake).is_dir():
            components["frozen-legacies-intake"] = _copy_intake(
                Path(intake), work / "frozen-legacies-intake")
        else:
            components["frozen-legacies-intake"] = {"absent": True}

        for name, key in (("control-center-ops", "control_center_ops"),
                          ("livist", "livist"),
                          ("frozen-legacies-storage", "frozen_legacies_storage")):
            configured = locations.get(key)
            # Preserve compatibility with explicit location maps created by
            # older callers; normal discovery always includes every store.
            if configured is None:
                continue
            source = Path(configured)
            if source.is_file():
                components[name] = dict(_sqlite_copy(source, work / f"{name}.db"),
                                        file=f"{name}.db")
            else:
                components[name] = {"absent": True}

        (work / "workspaces").mkdir(mode=0o700)
        for label, root in roots.items():
            if Path(root).is_dir():
                components[f"workspaces/{label}"] = _copy_tree(Path(root),
                                                               work / "workspaces" / label)
            else:
                components[f"workspaces/{label}"] = {"absent": True}

        problems = [f"{name}: integrity_check {c['integrity']}" for name, c in components.items()
                    if c.get("integrity") not in (None, "ok")]
        problems += [f"frozen-legacies: {p}"
                     for p in components["frozen-legacies"].get("problems") or []]
        files = _hashed_files(work)
        (work / SUMS).write_text("".join(f"{d}  ./{n}\n" for n, d in files.items()),
                                 encoding="utf-8")
        manifest = {
            "schema": SCHEMA, "version": 2, "created_at": time.time(), "stamp": stamp,
            "host": socket.gethostname(), "source_revision": _revision(repo),
            "components": components, "files": len(files),
            "symlinks": _hashed_links(work),
            "bytes": sum((work / n).stat().st_size for n in files),
            "problems": problems, "not_included": NOT_INCLUDED,
        }
        (work / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True),
                                     encoding="utf-8")
        for path in [work, *work.rglob("*")]:
            if path.is_symlink():
                continue
            os.chmod(path, 0o700 if path.is_dir() else 0o600)
        os.replace(work, target)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    finally:
        os.umask(previous)
    return target, manifest


# ── verify ────────────────────────────────────────────────────────────

def verify(backup: Path) -> dict:
    """Check a backup against its checksums and itself (read-only)."""
    from icesee_jupyter_book.applications.frozen_legacies.radar import backup as fl_backup

    backup = Path(backup)
    try:
        manifest = json.loads((backup / MANIFEST).read_text(encoding="utf-8"))
        sums = _read_sums(backup)
    except (OSError, ValueError):
        return {"ok": False, "problems": [f"{MANIFEST} or {SUMS} is missing or unreadable"]}
    problems = []
    present = _hashed_files(backup)
    for name, digest in sums.items():
        if name not in present:
            problems.append(f"{name} is missing")
        elif present[name] != digest:
            problems.append(f"{name} does not match {SUMS}")
    problems += [f"{name} is not listed in {SUMS}" for name in sorted(set(present) - set(sums))]
    # Version 1 backups predate authenticated link targets and remain readable.
    # New backups record hashes of os.readlink() text so verification never
    # follows a link outside the backup while still detecting retargeting.
    expected_links = manifest.get("symlinks")
    if expected_links is not None:
        present_links = _hashed_links(backup)
        for name, digest in expected_links.items():
            if name not in present_links:
                problems.append(f"{name} symlink is missing")
            elif present_links[name] != digest:
                problems.append(f"{name} symlink target does not match {MANIFEST}")
        problems += [f"{name} symlink is not listed in {MANIFEST}"
                     for name in sorted(set(present_links) - set(expected_links))]
    components = manifest.get("components", {})
    for name, component in components.items():
        if component.get("file") and (backup / component["file"]).is_file():
            check = _sqlite_check(backup / component["file"])
            if check["integrity"] != "ok":
                problems.append(f"{name}: integrity_check {check['integrity']}")
            if check["rows"] != component.get("rows"):
                problems.append(f"{name}: row counts differ from {MANIFEST}")
        if component.get("directory"):
            result = fl_backup.verify(backup / component["directory"])
            problems += [f"{name}: {p}" for p in result["problems"]]
    if len(sums) != manifest.get("files"):
        problems.append(f"{SUMS} lists {len(sums)} files, {MANIFEST} {manifest.get('files')}")
    return {"ok": not problems, "problems": problems, "stamp": manifest.get("stamp"),
            "files": len(sums), "components": sorted(components)}


# ── drill ─────────────────────────────────────────────────────────────

def drill(backup: Path, scratch: Path, *, repo: Path = REPO, keep: bool = False,
          locations: dict | None = None) -> dict:
    """Restore every component into ``scratch`` (never the installation) and
    check that the restored data opens and matches the backup."""
    from icesee_auth.storage import AuthStorage
    from icesee_jupyter_book.applications.frozen_legacies.radar import backup as fl_backup

    backup, scratch = Path(backup), Path(scratch)
    locations = locations or sources(repo)
    protected = list(locations["workspaces"].values())
    if locations.get("frozen_legacies_intake"):
        protected.append(Path(locations["frozen_legacies_intake"]))
    _check_destination(scratch, repo, protected, "drill directory")
    live = [Path(locations[k]) for k in ("auth", "frozen_legacies_catalog",
                                         "control_center_ops", "livist")]
    if locations.get("frozen_legacies_storage"):
        live.append(Path(locations["frozen_legacies_storage"]))
    if any(_inside(scratch, p.parent) for p in live):
        raise BackupError("The drill directory may not be next to the installation's data.")
    if scratch.exists() and any(scratch.iterdir()):
        raise BackupError(f"{scratch} is not empty.")
    check = verify(backup)
    if not check["ok"]:
        return {"ok": False, "verified": False, "problems": check["problems"]}
    manifest = json.loads((backup / MANIFEST).read_text(encoding="utf-8"))
    previous = os.umask(0o077)
    scratch.mkdir(parents=True, exist_ok=True)
    restored, problems = {}, []
    started = time.time()
    try:
        for name, component in manifest["components"].items():
            if component.get("absent"):
                restored[name] = "absent at backup time"
                continue
            if component.get("file"):
                target = scratch / f"{name}.db"
                shutil.copy2(backup / component["file"], target)
                result = _sqlite_check(target)
                ok = result["integrity"] == "ok" and result["rows"] == component["rows"]
                if name == "auth":
                    # the current auth code opens (and, if needed, migrates) the copy
                    storage = AuthStorage(target)
                    del storage
                    ok = ok and _sqlite_check(target)["integrity"] == "ok"
                restored[name] = "ok" if ok else "failed"
            elif component.get("directory"):
                result = fl_backup.restore(backup / component["directory"],
                                           catalog=scratch / "frozen-legacies" / "catalog.db",
                                           reviews=scratch / "frozen-legacies" / "reviews")
                ok = result["ok"] and result["counts"] == component["rows"]
                restored[name] = "ok" if ok else "failed"
                problems += [f"{name}: {p}" for p in result["problems"]]
            elif component.get("config_file"):
                target = scratch / component["config_file"]
                shutil.copy2(backup / component["config_file"], target)
                restored[name] = "ok" if _sha256(target) == component["sha256"] else "failed"
            elif name.startswith("workspaces/"):
                source = backup / name
                target = scratch / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, target, symlinks=True)
                same = (_hashed_files(source) == _hashed_files(target)
                        and _hashed_links(source) == _hashed_links(target))
                links = sorted(str(p.relative_to(target)) for p in target.rglob("*")
                               if p.is_symlink())
                ok = same and len(links) == component["links"]
                restored[name] = "ok" if ok else "failed"
            elif name == "frozen-legacies-intake":
                source = backup / name
                target = scratch / name
                shutil.copytree(source, target, symlinks=False)
                same = (_hashed_files(source) == _hashed_files(target)
                        and not _hashed_links(source) and not _hashed_links(target))
                restored[name] = "ok" if same else "failed"
            if restored[name] == "failed":
                problems.append(f"{name}: restored copy does not match the backup")
    finally:
        os.umask(previous)
        if not keep:
            shutil.rmtree(scratch, ignore_errors=True)
    return {"ok": not problems, "verified": True, "stamp": manifest.get("stamp"),
            "restored": restored, "problems": problems,
            "seconds": round(time.time() - started, 2), "kept": keep}


# ── restore (into a new data root) ───────────────────────────────────

def absolutize_registry(text: str, base: Path) -> tuple[str, int]:
    """Rewrite relative ``tiff:``/``nav:`` paths of a radar source registry
    against ``base`` (the registry's original directory), keeping comments and
    layout, so the registry means the same after it moves. Returns the new
    text and the number of rewritten paths."""
    import re

    pattern = re.compile(r"^(\s*(?:-\s+)?(?:tiff|nav):\s*)(.+?)\s*$")
    out, changed = [], 0
    for line in text.splitlines(keepends=True):
        match = pattern.match(line.rstrip("\n"))
        if match:
            raw = match.group(2)
            value = raw.split(" #", 1)[0].strip().strip("'\"")
            if value and value.lower() not in ("null", "~") and not value.startswith(("/", "~")):
                line = f"{match.group(1)}{json.dumps(str((Path(base) / value).resolve()))}\n"
                changed += 1
        out.append(line)
    return "".join(out), changed


def restore(backup: Path, data_root: Path, *, allow_unmarked: bool = False) -> dict:
    """Restore a verified backup into a new, empty data root laid out as
    :mod:`cryostack_src.storage_layout` expects (``db/``, ``workspace/users``,
    ...). Nothing that exists is overwritten; the result is checked as in
    ``drill``. Point the services at it with ``CRYOSTACK_DATA_ROOT``."""
    from cryostack_src import storage_layout as layout
    from icesee_auth.storage import AuthStorage
    from icesee_jupyter_book.applications.frozen_legacies.radar import backup as fl_backup

    backup, data_root = Path(backup), Path(data_root).resolve()
    _check_destination(data_root, REPO, [], "data root")
    if not allow_unmarked:
        durability_problems = layout.location_problems(data_root)
        if durability_problems:
            raise BackupError(f"{data_root} is not a usable marked durable volume: "
                              + "; ".join(durability_problems))
    targets = {item.name: data_root / item.relative for item in layout.STORES if item.durable}
    intake_target = data_root / "frozen_legacies" / "intakes"
    occupied = [str(path) for path in targets.values()
                if path.exists() and (path.is_file() or any(path.iterdir()))]
    if intake_target.exists():
        occupied.append(str(intake_target))
    if occupied:
        raise BackupError("Existing data would be replaced: " + ", ".join(occupied))
    check = verify(backup)
    if not check["ok"]:
        return {"ok": False, "verified": False, "problems": check["problems"]}
    manifest = json.loads((backup / MANIFEST).read_text(encoding="utf-8"))
    sqlite_targets = {"auth": targets["auth"], "control-center-ops": targets["control-center-ops"],
                      "livist": targets["livist"],
                      "frozen-legacies-storage": targets["frozen-legacies-storage"]}
    labels = [n for n, c in manifest["components"].items()
              if n.startswith("workspaces/") and not c.get("absent")]
    users = {}
    for label in labels:
        for entry in (backup / label).iterdir():
            users.setdefault(entry.name, []).append(label)
    clashes = sorted(u for u, where in users.items() if len(where) > 1)
    if clashes:
        raise BackupError(f"{len(clashes)} workspace(s) exist in more than one root of the "
                          "backup; merge them by hand before restoring.")
    previous = os.umask(0o077)
    restored, problems = {}, []
    try:
        for name, component in manifest["components"].items():
            if component.get("absent"):
                restored[name] = "absent at backup time"
                continue
            if component.get("file") and name in sqlite_targets:
                target = sqlite_targets[name]
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(f".{target.name}.restore")
                shutil.copy2(backup / component["file"], tmp)
                layout.durable_replace(tmp, target)
                result = _sqlite_check(target)
                ok = result["integrity"] == "ok" and result["rows"] == component["rows"]
                if name == "auth":
                    # the current auth code opens (and, if needed, migrates) it
                    AuthStorage(target)
                    ok = ok and _sqlite_check(target)["integrity"] == "ok"
                restored[name] = "ok" if ok else "failed"
            elif component.get("directory"):
                targets["frozen-legacies-catalog"].parent.mkdir(parents=True, exist_ok=True)
                targets["frozen-legacies-reviews"].parent.mkdir(parents=True, exist_ok=True)
                result = fl_backup.restore(backup / component["directory"],
                                           catalog=targets["frozen-legacies-catalog"],
                                           reviews=targets["frozen-legacies-reviews"])
                ok = result["ok"] and result["counts"] == component["rows"]
                restored[name] = "ok" if ok else "failed"
                problems += [f"{name}: {p}" for p in result["problems"]]
            elif component.get("config_file"):
                target = targets["frozen-legacies-radar-sources"]
                target.parent.mkdir(parents=True, exist_ok=True)
                text = (backup / component["config_file"]).read_text(encoding="utf-8")
                text, changed = absolutize_registry(text, Path(component["source_directory"]))
                layout.atomic_write(target, text.encode("utf-8"))
                restored[name] = f"ok ({changed} relative paths made absolute)"
            elif name == "frozen-legacies-intake":
                intake_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(backup / name, intake_target, symlinks=False)
                same = (_hashed_files(backup / name) == _hashed_files(intake_target)
                        and not _hashed_links(backup / name) and not _hashed_links(intake_target))
                restored[name] = "ok" if same else "failed"
        users_root = targets["workspaces"] / "users"
        users_root.mkdir(parents=True, exist_ok=True)
        for label in labels:
            source = backup / label
            for entry in sorted(source.iterdir()):
                destination = users_root / entry.name
                if entry.is_dir() and not entry.is_symlink():
                    shutil.copytree(entry, destination, symlinks=True)
                else:
                    shutil.copy2(entry, destination, follow_symlinks=False)
            same = all(_hashed_files(source / u) == _hashed_files(users_root / u)
                       for u in (e.name for e in source.iterdir()
                                 if e.is_dir() and not e.is_symlink()))
            restored[label] = "ok" if same else "failed"
        for path in [p for p in users_root.rglob("*") if p.is_dir() and not p.is_symlink()]:
            layout.fsync_directory(path)
        problems += [f"{n}: restored copy does not match the backup"
                     for n, v in restored.items() if v == "failed"]
        layout.atomic_write(data_root / "RESTORE.json", json.dumps({
            "restored_at": time.time(), "backup_stamp": manifest.get("stamp"),
            "source_host": manifest.get("host"), "restored": restored, "problems": problems,
        }, indent=1, sort_keys=True).encode("utf-8"))
    finally:
        os.umask(previous)
    return {"ok": not problems, "verified": True, "stamp": manifest.get("stamp"),
            "data_root": str(data_root), "restored": restored, "problems": problems,
            "environment": {layout.DATA_ROOT_ENV: str(data_root),
                            "CRYOSTACK_FROZEN_LEGACIES_INTAKE_ROOT": str(intake_target)}}


# ── export / unpack (encrypted off-host copy) ─────────────────────────

ARCHIVE_SUFFIX = ".tar.gpg"


def _gpg() -> str:
    gpg = shutil.which("gpg")
    if not gpg:
        raise BackupError("gpg is not installed.")
    return gpg


def export(backup: Path, recipient_key: Path, dest: Path, *, repo: Path = REPO) -> dict:
    """Encrypt a verified backup to one public key; the archive never exists in plaintext."""
    import tempfile

    backup, dest = Path(backup).resolve(), Path(dest)
    check = verify(backup)
    if not check["ok"]:
        return {"ok": False, "verified": False, "problems": check["problems"]}
    _check_destination(dest, repo, [], "export destination")
    previous = os.umask(0o077)
    try:
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / f"{backup.name}{ARCHIVE_SUFFIX}"
        if target.exists():
            raise BackupError(f"{target} already exists.")
        partial = dest / f".{target.name}.partial"
        with tempfile.TemporaryDirectory(prefix="cryostack-export-gpg-") as home:
            env = dict(os.environ, GNUPGHOME=home)
            imported = subprocess.run([_gpg(), "--batch", "--import", str(recipient_key)],
                                      env=env, capture_output=True, text=True)
            keys = subprocess.run([_gpg(), "--batch", "--with-colons", "--list-keys"],
                                  env=env, capture_output=True, text=True).stdout
            secret = subprocess.run([_gpg(), "--batch", "--with-colons", "--list-secret-keys"],
                                    env=env, capture_output=True, text=True).stdout
            if secret.strip():
                if shutil.which("gpgconf"):
                    subprocess.run(["gpgconf", "--kill", "all"], env=env, capture_output=True)
                raise BackupError("The recipient key file holds a private key; export needs the "
                                  "public key only (keep the private key off this host).")
            fingerprints = [line.split(":")[9] for line in keys.splitlines() if line.startswith("fpr:")]
            if imported.returncode != 0 or not fingerprints:
                raise BackupError(f"{recipient_key} is not a usable public key.")
            tar = subprocess.Popen(["tar", "--create", "--sort=name", "--numeric-owner",
                                    "-C", str(backup.parent), backup.name], stdout=subprocess.PIPE)
            gpg = subprocess.run([_gpg(), "--batch", "--yes", "--trust-model", "always",
                                  "--encrypt", "--recipient", fingerprints[0],
                                  "--output", str(partial)], stdin=tar.stdout, env=env,
                                 capture_output=True, text=True)
            tar.stdout.close()
            failed = tar.wait() != 0 or gpg.returncode != 0
            if shutil.which("gpgconf"):
                subprocess.run(["gpgconf", "--kill", "all"], env=env, capture_output=True)
            if failed:
                partial.unlink(missing_ok=True)
                raise BackupError("tar or gpg failed; nothing was exported.")
        os.chmod(partial, 0o600)
        os.replace(partial, target)
        digest = _sha256(target)
        sums = dest / f"{target.name}.sha256"
        sums.write_text(f"{digest}  {target.name}\n", encoding="utf-8")
        os.chmod(sums, 0o600)
    finally:
        os.umask(previous)
    return {"ok": True, "archive": str(target), "sha256": digest, "bytes": target.stat().st_size,
            "recipient": fingerprints[0], "stamp": check["stamp"], "files": check["files"]}


def _safe_members(listing: list[str], top: str) -> list[str]:
    bad = []
    for name in listing:
        parts = Path(name).parts
        if name.startswith("/") or ".." in parts or not parts or parts[0] != top:
            bad.append(name)
    return bad


def unpack(archive: Path, into: Path) -> dict:
    """Recovery host: check, decrypt (its own keyring) and unpack an exported backup."""
    import tempfile

    archive, into = Path(archive), Path(into)
    sums = archive.with_name(archive.name + ".sha256")
    if not sums.is_file() or sums.read_text(encoding="utf-8").split()[0] != _sha256(archive):
        return {"ok": False, "problems": [f"{archive.name} does not match {sums.name}"]}
    if into.exists() and any(into.iterdir()):
        raise BackupError(f"{into} is not empty.")
    top = archive.name[:-len(ARCHIVE_SUFFIX)]
    previous = os.umask(0o077)
    try:
        into.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=into, prefix=".decrypted-", suffix=".tar") as plain:
            gpg = subprocess.run([_gpg(), "--batch", "--yes", "--decrypt", "--output", plain.name,
                                  str(archive)], capture_output=True, text=True)
            if gpg.returncode != 0:
                return {"ok": False, "problems": ["gpg could not decrypt the archive (private key "
                                                  "missing or archive damaged)"]}
            listing = subprocess.run(["tar", "--list", "-f", plain.name], capture_output=True,
                                     text=True, check=True).stdout.splitlines()
            bad = _safe_members(listing, top)
            if bad:
                return {"ok": False, "problems": [f"unsafe archive member {bad[0]!r}"]}
            subprocess.run(["tar", "--extract", "--no-same-owner", "--no-same-permissions",
                            "-f", plain.name, "-C", str(into)], check=True)
    finally:
        os.umask(previous)
    result = verify(into / top)
    return {"ok": result["ok"], "backup": str(into / top), "problems": result["problems"]}


# ── command line ──────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create", help="write a new backup")
    p.add_argument("--dest", type=Path, required=True, help="directory that holds backups")
    p.add_argument("--installation", type=Path, default=REPO,
                   help="repository whose data is backed up (default: this checkout)")
    p = sub.add_parser("verify", help="check a backup")
    p.add_argument("backup", type=Path)
    p = sub.add_parser("drill", help="restore a backup into a scratch directory and check it")
    p.add_argument("backup", type=Path)
    p.add_argument("--scratch", type=Path, required=True)
    p.add_argument("--keep", action="store_true", help="keep the restored scratch copy")
    p.add_argument("--installation", type=Path, default=REPO,
                   help="repository whose data locations the drill must stay away from")
    p = sub.add_parser("restore", help="restore a backup into a new, empty data root")
    p.add_argument("backup", type=Path)
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--allow-unmarked", action="store_true",
                   help="restore into a directory that is not a marked durable volume (tests)")
    p = sub.add_parser("export", help="encrypt a verified backup for an off-host copy")
    p.add_argument("backup", type=Path)
    p.add_argument("--recipient-key", type=Path, required=True, help="ASCII-armoured public key")
    p.add_argument("--dest", type=Path, required=True, help="directory for the encrypted archive")
    p.add_argument("--installation", type=Path, default=REPO)
    p = sub.add_parser("unpack", help="decrypt and unpack an exported backup (recovery host)")
    p.add_argument("archive", type=Path)
    p.add_argument("--into", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            repo = args.installation.resolve()
            target, manifest = create(args.dest, repo=repo, locations=sources(repo))
            result = {"ok": not manifest["problems"], "backup": str(target),
                      "files": manifest["files"], "bytes": manifest["bytes"],
                      "components": {k: ("absent" if v.get("absent") else
                                         v.get("integrity") or v.get("files", "ok"))
                                     for k, v in manifest["components"].items()},
                      "problems": manifest["problems"]}
        elif args.command == "verify":
            result = verify(args.backup)
        elif args.command == "export":
            result = export(args.backup, args.recipient_key, args.dest,
                            repo=args.installation.resolve())
        elif args.command == "restore":
            result = restore(args.backup, args.data_root, allow_unmarked=args.allow_unmarked)
        elif args.command == "unpack":
            result = unpack(args.archive, args.into)
        else:
            repo = args.installation.resolve()
            result = drill(args.backup, args.scratch, repo=repo, keep=args.keep,
                           locations=sources(repo))
    except BackupError as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 2
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
