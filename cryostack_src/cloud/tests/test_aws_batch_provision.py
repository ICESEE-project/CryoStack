"""Cloud Commit 1 -- AWS Batch (Fargate) provisioning, describe-before-create,
idempotency. All AWS CLI calls are mocked; no real AWS resources are created.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryostack_src.cloud.drivers.aws import batch as batch_mod
from cryostack_src.cloud.drivers.aws import batch_provision as bp
from cryostack_src.cloud.drivers.aws.batch_config import (
    DEFAULT_ISSM_JOB_CONFIG,
    container_properties_payload,
    job_definition_fingerprint,
)
from cryostack_src.cloud.drivers.aws.models import AWSConfig

CONFIG = AWSConfig(region="us-east-2")
SUBNETS = ["subnet-a", "subnet-b"]
SGS = ["sg-1"]
JOB_ROLE = "arn:aws:iam::123456789012:role/CryoStackJobRole"
EXEC_ROLE = "arn:aws:iam::123456789012:role/CryoStackExecutionRole"
IMAGE = "123456789012.dkr.ecr.us-east-2.amazonaws.com/cryostack-issm:tested"


class FakeAWS:
    """A minimal in-memory AWS Batch / Logs the provisioner can drive."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.compute_envs: list[dict] = []
        self.job_queues: list[dict] = []
        self.job_defs: list[dict] = []
        self.log_groups: set[str] = set()

    # -- helpers -------------------------------------------------------
    def count(self, *prefix) -> int:
        p = list(prefix)
        return sum(1 for c in self.calls if c[: len(p)] == p)

    def last(self, *prefix) -> list[str]:
        p = list(prefix)
        for c in reversed(self.calls):
            if c[: len(p)] == p:
                return c
        raise AssertionError(f"no call {prefix}")

    @staticmethod
    def _opt(args: list[str], name: str):
        return args[args.index(name) + 1]

    # -- the run_aws stand-in ---------------------------------------
    def __call__(self, config, args):
        a = list(args)
        self.calls.append(a)

        if a[:2] == ["logs", "create-log-group"]:
            name = self._opt(a, "--log-group-name")
            if name in self.log_groups:
                return (254, "", "An error occurred (ResourceAlreadyExistsException)")
            self.log_groups.add(name)
            return (0, "{}", "")
        if a[:2] == ["logs", "put-retention-policy"]:
            return (0, "{}", "")

        if a[:2] == ["batch", "describe-compute-environments"]:
            envs = self.compute_envs
            if "--compute-environments" in a:
                want = self._opt(a, "--compute-environments")
                envs = [e for e in envs if e["computeEnvironmentName"] == want]
            return (0, json.dumps({"computeEnvironments": envs}), "")
        if a[:2] == ["batch", "create-compute-environment"]:
            self.compute_envs.append({
                "computeEnvironmentName": self._opt(a, "--compute-environment-name"),
                "type": "MANAGED", "state": "ENABLED",
                "computeResources": json.loads(self._opt(a, "--compute-resources")),
            })
            return (0, "{}", "")
        if a[:2] == ["batch", "update-compute-environment"]:
            want = self._opt(a, "--compute-environment")
            patch = json.loads(self._opt(a, "--compute-resources"))
            for e in self.compute_envs:
                if e["computeEnvironmentName"] == want:
                    e["computeResources"].update(patch)
            return (0, "{}", "")

        if a[:2] == ["batch", "describe-job-queues"]:
            qs = self.job_queues
            if "--job-queues" in a:
                want = self._opt(a, "--job-queues")
                qs = [q for q in qs if q["jobQueueName"] == want]
            return (0, json.dumps({"jobQueues": qs}), "")
        if a[:2] == ["batch", "create-job-queue"]:
            self.job_queues.append({
                "jobQueueName": self._opt(a, "--job-queue-name"),
                "state": "ENABLED",
                "priority": int(self._opt(a, "--priority")),
                "computeEnvironmentOrder": json.loads(
                    self._opt(a, "--compute-environment-order")),
            })
            return (0, "{}", "")
        if a[:2] == ["batch", "update-job-queue"]:
            want = self._opt(a, "--job-queue")
            for q in self.job_queues:
                if q["jobQueueName"] == want:
                    q["priority"] = int(self._opt(a, "--priority"))
                    q["state"] = "ENABLED"
                    q["computeEnvironmentOrder"] = json.loads(
                        self._opt(a, "--compute-environment-order"))
            return (0, "{}", "")

        if a[:2] == ["batch", "describe-job-definitions"]:
            defs = self.job_defs
            if "--job-definition-name" in a:
                want = self._opt(a, "--job-definition-name")
                defs = [d for d in defs if d["jobDefinitionName"] == want]
            return (0, json.dumps({"jobDefinitions": defs}), "")
        if a[:2] == ["batch", "register-job-definition"]:
            name = self._opt(a, "--job-definition-name")
            rev = 1 + max(
                [d["revision"] for d in self.job_defs
                 if d["jobDefinitionName"] == name], default=0)
            self.job_defs.append({
                "jobDefinitionName": name, "revision": rev, "status": "ACTIVE",
                "containerProperties": json.loads(self._opt(a, "--container-properties")),
                "timeout": json.loads(self._opt(a, "--timeout")),
                "retryStrategy": json.loads(self._opt(a, "--retry-strategy")),
            })
            return (0, "{}", "")

        raise AssertionError(f"unexpected AWS call: {a}")

    # -- pre-seed matching resources -------------------------------
    def seed_ready(self):
        self.compute_envs.append({
            "computeEnvironmentName": "cryostack-fargate", "type": "MANAGED",
            "state": "ENABLED",
            "computeResources": {"type": "FARGATE", "maxvCpus": 16,
                                 "subnets": SUBNETS, "securityGroupIds": SGS},
        })
        self.job_queues.append({
            "jobQueueName": "cryostack-queue", "state": "ENABLED", "priority": 1,
            "computeEnvironmentOrder": [
                {"order": 1, "computeEnvironment": "cryostack-fargate"}],
        })
        cp = container_properties_payload(
            model="issm", image=IMAGE, job_role_arn=JOB_ROLE,
            execution_role_arn=EXEC_ROLE, region="us-east-2")
        self.job_defs.append({
            "jobDefinitionName": "cryostack-issm", "revision": 3, "status": "ACTIVE",
            "containerProperties": cp,
            "timeout": {"attemptDurationSeconds": DEFAULT_ISSM_JOB_CONFIG.timeout_seconds},
            "retryStrategy": {"attempts": DEFAULT_ISSM_JOB_CONFIG.attempts},
        })
        self.log_groups.add("/cryostack/batch/issm")


@pytest.fixture
def aws(monkeypatch):
    fake = FakeAWS()
    monkeypatch.setattr(bp, "run_aws", fake)
    monkeypatch.setattr(batch_mod, "run_aws", fake)
    return fake


def _provision(**over):
    kw = dict(
        subnets=SUBNETS, security_groups=SGS, job_role_arn=JOB_ROLE,
        execution_role_arn=EXEC_ROLE, issm_image=IMAGE,
    )
    kw.update(over)
    return bp.ensure_batch_resources(CONFIG, **kw)


# ── fresh account: everything is created ────────────────────────────────
def test_fresh_account_creates_all_resources(aws):
    result = _provision()

    assert set(result.created) == {
        "compute_environment", "job_queue", "issm_job_definition"}
    assert result.updated == [] and result.reused == []
    assert result.log_groups == ["/cryostack/batch/issm"]

    assert aws.count("batch", "create-compute-environment") == 1
    assert aws.count("batch", "create-job-queue") == 1
    assert aws.count("batch", "register-job-definition") == 1
    assert aws.count("batch", "update-compute-environment") == 0

    # describe happened before every create
    kinds = [c[1] for c in aws.calls if c[0] == "batch"]
    assert kinds.index("describe-compute-environments") < kinds.index("create-compute-environment")
    assert kinds.index("describe-job-queues") < kinds.index("create-job-queue")

    # final discovery reflects the new resources
    assert result.resources.compute_environment == "cryostack-fargate"
    assert result.resources.job_queue == "cryostack-queue"
    assert result.resources.issm_job_definition == "cryostack-issm"


def test_compute_environment_request_is_fargate_and_bounded(aws):
    _provision()
    call = aws.last("batch", "create-compute-environment")
    cr = json.loads(call[call.index("--compute-resources") + 1])
    assert call[call.index("--type") + 1] == "MANAGED"
    assert cr["type"] == "FARGATE"
    assert cr["maxvCpus"] == 16
    assert "minvCpus" not in cr and "desiredvCpus" not in cr and "instanceTypes" not in cr


def test_job_definition_request_has_logs_roles_timeout_storage(aws):
    _provision()
    call = aws.last("batch", "register-job-definition")
    assert call[call.index("--platform-capabilities") + 1] == "FARGATE"
    cp = json.loads(call[call.index("--container-properties") + 1])
    timeout = json.loads(call[call.index("--timeout") + 1])
    retry = json.loads(call[call.index("--retry-strategy") + 1])
    assert cp["logConfiguration"]["logDriver"] == "awslogs"
    assert cp["jobRoleArn"] == JOB_ROLE
    assert cp["executionRoleArn"] == EXEC_ROLE
    assert cp["ephemeralStorage"]["sizeInGiB"] == 50
    assert timeout["attemptDurationSeconds"] == 3600
    assert retry["attempts"] == 1
    # log group created up front + retention pinned
    assert aws.count("logs", "create-log-group") == 1
    assert aws.count("logs", "put-retention-policy") == 1


# ── idempotency ────────────────────────────────────────────────────────
def test_second_run_reuses_everything(aws):
    aws.seed_ready()
    result = _provision()

    assert set(result.reused) == {
        "compute_environment", "job_queue", "issm_job_definition"}
    assert result.created == [] and result.updated == []
    assert aws.count("batch", "create-compute-environment") == 0
    assert aws.count("batch", "create-job-queue") == 0
    assert aws.count("batch", "register-job-definition") == 0
    assert aws.count("batch", "update-compute-environment") == 0


def test_maxvcpus_drift_triggers_update_not_recreate(aws):
    aws.seed_ready()
    aws.compute_envs[0]["computeResources"]["maxvCpus"] = 8       # drift

    result = _provision()
    assert "compute_environment" in result.updated
    assert aws.count("batch", "update-compute-environment") == 1
    assert aws.count("batch", "create-compute-environment") == 0
    assert aws.compute_envs[0]["computeResources"]["maxvCpus"] == 16


def test_image_drift_registers_a_new_job_definition_revision(aws):
    aws.seed_ready()
    aws.job_defs[0]["containerProperties"]["image"] = "old/image:v0"

    result = _provision()
    assert "issm_job_definition" in result.created
    assert aws.count("batch", "register-job-definition") == 1
    assert aws.job_defs[-1]["revision"] == 4                      # seeded rev was 3


def test_existing_log_group_is_tolerated(aws):
    aws.seed_ready()                                              # log group present
    aws.job_defs[0]["containerProperties"]["image"] = "force/rewrite:v0"

    result = _provision()                                        # touches the log group
    assert aws.count("logs", "put-retention-policy") == 1        # still pinned
    assert "issm_job_definition" in result.created


# ── degraded inputs never make an AWS mess ─────────────────────────────
def test_no_subnets_skips_batch_entirely(aws):
    result = _provision(subnets=[])
    assert any("subnet" in s for s in result.skipped)
    assert aws.count("batch", "create-compute-environment") == 0
    assert aws.count("batch", "register-job-definition") == 0
    assert result.resources is not None


def test_missing_roles_skips_only_the_job_definition(aws):
    result = _provision(job_role_arn="")
    assert set(result.created) == {"compute_environment", "job_queue"}
    assert any("issm_job_definition" in s for s in result.skipped)
    assert aws.count("batch", "register-job-definition") == 0


def test_missing_image_skips_only_the_job_definition(aws):
    result = _provision(issm_image=None)
    assert set(result.created) == {"compute_environment", "job_queue"}
    assert any("issm_job_definition" in s for s in result.skipped)
