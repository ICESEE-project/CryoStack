from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import ipywidgets as W


@dataclass
class WorkspaceDetails:
    container: W.VBox
    tabs: W.Tab
    #: Advanced mode: prepends the SAME editor widget as tab 0 ("Editor",
    #: then Runs/Files/Run Log/Results). Basic mode (or a caller that never
    #: passed ``editor_panel``): the original 4 tabs, unchanged. A no-op
    #: when ``build_run_details`` was called without ``editor_panel``.
    set_advanced_mode: Callable[[bool], None] = field(default=lambda advanced: None)


def build_run_details(
    *, log_output, results_output, download_controls, log_controls,
    runs_panel, files_panel, visualization_panel=None, editor_panel=None,
):
    """``editor_panel`` (optional) is the Advanced-mode file editor -- the
    caller's own already-built widget (the SAME instance its controller
    drives, never recreated here). When set, it becomes tab 0 ("Editor")
    of THIS SAME Tab widget whenever the caller invokes
    ``WorkspaceDetails.set_advanced_mode(True)`` -- the Tab's own
    children/titles are the show/hide mechanism, not a wrapper Accordion or
    a second Tab widget. ``set_advanced_mode(False)`` (or never calling it)
    restores/keeps the original 4 tabs. ``None`` (the default) keeps this
    function's output byte-for-byte identical to the no-editor case --
    ICESEE, which has no editor, never passes it.
    """
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

    base_children = (runs_panel, files_panel, logs_panel, results_panel)
    base_titles = ("Runs", "Files", "Run Log", "Results")

    tabs = W.Tab(
        children=list(base_children),
        layout=W.Layout(width="100%", min_height="0"),
    )
    for index, title in enumerate(base_titles):
        tabs.set_title(index, title)
    for panel in base_children:
        panel.add_class("cryostack-output-tab")
    if editor_panel is not None:
        editor_panel.add_class("cryostack-output-tab")
        editor_panel.add_class("cryostack-editor-tab")
    tabs.add_class("cryostack-output-tabs")
    tabs.add_class("cryostack-workspace-tabs")

    # tracks the CURRENT mode so repeated identical calls (update_visibility
    # re-runs on many unrelated toggles) are a no-op -- never reassigns
    # .children/titles unless the mode actually changed.
    _mode = {"advanced": False}

    def set_advanced_mode(advanced: bool) -> None:
        if editor_panel is None:
            return
        advanced = bool(advanced)
        if _mode["advanced"] == advanced:
            return
        _mode["advanced"] = advanced

        # remember which tab was showing BY TITLE (its index shifts by +1
        # in either direction once "Editor" is inserted/removed at 0) so
        # the user's current tab (e.g. "Run Log", mid Run-Log tail) is not
        # silently swapped for a different tab merely because its index
        # moved.
        was_title = None
        if tabs.children and tabs.selected_index is not None:
            was_title = tabs.get_title(tabs.selected_index)

        if advanced:
            children = [editor_panel, *base_children]
            titles = ("Editor", *base_titles)
        else:
            children = list(base_children)
            titles = base_titles

        tabs.children = children
        for index, title in enumerate(titles):
            tabs.set_title(index, title)

        if was_title is not None:
            for index, title in enumerate(titles):
                if title == was_title:
                    tabs.selected_index = index
                    break
            else:
                tabs.selected_index = 0

    container_children = [
        W.HTML("<div class='cryostack-workspace-heading'><span>Workspace</span></div>"), tabs,
    ]
    container = W.VBox(
        container_children,
        layout=W.Layout(width="100%", min_height="0", gap="0"),
    )
    container.add_class("cryostack-output-workspace")
    return WorkspaceDetails(container=container, tabs=tabs, set_advanced_mode=set_advanced_mode)
