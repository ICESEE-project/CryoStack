"""Compute-resource profiles: MATLAB licensing is a site property, not an image one."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from cryostack_src.resources.profiles import (
    ComputeProfile,
    get_compute_profile,
)

_PACE_VALUE = "1711@matlablic.ecs.gatech.edu"


def test_pace_profile_carries_the_gt_license_server():
    p = get_compute_profile("pace")
    assert p.has_matlab_license
    assert p.matlab_license_config() == {
        "env_var": "MLM_LICENSE_FILE",
        "value": _PACE_VALUE,
    }


def test_phoenix_is_the_same_gt_resource():
    assert get_compute_profile("Phoenix").matlab_license_config() == \
        get_compute_profile("pace").matlab_license_config()


def test_lookup_is_case_insensitive():
    assert get_compute_profile("  PACE  ").matlab_license_config()["value"] == _PACE_VALUE


def test_unknown_resource_has_no_matlab_license():
    p = get_compute_profile("ub-ccr")
    assert not p.has_matlab_license
    assert p.matlab_license_config() is None


def test_none_name_is_treated_as_unknown_not_pace():
    assert get_compute_profile(None).matlab_license_config() is None


def test_a_different_resource_can_declare_its_own_server():
    other = ComputeProfile(name="frontera", matlab_license_value="27000@license.tacc.utexas.edu")
    cfg = other.matlab_license_config()
    assert cfg == {"env_var": "MLM_LICENSE_FILE", "value": "27000@license.tacc.utexas.edu"}


def test_a_resource_can_use_a_different_env_var():
    other = ComputeProfile(
        name="x", matlab_license_env="LM_LICENSE_FILE", matlab_license_value="1234@lic"
    )
    assert other.matlab_license_config() == {"env_var": "LM_LICENSE_FILE", "value": "1234@lic"}


def test_invalid_env_var_name_is_rejected():
    with pytest.raises(ValueError):
        ComputeProfile(name="x", matlab_license_env="bad name", matlab_license_value="1@h")
