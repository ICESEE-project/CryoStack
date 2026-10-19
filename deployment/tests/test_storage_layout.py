"""Persistent state on durable storage: location resolution, durability
checks, the startup gate, durable writes, backup → restore into a data root,
and migration from the historical in-repository layout."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO), str(REPO / "deployment")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cryostack_backup as backup  # noqa: E402
import cryostack_storage as storage  # noqa: E402
from cryostack_src import storage_layout as layout  # noqa: E402

STORE_ENVS = [item.env for item in layout.STORES]


@pytest.fixture
def clean_env(monkeypatch):
    for name in STORE_ENVS + [layout.DATA_ROOT_ENV, layout.REQUIRE_ENV]:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def not_temporary(monkeypatch):
    """pytest's tmp_path is (correctly) a temporary directory; tests of the
    other checks treat it as an ordinary disk."""
    monkeypatch.setattr(layout, "_temporary_roots", lambda: [])


# ── resolution ───────────────────────────────────────────────────────
def test_every_store_resolves_env_then_data_root_then_legacy(clean_env, tmp_path):
    for item in layout.STORES:
        assert layout.resolve(item.name)[1] == "legacy"
    clean_env.setenv(layout.DATA_ROOT_ENV, str(tmp_path / "data"))
    for item in layout.STORES:
        assert layout.resolve(item.name) == (tmp_path / "data" / item.relative, "data-root")
    clean_env.setenv("CRYOSTACK_AUTH_DATABASE", str(tmp_path / "pinned.db"))
    assert layout.resolve("auth") == (tmp_path / "pinned.db", "env")


def test_the_services_use_the_data_root(clean_env, tmp_path):
    from control_center.ops_store import default_ops_database
    from cryostack_src.workspace.roots import resolve_workspace_root
    from icesee_jupyter_book.applications.frozen_legacies.radar import (
        catalog, review, sources, working_cache)
    from icesee_jupyter_book.applications.livist import settings as livist_settings
    from icesee_auth.manager import AuthManager

    data = tmp_path / "data"
    clean_env.setenv(layout.DATA_ROOT_ENV, str(data))
    assert resolve_workspace_root() == (data / "workspace").resolve()
    assert catalog.catalog_path() == data / "db" / "frozen_legacies_catalog.db"
    assert review.review_root(catalog.catalog_path()) == data / "frozen_legacies" / "reviews"
    assert default_ops_database(Path("/elsewhere/auth.db")) == data / "db" / "control_center_ops.db"
    assert livist_settings.database_path() == data / "db" / "livist.db"
    assert working_cache.WorkingCache().directory == data / "cache" / "frozen_legacies"
    assert sources.sources_file() is None                   # no registry yet
    (data / "config").mkdir(parents=True)
    (data / "config" / "radar_sources.yaml").write_text("version: 1\nsources: []\n")
    assert sources.sources_file() == data / "config" / "radar_sources.yaml"
    auth = AuthManager()
    assert Path(auth.storage.database_path).resolve() == (data / "db" / "cryostack_auth.db").resolve()


def test_workspace_manager_uses_the_data_root(clean_env, tmp_path):
    sys.path.insert(0, str(REPO / "cryostack_src" / "workspace" / "tests"))
    from test_multi_user_isolation import make_manager
    from cryostack_src.workspace import WorkspaceUser

    clean_env.setenv(layout.DATA_ROOT_ENV, str(tmp_path / "data"))
    manager = make_manager(WorkspaceUser(user_id="u1", source="cryostack-auth"), None)
    assert manager._workspace_root == (tmp_path / "data" / "workspace").resolve()


def test_export_environment_pins_child_processes(clean_env, tmp_path):
    environ = {}
    assert layout.export_environment(environ) == {}          # no data root: nothing changes
    clean_env.setenv(layout.DATA_ROOT_ENV, str(tmp_path / "d"))
    environ = {"CRYOSTACK_AUTH_DATABASE": "/kept.db"}
    exported = layout.export_environment(environ)
    assert "CRYOSTACK_AUTH_DATABASE" not in exported and environ["CRYOSTACK_AUTH_DATABASE"] == "/kept.db"
    assert environ["CRYOSTACK_WORKSPACE_ROOT"] == str(tmp_path / "d" / "workspace")


def test_every_persistent_path_variable_is_registered():
    """A new persistent store (e.g. a credential or quota store) must be added
    to storage_layout.STORES, or backups and the durability gate miss it."""
    pattern = re.compile(r'"(CRYOSTACK_[A-Z_]*(?:DATABASE|CATALOG|REVIEW_ROOT|RADAR_SOURCES|'
                         r'WORKSPACE_ROOT|_DB|STATE_DIR|DATA_DIR))"')
    found = set()
    for base in ("cryostack_src", "control_center", "icesee_auth", "icesee_jupyter_book/applications",
                 "bin"):
        for path in (REPO / base).rglob("*.py"):
            if "/tests/" in str(path) or "_vendor" in str(path):
                continue
            found |= set(pattern.findall(path.read_text(encoding="utf-8", errors="replace")))
    unregistered = sorted(found - set(STORE_ENVS) - {layout.DATA_ROOT_ENV})
    assert unregistered == []


# ── durability checks ────────────────────────────────────────────────
def _marked(directory: Path) -> Path:
    layout.init_volume(directory, attestation="test volume with snapshots", operator="test")
    return directory


def test_source_tree_temporary_and_unmarked_locations_are_rejected(clean_env, tmp_path):
    assert any("source tree" in p for p in layout.location_problems(REPO / "var" / "x.db"))
    assert any("temporary directory" in p for p in layout.location_problems(tmp_path / "x.db"))
    assert any("relative path" in p for p in layout.location_problems(Path("var/x.db")))
    if Path("/dev/shm").is_dir():
        problems = layout.location_problems(Path("/dev/shm/cryostack/x.db"))
        assert any("tmpfs" in p or "temporary" in p for p in problems)


def test_a_marked_volume_passes_and_its_marker_is_required(clean_env, tmp_path, not_temporary):
    volume = tmp_path / "volume"
    volume.mkdir()
    assert any("not on a volume marked durable" in p
               for p in layout.location_problems(volume / "db" / "auth.db"))
    _marked(volume)
    assert layout.location_problems(volume / "db" / "auth.db") == []
    marker = json.loads((volume / layout.MARKER).read_text())
    assert marker["attestation"] == "test volume with snapshots" and marker["volume_id"]
    with pytest.raises(layout.StorageLayoutError):
        layout.init_volume(volume, attestation="again", operator="test")
    with pytest.raises(layout.StorageLayoutError):
        layout.init_volume(tmp_path / "other", attestation="  ", operator="test")


def test_a_replaced_or_unmounted_volume_is_detected(clean_env, tmp_path, not_temporary):
    volume = _marked(tmp_path / "volume")
    doc = json.loads((volume / layout.MARKER).read_text())
    doc["device"] = doc["device"] + 1          # the marker came from another device
    (volume / layout.MARKER).write_text(json.dumps(doc))
    assert any("not the device it was marked on" in p
               for p in layout.location_problems(volume / "db" / "auth.db"))
    # an empty mount point (volume not mounted) has no marker at all
    assert any("not on a volume marked durable" in p
               for p in layout.location_problems(tmp_path / "mountpoint" / "db" / "auth.db"))


def test_a_copied_volume_marker_is_detected(clean_env, tmp_path, not_temporary):
    volume = _marked(tmp_path / "volume")
    copied = tmp_path / "copied"
    copied.mkdir()
    (copied / layout.MARKER).write_bytes((volume / layout.MARKER).read_bytes())
    problems = layout.location_problems(copied / "db" / "auth.db")
    assert any("marker may have been copied" in problem for problem in problems)


def test_the_gate_refuses_to_start_on_non_durable_storage(clean_env, tmp_path, not_temporary):
    sys.path.insert(0, str(REPO / "bin"))
    import icesee_app

    clean_env.setenv(layout.REQUIRE_ENV, "1")
    with pytest.raises(layout.StorageLayoutError, match="built-in default"):
        icesee_app.check_storage_layout()               # historical in-repository layout
    data = _marked(tmp_path / "data")
    clean_env.setenv(layout.DATA_ROOT_ENV, str(data))
    report = icesee_app.check_storage_layout()
    assert all(not r["problems"] for r in report)
    clean_env.delenv(layout.REQUIRE_ENV)
    clean_env.delenv(layout.DATA_ROOT_ENV)
    for name in STORE_ENVS:
        clean_env.delenv(name, raising=False)
    assert icesee_app.check_storage_layout()             # warns only, starts as before


def test_storage_cli_check_and_show(clean_env, tmp_path, not_temporary, capsys):
    assert storage.main(["check"]) == 1
    data = tmp_path / "data"
    assert storage.main(["init-volume", str(data), "--attest", "snapshots", "--operator", "t"]) == 0
    clean_env.setenv(layout.DATA_ROOT_ENV, str(data))
    capsys.readouterr()
    assert storage.main(["check"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert {s["store"] for s in shown["stores"]} == {i.name for i in layout.STORES}
    assert "secret" not in json.dumps(shown).lower()


# ── durable writes ───────────────────────────────────────────────────
def test_durable_replace_syncs_file_and_directory(tmp_path, monkeypatch):
    synced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(os.readlink(f"/proc/self/fd/{fd}")),
                                                 real(fd)))
    target = tmp_path / "state.json"
    target.write_text("old")
    layout.atomic_write(target, b"new")
    assert target.read_text() == "new"
    assert str(tmp_path) in synced and any(s.startswith(str(tmp_path / ".state.json.")) for s in synced)
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_a_failed_write_keeps_the_old_file(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    target.write_text("old")
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        layout.atomic_write(target, b"new")
    assert target.read_text() == "old" and [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_frozen_legacies_state_writes_are_durable(tmp_path, monkeypatch):
    from icesee_jupyter_book.applications.frozen_legacies.radar import manual

    calls = []
    monkeypatch.setattr(layout, "durable_replace",
                        lambda tmp, path: (calls.append(Path(path).name), os.replace(tmp, path)))
    manual._atomic_write(tmp_path / "session.json", lambda tmp: tmp.write_text("{}"))
    assert calls == ["session.json"]


def test_committed_transactions_are_durable():
    """WAL with synchronous=FULL (SQLite's default): a committed transaction
    survives a crash, not only a clean stop."""
    db = sqlite3.connect(":memory:")
    assert db.execute("PRAGMA synchronous").fetchone()[0] == 2


# ── backup → restore into a data root ────────────────────────────────
def _installation(root: Path) -> Path:
    """A historical in-repository installation with every kind of state."""
    from icesee_auth.storage import AuthStorage
    from control_center.ops_store import OpsStore
    from icesee_jupyter_book.applications.frozen_legacies.radar import catalog as C

    (root / "var").mkdir(parents=True)
    storage_auth = AuthStorage(root / "var" / "cryostack_auth.db")
    user = storage_auth.create_user(email="a@example.org", display_name="A", institution=None,
                                    password_hash="x")
    ops = OpsStore(root / "var" / "control_center_ops.db")
    ops.change_setting(key="frozen_legacies.working_cache_mb", new_value=4096, actor_id=user.id,
                       actor_label="a", reason="test", action="save")
    cat = C.RadarCatalog(root / "var" / "frozen_legacies_catalog.db")
    cat.add_source(source_id="archive", name="Archive", provider="local", dataset_id="test-archive",
                   config={"root": str(root / "archive"), "tiff_prefix": "", "nav_template": ""})
    ws = root / "users" / "user-1" / "frozen_legacies" / "radar" / "a"
    ws.mkdir(parents=True)
    (ws / "source.tiff").write_bytes(b"II*\x00" + b"\x01" * 1000)
    (ws / "asset.json").write_text('{"schema": "x"}')
    app = root / "icesee_jupyter_book" / "applications" / "frozen_legacies"
    app.mkdir(parents=True)
    (root / "radar").mkdir()
    (root / "radar" / "f127.tiff").write_bytes(b"II*\x00")
    (app / "radar_sources.local.yaml").write_text(
        "version: 1\nsources:\n  - key: f127   # comment kept\n"
        "    tiff: ../../../radar/f127.tiff\n    nav: null\n")
    del storage_auth, ops, cat
    import gc
    gc.collect()
    for db in (root / "var").glob("*.db"):           # settle: no open connection, no WAL
        connection = sqlite3.connect(db)
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.close()
    return root


def _env_for(monkeypatch, installation: Path):
    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(installation / "var" / "cryostack_auth.db"))
    monkeypatch.setenv("CRYOSTACK_CONTROL_OPS_DATABASE", str(installation / "var" / "control_center_ops.db"))
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_CATALOG",
                       str(installation / "var" / "frozen_legacies_catalog.db"))
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_RADAR_SOURCES", str(
        installation / "icesee_jupyter_book/applications/frozen_legacies/radar_sources.local.yaml"))


def test_backup_then_restore_into_a_new_data_root(clean_env, tmp_path, not_temporary):
    installation = _installation(tmp_path / "install")
    _env_for(clean_env, installation)
    locations = backup.sources(installation)
    locations["workspaces"] = {"gateway": installation / "users"}
    made, manifest = backup.create(tmp_path / "backups", repo=installation, locations=locations)
    assert manifest["components"]["frozen-legacies-radar-sources"]["config_file"]
    data = tmp_path / "data"
    data.mkdir()
    with pytest.raises(backup.BackupError, match="not a usable marked durable volume"):
        backup.restore(made, data)
    _marked(data)
    result = backup.restore(made, data)
    assert result["ok"], result
    for name in STORE_ENVS:
        clean_env.delenv(name, raising=False)
    clean_env.setenv(layout.DATA_ROOT_ENV, str(data))
    from control_center.ops_store import OpsStore, default_ops_database
    from icesee_jupyter_book.applications.frozen_legacies.radar import catalog as C, sources

    assert OpsStore(default_ops_database()).stored_settings()[
        "frozen_legacies.working_cache_mb"]["value"] == 4096
    assert C.create_catalog().get_source("archive") is not None
    registry = sources.sources_file().read_text()
    assert str((installation / "radar" / "f127.tiff").resolve()) in registry
    assert "# comment kept" in registry
    restored = data / "workspace" / "users" / "user-1" / "frozen_legacies" / "radar" / "a" / "source.tiff"
    assert restored.read_bytes().startswith(b"II*")
    with pytest.raises(backup.BackupError, match="Existing data would be replaced"):
        backup.restore(made, data)

    copied = tmp_path / "copied-data"
    copied.mkdir()
    (copied / layout.MARKER).write_bytes((data / layout.MARKER).read_bytes())
    with pytest.raises(backup.BackupError, match="marker may have been copied"):
        backup.restore(made, copied)


# ── migration from the historical layout ─────────────────────────────
def _digest_tree(root: Path) -> dict:
    """Every file's content; a ``-shm`` (SQLite's shared-memory index, rewritten
    by any reader) only by name."""
    return {str(p.relative_to(root)): (b"" if p.name.endswith("-shm") else p.read_bytes())
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_migrate_copies_everything_and_changes_nothing_at_the_source(clean_env, tmp_path,
                                                                     not_temporary):
    installation = _installation(tmp_path / "install")
    before = _digest_tree(installation)
    data = _marked(tmp_path / "data")
    plan = storage.migrate(installation, data, dry_run=True)
    assert {p["store"] for p in plan["plan"]} == {"auth", "control-center-ops",
                                                  "frozen-legacies-catalog",
                                                  "frozen-legacies-radar-sources", "workspaces"}
    assert not (data / "db").exists()
    result = storage.migrate(installation, data)
    assert result["ok"], result
    assert _digest_tree(installation) == before                 # sources untouched
    assert (data / "MIGRATION.json").is_file()
    assert result["stores"]["auth"]["rows"]["users"] == 1
    clean_env.setenv(layout.DATA_ROOT_ENV, str(data))
    assert all(not r["problems"] for r in layout.check() if r["durable"])
    with pytest.raises(storage.MigrationError, match="already holds data"):
        storage.migrate(installation, data)


def test_migrate_carries_transactions_a_crashed_service_left_in_the_wal(clean_env, tmp_path,
                                                                       not_temporary):
    installation = _installation(tmp_path / "install")
    catalog = installation / "var" / "frozen_legacies_catalog.db"
    writer = subprocess.Popen([sys.executable, "-c",
                               "import sqlite3,sys,time; c=sqlite3.connect(sys.argv[1]);"
                               "c.execute('PRAGMA wal_autocheckpoint=0');"
                               "c.execute('CREATE TABLE crash_probe (x)');"
                               "c.execute('INSERT INTO crash_probe VALUES (1)'); c.commit();"
                               "print('committed', flush=True); time.sleep(60)", str(catalog)],
                              stdout=subprocess.PIPE, text=True)
    assert writer.stdout.readline().strip() == "committed"
    writer.kill()                                   # crash: the commit is only in the WAL
    writer.wait()
    assert Path(f"{catalog}-wal").stat().st_size > 0
    data = _marked(tmp_path / "data")
    result = storage.migrate(installation, data)
    assert result["ok"], result
    assert result["stores"]["frozen-legacies-catalog"]["rows"]["crash_probe"] == 1


def test_migrate_refuses_while_the_services_have_the_databases_open(clean_env, tmp_path,
                                                                    not_temporary):
    installation = _installation(tmp_path / "install")
    data = _marked(tmp_path / "data")
    holder = subprocess.Popen([sys.executable, "-c",
                               "import sqlite3,sys,time; c=sqlite3.connect(sys.argv[1]);"
                               "c.execute('select 1'); print('open', flush=True); time.sleep(60)",
                               str(installation / "var" / "cryostack_auth.db")],
                              stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "open"
        with pytest.raises(storage.MigrationError, match="Stop the services first"):
            storage.migrate(installation, data)
    finally:
        holder.kill()
        holder.wait()
    assert not (data / "db").exists()


def test_migrate_refuses_temporary_or_source_tree_targets(clean_env, tmp_path):
    installation = _installation(tmp_path / "install")
    with pytest.raises(storage.MigrationError, match="temporary directory"):
        storage.migrate(installation, tmp_path / "data", allow_unmarked=True)
    with pytest.raises(storage.MigrationError, match="source tree"):
        storage.migrate(installation, REPO / "var" / "migrated", allow_unmarked=True)
