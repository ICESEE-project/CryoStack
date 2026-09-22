# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS IAM provisioning -- ISSM MATLAB-license secret grant
# File        : test_aws_iam_provision.py
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: MIT
#
# =============================================================================

"""The narrowly-scoped ``secretsmanager:GetSecretValue`` grant that lets the
ECS task-execution role read ONLY the configured ISSM MATLAB-license secret,
and its reconciliation on every Prepare Cloud.

All AWS CLI calls are mocked -- no real IAM resources are touched. Dummy
Secrets Manager ARNs and a dummy FlexNet endpoint (``27000@test-license.invalid``)
only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryostack_src.cloud.drivers.aws import iam_provision as ip
from cryostack_src.cloud.drivers.aws.iam import AWSIAMResources
from cryostack_src.cloud.drivers.aws.iam_policies import (
    MATLAB_LICENSE_SECRET_POLICY_NAME,
    matlab_license_secret_policy,
)
from cryostack_src.cloud.drivers.aws.models import AWSConfig

CONFIG = AWSConfig(region="us-east-2")

_ARN_A = "arn:aws:secretsmanager:us-east-2:123456789012:secret:cryostack/issm-matlab-A-a1b2c3"
_ARN_B = "arn:aws:secretsmanager:us-east-2:123456789012:secret:cryostack/issm-matlab-B-d4e5f6"

_EXEC_ROLE = ip.ECS_EXECUTION_ROLE_NAME


# ── the policy document (pure) ───────────────────────────────────────────
def test_policy_scopes_getsecretvalue_to_exactly_the_one_arn():
    doc = matlab_license_secret_policy(secret_arn=_ARN_A)
    assert doc == {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CryoStackReadMatlabLicenseSecret",
                "Effect": "Allow",
                "Action": "secretsmanager:GetSecretValue",
                "Resource": _ARN_A,
            }
        ],
    }


def test_policy_never_uses_a_wildcard_resource_and_only_getsecretvalue():
    doc = matlab_license_secret_policy(secret_arn=_ARN_A)
    blob = json.dumps(doc)
    assert '"*"' not in blob
    assert "Resource\": \"*\"" not in blob
    (stmt,) = doc["Statement"]
    assert stmt["Action"] == "secretsmanager:GetSecretValue"      # not a list, not broader
    assert stmt["Resource"] == _ARN_A
    # no KMS statement for the default AWS-managed key
    assert "kms" not in blob.lower()


def test_policy_rejects_a_license_value_or_a_non_secret_arn():
    for bad in ("27000@test-license.invalid",
                "MLM_LICENSE_FILE=27000@test-license.invalid",
                "arn:aws:iam::123456789012:role/whatever",
                "", "   "):
        with pytest.raises(ValueError):
            matlab_license_secret_policy(secret_arn=bad)


# ── reconciliation on Prepare Cloud ──────────────────────────────────────
class _FakeAWS:
    """Records ``iam`` CLI calls. ``missing`` policy names make
    ``delete-role-policy`` report NoSuchEntity (nothing to remove)."""

    def __init__(self, *, missing_on_delete=True):
        self.calls: list[list[str]] = []
        self._missing_on_delete = missing_on_delete

    def __call__(self, config, args):
        self.calls.append(list(args))
        if args[:2] == ["iam", "delete-role-policy"] and self._missing_on_delete:
            return (254, "", "An error occurred (NoSuchEntity) ... cannot be found.")
        if args[:2] == ["iam", "create-role"]:
            return (0, json.dumps({"Role": {"Arn": f"arn:aws:iam::123:role/{args[3]}"}}), "")
        return (0, "{}", "")

    # convenience views ---------------------------------------------------
    def put_policy_calls(self):
        out = []
        for c in self.calls:
            if c[:2] == ["iam", "put-role-policy"]:
                d = dict(zip(c[2::2], c[3::2]))
                out.append({
                    "role": d.get("--role-name"),
                    "name": d.get("--policy-name"),
                    "doc": json.loads(d.get("--policy-document", "{}")),
                })
        return out

    def delete_policy_calls(self):
        out = []
        for c in self.calls:
            if c[:2] == ["iam", "delete-role-policy"]:
                d = dict(zip(c[2::2], c[3::2]))
                out.append({"role": d.get("--role-name"), "name": d.get("--policy-name")})
        return out


def _all_roles_exist():
    return AWSIAMResources(
        batch_service_role="arn:aws:iam::123:role/cryostack-batch-service-role",
        ecs_execution_role="arn:aws:iam::123:role/cryostack-ecs-execution-role",
        job_role="arn:aws:iam::123:role/cryostack-job-role",
    )


def _prepare(monkeypatch, *, matlab_secret_arn, roles=None, missing_on_delete=True):
    fake = _FakeAWS(missing_on_delete=missing_on_delete)
    monkeypatch.setattr(ip, "run_aws", fake)
    monkeypatch.setattr(ip, "discover_iam_resources",
                        lambda *a, **k: roles or _all_roles_exist())
    result = ip.ensure_iam_resources(
        CONFIG, bucket="cryostack-runs-123", matlab_secret_arn=matlab_secret_arn)
    return fake, result


def test_configured_arn_grants_getsecretvalue_on_exactly_that_arn(monkeypatch):
    fake, result = _prepare(monkeypatch, matlab_secret_arn=_ARN_A)

    puts = [p for p in fake.put_policy_calls()
            if p["name"] == MATLAB_LICENSE_SECRET_POLICY_NAME]
    assert len(puts) == 1
    p = puts[0]
    assert p["role"] == _EXEC_ROLE
    (stmt,) = p["doc"]["Statement"]
    assert stmt["Action"] == "secretsmanager:GetSecretValue"
    assert stmt["Resource"] == _ARN_A
    assert '"*"' not in json.dumps(p["doc"])
    assert "ecs_execution_role:matlab_license_secret" in result.updated


def test_no_arn_adds_no_matlab_secret_permission(monkeypatch):
    fake, result = _prepare(monkeypatch, matlab_secret_arn="")

    assert [p for p in fake.put_policy_calls()
            if p["name"] == MATLAB_LICENSE_SECRET_POLICY_NAME] == []
    # it does *try* to remove any stale copy (idempotent), but never a put
    dels = fake.delete_policy_calls()
    assert dels == [{"role": _EXEC_ROLE, "name": MATLAB_LICENSE_SECRET_POLICY_NAME}]
    assert result.updated == []          # nothing was there -> nothing reported


def test_arn_change_A_to_B_reconciles_the_policy_to_B(monkeypatch):
    # run 1: A
    fake_a, _ = _prepare(monkeypatch, matlab_secret_arn=_ARN_A)
    (pa,) = [p for p in fake_a.put_policy_calls()
             if p["name"] == MATLAB_LICENSE_SECRET_POLICY_NAME]
    assert pa["doc"]["Statement"][0]["Resource"] == _ARN_A

    # run 2: B -- same well-known policy name, overwritten, now scoped to B only
    fake_b, result_b = _prepare(monkeypatch, matlab_secret_arn=_ARN_B)
    (pb,) = [p for p in fake_b.put_policy_calls()
             if p["name"] == MATLAB_LICENSE_SECRET_POLICY_NAME]
    assert pb["name"] == MATLAB_LICENSE_SECRET_POLICY_NAME     # same name -> replace
    assert pb["doc"]["Statement"][0]["Resource"] == _ARN_B
    assert _ARN_A not in json.dumps(pb["doc"])                 # A is gone
    assert "ecs_execution_role:matlab_license_secret" in result_b.updated


def test_clearing_the_arn_removes_cryostacks_own_policy(monkeypatch):
    fake, result = _prepare(
        monkeypatch, matlab_secret_arn="", missing_on_delete=False)
    assert fake.delete_policy_calls() == [
        {"role": _EXEC_ROLE, "name": MATLAB_LICENSE_SECRET_POLICY_NAME}]
    assert "ecs_execution_role:matlab_license_secret (removed)" in result.updated


def test_reconcile_never_touches_unrelated_policies(monkeypatch):
    fake, _ = _prepare(monkeypatch, matlab_secret_arn=_ARN_A)

    # the only put is our named policy; the only delete target is our named
    # policy; the managed AmazonECSTaskExecutionRolePolicy attach is untouched
    # (roles already exist -> no attach-role-policy call at all this run).
    for c in fake.calls:
        if c[:2] == ["iam", "put-role-policy"]:
            d = dict(zip(c[2::2], c[3::2]))
            assert d["--policy-name"] in (MATLAB_LICENSE_SECRET_POLICY_NAME,)
        if c[:2] == ["iam", "delete-role-policy"]:
            d = dict(zip(c[2::2], c[3::2]))
            assert d["--policy-name"] == MATLAB_LICENSE_SECRET_POLICY_NAME
        assert c[:2] != ["iam", "detach-role-policy"]
        assert c[:2] != ["iam", "delete-role"]


def test_grant_is_reconciled_even_when_the_execution_role_already_exists(monkeypatch):
    """The bug this fixes: the role is created once, so a first-run-only grant
    would never reach an account whose role predates this change."""
    fake, result = _prepare(monkeypatch, matlab_secret_arn=_ARN_A,
                            roles=_all_roles_exist())
    assert "ecs_execution_role" in result.reused          # not (re)created
    assert [p for p in fake.put_policy_calls()
            if p["name"] == MATLAB_LICENSE_SECRET_POLICY_NAME]   # still granted


def test_wildcard_resource_is_never_generated_anywhere(monkeypatch):
    for arn in (_ARN_A, _ARN_B):
        fake, _ = _prepare(monkeypatch, matlab_secret_arn=arn)
        for c in fake.calls:
            if c[:2] == ["iam", "put-role-policy"]:
                d = dict(zip(c[2::2], c[3::2]))
                doc = json.loads(d["--policy-document"])
                for stmt in doc["Statement"]:
                    assert stmt.get("Resource") != "*"
                    assert stmt.get("Resource") != ["*"]
