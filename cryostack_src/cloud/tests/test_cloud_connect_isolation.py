"""C7.1 -- account/user isolation for AWS connections.

Account A = 713938953301, Account B = 774888247882 (test fixtures only --
never product defaults).
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.connect import AWSConnection, AWSConnectionStore, verify_connection
from cryostack_src.workspace.identity import WorkspaceUser

ROLE_A = "arn:aws:iam::713938953301:role/CryoStackExecutionRole"
ROLE_B = "arn:aws:iam::774888247882:role/CryoStackExecutionRole"


def _user(uid: str) -> WorkspaceUser:
    return WorkspaceUser(user_id=uid, source="cryostack-auth")


class FakeAWS:
    def __init__(self, account):
        self.account = account

    def __call__(self, args, *, env=None):
        if args[:2] == ["sts", "assume-role"]:
            return {
                "Credentials": {
                    "AccessKeyId": f"ASIA_{self.account}",
                    "SecretAccessKey": "s",
                    "SessionToken": "t",
                    "Expiration": "2026-09-03T01:00:00Z",
                }
            }
        if args[:2] == ["sts", "get-caller-identity"]:
            return {"Account": self.account}
        raise AssertionError(args)


def test_two_users_get_distinct_external_ids_and_files(tmp_path):
    alice = AWSConnectionStore(user=_user("alice"), workspace_root=tmp_path)
    bob = AWSConnectionStore(user=_user("bob"), workspace_root=tmp_path)

    ca = alice.create(region="us-east-2")
    cb = bob.create(region="us-east-2")

    assert ca.external_id != cb.external_id
    assert ca.connection_id != cb.connection_id
    assert alice.path != bob.path


def test_a_cannot_read_or_use_bs_connection(tmp_path):
    bob = AWSConnectionStore(user=_user("bob"), workspace_root=tmp_path)
    bob.save(
        AWSConnection(
            connection_id="conn-bob", external_id="cryostack:bob:xyz",
            region="us-east-2", role_arn=ROLE_B,
        ).mark_connected(account_id="774888247882")
    )

    alice = AWSConnectionStore(user=_user("alice"), workspace_root=tmp_path)
    # Alice's store simply has nothing -- B's record is not on her path
    assert alice.load() is None
    assert alice.path != bob.path


def test_each_account_verifies_to_its_own_id_and_temp_creds_do_not_cross(tmp_path):
    alice = AWSConnectionStore(user=_user("alice"), workspace_root=tmp_path)
    bob = AWSConnectionStore(user=_user("bob"), workspace_root=tmp_path)

    ra = verify_connection(alice.create(region="us-east-2"), role_arn=ROLE_A,
                           runner=FakeAWS("713938953301"))
    rb = verify_connection(bob.create(region="us-east-2"), role_arn=ROLE_B,
                           runner=FakeAWS("774888247882"))

    assert ra.connection.account_id == "713938953301"
    assert rb.connection.account_id == "774888247882"
    assert ra.context.environment() != rb.context.environment()
    assert ra.context.environment()["AWS_ACCESS_KEY_ID"] == "ASIA_713938953301"


def test_attaching_a_foreign_role_arn_still_verifies_against_its_own_account(tmp_path):
    """A user pasting account B's role ARN into their own connection only
    succeeds if they actually control B (the AssumeRole itself is the gate);
    the resulting account_id is B's, recorded under *their* user file only."""
    alice = AWSConnectionStore(user=_user("alice"), workspace_root=tmp_path)
    conn = alice.create(region="us-east-2")

    result = verify_connection(conn, role_arn=ROLE_B, runner=FakeAWS("774888247882"))
    alice.save(result.connection)

    # recorded on Alice's path only; Bob's store is untouched
    bob = AWSConnectionStore(user=_user("bob"), workspace_root=tmp_path)
    assert bob.load() is None
    assert alice.load().account_id == "774888247882"


def test_role_arn_account_mismatch_is_rejected(tmp_path):
    alice = AWSConnectionStore(user=_user("alice"), workspace_root=tmp_path)
    conn = alice.create(region="us-east-2")
    # role says account B, but the session comes back as account A
    result = verify_connection(conn, role_arn=ROLE_B, runner=FakeAWS("713938953301"))
    assert not result.ok
    assert "mismatch" in result.connection.status_reason.lower()


def test_pending_replacement_is_isolated_per_user(tmp_path):
    """Alice's staged "Change AWS account" attempt (and the file it lives
    in) must be invisible to and unreachable from Bob's store -- same
    guarantee as the active connection, extended to the pending slot."""
    from cryostack_src.cloud.connect.onboarding import AWSOnboarding

    alice = AWSOnboarding(
        user=_user("alice"), workspace_root=tmp_path,
        template_url="https://x.example/t.json",
        principal_arn="arn:aws:iam::713938953301:role/cryostack-service",
    )
    bob = AWSOnboarding(
        user=_user("bob"), workspace_root=tmp_path,
        template_url="https://x.example/t.json",
        principal_arn="arn:aws:iam::713938953301:role/cryostack-service",
    )

    alice.begin()
    alice.begin_change_account()

    assert alice.store.pending_path != bob.store.pending_path
    assert bob.store.load_pending() is None
    assert not bob.has_pending_replacement()
    # Bob starting his own replacement never collides with Alice's
    bob.begin_change_account()
    assert alice.store.load_pending().external_id != bob.store.load_pending().external_id


def test_change_account_recovery_only_touches_the_acting_users_file(tmp_path):
    """"Change AWS account" (AWSOnboarding.reconnect -- delete + create) must
    never reach across to another CryoStack user's connection file."""
    from cryostack_src.cloud.connect.onboarding import AWSOnboarding

    alice = AWSOnboarding(
        user=_user("alice"), workspace_root=tmp_path,
        template_url="https://x.example/t.json",
        principal_arn="arn:aws:iam::713938953301:role/cryostack-service",
    )
    bob_store = AWSConnectionStore(user=_user("bob"), workspace_root=tmp_path)
    bob_store.save(
        AWSConnection(
            connection_id="conn-bob", external_id="cryostack:bob:xyz",
            region="us-east-2", role_arn=ROLE_B,
        ).mark_connected(account_id="774888247882")
    )

    alice.begin()
    alice.reconnect()                  # "Change AWS account" for alice only

    # Bob's connection is byte-for-byte untouched
    reloaded_bob = AWSConnectionStore(user=_user("bob"), workspace_root=tmp_path).load()
    assert reloaded_bob.connection_id == "conn-bob"
    assert reloaded_bob.external_id == "cryostack:bob:xyz"
    assert reloaded_bob.account_id == "774888247882"
