# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Batch Provisioning
# File        : batch_provision.py
#
# Description :
#     Idempotently provisions the AWS Batch on Fargate resources CryoStack
#     needs for cloud execution: a scale-to-zero compute environment, a job
#     queue, per-model job definitions and their CloudWatch log groups.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-31
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
AWS Batch (Fargate) provisioning for CryoStack.

Every operation is **describe-before-create/update**:

* compute environment -> describe; create if absent; update if ``maxvCpus`` or
  the subnet / security-group set drifted;
* job queue           -> describe; create if absent; update if priority or the
  bound compute environment drifted;
* job definition      -> describe the active revisions; register a new revision
  only when the container spec / timeout / retry drifted;
* log group           -> create (tolerating "already exists") and pin retention.

Discovery stays in ``batch.py``; this module holds the resource-changing calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .auth import run_aws
from .batch import AWSBatchResources, discover_batch_resources
from .batch_config import (
    COMPUTE_ENVIRONMENT_NAME,
    DEFAULT_ISSM_JOB_CONFIG,
    DEFAULT_MAX_VCPUS,
    JOB_QUEUE_NAME,
    JOB_QUEUE_PRIORITY,
    LOG_RETENTION_DAYS,
    FargateJobConfig,
    compute_resources_payload,
    container_properties_payload,
    job_definition_fingerprint,
    job_definition_name,
    log_group_name,
)
from .models import AWSConfig


@dataclass
class AWSBatchProvisionResult:
    """Outcome of preparing CryoStack's AWS Batch resources."""

    resources: AWSBatchResources
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    reused: list[str] = field(default_factory=list)
    log_groups: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    #: infrastructure state for the mirrored tested image (set by the driver);
    #: never a substitute for the scientific ``container`` provenance block.
    image_delivery: object | None = None


def _require_success(code: int, stdout: str, stderr: str, *, what: str) -> str:
    if code != 0:
        raise RuntimeError((stderr or stdout).strip() or f"{what} failed.")
    return stdout


def _describe(config: AWSConfig, args: list[str]) -> dict:
    """A describe call whose non-zero exit means 'inspect failed', not
    'resource absent' -- callers pass a filter that simply returns [] when
    the named resource does not exist."""
    code, stdout, stderr = run_aws(config, args)
    _require_success(code, stdout, stderr, what=" ".join(args[:2]))
    return json.loads(stdout or "{}")


# ── CloudWatch log group ──────────────────────────────────────────────────
def ensure_log_group(config: AWSConfig, *, model: str) -> str:
    """Create ``/cryostack/batch/<model>`` (idempotent) and pin its retention.

    The ECS task execution role can write streams but not create the group, so
    CryoStack creates it up front rather than relying on ``awslogs-create-group``.
    """
    name = log_group_name(model)
    code, stdout, stderr = run_aws(
        config, ["logs", "create-log-group", "--log-group-name", name]
    )
    text = (stderr or stdout or "")
    if code != 0 and "ResourceAlreadyExistsException" not in text:
        raise RuntimeError(text.strip() or f"Unable to create log group {name}.")

    code, stdout, stderr = run_aws(
        config,
        [
            "logs", "put-retention-policy",
            "--log-group-name", name,
            "--retention-in-days", str(LOG_RETENTION_DAYS),
        ],
    )
    _require_success(code, stdout, stderr, what="logs put-retention-policy")
    return name


# ── compute environment ───────────────────────────────────────────────────
def _current_compute_environment(config: AWSConfig) -> dict | None:
    payload = _describe(
        config,
        ["batch", "describe-compute-environments",
         "--compute-environments", COMPUTE_ENVIRONMENT_NAME],
    )
    envs = payload.get("computeEnvironments", [])
    return envs[0] if envs else None


def ensure_compute_environment(
    config: AWSConfig,
    *,
    subnets: list[str],
    security_groups: list[str],
    max_vcpus: int = DEFAULT_MAX_VCPUS,
) -> str:
    """Return one of ``created`` / ``updated`` / ``reused``."""
    desired = compute_resources_payload(
        subnets=subnets, security_groups=security_groups, max_vcpus=max_vcpus,
    )
    current = _current_compute_environment(config)

    if current is None:
        code, stdout, stderr = run_aws(
            config,
            [
                "batch", "create-compute-environment",
                "--compute-environment-name", COMPUTE_ENVIRONMENT_NAME,
                "--type", "MANAGED",
                "--state", "ENABLED",
                "--compute-resources", json.dumps(desired),
            ],
        )
        _require_success(code, stdout, stderr, what="batch create-compute-environment")
        return "created"

    cr = current.get("computeResources") or {}
    drift = (
        int(cr.get("maxvCpus", -1)) != int(desired["maxvCpus"])
        or set(cr.get("subnets") or []) != set(desired["subnets"])
        or set(cr.get("securityGroupIds") or []) != set(desired.get("securityGroupIds") or [])
    )
    if not drift:
        return "reused"

    code, stdout, stderr = run_aws(
        config,
        [
            "batch", "update-compute-environment",
            "--compute-environment", COMPUTE_ENVIRONMENT_NAME,
            "--state", "ENABLED",
            "--compute-resources", json.dumps({
                "maxvCpus": desired["maxvCpus"],
                "subnets": desired["subnets"],
                **({"securityGroupIds": desired["securityGroupIds"]}
                   if desired.get("securityGroupIds") else {}),
            }),
        ],
    )
    _require_success(code, stdout, stderr, what="batch update-compute-environment")
    return "updated"


# ── job queue ─────────────────────────────────────────────────────────────
def _current_job_queue(config: AWSConfig) -> dict | None:
    payload = _describe(
        config,
        ["batch", "describe-job-queues", "--job-queues", JOB_QUEUE_NAME],
    )
    queues = payload.get("jobQueues", [])
    return queues[0] if queues else None


def _compute_env_in_order(order: list[dict]) -> set[str]:
    names: set[str] = set()
    for entry in order or []:
        ref = entry.get("computeEnvironment") or ""
        names.add(ref.rsplit("/", 1)[-1])          # accept ARN or bare name
    return names


def ensure_job_queue(config: AWSConfig) -> str:
    ce_order = [{"order": 1, "computeEnvironment": COMPUTE_ENVIRONMENT_NAME}]
    current = _current_job_queue(config)

    if current is None:
        code, stdout, stderr = run_aws(
            config,
            [
                "batch", "create-job-queue",
                "--job-queue-name", JOB_QUEUE_NAME,
                "--state", "ENABLED",
                "--priority", str(JOB_QUEUE_PRIORITY),
                "--compute-environment-order", json.dumps(ce_order),
            ],
        )
        _require_success(code, stdout, stderr, what="batch create-job-queue")
        return "created"

    drift = (
        int(current.get("priority", -1)) != JOB_QUEUE_PRIORITY
        or COMPUTE_ENVIRONMENT_NAME not in _compute_env_in_order(
            current.get("computeEnvironmentOrder"))
        or (current.get("state") or "").upper() != "ENABLED"
    )
    if not drift:
        return "reused"

    code, stdout, stderr = run_aws(
        config,
        [
            "batch", "update-job-queue",
            "--job-queue", JOB_QUEUE_NAME,
            "--state", "ENABLED",
            "--priority", str(JOB_QUEUE_PRIORITY),
            "--compute-environment-order", json.dumps(ce_order),
        ],
    )
    _require_success(code, stdout, stderr, what="batch update-job-queue")
    return "updated"


# ── job definition ────────────────────────────────────────────────────────
def _active_job_definitions(config: AWSConfig, name: str) -> list[dict]:
    payload = _describe(
        config,
        ["batch", "describe-job-definitions",
         "--job-definition-name", name, "--status", "ACTIVE"],
    )
    return payload.get("jobDefinitions", [])


def ensure_job_definition(
    config: AWSConfig,
    *,
    model: str,
    image: str,
    job_role_arn: str,
    execution_role_arn: str,
    region: str,
    job_config: FargateJobConfig = DEFAULT_ISSM_JOB_CONFIG,
) -> str:
    name = job_definition_name(model)
    desired_cp = container_properties_payload(
        model=model, image=image, job_role_arn=job_role_arn,
        execution_role_arn=execution_role_arn, region=region, config=job_config,
    )
    desired_fp = job_definition_fingerprint(
        container_properties=desired_cp,
        timeout_seconds=job_config.timeout_seconds,
        attempts=job_config.attempts,
    )

    for revision in sorted(
        _active_job_definitions(config, name),
        key=lambda r: int(r.get("revision", 0)), reverse=True,
    ):
        existing_fp = job_definition_fingerprint(
            container_properties=revision.get("containerProperties") or {},
            timeout_seconds=int(
                (revision.get("timeout") or {}).get("attemptDurationSeconds", 0)),
            attempts=int((revision.get("retryStrategy") or {}).get("attempts", 1)),
        )
        if existing_fp == desired_fp:
            return "reused"
        break  # only the latest revision matters

    code, stdout, stderr = run_aws(
        config,
        [
            "batch", "register-job-definition",
            "--job-definition-name", name,
            "--type", "container",
            "--platform-capabilities", "FARGATE",
            "--container-properties", json.dumps(desired_cp),
            "--timeout", json.dumps(
                {"attemptDurationSeconds": int(job_config.timeout_seconds)}),
            "--retry-strategy", json.dumps({"attempts": int(job_config.attempts)}),
        ],
    )
    _require_success(code, stdout, stderr, what="batch register-job-definition")
    return "created"


# ── orchestration ─────────────────────────────────────────────────────────
def ensure_batch_resources(
    config: AWSConfig,
    *,
    subnets: list[str],
    security_groups: list[str],
    job_role_arn: str,
    execution_role_arn: str,
    issm_image: str | None,
    max_vcpus: int = DEFAULT_MAX_VCPUS,
    issm_job_config: FargateJobConfig = DEFAULT_ISSM_JOB_CONFIG,
    include_icepack: bool = False,
    icepack_image: str | None = None,
    icepack_job_config: FargateJobConfig | None = None,
) -> AWSBatchProvisionResult:
    """Prepare CryoStack's AWS Batch on Fargate environment, idempotently."""
    result = AWSBatchProvisionResult(resources=None)  # type: ignore[arg-type]

    if not subnets:
        result.skipped.append("batch (no usable subnets discovered)")
        result.messages.append(
            "AWS Batch provisioning skipped: no subnets in the default VPC.")
        result.resources = discover_batch_resources(config)
        return result

    def _bucket(name: str, outcome: str) -> None:
        {"created": result.created, "updated": result.updated,
         "reused": result.reused}[outcome].append(name)

    # 1. compute environment (Fargate -- scale to zero)
    _bucket("compute_environment", ensure_compute_environment(
        config, subnets=subnets, security_groups=security_groups,
        max_vcpus=max_vcpus,
    ))

    # 2. job queue
    _bucket("job_queue", ensure_job_queue(config))

    # 3. per-model job definitions (+ their log groups)
    if job_role_arn and execution_role_arn and issm_image:
        result.log_groups.append(ensure_log_group(config, model="issm"))
        _bucket("issm_job_definition", ensure_job_definition(
            config, model="issm", image=issm_image, job_role_arn=job_role_arn,
            execution_role_arn=execution_role_arn, region=config.region,
            job_config=issm_job_config,
        ))
    else:
        result.skipped.append(
            "issm_job_definition (needs job role, execution role and an image)")

    if include_icepack and job_role_arn and execution_role_arn and icepack_image:
        result.log_groups.append(ensure_log_group(config, model="icepack"))
        _bucket("icepack_job_definition", ensure_job_definition(
            config, model="icepack", image=icepack_image, job_role_arn=job_role_arn,
            execution_role_arn=execution_role_arn, region=config.region,
            job_config=icepack_job_config or DEFAULT_ISSM_JOB_CONFIG,
        ))

    result.resources = discover_batch_resources(config)
    return result
