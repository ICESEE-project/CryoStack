"""deployment/auth_db_migrate.py: backup, additive migration, verification
and rollback of the auth database, without printing user data."""
from __future__ import annotations

import json
import os
import socket
import sqlite3
import stat
import sys
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from deployment import auth_db_migrate as tool

FIXTURE = _REPO / "control_center" / "tests" / "fixtures" / "baseline_auth_schema.sql"
SECRET_VALUES = ("sess-live-0123456789", "old-user@example.org", "scrypt$secret-hash")


def _baseline_db(path: Path) -> Path:
    now = time.time()
    with sqlite3.connect(path) as c:
        c.executescript(FIXTURE.read_text())
        c.execute("PRAGMA journal_mode = WAL")
        c.execute("INSERT INTO users (id, email, display_name, password_hash, created_at) "
                  "VALUES ('u1', ?, 'Old', ?, 1.0)", (SECRET_VALUES[1], SECRET_VALUES[2]))
        c.execute("INSERT INTO sessions VALUES (?, 'u1', ?, ?, ?)", (SECRET_VALUES[0], now, now, now + 3600))
        c.execute("INSERT INTO sessions VALUES ('sess-expired', 'u1', 1.0, 1.0, 2.0)")
        c.execute("INSERT INTO user_roles VALUES ('r1', 'u1', 'owner', 1.0, NULL)")
    return path


def test_backup_migrate_verify_and_rollback(tmp_path, capsys):
    db = _baseline_db(tmp_path / "auth.db")
    before = tool.describe(db)

    backup = tool.backup(db, tmp_path / "backups")
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "backups").stat().st_mode) == 0o700
    with sqlite3.connect(f"file:{backup}?mode=ro", uri=True) as c:
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete"   # self-contained
    assert tool.describe(backup)["tables"].keys() == before["tables"].keys()

    report = tool.migrate(db, backup)
    assert report["ok"], report["problems"]
    assert report["added_tables"] == sorted(tool.NEW_TABLES)
    assert set(report["triggers_added"]) == {"access_audit_log_no_update", "access_audit_log_no_delete"}
    assert report["active_sessions_checked"] == 1 and report["active_sessions_resolving"] == 1
    assert report["unchanged_tables"]["users"] == 1

    # idempotent, and verify itself does not write
    fingerprint = tool.describe(db)["tables"]["sessions"]["fingerprint"]
    assert tool.migrate(db, backup)["ok"]
    assert tool.verify(backup, db)["ok"]
    assert tool.describe(db)["tables"]["sessions"]["fingerprint"] == fingerprint

    # the old code keeps working: existing tables are untouched
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT role FROM user_roles WHERE user_id = 'u1'").fetchone()[0] == "owner"

    tool.rollback(db, backup)
    restored = tool.describe(db)
    assert set(restored["tables"]) == set(before["tables"])
    for table, info in before["tables"].items():
        assert restored["tables"][table]["fingerprint"] == info["fingerprint"]

    # nothing printed or reported contains user data
    tool._print(tool.describe(db))
    tool._print(report)
    out = capsys.readouterr().out + json.dumps(report)
    assert not any(value in out for value in SECRET_VALUES)


def test_verify_detects_changed_or_missing_data(tmp_path):
    db = _baseline_db(tmp_path / "auth.db")
    backup = tool.backup(db, tmp_path / "backups")
    assert tool.migrate(db, backup)["ok"]
    with sqlite3.connect(db) as c:
        c.execute("UPDATE user_roles SET role = 'admin'")
        c.execute("DELETE FROM sessions WHERE id = ?", (SECRET_VALUES[0],))
    report = tool.verify(backup, db)
    assert not report["ok"]
    assert any("user_roles" in p for p in report["problems"])
    assert any("sessions" in p for p in report["problems"])


def test_migrate_and_rollback_refuse_while_a_gateway_listens(tmp_path, monkeypatch):
    db = _baseline_db(tmp_path / "auth.db")
    backup = tool.backup(db, tmp_path / "backups")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        monkeypatch.setattr(tool, "GATEWAY_PORT", listener.getsockname()[1])
        assert tool.main(["migrate", "--db", str(db), "--backup", str(backup)]) == 2
        assert tool.main(["rollback", "--db", str(db), "--backup", str(backup)]) == 2
    assert "access_events" not in tool.describe(db)["tables"]


def test_migrate_requires_a_backup(tmp_path):
    db = _baseline_db(tmp_path / "auth.db")
    with pytest.raises(tool.MigrationError):
        tool.migrate(db, tmp_path / "missing.db")
