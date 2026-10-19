#!/usr/bin/env python3
"""Non-destructive CEDAR readiness inspection and isolated semantics probe.

The default command only reads account, mount, capacity, marker and backup
metadata.  ``--write-probe`` is deliberately stricter: it runs only when the
caller *is* the configured service identity and the workspace path is an exact
approved network mount (NFS or SMB/CIFS). It creates one private, randomly named directory, checks cross-
process byte-range locking, atomic rename, file/directory fsync and SQLite WAL,
then removes the directory.  It never examines application or user files.

This tool does not mount storage, edit ``fstab``, create ACLs, migrate state,
restart services or change production configuration.
"""
from __future__ import annotations

import argparse
import fcntl
import grp
import json
import os
import pwd
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "deployment") not in sys.path:
    sys.path.insert(0, str(REPO / "deployment"))

NFS_FS = frozenset({"nfs", "nfs4"})
SMB_FS = frozenset({"cifs", "smb3"})
NETWORK_FS = NFS_FS | SMB_FS
DEFAULT_SERVICE_USER = "cryostack-app"
DEFAULT_UID = 978
DEFAULT_GID = 977
DEFAULT_RESERVE_BYTES = 5 * 1024 ** 3
DEFAULT_RESERVE_INODES = 100_000
REQUIRED_NFS_OPTIONS = frozenset({"hard", "noatime", "sec=sys"})
REQUIRED_SMB_OPTIONS = frozenset({"sec=none", "cache=strict", "forceuid", "forcegid"})


@dataclass(frozen=True)
class Mount:
    source: str
    target: Path
    fstype: str
    options: frozenset[str]


def _unescape_mount(value: str) -> str:
    """Decode the octal escapes used by ``/proc/*/mounts`` and fstab."""
    for encoded, plain in (("\\040", " "), ("\\011", "\t"),
                           ("\\012", "\n"), ("\\134", "\\")):
        value = value.replace(encoded, plain)
    return value


def read_mounts(path: Path = Path("/proc/self/mounts")) -> list[Mount]:
    mounts: list[Mount] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return mounts
    for line in lines:
        fields = line.split()
        if len(fields) < 4:
            continue
        mounts.append(Mount(_unescape_mount(fields[0]),
                            Path(_unescape_mount(fields[1])), fields[2],
                            frozenset(_unescape_mount(fields[3]).split(","))))
    return sorted(mounts, key=lambda item: len(str(item.target)), reverse=True)


def mount_for(path: Path, mounts: list[Mount]) -> Mount | None:
    """Return the most-specific mount containing ``path`` without requiring it
    to exist.  Symlinks in an existing path are resolved."""
    candidate = Path(os.path.realpath(path))
    for mount in mounts:
        target = Path(os.path.realpath(mount.target))
        if candidate == target or target in candidate.parents:
            return mount
    return None


def read_fstab(path: Path = Path("/etc/fstab")) -> list[Mount]:
    mounts: list[Mount] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return mounts
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 4:
            continue
        mounts.append(Mount(_unescape_mount(fields[0]),
                            Path(_unescape_mount(fields[1])), fields[2],
                            frozenset(_unescape_mount(fields[3]).split(","))))
    return mounts


def _check(name: str, status: str, detail: str, **evidence) -> dict:
    return {"name": name, "status": status, "detail": detail, **evidence}


def identity_checks(user: str, uid: int, gid: int) -> list[dict]:
    checks = []
    try:
        account = pwd.getpwnam(user)
    except KeyError:
        return [_check("service identity", "fail", f"account {user!r} does not exist")]
    exact = account.pw_uid == uid and account.pw_gid == gid
    checks.append(_check(
        "service identity", "pass" if exact else "fail",
        (f"{user} resolves to UID {account.pw_uid}, primary GID {account.pw_gid}; "
         f"expected {uid}:{gid}"), uid=account.pw_uid, gid=account.pw_gid))
    try:
        group_name = grp.getgrgid(gid).gr_name
    except KeyError:
        group_name = None
    checks.append(_check(
        "service login disabled", "pass" if account.pw_shell.endswith("nologin") else "warn",
        f"shell is {account.pw_shell}", home=account.pw_dir,
        primary_group=group_name))
    return checks


def _option_value(options: frozenset[str], name: str) -> str | None:
    prefix = name + "="
    return next((item[len(prefix):] for item in options if item.startswith(prefix)), None)


def mount_checks(path: Path, role: str, mode: str, mounts: list[Mount], fstab: list[Mount],
                 expected_source: str | None = None) -> list[dict]:
    path = Path(os.path.realpath(path))
    mount = mount_for(path, mounts)
    if mount is None:
        return [_check(f"{role} mount", "fail", "no containing mount was found")]
    target = Path(os.path.realpath(mount.target))
    exact = target == path
    checks = [_check(
        f"{role} exact mount", "pass" if exact else "fail",
        f"resolved by mount {target}; the configured path must itself be a mount point",
        target=str(target), source=mount.source, fstype=mount.fstype)]
    supported = mount.fstype in NETWORK_FS
    checks.append(_check(
        f"{role} network filesystem", "pass" if supported else "fail",
        f"filesystem is {mount.fstype}; supported types are NFS and SMB/CIFS",
        fstype=mount.fstype))
    if expected_source:
        checks.append(_check(
            f"{role} export", "pass" if mount.source == expected_source else "fail",
            f"mounted source is {mount.source!r}; expected {expected_source!r}"))
    actual_mode = "rw" if "rw" in mount.options else "ro" if "ro" in mount.options else "unknown"
    checks.append(_check(
        f"{role} access mode", "pass" if actual_mode == mode else "fail",
        f"runtime mode is {actual_mode}; expected {mode}"))
    if mount.fstype in NFS_FS:
        missing = sorted(REQUIRED_NFS_OPTIONS - mount.options)
        checks.append(_check(
            f"{role} NFS safety options", "pass" if not missing else "fail",
            "required runtime options are present" if not missing else
            "missing runtime options: " + ", ".join(missing),
            required=sorted(REQUIRED_NFS_OPTIONS), missing=missing))
        version = (_option_value(mount.options, "vers") or
                   _option_value(mount.options, "nfsvers"))
        checks.append(_check(
            f"{role} NFS version", "pass" if version in {"4.1", "4.2"} else "fail",
            f"runtime NFS version is {version or 'not reported'}; require 4.1 or newer"))
        for option, expected in (("timeo", "600"), ("rsize", "262144"),
                                 ("wsize", "262144")):
            actual = _option_value(mount.options, option)
            checks.append(_check(
                f"{role} {option}", "pass" if actual == expected else "warn",
                f"runtime {option} is {actual or 'not reported'}; proposed value is {expected}"))
    elif mount.fstype in SMB_FS:
        missing = sorted(REQUIRED_SMB_OPTIONS - mount.options)
        checks.append(_check(
            f"{role} SMB safety options", "pass" if not missing else "fail",
            "required runtime options are present" if not missing else
            "missing runtime options: " + ", ".join(missing),
            required=sorted(REQUIRED_SMB_OPTIONS), missing=missing))
        version = _option_value(mount.options, "vers")
        checks.append(_check(
            f"{role} SMB version", "pass" if version == "3.1.1" else "fail",
            f"runtime SMB version is {version or 'not reported'}; require 3.1.1"))
        actual_uid = _option_value(mount.options, "uid")
        actual_gid = _option_value(mount.options, "gid")
        identity_ok = actual_uid == str(DEFAULT_UID) and actual_gid == str(DEFAULT_GID)
        checks.append(_check(
            f"{role} SMB service identity", "pass" if identity_ok else "fail",
            f"runtime forced identity is {actual_uid or '?'}:{actual_gid or '?'}; "
            f"expected {DEFAULT_UID}:{DEFAULT_GID}"))
        checks.append(_check(
            f"{role} SMB timeout behavior", "warn" if "soft" in mount.options else "pass",
            "runtime uses soft timeout behavior; acceptance depends on the active fsync, "
            "locking and SQLite probes" if "soft" in mount.options else
            "runtime does not report soft timeout behavior"))
    configured = [item for item in fstab
                  if Path(os.path.realpath(item.target)) == path and item.source == mount.source]
    checks.append(_check(
        f"{role} boot ordering", "pass" if configured and "_netdev" in configured[0].options else
        "fail", "matching fstab entry includes _netdev" if configured and
        "_netdev" in configured[0].options else
        "no matching fstab entry with _netdev was found"))
    return checks


def capacity_checks(path: Path, role: str, reserve_bytes: int,
                    reserve_inodes: int = DEFAULT_RESERVE_INODES) -> list[dict]:
    try:
        stats = os.statvfs(path)
    except OSError as error:
        return [_check(f"{role} capacity", "fail", f"statvfs failed: {error.strerror}")]
    free = stats.f_bavail * stats.f_frsize
    total = stats.f_blocks * stats.f_frsize
    inodes = stats.f_favail
    inodes_reported = stats.f_files > 0 or stats.f_favail > 0
    return [
        _check(f"{role} free-space reserve", "pass" if free >= reserve_bytes else "fail",
               f"{free} bytes available; require at least {reserve_bytes}",
               free_bytes=free, total_bytes=total, reserve_bytes=reserve_bytes),
        _check(f"{role} free-inode reserve",
               ("warn" if not inodes_reported else
                "pass" if inodes >= reserve_inodes else "fail"),
               ("filesystem does not report inode capacity; enforce byte capacity and "
                "monitor server-side object/file counts" if not inodes_reported else
                f"{inodes} inodes available; require at least {reserve_inodes}"),
               free_inodes=inodes, total_inodes=stats.f_files,
               reserve_inodes=reserve_inodes, reported=inodes_reported),
    ]


def scratch_checks(scratch: Path, protected: list[Path], mounts: list[Mount]) -> list[dict]:
    scratch = Path(os.path.realpath(scratch))
    if not scratch.is_dir():
        return [_check("scratch directory", "fail", f"{scratch} is not a directory")]
    mount = mount_for(scratch, mounts)
    checks = [_check("scratch directory", "pass", "scratch exists", path=str(scratch))]
    network = mount is not None and mount.fstype in NETWORK_FS
    checks.append(_check("scratch is local/rebuildable", "fail" if network else "pass",
                         f"filesystem is {mount.fstype if mount else 'unknown'}"))
    for path in protected:
        real = Path(os.path.realpath(path))
        overlap = scratch == real or scratch in real.parents or real in scratch.parents
        checks.append(_check(
            f"scratch separated from {real.name or 'root'}", "fail" if overlap else "pass",
            "paths overlap" if overlap else "paths do not overlap"))
        try:
            protected_device = os.stat(path).st_dev
        except OSError as error:
            checks.append(_check(
                f"scratch device separate from {real.name or 'root'}", "fail",
                f"could not inspect protected path: {error.strerror}"))
        else:
            separate_device = os.stat(scratch).st_dev != protected_device
            checks.append(_check(
                f"scratch device separate from {real.name or 'root'}",
                "pass" if separate_device else "fail",
                "different filesystems" if separate_device else "same filesystem/device"))
    return checks


_LOCK_CHILD = r"""
import fcntl, json, os, sys
fd = os.open(sys.argv[1], os.O_RDWR)
try:
    try:
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = "acquired"
        fcntl.lockf(fd, fcntl.LOCK_UN)
    except BlockingIOError:
        result = "blocked"
finally:
    os.close(fd)
print(json.dumps({"result": result}))
"""


_SQLITE_CHILD = r"""
import json, sqlite3, sys
try:
    db = sqlite3.connect(sys.argv[1], timeout=0.1)
    try:
        db.execute("INSERT INTO probe(value) VALUES ('child')")
        db.commit()
        result = "committed"
    finally:
        db.close()
except sqlite3.OperationalError as error:
    result = "locked" if "locked" in str(error).lower() else "error:" + str(error)
print(json.dumps({"result": result}))
"""


def _child_result(script: str, path: Path) -> str:
    process = subprocess.run([sys.executable, "-c", script, str(path)],
                             capture_output=True, text=True, timeout=15)
    if process.returncode:
        return "error:child exited " + str(process.returncode)
    try:
        return json.loads(process.stdout)["result"]
    except (ValueError, KeyError, TypeError):
        return "error:invalid child response"


def probe_write_semantics(directory: Path) -> list[dict]:
    """Run isolated destructive-to-self checks, then remove every probe file."""
    directory = Path(directory)
    probe = directory / f".cryostack-preflight-{uuid.uuid4().hex}"
    checks: list[dict] = []
    created = False
    try:
        probe.mkdir(mode=0o700)
        created = True
        source, replacement = probe / "atomic.state", probe / ".atomic.state.next"
        with source.open("wb") as handle:
            handle.write(b"old")
            handle.flush()
            os.fsync(handle.fileno())
        with replacement.open("wb") as handle:
            handle.write(b"new")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(replacement, source)
        dir_fd = os.open(probe, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        checks.append(_check("atomic rename and fsync", "pass" if source.read_bytes() == b"new"
                             else "fail", "file and directory fsync plus replace completed"))

        lock_path = probe / "range-lock"
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, b"lock")
            os.fsync(fd)
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            while_locked = _child_result(_LOCK_CHILD, lock_path)
            fcntl.lockf(fd, fcntl.LOCK_UN)
            after_unlock = _child_result(_LOCK_CHILD, lock_path)
        finally:
            os.close(fd)
        lock_ok = while_locked == "blocked" and after_unlock == "acquired"
        checks.append(_check("POSIX byte-range locks", "pass" if lock_ok else "fail",
                             f"child while locked={while_locked}; after unlock={after_unlock}"))

        database = probe / "sqlite-wal.db"
        db = sqlite3.connect(database, timeout=5)
        try:
            journal = db.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower()
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE probe (value TEXT NOT NULL)")
            db.commit()
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO probe(value) VALUES ('parent')")
            while_locked = _child_result(_SQLITE_CHILD, database)
            db.commit()
            after_unlock = _child_result(_SQLITE_CHILD, database)
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            rows = db.execute("SELECT COUNT(*) FROM probe").fetchone()[0]
        finally:
            db.close()
        sqlite_ok = (journal == "wal" and while_locked == "locked" and
                     after_unlock == "committed" and integrity == "ok" and rows == 2)
        checks.append(_check(
            "SQLite WAL locking and integrity", "pass" if sqlite_ok else "fail",
            (f"journal={journal}; competing writer={while_locked}; post-unlock={after_unlock}; "
             f"integrity={integrity}; rows={rows}")))
    except (OSError, sqlite3.Error, subprocess.SubprocessError) as error:
        checks.append(_check("write semantics probe", "fail",
                             f"{type(error).__name__}: {error}"))
    finally:
        if created:
            try:
                shutil.rmtree(probe)
                parent_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
                checks.append(_check("probe cleanup", "pass", "isolated probe removed"))
            except OSError as error:
                checks.append(_check("probe cleanup", "fail",
                                     f"manual cleanup required for {probe.name}: {error.strerror}"))
    return checks


def backup_checks(backup_path: Path | None, drill_scratch: Path | None) -> list[dict]:
    if backup_path is None:
        return [_check("backup verification", "not_run", "provide --backup"),
                _check("restore drill", "not_run", "provide --backup and --drill-scratch")]
    import cryostack_backup

    verified = cryostack_backup.verify(backup_path)
    checks = [_check("backup verification", "pass" if verified["ok"] else "fail",
                     "checksums and component integrity pass" if verified["ok"] else
                     "; ".join(verified["problems"][:3]),
                     stamp=verified.get("stamp"), files=verified.get("files"))]
    if drill_scratch is None:
        checks.append(_check("restore drill", "not_run", "provide --drill-scratch"))
    elif not verified["ok"]:
        checks.append(_check("restore drill", "fail", "backup did not verify"))
    else:
        try:
            drilled = cryostack_backup.drill(backup_path, drill_scratch)
        except (OSError, cryostack_backup.BackupError) as error:
            checks.append(_check("restore drill", "fail",
                                 f"{type(error).__name__}: {error}"))
        else:
            checks.append(_check("restore drill", "pass" if drilled["ok"] else "fail",
                                 "all components restored and opened" if drilled["ok"] else
                                 "; ".join(drilled["problems"][:3]),
                                 seconds=drilled.get("seconds")))
    return checks


def preflight(*, workspace: Path, dataset: Path, scratch: Path,
              dataset_mode: str = "ro", expected_workspace_source: str | None = None,
              expected_dataset_source: str | None = None, service_user: str = DEFAULT_SERVICE_USER,
              uid: int = DEFAULT_UID, gid: int = DEFAULT_GID,
              reserve_bytes: int = DEFAULT_RESERVE_BYTES, state_root: Path | None = None,
              reserve_inodes: int = DEFAULT_RESERVE_INODES,
              backup_path: Path | None = None, drill_scratch: Path | None = None,
              write_probe: bool = False, mounts: list[Mount] | None = None,
              fstab: list[Mount] | None = None) -> dict:
    mounts = read_mounts() if mounts is None else mounts
    fstab = read_fstab() if fstab is None else fstab
    checks = identity_checks(service_user, uid, gid)
    checks += mount_checks(workspace, "workspace", "rw", mounts, fstab,
                           expected_workspace_source)
    checks += mount_checks(dataset, "dataset", dataset_mode, mounts, fstab,
                           expected_dataset_source)
    checks += capacity_checks(workspace, "workspace", reserve_bytes, reserve_inodes)
    checks += capacity_checks(dataset, "dataset", reserve_bytes, reserve_inodes)
    protected = [workspace, dataset]
    if state_root is not None:
        from cryostack_src import storage_layout

        protected.append(state_root)
        try:
            problems = storage_layout.location_problems(state_root)
        except OSError as error:
            checks.append(_check("state volume marker", "fail",
                                 f"could not inspect state root: {error.strerror}"))
        else:
            checks.append(_check("state volume marker", "pass" if not problems else "fail",
                                 "marked durable volume" if not problems else
                                 "; ".join(problems)))
        checks += capacity_checks(state_root, "state", reserve_bytes, reserve_inodes)
    else:
        checks.append(_check("state volume marker", "not_run", "provide --state-root"))
    checks += scratch_checks(scratch, protected, mounts)
    checks += backup_checks(backup_path, drill_scratch)
    if write_probe:
        workspace_mount = mount_for(workspace, mounts)
        exact_network_mount = (
            workspace_mount is not None and workspace_mount.fstype in NETWORK_FS and
            Path(os.path.realpath(workspace_mount.target)) == Path(os.path.realpath(workspace)))
        identity = os.geteuid() == uid and os.getegid() == gid
        if not exact_network_mount:
            checks.append(_check("write semantics probe", "fail",
                                 "refused: workspace is not an exact approved network mount"))
        elif not identity:
            checks.append(_check("write semantics probe", "fail",
                                 f"refused: run as UID:GID {uid}:{gid}, not "
                                 f"{os.geteuid()}:{os.getegid()}"))
        else:
            checks += probe_write_semantics(workspace)
    else:
        checks.append(_check("write semantics probe", "not_run",
                             "run as the service identity with --write-probe"))
    failures = [item for item in checks if item["status"] == "fail"]
    incomplete = [item for item in checks if item["status"] == "not_run"]
    return {
        "schema": "cryostack.cedar-preflight", "version": 1,
        "created_at": time.time(), "read_only": not write_probe,
        "ok": not failures, "ready_for_cutover": not failures and not incomplete,
        "summary": {status: sum(1 for item in checks if item["status"] == status)
                    for status in ("pass", "warn", "fail", "not_run")},
        "checks": checks,
        "next": ("Do not cut over; resolve failed and not-run checks."
                 if failures or incomplete else
                 "Preflight evidence is complete; cutover still requires operator approval."),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--workspace", required=True, type=Path,
                        help="exact CEDAR workspace mount (read/write)")
    parser.add_argument("--dataset", required=True, type=Path,
                        help="exact CEDAR shared-dataset mount")
    parser.add_argument("--scratch", required=True, type=Path,
                        help="local rebuildable scratch directory")
    parser.add_argument("--state-root", type=Path,
                        help="marked durable root for databases and authoritative metadata")
    parser.add_argument("--dataset-mode", choices=("ro", "rw"), default="ro")
    parser.add_argument("--workspace-source", help="exact expected NFS or SMB export")
    parser.add_argument("--dataset-source", help="exact expected NFS or SMB export")
    parser.add_argument("--service-user", default=DEFAULT_SERVICE_USER)
    parser.add_argument("--uid", type=int, default=DEFAULT_UID)
    parser.add_argument("--gid", type=int, default=DEFAULT_GID)
    parser.add_argument("--minimum-free-gib", type=float, default=5.0)
    parser.add_argument("--minimum-free-inodes", type=int, default=DEFAULT_RESERVE_INODES,
                        help="required available inode reserve on every persistent filesystem")
    parser.add_argument("--backup", type=Path, help="verified CryoStack backup directory")
    parser.add_argument("--drill-scratch", type=Path,
                        help="empty non-production directory for a restore drill")
    parser.add_argument("--write-probe", action="store_true",
                        help="run isolated semantics checks; caller must be service identity")
    args = parser.parse_args(argv)
    if args.minimum_free_gib < 0:
        parser.error("--minimum-free-gib cannot be negative")
    if args.minimum_free_inodes < 0:
        parser.error("--minimum-free-inodes cannot be negative")
    if args.drill_scratch and not args.backup:
        parser.error("--drill-scratch requires --backup")
    result = preflight(
        workspace=args.workspace, dataset=args.dataset, scratch=args.scratch,
        state_root=args.state_root, dataset_mode=args.dataset_mode,
        expected_workspace_source=args.workspace_source,
        expected_dataset_source=args.dataset_source,
        service_user=args.service_user, uid=args.uid, gid=args.gid,
        reserve_bytes=int(args.minimum_free_gib * 1024 ** 3),
        reserve_inodes=args.minimum_free_inodes,
        backup_path=args.backup, drill_scratch=args.drill_scratch,
        write_probe=args.write_probe)
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0 if result["ready_for_cutover"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
