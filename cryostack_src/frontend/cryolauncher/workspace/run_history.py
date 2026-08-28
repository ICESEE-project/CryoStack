from __future__ import annotations

from dataclasses import dataclass

import ipywidgets as W


@dataclass
class WorkspaceHistoryPanel:
    container: W.VBox
    refresh_button: W.Button
    runs: W.Select


def build_workspace_history_panel(*, manager) -> WorkspaceHistoryPanel:
    refresh_button = W.Button(description="Refresh", icon="refresh")
    runs = W.Select(description="Previous Runs", rows=4, layout=W.Layout(width="100%"))
    selected = W.HTML("<div class='icesee-subtle'>No run selected.</div>")
    files = W.Textarea(disabled=True, layout=W.Layout(width="100%", height="110px"))
    tail_button = W.Button(description="Tail Log", icon="file-text")
    download_button = W.Button(description="Download", icon="download")
    figures_button = W.Button(description="Figures", icon="image")
    confirm = W.Checkbox(description="Confirm deletion of selected run", indent=False)
    delete_button = W.Button(description="Delete", icon="trash", button_style="danger", disabled=True)

    details = W.Accordion(children=[files, W.HTML("Uses the existing Run Log tab."), W.HTML("Uses the existing Results tab."), W.HTML("Figures appear in Results.")])
    for index, title in enumerate(("Files", "Run Log", "Results", "Figures")):
        details.set_title(index, title)
    details.selected_index = None

    def refresh(_=None):
        discovered = manager.refresh()
        runs.options = [
            (f"{run.model.upper()} • {run.created:%Y-%m-%d} • {run.status.title()}", run.id)
            for run in discovered
        ] or [("No previous runs found", "")]
        if not discovered:
            runs.value = ""
        show_selection()

    def show_selection(change=None):
        run = manager.select_run(runs.value or "")
        confirm.value = False
        if not run:
            selected.value = "<div class='icesee-subtle'>No run selected.</div>"
            files.value = ""
            return
        selected.value = (
            f"<b>{run.model.upper()}</b> · {run.backend} · {run.execution_mode}"
            f"<br><span class='icesee-subtle'>{run.status.title()} · Job {run.jobid or '—'}</span>"
        )
        paths = manager.files(run.id)
        files.value = "\n".join(str(path.relative_to(run.workspace_directory)) for path in paths) or "(workspace files unavailable)"

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

    container = W.VBox([
        W.HTML("<div style='font-size:13px;font-weight:700'>Workspace</div>"),
        refresh_button, runs,
        W.HTML("<div style='font-size:12px;font-weight:700'>Selected Run</div>"),
        selected, details,
        W.HBox([tail_button, download_button, figures_button], layout=W.Layout(gap="8px", flex_wrap="wrap")),
        confirm, delete_button,
    ], layout=W.Layout(width="100%", gap="7px", padding="8px", border="1px solid #dfe6ef"))
    refresh()
    return WorkspaceHistoryPanel(container=container, refresh_button=refresh_button, runs=runs)
