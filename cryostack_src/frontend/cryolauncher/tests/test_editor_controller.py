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


# ── Advanced-mode editor sizing (now hosted in the right Workspace panel,
#    which has more usable vertical space than the old left column -- so
#    substantially taller than the original 320px, responsive min-height
#    rather than an unconditional bare fixed height) ───────────────────────
def test_editor_textarea_is_substantially_taller_than_the_original_compressed_height(setup):
    _mgr, _ed, ctrl, _canon, _ = setup
    layout = ctrl.editor.layout
    # original height was 320px -- assert a real, substantial increase in a
    # sane band, not one brittle exact pixel value.
    height_px = int(str(layout.height).rstrip("px"))
    assert 560 <= height_px <= 1000
    # a responsive floor (min_height), not only a bare fixed height
    assert layout.min_height == layout.height


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


# ── open_file_by_name: steering the default file (Icepack run.py) ─────────
def test_open_file_by_name_switches_to_the_named_file(setup):
    _mgr, _ed, ctrl, canon, _ = setup
    ctrl.refresh()
    assert ctrl.open_file_by_name("runme.m") is True
    assert ctrl.file_picker.value.endswith("runme.m")
    assert "Stressbalance" in ctrl.editor.value


def test_open_file_by_name_is_a_noop_when_the_name_is_absent(setup):
    _mgr, _ed, ctrl, canon, _ = setup
    ctrl.refresh()
    before = ctrl.file_picker.value
    assert ctrl.open_file_by_name("run.py") is False   # this fixture has no run.py
    assert ctrl.file_picker.value == before


def test_open_file_by_name_empty_name_is_a_noop(setup):
    _mgr, _ed, ctrl, canon, _ = setup
    ctrl.refresh()
    before = ctrl.file_picker.value
    assert ctrl.open_file_by_name("") is False
    assert ctrl.file_picker.value == before


def test_open_file_by_name_already_active_is_a_harmless_noop(setup):
    _mgr, _ed, ctrl, canon, _ = setup
    ctrl.refresh()
    ctrl.open_file_by_name("runme.m")
    assert ctrl.open_file_by_name("runme.m") is True
    assert ctrl.file_picker.value.endswith("runme.m")


def test_open_file_by_name_respects_the_dirty_guard(setup):
    """It must never silently discard unsaved work -- same guard a manual
    dropdown pick already goes through."""
    mgr, example_dir, ctrl, canon, clones = setup
    ctrl.refresh(); ctrl.clone_example(); example_dir.value = str(clones[0]); ctrl.refresh()
    _select(ctrl, "runme.m")
    ctrl.editor.value = "dirty edit\n"
    assert ctrl.dirty

    assert ctrl.open_file_by_name("Square.par") is False
    assert ctrl.file_picker.value.endswith("runme.m")     # never switched
    assert ctrl.editor.value == "dirty edit\n"             # never discarded


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


def test_missing_example_name_is_visible_in_editor_without_opening_run_log(setup):
    _mgr, _ed, ctrl, _canon, _ = setup
    ctrl.new_example()
    assert 'role="alert"' in ctrl.feedback.value
    assert 'name' in ctrl.feedback.value.lower()
    assert 'Enter an example name' in ctrl.feedback.value
    assert '[editor]' not in ctrl.feedback.value


def test_unsaved_context_warning_is_visible_and_save_acknowledges_resolution(setup):
    _mgr, ed, ctrl, _canon, clones = setup
    ctrl.name_field.value = 'inline-feedback-case'
    ctrl.clone_example()
    ed.value = str(clones[0])
    ctrl.refresh()
    _select(ctrl, 'runme.m')
    ctrl.editor.value += '% my edit\n'
    assert ctrl.guard_context_switch() is False
    assert 'Unsaved changes' in ctrl.feedback.value
    ctrl.save()
    assert not ctrl.dirty
    assert 'Saved' in ctrl.feedback.value


def test_editor_feedback_escapes_untrusted_filename_text(setup):
    _mgr, _ed, ctrl, _canon, _ = setup
    ctrl._print('[editor][ERROR]', 'ValueError', 'Unsafe <script>alert(1)</script> name')
    assert '<script>' not in ctrl.feedback.value
    assert '&lt;script&gt;' in ctrl.feedback.value
    assert 'ValueError' not in ctrl.feedback.value


def _editable_working_copy(setup):
    mgr, ed, ctrl, _canon, clones = setup
    ctrl.name_field.value = 'unsaved-work-rehearsal'
    ctrl.clone_example()
    ed.value = str(clones[0])
    ctrl.refresh()
    _select(ctrl, 'runme.m')
    return mgr, ctrl, clones[0]


def test_manual_refresh_keeps_unsaved_script(setup):
    _mgr, ctrl, _root = _editable_working_copy(setup)
    edited = ctrl.editor.value + '% keep this unsaved work\n'
    ctrl.editor.value = edited
    ctrl.buttons['refresh'].click()
    assert ctrl.editor.value == edited
    assert ctrl.dirty
    assert 'Unsaved changes' in ctrl.feedback.value
    ctrl.discard_toggle.value = True
    ctrl.buttons['refresh'].click()
    assert not ctrl.dirty
    assert ctrl.feedback.value == ''


def test_new_file_does_not_discard_the_current_unsaved_script(setup):
    _mgr, ctrl, root = _editable_working_copy(setup)
    edited = ctrl.editor.value + '% unsaved\n';ctrl.editor.value = edited
    ctrl.name_field.value = 'second.py'
    ctrl.create()
    assert not (root/'second.py').exists()
    assert ctrl.editor.value == edited and ctrl.dirty


def test_new_example_requires_resolution_of_unsaved_work(setup):
    mgr, ctrl, _root = _editable_working_copy(setup)
    edited = ctrl.editor.value + '% unsaved\n';ctrl.editor.value = edited
    before = mgr.list_user_examples('issm')
    ctrl.name_field.value = 'should-not-be-created'
    ctrl.new_example()
    assert mgr.list_user_examples('issm') == before
    assert ctrl.editor.value == edited and ctrl.dirty


def test_quota_refusal_preserves_buffer_and_shows_actionable_feedback(setup, monkeypatch):
    from cryostack_src.workspace.storage_policy import QuotaExceeded
    mgr, ctrl, root = _editable_working_copy(setup)
    original = (root/'runme.m').read_text()
    ctrl.editor.value = original + '% unsaved additional data\n'
    def refused(*args, **kwargs):
        raise QuotaExceeded('Workspace growth is unavailable; ask the organizer.', None)
    monkeypatch.setattr(mgr, 'save_text_file', refused)
    ctrl.save()
    assert ctrl.dirty and (root/'runme.m').read_text() == original
    assert 'ask the organizer' in ctrl.feedback.value
    assert 'QuotaExceeded' not in ctrl.feedback.value


def test_missing_volume_on_clone_is_visible_in_editor(setup, monkeypatch):
    from cryostack_src.workspace.storage_mount import WorkspaceStorageUnavailable
    mgr, _ed, ctrl, _canon, _clones = setup
    def unavailable(*args, **kwargs):
        raise WorkspaceStorageUnavailable('Workspace storage is unavailable; retry later.')
    monkeypatch.setattr(mgr, 'clone_example_to_workspace', unavailable)
    ctrl.clone_example()
    assert 'storage is unavailable' in ctrl.feedback.value


def test_denied_stale_example_clears_editor_without_aborting(setup, monkeypatch):
    mgr, selected, ctrl, canon, _ = setup
    ctrl.refresh()
    assert ctrl._loaded_path
    monkeypatch.setenv("CRYOSTACK_CANONICAL_EXAMPLE_ROOTS", str(canon.parent / "other"))
    ctrl.refresh()
    assert ctrl._loaded_path is None
    assert ctrl.editor.value == ""
    assert ctrl.editor.disabled
    assert not any(value for _, value in ctrl.file_picker.options)
    from cryostack_src.workspace.manager import WorkspacePermissionError
    with pytest.raises(WorkspacePermissionError):
        mgr.list_editable_files(str(canon))


# Source-file import is a deliberate save action, never an execution action.
def _script_upload(name, content=b"print('hello')\n"):
    from datetime import datetime, timezone
    return {"name": name, "content": memoryview(content), "type": "text/plain",
            "size": len(content), "last_modified": datetime.now(timezone.utc)}


def _owned_editor(setup):
    mgr, example_dir, ctrl, canon, clones = setup
    ctrl.refresh()
    ctrl.clone_example()
    example_dir.value = str(clones[0])
    ctrl.refresh()
    ctrl.open_file_by_name("runme.m")
    return mgr, ctrl, clones[0]


def test_script_import_never_writes_an_application_example(setup):
    _mgr, _ed, ctrl, canon, _ = setup
    ctrl.refresh()
    assert ctrl.buttons['import_scripts'].disabled
    assert ctrl.script_uploader.disabled
    ctrl.script_uploader.value = (_script_upload('custom.py'),)
    ctrl.import_script_files()
    assert not (canon/'custom.py').exists()
    assert 'workspace example' in ctrl.feedback.value


def test_import_saves_utf8_helpers_and_refreshes_editor_without_executing(setup):
    _mgr, ctrl, example = _owned_editor(setup)
    ctrl.script_uploader.value = (
        _script_upload('custom.py', b"raise AssertionError('do not execute imports')\n"),
        _script_upload('helper.m', "% \u03b4 helper\n".encode('utf-8')),
    )
    ctrl.buttons['import_scripts'].click()
    assert (example/'custom.py').read_text().startswith('raise AssertionError')
    assert (example/'helper.m').read_text() == '% \u03b4 helper\n'
    assert ctrl.file_picker.value.endswith('custom.py')
    assert ctrl.script_uploader.value == ()
    assert not ctrl.dirty
    assert 'Set Run target' in ctrl.feedback.value


def test_import_requires_explicit_replacement_of_seeded_entry_file(setup):
    _mgr, ctrl, example = _owned_editor(setup)
    original = (example/'runme.m').read_text()
    ctrl.script_uploader.value = (_script_upload('runme.m', b'md=model();\n'),)
    ctrl.import_script_files()
    assert (example/'runme.m').read_text() == original
    assert 'Replace existing script files' in ctrl.feedback.value
    ctrl.replace_imports.value = True
    ctrl.import_script_files()
    assert (example/'runme.m').read_text() == 'md=model();\n'
    assert not ctrl.replace_imports.value


def test_import_preserves_unsaved_editor_text_and_selected_files(setup):
    _mgr, ctrl, example = _owned_editor(setup)
    ctrl.editor.value = 'unsaved personal work\n'
    ctrl.script_uploader.value = (_script_upload('custom.py'),)
    ctrl.import_script_files()
    assert ctrl.editor.value == 'unsaved personal work\n'
    assert not (example/'custom.py').exists()
    assert ctrl.script_uploader.value
    assert 'Unsaved changes' in ctrl.feedback.value


@pytest.mark.parametrize('name,content', [
    ('../escape.py', b'pass\n'),
    ('binary.py', b'\xff\x00'),
    ('mesh.nc', b'data'),
    ('notebook.ipynb', b'{"cells": []}'),
])
def test_invalid_script_import_batch_creates_nothing(setup, name, content):
    _mgr, ctrl, example = _owned_editor(setup)
    ctrl.script_uploader.value = (_script_upload('valid.py'), _script_upload(name, content))
    ctrl.import_script_files()
    assert not (example/'valid.py').exists()
    assert 'role="alert"' in ctrl.feedback.value


def test_import_cannot_follow_a_symlink_to_another_owned_example(setup):
    mgr, ctrl, example = _owned_editor(setup)
    other = mgr.create_user_example(model='issm', name='other-example')
    (other/'shared.py').write_text('original\n')
    (example/'shared.py').symlink_to(other/'shared.py')
    ctrl.script_uploader.value = (_script_upload('shared.py', b'replacement\n'),)
    ctrl.replace_imports.value = True
    ctrl.import_script_files()
    assert (other/'shared.py').read_text() == 'original\n'
    assert 'not a regular file in this example' in ctrl.feedback.value


def test_script_import_uses_editor_size_limit(setup, monkeypatch):
    mgr, ctrl, example = _owned_editor(setup)
    monkeypatch.setattr(mgr, 'MAX_EDITABLE_BYTES', 3)
    ctrl.script_uploader.value = (_script_upload('large.py', b'pass\n'),)
    ctrl.import_script_files()
    assert not (example/'large.py').exists()
    assert 'script import limit' in ctrl.feedback.value
