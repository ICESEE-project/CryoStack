"""C7.2 -- AWSOnboarding: connect / verify / disconnect, offline.

Account A = 713938953301, Account B = 774888247882 (fixtures only).
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.connect.onboarding import (
    TEMPLATE_URL_ENV,
    AWSOnboarding,
    OnboardingConfigError,
)
from cryostack_src.cloud.connect.principal import PRINCIPAL_ENV, PrincipalNotConfiguredError
from cryostack_src.workspace.identity import WorkspaceUser

PRINCIPAL = "arn:aws:iam::713938953301:role/cryostack-service"
TEMPLATE_URL = "https://cryostack-public.example/cf/execution-role.json"
ROLE_A = "arn:aws:iam::713938953301:role/CryoStackExecutionRole"
ROLE_B = "arn:aws:iam::774888247882:role/CryoStackExecutionRole"


def _user(uid: str) -> WorkspaceUser:
    return WorkspaceUser(user_id=uid, source="cryostack-auth")


class FakeAWS:
    def __init__(self, account="713938953301", deny=False):
        self.account = account
        self.deny = deny

    def __call__(self, args, *, env=None):
        if args[:2] == ["sts", "assume-role"]:
            if self.deny:
                # mirror what the real _default_runner does: sanitise before raise
                from cryostack_src.cloud.connect.assume_role import (
                    AssumeRoleError,
                    _sanitise_cli_error,
                )

                raise AssumeRoleError(
                    _sanitise_cli_error(
                        "AccessDenied: not authorized to perform: sts:AssumeRole"
                    )
                )
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


def _onboarding(tmp_path, uid="alice", **kw):
    return AWSOnboarding(
        user=_user(uid),
        workspace_root=tmp_path,
        template_url=TEMPLATE_URL,
        principal_arn=PRINCIPAL,
        region="us-east-2",
        **kw,
    )


def test_missing_principal_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.delenv(PRINCIPAL_ENV, raising=False)
    ob = AWSOnboarding(
        user=_user("alice"), workspace_root=tmp_path, template_url=TEMPLATE_URL
    )
    with pytest.raises(PrincipalNotConfiguredError, match=PRINCIPAL_ENV):
        ob.begin()


def test_missing_template_url_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.delenv(TEMPLATE_URL_ENV, raising=False)
    ob = AWSOnboarding(
        user=_user("alice"), workspace_root=tmp_path, principal_arn=PRINCIPAL
    )
    with pytest.raises(OnboardingConfigError, match=TEMPLATE_URL_ENV):
        ob.begin()


def test_begin_mints_a_connection_and_builds_a_prefilled_url(tmp_path):
    ob = _onboarding(tmp_path)
    step = ob.begin()
    assert step.connection.status == "pending"
    assert step.external_id == step.connection.external_id
    q = parse_qs(urlparse(step.setup_url).fragment.split("?", 1)[1])
    assert q["param_ExternalId"] == [step.external_id]
    assert q["param_CryoStackPrincipalArn"] == [PRINCIPAL]
    assert q["templateURL"] == [TEMPLATE_URL]


def test_external_id_is_stable_across_page_reloads(tmp_path):
    first = _onboarding(tmp_path).begin().external_id
    # a fresh onboarding object == a page reload
    second = _onboarding(tmp_path).begin().external_id
    third = _onboarding(tmp_path).current().external_id
    assert first == second == third


def test_reconnect_rotates_the_external_id(tmp_path):
    ob = _onboarding(tmp_path)
    first = ob.begin().external_id
    second = ob.reconnect().external_id
    assert first != second


def test_verify_success_marks_connected_and_persists_no_secrets(tmp_path):
    ob = _onboarding(tmp_path, runner=FakeAWS("713938953301"))
    ob.begin()
    result = ob.verify(role_arn=ROLE_A)
    assert result.ok and result.connection.account_id == "713938953301"

    # reload: connected metadata restored, no STS credentials on disk
    reloaded = _onboarding(tmp_path)
    summary = reloaded.summary()
    assert summary["status"] == "connected"
    assert summary["account_id"] == "713938953301"
    assert summary["access"] == "Temporary role"
    assert summary["defaults"]["bucket"] == "cryostack-runs-713938953301"
    disk = reloaded.store.path.read_text(encoding="utf-8").lower()
    assert "sessiontoken" not in disk and "asia_" not in disk


def test_verify_account_mismatch_fails_closed(tmp_path):
    ob = _onboarding(tmp_path, runner=FakeAWS("713938953301"))
    ob.begin()
    result = ob.verify(role_arn=ROLE_B)  # role says B, session is A
    assert not result.ok
    assert "mismatch" in result.connection.status_reason.lower()
    assert ob.summary()["status"] == "error"


def test_verify_denial_is_actionable_not_an_exception(tmp_path):
    ob = _onboarding(tmp_path, runner=FakeAWS(deny=True))
    ob.begin()
    result = ob.verify(role_arn=ROLE_A)
    assert not result.ok
    assert "trust policy" in result.connection.status_reason.lower()


def test_disconnect_removes_only_the_acting_users_connection(tmp_path):
    alice = _onboarding(tmp_path, uid="alice", runner=FakeAWS("713938953301"))
    bob = _onboarding(tmp_path, uid="bob", runner=FakeAWS("774888247882"))
    alice.begin(); alice.verify(role_arn=ROLE_A)
    bob.begin(); bob.verify(role_arn=ROLE_B)

    alice.disconnect()
    assert alice.current() is None
    assert bob.current() is not None and bob.summary()["account_id"] == "774888247882"


def test_one_user_cannot_read_another_users_connection(tmp_path):
    bob = _onboarding(tmp_path, uid="bob", runner=FakeAWS("774888247882"))
    bob.begin()
    bob_ext = bob.verify(role_arn=ROLE_B).connection.external_id

    alice = _onboarding(tmp_path, uid="alice")
    assert alice.current() is None
    assert alice.summary()["status"] == "disconnected"
    # alice minting her own gets a different ExternalId + no visibility of B's
    assert alice.begin().external_id != bob_ext


def test_recheck_reuses_the_stored_role_arn(tmp_path):
    ob = _onboarding(tmp_path, runner=FakeAWS("713938953301"))
    ob.begin()
    ob.verify(role_arn=ROLE_A)
    again = ob.recheck()
    assert again.ok and again.connection.account_id == "713938953301"
