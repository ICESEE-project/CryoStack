# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Bootstrap
# File        : bootstrap.py
#
# Description :
#     Discovers and prepares AWS resources required for CryoStack cloud
#     execution while minimizing infrastructure setup for end users.
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
AWS bootstrap services for CryoStack.

This module discovers cloud resources associated with a user's AWS
account and prepares the infrastructure required for CryoStack
execution.

The bootstrap layer is intentionally separate from job execution.
Execution backends submit and monitor jobs; this module ensures that
the required AWS resources exist before submission.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .aws_batch import (
    AWSConfig,
    run_aws,
    require_success,
)


@dataclass
class AWSBootstrapResult:
    """
    Result of inspecting or preparing a CryoStack AWS environment.
    """

    region: str
    account_id: str | None

    bucket: str | None

    compute_environment: str | None
    job_queue: str | None
    job_definition: str | None

    ready: bool

    missing: list[str]
    messages: list[str]


def get_account_identity(
    config: AWSConfig,
) -> dict[str, Any]:
    """
    Return the AWS identity currently available to CryoStack.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "sts",
            "get-caller-identity",
        ],
    )

    require_success(
        code,
        stdout,
        stderr,
    )

    return json.loads(
        stdout or "{}"
    )


def s3_bucket_exists(
    config: AWSConfig,
    bucket: str,
) -> bool:
    """
    Check whether the configured AWS identity can access an S3 bucket.
    """

    code, _, _ = run_aws(
        config,
        [
            "s3api",
            "head-bucket",
            "--bucket",
            bucket,
        ],
    )

    return code == 0


def batch_compute_environment_exists(
    config: AWSConfig,
    name: str,
) -> bool:
    """
    Check whether an AWS Batch compute environment exists.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "batch",
            "describe-compute-environments",
            "--compute-environments",
            name,
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

    return bool(
        payload.get(
            "computeEnvironments"
        )
    )


def batch_job_queue_exists(
    config: AWSConfig,
    name: str,
) -> bool:
    """
    Check whether an AWS Batch job queue exists.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "batch",
            "describe-job-queues",
            "--job-queues",
            name,
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

    return bool(
        payload.get(
            "jobQueues"
        )
    )


def batch_job_definition_exists(
    config: AWSConfig,
    name: str,
) -> bool:
    """
    Check whether an active AWS Batch job definition exists.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "batch",
            "describe-job-definitions",
            "--job-definition-name",
            name,
            "--status",
            "ACTIVE",
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

    return bool(
        payload.get(
            "jobDefinitions"
        )
    )


def inspect_aws_environment(
    config: AWSConfig,
    *,
    bucket: str,
    compute_environment: str,
    job_queue: str,
    job_definition: str,
) -> AWSBootstrapResult:
    """
    Inspect the AWS account and report what CryoStack still needs.
    """

    messages: list[str] = []
    missing: list[str] = []

    identity = get_account_identity(
        config
    )

    account_id = identity.get(
        "Account"
    )

    messages.append(
        f"[aws] Account: {account_id}"
    )

    messages.append(
        f"[aws] Region : {config.region}"
    )

    if s3_bucket_exists(
        config,
        bucket,
    ):
        messages.append(
            f"[aws] S3 bucket ready: {bucket}"
        )
    else:
        missing.append(
            "s3_bucket"
        )

        messages.append(
            f"[aws] S3 bucket missing: {bucket}"
        )

    if batch_compute_environment_exists(
        config,
        compute_environment,
    ):
        messages.append(
            "[aws] Batch compute environment ready: "
            f"{compute_environment}"
        )
    else:
        missing.append(
            "compute_environment"
        )

        messages.append(
            "[aws] Batch compute environment missing: "
            f"{compute_environment}"
        )

    if batch_job_queue_exists(
        config,
        job_queue,
    ):
        messages.append(
            f"[aws] Batch queue ready: {job_queue}"
        )
    else:
        missing.append(
            "job_queue"
        )

        messages.append(
            f"[aws] Batch queue missing: {job_queue}"
        )

    if batch_job_definition_exists(
        config,
        job_definition,
    ):
        messages.append(
            "[aws] Batch job definition ready: "
            f"{job_definition}"
        )
    else:
        missing.append(
            "job_definition"
        )

        messages.append(
            "[aws] Batch job definition missing: "
            f"{job_definition}"
        )

    return AWSBootstrapResult(
        region=config.region,
        account_id=account_id,
        bucket=bucket,
        compute_environment=compute_environment,
        job_queue=job_queue,
        job_definition=job_definition,
        ready=not missing,
        missing=missing,
        messages=messages,
    )