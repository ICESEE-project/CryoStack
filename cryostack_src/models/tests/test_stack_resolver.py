"""A version choice must normalise to an immutable commit SHA before submission.

All git resolution is done through an injected ``ls_remote`` so these tests are
offline.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from cryostack_src.models.stack import COMPONENTS, ComponentChoice, resolve_component
from cryostack_src.models.stack.resolver import ComponentResolutionError

ICESEE = COMPONENTS["icesee"]
ICEPACK = COMPONENTS["icepack"]
ISSM = COMPONENTS["issm"]

_MAIN_SHA = "f7bcd21260beb97d8ecd011a22c3dbab5ee61026"
_TAG_SHA = "aced865cbecb385003d1ca98f6662e6945219bb1"
_BR_SHA = "1111111111111111111111111111111111111111"


def fake_ls_remote(calls):
    def _run(repo, *patterns):
        calls.append((repo, patterns))
        pats = set(patterns)
        if "--tags" in pats:
            return (
                f"{_TAG_SHA}\trefs/tags/2026.1\n"
                f"0b8f332d121a5464339f0b7cfe0e478cdcf1821f\trefs/tags/2026.3\n"
                f"7c9d257080c47de5062aa92cf55fbeb1b75933fe\trefs/tags/v4.24\n"
            )
        if any(p.endswith("/main") or p.endswith("/master") for p in patterns):
            branch = patterns[0].rsplit("/", 1)[-1]
            return f"{_MAIN_SHA}\trefs/heads/{branch}\n"
        if any(p == "refs/tags/2026.1" for p in patterns):
            return f"{_TAG_SHA}\trefs/tags/2026.1\n"
        if any(p == "refs/heads/experimental" for p in patterns):
            return f"{_BR_SHA}\trefs/heads/experimental\n"
        return ""
    return _run


# ── image mode: never touches the network ───────────────────────────────────
def test_image_mode_does_not_resolve_and_keeps_unknown_commit():
    calls: list = []
    r = resolve_component(ICESEE, ComponentChoice("icesee", "image"),
                          ls_remote=fake_ls_remote(calls))
    assert calls == []            # no network
    assert r.source == "image"
    assert r.requested_ref is None
    assert r.resolved_commit is None      # honest unknown
    assert r.commit_known is False
    p = r.as_provenance()
    assert p["resolved_commit"] is None
    assert p["commit_status"] == "unknown-until-image-inspected"
    assert p["version"] == "0.1.9"


def test_image_mode_issm_keeps_corrected_provenance():
    r = resolve_component(ISSM, ComponentChoice("issm", "image"), ls_remote=fake_ls_remote([]))
    p = r.as_provenance()
    assert p == {
        "source": "image",
        "requested_ref": None,
        "resolved_commit": "e70338d8685f8582b61958211e8f5fce2ea686ff",
        "version": "2026.1 (self-reported)",
        "source_ref": "main snapshot",
        "repository": "https://github.com/ISSMteam/ISSM.git",
        "resolved_via": "image",
    }


# ── main / ref / latest -> immutable SHA ────────────────────────────────────
def test_main_resolves_to_sha_and_records_both():
    calls: list = []
    r = resolve_component(ICESEE, ComponentChoice("icesee", "main"),
                          ls_remote=fake_ls_remote(calls))
    assert calls and calls[0][1] == ("refs/heads/main",)
    assert r.requested_ref == "main"
    assert r.resolved_commit == _MAIN_SHA
    p = r.as_provenance()
    assert p["requested_ref"] == "main" and p["resolved_commit"] == _MAIN_SHA


def test_specific_tag_ref_resolves_to_tag_sha():
    r = resolve_component(ICESEE, ComponentChoice("icesee", "ref", ref="2026.1"),
                          ls_remote=fake_ls_remote([]))
    assert r.requested_ref == "2026.1"
    assert r.resolved_commit == _TAG_SHA
    assert r.version == "2026.1"


def test_specific_branch_ref_resolves_to_branch_sha():
    r = resolve_component(ICESEE, ComponentChoice("icesee", "ref", ref="experimental"),
                          ls_remote=fake_ls_remote([]))
    assert r.resolved_commit == _BR_SHA
    assert r.version is None


def test_full_sha_ref_passes_through_immutably_without_network():
    calls: list = []
    sha = "0123456789abcdef0123456789abcdef01234567"
    r = resolve_component(ICESEE, ComponentChoice("icesee", "ref", ref=sha),
                          ls_remote=fake_ls_remote(calls))
    assert calls == []
    assert r.requested_ref == sha and r.resolved_commit == sha
    assert r.resolved_via == "user-sha"


def test_latest_picks_newest_semverish_tag():
    r = resolve_component(ICEPACK, ComponentChoice("icepack", "latest"),
                          ls_remote=fake_ls_remote([]))
    assert r.resolved_commit == "0b8f332d121a5464339f0b7cfe0e478cdcf1821f"  # 2026.3
    assert r.requested_ref == "2026.3"


# ── invalid requests ───────────────────────────────────────────────────────
def test_locked_component_rejects_non_image_mode():
    with pytest.raises(ComponentResolutionError):
        resolve_component(ISSM, ComponentChoice("issm", "main"), ls_remote=fake_ls_remote([]))


def test_unsupported_mode_rejected():
    with pytest.raises(ComponentResolutionError):
        resolve_component(ICESEE, ComponentChoice("icesee", "latest"), ls_remote=fake_ls_remote([]))


def test_ref_mode_requires_a_ref():
    with pytest.raises(ComponentResolutionError):
        resolve_component(ICESEE, ComponentChoice("icesee", "ref", ref=""), ls_remote=fake_ls_remote([]))


def test_unknown_ref_raises():
    with pytest.raises(ComponentResolutionError):
        resolve_component(
            ICESEE, ComponentChoice("icesee", "ref", ref="no-such-thing"),
            ls_remote=lambda *a: "",
        )
