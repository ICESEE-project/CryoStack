"""Generated-script tests for the ISSM ICESEE-Container solver launcher shim.

ISSM's cluster class inside the SIF writes its solver launch line as
``srun --cpu-bind=none --mpi=pmi2 -n <np> <cmd>``; the SIF has no Slurm client.
``_issm_container_launcher_shim`` installs an in-container ``srun`` that must
re-express that call as ``mpiexec -np <np> <cmd>`` preserving the task count
ISSM itself passed.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from cryostack_src.models.submission import _issm_container_launcher_shim

_ISSM = "/opt/ISSM/bin/issm.exe"


def _shim_source() -> str:
    block = _issm_container_launcher_shim(run_dir="/run/x")
    match = re.search(r"<<'CRYOSTACK_SRUN'\n(.*?)\nCRYOSTACK_SRUN", block, re.S)
    assert match, block
    return match.group(1)


def _run_shim(argv: list[str], *, env_extra: dict | None = None, tmp_path: Path) -> str:
    (tmp_path / "srun").write_text(_shim_source())
    (tmp_path / "srun").chmod(0o755)
    # fake mpiexec echoes exactly how ISSM's command reached it
    (tmp_path / "mpiexec").write_text('#!/bin/sh\necho "mpiexec $*"\n')
    (tmp_path / "mpiexec").chmod(0o755)
    env = {"PATH": f"{tmp_path}:{os.environ['PATH']}"}
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [str(tmp_path / "srun"), *argv], capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_shim_is_installed_in_generated_block():
    block = _issm_container_launcher_shim(run_dir="/home/u/run/issm_container")
    assert 'mkdir -p "/home/u/run/issm_container/.cryostack_launcher"' in block
    assert block.rstrip().endswith(
        'chmod +x "/home/u/run/issm_container/.cryostack_launcher/srun"'
    )
    assert 'exec mpiexec -np "$np" "$@"' in block
    assert " -n 8 " not in block  # nothing hardcoded to the allocation size


def test_srun_dash_n_2_becomes_mpiexec_np_2(tmp_path):
    got = _run_shim(
        ["--cpu-bind=none", "--mpi=pmi2", "-n", "2",
         _ISSM, "TransientSolution", "/opt/ISSM/execution/Square-1", "Square"],
        tmp_path=tmp_path,
    )
    assert got == (
        f"mpiexec -np 2 {_ISSM} TransientSolution /opt/ISSM/execution/Square-1 Square"
    )


def test_srun_dash_n_8_becomes_mpiexec_np_8(tmp_path):
    got = _run_shim(
        ["--cpu-bind=none", "--mpi=pmi2", "-n", "8",
         _ISSM, "StressbalanceSolution", "/opt/ISSM/execution/Square-7", "Square"],
        tmp_path=tmp_path,
    )
    assert got == (
        f"mpiexec -np 8 {_ISSM} StressbalanceSolution /opt/ISSM/execution/Square-7 Square"
    )


@pytest.mark.parametrize(
    ("flag", "expected_np"),
    [(["--ntasks", "3"], "3"), (["--ntasks=5"], "5"), (["-n4"], "4")],
)
def test_shim_parses_all_task_count_spellings(flag, expected_np, tmp_path):
    got = _run_shim([*flag, _ISSM, "Sol", "/e/d", "M"], tmp_path=tmp_path)
    assert got == f"mpiexec -np {expected_np} {_ISSM} Sol /e/d M"


def test_shim_falls_back_to_slurm_ntasks_when_no_count_passed(tmp_path):
    got = _run_shim(
        [_ISSM, "Sol", "/e/d", "M"],
        env_extra={"SLURM_NTASKS": "16"},
        tmp_path=tmp_path,
    )
    assert got == f"mpiexec -np 16 {_ISSM} Sol /e/d M"
