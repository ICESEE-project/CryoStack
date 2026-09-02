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

    # The right column is NOT pinned to the left. This scoped script (a) releases
    # any stale inline sizing a cached bundle pinned onto the Workspace column,
    # and (b) sizes the Run Log / Results *viewers* dynamically:
    #
    #   viewer max-height = viewport bottom - viewer top - footer padding
    #
    # so a viewer grows with its content and uses the available screen space,
    # then scrolls internally once it reaches the usable viewport bottom. Short
    # content stays compact (this only sets max-height). On narrow screens the
    # cap is dropped and the page just flows.
    height_sync = W.HTML("""
    <script>
    (() => {
        const VIEWERS = ".cryostack-log-viewer, .cryostack-results-viewer";
        const STALE = ".cryostack-right-workspace, .icesee-right";
        const MIN = 280;          // useful minimum viewer height (px)
        const FOOTER_PAD = 28;    // breathing room below a viewer (px)
        const NARROW = 1050;      // <= this width: natural page flow, no cap

        const releaseStale = () => document.querySelectorAll(STALE).forEach((el) => {
            el.style.removeProperty("height");
            el.style.removeProperty("min-height");
            el.style.removeProperty("max-height");
            el.style.removeProperty("overflow");
        });

        let raf = 0;
        const sizeViewers = () => {
            raf = 0;
            const narrow = window.innerWidth <= NARROW;
            document.querySelectorAll(VIEWERS).forEach((el) => {
                if (narrow) { el.style.removeProperty("max-height"); return; }
                const top = el.getBoundingClientRect().top;
                const avail = window.innerHeight - Math.max(top, 0) - FOOTER_PAD;
                el.style.maxHeight = Math.max(MIN, Math.round(avail)) + "px";
            });
        };
        const schedule = () => { if (!raf) raf = requestAnimationFrame(sizeViewers); };

        const start = () => {
            releaseStale();
            if (!document.querySelector(VIEWERS)) { setTimeout(start, 250); return; }
            schedule();
            window.addEventListener("resize", schedule, { passive: true });
            window.addEventListener("scroll", schedule, { passive: true, capture: true });
            const ro = new ResizeObserver(schedule);
            document.querySelectorAll(VIEWERS).forEach((el) => ro.observe(el));
            const tabs = document.querySelector(".cryostack-workspace-tabs");
            if (tabs) ro.observe(tabs);
            setTimeout(schedule, 400);
            setTimeout(schedule, 1200);
        };
        start();
    })();
    </script>
    """)
    return WorkspaceExplorer(container=container, height_sync=height_sync, left=left, right=right)
