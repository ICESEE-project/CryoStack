"""cryostack_src.cloud.runtime -- the PRRTE slot-undercounting fix for the
staged ISSM branch script, on Fargate AND EC2 alike.

Live Fargate diagnostics (see test_cloud_runtime_cpu_diagnostics.py)
confirmed a 2 vCPU Fargate task is genuinely 2 hardware threads of ONE
physical core (1 socket, 1 core/socket, 2 threads/core; cgroup CPU quota
unlimited -- no resource shortfall). PRRTE has no scheduler/hostfile on
this path and defaults to counting PHYSICAL CORES as slots, so it sees 1
slot and correctly refuses ISSM's ``mpiexec -np 2`` ("not enough slots")
even though the task truly has 2 usable logical CPUs.

A first attempt set only ``PRTE_MCA_rmaps_default_mapping_policy=:hwtcpus``
(PRRTE's ``map-by`` "HWTCPUS" qualifier). A live run proved this changes
only the mapping/binding CPU type (the one-rank probe's binding notation
did change from ``core:L0`` to ``hwt:L0``) but NOT slot discovery -- the
two-rank probe still failed "not enough slots". ``prterun --help map-by``
itself documents this qualifier as governing only "the mapping
algorithm", a different PRRTE subsystem from slot counting.

The real fix requires BOTH of PRRTE's own MCA parameters that together
implement ``mpiexec --use-hwthread-cpus`` (unusable directly here: ISSM's
own ``generic`` cluster class, ``src/m/classes/clusters/generic.m``
``BuildQueueScript``, hardcodes the literal command as
``sprintf('mpiexec -np %i ', cluster.np)`` with no field for extra
flags/hostfile/launcher options -- there is no CLI-injection seam):

* ``PRTE_MCA_prte_set_default_slots=hwthreads`` -- the actual slot-COUNT
  parameter (found via ``prte_info --all``, MCA "prte" framework
  parameter ``prte_set_default_slots``: "Set the number of slots on
  nodes that lack such info to the number of specified objects [...
  'cores' (default) ... or 'hwthreads' ...]").
* ``PRTE_MCA_rmaps_default_mapping_policy=:hwtcpus`` -- the mapping/
  binding CPU type, kept from the first attempt (still required: setting
  only the slots var fixes slot discovery but then fails at BINDING,
  since mapping is still core-based).

A SECOND attempt gated these two variables on ECS Task Metadata's
``LaunchType == "FARGATE"``, on the theory that EC2 always exposes
genuine independent cores. The first live EC2 run disproved this: that
EC2 instance ALSO had 1 core / 2 hardware threads (nproc --all=2,
lscpu Thread(s) per core=2), LaunchType correctly reported "EC2", the
Fargate-only gate left PRRTE's defaults untouched, and slot discovery
failed identically to the original bug. LaunchType says nothing about
real topology -- EC2 instance types vary independently of launch type.

The final, topology-based criterion: parse ``lscpu``'s own
"Thread(s) per core" line. > 1 means the allocated logical CPUs are
hardware threads of fewer physical cores than PRRTE's core-based default
would count -- apply the verified pair above, on ANY provider. == 1
means the logical CPUs already ARE independent cores -- PRRTE's default
is already correct and must be left alone (this is what keeps an EC2
instance with 2 genuine cores on normal core-based behavior). Unparseable
or missing `lscpu` output fails safe to PRRTE's untouched defaults --
never guessed either way. LaunchType is still fetched and logged for
diagnostics, but is no longer the decision criterion.

Verified locally, both statically and functionally (via subprocess), by
reproducing the failing 1-core/2-hwthread topology using hwloc's
synthetic-topology support (``HWLOC_SYNTHETIC="pack:1 core:1 pu:2"``,
which PRRTE's embedded hwloc honors) on hardware that has no real SMT to
test against otherwise -- see
``test_env_vars_are_the_locally_proven_equivalent_of_use_hwthread_cpus``
for the direct proof that these two env vars alone (no CLI flags)
reproduce ``mpiexec --use-hwthread-cpus`` exactly.

These tests exercise both the static script content and the actual bash
branching logic (via subprocess, with ``curl``/``lscpu``/``with-issm``
stubbed) -- not just text presence.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.runtime import build_cloud_runner, issm_cloud_runner_script

_SLOTS_EXPORT = 'export PRTE_MCA_prte_set_default_slots="hwthreads"'
_MAPPING_EXPORT = 'export PRTE_MCA_rmaps_default_mapping_policy=":hwtcpus"'


def _non_comment_lines(script: str) -> str:
    return "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#"))


# ── confined to the staged ISSM runner; other paths untouched ──────────
def test_hwtcpus_fix_lives_only_in_the_staged_issm_script():
    script = issm_cloud_runner_script()
    assert _SLOTS_EXPORT in script
    assert _MAPPING_EXPORT in script
    assert "Thread(s) per core" in script
    # LaunchType is still fetched for diagnostics, but must never be the
    # only signal driving the export lines themselves (see the functional
    # tests below for the actual behavioral proof).
    assert "LaunchType" in script


def test_hwtcpus_fix_never_leaks_into_the_generic_inline_runner():
    """icepack/smoke, and the 8192-char Container Overrides budget, must
    be completely unaffected -- this lives only in the separately-staged
    ISSM file."""
    generic = build_cloud_runner()
    assert "HWTCPUS" not in generic
    assert "hwthreads" not in generic
    assert "LaunchType" not in generic
    assert "rmaps_default_mapping_policy" not in generic
    assert "prte_set_default_slots" not in generic


def test_hwtcpus_fix_never_touches_the_remote_slurm_path():
    """cryostack_src.models.submission._issm_container_mpi_env (the
    Local/Remote/Slurm path's own, unrelated PRRTE fix for a different
    failure mode) must be byte-for-byte unchanged -- it already sets its
    OWN rmaps_default_mapping_policy value (":oversubscribe", for a
    genuinely different problem: np may exceed a small node's real core
    count there). The two fixes must never be confused or merged."""
    from cryostack_src.models.submission import _issm_container_mpi_env

    env = _issm_container_mpi_env()
    assert env == (
        "--env PRTE_MCA_ras=^slurm "
        "--env PRTE_MCA_plm=ssh "
        "--env PRTE_MCA_rmaps_default_mapping_policy=:oversubscribe "
    )
    assert "HWTCPUS" not in env
    assert "hwtcpus" not in env.lower()
    assert "hwthreads" not in env
    assert "prte_set_default_slots" not in env
    assert "LaunchType" not in env


# ── never oversubscribe, never a hostfile, never touches np ────────────
def test_fix_never_uses_oversubscribe_or_a_hostfile():
    """The allocation is not being exceeded -- it is being undercounted
    -- so this must never be solved by permitting more processes than
    slots (--oversubscribe) or by manufacturing a slot count via a
    hostfile now that the real topology is known precisely."""
    executable = _non_comment_lines(issm_cloud_runner_script())
    assert "oversubscribe" not in executable.lower()
    assert "hostfile" not in executable.lower()


def test_fix_never_changes_np_or_requested_aws_resources():
    # explanatory comments and echo'd section headers legitimately name
    # ISSM's own "-np 2" (to justify why the fix is needed) -- the real
    # invariant is that no actual mpiexec/prterun INVOCATION line in
    # this script sets/changes it.
    script = issm_cloud_runner_script()
    invocation_lines = [
        line for line in _non_comment_lines(script).splitlines()
        if ("mpiexec" in line or "prterun" in line) and "echo" not in line]
    assert invocation_lines, "expected at least one mpiexec invocation line"
    assert not any("-np 2" in line for line in invocation_lines)
    assert "CRYOSTACK_CLOUD_VCPU" not in script
    # the MPI-as-root fix from the prior patch must still be present,
    # completely undisturbed by this one
    assert "export OMPI_ALLOW_RUN_AS_ROOT=1" in script
    assert "export OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1" in script


def test_fix_never_calls_fail_or_exit():
    script = issm_cloud_runner_script()
    start = script.index('# -- CPU topology fix')
    end = script.index('log "diagnostics: begin')
    block = script[start:end]
    assert "fail " not in block
    assert "fail(" not in block
    assert "\nexit" not in block


def test_ecs_metadata_is_fetched_only_once():
    """No second network round-trip for the same information -- the
    topology-fix block fetches ECS Task Metadata once into
    _ecs_task_metadata (used only to parse LaunchType, which the
    diagnostics block then just logs by name -- never re-fetched)."""
    script = issm_cloud_runner_script()
    assert script.count("curl -s -m 5") == 1
    assert "_ecs_task_metadata=\"$(curl" in script
    assert "LaunchType=${_ecs_launch_type:-<not found>}" in script


def test_two_rank_diagnostic_probe_matches_issms_real_np_but_never_launches_issm_exe():
    script = issm_cloud_runner_script()
    assert "mpiexec --report-bindings -n 2 true" in script
    # explanatory comments (both the probe's own section header and the
    # topology-fix rationale above it) legitimately name "issm.exe" --
    # the invariant is that the actual invocation line never does.
    invoke_line = next(
        line for line in script.splitlines()
        if "mpiexec --report-bindings -n 2 true" in line)
    assert "issm.exe" not in invoke_line


# ── functional: actually execute the branching logic ────────────────────
def _run_with_stubs(
    *, curl_response: str | None, metadata_uri: str | None,
    lscpu_output: str | None,
) -> dict:
    """Execute the ACTUAL topology-fix block (extracted from the real
    generated script, not reimplemented) with with-issm/curl/lscpu
    stubbed and the MATLAB invocation removed, returning the parsed
    LaunchType/threads-per-core and whether the overrides took effect.
    This proves the bash branching logic itself works, not just that
    certain strings appear in the script text."""
    script = issm_cloud_runner_script()
    # stop before the final matlab invocation -- never execute it
    script = script.split('with-issm matlab')[0]

    stub_curl = ""
    if curl_response is not None:
        stub_curl = f"curl() {{ printf '%s' {curl_response!r}; }}\n"
    stub_lscpu = "lscpu() { return 1; }\n"
    if lscpu_output is not None:
        # base64-encoded: lscpu_output contains real newlines, and a
        # Python !r repr of a multi-line string turns those into literal
        # backslash-n text once embedded in a bash single-quoted string
        # (single quotes never interpret escapes) -- silently breaking
        # `grep '^Thread(s) per core:'`'s line-anchored match. Round-
        # tripping through base64 sidesteps quoting entirely.
        import base64
        _encoded = base64.b64encode(lscpu_output.encode()).decode()
        stub_lscpu = f"lscpu() {{ printf '%s' {_encoded!r} | base64 -d; }}\n"

    harness = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -uo pipefail
        log()  {{ printf '[cryostack-cloud] %s\\n' "$*" >&2; }}
        with-issm() {{ echo "with-issm: $*: not available" >&2; return 127; }}
        {stub_curl}
        {stub_lscpu}
        WORKDIR=/tmp
        RUN_TARGET=runme.m
        {script}
        echo "RESULT_LAUNCH_TYPE=${{_ecs_launch_type:-}}"
        echo "RESULT_THREADS_PER_CORE=${{_cs_threads_per_core:-}}"
        echo "RESULT_SLOTS_POLICY=${{PRTE_MCA_prte_set_default_slots:-}}"
        echo "RESULT_MAPPING_POLICY=${{PRTE_MCA_rmaps_default_mapping_policy:-}}"
        """)
    env = {"PATH": "/usr/bin:/bin"}
    if metadata_uri is not None:
        env["ECS_CONTAINER_METADATA_URI_V4"] = metadata_uri

    proc = subprocess.run(
        ["bash", "-c", harness], capture_output=True, text=True, timeout=15, env=env)
    result = {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT_LAUNCH_TYPE="):
            result["launch_type"] = line.split("=", 1)[1]
        elif line.startswith("RESULT_THREADS_PER_CORE="):
            result["threads_per_core"] = line.split("=", 1)[1]
        elif line.startswith("RESULT_SLOTS_POLICY="):
            result["slots_policy"] = line.split("=", 1)[1]
        elif line.startswith("RESULT_MAPPING_POLICY="):
            result["mapping_policy"] = line.split("=", 1)[1]
    return result


_FARGATE_METADATA = (
    '{"Cluster":"cryostack","LaunchType":"FARGATE","Limits":{"CPU":2,"Memory":8192}}'
)
_EC2_METADATA = (
    '{"Cluster":"cryostack","LaunchType":"EC2","Limits":{"CPU":2048,"Memory":8192}}'
)
_LSCPU_1_CORE_2_THREADS = (
    "Architecture:            x86_64\n"
    "CPU(s):                  2\n"
    "Thread(s) per core:      2\n"
    "Core(s) per socket:      1\n"
    "Socket(s):               1\n"
)
_LSCPU_2_GENUINE_CORES = (
    "Architecture:            x86_64\n"
    "CPU(s):                  2\n"
    "Thread(s) per core:      1\n"
    "Core(s) per socket:      2\n"
    "Socket(s):               1\n"
)


def test_functional_fargate_1core_2threads_applies_hwthread_overrides():
    """The original bug: a 2 vCPU Fargate task that is 1 core / 2 threads."""
    result = _run_with_stubs(
        curl_response=_FARGATE_METADATA, metadata_uri="http://169.254.170.2/v4/fake",
        lscpu_output=_LSCPU_1_CORE_2_THREADS,
    )
    assert result["returncode"] == 0, result["stderr"]
    assert result["launch_type"] == "FARGATE"
    assert result["threads_per_core"] == "2"
    assert result["slots_policy"] == "hwthreads"
    assert result["mapping_policy"] == ":hwtcpus"


def test_functional_ec2_1core_2threads_also_applies_hwthread_overrides():
    """The live regression this patch fixes: an EC2 task with the SAME
    1 core / 2 threads topology as the original Fargate bug must ALSO get
    the fix -- LaunchType alone is no longer sufficient reason to skip it."""
    result = _run_with_stubs(
        curl_response=_EC2_METADATA, metadata_uri="http://169.254.170.2/v4/fake",
        lscpu_output=_LSCPU_1_CORE_2_THREADS,
    )
    assert result["returncode"] == 0, result["stderr"]
    assert result["launch_type"] == "EC2"
    assert result["threads_per_core"] == "2"
    assert result["slots_policy"] == "hwthreads"
    assert result["mapping_policy"] == ":hwtcpus"


def test_functional_ec2_with_2_genuine_cores_leaves_prrte_defaults_untouched():
    """An EC2 instance that exposes 2 REAL independent cores (Thread(s)
    per core=1) must keep PRRTE's normal core-based behavior -- the fix
    must never be blindly forced onto every EC2 task."""
    result = _run_with_stubs(
        curl_response=_EC2_METADATA, metadata_uri="http://169.254.170.2/v4/fake",
        lscpu_output=_LSCPU_2_GENUINE_CORES,
    )
    assert result["returncode"] == 0, result["stderr"]
    assert result["launch_type"] == "EC2"
    assert result["threads_per_core"] == "1"
    assert result["slots_policy"] == ""
    assert result["mapping_policy"] == ""


def test_functional_fargate_with_2_genuine_cores_also_leaves_defaults_untouched():
    """Symmetric case: even on Fargate, if the topology ever genuinely
    reported 2 independent cores, the fix must not apply -- the criterion
    is topology, not provider."""
    result = _run_with_stubs(
        curl_response=_FARGATE_METADATA, metadata_uri="http://169.254.170.2/v4/fake",
        lscpu_output=_LSCPU_2_GENUINE_CORES,
    )
    assert result["returncode"] == 0, result["stderr"]
    assert result["threads_per_core"] == "1"
    assert result["slots_policy"] == ""
    assert result["mapping_policy"] == ""


def test_functional_lscpu_unavailable_fails_safe_to_untouched_default():
    result = _run_with_stubs(
        curl_response=_FARGATE_METADATA, metadata_uri="http://169.254.170.2/v4/fake",
        lscpu_output=None,
    )
    assert result["returncode"] == 0, result["stderr"]
    assert result["threads_per_core"] == ""
    assert result["slots_policy"] == ""
    assert result["mapping_policy"] == ""


def test_functional_lscpu_malformed_output_fails_safe_to_untouched_default():
    """lscpu ran but its output has no parseable 'Thread(s) per core' line
    (unexpected format/locale/truncated output) -- must never crash and
    must never guess a hardware-thread topology."""
    result = _run_with_stubs(
        curl_response=_FARGATE_METADATA, metadata_uri="http://169.254.170.2/v4/fake",
        lscpu_output="not the expected lscpu format at all",
    )
    assert result["returncode"] == 0, result["stderr"]
    assert result["threads_per_core"] == ""
    assert result["slots_policy"] == ""
    assert result["mapping_policy"] == ""


def test_functional_no_ecs_metadata_still_detects_topology_from_lscpu_alone():
    """A non-ECS/dev environment (no ECS_CONTAINER_METADATA_URI_V4 at all)
    must still apply the fix from lscpu alone -- LaunchType is diagnostic
    only, never required for the decision."""
    result = _run_with_stubs(
        curl_response=None, metadata_uri=None, lscpu_output=_LSCPU_1_CORE_2_THREADS,
    )
    assert result["returncode"] == 0, result["stderr"]
    assert result["launch_type"] == ""
    assert result["threads_per_core"] == "2"
    assert result["slots_policy"] == "hwthreads"
    assert result["mapping_policy"] == ":hwtcpus"


# ── the critical test: local, executable proof of equivalence to the
# real `mpiexec --use-hwthread-cpus` flag, on the failing topology ──────
_HAVE_MPIEXEC = shutil.which("mpiexec") is not None
_HAVE_LSTOPO = shutil.which("lstopo") is not None


@pytest.mark.skipif(
    not (_HAVE_MPIEXEC and _HAVE_LSTOPO),
    reason="requires a local Open MPI/PRRTE + hwloc install to execute real mpiexec")
def test_env_vars_are_the_locally_proven_equivalent_of_use_hwthread_cpus():
    """Reproduces the failing 1-core/2-hwthread topology (seen on both
    Fargate and EC2) via hwloc's synthetic-topology support (no real SMT
    hardware required) and proves two things the user explicitly required
    before another live run:

    1. Literal `mpiexec --use-hwthread-cpus -n 2 --report-bindings true`
       succeeds against this topology (confirming the diagnosis).
    2. Setting ONLY this fix's two env vars -- no CLI flags at all, the
       exact situation ISSM's generic.m puts CryoStack in -- reproduces
       that success identically (same exit code, same
       package[0][hwt:L0-1] binding for both ranks).

    Also confirms the fix does not blanket-oversubscribe: -n 3 against
    the same synthetic 2-hwthread topology still correctly fails.
    """
    import os

    env = {
        "PATH": "/usr/bin:/bin:" + str(Path(shutil.which("mpiexec")).parent),
        "HOME": os.environ.get("HOME", "/tmp"),
        "HWLOC_SYNTHETIC": "pack:1 core:1 pu:2",
        "OMPI_ALLOW_RUN_AS_ROOT": "1",
        "OMPI_ALLOW_RUN_AS_ROOT_CONFIRM": "1",
    }

    def run(*args, extra_env=None):
        full_env = {**env, **(extra_env or {})}
        return subprocess.run(
            ["mpiexec", *args], capture_output=True, text=True, timeout=30, env=full_env)

    # (1) baseline reproduces the live failure exactly
    baseline = run("-n", "2", "--report-bindings", "true")
    assert baseline.returncode != 0
    assert "not enough slots" in (baseline.stdout + baseline.stderr).lower()

    # (2) the real CLI flag succeeds against this exact topology
    real_flag = run("--use-hwthread-cpus", "-n", "2", "--report-bindings", "true")
    assert real_flag.returncode == 0, real_flag.stderr
    real_output = real_flag.stdout + real_flag.stderr

    # (3) our two env vars, alone, with NO CLI flags -- exactly how
    # ISSM's hardcoded `mpiexec -np 2 ...` invocation will see them
    via_env = run(
        "-n", "2", "--report-bindings", "true",
        extra_env={
            "PRTE_MCA_prte_set_default_slots": "hwthreads",
            "PRTE_MCA_rmaps_default_mapping_policy": ":hwtcpus",
        },
    )
    assert via_env.returncode == 0, via_env.stderr
    via_env_output = via_env.stdout + via_env.stderr

    # both ranks bound identically (hardware-thread notation, same node)
    assert "hwt:L0-1" in real_output
    assert "hwt:L0-1" in via_env_output
    assert real_flag.returncode == via_env.returncode == 0

    # not a blanket oversubscribe: a genuinely oversized request still fails
    still_bounded = run(
        "-n", "3", "true",
        extra_env={
            "PRTE_MCA_prte_set_default_slots": "hwthreads",
            "PRTE_MCA_rmaps_default_mapping_policy": ":hwtcpus",
        },
    )
    assert still_bounded.returncode != 0
    assert "not enough slots" in (still_bounded.stdout + still_bounded.stderr).lower()


@pytest.mark.skipif(
    not (_HAVE_MPIEXEC and _HAVE_LSTOPO),
    reason="requires a local Open MPI/PRRTE + hwloc install to execute real mpiexec")
def test_genuine_2core_topology_needs_no_override_and_still_bounds_np():
    """The symmetric proof for the "2 genuine cores" branch: against a
    REAL 2-independent-core synthetic topology, plain `mpiexec -n 2`
    (PRRTE's untouched default) already succeeds with CORE-notation
    bindings -- confirming the fix would be actively wrong to apply here
    -- and -n 3 still correctly fails (bounded, not oversubscribed)."""
    import os

    env = {
        "PATH": "/usr/bin:/bin:" + str(Path(shutil.which("mpiexec")).parent),
        "HOME": os.environ.get("HOME", "/tmp"),
        "HWLOC_SYNTHETIC": "pack:1 core:2 pu:1",
        "OMPI_ALLOW_RUN_AS_ROOT": "1",
        "OMPI_ALLOW_RUN_AS_ROOT_CONFIRM": "1",
    }

    def run(*args):
        return subprocess.run(
            ["mpiexec", *args], capture_output=True, text=True, timeout=30, env=env)

    ok = run("-n", "2", "--report-bindings", "true")
    assert ok.returncode == 0, ok.stderr
    assert "core:" in (ok.stdout + ok.stderr)
    assert "hwt:" not in (ok.stdout + ok.stderr)

    still_bounded = run("-n", "3", "true")
    assert still_bounded.returncode != 0
    assert "not enough slots" in (still_bounded.stdout + still_bounded.stderr).lower()


# ── Container Overrides headroom (unaffected -- diagnostics live in the
# separately-staged file, never the 8192-char-limited inline command) ──
def test_container_overrides_headroom_is_unaffected_by_the_hwtcpus_fix():
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
