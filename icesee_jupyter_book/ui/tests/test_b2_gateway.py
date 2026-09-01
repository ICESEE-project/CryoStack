"""B2 at the gateway level: restore, cross-user isolation, no blank PUT race.

Exercises the real ``build_icesheets_ui`` / ``build_icesee_ui`` against a
seeded per-user auth DB.
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

ALICE_STATE = {
    "schema_version": 2,
    "selected_resource": "pace",
    "selected_resource_name": "pace",
    "resources": {
        "pace": {
            "hpc_username": "alice-hpc",
            "remote_directory": "/scratch/alice",
            "account": "proj-alice",
            "email": "alice@lab.test",
            "access_mode": "connector",
            "auth_mode": "key",
        }
    },
}
ALICE_VALUES = ("alice-hpc", "/scratch/alice", "proj-alice", "alice@lab.test")


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "cryostack_auth.db"
    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(db))
    storage = AuthStorage(db)
    alice = storage.create_user(email="alice@x.test", display_name="Alice",
                                institution=None, password_hash="x")
    bob = storage.create_user(email="bob@x.test", display_name="Bob",
                              institution=None, password_hash="x")

    # kill network in the connector bridge
    import icesee_jupyter_book.core.connector_relay_client as rc

    def _boom(*a, **k):
        raise RuntimeError("no network in tests")

    monkeypatch.setattr(rc.requests, "post", _boom, raising=False)
    monkeypatch.setattr(rc.requests, "get", _boom, raising=False)

    # record every persistence PUT
    import icesee_jupyter_book.ui.workspace_bridge as wb
    saves: list = []
    monkeypatch.setattr(wb.WorkspaceBridge, "save",
                        lambda self, *, application, state: saves.append((application, state)))

    return storage, alice.id, bob.id, saves, monkeypatch


def _widget_strings(ui):
    out = []

    def walk(w):
        v = getattr(w, "value", None)
        if isinstance(v, str):
            out.append(v)
        for c in getattr(w, "children", None) or []:
            walk(c)

    walk(ui)
    return "\n".join(out)


def _build(name):
    if name == "icesheets":
        from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
        return build_icesheets_ui()
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui
    return build_icesee_ui()


@pytest.mark.parametrize("gw", ["icesheets", "icesee"])
def test_authenticated_user_settings_are_restored(gw, env, monkeypatch):
    storage, alice, _bob, saves, _ = env
    app = "cryolauncher" if gw == "icesheets" else "icesee"
    storage.save_workspace(user_id=alice, application=app, state_json=json.dumps(ALICE_STATE))
    monkeypatch.setenv("HTTP_X_CRYOSTACK_USER_ID", alice)

    joined = _widget_strings(_build(gw))
    for v in ALICE_VALUES:
        assert v in joined, f"{gw}: {v!r} not restored"


@pytest.mark.parametrize("gw", ["icesheets", "icesee"])
def test_user_b_sees_none_of_user_a_settings(gw, env, monkeypatch):
    storage, alice, bob, saves, _ = env
    app = "cryolauncher" if gw == "icesheets" else "icesee"
    storage.save_workspace(user_id=alice, application=app, state_json=json.dumps(ALICE_STATE))
    monkeypatch.setenv("HTTP_X_CRYOSTACK_USER_ID", bob)   # Bob has no row

    joined = _widget_strings(_build(gw))
    for v in ALICE_VALUES:
        assert v not in joined, f"{gw}: leaked {v!r} to another user"
    # resource facts still populate
    assert "login-phoenix-rh9.pace.gatech.edu" in joined


@pytest.mark.parametrize("gw", ["icesheets", "icesee"])
def test_no_blank_put_during_build_over_stored_state(gw, env, monkeypatch):
    storage, alice, _bob, saves, _ = env
    app = "cryolauncher" if gw == "icesheets" else "icesee"
    storage.save_workspace(user_id=alice, application=app, state_json=json.dumps(ALICE_STATE))
    monkeypatch.setenv("HTTP_X_CRYOSTACK_USER_ID", alice)

    _build(gw)

    # building + hydrating must not have written anything back
    assert saves == [], f"{gw}: {len(saves)} PUT(s) during build/restore: {saves}"

    # and the stored state is still intact
    row = storage.get_workspace(user_id=alice, application=app)
    assert json.loads(row.state_json)["resources"]["pace"]["hpc_username"] == "alice-hpc"


@pytest.mark.parametrize("gw", ["icesheets", "icesee"])
def test_restore_failure_is_non_fatal_and_blank(gw, env, monkeypatch):
    storage, alice, _bob, saves, _ = env
    monkeypatch.setenv("HTTP_X_CRYOSTACK_USER_ID", alice)
    # point the auth DB at a broken path -> load returns {}
    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", "/nonexistent/dir/nope.db")

    joined = _widget_strings(_build(gw))
    assert "login-phoenix-rh9.pace.gatech.edu" in joined      # resource facts survive
    for v in ALICE_VALUES:
        assert v not in joined
    assert saves == []


def test_both_gateways_use_the_same_generic_helpers():
    ish = Path(_REPO / "icesee_jupyter_book/ui/icesheets_gateway.py").read_text()
    ise = Path(_REPO / "icesee_jupyter_book/ui/icesee_gateway.py").read_text()
    for src in (ish, ise):
        assert "from cryostack_src.workspace.resource_state import (" in src
        assert "ResourceStateController(" in src
        assert "make_state_io(" in src
        assert "resource_state.hydrate()" in src
        assert "resource_state.switch_resource(" in src
        assert "strip_secrets(" in src
