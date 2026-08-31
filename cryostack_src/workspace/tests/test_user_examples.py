"""User example lifecycle: persistent, per-user, canonical stays read-only."""
from __future__ import annotations

import json
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
    return ex


# ── clone / create / rename / delete ─────────────────────────────────────
def test_clone_provenance_has_required_fields(tmp_path, canonical):
    m = _mgr(USER_A, tmp_path / "ws", canonical)
    dest = m.clone_example_to_workspace(source=canonical, model="issm", name="mine")
    prov = json.loads((dest / ".cryostack-example.json").read_text())
    for key in ("model", "name", "owner", "created", "source", "source_name", "source_type"):
        assert key in prov
    assert prov["model"] == "issm"
    assert prov["source_type"] == "canonical-clone"
    assert prov["owner"] == USER_A.safe_id


def test_create_new_example_with_and_without_template(tmp_path, canonical):
    m = _mgr(USER_A, tmp_path / "ws", canonical)
    a = m.create_user_example(model="issm", name="empty")
    assert a.is_dir() and not any(p.name != ".cryostack-example.json" for p in a.iterdir())
    assert json.loads((a / ".cryostack-example.json").read_text())["source_type"] == "new-empty"

    b = m.create_user_example(model="issm", name="scaffold", template={"runme.m": "md=model();\n"})
    assert (b / "runme.m").read_text() == "md=model();\n"
    assert json.loads((b / ".cryostack-example.json").read_text())["source_type"] == "new-template"


def test_rename_updates_provenance_and_path(tmp_path, canonical):
    m = _mgr(USER_A, tmp_path / "ws", canonical)
    old = m.clone_example_to_workspace(source=canonical, model="issm", name="a")
    new = m.rename_user_example(model="issm", old="a", new="b")
    assert not old.exists() and new.name == "b"
    assert json.loads((new / ".cryostack-example.json").read_text())["name"] == "b"


def test_rename_and_create_reject_bad_names(tmp_path, canonical):
    m = _mgr(USER_A, tmp_path / "ws", canonical)
    m.clone_example_to_workspace(source=canonical, model="issm", name="a")
    for bad in ("../x", "a/b", "..", "has space"):
        with pytest.raises((ValueError, WorkspacePermissionError)):
            m.create_user_example(model="issm", name=bad)
        with pytest.raises((ValueError, WorkspacePermissionError)):
            m.rename_user_example(model="issm", old="a", new=bad)


# ── persistence across "reload" (fresh manager, same root) ────────────────
def test_clone_create_rename_survive_reload(tmp_path, canonical):
    root = tmp_path / "ws"
    m1 = _mgr(USER_A, root, canonical)
    m1.clone_example_to_workspace(source=canonical, model="issm", name="cloned")
    m1.create_user_example(model="issm", name="made")
    m1.rename_user_example(model="issm", old="made", new="made2")

    m2 = _mgr(USER_A, root, canonical)            # simulate page reload
    names = {e["name"] for e in m2.list_user_examples("issm")}
    assert names == {"cloned", "made2"}


def test_delete_removes_only_that_example(tmp_path, canonical):
    m = _mgr(USER_A, tmp_path / "ws", canonical)
    m.clone_example_to_workspace(source=canonical, model="issm", name="keep")
    m.clone_example_to_workspace(source=canonical, model="issm", name="drop")
    m.delete_user_example(model="issm", name="drop")
    assert {e["name"] for e in m.list_user_examples("issm")} == {"keep"}


# ── canonical examples are inviolable ────────────────────────────────────
def test_canonical_example_cannot_be_renamed_or_deleted(tmp_path, canonical):
    m = _mgr(USER_A, tmp_path / "ws", canonical)
    with pytest.raises((FileNotFoundError, WorkspacePermissionError, ValueError)):
        m.rename_user_example(model="issm", old="SquareIceShelf", new="x")
    with pytest.raises((FileNotFoundError, WorkspacePermissionError, ValueError)):
        m.delete_user_example(model="issm", name="SquareIceShelf")
    assert (canonical / "runme.m").exists()


# ── isolation ───────────────────────────────────────────────────────────
def test_user_b_cannot_see_or_touch_user_a_examples(tmp_path, canonical):
    root = tmp_path / "shared"
    a = _mgr(USER_A, root, canonical)
    b = _mgr(USER_B, root, canonical)
    a.clone_example_to_workspace(source=canonical, model="issm", name="ada")

    assert b.list_user_examples("issm") == []                 # discovery
    with pytest.raises((FileNotFoundError, WorkspacePermissionError)):
        b.rename_user_example(model="issm", old="ada", new="stolen")
    with pytest.raises((FileNotFoundError, WorkspacePermissionError)):
        b.delete_user_example(model="issm", name="ada")
    a_runme = a._user_example_dir("issm", "ada") / "runme.m"
    with pytest.raises(WorkspacePermissionError):
        b.save_text_file(a_runme, "x")


# ── deletion never crosses artifact boundaries ──────────────────────────
def test_delete_run_never_deletes_examples_or_datasets(tmp_path, canonical):
    from datetime import datetime
    from cryostack_src.workspace.models import RunInfo

    m = _mgr(USER_A, tmp_path / "ws", canonical)
    m.clone_example_to_workspace(source=canonical, model="issm", name="ex1")
    m.save_datasets(({"name": "keep.nc", "content": b"x"},))
    run = m.register_run(RunInfo(id="run-1", name="run-1", model="issm", backend="c",
                                 execution_mode="remote", status="completed",
                                 created=datetime.now(), jobid="j"))
    assert m.delete_run(run.id) is True
    assert {e["name"] for e in m.list_user_examples("issm")} == {"ex1"}
    assert [d["name"] for d in m.list_datasets()] == ["keep.nc"]


def test_delete_example_never_deletes_reusable_datasets(tmp_path, canonical):
    m = _mgr(USER_A, tmp_path / "ws", canonical)
    ex = m.clone_example_to_workspace(source=canonical, model="issm", name="ex")
    m.save_datasets(({"name": "obs.nc", "content": b"x"},))
    m.reference_dataset(example_path=str(ex), dataset_name="obs.nc")
    m.delete_user_example(model="issm", name="ex")
    assert [d["name"] for d in m.list_datasets()] == ["obs.nc"]     # dataset survives
