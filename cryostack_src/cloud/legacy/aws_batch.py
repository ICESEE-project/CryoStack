# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Batch
# File        : aws_batch.py
#
# Description :
#     Provides low-level AWS Batch, CloudWatch Logs, and AWS CLI helpers
#     used by the CryoStack cloud execution backend.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-20
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: MIT
#
# =============================================================================

"""
AWS Batch services for CryoStack.

This module contains AWS-specific execution primitives used by the
CryoStack cloud backend. It intentionally contains no frontend logic.

The functions here provide the cloud equivalents of common HPC
operations such as job status inspection, log retrieval, and job
termination.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field


@dataclass
class AWSConfig:
    """
    AWS connection configuration.

    Two credential sources are supported, and exactly one is used per call:

    * **developer / operator mode** -- ambient AWS CLI credentials, optionally
      selected by a named ``profile``;
    * **end-user assumed-role mode** -- ``credentials`` carries the temporary
      ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` / ``AWS_SESSION_TOKEN``
      from an ``sts:AssumeRole`` call. When present it wins and ``profile`` /
      ambient credentials are never consulted.

    This mirrors :class:`cryostack_src.cloud.drivers.aws.models.AWSConfig`
    exactly -- every caller in this codebase actually passes THAT class's
    instances through here (``AWSDriver.status/logs/terminate`` -> this
    module), never this bare dataclass; it is kept credential-shaped too so
    ``run_aws`` below is correct regardless of which one a caller constructs.
    """

    region: str = "us-east-2"
    profile: str | None = None
    credentials: dict[str, str] | None = field(default=None, repr=False)


#: env vars that carry an ambient credential source; dropped when an
#: assumed-role ``AWSConfig.credentials`` is supplied so the temporary
#: credentials are the only ones the CLI subprocess can see. Must stay in
#: lockstep with ``cryostack_src/cloud/drivers/aws/auth.py``'s ``run_aws``
#: -- that is the credentials-aware implementation ``submit_batch_job`` uses;
#: this module is the one ``AWSDriver.status/logs/terminate`` call, and
#: previously did NOT read ``config.credentials`` at all (subprocess.run with
#: no ``env=`` override, i.e. plain ambient-environment passthrough) -- the
#: exact reason DescribeJobs/Terminate reached AWS as the host's own ambient
#: identity while SubmitJob correctly used the assumed-role session.
_AMBIENT_CRED_ENV = (
    "AWS_PROFILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_SECURITY_TOKEN",
)


def aws_command(
    config: AWSConfig,
) -> list[str]:
    """
    Build the base AWS CLI command.
    """

    command = ["aws"]

    # assumed-role temporary credentials win and never combine with a profile
    # (matches drivers/aws/auth.py's aws_command exactly)
    if config.profile and not getattr(config, "credentials", None):
        command.extend([
            "--profile",
            config.profile,
        ])

    if config.region:
        command.extend([
            "--region",
            config.region,
        ])

    return command


def run_aws(
    config: AWSConfig,
    arguments: list[str],
) -> tuple[int, str, str]:
    """
    Execute an AWS CLI command.

    When ``config.credentials`` carries assumed-role temporary credentials,
    the subprocess environment is the current environment with every ambient
    AWS credential var stripped and only the temporary
    ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` / ``AWS_SESSION_TOKEN``
    triple set -- the CLI cannot fall back to a host profile or ambient
    identity. Developer mode (no ``credentials``) is unchanged: ``env=None``
    inherits the current process environment exactly as before.
    """

    credentials = getattr(config, "credentials", None)
    env = None
    if credentials:
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in _AMBIENT_CRED_ENV
        }
        # only the three standard STS env vars are honoured
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            if credentials.get(key):
                env[key] = credentials[key]

    process = subprocess.run(
        aws_command(config) + arguments,
        capture_output=True,
        text=True,
        env=env,
    )

    return (
        process.returncode,
        process.stdout,
        process.stderr,
    )


def require_success(
    code: int,
    stdout: str,
    stderr: str,
) -> str:
    """
    Raise an exception when an AWS CLI operation fails.
    """

    if code != 0:
        raise RuntimeError(
            (stderr or stdout).strip()
            or "AWS command failed."
        )

    return stdout


def describe_job(
    config: AWSConfig,
    job_id: str,
) -> dict:
    """
    Return the complete AWS Batch job description.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "batch",
            "describe-jobs",
            "--jobs",
            job_id,
        ],
    )

    require_success(
        code,
        stdout,
        stderr,
    )

    payload = json.loads(
        stdout or "{}"
    )

    jobs = payload.get(
        "jobs",
        [],
    )

    if not jobs:
        raise RuntimeError(
            f"AWS Batch job not found: {job_id}"
        )

    return jobs[0]


def batch_status(
    config: AWSConfig,
    job_id: str,
) -> dict:
    """
    Return normalized information from an AWS Batch job.
    """

    job = describe_job(
        config,
        job_id,
    )

    container = (
        job.get("container")
        or {}
    )

    return {
        "status": job.get(
            "status",
            "",
        ),
        "reason": (
            job.get("statusReason")
            or container.get("reason")
            or ""
        ),
        "exit_code": container.get(
            "exitCode"
        ),
        "log_stream": container.get(
            "logStreamName"
        ),
        # non-secret resource identity revealed incrementally by DescribeJobs
        # (used to build the AWS diagnostics menu -- never a credential)
        "log_group": (
            (container.get("logConfiguration") or {})
            .get("options", {})
            .get("awslogs-group")
        ),
        "image": container.get("image"),
        "task_arn": container.get("taskArn"),
        "created_at": job.get(
            "createdAt"
        ),
        "started_at": job.get(
            "startedAt"
        ),
        "stopped_at": job.get(
            "stoppedAt"
        ),
        "job_name": job.get(
            "jobName"
        ),
        "job_queue": job.get(
            "jobQueue"
        ),
        "job_definition": job.get(
            "jobDefinition"
        ),
    }


#: AWS Batch's own default CloudWatch Logs group -- used automatically for
#: ANY job definition whose ``logConfiguration`` does not set an explicit
#: ``awslogs-group`` (a "legacy"/default Batch job definition). Never a
#: guess: it is the literal, documented AWS Batch default.
DEFAULT_LOG_GROUP = "/aws/batch/job"

#: terminal Batch job states -- once here, a job's log stream is either
#: already writable or it is never coming (log retention expired, the
#: container never emitted output, or a stale group/stream is resolved).
_TERMINAL_JOB_STATUSES = frozenset({"SUCCEEDED", "FAILED"})


def describe_job_definition(
    config: AWSConfig,
    job_definition: str,
) -> dict:
    """
    Return the AWS Batch job-definition description for ``job_definition``
    -- a name, ``name:revision``, or full ARN: exactly what
    :func:`describe_job`'s ``jobDefinition`` field returns.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "batch",
            "describe-job-definitions",
            "--job-definitions",
            job_definition,
        ],
    )

    require_success(
        code,
        stdout,
        stderr,
    )

    payload = json.loads(
        stdout or "{}"
    )

    definitions = payload.get(
        "jobDefinitions",
        [],
    )

    if not definitions:
        raise RuntimeError(
            f"AWS Batch job definition not found: {job_definition}"
        )

    return definitions[0]


def resolve_log_group(
    config: AWSConfig,
    job: dict,
) -> str:
    """
    Resolve the CloudWatch Logs group a Batch job's container actually
    writes to -- NEVER guessed from the model name, NEVER hardcoded
    globally.

    Resolution order: ``DescribeJobs(jobId).jobDefinition`` (already in
    ``job``, the dict :func:`describe_job` returned) -> ``DescribeJobDefinitions``
    -> ``containerProperties.logConfiguration.options["awslogs-group"]``.

    Falls back to AWS Batch's own default group (:data:`DEFAULT_LOG_GROUP`)
    when: ``job`` carries no ``jobDefinition`` reference, the describe call
    itself fails (permissions, a deregistered definition, a transient AWS
    error -- resolving logs must never be fatal), or the job definition
    simply never set ``awslogs-group`` -- an old/default Batch job
    definition. A CryoStack job definition that DOES set it
    (``batch_config.py``'s ``/cryostack/batch/<model>``) resolves to that
    exact configured value.
    """

    job_definition = job.get("jobDefinition")
    if not job_definition:
        return DEFAULT_LOG_GROUP

    try:
        definition = describe_job_definition(config, job_definition)
    except Exception:  # noqa: BLE001 -- best-effort; never block log reads
        return DEFAULT_LOG_GROUP

    container = definition.get("containerProperties") or {}
    options = (container.get("logConfiguration") or {}).get("options") or {}
    return options.get("awslogs-group") or DEFAULT_LOG_GROUP


def batch_logs(
    config: AWSConfig,
    job_id: str,
    *,
    limit: int = 200,
) -> str:
    """
    Retrieve recent CloudWatch logs for an AWS Batch job.

    The log GROUP is resolved per-job by :func:`resolve_log_group` -- never
    assumed globally -- so this correctly reads both a legacy/default Batch
    job (group :data:`DEFAULT_LOG_GROUP`, ``/aws/batch/job``) and a
    CryoStack job definition with an explicit ``awslogs-group`` (group
    ``/cryostack/...``). The log STREAM is always
    ``DescribeJobs(...).container.logStreamName``.
    """

    job = describe_job(
        config,
        job_id,
    )

    container = (
        job.get("container")
        or {}
    )

    log_stream = container.get(
        "logStreamName"
    )

    if not log_stream:
        status = job.get(
            "status",
            "UNKNOWN",
        )

        return (
            "CloudWatch log stream is not "
            f"available yet. Job status: {status}"
        )

    log_group = resolve_log_group(config, job)

    code, stdout, stderr = run_aws(
        config,
        [
            "logs",
            "get-log-events",
            "--log-group-name",
            log_group,
            "--log-stream-name",
            log_stream,
            "--limit",
            str(max(1, int(limit))),
            "--no-start-from-head",
        ],
    )

    if code != 0:
        text = (stderr or stdout or "").strip()
        low = text.lower()
        # ResourceNotFoundException ("the specified log stream/group does
        # not exist") is not a job or results failure -- distinguish "not
        # created yet" (job still in flight) from "genuinely absent on a
        # completed job" (report what we resolved so it is diagnosable,
        # but still return -- never raise -- so callers never mark the
        # job/Results failed over an unreadable log).
        if "resourcenotfoundexception" in low:
            status = job.get("status", "UNKNOWN")
            if status in _TERMINAL_JOB_STATUSES:
                return (
                    "Logs are unavailable: CloudWatch has no log stream "
                    f"for log group {log_group!r}, stream {log_stream!r} "
                    "on this completed job. The job's own status and "
                    "results are unaffected."
                )
            return (
                "Logs are not available yet. Job status: "
                f"{status}."
            )
        # AccessDenied and any other AWS CLI failure: raise as before --
        # the raw AWS text (which names the exact denied action, e.g.
        # "logs:GetLogEvents") reaches the frontend's existing
        # classify_cloud_failure / is_log_read_permission_error handling.
        raise RuntimeError(text or "AWS command failed.")

    payload = json.loads(
        stdout or "{}"
    )

    events = payload.get(
        "events",
        [],
    )

    if not events:
        return "(no CloudWatch log output yet)"

    return "\n".join(
        str(
            event.get(
                "message",
                "",
            )
        )
        for event in events
    )


def terminate_batch_job(
    config: AWSConfig,
    job_id: str,
    *,
    reason: str = (
        "Terminated from CryoStack"
    ),
) -> dict:
    """
    Cancel or terminate an AWS Batch job depending on its state.

    Jobs that have not started are cancelled. Jobs that have started
    are terminated.
    """

    job = describe_job(
        config,
        job_id,
    )

    status = (
        job.get("status")
        or ""
    ).upper()

    if status in {
        "SUCCEEDED",
        "FAILED",
    }:
        return {
            "ok": True,
            "action": "none",
            "status": status,
            "message": (
                "Job has already finished."
            ),
        }

    if status in {
        "SUBMITTED",
        "PENDING",
        "RUNNABLE",
    }:
        operation = "cancel-job"
        action = "cancelled"

    else:
        operation = "terminate-job"
        action = "terminated"

    code, stdout, stderr = run_aws(
        config,
        [
            "batch",
            operation,
            "--job-id",
            job_id,
            "--reason",
            reason,
        ],
    )

    require_success(
        code,
        stdout,
        stderr,
    )

    return {
        "ok": True,
        "action": action,
        "status": status,
        "job_id": job_id,
    }

def has_credentials(
    config: AWSConfig,
) -> bool:
    """
    Return whether AWS CLI credentials are available.
    """

    code, _, _ = run_aws(
        config,
        [
            "sts",
            "get-caller-identity",
        ],
    )

    return code == 0