"""Icepack Basic-mode parameter architecture (I1).

Evidence-based: the fixtures are the *real* upstream Icepack tutorial notebooks
when present on this machine, else small hand-built stand-ins with the exact
assignment forms observed in them.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cryostack_src.models import icepack
from cryostack_src.models.icepack import parameters as P

_ICEPACK_NB = Path("/home/bkyanjo3/icepack/notebooks/tutorials")


def _nb(cells: list[str]) -> str:
    return json.dumps({
        "cells": [{"cell_type": "code", "source": (c + "\n").splitlines(keepends=True)}
                  for c in cells],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    })


# ── classification is complete and sane ───────────────────────────────
def test_every_curated_parameter_is_classified_and_named_neutrally():
    for p in icepack.CURATED_ICEPACK_PARAMETERS:
        assert p.category in P._ALL_CATEGORIES
        # no ISSM vocabulary leaks in
        for issm in ("md.", "stressbalance", "requested_outputs", "rheology_B",
                     "friction.coefficient", "TransientSolution"):
            assert issm not in p.name and issm not in p.source_variable
        if p.category == P.CATEGORY_SAFE:
            assert p.assignment_pattern and p.minimum is not None and p.evidence


def test_only_safe_scalars_are_basic_mode_overridable():
    names = {p.name for p in icepack.BASIC_MODE_PARAMETERS}
    assert names == {"ice_temperature", "num_timesteps"}
    assert icepack.classify("fluidity_A") == P.CATEGORY_DERIVED
    assert icepack.classify("accumulation") == P.CATEGORY_UNSAFE
    assert icepack.classify("timestep_size") == P.CATEGORY_ADVANCED
    assert icepack.classify("mesh_resolution") == P.CATEGORY_UNKNOWN


# ── validation fails before submission ───────────────────────────────
@pytest.mark.parametrize("cfg,ok", [
    ({"ice_temperature": 255.15}, True),
    ({"ice_temperature": 260, "num_timesteps": 100}, True),
    ({"ice_temperature": 300}, False),           # above pressure-melting point
    ({"ice_temperature": 150}, False),           # below floor
    ({"ice_temperature": "warm"}, False),        # wrong type
    ({"num_timesteps": 0}, False),               # below minimum
    ({"num_timesteps": 3.5}, True),              # coerced to int 3
    ({"fluidity_A": 1.0}, False),                # derived -> not overridable
    ({"accumulation": 0.3}, False),              # unsafe generic
    ({"nonsense": 1}, False),                    # unknown key
])
def test_validate_icepack_config(cfg, ok):
    assert icepack.validate_icepack_config(cfg)["ok"] is ok


def test_apply_overrides_rejects_invalid_before_touching_source():
    with pytest.raises(P.IcepackParameterError):
        icepack.apply_overrides(_nb(["T = firedrake.Constant(255.0)"]),
                                {"ice_temperature": 999})


# ── the in-place substitution ────────────────────────────────────────
def test_temperature_override_is_a_single_exact_line_change():
    src = _nb([
        "import firedrake",
        "T = firedrake.Constant(255.15)\nA = icepack.rate_factor(T)",
        "num_timesteps = 200\nfor step in range(num_timesteps):\n    pass",
    ])
    out, prov = icepack.apply_overrides(src, {"ice_temperature": 260, "num_timesteps": 50})
    nb = json.loads(out)
    changed = [c for c in nb["cells"] if "CryoStack Basic-mode override" in "".join(c["source"])]
    assert len(changed) == 2
    body = "\n".join("".join(c["source"]) for c in nb["cells"])
    assert "T = firedrake.Constant(260.0)  # CryoStack Basic-mode override" in body
    assert "num_timesteps = 50  # CryoStack Basic-mode override" in body
    assert "A = icepack.rate_factor(T)" in body            # untouched
    assert {p["name"] for p in prov} == {"ice_temperature", "num_timesteps"}
    assert prov[0]["canonical"].startswith("T = firedrake.Constant(255.15)")


def test_no_overrides_returns_source_unchanged():
    src = _nb(["T = firedrake.Constant(255.0)"])
    out, prov = icepack.apply_overrides(src, {})
    assert out == src and prov == []


def test_example_without_the_parameter_fails_closed():
    src = _nb(["mesh = firedrake.UnitSquareMesh(8, 8)"])   # no T, no num_timesteps
    with pytest.raises(P.IcepackOverrideError):
        icepack.apply_overrides(src, {"ice_temperature": 260})


def test_ambiguous_assignment_is_refused_not_guessed():
    src = _nb(["T = firedrake.Constant(255.0)", "T = firedrake.Constant(260.0)"])
    with pytest.raises(P.IcepackOverrideError):
        icepack.apply_overrides(src, {"ice_temperature": 250})


def test_plain_python_script_path():
    src = "import firedrake\nT = Constant(255.0)\nprint('done')\n"
    out, prov = icepack.apply_overrides(src, {"ice_temperature": 258}, is_notebook=False)
    assert "T = firedrake.Constant(258.0)  # CryoStack Basic-mode override" in out
    assert "print('done')" in out
    assert prov[0]["location"] == "script"


def test_entrypoint_transform_helper_matches_stage_example_signature():
    tx = icepack.entrypoint_transform_for({"ice_temperature": 261})
    out = tx(_nb(["T = firedrake.Constant(255.0)"]))
    assert "Constant(261.0)" in out


# ── against the real notebooks, when available ───────────────────────
@pytest.mark.skipif(not _ICEPACK_NB.is_dir(), reason="upstream icepack checkout absent")
@pytest.mark.parametrize("stem", ["02-synthetic-ice-shelf", "04-synthetic-ice-stream-xy"])
def test_real_tutorial_temperature_override_applies(stem):
    # 02 and 04 both use `T = firedrake.Constant(<literal>)`
    src = (_ICEPACK_NB / f"{stem}.ipynb").read_text()
    out, prov = icepack.apply_overrides(src, {"ice_temperature": 262})
    assert json.loads(out)                       # still valid notebook JSON
    assert any(p["name"] == "ice_temperature" for p in prov)
    assert "Constant(262.0)" in out


@pytest.mark.skipif(not _ICEPACK_NB.is_dir(), reason="upstream icepack checkout absent")
def test_real_ice_sheet_rejects_temperature_expression():
    # 01 uses `T = Constant(273.15 - 5)` -- an expression, not a literal:
    # the conservative regex correctly refuses rather than corrupt it.
    src = (_ICEPACK_NB / "01-synthetic-ice-sheet.ipynb").read_text()
    with pytest.raises(P.IcepackOverrideError):
        icepack.apply_overrides(src, {"ice_temperature": 260})


@pytest.mark.skipif(not _ICEPACK_NB.is_dir(), reason="upstream icepack checkout absent")
def test_real_ice_stream_rejects_num_timesteps_override():
    src = (_ICEPACK_NB / "04-synthetic-ice-stream-xy.ipynb").read_text()
    # 04 derives num_timesteps = num_years * timesteps_per_year -> no literal
    with pytest.raises(P.IcepackOverrideError):
        icepack.apply_overrides(src, {"num_timesteps": 10})
