# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Hosted Pilot Participant Isolation
# File        : isolation.py
#
# Description :
#     IAM policy documents, the per-participant Batch job definition and the
#     scope check that keep hosted-pilot participants out of each other's
#     inputs, results, jobs and logs. Definitions only -- no AWS calls.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-11-15
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: MIT
#
# =============================================================================

"""
Participant isolation for the CryoStack hosted pilot.

Many untrusted participants share one project-owned AWS account and each
participant's own script runs inside the container. The hosted route
therefore uses the stronger option from the October execution review
(``deployment/soft_launch/pilot_execution_review``):

**The model task has NO AWS identity.** A hosted pilot job definition has no
``jobRoleArn``, so there are no task credentials for a script to find and no
S3, Secrets Manager or other AWS permission to misuse. Inputs and results
travel through the gateway with a per-reservation transfer capability.

* :func:`pilot_job_definition` -- the job definition, built by the reviewed
  ``PilotExecutionProfile`` (``control_center/services/project_execution.py``)
  and checked by :func:`assert_no_task_role`. Nothing is duplicated here: the
  command, bootstrap, bounds and tags are whatever the profile produces, so
  its own verifier accepts what is registered.
* :func:`pilot_execution_role_policy` / :func:`pilot_execution_role_trust` --
  the dedicated ``cryostack-pilot-execution`` role the ECS agent (not the
  model) uses: pull the image, write pilot log streams, read the transfer
  parameter and inject a participant's license secret. No S3, IAM or Batch.
* :func:`gateway_base_role_policy` -- what the gateway's own role needs, for
  the operator to review and attach.
* Hosted ISSM: a participant's MATLAB license is that participant's own
  Secrets Manager secret ``cryostack/pilot/<key>/matlab-license``.
  :func:`licensed_pilot_job_definition` adds it to that participant's
  reservation definition only, after :func:`assert_secret_scope`.

LEGACY, NOT USED BY THE HOSTED ROUTE: the per-participant job role, its S3
policy, the per-participant job definition that pins it, the S3 scope check
and the S3 session policy further down. They give the model task an AWS
identity (scoped to ``pilot/<key>/``) and are kept only for reference and so
close-out can recognise and remove such resources. They are not exported from
the package, and provisioning refuses them unless ``legacy_task_role=True``
is passed explicitly, which the hosted route never does.

This module contains documents and checks only. ``provision.py`` applies them.
"""

from __future__ import annotations

import json
import re

from cryostack_src.cloud.drivers.aws.batch_config import (
    DEFAULT_ISSM_JOB_CONFIG,
    JOB_QUEUE_NAME,
    LOG_GROUP_PREFIX,
    FargateJobConfig,
    container_properties_payload,
)
from cryostack_src.cloud.matlab_license import CloudMatlabLicense, MATLAB_LICENSE_ENV
from cryostack_src.cloud.s3_uri import S3LocationError
from cryostack_src.cloud.s3_uri import bucket_name as _s3_bucket_name

from .identity import (
    PILOT_NAME_PREFIX,
    PILOT_SECRET_PREFIX,
    TAG_PARTICIPANT,
    TAG_PILOT,
    normalize_model,
    participant_job_definition_name,
    participant_job_role_name,
    participant_key,
    participant_prefix,
    participant_secret_name,
    participant_tags,
)

#: The dedicated ECS execution role of hosted pilot jobs and its one inline
#: policy. The name is the one ``PilotExecutionProfile`` requires.
PILOT_EXECUTION_ROLE_NAME = "cryostack-pilot-execution"
PILOT_EXECUTION_POLICY_NAME = "CryoStackPilotExecution"
#: Log group / stream prefix the reviewed profile writes to.
PILOT_LOG_GROUP = "/cryostack/pilot"
PILOT_LOG_STREAM_PREFIX = "pilot"
#: SSM parameter path of per-reservation transfer capabilities.
PILOT_TRANSFER_PARAMETER_PREFIX = "/cryostack/pilot-transfer/"
#: ECR repositories the execution role may pull (the reviewed profile pins
#: an Icepack image; add the ISSM repository only once ISSM is qualified).
DEFAULT_PILOT_REPOSITORIES: tuple[str, ...] = ("cryostack-icepack",)

#: LEGACY: inline-policy name on a participant job role.
PARTICIPANT_STORAGE_POLICY_NAME = "CryoStackPilotParticipantStorage"

#: LEGACY: separate inline-policy name for the license-secret grant on a
#: shared (connected-account style) ECS execution role. The hosted route's
#: ``cryostack-pilot-execution`` role carries the grant in its own policy.
EXECUTION_ROLE_SECRET_POLICY_NAME = "CryoStackPilotLicenseSecrets"
#: The only model whose container receives a secret.
LICENSED_MODEL = "issm"

#: AWS limit on the plain-text size of an inline STS session policy.
SESSION_POLICY_MAX_CHARS = 2048

_ACCOUNT_ID_RE = re.compile(r"\A[0-9]{12}\Z")
_REGION_RE = re.compile(r"\A[a-z]{2}(?:-[a-z]+)+-[0-9]\Z")


class PilotScopeError(PermissionError):
    """An S3 location or secret is outside the participant's own scope."""


def _bucket(bucket: str) -> str:
    try:
        return _s3_bucket_name(bucket)
    except S3LocationError as err:
        raise ValueError(str(err)) from None


def _account(account_id: str) -> str:
    account = (account_id or "").strip()
    if not _ACCOUNT_ID_RE.match(account):
        raise ValueError("an AWS account id is exactly 12 digits")
    return account


def _region(region: str) -> str:
    name = (region or "").strip()
    if not _REGION_RE.match(name):
        raise ValueError("not an AWS region name")
    return name


def stream_prefix(user_id: str) -> str:
    """LEGACY -- not used by the hosted route (see the module docstring).

    ``awslogs-stream-prefix`` of a participant's job definitions.

    Putting the participant key first in the log-stream name lets the
    session policy scope ``logs:GetLogEvents`` to this participant's streams
    even though all participants share one log group per model.
    """
    return f"pilot-{participant_key(user_id)}"


def participant_job_role_arn(account_id: str, user_id: str) -> str:
    return f"arn:aws:iam::{_account(account_id)}:role/{participant_job_role_name(user_id)}"


# ── S3 statements shared by the job role and the session policy ──────────────
def _s3_statements(bucket: str, user_id: str) -> list[dict]:
    bucket_arn = f"arn:aws:s3:::{_bucket(bucket)}"
    prefix = participant_prefix(user_id)              # pilot/<key>/
    return [
        {
            "Sid": "PilotListOwnPrefix",
            "Effect": "Allow",
            "Action": "s3:ListBucket",
            "Resource": bucket_arn,
            "Condition": {"StringLike": {"s3:prefix": [prefix, f"{prefix}*"]}},
        },
        {
            "Sid": "PilotOwnObjects",
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
            "Resource": f"{bucket_arn}/{prefix}*",
        },
    ]


def participant_job_role_policy(bucket: str, user_id: str) -> dict:
    """LEGACY -- not used by the hosted route (see the module docstring).

    The ONLY permissions of one participant's Batch job role.

    * ``s3:GetObject`` / ``s3:PutObject`` / ``s3:DeleteObject`` on
      ``arn:aws:s3:::<bucket>/pilot/<key>/*``;
    * ``s3:ListBucket`` on the bucket, only for listings under
      ``pilot/<key>/``.

    Why ``ListBucket`` needs the condition: ``s3:ListBucket`` is a
    *bucket-level* action, so its ``Resource`` can only be the whole bucket
    ARN -- an object ARN such as ``.../pilot/<key>/*`` does not match it.
    Without a condition the role could list every key in the bucket,
    including other participants' run ids and file names. The ``s3:prefix``
    condition key holds the ``prefix`` parameter of the List request, so
    ``StringLike`` on ``pilot/<key>/*`` allows a listing only when the
    request itself is confined to this participant's prefix. A request with
    no prefix (or a shorter one such as ``pilot/``) carries no matching
    value and is denied.

    ``aws s3 sync`` (what the container runner uses for ``input/`` and
    ``outputs/``) lists with the full ``pilot/<key>/runs/<run-id>/...``
    prefix, which the ``*`` form covers. The bare ``pilot/<key>/`` is listed
    explicitly as well so the intent is visible to a reviewer; ``*`` already
    matches the empty string.

    There is deliberately no statement for logs, Batch, ECR, Secrets Manager
    or any other service: image pull, log writing and license-secret
    injection belong to the separate ECS execution role, which the
    participant's script cannot use. In particular the script cannot call
    ``secretsmanager:GetSecretValue`` for any secret, not even its own.
    """
    return {"Version": "2012-10-17", "Statement": _s3_statements(bucket, user_id)}


def participant_job_role_trust(account_id: str | None = None) -> dict:
    """Trust policy for a role assumed by ECS tasks only. Used for the pilot
    execution role (via :func:`pilot_execution_role_trust`) and for the
    LEGACY participant job role.

    With no ``account_id`` this equals the existing
    ``iam_policies.job_trust_policy()``. With one it adds the
    ``aws:SourceAccount`` confused-deputy condition from the reviewed
    execution-role trust template
    (``deployment/soft_launch/pilot_execution_review``), so only ECS tasks
    started in the pilot account itself can assume the role. Provisioning
    always passes the account id.
    """
    statement: dict = {
        "Effect": "Allow",
        "Principal": {"Service": "ecs-tasks.amazonaws.com"},
        "Action": "sts:AssumeRole",
    }
    if account_id is not None:
        statement["Condition"] = {
            "StringEquals": {"aws:SourceAccount": _account(account_id)}
        }
    return {"Version": "2012-10-17", "Statement": [statement]}


# ── per-participant MATLAB-license secret (hosted ISSM) ──────────────────────
#: Secrets Manager appends "-" and six random characters to the name.
_SECRET_SUFFIX_RE = re.compile(r"\A-[A-Za-z0-9]{6}\Z")


def _secret_in_scope(
    user_id: str, arn: str, *, account_id: str | None, region: str,
) -> bool:
    name = participant_secret_name(user_id)
    account = _account(account_id) if account_id is not None else None
    parts = arn.split(":", 6) if isinstance(arn, str) else []
    if len(parts) != 7:
        return False
    head, partition, service, where, owner, kind, resource = parts
    return (
        (head, partition, service, kind) == ("arn", "aws", "secretsmanager", "secret")
        and where == _region(region)
        and (account is None or owner == account)
        and bool(re.match(r"\A[0-9]{12}\Z", owner))
        and resource.startswith(name)
        and bool(_SECRET_SUFFIX_RE.match(resource[len(name):]))
    )


def assert_secret_scope(
    user_id: str,
    arn: str,
    *,
    account_id: str,
    region: str,
) -> str:
    """Return ``arn`` if it is THIS participant's MATLAB-license secret in
    the pilot account and Region; else raise :class:`PilotScopeError`.

    The ARN must be exactly
    ``arn:aws:secretsmanager:<region>:<account>:secret:cryostack/pilot/<key>/matlab-license-XXXXXX``
    (Secrets Manager's six-character suffix). Any other account, Region,
    participant key or secret name is refused, so one participant's job
    definition can never be pointed at another participant's license or at
    any other secret in the account. The message names neither the user nor
    the ARN.
    """
    if not _secret_in_scope(user_id, arn, account_id=_account(account_id), region=region):
        raise PilotScopeError("secret is not this participant's pilot license secret")
    return arn


def participant_secrets_block(
    user_id: str,
    secret_arn: str,
    *,
    account_id: str,
    region: str,
) -> list[dict]:
    """``containerProperties.secrets`` for a participant's ISSM job
    definition: ``[{"name": "MLM_LICENSE_FILE", "valueFrom": <their ARN>}]``.
    The same block the connected-account path builds
    (``CloudMatlabLicense.batch_secrets_block``), after the scope check."""
    arn = assert_secret_scope(user_id, secret_arn, account_id=account_id, region=region)
    return CloudMatlabLicense(
        configured=True, mechanism="secrets-manager", secret_arn=arn,
    ).batch_secrets_block()


def execution_role_secret_statement(account_id: str, region: str) -> dict:
    """The statement that lets the pilot ECS **execution** role read pilot
    participants' license secrets -- ``secretsmanager:GetSecretValue`` on
    ``cryostack/pilot/*`` in the pilot account and Region, nothing else.

    The execution role is used by the ECS agent to inject the value at
    launch; its credentials are never available inside the container. It is
    shared by all participants, so what keeps participant A from receiving
    participant B's license is that only CryoStack registers job
    definitions and every one is built through
    :func:`participant_job_definition_payload`, which refuses any secret but
    the participant's own. Participants must never be able to register or
    edit a job definition.
    """
    return {
        "Sid": "CryoStackPilotReadLicenseSecrets",
        "Effect": "Allow",
        "Action": "secretsmanager:GetSecretValue",
        "Resource": (
            f"arn:aws:secretsmanager:{_region(region)}:{_account(account_id)}:"
            f"secret:{PILOT_SECRET_PREFIX}*"
        ),
    }


def execution_role_secret_policy(account_id: str, region: str) -> dict:
    """LEGACY -- the hosted route's execution role carries this statement in
    :func:`pilot_execution_role_policy`.

    Inline policy document (:data:`EXECUTION_ROLE_SECRET_POLICY_NAME`)
    holding :func:`execution_role_secret_statement`. No KMS statement: the
    secrets use the Secrets Manager default AWS-managed key, as in the
    connected-account path."""
    return {
        "Version": "2012-10-17",
        "Statement": [execution_role_secret_statement(account_id, region)],
    }


# ── hosted route: no task role ───────────────────────────────────────────────
_RESERVATION_RE = re.compile(r"\A[a-f0-9]{32}\Z")
_REPOSITORY_RE = re.compile(r"\A[a-z0-9][a-z0-9._/-]{1,255}\Z")
#: Keys that would give a Batch job an AWS identity or a non-container shape.
_IDENTITY_KEYS = ("jobRoleArn", "taskRoleArn")
_FOREIGN_SHAPES = ("nodeProperties", "eksProperties", "ecsProperties")


def assert_no_task_role(definition: dict) -> dict:
    """Return ``definition`` if it gives the model task NO AWS identity;
    else raise :class:`PilotScopeError`.

    A hosted pilot job definition must be a plain container definition whose
    ``containerProperties`` has no ``jobRoleArn`` (not even an empty one) and
    does have an ``executionRoleArn`` named ``cryostack-pilot-execution``.
    Works on a definition about to be registered and on one returned by
    ``describe-job-definitions``.
    """
    if not isinstance(definition, dict):
        raise PilotScopeError("not a job definition")
    properties = definition.get("containerProperties")
    if not isinstance(properties, dict) or any(k in definition for k in _FOREIGN_SHAPES):
        raise PilotScopeError("a pilot job definition must be a plain container definition")
    if any(key in properties for key in _IDENTITY_KEYS):
        raise PilotScopeError("a pilot job definition must not carry a task (job) role")
    role = str(properties.get("executionRoleArn") or "")
    if not re.match(
        r"\Aarn:aws:iam::[0-9]{12}:role/" + PILOT_EXECUTION_ROLE_NAME + r"(?:-[A-Za-z0-9_-]+)?\Z",
        role,
    ):
        raise PilotScopeError("a pilot job definition must use the pilot execution role")
    return definition


def licensed_pilot_job_definition(
    definition: dict,
    *,
    user_id: str,
    matlab_secret_arn: str,
    account_id: str,
    region: str,
) -> dict:
    """A copy of a reviewed pilot job definition that also injects THIS
    participant's MATLAB license (``MLM_LICENSE_FILE``) for hosted ISSM.

    ``definition`` is the profile-built reservation definition; its
    per-reservation transfer capability stays in ``secrets`` and the license
    reference is added next to it. The ARN is scope-checked first, so one
    participant's definition can never reference another participant's
    secret, and a definition that already carries ``MLM_LICENSE_FILE`` is
    refused rather than overwritten. Still no task role.
    """
    assert_no_task_role(definition)
    block = participant_secrets_block(
        user_id, matlab_secret_arn, account_id=account_id, region=region)
    licensed = json.loads(json.dumps(definition))
    secrets = licensed["containerProperties"].setdefault("secrets", [])
    if any(isinstance(s, dict) and s.get("name") == MATLAB_LICENSE_ENV for s in secrets):
        raise PilotScopeError("the job definition already carries a license secret")
    secrets.extend(block)
    return licensed


def pilot_job_definition(
    profile,
    policy,
    *,
    reservation: str,
    user_id: str,
    run,
    transfer_parameter_arn: str,
    matlab_secret_arn: str | None = None,
) -> dict:
    """The ``RegisterJobDefinition`` request for one hosted pilot reservation.

    ``profile`` is the operator-reviewed ``PilotExecutionProfile`` and
    ``policy`` / ``run`` its ``FundingPolicy`` / ``FundedRun``. The definition
    is exactly ``profile.definition(...)`` -- name ``cryostack-pilot-<reservation>``,
    reviewed image, bootstrap command, bounds, tags, and the reservation's
    transfer capability as the SSM secret reference -- so the profile's own
    ``verify_definition`` accepts it. This function adds only the
    :func:`assert_no_task_role` check and, when ``matlab_secret_arn`` is
    given, the participant's own license secret.

    Whether a model is allowed at all is the profile's decision; it raises
    for anything it has not qualified.
    """
    definition = profile.definition(
        policy, reservation=reservation, user_id=user_id, run=run,
        transfer_parameter_arn=transfer_parameter_arn)
    assert_no_task_role(definition)
    if matlab_secret_arn:
        definition = licensed_pilot_job_definition(
            definition, user_id=user_id, matlab_secret_arn=matlab_secret_arn,
            account_id=profile.account_id, region=profile.region)
    return definition


def unlicensed_view(definition: dict, *, user_id: str, account_id: str, region: str) -> dict:
    """A copy of a (described) definition with this participant's OWN license
    secret entry removed, so the reviewed profile's verifier can check
    everything else. Any other ``MLM_LICENSE_FILE`` reference is refused."""
    view = json.loads(json.dumps(definition))
    properties = view.get("containerProperties") or {}
    kept = []
    for entry in properties.get("secrets") or []:
        if isinstance(entry, dict) and entry.get("name") == MATLAB_LICENSE_ENV:
            assert_secret_scope(
                user_id, entry.get("valueFrom"), account_id=account_id, region=region)
            continue
        kept.append(entry)
    if "secrets" in properties:
        properties["secrets"] = kept
    return view


def _repositories(repositories) -> list[str]:
    names = [repositories] if isinstance(repositories, str) else list(repositories or [])
    names = list(dict.fromkeys(str(name).strip() for name in names))
    if not names or not all(_REPOSITORY_RE.match(name) for name in names):
        raise ValueError("one or more ECR repository names are required")
    return names


def pilot_execution_role_trust(account_id: str) -> dict:
    """Trust policy of ``cryostack-pilot-execution``: ECS tasks of the pilot
    account only (the reviewed ``execution-role-trust.template.json``)."""
    return participant_job_role_trust(_account(account_id))


def pilot_execution_role_policy(
    account_id: str,
    region: str,
    *,
    repositories=DEFAULT_PILOT_REPOSITORIES,
) -> dict:
    """The only permissions of ``cryostack-pilot-execution``.

    The reviewed ``execution-role-policy.template.json`` with its slots
    filled, plus the license-secret read for hosted ISSM:

    * ECR: authorization token, and pull of the named repositories only;
    * Logs: create / write streams ``pilot/*`` in ``/cryostack/pilot`` only;
    * SSM: ``GetParameters`` under ``/cryostack/pilot-transfer/`` only;
    * Secrets Manager: ``GetSecretValue`` on ``cryostack/pilot/*`` only.

    No S3, IAM, Batch, KMS or STS action. This role is used by the ECS agent
    to start the container; the model inside never receives its credentials.
    """
    account, where = _account(account_id), _region(region)
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PullAuthorizationOnly",
                "Effect": "Allow",
                "Action": "ecr:GetAuthorizationToken",
                "Resource": "*",
            },
            {
                "Sid": "ReviewedImageRepositoryOnly",
                "Effect": "Allow",
                "Action": [
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                ],
                "Resource": [
                    f"arn:aws:ecr:{where}:{account}:repository/{name}"
                    for name in _repositories(repositories)
                ],
            },
            {
                "Sid": "PilotLogStreamsOnly",
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": (
                    f"arn:aws:logs:{where}:{account}:log-group:{PILOT_LOG_GROUP}"
                    f":log-stream:{PILOT_LOG_STREAM_PREFIX}/*"
                ),
            },
            {
                "Sid": "PilotTransferParametersOnly",
                "Effect": "Allow",
                "Action": "ssm:GetParameters",
                "Resource": (
                    f"arn:aws:ssm:{where}:{account}:parameter"
                    f"{PILOT_TRANSFER_PARAMETER_PREFIX}*"
                ),
            },
            execution_role_secret_statement(account, where),
        ],
    }


def gateway_base_role_policy(
    account_id: str,
    region: str,
    *,
    execution_role_name: str = PILOT_EXECUTION_ROLE_NAME,
    job_queue: str = JOB_QUEUE_NAME,
    result_bucket: str | None = None,
    result_prefix: str = "pilot-results/",
) -> dict:
    """The policy the operator attaches to the gateway's (broker's) own role
    in the pilot account. Printed for review by
    ``deployment/pilot/setup_pilot_account.py``; nothing attaches it
    automatically.

    * SSM: create / read / delete transfer parameters under
      ``/cryostack/pilot-transfer/`` only;
    * Batch: register / deregister ``cryostack-pilot-*`` job definitions,
      submit them to the one pilot queue, describe, and terminate only jobs
      tagged ``cryostack:pilot``;
    * IAM: ``PassRole`` for the pilot execution role to ECS tasks, nothing
      else -- the gateway cannot create or change any role or policy;
    * Secrets Manager: create / update / restore / delete participants'
      license secrets under ``cryostack/pilot/`` -- never read a value;
    * Logs: ``GetLogEvents`` in ``/cryostack/pilot`` only (the gateway
      checks a job's owner tag before reading its stream);
    * optionally (``result_bucket``) put / get result archives under the
      reviewed result prefix.

    No administrator or service-wide wildcard. ``Resource: "*"`` appears only
    where the action has no resource-level form (Batch describe calls, and
    ``CreateSecret`` which is bounded by its name condition instead).
    """
    account, where = _account(account_id), _region(region)
    if not re.match(r"\A[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z", job_queue or ""):
        raise ValueError("not an AWS Batch job queue name")
    if not re.match(r"\A[A-Za-z0-9+=,.@_-]{1,64}\Z", execution_role_name or ""):
        raise ValueError("not an IAM role name")
    batch = f"arn:aws:batch:{where}:{account}"
    definitions = f"{batch}:job-definition/{PILOT_NAME_PREFIX}*"
    secrets = f"arn:aws:secretsmanager:{where}:{account}:secret:{PILOT_SECRET_PREFIX}*"
    statements = [
        {
            "Sid": "PilotTransferParameters",
            "Effect": "Allow",
            "Action": ["ssm:PutParameter", "ssm:GetParameter", "ssm:DeleteParameter"],
            "Resource": (
                f"arn:aws:ssm:{where}:{account}:parameter{PILOT_TRANSFER_PARAMETER_PREFIX}*"
            ),
        },
        {
            "Sid": "PilotJobDefinitions",
            "Effect": "Allow",
            "Action": ["batch:RegisterJobDefinition", "batch:DeregisterJobDefinition"],
            "Resource": definitions,
        },
        {
            "Sid": "PilotSubmit",
            "Effect": "Allow",
            "Action": "batch:SubmitJob",
            "Resource": [definitions, f"{batch}:job-queue/{job_queue}"],
        },
        {
            "Sid": "PilotTagOnCreate",
            "Effect": "Allow",
            "Action": "batch:TagResource",
            "Resource": [definitions, f"{batch}:job/*"],
            "Condition": {"StringEquals": {f"aws:RequestTag/{TAG_PILOT}": "1"}},
        },
        {
            "Sid": "PilotDescribe",
            "Effect": "Allow",
            "Action": ["batch:DescribeJobs", "batch:DescribeJobDefinitions"],
            "Resource": "*",
        },
        {
            "Sid": "PilotTerminate",
            "Effect": "Allow",
            "Action": "batch:TerminateJob",
            "Resource": f"{batch}:job/*",
            "Condition": {"StringEquals": {f"aws:ResourceTag/{TAG_PILOT}": "1"}},
        },
        {
            "Sid": "PassPilotExecutionRoleOnly",
            "Effect": "Allow",
            "Action": "iam:PassRole",
            "Resource": f"arn:aws:iam::{account}:role/{execution_role_name}",
            "Condition": {"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}},
        },
        {
            "Sid": "PilotLicenseSecretCreate",
            "Effect": "Allow",
            "Action": "secretsmanager:CreateSecret",
            "Resource": "*",
            "Condition": {"StringLike": {"secretsmanager:Name": f"{PILOT_SECRET_PREFIX}*"}},
        },
        {
            "Sid": "PilotLicenseSecretManage",
            "Effect": "Allow",
            "Action": [
                "secretsmanager:PutSecretValue",
                "secretsmanager:RestoreSecret",
                "secretsmanager:DeleteSecret",
            ],
            "Resource": secrets,
        },
        {
            "Sid": "PilotLogsRead",
            "Effect": "Allow",
            "Action": "logs:GetLogEvents",
            "Resource": f"arn:aws:logs:{where}:{account}:log-group:{PILOT_LOG_GROUP}:log-stream:*",
        },
    ]
    if result_bucket:
        prefix = (result_prefix or "").strip()
        if not re.match(r"\A(?:[A-Za-z0-9_-]+/)+\Z", prefix):
            raise ValueError("the result prefix must be one or more 'name/' segments")
        statements.append({
            "Sid": "PilotResultArchives",
            "Effect": "Allow",
            "Action": ["s3:PutObject", "s3:GetObject"],
            "Resource": f"arn:aws:s3:::{_bucket(result_bucket)}/{prefix}*",
        })
    return {"Version": "2012-10-17", "Statement": statements}


# ═════════════════════════════════════════════════════════════════════════════
# LEGACY -- NOT USED BY THE HOSTED ROUTE
# Everything below gives the model task an AWS identity (a per-participant job
# role scoped to pilot/<key>/). Kept for reference and close-out only; see the
# module docstring.
# ═════════════════════════════════════════════════════════════════════════════

# ── per-participant job definition ───────────────────────────────────────────
def participant_container_properties(
    base: dict,
    *,
    user_id: str,
    account_id: str,
    region: str,
) -> dict:
    """LEGACY -- not used by the hosted route (see the module docstring).

    The per-participant variant of an existing ``containerProperties``.

    ``base`` is the output of ``batch_config.container_properties_payload``
    for the model. Image, command, resources, network, storage, platform and
    log group are kept; only two things change:

    * ``jobRoleArn`` becomes this participant's own role;
    * ``awslogs-stream-prefix`` becomes ``pilot-<key>`` (see
      :func:`stream_prefix`).

    A secret delivered into the container is readable by the participant's
    own script, so the only ``secrets`` entry accepted in ``base`` is
    ``MLM_LICENSE_FILE`` from this participant's OWN license secret
    (:func:`assert_secret_scope`). Anything else -- another participant's
    secret, any other secret, any other variable name -- is refused.
    """
    if not isinstance(base, dict) or not base.get("image"):
        raise ValueError("a participant job definition needs base container properties")
    secrets = base.get("secrets") or []
    if len(secrets) > 1:
        raise PilotScopeError("a pilot job definition may carry one license secret at most")
    for entry in secrets:
        if not isinstance(entry, dict) or entry.get("name") != MATLAB_LICENSE_ENV:
            raise PilotScopeError("a pilot job definition may only inject the license secret")
        assert_secret_scope(
            user_id, entry.get("valueFrom"), account_id=account_id, region=region)
    properties = json.loads(json.dumps(base))           # deep copy, JSON-safe
    properties["jobRoleArn"] = participant_job_role_arn(account_id, user_id)
    log = properties.setdefault("logConfiguration", {})
    log.setdefault("options", {})["awslogs-stream-prefix"] = stream_prefix(user_id)
    return properties


def participant_job_definition_payload(
    *,
    user_id: str,
    model: str,
    image: str,
    execution_role_arn: str,
    account_id: str,
    region: str,
    job_config: FargateJobConfig = DEFAULT_ISSM_JOB_CONFIG,
    command: list[str] | None = None,
    matlab_secret_arn: str | None = None,
) -> dict:
    """LEGACY -- not used by the hosted route (see the module docstring).

    The complete ``RegisterJobDefinition`` request for one participant.

    Built from the existing Fargate builder so the task shape (image,
    command, vCPU / memory, ephemeral storage, platform, timeout, attempts)
    is identical to the connected-account job definition for the model. The
    participant-specific parts are the name, the job role, the log-stream
    prefix and the tags. ``propagateTags`` asks Batch to copy the tags onto
    the ECS task so cost reports can be grouped by participant.

    ``matlab_secret_arn`` (ISSM only) adds the ``secrets`` block for this
    participant's own license secret; it is scope-checked first and refused
    for any other model.
    """
    model = normalize_model(model)
    secrets = None
    if matlab_secret_arn:
        if model != LICENSED_MODEL:
            raise PilotScopeError("only the ISSM job definition may carry a license secret")
        secrets = participant_secrets_block(
            user_id, matlab_secret_arn, account_id=account_id, region=region)
    base = container_properties_payload(
        model=model,
        image=image,
        # replaced below; the existing builder requires a non-empty value
        job_role_arn=participant_job_role_arn(account_id, user_id),
        execution_role_arn=execution_role_arn,
        region=_region(region),
        config=job_config,
        command=command,
        secrets=secrets,
    )
    return {
        "jobDefinitionName": participant_job_definition_name(user_id, model),
        "type": "container",
        "platformCapabilities": ["FARGATE"],
        "containerProperties": participant_container_properties(
            base, user_id=user_id, account_id=account_id, region=region),
        "timeout": {"attemptDurationSeconds": int(job_config.timeout_seconds)},
        "retryStrategy": {"attempts": int(job_config.attempts)},
        "tags": participant_tags(user_id, model=model),
        "propagateTags": True,
    }


# ── scope check ──────────────────────────────────────────────────────────────
def assert_run_scope(
    user_id: str,
    s3_uri_or_key: str,
    *,
    bucket: str | None = None,
) -> str:
    """LEGACY -- not used by the hosted route (see the module docstring).

    Return the object key if it lies inside ``pilot/<key>/``; else raise.

    Accepts an ``s3://bucket/key`` URI or a bare key. The gateway calls this
    before every S3, log, status or terminate operation it performs for a
    participant, with a location that came from stored state or a request.
    With ``bucket`` given, a URI naming any other bucket is refused too.

    The check is textual and strict: no leading ``/``, no empty, ``.`` or
    ``..`` segments, no backslash or control characters. S3 keys are opaque
    strings, so anything that only *normalises* into the prefix is treated as
    outside it. :class:`PilotScopeError` messages name neither the user nor
    the offending location.
    """
    prefix = participant_prefix(user_id)
    raw = s3_uri_or_key if isinstance(s3_uri_or_key, str) else ""
    key = raw
    if raw[:5].lower() == "s3://":
        uri_bucket, _, key = raw[5:].partition("/")
        if not uri_bucket:
            raise PilotScopeError("S3 location is outside the participant's pilot prefix")
        if bucket is not None and uri_bucket != _bucket(bucket):
            raise PilotScopeError("S3 location is not in the pilot bucket")
    elif "://" in raw:
        raise PilotScopeError("S3 location is outside the participant's pilot prefix")

    segments = key.split("/")
    body = segments[:-1] if key.endswith("/") else segments   # allow one trailing "/"
    bad = (
        not key.startswith(prefix)
        or "\\" in key
        or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in key)
        or any(seg in ("", ".", "..") for seg in body)
    )
    if bad:
        raise PilotScopeError("S3 location is outside the participant's pilot prefix")
    return key


# ── gateway session policy ───────────────────────────────────────────────────
def session_policy_for_participant(
    bucket: str,
    user_id: str,
    *,
    account_id: str | None = None,
    region: str | None = None,
    job_queue: str = JOB_QUEUE_NAME,
) -> dict:
    """LEGACY -- not used by the hosted route (see the module docstring).

    Inline STS session policy narrowing the gateway to ONE participant.

    Pass it as ``--policy`` when the gateway assumes its pilot-account role
    to act for a participant. A session policy can only remove permissions:
    the result is the intersection of this document and the role's own
    policies, so the role must already allow each action below.

    * S3: the same two statements as the participant's job role;
    * ``batch:SubmitJob`` only with this participant's job definitions
      (``cryostack-pilot-<key>-*``) on the pilot queue;
    * ``batch:DescribeJobs`` on ``*`` -- it has no resource-level form, so
      the gateway must still check the returned job's
      ``cryostack:participant`` tag before showing anything;
    * ``batch:TerminateJob`` / ``batch:CancelJob`` only on jobs tagged with
      this participant's key (the gateway must submit with ``job_tags``);
    * ``logs:GetLogEvents`` only on streams named ``pilot-<key>/...`` in the
      CryoStack Batch log groups.

    ``account_id`` / ``region`` narrow the Batch and Logs ARNs further; left
    out they are ``*``, which is safe here because the role's own policy
    still bounds the session. Compact JSON stays well under
    :data:`SESSION_POLICY_MAX_CHARS`; :func:`session_policy_json` enforces it.
    """
    key = participant_key(user_id)
    account = _account(account_id) if account_id is not None else "*"
    where = _region(region) if region is not None else "*"
    if not re.match(r"\A[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z", job_queue or ""):
        raise ValueError("not an AWS Batch job queue name")
    batch = f"arn:aws:batch:{where}:{account}"
    return {
        "Version": "2012-10-17",
        "Statement": [
            *_s3_statements(bucket, user_id),
            {
                "Sid": "PilotSubmitOwnDefinitions",
                "Effect": "Allow",
                "Action": "batch:SubmitJob",
                "Resource": [
                    f"{batch}:job-definition/{PILOT_NAME_PREFIX}{key}-*",
                    f"{batch}:job-queue/{job_queue}",
                ],
            },
            {
                "Sid": "PilotDescribeJobs",
                "Effect": "Allow",
                "Action": "batch:DescribeJobs",
                "Resource": "*",
            },
            {
                "Sid": "PilotStopOwnJobs",
                "Effect": "Allow",
                "Action": ["batch:TerminateJob", "batch:CancelJob"],
                "Resource": f"{batch}:job/*",
                "Condition": {
                    "StringEquals": {f"aws:ResourceTag/{TAG_PARTICIPANT}": key}
                },
            },
            {
                "Sid": "PilotReadOwnLogs",
                "Effect": "Allow",
                "Action": "logs:GetLogEvents",
                "Resource": (
                    f"arn:aws:logs:{where}:{account}:log-group:"
                    f"{LOG_GROUP_PREFIX}/*:log-stream:{stream_prefix(user_id)}/*"
                ),
            },
        ],
    }


def session_policy_json(policy: dict) -> str:
    """Compact JSON for ``sts assume-role --policy``; raises if too large."""
    text = json.dumps(policy, separators=(",", ":"), sort_keys=True)
    if len(text) > SESSION_POLICY_MAX_CHARS:
        raise ValueError(
            f"session policy is {len(text)} characters; the AWS limit is "
            f"{SESSION_POLICY_MAX_CHARS}")
    return text
