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
#: substrings that must never appear in a submit-job container override
#: VALUE -- this is what actually leaks a credential/license into an
#: unencrypted, log-visible AWS Batch RunTask override; see
#: _assert_env_has_no_secrets below for why key NAMES are checked
#: separately (and more narrowly) from values.
_FORBIDDEN_ENV_HINTS = (
    "aws_access", "aws_secret", "aws_session", "secret", "token", "password",
    "mlm_license", "license_file", "credential",
)

#: exact env-var NAMES exempt from the *name* half of the no-secrets scan
#: below -- narrowly, because their names legitimately contain a forbidden
#: substring (CRYOSTACK_LT_TOKEN contains "token") while the value they
#: carry is a short-lived, run-scoped, non-credential tunnel capability
#: identifier (an opaque grant token authorising exactly one private-
#: service tunnel for exactly one run), never an AWS credential or the
#: MATLAB license value -- see cryostack_src.cloud.matlab_license.
#: plan_license_tunnel. Their VALUES are still fully scanned below like
#: every other entry's -- this exemption is name-only.
_TUNNEL_ENV_NAMES = frozenset({
    "CRYOSTACK_LICENSE_TUNNEL_REQUIRED",
    "CRYOSTACK_LT_RELAY",
    "CRYOSTACK_LT_SESSION",
    "CRYOSTACK_LT_TOKEN",
    "CRYOSTACK_LT_PURPOSE",
    "CRYOSTACK_LT_ENDPOINT",
    "CRYOSTACK_LT_PORT",
})


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


def _assert_env_has_no_secrets(env: list[dict]) -> None:
    """Per-entry, not a single blob scan: a key NAME in
    :data:`_TUNNEL_ENV_NAMES` is exempt from the *name* half of the check
    (its name is fixed, developer-chosen, and known safe) -- but its VALUE
    is not, and neither is any other entry's name or value. This is
    narrower than the previous single ``json.dumps(env).lower()`` scan: it
    resolves the exact conflict where ``CRYOSTACK_LT_TOKEN`` (a NAME)
    contains the forbidden substring ``"token"`` while carrying a
    non-credential, run-scoped tunnel grant identifier, WITHOUT weakening
    the check for anything else -- an unexpected credential-shaped VALUE in
    ANY entry, tunnel-named or not, is still rejected.
    """
    for entry in env:
        name = str(entry.get("name", ""))
        value = str(entry.get("value", ""))
        if name not in _TUNNEL_ENV_NAMES:
            low_name = name.lower()
            if any(hint in low_name for hint in _FORBIDDEN_ENV_HINTS):
                raise CloudSubmitError("container overrides failed their no-secrets check")
        low_value = value.lower()
        if any(hint in low_value for hint in _FORBIDDEN_ENV_HINTS):
            raise CloudSubmitError("container overrides failed their no-secrets check")


def build_container_overrides(
    *, s3_run: str, model: str, run_target: str, extra_env: dict[str, str] | None = None,
) -> dict:
    """The ``--container-overrides`` document -- the three core non-secret
    env values, plus (optionally) additional plain, non-secret run
    configuration such as the private-service license tunnel plan
    (``cryostack_src.cloud.matlab_license.plan_license_tunnel``). Backend-
    neutral by construction: this function has no notion of Fargate vs.
    EC2 -- ``extra_env`` flows into the SAME override document either way,
    and into any future compute backend that submits through this same
    function.
    """
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
    for name, value in (extra_env or {}).items():
        env.append({"name": str(name), "value": str(value)})

    _assert_env_has_no_secrets(env)
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
    extra_env: dict[str, str] | None = None,
) -> list[str]:
    """The full ``aws batch submit-job ...`` argument list (no ``aws`` prefix).
    ``job_queue``/``job_definition`` already encode the Fargate-vs-EC2
    choice (resolved by the caller before this point); ``extra_env`` is
    layered on top identically regardless of which was chosen."""
    if not job_queue:
        raise CloudSubmitError("a cloud submission needs a Batch job queue")
    if not job_definition:
        raise CloudSubmitError("a cloud submission needs a Batch job definition")
    overrides = build_container_overrides(
        s3_run=s3_run, model=model, run_target=run_target, extra_env=extra_env)
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
    extra_env: dict[str, str] | None = None,
    aws=None,
) -> BatchSubmission:
    """Issue ``aws batch submit-job`` and return the captured job id.

    ``aws`` is an injectable ``callable(args) -> (code, out, err)`` (defaults to
    the driver's ``run_aws``) so tests never touch AWS. ``extra_env`` is the
    SAME mechanism for both Fargate and EC2 (and any future compute mode
    that submits through this function) -- see ``build_container_overrides``.
    """
    args = build_submit_job_args(
        job_name=job_name, job_queue=job_queue, job_definition=job_definition,
        s3_run=s3_run, model=model, run_target=run_target, run_id=run_id,
        extra_env=extra_env,
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
