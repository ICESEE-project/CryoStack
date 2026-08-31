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

One small runner, one execution descriptor. The runner:

1. reads its runtime configuration from the environment
   (``CRYOSTACK_S3_RUN`` / ``CRYOSTACK_MODEL`` / ``CRYOSTACK_RUN_TARGET``),
2. syncs ``<s3-run>/input/`` into a local working directory,
3. runs the model runtime -- exactly what ``stage_example_for_run`` prepared
   (injected ``runme.m``, ``cryostack_md_overrides.m``, ``data/<...>`` datasets,
   ``postprocess_icesee.m``),
4. syncs ``<workdir>/outputs/`` back to ``<s3-run>/outputs/`` (best effort,
   even on a failed run), and
5. exits with the *true* model exit code.

No scientific logic lives in the runner beyond selecting the per-model runtime
command. No credentials and no MATLAB license value are ever embedded -- the
license, if any, arrives only through the batch container's environment.
"""

from __future__ import annotations

import re

#: models with a complete cloud runtime path today
SUPPORTED_CLOUD_MODELS: tuple[str, ...] = ("issm",)

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
rc=0
case "${CRYOSTACK_MODEL}" in
  issm)
    with-issm matlab -nodesktop -nosplash -batch \
      "ICESEE_RUN_DIR='${WORKDIR}'; setenv('ICESEE_RUN_DIR','${WORKDIR}'); run('${RUN_TARGET}'); run('${WORKDIR}/postprocess_icesee.m');"
    rc=$?
    ;;
  icepack)
    fail 64 "Icepack cloud execution is not supported yet"
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


def build_cloud_runner() -> str:
    """The generic cloud runner script (identical for every execution mode)."""
    return _RUNNER


def cloud_run_command() -> list[str]:
    """The batch job-definition command that runs the generic runner."""
    return ["bash", "-c", build_cloud_runner()]
