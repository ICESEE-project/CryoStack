"""Run-local source-checkout plan + the generated checkout shell."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from cryostack_src.models.stack import (
    checkout_bind_suffix,
    checkout_setup_block,
    component_checkout_plan,
)
from cryostack_src.models.stack.runtime import StackRuntimeError

_SHA_A = "f7bcd21260beb97d8ecd011a22c3dbab5ee61026"
_SHA_B = "aced865cbecb385003d1ca98f6662e6945219bb1"


def _git_software(commit=_SHA_A, ref="main"):
    return {"icesee": {"source": "git", "requested_ref": ref, "resolved_commit": commit}}


# ── plan shape ─────────────────────────────────────────────────────────────
def test_image_only_software_yields_no_plan_no_binds_no_setup():
    sw = {"issm": {"source": "image", "resolved_commit": "e70338d8" * 5},
          "icesee": {"source": "image", "resolved_commit": None}}
    plan = component_checkout_plan(sw, "/run")
    assert plan == []
    assert checkout_setup_block(plan) == ""
    assert checkout_bind_suffix(plan) == ""


def test_git_component_binds_only_that_component_over_its_baked_path():
    plan = component_checkout_plan(_git_software(), "/run/x")
    assert len(plan) == 1
    c = plan[0]
    assert c.key == "icesee"
    assert c.repository == "https://github.com/ICESEE-project/ICESEE.git"
    assert c.commit == _SHA_A
    assert c.dest == "/run/x/.stack/icesee"
    assert c.bind_target == "/opt/ICESEE"
    assert checkout_bind_suffix(plan) == ',"/run/x/.stack/icesee":"/opt/ICESEE"'


# ── isolation ──────────────────────────────────────────────────────────────
def test_two_runs_use_different_run_local_stack_dirs():
    a = component_checkout_plan(_git_software(_SHA_A), "/base/runs/issm_container/A")
    b = component_checkout_plan(_git_software(_SHA_B), "/base/runs/issm_container/B")
    assert a[0].dest != b[0].dest
    assert a[0].dest.endswith("/A/.stack/icesee")
    assert b[0].dest.endswith("/B/.stack/icesee")


def test_checkout_is_fresh_each_run_never_reuses_stale_state():
    script = component_checkout_plan(_git_software(), "/run")[0].setup_script()
    assert "rm -rf /run/.stack/icesee" in script


# ── the generated checkout shell ──────────────────────────────────────────
def test_checkout_script_fetches_and_pins_the_exact_sha():
    script = component_checkout_plan(_git_software(_SHA_A), "/run")[0].setup_script()
    # exact commit fetched, with a full-history fallback
    assert f"fetch --no-tags --depth 1 origin {_SHA_A}" in script
    assert "'+refs/heads/*:refs/remotes/origin/*' '+refs/tags/*:refs/tags/*'" in script
    # detached checkout of the SHA / FETCH_HEAD -- never the branch name
    assert f"checkout -q --detach {_SHA_A}" in script
    assert "checkout -q --detach FETCH_HEAD" in script
    assert "checkout -q --detach main" not in script
    assert " main" not in script.replace("origin/main", "")  # no bare 'main'
    # post-checkout SHA verification
    assert 'rev-parse HEAD' in script
    assert f'if [ "$_have" != "{_SHA_A}" ]; then' in script


def test_checkout_failure_aborts_the_job_and_never_falls_back_to_the_image():
    script = component_checkout_plan(_git_software(), "/run")[0].setup_script()
    assert script.count("exit 3") >= 3            # every failure path aborts
    assert "[stack][ERROR]" in script
    # nothing that would silently use the baked copy
    assert "|| true" not in script.split("rev-parse HEAD")[0]
    assert "/opt/ICESEE" not in script            # the bind is separate; the
    # checkout script only ever touches the run-local dir
    assert "cp -r /opt" not in script


def test_checkout_script_only_uses_registry_url_and_validated_sha():
    # the only interpolated values are the registry repo and a 40-hex SHA
    plan = component_checkout_plan(_git_software(_SHA_A), "/run")
    script = plan[0].setup_script()
    assert "github.com/ICESEE-project/ICESEE.git" in script
    assert _SHA_A in script


# ── malformed input is rejected before submission ────────────────────────
def test_non_hex_resolved_commit_is_rejected():
    with pytest.raises(StackRuntimeError):
        component_checkout_plan({"icesee": {"source": "git", "resolved_commit": "main"}}, "/run")


def test_short_sha_is_rejected_only_full_40_hex_accepted():
    with pytest.raises(StackRuntimeError):
        component_checkout_plan({"icesee": {"source": "git", "resolved_commit": _SHA_A[:12]}}, "/run")


def test_unknown_component_key_is_rejected():
    with pytest.raises(StackRuntimeError):
        component_checkout_plan({"evil": {"source": "git", "resolved_commit": _SHA_A}}, "/run")


def test_compiled_component_cannot_be_source_overridden():
    with pytest.raises(StackRuntimeError):
        component_checkout_plan({"issm": {"source": "git", "resolved_commit": _SHA_A}}, "/run")


def test_shell_metacharacters_in_key_are_rejected():
    for bad in ("ice see", "icesee;rm -rf /", "../icesee", "ICESEE"):
        with pytest.raises(StackRuntimeError):
            component_checkout_plan({bad: {"source": "git", "resolved_commit": _SHA_A}}, "/run")
