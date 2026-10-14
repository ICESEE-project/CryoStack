"""Test isolation for the whole repository.

A checkout of this repository is also the production tree: the gateway runs
with it as its working directory, so ``users/`` holds the real per-user
workspaces and ``var/`` the authentication, LIVIST, Control Center and Frozen
Legacies databases. Several components default to exactly those locations
(the workspace root falls back to the process working directory; the
databases fall back to ``<repo>/var``).

So that no test ever lands there:

* before any test module is imported, every state location is pointed at a
  fresh per-session temporary directory, and gateway credentials are removed
  from the test environment;
* an audit hook makes any attempt from the test process to write, create,
  delete or open as a database something under a protected path fail at once
  with :class:`ProductionPathError` naming the path;
* at the end of the session, new entries in the protected directories (which a
  subprocess could have created) are reported.

Protected: ``<repo>/users``, ``<repo>/var``, ``~/.cryostack``, ``~/.aws`` and
every path in ``$CRYOSTACK_TEST_PROTECTED_PATHS`` (``os.pathsep``-separated),
e.g. the production checkout when the suite runs in another copy.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent

#: state locations redirected into the session's temporary root
_STATE_ENV = {
    "CRYOSTACK_WORKSPACE_ROOT": "workspace",
    "CRYOSTACK_AUTH_DATABASE": "var/cryostack_auth.db",
    "CRYOSTACK_LIVIST_DATABASE": "var/livist.db",
    "CRYOSTACK_LIVIST_INPUT_CACHE": "var/livist_input_cache",
    "CRYOSTACK_CONTROL_OPS_DATABASE": "var/control_center_ops.db",
    "CRYOSTACK_FROZEN_LEGACIES_CATALOG": "var/frozen_legacies_catalog.db",
    "CRYOSTACK_FROZEN_LEGACIES_WORKING_CACHE": "var/frozen_legacies_cache",
    "CRYOSTACK_FROZEN_LEGACIES_REVIEW_ROOT": "var/frozen_legacies_reviews",
}

#: gateway credentials a test must never see (tests that need one set their own)
_CREDENTIAL_ENV = (
    "CRYOSTACK_GITHUB_CLIENT_ID", "CRYOSTACK_GITHUB_CLIENT_SECRET",
    "CRYOSTACK_ORCID_CLIENT_ID", "CRYOSTACK_ORCID_CLIENT_SECRET",
    "CRYOSTACK_RELAY_CONTROL_TOKEN", "CRYOSTACK_VOILA_TOKEN",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN",
)

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

#: audit events whose path arguments are written, created or removed
_PATH_EVENTS = {
    "os.mkdir": (0,), "os.remove": (0,), "os.rmdir": (0,), "os.rename": (0, 1),
    "os.symlink": (1,), "os.link": (1,), "os.truncate": (0,), "os.chmod": (0,),
    "os.chown": (0,), "os.utime": (0,), "shutil.rmtree": (0,), "shutil.copyfile": (1,),
    "shutil.copytree": (1,), "shutil.move": (0, 1), "sqlite3.connect": (0,),
}


class ProductionPathError(PermissionError):
    """A test tried to touch production data."""


def protected_paths() -> tuple[Path, ...]:
    # icesee_runs/: the unauthenticated default run root (local_runner.run_dir)
    paths = [REPO_ROOT / "users", REPO_ROOT / "var",
             REPO_ROOT / "icesee_jupyter_book" / "icesee_runs",
             Path.home() / ".cryostack", Path.home() / ".aws"]
    extra = os.environ.get("CRYOSTACK_TEST_PROTECTED_PATHS", "")
    paths += [Path(p) for p in extra.split(os.pathsep) if p.strip()]
    return tuple(Path(os.path.realpath(p)) for p in paths)


_PROTECTED: tuple[Path, ...] = ()
#: blocked attempts, kept so a test fails even when the code under test
#: swallows the ProductionPathError
_VIOLATIONS: list[str] = []


def _is_protected(raw) -> Path | None:
    if isinstance(raw, int) or raw is None:
        return None
    try:
        text = os.fsdecode(raw)
    except TypeError:
        return None
    if text.startswith("file:"):                       # sqlite URI
        text = text[5:].split("?", 1)[0]
    if not text or text == ":memory:":
        return None
    path = Path(os.path.realpath(text))
    for root in _PROTECTED:
        if path == root or root in path.parents:
            return path
    return None


def _audit(event: str, args: tuple) -> None:
    if not _PROTECTED:
        return
    if event == "open":
        path, mode, flags = (tuple(args) + (None, None, None))[:3]
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS)
        hit = _is_protected(path) if writing else None
    elif event in _PATH_EVENTS:
        hit = next((p for i in _PATH_EVENTS[event] if i < len(args)
                    for p in [_is_protected(args[i])] if p), None)
    else:
        return
    if hit is not None:
        _VIOLATIONS.append(f"{event} {hit}")
        raise ProductionPathError(
            f"test isolation: {event} on protected path {hit} -- tests must use tmp_path "
            f"or the CRYOSTACK_* locations set by conftest.py, never production users/ or var/"
        )


def _listing(paths) -> set[str]:
    found = set()
    for root in paths:
        if root.is_dir() and root.name in ("users", "var"):
            found.update(str(p) for p in root.iterdir())
    return found


_STATE: dict = {}


def pytest_configure(config):
    global _PROTECTED
    root = Path(tempfile.mkdtemp(prefix="cryostack-tests-"))
    for name, relative in _STATE_ENV.items():
        target = root / relative
        (target if "." not in target.name else target.parent).mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(target)
    for name in _CREDENTIAL_ENV:
        os.environ.pop(name, None)
    _PROTECTED = protected_paths()
    if any(root == p or p in root.parents for p in _PROTECTED):
        raise pytest.UsageError(f"test temporary root {root} is inside a protected path")
    _STATE.update(root=root, before=_listing(_PROTECTED),
                  env={name: os.environ[name] for name in _STATE_ENV})
    if not _STATE.get("hooked"):
        sys.addaudithook(_audit)
        _STATE["hooked"] = True


@pytest.fixture(autouse=True)
def _no_production_paths():
    _VIOLATIONS.clear()
    yield
    problems = [f"blocked access to a production path: {a}" for a in sorted(set(_VIOLATIONS))]
    _VIOLATIONS.clear()
    # a test that unsets a redirected location (instead of letting monkeypatch
    # restore it) would send every later test back to the production default
    for name, value in _STATE.get("env", {}).items():
        if name not in os.environ:
            os.environ[name] = value
            problems.append(f"left {name} unset (use monkeypatch.setenv/delenv)")
    if problems:
        pytest.fail("test isolation:\n  " + "\n  ".join(problems), pytrace=False)


def pytest_terminal_summary(terminalreporter):
    if "before" not in _STATE:
        return
    added = sorted(_listing(_PROTECTED) - _STATE["before"])
    if added:
        terminalreporter.section("test isolation", sep="!", red=True)
        terminalreporter.write_line(
            f"{len(added)} new entries appeared in protected directories during this run "
            "(a subprocess started by a test, or live production activity):")
        for entry in added[:50]:
            terminalreporter.write_line(f"  {entry}")


def pytest_unconfigure(config):
    root = _STATE.pop("root", None)
    if root is not None:
        shutil.rmtree(root, ignore_errors=True)
