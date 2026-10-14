"""The repository-wide test isolation (conftest.py at the repository root).

Tests must never default to the production ``users/`` or ``var/`` of the
checkout they run in. These tests check that every state location resolves to
the session's temporary root and that an attempt to touch a protected path is
refused before anything is written.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


_GUARD = []


@pytest.fixture(autouse=True)
def _repository_conftest(pytestconfig):
    for plugin in pytestconfig.pluginmanager.get_plugins():
        if Path(getattr(plugin, "__file__", "") or "/").resolve() == REPO / "conftest.py":
            _GUARD[:] = [plugin]
            return
    pytest.fail("the repository conftest.py is not loaded")


def _guard():
    return _GUARD[0]


def _outside_production(path: Path) -> bool:
    path = Path(os.path.realpath(path))
    return not any(path == root or root in path.parents for root in _guard().protected_paths())


def test_state_locations_point_at_the_session_temporary_root():
    guard = _guard()
    for name in guard._STATE_ENV:
        assert _outside_production(Path(os.environ[name])), name
    for name in guard._CREDENTIAL_ENV:
        assert name not in os.environ, name


def test_default_workspace_and_databases_are_not_production():
    from cryostack_src.workspace.identity import WorkspaceUser
    from cryostack_src.workspace.roots import owner_root, resolve_workspace_root, user_run_root
    from icesee_auth import AuthManager
    from icesee_jupyter_book.applications.livist import settings as livist_settings
    from icesee_jupyter_book.ui.workspace_persistence import auth_database_path

    user = WorkspaceUser(user_id="isolation-check", display_name="", source="test")
    assert _outside_production(owner_root(user))
    assert _outside_production(resolve_workspace_root())
    assert _outside_production(user_run_root(app="icesee", user=user))
    assert _outside_production(auth_database_path())
    assert _outside_production(Path(AuthManager().storage.database_path))
    assert _outside_production(livist_settings.database_path())
    from icesee_jupyter_book.applications.livist import input_cache
    assert _outside_production(input_cache.cache_dir())
    assert not (REPO / "users" / user.safe_id).exists()


@pytest.mark.parametrize("attempt", [
    lambda p: (p / "users" / "isolation-probe").mkdir(parents=True),
    lambda p: (p / "users" / "isolation-probe.txt").write_text("x"),
    lambda p: open(p / "var" / "isolation-probe.txt", "a"),
    lambda p: os.open(p / "var" / "isolation-probe.txt", os.O_CREAT | os.O_WRONLY),
    lambda p: sqlite3.connect(p / "var" / "isolation-probe.db"),
    lambda p: sqlite3.connect(f"file:{p / 'var' / 'isolation-probe.db'}?mode=ro", uri=True),
], ids=["mkdir", "write_text", "open-append", "os.open", "sqlite", "sqlite-uri"])
def test_touching_production_paths_fails_clearly(attempt):
    guard = _guard()
    with pytest.raises(guard.ProductionPathError, match="protected path"):
        attempt(REPO)
    guard._VIOLATIONS.clear()       # expected here; any other test would now fail
    assert not (REPO / "users" / "isolation-probe").exists()
    assert not (REPO / "users" / "isolation-probe.txt").exists()
    assert not (REPO / "var" / "isolation-probe.txt").exists()
    assert not (REPO / "var" / "isolation-probe.db").exists()


def test_misbehaving_tests_fail_by_name(tmp_path):
    """A test that swallows the guard's error, or unsets a redirected location,
    still fails -- and the next test runs isolated again."""
    import subprocess

    (tmp_path / "test_inner.py").write_text(
        "import os, pathlib\n"
        f"REPO = pathlib.Path({str(REPO)!r})\n"
        "def test_swallows():\n"
        "    try:\n"
        "        (REPO / 'users' / 'isolation-probe').mkdir(parents=True)\n"
        "    except Exception:\n"
        "        pass\n"
        "def test_unsets_root():\n"
        "    del os.environ['CRYOSTACK_WORKSPACE_ROOT']\n"
        "def test_runs_isolated_afterwards():\n"
        "    assert not str(REPO) in os.environ['CRYOSTACK_WORKSPACE_ROOT']\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["PYTHONPATH"] = str(REPO)
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "conftest", "-p", "no:cacheprovider", "-q",
         "--rootdir", str(tmp_path), "-c", os.devnull, str(tmp_path / "test_inner.py")],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    out = done.stdout + done.stderr
    assert done.returncode != 0 and "3 passed, 2 errors" in out, out[-2000:]
    assert "blocked access to a production path" in out
    assert "left CRYOSTACK_WORKSPACE_ROOT unset" in out
    assert not (REPO / "users" / "isolation-probe").exists()


def test_extra_protected_paths_and_ordinary_temp_files(tmp_path, monkeypatch):
    guard = _guard()
    monkeypatch.setenv("CRYOSTACK_TEST_PROTECTED_PATHS", str(tmp_path / "prod"))
    monkeypatch.setattr(guard, "_PROTECTED", guard.protected_paths())
    with pytest.raises(guard.ProductionPathError):
        (tmp_path / "prod" / "users").mkdir(parents=True)
    guard._VIOLATIONS.clear()
    (tmp_path / "ok" / "users").mkdir(parents=True)          # anything else is fine
    (tmp_path / "ok" / "users" / "a.txt").write_text("fine")
    sqlite3.connect(tmp_path / "ok" / "a.db").close()


def test_the_default_icesee_run_root_in_the_checkout_is_protected():
    """``local_runner.run_dir()`` without a base writes into the checkout's
    ``icesee_jupyter_book/icesee_runs`` (unauthenticated default); a test that
    does so must fail instead of leaving run directories behind."""
    from icesee_jupyter_book.core import local_runner

    guard = _guard()
    runs = (local_runner.BOOK / "icesee_runs").resolve()
    assert any(runs == root or root in runs.parents for root in guard.protected_paths())
    with pytest.raises(guard.ProductionPathError):
        local_runner.run_dir(name="isolation-probe")
    guard._VIOLATIONS.clear()                       # the probe itself is expected
    assert not (runs / "isolation-probe").exists()
