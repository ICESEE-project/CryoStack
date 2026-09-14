# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Batch Job Submission
# File        : submit.py
#
# Description :
#     Builds and issues the `aws batch submit-job` call for a staged
#     CryoStack cloud run. Pure payload builders + one thin AWS call.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-09-01
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
AWS Batch submission for CryoStack cloud runs.

The generic cloud runner (``cloud/runtime.py``) is already baked into the job
definition's command. A run is therefore fully described to Batch by **three
non-secret environment values**:

    CRYOSTACK_S3_RUN      s3://<bucket>/runs/<run-id>     (from staging)
    CRYOSTACK_MODEL       issm
    CRYOSTACK_RUN_TARGET  runme.m

No AWS credentials, no MATLAB license value, and no local user paths are ever
placed in the container overrides -- Batch/Fargate injects the task role, and
the license (if any) arrives only through the job definition's own environment.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .auth import run_aws
from .models import AWSConfig

_JOB_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")
#: keys that must never appear in a submit-job container override
_FORBIDDEN_ENV_HINTS = (
    "aws_access", "aws_secret", "aws_session", "secret", "token", "password",
    "mlm_license", "license_file", "credential",
)


class CloudSubmitError(RuntimeError):
    """An AWS Batch job could not be submitted for a staged cloud run."""


@dataclass
class BatchSubmission:
    job_id: str
    job_name: str
    job_queue: str
    job_definition: str
    messages: list[str] = field(default_factory=list)


def sanitize_job_name(name: str, *, suffix: str = "") -> str:
    """AWS Batch job names: 1-128 chars of ``[A-Za-z0-9_-]``, must start with a
    letter or number. A run-id ``suffix`` keeps names unique and traceable."""
    base = _JOB_NAME_RE.sub("-", (name or "cryostack").strip()).strip("-") or "cryostack"
    if not base[0].isalnum():
        base = f"c-{base}"
    if suffix:
        suffix = _JOB_NAME_RE.sub("-", suffix.strip()).strip("-")
        base = f"{base}-{suffix}"
    return base[:128].rstrip("-") or "cryostack"


def build_container_overrides(*, s3_run: str, model: str, run_target: str) -> dict:
    """The ``--container-overrides`` document -- three non-secret env values."""
    s3_run = (s3_run or "").strip().rstrip("/")
    model = (model or "").strip().lower()
    run_target = (run_target or "").strip()
    if not s3_run.startswith("s3://"):
        raise CloudSubmitError(f"CRYOSTACK_S3_RUN must be an s3:// URI, got {s3_run!r}")
    if not model:
        raise CloudSubmitError("a cloud submission needs a model")
    if not run_target or run_target.startswith(("/", "~")) or ".." in run_target.split("/"):
        raise CloudSubmitError(f"unsafe run target for a cloud submission: {run_target!r}")

    env = [
        {"name": "CRYOSTACK_S3_RUN", "value": s3_run},
        {"name": "CRYOSTACK_MODEL", "value": model},
        {"name": "CRYOSTACK_RUN_TARGET", "value": run_target},
    ]
    blob = json.dumps(env).lower()
    if any(hint in blob for hint in _FORBIDDEN_ENV_HINTS):
        raise CloudSubmitError("container overrides failed their no-secrets check")
    return {"environment": env}


def build_submit_job_args(
    *,
    job_name: str,
    job_queue: str,
    job_definition: str,
    s3_run: str,
    model: str,
    run_target: str,
    run_id: str = "",
) -> list[str]:
    """The full ``aws batch submit-job ...`` argument list (no ``aws`` prefix)."""
    if not job_queue:
        raise CloudSubmitError("a cloud submission needs a Batch job queue")
    if not job_definition:
        raise CloudSubmitError("a cloud submission needs a Batch job definition")
    overrides = build_container_overrides(s3_run=s3_run, model=model, run_target=run_target)
    return [
        "batch", "submit-job",
        "--job-name", sanitize_job_name(job_name, suffix=run_id),
        "--job-queue", job_queue,
        "--job-definition", job_definition,
        "--container-overrides", json.dumps(overrides, separators=(",", ":")),
    ]


def submit_batch_job(
    config: AWSConfig,
    *,
    job_name: str,
    job_queue: str,
    job_definition: str,
    s3_run: str,
    model: str,
    run_target: str,
    run_id: str = "",
    aws=None,
) -> BatchSubmission:
    """Issue ``aws batch submit-job`` and return the captured job id.

    ``aws`` is an injectable ``callable(args) -> (code, out, err)`` (defaults to
    the driver's ``run_aws``) so tests never touch AWS.
    """
    args = build_submit_job_args(
        job_name=job_name, job_queue=job_queue, job_definition=job_definition,
        s3_run=s3_run, model=model, run_target=run_target, run_id=run_id,
    )
    invoke = aws or (lambda a: run_aws(config, a))
    code, out, err = invoke(args)
    if code != 0:
        raise CloudSubmitError((err or out).strip() or "aws batch submit-job failed")
    try:
        job_id = json.loads(out or "{}")["jobId"]
    except (ValueError, KeyError) as exc:
        raise CloudSubmitError(
            f"could not read a jobId from submit-job output: {exc}"
        ) from exc
    return BatchSubmission(
        job_id=str(job_id),
        job_name=args[args.index("--job-name") + 1],
        job_queue=job_queue,
        job_definition=job_definition,
        messages=[f"submitted AWS Batch job {job_id}"],
    )
