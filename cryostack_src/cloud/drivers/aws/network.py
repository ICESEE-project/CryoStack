# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Network
# File        : network.py
#
# Description :
#     Discovers AWS VPC, subnet, and security-group resources that can be
#     reused by CryoStack cloud execution environments.
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
AWS networking services for CryoStack.

This module discovers VPCs, subnets, and security groups that CryoStack
may use when preparing AWS Batch compute environments.

The current implementation is discovery-only and does not create or
modify AWS networking resources.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .auth import run_aws
from .models import AWSConfig


@dataclass
class AWSNetworkResources:
    """
    AWS networking resources available to CryoStack.
    """

    vpc_id: str | None

    subnet_ids: list[str]
    security_group_ids: list[str]

    default_vpc: bool = False


def _require_success(
    code: int,
    stdout: str,
    stderr: str,
) -> str:
    """
    Raise when an AWS networking operation fails.
    """

    if code != 0:
        raise RuntimeError(
            (stderr or stdout).strip()
            or "AWS networking command failed."
        )

    return stdout


def discover_default_vpc(
    config: AWSConfig,
) -> dict | None:
    """
    Discover the default VPC in the configured AWS region.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "ec2",
            "describe-vpcs",
            "--filters",
            "Name=is-default,Values=true",
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

    vpcs = payload.get(
        "Vpcs",
        [],
    )

    if not vpcs:
        return None

    return vpcs[0]


def discover_subnets(
    config: AWSConfig,
    *,
    vpc_id: str,
) -> list[dict]:
    """
    Discover subnets belonging to the supplied VPC.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "ec2",
            "describe-subnets",
            "--filters",
            (
                "Name=vpc-id,"
                f"Values={vpc_id}"
            ),
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

    return payload.get(
        "Subnets",
        [],
    )


def discover_security_groups(
    config: AWSConfig,
    *,
    vpc_id: str,
) -> list[dict]:
    """
    Discover security groups belonging to the supplied VPC.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "ec2",
            "describe-security-groups",
            "--filters",
            (
                "Name=vpc-id,"
                f"Values={vpc_id}"
            ),
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

    return payload.get(
        "SecurityGroups",
        [],
    )


def discover_network_resources(
    config: AWSConfig,
) -> AWSNetworkResources:
    """
    Discover the default AWS networking resources available to CryoStack.
    """

    vpc = discover_default_vpc(
        config
    )

    if not vpc:

        return AWSNetworkResources(
            vpc_id=None,
            subnet_ids=[],
            security_group_ids=[],
            default_vpc=False,
        )

    vpc_id = vpc.get(
        "VpcId"
    )

    if not vpc_id:

        return AWSNetworkResources(
            vpc_id=None,
            subnet_ids=[],
            security_group_ids=[],
            default_vpc=False,
        )

    subnets = discover_subnets(
        config,
        vpc_id=vpc_id,
    )

    security_groups = (
        discover_security_groups(
            config,
            vpc_id=vpc_id,
        )
    )

    #
    # Prefer the VPC's default security group.
    #
    selected_groups = [
        group["GroupId"]
        for group in security_groups
        if (
            group.get("GroupName")
            == "default"
            and group.get("GroupId")
        )
    ]

    #
    # Fall back to the first available group.
    #
    if not selected_groups:

        selected_groups = [
            group["GroupId"]
            for group in security_groups
            if group.get("GroupId")
        ][:1]

    subnet_ids = [
        subnet["SubnetId"]
        for subnet in subnets
        if subnet.get("SubnetId")
    ]

    return AWSNetworkResources(
        vpc_id=vpc_id,
        subnet_ids=subnet_ids,
        security_group_ids=(
            selected_groups
        ),
        default_vpc=True,
    )