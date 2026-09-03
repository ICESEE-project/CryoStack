"""C7.2 -- CryoStackExecutionRole template + Quick Create URL."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.connect.cloudformation import (
    EXECUTION_ROLE_NAME,
    execution_role_template,
    quick_create_url,
    render_template,
)

PRINCIPAL = "arn:aws:iam::713938953301:role/cryostack-service"
EXTERNAL_ID = "cryostack:alice-abc:sekret+random/value"
TEMPLATE_URL = "https://cryostack-public.s3.amazonaws.com/cf/execution-role.json"


@pytest.fixture
def template():
    return execution_role_template()


def _all_statements(template):
    policy = template["Resources"]["CryoStackExecutionRole"]["Properties"]["Policies"][0]
    return policy["PolicyDocument"]["Statement"]


def test_trust_policy_requires_sts_external_id_and_the_cryostack_principal(template):
    trust = template["Resources"]["CryoStackExecutionRole"]["Properties"][
        "AssumeRolePolicyDocument"
    ]
    stmt = trust["Statement"][0]
    assert stmt["Action"] == "sts:AssumeRole"
    assert stmt["Principal"]["AWS"] == {"Ref": "CryoStackPrincipalArn"}
    assert stmt["Condition"]["StringEquals"]["sts:ExternalId"] == {"Ref": "ExternalId"}


def test_external_id_is_a_noecho_parameter(template):
    param = template["Parameters"]["ExternalId"]
    assert param["NoEcho"] is True
    assert param["Type"] == "String"


def test_role_name_is_the_documented_constant(template):
    assert (
        template["Resources"]["CryoStackExecutionRole"]["Properties"]["RoleName"]
        == EXECUTION_ROLE_NAME
        == "CryoStackExecutionRole"
    )


def test_no_administrator_access_and_no_star_star(template):
    blob = json.dumps(template)
    assert "AdministratorAccess" not in blob
    assert "PowerUserAccess" not in blob
    for stmt in _all_statements(template):
        actions = stmt["Action"]
        actions = [actions] if isinstance(actions, str) else actions
        resources = stmt["Resource"]
        resources = [resources] if isinstance(resources, str) else resources
        # a bare Action:"*" is never allowed; Resource:"*" only for known
        # un-scopable describe/auth/identity statements
        assert "*" not in actions
        if "*" in resources:
            assert stmt["Sid"] in {
                "CryoStackEcrAuth",
                "CryoStackBatchRead",
                "CryoStackNetworkDiscovery",
                "CryoStackIdentityAndPricing",
            }, stmt["Sid"]


def test_s3_is_scoped_to_cryostack_runs(template):
    sids = {s["Sid"]: s for s in _all_statements(template)}
    assert sids["CryoStackRunsBuckets"]["Resource"] == {
        "Fn::Sub": "arn:${AWS::Partition}:s3:::cryostack-runs-*"
    }
    assert sids["CryoStackRunsObjects"]["Resource"] == {
        "Fn::Sub": "arn:${AWS::Partition}:s3:::cryostack-runs-*/*"
    }


def test_ecr_repo_actions_are_scoped_to_cryostack_repositories(template):
    sids = {s["Sid"]: s for s in _all_statements(template)}
    assert "cryostack-*" in sids["CryoStackEcrRepos"]["Resource"]["Fn::Sub"]
    assert "repository/cryostack-*" in sids["CryoStackEcrRepos"]["Resource"]["Fn::Sub"]


def test_batch_submit_describe_terminate_are_all_present(template):
    actions = set()
    for stmt in _all_statements(template):
        a = stmt["Action"]
        actions.update([a] if isinstance(a, str) else a)
    assert {"batch:SubmitJob", "batch:DescribeJobs", "batch:TerminateJob"} <= actions


def test_cloudwatch_log_reads_are_scoped_to_the_cryostack_group(template):
    sids = {s["Sid"]: s for s in _all_statements(template)}
    read = sids["CryoStackLogsRead"]
    assert "logs:GetLogEvents" in read["Action"]
    assert "log-group:/cryostack/*" in read["Resource"]["Fn::Sub"]


def test_passrole_is_tightly_scoped_to_cryostack_roles_and_services(template):
    sids = {s["Sid"]: s for s in _all_statements(template)}
    pr = sids["CryoStackPassRole"]
    assert pr["Action"] == "iam:PassRole"
    assert pr["Resource"]["Fn::Sub"].endswith("role/cryostack-*")
    services = pr["Condition"]["StringEquals"]["iam:PassedToService"]
    assert set(services) == {"batch.amazonaws.com", "ecs-tasks.amazonaws.com"}


def test_render_template_is_valid_json_round_trip(template):
    assert json.loads(render_template()) == template


def test_checked_in_deployment_artifact_matches_render_template():
    artifact = (
        _REPO / "deployment" / "cloudformation" / "cryostack-execution-role.json"
    )
    assert artifact.is_file(), "regenerate deployment/cloudformation/ (see its README)"
    assert json.loads(artifact.read_text(encoding="utf-8")) == json.loads(
        render_template()
    )


# -- Quick Create URL --------------------------------------------------
def test_quick_create_url_is_well_formed_and_encoded():
    url = quick_create_url(
        template_url=TEMPLATE_URL,
        external_id=EXTERNAL_ID,
        region="us-east-2",
        principal_arn=PRINCIPAL,
        stack_name="cryostack-access",
    )
    parsed = urlparse(url)
    assert parsed.netloc == "us-east-2.console.aws.amazon.com"
    assert parsed.path == "/cloudformation/home"
    assert parsed.fragment.startswith("/stacks/quickcreate")

    query = parse_qs(parsed.fragment.split("?", 1)[1])
    assert query["templateURL"] == [TEMPLATE_URL]
    assert query["stackName"] == ["cryostack-access"]
    # the ExternalId survives a full encode/decode round trip byte-for-byte
    assert query["param_ExternalId"] == [EXTERNAL_ID]
    assert query["param_CryoStackPrincipalArn"] == [PRINCIPAL]
    # reserved characters were percent-encoded in the raw string
    raw = parsed.fragment.split("?", 1)[1]
    assert "sekret%2Brandom%2Fvalue" in raw


def test_quick_create_url_requires_every_input():
    for missing in ("template_url", "external_id", "region", "principal_arn"):
        kwargs = dict(
            template_url=TEMPLATE_URL,
            external_id=EXTERNAL_ID,
            region="us-east-2",
            principal_arn=PRINCIPAL,
        )
        kwargs[missing] = ""
        with pytest.raises(ValueError):
            quick_create_url(**kwargs)
