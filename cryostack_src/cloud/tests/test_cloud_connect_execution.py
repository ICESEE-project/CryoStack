"""C7.3 -- resolve_cloud_execution: BYO vs developer credential routing.

Fixtures: A = 713938953301, B = 774888247882 (never product defaults).
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.connect import AWSConnectionStore, verify_connection
from cryostack_src.cloud.connect.execution import (
    MODE_BYO,
    MODE_DEVELOPER,
    CloudAccessError,
    resolve_cloud_execution,
)
from cryostack_src.workspace.identity import WorkspaceUser

ROLE_A = "arn:aws:iam::713938953301:role/CryoStackExecutionRole"
ROLE_B = "arn:aws:iam::774888247882:role/CryoStackExecutionRole"


def _user(uid):
    return WorkspaceUser(user_id=uid, source="cryostack-auth")


class FakeAWS:
    def __init__(self, account, *, deny=False):
        self.account = account
        self.deny = deny
        self.calls = 0

    def __call__(self, args, *, env=None):
        if args[:2] == ["sts", "assume-role"]:
            self.calls += 1
            if self.deny:
                from cryostack_src.cloud.connect.assume_role import AssumeRoleError

                raise AssumeRoleError("temporary session unavailable")
            return {
                "Credentials": {
                    "AccessKeyId": f"ASIA_{self.account}_{self.calls}",
                    "SecretAccessKey": "sekret", "SessionToken": "tok",
                    "Expiration": "2026-09-03T01:00:00Z",
                }
            }
        if args[:2] == ["sts", "get-caller-identity"]:
            return {"Account": self.account}
        raise AssertionError(args)


def _connect(tmp_path, uid, role_arn, account, *, runner=None):
    store = AWSConnectionStore(user=_user(uid), workspace_root=tmp_path)
    conn = store.create(region="us-east-2")
    result = verify_connection(conn, role_arn=role_arn, runner=runner or FakeAWS(account))
    store.save(result.connection)
    return store


# -- developer mode -----------------------------------------------
def test_no_connection_is_developer_mode_with_profile_preserved(tmp_path):
    ex = resolve_cloud_execution(
        user=_user("dev"), workspace_root=tmp_path,
        region_hint="eu-west-1", profile_hint="cryo-dev",
    )
    assert ex.mode == MODE_DEVELOPER
    assert ex.credentials is None
    assert ex.profile == "cryo-dev"
    assert ex.region == "eu-west-1"
    assert ex.account_id == ""


# -- BYO mode ---------------------------------------------------
def test_connected_account_yields_a_fresh_assume_role_each_call(tmp_path):
    runner = FakeAWS("713938953301")
    _connect(tmp_path, "alice", ROLE_A, "713938953301", runner=runner)
    before = runner.calls

    ex1 = resolve_cloud_execution(user=_user("alice"), workspace_root=tmp_path, runner=runner)
    ex2 = resolve_cloud_execution(user=_user("alice"), workspace_root=tmp_path, runner=runner)

    assert ex1.mode == ex2.mode == MODE_BYO
    assert ex1.profile is None and ex2.profile is None
    assert runner.calls == before + 2                     # a fresh AssumeRole per op
    assert ex1.credentials != ex2.credentials             # distinct temp creds
    assert ex1.credentials["AWS_SESSION_TOKEN"] == "tok"


def test_byo_region_comes_from_the_connection(tmp_path):
    _connect(tmp_path, "alice", ROLE_A, "713938953301")
    ex = resolve_cloud_execution(
        user=_user("alice"), workspace_root=tmp_path,
        region_hint="eu-central-1",                       # ignored in BYO mode
        runner=FakeAWS("713938953301"),
    )
    assert ex.region == "us-east-2"


def test_byo_derives_the_account_scoped_defaults(tmp_path):
    _connect(tmp_path, "alice", ROLE_B, "774888247882")
    ex = resolve_cloud_execution(
        user=_user("alice"), workspace_root=tmp_path, runner=FakeAWS("774888247882")
    )
    assert ex.account_id == "774888247882"
    assert ex.defaults.bucket == "cryostack-runs-774888247882"
    assert ex.defaults.job_queue == "cryostack-queue"
    assert ex.defaults.job_definition == "cryostack-issm"
    assert ex.bucket(developer_fallback="ignored") == "cryostack-runs-774888247882"


# -- Icepack Cloud Execution checkpoint -----------------------------------
def test_byo_derives_icepack_specific_defaults_without_a_second_connection(tmp_path):
    """The SAME verified BYO connection, asked for the Icepack model instead
    of the (implicit) ISSM default, derives Icepack's own resource names --
    no separate onboarding, no cross-model leakage into the bucket (which
    stays account-scoped only, not model-scoped)."""
    _connect(tmp_path, "alice", ROLE_B, "774888247882")
    ex = resolve_cloud_execution(
        user=_user("alice"), workspace_root=tmp_path,
        runner=FakeAWS("774888247882"), model="icepack",
    )
    assert ex.account_id == "774888247882"
    assert ex.defaults.bucket == "cryostack-runs-774888247882"     # unchanged: account-scoped
    assert ex.defaults.job_queue == "cryostack-queue"              # shared queue
    assert ex.defaults.job_definition == "cryostack-icepack"       # model-scoped
    assert ex.defaults.ecr_repository == "cryostack-icepack"


def test_switching_model_never_leaks_the_other_models_job_definition(tmp_path):
    """Two resolves for the SAME connection, different models -- neither
    result carries a trace of the other model's resource names."""
    _connect(tmp_path, "alice", ROLE_B, "774888247882")
    issm = resolve_cloud_execution(
        user=_user("alice"), workspace_root=tmp_path,
        runner=FakeAWS("774888247882"), model="issm",
    )
    icepack = resolve_cloud_execution(
        user=_user("alice"), workspace_root=tmp_path,
        runner=FakeAWS("774888247882"), model="icepack",
    )
    assert issm.defaults.job_definition == "cryostack-issm"
    assert icepack.defaults.job_definition == "cryostack-icepack"
    assert issm.defaults.job_definition != icepack.defaults.job_definition
    assert issm.defaults.ecr_repository != icepack.defaults.ecr_repository
    # everything account-scoped (not model-scoped) stays identical
    assert issm.defaults.bucket == icepack.defaults.bucket
    assert issm.account_id == icepack.account_id == "774888247882"


# -- fail closed ------------------------------------------------
def test_assume_role_failure_never_falls_back_to_ambient(tmp_path):
    _connect(tmp_path, "alice", ROLE_A, "713938953301")
    with pytest.raises(CloudAccessError) as err:
        resolve_cloud_execution(
            user=_user("alice"), workspace_root=tmp_path,
            profile_hint="cryo-dev",                      # must NOT be used
            runner=FakeAWS("713938953301", deny=True),
        )
    assert "could not access your aws account" in str(err.value).lower()


def test_pending_connection_fails_closed_not_developer_fallback(tmp_path):
    store = AWSConnectionStore(user=_user("alice"), workspace_root=tmp_path)
    store.create(region="us-east-2")                      # never verified
    with pytest.raises(CloudAccessError, match="not verified"):
        resolve_cloud_execution(user=_user("alice"), workspace_root=tmp_path)


def test_account_drift_since_verification_fails_closed(tmp_path):
    _connect(tmp_path, "alice", ROLE_B, "774888247882")
    # the same role ARN now resolves to a different account
    runner = FakeAWS("774888247882")

    def drift(args, *, env=None):
        if args[:2] == ["sts", "get-caller-identity"]:
            return {"Account": "713938953301"}
        return runner(args, env=env)

    with pytest.raises(CloudAccessError):
        resolve_cloud_execution(user=_user("alice"), workspace_root=tmp_path, runner=drift)


# -- isolation -------------------------------------------------
def test_two_users_never_cross_credentials_or_accounts(tmp_path):
    _connect(tmp_path, "alice", ROLE_A, "713938953301")
    _connect(tmp_path, "bob", ROLE_B, "774888247882")

    a = resolve_cloud_execution(user=_user("alice"), workspace_root=tmp_path,
                                runner=FakeAWS("713938953301"))
    b = resolve_cloud_execution(user=_user("bob"), workspace_root=tmp_path,
                                runner=FakeAWS("774888247882"))

    assert a.account_id == "713938953301" and b.account_id == "774888247882"
    assert a.credentials["AWS_ACCESS_KEY_ID"].startswith("ASIA_713938953301")
    assert b.credentials["AWS_ACCESS_KEY_ID"].startswith("ASIA_774888247882")
    assert a.defaults.bucket != b.defaults.bucket


def test_resolved_execution_repr_hides_credentials(tmp_path):
    _connect(tmp_path, "alice", ROLE_A, "713938953301")
    ex = resolve_cloud_execution(user=_user("alice"), workspace_root=tmp_path,
                                 runner=FakeAWS("713938953301"))
    assert "sekret" not in repr(ex) and "tok" not in repr(ex)
