"""Regression: once an AWS account has a configured MATLAB license secret
ARN, that ARN must survive every later touchpoint -- a fresh UI render,
Re-check, Cloud Review rebuilding its execution context, and subsequent
ISSM preflight -- never just the instant after Configure.

This is the invariant the "already configured" panel message promises
("CryoStack will keep using it automatically") and the invariant Cloud
Review's own "ISSM runtime -- Needs a MATLAB license" verdict must respect
once it is genuinely true. Each stage here reloads the connection through
the SAME real, on-disk store Configure itself writes to -- no widget, no
cached reference, no shortcut -- so a regression that starts reading a
stale/blank connection anywhere in this chain fails one of these tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.connect.onboarding import AWSOnboarding
from cryostack_src.cloud.connect.store import AWSConnectionStore
from cryostack_src.workspace.identity import WorkspaceUser

_ACCOUNT = "774888247882"
_ROLE = f"arn:aws:iam::{_ACCOUNT}:role/CryoStackExecutionRole"
_ARN = f"arn:aws:secretsmanager:us-east-2:{_ACCOUNT}:secret:cryostack/issm-matlab-license-AbCdEf"


class _NullLog:
    """A no-op ``with log_output:`` stand-in -- these tests don't assert on
    Run Log content, only on persisted/resolved MATLAB-license state."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeAWS:
    """The same minimal STS stub used by cryostack_src/cloud/tests/
    test_cloud_connect_onboarding.py -- answers assume-role and
    get-caller-identity only; anything else is a test bug."""

    def __init__(self, account=_ACCOUNT):
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


def _configured_connection(tmp_path, user_id="lifecycle-user"):
    """A connected AWS account with the MATLAB license already configured
    -- the state Configure license leaves behind, built directly through
    the real store (not through the UI click handler; that path is
    covered separately in test_matlab_license_arn_ui.py)."""
    user = WorkspaceUser(user_id=user_id, source="env-override")
    store = AWSConnectionStore(user=user, workspace_root=tmp_path)
    connection = (
        store.create(region="us-east-2")
        .with_role(_ROLE)
        .mark_connected(account_id=_ACCOUNT)
        .with_matlab_license_secret(_ARN)
    )
    store.save(connection)
    return user, store


# ── configure -> a brand new UI render (e.g. a fresh Voila kernel) ──────
def test_configure_then_rerender_shows_the_configured_state(tmp_path, monkeypatch):
    from cryostack_src.frontend.cryolauncher.cloud_environment import (
        build_cloud_environment_card,
        wire_matlab_license_widgets,
    )

    user, store = _configured_connection(tmp_path)
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user.user_id)
    monkeypatch.setenv("USER", f"{user.user_id}-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))

    # a COMPLETELY FRESH widget build -- never reusing any widget instance
    # or closure from whatever originally called Configure.
    card = build_cloud_environment_card()
    wire_matlab_license_widgets(card, owner=user, log_output=_NullLog())

    assert card.matlab_license_arn.value == _ARN
    assert card.matlab_license_entry_box.layout.display == "none"
    assert card.matlab_license_configured_row.layout.display == "flex"
    # merely rendering never writes anything back
    assert store.load().matlab_license_secret_arn == _ARN


# ── configure -> Re-check ────────────────────────────────────────────────
def test_configure_then_recheck_preserves_the_license_arn(tmp_path):
    user, store = _configured_connection(tmp_path)

    ob = AWSOnboarding(
        user=user, workspace_root=tmp_path,
        template_url="https://cryostack-public.example/cf/execution-role.json",
        principal_arn="arn:aws:iam::713938953301:role/cryostack-service",
        region="us-east-2", runner=_FakeAWS(),
    )
    result = ob.recheck()

    assert result.ok
    assert result.connection.matlab_license_secret_arn == _ARN
    reloaded = store.load()
    assert reloaded.matlab_license_secret_arn == _ARN
    assert reloaded.status == "connected"


# ── configure -> Cloud Review rebuilding its execution context ─────────
def test_configure_then_review_rebuild_reports_configured(tmp_path):
    from cryostack_src.cloud.connect.execution import resolve_cloud_execution

    user, _store = _configured_connection(tmp_path)

    # Cloud Review's own resolution path -- a FRESH call, exactly as a
    # rebuild would make it, never reusing any earlier CloudExecution.
    execution = resolve_cloud_execution(
        user=user, workspace_root=tmp_path, runner=_FakeAWS())

    assert execution.is_byo
    lic = execution.matlab_license
    assert lic.configured is True
    assert lic.secret_arn == _ARN


def test_configure_then_repeated_review_rebuilds_stay_consistent(tmp_path):
    """Cloud Review can rebuild its execution context many times (mode
    changes, navigating tabs, re-opening the Review step) -- every one of
    them must see the same configured state, not just the first."""
    from cryostack_src.cloud.connect.execution import resolve_cloud_execution

    user, _store = _configured_connection(tmp_path)

    for _ in range(3):
        execution = resolve_cloud_execution(
            user=user, workspace_root=tmp_path, runner=_FakeAWS())
        assert execution.matlab_license.configured is True
        assert execution.matlab_license.secret_arn == _ARN


# ── subsequent ISSM preflight: must stay Ready, never re-blocked ───────
def test_configure_then_issm_preflight_stays_ready(tmp_path):
    from cryostack_src.cloud.connect.execution import resolve_cloud_execution
    from cryostack_src.cloud.preflight import assert_cloud_run_allowed

    user, _store = _configured_connection(tmp_path)
    execution = resolve_cloud_execution(
        user=user, workspace_root=tmp_path, runner=_FakeAWS())

    # must not raise -- this is the exact check Cloud Review's "Needs a
    # MATLAB license" verdict is downstream of.
    assert_cloud_run_allowed(
        model="issm",
        matlab_license_configured=execution.matlab_license.configured,
    )


def test_unconfigured_connection_still_correctly_blocks_issm_preflight(tmp_path):
    """The other half of the invariant: preflight must not be weakened
    globally -- an account that genuinely has no MATLAB license configured
    must still be refused, so this fix never masks a real missing-license
    case."""
    from cryostack_src.cloud.connect.execution import resolve_cloud_execution
    from cryostack_src.cloud.preflight import assert_cloud_run_allowed
    from cryostack_src.cloud.runtime import CloudRuntimeError

    user = WorkspaceUser(user_id="unconfigured-user", source="env-override")
    store = AWSConnectionStore(user=user, workspace_root=tmp_path)
    connection = store.create(region="us-east-2").with_role(_ROLE).mark_connected(
        account_id=_ACCOUNT)
    store.save(connection)

    execution = resolve_cloud_execution(
        user=user, workspace_root=tmp_path, runner=_FakeAWS())
    assert execution.matlab_license.configured is False

    import pytest
    with pytest.raises(CloudRuntimeError):
        assert_cloud_run_allowed(
            model="issm",
            matlab_license_configured=execution.matlab_license.configured,
        )


# ── AWS Disconnect must never touch the MATLAB license secret ─────────
def test_disconnect_never_calls_any_secrets_manager_api(tmp_path, monkeypatch):
    """Disconnect discards CryoStack's local connection record (forgetting
    the ARN along with everything else about the connection) but must
    NEVER itself call AWS to create or describe a secret -- the AWS-side
    secret is left completely untouched, and Disconnect never interferes
    with the existing-secret recovery mechanism."""
    import cryostack_src.cloud.drivers.aws.secrets as secrets_mod
    from cryostack_src.cloud.connect.onboarding import AWSOnboarding

    user, store = _configured_connection(tmp_path)

    calls: list[str] = []
    for fn_name in ("create_matlab_license_secret", "describe_matlab_license_secret"):
        def _tracker(*a, _name=fn_name, **kw):
            calls.append(_name)
            raise AssertionError(f"{_name} must never be called by Disconnect")
        monkeypatch.setattr(secrets_mod, fn_name, _tracker)

    ob = AWSOnboarding(
        user=user, workspace_root=tmp_path,
        template_url="https://cryostack-public.example/cf/execution-role.json",
        principal_arn="arn:aws:iam::713938953301:role/cryostack-service",
        region="us-east-2", runner=_FakeAWS(),
    )
    ob.disconnect()

    assert calls == []
    # the WHOLE connection record is gone -- including the ARN, as part
    # of forgetting the account entirely -- never a partial/managed
    # deletion of just the license
    assert store.load() is None
