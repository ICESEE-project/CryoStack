"""AWSDriver.prepare_batch wiring: tested-image delivery -> digest-pinned job
definition. ensure_batch_resources and mirror_tested_image are covered
separately; here we only check the driver stitches them together correctly."""
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
from cryostack_src.cloud.drivers.aws.registry_delivery import (
    ECRImageDelivery,
    RegistryDeliveryError,
)

_NET = SimpleNamespace(subnet_ids=["subnet-a"], security_group_ids=["sg-1"], vpc_id="vpc-1")
_IAM = SimpleNamespace(
    job_role="arn:aws:iam::123:role/CryoStackJobRole",
    ecs_execution_role="arn:aws:iam::123:role/CryoStackExecutionRole",
)
_IMMUTABLE = "123.dkr.ecr.us-east-2.amazonaws.com/cryostack-issm@sha256:dddd"


@pytest.fixture
def captured(monkeypatch):
    calls = {}

    def fake_ensure(config, **kwargs):
        calls.update(kwargs)
        calls["region"] = config.region
        return SimpleNamespace(
            resources=SimpleNamespace(), created=[], updated=[], reused=[],
            skipped=[], log_groups=[], messages=[], image_delivery=None)

    monkeypatch.setattr(driver_mod, "ensure_batch_resources", fake_ensure)
    return calls


def _delivery(**over):
    base = dict(
        model="issm", repository="cryostack-issm",
        repository_uri="123.dkr.ecr.us-east-2.amazonaws.com/cryostack-issm",
        tag="tested",
        source_reference="bkyanjo/icesee-combined:v1.0.0",
        source_digest="sha256:a727f60a",
        destination_digest="sha256:dddd",
        immutable_reference=_IMMUTABLE,
        verified=True, reused=True,
    )
    base.update(over)
    return ECRImageDelivery(**base)


def test_verified_delivery_pins_job_definition_by_digest(monkeypatch, captured):
    monkeypatch.setattr(driver_mod, "mirror_tested_image",
                        lambda config, **kw: _delivery())
    result = AWSDriver(region="us-east-2").prepare_batch(network=_NET, iam=_IAM)

    assert captured["issm_image"] == _IMMUTABLE
    assert "@sha256:" in captured["issm_image"] and ":tested" not in captured["issm_image"]
    assert result.image_delivery.verified is True


def test_failed_delivery_leaves_job_definition_untouched(monkeypatch, captured):
    def boom(config, **kw):
        raise RegistryDeliveryError("no copier configured")

    monkeypatch.setattr(driver_mod, "mirror_tested_image", boom)
    result = AWSDriver(region="us-east-2").prepare_batch(network=_NET, iam=_IAM)

    assert captured["issm_image"] is None            # job definition not registered
    assert result.image_delivery is None
    assert any("not ready" in m for m in result.messages)


def test_image_copier_is_forwarded(monkeypatch, captured):
    seen = {}

    def spy(config, *, model, copier):
        seen["model"] = model
        seen["copier"] = copier
        return _delivery()

    monkeypatch.setattr(driver_mod, "mirror_tested_image", spy)
    sentinel = object()
    AWSDriver(region="us-east-2").prepare_batch(
        network=_NET, iam=_IAM, image_copier=sentinel)
    assert seen == {"model": "issm", "copier": sentinel}
