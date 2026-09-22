# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS IAM
# File        : iam.py
#
# Description :
#     Discovers IAM roles that may be reused by CryoStack cloud execution
#     environments and reports missing cloud execution roles.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-24
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: MIT
#
# =============================================================================

"""
AWS IAM services for CryoStack.

This module discovers IAM roles that may be reused by CryoStack for
AWS Batch execution.

The current implementation is intentionally read-only. Automatic role
creation and policy attachment will be added only after the required
permissions have been defined and reviewed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .auth import run_aws
from .models import AWSConfig


@dataclass
class AWSIAMResources:
    """
    AWS IAM roles discovered for CryoStack.
    """

    batch_service_role: str | None
    ecs_execution_role: str | None
    job_role: str | None

    batch_service_role_name: str | None = None
    ecs_execution_role_name: str | None = None
    job_role_name: str | None = None

    #: ECS instance PROFILE ARN for the Advanced EC2 Batch compute environment
    #: (the value Batch calls ``instanceRole``). ``None`` until EC2 mode is
    #: prepared; never required for the default Fargate path.
    ec2_instance_profile: str | None = None
    ec2_instance_profile_name: str | None = None

    missing: list[str] | None = None


def _require_success(
    code: int,
    stdout: str,
    stderr: str,
) -> str:
    """
    Raise when an AWS IAM command fails.
    """

    if code != 0:
        raise RuntimeError(
            (stderr or stdout).strip()
            or "AWS IAM command failed."
        )

    return stdout


def list_roles(
    config: AWSConfig,
) -> list[dict]:
    """
    Return IAM roles visible to the connected AWS identity.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "iam",
            "list-roles",
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
        "Roles",
        [],
    )


def find_role(
    roles: list[dict],
    names: list[str],
) -> dict | None:
    """
    Find the first IAM role matching one of the supplied names.
    """

    wanted = {
        name.strip().lower()
        for name in names
    }

    for role in roles:

        role_name = (
            role.get("RoleName")
            or ""
        )

        if (
            role_name
            .strip()
            .lower()
            in wanted
        ):
            return role

    return None


def list_instance_profiles(config: AWSConfig) -> list[dict]:
    """Instance profiles visible to the connected AWS identity (for the
    Advanced EC2 Batch compute environment).

    Best-effort: a role scoped only for the Fargate path may lack
    ``iam:ListInstanceProfiles``. That must not break the default Prepare
    Cloud, so a failure here yields ``[]`` -- EC2 provisioning, which needs
    this, surfaces its own clear error later.
    """
    code, stdout, stderr = run_aws(config, ["iam", "list-instance-profiles"])
    if code != 0:
        return []
    try:
        return json.loads(stdout or "{}").get("InstanceProfiles", [])
    except (ValueError, TypeError):
        return []


def find_instance_profile(profiles: list[dict], names: list[str]) -> dict | None:
    wanted = {n.strip().lower() for n in names}
    for prof in profiles:
        if (prof.get("InstanceProfileName") or "").strip().lower() in wanted:
            return prof
    return None


def discover_iam_resources(
    config: AWSConfig,
) -> AWSIAMResources:
    """
    Discover IAM roles commonly needed by CryoStack AWS execution.
    """

    roles = list_roles(
        config
    )

    # NOTE: the legacy PascalCase ``CryoStackExecutionRole`` is deliberately
    # NOT in the execution-role list. In a BYO-AWS account that name belongs to
    # the user's cross-account trust role (C7.2); matching it here would make
    # CryoStack pass that role to Batch as the ECS task-execution role. The
    # CryoStack-provisioned roles are ``cryostack-*`` (see iam_provision.py).
    batch_role = find_role(
        roles,
        [
            "cryostack-batch-service-role",
            "AWSBatchServiceRole",
        ],
    )

    execution_role = find_role(
        roles,
        [
            "cryostack-ecs-execution-role",
            "ecsTaskExecutionRole",
        ],
    )

    job_role = find_role(
        roles,
        [
            "cryostack-job-role",
        ],
    )

    ec2_instance_profile = find_instance_profile(
        list_instance_profiles(config),
        ["cryostack-ec2-instance-profile"],
    )

    missing: list[str] = []

    if not batch_role:
        missing.append(
            "batch_service_role"
        )

    if not execution_role:
        missing.append(
            "ecs_execution_role"
        )

    if not job_role:
        missing.append(
            "job_role"
        )

    return AWSIAMResources(
        batch_service_role=(
            batch_role.get("Arn")
            if batch_role
            else None
        ),
        ecs_execution_role=(
            execution_role.get("Arn")
            if execution_role
            else None
        ),
        job_role=(
            job_role.get("Arn")
            if job_role
            else None
        ),
        batch_service_role_name=(
            batch_role.get("RoleName")
            if batch_role
            else None
        ),
        ecs_execution_role_name=(
            execution_role.get("RoleName")
            if execution_role
            else None
        ),
        job_role_name=(
            job_role.get("RoleName")
            if job_role
            else None
        ),
        ec2_instance_profile=(
            ec2_instance_profile.get("Arn")
            if ec2_instance_profile
            else None
        ),
        ec2_instance_profile_name=(
            ec2_instance_profile.get("InstanceProfileName")
            if ec2_instance_profile
            else None
        ),
        missing=missing,
    )