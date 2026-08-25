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
import re
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


class AWSCredentialsError(RuntimeError):
    """
    Raised when no AWS credentials are available.
    """
    pass

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

    if code != 0:

        if "NoCredentials" in stderr:
            raise AWSCredentialsError(
                "AWS credentials not configured."
            )

        require_success(
            code,
            stdout,
            stderr,
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

    try:

        identity = get_account_identity(
            config
        )

    except AWSCredentialsError:

        return AWSCapabilityResult(
            account_id="",
            region=config.region,
            network=AWSNetworkResources(
                vpc_id=None,
                subnet_ids=[],
                security_group_ids=[],
                default_vpc=False,
            ),
            iam=AWSIAMResources(
                batch_service_role=None,
                ecs_execution_role=None,
                job_role=None,
            ),
            messages=[
                "AWS credentials are not configured.",
                "Run 'aws configure' or connect your AWS account.",
            ],
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

def cryostack_resource_name(
    *,
    account_id: str,
    resource: str,
) -> str:
    """
    Build a predictable CryoStack AWS resource name.
    """

    account = re.sub(
        r"[^0-9]",
        "",
        account_id,
    )

    resource = re.sub(
        r"[^a-z0-9-]",
        "-",
        resource.strip().lower(),
    )

    resource = re.sub(
        r"-+",
        "-",
        resource,
    ).strip("-")

    return (
        f"cryostack-{resource}-{account}"
    )

def create_s3_bucket(
    config: AWSConfig,
    bucket: str,
) -> None:
    """
    Create the CryoStack run bucket.

    S3 uses a special create-bucket syntax for us-east-1,
    while other regions require a LocationConstraint.
    """

    arguments = [
        "s3api",
        "create-bucket",
        "--bucket",
        bucket,
    ]

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

    require_success(
        code,
        stdout,
        stderr,
    )

def enable_s3_encryption(
    config: AWSConfig,
    bucket: str,
) -> None:
    """
    Configure default server-side encryption for the run bucket.
    """

    encryption = {
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
            json.dumps(encryption),
        ],
    )

    require_success(
        code,
        stdout,
        stderr,
    )

def block_s3_public_access(
    config: AWSConfig,
    bucket: str,
) -> None:
    """
    Prevent public access to CryoStack experiment storage.
    """

    public_access = {
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
            json.dumps(public_access),
        ],
    )

    require_success(
        code,
        stdout,
        stderr,
    )

def ensure_s3_bucket(
    config: AWSConfig,
    *,
    bucket: str | None = None,
) -> tuple[str, bool]:
    """
    Ensure that CryoStack has an S3 run bucket.

    Returns
    -------
    tuple[str, bool]
        Bucket name and whether it was created during this call.
    """

    try:

        identity = get_account_identity(
            config
        )

    except AWSCredentialsError:

        return AWSCapabilityResult(
            account_id="",
            region=config.region,
            network=AWSNetworkResources(
                vpc_id=None,
                subnet_ids=[],
                security_group_ids=[],
                default_vpc=False,
            ),
            iam=AWSIAMResources(
                batch_service_role=None,
                ecs_execution_role=None,
                job_role=None,
            ),
            messages=[
                "AWS credentials are not configured.",
                "Run 'aws configure' or connect your AWS account.",
            ],
        )

    account_id = identity.get(
        "Account"
    )

    if not account_id:
        raise RuntimeError(
            "Could not determine AWS account ID."
        )

    if not bucket:
        bucket = cryostack_resource_name(
            account_id=account_id,
            resource="runs",
        )

    if s3_bucket_exists(
        config,
        bucket,
    ):
        return bucket, False

    create_s3_bucket(
        config,
        bucket,
    )

    enable_s3_encryption(
        config,
        bucket,
    )

    block_s3_public_access(
        config,
        bucket,
    )

    return bucket, True


@dataclass
class AWSStorageResult:
    """
    Prepared CryoStack cloud storage.
    """

    bucket: str
    created: bool
    region: str
    account_id: str
    s3_prefix: str


def prepare_aws_storage(
    config: AWSConfig,
    *,
    bucket: str | None = None,
) -> AWSStorageResult:
    """
    Prepare the default CryoStack AWS storage environment.
    """

    try:

        identity = get_account_identity(
            config
        )

    except AWSCredentialsError:

        return AWSCapabilityResult(
            account_id="",
            region=config.region,
            network=AWSNetworkResources(
                vpc_id=None,
                subnet_ids=[],
                security_group_ids=[],
                default_vpc=False,
            ),
            iam=AWSIAMResources(
                batch_service_role=None,
                ecs_execution_role=None,
                job_role=None,
            ),
            messages=[
                "AWS credentials are not configured.",
                "Run 'aws configure' or connect your AWS account.",
            ],
        )

    account_id = identity.get(
        "Account"
    )

    if not account_id:
        raise RuntimeError(
            "Could not determine AWS account."
        )

    bucket_name, created = ensure_s3_bucket(
        config,
        bucket=bucket,
    )

    return AWSStorageResult(
        bucket=bucket_name,
        created=created,
        region=config.region,
        account_id=account_id,
        s3_prefix=(
            f"s3://{bucket_name}/runs"
        ),
    )

@dataclass
class AWSNetworkResources:
    """
    AWS networking resources discovered for CryoStack.
    """

    vpc_id: str | None

    subnet_ids: list[str]
    security_group_ids: list[str]

    default_vpc: bool


@dataclass
class AWSIAMResources:
    """
    IAM roles discovered for CryoStack cloud execution.
    """

    batch_service_role: str | None
    ecs_execution_role: str | None
    job_role: str | None


@dataclass
class AWSCapabilityResult:
    """
    Cloud capabilities discovered from the connected AWS account.
    """

    account_id: str
    region: str

    network: AWSNetworkResources
    iam: AWSIAMResources

    messages: list[str]

def discover_default_vpc(
    config: AWSConfig,
) -> dict | None:
    """
    Discover the account's default VPC in the configured region.
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

    require_success(
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
    Discover subnets belonging to a VPC.
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

    require_success(
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
    Discover security groups belonging to a VPC.
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

    require_success(
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
    Discover networking CryoStack may use for AWS Batch.
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
    # Prefer the default security group.
    #
    default_groups = [
        group["GroupId"]
        for group in security_groups
        if group.get("GroupName") == "default"
        and group.get("GroupId")
    ]

    if not default_groups:
        default_groups = [
            group["GroupId"]
            for group in security_groups
            if group.get("GroupId")
        ][:1]

    return AWSNetworkResources(
        vpc_id=vpc_id,
        subnet_ids=[
            subnet["SubnetId"]
            for subnet in subnets
            if subnet.get("SubnetId")
        ],
        security_group_ids=default_groups,
        default_vpc=True,
    )

def list_iam_roles(
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

    require_success(
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

def _find_role_arn(
    roles: list[dict],
    names: list[str],
) -> str | None:
    """
    Find the first IAM role matching one of the supplied names.
    """

    wanted = {
        name.lower()
        for name in names
    }

    for role in roles:

        name = (
            role.get("RoleName")
            or ""
        )

        if name.lower() in wanted:
            return role.get(
                "Arn"
            )

    return None


def discover_iam_resources(
    config: AWSConfig,
) -> AWSIAMResources:
    """
    Discover IAM roles commonly used by CryoStack AWS execution.
    """

    roles = list_iam_roles(
        config
    )

    batch_service_role = _find_role_arn(
        roles,
        [
            "AWSBatchServiceRole",
            "CryoStackBatchServiceRole",
        ],
    )

    ecs_execution_role = _find_role_arn(
        roles,
        [
            "ecsTaskExecutionRole",
            "CryoStackExecutionRole",
        ],
    )

    job_role = _find_role_arn(
        roles,
        [
            "CryoStackJobRole",
            "CryoStackBatchJobRole",
        ],
    )

    return AWSIAMResources(
        batch_service_role=(
            batch_service_role
        ),
        ecs_execution_role=(
            ecs_execution_role
        ),
        job_role=job_role,
    )

def discover_aws_capabilities(
    config: AWSConfig,
) -> AWSCapabilityResult:
    """
    Discover AWS resources CryoStack may reuse automatically.
    """

    messages: list[str] = []

    try:

        identity = get_account_identity(
            config
        )

    except AWSCredentialsError:

        return AWSCapabilityResult(
            account_id="",
            region=config.region,
            network=AWSNetworkResources(
                vpc_id=None,
                subnet_ids=[],
                security_group_ids=[],
                default_vpc=False,
            ),
            iam=AWSIAMResources(
                batch_service_role=None,
                ecs_execution_role=None,
                job_role=None,
            ),
            messages=[
                "AWS credentials are not configured.",
                "Run 'aws configure' or connect your AWS account.",
            ],
        )

    account_id = identity.get(
        "Account"
    )

    if not account_id:
        raise RuntimeError(
            "Could not determine AWS account."
        )

    network = discover_network_resources(
        config
    )

    iam = discover_iam_resources(
        config
    )

    messages.append(
        f"[aws] Account: {account_id}"
    )

    messages.append(
        f"[aws] Region : {config.region}"
    )

    if network.vpc_id:
        messages.append(
            "[aws] Default VPC: "
            f"{network.vpc_id}"
        )

        messages.append(
            "[aws] Subnets: "
            f"{len(network.subnet_ids)}"
        )

        messages.append(
            "[aws] Security groups: "
            f"{len(network.security_group_ids)}"
        )
    else:
        messages.append(
            "[aws] No default VPC discovered."
        )

    if iam.batch_service_role:
        messages.append(
            "[aws] Batch service role found."
        )
    else:
        messages.append(
            "[aws] Batch service role missing."
        )

    if iam.ecs_execution_role:
        messages.append(
            "[aws] ECS execution role found."
        )
    else:
        messages.append(
            "[aws] ECS execution role missing."
        )

    if iam.job_role:
        messages.append(
            "[aws] CryoStack job role found."
        )
    else:
        messages.append(
            "[aws] CryoStack job role missing."
        )

    return AWSCapabilityResult(
        account_id=account_id,
        region=config.region,
        network=network,
        iam=iam,
        messages=messages,
    )