"""deployment/cryostack_backup.py: one-command backup of every component,
verification against checksums, and a restore drill into a scratch
directory -- without printing user data or following workspace links."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from deployment import cryostack_backup as tool

EMAIL = "backup-user@example.org"


@pytest.fixture
def install(tmp_path, monkeypatch):
    """A small installation outside the repository: every store populated."""
    from control_center.ops_store import OpsStore
    from icesee_auth.storage import AuthStorage
    from icesee_jupyter_book.applications.frozen_legacies.radar import catalog as fl_catalog
    from icesee_jupyter_book.applications.frozen_legacies.radar import review as fl_review
    from icesee_jupyter_book.applications.livist.store import LivistStore

    var = tmp_path / "install" / "var"
    var.mkdir(parents=True)
    monkeypatch.setenv(fl_catalog.CATALOG_ENV, str(var / "catalog.db"))
    monkeypatch.setenv(fl_review.REVIEW_ROOT_ENV, str(var / "reviews"))
    auth = AuthStorage(var / "auth.db")
    user = auth.create_user(email=EMAIL, display_name="Backup", institution=None,
                            password_hash="scrypt$not-a-real-hash")
    session = auth.create_session(ttl_seconds=600, user_id=user.id)
    OpsStore(var / "ops.db")
    LivistStore(var / "livist.db")
    fl_catalog.create_catalog()
    gateway = tmp_path / "install" / "users"
    (gateway / "u1" / "frozen_legacies").mkdir(parents=True)
    (gateway / "u1" / "frozen_legacies" / "session.json").write_text('{"revision": 3}')
    (gateway / "u1" / "notes.txt").write_text("workspace notes")
    os.symlink("notes.txt", gateway / "u1" / "link-to-notes")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("must-not-be-copied")
    os.symlink(outside, gateway / "u1" / "linked-dir")
    voila = tmp_path / "install" / "voila-users"
    (voila / "u1").mkdir(parents=True)
    (voila / "u1" / "run.yaml").write_text("ensemble: 8\n")
    registry = tmp_path / "install" / "radar_sources.local.yaml"
    registry.write_text("version: 1\nsources:\n  - key: f127\n    tiff: radar/f127.tiff\n")
    intake = tmp_path / "install" / "intakes"
    intake_session = intake / ".upload-sessions" / ("in-" + "a" * 32)
    (intake_session / "chunks" / "0").mkdir(parents=True)
    (intake_session / "session.json").write_text('{"schema":"cryostack.frozen-legacies.resumable-intake","state":"open"}')
    (intake_session / "chunks" / "0" / "0.chunk").write_bytes(b"unfinished upload")
    (intake / ".upload-sessions" / ".intake.lock").touch(mode=0o600)
    (intake / ".upload-sessions" / "janitor-audit.jsonl").write_text('{"action":"dry-run"}\n')
    release = intake / "release-127"
    release.mkdir()
    (release / "receipt.json").write_text('{"state":"finalized"}')
    locations = {"auth": var / "auth.db", "frozen_legacies_catalog": var / "catalog.db",
                 "control_center_ops": var / "ops.db", "livist": var / "livist.db",
                 "frozen_legacies_radar_sources": registry,
                 "frozen_legacies_intake": intake,
                 "workspaces": {"gateway": gateway, "voila": voila}}
    return {"locations": locations, "session": session.id, "tmp": tmp_path}


def _create(install):
    return tool.create(install["tmp"] / "backups", locations=install["locations"])


def test_create_verify_and_drill_every_component(install):
    target, manifest = _create(install)
    assert manifest["problems"] == []
    components = manifest["components"]
    assert components["auth"]["integrity"] == "ok" and components["auth"]["rows"]["users"] == 1
    assert components["frozen-legacies"]["submissions"] == 0
    assert components["control-center-ops"]["integrity"] == "ok"
    assert components["livist"]["integrity"] == "ok"
    assert components["frozen-legacies-intake"]["lock"] == "volume"
    assert components["frozen-legacies-intake"]["files"] == 5
    assert components["workspaces/gateway"] == {"files": 2, "links": 2, "bytes": 30,
                                                 "directories": 1}
    assert components["workspaces/voila"]["files"] == 1
    # owner-only permissions on every entry
    for path in [target, *target.rglob("*")]:
        if path.is_symlink():
            continue
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == (0o700 if path.is_dir() else 0o600), (path, oct(mode))
    assert not list(target.parent.glob(".*.partial"))
    # links are copied as links and never followed out of the workspace
    copied = target / "workspaces" / "gateway" / "u1"
    assert (copied / "linked-dir").is_symlink() and (copied / "link-to-notes").is_symlink()
    assert not any("must-not-be-copied" in p.read_text(errors="ignore")
                   for p in target.rglob("*") if p.is_file() and not p.is_symlink())
    # SHA256SUMS is usable with the standard tool
    if shutil.which("sha256sum"):
        subprocess.run(["sha256sum", "-c", "--quiet", tool.SUMS], cwd=target, check=True)

    assert tool.verify(target)["ok"]
    scratch = install["tmp"] / "drill"
    result = tool.drill(target, scratch, locations=install["locations"])
    assert result["ok"], result
    assert set(result["restored"].values()) == {"ok"}
    assert not scratch.exists()                      # removed unless --keep


def test_intake_backup_refuses_links(install):
    intake = install["locations"]["frozen_legacies_intake"]
    os.symlink(install["tmp"] / "outside", intake / "unsafe")
    with pytest.raises(tool.BackupError, match="symbolic link"):
        _create(install)
    assert not list((install["tmp"] / "backups").glob(".*.partial"))


def test_intake_backup_requires_existing_writer_lock(install):
    intake = install["locations"]["frozen_legacies_intake"]
    (intake / ".upload-sessions" / ".intake.lock").unlink()
    with pytest.raises(tool.BackupError, match="no safe writer lock"):
        _create(install)


def test_intake_backup_does_not_follow_replaced_writer_lock(install):
    intake = install["locations"]["frozen_legacies_intake"]
    lock = intake / ".upload-sessions" / ".intake.lock"
    outside = install["tmp"] / "outside-lock"
    outside.write_text("must not be opened as the intake lock")
    lock.unlink()
    lock.symlink_to(outside)
    with pytest.raises(tool.BackupError, match="no safe writer lock"):
        _create(install)


def test_restore_preserves_resumable_intake_state(install):
    locations = dict(install["locations"])
    locations["workspaces"] = {"gateway": locations["workspaces"]["gateway"]}
    target, _manifest = tool.create(install["tmp"] / "backups", locations=locations)
    data_root = install["tmp"] / "restored-data"
    result = tool.restore(target, data_root, allow_unmarked=True)
    assert result["ok"], result
    intake = Path(result["environment"]["CRYOSTACK_FROZEN_LEGACIES_INTAKE_ROOT"])
    session = intake / ".upload-sessions" / ("in-" + "a" * 32)
    assert json.loads((session / "session.json").read_text())["state"] == "open"
    assert (session / "chunks" / "0" / "0.chunk").read_bytes() == b"unfinished upload"
    assert (intake / ".upload-sessions" / "janitor-audit.jsonl").is_file()
    assert json.loads((intake / "release-127" / "receipt.json").read_text())["state"] == "finalized"


def test_verify_and_drill_reject_a_damaged_backup(install):
    target, _manifest = _create(install)
    damaged = target / "workspaces" / "voila" / "u1" / "run.yaml"
    damaged.write_text("ensemble: 9\n")
    check = tool.verify(target)
    assert not check["ok"] and any("run.yaml" in p for p in check["problems"])
    result = tool.drill(target, install["tmp"] / "drill", locations=install["locations"])
    assert result == {"ok": False, "verified": False, "problems": check["problems"]}
    damaged.write_text("ensemble: 8\n")
    (target / "workspaces" / "voila" / "u1" / "extra.txt").write_text("x")
    assert any("not listed" in p for p in tool.verify(target)["problems"])


def test_verify_and_drill_reject_a_retargeted_workspace_symlink(install):
    target, manifest = _create(install)
    link = target / "workspaces" / "gateway" / "u1" / "link-to-notes"
    recorded = manifest["symlinks"][str(link.relative_to(target))]
    assert recorded == tool._hashed_links(target)[str(link.relative_to(target))]

    link.unlink()
    os.symlink("frozen_legacies/session.json", link)
    check = tool.verify(target)
    assert not check["ok"]
    assert any("symlink target does not match" in problem for problem in check["problems"])
    result = tool.drill(target, install["tmp"] / "drill", locations=install["locations"])
    assert result == {"ok": False, "verified": False, "problems": check["problems"]}


def test_verify_accepts_legacy_manifest_without_symlink_digests(install):
    target, manifest = _create(install)
    manifest["version"] = 1
    manifest.pop("symlinks")
    (target / tool.MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True))
    assert tool.verify(target)["ok"]


def test_destinations_inside_the_installation_are_refused(install, tmp_path):
    locations = install["locations"]
    with pytest.raises(tool.BackupError, match="may not be inside"):
        tool.create(_REPO / "var" / "backups", locations=locations)
    with pytest.raises(tool.BackupError, match="may not be inside"):
        tool.create(locations["workspaces"]["gateway"] / "backups", locations=locations)
    with pytest.raises(tool.BackupError, match="may not be inside"):
        tool.create(locations["frozen_legacies_intake"] / "backups", locations=locations)
    target, _ = _create(install)
    with pytest.raises(tool.BackupError, match="next to the installation"):
        tool.drill(target, locations["auth"].parent / "drill", locations=locations)
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "file").write_text("x")
    with pytest.raises(tool.BackupError, match="not empty"):
        tool.drill(target, busy, locations=locations)
    assert (busy / "file").read_text() == "x"


def test_absent_components_are_recorded_not_invented(install):
    locations = dict(install["locations"])
    locations["livist"] = install["tmp"] / "missing" / "livist.db"
    locations["frozen_legacies_catalog"] = install["tmp"] / "missing" / "catalog.db"
    target, manifest = tool.create(install["tmp"] / "backups", locations=locations)
    assert manifest["components"]["livist"] == {"absent": True}
    assert manifest["components"]["frozen-legacies"] == {"absent": True}
    result = tool.drill(target, install["tmp"] / "drill", locations=locations)
    assert result["ok"] and result["restored"]["livist"] == "absent at backup time"
    locations["auth"] = install["tmp"] / "missing" / "auth.db"
    with pytest.raises(tool.BackupError, match="No authentication database"):
        tool.create(install["tmp"] / "backups2", locations=locations)


def test_command_output_holds_no_user_data(install, monkeypatch, capsys):
    monkeypatch.setattr(tool, "sources", lambda repo=tool.REPO: install["locations"])
    assert tool.main(["create", "--dest", str(install["tmp"] / "backups")]) == 0
    created = json.loads(capsys.readouterr().out)
    backup = created["backup"]
    assert tool.main(["verify", backup]) == 0
    assert tool.main(["drill", backup, "--scratch", str(install["tmp"] / "drill")]) == 0
    output = json.dumps(created) + capsys.readouterr().out
    for secret in (EMAIL, install["session"], "scrypt$not-a-real-hash", "workspace notes"):
        assert secret not in output
    assert tool.main(["create", "--dest", str(_REPO / "var" / "x")]) == 2


def _wal_idle(path):
    import gc
    gc.collect()                       # the fixture's stores close their connections
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode = WAL")
    db.close()
    assert not Path(f"{path}-wal").exists()


def test_idle_wal_databases_get_no_companion_files(install):
    locations = install["locations"]
    var = locations["auth"].parent
    for name in ("auth", "frozen_legacies_catalog", "control_center_ops", "livist"):
        _wal_idle(locations[name])
    before = sorted(p.name for p in var.iterdir())
    target, manifest = _create(install)
    assert manifest["problems"] == []
    assert sorted(p.name for p in var.iterdir()) == before          # no -wal/-shm left behind
    assert {manifest["components"][c]["method"] for c in
            ("auth", "frozen-legacies", "control-center-ops", "livist")} == {"immutable"}
    assert not (target / ".frozen-legacies-catalog.db").exists()
    assert tool.verify(target)["ok"]


def test_database_in_use_is_copied_online(install):
    locations = install["locations"]
    _wal_idle(locations["livist"])
    writer = sqlite3.connect(locations["livist"])
    try:
        writer.execute("CREATE TABLE IF NOT EXISTS in_use (x)")
        writer.execute("INSERT INTO in_use VALUES (1)")
        writer.commit()
        assert Path(f"{locations['livist']}-wal").exists()
        _target, manifest = _create(install)
    finally:
        writer.close()
    livist = manifest["components"]["livist"]
    assert livist["method"] == "online" and livist["integrity"] == "ok"
    assert livist["rows"]["in_use"] == 1


def test_a_database_that_keeps_changing_is_not_kept(install, monkeypatch):
    _wal_idle(install["locations"]["livist"])
    states = iter(range(100))
    monkeypatch.setattr(tool, "_file_state", lambda path: next(states))
    monkeypatch.setattr(tool.time, "sleep", lambda seconds: None)
    with pytest.raises(tool.BackupError, match="kept changing"):
        _create(install)
    assert not list((install["tmp"] / "backups").glob("*Z"))


def test_installation_option_reads_that_checkout(tmp_path, monkeypatch, capsys):
    from icesee_auth.storage import AuthStorage
    from icesee_jupyter_book.applications.frozen_legacies.radar import catalog as fl_catalog

    other = tmp_path / "other-checkout"
    (other / "var").mkdir(parents=True)
    (other / "users" / "u9").mkdir(parents=True)
    (other / "users" / "u9" / "a.txt").write_text("x")
    AuthStorage(other / "var" / "cryostack_auth.db")
    for name in ("CRYOSTACK_DATA_ROOT", "CRYOSTACK_AUTH_DATABASE", "CRYOSTACK_LIVIST_DATABASE",
                 "CRYOSTACK_WORKSPACE_ROOT", "CRYOSTACK_CONTROL_OPS_DATABASE",
                 fl_catalog.CATALOG_ENV):
        monkeypatch.delenv(name, raising=False)
    located = tool.sources(other)
    assert located["auth"] == other / "var" / "cryostack_auth.db"
    assert located["frozen_legacies_catalog"] == other / "var" / "frozen_legacies_catalog.db"
    assert located["control_center_ops"] == other / "var" / "control_center_ops.db"
    assert tool.main(["create", "--dest", str(tmp_path / "b"), "--installation", str(other)]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["components"]["workspaces/gateway"] == 1
    assert created["components"]["frozen-legacies"] == "absent"
    assert tool.main(["create", "--dest", str(other / "var" / "b"), "--installation", str(other)]) == 2
    assert tool.main(["drill", created["backup"], "--scratch", str(other / "var" / "d"),
                      "--installation", str(other)]) == 2
    assert tool.main(["drill", created["backup"], "--scratch", str(tmp_path / "d"),
                      "--installation", str(other)]) == 0


# ── encrypted off-host copy ──────────────────────────────────────────

@pytest.fixture
def keypair(tmp_path):
    """A throw-away recovery key: private half in its own keyring, public half exported."""
    if not shutil.which("gpg"):
        pytest.skip("gpg not installed")
    home = Path(tempfile.mkdtemp(prefix="gpgt-", dir="/tmp"))
    os.chmod(home, 0o700)
    env = dict(os.environ, GNUPGHOME=str(home))
    subprocess.run(["gpg", "--batch", "--passphrase", "", "--pinentry-mode", "loopback",
                    "--quick-generate-key", "CryoStack recovery test <recovery@example.org>",
                    "default", "default", "never"], env=env, check=True, capture_output=True)
    public = tmp_path / "recovery-pub.asc"
    public.write_bytes(subprocess.run(["gpg", "--batch", "--armor", "--export"], env=env,
                                      check=True, capture_output=True).stdout)
    private = tmp_path / "recovery-secret.asc"
    private.write_bytes(subprocess.run(["gpg", "--batch", "--armor", "--pinentry-mode", "loopback",
                                        "--passphrase", "", "--export-secret-keys"], env=env,
                                       check=True, capture_output=True).stdout)
    yield {"home": home, "env": env, "public": public, "private": private}
    subprocess.run(["gpgconf", "--kill", "all"], env=env, capture_output=True)
    shutil.rmtree(home, ignore_errors=True)


def test_export_unpack_and_drill_round_trip(install, keypair, monkeypatch):
    target, _ = _create(install)
    out = install["tmp"] / "offhost"
    result = tool.export(target, keypair["public"], out)
    assert result["ok"], result
    archive = Path(result["archive"])
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert stat.S_IMODE(Path(str(archive) + ".sha256").stat().st_mode) == 0o600
    assert list(out.iterdir()) == sorted(out.iterdir(), key=str) and len(list(out.iterdir())) == 2
    raw = archive.read_bytes()
    for secret in (EMAIL.encode(), b"scrypt$not-a-real-hash", b"workspace notes", b"SQLite format 3"):
        assert secret not in raw                          # encrypted, not just compressed
    # recovery host: its own keyring with the private key
    monkeypatch.setenv("GNUPGHOME", str(keypair["home"]))
    restored = tool.unpack(archive, install["tmp"] / "recovered")
    assert restored["ok"], restored
    drill = tool.drill(Path(restored["backup"]), install["tmp"] / "drill",
                       locations=install["locations"])
    assert drill["ok"] and set(drill["restored"].values()) == {"ok"}


def test_unpack_refuses_a_damaged_archive_or_a_missing_key(install, keypair, monkeypatch, tmp_path):
    target, _ = _create(install)
    archive = Path(tool.export(target, keypair["public"], install["tmp"] / "offhost")["archive"])
    other = Path(tempfile.mkdtemp(prefix="gpgo-", dir="/tmp"))
    os.chmod(other, 0o700)
    try:
        monkeypatch.setenv("GNUPGHOME", str(other))        # no private key here
        result = tool.unpack(archive, tmp_path / "a")
        assert not result["ok"] and "decrypt" in result["problems"][0]
    finally:
        subprocess.run(["gpgconf", "--kill", "all"], env=dict(os.environ, GNUPGHOME=str(other)),
                       capture_output=True)
        shutil.rmtree(other, ignore_errors=True)
    data = bytearray(archive.read_bytes())
    data[len(data) // 2] ^= 0xFF
    archive.write_bytes(bytes(data))
    monkeypatch.setenv("GNUPGHOME", str(keypair["home"]))
    result = tool.unpack(archive, tmp_path / "b")
    assert not result["ok"] and "does not match" in result["problems"][0]


def test_export_refuses_private_keys_unverified_backups_and_repo_destinations(install, keypair):
    target, _ = _create(install)
    with pytest.raises(tool.BackupError, match="private key"):
        tool.export(target, keypair["private"], install["tmp"] / "x")
    with pytest.raises(tool.BackupError, match="may not be inside"):
        tool.export(target, keypair["public"], _REPO / "var" / "offhost")
    (target / "workspaces" / "voila" / "u1" / "run.yaml").write_text("tampered")
    result = tool.export(target, keypair["public"], install["tmp"] / "y")
    assert result["ok"] is False and not (install["tmp"] / "y").exists()


def test_unsafe_archive_members_are_refused():
    assert tool._safe_members(["20261011T000000Z/a", "20261011T000000Z/b/c"], "20261011T000000Z") == []
    assert tool._safe_members(["/etc/passwd"], "x") == ["/etc/passwd"]
    assert tool._safe_members(["x/../../etc"], "x") == ["x/../../etc"]
    assert tool._safe_members(["other/file"], "x") == ["other/file"]


def test_export_and_unpack_commands(install, keypair, monkeypatch, capsys):
    target, _ = _create(install)
    out = install["tmp"] / "cli-offhost"
    assert tool.main(["export", str(target), "--recipient-key", str(keypair["public"]),
                      "--dest", str(out)]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["ok"] and exported["files"] == tool.verify(target)["files"]
    monkeypatch.setenv("GNUPGHOME", str(keypair["home"]))
    assert tool.main(["unpack", exported["archive"], "--into", str(install["tmp"] / "cli-rec")]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
