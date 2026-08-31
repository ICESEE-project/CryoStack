"""Basic-mode ISSM md configuration: solver detection, validation, MATLAB gen."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryostack_src.models.issm.md_config import (
    OVERRIDE_SCRIPT_NAME,
    build_md_override_script,
    curated_parameters_for,
    detect_solvers,
    inject_override_step,
    validate_md_config,
)

_SB = "md=model;\nmd=parameterize(md,'Square.par');\nmd=solve(md,'Stressbalance');\n"
_TR = "md=solve(md,'Stressbalance');\nmd=solve(md,'Transient');\n"


# ── solver detection ────────────────────────────────────────────────────────
def test_detects_stressbalance_and_alias_sb():
    assert detect_solvers("md=solve(md,'Stressbalance');") == ("stressbalance",)
    assert detect_solvers("x=solve(md , 'sb' )") == ("stressbalance",)


def test_detects_multiple_solvers_in_order():
    assert detect_solvers(_TR) == ("stressbalance", "transient")


def test_no_solver_when_none_present():
    assert detect_solvers("md=triangle(md,'x.exp',5000);") == ()


# ── curated parameter gating ───────────────────────────────────────────────
def test_only_solver_relevant_parameters_are_offered():
    sb = {p.key for p in curated_parameters_for(("stressbalance",))}
    assert "stressbalance.restol" in sb
    assert "friction.coefficient" in sb
    assert "timestepping.time_step" not in sb          # transient-only
    assert "transient.isthermal" not in sb

    tr = {p.key for p in curated_parameters_for(("transient",))}
    assert "timestepping.final_time" in tr
    assert "transient.isthermal" in tr


def test_no_parameters_when_no_solver():
    assert curated_parameters_for(()) == ()


# ── validation ─────────────────────────────────────────────────────────────
def test_valid_config_normalizes_types():
    v = validate_md_config(
        {"stressbalance.maxiter": "150", "stressbalance.restol": 1e-6,
         "friction.coefficient": 1.5},
        solvers=("stressbalance",),
    )
    assert v.ok
    assert v.normalized == {
        "stressbalance.maxiter": 150,
        "stressbalance.restol": 1e-6,
        "friction.coefficient": 1.5,
    }


def test_out_of_range_is_rejected_with_a_clear_message():
    v = validate_md_config({"stressbalance.maxiter": 99999}, solvers=("stressbalance",))
    assert not v.ok
    assert "above maximum" in v.errors[0]


def test_non_integer_for_int_field_is_rejected():
    v = validate_md_config({"stressbalance.maxiter": 10.5}, solvers=("stressbalance",))
    assert not v.ok


def test_parameter_not_applicable_to_selected_solver_is_rejected():
    v = validate_md_config({"transient.isthermal": True}, solvers=("stressbalance",))
    assert not v.ok
    assert "not applicable" in v.errors[0]


def test_unknown_key_is_rejected():
    v = validate_md_config({"geometry.surface": 5}, solvers=("stressbalance",))
    assert not v.ok


def test_noop_multiplier_is_dropped():
    v = validate_md_config({"friction.coefficient": 1.0}, solvers=("stressbalance",))
    assert v.ok and v.normalized == {}


def test_bool_accepts_on_off_and_truthy_strings():
    v = validate_md_config(
        {"transient.isstressbalance": "off", "transient.ismasstransport": True},
        solvers=("transient",),
    )
    assert v.ok
    assert v.normalized == {
        "transient.isstressbalance": False,
        "transient.ismasstransport": True,
    }


def test_outputs_only_from_the_whitelist():
    ok = validate_md_config(
        {"transient.requested_outputs": ["IceVolume", "TotalSmb"]}, solvers=("transient",)
    )
    assert ok.ok and ok.normalized["transient.requested_outputs"] == ["IceVolume", "TotalSmb"]

    bad = validate_md_config(
        {"transient.requested_outputs": ["md.geometry.surface"]}, solvers=("transient",)
    )
    assert not bad.ok


# ── MATLAB generation ──────────────────────────────────────────────────────
def test_override_script_uses_fixed_templates_no_raw_expression():
    script = build_md_override_script({
        "stressbalance.maxiter": 200,
        "friction.coefficient": 2.0,
        "materials.rheology_B": 0.8,
        "transient.isthermal": True,
        "transient.requested_outputs": ["IceVolume"],
    })
    assert "md.stressbalance.maxiter = 200;" in script
    assert "md.friction.coefficient = md.friction.coefficient .* 2.0;" in script     # transform, not replace
    assert "md.materials.rheology_B = md.materials.rheology_B .* 0.8;" in script
    assert "md.transient.isthermal = 1;" in script
    assert "'IceVolume'" in script
    assert "error('[cryostack] md is not defined yet')" in script
    # never a bare "md.<x> = md.<x>;" self-assignment path, never a user string
    assert "md.geometry" not in script


def test_small_numbers_render_as_valid_matlab():
    s = build_md_override_script({"stressbalance.restol": 1e-9})
    assert "md.stressbalance.restol = 1e-09;" in s or "md.stressbalance.restol = 1e-9;" in s


# ── injection ──────────────────────────────────────────────────────────────
def test_injects_run_call_before_first_solve_preserving_indent():
    out = inject_override_step("  a=1;\n  md = solve(md,'Stressbalance');\n")
    lines = out.splitlines()
    assert lines[1] == f"  run('{OVERRIDE_SCRIPT_NAME}');"
    assert "solve" in lines[2]


def test_injection_is_idempotent():
    once = inject_override_step(_SB)
    twice = inject_override_step(once)
    assert once == twice
    assert once.count(OVERRIDE_SCRIPT_NAME) == 1


def test_injection_before_the_first_of_several_solves():
    out = inject_override_step(_TR)
    body = out.splitlines()
    assert body[0] == f"run('{OVERRIDE_SCRIPT_NAME}');"
    assert body.count(f"run('{OVERRIDE_SCRIPT_NAME}');") == 1


def test_no_solve_appends_the_call():
    out = inject_override_step("md=model;\nmd=triangle(md,'x.exp',5000);\n")
    assert out.rstrip().endswith(f"run('{OVERRIDE_SCRIPT_NAME}');")
