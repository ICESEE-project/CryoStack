#!/usr/bin/env python3
"""Copy CryoStack HPC keys into the per-user homes of sandboxed kernels.

Without the sandbox, every kernel used the Voila account's ``~/.ssh``:
CryoStack keys in ``~/.ssh/cryostack/id_ed25519_<namespace>`` whose
namespace starts with the first 16 characters of the CryoStack user id
(``cryostack_src/remote/ssh_identity.py``). With ``CRYOSTACK_KERNEL_SANDBOX=bwrap``
a kernel's home is ``<workspace root>/users/<safe id>/.cryostack/home``, so each
key pair must be copied to its owner's home once.

Dry run by default (prints the plan, names only). ``--apply`` copies key pairs
(0600 / 0644) and the shared ``known_hosts`` (host public keys); originals are
never moved or deleted, so the change can be undone by deleting the copies.
Keys whose owner cannot be identified are listed and left alone.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def _users(workspace_root: Path) -> dict[str, Path]:
    """16-character id prefix -> user directory (only unambiguous prefixes)."""
    seen: dict[str, list[Path]] = {}
    users = workspace_root / "users"
    for entry in sorted(users.iterdir()) if users.is_dir() else []:
        if entry.is_dir() and not entry.is_symlink():
            slug = entry.name.rsplit("-", 1)[0].lower()
            seen.setdefault(slug[:16], []).append(entry)
    return {prefix: dirs[0] for prefix, dirs in seen.items() if len(dirs) == 1}


def plan(ssh_dir: Path, workspace_root: Path) -> dict:
    users = _users(workspace_root)
    copies, unmatched = [], []
    for key in sorted((ssh_dir / "cryostack").glob("id_ed25519_*")) if (ssh_dir / "cryostack").is_dir() else []:
        if key.suffix == ".pub" or not key.is_file():
            continue
        namespace = key.name[len("id_ed25519_"):]
        owner = users.get(namespace.split("-", 1)[0].lower())
        if owner is None:
            unmatched.append(key.name)
            continue
        target = owner / ".cryostack" / "home" / ".ssh" / "cryostack"
        copies.append({"key": key.name, "user_dir": owner.name, "target": str(target),
                       "exists": (target / key.name).exists()})
    return {"copies": copies, "unmatched": unmatched,
            "known_hosts": (ssh_dir / "known_hosts").is_file()}


def apply(result: dict, ssh_dir: Path) -> None:
    for item in result["copies"]:
        target = Path(item["target"])
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        for parent in (target, target.parent):
            parent.chmod(0o700)
        for name, mode in ((item["key"], 0o600), (item["key"] + ".pub", 0o644)):
            source = ssh_dir / "cryostack" / name
            if source.is_file() and not (target / name).exists():
                shutil.copyfile(source, target / name)
                (target / name).chmod(mode)
        hosts = ssh_dir / "known_hosts"
        if result["known_hosts"] and not (target.parent / "known_hosts").exists():
            shutil.copyfile(hosts, target.parent / "known_hosts")
            (target.parent / "known_hosts").chmod(0o600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ssh-dir", type=Path, default=Path.home() / ".ssh",
                        help="the Voila account's ~/.ssh (default: this account's)")
    parser.add_argument("--workspace-root", type=Path, required=True,
                        help="Voila workspace root (holds users/)")
    parser.add_argument("--apply", action="store_true", help="copy (default: dry run)")
    args = parser.parse_args(argv)
    result = plan(args.ssh_dir, args.workspace_root)
    if args.apply:
        apply(result, args.ssh_dir)
    print(json.dumps(dict(result, applied=args.apply), indent=1))
    return 0 if not result["unmatched"] else 1


if __name__ == "__main__":
    sys.exit(main())
