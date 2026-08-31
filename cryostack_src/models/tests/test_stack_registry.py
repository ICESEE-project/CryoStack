"""The component registry must state verified facts and honest unknowns."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryostack_src.models.stack import (
    COMPILED,
    COMPONENTS,
    ENVIRONMENT_SENSITIVE,
    MODEL_COMPONENTS,
    MODE_IMAGE,
    OVERRIDE_BIND,
    OVERRIDE_NONE,
    SOURCE_OVERRIDABLE,
    components_for_model,
)


def test_four_components_registered():
    assert set(COMPONENTS) == {"issm", "icesee", "icepack", "firedrake"}


def test_model_component_mapping_and_order():
    assert MODEL_COMPONENTS["issm"] == ("issm", "icesee")
    assert MODEL_COMPONENTS["icepack"] == ("icepack", "firedrake", "icesee")
    assert [c.key for c in components_for_model("ISSM")] == ["issm", "icesee"]


def test_issm_is_compiled_and_locked_with_corrected_provenance():
    issm = COMPONENTS["issm"]
    assert issm.update_class == COMPILED
    assert issm.override == OVERRIDE_NONE
    assert issm.modes == (MODE_IMAGE,)
    assert issm.locked is True
    # provenance correction: e70338d8 is NOT the 2026.1 tag commit
    assert issm.baked_commit == "e70338d8685f8582b61958211e8f5fce2ea686ff"
    assert issm.baked_version == "2026.1 (self-reported)"
    assert issm.baked_source_ref == "main snapshot"


def test_firedrake_is_environment_sensitive_and_locked():
    fd = COMPONENTS["firedrake"]
    assert fd.update_class == ENVIRONMENT_SENSITIVE
    assert fd.override == OVERRIDE_NONE
    assert fd.modes == (MODE_IMAGE,)
    assert fd.baked_version == "2025.10.2"
    assert fd.baked_commit is None  # PyPI release, no git checkout in the image


def test_icesee_is_source_overridable_no_latest_mode():
    ic = COMPONENTS["icesee"]
    assert ic.update_class == SOURCE_OVERRIDABLE
    assert ic.override == OVERRIDE_BIND
    assert ic.modes == ("image", "main", "ref")   # no "latest" — no releases upstream
    assert ic.baked_version == "0.1.9"
    assert ic.baked_commit is None  # UNKNOWN — must not be inferred from build date


def test_icepack_is_source_overridable_but_gated_by_firedrake():
    ip = COMPONENTS["icepack"]
    assert ip.update_class == SOURCE_OVERRIDABLE
    assert ip.gated_by == "firedrake"
    assert ip.default_branch == "master"
    assert ip.baked_commit is None  # UNKNOWN


def test_no_component_has_an_inferred_commit():
    # only ISSM's SHA is a hard fact (recovered from PACE); the rest are unknown
    known = {k: c.baked_commit for k, c in COMPONENTS.items() if c.baked_commit}
    assert known == {"issm": "e70338d8685f8582b61958211e8f5fce2ea686ff"}


def test_locked_components_carry_a_lock_note():
    for key in ("issm", "firedrake"):
        assert COMPONENTS[key].lock_note
