"""Advanced-mode editor: dirty state, unsaved-work guards, canonical read-only."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from cryostack_src.frontend.cryolauncher.workspace.editor import build_editor_panel
from cryostack_src.workspace import WorkspaceManager, WorkspaceUser

USER_A = WorkspaceUser(user_id="user-A", source="cryostack-auth")


class _Widget:
    def __init__(self, value=None):
        self.value = value
        self.options = ()


class _Log(list):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def clear_output(self):
        self.clear()


def _mgr(root, example_dir):
    return WorkspaceManager(
        owner=USER_A, workspace_root=root, status={}, session={"id": "s"},
        example_dir=example_dir, model=_Widget("issm"), backend=_Widget("c"),
        file_picker=_Widget(), file_editor=_Widget(), log_output=None, results_output=None,
        cluster_host=_Widget(""), cluster_user=_Widget(""), cluster_port=_Widget(1),
        access_mode=_Widget(""), normalize_remote_path=lambda p: p,
        connector_fetch_archive=None, should_use_connector=lambda: False,
        connector_ssh=None, ssh_run=None, cluster_name=_Widget(""),
    )


@pytest.fixture
def setup(tmp_path):
    canon = tmp_path / "shipped" / "SquareIceShelf"
    canon.mkdir(parents=True)
    (canon / "runme.m").write_text("md=solve(md,'Stressbalance');\n")
    (canon / "Square.par").write_text("% params\n")
    (canon / "note.ipynb").write_text('{"cells": [], "metadata": {}}')
    example_dir = _Widget(str(canon))
    mgr = _mgr(tmp_path / "ws", example_dir)
    clones: list[Path] = []
    changes: list[tuple] = []
    panel = build_editor_panel(
        manager=mgr, model_value=lambda: "issm", example_dir_widget=example_dir,
        log_output=_Log(), on_files_changed=lambda: None,
        on_clone_created=clones.append,
        on_examples_changed=lambda action, dest: changes.append((action, dest)),
        example_template=lambda: {"runme.m": "md = model();\n"},
    )
    panel.controller._changes = changes
    return mgr, example_dir, panel.controller, canon, clones


def _select(ctrl, label_or_abs):
    for label, value in ctrl.file_picker.options:
        if label == label_or_abs or value == label_or_abs:
            ctrl.file_picker.value = value
            return
    raise AssertionError(f"{label_or_abs} not in picker")


# ── canonical is read-only ────────────────────────────────────────────────
def test_canonical_file_opens_read_only(setup):
    _mgr, _ed, ctrl, canon, _ = setup
    ctrl.refresh()
    assert ctrl.editor.disabled is True
    assert ctrl._readonly is True
    ctrl.editor.value = "tampered"
    assert ctrl.dirty is False                       # canonical edits are not "dirty"
    ctrl.save()
    assert (canon / "runme.m").read_text() == "md=solve(md,'Stressbalance');\n"


def test_notebook_is_read_only_and_not_converted(setup):
    _mgr, _ed, ctrl, canon, _ = setup
    ctrl.refresh()
    _select(ctrl, "note.ipynb")
    assert ctrl.editor.disabled is True
    assert not (canon / "note.py").exists()          # never silently written as .py


# ── clone -> editable ─────────────────────────────────────────────────────
def test_clone_to_workspace_then_edit_and_save(setup):
    mgr, example_dir, ctrl, canon, clones = setup
    ctrl.refresh()
    _select(ctrl, "runme.m")
    ctrl.clone_example()
    assert clones and clones[0].is_dir()
    example_dir.value = str(clones[0])               # gateway would do this
    ctrl.refresh()
    assert ctrl.file_picker.value.endswith("runme.m")   # same file preserved across the clone
    assert ctrl.editor.disabled is False
    ctrl.editor.value = "md=solve(md,'Transient');\n"
    assert ctrl.dirty is True
    ctrl.save()
    assert ctrl.dirty is False
    assert (clones[0] / "runme.m").read_text() == "md=solve(md,'Transient');\n"


# ── unsaved-work guards ───────────────────────────────────────────────────
def test_switching_file_is_vetoed_while_dirty(setup):
    mgr, example_dir, ctrl, canon, clones = setup
    ctrl.refresh(); ctrl.clone_example(); example_dir.value = str(clones[0]); ctrl.refresh()
    _select(ctrl, "runme.m")
    ctrl.editor.value = "dirty edit\n"
    assert ctrl.dirty
    _select(ctrl, "Square.par")                      # attempt switch
    assert ctrl.file_picker.value.endswith("runme.m")   # reverted
    assert ctrl.editor.value == "dirty edit\n"           # preserved

    ctrl.discard_toggle.value = True
    _select(ctrl, "Square.par")
    assert ctrl.file_picker.value.endswith("Square.par")
    assert ctrl.discard_toggle.value is False            # reset after use


def test_context_switch_guard_blocks_then_allows_after_save(setup):
    mgr, example_dir, ctrl, canon, clones = setup
    ctrl.refresh(); ctrl.clone_example(); example_dir.value = str(clones[0]); ctrl.refresh()
    ctrl.editor.value = "unsaved\n"
    assert ctrl.guard_context_switch() is False
    ctrl.save()
    assert ctrl.guard_context_switch() is True


def test_context_switch_guard_allows_with_discard(setup):
    mgr, example_dir, ctrl, canon, clones = setup
    ctrl.refresh(); ctrl.clone_example(); example_dir.value = str(clones[0]); ctrl.refresh()
    ctrl.editor.value = "unsaved\n"
    ctrl.discard_toggle.value = True
    assert ctrl.guard_context_switch() is True
    assert ctrl.discard_toggle.value is False


# ── new / delete ──────────────────────────────────────────────────────────
def test_new_file_requires_a_workspace_example(setup):
    mgr, example_dir, ctrl, canon, clones = setup
    ctrl.refresh()
    ctrl.name_field.value = "scratch.m"
    ctrl.create()                                    # canonical example -> refused
    assert not (canon / "scratch.m").exists()


def test_new_and_delete_inside_workspace_example(setup):
    mgr, example_dir, ctrl, canon, clones = setup
    ctrl.refresh(); ctrl.clone_example(); example_dir.value = str(clones[0]); ctrl.refresh()
    ctrl.name_field.value = "scratch.m"
    ctrl.create()
    assert (clones[0] / "scratch.m").exists()
    _select(ctrl, "scratch.m")
    ctrl.delete()                                    # not confirmed
    assert (clones[0] / "scratch.m").exists()
    ctrl.confirm_delete.value = True
    ctrl.delete()
    assert not (clones[0] / "scratch.m").exists()


# ── user example management from the editor ───────────────────────────────
def test_new_example_creates_from_template_and_notifies(setup):
    mgr, example_dir, ctrl, canon, _ = setup
    ctrl.refresh()
    ctrl.name_field.value = "myrun"
    ctrl.new_example()
    dest = mgr.user_examples_root("issm") / "myrun"
    assert (dest / "runme.m").read_text() == "md = model();\n"
    assert ("created", dest) in ctrl._changes


def test_rename_and_delete_only_for_user_owned_examples(setup):
    mgr, example_dir, ctrl, canon, clones = setup
    ctrl.refresh()
    ctrl.rename_example()                       # canonical selected -> refused
    ctrl.delete_example()
    assert ctrl._changes == []

    ctrl.clone_example()
    example_dir.value = str(clones[0])
    ctrl.refresh()
    ctrl.name_field.value = "renamed"
    ctrl.rename_example()
    assert ("renamed", mgr.user_examples_root("issm") / "renamed") in ctrl._changes

    example_dir.value = str(mgr.user_examples_root("issm") / "renamed")
    ctrl.refresh()
    ctrl.delete_example()                       # not confirmed
    assert (mgr.user_examples_root("issm") / "renamed").exists()
    ctrl._confirm_example_delete.value = True
    ctrl.delete_example()
    assert not (mgr.user_examples_root("issm") / "renamed").exists()
    assert ("deleted", None) in ctrl._changes
