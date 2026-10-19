"""CEDAR preflight is fail-closed and leaves only explicit test evidence."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for item in (str(REPO), str(REPO / "deployment")):
    if item not in sys.path:
        sys.path.insert(0, item)

import cedar_preflight as cedar  # noqa: E402


NFS_OPTIONS = frozenset({
    "rw", "hard", "noatime", "sec=sys", "vers=4.1", "timeo=600",
    "rsize=262144", "wsize=262144",
})


def _mount(source: str, target: Path, fstype: str = "nfs4", options=NFS_OPTIONS):
    return cedar.Mount(source, target, fstype, frozenset(options))


def _statuses(checks: list[dict]) -> dict[str, str]:
    return {item["name"]: item["status"] for item in checks}


def test_mount_and_fstab_parsers_decode_paths(tmp_path):
    proc = tmp_path / "mounts"
    proc.write_text(
        "server:/cedar\\040share /srv/cryostack\\040users nfs4 "
        "rw,hard,noatime,sec=sys,vers=4.1,timeo=600,rsize=262144,wsize=262144 0 0\n")
    found = cedar.read_mounts(proc)
    assert found == [cedar.Mount("server:/cedar share", Path("/srv/cryostack users"),
                                 "nfs4", NFS_OPTIONS)]

    fstab = tmp_path / "fstab"
    fstab.write_text(
        "# storage\nserver:/users /srv/users nfs4 rw,sec=sys,_netdev 0 0\n")
    assert "_netdev" in cedar.read_fstab(fstab)[0].options


def test_mount_check_requires_exact_nfs_source_mode_options_and_boot_order(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = "cedar-cos.nas.gatech.edu:/cedar_cos/cos-lab-nuiaq/cryostack/users"
    mounts = [_mount(source, workspace)]
    fstab = [_mount(source, workspace, options=NFS_OPTIONS | {"_netdev"})]
    checks = cedar.mount_checks(workspace, "workspace", "rw", mounts, fstab, source)
    assert set(_statuses(checks).values()) == {"pass"}

    nested = workspace / "users"
    bad = cedar.mount_checks(nested, "workspace", "rw", mounts, fstab, source)
    assert _statuses(bad)["workspace exact mount"] == "fail"

    weak = [_mount(source, workspace, "ext4", {"rw"})]
    bad = cedar.mount_checks(workspace, "workspace", "rw", weak, [], source)
    statuses = _statuses(bad)
    assert statuses["workspace network filesystem"] == "fail"
    assert "workspace NFS safety options" not in statuses
    assert "workspace SMB safety options" not in statuses
    assert statuses["workspace boot ordering"] == "fail"


def test_mount_check_accepts_cedar_smb31_service_identity_and_reports_soft_timeout(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = "//cos-smb01.cos.gatech.edu/cryostack-users"
    runtime = frozenset({
        "rw", "vers=3.1.1", "sec=none", "cache=strict", "forceuid", "forcegid",
        "uid=978", "gid=977", "soft",
    })
    configured = frozenset({
        "guest", "uid=978", "gid=977", "file_mode=0770", "dir_mode=0770",
        "nofail", "_netdev",
    })
    checks = cedar.mount_checks(
        workspace, "workspace", "rw",
        [_mount(source, workspace, "cifs", runtime)],
        [_mount(source, workspace, "cifs", configured)], source)
    statuses = _statuses(checks)
    assert statuses["workspace network filesystem"] == "pass"
    assert statuses["workspace SMB safety options"] == "pass"
    assert statuses["workspace SMB version"] == "pass"
    assert statuses["workspace SMB service identity"] == "pass"
    assert statuses["workspace SMB timeout behavior"] == "warn"
    assert statuses["workspace boot ordering"] == "pass"


def test_dataset_mode_is_explicit(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    source = "server:/dataset"
    ro_options = (NFS_OPTIONS - {"rw"}) | {"ro"}
    mounts = [_mount(source, dataset, options=ro_options)]
    fstab = [_mount(source, dataset, options=ro_options | {"_netdev"})]
    assert _statuses(cedar.mount_checks(dataset, "dataset", "ro", mounts, fstab))[
        "dataset access mode"] == "pass"
    assert _statuses(cedar.mount_checks(dataset, "dataset", "rw", mounts, fstab))[
        "dataset access mode"] == "fail"


def test_capacity_and_scratch_boundary_checks(tmp_path):
    workspace = tmp_path / "workspace"
    dataset = tmp_path / "dataset"
    scratch = tmp_path / "scratch"
    for path in (workspace, dataset, scratch):
        path.mkdir()
    capacity = cedar.capacity_checks(workspace, "workspace", 0, 0)
    assert _statuses(capacity) == {
        "workspace free-space reserve": "pass", "workspace free-inode reserve": "pass"}

    inode_floor = cedar.capacity_checks(workspace, "workspace", 0, sys.maxsize)
    inode_check = next(item for item in inode_floor
                       if item["name"] == "workspace free-inode reserve")
    assert inode_check["status"] == "fail"
    assert inode_check["reserve_inodes"] == sys.maxsize
    assert inode_check["free_inodes"] < inode_check["reserve_inodes"]

    mounts = [_mount("local", tmp_path, "ext4", {"rw"})]
    checks = cedar.scratch_checks(scratch, [workspace], mounts)
    statuses = _statuses(checks)
    assert statuses["scratch is local/rebuildable"] == "pass"
    assert statuses["scratch separated from workspace"] == "pass"
    assert statuses["scratch device separate from workspace"] == "fail"

    overlap = cedar.scratch_checks(workspace / "cache", [workspace], mounts)
    # A missing scratch directory fails before any overlap can be accepted.
    assert overlap[0]["status"] == "fail"


def test_unreported_smb_inode_counts_are_warning_not_false_exhaustion(tmp_path, monkeypatch):
    class Stats:
        f_bavail = 20
        f_frsize = 1024
        f_blocks = 40
        f_favail = 0
        f_files = 0

    monkeypatch.setattr(cedar.os, "statvfs", lambda _path: Stats())
    checks = cedar.capacity_checks(tmp_path, "workspace", 0, 100_000)
    inode = next(item for item in checks if item["name"] == "workspace free-inode reserve")
    assert inode["status"] == "warn"
    assert inode["reported"] is False

def test_isolated_semantics_probe_checks_locks_rename_fsync_sqlite_and_cleans(tmp_path):
    before = set(tmp_path.iterdir())
    checks = cedar.probe_write_semantics(tmp_path)
    assert _statuses(checks) == {
        "atomic rename and fsync": "pass",
        "POSIX byte-range locks": "pass",
        "SQLite WAL locking and integrity": "pass",
        "probe cleanup": "pass",
    }
    assert set(tmp_path.iterdir()) == before


def test_write_probe_refuses_wrong_identity_without_creating_files(tmp_path, monkeypatch):
    workspace, dataset, scratch = (tmp_path / name for name in ("workspace", "dataset", "scratch"))
    for path in (workspace, dataset, scratch):
        path.mkdir()
    mounts = [
        _mount("server:/users", workspace),
        _mount("server:/dataset", dataset, options=(NFS_OPTIONS - {"rw"}) | {"ro"}),
        _mount("local", scratch, "ext4", {"rw"}),
    ]
    fstab = [
        _mount("server:/users", workspace, options=NFS_OPTIONS | {"_netdev"}),
        _mount("server:/dataset", dataset,
               options=(NFS_OPTIONS - {"rw"}) | {"ro", "_netdev"}),
    ]
    current = cedar.pwd.getpwuid(os.geteuid())
    monkeypatch.setattr(cedar, "backup_checks", lambda *_: [])
    result = cedar.preflight(
        workspace=workspace, dataset=dataset, scratch=scratch, write_probe=True,
        service_user=current.pw_name, uid=os.geteuid() + 1, gid=os.getegid(),
        reserve_bytes=0, mounts=mounts, fstab=fstab)
    probe = next(item for item in result["checks"] if item["name"] == "write semantics probe")
    assert probe["status"] == "fail" and "refused" in probe["detail"]
    assert not list(workspace.iterdir())


def test_default_preflight_is_read_only_and_incomplete_until_evidence_is_supplied(
        tmp_path, monkeypatch):
    workspace, dataset, scratch = (tmp_path / name for name in ("workspace", "dataset", "scratch"))
    for path in (workspace, dataset, scratch):
        path.mkdir()
    mounts = [
        _mount("server:/users", workspace),
        _mount("server:/dataset", dataset, options=(NFS_OPTIONS - {"rw"}) | {"ro"}),
        _mount("local", scratch, "ext4", {"rw"}),
    ]
    fstab = [
        _mount("server:/users", workspace, options=NFS_OPTIONS | {"_netdev"}),
        _mount("server:/dataset", dataset,
               options=(NFS_OPTIONS - {"rw"}) | {"ro", "_netdev"}),
    ]
    account = cedar.pwd.getpwuid(os.geteuid())
    monkeypatch.setattr(cedar, "identity_checks", lambda *_: [
        cedar._check("service identity", "pass", "test identity")])
    result = cedar.preflight(
        workspace=workspace, dataset=dataset, scratch=scratch,
        service_user=account.pw_name, uid=os.geteuid(), gid=os.getegid(),
        reserve_bytes=0, mounts=mounts, fstab=fstab)
    assert result["read_only"] is True
    assert result["ok"] is False  # scratch deliberately shares the test filesystem
    assert result["ready_for_cutover"] is False
    assert result["summary"]["not_run"] == 4  # state, backup, drill, write semantics
    assert not list(workspace.iterdir()) and not list(dataset.iterdir())


def test_cli_rejects_restore_drill_without_backup(capsys):
    with pytest.raises(SystemExit) as error:
        cedar.main(["--workspace", "/w", "--dataset", "/d", "--scratch", "/s",
                    "--drill-scratch", "/drill"])
    assert error.value.code == 2
    assert "requires --backup" in capsys.readouterr().err


def test_cli_rejects_negative_inode_reserve(capsys):
    with pytest.raises(SystemExit) as error:
        cedar.main(["--workspace", "/w", "--dataset", "/d", "--scratch", "/s",
                    "--minimum-free-inodes", "-1"])
    assert error.value.code == 2
    assert "--minimum-free-inodes cannot be negative" in capsys.readouterr().err


def test_report_contains_no_directory_listing_or_file_content(tmp_path, monkeypatch):
    workspace, dataset, scratch = (tmp_path / name for name in ("workspace", "dataset", "scratch"))
    for path in (workspace, dataset, scratch):
        path.mkdir()
    (workspace / "private-user-name.txt").write_text("secret-content")
    mounts = [_mount("server:/users", workspace), _mount("server:/dataset", dataset),
              _mount("local", scratch, "ext4", {"rw"})]
    monkeypatch.setattr(cedar, "identity_checks", lambda *_: [])
    report = cedar.preflight(workspace=workspace, dataset=dataset, scratch=scratch,
                             reserve_bytes=0, mounts=mounts, fstab=[])
    encoded = json.dumps(report)
    assert "private-user-name" not in encoded and "secret-content" not in encoded


def test_unreadable_state_root_is_a_reported_failure_not_a_crash(tmp_path, monkeypatch):
    workspace, dataset, scratch = (tmp_path / name for name in ("workspace", "dataset", "scratch"))
    for path in (workspace, dataset, scratch):
        path.mkdir()
    mounts = [_mount("server:/users", workspace), _mount("server:/dataset", dataset),
              _mount("local", scratch, "ext4", {"rw"})]
    monkeypatch.setattr(cedar, "identity_checks", lambda *_: [])
    from cryostack_src import storage_layout
    monkeypatch.setattr(storage_layout, "location_problems",
                        lambda _path: (_ for _ in ()).throw(PermissionError(13, "denied")))
    result = cedar.preflight(workspace=workspace, dataset=dataset, scratch=scratch,
                             state_root=tmp_path / "unreadable", reserve_bytes=0,
                             mounts=mounts, fstab=[])
    marker = next(item for item in result["checks"] if item["name"] == "state volume marker")
    assert marker["status"] == "fail" and "could not inspect" in marker["detail"]


def test_restore_drill_operational_error_is_reported(monkeypatch, tmp_path):
    import cryostack_backup
    monkeypatch.setattr(cryostack_backup, "verify", lambda _path: {
        "ok": True, "stamp": "test", "files": 1, "problems": []})
    monkeypatch.setattr(cryostack_backup, "drill",
                        lambda *_: (_ for _ in ()).throw(
                            cryostack_backup.BackupError("scratch is not empty")))
    checks = cedar.backup_checks(tmp_path / "backup", tmp_path / "drill")
    assert _statuses(checks) == {"backup verification": "pass", "restore drill": "fail"}
    assert "scratch is not empty" in checks[-1]["detail"]
