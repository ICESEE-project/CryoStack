"""resolve_stack() produces the authoritative manifest software/container block."""
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
    StackCompatError,
    resolve_stack,
    stack_log_line,
)

_MAIN_SHA = "f7bcd21260beb97d8ecd011a22c3dbab5ee61026"


def _ls_remote(repo, *patterns):
    if any(p.endswith("/main") for p in patterns):
        return f"{_MAIN_SHA}\trefs/heads/main\n"
    return ""


def _digest_resolver(ref):
    return "sha256:abcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabc00"


# ── tested profile: no network, image stack, honest unknowns ───────────────
def test_tested_issm_is_pure_image_no_network():
    calls = []
    out = resolve_stack(
        model="issm", profile=STACK_PROFILE_TESTED, selections=None,
        container_source="git", image_uri="",
        ls_remote=lambda *a, **k: (calls.append(a) or ""),
    )
    assert calls == []
    assert out["profile"] == "tested"
    assert set(out["software"]) == {"issm", "icesee"}

    issm = out["software"]["issm"]
    assert issm["source"] == "image"
    assert issm["resolved_commit"] == "e70338d8685f8582b61958211e8f5fce2ea686ff"
    assert issm["version"] == "2026.1 (self-reported)"
    assert issm["source_ref"] == "main snapshot"

    icesee = out["software"]["icesee"]
    assert icesee["source"] == "image"
    assert icesee["resolved_commit"] is None            # unknown, not inferred
    assert icesee["commit_status"] == "unknown-until-image-inspected"


def test_tested_icepack_model_stack_is_all_image():
    out = resolve_stack(
        model="icepack", profile=STACK_PROFILE_TESTED, selections=None,
        container_source="git", image_uri="",
    )
    assert set(out["software"]) == {"icepack", "firedrake", "icesee"}
    assert all(sw["source"] == "image" for sw in out["software"].values())
    assert out["software"]["firedrake"]["version"] == "2025.10.2"


# ── container identity is part of the contract ────────────────────────────
def test_git_container_records_immutable_build_provenance_not_a_fake_digest():
    out = resolve_stack(model="issm", profile=STACK_PROFILE_TESTED, selections=None,
                        container_source="git", image_uri="")
    c = out["container"]
    assert c["source"] == "git"
    assert c["digest"] is None
    bp = c["build_provenance"]
    assert bp["base_image"] == "docker.io/bkyanjo/combined-lean:v1.0"
    assert bp["base_image_digest"].startswith("sha256:e2dc1c0d")
    assert bp["definition"].endswith("combined-env-inbuilt-matlab.def")


def test_docker_container_anchors_on_resolved_digest():
    out = resolve_stack(
        model="issm", profile=STACK_PROFILE_TESTED, selections=None,
        container_source="docker", image_uri="ghcr.io/icesee-project/icesee-combined:latest",
        digest_resolver=_digest_resolver,
    )
    c = out["container"]
    assert c["source"] == "docker"
    assert c["digest"] == _digest_resolver(None)
    assert c["reference"].startswith("docker://")


def test_docker_container_without_digest_resolver_flags_the_gap():
    out = resolve_stack(
        model="issm", profile=STACK_PROFILE_TESTED, selections=None,
        container_source="docker", image_uri="bkyanjo/icesee-combined:v1.0.0",
    )
    c = out["container"]
    assert c["digest"] is None
    assert c["build_provenance"]["digest_status"] == "unresolved"
    assert c["build_provenance"]["requested_tag"] == "v1.0.0"


# ── custom profile: valid + invalid combinations ─────────────────────────
def test_custom_icesee_main_resolved_to_sha_and_recorded():
    out = resolve_stack(
        model="issm", profile=STACK_PROFILE_CUSTOM,
        selections={"icesee": ComponentSelection("icesee", "main")},
        container_source="git", image_uri="", ls_remote=_ls_remote,
    )
    icesee = out["software"]["icesee"]
    assert icesee["source"] == "git"
    assert icesee["requested_ref"] == "main"
    assert icesee["resolved_commit"] == _MAIN_SHA
    # issm still image in the same run
    assert out["software"]["issm"]["source"] == "image"


def test_custom_invalid_combo_raises_before_any_resolution():
    with pytest.raises(StackCompatError) as ei:
        resolve_stack(
            model="icepack", profile=STACK_PROFILE_CUSTOM,
            selections={"icepack": ComponentSelection("icepack", "ref", ref="v1.0.2")},
            container_source="git", image_uri="", ls_remote=_ls_remote,
        )
    assert "not validated with Firedrake 2025.10.2" in str(ei.value)


def test_custom_issm_override_raises():
    with pytest.raises(StackCompatError):
        resolve_stack(
            model="issm", profile=STACK_PROFILE_CUSTOM,
            selections={"issm": ComponentSelection("issm", "main")},
            container_source="git", image_uri="", ls_remote=_ls_remote,
        )


# ── log line is derived from the same structured provenance ──────────────
def test_stack_log_line_is_single_immutable_human_record():
    out = resolve_stack(
        model="issm", profile=STACK_PROFILE_CUSTOM,
        selections={"icesee": ComponentSelection("icesee", "main")},
        container_source="docker", image_uri="ghcr.io/x/icesee-combined:v1.0.0",
        digest_resolver=_digest_resolver, ls_remote=_ls_remote,
    )
    line = stack_log_line(out)
    assert line.startswith("[stack] custom")
    assert "sha256:abcabc" in line
    assert "issm=image" in line and "@e70338d8685f" in line
    assert "icesee=git" in line and "(main)" in line and _MAIN_SHA[:12] in line
