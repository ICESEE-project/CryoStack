"""Regression tests for the ISSM ICESEE-Container MPI solver launch.

Real PACE job 12738507 reached the container, MATLAB, and ISSM marshalling,
then died at ``launching solution sequence`` with::

    No executable was specified on the prterun command line.  Aborting.
    No available launching agents were found.

Root cause: the ISSM ``generic`` cluster inside the SIF emits
``mpiexec -np <np> <ISSM_DIR>/bin/issm.exe ...`` (PRRTE 4 / OpenMPI 5), *never*
``srun``. A ``.cryostack_launcher/srun`` shim on ``PATH`` -- meant to catch an
``srun`` ISSM never emits -- instead intercepted PRRTE's own ``srun prted``
launch on the 2-node allocation and re-exec'd a broken ``mpiexec``.

Fix: no shim. Pin PRRTE to the batch node via ``apptainer exec --env`` so the
self-launched ``mpiexec`` never needs ``srun``/``ssh``; a container ISSM run is
single-node and the submit path says so when ``-N`` > 1.
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
from cryostack_src.models.submission import (
    _issm_container_mpi_env,
    _issm_container_single_node_note,
)
from cryostack_src.resources.profiles import get_compute_profile


class _Result:
    def __init__(self, stdout: str = "", rc: int = 0) -> None:
        self.returncode = rc
        self.stdout = stdout
        self.stderr = ""


@pytest.fixture
def render(monkeypatch):
    """Render the generated sbatch text for a direct container ISSM run."""

    def _fake_ssh_run(host, user, port, cmd, timeout=20):
        if "run_icesheets.sbatch" in cmd and "b64decode" in cmd:
            for blob in sorted(
                re.findall(r"[A-Za-z0-9+/]{80,}={0,2}", cmd), key=len, reverse=True
            ):
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
    monkeypatch.setattr(
        submission, "subprocess",
        types.SimpleNamespace(run=lambda *a, **k: _Result()),
        raising=False,
    )

    example = Path(tempfile.mkdtemp()) / "SquareIceShelf"
    example.mkdir()
    (example / "runme.m").write_text(
        "md.cluster=generic('name',oshostname(),'np',2);\nmd=solve(md,'Stressbalance');\n"
    )

    def _render(*, nodes: int = 1, ntasks: int = 8, tpn: int = 8) -> tuple[str, list[str]]:
        _fake_ssh_run.sbatch = ""
        out = submission.submit_remote_icesheets(
            host="login", user="u", port=22,
            remote_base_dir="~/base", remote_tag="icesheets",
            backend="container", model="issm",
            example_dir=str(example), exec_dir=str(example),
            image_uri="", container_source="git",
            spack_enable=False, spack_repo_url="", spack_dirname="ICESEE-Spack",
            spack_install_if_needed=False, spack_install_mode="",
            spack_slurm_dir="", spack_pmix_dir="",
            slurm_time="01:00:00", slurm_job_name="ISSM",
            slurm_nodes=nodes, slurm_ntasks=ntasks, slurm_tpn=tpn,
            slurm_part="cpu-small", slurm_mem="16G",
            slurm_account="gts-arobel3-atlas", slurm_mail="",
            test_mode=False, run_file="",
            matlab_license=get_compute_profile("pace").matlab_license_config(),
        )
        return _fake_ssh_run.sbatch, out["messages"]

    return _render


# ── the shim is gone ────────────────────────────────────────────────────
def test_no_srun_shim_anywhere_in_the_generated_sbatch(render):
    sbatch, _ = render()
    assert ".cryostack_launcher" not in sbatch
    assert "CRYOSTACK_SRUN" not in sbatch
    assert 'exec mpiexec -np "$np"' not in sbatch
    # nothing prepends a fake launcher dir onto the in-container PATH
    assert "setenv('PATH'" not in sbatch


def test_helper_no_longer_exists():
    assert not hasattr(submission, "_issm_container_launcher_shim")


# ── PRRTE is pinned to the batch node ───────────────────────────────────
def test_prte_env_pins_the_solver_to_the_local_node(render):
    sbatch, _ = render()
    exec_line = next(
        ln for ln in sbatch.splitlines() if "with-issm matlab" in ln
    )
    assert "--env PRTE_MCA_ras=^slurm" in exec_line
    assert "--env PRTE_MCA_plm=ssh" in exec_line
    assert "--env PRTE_MCA_rmaps_default_mapping_policy=:oversubscribe" in exec_line
    # the MATLAB licence env is still there too
    assert "--env MLM_LICENSE_FILE=" in exec_line


def test_env_string_is_well_formed_flags_only():
    frag = _issm_container_mpi_env()
    toks = frag.split()
    assert toks and all(
        a == "--env" or "=" in a for a in toks
    ), frag
    # no empty launcher, no naked mpiexec, no executable path
    assert "mpiexec" not in frag and "srun" not in frag


# ── one MATLAB driver, no outer srun -N/-n wrapper (846c364 preserved) ──
def test_exactly_one_matlab_driver_and_no_outer_srun(render):
    sbatch, _ = render(nodes=2, ntasks=48, tpn=24)
    assert sbatch.count("with-issm matlab") == 1
    # no `srun -N.. -n..` wrapping the apptainer exec
    assert not re.search(r"(?:^|[;&|]\s*)srun\s+-", sbatch, re.M)
    assert "apptainer exec" in sbatch
    # the allocation header is untouched
    assert "#SBATCH -N 2" in sbatch
    assert "#SBATCH --ntasks=48" in sbatch


# ── process-count source of truth: -N>1 is surfaced, not silently eaten ─
def test_multi_node_container_issm_emits_a_single_node_advisory(render):
    _, messages = render(nodes=2, ntasks=48, tpn=24)
    joined = "\n".join(messages)
    assert "self-launches MPI on the batch node only" in joined
    assert "md.cluster.np" in joined
    assert "-N 2 is not used by the solver" in joined


def test_single_node_container_issm_has_no_advisory(render):
    _, messages = render(nodes=1, ntasks=8, tpn=8)
    assert not any("not used by the solver" in m for m in messages)


@pytest.mark.parametrize(
    ("backend", "model", "nodes", "expect_note"),
    [
        ("container", "issm", 2, True),
        ("container", "issm", 1, False),
        ("container", "issm", "3", True),      # str node count still counted
        ("spack", "issm", 4, False),           # spack ISSM *can* go multi-node
        ("container", "icepack", 2, False),    # icepack has no self-launched MPI
        ("container", "issm", None, False),    # unparseable -> treated as 1
    ],
)
def test_single_node_note_matrix(backend, model, nodes, expect_note):
    note = _issm_container_single_node_note(backend=backend, model=model, nodes=nodes)
    assert bool(note) is expect_note


# ── the documented state stays in sync with the code (issue closure) ────
def test_developer_guide_documents_the_single_node_container_issm_limit():
    guide = " ".join(
        (_REPO_ROOT / "icesee_jupyter_book" / "docs" / "developer_guide.md")
        .read_text().split()
    )
    assert "Container ISSM is therefore single-node." in guide
    assert "PRTE_MCA_ras=^slurm" in guide
    assert "Do not reintroduce the removed `srun` shim" in guide
    assert "use the Spack backend" in guide
