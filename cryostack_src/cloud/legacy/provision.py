# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Cloud Provisioning
# File        : provision.py
#
# Description :
#     Orchestrates cloud resource preparation for CryoStack while keeping
#     provider-specific provisioning logic isolated from frontend code.
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
Cloud resource provisioning for CryoStack.

This module coordinates provider-specific resource preparation through
a provider-independent interface.

Provisioning is introduced incrementally as part of the CryoStack
strangler migration. The initial implementation prepares cloud storage
only. Compute, IAM, registry, and Batch provisioning will be added in
separate migration slices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .drivers.aws import (
    AWSConfig,
    AWSCredentialsError,
    prepare_storage,
)

from .drivers.aws import (
    AWSConfig,
    AWSCredentialsError,
    ensure_iam_resources,
    prepare_storage,
)

from .provision import (
    CloudProvisionResult,
    provision_iam,
    provision_storage,
)

@dataclass
class CloudProvisionResult:
    """
    Result of a CryoStack cloud provisioning operation.
    """

    provider: str
    region: str

    success: bool

    account_id: str | None = None

    resources: dict[str, Any] = field(
        default_factory=dict
    )

    messages: list[str] = field(
        default_factory=list
    )

    def provision_iam(
        self,
        *,
        provider: str,
        region: str,
        profile: str | None = None,
        bucket: str,
    ) -> CloudProvisionResult:

        return provision_iam(
            provider=provider,
            region=region,
            profile=profile,
            bucket=bucket,
        )


def provision_storage(
    *,
    provider: str,
    region: str,
    profile: str | None = None,
    bucket: str | None = None,
) -> CloudProvisionResult:
    """
    Prepare cloud storage required by CryoStack.

    The caller does not need to know provider-specific details such as
    S3 commands or naming conventions.
    """

    provider_name = (
        provider
        .strip()
        .lower()
    )

    if provider_name != "aws":
        raise ValueError(
            f"Unsupported cloud provider: {provider}"
        )

    config = AWSConfig(
        region=region,
        profile=profile,
    )

    try:

        storage = prepare_storage(
            config,
            bucket=bucket,
        )

    except AWSCredentialsError:

        return CloudProvisionResult(
            provider="aws",
            region=region,
            success=False,
            messages=[
                "AWS account is not connected.",
            ],
        )

    messages = []

    if storage.created:

        messages.append(
            "CryoStack cloud storage was created."
        )

    else:

        messages.append(
            "CryoStack cloud storage already exists."
        )

    messages.append(
        f"S3 bucket: {storage.bucket}"
    )

    messages.append(
        f"Run prefix: {storage.s3_prefix}"
    )

    return CloudProvisionResult(
        provider="aws",
        region=region,
        success=True,
        account_id=storage.account_id,
        resources={
            "bucket": storage.bucket,
            "s3_prefix": storage.s3_prefix,
            "created": storage.created,
        },
        messages=messages,
    )

def provision_iam(
    *,
    provider: str,
    region: str,
    profile: str | None = None,
    bucket: str,
) -> CloudProvisionResult:
    """
    Prepare IAM roles needed by CryoStack cloud execution.
    """

    provider_name = (
        provider
        .strip()
        .lower()
    )

    if provider_name != "aws":
        raise ValueError(
            f"Unsupported cloud provider: {provider}"
        )

    config = AWSConfig(
        region=region,
        profile=profile,
    )

    try:

        result = ensure_iam_resources(
            config,
            bucket=bucket,
        )

    except AWSCredentialsError:

        return CloudProvisionResult(
            provider="aws",
            region=region,
            success=False,
            messages=[
                "AWS account is not connected.",
            ],
        )

    resources = result.resources

    return CloudProvisionResult(
        provider="aws",
        region=region,
        success=True,
        resources={
            "batch_service_role": (
                resources.batch_service_role
            ),
            "ecs_execution_role": (
                resources.ecs_execution_role
            ),
            "job_role": (
                resources.job_role
            ),
            "created": result.created,
            "reused": result.reused,
        },
        messages=[
            (
                "CryoStack IAM resources "
                "are ready."
            ),
            (
                "Created: "
                + (
                    ", ".join(result.created)
                    if result.created
                    else "none"
                )
            ),
            (
                "Reused: "
                + (
                    ", ".join(result.reused)
                    if result.reused
                    else "none"
                )
            ),
        ],
    )

