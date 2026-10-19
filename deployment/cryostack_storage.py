#!/usr/bin/env python3
"""Durable storage for a CryoStack installation: inspect, mark, migrate.

Persistent state (accounts, workspaces and uploads, the radar catalog with
its data sources, review snapshots, Control Center settings including storage
quotas) belongs on a volume that survives redeploys, source updates and
reboots -- not in the repository and not in a temporary directory. See
``cryostack_src/storage_layout.py`` for the locations and the checks.

Commands::

    cryostack_storage.py show                 # where every store is, and why
    cryostack_storage.py check                # exit 1 unless every store is durable
    cryostack_storage.py init-volume DIR --attest "NFS project storage, nightly snapshots" \\
        --operator "<name>"                   # mark a directory as a durable volume
    cryostack_storage.py migrate --installation <repository> --data-root DIR [--dry-run]

``migrate`` copies an installation's state from its historical locations
(``var/``, ``users/``, the radar source registry in the application
directory) into the data root's layout. The services must be stopped (it
refuses while any process has the databases open). Databases are copied with
SQLite's backup API from read-only connections and checked (integrity, row
counts); directories are copied with links kept as links and checked file by
file; relative paths in the radar source registry are made absolute so they
keep pointing at the same files. Nothing at the old locations is changed or
deleted. ``MIGRATION.json`` in the data root records what was copied. Then
set ``CRYOSTACK_DATA_ROOT`` (and ``CRYOSTACK_REQUIRE_DURABLE_STORAGE=1``) for
the services and start them.

For a restore from a backup use ``cryostack_backup.py restore``.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "deployment") not in sys.path:
    sys.path.insert(0, str(REPO / "deployment"))

from cryostack_src import storage_layout as layout  # noqa: E402

#: stores copied by ``migrate`` (caches are rebuilt, never migrated)
MIGRATED = ("auth", "control-center-ops", "livist", "frozen-legacies-catalog",
            "frozen-legacies-storage",
            "frozen-legacies-reviews", "frozen-legacies-radar-sources", "workspaces")


class MigrationError(RuntimeError):
    pass


def open_by_processes(paths: list[Path]) -> list[int]:
    """PIDs (of processes this user can inspect) that have any of ``paths`` open."""
    wanted = {os.path.realpath(p) for p in paths if Path(p).exists()}
    wanted |= {w + suffix for w in list(wanted) for suffix in ("-wal", "-shm")}
    pids = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            for fd in (proc / "fd").iterdir():
                try:
                    if os.readlink(fd) in wanted:
                        pids.append(int(proc.name))
                        break
                except OSError:
                    continue
        except OSError:
            continue
    return sorted(set(pids))


def row_counts(path: Path) -> dict[str, int]:
    """Rows per table through a read-only connection that includes the WAL
    (an immutable read would miss transactions not yet checkpointed, as left
    by a service that stopped uncleanly)."""
    import sqlite3

    import cryostack_backup as backup

    if not Path(f"{path}-wal").exists():
        # idle database: an immutable read leaves no -wal/-shm companions behind
        return backup._sqlite_check(Path(path))["rows"]
    db = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True, timeout=30)
    try:
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        return {t: db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in sorted(tables)}
    finally:
        db.close()


def legacy_locations(installation: Path) -> dict[str, list[Path]]:
    """Historical locations of each migrated store in ``installation``."""
    out = {name: [installation / layout.store(name).legacy] for name in MIGRATED}
    out["workspaces"] = [installation / "users",
                         installation / "icesee_jupyter_book" / "icesee_jupyter_notebooks" / "users"]
    return out


def migrate(installation: Path, data_root: Path, *, dry_run: bool = False,
            allow_unmarked: bool = False) -> dict:
    import cryostack_backup as backup

    installation, data_root = installation.resolve(), Path(data_root).resolve()
    problems = layout.location_problems(data_root, need_marker=not allow_unmarked)
    if problems:
        raise MigrationError(f"{data_root} cannot hold the installation's state: "
                             + "; ".join(problems))
    sources = legacy_locations(installation)
    databases = [p for name in ("auth", "control-center-ops", "livist", "frozen-legacies-catalog",
                                "frozen-legacies-storage")
                 for p in sources[name]]
    busy = open_by_processes(databases)
    if busy:
        raise MigrationError(f"Stop the services first: processes {busy} have the databases open.")
    plan, records = [], {}
    for name in MIGRATED:
        target = data_root / layout.store(name).relative
        present = [p for p in sources[name] if p.exists()]
        if name == "workspaces":
            target = target / "users"
            present = [p for p in present if p.is_dir() and any(p.iterdir())]
        if not present:
            records[name] = {"absent": True}
            continue
        if target.exists() and (target.is_file() or any(target.iterdir())):
            raise MigrationError(f"{target} already holds data; migrate into an empty data root.")
        plan.append((name, present, target))
    if "workspaces" in {n for n, _p, _t in plan}:
        _n, roots, _t = next(item for item in plan if item[0] == "workspaces")
        seen: dict[str, tuple[Path, set[Path]]] = {}
        for root in roots:
            for entry in root.iterdir():
                if entry.name in seen:
                    previous_root, previous_files = seen[entry.name]
                    current_files = {p.relative_to(entry) for p in entry.rglob("*")
                                     if not p.is_dir() or p.is_symlink()}
                    overlap = sorted(str(p) for p in previous_files & current_files)
                    if overlap:
                        raise MigrationError(f"Workspace {entry.name!r} has {len(overlap)} "
                                             f"conflicting path(s) in both {previous_root} and "
                                             f"{root}; merge them by hand first: {overlap[:3]}")
                    seen[entry.name] = (previous_root, previous_files | current_files)
                else:
                    files = {p.relative_to(entry) for p in entry.rglob("*")
                             if not p.is_dir() or p.is_symlink()}
                    seen[entry.name] = (root, files)
    if dry_run:
        return {"ok": True, "dry_run": True, "data_root": str(data_root),
                "plan": [{"store": n, "from": [str(p) for p in s], "to": str(t)}
                         for n, s, t in plan],
                "absent": sorted(n for n, r in records.items() if r.get("absent"))}
    previous = os.umask(0o077)
    try:
        for name, present, target in plan:
            target.parent.mkdir(parents=True, exist_ok=True)
            kind = layout.store(name).kind
            if kind == "sqlite":
                source = present[0]
                tmp = target.with_name(f".{target.name}.migrating")
                method = backup._sqlite_snapshot(source, tmp)
                layout.durable_replace(tmp, target)
                before, after = row_counts(source), row_counts(target)
                ok = backup._sqlite_check(target)["integrity"] == "ok" and before == after
                records[name] = {"from": str(source), "to": str(target), "method": method,
                                 "rows": after, "ok": ok}
            elif kind == "file":
                source = present[0]
                text, changed = backup.absolutize_registry(source.read_text(encoding="utf-8"),
                                                           source.resolve().parent)
                layout.atomic_write(target, text.encode("utf-8"))
                records[name] = {"from": str(source), "to": str(target),
                                 "relative_paths_made_absolute": changed, "ok": True}
            else:
                target.mkdir(parents=True, exist_ok=True)
                files = links = outside = 0
                ok = True
                for root in present:
                    for entry in sorted(root.iterdir()):
                        destination = target / entry.name
                        if entry.is_dir() and not entry.is_symlink():
                            shutil.copytree(entry, destination, symlinks=True, dirs_exist_ok=True)
                            source_hashes = backup._hashed_files(entry)
                            destination_hashes = backup._hashed_files(destination)
                            ok = ok and all(destination_hashes.get(path) == digest
                                            for path, digest in source_hashes.items())
                        else:
                            shutil.copy2(entry, destination, follow_symlinks=False)
                    for path in root.rglob("*"):
                        if path.is_symlink():
                            links += 1
                            if os.path.isabs(os.readlink(path)) and \
                                    layout._inside(Path(os.readlink(path)), installation):
                                outside += 1
                        elif path.is_file():
                            files += 1
                for path in [target, *[p for p in target.rglob("*") if p.is_dir() and not p.is_symlink()]]:
                    layout.fsync_directory(path)
                records[name] = {"from": [str(p) for p in present], "to": str(target),
                                 "files": files, "links": links,
                                 "links_into_installation": outside, "ok": ok}
        problems = [f"{n}: copy does not match its source" for n, r in records.items()
                    if r.get("ok") is False]
        warnings = [f"{n}: {r['links_into_installation']} link(s) point into the installation"
                    for n, r in records.items() if r.get("links_into_installation")]
        result = {"ok": not problems, "migrated_at": time.time(), "installation": str(installation),
                  "data_root": str(data_root), "stores": records, "problems": problems,
                  "warnings": warnings,
                  "environment": {layout.DATA_ROOT_ENV: str(data_root), layout.REQUIRE_ENV: "1"}}
        layout.atomic_write(data_root / "MIGRATION.json",
                            json.dumps(result, indent=1, sort_keys=True).encode("utf-8"))
        return result
    finally:
        os.umask(previous)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show", help="where every persistent store is, and why")
    sub.add_parser("check", help="exit 1 unless every persistent store is durable")
    p = sub.add_parser("init-volume", help="mark a directory as a durable volume")
    p.add_argument("directory", type=Path)
    p.add_argument("--attest", required=True,
                   help="why the volume is durable (snapshots, backups, replication)")
    p.add_argument("--operator", default=getpass.getuser())
    p = sub.add_parser("migrate", help="copy state from the historical locations to a data root")
    p.add_argument("--installation", type=Path, default=REPO)
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-unmarked", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.command in ("show", "check"):
            report = layout.check()
            result = {"ok": not any(r["problems"] for r in report),
                      "data_root": str(layout.data_root() or ""), "required": layout.required(),
                      "stores": report}
            print(json.dumps(result, indent=1))
            return 0 if result["ok"] or args.command == "show" else 1
        if args.command == "init-volume":
            result = {"ok": True, "volume": layout.init_volume(args.directory,
                                                               attestation=args.attest,
                                                               operator=args.operator)}
        else:
            result = migrate(args.installation, args.data_root, dry_run=args.dry_run,
                             allow_unmarked=args.allow_unmarked)
    except (layout.StorageLayoutError, MigrationError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 2
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
