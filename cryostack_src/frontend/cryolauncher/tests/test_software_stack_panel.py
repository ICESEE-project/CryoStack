"""The Software versions panel: model-aware, locked components visible, default Tested."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryostack_src.frontend.cryolauncher.software_stack import build_software_stack_panel
from cryostack_src.models.stack import MODE_IMAGE, MODE_MAIN, MODE_REF, ComponentSelection


def _row_modes(panel, key):
    dd, _ref = panel._state["rows"][key]
    return [v[0] for _lbl, v in dd.options]


def test_default_profile_is_tested_and_selections_empty():
    p = build_software_stack_panel()
    assert p.profile() == "tested"
    assert p.selections() == {}


def test_issm_model_shows_issm_locked_and_icesee_selectable():
    p = build_software_stack_panel()          # defaults to issm
    assert set(p._state["rows"]) == {"issm", "icesee"}
    issm_dd = p._state["rows"]["issm"][0]
    assert _row_modes(p, "issm") == [MODE_IMAGE]     # locked
    assert issm_dd.disabled is True
    assert _row_modes(p, "icesee") == [MODE_IMAGE, MODE_MAIN, MODE_REF]


def test_icepack_model_shows_firedrake_locked_icepack_image_only_icesee_full():
    p = build_software_stack_panel()
    p.set_model("icepack")
    assert list(p._state["rows"]) == ["icepack", "firedrake", "icesee"]
    assert _row_modes(p, "firedrake") == [MODE_IMAGE]
    assert p._state["rows"]["firedrake"][0].disabled is True
    # no validated icepack compat entries -> image only, not the resolver's raw modes
    assert _row_modes(p, "icepack") == [MODE_IMAGE]
    assert _row_modes(p, "icesee") == [MODE_IMAGE, MODE_MAIN, MODE_REF]


def test_tested_disables_all_dropdowns_custom_enables_unlocked_only():
    p = build_software_stack_panel()
    p._state["profile"].value = "custom"
    assert p._state["rows"]["issm"][0].disabled is True      # still locked
    assert p._state["rows"]["icesee"][0].disabled is False   # now selectable
    p._state["profile"].value = "tested"
    assert p._state["rows"]["icesee"][0].disabled is True


def test_selections_reports_custom_icesee_main_and_ref():
    p = build_software_stack_panel()
    p._state["profile"].value = "custom"
    dd, ref = p._state["rows"]["icesee"]
    dd.value = (MODE_MAIN, None)
    assert p.selections() == {"icesee": ComponentSelection("icesee", MODE_MAIN, None)}
    dd.value = (MODE_REF, None)
    ref.value = "  2026.1 "
    assert p.selections() == {"icesee": ComponentSelection("icesee", MODE_REF, "2026.1")}


def test_switching_to_tested_clears_custom_selection():
    p = build_software_stack_panel()
    p._state["profile"].value = "custom"
    p._state["rows"]["icesee"][0].value = (MODE_MAIN, None)
    p._state["profile"].value = "tested"
    assert p.selections() == {}
    assert p._state["rows"]["icesee"][0].value == (MODE_IMAGE, None)
