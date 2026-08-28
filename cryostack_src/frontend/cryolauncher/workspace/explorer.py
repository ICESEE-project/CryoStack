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

    right = W.VBox(
        [run_details],
        layout=W.Layout(width="100%", min_width="0", min_height="0", overflow="hidden"),
    )
    for css_class in ("icesee-card", "icesee-right", "cryostack-right-workspace"):
        right.add_class(css_class)

    container = W.HBox([left, right], layout=W.Layout(width="100%"))
    container.add_class("icesee-grid")

    height_sync = W.HTML("""
    <script>
    (() => {
        function setupCryoStackWorkspaceSync() {
            const left = document.querySelector(".cryostack-left-workspace");
            const right = document.querySelector(".cryostack-right-workspace");
            if (!left || !right) {
                setTimeout(setupCryoStackWorkspaceSync, 250);
                return;
            }
            if (right.dataset.heightSyncAttached === "1") return;
            right.dataset.heightSyncAttached = "1";
            const syncHeight = () => {
                const height = left.getBoundingClientRect().height;
                if (height > 0) {
                    right.style.height = `${height}px`;
                    right.style.maxHeight = `${height}px`;
                    right.style.minHeight = `${height}px`;
                }
            };
            syncHeight();
            const observer = new ResizeObserver(syncHeight);
            observer.observe(left);
            window.addEventListener("resize", syncHeight);
        }
        setupCryoStackWorkspaceSync();
    })();
    </script>
    """)
    return WorkspaceExplorer(container=container, height_sync=height_sync, left=left, right=right)
