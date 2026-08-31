"""Cloud Commit 1 -- AWSDriver.prepare_batch wiring (network / IAM / ECR ->
Fargate provisioning). ensure_batch_resources itself is covered separately;
here we only check the driver passes the right inputs."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryostack_src.cloud.drivers.aws import driver as driver_mod
from cryostack_src.cloud.drivers.aws.driver import AWSDriver

_NET = SimpleNamespace(subnet_ids=["subnet-a"], security_group_ids=["sg-1"], vpc_id="vpc-1")
_IAM = SimpleNamespace(
    job_role="arn:aws:iam::123:role/CryoStackJobRole",
    ecs_execution_role="arn:aws:iam::123:role/CryoStackExecutionRole",
)


@pytest.fixture
def captured(monkeypatch):
    calls = {}

    def fake_ensure(config, **kwargs):
        calls.update(kwargs)
        calls["region"] = config.region
        return SimpleNamespace(resources=SimpleNamespace(), created=[], updated=[],
                               reused=[], skipped=[], log_groups=[])

    monkeypatch.setattr(driver_mod, "ensure_batch_resources", fake_ensure)
    return calls


def test_prepare_batch_uses_ecr_tested_tag(captured):
    driver = AWSDriver(region="us-east-2")
    registry = SimpleNamespace(
        issm_repository_uri="123.dkr.ecr.us-east-2.amazonaws.com/cryostack-issm")
    driver.prepare_batch(network=_NET, iam=_IAM, registry=registry)

    assert captured["issm_image"] == (
        "123.dkr.ecr.us-east-2.amazonaws.com/cryostack-issm:tested")
    assert captured["subnets"] == ["subnet-a"]
    assert captured["security_groups"] == ["sg-1"]
    assert captured["job_role_arn"].endswith("CryoStackJobRole")
    assert captured["execution_role_arn"].endswith("CryoStackExecutionRole")


def test_prepare_batch_without_ecr_repo_passes_no_image(captured):
    driver = AWSDriver(region="us-east-2")
    driver.prepare_batch(network=_NET, iam=_IAM,
                         registry=SimpleNamespace(issm_repository_uri=None))
    assert captured["issm_image"] is None
