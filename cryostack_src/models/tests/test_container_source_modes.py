"""Generated-sbatch tests for the three portable container source modes.

``container_source`` + ``image_uri`` select how the ISSM ICESEE-Container SIF
is provisioned inside the submitted Slurm job:

* ``local``  -- use an existing SIF path as-is
* ``git``    -- clone/update ICESEE-Containers, build the selected .def when the
  cached SIF is absent or stale
* ``docker`` -- ``apptainer pull docker://<image_uri>`` into a per-image cache

Every mode caches exactly one SIF per source/image identity, reuses it on later
runs, needs no host Slurm/PMIx, keeps the launcher shim, and preserves the
ICESEE_RUN_DIR + postprocess result contract.
"""
from __future__ import annotations

import base64
import re
import sys
import tempfile
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

import cryostack_src.models.submission as submission
from cryostack_src.resources.profiles import get_compute_profile

_RUN_DIR = "/home/u/base/icesheets/runs/issm_container"
_CONTAINERS = "/home/u/base/icesheets/ICESEE-Containers"


class _Result:
    def __init__(self, stdout: str = "", rc: int = 0) -> None:
        self.returncode = rc
        self.stdout = stdout
        self.stderr = ""


@pytest.fixture
def render(monkeypatch):
    """Return a function that renders the sbatch text for a container run."""

    def _fake_ssh_run(host, user, port, cmd, timeout=20):
        if "run_icesheets.sbatch" in cmd and "b64decode" in cmd:
            for blob in sorted(re.findall(r"[A-Za-z0-9+/]{80,}={0,2}", cmd), key=len, reverse=True):
                try:
                    _fake_ssh_run.sbatch = base64.b64decode(blob).decode()
                    break
                except Exception:
                    continue
        if cmd.strip().startswith("sbatch"):
            return _Result("Submitted batch job 4242\n")
        if cmd.strip().startswith("test -f"):
            return _Result("FOUND\n")
        return _Result("/abs/ok\n")

    monkeypatch.setattr(submission, "ssh_run", _fake_ssh_run)
    monkeypatch.setattr(submission, "resolve_remote_abs_path", lambda *a, **k: "/home/u/base")
    monkeypatch.setattr(submission, "expand_remote_home", lambda x: x)
    # submit_remote_icesheets stages the example with subprocess.run (rsync);
    # the module does not import subprocess, so inject a stub for the render.
    monkeypatch.setattr(
        submission, "subprocess",
        types.SimpleNamespace(run=lambda *a, **k: _Result()),
        raising=False,
    )

    example = Path(tempfile.mkdtemp()) / "SquareShelf"
    example.mkdir()
    (example / "runme.m").write_text("md.cluster=generic('name',oshostname(),'np',2);\n")

    def _render(*, container_source: str, image_uri: str = "") -> str:
        _fake_ssh_run.sbatch = ""
        submission.submit_remote_icesheets(
            host="login", user="u", port=22,
            remote_base_dir="~/base", remote_tag="icesheets",
            backend="container", model="issm",
            example_dir=str(example), exec_dir=str(example),
            image_uri=image_uri, container_source=container_source,
            spack_enable=False, spack_repo_url="", spack_dirname="ICESEE-Spack",
            spack_install_if_needed=False, spack_install_mode="",
            spack_slurm_dir="", spack_pmix_dir="",
            slurm_time="01:00:00", slurm_job_name="ICESHEETS", slurm_nodes=1,
            slurm_ntasks=8, slurm_tpn=8, slurm_part="cpu", slurm_mem="16G",
            slurm_account="", slurm_mail="", test_mode=False, run_file="",
            matlab_license=get_compute_profile("pace").matlab_license_config(),
        )
        return _fake_ssh_run.sbatch

    return _render


def _assert_common_container_contract(txt: str, sif_path: str):
    # exactly one MATLAB driver, no outer srun around it
    assert txt.count("with-issm matlab") == 1
    assert not re.search(r"(?:^|[;&|]\s*)srun\s+-", txt, re.M)
    # allocation preserved
    assert "#SBATCH --ntasks=8" in txt
    # the run uses the provisioned SIF
    assert f'"{sif_path}" with-issm matlab' in txt
    # launcher shim + result/postprocess contract preserved
    assert f'{_RUN_DIR}/.cryostack_launcher' in txt
    assert 'exec mpiexec -np "$np" "$@"' in txt
    assert f'"{_RUN_DIR}":"{_RUN_DIR}"' in txt
    assert f"ICESEE_RUN_DIR='{_RUN_DIR}'" in txt
    assert f"run('{_RUN_DIR}/postprocess_icesee.m'); exit" in txt
    # no host Slurm/PMIx dependency introduced by provisioning
    assert "/opt/slurm" not in txt
    assert "/opt/pmix" not in txt


def test_local_mode_uses_existing_sif_without_build(render):
    sif = "/shared/images/combined-env.sif"
    txt = render(container_source="local", image_uri=sif)
    assert "[container] source: local" in txt
    assert f'sif_path="{sif}"' in txt
    assert "[container] using cached image" in txt
    # no provisioning actions
    assert "git clone" not in txt
    assert "apptainer build" not in txt
    assert "apptainer pull" not in txt
    # missing-image guard -> deterministic in-job failure
    assert 'if [ ! -f "$sif_path" ]; then' in txt
    _assert_common_container_contract(txt, sif)


def test_git_mode_clones_and_builds_selected_def_when_absent_or_stale(render):
    txt = render(container_source="git")
    sif = f"{_CONTAINERS}/spack-managed/combined-container/combined-env.sif"
    assert "[container] source: git" in txt
    assert f'git clone {submission._ICESEE_CONTAINERS_REPO} "{_CONTAINERS}"' in txt
    assert f'git -C "{_CONTAINERS}" pull --ff-only' in txt
    assert 'def_path="' in txt and "combined-env-inbuilt-matlab.def" in txt
    # build only when cached SIF absent or older than the def
    assert 'if [ ! -f "$sif_path" ] || [ "$def_path" -nt "$sif_path" ]; then' in txt
    assert 'apptainer build "$sif_path" "$def_path"' in txt
    assert "[container] using cached image" in txt  # the reuse branch
    assert "apptainer pull" not in txt
    _assert_common_container_contract(txt, sif)


def test_git_mode_honours_selected_def_name(render):
    txt = render(container_source="git", image_uri="combined-env-mini.def")
    sif = f"{_CONTAINERS}/spack-managed/combined-container/combined-env-mini.sif"
    assert "combined-env-mini.def" in txt
    assert f'sif_path="{sif}"' in txt
    assert "building combined-env-mini.sif from combined-env-mini.def" in txt
    _assert_common_container_contract(txt, sif)


def test_docker_mode_pulls_and_caches_one_sif_per_image(render):
    ref = "ghcr.io/icesee-project/issm:1.2"
    txt = render(container_source="docker", image_uri=ref)
    slug = submission._oci_cache_slug(ref)
    sif = f"{_CONTAINERS}/oci-cache/{slug}.sif"
    assert "[container] source: docker" in txt
    assert f"[container] pulling image docker://{ref} ..." in txt
    assert f'apptainer pull "$sif_path" "docker://{ref}"' in txt
    assert f'sif_path="{sif}"' in txt
    # reuse-vs-pull branch: cached SIF short-circuits the pull
    assert 'if [ -f "$sif_path" ]; then' in txt
    assert txt.count("[container] using cached image") >= 1
    # registry path must not build an image on the HPC system
    assert "apptainer build" not in txt
    assert "docker build" not in txt
    assert "git clone" not in txt
    _assert_common_container_contract(txt, sif)


def test_docker_mode_accepts_full_ref_with_scheme(render):
    txt = render(container_source="docker", image_uri="docker://alpine:3.20")
    assert 'apptainer pull "$sif_path" "docker://alpine:3.20"' in txt
    assert "docker://docker://" not in txt


def test_legacy_registry_value_falls_back_to_git(render):
    txt = render(container_source="registry")
    assert "[container] source: git" in txt
    assert 'apptainer build "$sif_path" "$def_path"' in txt


def test_connector_submission_shares_the_same_source_modes(monkeypatch):
    """The connector path renders the same provisioning for each mode."""
    captured = {}

    def _fake_connector_ssh(session_id, host, user, port, cmd, timeout=20, cluster_name="pace"):
        if "run_icesheets.sbatch" in cmd and "b64decode" in cmd:
            for blob in sorted(re.findall(r"[A-Za-z0-9+/]{80,}={0,2}", cmd), key=len, reverse=True):
                try:
                    captured["sbatch"] = base64.b64decode(blob).decode()
                    break
                except Exception:
                    continue
        return {"ok": True, "stdout": "/home/u/base\n", "stderr": ""}

    monkeypatch.setattr(submission, "connector_ssh", _fake_connector_ssh)
    monkeypatch.setattr(
        submission, "connector_stage_archive",
        lambda *a, **k: {"ok": True, "stdout": "", "stderr": ""},
    )
    monkeypatch.setattr(
        submission, "connector_slurm_submit",
        lambda *a, **k: {"ok": True, "submitted": True, "jobid": "4242"},
    )

    example = Path(tempfile.mkdtemp()) / "SquareShelf"
    example.mkdir()
    (example / "runme.m").write_text("md.cluster=generic('name',oshostname(),'np',2);\n")

    submission.submit_remote_icesheets_via_connector(
        session_id="s", host="login", user="u", port=22,
        remote_base_dir="~/base", remote_tag="icesheets",
        backend="container", model="issm",
        example_dir=str(example), exec_dir=str(example),
        image_uri="ghcr.io/icesee-project/issm:1.2", container_source="docker",
        spack_enable=False, spack_repo_url="", spack_dirname="ICESEE-Spack",
        spack_install_if_needed=False, spack_install_mode="",
        spack_slurm_dir="", spack_pmix_dir="",
        slurm_time="01:00:00", slurm_job_name="ICESHEETS", slurm_nodes=1,
        slurm_ntasks=8, slurm_tpn=8, slurm_part="cpu", slurm_mem="16G",
        slurm_account="", slurm_mail="", test_mode=False, run_file="",
        matlab_license=get_compute_profile("pace").matlab_license_config(),
    )

    txt = captured["sbatch"]
    slug = submission._oci_cache_slug("ghcr.io/icesee-project/issm:1.2")
    sif = f"{_CONTAINERS}/oci-cache/{slug}.sif"
    assert "[container] source: docker" in txt
    assert f'apptainer pull "$sif_path" "docker://ghcr.io/icesee-project/issm:1.2"' in txt
    _assert_common_container_contract(txt, sif)
