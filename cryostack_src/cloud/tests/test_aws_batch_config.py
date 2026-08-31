"""Cloud Commit 1 -- Fargate job/compute configuration (pure, no AWS calls)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryostack_src.cloud.drivers.aws.batch_config import (
    COMPUTE_ENVIRONMENT_NAME,
    DEFAULT_ISSM_JOB_CONFIG,
    DEFAULT_MAX_VCPUS,
    FargateJobConfig,
    compute_resources_payload,
    container_properties_payload,
    job_definition_fingerprint,
    job_definition_name,
    log_group_name,
    validate_fargate_job_config,
)


# ── deterministic names ──────────────────────────────────────────────────
def test_names_are_deterministic():
    assert COMPUTE_ENVIRONMENT_NAME == "cryostack-fargate"
    assert job_definition_name("issm") == "cryostack-issm"
    assert job_definition_name("icepack") == "cryostack-icepack"
    assert log_group_name("  ISSM ") == "/cryostack/batch/issm"


# ── config validation ────────────────────────────────────────────────────
def test_default_config_is_valid():
    validate_fargate_job_config(DEFAULT_ISSM_JOB_CONFIG)
    assert DEFAULT_ISSM_JOB_CONFIG.timeout_seconds == 3600      # mandatory bound
    assert DEFAULT_ISSM_JOB_CONFIG.attempts == 1               # no silent retries


@pytest.mark.parametrize("bad", [
    {"vcpu": "3"},                       # not a Fargate vCPU value
    {"vcpu": "2", "memory_mib": "5000"},  # not a 1024 step for 2 vCPU
    {"vcpu": "2", "memory_mib": "1024"},  # below the 2-vCPU minimum
    {"ephemeral_gib": 10},               # below Fargate's 21 GiB floor
    {"ephemeral_gib": 500},              # above the 200 GiB ceiling
    {"timeout_seconds": 30},             # a job must have a real timeout
    {"attempts": 0},
])
def test_invalid_configs_are_rejected(bad):
    with pytest.raises(ValueError):
        validate_fargate_job_config(FargateJobConfig(**bad))


# ── compute environment (scale to zero) ─────────────────────────────────
def test_compute_resources_is_fargate_scale_to_zero():
    cr = compute_resources_payload(
        subnets=["subnet-a", "subnet-b"], security_groups=["sg-1"],
    )
    assert cr["type"] == "FARGATE"
    assert cr["maxvCpus"] == DEFAULT_MAX_VCPUS
    assert cr["subnets"] == ["subnet-a", "subnet-b"]
    assert cr["securityGroupIds"] == ["sg-1"]
    # nothing that would keep EC2 / capacity warm
    for forbidden in ("minvCpus", "desiredvCpus", "instanceTypes", "instanceRole"):
        assert forbidden not in cr


def test_compute_resources_requires_a_subnet():
    with pytest.raises(ValueError):
        compute_resources_payload(subnets=[], security_groups=[])


# ── container properties ────────────────────────────────────────────────
def test_container_properties_has_every_mandatory_field():
    cp = container_properties_payload(
        model="issm", image="123.dkr.ecr.us-east-2.amazonaws.com/cryostack-issm:tested",
        job_role_arn="arn:aws:iam::123:role/CryoStackJobRole",
        execution_role_arn="arn:aws:iam::123:role/CryoStackExecutionRole",
        region="us-east-2",
    )
    assert cp["jobRoleArn"].endswith("CryoStackJobRole")
    assert cp["executionRoleArn"].endswith("CryoStackExecutionRole")
    assert cp["ephemeralStorage"]["sizeInGiB"] == 50
    assert cp["networkConfiguration"]["assignPublicIp"] == "ENABLED"
    assert cp["fargatePlatformConfiguration"]["platformVersion"] == "LATEST"
    assert cp["logConfiguration"]["logDriver"] == "awslogs"
    assert cp["logConfiguration"]["options"]["awslogs-group"] == "/cryostack/batch/issm"
    assert {"type": "VCPU", "value": "2"} in cp["resourceRequirements"]
    assert {"type": "MEMORY", "value": "8192"} in cp["resourceRequirements"]


@pytest.mark.parametrize("kw", [
    {"image": ""},
    {"job_role_arn": ""},
    {"execution_role_arn": ""},
])
def test_container_properties_requires_image_and_roles(kw):
    base = dict(
        model="issm", image="x:tested", job_role_arn="arn:job",
        execution_role_arn="arn:exec", region="us-east-2",
    )
    base.update(kw)
    with pytest.raises(ValueError):
        container_properties_payload(**base)


# ── drift fingerprint ───────────────────────────────────────────────────
def test_fingerprint_is_order_independent():
    cp_a = container_properties_payload(
        model="issm", image="x:tested", job_role_arn="arn:job",
        execution_role_arn="arn:exec", region="us-east-2")
    cp_b = dict(cp_a)
    cp_b["resourceRequirements"] = list(reversed(cp_a["resourceRequirements"]))
    fp_a = job_definition_fingerprint(container_properties=cp_a, timeout_seconds=3600, attempts=1)
    fp_b = job_definition_fingerprint(container_properties=cp_b, timeout_seconds=3600, attempts=1)
    assert fp_a == fp_b


def test_fingerprint_tracks_image_and_timeout():
    cp = container_properties_payload(
        model="issm", image="x:tested", job_role_arn="arn:job",
        execution_role_arn="arn:exec", region="us-east-2")
    base = job_definition_fingerprint(container_properties=cp, timeout_seconds=3600, attempts=1)
    assert base != job_definition_fingerprint(
        container_properties={**cp, "image": "y:tested"}, timeout_seconds=3600, attempts=1)
    assert base != job_definition_fingerprint(
        container_properties=cp, timeout_seconds=7200, attempts=1)
