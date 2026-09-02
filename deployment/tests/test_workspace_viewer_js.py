"""Workspace Run Log / Results viewer sizing + live-tail follow.

Two layers:
  * JS unit tests (Node) for the pure geometry / follow-state functions --
    run here via ``node --test`` and skipped when node is unavailable.
  * Structural checks that the runtime stays geometry-aware (no hardcoded
    ``calc(100vh - N)``), scopes its cap to a custom property on the Run Log /
    Results viewers only, and keeps the single tail mechanism.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
_JS = _REPO / "cryostack_src/frontend/cryolauncher/workspace/viewer_geometry.js"
_EXPLORER = _REPO / "cryostack_src/frontend/cryolauncher/workspace/explorer.py"
_THEME = _REPO / "cryostack_src/frontend/shared/theme.py"
_GATEWAY = _REPO / "icesee_jupyter_book/ui/icesheets_gateway.py"
_NODE_TEST = _HERE / "workspace_viewer.test.mjs"

_NODE = shutil.which("node")


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_viewer_geometry_js_unit_tests():
    result = subprocess.run(
        [_NODE, "--test", str(_NODE_TEST)],
        capture_output=True, text=True, cwd=str(_HERE),
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


def test_module_and_embed_exist():
    assert _JS.is_file()
    src = _EXPLORER.read_text()
    # explorer embeds the module (single source of truth), stripping ES `export`
    assert 'with_name("viewer_geometry.js")' in src
    assert "re.sub(" in src and "export" in src


def test_sizing_is_geometry_aware_not_a_hardcoded_constant():
    js = _JS.read_text()
    assert "getBoundingClientRect" in js
    assert "visualViewport" in js and "innerHeight" in js
    assert ".cryostack-left-workspace" in js          # left-column bottom measured
    # no fragile hardcoded viewport arithmetic
    assert "calc(100vh" not in js
    assert "100vh -" not in js


def test_cap_is_a_scoped_custom_property_on_the_viewers_only():
    js = _JS.read_text()
    assert "--cryostack-workspace-viewer-max-height" in js
    assert ".cryostack-log-viewer" in js and ".cryostack-results-viewer" in js
    # the Workspace card height is never set from JS (only setProperty on the
    # scoped custom property; the card's own style.height is never touched)
    assert "style.height =" not in js
    assert ".style.setProperty(PROP" in js
    # CSS consumes the property, only on the viewers
    css = _THEME.read_text()
    assert "max-height: var(--cryostack-workspace-viewer-max-height" in css


def test_recalculation_is_event_driven_not_polled():
    js = _JS.read_text()
    assert "ResizeObserver" in js
    assert "requestAnimationFrame" in js              # debounce
    assert 'addEventListener("resize"' in js
    assert "visualViewport.addEventListener" in js
    assert "MutationObserver" in js                   # left-column / content changes
    assert "setInterval" not in js                    # never poll


def test_single_tail_mechanism():
    js = _JS.read_text()
    assert "nextTailState" in js
    assert "cryostack-tail-jump" in js
    # the old duplicate auto-scroll script in the gateway is gone
    gw = _GATEWAY.read_text()
    assert "installCryoStackLogScroll" not in gw


def test_live_tail_follow_semantics_present():
    js = _JS.read_text()
    # follow while at bottom; suspend on user scroll-up; resume on jump
    assert '"user-scroll"' in js and '"jump"' in js and '"mutation"' in js
    assert "programmatic" in js                       # ignore self-induced scroll
    assert "jump.hidden" in js


def test_tiny_geometry_does_not_collapse_the_viewer():
    js = _JS.read_text()
    # returns null on tiny/invalid geometry; caller removes the property so the
    # CSS min-height + natural flow take over
    assert "return null" in js
    assert "removeProperty(PROP)" in js
