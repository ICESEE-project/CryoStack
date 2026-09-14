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
    looks_like_pairing_code,
    normalize_pairing_code,
    should_show_on_state,
    window_view,
)

_MENU = _REPO / "icesee_hpc_connector" / "connector_menubar_app.py"
_WINDOW = _REPO / "icesee_hpc_connector" / "connector_window.py"

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


# ── pairing field behaves like a normal text field ────────────────────
def test_pairing_field_gets_first_responder_and_is_cleared_after_pairing():
    src = _WINDOW.read_text()
    # cursor lands in the field when the window shows in the code-entry state
    assert "makeFirstResponder_(self._field)" in src
    assert "if not self._field.isHidden():" in src
    # the code is wiped once we leave the entry state (post-pair / connecting)
    assert 'if not view["show_code_field"]:' in src
    assert 'self._field.setStringValue_("")' in src
    # explicit editable/selectable single-line config for paste + context menu
    assert "setEditable_(True)" in src and "setSelectable_(True)" in src


def test_app_installs_a_standard_edit_menu_for_clipboard_shortcuts():
    src = _MENU.read_text()
    darwin = src.split('if sys.platform == "darwin":')[1].split("# ====")[0]
    assert "_install_edit_menu(AppKit)" in darwin
    for sel in ('"cut:"', '"copy:"', '"paste:"', '"selectAll:"'):
        assert sel in darwin, sel
    assert "setMainMenu_(main)" in darwin
    # guarded against installing twice
    assert 'title() == "Edit"' in darwin
    # re-installed after the run loop starts (rumps builds NSApp late)
    assert "_edit_menu_ready" in darwin


@pytest.mark.parametrize("raw,norm", [
    ("  ABCDE-FGHJK \n", "ABCDE-FGHJK"),
    ("ABCDE-FGHJK", "ABCDE-FGHJK"),
    ("\tXY2P4-9MNQR\r\n", "XY2P4-9MNQR"),
    (None, ""),
])
def test_normalize_pairing_code_trims_transfer_noise(raw, norm):
    assert normalize_pairing_code(raw) == norm


@pytest.mark.parametrize("text,ok", [
    ("ABCDE-FGHJK", True),
    ("  abcde-fghjk  ", True),          # normalised + upper-cased
    ("ABCDEFGHJK", False),              # no dash
    ("ABCDE-FGHJKX", False),            # too long
    ("ABCD1-FGHJK", False),             # 1 is not in the alphabet
    ("hello world", False),
    ("", False),
    (None, False),
])
def test_looks_like_pairing_code_matches_only_the_code_shape(text, ok):
    assert looks_like_pairing_code(text) is ok


def test_pairing_prompts_prefill_only_a_code_shaped_clipboard():
    win = _WINDOW.read_text()
    menu = _MENU.read_text()
    # AppKit window: pre-fill on show, guarded by looks_like_pairing_code
    assert "_prefill_from_clipboard_if_code" in win
    assert "looks_like_pairing_code(text)" in win
    # rumps modal + tk dialog: default/initial value from a code-shaped clipboard
    assert "_clipboard_pairing_code()" in menu
    assert "default_text=_clipboard_pairing_code()" in menu
    assert "initialvalue=prefill" in menu


def test_window_has_an_explicit_paste_button_that_does_not_autosubmit():
    src = _WINDOW.read_text()
    assert "NSPasteboard.generalPasteboard()" in src
    assert '"onPaste:"' in src
    assert "_paste_from_clipboard" in src
    # the paste helper populates the field and never calls the submit path
    helper = src.split("def _paste_from_clipboard")[1].split("\n    def ")[0]
    assert "setStringValue_" in helper
    assert "_on_action" not in helper and "_fire(" not in helper
    # normalised before it lands in the field
    assert "normalize_pairing_code(" in helper
    # the Paste button is shown/hidden with the code field
    assert '_paste_btn.setHidden_(not view["show_code_field"])' in src


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
