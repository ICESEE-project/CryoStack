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

#: names whose mere presence in a tool module is a policy violation. Matched as
#: bare identifiers, attribute tails, dotted tails, and import paths — see
#: :func:`_referenced_names`. Chosen to be unambiguous (a plain regex or a dict
#: key must not trip them).
PROHIBITED_SYMBOLS = frozenset({
    # arbitrary remote command execution (CryoStack helpers)
    "check_backend", "connector_ssh", "send_command", "ssh_run", "run_ssh",
    "run_shell", "run_subprocess", "bootstrap_passwordless_ssh",
    "remote_install_pubkey_with_password", "connector_install_pubkey_with_password",
    # arbitrary command execution / dynamic code — module + call forms
    "subprocess", "Popen", "os.system", "os.popen", "os.spawnv", "os.spawnvp",
    "posix_spawn", "os.execv", "os.execve", "os.execvp", "os.fork",
    "socket", "pty", "ctypes", "importlib", "import_module", "runpy",
    "__import__", "compile_command",
    # secret retrieval / holding
    "deployment_token", "ensure_deployment_token", "current_binding",
    "_control_headers_for", "matlab_license_config", "matlab_license_value",
    # identity spoofing / environment access
    "os.environ", "os.getenv", "os.putenv", "os.setenv", "getpass", "getuser",
})

#: builtins that are dangerous ONLY when *called as a bare name* (``eval(x)``),
#: not as an attribute (``re.compile(...)``). Checked separately.
_PROHIBITED_BUILTIN_CALLS = frozenset({"eval", "exec", "compile", "__import__"})

#: prohibited names a module is nonetheless permitted to reference. Tiny + justified.
_ALLOWED_USES: dict[str, frozenset[str]] = {}

#: modules whose source is subject to the prohibited-symbol scan. Kept in sync
#: with the package by ``test_agent_core`` (asserts every agents/*.py is either
#: here or in the known-core allowlist).
TOOL_MODULES = ("readonly_tools", "planning_tools", "planning", "approval",
                "assistant", "execution", "trace", "trace_store", "experiment",
                "fingerprint", "store", "llm", "llm_adapters", "inspect", "eval",
                "registry", "context", "tools", "permissions")

#: agents/*.py deliberately NOT scanned (pure plumbing, no capability surface)
_UNSCANNED_OK = frozenset({"__init__", "policy"})


def _referenced_names(source: str) -> set[str]:
    names: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr not in _PROHIBITED_BUILTIN_CALLS:    # re.compile is fine
                names.add(node.attr)
            if isinstance(node.value, ast.Name):
                names.add(f"{node.value.id}.{node.attr}")     # e.g. os.environ
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for a in node.names:
                names.add(f"{mod}.{a.name}" if mod else a.name)   # os.environ
                names.add(a.name)
        elif isinstance(node, ast.alias):
            full = node.name
            names.add(full)
            names.add(full.split(".")[0])
            names.add(full.split(".")[-1])
            if node.asname:
                names.add(node.asname)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _PROHIBITED_BUILTIN_CALLS:
                names.add(node.func.id)                        # eval( / exec( / ...
        elif isinstance(node, ast.Name):
            # a bare Name matters only if it is itself a prohibited helper name
            if node.id in PROHIBITED_SYMBOLS:
                names.add(node.id)
    return names


def scan_tool_module(path: str | Path) -> list[str]:
    """Return the prohibited symbols referenced by the module at ``path``,
    minus that module's tiny :data:`_ALLOWED_USES` allowance."""
    p = Path(path)
    src = p.read_text(encoding="utf-8")
    used = _referenced_names(src)
    hits = (PROHIBITED_SYMBOLS | _PROHIBITED_BUILTIN_CALLS) & used
    hits -= _ALLOWED_USES.get(p.stem, frozenset())
    return sorted(hits)


def assert_tool_modules_are_clean() -> None:
    here = Path(__file__).parent
    listed = set(TOOL_MODULES) | _UNSCANNED_OK
    present = {f.stem for f in here.glob("*.py")}
    unlisted = present - listed
    if unlisted:
        raise AssertionError(
            "agents/ modules not in policy.TOOL_MODULES (add them, or to "
            f"_UNSCANNED_OK with a reason): {sorted(unlisted)}")

    violations: dict[str, list[str]] = {}
    for name in TOOL_MODULES:
        f = here / f"{name}.py"
        if not f.is_file():
            raise AssertionError(
                f"policy.TOOL_MODULES names {name!r} but agents/{name}.py "
                "does not exist")
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
