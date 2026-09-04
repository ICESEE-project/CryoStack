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


# -- C7 live-acceptance: recovering a failed/stranded connection -----------
def test_forgotten_role_arn_survives_a_failed_verify_and_is_readable_back(tmp_path):
    """A failed AssumeRole still persists the Role ARN the user typed --
    "forgotten ARN" is recoverable because it was never lost."""
    ob = _onboarding(tmp_path, runner=FakeAWS(deny=True))
    ob.begin()
    result = ob.verify(role_arn=ROLE_A)
    assert not result.ok

    reloaded = _onboarding(tmp_path)
    summary = reloaded.summary()
    assert summary["status"] == "error"
    assert summary["role_arn"] == ROLE_A


def test_retry_via_begin_after_a_failed_verify_does_not_rotate_the_external_id(tmp_path):
    """"Retry connection" is `begin()` on the existing record -- it must
    reuse the ExternalId a failed verification already spent (the cross-
    account trust policy was written against it), never mint a new one."""
    ob = _onboarding(tmp_path, runner=FakeAWS(deny=True))
    ob.begin()
    before = ob.current().external_id
    ob.verify(role_arn=ROLE_A)                 # fails -> status "error"
    after_failure = ob.current().external_id
    assert after_failure == before

    # "Retry connection" reopens the card via begin() -- same record
    retry_step = ob.begin()
    assert retry_step.external_id == before
    assert retry_step.connection.role_arn == ROLE_A
    assert ob.current().external_id == before   # still not rotated


def test_retry_then_verify_succeeds_and_recovers_the_same_connection(tmp_path):
    """A repaired role (the user fixed the trust policy in AWS) verifies
    successfully on retry, still under the original ExternalId."""
    ob = _onboarding(tmp_path, runner=FakeAWS(deny=True))
    ob.begin()
    ext_id = ob.current().external_id
    ob.verify(role_arn=ROLE_A)
    assert ob.summary()["status"] == "error"

    ob2 = _onboarding(tmp_path, runner=FakeAWS("713938953301"))  # role now works
    result = ob2.verify(role_arn=ROLE_A)
    assert result.ok
    assert result.connection.external_id == ext_id
    assert result.connection.account_id == "713938953301"


def test_begin_change_account_stages_without_touching_the_active_connection(tmp_path):
    """Starting a replacement must not read or modify the active record at
    all -- the smallest, most direct proof that Change AWS account is not
    immediately destructive."""
    ob = _onboarding(tmp_path, runner=FakeAWS(deny=True))
    ob.begin()
    ob.verify(role_arn=ROLE_A)                 # active left in "error"
    active_before = ob.current()

    step = ob.begin_change_account()
    assert ob.current() == active_before        # untouched, byte-for-byte
    assert step.connection.status == "pending"
    assert step.connection.role_arn == ""
    assert step.connection.external_id != active_before.external_id
    assert ob.has_pending_replacement()
    assert ob.pending_replacement_summary()["status"] == "pending"


def test_begin_change_account_is_idempotent_across_repeat_calls(tmp_path):
    """A second click (or a page reload resuming the same attempt) must
    reuse the SAME pending ExternalId, not mint another one -- otherwise a
    role already created against the first would stop matching."""
    ob = _onboarding(tmp_path)
    first = ob.begin_change_account()
    second = ob.begin_change_account()
    assert first.external_id == second.external_id
    assert ob.store.load_pending().connection_id == first.connection.connection_id


def test_verify_pending_replacement_failure_leaves_active_connection_intact(tmp_path):
    ob = _onboarding(tmp_path, runner=FakeAWS("713938953301"))
    ob.begin()
    ob.verify(role_arn=ROLE_A)
    active_before = ob.current()
    assert active_before.is_connected

    denying = _onboarding(tmp_path, runner=FakeAWS(deny=True))
    denying.begin_change_account()
    result = denying.verify_pending_replacement(role_arn=ROLE_B)
    assert not result.ok

    assert ob.current() == active_before          # active: untouched
    pending = ob.store.load_pending()
    assert pending is not None and pending.status == "error"


def test_verify_pending_replacement_success_promotes_atomically(tmp_path):
    ob = _onboarding(tmp_path, runner=FakeAWS("713938953301"))
    ob.begin()
    ob.verify(role_arn=ROLE_A)
    old_external_id = ob.current().external_id

    switching = _onboarding(tmp_path, runner=FakeAWS("774888247882"))
    switching.begin_change_account()
    new_pending_external_id = switching.store.load_pending().external_id
    result = switching.verify_pending_replacement(role_arn=ROLE_B)
    assert result.ok

    active = ob.current()
    assert active.account_id == "774888247882"
    assert active.external_id == new_pending_external_id
    assert active.external_id != old_external_id
    assert ob.store.load_pending() is None         # promoted AND cleared


def test_cancel_change_account_only_discards_the_pending_slot(tmp_path):
    ob = _onboarding(tmp_path, runner=FakeAWS(deny=True))
    ob.begin()
    ob.verify(role_arn=ROLE_A)
    active_before = ob.current()

    ob.begin_change_account()
    assert ob.has_pending_replacement()
    ob.cancel_change_account()
    assert not ob.has_pending_replacement()
    assert ob.current() == active_before


def test_pending_replacement_survives_reading_the_onboarding_object_fresh(tmp_path):
    """Simulates a page refresh mid-switch: a brand-new AWSOnboarding over
    the same store must find the SAME pending record (not lose it, not
    silently fold it into the active connection)."""
    ob = _onboarding(tmp_path, runner=FakeAWS(deny=True))
    ob.begin()
    ob.verify(role_arn=ROLE_A)

    started = _onboarding(tmp_path)
    step = started.begin_change_account()

    reloaded = _onboarding(tmp_path)
    assert reloaded.has_pending_replacement()
    assert reloaded.store.load_pending().external_id == step.external_id
    # the active connection is exactly what it was before the reload
    assert reloaded.summary()["status"] == "error"


def test_same_account_replacement_still_promotes_with_a_fresh_external_id(tmp_path):
    """The live-acceptance scenario: the browser is still on the SAME AWS
    account when Change AWS account is used. CryoStack cannot see the
    CloudFormation AlreadyExistsException -- only the AssumeRole outcome --
    so a role that DOES verify for the same account must promote cleanly
    rather than strand the user, just with a freshly rotated ExternalId."""
    ob = _onboarding(tmp_path, runner=FakeAWS("774888247882"))
    ob.begin()
    ob.verify(role_arn=ROLE_B)
    old_external_id = ob.current().external_id

    same = _onboarding(tmp_path, runner=FakeAWS("774888247882"))
    same.begin_change_account()
    result = same.verify_pending_replacement(role_arn=ROLE_B)
    assert result.ok
    active = ob.current()
    assert active.account_id == "774888247882"
    assert active.external_id != old_external_id   # rotated, not reused
    assert same.store.load_pending() is None


def test_change_account_via_reconnect_replaces_only_this_users_metadata(tmp_path):
    """"Change AWS account" == reconnect(): a fresh connection_id + external_id
    for THIS user only. It never touches another user's file (isolation is
    covered separately) and, being a pure local JSON write, never touches any
    other kind of local state (run history, logs, results) either."""
    ob = _onboarding(tmp_path, runner=FakeAWS(deny=True))
    ob.begin()
    ob.verify(role_arn=ROLE_A)                  # left in "error"
    stranded_path = ob.store.path
    stranded_external_id = ob.current().external_id

    step = ob.reconnect()                       # "Change AWS account"
    assert step.connection.status == "pending"
    assert step.connection.role_arn == ""        # no carry-over to a new account
    assert step.connection.external_id != stranded_external_id
    assert ob.store.path == stranded_path         # same file, new content

    ob2 = _onboarding(tmp_path, runner=FakeAWS("774888247882"))
    result = ob2.verify(role_arn=ROLE_B)
    assert result.ok and result.connection.account_id == "774888247882"
