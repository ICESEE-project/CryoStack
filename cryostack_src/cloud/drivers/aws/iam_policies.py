# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS IAM Policies
# File        : iam_policies.py
#
# Description :
#     Defines the IAM trust and permission policies required by CryoStack
#     AWS Batch execution environments.
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
AWS IAM policy definitions for CryoStack.

This module contains policy documents only. It does not create or modify
AWS IAM resources.

Keeping policy definitions separate from provisioning makes CryoStack's
AWS permissions explicit, reviewable, and easier to maintain.
"""

from __future__ import annotations

from cryostack_src.cloud.matlab_license import is_secret_arn

#: Inline-policy name for the ISSM MATLAB-license secret grant on the ECS
#: task-execution role. A single well-known name so Prepare Cloud can
#: put/overwrite/remove exactly this policy without touching any other.
MATLAB_LICENSE_SECRET_POLICY_NAME = "CryoStackMatlabLicenseSecret"


def batch_service_trust_policy() -> dict:
    """
    Trust relationship used by the AWS Batch service role.
    """

    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "batch.amazonaws.com"
                },
                "Action": "sts:AssumeRole",
            }
        ],
    }


def ecs_execution_trust_policy() -> dict:
    """
    Trust relationship used by the ECS task execution role.
    """

    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "ecs-tasks.amazonaws.com"
                },
                "Action": "sts:AssumeRole",
            }
        ],
    }


def job_trust_policy() -> dict:
    """
    Trust relationship used by the CryoStack Batch job role.
    """

    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "ecs-tasks.amazonaws.com"
                },
                "Action": "sts:AssumeRole",
            }
        ],
    }


def job_s3_policy(
    *,
    bucket: str,
) -> dict:
    """
    Minimum S3 permissions required by a CryoStack execution container.
    """

    bucket_arn = (
        f"arn:aws:s3:::{bucket}"
    )

    object_arn = (
        f"{bucket_arn}/runs/*"
    )

    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CryoStackListRuns",
                "Effect": "Allow",
                "Action": [
                    "s3:ListBucket",
                ],
                "Resource": [
                    bucket_arn,
                ],
                "Condition": {
                    "StringLike": {
                        "s3:prefix": [
                            "runs",
                            "runs/*",
                        ]
                    }
                },
            },
            {
                "Sid": "CryoStackRunObjects",
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                ],
                "Resource": [
                    object_arn,
                ],
            },
        ],
    }


def matlab_license_secret_policy(
    *,
    secret_arn: str,
) -> dict:
    """Least-privilege policy letting the ECS task-execution role read ONLY
    the one AWS Secrets Manager secret that holds the ISSM MATLAB license
    value (``MLM_LICENSE_FILE``), so AWS Batch can inject it into the
    container via ``containerProperties.secrets``.

    * ``Resource`` is the exact secret ARN -- never ``"*"``.
    * Only ``secretsmanager:GetSecretValue``.
    * No KMS statement: a secret encrypted with the Secrets Manager default
      AWS-managed key (``aws/secretsmanager``) needs none -- that key's own
      key policy already lets Secrets Manager decrypt on the caller's
      behalf. A customer-managed KMS key WOULD additionally need
      ``kms:Decrypt`` scoped to that key ARN; CryoStack does not yet collect
      a CMK ARN, so that stays a documented future case rather than a reason
      to broaden this policy now (see the module docstring / audit).

    Raises ``ValueError`` for anything that is not a Secrets Manager secret
    ARN -- the value must never reach this layer.
    """

    arn = (secret_arn or "").strip()
    if not is_secret_arn(arn):
        raise ValueError(
            "matlab_license_secret_policy requires an AWS Secrets Manager "
            f"secret ARN, got {arn!r}"
        )

    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CryoStackReadMatlabLicenseSecret",
                "Effect": "Allow",
                "Action": "secretsmanager:GetSecretValue",
                "Resource": arn,
            }
        ],
    }