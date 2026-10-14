"""Backup, verification and restore of Frozen Legacies installation data.

What is authoritative, and where:

=========================  ==============================================  ==============
Data                       Where                                           Rebuildable?
=========================  ==============================================  ==============
Data-source configuration  catalog ``data_sources``                        no (re-enter)
Radar file index           catalog ``radar_assets``, ``index_runs``        yes: re-index
Submissions, decisions     catalog ``submissions``                         **no**
Published observations     catalog ``published_observations``              from snapshots
Review snapshots           ``frozen_legacies_reviews/<id>/`` (files)       **no**
User sessions, picks,      ``users/<id>/frozen_legacies/`` (workspaces)    **no** -- backed
products, georeferencing                                                   up with ``users/``
My picks / progress index  catalog ``user_observations``,                  yes: from the
                           ``user_asset_state``                            workspaces
=========================  ==============================================  ==============

A submission row is meaningless without its snapshot directory and a
snapshot without its row, so neither SQLite nor the snapshot folder alone is
a backup. This module copies both, consistently:

1. the catalog with SQLite's online backup API (a consistent copy while the
   gateway keeps running; no lock-out of readers or writers beyond a moment);
2. every snapshot that copy refers to (snapshots are immutable and written
   before their row is committed, so each referenced snapshot is complete);
3. ``MANIFEST.json`` with hashes, table counts and any problems found.

Usage (as the gateway's service user)::

    python -m icesee_jupyter_book.applications.frozen_legacies.radar.backup create --out /backups/frozen-legacies
    python -m icesee_jupyter_book.applications.frozen_legacies.radar.backup verify /backups/frozen-legacies/<backup>
    python -m icesee_jupyter_book.applications.frozen_legacies.radar.backup restore /backups/frozen-legacies/<backup>

``create`` and ``verify`` exit non-zero when anything is missing or does not
match; ``restore`` refuses to overwrite existing data unless ``--force`` is
given (the existing files are then moved aside, not deleted), and should be
run with the GUI services stopped (``deployment/services.sh stop-gui``).
User workspaces are not part of this backup: back up ``users/`` (the
gateway's workspace root) at the same time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

from .catalog import catalog_path
from .review import SNAPSHOT_MANIFEST, ReviewStore, review_root


SCHEMA = "cryostack.frozen_legacies.backup"
CATALOG_NAME = "frozen_legacies_catalog.db"
REVIEWS_NAME = "frozen_legacies_reviews"
TABLES = ("data_sources", "radar_assets", "index_runs", "submissions",
          "published_observations", "user_observations", "user_asset_state")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _counts(db: sqlite3.Connection) -> dict:
    present = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in TABLES if t in present}


def _submission_ids(db: sqlite3.Connection) -> list[str]:
    present = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "submissions" not in present:
        return []
    return [r[0] for r in db.execute("SELECT submission_id FROM submissions ORDER BY submitted_at")]


def _check_catalog_copy(path: Path, reviews: Path) -> tuple[dict, list[str]]:
    """Integrity of a catalog copy and its snapshots; returns (counts, problems)."""
    problems = []
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = db.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            problems.append(f"catalog integrity check: {result}")
        counts = _counts(db)
        ids = _submission_ids(db)
        orphans = db.execute(
            "SELECT COUNT(*) FROM published_observations p LEFT JOIN submissions s"
            " ON s.submission_id = p.submission_id WHERE s.status IS NOT 'published'"
        ).fetchone()[0] if "published_observations" in counts else 0
        if orphans:
            problems.append(f"{orphans} published observations belong to no published submission")
    finally:
        db.close()
    store = ReviewStore(_ReadOnlyCatalog(path), root=reviews)
    for sid in ids:
        submission = store.get(sid)
        check = store.verify_snapshot(submission)
        if not check["ok"]:
            problems.append(f"snapshot {sid}: " + "; ".join(check["problems"]))
    return counts, problems


class _ReadOnlyCatalog:
    """Just enough of :class:`RadarCatalog` for :class:`ReviewStore` reads,
    without creating or migrating anything."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _connect(self):
        db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        return _Closing(db)


class _Closing:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *exc):
        self.db.close()


def create(out: Path, *, catalog: Path | None = None, reviews: Path | None = None) -> tuple[Path, dict]:
    """Write a new backup directory under ``out``; returns (directory, manifest)."""
    catalog = Path(catalog or catalog_path())
    if not catalog.is_file():
        raise SystemExit(f"No Frozen Legacies catalog at {catalog}; nothing to back up.")
    reviews = Path(reviews or review_root(catalog))
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = Path(out) / f"frozen-legacies-{stamp}"
    work = Path(out) / f".frozen-legacies-{stamp}.partial"
    work.mkdir(parents=True, mode=0o750)
    try:
        # 1. consistent copy of the live database
        source = sqlite3.connect(catalog, timeout=30)
        copy = sqlite3.connect(work / CATALOG_NAME)
        try:
            source.backup(copy)
            # a self-contained file: no -wal/-shm companions in the backup
            copy.execute("PRAGMA journal_mode = DELETE")
        finally:
            copy.close()
            source.close()
        os.chmod(work / CATALOG_NAME, 0o640)
        # 2. the snapshots that copy refers to
        db = sqlite3.connect(work / CATALOG_NAME)
        try:
            ids = _submission_ids(db)
        finally:
            db.close()
        (work / REVIEWS_NAME).mkdir(mode=0o750)
        missing = []
        for sid in ids:
            src = reviews / sid
            if src.is_dir() and not src.is_symlink():
                shutil.copytree(src, work / REVIEWS_NAME / sid, symlinks=False)
            else:
                missing.append(sid)
        # 3. verification of the copy itself, and the manifest
        counts, problems = _check_catalog_copy(work / CATALOG_NAME, work / REVIEWS_NAME)
        problems = [f"snapshot {sid} is missing on the server" for sid in missing] + [
            p for p in problems if not any(p.startswith(f"snapshot {sid}:") for sid in missing)]
        files = {str(p.relative_to(work)): _sha256(p)
                 for p in sorted(work.rglob("*")) if p.is_file()}
        manifest = {"schema": SCHEMA, "version": 1, "created_at": time.time(),
                    "catalog": CATALOG_NAME, "reviews": REVIEWS_NAME, "counts": counts,
                    "submissions": len(ids), "problems": problems, "files": files,
                    "not_included": "user workspaces (users/): back them up with the "
                                    "gateway's workspace root"}
        (work / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, sort_keys=True),
                                            encoding="utf-8")
        os.chmod(work / "MANIFEST.json", 0o640)
        os.replace(work, target)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return target, manifest


def verify(backup: Path) -> dict:
    """Check a backup directory against its manifest and itself."""
    backup = Path(backup)
    problems = []
    try:
        manifest = json.loads((backup / "MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "problems": ["MANIFEST.json is missing or unreadable"]}
    for name, digest in manifest.get("files", {}).items():
        path = backup / name
        if not path.is_file():
            problems.append(f"{name} is missing")
        elif _sha256(path) != digest:
            problems.append(f"{name} does not match the manifest")
    if (backup / CATALOG_NAME).is_file():
        counts, found = _check_catalog_copy(backup / CATALOG_NAME, backup / REVIEWS_NAME)
        problems += found
        if counts != manifest.get("counts"):
            problems.append("table counts differ from the manifest")
    problems += [f"recorded at backup time: {p}" for p in manifest.get("problems", [])]
    return {"ok": not problems, "problems": problems, "counts": manifest.get("counts"),
            "submissions": manifest.get("submissions"), "created_at": manifest.get("created_at")}


def restore(backup: Path, *, catalog: Path | None = None, reviews: Path | None = None,
            force: bool = False) -> dict:
    """Restore a verified backup into the installation's catalog and review store."""
    backup = Path(backup)
    check = verify(backup)
    if not check["ok"]:
        raise SystemExit("The backup does not verify; not restoring:\n  "
                         + "\n  ".join(check["problems"]))
    catalog = Path(catalog or catalog_path())
    reviews = Path(reviews or review_root(catalog))
    existing = [p for p in (catalog, reviews) if p.exists()]
    if existing and not force:
        raise SystemExit("Existing data would be replaced: " + ", ".join(map(str, existing))
                         + ". Stop the GUI services and re-run with --force (the existing "
                           "files are moved aside, not deleted).")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    moved = []
    for path in [catalog, Path(f"{catalog}-wal"), Path(f"{catalog}-shm"), reviews]:
        if path.exists():
            aside = path.with_name(f"{path.name}.pre-restore-{stamp}")
            os.replace(path, aside)
            moved.append(str(aside))
    catalog.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup / CATALOG_NAME, catalog)
    os.chmod(catalog, 0o640)
    shutil.copytree(backup / REVIEWS_NAME, reviews, symlinks=False)
    counts, problems = _check_catalog_copy(catalog, reviews)
    return {"ok": not problems, "problems": problems, "counts": counts, "moved_aside": moved}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up, verify or restore Frozen Legacies "
                                                 "catalog and review data.")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create", help="write a new backup")
    c.add_argument("--out", required=True, type=Path, help="directory that holds backups")
    v = sub.add_parser("verify", help="check a backup")
    v.add_argument("backup", type=Path)
    r = sub.add_parser("restore", help="restore a backup (GUI services stopped)")
    r.add_argument("backup", type=Path)
    r.add_argument("--force", action="store_true",
                   help="replace existing data (moved aside, not deleted)")
    args = parser.parse_args(argv)
    if args.command == "create":
        target, manifest = create(args.out)
        print(f"backup: {target}")
        print(f"tables: {manifest['counts']}")
        for problem in manifest["problems"]:
            print(f"PROBLEM: {problem}", file=sys.stderr)
        return 1 if manifest["problems"] else 0
    if args.command == "verify":
        result = verify(args.backup)
        print("backup verifies" if result["ok"] else "backup does NOT verify")
        for problem in result["problems"]:
            print(f"PROBLEM: {problem}", file=sys.stderr)
        return 0 if result["ok"] else 1
    result = restore(args.backup, force=args.force)
    print(f"restored: {result['counts']}")
    for path in result["moved_aside"]:
        print(f"moved aside: {path}")
    for problem in result["problems"]:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
