"""CryoLauncher reusable dataset panel -- a generic, model-neutral facility.

Datasets live under ``<owner_root>/datasets/`` (never inside an example or run
directory). A user only ever sees / references / deletes their own. Scientific
formats (.mat/.h5/.nc/.csv/.dat/.exp/...) are visible even though most are not
text-editable.
"""
from __future__ import annotations

import html
from dataclasses import dataclass

import ipywidgets as W

from cryostack_src.workspace.manager import WorkspaceManager


def _size(n: int) -> str:
    step = 0
    val = float(n)
    while val >= 1024 and step < 3:
        val /= 1024
        step += 1
    return f"{val:.0f} {'B KB MB GB'.split()[step]}" if step == 0 else f"{val:.1f} {'B KB MB GB'.split()[step]}"


@dataclass
class DatasetPanel:
    container: W.VBox
    refresh: "callable"


def build_dataset_panel(
    *,
    manager: WorkspaceManager,
    uploader: W.FileUpload,
    log_output,
    current_example_path,          # callable -> str | "" (a user example, or "")
    on_changed=None,
) -> DatasetPanel:
    listing = W.Select(options=[], rows=6, layout=W.Layout(width="100%"))
    status = W.HTML()
    overwrite_toggle = W.Checkbox(value=False, description="Overwrite existing",
                                  indent=False)
    confirm_delete = W.Checkbox(value=False, description="Confirm delete",
                                indent=False)
    ref_as = W.Text(placeholder="reference as… (optional)",
                    layout=W.Layout(width="200px"))

    def _btn(desc, icon, style=""):
        return W.Button(description=desc, icon=icon, button_style=style,
                        layout=W.Layout(width="auto"))

    upload_btn = _btn("Upload", "upload", "primary")
    refresh_btn = _btn("Refresh", "refresh")
    delete_btn = _btn("Delete", "trash", "danger")
    reference_btn = _btn("Reference in example", "link", "info")

    _rows: list[dict] = []

    def _log(*p):
        if log_output is not None:
            with log_output:
                print(*p)

    def _selected_name() -> str | None:
        val = listing.value
        return val.split("  · ", 1)[0] if val else None

    def refresh(_=None):
        nonlocal _rows
        _rows = manager.list_datasets()
        opts = []
        for d in _rows:
            tag = "text" if d["editable"] else "data"
            ref = f"  · referenced by {len(d['referenced_by'])}" if d["referenced_by"] else ""
            opts.append(f"{d['name']}  · {_size(d['size'])}  · {tag}{ref}")
        listing.options = opts
        if opts:
            listing.value = opts[0]
        n = len(_rows)
        status.value = (
            f"<span class='icesee-subtle'>{n} dataset{'s' if n != 1 else ''} in "
            f"your workspace</span>"
        )
        _render()

    def _render(*_a):
        has_sel = _selected_name() is not None
        delete_btn.disabled = not has_sel
        confirm_delete.layout.display = "" if has_sel else "none"
        ex = (current_example_path() or "").strip()
        can_ref = has_sel and bool(ex) and manager.is_user_owned(ex)
        reference_btn.disabled = not can_ref
        ref_as.layout.display = "" if can_ref else "none"

    listing.observe(_render, names="value")

    def on_upload(_=None):
        value = uploader.value
        if not value:
            _log("[dataset] No files selected.")
            return
        result = manager.save_datasets(value, overwrite=overwrite_toggle.value)
        for name in result["saved"]:
            _log(f"[dataset] uploaded {name}")
        for name in result["skipped"]:
            _log(f"[dataset] {name} already exists — tick 'Overwrite existing' to replace it.")
        for err in result["errors"]:
            _log(f"[dataset][ERROR] {err}")
        try:
            uploader.value = ()
            uploader._counter = 0
        except Exception:
            pass
        overwrite_toggle.value = False
        refresh()
        if on_changed is not None:
            on_changed()

    def on_delete(_=None):
        name = _selected_name()
        if not name:
            return
        if not confirm_delete.value:
            _log(f"[dataset] Tick 'Confirm delete' to remove {name}.")
            return
        row = next((d for d in _rows if d["name"] == name), None)
        if row and row["referenced_by"]:
            _log(f"[dataset][WARN] {name} is referenced by: "
                 f"{', '.join(row['referenced_by'])} — those references will break.")
        try:
            removed = manager.delete_dataset(name)
        except Exception as err:  # noqa: BLE001 - surfaced to the user
            _log("[dataset][ERROR]", type(err).__name__, err)
            return
        confirm_delete.value = False
        _log(f"[dataset] deleted {removed}")
        refresh()
        if on_changed is not None:
            on_changed()

    def on_reference(_=None):
        name = _selected_name()
        ex = (current_example_path() or "").strip()
        if not name or not ex:
            return
        try:
            refs = manager.reference_dataset(
                example_path=ex, dataset_name=name,
                as_path=(ref_as.value.strip() or None),
            )
        except Exception as err:  # noqa: BLE001
            _log("[dataset][ERROR]", type(err).__name__, err)
            return
        ref_as.value = ""
        _log(f"[dataset] {name} referenced by this example (now {len(refs)} reference(s)). "
             "It is copied into the run only when the example is staged.")
        refresh()

    upload_btn.on_click(on_upload)
    refresh_btn.on_click(refresh)
    delete_btn.on_click(on_delete)
    reference_btn.on_click(on_reference)

    container = W.VBox(
        [
            W.HTML("<div class='cryostack-section-label'>Datasets</div>"),
            W.HBox([uploader, upload_btn, overwrite_toggle, refresh_btn],
                   layout=W.Layout(gap="8px", align_items="center", flex_wrap="wrap")),
            status,
            listing,
            W.HBox([delete_btn, confirm_delete, reference_btn, ref_as],
                   layout=W.Layout(gap="10px", align_items="center", flex_wrap="wrap")),
        ],
        layout=W.Layout(width="100%", gap="6px"),
    )
    refresh()
    return DatasetPanel(container=container, refresh=refresh)
