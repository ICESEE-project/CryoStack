from __future__ import annotations

from dataclasses import dataclass

import ipywidgets as W


@dataclass
class WorkspaceExplorer:
    container: W.HBox
    height_sync: W.HTML
    left: W.VBox
    right: W.VBox


def build_workspace_explorer(*, run_settings, runtime, run_details) -> WorkspaceExplorer:
    left = W.VBox(
        [run_settings, runtime],
        layout=W.Layout(width="100%", min_width="0", gap="12px"),
    )
    for css_class in ("icesee-card", "icesee-left", "cryostack-left-workspace"):
        left.add_class(css_class)

    # The right (Workspace) column determines its OWN natural height: no fixed
    # height, no max-height, overflow visible so nothing is clipped when the
    # left card is short (e.g. Agent mode). Page-level scrolling handles a tall
    # Workspace -- there is no inner Workspace scrollbar.
    right = W.VBox(
        [run_details],
        layout=W.Layout(width="100%", min_width="0", align_self="flex-start"),
    )
    for css_class in ("icesee-card", "icesee-right", "cryostack-right-workspace"):
        right.add_class(css_class)

    # Two-column shell: columns align at the TOP and each grows to its own
    # content height -- never equal-height / stretch (the left card must not
    # cap Workspace).
    container = W.HBox(
        [left, right],
        layout=W.Layout(width="100%", align_items="flex-start"),
    )
    container.add_class("icesee-grid")

    # No height synchronisation: the right column is not pinned to the left.
    # This inert script only *releases* any stale inline sizing a previously
    # cached bundle may have pinned onto the Workspace column.
    height_sync = W.HTML("""
    <script>
    (() => {
        const release = () => {
            document.querySelectorAll(
                ".cryostack-right-workspace, .icesee-right"
            ).forEach((el) => {
                el.style.removeProperty("height");
                el.style.removeProperty("min-height");
                el.style.removeProperty("max-height");
                el.style.removeProperty("overflow");
            });
        };
        release();
        setTimeout(release, 500);
    })();
    </script>
    """)
    return WorkspaceExplorer(container=container, height_sync=height_sync, left=left, right=right)
