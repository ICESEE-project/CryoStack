from __future__ import annotations

from dataclasses import dataclass

import ipywidgets as W


@dataclass
class WorkspaceDetails:
    container: W.VBox
    tabs: W.Tab


def build_run_details(
    *, log_output, results_output, download_controls, log_controls,
    runs_panel, files_panel, visualization_panel=None,
):
    # Natural-height Workspace: no height:100% / overflow:hidden chain. The
    # column grows to fit its content and the page scrolls; only the live-log
    # terminal keeps its own scroll (handled in CSS via .cryostack-live-log).
    logs_panel = W.VBox(
        [log_output, log_controls],
        layout=W.Layout(width="100%", min_height="0", gap="8px"),
    )
    results_children = [results_output, download_controls]
    if visualization_panel is not None:
        results_children.insert(0, visualization_panel)
    results_panel = W.VBox(
        results_children,
        layout=W.Layout(width="100%", min_height="0", gap="8px"),
    )
    tabs = W.Tab(
        children=[runs_panel, files_panel, logs_panel, results_panel],
        layout=W.Layout(width="100%", min_height="0"),
    )
    for index, title in enumerate(("Runs", "Files", "Run Log", "Results")):
        tabs.set_title(index, title)
    for panel in (runs_panel, files_panel, logs_panel, results_panel):
        panel.add_class("cryostack-output-tab")
    tabs.add_class("cryostack-output-tabs")
    tabs.add_class("cryostack-workspace-tabs")
    container = W.VBox(
        [W.HTML("<div class='cryostack-workspace-heading'><span>Workspace</span></div>"), tabs],
        layout=W.Layout(width="100%", min_height="0", gap="0"),
    )
    container.add_class("cryostack-output-workspace")
    return WorkspaceDetails(container=container, tabs=tabs)
