# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Hosted Pilot Participant Provisioning
# File        : provision.py
#
# Description :
#     Idempotently creates, reconciles and removes the per-participant IAM
#     job role and AWS Batch job definitions in the hosted pilot account.
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
AWS resources of the CryoStack hosted pilot that the gateway manages.

The hosted route gives the model task NO AWS identity (see ``isolation.py``).
What the gateway provisions at run time is therefore small:

* :func:`ensure_pilot_job_definition` -- registers the reviewed, per-reservation
  job definition (no ``jobRoleArn``) and returns the ARN of the exact revision
  after the reviewed profile's own verifier has accepted what AWS stored;
* :func:`ensure_participant_secret` -- a participant's own MATLAB-license
  secret ``cryostack/pilot/<key>/matlab-license`` (hosted ISSM);
* :func:`remove_reservation_resources` / :func:`remove_participant_resources`
  -- clean-up.

The dedicated execution role, the pilot log group and the account guardrails
are created by the OPERATOR with ``deployment/pilot/setup_pilot_account.py``;
the gateway has no permission to create or change a role.

The license VALUE is handled by :func:`ensure_participant_secret` alone, the
same way ``drivers/aws/secrets.py`` does: it goes to the AWS CLI on stdin
(``--secret-string file:///dev/stdin``), never argv, an environment variable
or a temp file, and is never logged, returned or put in an exception.

LEGACY, NOT USED BY THE HOSTED ROUTE: :func:`ensure_participant_resources`
(a per-participant job role plus job definitions that pin it) and
:func:`ensure_execution_role_secret_access`. The first refuses to run unless
``legacy_task_role=True`` is passed explicitly. Close-out still removes such
resources if they exist.

``aws`` is an injectable ``callable(args: list[str]) -> (code, out, err)``
(default: the driver's ``run_aws`` with ``config``) so tests never touch AWS.
For :func:`ensure_participant_secret` it must also accept ``input=<str>``.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping
from urllib.parse import unquote

from cryostack_src.cloud.drivers.aws.auth import run_aws
from cryostack_src.cloud.drivers.aws.batch_config import (
    DEFAULT_ISSM_JOB_CONFIG,
    FargateJobConfig,
    job_definition_fingerprint,
)
from cryostack_src.cloud.drivers.aws.models import AWSConfig

from .identity import (
    PILOT_NAME_PREFIX,
    normalize_model,
    participant_job_role_name,
    participant_key,
    participant_secret_name,
)
from .isolation import (
    EXECUTION_ROLE_SECRET_POLICY_NAME,
    PILOT_TRANSFER_PARAMETER_PREFIX,
    assert_no_task_role,
    pilot_job_definition,
    unlicensed_view,
    LICENSED_MODEL,
    PARTICIPANT_STORAGE_POLICY_NAME,
    PilotScopeError,
    _secret_in_scope,
    assert_secret_scope,
    execution_role_secret_policy,
    participant_job_definition_payload,
    participant_job_role_arn,
    participant_job_role_policy,
    participant_job_role_trust,
)

AwsRunner = Callable[[list[str]], tuple[int, str, str]]

DEFAULT_PILOT_MODELS: tuple[str, ...] = ("icepack", "issm")

#: Days a removed participant's license secret stays recoverable (AWS
#: allows 7-30).
SECRET_RECOVERY_WINDOW_DAYS = 7

#: A role created a moment ago may not be visible to the next IAM call yet.
IAM_RETRY_ATTEMPTS = 5
IAM_RETRY_INTERVAL_SECONDS = 3.0


class PilotProvisionError(RuntimeError):
    """Participant resources could not be brought to the reviewed state."""


@dataclass
class PilotParticipantResources:
    """What :func:`ensure_participant_resources` found or made."""

    participant: str                       # the participant key, never a user id
    role_name: str
    role_arn: str
    #: model -> job-definition name / ``arn:...:job-definition/<name>:<rev>``.
    #: Submit with the ARN so a run uses exactly the revision verified here.
    job_definition_names: dict[str, str] = field(default_factory=dict)
    job_definition_arns: dict[str, str] = field(default_factory=dict)
    created: list[str] = field(default_factory=list)
    reused: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    #: model -> plain reason it was not provisioned (e.g. ISSM with no
    #: license secret configured). Not an error.
    skipped: dict[str, str] = field(default_factory=dict)


@dataclass
class PilotJobDefinition:
    """What :func:`ensure_pilot_job_definition` registered or found."""

    name: str
    #: ``arn:...:job-definition/<name>:<revision>`` -- submit exactly this.
    arn: str
    created: bool


@dataclass
class PilotParticipantRemoval:
    """What :func:`remove_participant_resources` removed or found absent."""

    participant: str
    removed: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)


def _runner(config: AWSConfig, aws: AwsRunner | None) -> AwsRunner:
    return aws or (lambda args: run_aws(config, args))


def _text(stdout: str, stderr: str) -> str:
    return (stderr or stdout or "").strip()


def _missing(stdout: str, stderr: str) -> bool:
    blob = _text(stdout, stderr).lower()
    return "nosuchentity" in blob or "cannot be found" in blob


def _require(code: int, stdout: str, stderr: str, *, what: str) -> dict:
    if code != 0:
        raise PilotProvisionError(_text(stdout, stderr) or f"{what} failed.")
    try:
        return json.loads(stdout or "{}")
    except ValueError:
        raise PilotProvisionError(f"{what} returned unreadable output.") from None


def _document(value) -> dict:
    """An IAM policy document as a dict. The AWS CLI already decodes it; the
    raw API form (URL-encoded JSON text) is accepted too."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(unquote(value))
        except ValueError:
            return {}
    return {}


def _canonical(value):
    """Order-insensitive form for comparing policy documents: single-item
    lists equal their bare item, and list order does not matter."""
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        items = sorted((_canonical(item) for item in value),
                       key=lambda item: json.dumps(item, sort_keys=True))
        return items[0] if len(items) == 1 else items
    return value


def _same_document(left: dict, right: dict) -> bool:
    return _canonical(left) == _canonical(right)


# ── hosted route: reviewed job definition, no task role ──────────────────────
def ensure_pilot_job_definition(
    config: AWSConfig,
    profile,
    policy,
    *,
    reservation: str,
    user_id: str,
    run,
    transfer_parameter_arn: str,
    matlab_secret_arn: str | None = None,
    aws: AwsRunner | None = None,
) -> PilotJobDefinition:
    """Register the reviewed job definition of one reservation (or reuse the
    one already registered) and return its verified revision ARN.

    The request is ``isolation.pilot_job_definition(...)``, i.e. exactly what
    the reviewed ``PilotExecutionProfile`` builds, with no ``jobRoleArn``.
    The same sequence as ``PilotSubmissionBroker.submit``: register, check
    the returned name / revision, describe that one revision, and let
    ``profile.verified_definition_arn`` accept or refuse what AWS stored.
    The described definition is handed to the verifier unmodified (apart
    from setting aside the participant's own license secret, which the
    profile does not know about). A definition that already exists but does
    not verify is refused, never replaced.

    The transfer parameter must already exist; this function does not create
    it and never sees the capability value.
    """
    invoke = _runner(config, aws)
    if config.region != profile.region:
        raise PilotProvisionError("the AWS session region differs from the execution review")
    binding = dict(reservation=reservation, user_id=user_id, run=run,
                   transfer_parameter_arn=transfer_parameter_arn)
    definition = pilot_job_definition(
        profile, policy, matlab_secret_arn=matlab_secret_arn or None, **binding)
    name = definition["jobDefinitionName"]
    prefix = (f"arn:aws:batch:{profile.region}:{profile.account_id}:"
              f"job-definition/{name}:")

    def verified(described: dict) -> str:
        try:
            assert_no_task_role(described)
            view = described
            if matlab_secret_arn:
                wanted = sorted(
                    (s.get("name"), s.get("valueFrom"))
                    for s in definition["containerProperties"]["secrets"])
                found = sorted(
                    (s.get("name"), s.get("valueFrom"))
                    for s in (described.get("containerProperties") or {}).get("secrets") or []
                    if isinstance(s, dict))
                if found != wanted:
                    raise PermissionError("secrets differ")
                view = unlicensed_view(
                    described, user_id=user_id,
                    account_id=profile.account_id, region=profile.region)
            return profile.verified_definition_arn(view, policy, **binding)
        except PermissionError:
            raise PilotProvisionError(
                f"job definition {name} differs from the execution review") from None

    active = _active_definitions(invoke, name)
    if active:
        if len(active) != 1:
            raise PilotProvisionError(
                f"job definition {name} has more than one active revision; reconcile first")
        return PilotJobDefinition(name=name, arn=verified(active[0]), created=False)

    code, out, err = invoke([
        "batch", "register-job-definition",
        "--cli-input-json", json.dumps(definition, separators=(",", ":"), sort_keys=True),
    ])
    registered = _require(code, out, err, what="batch register-job-definition")
    arn, revision = registered.get("jobDefinitionArn"), registered.get("revision")
    if type(revision) is not int or revision < 1 or arn != f"{prefix}{revision}":
        raise PilotProvisionError(
            "registration result differs from the reviewed account, name or revision")
    code, out, err = invoke(["batch", "describe-job-definitions", "--job-definitions", arn])
    described = _require(
        code, out, err, what="batch describe-job-definitions").get("jobDefinitions") or []
    if len(described) != 1:
        raise PilotProvisionError("one authoritative job-definition revision is required")
    return PilotJobDefinition(name=name, arn=verified(described[0]), created=True)


def remove_reservation_resources(
    config: AWSConfig,
    *,
    reservation: str,
    aws: AwsRunner | None = None,
) -> list[str]:
    """Clean up after a reservation that has reached a terminal state:
    deregister its job definition and delete its transfer parameter.
    Idempotent; returns what was removed. Call it only after the job is
    confirmed finished -- a queued job needs both to start."""
    if not isinstance(reservation, str) or not re.match(r"\A[a-f0-9]{32}\Z", reservation):
        raise ValueError("canonical reservation identifier required")
    invoke = _runner(config, aws)
    removed: list[str] = []
    for definition in _active_definitions(invoke, f"{PILOT_NAME_PREFIX}{reservation}"):
        _deregister(invoke, definition)
        removed.append(f"job_definition:{definition.get('revision')}")
    code, out, err = invoke([
        "ssm", "delete-parameter",
        "--name", f"{PILOT_TRANSFER_PARAMETER_PREFIX}{reservation}"])
    if code == 0:
        removed.append("transfer_parameter")
    elif "parameternotfound" not in _text(out, err).lower():
        raise PilotProvisionError(_text(out, err) or "ssm delete-parameter failed.")
    return removed


# ═════════════════════════════════════════════════════════════════════════════
# LEGACY task-role path -- NOT USED BY THE HOSTED ROUTE (see module docstring)
# ═════════════════════════════════════════════════════════════════════════════

# ── IAM job role ─────────────────────────────────────────────────────────────
def _ensure_job_role(
    aws: AwsRunner,
    *,
    user_id: str,
    bucket: str,
    account_id: str,
    result: PilotParticipantResources,
    sleep: Callable[[float], None],
) -> None:
    name = result.role_name
    trust = participant_job_role_trust(account_id)
    policy = participant_job_role_policy(bucket, user_id)

    code, out, err = aws(["iam", "get-role", "--role-name", name])
    if code != 0 and not _missing(out, err):
        raise PilotProvisionError(_text(out, err) or "iam get-role failed.")

    if code != 0:
        code, out, err = aws([
            "iam", "create-role",
            "--role-name", name,
            "--assume-role-policy-document", json.dumps(trust),
            "--description", "CryoStack hosted pilot participant job role",
        ])
        if code != 0 and "EntityAlreadyExists" not in _text(out, err):
            raise PilotProvisionError(_text(out, err) or "iam create-role failed.")
        created_now = code == 0
        (result.created if created_now else result.reused).append("job_role")
    else:
        created_now = False
        role = json.loads(out or "{}").get("Role") or {}
        if not _same_document(_document(role.get("AssumeRolePolicyDocument")), trust):
            code, out, err = aws([
                "iam", "update-assume-role-policy",
                "--role-name", name,
                "--policy-document", json.dumps(trust),
            ])
            _require(code, out, err, what="iam update-assume-role-policy")
            result.updated.append("job_role:trust")
        result.reused.append("job_role")

    if not created_now:
        _refuse_extra_policies(aws, name)
        code, out, err = aws([
            "iam", "get-role-policy",
            "--role-name", name,
            "--policy-name", PARTICIPANT_STORAGE_POLICY_NAME,
        ])
        if code != 0 and not _missing(out, err):
            raise PilotProvisionError(_text(out, err) or "iam get-role-policy failed.")
        if code == 0 and _same_document(
            _document(json.loads(out or "{}").get("PolicyDocument")), policy
        ):
            return
        result.updated.append("job_role:storage_policy")

    put = [
        "iam", "put-role-policy",
        "--role-name", name,
        "--policy-name", PARTICIPANT_STORAGE_POLICY_NAME,
        "--policy-document", json.dumps(policy),
    ]
    for attempt in range(IAM_RETRY_ATTEMPTS):
        code, out, err = aws(put)
        # only a just-created role may legitimately be "not found" for a moment
        if code == 0 or not (created_now and _missing(out, err)):
            break
        if attempt < IAM_RETRY_ATTEMPTS - 1:
            sleep(IAM_RETRY_INTERVAL_SECONDS)
    _require(code, out, err, what="iam put-role-policy")


def _refuse_extra_policies(aws: AwsRunner, role_name: str) -> None:
    """Fail closed if an existing participant role carries anything beyond
    the one reviewed inline policy. Nothing is deleted automatically."""
    code, out, err = aws(["iam", "list-role-policies", "--role-name", role_name])
    inline = _require(code, out, err, what="iam list-role-policies").get("PolicyNames") or []
    code, out, err = aws(["iam", "list-attached-role-policies", "--role-name", role_name])
    attached = _require(
        code, out, err, what="iam list-attached-role-policies"
    ).get("AttachedPolicies") or []
    extra = [n for n in inline if n != PARTICIPANT_STORAGE_POLICY_NAME]
    if extra or attached:
        raise PilotProvisionError(
            f"participant role {role_name} has {len(extra)} unexpected inline and "
            f"{len(attached)} attached policies; review and remove them before "
            "this participant can run")


# ── Batch job definitions ────────────────────────────────────────────────────
def _definition_fingerprint(definition: dict) -> dict:
    properties = definition.get("containerProperties") or {}
    fingerprint = job_definition_fingerprint(
        container_properties=properties,
        timeout_seconds=int((definition.get("timeout") or {}).get("attemptDurationSeconds", 0)),
        attempts=int((definition.get("retryStrategy") or {}).get("attempts", 1)),
    )
    options = (properties.get("logConfiguration") or {}).get("options") or {}
    fingerprint["logStreamPrefix"] = options.get("awslogs-stream-prefix")
    fingerprint["logRegion"] = options.get("awslogs-region")
    runtime = properties.get("runtimePlatform") or {}
    fingerprint["runtimePlatform"] = (
        runtime.get("cpuArchitecture"), runtime.get("operatingSystemFamily"))
    fingerprint["platformCapabilities"] = sorted(definition.get("platformCapabilities") or [])
    fingerprint["tags"] = dict(sorted((definition.get("tags") or {}).items()))
    fingerprint["propagateTags"] = bool(definition.get("propagateTags"))
    return fingerprint


def _active_definitions(aws: AwsRunner, name: str | None = None) -> list[dict]:
    args = ["batch", "describe-job-definitions", "--status", "ACTIVE"]
    if name:
        args += ["--job-definition-name", name]
    code, out, err = aws(args)
    found = _require(code, out, err, what="batch describe-job-definitions")
    return sorted(
        found.get("jobDefinitions") or [],
        key=lambda item: int(item.get("revision", 0)), reverse=True,
    )


def _deregister(aws: AwsRunner, definition: dict) -> None:
    target = definition.get("jobDefinitionArn") or (
        f"{definition.get('jobDefinitionName')}:{definition.get('revision')}")
    code, out, err = aws(["batch", "deregister-job-definition", "--job-definition", target])
    _require(code, out, err, what="batch deregister-job-definition")


def _ensure_job_definition(
    aws: AwsRunner,
    payload: dict,
    *,
    model: str,
    result: PilotParticipantResources,
) -> None:
    name = payload["jobDefinitionName"]
    desired = _definition_fingerprint(payload)
    active = _active_definitions(aws, name)
    label = f"job_definition:{model}"

    keep = active[0] if active and _definition_fingerprint(active[0]) == desired else None
    if keep is not None:
        arn = keep.get("jobDefinitionArn") or ""
        result.reused.append(label)
        stale = active[1:]
    else:
        args = [
            "batch", "register-job-definition",
            "--job-definition-name", name,
            "--type", payload["type"],
            "--platform-capabilities", *payload["platformCapabilities"],
            "--container-properties", json.dumps(payload["containerProperties"]),
            "--timeout", json.dumps(payload["timeout"]),
            "--retry-strategy", json.dumps(payload["retryStrategy"]),
            "--tags", json.dumps(payload["tags"]),
            "--propagate-tags",
        ]
        code, out, err = aws(args)
        arn = _require(
            code, out, err, what="batch register-job-definition"
        ).get("jobDefinitionArn") or ""
        (result.updated if active else result.created).append(label)
        stale = active

    if not arn:
        raise PilotProvisionError(f"could not determine the job-definition ARN for {name}")
    # A superseded revision may pin an older image, role or shape; leave
    # exactly one ACTIVE revision so a submit by name cannot pick it up.
    for old in stale:
        _deregister(aws, old)
    result.job_definition_names[model] = name
    result.job_definition_arns[model] = arn


# ── MATLAB-license secret (hosted ISSM) ──────────────────────────────────────
def _scrub(text: str, value: str) -> str:
    """Bounded error text with the license value removed. The value is never
    on argv, so the CLI cannot echo it; this is defence in depth."""
    clean = text or ""
    for secret in {value, value.strip()}:
        if secret:
            clean = clean.replace(secret, "[redacted]")
    return clean.strip()[:500]


def ensure_participant_secret(
    config: AWSConfig,
    *,
    user_id: str,
    value: str,
    account_id: str | None = None,
    aws: Callable[..., tuple[int, str, str]] | None = None,
) -> str:
    """Create, or update in place, this participant's MATLAB-license secret
    and return ONLY its ARN.

    ``value`` is the plaintext ``MLM_LICENSE_FILE`` string, held in memory
    only. It is passed to the AWS CLI on stdin exactly as
    ``secrets.py::create_matlab_license_secret`` does and appears in no
    argument, log line, exception or return value. The secret name is fixed
    by the participant key, so a caller cannot write to any other secret.

    * no secret yet                -> ``create-secret``;
    * the secret already exists    -> ``put-secret-value`` (new version);
    * it is scheduled for deletion -> ``restore-secret``, then
      ``put-secret-value``.

    The returned ARN is checked to be this participant's secret in
    ``config.region`` (and ``account_id`` when given) before it is returned.
    """
    name = participant_secret_name(user_id)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A license value is required.")
    invoke = aws or (
        lambda args, input=None: run_aws(config, args, input=input))

    def fail(out: str, err: str, what: str) -> PilotProvisionError:
        return PilotProvisionError(
            _scrub(err or out, value) or f"AWS Secrets Manager {what} failed.")

    def put() -> tuple[int, str, str]:
        return invoke([
            "secretsmanager", "put-secret-value",
            "--secret-id", name,
            "--secret-string", "file:///dev/stdin",
            "--output", "json",
        ], input=value)

    code, out, err = invoke([
        "secretsmanager", "create-secret",
        "--name", name,
        "--secret-string", "file:///dev/stdin",
        "--output", "json",
    ], input=value)
    if code != 0:
        text = (err or out or "")
        pending_delete = "scheduled for deletion" in text.lower()
        if "ResourceExistsException" not in text and not pending_delete:
            raise fail(out, err, "create-secret")
        if not pending_delete:
            code, out, err = put()
            pending_delete = code != 0 and "scheduled for deletion" in (err or out or "").lower()
        if pending_delete:
            code, out, err = invoke(["secretsmanager", "restore-secret", "--secret-id", name])
            if code != 0:
                raise fail(out, err, "restore-secret")
            code, out, err = put()
        if code != 0:
            raise fail(out, err, "put-secret-value")

    try:
        arn = str(json.loads(out or "{}").get("ARN") or "").strip()
    except ValueError:
        arn = ""
    if not arn or not _secret_in_scope(
        user_id, arn, account_id=account_id, region=config.region
    ):
        raise PilotProvisionError(
            "AWS Secrets Manager did not return this participant's secret ARN.")
    return arn


def ensure_execution_role_secret_access(
    config: AWSConfig,
    *,
    execution_role_name: str,
    account_id: str,
    aws: AwsRunner | None = None,
) -> str:
    """LEGACY -- not used by the hosted route: ``cryostack-pilot-execution``
    gets this permission in its own policy from the operator tool, and the
    gateway role cannot change role policies.

    Give a shared ECS execution role its one Secrets Manager permission
    (``GetSecretValue`` on ``cryostack/pilot/*``) as a separately named
    inline policy. Account-wide, needed once before the first hosted ISSM
    run. Returns ``created`` / ``updated`` / ``reused``."""
    invoke = _runner(config, aws)
    policy = execution_role_secret_policy(account_id, config.region)
    code, out, err = invoke([
        "iam", "get-role-policy",
        "--role-name", execution_role_name,
        "--policy-name", EXECUTION_ROLE_SECRET_POLICY_NAME,
    ])
    if code != 0 and not _missing(out, err):
        raise PilotProvisionError(_text(out, err) or "iam get-role-policy failed.")
    existed = code == 0
    if existed and _same_document(
        _document(json.loads(out or "{}").get("PolicyDocument")), policy
    ):
        return "reused"
    code, out, err = invoke([
        "iam", "put-role-policy",
        "--role-name", execution_role_name,
        "--policy-name", EXECUTION_ROLE_SECRET_POLICY_NAME,
        "--policy-document", json.dumps(policy),
    ])
    _require(code, out, err, what="iam put-role-policy")
    return "updated" if existed else "created"


def _image(image_for_model, model: str) -> str:
    image = (
        image_for_model(model) if callable(image_for_model)
        else (image_for_model or {}).get(model)
    )
    if not isinstance(image, str) or not image.strip():
        raise PilotProvisionError(f"no container image is configured for pilot model {model}")
    return image.strip()


def ensure_participant_resources(
    config: AWSConfig,
    *,
    user_id: str,
    models: Iterable[str] = DEFAULT_PILOT_MODELS,
    bucket: str,
    account_id: str,
    execution_role_arn: str,
    image_for_model: Mapping[str, str] | Callable[[str], str],
    job_config_for_model: Mapping[str, FargateJobConfig] | None = None,
    command: list[str] | None = None,
    matlab_secret_arn: str | None = None,
    legacy_task_role: bool = False,
    aws: AwsRunner | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> PilotParticipantResources:
    """LEGACY -- NOT USED BY THE HOSTED ROUTE. Gives the model task an AWS
    identity (a per-participant job role scoped to ``pilot/<key>/``). The
    hosted route uses :func:`ensure_pilot_job_definition`, which has no task
    role at all. This function refuses to do anything unless
    ``legacy_task_role=True`` is passed explicitly.

    Ensure one participant's job role and job definitions exist and match
    the reviewed shape. Idempotent; returns what was created, reused or
    updated.

    ``image_for_model`` maps a model to its image reference (a mapping or a
    callable). ``job_config_for_model`` optionally overrides the default
    Fargate task shape per model. ``command`` is the container command baked
    into the definitions (the same one the connected-account path uses).

    ``matlab_secret_arn`` is this participant's own license secret (from
    :func:`ensure_participant_secret`); it is scope-checked and goes only
    into the ISSM job definition. Without it ISSM is skipped and reported in
    ``skipped`` -- the other models are still provisioned. An ISSM job
    definition left from an earlier call is not touched by a skip.

    Every desired document is built and validated BEFORE the first AWS call,
    so a bad argument never leaves a half-provisioned participant.
    """
    if legacy_task_role is not True:
        raise PilotProvisionError(
            "the hosted pilot route gives model tasks no AWS role; per-participant "
            "job roles are legacy and need legacy_task_role=True")
    invoke = _runner(config, aws)
    wanted = list(dict.fromkeys(normalize_model(m) for m in models))
    if not wanted:
        raise PilotProvisionError("at least one pilot model is required")

    result = PilotParticipantResources(
        participant=participant_key(user_id),
        role_name=participant_job_role_name(user_id),
        role_arn=participant_job_role_arn(account_id, user_id),
    )
    secret_arn = (matlab_secret_arn or "").strip()
    if secret_arn:
        try:
            assert_secret_scope(
                user_id, secret_arn, account_id=account_id, region=config.region)
        except PilotScopeError:
            raise PilotProvisionError(
                "the MATLAB license secret is not this participant's pilot secret"
            ) from None
    payloads: dict[str, dict] = {}
    for model in wanted:
        licensed = model == LICENSED_MODEL
        if licensed and not secret_arn:
            result.skipped[model] = "no MATLAB license secret is configured for this participant"
            continue
        payloads[model] = participant_job_definition_payload(
            user_id=user_id,
            model=model,
            image=_image(image_for_model, model),
            execution_role_arn=execution_role_arn,
            account_id=account_id,
            region=config.region,
            job_config=(job_config_for_model or {}).get(model, DEFAULT_ISSM_JOB_CONFIG),
            command=command,
            matlab_secret_arn=secret_arn if licensed else None,
        )

    _ensure_job_role(
        invoke, user_id=user_id, bucket=bucket, account_id=account_id,
        result=result, sleep=sleep,
    )
    for model, payload in payloads.items():
        _ensure_job_definition(invoke, payload, model=model, result=result)
    return result


def remove_participant_resources(
    config: AWSConfig,
    *,
    user_id: str,
    recovery_window_days: int = SECRET_RECOVERY_WINDOW_DAYS,
    aws: AwsRunner | None = None,
) -> PilotParticipantRemoval:
    """Close-out for one participant: schedule their MATLAB-license secret
    for deletion (recoverable for ``recovery_window_days``), and remove any
    LEGACY task-role resources that exist for them -- per-participant job
    definitions ``cryostack-pilot-<key>-*`` and the job role
    ``cryostack-pilot-job-<key>`` with all its policies. Idempotent.
    Per-reservation definitions are removed by
    :func:`remove_reservation_resources`.

    Call it only when the participant has no queued or running job: a job
    that starts after its role is gone fails. S3 objects under
    ``pilot/<key>/`` are not touched here -- fetch results first; the bucket
    lifecycle rule expires what is left.
    """
    invoke = _runner(config, aws)
    key = participant_key(user_id)
    role = participant_job_role_name(user_id)
    outcome = PilotParticipantRemoval(participant=key)

    prefix = f"{PILOT_NAME_PREFIX}{key}-"
    mine = [
        item for item in _active_definitions(invoke)
        if str(item.get("jobDefinitionName") or "").startswith(prefix)
    ]
    for definition in mine:
        _deregister(invoke, definition)
        outcome.removed.append(
            f"job_definition:{definition.get('jobDefinitionName')}:{definition.get('revision')}")
    if not mine:
        outcome.absent.append("job_definitions")

    if not 7 <= int(recovery_window_days) <= 30:
        raise ValueError("the secret recovery window is 7 to 30 days")
    code, out, err = invoke([
        "secretsmanager", "delete-secret",
        "--secret-id", participant_secret_name(user_id),
        "--recovery-window-in-days", str(int(recovery_window_days)),
    ])
    blob = _text(out, err).lower()
    if code == 0:
        outcome.removed.append("license_secret (deletion scheduled)")
    elif "resourcenotfound" in blob or "scheduled for deletion" in blob:
        outcome.absent.append("license_secret")
    else:
        raise PilotProvisionError(_text(out, err) or "secretsmanager delete-secret failed.")

    code, out, err = invoke(["iam", "list-role-policies", "--role-name", role])
    if code != 0 and _missing(out, err):
        outcome.absent.append("job_role")
        return outcome
    for name in _require(code, out, err, what="iam list-role-policies").get("PolicyNames") or []:
        code, out, err = invoke([
            "iam", "delete-role-policy", "--role-name", role, "--policy-name", name])
        if code != 0 and not _missing(out, err):
            raise PilotProvisionError(_text(out, err) or "iam delete-role-policy failed.")
        outcome.removed.append(f"job_role_policy:{name}")

    code, out, err = invoke(["iam", "list-attached-role-policies", "--role-name", role])
    attached = _require(
        code, out, err, what="iam list-attached-role-policies"
    ).get("AttachedPolicies") or []
    for item in attached:
        code, out, err = invoke([
            "iam", "detach-role-policy",
            "--role-name", role, "--policy-arn", str(item.get("PolicyArn"))])
        if code != 0 and not _missing(out, err):
            raise PilotProvisionError(_text(out, err) or "iam detach-role-policy failed.")
        outcome.removed.append(f"job_role_attachment:{item.get('PolicyName')}")

    code, out, err = invoke(["iam", "delete-role", "--role-name", role])
    if code != 0 and not _missing(out, err):
        raise PilotProvisionError(_text(out, err) or "iam delete-role failed.")
    (outcome.removed if code == 0 else outcome.absent).append("job_role")
    return outcome
