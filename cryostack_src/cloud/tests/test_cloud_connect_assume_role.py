"""C7.1 -- cross-account STS AssumeRole + verification, fully offline."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.connect import (
    AWSConnection,
    AssumeRoleError,
    assume_role,
    verify_connection,
)

ROLE_B = "arn:aws:iam::774888247882:role/CryoStackExecutionRole"
EXTERNAL_ID = "cryostack:alice-abc:secret-random"


class FakeAWS:
    """Records every `aws` invocation and replays canned STS responses."""

    def __init__(self, *, account="774888247882", deny=False, no_creds=False):
        self.account = account
        self.deny = deny
        self.no_creds = no_creds
        self.calls: list[dict] = []

    def __call__(self, args, *, env=None):
        self.calls.append({"args": list(args), "env": dict(env) if env else None})
        if args[:2] == ["sts", "assume-role"]:
            if self.deny:
                raise AssumeRoleError("AccessDenied: not authorized to perform: sts:AssumeRole")
            if "--external-id" not in args:
                raise AssumeRoleError("test policy requires an ExternalId")
            if self.no_creds:
                return {"AssumedRoleUser": {"Arn": "x"}}
            return {
                "Credentials": {
                    "AccessKeyId": "ASIA_TEMP",
                    "SecretAccessKey": "temp-secret",
                    "SessionToken": "temp-token",
                    "Expiration": "2026-09-03T01:00:00Z",
                }
            }
        if args[:2] == ["sts", "get-caller-identity"]:
            assert env and env.get("AWS_ACCESS_KEY_ID") == "ASIA_TEMP"
            return {"Account": self.account, "Arn": f"arn:aws:sts::{self.account}:assumed-role/x/y"}
        raise AssertionError(f"unexpected call: {args}")


def test_assume_role_returns_a_live_context_with_temporary_env():
    fake = FakeAWS()
    ctx = assume_role(role_arn=ROLE_B, external_id=EXTERNAL_ID, region="us-east-2", runner=fake)
    assert ctx.account_id == "774888247882"
    env = ctx.environment()
    assert env["AWS_ACCESS_KEY_ID"] == "ASIA_TEMP"
    assert env["AWS_SESSION_TOKEN"] == "temp-token"
    # the assume-role call actually carried the ExternalId
    ar = next(c for c in fake.calls if c["args"][:2] == ["sts", "assume-role"])
    assert "--external-id" in ar["args"]
    assert EXTERNAL_ID in ar["args"]
    # duration is bounded and short
    assert "900" in ar["args"]


def test_assume_role_without_external_id_fails_in_test_policy():
    with pytest.raises(AssumeRoleError):
        assume_role(role_arn=ROLE_B, external_id="", region="us-east-2", runner=FakeAWS())


def test_account_mismatch_fails_closed():
    fake = FakeAWS(account="713938953301")  # not the account in ROLE_B
    with pytest.raises(AssumeRoleError, match="mismatch"):
        assume_role(role_arn=ROLE_B, external_id=EXTERNAL_ID, region="us-east-2", runner=fake)


def test_missing_credentials_in_payload_is_an_error():
    with pytest.raises(AssumeRoleError):
        assume_role(
            role_arn=ROLE_B, external_id=EXTERNAL_ID, region="us-east-2",
            runner=FakeAWS(no_creds=True),
        )


def test_context_repr_never_shows_secret_material():
    ctx = assume_role(role_arn=ROLE_B, external_id=EXTERNAL_ID, region="us-east-2", runner=FakeAWS())
    for rendered in (repr(ctx), str(ctx), f"{ctx!r}", f"{ctx}"):
        assert "temp-secret" not in rendered
        assert "temp-token" not in rendered
        assert "ASIA_TEMP" not in rendered
        assert "redacted" in rendered.lower()


def test_verify_connection_folds_result_into_a_persistable_record():
    conn = AWSConnection(connection_id="c1", external_id=EXTERNAL_ID, region="us-east-2")
    result = verify_connection(conn, role_arn=ROLE_B, runner=FakeAWS())
    assert result.ok
    assert result.connection.account_id == "774888247882"
    assert result.connection.is_connected
    # the context is returned for immediate use but is not part of the record
    assert result.context is not None
    assert "context" not in result.connection.to_dict()


def test_verify_connection_reports_denial_as_error_status_not_exception():
    conn = AWSConnection(connection_id="c1", external_id=EXTERNAL_ID, region="us-east-2")
    result = verify_connection(conn, role_arn=ROLE_B, runner=FakeAWS(deny=True))
    assert not result.ok
    assert result.connection.status == "error"
    assert result.connection.status_reason
    assert result.context is None
