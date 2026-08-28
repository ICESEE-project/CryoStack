from __future__ import annotations

from dataclasses import dataclass

import ipywidgets as W


@dataclass
class WorkspaceDetails:
    container: W.VBox
    tabs: W.Tab


def build_run_details(
    *, log_output, results_output, download_controls, log_controls,
    runs_panel, files_panel,
):
    logs_panel = W.VBox(
        [log_output, log_controls],
        layout=W.Layout(width="100%", height="100%", min_height="0", gap="8px", overflow="hidden"),
    )
    results_panel = W.VBox(
        [results_output, download_controls],
        layout=W.Layout(width="100%", height="100%", min_height="0", gap="8px", overflow="hidden"),
    )
    tabs = W.Tab(
        children=[runs_panel, files_panel, logs_panel, results_panel],
        layout=W.Layout(width="100%", min_height="0", flex="1 1 0", overflow="hidden"),
    )
    for index, title in enumerate(("Runs", "Files", "Run Log", "Results")):
        tabs.set_title(index, title)
    for panel in (runs_panel, files_panel, logs_panel, results_panel):
        panel.add_class("cryostack-output-tab")
    tabs.add_class("cryostack-output-tabs")
    tabs.add_class("cryostack-workspace-tabs")
    container = W.VBox(
        [W.HTML("<div class='cryostack-workspace-heading'><span>Workspace</span></div>"), tabs],
        layout=W.Layout(width="100%", height="100%", min_height="0", gap="0", overflow="hidden"),
    )
    container.add_class("cryostack-output-workspace")
    return WorkspaceDetails(container=container, tabs=tabs)
