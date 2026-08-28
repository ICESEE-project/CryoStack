"""Compatibility authority: only trusted stack combinations are submittable."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from cryostack_src.models.stack import (
    STACK_PROFILE_CUSTOM,
    STACK_PROFILE_TESTED,
    ComponentSelection,
    offered_options,
    validate_stack,
)
from cryostack_src.models.stack.compat import ICEPACK_FIREDRAKE_COMPAT


def _verdict(v, key):
    return next(x for x in v.verdicts if x.key == key)


# ── tested profile: image stack, ignores stray selections ──────────────────
def test_tested_profile_is_always_ok_and_ignores_selections():
    v = validate_stack(
        model="issm", profile=STACK_PROFILE_TESTED,
        selections={"icesee": ComponentSelection("icesee", "main")},
    )
    assert v.ok
    assert all(x.ok for x in v.verdicts)


# ── custom profile: locked components ──────────────────────────────────────
def test_custom_issm_locked_to_image():
    v = validate_stack(
        model="issm", profile=STACK_PROFILE_CUSTOM,
        selections={"issm": ComponentSelection("issm", "main")},
    )
    assert not v.ok
    d = _verdict(v, "issm")
    assert d.locked and not d.ok
    assert "another container image" in d.reason


def test_custom_firedrake_locked_to_image():
    v = validate_stack(
        model="icepack", profile=STACK_PROFILE_CUSTOM,
        selections={"firedrake": ComponentSelection("firedrake", "ref", ref="2025.12.0")},
    )
    assert not v.ok
    assert _verdict(v, "firedrake").locked


# ── custom profile: ICESEE source overrides are allowed ────────────────────
def test_custom_icesee_main_and_ref_allowed():
    for sel in (ComponentSelection("icesee", "main"),
                ComponentSelection("icesee", "ref", ref="2026.1")):
        v = validate_stack(model="issm", profile=STACK_PROFILE_CUSTOM,
                           selections={"icesee": sel})
        assert v.ok, sel


def test_custom_icesee_ref_without_value_blocked():
    v = validate_stack(model="issm", profile=STACK_PROFILE_CUSTOM,
                       selections={"icesee": ComponentSelection("icesee", "ref", ref="")})
    assert not v.ok


# ── custom profile: Icepack blocked unless a compat entry exists ───────────
def test_custom_icepack_non_image_blocked_without_compat_entry():
    v = validate_stack(
        model="icepack", profile=STACK_PROFILE_CUSTOM,
        selections={"icepack": ComponentSelection("icepack", "ref", ref="v1.0.2")},
    )
    assert not v.ok
    d = _verdict(v, "icepack")
    assert not d.locked  # it's overridable in principle, just not validated here
    assert "not validated with Firedrake 2025.10.2" in d.reason
    assert "compatible container image is required" in d.reason


def test_custom_icepack_ref_allowed_when_compat_entry_present(monkeypatch):
    monkeypatch.setitem(ICEPACK_FIREDRAKE_COMPAT, "2025.10.2", frozenset({"v1.0.2"}))
    v = validate_stack(
        model="icepack", profile=STACK_PROFILE_CUSTOM,
        selections={"icepack": ComponentSelection("icepack", "ref", ref="v1.0.2")},
    )
    assert v.ok
    assert _verdict(v, "icepack").ok


def test_custom_icepack_image_always_ok():
    v = validate_stack(model="icepack", profile=STACK_PROFILE_CUSTOM,
                       selections={"icepack": ComponentSelection("icepack", "image")})
    assert v.ok


# ── never implies a silent Firedrake upgrade ──────────────────────────────
def test_icepack_override_never_touches_firedrake_verdict():
    v = validate_stack(
        model="icepack", profile=STACK_PROFILE_CUSTOM,
        selections={"icepack": ComponentSelection("icepack", "latest")},
    )
    assert _verdict(v, "firedrake").ok      # firedrake stays image, untouched
    assert not _verdict(v, "icepack").ok


# ── offered_options: what the UI may present ──────────────────────────────
def test_offered_options_issm_image_only_but_visible():
    opts = offered_options("issm")
    assert [o.mode for o in opts] == ["image"]
    assert "2026.1" in opts[0].label


def test_offered_options_firedrake_image_only():
    assert [o.mode for o in offered_options("firedrake")] == ["image"]
    assert "2025.10.2" in offered_options("firedrake")[0].label


def test_offered_options_icesee_full():
    assert [o.mode for o in offered_options("icesee")] == ["image", "main", "ref"]


def test_offered_options_icepack_image_only_until_compat_entries(monkeypatch):
    assert [o.mode for o in offered_options("icepack")] == ["image"]
    monkeypatch.setitem(ICEPACK_FIREDRAKE_COMPAT, "2025.10.2", frozenset({"v1.0.2"}))
    opts = offered_options("icepack")
    assert opts[0].mode == "image"
    assert any(o.ref == "v1.0.2" for o in opts[1:])
