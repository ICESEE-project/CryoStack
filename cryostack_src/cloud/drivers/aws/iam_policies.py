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