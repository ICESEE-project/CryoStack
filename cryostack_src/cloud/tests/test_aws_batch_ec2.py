# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Batch EC2 compute (Advanced) -- Fargate stays the default
# File        : test_aws_batch_ec2.py
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""EC2 is an Advanced AWS Batch compute option. Fargate remains the default and
its resources / job definitions / behaviour are untouched. EC2 gets its own
compute environment (``cryostack-ec2``), queue (``cryostack-ec2-queue``) and
``cryostack-<model>-ec2`` job definitions, reusing the same ECR image, runtime
command and Secrets Manager MATLAB-license mechanism.

All AWS CLI calls are mocked; no real AWS resources are created.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.config import resolve_cloud_config
from cryostack_src.cloud.drivers.aws import batch_provision as bp
from cryostack_src.cloud.drivers.aws import iam_provision as ip
from cryostack_src.cloud.drivers.aws.batch_config import (
    COMPUTE_ENVIRONMENT_NAME,
    EC2_COMPUTE_ENVIRONMENT_NAME,
    EC2_JOB_QUEUE_NAME,
    JOB_QUEUE_NAME,
    EC2ComputeConfig,
    EC2JobConfig,
    compute_environment_name,
    container_properties_payload,
    ec2_compute_resources_payload,
    ec2_container_properties_payload,
    job_definition_name,
    job_queue_name,
    normalize_compute_mode,
    validate_ec2_compute_config,
    validate_ec2_job_config,
)
from cryostack_src.cloud.drivers.aws.models import AWSConfig

CONFIG = AWSConfig(region="us-east-2")
SUBNETS = ["subnet-a", "subnet-b"]
SGS = ["sg-1"]
JOB_ROLE = "arn:aws:iam::123456789012:role/cryostack-job-role"
EXEC_ROLE = "arn:aws:iam::123456789012:role/cryostack-ecs-execution-role"
INSTANCE_PROFILE = "arn:aws:iam::123456789012:instance-profile/cryostack-ec2-instance-profile"
IMAGE = "123456789012.dkr.ecr.us-east-2.amazonaws.com/cryostack-issm@sha256:" + "a" * 64
SECRET = "arn:aws:secretsmanager:us-east-2:123456789012:secret:cryostack/issm-matlab-Ab1"


# ── names / compute-mode normalisation ──────────────────────────────────
def test_compute_mode_normalises_backward_compatibly():
    assert normalize_compute_mode(None) == "fargate"
    assert normalize_compute_mode("") == "fargate"
    assert normalize_compute_mode("FARGATE") == "fargate"
    assert normalize_compute_mode("nonsense") == "fargate"
    assert normalize_compute_mode("ec2") == "ec2"
    assert normalize_compute_mode(" EC2 ") == "ec2"


def test_deterministic_names_split_fargate_and_ec2():
    assert job_definition_name("icepack") == "cryostack-icepack"
    assert job_definition_name("icepack", "fargate") == "cryostack-icepack"
    assert job_definition_name("icepack", "ec2") == "cryostack-icepack-ec2"
    assert job_queue_name() == JOB_QUEUE_NAME == "cryostack-queue"
    assert job_queue_name("ec2") == EC2_JOB_QUEUE_NAME == "cryostack-ec2-queue"
    assert compute_environment_name() == COMPUTE_ENVIRONMENT_NAME == "cryostack-fargate"
    assert compute_environment_name("ec2") == EC2_COMPUTE_ENVIRONMENT_NAME == "cryostack-ec2"


# ── EC2 payloads: EC2-only, no Fargate assumptions ─────────────────────
def test_ec2_compute_resources_payload_is_scale_to_zero_optimal_ondemand():
    payload = ec2_compute_resources_payload(
        subnets=SUBNETS, security_groups=SGS, instance_role_arn=INSTANCE_PROFILE)
    assert payload["type"] == "EC2"
    assert payload["minvCpus"] == 0 and payload["desiredvCpus"] == 0
    assert payload["maxvCpus"] == 16
    assert payload["instanceTypes"] == ["optimal"]
    assert payload["instanceRole"] == INSTANCE_PROFILE
    assert payload["allocationStrategy"] == "BEST_FIT_PROGRESSIVE"
    assert payload["subnets"] == SUBNETS
    assert "SPOT" not in json.dumps(payload)         # first pass: On-Demand only
    # no Fargate-only keys
    assert "fargatePlatformConfiguration" not in json.dumps(payload)


def test_ec2_compute_resources_payload_honours_advanced_knobs():
    payload = ec2_compute_resources_payload(
        subnets=SUBNETS, security_groups=SGS, instance_role_arn=INSTANCE_PROFILE,
        config=EC2ComputeConfig(max_vcpus=256, instance_types=("c5", "m5")))
    assert payload["maxvCpus"] == 256
    assert payload["instanceTypes"] == ["c5", "m5"]


def test_ec2_container_properties_omit_every_fargate_only_key():
    cp = ec2_container_properties_payload(
        model="issm", image=IMAGE, job_role_arn=JOB_ROLE,
        execution_role_arn=EXEC_ROLE, region="us-east-2",
        command=["bash", "-c", "run"], secrets=[{"name": "MLM_LICENSE_FILE",
                                                 "valueFrom": SECRET}])
    for fargate_only in ("networkConfiguration", "fargatePlatformConfiguration",
                         "ephemeralStorage"):
        assert fargate_only not in cp
    # kept, identical to Fargate
    assert cp["image"] == IMAGE
    assert cp["command"] == ["bash", "-c", "run"]
    assert cp["jobRoleArn"] == JOB_ROLE and cp["executionRoleArn"] == EXEC_ROLE
    assert {"type": "VCPU", "value": "2"} in cp["resourceRequirements"]
    assert cp["logConfiguration"]["logDriver"] == "awslogs"
    assert cp["runtimePlatform"]["cpuArchitecture"] == "X86_64"
    # MATLAB license: ARN reference only, exactly like Fargate
    assert cp["secrets"] == [{"name": "MLM_LICENSE_FILE", "valueFrom": SECRET}]


def test_ec2_container_properties_reject_a_raw_license_value():
    with pytest.raises(ValueError):
        ec2_container_properties_payload(
            model="issm", image=IMAGE, job_role_arn=JOB_ROLE,
            execution_role_arn=EXEC_ROLE, region="us-east-2",
            secrets=[{"name": "MLM_LICENSE_FILE", "valueFrom": "27000@host"}])


def test_ec2_job_config_is_not_bound_by_the_fargate_memory_table():
    # 3 vCPU / 5000 MiB would be rejected by validate_fargate_job_config
    validate_ec2_job_config(EC2JobConfig(vcpu="3", memory_mib="5000"))
    with pytest.raises(ValueError):
        validate_ec2_job_config(EC2JobConfig(vcpu="0"))
    with pytest.raises(ValueError):
        validate_ec2_compute_config(EC2ComputeConfig(min_vcpus=8, max_vcpus=4))


# ── config model: backward compatible ─────────────────────────────────
def test_resolve_cloud_config_defaults_to_fargate():
    cfg = resolve_cloud_config(model="icepack")
    assert cfg.compute_mode == "fargate" and cfg.is_ec2 is False
    assert cfg.job_queue == "cryostack-queue"
    assert cfg.job_definition == "cryostack-icepack"
    # a Fargate run's provenance is byte-identical to before -- no new key
    assert "aws_batch_compute" not in cfg.provenance()


def test_old_saved_config_without_the_field_deserialises_to_fargate():
    # simulate an old persisted config: the arg simply is not supplied
    cfg = resolve_cloud_config(model="issm", aws_batch_compute="")
    assert cfg.compute_mode == "fargate"


def test_resolve_cloud_config_explicit_ec2_selects_the_ec2_pair():
    cfg = resolve_cloud_config(model="icepack", aws_batch_compute="ec2")
    assert cfg.is_ec2 is True
    assert cfg.job_queue == "cryostack-ec2-queue"
    assert cfg.job_definition == "cryostack-icepack-ec2"
    assert cfg.provenance()["aws_batch_compute"] == "ec2"


# ── provisioning: Fargate unchanged, EC2 added alongside ───────────────
class _FakeBatchAWS:
    """Minimal in-memory AWS Batch. Records every call; every describe returns
    VALID immediately; register-job-definition keeps --platform-capabilities."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.ces: dict[str, dict] = {}
        self.queues: dict[str, dict] = {}
        self.jobdefs: list[dict] = []
        self.log_groups: set[str] = set()

    @staticmethod
    def _opt(a, name):
        return a[a.index(name) + 1]

    def __call__(self, config, a):
        a = list(a)
        self.calls.append(a)
        if a[:2] == ["logs", "create-log-group"]:
            self.log_groups.add(self._opt(a, "--log-group-name"))
            return (0, "{}", "")
        if a[:2] == ["logs", "put-retention-policy"]:
            return (0, "{}", "")
        if a[:2] == ["batch", "describe-compute-environments"]:
            want = self._opt(a, "--compute-environments")
            e = self.ces.get(want)
            return (0, json.dumps({"computeEnvironments": (
                [{**e, "status": "VALID"}] if e else [])}), "")
        if a[:2] == ["batch", "create-compute-environment"]:
            n = self._opt(a, "--compute-environment-name")
            self.ces[n] = {"computeEnvironmentName": n, "state": "ENABLED",
                           "computeResources": json.loads(
                               self._opt(a, "--compute-resources"))}
            return (0, "{}", "")
        if a[:2] == ["batch", "update-compute-environment"]:
            return (0, "{}", "")
        if a[:2] == ["batch", "describe-job-queues"]:
            want = self._opt(a, "--job-queues")
            q = self.queues.get(want)
            return (0, json.dumps({"jobQueues": (
                [{**q, "status": "VALID"}] if q else [])}), "")
        if a[:2] == ["batch", "create-job-queue"]:
            n = self._opt(a, "--job-queue-name")
            self.queues[n] = {
                "jobQueueName": n, "state": "ENABLED", "priority": 1,
                "computeEnvironmentOrder": json.loads(
                    self._opt(a, "--compute-environment-order"))}
            return (0, "{}", "")
        if a[:2] == ["batch", "update-job-queue"]:
            return (0, "{}", "")
        if a[:2] == ["batch", "describe-job-definitions"]:
            want = self._opt(a, "--job-definition-name")
            return (0, json.dumps({"jobDefinitions": [
                d for d in self.jobdefs if d["jobDefinitionName"] == want]}), "")
        if a[:2] == ["batch", "register-job-definition"]:
            self.jobdefs.append({
                "jobDefinitionName": self._opt(a, "--job-definition-name"),
                "revision": 1, "status": "ACTIVE",
                "platformCapabilities": self._opt(a, "--platform-capabilities"),
                "containerProperties": json.loads(
                    self._opt(a, "--container-properties")),
                "timeout": json.loads(self._opt(a, "--timeout")),
                "retryStrategy": json.loads(self._opt(a, "--retry-strategy")),
            })
            return (0, "{}", "")
        raise AssertionError(f"unexpected AWS call: {a}")

    # views ---------------------------------------------------------
    def registered(self, name):
        return [d for d in self.jobdefs if d["jobDefinitionName"] == name]


@pytest.fixture
def fake_batch(monkeypatch):
    f = _FakeBatchAWS()
    monkeypatch.setattr(bp, "run_aws", f)
    monkeypatch.setattr(
        "cryostack_src.cloud.drivers.aws.batch.run_aws", f, raising=False)
    # discover_batch_resources() runs at the end; stub it out
    monkeypatch.setattr(bp, "discover_batch_resources", lambda *a, **k: object())
    return f


def _fargate_only(fake_batch):
    return bp.ensure_batch_resources(
        CONFIG, subnets=SUBNETS, security_groups=SGS,
        job_role_arn=JOB_ROLE, execution_role_arn=EXEC_ROLE,
        issm_image=IMAGE, job_command=["bash", "-c", "run"],
        issm_secrets=[{"name": "MLM_LICENSE_FILE", "valueFrom": SECRET}],
        sleep=lambda _s: None,
    )


def test_fargate_only_provisioning_is_unchanged(fake_batch):
    res = _fargate_only(fake_batch)
    assert "cryostack-fargate" in fake_batch.ces
    assert "cryostack-queue" in fake_batch.queues
    assert "cryostack-ec2" not in fake_batch.ces          # never created
    assert "cryostack-ec2-queue" not in fake_batch.queues
    (jd,) = fake_batch.registered("cryostack-issm")
    assert jd["platformCapabilities"] == "FARGATE"
    assert "fargatePlatformConfiguration" in jd["containerProperties"]
    assert not any("-ec2" in d["jobDefinitionName"] for d in fake_batch.jobdefs)


def test_ec2_provisioning_adds_separate_resources_without_touching_fargate(fake_batch):
    res = bp.ensure_batch_resources(
        CONFIG, subnets=SUBNETS, security_groups=SGS,
        job_role_arn=JOB_ROLE, execution_role_arn=EXEC_ROLE,
        issm_image=IMAGE, job_command=["bash", "-c", "run"],
        issm_secrets=[{"name": "MLM_LICENSE_FILE", "valueFrom": SECRET}],
        ec2=bp.EC2Provisioning(instance_role_arn=INSTANCE_PROFILE),
        sleep=lambda _s: None,
    )
    # Fargate still there, unchanged
    assert "cryostack-fargate" in fake_batch.ces
    assert "cryostack-queue" in fake_batch.queues
    (fjd,) = fake_batch.registered("cryostack-issm")
    assert fjd["platformCapabilities"] == "FARGATE"
    # EC2 added, separate
    assert fake_batch.ces["cryostack-ec2"]["computeResources"]["type"] == "EC2"
    assert (fake_batch.queues["cryostack-ec2-queue"]["computeEnvironmentOrder"][0]
            ["computeEnvironment"] == "cryostack-ec2")
    (ejd,) = fake_batch.registered("cryostack-issm-ec2")
    assert ejd["platformCapabilities"] == "EC2"
    # EC2 job def: no Fargate-only keys, SAME image, SAME command, SAME secret
    ecp = ejd["containerProperties"]
    for k in ("fargatePlatformConfiguration", "networkConfiguration",
              "ephemeralStorage"):
        assert k not in ecp
    assert ecp["image"] == fjd["containerProperties"]["image"] == IMAGE
    assert ecp["command"] == fjd["containerProperties"]["command"]
    assert ecp["secrets"] == fjd["containerProperties"]["secrets"]


def test_ec2_provisioning_without_instance_profile_is_skipped_cleanly(fake_batch):
    res = bp.ensure_batch_resources(
        CONFIG, subnets=SUBNETS, security_groups=SGS,
        job_role_arn=JOB_ROLE, execution_role_arn=EXEC_ROLE, issm_image=IMAGE,
        job_command=["bash", "-c", "run"],
        ec2=bp.EC2Provisioning(instance_role_arn=""),
        sleep=lambda _s: None,
    )
    assert "cryostack-ec2" not in fake_batch.ces
    assert any("ec2 batch" in s for s in res.skipped)


# ── IAM: EC2 instance profile only when EC2 is prepared ────────────────
class _FakeIamAWS:
    def __init__(self):
        self.calls: list[list[str]] = []
        self._has_profile = False

    def __call__(self, config, a):
        a = list(a)
        self.calls.append(a)
        if a[:2] == ["iam", "list-instance-profiles"]:
            profs = ([{"InstanceProfileName": "cryostack-ec2-instance-profile",
                       "Arn": INSTANCE_PROFILE}] if self._has_profile else [])
            return (0, json.dumps({"InstanceProfiles": profs}), "")
        if a[:2] == ["iam", "list-roles"]:
            return (0, json.dumps({"Roles": []}), "")
        if a[:2] == ["iam", "create-role"]:
            return (0, json.dumps(
                {"Role": {"Arn": f"arn:aws:iam::1:role/{a[3]}"}}), "")
        if a[:2] == ["iam", "create-instance-profile"]:
            self._has_profile = True
            return (0, "{}", "")
        if a[0] == "iam":                # attach / put / delete / add-role -> ok
            return (0, "{}", "")
        raise AssertionError(f"unexpected: {a}")

    def did(self, *prefix):
        p = list(prefix)
        return any(c[:len(p)] == p for c in self.calls)


def test_default_prepare_never_creates_an_ec2_instance_profile(monkeypatch):
    f = _FakeIamAWS()
    monkeypatch.setattr(ip, "run_aws", f)
    monkeypatch.setattr("cryostack_src.cloud.drivers.aws.iam.run_aws", f, raising=False)
    res = ip.ensure_iam_resources(CONFIG, bucket="b")          # include_ec2 defaults False
    assert not f.did("iam", "create-instance-profile")
    assert res.ec2_instance_profile == ""


def test_ec2_prepare_creates_the_instance_profile_with_one_managed_policy(monkeypatch):
    f = _FakeIamAWS()
    monkeypatch.setattr(ip, "run_aws", f)
    monkeypatch.setattr("cryostack_src.cloud.drivers.aws.iam.run_aws", f, raising=False)
    res = ip.ensure_iam_resources(CONFIG, bucket="b", include_ec2=True)
    assert f.did("iam", "create-instance-profile")
    assert f.did("iam", "add-role-to-instance-profile")
    # exactly one managed policy on the instance role -- no custom/wildcard
    attaches = [c for c in f.calls if c[:2] == ["iam", "attach-role-policy"]
                and "cryostack-ec2-instance-role" in c]
    assert len(attaches) == 1
    assert "AmazonEC2ContainerServiceforEC2Role" in attaches[0][
        attaches[0].index("--policy-arn") + 1]
    assert "ec2_instance_profile" in (res.created + res.reused)


def test_rerunning_prepare_cloud_with_ec2_is_idempotent(monkeypatch):
    """A second Prepare Cloud for the same connection must reuse the
    instance profile it already created -- never a duplicate
    create-instance-profile/create-role, and never an error."""
    f = _FakeIamAWS()
    monkeypatch.setattr(ip, "run_aws", f)
    monkeypatch.setattr("cryostack_src.cloud.drivers.aws.iam.run_aws", f, raising=False)

    first = ip.ensure_iam_resources(CONFIG, bucket="b", include_ec2=True)
    assert "ec2_instance_profile" in first.created
    assert first.ec2_instance_profile == INSTANCE_PROFILE

    second = ip.ensure_iam_resources(CONFIG, bucket="b", include_ec2=True)
    assert "ec2_instance_profile" in second.reused
    assert second.ec2_instance_profile == INSTANCE_PROFILE

    creates = [c for c in f.calls if c[:2] == ["iam", "create-instance-profile"]]
    assert len(creates) == 1        # only the first run actually created it


# ── driver.submit: queue + job definition follow the compute mode ─────
def _submit(monkeypatch, **kw):
    from cryostack_src.cloud.drivers.aws.driver import AWSDriver
    captured = {}

    def fake_stage(config, **s):
        class _S:
            run_id = "cloud-x"; s3_run = "s3://b/runs/cloud-x"
            s3_input = s3_run + "/input"; s3_outputs = s3_run + "/outputs"
            messages = []
        return _S()

    def fake_submit_job(config, *, job_queue, job_definition, **s):
        captured["job_queue"] = job_queue
        captured["job_definition"] = job_definition

        class _B:
            job_id = "job-1"
            messages = []
        _B.job_queue = job_queue
        _B.job_definition = job_definition
        return _B()

    monkeypatch.setattr(
        "cryostack_src.cloud.drivers.aws.staging.stage_run_inputs", fake_stage)
    monkeypatch.setattr(
        "cryostack_src.cloud.drivers.aws.submit.submit_batch_job", fake_submit_job)
    monkeypatch.setattr(
        "cryostack_src.cloud.preflight.assert_cloud_run_allowed",
        lambda **k: None)

    drv = AWSDriver(region="us-east-2")
    out = drv.submit(staged_source="/tmp/x", model="icepack", run_target="run.py",
                     bucket="cryostack-runs-1", **kw)
    return out, captured


def test_submit_defaults_to_the_fargate_queue_and_job_definition(monkeypatch):
    out, cap = _submit(monkeypatch)
    assert cap["job_queue"] == "cryostack-queue"
    assert cap["job_definition"] == "cryostack-icepack"
    assert out["aws_batch_compute"] == "fargate"


def test_submit_ec2_mode_targets_the_ec2_queue_and_job_definition(monkeypatch):
    out, cap = _submit(monkeypatch, compute_mode="ec2")
    assert cap["job_queue"] == "cryostack-ec2-queue"
    assert cap["job_definition"] == "cryostack-icepack-ec2"
    assert out["aws_batch_compute"] == "ec2"


def test_submit_never_puts_the_license_in_container_overrides_ec2_or_fargate():
    from cryostack_src.cloud.drivers.aws.submit import build_container_overrides
    ov = build_container_overrides(
        s3_run="s3://b/runs/r", model="issm", run_target="runme.m")
    assert {e["name"] for e in ov["environment"]} == {
        "CRYOSTACK_S3_RUN", "CRYOSTACK_MODEL", "CRYOSTACK_RUN_TARGET"}


# ── UI: EC2 only under Advanced, hidden until chosen ──────────────────
def test_cloud_environment_card_hides_ec2_controls_until_ec2_is_selected():
    from cryostack_src.frontend.cryolauncher.cloud_environment import (
        build_cloud_environment_card,
    )
    card = build_cloud_environment_card()
    assert card.compute_mode.value == "fargate"
    assert card.ec2_options_box.layout.display == "none"
    # the choice lives inside the Advanced accordion, not the primary view
    assert card.compute_mode in card.advanced.children[0].children

    card.compute_mode.value = "ec2"
    assert card.ec2_options_box.layout.display == "flex"
    assert card.ec2_max_vcpus.value == 16
    assert card.ec2_instance_types.value == "optimal"


# =============================================================================
# EC2 Advanced roadmap: Spot / custom network / guarded GPU / guarded
# multi-node, plus the centralized compatibility matrix.
# =============================================================================
from cryostack_src.cloud.drivers.aws.batch_config import (  # noqa: E402
    EC2_ACCELERATOR_GPU,
    EC2_CAPACITY_SPOT,
    EC2_NETWORK_CUSTOM,
    EC2_SPOT_COMPUTE_ENVIRONMENT_NAME,
    EC2_SPOT_JOB_QUEUE_NAME,
    EC2_TOPOLOGY_MULTINODE,
    ComputeSelectionError,
    assert_compute_selection,
    ec2_gpu_resource_requirement,
    ec2_multinode_job_definition_payload,
    normalize_ec2_accelerator,
    normalize_ec2_capacity,
    normalize_ec2_network,
    normalize_ec2_topology,
    validate_compute_selection,
)

_SPOT = EC2ComputeConfig(capacity="spot")
_CUSTOM_NET = EC2ComputeConfig(
    network="custom", subnet_ids=("subnet-priv-a",), security_group_ids=("sg-priv",))
_GPU = EC2ComputeConfig(accelerator="gpu", gpu_count=2)
_MULTINODE = EC2ComputeConfig(topology="multi_node", node_count=4)


# ── normalisation: backward compatible, everything defaults to the plain case
def test_ec2_submode_normalisation_defaults_to_the_plain_case():
    for fn, plain in (
        (normalize_ec2_capacity, "on_demand"),
        (normalize_ec2_accelerator, "none"),
        (normalize_ec2_network, "default"),
        (normalize_ec2_topology, "single_node"),
    ):
        assert fn(None) == plain
        assert fn("") == plain
        assert fn("garbage") == plain


def test_bare_ec2_compute_config_is_the_plain_on_demand_single_node_default():
    cfg = EC2ComputeConfig()
    assert not (cfg.is_spot or cfg.is_custom_network or cfg.is_gpu or cfg.is_multinode)


# ── Spot ──────────────────────────────────────────────────────────────────
def test_spot_names_are_separate_from_on_demand():
    assert compute_environment_name("ec2", "spot") == EC2_SPOT_COMPUTE_ENVIRONMENT_NAME
    assert compute_environment_name("ec2", "on_demand") == EC2_COMPUTE_ENVIRONMENT_NAME
    assert job_queue_name("ec2", "spot") == EC2_SPOT_JOB_QUEUE_NAME
    assert job_queue_name("ec2", "on_demand") == EC2_JOB_QUEUE_NAME
    # capacity does NOT change the container spec -> same job definition name
    assert job_definition_name("issm", "ec2") == "cryostack-issm-ec2"


def test_spot_compute_resources_payload_uses_spot_type_and_allocation():
    payload = ec2_compute_resources_payload(
        subnets=SUBNETS, security_groups=SGS, instance_role_arn=INSTANCE_PROFILE,
        config=_SPOT)
    assert payload["type"] == "SPOT"
    assert payload["allocationStrategy"] == "SPOT_PRICE_CAPACITY_OPTIMIZED"
    assert payload["minvCpus"] == 0 and payload["desiredvCpus"] == 0


def test_on_demand_unaffected_by_spot_addition():
    payload = ec2_compute_resources_payload(
        subnets=SUBNETS, security_groups=SGS, instance_role_arn=INSTANCE_PROFILE)
    assert payload["type"] == "EC2"
    assert payload["allocationStrategy"] == "BEST_FIT_PROGRESSIVE"


def test_spot_provisioning_adds_its_own_ce_and_queue(fake_batch):
    bp.ensure_batch_resources(
        CONFIG, subnets=SUBNETS, security_groups=SGS,
        job_role_arn=JOB_ROLE, execution_role_arn=EXEC_ROLE, issm_image=IMAGE,
        job_command=["bash", "-c", "run"],
        ec2=bp.EC2Provisioning(instance_role_arn=INSTANCE_PROFILE, ec2_config=_SPOT),
        sleep=lambda _s: None,
    )
    assert fake_batch.ces["cryostack-ec2-spot"]["computeResources"]["type"] == "SPOT"
    assert "cryostack-ec2" not in fake_batch.ces               # on-demand CE untouched
    assert (fake_batch.queues["cryostack-ec2-spot-queue"]["computeEnvironmentOrder"][0]
            ["computeEnvironment"] == "cryostack-ec2-spot")
    # same job definition as on-demand EC2 -- capacity is a CE/queue property
    (jd,) = fake_batch.registered("cryostack-issm-ec2")
    assert jd["platformCapabilities"] == "EC2"


def test_submit_ec2_spot_targets_the_spot_queue(monkeypatch):
    out, cap = _submit(monkeypatch, compute_mode="ec2",
                       ec2_config=EC2ComputeConfig(capacity="spot"))
    assert cap["job_queue"] == "cryostack-ec2-spot-queue"
    assert cap["job_definition"] == "cryostack-icepack-ec2"    # unchanged by capacity


# ── custom / private network ─────────────────────────────────────────────
def test_custom_network_overrides_discovered_subnets_and_security_groups():
    payload = ec2_compute_resources_payload(
        subnets=SUBNETS, security_groups=SGS, instance_role_arn=INSTANCE_PROFILE,
        config=_CUSTOM_NET)
    assert payload["subnets"] == ["subnet-priv-a"]
    assert payload["securityGroupIds"] == ["sg-priv"]
    assert "subnet-a" not in payload["subnets"]                # discovery ignored


def test_default_network_still_uses_discovery():
    payload = ec2_compute_resources_payload(
        subnets=SUBNETS, security_groups=SGS, instance_role_arn=INSTANCE_PROFILE)
    assert payload["subnets"] == SUBNETS
    assert payload["securityGroupIds"] == SGS


def test_custom_network_without_a_subnet_id_is_rejected():
    with pytest.raises(ValueError):
        validate_ec2_compute_config(EC2ComputeConfig(network="custom"))


def test_custom_network_never_creates_vpn_or_gateway_resources(fake_batch):
    # the fake raises AssertionError on any call it doesn't recognise --
    # proof that custom-network provisioning issues ONLY the same
    # create-compute-environment / create-job-queue / register-job-definition
    # calls as the default path, never a VPN/TGW/NAT-shaped one.
    bp.ensure_batch_resources(
        CONFIG, subnets=SUBNETS, security_groups=SGS,
        job_role_arn=JOB_ROLE, execution_role_arn=EXEC_ROLE, issm_image=IMAGE,
        job_command=["bash", "-c", "run"],
        ec2=bp.EC2Provisioning(instance_role_arn=INSTANCE_PROFILE,
                               ec2_config=_CUSTOM_NET),
        sleep=lambda _s: None,
    )
    assert fake_batch.ces["cryostack-ec2"]["computeResources"]["subnets"] == \
        ["subnet-priv-a"]


# ── GPU: infrastructure only, guarded submission ─────────────────────────
def test_gpu_resource_requirement_is_none_unless_accelerator_is_gpu():
    assert ec2_gpu_resource_requirement(EC2ComputeConfig()) is None
    assert ec2_gpu_resource_requirement(_GPU) == {"type": "GPU", "value": "2"}


def test_gpu_container_properties_add_a_gpu_resource_requirement():
    cp = ec2_container_properties_payload(
        model="issm", image=IMAGE, job_role_arn=JOB_ROLE,
        execution_role_arn=EXEC_ROLE, region="us-east-2", compute=_GPU)
    kinds = {r["type"] for r in cp["resourceRequirements"]}
    assert kinds == {"VCPU", "MEMORY", "GPU"}


def test_gpu_job_definition_name_gets_its_own_deterministic_suffix():
    assert job_definition_name("issm", "ec2", accelerator="gpu") == "cryostack-issm-ec2-gpu"
    assert job_definition_name("issm", "ec2") == "cryostack-issm-ec2"      # unaffected


def test_gpu_instance_types_default_to_the_gpu_family_when_unset():
    payload = ec2_compute_resources_payload(
        subnets=SUBNETS, security_groups=SGS, instance_role_arn=INSTANCE_PROFILE,
        config=_GPU)
    assert set(payload["instanceTypes"]) & {"g4dn", "g5"}


def test_gpu_is_valid_infrastructure_but_blocked_from_submission_by_default():
    reasons = validate_compute_selection("ec2", _GPU)
    assert reasons and "CUDA" in " ".join(reasons)
    with pytest.raises(ComputeSelectionError):
        assert_compute_selection("ec2", _GPU)


def test_gpu_submission_is_allowed_once_a_qualified_image_flag_is_set():
    assert validate_compute_selection(
        "ec2", _GPU, gpu_image_qualified=True) == []


def test_gpu_is_never_valid_on_fargate():
    reasons = validate_compute_selection("fargate", _GPU)
    assert reasons and "Fargate" in " ".join(reasons)


def test_qualified_image_has_no_cuda_runtime_documented_gap():
    """This is the actual gap the GPU guard exists for -- v1.0.2 is CPU-only
    (jaxlib 0.4.38 is the CPU build; no /usr/local/cuda, no nvidia-smi/nvcc).
    The constant records that fact; flip it only for a real GPU-qualified
    image registered in TESTED_IMAGES."""
    from cryostack_src.cloud.drivers.aws.batch_config import GPU_IMAGE_QUALIFIED
    assert GPU_IMAGE_QUALIFIED is False


# ── Multi-node: infrastructure only, guarded scientific submission ───────
def test_multinode_job_definition_payload_shape():
    cp = {"image": IMAGE, "command": ["cryostack-run"]}
    body = ec2_multinode_job_definition_payload(container_properties=cp, node_count=4)
    assert body["type"] == "multinode"
    props = body["nodeProperties"]
    assert props["numNodes"] == 4
    assert props["mainNode"] == 0
    (rng,) = props["nodeRangeProperties"]
    assert rng["targetNodes"] == "0:3"
    assert rng["container"] == cp


def test_multinode_needs_at_least_two_nodes():
    with pytest.raises(ValueError):
        ec2_multinode_job_definition_payload(
            container_properties={"image": IMAGE}, node_count=1)
    with pytest.raises(ValueError):
        validate_ec2_compute_config(EC2ComputeConfig(topology="multi_node", node_count=1))


def test_multinode_job_definition_name_gets_its_own_deterministic_suffix():
    assert (job_definition_name("issm", "ec2", topology="multi_node")
            == "cryostack-issm-ec2-mnp")


def test_multinode_is_valid_infrastructure_but_blocked_from_science_by_default():
    reasons = validate_compute_selection("ec2", _MULTINODE)
    assert reasons and "distributed MPI" in " ".join(reasons)


def test_multinode_submission_is_allowed_once_runtime_support_flag_is_set():
    assert validate_compute_selection(
        "ec2", _MULTINODE, multinode_runtime_supported=True) == []


def test_multinode_is_never_valid_on_fargate():
    reasons = validate_compute_selection("fargate", _MULTINODE)
    assert reasons and "Fargate" in " ".join(reasons)


def test_current_scientific_runners_do_not_support_distributed_mpi_documented_gap():
    """The actual gap the multi-node guard exists for: cloud/runtime.py's
    generic runner and the ISSM/Icepack/ICESEE runners have no
    AWS_BATCH_JOB_NODE_INDEX / distributed-MPI handling; ICESEE's own runner
    explicitly refuses NP>1 as unsafe. Flip only once a distributed runner is
    implemented AND scientifically validated across real Batch nodes."""
    from cryostack_src.cloud.drivers.aws.batch_config import (
        MULTINODE_RUNTIME_SUPPORTED,
    )
    assert MULTINODE_RUNTIME_SUPPORTED is False


def test_multinode_job_definition_registers_with_node_properties(fake_batch, monkeypatch):
    """A dedicated fake that also understands multinode registration --
    proves ensure_job_definition emits --type multinode --node-properties
    (never --container-properties) and registers under its own -ec2-mnp
    name, never the plain -ec2 one."""
    def _register_multinode(config, a):
        a = list(a)
        fake_batch.calls.append(a)
        if a[:2] == ["batch", "register-job-definition"] and "--node-properties" in a:
            name = a[a.index("--job-definition-name") + 1]
            fake_batch.jobdefs.append({
                "jobDefinitionName": name, "revision": 1, "status": "ACTIVE",
                "platformCapabilities": a[a.index("--platform-capabilities") + 1],
                "nodeProperties": json.loads(a[a.index("--node-properties") + 1]),
                "timeout": json.loads(a[a.index("--timeout") + 1]),
                "retryStrategy": json.loads(a[a.index("--retry-strategy") + 1]),
            })
            return (0, "{}", "")
        return fake_batch(config, a)

    monkeypatch.setattr(bp, "run_aws", _register_multinode)
    outcome = bp.ensure_job_definition(
        CONFIG, model="issm", image=IMAGE, job_role_arn=JOB_ROLE,
        execution_role_arn=EXEC_ROLE, region="us-east-2",
        job_config=EC2JobConfig(), compute_mode="ec2", compute=_MULTINODE,
    )
    assert outcome == "created"
    (jd,) = [d for d in fake_batch.jobdefs
             if d["jobDefinitionName"] == "cryostack-issm-ec2-mnp"]
    assert jd["nodeProperties"]["numNodes"] == 4
    assert "containerProperties" not in jd


# ── centralized compatibility matrix ─────────────────────────────────────
def test_fargate_only_the_plain_default_is_valid():
    assert validate_compute_selection("fargate") == []
    assert validate_compute_selection("fargate", EC2ComputeConfig()) == []


def test_ec2_on_demand_spot_and_custom_network_are_always_valid():
    assert validate_compute_selection("ec2") == []
    assert validate_compute_selection("ec2", _SPOT) == []
    assert validate_compute_selection("ec2", _CUSTOM_NET) == []


def test_invalid_combinations_are_rejected_before_submission():
    from cryostack_src.cloud.preflight import assert_cloud_run_allowed

    with pytest.raises(Exception):
        assert_cloud_run_allowed(
            model="issm", matlab_license_configured=True,
            compute_mode="fargate", ec2_config=_GPU,
        )
    with pytest.raises(Exception):
        assert_cloud_run_allowed(
            model="issm", matlab_license_configured=True,
            compute_mode="ec2", ec2_config=_MULTINODE,
        )
    # plain EC2 with the license configured is clear to go
    assert_cloud_run_allowed(
        model="issm", matlab_license_configured=True,
        compute_mode="ec2", ec2_config=EC2ComputeConfig(),
    )


def test_preflight_without_compute_mode_is_unaffected_backward_compatible():
    """A caller that has not adopted compute_mode/ec2_config at all (every
    caller before this change) sees exactly the same reasons as before."""
    from cryostack_src.cloud.preflight import cloud_run_preflight

    assert cloud_run_preflight(model="issm", matlab_license_configured=True) == []
    assert cloud_run_preflight(model="issm", matlab_license_configured=False) != []


# ── UI: progressive disclosure for each EC2 sub-mode ─────────────────────
def test_ec2_submode_controls_are_hidden_until_their_own_option_is_chosen():
    from cryostack_src.frontend.cryolauncher.cloud_environment import (
        build_cloud_environment_card,
    )
    card = build_cloud_environment_card()
    card.compute_mode.value = "ec2"

    assert card.ec2_network_box.layout.display == "none"
    card.ec2_network.value = "custom"
    assert card.ec2_network_box.layout.display == "flex"
    card.ec2_network.value = "default"
    assert card.ec2_network_box.layout.display == "none"

    assert card.ec2_multinode_box.layout.display == "none"
    card.ec2_topology.value = "multi_node"
    assert card.ec2_multinode_box.layout.display == "flex"
    card.ec2_topology.value = "single_node"
    assert card.ec2_multinode_box.layout.display == "none"

    # defaults are the plain/valid case
    assert card.ec2_capacity.value == "on_demand"
    assert card.ec2_accelerator.value == "none"
    assert card.ec2_network.value == "default"
    assert card.ec2_topology.value == "single_node"


def test_ec2_submode_widgets_feed_ec2computeconfig_correctly():
    from cryostack_src.frontend.cryolauncher.cloud_environment import (
        build_cloud_environment_card,
    )
    from cryostack_src.frontend.cryolauncher.cloud_runtime import (
        _ec2_config_from_widgets,
    )
    card = build_cloud_environment_card()
    card.compute_mode.value = "ec2"
    card.ec2_capacity.value = "spot"
    card.ec2_network.value = "custom"
    card.ec2_subnet_ids.value = "subnet-x, subnet-y"
    card.ec2_security_group_ids.value = "sg-x"
    card.ec2_topology.value = "multi_node"
    card.ec2_node_count.value = 6

    cfg = _ec2_config_from_widgets(card)
    assert cfg.capacity == "spot"
    assert cfg.network == "custom"
    assert cfg.subnet_ids == ("subnet-x", "subnet-y")
    assert cfg.security_group_ids == ("sg-x",)
    assert cfg.topology == "multi_node"
    assert cfg.node_count == 6
    assert cfg.accelerator == "none"                     # untouched default
