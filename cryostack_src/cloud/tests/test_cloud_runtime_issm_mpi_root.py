"""cryostack_src.cloud.runtime -- ISSM's in-container MPI launch refusing
to run as root on AWS Fargate/EC2.

Live-run regression: bkyanjo/icesee-combined sets no ``USER`` (see
tools/cloud/Dockerfile), so the Batch/Fargate task runs the container as
root. ISSM's ``generic`` cluster launches its solver via Spack OpenMPI 5 /
PRRTE's own ``mpiexec``/``prterun``, which refuses outright to run as root
("prterun has detected an attempt to run as root") -- PRRTE's own
built-in safety check, unrelated to the Slurm/Remote path's own
``PRTE_MCA_*`` fix for a *different* PRRTE failure mode (multi-node
allocation confusing the launch agent; see
cryostack_src.models.submission._issm_container_mpi_env and
test_container_issm_mpi_launch.py). The fix here is PRRTE/Open MPI's own
advertised override for a deliberately root-only container -- exported as
plain environment variables (never a CLI flag, since ISSM itself, not
CryoStack, constructs the actual mpiexec/prterun command line), scoped
only to the AWS cloud ISSM branch.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.runtime import build_cloud_runner, issm_cloud_runner_script

_ALLOW_ROOT = "export OMPI_ALLOW_RUN_AS_ROOT=1"
_ALLOW_ROOT_CONFIRM = "export OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1"


def test_both_root_override_vars_are_exported():
    script = issm_cloud_runner_script()
    assert _ALLOW_ROOT in script
    assert _ALLOW_ROOT_CONFIRM in script


def test_root_override_is_exported_before_matlab_starts():
    script = issm_cloud_runner_script()
    allow_idx = script.index(_ALLOW_ROOT)
    confirm_idx = script.index(_ALLOW_ROOT_CONFIRM)
    matlab_idx = script.index("with-issm matlab")
    assert allow_idx < confirm_idx < matlab_idx


def test_root_override_applies_unconditionally_not_just_when_the_tunnel_is_used():
    """The root-execution refusal is independent of whether the MATLAB
    license tunnel is active (a direct-secret ISSM run hits the exact same
    solver-launch failure) -- the export must precede, not live inside,
    the ``CRYOSTACK_LICENSE_TUNNEL_REQUIRED`` conditional block."""
    script = issm_cloud_runner_script()
    allow_idx = script.index(_ALLOW_ROOT)
    tunnel_conditional_idx = script.index(
        'if [ "${CRYOSTACK_LICENSE_TUNNEL_REQUIRED:-0}" = "1" ]; then')
    assert allow_idx < tunnel_conditional_idx


def test_root_override_is_scoped_to_the_staged_issm_script_only():
    """Never leaked into the generic runner's own inline command text (it
    would apply to smoke/icepack too, and would eat into the Container
    Overrides budget test_cloud_runtime.py guards) -- it lives only in the
    staged ISSM branch file, invoked by filename."""
    generic_script = build_cloud_runner()
    assert "OMPI_ALLOW_RUN_AS_ROOT" not in generic_script


def test_root_override_is_not_applied_on_the_slurm_remote_path():
    """The Local/Remote (Slurm/SSH) path's own PRRTE fix
    (_issm_container_mpi_env) addresses a different failure mode
    entirely -- apptainer there already runs as the submitting HPC user,
    never root -- so this override must never bleed into that path."""
    from cryostack_src.models.submission import _issm_container_mpi_env

    assert "OMPI_ALLOW_RUN_AS_ROOT" not in _issm_container_mpi_env()
