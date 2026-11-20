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
    feedback = W.HTML()
    reference_hint = W.HTML()
    uploader.description = "Choose data files"
    overwrite_toggle = W.Checkbox(value=False, description="Overwrite existing",
                                  indent=False)
    confirm_delete = W.Checkbox(value=False, description="Confirm delete",
                                indent=False)
    ref_as = W.Text(placeholder="path inside data/ (optional)",
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

    def _feedback(message: str, *, error: bool = False):
        owner_root = getattr(manager, "_owner_root", None)
        if owner_root is not None:
            message = message.replace(str(owner_root), "Your workspace")
        role, color = ("alert", "#a32525") if error else ("status", "#285580")
        feedback.value = (
            f'<div role="{role}" style="border-left:3px solid {color};'
            f'padding:6px 10px;color:{color};overflow-wrap:anywhere;">'
            f"{html.escape(message)}</div>"
        )

    def _selected_name() -> str | None:
        val = listing.value
        return val or None

    def refresh(_=None, *, preferred=None):
        nonlocal _rows
        previous = listing.value
        _rows = manager.list_datasets()
        opts = []
        for d in _rows:
            tag = "text" if d["editable"] else "data"
            ref = f"  · referenced by {len(d['referenced_by'])}" if d["referenced_by"] else ""
            label = f"{d['name']}  · {_size(d['size'])}  · {tag}{ref}"
            opts.append((label, d["name"]))
        listing.options = opts
        if opts:
            names = {name for _label, name in opts}
            listing.value = preferred if preferred in names else previous if previous in names else opts[0][1]
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
        if not has_sel:
            hint = "Upload and select a dataset, then reference it in your workspace example."
        elif not can_ref:
            hint = "To reference this dataset, select an example in My Workspace. " \
                   "Use New example or Clone to My Workspace in the Advanced editor first."
        else:
            name = _selected_name()
            try:
                existing = next((r for r in manager.example_dataset_references(ex)
                                 if r.get("name") == name), None)
            except Exception:
                existing = None
            if existing and not ref_as.value.strip():
                hint = f"Referenced in this example as data/{existing.get('as', name)}. " \
                       "The next run copies the file there; your script must read that path."
            else:
                target = ref_as.value.strip() or name
                hint = f"Click Reference in example to stage this file as data/{target} " \
                       "on the next run. Your script must read that path."
        reference_hint.value = f"<div class='icesee-subtle'>{html.escape(hint)}</div>"

    listing.observe(_render, names="value")
    ref_as.observe(_render, names="value")
    # The dataset selection may stay unchanged when the example changes.
    # Re-evaluate ownership immediately so reference controls do not retain
    # their disabled state from a canonical example.
    example_widget = getattr(manager, "example_dir", None)
    if callable(getattr(example_widget, "observe", None)):
        example_widget.observe(_render, names="value")

    def on_upload(_=None):
        value = uploader.value
        if not value:
            _log("[dataset] No files selected.")
            _feedback("Choose data files before clicking Upload.", error=True)
            return
        try:
            result = manager.save_datasets(value, overwrite=overwrite_toggle.value)
        except Exception as err:
            _log("[dataset][ERROR]", type(err).__name__, err)
            _feedback(f"Upload failed: {err}", error=True)
            return
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
        preferred = result["saved"][0] if result["saved"] else listing.value
        refresh(preferred=preferred)
        summary = []
        if result["saved"]:
            summary.append("Uploaded: " + ", ".join(result["saved"]) + ".")
        if result["skipped"]:
            summary.append("Already present: " + ", ".join(result["skipped"]) +
                           ". Tick Overwrite existing only if you intend to replace them.")
        if result["errors"]:
            summary.append("Upload errors: " + "; ".join(result["errors"]))
        _feedback(" ".join(summary), error=bool(result["errors"]))
        if on_changed is not None:
            on_changed()

    def on_delete(_=None):
        name = _selected_name()
        if not name:
            return
        if not confirm_delete.value:
            _log(f"[dataset] Tick 'Confirm delete' to remove {name}.")
            _feedback(f"Tick Confirm delete to remove {name}.", error=True)
            return
        row = next((d for d in _rows if d["name"] == name), None)
        if row and row["referenced_by"]:
            _log(f"[dataset][WARN] {name} is referenced by: "
                 f"{', '.join(row['referenced_by'])} — those references will break.")
        try:
            removed = manager.delete_dataset(name)
        except Exception as err:  # noqa: BLE001 - surfaced to the user
            _log("[dataset][ERROR]", type(err).__name__, err)
            _feedback(f"Delete failed: {err}", error=True)
            return
        confirm_delete.value = False
        _log(f"[dataset] deleted {removed}")
        _feedback(f"Deleted {name}.")
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
            _feedback(f"Reference failed: {err}", error=True)
            return
        ref_as.value = ""
        _log(f"[dataset] {name} referenced by this example (now {len(refs)} reference(s)). "
             "It is copied into the run only when the example is staged.")
        refresh(preferred=name)
        reference = next(r for r in refs if r.get("name") == name)
        _feedback(f"Referenced {name}. In your script, read data/{reference.get('as', name)}. "
                  "The file is copied into that path when the next run is staged.")
        if on_changed is not None:
            on_changed()

    upload_btn.on_click(on_upload)
    refresh_btn.on_click(refresh)
    delete_btn.on_click(on_delete)
    reference_btn.on_click(on_reference)

    container = W.VBox(
        [
            W.HTML("<div class='cryostack-section-label'>Datasets</div>"),
            W.HTML("<div class='icesee-subtle'>Any file extension can be uploaded, up to "
                   "50 MiB per file. Your script must support the data format; upload alone "
                   "does not initialize the model.</div>"),
            W.HBox([uploader, upload_btn, overwrite_toggle, refresh_btn],
                   layout=W.Layout(gap="8px", align_items="center", flex_wrap="wrap")),
            status,
            feedback,
            listing,
            reference_hint,
            W.HBox([delete_btn, confirm_delete, reference_btn, ref_as],
                   layout=W.Layout(gap="10px", align_items="center", flex_wrap="wrap")),
        ],
        layout=W.Layout(width="100%", gap="6px"),
    )
    refresh()
    return DatasetPanel(container=container, refresh=refresh)
