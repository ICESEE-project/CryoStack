"""Machine-enforced agent policy checks (A2).

Two things live here:

1. :data:`PROHIBITED_SYMBOLS` — importable names a tool module must never
   reference, because they are arbitrary-command or secret-bearing surface
   (``overnight/AGENT_SAFETY_MODEL.md`` §4). ``assert_tool_modules_are_clean``
   walks the tool packages' source and fails if any appears.

2. :func:`assert_same_user` / :func:`assert_within_workspace` — call-site guards
   for tools that touch the filesystem or a WorkspaceManager, so a tool can
   never be tricked into acting outside the context's identity.
"""
from __future__ import annotations

import ast
from pathlib import Path

from cryostack_src.workspace.identity import WorkspaceIdentityError

#: names whose mere presence in a tool module is a policy violation
PROHIBITED_SYMBOLS = frozenset({
    # arbitrary remote command execution
    "check_backend", "connector_ssh", "send_command", "ssh_run", "run_ssh",
    "run_shell", "run_subprocess", "bootstrap_passwordless_ssh",
    "remote_install_pubkey_with_password", "connector_install_pubkey_with_password",
    # secret retrieval / holding
    "deployment_token", "ensure_deployment_token", "current_binding",
    "_control_headers_for", "matlab_license_config",
    # identity spoofing
    "os.environ", "getpass",
})

#: modules whose tool functions are subject to the source scan
TOOL_MODULES = ("readonly_tools", "planning_tools", "planning", "approval",
                "assistant", "execution", "trace", "trace_store", "experiment")


def _referenced_names(source: str) -> set[str]:
    names: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
            names.add(node.name)
    return names


def scan_tool_module(path: str | Path) -> list[str]:
    """Return the prohibited symbols referenced by the module at ``path``."""
    src = Path(path).read_text(encoding="utf-8")
    used = _referenced_names(src)
    return sorted(PROHIBITED_SYMBOLS & used)


def assert_tool_modules_are_clean() -> None:
    here = Path(__file__).parent
    violations: dict[str, list[str]] = {}
    for name in TOOL_MODULES:
        f = here / f"{name}.py"
        if f.is_file():
            bad = scan_tool_module(f)
            if bad:
                violations[name] = bad
    if violations:
        raise AssertionError(
            "agent tool modules reference prohibited symbols: "
            + "; ".join(f"{m}: {', '.join(s)}" for m, s in violations.items())
        )


# -- call-site guards -------------------------------------------------
def assert_same_user(ctx, owner) -> None:
    """A tool that resolves an owner-scoped API must pass the context's user,
    never an LLM-supplied one. This guard makes an accidental mismatch loud."""
    cid = getattr(ctx, "user_id", None)
    oid = getattr(owner, "user_id", owner)
    if cid is None or str(cid) != str(oid):
        raise WorkspaceIdentityError(
            "agent tool attempted to act as a different identity "
            f"(context={cid!r}, requested={oid!r})"
        )


def assert_within_workspace(manager, path: str | Path) -> Path:
    """Resolve ``path`` only if it is inside ``manager``'s containment."""
    p = Path(path).expanduser().resolve()
    owner_root = getattr(manager, "_owner_root", None)
    if owner_root is None or not str(p).startswith(str(Path(owner_root).resolve())):
        raise WorkspaceIdentityError(
            f"path {p} is outside the authenticated user's workspace"
        )
    return p
