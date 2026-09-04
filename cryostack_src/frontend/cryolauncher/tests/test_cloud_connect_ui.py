"""C7.2 -- the AWS ACCOUNT onboarding block + its callbacks.

UI-only: the real ipywidgets card is built, but AWS is a fake STS runner and
the store is a tmp workspace. A deferred ``spawn`` lets the busy state be
observed.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.connect.onboarding import AWSOnboarding
from cryostack_src.frontend.cryolauncher import cloud_environment as ce_mod
from cryostack_src.frontend.cryolauncher.cloud_connect_runtime import (
    build_aws_connect_callbacks,
)
from cryostack_src.frontend.cryolauncher.cloud_environment import (
    build_cloud_environment_card,
    set_aws_account_view,
)
from cryostack_src.workspace.identity import WorkspaceUser

PRINCIPAL = "arn:aws:iam::713938953301:role/cryostack-service"
TEMPLATE_URL = "https://cryostack-public.example/cf/execution-role.json"
ROLE_B = "arn:aws:iam::774888247882:role/CryoStackExecutionRole"
ROLE_A = "arn:aws:iam::713938953301:role/CryoStackExecutionRole"


class _Out:
    def __init__(self):
        self.text = ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def clear_output(self, *a, **k):
        self.text = ""


class FakeAWS:
    def __init__(self, account="774888247882", deny=False):
        self.account = account
        self.deny = deny

    def __call__(self, args, *, env=None):
        if args[:2] == ["sts", "assume-role"]:
            if self.deny:
                from cryostack_src.cloud.connect.assume_role import (
                    AssumeRoleError,
                    _sanitise_cli_error,
                )

                raise AssumeRoleError(_sanitise_cli_error("AccessDenied: sts:AssumeRole"))
            return {
                "Credentials": {
                    "AccessKeyId": "ASIA_TEMP", "SecretAccessKey": "sekret",
                    "SessionToken": "tok", "Expiration": "2026-09-03T01:00:00Z",
                }
            }
        if args[:2] == ["sts", "get-caller-identity"]:
            return {"Account": self.account}
        raise AssertionError(args)


class _DeferredSpawn:
    def __init__(self):
        self.pending = []

    def __call__(self, coro):
        self.pending.append(coro)

    def run(self):
        import asyncio

        while self.pending:
            asyncio.run(self.pending.pop(0))


@pytest.fixture
def card():
    return build_cloud_environment_card()


def _factory(tmp_path, *, runner):
    def make():
        return AWSOnboarding(
            user=WorkspaceUser(user_id="alice", source="cryostack-auth"),
            workspace_root=tmp_path,
            template_url=TEMPLATE_URL,
            principal_arn=PRINCIPAL,
            region="us-east-2",
            runner=runner,
        )

    return make


# -- static UI guarantees -------------------------------------------
def test_card_has_no_access_key_or_secret_field_anywhere(card):
    texts = []

    def walk(w):
        for attr in ("value", "placeholder", "description"):
            v = getattr(w, attr, None)
            if isinstance(v, str):
                texts.append(v.lower())
        for child in getattr(w, "children", []) or []:
            walk(child)
        for child in getattr(getattr(w, "advanced", None), "children", []) or []:
            walk(child)

    walk(card.container)
    walk(card.advanced)
    blob = " ".join(texts)
    # the reassurance copy is allowed to mention "access keys"; a *prompt* to
    # enter one is not.
    blob = blob.replace("does not store your aws access keys", "")
    assert "access key id" not in blob
    assert "secret access key" not in blob
    assert "aws password" not in blob
    assert "enter your" not in blob or "access" not in blob
    # the source module never builds a password/secret input
    src = inspect.getsource(ce_mod)
    assert "Password(" not in src


def test_disconnected_copy_is_the_contract_text(card):
    set_aws_account_view(card, {"status": "disconnected", "region": "us-east-2"})
    assert "Not connected" in card.aws_account_status.value
    assert "does not store your AWS access keys" in card.aws_account_detail.value
    assert card.connect_form.layout.display == "none"


def test_connected_view_shows_account_and_temporary_role(card):
    set_aws_account_view(
        card,
        {
            "status": "connected", "account_id": "774888247882",
            "region": "us-east-2", "verified_at": "2026-09-03T12:00:00+00:00",
        },
    )
    d = card.aws_account_detail.value
    assert "774888247882" in d and "Temporary role" in d
    assert card.connect_actions.layout.display == "flex"
    assert card.connect_button.layout.display == "none"


# -- callback behaviour --------------------------------------------
def test_connect_reveals_the_card_and_a_quick_create_link(tmp_path, card):
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=_factory(tmp_path, runner=FakeAWS()),
        log_output=_Out(),
    )
    cbs.connect()
    assert card.connect_form.layout.display == "flex"
    assert "Open AWS Setup" in card.open_setup_link.value
    assert "quickcreate" in card.open_setup_link.value
    assert "param_ExternalId" in card.open_setup_link.value


def test_verify_success_moves_the_block_to_connected(tmp_path, card):
    spawn = _DeferredSpawn()
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=_factory(tmp_path, runner=FakeAWS("774888247882")),
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_B
    cbs.verify()
    spawn.run()
    assert "Connected" in card.aws_account_status.value
    assert "774888247882" in card.aws_account_detail.value
    # no secret material rendered
    assert "sekret" not in card.aws_account_detail.value
    assert "ASIA_TEMP" not in card.aws_account_detail.value


def test_verify_account_mismatch_fails_closed_in_ui(tmp_path, card):
    spawn = _DeferredSpawn()
    cbs = build_aws_connect_callbacks(
        widgets=card,
        onboarding_factory=_factory(tmp_path, runner=FakeAWS("713938953301")),
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_B  # role says B, session comes back A
    cbs.verify()
    spawn.run()
    assert "Not verified" in card.aws_account_status.value
    assert "mismatch" in card.aws_account_detail.value.lower()


def test_verify_denial_shows_actionable_error(tmp_path, card):
    spawn = _DeferredSpawn()
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=_factory(tmp_path, runner=FakeAWS(deny=True)),
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_B
    cbs.verify()
    spawn.run()
    assert "trust policy" in card.aws_account_detail.value.lower()


def test_verify_requires_a_role_arn(tmp_path, card):
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=_factory(tmp_path, runner=FakeAWS()),
        log_output=_Out(),
    )
    cbs.connect()
    card.role_arn_input.value = ""
    cbs.verify()
    assert "role arn" in card.aws_account_detail.value.lower()


def test_on_state_fires_for_every_state_so_the_gateway_can_toggle_test_button(tmp_path, card):
    """C7.3: once connected, Prepare -- not Test connection -- is the normal
    action; disconnecting must restore Test connection."""
    spawn = _DeferredSpawn()
    seen = []
    cbs = build_aws_connect_callbacks(
        widgets=card,
        onboarding_factory=_factory(tmp_path, runner=FakeAWS("774888247882")),
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
        on_state=lambda s: seen.append(s.get("status")),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_B
    cbs.verify()
    spawn.run()
    assert "connected" in seen

    seen.clear()
    cbs.disconnect()
    assert seen and seen[-1] == "disconnected"


def test_disconnect_returns_to_the_disconnected_view(tmp_path, card):
    spawn = _DeferredSpawn()
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=_factory(tmp_path, runner=FakeAWS("774888247882")),
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_B
    cbs.verify()
    spawn.run()
    assert "Connected" in card.aws_account_status.value

    cbs.disconnect()
    assert "Not connected" in card.aws_account_status.value
    assert card.role_arn_input.value == ""


def test_missing_principal_shows_a_clear_config_error(tmp_path, card):
    def make():
        return AWSOnboarding(
            user=WorkspaceUser(user_id="alice", source="cryostack-auth"),
            workspace_root=tmp_path, template_url=TEMPLATE_URL, region="us-east-2",
        )  # no principal_arn, env unset

    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=make, log_output=_Out()
    )
    cbs.connect()
    assert "CRYOSTACK_AWS_PRINCIPAL_ARN" in card.aws_account_detail.value


def test_refresh_restores_connected_metadata_without_sts_credentials(tmp_path, card):
    spawn = _DeferredSpawn()
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=_factory(tmp_path, runner=FakeAWS("774888247882")),
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_B
    cbs.verify()
    spawn.run()

    # a "page reload": a fresh card + fresh callbacks, same tmp workspace
    fresh = build_cloud_environment_card()
    cbs2 = build_aws_connect_callbacks(
        widgets=fresh, onboarding_factory=_factory(tmp_path, runner=FakeAWS("774888247882")),
        log_output=_Out(),
    )
    cbs2.refresh()
    assert "Connected" in fresh.aws_account_status.value
    assert "774888247882" in fresh.aws_account_detail.value


# -- C7 live-acceptance: failed-verification recovery ---------------------
def test_failed_verification_reveals_two_explicit_recovery_actions(tmp_path, card):
    """The stranding bug: a failed verify used to leave NO reachable action
    (connect_actions -- Re-check/Disconnect -- is connected-only). Retry
    connection / Change AWS account must be visible and enabled instead."""
    spawn = _DeferredSpawn()
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=_factory(tmp_path, runner=FakeAWS(deny=True)),
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_B
    cbs.verify()
    spawn.run()

    assert "Not verified" in card.aws_account_status.value
    assert card.recovery_actions.layout.display == "flex"
    assert card.retry_button.disabled is False
    assert card.change_account_button.disabled is False


def test_retry_prepopulates_the_saved_role_arn_and_keeps_the_external_id(tmp_path, card):
    """Forgotten-ARN recovery: the saved Role ARN comes back on Retry, and the
    ExternalId is the SAME one the (already-written) trust policy uses --
    retry must never silently break a repair by rotating it."""
    spawn = _DeferredSpawn()
    factory = _factory(tmp_path, runner=FakeAWS(deny=True))
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=factory,
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    external_id_before = factory().current().external_id
    card.role_arn_input.value = ROLE_B
    cbs.verify()
    spawn.run()
    assert "Not verified" in card.aws_account_status.value

    card.role_arn_input.value = ""            # simulate "I forgot it"
    cbs.retry()
    assert card.role_arn_input.value == ROLE_B
    assert card.connect_form.layout.display == "flex"
    assert factory().current().external_id == external_id_before


def test_retry_then_verify_recovers_a_repaired_connection(tmp_path):
    """End to end: fails, Retry, fix nothing but the AWS-side role (simulated
    by swapping in a working runner) -- the SAME local connection verifies."""
    card = build_cloud_environment_card()
    spawn = _DeferredSpawn()
    denying = _factory(tmp_path, runner=FakeAWS(deny=True))
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=denying,
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_B
    cbs.verify()
    spawn.run()
    assert "Not verified" in card.aws_account_status.value

    working = _factory(tmp_path, runner=FakeAWS("774888247882"))
    cbs2 = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=working,
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs2.retry()
    assert card.role_arn_input.value == ROLE_B     # prepopulated, unchanged
    cbs2.verify()
    spawn.run()
    assert "Connected" in card.aws_account_status.value
    assert "774888247882" in card.aws_account_detail.value


def test_change_account_stages_a_replacement_without_touching_the_active_connection(
    tmp_path, card
):
    """"Change AWS account" must NOT be immediately destructive: starting it
    mints a fresh ExternalId into a SEPARATE pending slot, and the active
    connection (its own ExternalId + Role ARN) is untouched -- still visible,
    still what Retry connection would use."""
    spawn = _DeferredSpawn()
    factory = _factory(tmp_path, runner=FakeAWS(deny=True))
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=factory,
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_B
    cbs.verify()
    spawn.run()
    assert "Not verified" in card.aws_account_status.value
    active_before = factory().current()

    cbs.change_account()

    # the active connection is byte-for-byte unchanged
    active_after = factory().current()
    assert active_after == active_before
    assert active_after.role_arn == ROLE_B
    # the ACTIVE view (still "error") is unaffected -- change_account never
    # calls _render() for the active summary
    assert "Not verified" in card.aws_account_status.value

    # the pending replacement is a genuinely separate, fresh record
    pending = factory().store.load_pending()
    assert pending is not None
    assert pending.status == "pending"
    assert pending.role_arn == ""
    assert pending.external_id != active_after.external_id
    assert card.change_account_panel.layout.display == "flex"
    assert "Open AWS Setup" in card.change_setup_link.value


def test_change_account_cancel_discards_the_pending_attempt_only(tmp_path, card):
    """Cancel / Back to current account: the pending replacement disappears,
    the active connection (Role ARN + ExternalId) is exactly as it was."""
    spawn = _DeferredSpawn()
    factory = _factory(tmp_path, runner=FakeAWS(deny=True))
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=factory,
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_B
    cbs.verify()
    spawn.run()
    active_before = factory().current()

    cbs.change_account()
    assert factory().store.load_pending() is not None

    cbs.change_cancel()
    assert factory().store.load_pending() is None
    assert factory().current() == active_before
    assert card.change_account_panel.layout.display == "none"
    assert card.change_role_arn_input.value == ""


def test_change_account_failed_verification_leaves_the_active_connection_intact(
    tmp_path, card
):
    """A wrong/incomplete role for the replacement fails closed: the pending
    record records the error, the ACTIVE connection is never touched, and
    Retry connection on the original account still works afterwards."""
    spawn = _DeferredSpawn()
    factory = _factory(tmp_path, runner=FakeAWS("774888247882"))
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=factory,
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_B
    cbs.verify()
    spawn.run()
    assert "Connected" in card.aws_account_status.value
    active_before = factory().current()

    denying = _factory(tmp_path, runner=FakeAWS(deny=True))
    cbs2 = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=denying,
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs2.change_account()
    card.change_role_arn_input.value = ROLE_A
    cbs2.change_verify()
    spawn.run()

    # active connection: completely unaffected by the failed replacement
    assert factory().current() == active_before
    assert "Connected" in card.aws_account_status.value
    assert "774888247882" in card.aws_account_detail.value
    # the pending record carries the failure, the panel stays open
    pending = factory().store.load_pending()
    assert pending is not None and pending.status == "error"
    assert card.change_account_panel.layout.display == "flex"
    assert "trust policy" in card.change_account_status.value.lower()


def test_change_account_a_to_b_switch_promotes_atomically_on_success(tmp_path, card):
    """The only moment the active connection changes: a successful
    AssumeRole/GetCallerIdentity for the replacement. Before that instant the
    OLD account (A) is active; after it, B is -- there is no in-between
    state where neither or both are "active"."""
    spawn = _DeferredSpawn()
    factory_a = _factory(tmp_path, runner=FakeAWS("713938953301"))
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=factory_a,
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_A
    cbs.verify()
    spawn.run()
    assert "Connected" in card.aws_account_status.value
    assert "713938953301" in card.aws_account_detail.value

    factory_b = _factory(tmp_path, runner=FakeAWS("774888247882"))
    cbs2 = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=factory_b,
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs2.change_account()
    # mid-flight: A is STILL the active connection
    assert factory_b().current().account_id == "713938953301"

    card.change_role_arn_input.value = ROLE_B
    cbs2.change_verify()
    spawn.run()

    # atomically promoted: B is now active, no pending record remains
    active = factory_b().current()
    assert active.account_id == "774888247882"
    assert active.role_arn == ROLE_B
    assert factory_b().store.load_pending() is None
    assert "Connected" in card.aws_account_status.value
    assert "774888247882" in card.aws_account_detail.value
    assert card.change_account_panel.layout.display == "none"


def test_old_connection_stays_usable_via_retry_until_the_replacement_verifies(
    tmp_path, card
):
    """While a replacement is pending (and un-verified), the ORIGINAL
    connection is not merely inert -- Retry connection on it still works,
    proving its ExternalId/Role ARN were never disturbed."""
    spawn = _DeferredSpawn()
    factory = _factory(tmp_path, runner=FakeAWS(deny=True))
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=factory,
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_B
    cbs.verify()
    spawn.run()
    original_external_id = factory().current().external_id

    cbs.change_account()                     # start a replacement, never verified
    assert factory().store.load_pending() is not None

    # Retry connection on the ORIGINAL still reuses its own ExternalId and
    # can still be verified successfully
    working = _factory(tmp_path, runner=FakeAWS("774888247882"))
    cbs2 = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=working,
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs2.retry()
    assert card.role_arn_input.value == ROLE_B
    cbs2.verify()
    spawn.run()
    assert "Connected" in card.aws_account_status.value
    active = working().current()
    assert active.external_id == original_external_id
    assert active.account_id == "774888247882"
    # the abandoned pending replacement is still just sitting there, inert
    assert working().store.load_pending() is not None


def test_change_account_while_still_on_the_old_aws_console_session(tmp_path, card):
    """Reproduces the live-acceptance report: the user clicks Change AWS
    account but their browser is still signed into the SAME AWS account, so
    the "new" role ends up belonging to the SAME account. This must promote
    cleanly (a fresh, valid ExternalId for an account that verified) rather
    than strand the user -- CryoStack cannot see the CloudFormation
    AlreadyExistsException itself, only the AssumeRole outcome."""
    spawn = _DeferredSpawn()
    factory = _factory(tmp_path, runner=FakeAWS("774888247882"))
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=factory,
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_B
    cbs.verify()
    spawn.run()
    original_external_id = factory().current().external_id

    # still signed into account B -- Change AWS account, then paste B's role
    # again (the ONLY role that exists there)
    same_account = _factory(tmp_path, runner=FakeAWS("774888247882"))
    cbs2 = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=same_account,
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs2.change_account()
    card.change_role_arn_input.value = ROLE_B
    cbs2.change_verify()
    spawn.run()

    # promotes cleanly: still connected to B, just under a NEW ExternalId
    active = same_account().current()
    assert active.status == "connected" and active.account_id == "774888247882"
    assert active.external_id != original_external_id
    assert same_account().store.load_pending() is None
    assert "Connected" in card.aws_account_status.value


def test_change_account_pending_replacement_survives_a_page_refresh(tmp_path):
    """A refresh mid-switch must be recoverable: the pending replacement is
    read back (never silently discarded, never silently promoted), while the
    active connection renders exactly as it did before the refresh."""
    card = build_cloud_environment_card()
    spawn = _DeferredSpawn()
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=_factory(tmp_path, runner=FakeAWS(deny=True)),
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_B
    cbs.verify()
    spawn.run()
    assert "Not verified" in card.aws_account_status.value

    cbs.change_account()
    card.change_role_arn_input.value = ROLE_A     # typed, not yet verified

    # "page reload": a fresh card + fresh callbacks over the SAME workspace
    fresh = build_cloud_environment_card()
    cbs2 = build_aws_connect_callbacks(
        widgets=fresh, onboarding_factory=_factory(tmp_path, runner=FakeAWS(deny=True)),
        log_output=_Out(),
    )
    cbs2.refresh()

    # active connection: same stranded state as before the refresh
    assert "Not verified" in fresh.aws_account_status.value
    assert fresh.recovery_actions.layout.display == "flex"
    # pending replacement: recovered, not discarded, not silently promoted
    assert fresh.change_account_panel.layout.display == "flex"
    assert "Open AWS Setup" in fresh.change_setup_link.value


def test_recovery_after_page_refresh_shows_error_not_disconnected(tmp_path):
    """A "page reload": a fresh card + fresh callbacks over the SAME on-disk
    connection must render the stranded state (and its recovery actions),
    never silently fall back to "disconnected"."""
    card = build_cloud_environment_card()
    spawn = _DeferredSpawn()
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=_factory(tmp_path, runner=FakeAWS(deny=True)),
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_B
    cbs.verify()
    spawn.run()
    assert "Not verified" in card.aws_account_status.value

    fresh = build_cloud_environment_card()
    cbs2 = build_aws_connect_callbacks(
        widgets=fresh, onboarding_factory=_factory(tmp_path, runner=FakeAWS(deny=True)),
        log_output=_Out(),
    )
    cbs2.refresh()
    assert "Not verified" in fresh.aws_account_status.value
    assert fresh.recovery_actions.layout.display == "flex"
    # the setup link is rebuilt too -- not stuck on the built-in placeholder
    assert "Open AWS Setup" in fresh.open_setup_link.value


def test_recovery_actions_never_render_a_secret(tmp_path, card):
    """No STS credential material anywhere in the recovered-state UI."""
    spawn = _DeferredSpawn()
    cbs = build_aws_connect_callbacks(
        widgets=card, onboarding_factory=_factory(tmp_path, runner=FakeAWS(deny=True)),
        log_output=_Out(), spawn=spawn, to_thread=lambda fn: _immediate(fn),
    )
    cbs.connect()
    card.role_arn_input.value = ROLE_B
    cbs.verify()
    spawn.run()
    cbs.retry()
    cbs.change_account()
    card.change_role_arn_input.value = ROLE_A
    cbs.change_verify()
    spawn.run()

    texts = [
        card.aws_account_status.value, card.aws_account_detail.value,
        card.open_setup_link.value, card.role_arn_input.value,
        card.change_account_status.value, card.change_setup_link.value,
        card.change_role_arn_input.value,
    ]
    blob = " ".join(texts).lower()
    assert "secretaccesskey" not in blob
    assert "sessiontoken" not in blob
    assert "asia_" not in blob and "akia" not in blob


def _immediate(fn):
    """Stand-in for asyncio.to_thread that runs the worker inline and returns
    an already-awaitable result."""

    async def _coro():
        return fn()

    return _coro()
