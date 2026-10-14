"""Per-user Frozen Legacies workspace: layout, safe asset IDs, containment,
and isolation between CryoStack users."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.workspace import (
    WorkspaceIdentityError,
    WorkspaceUser,
    owner_root,
    resolve_workspace_user,
)
from cryostack_src.workspace.manager import WorkspacePermissionError
from icesee_jupyter_book.applications.frozen_legacies.workspace import (
    ASSET_OUTPUTS,
    AssetNotFoundError,
    FrozenLegaciesWorkspace,
    is_valid_asset_id,
    new_asset_id,
    workspace_user_for,
)

_A = WorkspaceUser(user_id="user-a", source="cryostack-auth")
_B = WorkspaceUser(user_id="user-b", source="cryostack-auth")


def _ws(root, user=_A):
    return FrozenLegaciesWorkspace(user, workspace_root=root)


# ── identity ─────────────────────────────────────────────────────────
def test_identity_matches_the_voila_applications():
    """The gateway user maps to the same users/<safe_id> as CryoLauncher/ICESEE."""
    auth_user = SimpleNamespace(id="3f2a9c", display_name="A")
    voila_user = resolve_workspace_user({"HTTP_X_CRYOSTACK_USER_ID": "3f2a9c"})
    assert workspace_user_for(auth_user).safe_id == voila_user.safe_id
    assert workspace_user_for(auth_user).is_authenticated


@pytest.mark.parametrize("user_id", ["", "   ", None])
def test_missing_identity_is_rejected(user_id):
    with pytest.raises(WorkspaceIdentityError):
        workspace_user_for(SimpleNamespace(id=user_id, display_name=""))


@pytest.mark.parametrize("user", [
    WorkspaceUser(user_id="anonymous", source="unauthenticated"),
    WorkspaceUser(user_id="someone", source="env-override"),
    WorkspaceUser(user_id="anonymous", source="cryostack-auth"),
])
def test_workspace_requires_an_authenticated_user(tmp_path, user):
    with pytest.raises(WorkspaceIdentityError):
        _ws(tmp_path, user)


# ── layout ───────────────────────────────────────────────────────────
def test_application_scoped_layout(tmp_path):
    ws = _ws(tmp_path)
    assert ws.root == owner_root(_A, workspace_root=tmp_path) / "frozen_legacies"
    assert ws.radar_root == ws.root / "radar"
    assert not ws.root.exists()          # nothing is created until ensure()

    ws.ensure()
    assert ws.radar_root.is_dir()

    asset_id, path = ws.create_asset()
    assert path == ws.radar_root / asset_id
    assert (path / ASSET_OUTPUTS).is_dir()
    assert ws.list_asset_ids() == [asset_id]
    assert ws.asset_file(asset_id, "asset.json") == path / "asset.json"
    assert ws.asset_file(asset_id, "source.tiff") == path / "source.tiff"
    assert ws.asset_file(asset_id, "nav.csv") == path / "nav.csv"
    assert ws.asset_file(asset_id, "session.json") == path / "session.json"
    assert ws.output_file(asset_id, "F127-C0471_C0483.csv") == (
        path / "outputs" / "F127-C0471_C0483.csv"
    )


# ── safe asset IDs ───────────────────────────────────────────────────
def test_generated_asset_ids_are_valid_and_unique():
    ids = {new_asset_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(is_valid_asset_id(i) for i in ids)


@pytest.mark.parametrize("bad", [
    "", "..", "../x", "a/b", "/etc", ".hidden", None, 7,
    "0" * 31, "0" * 33, "A" * 32, "g" * 32,
    "0" * 31 + "/", "0" * 30 + "..", "0" * 31 + "\x00",
])
def test_invalid_asset_ids_never_touch_the_filesystem(tmp_path, bad):
    ws = _ws(tmp_path)
    assert not is_valid_asset_id(bad)
    with pytest.raises(WorkspacePermissionError):
        ws.asset_dir(bad)
    with pytest.raises(WorkspacePermissionError):
        ws.asset_file(bad, "asset.json")


def test_unknown_asset_is_not_found(tmp_path):
    ws = _ws(tmp_path)
    ws.ensure()
    with pytest.raises(AssetNotFoundError):
        ws.asset_dir(new_asset_id())


def test_listing_ignores_foreign_entries(tmp_path):
    ws = _ws(tmp_path)
    asset_id, _ = ws.create_asset()
    (ws.radar_root / "not-an-asset").mkdir()
    (ws.radar_root / ("f" * 32)).write_text("a file, not an asset")
    assert ws.list_asset_ids() == [asset_id]


# ── path traversal ───────────────────────────────────────────────────
@pytest.mark.parametrize("name", [
    "../asset.json", "../../x", "a/b.csv", "/etc/passwd", ".hidden",
    "", "..", "x\\y.csv", "x\x00.csv", "a" * 201,
])
def test_output_filenames_cannot_escape_outputs(tmp_path, name):
    ws = _ws(tmp_path)
    asset_id, _ = ws.create_asset()
    with pytest.raises(WorkspacePermissionError):
        ws.output_file(asset_id, name)


@pytest.mark.parametrize("name", ["outputs", "../asset.json", "other.json", ""])
def test_only_fixed_layout_files_are_addressable(tmp_path, name):
    ws = _ws(tmp_path)
    asset_id, _ = ws.create_asset()
    with pytest.raises(WorkspacePermissionError):
        ws.asset_file(asset_id, name)


def test_contain_rejects_paths_outside_the_workspace(tmp_path):
    ws = _ws(tmp_path)
    ws.ensure()
    for outside in (
        tmp_path,
        ws.root.parent,                       # <owner_root> itself
        ws.root / ".." / "examples",
        Path("/etc/passwd"),
    ):
        with pytest.raises(WorkspacePermissionError):
            ws.contain(outside)
    assert ws.contain(ws.radar_root / "x") == ws.radar_root / "x"


def test_symlink_escapes_are_rejected(tmp_path):
    a, b = _ws(tmp_path, _A), _ws(tmp_path, _B)
    a_id, a_path = a.create_asset()
    b_id, b_path = b.create_asset()
    (b_path / "outputs" / "secret.csv").write_text("b's data")

    # an output that is a link into another user's workspace
    (a_path / "outputs" / "link.csv").symlink_to(b_path / "outputs" / "secret.csv")
    with pytest.raises(WorkspacePermissionError):
        a.output_file(a_id, "link.csv")

    # an asset directory that is a link to another user's asset
    os.symlink(b_path, a.radar_root / b_id)
    with pytest.raises(WorkspacePermissionError):
        a.asset_dir(b_id)
    assert b_id not in a.list_asset_ids()


# ── cross-user isolation ─────────────────────────────────────────────
def test_users_never_see_each_others_assets(tmp_path):
    a, b = _ws(tmp_path, _A), _ws(tmp_path, _B)
    a_id, _ = a.create_asset()
    b_id, _ = b.create_asset()

    assert a.root != b.root
    assert not a.root.is_relative_to(b.root) and not b.root.is_relative_to(a.root)
    assert a.list_asset_ids() == [a_id]
    assert b.list_asset_ids() == [b_id]

    with pytest.raises(AssetNotFoundError):
        a.asset_dir(b_id)
    with pytest.raises(AssetNotFoundError):
        b.asset_file(a_id, "session.json")
    with pytest.raises(WorkspacePermissionError):
        a.contain(b.radar_root / b_id)
