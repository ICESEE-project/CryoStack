# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Storage
# File        : storage.py
#
# Description :
#     Provides S3 discovery and provisioning services used by CryoStack
#     cloud execution environments.
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
AWS storage services for CryoStack.

This module manages the S3 storage used for cloud experiment staging
and results. It contains no frontend or execution-specific logic.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .auth import (
    get_account_identity,
    run_aws,
)
from .models import AWSConfig
from cryostack_src.cloud.s3_uri import bucket_name as _s3_bucket_name


@dataclass
class AWSStorageResult:
    """
    Prepared CryoStack S3 storage.
    """

    bucket: str
    region: str
    account_id: str

    s3_prefix: str

    created: bool = False


def cryostack_resource_name(
    *,
    account_id: str,
    resource: str,
) -> str:
    """
    Build a predictable AWS resource name for CryoStack.
    """

    account = re.sub(
        r"[^0-9]",
        "",
        account_id,
    )

    name = re.sub(
        r"[^a-z0-9-]",
        "-",
        resource.strip().lower(),
    )

    name = re.sub(
        r"-+",
        "-",
        name,
    ).strip("-")

    return (
        f"cryostack-{name}-{account}"
    )


def bucket_exists(
    config: AWSConfig,
    bucket: str,
) -> bool:
    """
    Return whether an S3 bucket is accessible.
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


def create_bucket(
    config: AWSConfig,
    bucket: str,
) -> None:
    """
    Create an S3 bucket in the configured AWS region.
    """

    arguments = [
        "s3api",
        "create-bucket",
        "--bucket",
        bucket,
    ]

    #
    # us-east-1 is special in the S3 API.
    #
    if config.region != "us-east-1":

        arguments.extend([
            "--create-bucket-configuration",
            (
                "LocationConstraint="
                f"{config.region}"
            ),
        ])

    code, stdout, stderr = run_aws(
        config,
        arguments,
    )

    if code != 0:
        raise RuntimeError(
            (stderr or stdout).strip()
            or "Unable to create S3 bucket."
        )


def enable_bucket_encryption(
    config: AWSConfig,
    bucket: str,
) -> None:
    """
    Enable default server-side encryption.
    """

    policy = {
        "Rules": [
            {
                "ApplyServerSideEncryptionByDefault": {
                    "SSEAlgorithm": "AES256",
                }
            }
        ]
    }

    code, stdout, stderr = run_aws(
        config,
        [
            "s3api",
            "put-bucket-encryption",
            "--bucket",
            bucket,
            "--server-side-encryption-configuration",
            json.dumps(policy),
        ],
    )

    if code != 0:
        raise RuntimeError(
            (stderr or stdout).strip()
            or (
                "Unable to enable S3 "
                "bucket encryption."
            )
        )


def block_public_access(
    config: AWSConfig,
    bucket: str,
) -> None:
    """
    Block public access to CryoStack experiment storage.
    """

    policy = {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    }

    code, stdout, stderr = run_aws(
        config,
        [
            "s3api",
            "put-public-access-block",
            "--bucket",
            bucket,
            "--public-access-block-configuration",
            json.dumps(policy),
        ],
    )

    if code != 0:
        raise RuntimeError(
            (stderr or stdout).strip()
            or (
                "Unable to configure S3 "
                "public access protection."
            )
        )


def ensure_bucket(
    config: AWSConfig,
    *,
    bucket: str | None = None,
) -> tuple[str, bool]:
    """
    Ensure the CryoStack S3 bucket exists.

    Returns the bucket name and whether it was created.
    """

    identity = get_account_identity(
        config
    )

    account_id = identity.get(
        "Account"
    )

    if not account_id:
        raise RuntimeError(
            "Could not determine AWS account ID."
        )

    # normalize whatever the caller/UI passed: 'bucket', 's3://bucket',
    # 's3://bucket/prefix' -> the bucket NAME only. AWS S3 APIs reject a URI.
    bucket_name = (
        _s3_bucket_name(bucket)
        if (bucket or "").strip()
        else cryostack_resource_name(
            account_id=account_id,
            resource="runs",
        )
    )

    if bucket_exists(
        config,
        bucket_name,
    ):
        return (
            bucket_name,
            False,
        )

    create_bucket(
        config,
        bucket_name,
    )

    enable_bucket_encryption(
        config,
        bucket_name,
    )

    block_public_access(
        config,
        bucket_name,
    )

    return (
        bucket_name,
        True,
    )


def prepare_storage(
    config: AWSConfig,
    *,
    bucket: str | None = None,
) -> AWSStorageResult:
    """
    Prepare the default CryoStack AWS storage environment.
    """

    identity = get_account_identity(
        config
    )

    account_id = identity.get(
        "Account"
    )

    if not account_id:
        raise RuntimeError(
            "Could not determine AWS account."
        )

    bucket_name, created = (
        ensure_bucket(
            config,
            bucket=bucket,
        )
    )

    return AWSStorageResult(
        bucket=bucket_name,
        region=config.region,
        account_id=account_id,
        s3_prefix=(
            f"s3://{bucket_name}/runs"
        ),
        created=created,
    )