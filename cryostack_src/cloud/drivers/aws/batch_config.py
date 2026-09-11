# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Batch Configuration
# File        : batch_config.py
#
# Description :
#     Deterministic names and Fargate job specifications for CryoStack
#     AWS Batch execution. Definitions only -- no AWS calls.
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
AWS Batch resource configuration for CryoStack.

Kept separate from provisioning (``batch_provision.py``) and discovery
(``batch.py``) so the exact Fargate shape CryoStack asks AWS for is explicit,
reviewable and unit-testable without touching AWS.

First supported configuration: **AWS Batch on Fargate** -- managed, scale to
zero, no always-on EC2 capacity. Every job carries a mandatory timeout,
bounded vCPU/memory, bounded ephemeral storage and an ``awslogs`` driver.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── deterministic resource names ─────────────────────────────────────────────
# AWS Batch names are scoped to account + region, so (unlike the global S3
# bucket) they need no account suffix to stay deterministic.
COMPUTE_ENVIRONMENT_NAME = "cryostack-fargate"
JOB_QUEUE_NAME = "cryostack-queue"
JOB_DEFINITION_NAMES = {
    "issm": "cryostack-issm",
    "icepack": "cryostack-icepack",
    "icesee": "cryostack-icesee",
}

# ── EC2 compute (Advanced) ───────────────────────────────────────────────────
# EC2 is an OPTIONAL, advanced compute mode. Its resources are separate from
# Fargate's (never renamed / reused / overwritten) so a Fargate<->EC2 switch
# can never scramble the other's platform configuration. Fargate stays the
# default and is always provisioned; EC2 is provisioned only when selected.
COMPUTE_MODE_FARGATE = "fargate"
COMPUTE_MODE_EC2 = "ec2"
SUPPORTED_COMPUTE_MODES = (COMPUTE_MODE_FARGATE, COMPUTE_MODE_EC2)

EC2_COMPUTE_ENVIRONMENT_NAME = "cryostack-ec2"
EC2_JOB_QUEUE_NAME = "cryostack-ec2-queue"

#: EC2 job-definition names get a deterministic ``-ec2`` suffix so an EC2
#: revision never overwrites a Fargate revision's platform configuration.
EC2_JOB_DEFINITION_SUFFIX = "-ec2"

#: "optimal" lets AWS Batch pick from the C/M/R instance families that best fit
#: each job -- no instance-family knowledge required from the user.
DEFAULT_EC2_INSTANCE_TYPES: tuple[str, ...] = ("optimal",)
#: BEST_FIT_PROGRESSIVE: launch the best-fitting type, fall back to others as
#: capacity allows. The sane default for a mixed On-Demand CPU workload.
DEFAULT_EC2_ALLOCATION_STRATEGY = "BEST_FIT_PROGRESSIVE"
# ECR repositories that hold CryoStack's tested images (one per model). Kept
# here so provisioning, delivery and discovery agree on the name.
ECR_REPOSITORY_NAMES = {
    "issm": "cryostack-issm",
    "icepack": "cryostack-icepack",
    "icesee": "cryostack-icesee",
}

LOG_GROUP_PREFIX = "/cryostack/batch"
LOG_RETENTION_DAYS = 30                       # cost guardrail

# ── compute environment ─────────────────────────────────────────────────────
DEFAULT_MAX_VCPUS = 16                        # hard ceiling on concurrent vCPUs
JOB_QUEUE_PRIORITY = 1

# Valid AWS Fargate vCPU values and, for each, the [min, max] task memory (MiB)
# and the memory step. Used to reject an impossible task shape before AWS does.
_FARGATE_MEMORY_RULES: dict[str, tuple[int, int, int]] = {
    "0.25": (512, 2048, 512),
    "0.5": (1024, 4096, 1024),
    "1": (2048, 8192, 1024),
    "2": (4096, 16384, 1024),
    "4": (8192, 30720, 1024),
    "8": (16384, 61440, 4096),
    "16": (32768, 122880, 8192),
}

_MIN_EPHEMERAL_GIB = 21
_MAX_EPHEMERAL_GIB = 200
_MIN_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class FargateJobConfig:
    """The runtime shape of one CryoStack Batch job on Fargate."""

    vcpu: str = "2"
    memory_mib: str = "8192"                  # valid with vcpu="2"
    ephemeral_gib: int = 50                   # staged example tree + outputs/
    timeout_seconds: int = 3600              # mandatory -- a run is always bounded
    attempts: int = 1                        # never silently retry a billable job
    platform_version: str = "LATEST"
    assign_public_ip: str = "ENABLED"        # default-VPC public subnets -> ECR/S3
    cpu_architecture: str = "X86_64"
    operating_system_family: str = "LINUX"


DEFAULT_ISSM_JOB_CONFIG = FargateJobConfig()


def validate_fargate_job_config(config: FargateJobConfig) -> None:
    """Raise ``ValueError`` for a task shape AWS Fargate would reject."""
    rule = _FARGATE_MEMORY_RULES.get(str(config.vcpu))
    if rule is None:
        raise ValueError(
            f"Fargate vCPU must be one of {sorted(_FARGATE_MEMORY_RULES)}; "
            f"got {config.vcpu!r}"
        )
    lo, hi, step = rule
    try:
        memory = int(config.memory_mib)
    except (TypeError, ValueError):
        raise ValueError(f"memory_mib must be an integer MiB value; got {config.memory_mib!r}")
    if not (lo <= memory <= hi) or (memory - lo) % step:
        raise ValueError(
            f"Fargate memory {memory} MiB is not valid for {config.vcpu} vCPU "
            f"(allowed {lo}-{hi} MiB in steps of {step})"
        )
    if not (_MIN_EPHEMERAL_GIB <= int(config.ephemeral_gib) <= _MAX_EPHEMERAL_GIB):
        raise ValueError(
            f"ephemeral_gib must be {_MIN_EPHEMERAL_GIB}-{_MAX_EPHEMERAL_GIB}; "
            f"got {config.ephemeral_gib}"
        )
    if int(config.timeout_seconds) < _MIN_TIMEOUT_SECONDS:
        raise ValueError(
            f"timeout_seconds must be >= {_MIN_TIMEOUT_SECONDS}; got {config.timeout_seconds}"
        )
    if int(config.attempts) < 1:
        raise ValueError("attempts must be >= 1")


def log_group_name(model: str) -> str:
    return f"{LOG_GROUP_PREFIX}/{(model or 'run').strip().lower()}"


def normalize_compute_mode(mode: str | None) -> str:
    """``"ec2"`` only for an explicit, recognised EC2 selection; everything
    else -- including ``None``, ``""`` and an old saved config that never
    carried the field -- resolves to Fargate. Backward compatibility is the
    whole point: a deserialised config must default to the validated path."""
    m = (mode or "").strip().lower()
    return COMPUTE_MODE_EC2 if m == COMPUTE_MODE_EC2 else COMPUTE_MODE_FARGATE


def job_definition_name(model: str, compute_mode: str | None = None) -> str:
    """Deterministic job-definition name. EC2 gets a ``-ec2`` suffix so its
    revisions can never overwrite a Fargate revision (different platform
    capabilities / container spec). Default (no / Fargate mode) is unchanged."""
    base = JOB_DEFINITION_NAMES.get(
        (model or "").strip().lower(), f"cryostack-{model}")
    if normalize_compute_mode(compute_mode) == COMPUTE_MODE_EC2:
        return f"{base}{EC2_JOB_DEFINITION_SUFFIX}"
    return base


def compute_environment_name(compute_mode: str | None = None) -> str:
    return (EC2_COMPUTE_ENVIRONMENT_NAME
            if normalize_compute_mode(compute_mode) == COMPUTE_MODE_EC2
            else COMPUTE_ENVIRONMENT_NAME)


def job_queue_name(compute_mode: str | None = None) -> str:
    return (EC2_JOB_QUEUE_NAME
            if normalize_compute_mode(compute_mode) == COMPUTE_MODE_EC2
            else JOB_QUEUE_NAME)


# ── EC2 config dataclasses + payload builders (pure) ─────────────────────────
_MIN_EC2_MAX_VCPUS = 1
_MAX_EC2_MAX_VCPUS = 10000                    # AWS Batch hard limit is 1M; keep sane


@dataclass(frozen=True)
class EC2ComputeConfig:
    """The shape of the *managed EC2* Batch compute environment (Advanced).

    Deliberately minimal: On-Demand only, scale-to-zero (``min``/``desired`` 0),
    ``optimal`` instance selection. Spot / GPU / launch templates / custom AMIs
    are intentionally out of the first pass but the fields they would need slot
    in here without touching call sites."""

    min_vcpus: int = 0
    desired_vcpus: int = 0
    max_vcpus: int = DEFAULT_MAX_VCPUS
    instance_types: tuple[str, ...] = DEFAULT_EC2_INSTANCE_TYPES
    allocation_strategy: str = DEFAULT_EC2_ALLOCATION_STRATEGY


@dataclass(frozen=True)
class EC2JobConfig:
    """The runtime shape of one CryoStack Batch job on EC2.

    No Fargate-only knobs: no ``ephemeral_gib`` (EC2 uses the instance's own
    disk), no ``assign_public_ip`` (that is compute-environment level on EC2),
    no ``platform_version``. The Fargate vCPU/memory compatibility table is
    NOT applied -- on EC2 ``memory`` is just the container's hard limit."""

    vcpu: str = "2"
    memory_mib: str = "8192"
    timeout_seconds: int = 3600
    attempts: int = 1
    cpu_architecture: str = "X86_64"
    operating_system_family: str = "LINUX"


DEFAULT_EC2_JOB_CONFIG = EC2JobConfig()


def validate_ec2_compute_config(config: EC2ComputeConfig) -> None:
    """Raise ``ValueError`` for an EC2 compute environment AWS Batch would
    reject. Much looser than Fargate -- no memory table."""
    lo, want, hi = (int(config.min_vcpus), int(config.desired_vcpus),
                    int(config.max_vcpus))
    if lo < 0:
        raise ValueError(f"EC2 min_vcpus must be >= 0; got {lo}")
    if not (_MIN_EC2_MAX_VCPUS <= hi <= _MAX_EC2_MAX_VCPUS):
        raise ValueError(
            f"EC2 max_vcpus must be {_MIN_EC2_MAX_VCPUS}-{_MAX_EC2_MAX_VCPUS}; "
            f"got {hi}")
    if not (lo <= want <= hi):
        raise ValueError(
            f"EC2 desired_vcpus must be between min ({lo}) and max ({hi}); "
            f"got {want}")
    if not config.instance_types:
        raise ValueError("EC2 compute environment needs at least one instance type")


def validate_ec2_job_config(config: EC2JobConfig) -> None:
    """Raise ``ValueError`` for an EC2 job shape AWS Batch would reject."""
    try:
        if float(config.vcpu) <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError(f"EC2 vcpu must be a positive number; got {config.vcpu!r}")
    try:
        if int(config.memory_mib) <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError(
            f"EC2 memory_mib must be a positive integer MiB value; "
            f"got {config.memory_mib!r}")
    if int(config.timeout_seconds) < _MIN_TIMEOUT_SECONDS:
        raise ValueError(
            f"timeout_seconds must be >= {_MIN_TIMEOUT_SECONDS}; "
            f"got {config.timeout_seconds}")
    if int(config.attempts) < 1:
        raise ValueError("attempts must be >= 1")


def ec2_compute_resources_payload(
    *,
    subnets: list[str],
    security_groups: list[str],
    instance_role_arn: str,
    config: EC2ComputeConfig = EC2ComputeConfig(),
) -> dict:
    """``computeResources`` for a managed EC2 (scale-to-zero) compute
    environment. Same VPC/subnet/SG model as Fargate for now.

    ``instance_role_arn`` is the ECS **instance profile** ARN (the value Batch
    calls ``instanceRole``). No ``launchTemplate`` -- AWS Batch supplies the
    ECS-optimized AMI automatically for a managed EC2 environment.
    """
    validate_ec2_compute_config(config)
    if not subnets:
        raise ValueError("an EC2 compute environment needs at least one subnet")
    if not (instance_role_arn or "").strip():
        raise ValueError("an EC2 compute environment needs an ECS instance role")
    payload: dict = {
        "type": "EC2",
        "allocationStrategy": config.allocation_strategy,
        "minvCpus": int(config.min_vcpus),
        "desiredvCpus": int(config.desired_vcpus),
        "maxvCpus": int(config.max_vcpus),
        "instanceTypes": list(config.instance_types),
        "instanceRole": instance_role_arn,
        "subnets": list(subnets),
    }
    if security_groups:
        payload["securityGroupIds"] = list(security_groups)
    return payload


def ec2_container_properties_payload(
    *,
    model: str,
    image: str,
    job_role_arn: str,
    execution_role_arn: str,
    region: str,
    config: EC2JobConfig = DEFAULT_EC2_JOB_CONFIG,
    command: list[str] | None = None,
    secrets: list[dict] | None = None,
) -> dict:
    """``containerProperties`` for an **EC2** CryoStack job definition.

    Same image / command / roles / resourceRequirements / runtimePlatform /
    awslogs / Secrets Manager wiring as Fargate, minus every Fargate-only key:
    no ``networkConfiguration``, no ``fargatePlatformConfiguration``, no
    ``ephemeralStorage``. The MATLAB-license secret path (``executionRoleArn``
    + ``secrets``) is identical to Fargate.
    """
    validate_ec2_job_config(config)
    if not image:
        raise ValueError("a job definition needs a container image reference")
    if not (job_role_arn and execution_role_arn):
        raise ValueError("job definition needs both a job role and an execution role")
    payload = {
        "image": image,
        "command": list(command or ["cryostack-run"]),
        "jobRoleArn": job_role_arn,
        "executionRoleArn": execution_role_arn,
        "resourceRequirements": [
            {"type": "VCPU", "value": str(config.vcpu)},
            {"type": "MEMORY", "value": str(config.memory_mib)},
        ],
        "runtimePlatform": {
            "cpuArchitecture": config.cpu_architecture,
            "operatingSystemFamily": config.operating_system_family,
        },
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": log_group_name(model),
                "awslogs-region": region,
                "awslogs-stream-prefix": (model or "run").strip().lower(),
            },
        },
    }
    clean_secrets = [
        {"name": str(s["name"]), "valueFrom": str(s["valueFrom"])}
        for s in (secrets or [])
        if isinstance(s, dict) and s.get("name") and s.get("valueFrom")
    ]
    if clean_secrets:
        for s in clean_secrets:
            if not s["valueFrom"].startswith("arn:aws:"):
                raise ValueError(
                    "containerProperties.secrets[].valueFrom must be an ARN, "
                    "never a value"
                )
        payload["secrets"] = clean_secrets
    return payload


# ── payload builders (pure) ────────────────────────────────────────────────
def compute_resources_payload(
    *,
    subnets: list[str],
    security_groups: list[str],
    max_vcpus: int = DEFAULT_MAX_VCPUS,
) -> dict:
    """``computeResources`` for a Fargate (scale-to-zero) compute environment.

    No ``minvCpus``/``desiredvCpus`` and no instance types: Fargate provisions
    per-job and releases immediately, so nothing runs (or bills) while the
    queue is idle.
    """
    if not subnets:
        raise ValueError("a Fargate compute environment needs at least one subnet")
    if int(max_vcpus) < 1:
        raise ValueError("max_vcpus must be >= 1")
    payload: dict = {
        "type": "FARGATE",
        "maxvCpus": int(max_vcpus),
        "subnets": list(subnets),
    }
    if security_groups:
        payload["securityGroupIds"] = list(security_groups)
    return payload


def container_properties_payload(
    *,
    model: str,
    image: str,
    job_role_arn: str,
    execution_role_arn: str,
    region: str,
    config: FargateJobConfig = DEFAULT_ISSM_JOB_CONFIG,
    command: list[str] | None = None,
    secrets: list[dict] | None = None,
) -> dict:
    """``containerProperties`` for a Fargate CryoStack job definition.

    ``secrets`` (``[{"name","valueFrom"}]``) is passed straight through to
    ``containerProperties.secrets`` -- used for the ISSM MATLAB license
    (a Secrets Manager ARN in the user's own account; AWS Batch injects the
    value at launch). It is a list of ARN REFERENCES, never a value.
    """
    validate_fargate_job_config(config)
    if not image:
        raise ValueError("a job definition needs a container image reference")
    if not (job_role_arn and execution_role_arn):
        raise ValueError("job definition needs both a job role and an execution role")
    payload = {
        "image": image,
        # Commit 3 replaces this with the generic cloud runner entrypoint.
        "command": list(command or ["cryostack-run"]),
        "jobRoleArn": job_role_arn,
        "executionRoleArn": execution_role_arn,
        "resourceRequirements": [
            {"type": "VCPU", "value": str(config.vcpu)},
            {"type": "MEMORY", "value": str(config.memory_mib)},
        ],
        "networkConfiguration": {"assignPublicIp": config.assign_public_ip},
        "ephemeralStorage": {"sizeInGiB": int(config.ephemeral_gib)},
        "fargatePlatformConfiguration": {"platformVersion": config.platform_version},
        "runtimePlatform": {
            "cpuArchitecture": config.cpu_architecture,
            "operatingSystemFamily": config.operating_system_family,
        },
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": log_group_name(model),
                "awslogs-region": region,
                "awslogs-stream-prefix": (model or "run").strip().lower(),
            },
        },
    }
    clean_secrets = [
        {"name": str(s["name"]), "valueFrom": str(s["valueFrom"])}
        for s in (secrets or [])
        if isinstance(s, dict) and s.get("name") and s.get("valueFrom")
    ]
    if clean_secrets:
        # ARN references only -- fail closed if a raw value slipped through.
        for s in clean_secrets:
            if not s["valueFrom"].startswith("arn:aws:"):
                raise ValueError(
                    "containerProperties.secrets[].valueFrom must be an ARN, "
                    "never a value"
                )
        payload["secrets"] = clean_secrets
    return payload


def job_definition_fingerprint(
    *,
    container_properties: dict,
    timeout_seconds: int,
    attempts: int,
) -> dict:
    """The subset of a job definition CryoStack cares about, for
    describe-before-register drift detection."""
    cp = container_properties
    return {
        "image": cp.get("image"),
        "command": cp.get("command"),
        "jobRoleArn": cp.get("jobRoleArn"),
        "executionRoleArn": cp.get("executionRoleArn"),
        "resourceRequirements": sorted(
            (r.get("type"), r.get("value"))
            for r in cp.get("resourceRequirements", [])
        ),
        "assignPublicIp": (cp.get("networkConfiguration") or {}).get("assignPublicIp"),
        "ephemeralStorage": (cp.get("ephemeralStorage") or {}).get("sizeInGiB"),
        "platformVersion": (cp.get("fargatePlatformConfiguration") or {}).get("platformVersion"),
        "logDriver": (cp.get("logConfiguration") or {}).get("logDriver"),
        "logGroup": ((cp.get("logConfiguration") or {}).get("options") or {}).get("awslogs-group"),
        # secret ARN references only -- a change here (e.g. a MATLAB license
        # secret added/removed) re-registers the job definition
        "secrets": sorted(
            (s.get("name"), s.get("valueFrom")) for s in cp.get("secrets", [])
        ),
        "timeoutSeconds": int(timeout_seconds),
        "attempts": int(attempts),
    }
