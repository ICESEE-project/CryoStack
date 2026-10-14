#!/usr/bin/env python3
"""Back up, migrate, verify and roll back the CryoStack authentication database.

The access-administration release adds two tables to the auth database
(``access_events`` and the append-only ``access_audit_log`` with its indexes
and triggers). The change is additive: ``CREATE ... IF NOT EXISTS`` only, no
existing table or column is altered, and the previous gateway code ignores the
new tables. The gateway would create them on its next start anyway; this tool
makes the step explicit, verifiable and reversible.

Commands (the gateway must be stopped for ``migrate`` and ``rollback``)::

    auth_db_migrate.py backup   --db var/cryostack_auth.db --out var/backups
    auth_db_migrate.py migrate  --db var/cryostack_auth.db --backup <backup file>
    auth_db_migrate.py verify   --before <backup file> --after var/cryostack_auth.db
    auth_db_migrate.py rollback --db var/cryostack_auth.db --backup <backup file>

Output is limited to table names, row counts, schema and content
fingerprints: no user names, emails, password hashes or session ids are ever
printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: tables this release adds; everything else must be unchanged by `migrate`
NEW_TABLES = ("access_events", "access_audit_log")
GATEWAY_PORT = 8080


class MigrationError(RuntimeError):
    pass


# ── read-only inspection ──────────────────────────────────────────────

def _connect_ro(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise MigrationError(f"No database at {path}.")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _tables(connection: sqlite3.Connection) -> list[str]:
    return [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _fingerprint(connection: sqlite3.Connection, table: str) -> str:
    """SHA-256 over every row in primary-key/rowid order (content-free output)."""
    digest = hashlib.sha256()
    columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
    order = "rowid" if _has_rowid(connection, table) else ", ".join(f'"{c}"' for c in columns)
    for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY {order}'):
        digest.update(json.dumps(row, default=repr).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _has_rowid(connection: sqlite3.Connection, table: str) -> bool:
    sql = connection.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0] or ""
    return "WITHOUT ROWID" not in sql.upper()


def describe(path: Path) -> dict:
    """Counts, schema and fingerprints of every table -- never row contents."""
    with _connect_ro(path) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {}
        for table in _tables(connection):
            tables[table] = {
                "rows": connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
                "schema": connection.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0],
                "fingerprint": _fingerprint(connection, table),
            }
        active = None
        if "sessions" in tables:
            columns = {row[1] for row in connection.execute('PRAGMA table_info("sessions")')}
            if "expires_at" in columns:
                active = connection.execute(
                    "SELECT COUNT(*) FROM sessions WHERE expires_at > ?", (time.time(),)).fetchone()[0]
        triggers = sorted(row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"))
    return {"integrity": integrity, "tables": tables, "active_sessions": active, "triggers": triggers}


def _session_ids(path: Path) -> list[tuple[str, str]]:
    with _connect_ro(path) as connection:
        if "sessions" not in _tables(connection):
            return []
        return [(row[0], row[1]) for row in connection.execute(
            "SELECT id, user_id FROM sessions WHERE user_id IS NOT NULL AND expires_at > ?", (time.time(),))]


# ── commands ──────────────────────────────────────────────────────────

def _gateway_running(port: int = GATEWAY_PORT) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _require_stopped(force: bool) -> None:
    if _gateway_running() and not force:
        raise MigrationError(
            f"Something is listening on 127.0.0.1:{GATEWAY_PORT}; stop the gateway first "
            "(deployment/services.sh stop).")


def backup(db: Path, out_dir: Path) -> Path:
    """Consistent online copy via SQLite's backup API (safe while the gateway runs)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)
    target = out_dir / f"{db.stem}.{time.strftime('%Y%m%dT%H%M%S')}.db"
    if target.exists():
        raise MigrationError(f"{target} already exists.")
    source = _connect_ro(db)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
        # one self-contained file: no -wal/-shm needed to restore it
        destination.execute("PRAGMA journal_mode = DELETE")
    finally:
        destination.close()
        source.close()
    os.chmod(target, 0o600)
    result = describe(target)
    if result["integrity"] != "ok":
        raise MigrationError(f"The backup failed integrity_check: {result['integrity']}")
    return target


def migrate(db: Path, backup_path: Path) -> dict:
    """Apply the additive schema by opening the database with the current code."""
    if not backup_path.is_file():
        raise MigrationError("Take a backup first and pass it with --backup.")
    if describe(backup_path)["integrity"] != "ok":
        raise MigrationError("The backup does not pass integrity_check.")
    from icesee_auth.storage import AuthStorage

    AuthStorage(db)                                   # CREATE ... IF NOT EXISTS only
    return verify(backup_path, db)


def verify(before: Path, after: Path) -> dict:
    """Old tables byte-identical, new tables present, sessions still valid."""
    old, new = describe(before), describe(after)
    problems = []
    if new["integrity"] != "ok":
        problems.append(f"integrity_check: {new['integrity']}")
    for table, info in old["tables"].items():
        now = new["tables"].get(table)
        if now is None:
            problems.append(f"table {table} is missing")
        elif now["schema"] != info["schema"]:
            problems.append(f"table {table} schema changed")
        elif now["fingerprint"] != info["fingerprint"] or now["rows"] != info["rows"]:
            problems.append(f"table {table} content changed")
    for table in NEW_TABLES:
        if table not in new["tables"]:
            problems.append(f"new table {table} was not created")
    added = sorted(set(new["tables"]) - set(old["tables"]))
    unexpected = [t for t in added if t not in NEW_TABLES]
    if unexpected:
        problems.append(f"unexpected new tables: {unexpected}")

    sessions = _session_ids(before)
    surviving = _resolving_sessions(after, sessions)
    if surviving != len(sessions):
        problems.append(f"{len(sessions) - surviving} active sessions no longer resolve")
    return {
        "ok": not problems,
        "problems": problems,
        "integrity": new["integrity"],
        "unchanged_tables": {t: old["tables"][t]["rows"] for t in old["tables"]},
        "added_tables": added,
        "triggers_added": sorted(set(new["triggers"]) - set(old["triggers"])),
        "active_sessions_checked": len(sessions),
        "active_sessions_resolving": surviving,
    }


def _resolving_sessions(db: Path, sessions: list[tuple[str, str]]) -> int:
    """How many sessions the current code still resolves to the same user.

    Checked on a private temporary copy, so verification never writes to the
    database it verifies.
    """
    from icesee_auth.storage import AuthStorage

    with tempfile.TemporaryDirectory(prefix="auth-verify-") as scratch:
        copy = Path(scratch) / "verify.db"
        source = _connect_ro(db)
        target = sqlite3.connect(copy)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        storage = AuthStorage(copy)
        return sum(
            1 for session_id, user_id in sessions
            if (found := storage.get_session(session_id)) is not None and found.user_id == user_id)


def rollback(db: Path, backup_path: Path) -> dict:
    """Replace the database with the backup (anything written since is lost)."""
    if describe(backup_path)["integrity"] != "ok":
        raise MigrationError("The backup does not pass integrity_check; refusing to restore it.")
    staging = db.with_name(db.name + ".restore")
    shutil.copy2(backup_path, staging)
    os.chmod(staging, 0o600)
    with open(staging, "rb") as handle:
        os.fsync(handle.fileno())
    for suffix in ("-wal", "-shm"):
        side = db.with_name(db.name + suffix)
        if side.exists():
            side.unlink()
    os.replace(staging, db)
    return describe(db) | {"restored_from": backup_path.name}


def _print(result) -> None:
    if isinstance(result, dict) and "tables" in result:
        result = {**result, "tables": {t: {"rows": v["rows"]} for t, v in result["tables"].items()}}
    print(json.dumps(result, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("backup"); p.add_argument("--db", type=Path, required=True); p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("migrate"); p.add_argument("--db", type=Path, required=True); p.add_argument("--backup", type=Path, required=True)
    p.add_argument("--force", action="store_true", help="skip the gateway-stopped check (copies only)")
    p = sub.add_parser("verify"); p.add_argument("--before", type=Path, required=True); p.add_argument("--after", type=Path, required=True)
    p = sub.add_parser("rollback"); p.add_argument("--db", type=Path, required=True); p.add_argument("--backup", type=Path, required=True)
    p.add_argument("--force", action="store_true", help="skip the gateway-stopped check (copies only)")
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            path = backup(args.db, args.out)
            _print({"backup": str(path), **describe(path)})
            return 0
        if args.command == "migrate":
            _require_stopped(args.force)
            result = migrate(args.db, args.backup)
        elif args.command == "verify":
            result = verify(args.before, args.after)
        else:
            _require_stopped(args.force)
            result = rollback(args.db, args.backup)
        _print(result)
        return 0 if result.get("ok", True) else 1
    except MigrationError as error:
        print(f"[auth-db] {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
