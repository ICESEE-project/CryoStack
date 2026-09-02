"""Regression guards for the IceSheets two-column desktop layout.

The Workspace (right) column must determine its own natural height and never
be capped by the short Run-settings (left) card -- the Agent-mode clipping
defect. These guard the CSS/layout contract, not pixel rendering.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import ipywidgets as W

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.frontend.cryolauncher.workspace.explorer import (
    build_workspace_explorer,
)
from cryostack_src.frontend.cryolauncher.workspace.run_details import (
    build_run_details,
)
from cryostack_src.frontend.shared.theme import CRYOSTACK_FRONTEND_CSS

_SHARED_CSS = (_REPO / "icesee_jupyter_book/ui/shared_app_styles.py").read_text()


def _rule(css: str, selector: str, *, inside_media: bool | None = False) -> str:
    """Return the declaration block for the first *top-level* rule whose
    selector list contains `selector` exactly. Comments stripped first."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    # blank out @media bodies so a bare selector inside one is not matched
    if inside_media is False:
        css = re.sub(r"@media[^{]*\{(?:[^{}]|\{[^{}]*\})*\}", " ", css)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sels = [s.strip() for s in m.group(1).split(",")]
        if selector in sels:
            return m.group(2)
    raise AssertionError(f"no rule for {selector!r}")


# ── explorer widget layout ──────────────────────────────────────────────
def _explorer():
    return build_workspace_explorer(
        run_settings=W.HTML("left"), runtime=W.HTML("rt"),
        run_details=build_run_details(
            log_output=W.Output(), results_output=W.Output(),
            download_controls=W.HTML(), log_controls=W.HTML(),
            runs_panel=W.HTML("runs"), files_panel=W.HTML("files"),
        ).container,
    )


def test_right_column_is_top_aligned_not_stretched():
    ex = _explorer()
    assert ex.container.layout.align_items in ("flex-start", "start")
    assert ex.right.layout.align_self in ("flex-start", "start")


def test_right_column_has_no_clipping_height_or_overflow():
    ex = _explorer()
    for lay in (ex.right.layout,):
        assert lay.height in (None, "", "auto"), lay.height
        assert lay.max_height in (None, ""), lay.max_height
        assert lay.overflow not in ("hidden",), lay.overflow


def test_run_details_containers_are_natural_height():
    d = build_run_details(
        log_output=W.Output(), results_output=W.Output(),
        download_controls=W.HTML(), log_controls=W.HTML(),
        runs_panel=W.HTML(), files_panel=W.HTML(),
    )
    for w in (d.container, d.tabs, *d.tabs.children):
        lay = w.layout
        assert lay.height in (None, "", "auto"), (w, lay.height)
        assert lay.max_height in (None, ""), (w, lay.max_height)
        assert lay.overflow not in ("hidden",), (w, lay.overflow)
    # the Tab must not use flex:1 1 0 (collapses without a fixed-height parent)
    assert (d.tabs.layout.flex or "") not in ("1 1 0", "1 1 auto")


def test_height_sync_no_longer_pins_the_right_column():
    ex = _explorer()
    js = ex.height_sync.value.replace(" ", "")
    # the right column is never given a fixed height copied from the left
    assert "right.style.height=" not in js
    assert "right.style.maxHeight=" not in js
    assert "right.style.minHeight=" not in js
    # it releases any stale inline sizing on the workspace column
    assert "removeProperty" in js


def test_viewer_sizing_script_caps_max_height_not_height():
    ex = _explorer()
    js = ex.height_sync.value
    # sizes the Run Log / Results *viewers* only, via max-height
    assert ".cryostack-log-viewer" in js and ".cryostack-results-viewer" in js
    assert "maxHeight" in js
    # derived from the viewport, not a fixed constant height
    assert "innerHeight" in js and "getBoundingClientRect" in js
    # never sets an explicit height on the viewer
    assert re.search(r"\.style\.height\s*=", js) is None
    # narrow screens: the cap is dropped
    assert "removeProperty(\"max-height\")" in js or "removeProperty('max-height')" in js


# ── CSS contract ────────────────────────────────────────────────────────
def test_desktop_grid_is_top_aligned():
    for css in (CRYOSTACK_FRONTEND_CSS, _SHARED_CSS):
        block = _rule(css, ".icesee-grid")
        assert "align-items: start" in block or "align-items: flex-start" in block
        assert "align-items: stretch" not in block


def test_workspace_classes_have_no_clipping_height_or_hidden_overflow():
    css = CRYOSTACK_FRONTEND_CSS
    for sel in (".cryostack-output-workspace", ".cryostack-output-tabs",
                ".cryostack-output-tab", ".icesee-right"):
        block = _rule(css, sel)
        assert "height: 100%" not in block, sel
        assert "max-height" not in block, sel
        assert "overflow: hidden" not in block, sel
        assert "position: absolute" not in block, sel


def test_workspace_content_body_scrolls_with_the_page():
    block = _rule(CRYOSTACK_FRONTEND_CSS, ".cryostack-workspace-tabs > .widget-tab-contents")
    assert "overflow: visible" in block
    assert "max-height" not in block


def test_right_widget_vbox_is_not_absolutely_positioned():
    block = _rule(CRYOSTACK_FRONTEND_CSS, ".icesee-right > .widget-vbox")
    assert "position: absolute" not in block
    assert "position: static" in block
    assert "overflow: hidden" not in block


# ── responsive / sticky ────────────────────────────────────────────────
def test_responsive_breakpoint_stacks_the_columns():
    css = CRYOSTACK_FRONTEND_CSS
    m = re.search(r"@media\s*\(max-width:\s*1050px\)\s*\{(.*?)\n\}", css, re.S)
    assert m, "no max-width:1050px stack breakpoint"
    body = m.group(1)
    assert "grid-template-columns: 1fr" in body


def test_tab_body_floor_is_compact_not_the_viewer_height():
    """Runs / Files must not be forced to the taller Run Log / Results height."""
    block = _rule(CRYOSTACK_FRONTEND_CSS,
                  ".cryostack-workspace-tabs > .widget-tab-contents")
    m = re.search(r"min-height:\s*(\d+)px", block)
    assert m and int(m.group(1)) <= 200, block


def test_log_and_results_viewers_have_bounded_overflow_no_fixed_height():
    css = CRYOSTACK_FRONTEND_CSS
    for sel in (".cryostack-log-viewer", ".cryostack-results-viewer"):
        block = _rule(css, sel)
        assert "overflow" in block                       # scrollable when needed
        assert "height: 100%" not in block
        assert "100vh" not in block
        assert "max-height" not in block                 # the script sets the cap
        assert re.search(r"min-height:\s*\d+px", block)   # a useful minimum


def test_mobile_relaxes_viewer_nested_scrolling():
    css = CRYOSTACK_FRONTEND_CSS
    m = re.search(r"@media\s*\(max-width:\s*1050px\)\s*\{(.*?)\n\}", css, re.S)
    body = m.group(1)
    assert ".cryostack-log-viewer" in body and ".cryostack-results-viewer" in body
    assert "max-height: none" in body
    assert "overflow-x: hidden" in body                  # no horizontal overflow


def test_sticky_is_desktop_only_and_off_at_narrow_widths():
    css = CRYOSTACK_FRONTEND_CSS
    # every 'position: sticky' occurrence must be inside a min-width media query
    for m in re.finditer(r"position:\s*sticky", css):
        head = css[:m.start()]
        last_media = head.rfind("@media")
        last_close = head.rfind("}")
        assert last_media > last_close, "sticky outside a media query"
        media_line = css[last_media:css.index("{", last_media)]
        assert "min-width" in media_line, media_line
    # and the narrow breakpoint forces static
    m = re.search(r"@media\s*\(max-width:\s*1050px\)\s*\{(.*?)\n\}", css, re.S)
    assert "position: static" in m.group(1)
