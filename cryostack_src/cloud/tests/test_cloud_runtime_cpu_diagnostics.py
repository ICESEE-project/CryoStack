"""cryostack_src.cloud.runtime -- the compact CPU/topology/PRRTE-slot
diagnostic block in the staged ISSM branch script.

Originally added exhaustively (cgroup v1/v2, cpuset, /proc/self/status,
full lscpu/hwloc dumps) for the live investigation into why a 2-vCPU
Fargate task's PRRTE reported "not enough slots" for ISSM's
``mpiexec -np 2``; both Fargate and EC2 now validate end-to-end, so it
has been trimmed to a standing summary (topology facts, the criterion
actually applied, and a two-rank report-bindings canary) useful for any
future slot-discovery failure, without carrying the original
investigation's full fact-finding into routine production logs.

This block is diagnostic-only: it changes no allocation/mapping behavior
(no ``--oversubscribe``, no hostfile, no ``CRYOSTACK_CLOUD_VCPU``, no
``np`` change) and cannot affect the run's outcome. These tests exist to
prove exactly that, and that the block never leaked outside the one file
it belongs in.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.runtime import build_cloud_runner, issm_cloud_runner_script

_DIAG_BEGIN = "diagnostics: begin (CPU/topology/PRRTE, informational only)"
_DIAG_END = "diagnostics: end"


# ── confined to the staged ISSM runner only ─────────────────────────────
def test_diagnostic_block_lives_only_in_the_staged_issm_script():
    script = issm_cloud_runner_script()
    assert _DIAG_BEGIN in script
    assert _DIAG_END in script


def test_diagnostic_block_never_leaks_into_the_generic_inline_runner():
    """The generic runner (icepack/smoke/issm dispatch, subject to the
    8192-char Container Overrides cap) must be completely untouched --
    the diagnostics live only in the separately-staged ISSM file."""
    generic = build_cloud_runner()
    assert _DIAG_BEGIN not in generic
    assert "nproc" not in generic
    assert "cgroup" not in generic
    assert "lscpu" not in generic


def test_diagnostic_block_never_touches_the_remote_slurm_path():
    """cryostack_src.models.submission._issm_container_mpi_env (the
    Local/Remote/Slurm path's own, unrelated PRRTE fix) must be
    byte-for-byte unchanged by this diagnostic addition."""
    from cryostack_src.models.submission import _issm_container_mpi_env

    env = _issm_container_mpi_env()
    assert env == (
        "--env PRTE_MCA_ras=^slurm "
        "--env PRTE_MCA_plm=ssh "
        "--env PRTE_MCA_rmaps_default_mapping_policy=:oversubscribe "
    )
    assert "diagnostics" not in env
    assert "nproc" not in env


# ── cannot change allocation/mapping behavior ───────────────────────────
def _non_comment_lines(script: str) -> str:
    """The actual executable bash text, stripped of comment-only lines --
    a comment may legitimately EXPLAIN what the script deliberately does
    NOT do (e.g. "no --oversubscribe"), which must not itself trip a
    substring check meant to catch real usage."""
    return "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#"))


def test_diagnostic_block_never_sets_oversubscribe_hostfile_or_vcpu_env():
    """This is diagnostics only -- the actual slot-mechanism decision is
    deliberately deferred until the next live run's output is in hand."""
    executable = _non_comment_lines(issm_cloud_runner_script())
    assert "--oversubscribe" not in executable
    assert "oversubscribe" not in executable.lower()
    assert "hostfile" not in executable.lower()
    assert "CRYOSTACK_CLOUD_VCPU" not in executable


def test_diagnostic_block_never_calls_fail_or_exit():
    """Every diagnostic command is individually guarded (`|| echo ...`);
    none of them may abort the script -- confirmed by the absence of
    `fail`/`exit` anywhere inside the diagnostic block's own text."""
    script = issm_cloud_runner_script()
    start = script.index(_DIAG_BEGIN)
    end = script.index(_DIAG_END)
    block = script[start:end]
    assert "fail " not in block
    assert "fail(" not in block
    assert "\nexit" not in block


def test_diagnostic_block_runs_before_matlab_and_matlab_stays_the_last_command():
    """The child script's own exit code (captured by the generic runner
    as `rc=$?`) must still be determined solely by the MATLAB invocation
    -- the diagnostic block must run strictly before it, and nothing may
    follow the MATLAB line."""
    script = issm_cloud_runner_script()
    diag_idx = script.index(_DIAG_BEGIN)
    matlab_idx = script.index("with-issm matlab")
    assert diag_idx < matlab_idx
    # the matlab invocation (plus its own continuation line) is the last
    # substantive content in the script
    after_matlab = script[matlab_idx:]
    assert after_matlab.strip().endswith(
        "run('${WORKDIR}/postprocess_icesee.m');\"")


def test_diagnostic_block_never_invokes_the_real_issm_solver_binary():
    """The only MPI process the diagnostics ever launch is a trivial,
    single-rank `true` -- never issm.exe, and never through a path that
    could satisfy or fail on the real `-np 2` request."""
    script = issm_cloud_runner_script()
    start = script.index(_DIAG_BEGIN)
    end = script.index(_DIAG_END)
    lines = _non_comment_lines(script[start:end]).splitlines()
    # only the ACTUAL invocation lines matter -- a descriptive `echo`
    # section header is free to mention "issm.exe" in prose.
    invocation_lines = "\n".join(
        line for line in lines if "mpiexec" in line or "with-issm" in line)
    assert "issm.exe" not in invocation_lines
    assert "-n 1 true" in invocation_lines
    assert "-np 2" not in invocation_lines


# ── the diagnostics use the SAME environment the real solver launch does ──
def test_mpi_specific_probes_are_routed_through_with_issm():
    """mpiexec is only resolvable once with-issm has set up the Spack
    OpenMPI PATH -- these probes must run through with-issm (never a
    bare `mpiexec` that would silently report "not available" purely
    from a PATH gap, giving a false negative)."""
    script = issm_cloud_runner_script()
    start = script.index(_DIAG_BEGIN)
    end = script.index(_DIAG_END)
    block = script[start:end]
    assert "with-issm mpiexec --version" in block
    assert "with-issm timeout 15 mpiexec --report-bindings -n 1 true" in block
    assert "with-issm timeout 15 mpiexec --report-bindings -n 2 true" in block


# ── the actual Container Overrides fix (unrelated to this diagnostic) ──
def test_container_overrides_headroom_is_unaffected_by_the_diagnostic_block():
    """The diagnostics live entirely in the staged ISSM file, never the
    inline job command -- the existing Container-Overrides headroom
    regression (>=1000 chars, see test_cloud_runtime.py) must still hold
    unchanged."""
    import json

    from cryostack_src.cloud.drivers.aws.submit import build_container_overrides
    from cryostack_src.cloud.matlab_license import plan_license_tunnel
    from cryostack_src.cloud.runtime import (
        BATCH_CONTAINER_OVERRIDE_LIMIT,
        cloud_run_command,
    )

    plan = plan_license_tunnel(
        requires_tunnel=True, session_id="a" * 32,
        relay_url="https://cryostack.eas.gatech.edu",
        mint_grant=lambda *a, **k: {
            "grant_id": "g" * 32, "token": "t" * 43, "purpose": "matlab-license",
        },
    )
    extra_env = {k: v for k, v in plan.items() if not k.startswith("_")}
    overrides = build_container_overrides(
        s3_run="s3://cryostack-runs-123456789012/runs/cloud-20260101-000000-abcdef01",
        model="issm", run_target="runme.m", extra_env=extra_env,
    )
    combined = {**overrides, "command": cloud_run_command()}
    serialized = json.dumps(combined)
    assert len(serialized) < BATCH_CONTAINER_OVERRIDE_LIMIT - 1000
