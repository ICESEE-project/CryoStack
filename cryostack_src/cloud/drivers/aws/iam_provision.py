# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS IAM Provisioning
# File        : iam_provision.py
#
# Description :
#     Creates and configures the minimum IAM roles required for CryoStack
#     AWS Batch execution.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-24
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
AWS IAM provisioning services for CryoStack.

The functions in this module create only the IAM resources required for
CryoStack Batch execution and prefer AWS-managed service policies where
appropriate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .auth import run_aws
from .iam import (
    AWSIAMResources,
    discover_iam_resources,
)
from .iam_policies import (
    batch_service_trust_policy,
    ecs_execution_trust_policy,
    job_s3_policy,
    job_trust_policy,
)
from .models import AWSConfig


@dataclass
class AWSIAMProvisionResult:
    """
    Result of preparing CryoStack IAM resources.
    """

    resources: AWSIAMResources

    created: list[str]
    reused: list[str]


def _require_success(
    code: int,
    stdout: str,
    stderr: str,
) -> str:

    if code != 0:
        raise RuntimeError(
            (stderr or stdout).strip()
            or "AWS IAM provisioning failed."
        )

    return stdout


def create_role(
    config: AWSConfig,
    *,
    name: str,
    trust_policy: dict,
) -> str:
    """
    Create an IAM role and return its ARN.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "iam",
            "create-role",
            "--role-name",
            name,
            "--assume-role-policy-document",
            json.dumps(trust_policy),
        ],
    )

    _require_success(
        code,
        stdout,
        stderr,
    )

    payload = json.loads(
        stdout or "{}"
    )

    role = payload.get(
        "Role",
        {},
    )

    arn = role.get(
        "Arn"
    )

    if not arn:
        raise RuntimeError(
            f"Unable to determine ARN for IAM role {name}."
        )

    return arn


def attach_managed_policy(
    config: AWSConfig,
    *,
    role_name: str,
    policy_arn: str,
) -> None:

    code, stdout, stderr = run_aws(
        config,
        [
            "iam",
            "attach-role-policy",
            "--role-name",
            role_name,
            "--policy-arn",
            policy_arn,
        ],
    )

    _require_success(
        code,
        stdout,
        stderr,
    )


def put_inline_policy(
    config: AWSConfig,
    *,
    role_name: str,
    policy_name: str,
    policy: dict,
) -> None:

    code, stdout, stderr = run_aws(
        config,
        [
            "iam",
            "put-role-policy",
            "--role-name",
            role_name,
            "--policy-name",
            policy_name,
            "--policy-document",
            json.dumps(policy),
        ],
    )

    _require_success(
        code,
        stdout,
        stderr,
    )

def ensure_iam_resources(
    config: AWSConfig,
    *,
    bucket: str,
) -> AWSIAMProvisionResult:
    """
    Ensure the IAM roles required by CryoStack AWS Batch exist.
    """

    current = discover_iam_resources(
        config
    )

    created: list[str] = []
    reused: list[str] = []

    #
    # ---------------------------------------------------------
    # Batch service role
    # ---------------------------------------------------------
    #
    if current.batch_service_role:

        reused.append(
            "batch_service_role"
        )

    else:

        create_role(
            config,
            name="CryoStackBatchServiceRole",
            trust_policy=(
                batch_service_trust_policy()
            ),
        )

        attach_managed_policy(
            config,
            role_name=(
                "CryoStackBatchServiceRole"
            ),
            policy_arn=(
                "arn:aws:iam::aws:policy/"
                "service-role/"
                "AWSBatchServiceRole"
            ),
        )

        created.append(
            "batch_service_role"
        )

    #
    # ---------------------------------------------------------
    # ECS execution role
    # ---------------------------------------------------------
    #
    if current.ecs_execution_role:

        reused.append(
            "ecs_execution_role"
        )

    else:

        create_role(
            config,
            name="CryoStackExecutionRole",
            trust_policy=(
                ecs_execution_trust_policy()
            ),
        )

        attach_managed_policy(
            config,
            role_name=(
                "CryoStackExecutionRole"
            ),
            policy_arn=(
                "arn:aws:iam::aws:policy/"
                "service-role/"
                "AmazonECSTaskExecutionRolePolicy"
            ),
        )

        created.append(
            "ecs_execution_role"
        )

    #
    # ---------------------------------------------------------
    # CryoStack job role
    # ---------------------------------------------------------
    #
    if current.job_role:

        reused.append(
            "job_role"
        )

    else:

        create_role(
            config,
            name="CryoStackJobRole",
            trust_policy=(
                job_trust_policy()
            ),
        )

        put_inline_policy(
            config,
            role_name="CryoStackJobRole",
            policy_name=(
                "CryoStackRunStorage"
            ),
            policy=job_s3_policy(
                bucket=bucket,
            ),
        )

        created.append(
            "job_role"
        )

    #
    # Rediscover so returned values contain
    # the final role ARNs.
    #
    resources = discover_iam_resources(
        config
    )

    return AWSIAMProvisionResult(
        resources=resources,
        created=created,
        reused=reused,
    )