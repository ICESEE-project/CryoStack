from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import ipywidgets as W

#: single source of truth -- the geometry math is unit-tested with `node --test`
#: (deployment/tests/workspace_viewer.test.mjs); the same file is embedded here
#: with the ES `export` keywords stripped so it runs inline in Voila.
_VIEWER_JS = re.sub(
    r"^export\s+(function|const|let|class)\b", r"\1",
    Path(__file__).with_name("viewer_geometry.js").read_text(),
    flags=re.MULTILINE,
)


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

    # The right column is NOT pinned to the left. This scoped script sizes the
    # Run Log / Results *viewers* from actual rendered geometry (viewport,
    # viewer top, left-column bottom) via a scoped custom property, and drives
    # the live-tail auto-follow. It never sets the Workspace card height.
    height_sync = W.HTML(f"<script>\n{_VIEWER_JS}\n</script>")
    return WorkspaceExplorer(container=container, height_sync=height_sync, left=left, right=right)
