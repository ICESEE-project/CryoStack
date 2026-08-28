from __future__ import annotations

from pathlib import Path

import ipywidgets as W

from .tree import list_editable_files


def refresh_file_picker(*, example_dir, file_picker, file_editor) -> None:
    files = list_editable_files(example_dir.value.strip())
    if not files:
        file_picker.options = [("(no editable files found)", "")]
        file_picker.value = ""
        file_editor.value = ""
        return
    file_picker.options = files
    file_picker.value = files[0][1]


def load_selected_file(*, file_picker, file_editor) -> None:
    selected_file = file_picker.value or ""
    if not selected_file:
        file_editor.value = ""
        return
    path = Path(selected_file).expanduser()
    if not path.exists() or not path.is_file():
        file_editor.value = ""
        return
    try:
        if path.suffix.lower() == ".ipynb":
            python_path = path.with_suffix(".py")
            try:
                import nbformat
                from nbconvert import PythonExporter

                notebook = nbformat.read(str(path), as_version=4)
                source, _ = PythonExporter().from_notebook_node(notebook)
                python_path.write_text(source, encoding="utf-8")
                file_editor.value = source
                return
            except Exception as error:
                file_editor.value = (
                    "[ERROR] Could not convert notebook to Python script:\n"
                    f"{type(error).__name__}: {error}"
                )
                return
        file_editor.value = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        file_editor.value = "[Binary or non-text file cannot be displayed here.]"
    except Exception as error:
        file_editor.value = f"[ERROR] Could not read file: {type(error).__name__}: {error}"


def save_selected_file(*, file_picker, file_editor, log_output: W.Output) -> None:
    log_output.clear_output()
    selected_file = file_picker.value or ""
    if not selected_file:
        with log_output:
            print("[advanced] No file selected.")
        return
    path = Path(selected_file).expanduser()
    try:
        if path.suffix.lower() == ".ipynb":
            python_path = path.with_suffix(".py")
            python_path.write_text(file_editor.value, encoding="utf-8")
            with log_output:
                print(f"[advanced] Saved converted script: {python_path}")
            return
        path.write_text(file_editor.value, encoding="utf-8")
        with log_output:
            print(f"[advanced] Saved: {path}")
    except Exception as error:
        with log_output:
            print("[advanced][ERROR]", type(error).__name__, error)
