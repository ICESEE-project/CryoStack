# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS IAM Provisioning
# File        : iam_provision.py
#
# Description :
#     Creates and configures the minimum IAM roles required for CryoStack
#     AWS Batch execution.
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
AWS IAM provisioning services for CryoStack.

The functions in this module create only the IAM resources required for
CryoStack Batch execution and prefer AWS-managed service policies where
appropriate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .auth import run_aws
from .iam import (
    AWSIAMResources,
    discover_iam_resources,
)
from .iam_policies import (
    MATLAB_LICENSE_SECRET_POLICY_NAME,
    batch_service_trust_policy,
    ecs_execution_trust_policy,
    job_s3_policy,
    job_trust_policy,
    matlab_license_secret_policy,
)
from .models import AWSConfig

# CryoStack-provisioned IAM role names. Kept as ``cryostack-*`` (kebab) so they
# match the least-privilege ``role/cryostack-*`` scope of the cross-account
# CryoStackExecutionRole users create in C7.2 -- and so they never collide with
# that PascalCase cross-account role name (which must stay outside this scope
# and must never be mistaken for the ECS task-execution role: see iam.py).
BATCH_SERVICE_ROLE_NAME = "cryostack-batch-service-role"
ECS_EXECUTION_ROLE_NAME = "cryostack-ecs-execution-role"
JOB_ROLE_NAME = "cryostack-job-role"


@dataclass
class AWSIAMProvisionResult:
    """
    Result of preparing CryoStack IAM resources.
    """

    resources: AWSIAMResources

    created: list[str]
    reused: list[str]
    #: policies reconciled on an already-existing role this run (e.g. the
    #: ISSM MATLAB-license secret grant re-scoped to a changed ARN).
    updated: list[str] = field(default_factory=list)


def _require_success(
    code: int,
    stdout: str,
    stderr: str,
) -> str:

    if code != 0:
        raise RuntimeError(
            (stderr or stdout).strip()
            or "AWS IAM provisioning failed."
        )

    return stdout


def create_role(
    config: AWSConfig,
    *,
    name: str,
    trust_policy: dict,
) -> str:
    """
    Create an IAM role and return its ARN.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "iam",
            "create-role",
            "--role-name",
            name,
            "--assume-role-policy-document",
            json.dumps(trust_policy),
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

    role = payload.get(
        "Role",
        {},
    )

    arn = role.get(
        "Arn"
    )

    if not arn:
        raise RuntimeError(
            f"Unable to determine ARN for IAM role {name}."
        )

    return arn


def attach_managed_policy(
    config: AWSConfig,
    *,
    role_name: str,
    policy_arn: str,
) -> None:

    code, stdout, stderr = run_aws(
        config,
        [
            "iam",
            "attach-role-policy",
            "--role-name",
            role_name,
            "--policy-arn",
            policy_arn,
        ],
    )

    _require_success(
        code,
        stdout,
        stderr,
    )


def put_inline_policy(
    config: AWSConfig,
    *,
    role_name: str,
    policy_name: str,
    policy: dict,
) -> None:

    code, stdout, stderr = run_aws(
        config,
        [
            "iam",
            "put-role-policy",
            "--role-name",
            role_name,
            "--policy-name",
            policy_name,
            "--policy-document",
            json.dumps(policy),
        ],
    )

    _require_success(
        code,
        stdout,
        stderr,
    )


def delete_inline_policy(
    config: AWSConfig,
    *,
    role_name: str,
    policy_name: str,
) -> bool:
    """Delete one inline role policy by name. Returns ``True`` if a policy
    was removed, ``False`` if there was nothing to remove (already absent).
    Any other failure raises -- an unexpected error must not be swallowed.
    """

    code, stdout, stderr = run_aws(
        config,
        [
            "iam",
            "delete-role-policy",
            "--role-name",
            role_name,
            "--policy-name",
            policy_name,
        ],
    )

    if code == 0:
        return True

    blob = (stderr or stdout or "").lower()
    if "nosuchentity" in blob or "cannot be found" in blob:
        return False

    raise RuntimeError(
        (stderr or stdout).strip()
        or "Failed to delete inline role policy."
    )


def _reconcile_matlab_license_secret(
    config: AWSConfig,
    *,
    matlab_secret_arn: str,
    updated: list[str],
) -> None:
    """Reconcile the ISSM MATLAB-license secret grant on the ECS
    task-execution role. Runs on EVERY Prepare Cloud, independent of whether
    the role was just created:

    * a configured ARN -> put/overwrite an inline policy scoped to EXACTLY
      that secret ARN. An ARN change (secret A -> secret B) is handled by the
      overwrite: the role stops being able to read A and is scoped to B.
    * no ARN -> remove CryoStack's own ``CryoStackMatlabLicenseSecret``
      inline policy if present, so the role never keeps a stale grant. Only
      that one named policy is ever touched; every other policy on the role
      (the AWS-managed ``AmazonECSTaskExecutionRolePolicy``, anything the
      user added) is left exactly as it was.

    KMS: a secret encrypted with the Secrets Manager default AWS-managed key
    needs no extra ``kms:Decrypt`` grant. A customer-managed key would; the
    UI does not collect a CMK ARN today, so that is a documented future case
    (see :func:`matlab_license_secret_policy`).
    """

    arn = (matlab_secret_arn or "").strip()

    if arn:
        put_inline_policy(
            config,
            role_name=ECS_EXECUTION_ROLE_NAME,
            policy_name=MATLAB_LICENSE_SECRET_POLICY_NAME,
            policy=matlab_license_secret_policy(secret_arn=arn),
        )
        updated.append("ecs_execution_role:matlab_license_secret")
        return

    if delete_inline_policy(
        config,
        role_name=ECS_EXECUTION_ROLE_NAME,
        policy_name=MATLAB_LICENSE_SECRET_POLICY_NAME,
    ):
        updated.append("ecs_execution_role:matlab_license_secret (removed)")


def ensure_iam_resources(
    config: AWSConfig,
    *,
    bucket: str,
    matlab_secret_arn: str = "",
) -> AWSIAMProvisionResult:
    """
    Ensure the IAM roles required by CryoStack AWS Batch exist.
    """

    current = discover_iam_resources(
        config
    )

    created: list[str] = []
    reused: list[str] = []
    updated: list[str] = []

    #
    # ---------------------------------------------------------
    # Batch service role
    # ---------------------------------------------------------
    #
    if current.batch_service_role:

        reused.append(
            "batch_service_role"
        )

    else:

        create_role(
            config,
            name=BATCH_SERVICE_ROLE_NAME,
            trust_policy=(
                batch_service_trust_policy()
            ),
        )

        attach_managed_policy(
            config,
            role_name=BATCH_SERVICE_ROLE_NAME,
            policy_arn=(
                "arn:aws:iam::aws:policy/"
                "service-role/"
                "AWSBatchServiceRole"
            ),
        )

        created.append(
            "batch_service_role"
        )

    #
    # ---------------------------------------------------------
    # ECS execution role
    # ---------------------------------------------------------
    #
    if current.ecs_execution_role:

        reused.append(
            "ecs_execution_role"
        )

    else:

        create_role(
            config,
            name=ECS_EXECUTION_ROLE_NAME,
            trust_policy=(
                ecs_execution_trust_policy()
            ),
        )

        attach_managed_policy(
            config,
            role_name=ECS_EXECUTION_ROLE_NAME,
            policy_arn=(
                "arn:aws:iam::aws:policy/"
                "service-role/"
                "AmazonECSTaskExecutionRolePolicy"
            ),
        )

        created.append(
            "ecs_execution_role"
        )

    #
    # Reconcile the ISSM MATLAB-license secret grant on the ECS execution
    # role EVERY run -- whether the role was just created or already existed
    # -- so a changed secret ARN (A -> B) re-scopes the grant and a cleared
    # ARN removes it. No-op (and no permission added) when unconfigured.
    #
    _reconcile_matlab_license_secret(
        config,
        matlab_secret_arn=matlab_secret_arn,
        updated=updated,
    )

    #
    # ---------------------------------------------------------
    # CryoStack job role
    # ---------------------------------------------------------
    #
    if current.job_role:

        reused.append(
            "job_role"
        )

    else:

        create_role(
            config,
            name=JOB_ROLE_NAME,
            trust_policy=(
                job_trust_policy()
            ),
        )

        put_inline_policy(
            config,
            role_name=JOB_ROLE_NAME,
            policy_name=(
                "CryoStackRunStorage"
            ),
            policy=job_s3_policy(
                bucket=bucket,
            ),
        )

        created.append(
            "job_role"
        )

    #
    # Rediscover so returned values contain
    # the final role ARNs.
    #
    resources = discover_iam_resources(
        config
    )

    return AWSIAMProvisionResult(
        resources=resources,
        created=created,
        reused=reused,
        updated=updated,
    )