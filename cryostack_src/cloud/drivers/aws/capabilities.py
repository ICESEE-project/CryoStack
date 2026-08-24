# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Capabilities
# File        : capabilities.py
#
# Description :
#     Combines AWS account, storage, network, IAM, registry, and Batch
#     discovery into a single CryoStack cloud capability report.
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
Combined AWS capability discovery for CryoStack.
"""

from __future__ import annotations

from .auth import discover_account
from .batch import discover_batch_resources
from .iam import discover_iam_resources
from .models import (
    AWSConfig,
    AWSCapabilities,
)
from .network import discover_network_resources
from .registry import discover_registry_resources
from .storage import (
    bucket_exists,
    cryostack_resource_name,
)


def discover_capabilities(
    config: AWSConfig,
) -> AWSCapabilities:
    """
    Discover the AWS capabilities currently available to CryoStack.
    """

    account = discover_account(
        config
    )

    if not account.authenticated:

        return AWSCapabilities(
            account_id=None,
            region=config.region,
            authenticated=False,
            storage_ready=False,
            network_ready=False,
            iam_ready=False,
            registry_ready=False,
            batch_ready=False,
            missing=[
                "aws_connection",
            ],
            messages=[
                "AWS account is not connected.",
            ],
        )

    account_id = account.account_id

    if not account_id:
        return AWSCapabilities(
            account_id=None,
            region=config.region,
            authenticated=False,
            storage_ready=False,
            network_ready=False,
            iam_ready=False,
            registry_ready=False,
            batch_ready=False,
            missing=[
                "account_id",
            ],
            messages=[
                "AWS account identity is incomplete.",
            ],
        )

    messages: list[str] = []
    missing: list[str] = []

    #
    # Storage
    #
    bucket = cryostack_resource_name(
        account_id=account_id,
        resource="runs",
    )

    storage_ready = bucket_exists(
        config,
        bucket,
    )

    if storage_ready:
        messages.append(
            f"Storage ready: {bucket}"
        )
    else:
        missing.append(
            "storage"
        )

        messages.append(
            f"Storage missing: {bucket}"
        )

    #
    # Network
    #
    network = discover_network_resources(
        config
    )

    network_ready = bool(
        network.vpc_id
        and network.subnet_ids
        and network.security_group_ids
    )

    if not network_ready:
        missing.append(
            "network"
        )

    #
    # IAM
    #
    iam = discover_iam_resources(
        config
    )

    iam_ready = not bool(
        iam.missing
    )

    if not iam_ready:
        missing.extend(
            f"iam:{item}"
            for item in (
                iam.missing
                or []
            )
        )

    #
    # Registry
    #
    registry = discover_registry_resources(
        config
    )

    #
    # For ISSM-first cloud parity we only require
    # the ISSM repository initially.
    #
    registry_ready = bool(
        registry.issm_repository_uri
    )

    if not registry_ready:
        missing.append(
            "registry:issm"
        )

    #
    # Batch
    #
    batch = discover_batch_resources(
        config
    )

    #
    # Again, ISSM-first. Icepack can be added
    # without making today's environment unready.
    #
    batch_ready = bool(
        batch.compute_environment
        and batch.job_queue
        and batch.issm_job_definition
    )

    if not batch_ready:

        if not batch.compute_environment:
            missing.append(
                "batch:compute_environment"
            )

        if not batch.job_queue:
            missing.append(
                "batch:job_queue"
            )

        if not batch.issm_job_definition:
            missing.append(
                "batch:issm_job_definition"
            )

    return AWSCapabilities(
        account_id=account_id,
        region=config.region,
        authenticated=True,
        storage_ready=storage_ready,
        network_ready=network_ready,
        iam_ready=iam_ready,
        registry_ready=registry_ready,
        batch_ready=batch_ready,
        missing=missing,
        messages=messages,
    )

