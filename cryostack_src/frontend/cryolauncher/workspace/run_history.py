from __future__ import annotations

from dataclasses import dataclass

import ipywidgets as W


@dataclass
class WorkspaceHistoryPanel:
    runs_panel: W.VBox
    files_panel: W.VBox
    refresh_button: W.Button
    runs: W.Select


def build_workspace_history_panel(*, manager) -> WorkspaceHistoryPanel:
    refresh_button = W.Button(description="Refresh", icon="refresh")
    runs = W.Select(description="Previous Runs", rows=4, layout=W.Layout(width="100%"))
    selected = W.HTML("<div class='icesee-subtle'>No run selected.</div>")
    files = W.HTML("<div class='icesee-subtle'>Select a run to inspect its workspace.</div>")
    tail_button = W.Button(description="Tail Log", icon="file-text")
    download_button = W.Button(description="Download", icon="download")
    figures_button = W.Button(description="Figures", icon="image")
    confirm = W.Checkbox(description="Confirm deletion of selected run", indent=False)
    delete_button = W.Button(description="Delete", icon="trash", button_style="danger", disabled=True)

    def refresh(_=None):
        previously_selected = manager.selected_run() if hasattr(manager, "selected_run") else None
        discovered = manager.refresh()
        runs.options = [
            (f"{run.model.upper()} • {run.created:%Y-%m-%d} • {run.status.title()}", run.id)
            for run in discovered
        ] or [("No previous runs found", "")]
        run_ids = {run.id for run in discovered}
        if discovered:
            runs.value = previously_selected.id if previously_selected and previously_selected.id in run_ids else discovered[0].id
        else:
            runs.value = ""
        show_selection()

    def show_selection(change=None):
        run = manager.select_run(runs.value or "")
        confirm.value = False
        if not run:
            selected.value = "<div class='icesee-subtle'>No run selected.</div>"
            files.value = "<div class='icesee-subtle'>Select a run to inspect its workspace.</div>"
            return
        selected.value = (
            f"<b>{run.model.upper()}</b> · {run.backend} · {run.execution_mode}"
            f"<br><span class='icesee-subtle'>{run.status.title()} · Job {run.jobid or '—'}</span>"
        )
        paths = manager.files(run.id)
        labels = [str(path.relative_to(run.workspace_directory)) for path in paths]
        if labels:
            import html
            files.value = (
                "<pre class='cryostack-workspace-tree'>"
                + "\n".join(f"├── {html.escape(label)}" for label in labels)
                + "</pre>"
            )
        else:
            files.value = "<div class='icesee-subtle'>(workspace files unavailable)</div>"

    def tail(_):
        if runs.value:
            manager.tail(runs.value)

    def download(_):
        if runs.value:
            manager.download_results(runs.value)

    def figures(_):
        if runs.value:
            manager.download_figures(runs.value)

    def delete(_):
        if runs.value and confirm.value and manager.delete_run(runs.value):
            refresh()

    refresh_button.on_click(refresh)
    runs.observe(show_selection, names="value")
    confirm.observe(lambda change: setattr(delete_button, "disabled", not change["new"]), names="value")
    tail_button.on_click(tail)
    download_button.on_click(download)
    figures_button.on_click(figures)
    delete_button.on_click(delete)

    runs_panel = W.VBox([
        W.HBox([refresh_button]), runs,
        W.HTML("<div style='font-size:12px;font-weight:700'>Selected Run</div>"),
        selected,
        W.HBox([tail_button, download_button, figures_button], layout=W.Layout(gap="8px", flex_wrap="wrap")),
        confirm, delete_button,
    ], layout=W.Layout(width="100%", height="100%", min_height="0", gap="7px", overflow_y="auto"))
    files_panel = W.VBox(
        [files],
        layout=W.Layout(width="100%", height="100%", min_height="0", overflow_y="auto"),
    )
    refresh()
    return WorkspaceHistoryPanel(
        runs_panel=runs_panel,
        files_panel=files_panel,
        refresh_button=refresh_button,
        runs=runs,
    )
