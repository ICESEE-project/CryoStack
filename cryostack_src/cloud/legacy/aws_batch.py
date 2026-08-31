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
# SPDX-License-Identifier: BSD-3-Clause
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
import subprocess
from dataclasses import dataclass


@dataclass
class AWSConfig:
    """
    AWS connection configuration.

    During development, CryoStack may use a named AWS CLI profile.
    Future account connections may provide short-lived credentials
    through IAM role assumption without changing the execution API.
    """

    region: str = "us-east-2"
    profile: str | None = None


def aws_command(
    config: AWSConfig,
) -> list[str]:
    """
    Build the base AWS CLI command.
    """

    command = ["aws"]

    if config.profile:
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
    """

    process = subprocess.run(
        aws_command(config) + arguments,
        capture_output=True,
        text=True,
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


def batch_logs(
    config: AWSConfig,
    job_id: str,
    *,
    limit: int = 200,
    log_group: str = "/aws/batch/job",
) -> str:
    """
    Retrieve recent CloudWatch logs for an AWS Batch job.
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

    require_success(
        code,
        stdout,
        stderr,
    )

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