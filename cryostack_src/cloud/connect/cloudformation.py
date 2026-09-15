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
AWS console. It creates a single IAM role -- logical id
``CryoStackExecutionRole`` -- that:

* trusts **only** the deployment-configured CryoStack principal;
* can be assumed **only** when ``sts:ExternalId`` equals the per-connection
  value CryoStack minted;
* grants the **least privilege** the current demo path needs -- scoped to
  ``cryostack-*`` resources. No ``AdministratorAccess``, no
  ``Action:"*" / Resource:"*"``.

``ExternalId`` and the CryoStack principal ARN are template *parameters*, so
one published template serves every deployment and every user.

**Role/stack naming (2026-09-08 onboarding fix).** The role resource does
NOT set an explicit ``RoleName`` -- CloudFormation generates a unique,
stack-scoped physical name and the template's ``Outputs.RoleArn`` (which
the user pastes back into CryoStack) is always the real, actual ARN of
whatever CloudFormation actually created. Two consequences:

* A second CryoStack connection (a different CryoStack identity, or a
  genuinely new connection replacing this one) can create its own role in
  the SAME AWS account without ever colliding on role name -- previously
  every connection's role was hardcoded to the single physical name
  ``CryoStackExecutionRole``, so a second ``CREATE_STACK`` in the same
  account always failed with "Resource of type 'AWS::IAM::Role' ... already
  exists" and rolled back.
* CryoStack never needs to assume, validate against, or hardcode any
  particular physical role name anywhere downstream (verify.py/assume_role.py
  already only require a syntactically valid ARN + a matching ExternalId --
  see :func:`cryostack_src.cloud.connect.models.is_valid_role_arn`), so this
  requires no change to the verify/assume-role/execution path at all.

The STACK name is likewise never the single fixed ``DEFAULT_STACK_NAME`` --
see :func:`connection_stack_name`, used by ``onboarding.py`` to scope it to
one connection (and, via ``AWSConnection.stack_attempt``, to one attempt of
that connection), so a stack that rolled back to ``ROLLBACK_COMPLETE``
never strands the user on a name they can't reuse.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote, urlencode

#: kept for backward-compatible reference/tests and as the template's Role
#: LOGICAL id -- no longer the role's PHYSICAL name (see module docstring).
EXECUTION_ROLE_NAME = "CryoStackExecutionRole"
DEFAULT_STACK_NAME = "cryostack-access"
TEMPLATE_VERSION = "2026-09-14b"

_STACK_NAME_MAX_LENGTH = 128
_STACK_SLUG_RE = re.compile(r"[^a-z0-9]+")

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
            # -- ECR: the auth token and the account-wide repository *listing*
            #    are un-scopable; every repository-specific action -> cryostack-*
            {
                "Sid": "CryoStackEcrAuth",
                "Effect": "Allow",
                "Action": "ecr:GetAuthorizationToken",
                "Resource": "*",
            },
            {
                # `ecr:DescribeRepositories` is called without a repository
                # filter during discovery (registry.py:list_repositories),
                # which AWS authorises against arn:...:repository/* -- a
                # `repository/cryostack-*` scope denies it. Read-only.
                "Sid": "CryoStackEcrListRepositories",
                "Effect": "Allow",
                "Action": "ecr:DescribeRepositories",
                "Resource": "*",
            },
            {
                "Sid": "CryoStackEcrRepos",
                "Effect": "Allow",
                "Action": [
                    "ecr:CreateRepository",
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
                    "ecr:GetLifecyclePolicy",
                    "ecr:PutLifecyclePolicy",
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
            #
            # `logs:GetLogEvents` is the ONLY CloudWatch Logs read operation
            # this codebase calls (cryostack_src/cloud/legacy/aws_batch.py's
            # `batch_logs` -- `aws logs get-log-events`); it does not use
            # `FilterLogEvents`, `DescribeLogStreams` or `DescribeLogGroups`,
            # so those are intentionally NOT granted (least privilege -- an
            # unused permission is a permission that cannot regress into a
            # future overbroad grant). The stream/log-group NAME it reads
            # comes from Batch's own `DescribeJobs` (`CryoStackBatchRead`
            # above), never from a `Describe*`/`Filter*` Logs call.
            #
            # Two resource families, both granted -- `batch_logs` currently
            # reads the AWS Batch DEFAULT group (`/aws/batch/job`, used
            # whenever a job definition's `logConfiguration` does not
            # override `awslogs-group`, and the group this permission fix
            # was written against: a live AccessDeniedException on
            # `logs:GetLogEvents` for
            # `log-group:/aws/batch/job:log-stream:icepack/default/...`),
            # while newly-registered job definitions
            # (`batch_config.py:container_properties_payload`) explicitly
            # set `awslogs-group` to the CryoStack-managed
            # `/cryostack/batch/<model>` group `ensure_log_group` creates.
            # Granting both means log reads work against either, without
            # widening past AWS Batch's own log-group namespaces.
            {
                "Sid": "CryoStackLogsRead",
                "Effect": "Allow",
                "Action": "logs:GetLogEvents",
                "Resource": [
                    sub(f"arn:{partition}:logs:*:{account}:log-group:/cryostack/*"),
                    sub(f"arn:{partition}:logs:*:{account}:log-group:/aws/batch/job:*"),
                ],
            },
            {
                "Sid": "CryoStackLogsGroup",
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:PutRetentionPolicy"],
                "Resource": sub(
                    f"arn:{partition}:logs:*:{account}:log-group:/cryostack/*"
                ),
            },
            # -- Secrets Manager: guided ISSM MATLAB-license secret setup --
            #
            # `secretsmanager:CreateSecret` has NO resource-level permission
            # support in AWS IAM: at authorization time the secret does not
            # exist yet, so its final ARN (which AWS suffixes with a random
            # 6-character string) cannot be named in `Resource`. AWS's own
            # documented pattern for restricting CreateSecret is `Resource:
            # "*"` combined with the `secretsmanager:Name` condition key --
            # used here exactly as documented, scoped to the ONE prefix
            # `cryostack_src/cloud/drivers/aws/secrets.py`'s
            # `create_matlab_license_secret` is hard-restricted to
            # (`SECRET_NAME_PREFIX = "cryostack/"`) -- never `secretsmanager:*`,
            # never an unconditioned `Resource: "*"`. No Region condition:
            # this ONE template is shared by every CryoStack connection
            # regardless of which Region it connects in (every other
            # resource family above is likewise Region-wildcarded, e.g.
            # `logs:*:{account}:...`), so a fixed `aws:RequestedRegion` value
            # cannot be baked into it.
            #
            # This is CREATE only -- no `GetSecretValue`, no `PutSecretValue`,
            # no `UpdateSecret`, no `DeleteSecret`. Reading the secret at
            # container-launch time is a SEPARATE, already-existing grant on
            # a SEPARATE role (`cryostack-ecs-execution-role`'s
            # `CryoStackMatlabLicenseSecret` inline policy -- see
            # `iam_policies.py:matlab_license_secret_policy` /
            # `iam_provision.py:_reconcile_matlab_license_secret`), scoped to
            # the exact ARN CreateSecret returns.
            {
                "Sid": "CryoStackMatlabLicenseSecretCreate",
                "Effect": "Allow",
                "Action": "secretsmanager:CreateSecret",
                "Resource": "*",
                "Condition": {
                    "StringLike": {
                        "secretsmanager:Name": "cryostack/*"
                    }
                },
            },
            # -- IAM: discover existing roles (ListRoles is account-level) --
            {
                "Sid": "CryoStackIamListRoles",
                "Effect": "Allow",
                "Action": "iam:ListRoles",
                "Resource": "*",
            },
            # -- IAM: discover existing instance profiles (Advanced EC2 Batch
            #    reconciliation -- iam.py:list_instance_profiles). Like
            #    `iam:ListRoles` above, `iam:ListInstanceProfiles` has no
            #    resource-level permissions in AWS IAM (see the IAM Actions,
            #    Resources, and Condition Keys reference): it is an
            #    account-wide list call, so `Resource: "*"` is the only valid
            #    form -- not a broadening choice. It grants no read access to
            #    instance-profile *contents* beyond name/ARN/role membership,
            #    which `iam:ListRoles` already effectively exposes for roles.
            {
                "Sid": "CryoStackIamListInstanceProfiles",
                "Effect": "Allow",
                "Action": "iam:ListInstanceProfiles",
                "Resource": "*",
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
            # -- IAM: Advanced EC2 Batch only -- create + populate the ECS
            #    instance profile the EC2 hosts assume
            #    (iam_provision.py:ensure_ec2_instance_profile). Both actions'
            #    only resource type in AWS IAM is `instance-profile`, a
            #    separate ARN namespace from `role/*` above, so it needs its
            #    own statement scoped to the one CryoStack-owned instance-
            #    profile name family. Never touched by the default Fargate
            #    path -- ensure_ec2_instance_profile is only called when the
            #    user selects EC2 mode.
            {
                "Sid": "CryoStackEc2InstanceProfile",
                "Effect": "Allow",
                "Action": [
                    "iam:CreateInstanceProfile",
                    "iam:AddRoleToInstanceProfile",
                ],
                "Resource": sub(
                    f"arn:{partition}:iam::{account}:instance-profile/cryostack-*"
                ),
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
                            # Advanced EC2 Batch: AWS Batch's `instanceRole`
                            # (the instance PROFILE) attaches
                            # cryostack-ec2-instance-role to the EC2 hosts it
                            # launches -- the role is ultimately assumed by
                            # ec2.amazonaws.com, so CreateComputeEnvironment /
                            # UpdateComputeEnvironment with an EC2 instanceRole
                            # requires this PassedToService value in addition
                            # to the two above. Resource stays role/cryostack-*
                            # -- unchanged and no less scoped than before.
                            "ec2.amazonaws.com",
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
                    # No RoleName -- CloudFormation generates a unique,
                    # stack-scoped physical name so two connections (or a
                    # retried stack) never collide on a fixed role name. The
                    # actual ARN is always read back from Outputs.RoleArn.
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
# per-connection stack naming
# ---------------------------------------------------------------------------
def connection_stack_name(connection_id: str, *, attempt: int = 1) -> str:
    """A CloudFormation stack name scoped to ONE CryoStack connection --
    never the single fixed ``DEFAULT_STACK_NAME`` every prior connection
    shared.

    ``connection_id`` (``AWSConnectionStore``'s own opaque, random
    ``conn-<hex>`` id -- never a display name or email, per the "role/stack
    identity follows the connection" rule) makes two different connections'
    stacks always resolve to two different names, so a second CryoStack
    identity -- or a genuinely new connection replacing this one -- can
    never collide with an existing stack in the same AWS account.

    ``attempt`` (from ``AWSConnection.stack_attempt``, default 1) lets the
    SAME connection mint a fresh, non-colliding stack name without touching
    its ExternalId or role -- the escape hatch for a previous attempt that
    rolled back to ``ROLLBACK_COMPLETE``. An ordinary retry (page reload,
    "Retry connection") never bumps it, so it keeps reusing the exact same
    stack name -- and, once that stack has actually completed, the exact
    same role.
    """
    slug = _STACK_SLUG_RE.sub("-", (connection_id or "").strip().lower()).strip("-")
    if not slug:
        raise ValueError("connection_stack_name: connection_id is required")
    name = f"{DEFAULT_STACK_NAME}-{slug}"
    if int(attempt or 1) > 1:
        name = f"{name}-{int(attempt)}"
    return name[:_STACK_NAME_MAX_LENGTH]


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


# ---------------------------------------------------------------------------
# Existing-stack console link -- navigation only, no pre-filled parameters
# ---------------------------------------------------------------------------
def existing_stack_console_url(*, region: str, stack_name: str) -> str:
    """A CloudFormation console link to the region's Stacks list, filtered
    to the existing stack by name. Navigation only -- deliberately carries
    NO ExternalId, NO CryoStackPrincipalArn, and no other trust-sensitive
    value in the URL at all.

    An earlier revision tried to build an *Update stack* deep link
    (``#/stacks/update/template?stackId=...&param_ExternalId=...``) that
    pre-filled the SAME ExternalId/PrincipalArn Quick Create uses. That
    scheme is **not** a documented or supported AWS CloudFormation console
    feature -- AWS documents URL-based parameter pre-fill only for
    *creating* a brand-new stack (quick-create links); there is no
    equivalent for updating an existing one, and ``ExternalId`` is a
    ``NoEcho`` template parameter, which the real Update Stack wizard
    always renders blank regardless of the query string. Using it caused a
    live AssumeRole regression on a connected account (774888247882):
    whatever the fragment actually resolved to did not reproduce the
    stack's original trust-policy inputs.

    This link only gets the user to the right region's Stacks page, with a
    text filter set to the stack name -- a plain, best-effort search-box
    value, not a sensitive form field. Every subsequent step (select the
    stack, choose Update, "Replace current template", paste in the current
    CryoStack template URL, and leave every existing parameter as "Use
    existing value") is manual, and is spelled out in the UI text rather
    than asserted as automatic.
    """
    for name, value in (("region", region), ("stack_name", stack_name)):
        if not (value or "").strip():
            raise ValueError(f"existing_stack_console_url: {name} is required")

    region = region.strip()
    base = (
        f"https://{region}.console.aws.amazon.com/cloudformation/home"
        f"?region={quote(region, safe='')}#/stacks"
    )
    params = urlencode(
        {
            "filteringText": stack_name.strip(),
            "filteringStatus": "active",
            "viewNested": "true",
        },
        quote_via=quote,
    )
    return f"{base}?{params}"
