"""B2: authenticated, user-scoped server-side read of saved workspace state.

The Voila kernel reads the shared auth DB directly (no browser cookie), scoped
by the proxy-verified user id. Cross-user isolation and fail-closed behaviour.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_auth.storage import AuthStorage
from icesee_jupyter_book.ui.workspace_persistence import (
    load_user_workspace_state,
    make_state_io,
)


@pytest.fixture
def auth_db(tmp_path, monkeypatch):
    db = tmp_path / "cryostack_auth.db"
    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(db))
    storage = AuthStorage(db)
    alice = storage.create_user(email="alice@x.test", display_name="Alice",
                                institution=None, password_hash="x")
    bob = storage.create_user(email="bob@x.test", display_name="Bob",
                              institution=None, password_hash="x")
    return storage, alice.id, bob.id


def test_load_returns_the_authenticated_users_own_row(auth_db):
    storage, alice, bob = auth_db
    storage.save_workspace(
        user_id=alice, application="cryolauncher",
        state_json=json.dumps({"schema_version": 2,
                               "resources": {"pace": {"hpc_username": "alice",
                                                      "account": "project-a"}}}),
    )
    got = load_user_workspace_state(alice, "cryolauncher")
    assert got["resources"]["pace"]["hpc_username"] == "alice"

    # Bob has no row -> blank; never Alice's
    assert load_user_workspace_state(bob, "cryolauncher") == {}
    assert load_user_workspace_state(bob, "icesheets") == {}   # alias -> cryolauncher


def test_blank_user_id_never_reads_anything(auth_db):
    storage, alice, _ = auth_db
    storage.save_workspace(user_id=alice, application="cryolauncher", state_json='{"x":1}')
    assert load_user_workspace_state("", "cryolauncher") == {}
    assert load_user_workspace_state(None, "cryolauncher") == {}


def test_missing_database_is_blank_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(tmp_path / "does-not-exist.db"))
    assert load_user_workspace_state("anyone", "cryolauncher") == {}


def test_corrupt_state_json_is_blank(auth_db):
    storage, alice, _ = auth_db
    storage.save_workspace(user_id=alice, application="cryolauncher", state_json="not json{{")
    assert load_user_workspace_state(alice, "cryolauncher") == {}


def test_make_state_io_save_reuses_the_browser_bridge(auth_db):
    _, alice, _ = auth_db

    class FakeBridge:
        def __init__(self):
            self.calls = []

        def save(self, *, application, state):
            self.calls.append((application, state))

    bridge = FakeBridge()
    load_state, save_state = make_state_io(bridge, "icesheets", alice)
    save_state({"schema_version": 2, "resources": {}})
    assert bridge.calls == [("cryolauncher", {"schema_version": 2, "resources": {}})]
    assert load_state() == {}     # nothing saved server-side yet
