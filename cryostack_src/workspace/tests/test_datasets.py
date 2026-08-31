"""Reusable user datasets under <owner_root>/datasets/ -- upload/list/delete/isolate."""
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


def _mgr(owner, root):
    return WorkspaceManager(
        owner=owner, workspace_root=root, status={}, session={"id": "s"},
        example_dir=_Widget(str(root)), model=_Widget("issm"), backend=_Widget("c"),
        file_picker=_Widget(), file_editor=_Widget(), log_output=None, results_output=None,
        cluster_host=_Widget(""), cluster_user=_Widget(""), cluster_port=_Widget(1),
        access_mode=_Widget(""), normalize_remote_path=lambda p: p,
        connector_fetch_archive=None, should_use_connector=lambda: False,
        connector_ssh=None, ssh_run=None, cluster_name=_Widget(""),
    )


def _u(name, content=b"x"):
    return {"name": name, "content": content}


# ── upload ──────────────────────────────────────────────────────────────
def test_upload_multiple_no_extension_restriction(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    res = m.save_datasets((_u("mesh.exp"), _u("obs.nc"), _u("run.mat"),
                           _u("t.csv"), _u("weird.xyz")))
    assert set(res["saved"]) == {"mesh.exp", "obs.nc", "run.mat", "t.csv", "weird.xyz"}
    assert {d["name"] for d in m.list_datasets()} == set(res["saved"])


def test_traversal_and_absolute_names_rejected(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    res = m.save_datasets((_u("../../evil.mat"), _u("a/b.nc"), _u("/etc/passwd"),
                           _u(".hidden"), _u("ok.nc")))
    assert res["saved"] == ["ok.nc"]
    assert len(res["errors"]) == 4
    assert not (tmp_path / "evil.mat").exists()


def test_overwrite_requires_explicit_flag(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    m.save_datasets((_u("obs.nc", b"v1"),))
    r2 = m.save_datasets((_u("obs.nc", b"v2"),))
    assert r2["skipped"] == ["obs.nc"]
    assert m._resolve_dataset("obs.nc").read_bytes() == b"v1"
    r3 = m.save_datasets((_u("obs.nc", b"v2"),), overwrite=True)
    assert r3["saved"] == ["obs.nc"]
    assert m._resolve_dataset("obs.nc").read_bytes() == b"v2"


def test_oversize_upload_rejected_with_clear_message(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    res = m.save_datasets((_u("big.dat", b"x" * (m.MAX_DATASET_UPLOAD_BYTES + 1)),))
    assert res["saved"] == []
    assert "exceeds" in res["errors"][0] and "limit" in res["errors"][0]


# ── visibility: data files visible, only text is editable ───────────────
def test_binary_scientific_files_visible_but_not_text_editable(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    m.save_datasets((_u("field.h5"), _u("notes.txt")))
    listing = {d["name"]: d["editable"] for d in m.list_datasets()}
    assert set(listing) == {"field.h5", "notes.txt"}     # both visible
    assert listing["field.h5"] is False                  # binary -> not editable
    assert listing["notes.txt"] is True


# ── delete ──────────────────────────────────────────────────────────────
def test_delete_removes_only_the_selected_dataset(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    m.save_datasets((_u("a.nc"), _u("b.nc"), _u("c.nc")))
    removed = m.delete_dataset("b.nc")
    assert not removed.exists()
    assert {d["name"] for d in m.list_datasets()} == {"a.nc", "c.nc"}


def test_delete_missing_dataset_raises(tmp_path):
    m = _mgr(USER_A, tmp_path / "ws")
    with pytest.raises(FileNotFoundError):
        m.delete_dataset("nope.nc")
    with pytest.raises((ValueError, WorkspacePermissionError)):
        m.delete_dataset("../../etc/passwd")


# ── persistence + isolation ────────────────────────────────────────────
def test_datasets_survive_reload(tmp_path):
    root = tmp_path / "ws"
    _mgr(USER_A, root).save_datasets((_u("obs.nc"), _u("mesh.exp")))
    m2 = _mgr(USER_A, root)
    assert {d["name"] for d in m2.list_datasets()} == {"obs.nc", "mesh.exp"}


def test_user_b_cannot_discover_read_or_delete_user_a_dataset(tmp_path):
    root = tmp_path / "shared"
    a = _mgr(USER_A, root)
    b = _mgr(USER_B, root)
    a.save_datasets((_u("private.nc", b"secret"),))

    assert b.list_datasets() == []
    with pytest.raises(FileNotFoundError):
        b.delete_dataset("private.nc")
    a_ds = a._resolve_dataset("private.nc")
    with pytest.raises(WorkspacePermissionError):
        b.read_text_file(a_ds)


# ── references + run staging ───────────────────────────────────────────
def test_reference_then_stage_copies_only_referenced_data(tmp_path):
    canon = tmp_path / "shipped" / "SquareIceShelf"
    canon.mkdir(parents=True)
    (canon / "runme.m").write_text("md=solve(md,'Stressbalance');\n")
    m = _mgr(USER_A, tmp_path / "ws")
    m.save_datasets((_u("obs.nc", b"NC"), _u("unused.mat", b"XX")))
    ex = m.clone_example_to_workspace(source=canon, model="issm", name="ex")
    m.reference_dataset(example_path=str(ex), dataset_name="obs.nc", as_path="data/obs.nc")

    staged = m.stage_example_for_run(source_example=str(ex))
    assert (staged.path / "data" / "data" / "obs.nc").read_bytes() == b"NC"
    assert not (staged.path / "data" / "unused.mat").exists()
    assert m.examples_referencing_dataset("obs.nc") == ["ex"]


def test_deleting_referenced_dataset_is_reported(tmp_path):
    canon = tmp_path / "shipped" / "SquareIceShelf"
    canon.mkdir(parents=True)
    (canon / "runme.m").write_text("x\n")
    m = _mgr(USER_A, tmp_path / "ws")
    m.save_datasets((_u("obs.nc"),))
    ex = m.clone_example_to_workspace(source=canon, model="issm", name="ex")
    m.reference_dataset(example_path=str(ex), dataset_name="obs.nc")
    assert "ex" in m.list_datasets()[0]["referenced_by"]
    m.delete_dataset("obs.nc")                             # allowed; caller warns
    assert m.list_datasets() == []
