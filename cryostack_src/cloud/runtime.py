# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Generic Cloud Runtime
# File        : runtime.py
#
# Description :
#     The provider-neutral cloud execution contract: the small runner that
#     runs inside the batch container, and the machine-readable execution
#     descriptor staged alongside a run's inputs.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-31
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
CryoStack generic cloud runtime.

One small runner, one execution descriptor -- the SAME runner for every
supported model; only the ``case "${CRYOSTACK_MODEL}"`` branch differs. The
runner:

1. reads its runtime configuration from the environment
   (``CRYOSTACK_S3_RUN`` / ``CRYOSTACK_MODEL`` / ``CRYOSTACK_RUN_TARGET``),
2. syncs ``<s3-run>/input/`` into a local working directory,
3. runs the model runtime -- exactly what ``stage_example_for_run`` prepared
   (ISSM: injected ``runme.m``, ``cryostack_md_overrides.m``, ``data/<...>``
   datasets, ``postprocess_icesee.m``; Icepack: the selected example's own
   ``.py``/``.ipynb`` run target, then -- if the caller staged one alongside
   the run inputs -- the portable output collector produced by
   :mod:`cryostack_src.models.icepack.postprocess`),
4. syncs ``<workdir>/outputs/`` back to ``<s3-run>/outputs/`` (best effort,
   even on a failed run), and
5. exits with the *true* model exit code.

No scientific logic lives in the runner beyond selecting the per-model runtime
command. No credentials and no MATLAB license value are ever embedded -- the
license, if any, arrives only through the batch container's environment.

**Execution-artifact contract**: this runner script itself becomes the Batch
job definition's ``containerProperties.command`` (:func:`cloud_run_command`),
and AWS Batch resolves/forwards a job's effective container command through
ECS ``RunTask`` overrides on every launch -- capped at 8192 characters,
exactly like ``submit-job``'s own ``--container-overrides``. Any run-specific
or model-specific logic (an output collector, a helper script, ...) that
would make this text large must therefore never be embedded inline here: it
is staged as an ordinary FILE alongside the run's other inputs (via
``WorkspaceManager.stage_example_for_run``'s ``extra_files``, exactly how
ISSM's own ``postprocess_icesee.m`` already works) and simply *invoked* by
filename after ``phase 1`` downloads it -- the runner only ever contains the
short, per-model INVOCATION, never the helper's source text. A run that
predates this convention (or a caller that never staged the helper) is not a
hard failure: the invocation is skipped with a warning, exactly like every
other best-effort step here.
"""

from __future__ import annotations

import re

#: models with a complete cloud runtime path today
SUPPORTED_CLOUD_MODELS: tuple[str, ...] = ("issm", "icepack")

#: filenames the Icepack branch looks for under WORKDIR after phase 1 -- the
#: SAME names a caller must use as extra_files keys when staging (see
#: icepack_postprocess_extra_files() below); a single source of truth so the
#: runner script and the staging helper can never drift apart. The runner +
#: export module names are re-exported from
#: cryostack_src.models.icepack.export so the cloud and Remote/SLURM paths
#: stage the identical helpers.
ICEPACK_POSTPROCESS_FILENAME = "cryostack_icepack_postprocess.py"
ICEPACK_RUNNER_FILENAME = "cryostack_icepack_runner.py"
ICEPACK_EXPORT_FILENAME = "cryostack_icepack_export.py"

#: ISSM's optional private-service license tunnel client
#: (cryostack_src.cloud.license_tunnel_client) -- staged as a standalone
#: FILE alongside the run's other inputs, the SAME mechanism the Icepack
#: helpers above already use, and invoked by filename after phase 1 --
#: NEVER via ``python3 -m cryostack_src...``. The Batch container is a
#: scientific image (ISSM/Icepack/MATLAB); it does not, and must not need
#: to, have the CryoLauncher web application's own ``cryostack_src``
#: package installed to run this one small, dependency-minimal helper.
LICENSE_TUNNEL_CLIENT_FILENAME = "cryostack_license_tunnel_client.py"

#: the ISSM branch's own logic (license-tunnel setup + the MATLAB
#: invocation) -- staged as a standalone FILE, the SAME mechanism as
#: LICENSE_TUNNEL_CLIENT_FILENAME above, and invoked by filename from the
#: generic runner's ``issm)`` case. This keeps the inline, per-launch
#: job-definition command small: see issm_cloud_runner_script() and the
#: module docstring's execution-artifact contract.
ISSM_CLOUD_RUNNER_FILENAME = "cryostack_issm_cloud_runner.sh"

#: version of the structured-result contract the run must produce
RESULT_CONTRACT_VERSION = 1

RUN_DESCRIPTOR_NAME = "cryostack-run.json"
RUN_DESCRIPTOR_SCHEMA = "cryostack.cloud.run"
RUN_DESCRIPTOR_VERSION = 1

_RUN_TARGET_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/-]{0,255}\Z")


class CloudRuntimeError(RuntimeError):
    """The cloud runtime contract could not be satisfied for this run."""


def is_supported_cloud_model(model: str) -> bool:
    return (model or "").strip().lower() in SUPPORTED_CLOUD_MODELS


# ── execution descriptor ─────────────────────────────────────────────────
def build_run_descriptor(
    *,
    model: str,
    run_target: str,
    working_directory: str = ".",
    result_contract_version: int = RESULT_CONTRACT_VERSION,
) -> dict:
    """The machine-readable execution descriptor placed under ``input/``.

    Execution inputs only -- **never** AWS/SSH credentials, local user paths or
    a MATLAB license value.
    """
    m = (model or "").strip().lower()
    if not m:
        raise CloudRuntimeError("a cloud run descriptor needs a model")
    target = (run_target or "").strip()
    if not target or target.startswith(("/", "~")) or ".." in target.split("/"):
        raise CloudRuntimeError(f"unsafe run target for a cloud run: {run_target!r}")
    if not _RUN_TARGET_RE.match(target):
        raise CloudRuntimeError(f"unsafe run target for a cloud run: {run_target!r}")
    wd = (working_directory or ".").strip()
    if wd.startswith(("/", "~")) or ".." in wd.split("/"):
        raise CloudRuntimeError(f"working_directory must be relative: {working_directory!r}")
    return {
        "schema": RUN_DESCRIPTOR_SCHEMA,
        "version": RUN_DESCRIPTOR_VERSION,
        "model": m,
        "run_target": target,
        "working_directory": wd or ".",
        "result_contract_version": int(result_contract_version),
    }


_SECRET_HINTS = (
    "aws_access_key", "aws_secret", "aws_session", "secret_access_key",
    "mlm_license", "license_file", "ssh", "password", "token", "/home/",
    "/users/", "credential",
)


def descriptor_is_clean(descriptor: dict) -> bool:
    """True when the descriptor carries no credential-like or absolute-path
    values (a guard for the staging helper and its tests)."""
    import json

    blob = json.dumps(descriptor, sort_keys=True).lower()
    return not any(hint in blob for hint in _SECRET_HINTS)


# ── the runner ───────────────────────────────────────────────────────────
_RUNNER = r"""#!/usr/bin/env bash
# =====================================================================
# CryoStack generic cloud runner  (auto-generated -- do not edit)
# =====================================================================
set -uo pipefail

log()  { printf '[cryostack-cloud] %s\n' "$*" >&2; }
fail() { log "ERROR ($1): $2"; exit "$1"; }

: "${CRYOSTACK_S3_RUN:?CRYOSTACK_S3_RUN is required}"
: "${CRYOSTACK_MODEL:?CRYOSTACK_MODEL is required}"
RUN_TARGET="${CRYOSTACK_RUN_TARGET:-runme.m}"
WORKDIR="${CRYOSTACK_WORKDIR:-/tmp/cryostack/run}"
OUTPUTS="${WORKDIR}/outputs"

command -v aws >/dev/null 2>&1 || fail 3 "the batch container has no 'aws' CLI (needed for S3 I/O)"

# -- phase 1: fetch the staged inputs ---------------------------------
log "phase 1/3  sync  ${CRYOSTACK_S3_RUN}/input/  ->  ${WORKDIR}"
mkdir -p "${WORKDIR}" "${OUTPUTS}" || fail 4 "cannot create ${WORKDIR}"
aws s3 sync "${CRYOSTACK_S3_RUN}/input/" "${WORKDIR}/" --only-show-errors \
    || fail 4 "input sync failed"

# -- phase 2: run the model runtime (the science is never swallowed) --
cd "${WORKDIR}" || fail 5 "cannot enter ${WORKDIR}"
export ICESEE_RUN_DIR="${WORKDIR}"
log "phase 2/3  run   model=${CRYOSTACK_MODEL}  target=${RUN_TARGET}"
# captured now (staged inputs just landed) so a model-specific output
# collector can tell "staged input" from "artifact this run produced"
export CRYOSTACK_RUN_STARTED="$(date +%s)"
rc=0
case "${CRYOSTACK_MODEL}" in
  smoke)
    # license-neutral infrastructure smoke test: no model runtime, just prove
    # the container can read the staged input and write a structured output.
    log "smoke: writing outputs/metadata.json (no model runtime)"
    mkdir -p "${OUTPUTS}"
    _host="$(hostname 2>/dev/null)"; [ -n "${_host}" ] || _host="container"
    printf '{"schema":"cryostack.cloud.smoke","version":1,"ok":true,"run_target":"%s","hostname":"%s"}\n' \
      "${RUN_TARGET}" "${_host}" > "${OUTPUTS}/metadata.json"
    [ -f "${WORKDIR}/${RUN_TARGET}" ] && cp -f "${WORKDIR}/${RUN_TARGET}" "${OUTPUTS}/echoed-input.txt"
    rc=0
    ;;
  issm)
    # tunnel setup + matlab invocation: a STAGED FILE, not inlined here --
    # keeps this per-launch command small (see issm_cloud_runner_script()).
    WORKDIR="${WORKDIR}" RUN_TARGET="${RUN_TARGET}" \
      bash "${WORKDIR}/__CRYOSTACK_ISSM_CLOUD_RUNNER_FILENAME__"
    rc=$?
    ;;
  icepack)
    # notebooks are converted to a script first (same rule as the local /
    # remote Icepack execution path in models/icepack/execution.py); a
    # single stage, no license, no MATLAB. A materialized run.py already IS
    # a script -- the *.ipynb branch only matters for a raw notebook target.
    case "${RUN_TARGET}" in
      *.ipynb)
        PY_TARGET="${RUN_TARGET%.ipynb}.py"
        with-icepack jupyter nbconvert --to script "${WORKDIR}/${RUN_TARGET}" \
          || log "WARNING: nbconvert failed; the run will fail on the missing script"
        SCRIPT="${WORKDIR}/${PY_TARGET}"
        ;;
      *)
        SCRIPT="${WORKDIR}/${RUN_TARGET}"
        ;;
    esac
    # Run through the CryoStack Icepack runner when it was staged (same
    # helper the Remote/SLURM path uses -- cryostack_src/models/icepack/
    # export.py):
    #   * forces a headless Matplotlib backend (Agg) BEFORE the script
    #     imports it -- the tutorials rely on Jupyter inline display;
    #   * persists still-open figures the script drew to
    #     outputs/figures/figure-NN.png (deterministic, de-duplicated, never
    #     by injecting savefig into the science script);
    #   * runs the allow-list structured field export (never guesses).
    # The runner exits with the SCIENCE exit code; its extra steps are
    # non-fatal. Falls back to a bare `python` if the helper wasn't staged.
    if [ -f "${WORKDIR}/__CRYOSTACK_ICEPACK_RUNNER_FILENAME__" ]; then
      with-icepack python "${WORKDIR}/__CRYOSTACK_ICEPACK_RUNNER_FILENAME__" \
        "${SCRIPT}" "${WORKDIR}"
      rc=$?
    else
      MPLBACKEND=Agg with-icepack python "${SCRIPT}"
      rc=$?
    fi
    log "icepack model runtime exit code: ${rc}"
    # Portable stdlib collector (models/icepack/postprocess.py) -- folds any
    # figures / native files into outputs/ and writes an HONEST status
    # (ok | artifacts | empty), never clobbering the exporter's richer
    # metadata. Best effort, even on a failed run (rc is never overwritten):
    # the science already happened. Staged as an ACTUAL FILE alongside
    # run.py -- NEVER embedded inline here (this whole script becomes the
    # Batch job definition's command, capped at 8192 chars on every launch).
    if [ -f "${WORKDIR}/__CRYOSTACK_ICEPACK_PP_FILENAME__" ]; then
      if command -v python3 >/dev/null 2>&1; then
        CRYOSTACK_RUN_DIR="${WORKDIR}" CRYOSTACK_EXAMPLE_DIR="${WORKDIR}" \
        python3 "${WORKDIR}/__CRYOSTACK_ICEPACK_PP_FILENAME__" \
          || log "WARNING: Icepack output collection failed (model rc=${rc})"
      else
        log "WARNING: python3 not found in the container; skipping Icepack output collection"
      fi
    else
      log "WARNING: __CRYOSTACK_ICEPACK_PP_FILENAME__ was not staged with this run's inputs; skipping Icepack output collection"
    fi
    ;;
  *)
    fail 64 "unsupported model: ${CRYOSTACK_MODEL}"
    ;;
esac
log "model runtime exit code: ${rc}"

# -- phase 3: publish outputs (best effort, even on a failed run) ----
if [ -d "${OUTPUTS}" ]; then
  log "phase 3/3  sync  ${OUTPUTS}/  ->  ${CRYOSTACK_S3_RUN}/outputs/"
  aws s3 sync "${OUTPUTS}/" "${CRYOSTACK_S3_RUN}/outputs/" --only-show-errors \
      || log "WARNING: output sync failed (model rc=${rc})"
fi

# -- phase 4: propagate the true scientific exit code --------------
exit "${rc}"
"""


#: the container-overrides / job-definition-command size limit AWS Batch
#: enforces on every job launch (it forwards the effective command through
#: an ECS RunTask override, capped the same as submit-job's own
#: --container-overrides). Kept here so tests -- and any future runner
#: change -- can assert against the real number, not a guess.
BATCH_CONTAINER_OVERRIDE_LIMIT = 8192


def build_cloud_runner() -> str:
    """The generic cloud runner script (identical for every execution mode,
    and for every model -- see this module's docstring for why NO
    model-specific helper source may be embedded here). Only the Icepack
    helper FILENAMES are substituted (a single source of truth shared with
    :func:`icepack_postprocess_extra_files`), never their source text."""
    return (
        _RUNNER
        .replace("__CRYOSTACK_ICEPACK_PP_FILENAME__", ICEPACK_POSTPROCESS_FILENAME)
        .replace("__CRYOSTACK_ICEPACK_RUNNER_FILENAME__", ICEPACK_RUNNER_FILENAME)
        .replace("__CRYOSTACK_LICENSE_TUNNEL_CLIENT_FILENAME__", LICENSE_TUNNEL_CLIENT_FILENAME)
        .replace("__CRYOSTACK_ISSM_CLOUD_RUNNER_FILENAME__", ISSM_CLOUD_RUNNER_FILENAME)
    )


#: the ISSM branch's own script: license-tunnel setup (primary, plus the
#: optional FlexNet vendor-daemon hop -- see matlab_license.
#: plan_license_tunnel/site_cloud_license_vendor_port) then the MATLAB
#: invocation. Staged as an ACTUAL FILE (see issm_cloud_runner_extra_files
#: below), never embedded in the generic runner's own command text -- see
#: BATCH_CONTAINER_OVERRIDE_LIMIT and this module's docstring. ``WORKDIR``
#: and ``RUN_TARGET`` are handed in as plain environment variables by the
#: generic runner's ``issm)`` case (they are not exported there).
#:
#: A tunnel failure here (``fail 65 ...``) exits only THIS child process,
#: unlike the old inlined version which exited the whole top-level runner
#: immediately. The generic runner still captures this file's exit code
#: as ``rc`` and propagates it unchanged (phase 4) -- the only observable
#: difference is a harmless, best-effort phase-3 sync of an (empty, since
#: MATLAB never started) outputs directory before the same final exit
#: code is returned.
_ISSM_CLOUD_RUNNER = r"""#!/usr/bin/env bash
# =====================================================================
# CryoStack ISSM cloud-run branch  (auto-generated -- do not edit)
# =====================================================================
set -uo pipefail

log()  { printf '[cryostack-cloud] %s\n' "$*" >&2; }
fail() { log "ERROR ($1): $2"; exit "$1"; }

# The Fargate/EC2 task runs this container as whatever user the image
# defaults to -- bkyanjo/icesee-combined sets no USER (tools/cloud/
# Dockerfile), so that is root. ISSM's ``generic`` MPI cluster launches
# its solver via Spack OpenMPI 5 / PRRTE's own ``mpiexec``/``prterun``,
# which refuses outright to run as root ("prterun has detected an
# attempt to run as root") -- this is PRRTE's own built-in safety check,
# not a launch-agent/allocation problem. These are PRRTE/Open MPI's own
# advertised override variables for a deliberately root-only container
# (its own failure message names exactly these two) -- never a CLI flag,
# since ISSM (not CryoStack) constructs the actual mpiexec/prterun
# command line. Unrelated to, and never applied on, the Slurm/Remote
# path's own PRTE_MCA_* fix in cryostack_src.models.submission
# (_issm_container_mpi_env) -- that fixes a different PRRTE failure mode
# (multi-node Slurm allocation confusing the launch agent), and apptainer
# there already runs as the submitting HPC user, never root.
export OMPI_ALLOW_RUN_AS_ROOT=1
export OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1

# optional private-service license tunnel (values read from env by
# license_tunnel_client.py itself); aborts before matlab on failure.
# Staged as an ACTUAL FILE (phase 1 already synced it into WORKDIR) --
# never `python3 -m cryostack_src...`: this container has no reason to
# have the CryoLauncher web app's own package installed.
if [ "${CRYOSTACK_LICENSE_TUNNEL_REQUIRED:-0}" = "1" ]; then
  _lt_msg="$(python3 "${WORKDIR}/__CRYOSTACK_LICENSE_TUNNEL_CLIENT_FILENAME__" listen)" \
    || fail 65 "${_lt_msg}"
  _mlm="MLM_LICENSE_FILE"
  export "${_mlm}=${CRYOSTACK_LT_PORT}@127.0.0.1"
  # optional second hop: this site's FlexNet vendor daemon (only set
  # when the site profile confirms one -- see matlab_license.
  # site_cloud_license_vendor_port). Reuses the same relay/session/
  # token/purpose (already in this process's own environment) --
  # only the endpoint and local port differ, so both are given
  # explicitly rather than repeating the whole flag set.
  if [ -n "${CRYOSTACK_LT_VENDOR_PORT:-}" ]; then
    _lt_msg2="$(python3 "${WORKDIR}/__CRYOSTACK_LICENSE_TUNNEL_CLIENT_FILENAME__" listen \
      --endpoint vendor --port "${CRYOSTACK_LT_VENDOR_PORT}")" \
      || fail 65 "${_lt_msg2}"
  fi
fi

# -- CPU topology fix (Fargate and EC2 alike): live diagnostics confirmed
# a 2 vCPU Fargate task is genuinely 2 hardware threads of ONE physical
# core (1 socket, 1 core/socket, 2 threads/core; cgroup CPU quota unlimited -- no
# resource shortfall at all). PRRTE has no scheduler/hostfile on this
# path, so it defaults to counting PHYSICAL CORES as slots: it sees 1
# core -> 1 slot, and correctly refuses ISSM's mpiexec -np 2 ("not
# enough slots") even though the task truly has 2 usable logical CPUs.
#
# The allocation is not being exceeded -- it is being undercounted --
# so this is fixed by making PRRTE behave as if `mpiexec
# --use-hwthread-cpus` had been passed, never by --oversubscribe (which
# would still be lying about how many slots exist) or a hostfile (which
# would be manufacturing a number we now know precisely from the real
# topology). --use-hwthread-cpus itself can't be used directly: ISSM's
# own generic cluster class (src/m/classes/clusters/generic.m,
# BuildQueueScript) hardcodes the literal command as
# `sprintf('mpiexec -np %i ', cluster.np)` with no field at all for
# extra flags, launcher options, or a hostfile -- confirmed by reading
# that class's full property list and BuildQueueScript body; there is
# no supported seam to inject a CLI flag here without modifying ISSM
# itself or the scientific runme.m, neither of which this patch touches.
#
# A first attempt set only PRTE_MCA_rmaps_default_mapping_policy=:hwtcpus
# (PRRTE's `map-by` "HWTCPUS" qualifier). A live run showed this changes
# ONLY the mapping/binding CPU type (confirmed by the one-rank probe's
# binding notation changing from package[0][core:L0] to
# package[0][hwt:L0]) but NOT slot discovery -- the two-rank probe still
# reported "not enough slots", and `prterun --help map-by` itself
# documents this qualifier as governing only "the mapping algorithm",
# a separate PRRTE subsystem from slot counting.
#
# The actual slot-count parameter, found via `prte_info --all` (not
# guessed): MCA "prte" framework parameter "prte_set_default_slots" --
# "Set the number of slots on nodes that lack such info to the number
# of specified objects [... 'cores' (default) ... or 'hwthreads' ...]".
# Reproduced the exact live failure and fix locally using hwloc's
# synthetic-topology support (HWLOC_SYNTHETIC="pack:1 core:1 pu:2",
# which PRRTE's embedded hwloc honors) to emulate Fargate's precise
# 1-core/2-hwthread shape on hardware that has no real SMT to test
# against otherwise:
#   - plain `mpiexec -n 2 --report-bindings true`: fails "not enough
#     slots" (reproduces the live failure exactly)
#   - `mpiexec --use-hwthread-cpus -n 2 --report-bindings true`:
#     succeeds, binds both ranks to package[0][hwt:L0-1]; PRRTE's own
#     error text for the failing case even names this flag as the fix
#   - PRTE_MCA_prte_set_default_slots=hwthreads alone: fixes slot
#     discovery (no more "not enough slots") but then fails at BINDING
#     instead, because mapping is still CORE-based -- confirming the
#     two MCA parameters are independent and both are required
#   - PRTE_MCA_prte_set_default_slots=hwthreads together with
#     PRTE_MCA_rmaps_default_mapping_policy=:hwtcpus, as plain
#     environment variables with NO CLI flags at all: succeeds
#     identically to --use-hwthread-cpus (same exit code, same
#     package[0][hwt:L0-1] binding output) -- this is the exact,
#     locally-proven environment-variable equivalent of
#     --use-hwthread-cpus for an mpiexec invocation whose command line
#     CryoStack cannot alter
#   - -n 3 against the same synthetic 2-hwthread topology still
#     correctly fails "not enough slots" (verified on both the
#     synthetic topology and, for -n 9 against 8 real cores, on this
#     machine's real hardware) -- this is not a blanket oversubscribe,
#     it reflects the real, now-correctly-counted slot total
#
# A first live EC2 run then proved LaunchType is the WRONG detection
# criterion, not merely too narrow: the very first ISSM/EC2 attempt
# landed on an EC2 instance whose topology is ALSO 1 core / 2 hardware
# threads (nproc --all=2, Thread(s) per core=2, Core(s) per socket=1,
# Socket(s)=1) -- ECS reported LaunchType=EC2, this Fargate-only gate
# left PRRTE's defaults untouched, and slot discovery failed identically
# to the original Fargate bug. EC2 instance TYPES vary in real core
# count independently of launch type -- LaunchType tells us nothing
# about whether the allocated logical CPUs are independent cores or
# hardware threads of fewer cores; only the topology itself does.
#
# The detection criterion is therefore the topology fact this whole
# investigation has always actually been about: hardware threads per
# core, read directly from `lscpu` (already relied on, unconditionally,
# by the diagnostics below -- this reuses that same tool, just earlier
# and parsed). Thread(s) per core > 1 means the allocated logical CPUs
# are hardware threads of fewer physical cores than PRRTE's core-based
# default would count -- exactly the condition the verified
# --use-hwthread-cpus-equivalent pair (see above) corrects, on ANY
# provider or instance shape, Fargate or EC2 alike. Thread(s) per
# core == 1 means the allocated logical CPUs already ARE independent
# cores -- PRRTE's default core-based accounting is already correct
# and must be left alone (an EC2 instance with 2 genuine cores must
# never be forced into hardware-thread semantics it does not need).
# Fails safe: if `lscpu` is unavailable or its output does not parse to
# a plain positive integer, PRRTE's untouched defaults (CORECPUS
# mapping, cores-based slot count) are kept -- never guessed either way.
#
# ARCHITECTURAL NOTE (not fixed here, follow-up work): the "2" in
# "2 vCPU" and the "2" in ISSM's mpiexec -np 2 currently agree only by
# coincidence -- np comes from the scientist's own scaffolded example
# (cryostack_src/models/issm/execution.py), completely independent of
# whatever CPU allocation CryoStack actually requested for this job
# (cryostack_src/cloud/drivers/aws/batch_config.py). CryoStack does not
# yet validate or derive the ISSM process count from the selected cloud
# resource allocation. This patch makes today's np=2 request work
# correctly against the real topology of whatever instance the task
# lands on; it does not make the two numbers agree by design for a
# future np/vCPU mismatch.
_ecs_task_metadata=""
if [ -n "${ECS_CONTAINER_METADATA_URI_V4:-}" ]; then
  _ecs_task_metadata="$(curl -s -m 5 "${ECS_CONTAINER_METADATA_URI_V4}/task" 2>/dev/null)"
fi
_ecs_launch_type="$(printf '%s' "${_ecs_task_metadata}" \
  | grep -o '"LaunchType"[[:space:]]*:[[:space:]]*"[A-Za-z0-9_-]*"' \
  | grep -o '"[A-Za-z0-9_-]*"$' | tr -d '"')"
_cs_threads_per_core="$(lscpu 2>/dev/null \
  | grep -i '^Thread(s) per core:' | grep -o '[0-9]\+' | head -1)"
case "${_cs_threads_per_core}" in
  ''|*[!0-9]*)
    log "topology: could not determine hardware threads per core (lscpu unavailable or unparseable, LaunchType=${_ecs_launch_type:-unknown}) -- leaving PRRTE's defaults (core-based slots and mapping) unchanged"
    ;;
  *)
    if [ "${_cs_threads_per_core}" -gt 1 ]; then
      log "topology: lscpu reports ${_cs_threads_per_core} hardware thread(s) per core (LaunchType=${_ecs_launch_type:-unknown}) -- using PRRTE's hardware-thread slot count and mapping (== mpiexec --use-hwthread-cpus)"
      export PRTE_MCA_prte_set_default_slots="hwthreads"
      export PRTE_MCA_rmaps_default_mapping_policy=":hwtcpus"
    else
      log "topology: lscpu reports ${_cs_threads_per_core} hardware thread(s) per core (LaunchType=${_ecs_launch_type:-unknown}) -- leaving PRRTE's defaults (core-based slots and mapping) unchanged"
    fi
    ;;
esac

# -- diagnostics: a compact CPU-topology/PRRTE-slot summary, kept (in
# trimmed form) as a standing aid for any future slot-discovery failure
# on a not-yet-seen instance shape -- the original investigation's
# exhaustive fact-finding (cgroup v1/v2 quota files, cpuset files,
# /proc/self/status, full lscpu/hwloc dumps) has been removed now that
# the root cause is closed and permanently encoded in the topology
# criterion itself above (no cgroup CPU-quota shortfall was ever
# involved -- confirmed and documented there). Strictly best-effort and
# informational -- every command is individually guarded and none of
# their exit codes are consulted, so nothing here can fail, block, or
# change what runs afterward. `mpiexec` is only resolvable once
# `with-issm` has set up the Spack OpenMPI PATH (see with-issm's own
# script), so that probe runs THROUGH with-issm -- the exact environment
# the real solver launch below uses -- while system-level probes
# (nproc, lscpu) run directly. Never launches ISSM's own solver
# (issm.exe) and never changes allocation/mapping behavior (no
# --oversubscribe, no hostfile, no env var overrides).
log "diagnostics: begin (CPU/topology/PRRTE, informational only)"
{
  echo "== CPU topology =="
  echo "nproc --all: $(nproc --all 2>&1 || echo unavailable)"
  lscpu 2>&1 | grep -E '^(Thread\(s\) per core|Core\(s\) per socket|Socket\(s\)):' \
    || echo "(lscpu unavailable)"
  echo "== topology detection criterion and PRRTE hardware-thread overrides applied =="
  echo "LaunchType=${_ecs_launch_type:-<not found>} (informational only -- no longer the detection criterion)"
  echo "lscpu Thread(s) per core=${_cs_threads_per_core:-<unparseable>}"
  echo "PRTE_MCA_prte_set_default_slots=${PRTE_MCA_prte_set_default_slots:-<unset -- PRRTE default (cores)>}"
  echo "PRTE_MCA_rmaps_default_mapping_policy=${PRTE_MCA_rmaps_default_mapping_policy:-<unset -- PRRTE default (CORECPUS)>}"
  echo "== Open MPI / PRRTE version =="
  with-issm mpiexec --version 2>&1 || echo "(unavailable)"
  echo "== PRRTE single-process report-bindings (never launches issm.exe) =="
  with-issm timeout 15 mpiexec --report-bindings -n 1 true 2>&1 \
    || echo "(unavailable or failed -- informational only)"
  echo "== PRRTE two-process report-bindings, matching ISSM's -np 2 (still never launches issm.exe -- direct proof this run's real solver launch will or will not get enough slots) =="
  with-issm timeout 15 mpiexec --report-bindings -n 2 true 2>&1 \
    || echo "(unavailable or failed -- informational only)"
} >&2
log "diagnostics: end"

with-issm matlab -nodesktop -nosplash -batch \
  "ICESEE_RUN_DIR='${WORKDIR}'; setenv('ICESEE_RUN_DIR','${WORKDIR}'); run('${RUN_TARGET}'); run('${WORKDIR}/postprocess_icesee.m');"
"""


def issm_cloud_runner_script() -> str:
    """The staged ISSM branch script (see :data:`_ISSM_CLOUD_RUNNER`) --
    only the license-tunnel-client FILENAME is substituted (a single
    source of truth shared with :func:`license_tunnel_client_extra_files`),
    never its source text."""
    return _ISSM_CLOUD_RUNNER.replace(
        "__CRYOSTACK_LICENSE_TUNNEL_CLIENT_FILENAME__", LICENSE_TUNNEL_CLIENT_FILENAME)


def icepack_postprocess_extra_files() -> dict[str, str]:
    """The ``extra_files`` a cloud-run caller merges into
    ``WorkspaceManager.stage_example_for_run`` so the Icepack post-run
    helpers are staged as ordinary files alongside ``run.py`` -- the SAME
    generic mechanism ISSM's own ``postprocess_icesee.m`` already uses, and
    the SAME helper source the Remote/SLURM path stages
    (``cryostack_src.models.icepack.export``). Never embedded into the runner
    script itself (see the module docstring and
    :data:`BATCH_CONTAINER_OVERRIDE_LIMIT`).

    Three files:

    * ``cryostack_icepack_runner.py`` -- forces a headless Matplotlib
      backend, runs the science script, persists live figures, then runs the
      structured export;
    * ``cryostack_icepack_export.py`` -- the allow-list structured field
      exporter (needs Firedrake -- runs in ``with-icepack``);
    * ``cryostack_icepack_postprocess.py`` -- the stdlib collector that folds
      figures / native files into ``outputs/`` and writes an honest status.
    """
    from cryostack_src.models.icepack.export import (
        export_module_source,
        runner_module_source,
    )
    from cryostack_src.models.icepack.postprocess import build_postprocess

    return {
        ICEPACK_RUNNER_FILENAME: runner_module_source(),
        ICEPACK_EXPORT_FILENAME: export_module_source(),
        ICEPACK_POSTPROCESS_FILENAME: build_postprocess(),
    }


#: dedicated runtime-support directory the tunnel client's own dependency
#: bundle is staged under -- NEVER mixed into the scientist's model/example
#: files. cryostack_src.cloud.license_tunnel_client adds this (resolved
#: next to its own staged file) to sys.path for THIS PROCESS ONLY before
#: ``import websockets`` is attempted; nothing outside that one process is
#: ever touched (no /opt/venv-* modification, no global PYTHONPATH).
RUNTIME_SUPPORT_DIRNAME = ".cryostack_runtime"

#: the pinned, vendored websockets subset -- see
#: cryostack_src/cloud/_vendor/websockets_16_0/PROVENANCE.md for exactly
#: which modules and why (empirically traced against the real client-only
#: connect/send/recv/close code path, no C extension -- frames.py's own
#: ``try: from .speedups import apply_mask / except ImportError: from
#: .utils import apply_mask`` fallback is relied on deliberately).
_VENDOR_WEBSOCKETS_DIR = "websockets_16_0"
_VENDOR_WEBSOCKETS_STAGED_PACKAGE = "websockets"


def license_tunnel_client_extra_files() -> dict[str, str]:
    """The ``extra_files`` a cloud-run caller merges into
    ``WorkspaceManager.stage_example_for_run`` so ISSM's optional private-
    service license tunnel client -- AND its pinned ``websockets``
    dependency bundle -- are staged as ordinary files alongside the run's
    other inputs -- the SAME mechanism :func:`icepack_postprocess_extra_files`
    already uses, extended (see ``WorkspaceManager._write_extra_file``) to
    also accept the few ``/``-separated, safely-contained relative paths
    needed to lay out a real importable package tree under
    ``.cryostack_runtime/websockets/`` -- never mixed with the scientist's
    own model/example files.

    The module itself (``cryostack_src.cloud.license_tunnel_client``) has
    no ``cryostack_src`` imports of its own, precisely so its raw source
    text is safe to stage and run standalone inside the scientific Batch
    container, which does not have the CryoLauncher web application's own
    package installed. Staged unconditionally for every ISSM cloud run
    (cheap, and the runner only ever INVOKES the client when
    ``CRYOSTACK_LICENSE_TUNNEL_REQUIRED=1``) -- never embedded into the
    runner script itself (see the module docstring and
    :data:`BATCH_CONTAINER_OVERRIDE_LIMIT`)."""
    from pathlib import Path

    import cryostack_src.cloud.license_tunnel_client as _ltc

    files: dict[str, str] = {
        LICENSE_TUNNEL_CLIENT_FILENAME: Path(_ltc.__file__).read_text(encoding="utf-8"),
    }

    vendor_root = Path(__file__).with_name("_vendor") / _VENDOR_WEBSOCKETS_DIR
    for path in sorted(vendor_root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in (".py",) and path.name != "LICENSE":
            continue    # never the .md provenance note -- repo-only documentation
        rel = path.relative_to(vendor_root)
        staged_rel = "/".join(
            (RUNTIME_SUPPORT_DIRNAME, _VENDOR_WEBSOCKETS_STAGED_PACKAGE, *rel.parts))
        files[staged_rel] = path.read_text(encoding="utf-8")

    return files


def issm_cloud_runner_extra_files() -> dict[str, str]:
    """The ``extra_files`` a cloud-run caller merges into
    ``WorkspaceManager.stage_example_for_run`` so the ISSM branch script
    (:func:`issm_cloud_runner_script` -- license-tunnel setup + the MATLAB
    invocation) is staged as an ordinary file alongside the run's other
    inputs, the SAME mechanism :func:`license_tunnel_client_extra_files`
    already uses. Staged unconditionally for every ISSM cloud run,
    alongside that function's files -- callers merge both dicts (see
    icesheets_gateway.py's ISSM cloud-staging helper)."""
    return {ISSM_CLOUD_RUNNER_FILENAME: issm_cloud_runner_script()}


def cloud_run_command() -> list[str]:
    """The batch job-definition command that runs the generic runner."""
    return ["bash", "-c", build_cloud_runner()]
