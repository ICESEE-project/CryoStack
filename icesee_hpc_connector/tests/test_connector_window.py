"""macOS discoverability: the onboarding/status window view-model."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_hpc_connector.connector_controller import ConnectorState
from icesee_hpc_connector.connector_window import (
    ACTION_HIDE,
    ACTION_OPEN_CRYOSTACK,
    ACTION_PAIR,
    WindowMode,
    build_appkit_window,
    should_show_on_state,
    window_view,
)

_MENU = _REPO / "icesee_hpc_connector" / "connector_menubar_app.py"

_ONBOARDING = (
    ConnectorState.IDLE, ConnectorState.WAITING,
    ConnectorState.DISCONNECTED, ConnectorState.STOPPED, ConnectorState.ERROR,
)


@pytest.mark.parametrize("state", _ONBOARDING)
def test_onboarding_shows_an_obvious_pairing_field(state):
    v = window_view(state)
    assert v["mode"] == WindowMode.ONBOARDING
    assert v["show_code_field"] is True
    assert [a for _l, a in v["buttons"]] == [ACTION_PAIR]
    assert "menu bar" in v["footnote"].lower()          # "keeps running in menu bar"
    assert v["headline"] == "Status: Not paired"


def test_error_and_disconnected_prompt_for_a_fresh_code():
    assert "fresh pairing code" in window_view(ConnectorState.ERROR)["body"].lower()
    assert "fresh pairing code" in window_view(ConnectorState.DISCONNECTED)["body"].lower()


def test_connected_panel_has_open_and_hide_not_a_code_field():
    v = window_view(ConnectorState.CONNECTED)
    assert v["mode"] == WindowMode.CONNECTED
    assert v["show_code_field"] is False
    assert [a for _l, a in v["buttons"]] == [ACTION_OPEN_CRYOSTACK, ACTION_HIDE]
    assert v["headline"] == "✓ Connected"


def test_working_state_is_transient_and_field_free():
    for state in (ConnectorState.PAIRING, ConnectorState.RECONNECTING):
        v = window_view(state)
        assert v["mode"] == WindowMode.WORKING
        assert v["show_code_field"] is False
        assert [a for _l, a in v["buttons"]] == [ACTION_HIDE]


def test_window_auto_shows_until_connected():
    for state in _ONBOARDING + (ConnectorState.PAIRING, ConnectorState.RECONNECTING):
        assert should_show_on_state(state) is True
    assert should_show_on_state(ConnectorState.CONNECTED) is False


def test_appkit_window_is_none_without_a_mac_gui():
    # off macOS (or with no display) this must degrade gracefully, not raise
    assert build_appkit_window(lambda *_a: None) is None


# ── the menu bar stays a full control surface + window is discoverable ──
def test_menu_bar_keeps_every_useful_item_and_adds_show_window():
    src = _MENU.read_text()
    darwin = src.split('if sys.platform == "darwin":')[1].split("# ====")[0]
    for item in ('"Show CryoStack Connector"', '"Pair with CryoStack…"',
                 '"Open Setup Page"', '"Open Log File"', '"Quit"'):
        assert item in darwin, item
    assert "self._status_item" in darwin                # Status: connected ✓ etc.


def test_first_launch_is_dock_visible_and_shows_the_window():
    src = _MENU.read_text()
    darwin = src.split('if sys.platform == "darwin":')[1].split("# ====")[0]
    assert "NSApplicationActivationPolicyRegular" in darwin
    assert "build_appkit_window(self._on_window_action)" in darwin
    assert "self.window.show()" in darwin
    # Dock-icon click brings the window forward
    assert "applicationShouldHandleReopen" in darwin
    # explicit hide is user-driven only; auto-show respects it
    assert "_user_hid_window" in darwin
