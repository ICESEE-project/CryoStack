"""CryoLauncher Advanced-mode workspace editor -- a generic, model-neutral facility.

It edits an arbitrary example/workspace tree. It has no ISSM (or any model)
assumptions: model-specific behaviour lives in the model adapters, not here.

Contract:

* application-shipped (canonical) examples are **read-only**. Opening a file
  from one shows it disabled, and the user is directed to *Clone to My
  Workspace*; the resulting copy under ``<owner_root>/examples/<model>/<name>``
  is fully user-owned.
* every write / create / delete goes through :class:`WorkspaceManager`, which
  enforces containment against the authenticated user's root -- never against a
  dropdown-supplied path.
* unsaved work is never silently destroyed: switching file / example / model /
  Basic<->Advanced is vetoed while the buffer is dirty, unless the user ticks
  *Discard unsaved changes*.
* ``.ipynb`` files are shown **read-only** (raw JSON). They are never silently
  rewritten as ``.py``.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

import ipywidgets as W

from cryostack_src.workspace.manager import WorkspaceManager, WorkspacePermissionError

_READONLY_NOTE = (
    "Read-only — this is an application example. Use "
    "<b>Clone to My Workspace</b> to make an editable copy."
)
_NOTEBOOK_NOTE = "Notebook shown read-only in this phase (raw JSON)."


@dataclass
class EditorPanel:
    container: W.VBox
    controller: "EditorController"


class EditorController:
    def __init__(
        self,
        *,
        manager: WorkspaceManager,
        model_value,
        example_dir_widget,
        log_output,
        file_picker: W.Dropdown,
        editor: W.Textarea,
        status: W.HTML,
        name_field: W.Text,
        discard_toggle: W.Checkbox,
        confirm_delete: W.Checkbox,
        buttons: dict,
        on_files_changed=None,
        on_clone_created=None,
        on_examples_changed=None,
        example_template=None,
        confirm_example_delete: W.Checkbox | None = None,
    ) -> None:
        self.m = manager
        self._model_value = model_value
        self._example_dir = example_dir_widget
        self._log = log_output
        self._on_examples_changed = on_examples_changed
        self._example_template = example_template or (lambda: None)
        self._confirm_example_delete = confirm_example_delete
        self.file_picker = file_picker
        self.editor = editor
        self.status = status
        self.name_field = name_field
        self.discard_toggle = discard_toggle
        self.confirm_delete = confirm_delete
        self.buttons = buttons
        self._on_files_changed = on_files_changed
        self._on_clone_created = on_clone_created

        self._loaded_path: str | None = None
        self._clean_text: str = ""
        self._readonly: bool = True
        self._is_notebook: bool = False
        self._suppress: bool = False

        file_picker.observe(self._on_pick, names="value")
        editor.observe(lambda _c: self._render(), names="value")
        discard_toggle.observe(lambda _c: self._render(), names="value")
        buttons["save"].on_click(self.save)
        buttons["save_as"].on_click(self.save_as)
        buttons["new"].on_click(self.create)
        buttons["delete"].on_click(self.delete)
        buttons["refresh"].on_click(lambda _b: self.refresh())
        buttons["clone"].on_click(self.clone_example)
        if "new_example" in buttons:
            buttons["new_example"].on_click(self.new_example)
        if "rename_example" in buttons:
            buttons["rename_example"].on_click(self.rename_example)
        if "delete_example" in buttons:
            buttons["delete_example"].on_click(self.delete_example)

    # ── state ────────────────────────────────────────────────────────────
    @property
    def dirty(self) -> bool:
        return (
            self._loaded_path is not None
            and not self._readonly
            and self.editor.value != self._clean_text
        )

    def current_example_is_user_owned(self) -> bool:
        return self.m.is_user_owned(self._example_dir.value)

    def _print(self, *parts) -> None:
        if self._log is not None:
            with self._log:
                print(*parts)

    # ── guards ───────────────────────────────────────────────────────────
    def guard_context_switch(self) -> bool:
        """Return True when it is safe to switch example / model / mode."""
        if not self.dirty or self.discard_toggle.value:
            self.discard_toggle.value = False
            return True
        self._print(
            f"[editor] Unsaved changes in {Path(self._loaded_path).name}. "
            "Save, Save As, or tick 'Discard unsaved changes' first."
        )
        return False

    # ── file list ────────────────────────────────────────────────────────
    def refresh(self) -> None:
        example = (self._example_dir.value or "").strip()
        files = self.m.list_editable_files(example) if example else []
        prev_value = self.file_picker.value
        prev_name = Path(self._loaded_path).name if self._loaded_path else None
        self._suppress = True
        try:
            self.file_picker.options = files or [("(no editable files found)", "")]
            values = [v for _l, v in self.file_picker.options]
            if prev_value in values:
                chosen = prev_value
            elif prev_name and any(Path(v).name == prev_name for v in values if v):
                chosen = next(v for v in values if v and Path(v).name == prev_name)
            else:
                chosen = values[0]
            self.file_picker.value = chosen
        finally:
            self._suppress = False
        self._load(self.file_picker.value)

    # ── open ─────────────────────────────────────────────────────────────
    def _on_pick(self, change) -> None:
        if self._suppress:
            return
        if self.dirty and not self.discard_toggle.value:
            self._print(
                f"[editor] Unsaved changes in {Path(self._loaded_path).name}. "
                "Save, Save As, or tick 'Discard unsaved changes' to switch file."
            )
            self._suppress = True
            self.file_picker.value = self._loaded_path
            self._suppress = False
            return
        self._load(change["new"])

    def _load(self, path: str | None) -> None:
        self.discard_toggle.value = False
        if not path:
            self._loaded_path, self._clean_text = None, ""
            self._readonly, self._is_notebook = True, False
            self._set_editor("", disabled=True)
            self._render()
            return

        p = Path(path)
        self._is_notebook = p.suffix.lower() == ".ipynb"
        user_owned = self.m.is_user_owned(path)
        self._readonly = self._is_notebook or not user_owned
        try:
            text = self.m.read_text_file(path)
        except FileNotFoundError:
            text = ""
        except (WorkspacePermissionError, UnicodeDecodeError, OSError) as err:
            text = f"[cannot open this file: {type(err).__name__}: {err}]"
            self._readonly = True

        self._loaded_path = path
        self._set_editor(text, disabled=self._readonly)
        self._clean_text = text
        self._render()

    def _set_editor(self, text: str, *, disabled: bool) -> None:
        self._suppress = True
        try:
            self.editor.value = text
            self.editor.disabled = disabled
        finally:
            self._suppress = False

    # ── write actions ────────────────────────────────────────────────────
    def save(self, _=None) -> None:
        if not self._loaded_path or self._readonly:
            self._print("[editor] This file is read-only. Clone the example to your "
                        "workspace, or use Save As into a workspace example.")
            return
        try:
            saved = self.m.save_text_file(self._loaded_path, self.editor.value)
        except (WorkspacePermissionError, FileNotFoundError, OSError) as err:
            self._print("[editor][ERROR]", type(err).__name__, err)
            return
        self._clean_text = self.editor.value
        self.discard_toggle.value = False
        self._print(f"[editor] Saved {saved}")
        self._render()

    def _target_dir_for_new_file(self) -> Path | None:
        if self._loaded_path and self.m.is_user_owned(self._loaded_path):
            return Path(self._loaded_path).parent
        if self.current_example_is_user_owned():
            return Path(self._example_dir.value)
        return None

    def save_as(self, _=None) -> None:
        directory = self._target_dir_for_new_file()
        if directory is None:
            self._print("[editor] Save As needs a workspace example. Use "
                        "'Clone to My Workspace' first.")
            return
        self._create_file(directory, self.name_field.value, self.editor.value, "Saved as")

    def create(self, _=None) -> None:
        directory = self._target_dir_for_new_file()
        if directory is None:
            self._print("[editor] New file needs a workspace example. Use "
                        "'Clone to My Workspace' first.")
            return
        self._create_file(directory, self.name_field.value, "", "Created")

    def _create_file(self, directory: Path, name: str, text: str, verb: str) -> None:
        try:
            created = self.m.create_text_file(directory, name, text)
        except (ValueError, FileExistsError, WorkspacePermissionError,
                FileNotFoundError, OSError) as err:
            self._print("[editor][ERROR]", type(err).__name__, err)
            return
        self._print(f"[editor] {verb} {created}")
        self.name_field.value = ""
        self._notify_files_changed()
        self.refresh()
        if str(created) in [v for _l, v in self.file_picker.options]:
            self.file_picker.value = str(created)

    def delete(self, _=None) -> None:
        if not self._loaded_path:
            return
        if not self.m.is_user_owned(self._loaded_path):
            self._print("[editor] Application example files cannot be deleted.")
            return
        if not self.confirm_delete.value:
            self._print(f"[editor] Tick 'Confirm delete' to remove "
                        f"{Path(self._loaded_path).name}.")
            return
        try:
            removed = self.m.delete_user_file(self._loaded_path)
        except (WorkspacePermissionError, FileNotFoundError, OSError) as err:
            self._print("[editor][ERROR]", type(err).__name__, err)
            return
        self.confirm_delete.value = False
        self._loaded_path, self._clean_text = None, ""
        self._print(f"[editor] Deleted {removed}")
        self._notify_files_changed()
        self.refresh()

    def clone_example(self, _=None) -> None:
        source = (self._example_dir.value or "").strip()
        if not source:
            self._print("[editor] Select an example first.")
            return
        if self.m.is_user_owned(source):
            self._print("[editor] This example is already in your workspace.")
            return
        try:
            dest = self.m.clone_example_to_workspace(
                source=source, model=self._model_value(),
                name=(self.name_field.value.strip() or None),
            )
        except (ValueError, FileExistsError, WorkspacePermissionError, OSError) as err:
            self._print("[editor][ERROR]", type(err).__name__, err)
            return
        self.name_field.value = ""
        self._print(f"[editor] Cloned to your workspace: {dest}")
        if self._on_clone_created is not None:
            self._on_clone_created(dest)

    # ── user example lifecycle ───────────────────────────────────────────
    def _current_user_example_name(self) -> str | None:
        ex = (self._example_dir.value or "").strip()
        return Path(ex).name if ex and self.m.is_user_owned(ex) else None

    def new_example(self, _=None) -> None:
        name = self.name_field.value.strip()
        try:
            dest = self.m.create_user_example(
                model=self._model_value(), name=name, template=self._example_template(),
            )
        except Exception as err:  # noqa: BLE001 - surfaced to the user log
            self._print("[editor][ERROR]", type(err).__name__, err)
            return
        self.name_field.value = ""
        self._print(f"[editor] Created workspace example: {dest}")
        if self._on_examples_changed is not None:
            self._on_examples_changed("created", dest)

    def rename_example(self, _=None) -> None:
        old = self._current_user_example_name()
        if old is None:
            self._print("[editor] Only your own workspace examples can be renamed.")
            return
        if not self.guard_context_switch():
            return
        new = self.name_field.value.strip()
        try:
            dest = self.m.rename_user_example(model=self._model_value(), old=old, new=new)
        except Exception as err:  # noqa: BLE001 - surfaced to the user log
            self._print("[editor][ERROR]", type(err).__name__, err)
            return
        self.name_field.value = ""
        self._print(f"[editor] Renamed to: {dest}")
        if self._on_examples_changed is not None:
            self._on_examples_changed("renamed", dest)

    def delete_example(self, _=None) -> None:
        name = self._current_user_example_name()
        if name is None:
            self._print("[editor] Only your own workspace examples can be deleted.")
            return
        # deleting the example discards its buffer anyway; still require an
        # explicit discard so it is never silent
        if self.dirty and not self.discard_toggle.value:
            self._print("[editor] Unsaved changes — save, or tick 'Discard unsaved "
                        "changes', before deleting the example.")
            return
        self.discard_toggle.value = False
        if self._confirm_example_delete is None or not self._confirm_example_delete.value:
            self._print(f"[editor] Tick 'Confirm delete example' to remove {name}.")
            return
        try:
            removed = self.m.delete_user_example(model=self._model_value(), name=name)
        except Exception as err:  # noqa: BLE001 - surfaced to the user log
            self._print("[editor][ERROR]", type(err).__name__, err)
            return
        self._confirm_example_delete.value = False
        self._loaded_path, self._clean_text = None, ""
        self._print(f"[editor] Deleted workspace example: {removed}")
        if self._on_examples_changed is not None:
            self._on_examples_changed("deleted", None)

    def _notify_files_changed(self) -> None:
        if self._on_files_changed is not None:
            try:
                self._on_files_changed()
            except Exception:  # a run-target refresh must not break the editor
                pass

    # ── rendering ────────────────────────────────────────────────────────
    def _render(self, *_a) -> None:
        b = self.buttons
        editable = self._loaded_path is not None and not self._readonly
        user_example = self.current_example_is_user_owned()

        b["save"].disabled = not editable
        b["delete"].disabled = not (self._loaded_path and self.m.is_user_owned(self._loaded_path))
        b["save_as"].disabled = not (user_example or (
            self._loaded_path and self.m.is_user_owned(self._loaded_path)))
        b["new"].disabled = b["save_as"].disabled
        b["clone"].disabled = user_example or not (self._example_dir.value or "").strip()
        if "rename_example" in b:
            b["rename_example"].disabled = not user_example
            b["delete_example"].disabled = not user_example
        if self._confirm_example_delete is not None:
            self._confirm_example_delete.layout.display = "" if user_example else "none"

        self.discard_toggle.layout.display = "" if self.dirty else "none"
        self.confirm_delete.layout.display = "" if not b["delete"].disabled else "none"

        if self._loaded_path is None:
            self.status.value = "<span class='icesee-subtle'>No file open.</span>"
            return
        name = html.escape(Path(self._loaded_path).name)
        if self.dirty:
            tag = "<span style='color:#9a6700;font-weight:600;'>● unsaved</span>"
        elif self._is_notebook:
            tag = f"<span class='icesee-subtle'>{_NOTEBOOK_NOTE}</span>"
        elif self._readonly:
            tag = f"<span class='icesee-subtle'>{_READONLY_NOTE}</span>"
        else:
            tag = "<span style='color:#1a7f37;'>saved</span>"
        lines = self.editor.value.count("\n") + 1
        self.status.value = (
            f"<div><b>{name}</b> &nbsp;<span class='icesee-subtle'>{lines} lines</span> "
            f"&nbsp;{tag}</div>"
        )


def build_editor_panel(
    *,
    manager: WorkspaceManager,
    model_value,
    example_dir_widget,
    log_output,
    on_files_changed=None,
    on_clone_created=None,
    on_examples_changed=None,
    example_template=None,
) -> EditorPanel:
    file_picker = W.Dropdown(options=[("(no editable files found)", "")],
                             layout=W.Layout(width="100%"))
    editor = W.Textarea(value="", layout=W.Layout(width="100%", height="320px"))
    status = W.HTML()
    name_field = W.Text(placeholder="name for new / rename / save-as / clone",
                        layout=W.Layout(width="260px"))
    discard_toggle = W.Checkbox(value=False, description="Discard unsaved changes",
                                indent=False, layout=W.Layout(display="none"))
    confirm_delete = W.Checkbox(value=False, description="Confirm delete",
                                indent=False, layout=W.Layout(display="none"))
    confirm_example_delete = W.Checkbox(value=False, description="Confirm delete example",
                                        indent=False, layout=W.Layout(display="none"))

    def _btn(desc, icon, style=""):
        return W.Button(description=desc, icon=icon, button_style=style,
                        layout=W.Layout(width="auto"))

    buttons = {
        "save": _btn("Save", "save", "primary"),
        "save_as": _btn("Save As", "copy"),
        "new": _btn("New file", "file"),
        "delete": _btn("Delete", "trash", "danger"),
        "refresh": _btn("Refresh", "refresh"),
        "clone": _btn("Clone to My Workspace", "cloud-download", "info"),
        "new_example": _btn("New example", "folder-open", "info"),
        "rename_example": _btn("Rename example", "pencil"),
        "delete_example": _btn("Delete example", "trash", "danger"),
    }

    controller = EditorController(
        manager=manager, model_value=model_value, example_dir_widget=example_dir_widget,
        log_output=log_output, file_picker=file_picker, editor=editor, status=status,
        name_field=name_field, discard_toggle=discard_toggle,
        confirm_delete=confirm_delete, buttons=buttons,
        on_files_changed=on_files_changed, on_clone_created=on_clone_created,
        on_examples_changed=on_examples_changed, example_template=example_template,
        confirm_example_delete=confirm_example_delete,
    )

    container = W.VBox(
        [
            W.HBox([buttons["new_example"], buttons["clone"],
                    buttons["rename_example"], buttons["delete_example"],
                    confirm_example_delete],
                   layout=W.Layout(gap="6px", align_items="center", flex_wrap="wrap")),
            W.HBox([W.HTML("<div class='icesee-lbl'>File:</div>",
                           layout=W.Layout(width="90px", min_width="90px")),
                    file_picker, buttons["refresh"]],
                   layout=W.Layout(align_items="center", gap="8px")),
            status,
            editor,
            W.HBox([buttons["save"], buttons["save_as"], buttons["new"],
                    buttons["delete"]],
                   layout=W.Layout(gap="6px", flex_wrap="wrap")),
            W.HBox([name_field, discard_toggle, confirm_delete],
                   layout=W.Layout(gap="12px", align_items="center", flex_wrap="wrap")),
        ],
        layout=W.Layout(width="100%", gap="8px"),
    )
    controller._render()
    return EditorPanel(container=container, controller=controller)
