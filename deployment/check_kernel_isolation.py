#!/usr/bin/env python3
"""Check what the account that runs Voila kernels can reach.

Run it as the kernel account (``sudo -u <kernel account> python3
deployment/check_kernel_isolation.py --installation <repo> --operator-home
<home of the gateway account>``), or from a kernel. It only asks the kernel
whether access *would* be granted (``os.access`` / ``stat``); it never opens a
secret, so it is safe to run anywhere.

Must be unreachable: the gateway's environment (OAuth secrets, relay
token), the installation's databases (password hashes, sessions), the
operator's AWS credentials, SSH keys and CryoStack tokens, backups, and
write access to the code. Must stay reachable: the code (read), the
Python that runs it, and the Voila workspace root (write).

Exit status 0 only when nothing on the first list is reachable and
everything on the second is.
"""
from __future__ import annotations

import argparse
import json
import os
import pwd
import sys
from pathlib import Path

_DATABASES = ("cryostack_auth.db", "control_center_ops.db", "livist.db",
              "frozen_legacies_catalog.db")


def gateway_pids(proc: Path = Path("/proc")) -> list[int]:
    """PIDs whose command line runs the gateway (not its ``voila`` mode)."""
    found = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if any(a.endswith(b"bin/icesee_app.py") for a in argv) and b"voila" not in argv:
            found.append(int(entry.name))
    return sorted(found)


def _readable(path: Path) -> bool:
    return path.exists() and os.access(path, os.R_OK)


def _listable(path: Path) -> bool:
    """Its contents can be listed (an empty placeholder, as a sandbox mounts, shows nothing)."""
    if not (path.is_dir() and os.access(path, os.R_OK | os.X_OK)):
        return False
    try:
        return any(path.iterdir())
    except OSError:
        return False


def _writable(path: Path) -> bool:
    return path.exists() and os.access(path, os.W_OK)


def check(installation: Path, operator_home: Path, *, workspace_root: Path | None = None,
          own_workspace: Path | None = None, python: Path | None = None,
          pids: list[int] | None = None, proc: Path = Path("/proc")) -> dict:
    """``own_workspace``: the directory of the user this kernel serves; every
    other directory under ``<workspace_root>/users`` must then be unreachable.
    ``pids``: gateway processes (found in ``proc`` when not given). A path that
    does not exist for this account -- as in a sandbox -- counts as unreachable."""
    installation, operator_home = Path(installation), Path(operator_home)
    workspace_root = Path(workspace_root) if workspace_root else (installation / "icesee_jupyter_book"
                                        / "icesee_jupyter_notebooks" / "users")
    python = python or Path(sys.executable)
    pids = gateway_pids(proc) if pids is None else pids

    must_deny: list[tuple[str, Path, callable]] = []
    for pid in pids:
        must_deny.append((f"gateway environment (pid {pid})", proc / str(pid) / "environ", _readable))
    for name in _DATABASES:
        must_deny.append((f"database var/{name}", installation / "var" / name, _readable))
    must_deny += [
        ("operator AWS credentials", operator_home / ".aws" / "credentials", _readable),
        ("operator AWS config", operator_home / ".aws" / "config", _readable),
        ("operator SSH directory", operator_home / ".ssh", _listable),
        ("operator CryoStack tokens", operator_home / ".cryostack", _listable),
        ("backups", operator_home / "cryostack-backups", _listable),
        ("gateway workspaces users/", installation / "users", _listable),
        ("write access to the gateway code", installation / "bin" / "icesee_app.py", _writable),
        ("write access to the auth code", installation / "icesee_auth", _writable),
    ]
    users_dir = workspace_root / "users"
    if own_workspace is not None and users_dir.is_dir():
        own = Path(own_workspace).resolve()
        for entry in sorted(users_dir.iterdir()):
            if entry.resolve() != own:
                must_deny.append((f"other user's workspace {entry.name}", entry, _listable))
    must_allow = [
        ("read the gateway code", installation / "bin" / "icesee_app.py", _readable),
        ("run the Python interpreter", python, lambda p: p.exists() and os.access(p, os.X_OK)),
        ("write the user's workspace" if own_workspace else "write the Voila workspace root",
         Path(own_workspace) if own_workspace else workspace_root, _writable),
    ]

    exposed, denied, absent, missing = [], [], [], []
    for label, path, test in must_deny:
        if not path.exists() and not path.is_symlink():
            absent.append(label)
        elif test(path):
            exposed.append(label)
        else:
            denied.append(label)
    allowed = []
    for label, path, test in must_allow:
        (allowed if test(path) else missing).append(label)
    account = pwd.getpwuid(os.getuid()).pw_name
    owners = sorted({pwd.getpwuid((proc / str(p)).stat().st_uid).pw_name
                     for p in pids if (proc / str(p)).exists()})
    sandboxed = bool(pids) and not any((proc / str(p)).exists() for p in pids)
    return {
        # separate account, or a sandbox in which the gateway is not even visible
        "ok": not exposed and not missing and (sandboxed or account not in owners),
        "gateway_visible": not sandboxed,
        "account": account,
        "gateway_accounts": owners,
        "same_account_as_gateway": account in owners,
        "exposed": exposed,
        "denied": denied,
        "not_present": absent,
        "allowed": allowed,
        "missing_access": missing,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--installation", type=Path, required=True,
                        help="repository the gateway runs from")
    parser.add_argument("--operator-home", type=Path, required=True,
                        help="home directory of the account that runs the gateway")
    parser.add_argument("--workspace-root", type=Path, help="Voila workspace root (holds users/)")
    parser.add_argument("--own-workspace", type=Path,
                        help="this user's workspace; every other user's must be unreachable")
    parser.add_argument("--gateway-pid", type=int, action="append",
                        help="gateway PID (repeatable; default: found in /proc)")
    args = parser.parse_args(argv)
    result = check(args.installation, args.operator_home, workspace_root=args.workspace_root,
                   own_workspace=args.own_workspace, pids=args.gateway_pid)
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
