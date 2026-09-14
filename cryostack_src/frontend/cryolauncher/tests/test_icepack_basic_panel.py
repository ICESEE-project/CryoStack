"""The Basic-mode Icepack panel (I1 gateway layer)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

from cryostack_src.frontend.cryolauncher.icepack_basic_panel import build_icepack_basic_panel


def test_panel_exposes_only_the_two_curated_parameters():
    p = build_icepack_basic_panel()
    assert set(p._rows) == {"ice_temperature", "num_timesteps"}


def test_rows_are_opt_in_and_disabled_until_checked():
    p = build_icepack_basic_panel()
    assert p.overrides() == {}
    en, ctl = p._rows["ice_temperature"]
    assert ctl.disabled is True
    en.value = True
    assert ctl.disabled is False
    ctl.value = 261.0
    assert p.overrides() == {"ice_temperature": 261.0}


def test_validate_delegates_to_the_adapter_and_bounds_apply():
    p = build_icepack_basic_panel()
    en, ctl = p._rows["ice_temperature"]
    en.value = True
    ctl.value = 260.0
    v = p.validate()
    assert v.ok and v.normalized == {"ice_temperature": 260.0}
    # the BoundedFloatText clamps below the curated minimum
    ctl.value = 100.0
    assert ctl.value >= 200.0


def test_bounded_control_ranges_come_from_the_spec():
    p = build_icepack_basic_panel()
    _, temp = p._rows["ice_temperature"]
    assert temp.min == 200.0 and temp.max == 273.15
    _, steps = p._rows["num_timesteps"]
    assert steps.min == 1


def test_set_example_and_set_visible_are_safe_noops():
    p = build_icepack_basic_panel()
    p.set_example("/whatever")
    p.set_visible(False)
    p.set_visible(True)
