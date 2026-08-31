"""ICESEE-Spack lifecycle module: probe scripts, classification, setup sbatch."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from cryostack_src.remote import spack_env
from cryostack_src.remote.spack_env import (
    EnvStatus,
    SetupSlurmOpts,
    classify_probe,
    install_sbatch_text,
    probe_script,
    spack_paths,
    spack_paths_from_repo,
)

_PACE_LICENSE = {"env_var": "MLM_LICENSE_FILE", "value": "1711@matlablic.ecs.gatech.edu"}


def _paths():
    return spack_paths("/home/u/base", "ICESEE-Spack")


# ── paths ────────────────────────────────────────────────────────────────
def test_paths_and_marker_are_model_scoped():
    p = _paths()
    assert p.repo == "/home/u/base/ICESEE-Spack"
    assert p.activate == "/home/u/base/ICESEE-Spack/scripts/activate.sh"
    assert p.marker("issm").endswith(".icesee_spack_issm_ready")
    assert p.marker("icepack").endswith(".icesee_spack_icepack_ready")
    assert spack_paths_from_repo("/x/y/ICESEE-Spack").repo == "/x/y/ICESEE-Spack"


# ── probe scripts ────────────────────────────────────────────────────────
def test_issm_probe_checks_repo_activate_issmdir_and_executable_no_matlab():
    s = probe_script(model="issm", paths=_paths())
    assert "CRYOSTACK_ENV_REPO=" in s
    assert "scripts/activate.sh" in s
    assert "ISSM_DIR" in s and "issm.exe" in s
    assert "matlab" not in s.lower()          # decision 2: no MATLAB in Check


def test_icepack_probe_imports_firedrake_and_icepack():
    s = probe_script(model="icepack", paths=_paths())
    assert "import firedrake, icepack" in s
    assert "matlab" not in s.lower()


def test_probe_rejects_unknown_model():
    with pytest.raises(ValueError):
        probe_script(model="nope", paths=_paths())


# ── classification ──────────────────────────────────────────────────────
def test_classify_fresh_resource_is_not_installed():
    r = classify_probe("CRYOSTACK_ENV_REPO=absent", model="issm")
    assert r.status is EnvStatus.NOT_INSTALLED


def test_classify_cloned_but_unbuilt_is_repo_only():
    out = "CRYOSTACK_ENV_REPO=present\nCRYOSTACK_ENV_ACTIVATE=ok\nCRYOSTACK_ENV_MODEL=fail:issm_exe_missing"
    r = classify_probe(out, model="issm")
    assert r.status is EnvStatus.REPO_ONLY
    assert "not built" in " ".join(r.messages).lower()


def test_classify_broken_activation_is_repo_only():
    out = "CRYOSTACK_ENV_REPO=present\nCRYOSTACK_ENV_ACTIVATE=fail:source_error\nCRYOSTACK_ENV_MODEL=skip"
    assert classify_probe(out, model="icepack").status is EnvStatus.REPO_ONLY


def test_classify_all_ok_is_ready_issm():
    out = "CRYOSTACK_ENV_REPO=present\nCRYOSTACK_ENV_ACTIVATE=ok\nCRYOSTACK_ENV_MODEL=ok"
    assert classify_probe(out, model="issm").status is EnvStatus.READY


def test_classify_all_ok_is_ready_icepack():
    out = "CRYOSTACK_ENV_REPO=present\nCRYOSTACK_ENV_ACTIVATE=ok\nCRYOSTACK_ENV_MODEL=ok"
    assert classify_probe(out, model="icepack").status is EnvStatus.READY


def test_marker_alone_does_not_make_it_ready():
    # decision 4: a marker with a failing probe is stale, not Ready
    out = "CRYOSTACK_ENV_REPO=present\nCRYOSTACK_ENV_MARKER=present\nCRYOSTACK_ENV_ACTIVATE=ok\nCRYOSTACK_ENV_MODEL=fail:import_failed"
    assert classify_probe(out, model="icepack").status is EnvStatus.REPO_ONLY


def test_env_status_badge_mapping():
    assert EnvStatus.READY.badge_state == "ready"
    assert EnvStatus.INSTALLING.badge_state == "running"
    assert EnvStatus.FAILED.badge_state == "error"
    assert EnvStatus.NOT_INSTALLED.badge_state == "idle"


# ── setup sbatch ────────────────────────────────────────────────────────
def test_issm_setup_sbatch_is_a_slurm_job_with_install_verify_and_license():
    s = install_sbatch_text(
        model="issm", paths=_paths(), setup_dir="/home/u/base/ICESEE-Spack-setup",
        slurm=SetupSlurmOpts(partition="cpu-small", account="acct"),
        matlab_license=_PACE_LICENSE,
    )
    assert s.startswith("#!/bin/bash")
    assert "#SBATCH -J ICESEE-Spack-setup" in s
    assert "#SBATCH -o /home/u/base/ICESEE-Spack-setup/spack-setup-%j.out" in s
    assert "#SBATCH -A acct" in s
    assert "./scripts/install.sh --with-issm" in s
    # deep verification on the compute node, with the compute-profile license
    assert "export MLM_LICENSE_FILE=1711@matlablic.ecs.gatech.edu" in s
    assert 'matlab -batch' in s and "issmversion" in s
    assert "CRYOSTACK_ENV_DEEP=ok" in s
    # marker written only after verification, at the end
    assert s.index(".icesee_spack_issm_ready") > s.index("issmversion")
    # never a synchronous ssh install: this is an sbatch script
    assert "sbatch" not in s


def test_icepack_setup_sbatch_verifies_firedrake_and_icepack_no_matlab():
    s = install_sbatch_text(
        model="icepack", paths=_paths(), setup_dir="/s/dir",
        matlab_license=None,
    )
    assert "./scripts/install.sh --with-icepack" in s
    assert "import firedrake" in s and "import icepack" in s
    assert "matlab" not in s.lower()
    assert "MLM_LICENSE_FILE" not in s


def test_setup_sbatch_rejects_unknown_model():
    with pytest.raises(ValueError):
        install_sbatch_text(model="nope", paths=_paths(), setup_dir="/s")


def test_deep_verify_ok_reads_the_marker_line():
    assert spack_env.deep_verify_ok("...\nCRYOSTACK_ENV_DEEP=ok\n...") is True
    assert spack_env.deep_verify_ok("CRYOSTACK_ENV_DEEP=fail") is False
