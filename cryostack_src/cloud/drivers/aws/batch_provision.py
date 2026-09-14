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
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .auth import run_aws
from .batch import AWSBatchResources, discover_batch_resources
from .batch_config import (
    COMPUTE_ENVIRONMENT_NAME,
    COMPUTE_MODE_EC2,
    DEFAULT_EC2_JOB_CONFIG,
    DEFAULT_ISSM_JOB_CONFIG,
    DEFAULT_MAX_VCPUS,
    EC2_COMPUTE_ENVIRONMENT_NAME,
    EC2_JOB_QUEUE_NAME,
    JOB_QUEUE_NAME,
    JOB_QUEUE_PRIORITY,
    LOG_RETENTION_DAYS,
    EC2ComputeConfig,
    EC2JobConfig,
    FargateJobConfig,
    compute_environment_name,
    compute_resources_payload,
    container_properties_payload,
    ec2_compute_resources_payload,
    ec2_container_properties_payload,
    ec2_multinode_job_definition_payload,
    job_definition_fingerprint,
    job_definition_name,
    job_queue_name,
    log_group_name,
    normalize_compute_mode,
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
    #: same, for the Icepack tested-image delivery when requested
    #: (``include_icepack=True``); ``None`` when Icepack wasn't prepared.
    icepack_image_delivery: object | None = None
    #: same, for the ICESEE tested-image delivery when requested
    #: (``include_icesee=True``); ``None`` when ICESEE wasn't prepared.
    icesee_image_delivery: object | None = None


def _require_success(code: int, stdout: str, stderr: str, *, what: str) -> str:
    if code != 0:
        raise RuntimeError((stderr or stdout).strip() or f"{what} failed.")
    return stdout


# ── Batch resource readiness polling ─────────────────────────────────────
# AWS brings a compute environment / job queue to ``status == VALID``
# asynchronously after a create or update. Attaching a job queue to a
# still-transitioning compute environment fails with
#   "Compute Environment ... is not valid. It must be valid before attaching
#    it to the job queue."
# The fix is to poll ``describe-*`` until VALID -- never a fixed sleep.
BATCH_READY_INTERVAL_SECONDS = 10        # between describe-* polls
BATCH_READY_TIMEOUT_SECONDS = 300        # CE VALID is usually < 60s; queue < 30s


class BatchResourceNotReady(RuntimeError):
    """A Batch compute environment / job queue did not reach ``VALID``."""


def _poll_batch_status(
    describe: Callable[[], dict | None],
    *,
    what: str,
    interval: float = BATCH_READY_INTERVAL_SECONDS,
    timeout: float = BATCH_READY_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Poll ``describe()`` (returns the resource dict, or ``None`` if a lookup
    momentarily failed) until its ``status`` is ``VALID``.

    * ``VALID``   -> return the resource dict;
    * ``INVALID`` -> raise :class:`BatchResourceNotReady` with ``statusReason``;
    * deadline    -> raise with the last observed ``state`` / ``status`` /
      ``statusReason``.

    Deterministic for tests: the number of describe attempts is
    ``timeout // interval + 1`` and ``sleep`` is injectable.
    """
    attempts = max(1, int(timeout // max(1e-9, interval)) + 1)
    last: dict = {}
    for i in range(attempts):
        res = describe() or None
        if res:
            last = res
        status = (last.get("status") or "").upper()
        if status == "VALID":
            return last
        if status == "INVALID":
            raise BatchResourceNotReady(
                f"{what} is INVALID: "
                f"{last.get('statusReason') or 'no reason reported'}")
        if i < attempts - 1:
            sleep(interval)
    raise BatchResourceNotReady(
        f"{what} did not become VALID within ~{int(timeout)}s "
        f"(last state={last.get('state')!r} status={last.get('status')!r} "
        f"reason={last.get('statusReason') or 'none'})")


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
def _current_compute_environment(
    config: AWSConfig, name: str = COMPUTE_ENVIRONMENT_NAME,
) -> dict | None:
    payload = _describe(
        config,
        ["batch", "describe-compute-environments",
         "--compute-environments", name],
    )
    envs = payload.get("computeEnvironments", [])
    return envs[0] if envs else None


def ensure_compute_environment(
    config: AWSConfig,
    *,
    subnets: list[str],
    security_groups: list[str],
    max_vcpus: int = DEFAULT_MAX_VCPUS,
    ready_interval: float = BATCH_READY_INTERVAL_SECONDS,
    ready_timeout: float = BATCH_READY_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Return one of ``created`` / ``updated`` / ``reused``.

    In every case the compute environment is ``VALID`` before this returns --
    a fresh one is still transitioning right after ``create``, and a reused one
    may be mid-``UPDATING`` from an earlier aborted run. A queue cannot be
    attached to a non-``VALID`` compute environment.
    """
    what = f"compute environment {COMPUTE_ENVIRONMENT_NAME}"

    def _wait() -> None:
        _poll_batch_status(
            lambda: _current_compute_environment(config), what=what,
            interval=ready_interval, timeout=ready_timeout, sleep=sleep,
        )

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
        _wait()
        return "created"

    cr = current.get("computeResources") or {}
    drift = (
        int(cr.get("maxvCpus", -1)) != int(desired["maxvCpus"])
        or set(cr.get("subnets") or []) != set(desired["subnets"])
        or set(cr.get("securityGroupIds") or []) != set(desired.get("securityGroupIds") or [])
    )
    if not drift:
        if (current.get("status") or "").upper() != "VALID":
            _wait()                       # transitioning from a prior partial run
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
    _wait()
    return "updated"


#: infix that appears ONLY in AWS Batch's own service-linked role ARN
#: (``arn:aws:iam::<account>:role/aws-service-role/batch.amazonaws.com/
#: AWSServiceRoleForBatch``) -- never in a regular IAM role such as
#: CryoStack's own ``cryostack-batch-service-role``.
_BATCH_SERVICE_LINKED_ROLE_INFIX = "/aws-service-role/batch.amazonaws.com/"


def _is_batch_service_linked_role(service_role: str | None) -> bool:
    """AWS Batch only allows ``UpdateComputeEnvironment`` to touch a MANAGED
    compute environment's infrastructure fields (``instanceRole``/
    ``instanceTypes``/``allocationStrategy``/``subnets``/
    ``securityGroupIds``/...) when it runs on ITS OWN service-linked role.
    On one created with an explicit regular IAM role (e.g. CryoStack's own
    ``cryostack-batch-service-role``), every such update is rejected:
    ``ClientException: ... can be updated only for Non-fargate Compute
    Environment having a Batch Service Linked Role``."""
    return _BATCH_SERVICE_LINKED_ROLE_INFIX in (service_role or "")


def _poll_until_state(
    describe: Callable[[], dict | None], *, state: str, what: str,
    interval: float, timeout: float, sleep: Callable[[float], None],
) -> dict:
    """Poll until ``describe()`` reports ``state`` (e.g. ``"DISABLED"``) with
    ``status == "VALID"`` -- the same VALID-before-proceeding rule as
    :func:`_poll_batch_status`, but for a state transition rather than a
    fresh create/update settling."""
    attempts = max(1, int(timeout // max(1e-9, interval)) + 1)
    last: dict = {}
    for i in range(attempts):
        res = describe() or None
        if res:
            last = res
        if ((last.get("state") or "").upper() == state.upper()
                and (last.get("status") or "").upper() == "VALID"):
            return last
        if (last.get("status") or "").upper() == "INVALID":
            raise BatchResourceNotReady(
                f"{what} is INVALID: "
                f"{last.get('statusReason') or 'no reason reported'}")
        if i < attempts - 1:
            sleep(interval)
    raise BatchResourceNotReady(
        f"{what} did not reach state={state} within ~{int(timeout)}s "
        f"(last state={last.get('state')!r} status={last.get('status')!r})")


def _poll_until_gone(
    describe: Callable[[], dict | None], *, what: str,
    interval: float, timeout: float, sleep: Callable[[float], None],
) -> None:
    """Poll until ``describe()`` returns ``None`` -- AWS Batch deletes a
    compute environment / job queue asynchronously."""
    attempts = max(1, int(timeout // max(1e-9, interval)) + 1)
    for i in range(attempts):
        if describe() is None:
            return
        if i < attempts - 1:
            sleep(interval)
    raise BatchResourceNotReady(f"{what} was not deleted within ~{int(timeout)}s")


def _replace_legacy_ec2_compute_environment(
    config: AWSConfig, *, name: str, ec2_config: EC2ComputeConfig,
    ready_interval: float, ready_timeout: float,
    sleep: Callable[[float], None],
) -> None:
    """Blue/green replacement for an EC2 compute environment that was
    created with a regular IAM role instead of AWS Batch's service-linked
    role (see :func:`_is_batch_service_linked_role`) -- AWS Batch never
    allows updating such an environment's infrastructure fields in place, so
    the only supported fix is: detach it from its job queue, delete the
    queue, delete the compute environment, and let the caller
    (:func:`ensure_ec2_compute_environment`) recreate both fresh (which
    never passes a custom service role, so AWS Batch uses/creates the
    service-linked role).

    Scoped strictly to the CryoStack-owned compute-environment name passed
    in (``name``) and the queue name AWS Batch's own
    ``computeEnvironmentOrder`` says references it -- never touches any
    other Batch resource, and this function only ever runs after the caller
    has already confirmed ``name`` is a legacy-role environment.
    """
    queue_name = job_queue_name(COMPUTE_MODE_EC2, ec2_config.capacity)
    q_what = f"job queue {queue_name}"
    ce_what = f"compute environment {name}"

    queue = _current_job_queue(config, queue_name)
    if queue is not None and name in _compute_env_in_order(
            queue.get("computeEnvironmentOrder")):
        if (queue.get("state") or "").upper() != "DISABLED":
            code, stdout, stderr = run_aws(
                config, ["batch", "update-job-queue",
                         "--job-queue", queue_name, "--state", "DISABLED"])
            _require_success(
                code, stdout, stderr, what="batch update-job-queue (disable)")
        _poll_until_state(
            lambda: _current_job_queue(config, queue_name), state="DISABLED",
            what=q_what, interval=ready_interval, timeout=ready_timeout,
            sleep=sleep,
        )
        code, stdout, stderr = run_aws(
            config, ["batch", "delete-job-queue", "--job-queue", queue_name])
        _require_success(code, stdout, stderr, what="batch delete-job-queue")
        _poll_until_gone(
            lambda: _current_job_queue(config, queue_name), what=q_what,
            interval=ready_interval, timeout=ready_timeout, sleep=sleep,
        )

    current = _current_compute_environment(config, name)
    if current is not None:
        if (current.get("state") or "").upper() != "DISABLED":
            code, stdout, stderr = run_aws(
                config, ["batch", "update-compute-environment",
                         "--compute-environment", name, "--state", "DISABLED"])
            _require_success(
                code, stdout, stderr,
                what="batch update-compute-environment (disable)")
        _poll_until_state(
            lambda: _current_compute_environment(config, name),
            state="DISABLED", what=ce_what, interval=ready_interval,
            timeout=ready_timeout, sleep=sleep,
        )
        code, stdout, stderr = run_aws(
            config, ["batch", "delete-compute-environment",
                     "--compute-environment", name])
        _require_success(code, stdout, stderr, what="batch delete-compute-environment")
        _poll_until_gone(
            lambda: _current_compute_environment(config, name), what=ce_what,
            interval=ready_interval, timeout=ready_timeout, sleep=sleep,
        )


def ensure_ec2_compute_environment(
    config: AWSConfig,
    *,
    subnets: list[str],
    security_groups: list[str],
    instance_role_arn: str,
    ec2_config: EC2ComputeConfig = EC2ComputeConfig(),
    name: str | None = None,
    ready_interval: float = BATCH_READY_INTERVAL_SECONDS,
    ready_timeout: float = BATCH_READY_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Managed EC2 (scale-to-zero) compute environment. Defaults to
    ``cryostack-ec2``; the caller passes ``cryostack-ec2-spot`` for Spot
    capacity so On-Demand and Spot environments never collide or overwrite
    each other's ``type``/``allocationStrategy``.

    Never passes an explicit ``--service-role``: AWS Batch's recommended,
    supported behaviour for a MANAGED compute environment is to use/create
    its own service-linked role (``AWSServiceRoleForBatch``), which is also
    the ONLY role AWS Batch will let an in-place ``UpdateComputeEnvironment``
    touch infrastructure fields on (see
    :func:`_is_batch_service_linked_role`). If an existing environment under
    this name was created with a regular IAM role instead (a stale/legacy
    environment from before this was fixed), it is migrated -- deleted and
    recreated -- via :func:`_replace_legacy_ec2_compute_environment` rather
    than sent an update AWS is guaranteed to reject.

    Separate from the Fargate compute environment -- never renamed / reused /
    overwritten. Returns ``created`` / ``updated`` / ``reused`` /
    ``migrated``, VALID before it returns. Drift = maxvCpus / subnets /
    security groups / instance types / instance role.
    """
    name = name or EC2_COMPUTE_ENVIRONMENT_NAME
    what = f"compute environment {name}"

    def _wait() -> None:
        _poll_batch_status(
            lambda: _current_compute_environment(config, name), what=what,
            interval=ready_interval, timeout=ready_timeout, sleep=sleep,
        )

    desired = ec2_compute_resources_payload(
        subnets=subnets, security_groups=security_groups,
        instance_role_arn=instance_role_arn, config=ec2_config,
    )
    current = _current_compute_environment(config, name)

    migrated = False
    if current is not None and not _is_batch_service_linked_role(
            current.get("serviceRole")):
        _replace_legacy_ec2_compute_environment(
            config, name=name, ec2_config=ec2_config,
            ready_interval=ready_interval, ready_timeout=ready_timeout,
            sleep=sleep,
        )
        current = None
        migrated = True

    if current is None:
        args = [
            "batch", "create-compute-environment",
            "--compute-environment-name", name,
            "--type", "MANAGED",
            "--state", "ENABLED",
            "--compute-resources", json.dumps(desired),
        ]
        code, stdout, stderr = run_aws(config, args)
        _require_success(code, stdout, stderr, what="batch create-compute-environment")
        _wait()
        return "migrated" if migrated else "created"

    cr = current.get("computeResources") or {}
    drift = (
        int(cr.get("maxvCpus", -1)) != int(desired["maxvCpus"])
        or set(cr.get("subnets") or []) != set(desired["subnets"])
        or set(cr.get("securityGroupIds") or []) != set(desired.get("securityGroupIds") or [])
        or list(cr.get("instanceTypes") or []) != list(desired["instanceTypes"])
    )
    if not drift:
        if (current.get("status") or "").upper() != "VALID":
            _wait()
        return "reused"

    code, stdout, stderr = run_aws(
        config,
        [
            "batch", "update-compute-environment",
            "--compute-environment", name,
            "--state", "ENABLED",
            "--compute-resources", json.dumps({
                "minvCpus": desired["minvCpus"],
                "desiredvCpus": desired["desiredvCpus"],
                "maxvCpus": desired["maxvCpus"],
                "instanceTypes": desired["instanceTypes"],
                "subnets": desired["subnets"],
                **({"securityGroupIds": desired["securityGroupIds"]}
                   if desired.get("securityGroupIds") else {}),
            }),
        ],
    )
    _require_success(code, stdout, stderr, what="batch update-compute-environment")
    _wait()
    return "updated"


# ── job queue ─────────────────────────────────────────────────────────────
def _current_job_queue(
    config: AWSConfig, name: str = JOB_QUEUE_NAME,
) -> dict | None:
    payload = _describe(
        config,
        ["batch", "describe-job-queues", "--job-queues", name],
    )
    queues = payload.get("jobQueues", [])
    return queues[0] if queues else None


def _compute_env_in_order(order: list[dict]) -> set[str]:
    names: set[str] = set()
    for entry in order or []:
        ref = entry.get("computeEnvironment") or ""
        names.add(ref.rsplit("/", 1)[-1])          # accept ARN or bare name
    return names


def ensure_job_queue(
    config: AWSConfig,
    *,
    name: str = JOB_QUEUE_NAME,
    compute_environment: str = COMPUTE_ENVIRONMENT_NAME,
    ready_interval: float = BATCH_READY_INTERVAL_SECONDS,
    ready_timeout: float = BATCH_READY_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Return one of ``created`` / ``updated`` / ``reused``.

    Requires the bound compute environment to be ``VALID`` first (AWS rejects a
    ``create-job-queue`` otherwise), and polls the queue itself to ``VALID``
    before returning. ``name`` / ``compute_environment`` default to the Fargate
    pair; the EC2 queue passes its own (``cryostack-ec2-queue`` ->
    ``cryostack-ec2``) so the two never share ordering.
    """
    what = f"job queue {name}"

    def _wait_queue() -> None:
        _poll_batch_status(
            lambda: _current_job_queue(config, name), what=what,
            interval=ready_interval, timeout=ready_timeout, sleep=sleep,
        )

    ce_order = [{"order": 1, "computeEnvironment": compute_environment}]
    current = _current_job_queue(config, name)

    if current is None:
        # defensive: the CE must be VALID before it can be attached
        ce = _current_compute_environment(config, compute_environment)
        if (ce or {}).get("status", "").upper() != "VALID":
            _poll_batch_status(
                lambda: _current_compute_environment(config, compute_environment),
                what=f"compute environment {compute_environment}",
                interval=ready_interval, timeout=ready_timeout, sleep=sleep,
            )
        code, stdout, stderr = run_aws(
            config,
            [
                "batch", "create-job-queue",
                "--job-queue-name", name,
                "--state", "ENABLED",
                "--priority", str(JOB_QUEUE_PRIORITY),
                "--compute-environment-order", json.dumps(ce_order),
            ],
        )
        _require_success(code, stdout, stderr, what="batch create-job-queue")
        _wait_queue()
        return "created"

    drift = (
        int(current.get("priority", -1)) != JOB_QUEUE_PRIORITY
        or compute_environment not in _compute_env_in_order(
            current.get("computeEnvironmentOrder"))
        or (current.get("state") or "").upper() != "ENABLED"
    )
    if not drift:
        if (current.get("status") or "").upper() != "VALID":
            _wait_queue()
        return "reused"

    code, stdout, stderr = run_aws(
        config,
        [
            "batch", "update-job-queue",
            "--job-queue", name,
            "--state", "ENABLED",
            "--priority", str(JOB_QUEUE_PRIORITY),
            "--compute-environment-order", json.dumps(ce_order),
        ],
    )
    _require_success(code, stdout, stderr, what="batch update-job-queue")
    _wait_queue()
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
    job_config: FargateJobConfig | EC2JobConfig = DEFAULT_ISSM_JOB_CONFIG,
    command: list[str] | None = None,
    secrets: list[dict] | None = None,
    compute_mode: str = "fargate",
    compute: "EC2ComputeConfig | None" = None,
) -> str:
    """Register (or reuse) a model's job definition.

    ``compute_mode`` selects the platform: ``"fargate"`` (default -- unchanged
    behaviour, name ``cryostack-<model>``, ``--platform-capabilities FARGATE``,
    Fargate ``containerProperties``) or ``"ec2"`` (EC2 ``containerProperties``
    with no Fargate-only keys). The Secrets Manager MATLAB-license path, the
    image digest and the container command are identical for both.

    ``compute`` (EC2 only) is the full :class:`EC2ComputeConfig` -- its
    ``accelerator``/``topology`` pick the deterministic job-definition name
    and whether this registers a plain single-container job or an AWS Batch
    **multi-node parallel** one (``--type multinode``). Capacity (On-Demand
    vs Spot) does NOT affect the job definition -- only the compute
    environment/queue it is submitted to.
    """
    is_ec2 = normalize_compute_mode(compute_mode) == COMPUTE_MODE_EC2
    ec2_cfg = compute if (is_ec2 and compute is not None) else None
    name = job_definition_name(
        model, compute_mode,
        accelerator=(ec2_cfg.accelerator if ec2_cfg else None),
        topology=(ec2_cfg.topology if ec2_cfg else None),
    )
    platform_capability = "EC2" if is_ec2 else "FARGATE"
    is_multinode = bool(ec2_cfg and ec2_cfg.is_multinode)

    if is_ec2:
        if not isinstance(job_config, EC2JobConfig):
            job_config = DEFAULT_EC2_JOB_CONFIG
        desired_cp = ec2_container_properties_payload(
            model=model, image=image, job_role_arn=job_role_arn,
            execution_role_arn=execution_role_arn, region=region,
            config=job_config, command=command, secrets=secrets,
            compute=ec2_cfg,
        )
    else:
        desired_cp = container_properties_payload(
            model=model, image=image, job_role_arn=job_role_arn,
            execution_role_arn=execution_role_arn, region=region,
            config=job_config, command=command, secrets=secrets,
        )
    desired_fp = job_definition_fingerprint(
        container_properties=desired_cp,
        timeout_seconds=job_config.timeout_seconds,
        attempts=job_config.attempts,
    )
    if is_multinode:
        desired_fp["numNodes"] = int(ec2_cfg.node_count)

    def _existing_container_properties(revision: dict) -> dict:
        node_props = revision.get("nodeProperties") or {}
        ranges = node_props.get("nodeRangeProperties") or []
        if ranges:
            return ranges[0].get("container") or {}
        return revision.get("containerProperties") or {}

    for revision in sorted(
        _active_job_definitions(config, name),
        key=lambda r: int(r.get("revision", 0)), reverse=True,
    ):
        existing_fp = job_definition_fingerprint(
            container_properties=_existing_container_properties(revision),
            timeout_seconds=int(
                (revision.get("timeout") or {}).get("attemptDurationSeconds", 0)),
            attempts=int((revision.get("retryStrategy") or {}).get("attempts", 1)),
        )
        if is_multinode:
            existing_fp["numNodes"] = int(
                (revision.get("nodeProperties") or {}).get("numNodes", -1))
        if existing_fp == desired_fp:
            return "reused"
        break  # only the latest revision matters

    args = [
        "batch", "register-job-definition",
        "--job-definition-name", name,
        "--platform-capabilities", platform_capability,
        "--timeout", json.dumps(
            {"attemptDurationSeconds": int(job_config.timeout_seconds)}),
        "--retry-strategy", json.dumps({"attempts": int(job_config.attempts)}),
    ]
    if is_multinode:
        node_body = ec2_multinode_job_definition_payload(
            container_properties=desired_cp, node_count=ec2_cfg.node_count)
        args += [
            "--type", "multinode",
            "--node-properties", json.dumps(node_body["nodeProperties"]),
        ]
    else:
        args += [
            "--type", "container",
            "--container-properties", json.dumps(desired_cp),
        ]

    code, stdout, stderr = run_aws(config, args)
    _require_success(code, stdout, stderr, what="batch register-job-definition")
    return "created"


# ── orchestration ─────────────────────────────────────────────────────────
@dataclass
class EC2Provisioning:
    """Everything :func:`ensure_batch_resources` needs to *additionally* stand
    up the Advanced EC2 compute environment / queue / ``-ec2`` job definitions.

    Passed ONLY when the user selected EC2 mode. When ``None`` the function is
    byte-for-byte the Fargate-only path it has always been.
    """

    instance_role_arn: str
    ec2_config: EC2ComputeConfig = field(default_factory=EC2ComputeConfig)
    issm_job_config: EC2JobConfig | None = None
    icepack_job_config: EC2JobConfig | None = None
    icesee_job_config: EC2JobConfig | None = None


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
    job_command: list[str] | None = None,
    issm_secrets: list[dict] | None = None,
    include_icepack: bool = False,
    icepack_image: str | None = None,
    icepack_job_config: FargateJobConfig | None = None,
    include_icesee: bool = False,
    icesee_image: str | None = None,
    icesee_job_config: FargateJobConfig | None = None,
    icesee_command: list[str] | None = None,
    ec2: EC2Provisioning | None = None,
    ready_interval: float = BATCH_READY_INTERVAL_SECONDS,
    ready_timeout: float = BATCH_READY_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> AWSBatchProvisionResult:
    """Prepare CryoStack's AWS Batch environment, idempotently.

    The **Fargate** compute environment / queue / job definitions are ALWAYS
    provisioned (unchanged), so a Fargate <-> EC2 switch never needs a
    re-prepare of the default path. When ``ec2`` is supplied, the Advanced EC2
    compute environment (``cryostack-ec2``), its own queue
    (``cryostack-ec2-queue``) and ``cryostack-<model>-ec2`` job definitions are
    provisioned in ADDITION -- never in place of -- the Fargate ones.

    The compute environment is waited to ``VALID`` before the queue is
    created/attached, and the queue is waited to ``VALID`` before the job
    definitions are registered. ``ready_interval`` / ``ready_timeout`` /
    ``sleep`` make the polling deterministic for tests.
    """
    result = AWSBatchProvisionResult(resources=None)  # type: ignore[arg-type]

    if not subnets:
        result.skipped.append("batch (no usable subnets discovered)")
        result.messages.append(
            "AWS Batch provisioning skipped: no subnets in the default VPC.")
        result.resources = discover_batch_resources(config)
        return result

    def _bucket(name: str, outcome: str) -> None:
        if outcome == "migrated":
            result.updated.append(name)
            result.messages.append(
                f"{name}: replaced (was using a custom Batch service role; "
                "recreated on the AWS Batch service-linked role)"
            )
            return
        {"created": result.created, "updated": result.updated,
         "reused": result.reused}[outcome].append(name)

    _ready = dict(ready_interval=ready_interval, ready_timeout=ready_timeout,
                  sleep=sleep)

    # 1. compute environment (Fargate -- scale to zero); waited to VALID
    _bucket("compute_environment", ensure_compute_environment(
        config, subnets=subnets, security_groups=security_groups,
        max_vcpus=max_vcpus, **_ready,
    ))

    # 2. job queue -- only attached once the CE is VALID; waited to VALID
    _bucket("job_queue", ensure_job_queue(config, **_ready))

    # 3. per-model job definitions (+ their log groups)
    if job_role_arn and execution_role_arn and issm_image:
        result.log_groups.append(ensure_log_group(config, model="issm"))
        _bucket("issm_job_definition", ensure_job_definition(
            config, model="issm", image=issm_image, job_role_arn=job_role_arn,
            execution_role_arn=execution_role_arn, region=config.region,
            job_config=issm_job_config, command=job_command,
            secrets=issm_secrets,   # ISSM MATLAB license (Secrets Manager ARN)
        ))
    else:
        result.skipped.append(
            "issm_job_definition (needs job role, execution role and an image)")

    if include_icepack:
        if job_role_arn and execution_role_arn and icepack_image:
            result.log_groups.append(ensure_log_group(config, model="icepack"))
            _bucket("icepack_job_definition", ensure_job_definition(
                config, model="icepack", image=icepack_image, job_role_arn=job_role_arn,
                execution_role_arn=execution_role_arn, region=config.region,
                job_config=icepack_job_config or DEFAULT_ISSM_JOB_CONFIG,
                command=job_command,
            ))
        else:
            result.skipped.append(
                "icepack_job_definition (needs job role, execution role and an image)")

    if include_icesee:
        if job_role_arn and execution_role_arn and icesee_image:
            result.log_groups.append(ensure_log_group(config, model="icesee"))
            _bucket("icesee_job_definition", ensure_job_definition(
                config, model="icesee", image=icesee_image, job_role_arn=job_role_arn,
                execution_role_arn=execution_role_arn, region=config.region,
                job_config=icesee_job_config or DEFAULT_ISSM_JOB_CONFIG,
                # ICESEE is not one of cryostack_src.cloud.runtime's
                # SUPPORTED_CLOUD_MODELS and never shares the generic
                # `job_command` (CRYOSTACK_* env contract) ISSM/Icepack use --
                # it needs its own ICESEE_* env-var-driven command, passed in
                # by the caller (icesee_jupyter_book.core.cloud_runner's
                # icesee_batch_command()).
                command=icesee_command,
            ))
        else:
            result.skipped.append(
                "icesee_job_definition (needs job role, execution role and an image)")

    # 4. Advanced: EC2 compute environment + queue + -ec2 job definitions.
    #    Only when the user selected EC2 mode; never touches the Fargate
    #    resources above. Shares the model log groups (same /cryostack/batch/
    #    <model>), the ECR image, the job role, the ECS execution role (so the
    #    MATLAB Secrets Manager grant is reused unchanged) and the container
    #    command.
    if ec2 is not None:
        if not (ec2.instance_role_arn or "").strip():
            result.skipped.append(
                "ec2 batch (no ECS instance profile -- run IAM prepare first)")
        else:
            _ec2_cfg = ec2.ec2_config
            _ce_name = compute_environment_name(COMPUTE_MODE_EC2, _ec2_cfg.capacity)
            _q_name = job_queue_name(COMPUTE_MODE_EC2, _ec2_cfg.capacity)
            _ce_label = "ec2_spot_compute_environment" if _ec2_cfg.is_spot \
                else "ec2_compute_environment"
            _q_label = "ec2_spot_job_queue" if _ec2_cfg.is_spot else "ec2_job_queue"

            _bucket(_ce_label, ensure_ec2_compute_environment(
                config,
                # custom network: the caller's discovered subnets/SGs are
                # overridden inside ec2_compute_resources_payload itself when
                # _ec2_cfg.network == "custom" -- always pass discovery
                # through so the default path is unaffected.
                subnets=subnets, security_groups=security_groups,
                instance_role_arn=ec2.instance_role_arn,
                ec2_config=_ec2_cfg, name=_ce_name, **_ready,
            ))
            _bucket(_q_label, ensure_job_queue(
                config, name=_q_name, compute_environment=_ce_name, **_ready,
            ))
            _ec2_defaults = DEFAULT_EC2_JOB_CONFIG
            _jd_suffix = ("_ec2_gpu" if _ec2_cfg.is_gpu
                          else "_ec2_mnp" if _ec2_cfg.is_multinode else "_ec2")
            if job_role_arn and execution_role_arn and issm_image:
                _bucket(f"issm_job_definition{_jd_suffix}", ensure_job_definition(
                    config, model="issm", image=issm_image,
                    job_role_arn=job_role_arn,
                    execution_role_arn=execution_role_arn, region=config.region,
                    job_config=ec2.issm_job_config or _ec2_defaults,
                    command=job_command, secrets=issm_secrets,
                    compute_mode=COMPUTE_MODE_EC2, compute=_ec2_cfg,
                ))
            if include_icepack and job_role_arn and execution_role_arn and icepack_image:
                _bucket(f"icepack_job_definition{_jd_suffix}", ensure_job_definition(
                    config, model="icepack", image=icepack_image,
                    job_role_arn=job_role_arn,
                    execution_role_arn=execution_role_arn, region=config.region,
                    job_config=ec2.icepack_job_config or _ec2_defaults,
                    command=job_command, compute_mode=COMPUTE_MODE_EC2,
                    compute=_ec2_cfg,
                ))
            if include_icesee and job_role_arn and execution_role_arn and icesee_image:
                _bucket(f"icesee_job_definition{_jd_suffix}", ensure_job_definition(
                    config, model="icesee", image=icesee_image,
                    job_role_arn=job_role_arn,
                    execution_role_arn=execution_role_arn, region=config.region,
                    job_config=ec2.icesee_job_config or _ec2_defaults,
                    command=icesee_command, compute_mode=COMPUTE_MODE_EC2,
                    compute=_ec2_cfg,
                ))

    result.resources = discover_batch_resources(config)
    return result
