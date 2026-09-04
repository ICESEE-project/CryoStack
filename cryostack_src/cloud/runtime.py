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
   ``.py``/``.ipynb`` run target, then the portable output collector from
   :mod:`cryostack_src.models.icepack.postprocess`),
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
SUPPORTED_CLOUD_MODELS: tuple[str, ...] = ("issm", "icepack")

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
    with-issm matlab -nodesktop -nosplash -batch \
      "ICESEE_RUN_DIR='${WORKDIR}'; setenv('ICESEE_RUN_DIR','${WORKDIR}'); run('${RUN_TARGET}'); run('${WORKDIR}/postprocess_icesee.m');"
    rc=$?
    ;;
  icepack)
    # notebooks are converted to a script first (same rule as the local /
    # remote Icepack execution path in models/icepack/execution.py); a
    # single stage, no license, no MATLAB.
    case "${RUN_TARGET}" in
      *.ipynb)
        PY_TARGET="${RUN_TARGET%.ipynb}.py"
        with-icepack jupyter nbconvert --to script "${WORKDIR}/${RUN_TARGET}" \
          && with-icepack python "${WORKDIR}/${PY_TARGET}"
        rc=$?
        ;;
      *)
        with-icepack python "${WORKDIR}/${RUN_TARGET}"
        rc=$?
        ;;
    esac
    log "icepack model runtime exit code: ${rc}"
    # portable output collector (models/icepack/postprocess.py, embedded
    # verbatim below) -- gathers figures / native files into outputs/ and
    # writes an honest metadata.json. Best effort, even on a failed run
    # (rc is never overwritten by this step): the science already happened.
    cat > "${WORKDIR}/cryostack_icepack_postprocess.py" <<'CRYOSTACK_ICEPACK_PP_EOF'
__CRYOSTACK_ICEPACK_POSTPROCESS_SCRIPT__
CRYOSTACK_ICEPACK_PP_EOF
    if command -v python3 >/dev/null 2>&1; then
      CRYOSTACK_RUN_DIR="${WORKDIR}" CRYOSTACK_EXAMPLE_DIR="${WORKDIR}" \
      python3 "${WORKDIR}/cryostack_icepack_postprocess.py" \
        || log "WARNING: Icepack output collection failed (model rc=${rc})"
    else
      log "WARNING: python3 not found in the container; skipping Icepack output collection"
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


_ICEPACK_POSTPROCESS_PLACEHOLDER = "__CRYOSTACK_ICEPACK_POSTPROCESS_SCRIPT__"


def build_cloud_runner() -> str:
    """The generic cloud runner script (identical for every execution mode).

    The Icepack branch embeds the SAME portable output collector Local /
    Remote already use (:func:`cryostack_src.models.icepack.postprocess.
    build_postprocess`) -- no duplicated collection logic, just a different
    shell wrapper around the identical script text.
    """
    from cryostack_src.models.icepack.postprocess import build_postprocess

    return _RUNNER.replace(_ICEPACK_POSTPROCESS_PLACEHOLDER, build_postprocess())


def cloud_run_command() -> list[str]:
    """The batch job-definition command that runs the generic runner."""
    return ["bash", "-c", build_cloud_runner()]
