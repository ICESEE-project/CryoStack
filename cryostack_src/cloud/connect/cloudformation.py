# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Account Connection
# File        : cloudformation.py
#
# Description :
#     The CryoStackExecutionRole CloudFormation template and the console
#     Quick Create URL builder used by the "Connect AWS Account" flow.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-09-03
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
Cross-account onboarding via CloudFormation Quick Create.

The user opens a pre-filled CloudFormation *Quick Create* page in their own
AWS console. It creates a single IAM role -- ``CryoStackExecutionRole`` --
that:

* trusts **only** the deployment-configured CryoStack principal;
* can be assumed **only** when ``sts:ExternalId`` equals the per-connection
  value CryoStack minted;
* grants the **least privilege** the current demo path needs -- scoped to
  ``cryostack-*`` resources. No ``AdministratorAccess``, no
  ``Action:"*" / Resource:"*"``.

``ExternalId`` and the CryoStack principal ARN are template *parameters*, so
one published template serves every deployment and every user.
"""

from __future__ import annotations

import json
from urllib.parse import quote, urlencode

EXECUTION_ROLE_NAME = "CryoStackExecutionRole"
DEFAULT_STACK_NAME = "cryostack-access"
TEMPLATE_VERSION = "2026-09-03"

# names CryoStack provisions inside the user's account (kept in sync with
# cryostack_src.cloud.drivers.aws.batch_config)
_CRYOSTACK_RESOURCE_GLOB = "cryostack-*"


# ---------------------------------------------------------------------------
# template
# ---------------------------------------------------------------------------
def _trust_policy() -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": {"Ref": "CryoStackPrincipalArn"}},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"sts:ExternalId": {"Ref": "ExternalId"}}
                },
            }
        ],
    }


def _permissions_policy() -> dict:
    partition = "${AWS::Partition}"
    account = "${AWS::AccountId}"

    def sub(value: str) -> dict:
        return {"Fn::Sub": value}

    return {
        "Version": "2012-10-17",
        "Statement": [
            # -- S3 run I/O: scoped to cryostack-runs-* --------------------
            {
                "Sid": "CryoStackRunsBuckets",
                "Effect": "Allow",
                "Action": [
                    "s3:CreateBucket",
                    "s3:GetBucketLocation",
                    "s3:ListBucket",
                    "s3:PutBucketVersioning",
                    "s3:PutBucketPublicAccessBlock",
                    "s3:PutEncryptionConfiguration",
                    "s3:PutLifecycleConfiguration",
                ],
                "Resource": sub(f"arn:{partition}:s3:::cryostack-runs-*"),
            },
            {
                "Sid": "CryoStackRunsObjects",
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:AbortMultipartUpload",
                    "s3:ListMultipartUploadParts",
                ],
                "Resource": sub(f"arn:{partition}:s3:::cryostack-runs-*/*"),
            },
            # -- ECR: auth token is un-scopable; everything else -> cryostack-*
            {
                "Sid": "CryoStackEcrAuth",
                "Effect": "Allow",
                "Action": "ecr:GetAuthorizationToken",
                "Resource": "*",
            },
            {
                "Sid": "CryoStackEcrRepos",
                "Effect": "Allow",
                "Action": [
                    "ecr:CreateRepository",
                    "ecr:DescribeRepositories",
                    "ecr:DescribeImages",
                    "ecr:ListImages",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:InitiateLayerUpload",
                    "ecr:UploadLayerPart",
                    "ecr:CompleteLayerUpload",
                    "ecr:PutImage",
                    "ecr:SetRepositoryPolicy",
                    "ecr:GetRepositoryPolicy",
                ],
                "Resource": sub(
                    f"arn:{partition}:ecr:*:{account}:repository/cryostack-*"
                ),
            },
            # -- AWS Batch: describe/list broad; mutate scoped to cryostack-*
            {
                "Sid": "CryoStackBatchRead",
                "Effect": "Allow",
                "Action": [
                    "batch:DescribeComputeEnvironments",
                    "batch:DescribeJobQueues",
                    "batch:DescribeJobDefinitions",
                    "batch:DescribeJobs",
                    "batch:ListJobs",
                ],
                "Resource": "*",
            },
            {
                "Sid": "CryoStackBatchProvision",
                "Effect": "Allow",
                "Action": [
                    "batch:CreateComputeEnvironment",
                    "batch:UpdateComputeEnvironment",
                    "batch:DeleteComputeEnvironment",
                    "batch:CreateJobQueue",
                    "batch:UpdateJobQueue",
                    "batch:DeleteJobQueue",
                    "batch:RegisterJobDefinition",
                    "batch:DeregisterJobDefinition",
                    "batch:TagResource",
                ],
                "Resource": [
                    sub(
                        f"arn:{partition}:batch:*:{account}:compute-environment/cryostack-*"
                    ),
                    sub(f"arn:{partition}:batch:*:{account}:job-queue/cryostack-*"),
                    sub(
                        f"arn:{partition}:batch:*:{account}:job-definition/cryostack-*"
                    ),
                ],
            },
            {
                "Sid": "CryoStackBatchRun",
                "Effect": "Allow",
                "Action": ["batch:SubmitJob"],
                "Resource": [
                    sub(f"arn:{partition}:batch:*:{account}:job-queue/cryostack-*"),
                    sub(
                        f"arn:{partition}:batch:*:{account}:job-definition/cryostack-*"
                    ),
                ],
            },
            {
                "Sid": "CryoStackBatchTerminate",
                "Effect": "Allow",
                "Action": ["batch:TerminateJob", "batch:CancelJob"],
                "Resource": sub(f"arn:{partition}:batch:*:{account}:job/*"),
            },
            # -- CloudWatch Logs: read job output; create the group ------
            {
                "Sid": "CryoStackLogsRead",
                "Effect": "Allow",
                "Action": [
                    "logs:GetLogEvents",
                    "logs:FilterLogEvents",
                    "logs:DescribeLogStreams",
                    "logs:DescribeLogGroups",
                ],
                "Resource": sub(
                    f"arn:{partition}:logs:*:{account}:log-group:/cryostack/*"
                ),
            },
            {
                "Sid": "CryoStackLogsGroup",
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:PutRetentionPolicy"],
                "Resource": sub(
                    f"arn:{partition}:logs:*:{account}:log-group:/cryostack/*"
                ),
            },
            # -- IAM: create + pass ONLY the cryostack-* service roles ----
            {
                "Sid": "CryoStackServiceRoles",
                "Effect": "Allow",
                "Action": [
                    "iam:CreateRole",
                    "iam:GetRole",
                    "iam:TagRole",
                    "iam:ListRolePolicies",
                    "iam:ListAttachedRolePolicies",
                    "iam:GetRolePolicy",
                    "iam:PutRolePolicy",
                    "iam:DeleteRolePolicy",
                    "iam:AttachRolePolicy",
                    "iam:DetachRolePolicy",
                ],
                "Resource": sub(f"arn:{partition}:iam::{account}:role/cryostack-*"),
            },
            {
                "Sid": "CryoStackPassRole",
                "Effect": "Allow",
                "Action": "iam:PassRole",
                "Resource": sub(f"arn:{partition}:iam::{account}:role/cryostack-*"),
                "Condition": {
                    "StringEquals": {
                        "iam:PassedToService": [
                            "batch.amazonaws.com",
                            "ecs-tasks.amazonaws.com",
                        ]
                    }
                },
            },
            {
                "Sid": "CryoStackBatchServiceLinkedRole",
                "Effect": "Allow",
                "Action": "iam:CreateServiceLinkedRole",
                "Resource": sub(
                    f"arn:{partition}:iam::{account}:role/aws-service-role/"
                    "batch.amazonaws.com/*"
                ),
                "Condition": {
                    "StringEquals": {"iam:AWSServiceName": "batch.amazonaws.com"}
                },
            },
            # -- EC2 describe: networking discovery (un-scopable) --------
            {
                "Sid": "CryoStackNetworkDiscovery",
                "Effect": "Allow",
                "Action": [
                    "ec2:DescribeVpcs",
                    "ec2:DescribeSubnets",
                    "ec2:DescribeSecurityGroups",
                    "ec2:DescribeRouteTables",
                    "ec2:DescribeAvailabilityZones",
                ],
                "Resource": "*",
            },
            # -- identity + region-price lookups for the cost estimate --
            {
                "Sid": "CryoStackIdentityAndPricing",
                "Effect": "Allow",
                "Action": [
                    "sts:GetCallerIdentity",
                    "pricing:GetProducts",
                ],
                "Resource": "*",
            },
        ],
    }


def execution_role_template() -> dict:
    """The full CryoStackExecutionRole CloudFormation template (as a dict)."""
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": (
            "CryoStack cross-account access role. Grants CryoStack least-"
            "privilege access to run scientific experiments on AWS Batch in "
            "your account, assumable only with your unique ExternalId. "
            f"(template {TEMPLATE_VERSION})"
        ),
        "Parameters": {
            "ExternalId": {
                "Type": "String",
                "NoEcho": True,
                "MinLength": 8,
                "AllowedPattern": r"[\w+=,.@:/-]+",
                "Description": (
                    "The unique ExternalId shown in CryoStack. Do not change it."
                ),
            },
            "CryoStackPrincipalArn": {
                "Type": "String",
                "AllowedPattern": r"arn:aws[a-z-]*:(iam|sts)::\d{12}:.+",
                "Description": (
                    "The CryoStack AWS principal allowed to assume this role. "
                    "Pre-filled by CryoStack; do not change it."
                ),
            },
        },
        "Resources": {
            "CryoStackExecutionRole": {
                "Type": "AWS::IAM::Role",
                "Properties": {
                    "RoleName": EXECUTION_ROLE_NAME,
                    "Description": (
                        "Assumed by CryoStack to run experiments on AWS Batch."
                    ),
                    "MaxSessionDuration": 3600,
                    "AssumeRolePolicyDocument": _trust_policy(),
                    "Policies": [
                        {
                            "PolicyName": "CryoStackExecutionAccess",
                            "PolicyDocument": _permissions_policy(),
                        }
                    ],
                    "Tags": [
                        {"Key": "app", "Value": "cryostack"},
                        {"Key": "managed-by", "Value": "cryostack-quick-create"},
                    ],
                },
            }
        },
        "Outputs": {
            "RoleArn": {
                "Description": "Paste this back into CryoStack to verify the connection.",
                "Value": {"Fn::GetAtt": ["CryoStackExecutionRole", "Arn"]},
            }
        },
    }


def render_template(*, indent: int | None = 2) -> str:
    """The template as a JSON string, ready to host at a public URL."""
    return json.dumps(execution_role_template(), indent=indent, sort_keys=False)


# ---------------------------------------------------------------------------
# Quick Create URL
# ---------------------------------------------------------------------------
def quick_create_url(
    *,
    template_url: str,
    external_id: str,
    region: str,
    principal_arn: str,
    stack_name: str = DEFAULT_STACK_NAME,
) -> str:
    """A CloudFormation console *Quick Create* URL, pre-filled and safely encoded.

    The user only has to review and click **Create stack** -- the role name,
    ExternalId, and CryoStack principal are already set.
    """
    for name, value in (
        ("template_url", template_url),
        ("external_id", external_id),
        ("region", region),
        ("principal_arn", principal_arn),
    ):
        if not (value or "").strip():
            raise ValueError(f"quick_create_url: {name} is required")

    region = region.strip()
    base = (
        f"https://{region}.console.aws.amazon.com/cloudformation/home"
        f"?region={quote(region, safe='')}#/stacks/quickcreate"
    )
    params = urlencode(
        {
            "templateURL": template_url.strip(),
            "stackName": stack_name.strip(),
            "param_ExternalId": external_id.strip(),
            "param_CryoStackPrincipalArn": principal_arn.strip(),
        },
        quote_via=quote,
    )
    return f"{base}?{params}"
