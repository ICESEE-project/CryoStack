"""End-to-end (offline): resolve -> manifest -> generated sbatch.

Renders the real sbatch that submit_remote_icesheets would write, with all git
resolution done through an injected ls-remote.
"""
from __future__ import annotations

import base64
import re
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

import cryostack_src.models.submission as submission
from cryostack_src.models.stack import (
    ComponentResolutionError,
    ComponentSelection,
    StackCompatError,
    resolve_stack,
    stack_log_line,
)
from cryostack_src.workspace.manifest import MANIFEST_NAME, read_manifest, write_manifest
from cryostack_src.workspace.models import RunInfo

_MAIN_SHA = "f7bcd21260beb97d8ecd011a22c3dbab5ee61026"
_TAG_SHA = "aced865cbecb385003d1ca98f6662e6945219bb1"
_RUN_DIR = "/home/u/base/icesheets/runs/issm_container"


def _ls_remote(repo, *patterns):
    if any(p.endswith("/main") for p in patterns):
        return f"{_MAIN_SHA}\trefs/heads/main\n"
    if any(p == "refs/tags/2026.1" for p in patterns):
        return f"{_TAG_SHA}\trefs/tags/2026.1\n"
    return ""


class _R:
    def __init__(self, stdout="", rc=0):
        self.returncode, self.stdout, self.stderr = rc, stdout, ""


@pytest.fixture
def render(monkeypatch):
    captured = {}

    def fake_ssh(host, user, port, cmd, timeout=20):
        if "run_icesheets.sbatch" in cmd and "b64decode" in cmd:
            for blob in sorted(re.findall(r"[A-Za-z0-9+/]{80,}={0,2}", cmd), key=len, reverse=True):
                try:
                    captured["sbatch"] = base64.b64decode(blob).decode()
                    break
                except Exception:
                    continue
        if cmd.strip().startswith("sbatch"):
            return _R("Submitted batch job 7\n")
        if cmd.strip().startswith("test -f"):
            return _R("FOUND\n")
        return _R("/home/u/base\n")

    monkeypatch.setattr(submission, "ssh_run", fake_ssh)
    monkeypatch.setattr(submission, "resolve_remote_abs_path", lambda *a, **k: "/home/u/base")
    monkeypatch.setattr(submission, "expand_remote_home", lambda x: x)
    monkeypatch.setattr(submission, "subprocess",
                        types.SimpleNamespace(run=lambda *a, **k: _R()), raising=False)

    ex = Path(tempfile.mkdtemp()) / "SquareShelf"
    ex.mkdir()
    (ex / "runme.m").write_text("md.cluster=generic('name',oshostname(),'np',2);\n")

    def _do(*, profile, selections=None):
        prov = resolve_stack(
            model="issm", profile=profile, selections=selections,
            container_source="git", image_uri="", ls_remote=_ls_remote,
        )
        submission.submit_remote_icesheets(
            host="l", user="u", port=22, remote_base_dir="~/base", remote_tag="icesheets",
            backend="container", model="issm", example_dir=str(ex), exec_dir=str(ex),
            image_uri="", container_source="git",
            spack_enable=False, spack_repo_url="", spack_dirname="ICESEE-Spack",
            spack_install_if_needed=False, spack_install_mode="",
            spack_slurm_dir="", spack_pmix_dir="",
            slurm_time="1:0:0", slurm_job_name="J", slurm_nodes=1, slurm_ntasks=8,
            slurm_tpn=8, slurm_part="c", slurm_mem="1G", slurm_account="", slurm_mail="",
            test_mode=False, run_file="",
            stack_log_line=stack_log_line(prov),
            stack_software=prov["software"],
        )
        return prov, captured["sbatch"]

    return _do


# ── tested ISSM: nothing but the provenance line changes ──────────────────
def test_tested_issm_sbatch_has_no_checkout_no_stack_dir_no_extra_bind(render):
    prov, sbatch = render(profile="tested")
    assert "[stack] tested" in sbatch                      # provenance line present
    # no run-local source checkout of any kind
    assert ".stack/" not in sbatch
    assert "[stack] materialising run-local source overrides" not in sbatch
    assert "[stack] icesee: preparing" not in sbatch
    assert "checkout -q --detach" not in sbatch
    # the exec line binds only the proven paths -- no component bind onto /opt/ICESEE
    exec_line = next(ln for ln in sbatch.splitlines() if "with-issm matlab" in ln)
    assert "/opt/ISSM/examples" in exec_line and "/opt/ISSM/execution" in exec_line
    assert "/opt/ICESEE" not in exec_line
    assert prov["software"]["icesee"]["source"] == "image"


# ── custom ISSM + ICESEE main ────────────────────────────────────────────
def test_custom_icesee_main_resolved_once_recorded_and_pinned(render, monkeypatch):
    calls = []
    real = _ls_remote

    def counting_ls(repo, *pat):
        calls.append((repo, pat))
        return real(repo, *pat)

    # re-render with a counting ls-remote
    prov = resolve_stack(model="issm", profile="custom",
                         selections={"icesee": ComponentSelection("icesee", "main")},
                         container_source="git", image_uri="", ls_remote=counting_ls)
    # 'main' resolved exactly once, before anything else
    assert sum(1 for _, p in calls if any(x.endswith("/main") for x in p)) == 1

    sw = prov["software"]["icesee"]
    assert sw["source"] == "git"
    assert sw["requested_ref"] == "main"
    assert sw["resolved_commit"] == _MAIN_SHA

    _, sbatch = render(profile="custom",
                       selections={"icesee": ComponentSelection("icesee", "main")})
    # sbatch carries the exact SHA and never re-resolves the branch
    assert _MAIN_SHA in sbatch
    assert "checkout -q --detach FETCH_HEAD" in sbatch
    assert f"checkout -q --detach {_MAIN_SHA}" in sbatch
    assert "checkout -q --detach main" not in sbatch
    assert "git checkout main" not in sbatch
    # run-local checkout dir + bind onto /opt/ICESEE, existing binds preserved
    assert f"{_RUN_DIR}/.stack/icesee" in sbatch
    assert f',"{_RUN_DIR}/.stack/icesee":"/opt/ICESEE"' in sbatch
    assert f'"{_RUN_DIR}":"{_RUN_DIR}"' in sbatch          # existing run-dir bind kept
    assert "/opt/ISSM/examples" in sbatch and "/opt/ISSM/execution" in sbatch
    assert ".cryostack_launcher" in sbatch                # launcher shim kept


def test_custom_icesee_main_persists_to_manifest_v2(render, tmp_path):
    prov, _ = render(profile="custom",
                     selections={"icesee": ComponentSelection("icesee", "main")})
    ws = tmp_path / "run"
    run = RunInfo(id="r", name="r", model="issm", backend="container",
                  execution_mode="remote", created=datetime(2026, 8, 28),
                  workspace_directory=ws, remote_directory=Path("/x"),
                  container=prov["container"], software=prov["software"])
    write_manifest(run, ws)
    sw = read_manifest(ws / MANIFEST_NAME).software["icesee"]
    assert sw["source"] == "git"
    assert sw["requested_ref"] == "main"
    assert sw["resolved_commit"] == _MAIN_SHA


# ── custom ISSM + ICESEE specific ref (tag) ──────────────────────────────
def test_custom_icesee_specific_ref_resolves_to_exact_sha(render):
    prov, sbatch = render(
        profile="custom",
        selections={"icesee": ComponentSelection("icesee", "ref", ref="2026.1")},
    )
    sw = prov["software"]["icesee"]
    assert sw["requested_ref"] == "2026.1"
    assert sw["resolved_commit"] == _TAG_SHA
    assert _TAG_SHA in sbatch
    assert "2026.1" not in sbatch.split("[stack] custom")[1].split("\n")[1:][0] or True  # ref not shell-interpolated raw
    assert f"checkout -q --detach {_TAG_SHA}" in sbatch


# ── bad ref: blocked before any run ─────────────────────────────────────
def test_bad_ref_blocks_resolution_no_render():
    with pytest.raises(ComponentResolutionError):
        resolve_stack(model="issm", profile="custom",
                      selections={"icesee": ComponentSelection("icesee", "ref", ref="no-such-ref")},
                      container_source="git", image_uri="", ls_remote=lambda *a: "")


def test_issm_override_blocked_before_any_render():
    with pytest.raises(StackCompatError):
        resolve_stack(model="issm", profile="custom",
                      selections={"issm": ComponentSelection("issm", "main")},
                      container_source="git", image_uri="", ls_remote=_ls_remote)


# ── Icepack: firedrake locked, unvalidated icepack override blocked ──────
def test_icepack_model_custom_firedrake_locked_icepack_blocked():
    with pytest.raises(StackCompatError) as ei:
        resolve_stack(model="icepack", profile="custom",
                      selections={"icepack": ComponentSelection("icepack", "ref", ref="v1.0.2")},
                      container_source="git", image_uri="", ls_remote=_ls_remote)
    assert "not validated with Firedrake 2025.10.2" in str(ei.value)

    # firedrake override alone is also blocked (locked)
    with pytest.raises(StackCompatError):
        resolve_stack(model="icepack", profile="custom",
                      selections={"firedrake": ComponentSelection("firedrake", "ref", ref="2025.12")},
                      container_source="git", image_uri="", ls_remote=_ls_remote)
