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


def _immediate(fn):
    """Stand-in for asyncio.to_thread that runs the worker inline and returns
    an already-awaitable result."""

    async def _coro():
        return fn()

    return _coro()
