#!/usr/bin/env python3
"""Start a Voila kernel, optionally inside a per-user sandbox.

Used as the ``python3`` kernelspec of the gateway's Voila servers
(``bin/voila_config/kernels/python3``). ``CRYOSTACK_KERNEL_SANDBOX``:

``off`` (default)
    the stock ``python -m ipykernel_launcher -f <connection file>``.
``bwrap``
    the same command inside a bubblewrap sandbox (no root needed) that sees:

    * its own process tree only -- not the gateway or other kernels;
    * the system, the Python environment and the code, read-only, with the
      installation's ``var/`` (databases), ``users/`` (gateway workspaces),
      logs and local source configuration hidden;
    * of the Voila workspace root, only the signed-in user's directory
      (writable); ``icesee_jupyter_book/icesee_runs`` is that user's own;
    * ``HOME`` in that user's workspace, so HPC keys and SSH settings are
      per user; the operator's home (``~/.aws``, ``~/.ssh``, ``~/.cryostack``,
      backups) is absent;
    * model installations (``ISSM_DIR``, ``ICEPACK_ROOT``, ...) read-only;
      AWS settings only from ``CRYOSTACK_KERNEL_AWS_DIR`` when given.

    The network is shared (Voila, the gateway, HPC and cloud are reached as
    before). Without a CryoStack identity or without bubblewrap the kernel
    does not start (fail closed).
"""
from __future__ import annotations

import grp
import os
import pwd
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MODE_ENV = "CRYOSTACK_KERNEL_SANDBOX"
BWRAP_ENV = "CRYOSTACK_KERNEL_BWRAP"
RO_PATHS_ENV = "CRYOSTACK_KERNEL_RO_PATHS"
AWS_DIR_ENV = "CRYOSTACK_KERNEL_AWS_DIR"
HIDE_ENV = "CRYOSTACK_KERNEL_HIDE"

#: installation paths a kernel never sees (relative to the repository)
HIDDEN_DIRS = ("var", "users")
HIDDEN_FILES = ("icesee.log", "relay.log",
                "icesee_jupyter_book/applications/frozen_legacies/radar_sources.local.yaml")
#: model installations: environment variable -> directory names in the operator home
MODEL_ROOTS = {"ISSM_DIR": ("ISSM", "issm"), "ICEPACK_ROOT": ("icepack", "Icepack"),
               "ICESEE_GHUB_ROOT": ()}
#: settings a sandboxed kernel must not use (JPY_PARENT_PID names a process
#: outside its PID namespace; --die-with-parent ties the kernel to it instead)
DROPPED_ENV = ("CRYOSTACK_AUTH_DATABASE", "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE",
               "JPY_PARENT_PID")


class SandboxError(RuntimeError):
    pass


def kernel_command(connection_file: str, extra: list[str] | None = None) -> list[str]:
    return [sys.executable, "-m", "ipykernel_launcher", "-f", connection_file, *(extra or [])]


def _owner_dir(workspace_root: Path, user_id: str) -> Path:
    from cryostack_src.workspace.identity import WorkspaceUser

    user = WorkspaceUser(user_id=user_id, source="cryostack-auth")
    if not user.is_authenticated:
        raise SandboxError("no CryoStack identity for this kernel")
    return workspace_root / "users" / user.safe_id


def _flatten_ssh_config(path: Path, depth: int = 0) -> str:
    """The client configuration with every ``Include`` inlined (ssh semantics:
    relative patterns are under /etc/ssh, files in lexical order)."""
    import glob
    import shlex

    if depth > 8:
        return ""
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        words = line.strip().split(None, 1)
        if words and words[0].lower() == "include" and len(words) == 2:
            for pattern in shlex.split(words[1]):
                pattern = pattern if pattern.startswith("/") else f"/etc/ssh/{pattern}"
                for included in sorted(glob.glob(os.path.expanduser(pattern))):
                    if os.path.isfile(included) and os.access(included, os.R_OK):
                        out.append(f"# --- {included}")
                        out.append(_flatten_ssh_config(Path(included), depth + 1))
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def sandbox_command(connection_file: str, *, env: dict | None = None, cwd: Path | None = None,
                    bwrap: str | None = None, operator_home: Path | None = None,
                    extra: list[str] | None = None) -> tuple[list[str], dict]:
    """(argv, environment) of the sandboxed kernel; directories it needs are created."""
    env = dict(os.environ if env is None else env)
    cwd = Path(cwd or os.getcwd()).resolve()
    operator_home = Path(operator_home or Path.home())
    bwrap = bwrap or env.get(BWRAP_ENV) or shutil.which("bwrap")
    if not bwrap:
        raise SandboxError("bubblewrap (bwrap) is not installed")
    from cryostack_src.workspace.identity import USER_ID_ENV

    user_id = (env.get(USER_ID_ENV) or "").strip()
    if not user_id:
        raise SandboxError("no CryoStack identity for this kernel")
    root_value = (env.get("CRYOSTACK_WORKSPACE_ROOT") or "").strip()
    workspace_root = Path(root_value).resolve() if root_value else cwd
    owner = _owner_dir(workspace_root, user_id)
    home = owner / ".cryostack" / "home"
    runs = owner / ".cryostack" / "icesee_runs"
    book_runs = REPO / "icesee_jupyter_book" / "icesee_runs"
    for path in (owner, home, runs):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    book_runs.mkdir(exist_ok=True)               # mount point inside the read-only code

    prefix = Path(sys.prefix).resolve()
    args = [bwrap, "--die-with-parent", "--new-session", "--unshare-pid", "--unshare-ipc",
            "--unshare-uts", "--unshare-cgroup-try", "--cap-drop", "ALL",
            "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc"]
    for link in ("bin", "lib", "lib64", "sbin"):
        target = Path("/") / link
        if target.is_symlink():
            args += ["--symlink", os.readlink(target), str(target)]
    # /sys read-only: MPI (hwloc, UCX) discovers CPUs and interfaces there
    args += ["--ro-bind", "/sys", "/sys"]
    args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/dev/shm", "--tmpfs", "/tmp",
             "--tmpfs", "/var/tmp", "--tmpfs", "/run"]
    if Path("/etc/cryostack").exists():
        args += ["--tmpfs", "/etc/cryostack"]
    args += ["--ro-bind", str(prefix), str(prefix)]
    base = Path(sys.base_prefix).resolve()
    if base != prefix:
        args += ["--ro-bind", str(base), str(base)]
    args += ["--ro-bind", str(REPO), str(REPO)]
    for name in HIDDEN_DIRS:
        if (REPO / name).exists():
            args += ["--tmpfs", str(REPO / name)]
    hidden = list(HIDDEN_FILES) + [p for p in (env.get(HIDE_ENV) or "").split(os.pathsep) if p]
    for name in hidden:
        path = REPO / name
        if path.is_file():
            args += ["--ro-bind", "/dev/null", str(path)]
        elif path.is_dir():
            args += ["--tmpfs", str(path)]

    extra_env = {}
    read_only = [Path(p) for p in (env.get(RO_PATHS_ENV) or "").split(os.pathsep) if p]
    for variable, names in MODEL_ROOTS.items():
        value = (env.get(variable) or "").strip()
        if value:
            read_only.append(Path(value))
            continue
        for name in names:                      # home-relative guesses no longer work
            candidate = operator_home / name
            if candidate.is_dir():
                read_only.append(candidate)
                extra_env[variable] = str(candidate)
                break
    for path in read_only:
        if path.exists():
            args += ["--ro-bind", str(path), str(path)]

    # only this user's part of the workspace root, writable
    args += ["--tmpfs", str(workspace_root / "users"), "--bind", str(owner), str(owner)]
    args += ["--bind", str(runs), str(book_runs)]

    aws_dir = (env.get(AWS_DIR_ENV) or "").strip()
    if aws_dir:
        args += ["--ro-bind", aws_dir, "/run/cryostack/aws"]
        extra_env["AWS_CONFIG_FILE"] = "/run/cryostack/aws/config"
        extra_env["AWS_SHARED_CREDENTIALS_FILE"] = "/run/cryostack/aws/credentials"

    # accounts may come from a directory service the sandbox cannot reach:
    # give the kernel (ssh, getpass, ...) its own entry, with the sandbox home
    identity = owner / ".cryostack" / "identity"
    identity.mkdir(exist_ok=True, mode=0o700)
    uid, gid = os.getuid(), os.getgid()
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        name = f"u{uid}"
    try:
        group = grp.getgrgid(gid).gr_name
    except KeyError:
        group = name
    (identity / "passwd").write_text(f"root:x:0:0:root:/root:/sbin/nologin\n"
                                     f"{name}:x:{uid}:{gid}:CryoStack kernel:{home}:/bin/sh\n")
    (identity / "group").write_text(f"root:x:0:\n{group}:x:{gid}:\n")
    args += ["--ro-bind", str(identity / "passwd"), "/etc/passwd",
             "--ro-bind", str(identity / "group"), "/etc/group"]
    # root-owned files appear owned by "nobody" in the sandbox and ssh refuses
    # such client configuration: hand it one flattened copy the kernel owns
    ssh_config = Path("/etc/ssh/ssh_config")
    if ssh_config.is_file():
        flat = identity / "ssh_config"
        flat.write_text(_flatten_ssh_config(ssh_config))
        flat.chmod(0o600)
        args += ["--ro-bind", str(flat), str(ssh_config)]

    connection = Path(connection_file).resolve()
    args += ["--ro-bind", str(connection), str(connection), "--chdir", str(cwd)]

    child_env = {k: v for k, v in env.items() if k not in DROPPED_ENV and k != BWRAP_ENV}
    child_env.update(extra_env)
    child_env["HOME"] = str(home)
    # kernels started from inside (report notebooks) are already in the sandbox
    child_env[MODE_ENV] = "off"
    child_env["TMPDIR"] = "/tmp"
    args += ["--", *kernel_command(str(connection), extra)]
    return args, child_env


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2 or argv[0] != "-f":
        print("usage: cryostack_kernel.py -f <connection file> [ipykernel options]", file=sys.stderr)
        return 2
    # nbclient/papermill add kernel options such as --HistoryManager.hist_file=:memory:
    connection, extra = argv[1], argv[2:]
    mode = (os.environ.get(MODE_ENV) or "off").strip().lower()
    if mode == "off":
        command = kernel_command(connection, extra)
        os.execv(command[0], command)
    if mode != "bwrap":
        print(f"{MODE_ENV} must be 'off' or 'bwrap', not {mode!r}", file=sys.stderr)
        return 2
    try:
        command, env = sandbox_command(connection, extra=extra)
    except (SandboxError, OSError) as error:
        print(f"CryoStack kernel sandbox: {error}; the kernel was not started.", file=sys.stderr)
        return 1
    os.execve(command[0], command, env)
    return 1  # not reached


if __name__ == "__main__":
    sys.exit(main())
