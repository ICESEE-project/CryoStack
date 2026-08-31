"""Merged discovery: canonical (read-only, filtered) + this user's examples."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from icesee_jupyter_book.core.icesheet_examples import merged_examples_for_model
from cryostack_src.models.issm.execution import example_runnable
from cryostack_src.workspace import WorkspaceManager, WorkspaceUser

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
def issm_tree(tmp_path):
    root = tmp_path / "ISSM"
    ex = root / "examples"
    for name in ("SquareIceShelf", "Greenland"):
        d = ex / name
        d.mkdir(parents=True)
        (d / "runme.m").write_text("md=solve(md,'Stressbalance');\n")
    for util in ("Data", "Mesh", "Functions"):        # utility dirs, no runme.m
        (ex / util).mkdir(parents=True)
    return root


def _canonical(model, issm_tree, **kw):
    return merged_examples_for_model(
        model, issm_root=str(issm_tree), runnable_check=example_runnable, **kw
    )


def test_non_runnable_utility_dirs_are_filtered(issm_tree):
    labels = {e.label for e in _canonical("issm", issm_tree)}
    assert "SquareIceShelf" in labels and "Greenland" in labels
    assert not ({"Data", "Mesh", "Functions"} & labels)


def test_canonical_examples_are_read_only(issm_tree):
    for e in _canonical("issm", issm_tree):
        assert e.owned is False and e.read_only is True


def test_user_examples_are_merged_and_tagged(tmp_path, issm_tree):
    canon = issm_tree / "examples" / "SquareIceShelf"
    m = _mgr(USER_A, tmp_path / "ws", canon)
    m.clone_example_to_workspace(source=canon, model="issm", name="mine")

    merged = _canonical("issm", issm_tree, user_examples=m.list_user_examples("issm"))
    mine = next(e for e in merged if e.path.name == "mine")
    assert mine.owned is True and mine.read_only is False and mine.runnable is True
    assert "mine" in mine.label


def test_new_empty_user_example_is_offered_but_not_runnable(tmp_path, issm_tree):
    canon = issm_tree / "examples" / "SquareIceShelf"
    m = _mgr(USER_A, tmp_path / "ws", canon)
    m.create_user_example(model="issm", name="blank")     # no runme.m
    merged = _canonical("issm", issm_tree, user_examples=m.list_user_examples("issm"))
    blank = next(e for e in merged if e.path.name == "blank")
    assert blank.owned is True and blank.runnable is False


def test_user_a_discovery_never_shows_user_b_examples(tmp_path, issm_tree):
    canon = issm_tree / "examples" / "SquareIceShelf"
    root = tmp_path / "shared"
    a = _mgr(USER_A, root, canon)
    b = _mgr(USER_B, root, canon)
    b.clone_example_to_workspace(source=canon, model="issm", name="bob-only")

    a_merged = _canonical("issm", issm_tree, user_examples=a.list_user_examples("issm"))
    assert not any(e.path.name == "bob-only" for e in a_merged)


def test_run_target_discovery_works_for_a_user_clone(tmp_path, issm_tree):
    canon = issm_tree / "examples" / "Greenland"
    m = _mgr(USER_A, tmp_path / "ws", canon)
    clone = m.clone_example_to_workspace(source=canon, model="issm", name="g2")
    files = [Path(v).name for _l, v in m.list_editable_files(str(clone))]
    assert "runme.m" in files
    assert example_runnable(clone) is True
