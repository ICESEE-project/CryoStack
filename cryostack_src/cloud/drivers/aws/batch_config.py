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
#: EC2 Spot capacity -- separate compute environment + queue so a Spot job
#: never lands on an On-Demand environment or vice versa.
EC2_SPOT_COMPUTE_ENVIRONMENT_NAME = "cryostack-ec2-spot"
EC2_SPOT_JOB_QUEUE_NAME = "cryostack-ec2-spot-queue"

#: EC2 job-definition names get a deterministic ``-ec2`` suffix so an EC2
#: revision never overwrites a Fargate revision's platform configuration.
#: Accelerator / topology add further deterministic suffixes (a GPU or
#: multi-node job definition has a genuinely different container spec).
EC2_JOB_DEFINITION_SUFFIX = "-ec2"
EC2_GPU_JOB_DEFINITION_SUFFIX = "-ec2-gpu"
EC2_MULTINODE_JOB_DEFINITION_SUFFIX = "-ec2-mnp"

#: "optimal" lets AWS Batch pick from the C/M/R instance families that best fit
#: each job -- no instance-family knowledge required from the user.
DEFAULT_EC2_INSTANCE_TYPES: tuple[str, ...] = ("optimal",)
#: GPU instance families AWS Batch's ECS-GPU AMI supports out of the box.
DEFAULT_EC2_GPU_INSTANCE_TYPES: tuple[str, ...] = ("g4dn", "g5")
#: BEST_FIT_PROGRESSIVE: launch the best-fitting type, fall back to others as
#: capacity allows. The sane default for a mixed On-Demand CPU workload.
DEFAULT_EC2_ALLOCATION_STRATEGY = "BEST_FIT_PROGRESSIVE"
#: Spot: price + capacity optimized. Needs NO EC2 spot-fleet IAM role
#: (unlike a custom-AMI SPOT setup), least-interrupted cheap capacity.
DEFAULT_EC2_SPOT_ALLOCATION_STRATEGY = "SPOT_PRICE_CAPACITY_OPTIMIZED"

# ── EC2 sub-mode enums (all default to the plain On-Demand CPU single-node) ──
EC2_CAPACITY_ON_DEMAND = "on_demand"
EC2_CAPACITY_SPOT = "spot"
SUPPORTED_EC2_CAPACITIES = (EC2_CAPACITY_ON_DEMAND, EC2_CAPACITY_SPOT)

EC2_ACCELERATOR_NONE = "none"
EC2_ACCELERATOR_GPU = "gpu"
SUPPORTED_EC2_ACCELERATORS = (EC2_ACCELERATOR_NONE, EC2_ACCELERATOR_GPU)

EC2_TOPOLOGY_SINGLE = "single_node"
EC2_TOPOLOGY_MULTINODE = "multi_node"
SUPPORTED_EC2_TOPOLOGIES = (EC2_TOPOLOGY_SINGLE, EC2_TOPOLOGY_MULTINODE)

EC2_NETWORK_DEFAULT = "default"
EC2_NETWORK_CUSTOM = "custom"
SUPPORTED_EC2_NETWORKS = (EC2_NETWORK_DEFAULT, EC2_NETWORK_CUSTOM)

_MIN_MULTINODE_NODES = 2
_MAX_MULTINODE_NODES = 64                     # sane cap; AWS allows more


def normalize_ec2_capacity(value: str | None) -> str:
    v = (value or "").strip().lower()
    return EC2_CAPACITY_SPOT if v == EC2_CAPACITY_SPOT else EC2_CAPACITY_ON_DEMAND


def normalize_ec2_accelerator(value: str | None) -> str:
    v = (value or "").strip().lower()
    return EC2_ACCELERATOR_GPU if v == EC2_ACCELERATOR_GPU else EC2_ACCELERATOR_NONE


def normalize_ec2_topology(value: str | None) -> str:
    v = (value or "").strip().lower().replace("-", "_")
    return EC2_TOPOLOGY_MULTINODE if v == EC2_TOPOLOGY_MULTINODE else EC2_TOPOLOGY_SINGLE


def normalize_ec2_network(value: str | None) -> str:
    v = (value or "").strip().lower()
    return EC2_NETWORK_CUSTOM if v == EC2_NETWORK_CUSTOM else EC2_NETWORK_DEFAULT
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


def job_definition_name(
    model: str,
    compute_mode: str | None = None,
    *,
    accelerator: str | None = None,
    topology: str | None = None,
) -> str:
    """Deterministic job-definition name. EC2 gets a ``-ec2`` suffix so its
    revisions can never overwrite a Fargate revision (different platform
    capabilities / container spec). Default (no / Fargate mode) is unchanged.

    A GPU or multi-node EC2 job definition has a genuinely different
    container spec (``resourceRequirements``/``nodeProperties``), so it gets
    its own deterministic name too -- never the plain ``-ec2`` one. Capacity
    (On-Demand vs Spot) does NOT change the container spec, so it shares the
    same job definition; only the compute environment / queue differ."""
    base = JOB_DEFINITION_NAMES.get(
        (model or "").strip().lower(), f"cryostack-{model}")
    if normalize_compute_mode(compute_mode) != COMPUTE_MODE_EC2:
        return base
    if normalize_ec2_topology(topology) == EC2_TOPOLOGY_MULTINODE:
        return f"{base}{EC2_MULTINODE_JOB_DEFINITION_SUFFIX}"
    if normalize_ec2_accelerator(accelerator) == EC2_ACCELERATOR_GPU:
        return f"{base}{EC2_GPU_JOB_DEFINITION_SUFFIX}"
    return f"{base}{EC2_JOB_DEFINITION_SUFFIX}"


def compute_environment_name(
    compute_mode: str | None = None, capacity: str | None = None,
) -> str:
    if normalize_compute_mode(compute_mode) != COMPUTE_MODE_EC2:
        return COMPUTE_ENVIRONMENT_NAME
    return (EC2_SPOT_COMPUTE_ENVIRONMENT_NAME
            if normalize_ec2_capacity(capacity) == EC2_CAPACITY_SPOT
            else EC2_COMPUTE_ENVIRONMENT_NAME)


def job_queue_name(compute_mode: str | None = None, capacity: str | None = None) -> str:
    if normalize_compute_mode(compute_mode) != COMPUTE_MODE_EC2:
        return JOB_QUEUE_NAME
    return (EC2_SPOT_JOB_QUEUE_NAME
            if normalize_ec2_capacity(capacity) == EC2_CAPACITY_SPOT
            else EC2_JOB_QUEUE_NAME)


# ── EC2 config dataclasses + payload builders (pure) ─────────────────────────
_MIN_EC2_MAX_VCPUS = 1
_MAX_EC2_MAX_VCPUS = 10000                    # AWS Batch hard limit is 1M; keep sane


@dataclass(frozen=True)
class EC2ComputeConfig:
    """The shape of the *managed EC2* Batch compute environment (Advanced).

    Every sub-mode defaults to the plain, validated case (On-Demand, no
    accelerator, single node, the discovered default VPC), so a bare
    ``EC2ComputeConfig()`` is exactly first-pass EC2. Each dimension is
    independent and orthogonal:

    * ``capacity``   -- On-Demand (default) or Spot. Changes the compute
      environment's ``type``/``allocationStrategy`` only -- never the
      container spec, so On-Demand and Spot queues share one job definition.
    * ``network``    -- ``"default"`` (the same discovered VPC/subnets/SGs
      Fargate uses) or ``"custom"``, which then reads ``vpc_id`` /
      ``subnet_ids`` / ``security_group_ids`` instead of discovery. No
      VPN/Direct Connect/Transit Gateway is created here -- this only lets
      CryoStack *use* a VPC that is already connected to wherever it needs
      to reach (e.g. a campus network for a FlexNet license server).
    * ``accelerator``/``gpu_count`` -- infra only; see
      :func:`ec2_gpu_resource_requirement`. Whether a job may actually
      *submit* with GPU depends on the container image (see
      ``cloud/compute_compatibility.py``), never on this dataclass alone.
    * ``topology``/``node_count`` -- infra only; see
      :func:`ec2_multinode_node_properties`. Whether a job may actually run
      distributed MPI is a scientific-runtime question, not a Batch one.
    """

    min_vcpus: int = 0
    desired_vcpus: int = 0
    max_vcpus: int = DEFAULT_MAX_VCPUS
    instance_types: tuple[str, ...] = DEFAULT_EC2_INSTANCE_TYPES
    allocation_strategy: str = DEFAULT_EC2_ALLOCATION_STRATEGY
    capacity: str = EC2_CAPACITY_ON_DEMAND
    network: str = EC2_NETWORK_DEFAULT
    vpc_id: str = ""
    subnet_ids: tuple[str, ...] = ()
    security_group_ids: tuple[str, ...] = ()
    accelerator: str = EC2_ACCELERATOR_NONE
    gpu_count: int = 1
    topology: str = EC2_TOPOLOGY_SINGLE
    node_count: int = 2

    @property
    def is_spot(self) -> bool:
        return normalize_ec2_capacity(self.capacity) == EC2_CAPACITY_SPOT

    @property
    def is_custom_network(self) -> bool:
        return normalize_ec2_network(self.network) == EC2_NETWORK_CUSTOM

    @property
    def is_gpu(self) -> bool:
        return normalize_ec2_accelerator(self.accelerator) == EC2_ACCELERATOR_GPU

    @property
    def is_multinode(self) -> bool:
        return normalize_ec2_topology(self.topology) == EC2_TOPOLOGY_MULTINODE


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
    if config.is_custom_network and not config.subnet_ids:
        raise ValueError(
            "EC2 custom network needs at least one subnet id (vpc_id/"
            "security_group_ids are optional but subnet_ids is not)")
    if config.is_multinode and not (_MIN_MULTINODE_NODES <= int(config.node_count)
                                     <= _MAX_MULTINODE_NODES):
        raise ValueError(
            f"EC2 multi-node node_count must be {_MIN_MULTINODE_NODES}-"
            f"{_MAX_MULTINODE_NODES}; got {config.node_count}")
    if config.is_gpu and int(config.gpu_count) < 1:
        raise ValueError(f"EC2 gpu_count must be >= 1; got {config.gpu_count}")


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
    environment.

    Network: when ``config.network == "custom"`` the caller's discovered
    ``subnets``/``security_groups`` are IGNORED in favour of
    ``config.subnet_ids``/``config.security_group_ids`` -- CryoStack places
    the environment into an already-connected VPC (e.g. one routed to a
    campus network) rather than the discovered default VPC. No VPN/transit
    gateway/NAT is created; the VPC must already have whatever route it
    needs.

    Capacity: ``config.capacity == "spot"`` sets ``type: "SPOT"`` and the
    Spot-specific allocation strategy (price+capacity optimized -- needs no
    separate EC2 Spot Fleet IAM role, unlike a launch-template Spot Fleet).

    ``instance_role_arn`` is the ECS **instance profile** ARN (the value
    Batch calls ``instanceRole``). No ``launchTemplate`` -- AWS Batch
    supplies the ECS-optimized (or ECS-GPU-optimized, for a GPU instance
    family) AMI automatically for a managed EC2 environment.
    """
    validate_ec2_compute_config(config)

    if config.is_custom_network:
        use_subnets = list(config.subnet_ids)
        use_sgs = list(config.security_group_ids)
    else:
        use_subnets = list(subnets)
        use_sgs = list(security_groups)

    if not use_subnets:
        raise ValueError("an EC2 compute environment needs at least one subnet")
    if not (instance_role_arn or "").strip():
        raise ValueError("an EC2 compute environment needs an ECS instance role")

    instance_types = (list(config.instance_types) if not config.is_gpu
                       else list(config.instance_types
                                 if config.instance_types != DEFAULT_EC2_INSTANCE_TYPES
                                 else DEFAULT_EC2_GPU_INSTANCE_TYPES))

    payload: dict = {
        "type": "SPOT" if config.is_spot else "EC2",
        "allocationStrategy": (DEFAULT_EC2_SPOT_ALLOCATION_STRATEGY if config.is_spot
                                else config.allocation_strategy),
        "minvCpus": int(config.min_vcpus),
        "desiredvCpus": int(config.desired_vcpus),
        "maxvCpus": int(config.max_vcpus),
        "instanceTypes": instance_types,
        "instanceRole": instance_role_arn,
        "subnets": use_subnets,
    }
    if use_sgs:
        payload["securityGroupIds"] = use_sgs
    return payload


def ec2_gpu_resource_requirement(config: EC2ComputeConfig) -> dict | None:
    """The ``resourceRequirements`` entry AWS Batch needs to schedule a
    container onto a GPU-attached EC2 host, or ``None`` when accelerator is
    ``"none"``. Infrastructure only -- see the module docstring / the
    ``compute_compatibility`` gate for whether a job may actually SUBMIT
    with this: it needs a CUDA-capable image, which
    ``bkyanjo/icesee-combined:v1.0.2`` is NOT (CPU-only build)."""
    if not config.is_gpu:
        return None
    return {"type": "GPU", "value": str(int(config.gpu_count))}


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
    compute: EC2ComputeConfig | None = None,
) -> dict:
    """``containerProperties`` for an **EC2** CryoStack job definition.

    Same image / command / roles / resourceRequirements / runtimePlatform /
    awslogs / Secrets Manager wiring as Fargate, minus every Fargate-only key:
    no ``networkConfiguration``, no ``fargatePlatformConfiguration``, no
    ``ephemeralStorage``. The MATLAB-license secret path (``executionRoleArn``
    + ``secrets``) is identical to Fargate.

    ``compute`` (optional) supplies the GPU resource requirement when its
    accelerator is ``"gpu"`` -- purely additive; never removes VCPU/MEMORY.
    """
    validate_ec2_job_config(config)
    if not image:
        raise ValueError("a job definition needs a container image reference")
    if not (job_role_arn and execution_role_arn):
        raise ValueError("job definition needs both a job role and an execution role")
    resource_requirements = [
        {"type": "VCPU", "value": str(config.vcpu)},
        {"type": "MEMORY", "value": str(config.memory_mib)},
    ]
    gpu_req = ec2_gpu_resource_requirement(compute) if compute is not None else None
    if gpu_req:
        resource_requirements.append(gpu_req)
    payload = {
        "image": image,
        "command": list(command or ["cryostack-run"]),
        "jobRoleArn": job_role_arn,
        "executionRoleArn": execution_role_arn,
        "resourceRequirements": resource_requirements,
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


def ec2_multinode_job_definition_payload(
    *,
    container_properties: dict,
    node_count: int,
    main_node_index: int = 0,
) -> dict:
    """The AWS Batch **multi-node parallel** job-definition body:
    ``nodeProperties`` wrapping ONE shared ``containerProperties`` across
    every node range (CryoStack does not yet vary per-node resources).

    Infrastructure only -- see the module docstring. Registering this job
    definition does not by itself make the scientific runtime launch MPI
    across nodes; ``cloud/compute_compatibility.py`` gates actual submission
    on the runtime having distributed-MPI support, which it does not today.
    """
    if int(node_count) < _MIN_MULTINODE_NODES:
        raise ValueError(
            f"multi-node parallel jobs need at least {_MIN_MULTINODE_NODES} "
            f"nodes; got {node_count}")
    return {
        "type": "multinode",
        "nodeProperties": {
            "numNodes": int(node_count),
            "mainNode": int(main_node_index),
            "nodeRangeProperties": [
                {
                    "targetNodes": f"0:{int(node_count) - 1}",
                    "container": container_properties,
                }
            ],
        },
    }


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


# ── centralized Fargate/EC2 compatibility matrix ─────────────────────────────
# Single source of truth for which compute-mode combinations are valid, so the
# rule set lives in ONE place instead of being scattered across the frontend,
# preflight and the provisioning layer. Both the UI (to grey out an invalid
# choice) and preflight (to block a submission) call the same function.

#: bkyanjo/icesee-combined:v1.0.2 has NO CUDA runtime -- verified: no
#: /usr/local/cuda, no nvidia-smi/nvcc, no CUDA libs, jaxlib 0.4.38 is the
#: CPU build. Flip this (or, better, make it a real per-image lookup) only
#: once a GPU-qualified image is registered. Never silently allow a CPU-only
#: image to accept a GPU job.
GPU_IMAGE_QUALIFIED = False

#: cloud/runtime.py's generic cloud runner and the ISSM/Icepack/ICESEE
#: runners have no AWS_BATCH_JOB_NODE_INDEX / distributed-MPI awareness
#: today (the ICESEE runner explicitly refuses NP>1 as unsafe -- see
#: icesee_jupyter_book/core/cloud_runner.py). Flip this only once a
#: distributed runner exists AND has been scientifically validated across
#: real Batch nodes.
MULTINODE_RUNTIME_SUPPORTED = False


class ComputeSelectionError(ValueError):
    """An invalid Fargate/EC2 compute-mode combination -- rejected before any
    AWS resource is touched, never silently coerced to something valid."""


def validate_compute_selection(
    compute_mode: str | None,
    ec2_config: EC2ComputeConfig | None = None,
    *,
    gpu_image_qualified: bool = GPU_IMAGE_QUALIFIED,
    multinode_runtime_supported: bool = MULTINODE_RUNTIME_SUPPORTED,
) -> list[str]:
    """Return the blocking reasons for this compute selection (empty list ==
    clear to submit). Never raises -- callers decide whether to raise, log,
    or grey out a UI control; :func:`assert_compute_selection` is the
    raise-on-block convenience wrapper.

    Fargate:      only the plain default is valid. Spot / GPU / custom
                  network / multi-node are EC2-only concepts and rejected
                  outright -- Fargate never sees them.
    EC2 On-Demand / Spot / custom network:
                  always valid (shape errors -- e.g. a custom network with no
                  subnet id -- surface via EC2ComputeConfig's own
                  validate_ec2_compute_config, folded in here).
    EC2 GPU:      valid as INFRASTRUCTURE; blocked from submission unless
                  ``gpu_image_qualified`` (false today -- v1.0.2 is CPU-only).
    EC2 multi-node:
                  valid as INFRASTRUCTURE; blocked from SCIENTIFIC submission
                  unless ``multinode_runtime_supported`` (false today -- no
                  distributed runner).
    """
    mode = normalize_compute_mode(compute_mode)
    cfg = ec2_config or EC2ComputeConfig()
    reasons: list[str] = []

    if mode != COMPUTE_MODE_EC2:
        if cfg.is_spot:
            reasons.append(
                "Spot capacity is an EC2-only option; not valid with Fargate.")
        if cfg.is_gpu:
            reasons.append("GPU is an EC2-only option; not valid with Fargate.")
        if cfg.is_custom_network:
            reasons.append(
                "Custom/private networking is an EC2-only option; not valid "
                "with Fargate.")
        if cfg.is_multinode:
            reasons.append(
                "Multi-node execution is an EC2-only option; not valid with "
                "Fargate.")
        return reasons

    try:
        validate_ec2_compute_config(cfg)
    except ValueError as err:
        reasons.append(str(err))

    if cfg.is_gpu and not gpu_image_qualified:
        reasons.append(
            "GPU infrastructure is configured, but the qualified CryoStack "
            "container image has no CUDA runtime. A GPU-qualified image is "
            "required before a GPU job can be submitted."
        )
    if cfg.is_multinode and not multinode_runtime_supported:
        reasons.append(
            "Multi-node infrastructure is configured, but CryoStack's "
            "scientific runners do not yet establish distributed MPI across "
            "AWS Batch nodes. Multi-node submission stays experimental/"
            "guarded until a distributed runner is validated."
        )
    return reasons


def assert_compute_selection(
    compute_mode: str | None,
    ec2_config: EC2ComputeConfig | None = None,
    **kwargs,
) -> None:
    """Raise :class:`ComputeSelectionError` for an invalid combination;
    no-op when the selection is clear to submit."""
    reasons = validate_compute_selection(compute_mode, ec2_config, **kwargs)
    if reasons:
        raise ComputeSelectionError(" ".join(reasons))
