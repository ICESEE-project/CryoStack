"""Generic, model-neutral file operations: containment is enforced by WorkspaceManager."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from cryostack_src.workspace import WorkspaceManager, WorkspaceUser
from cryostack_src.workspace.manager import WorkspacePermissionError

USER_A = WorkspaceUser(user_id="user-A", source="cryostack-auth")
USER_B = WorkspaceUser(user_id="user-B", source="cryostack-auth")


class _Widget:
    def __init__(self, value=None):
        self.value = value
        self.options = ()


def _mgr(owner, root, example_dir):
    return WorkspaceManager(
        owner=owner, workspace_root=root, status={}, session={"id": "s"},
        example_dir=_Widget(str(example_dir)), model=_Widget("issm"), backend=_Widget("c"),
        file_picker=_Widget(), file_editor=_Widget(), log_output=None, results_output=None,
        cluster_host=_Widget(""), cluster_user=_Widget(""), cluster_port=_Widget(1),
        access_mode=_Widget(""), normalize_remote_path=lambda p: p,
        connector_fetch_archive=None, should_use_connector=lambda: False,
        connector_ssh=None, ssh_run=None, cluster_name=_Widget(""),
    )


@pytest.fixture
def canonical(tmp_path):
    ex = tmp_path / "shipped" / "SquareIceShelf"
    ex.mkdir(parents=True)
    (ex / "runme.m").write_text("md=solve(md,'Stressbalance');\n")
    (ex / "notebook.ipynb").write_text('{"cells": []}')
    return ex


# ── containment ────────────────────────────────────────────────────────────
def test_write_outside_workspace_is_refused(tmp_path, canonical):
    m = _mgr(USER_A, tmp_path / "ws", canonical)
    with pytest.raises(WorkspacePermissionError):
        m.save_text_file(canonical / "runme.m", "hacked")        # canonical
    with pytest.raises(WorkspacePermissionError):
        m.save_text_file("/etc/cryostack_pwn", "x")               # absolute escape


def test_delete_outside_workspace_is_refused(tmp_path, canonical):
    m = _mgr(USER_A, tmp_path / "ws", canonical)
    with pytest.raises(WorkspacePermissionError):
        m.delete_user_file(canonical / "runme.m")


def test_path_traversal_in_name_is_rejected(tmp_path, canonical):
    m = _mgr(USER_A, tmp_path / "ws", canonical)
    d = m.clone_example_to_workspace(source=canonical, model="issm")
    for bad in ("../evil", "a/b", "..", ".", "has space", "/abs"):
        with pytest.raises((ValueError, WorkspacePermissionError)):
            m.create_text_file(d, bad, "x")


def test_read_is_scoped_to_workspace_or_current_example(tmp_path, canonical):
    m = _mgr(USER_A, tmp_path / "ws", canonical)
    assert "solve" in m.read_text_file(canonical / "runme.m")     # current example: ok
    outside = tmp_path / "secret.txt"
    outside.write_text("nope")
    with pytest.raises(WorkspacePermissionError):
        m.read_text_file(outside)


def test_oversized_file_is_not_loaded(tmp_path, canonical):
    m = _mgr(USER_A, tmp_path / "ws", canonical)
    big = canonical / "big.txt"
    big.write_text("x" * (m.MAX_EDITABLE_BYTES + 1))
    with pytest.raises(WorkspacePermissionError):
        m.read_text_file(big)


# ── user-owned lifecycle ──────────────────────────────────────────────────
def test_clone_creates_user_owned_copy_with_provenance(tmp_path, canonical):
    m = _mgr(USER_A, tmp_path / "ws", canonical)
    dest = m.clone_example_to_workspace(source=canonical, model="ISSM", name="mine")
    assert dest == (m._owner_root / "examples" / "issm" / "mine").resolve()
    assert m.is_user_owned(dest / "runme.m")
    prov = dest / ".cryostack-example.json"
    assert prov.is_file()
    assert (canonical / "runme.m").read_text() == "md=solve(md,'Stressbalance');\n"  # source intact


def test_clone_refuses_to_overwrite_existing_workspace_example(tmp_path, canonical):
    m = _mgr(USER_A, tmp_path / "ws", canonical)
    m.clone_example_to_workspace(source=canonical, model="issm", name="dup")
    with pytest.raises(FileExistsError):
        m.clone_example_to_workspace(source=canonical, model="issm", name="dup")


def test_edit_create_delete_within_a_workspace_example(tmp_path, canonical):
    m = _mgr(USER_A, tmp_path / "ws", canonical)
    d = m.clone_example_to_workspace(source=canonical, model="issm")
    m.save_text_file(d / "runme.m", "new body\n")
    assert (d / "runme.m").read_text() == "new body\n"
    created = m.create_text_file(d, "notes.txt", "hello")
    assert created.read_text() == "hello"
    with pytest.raises(FileExistsError):
        m.create_text_file(d, "notes.txt", "again")
    m.delete_user_file(created)
    assert not created.exists()


# ── isolation ─────────────────────────────────────────────────────────────
def test_one_user_cannot_write_or_delete_another_users_files(tmp_path, canonical):
    root = tmp_path / "shared"
    a = _mgr(USER_A, root, canonical)
    b = _mgr(USER_B, root, canonical)
    a_example = a.clone_example_to_workspace(source=canonical, model="issm", name="ada")
    a_file = a_example / "runme.m"

    with pytest.raises(WorkspacePermissionError):
        b.save_text_file(a_file, "stolen")
    with pytest.raises(WorkspacePermissionError):
        b.delete_user_file(a_file)
    assert b.is_user_owned(a_file) is False
    with pytest.raises(WorkspacePermissionError):
        b.read_text_file(a_file)                       # B's example root is elsewhere
