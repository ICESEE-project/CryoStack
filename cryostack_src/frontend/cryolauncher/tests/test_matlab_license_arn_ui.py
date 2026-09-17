"""ISSM cloud MATLAB license UX.

Basic mode shows ONLY a masked license-value field and a "Configure
license" button -- no ARN, no secret name, no MLM_LICENSE_FILE, no IAM
terminology. CryoStack creates/reuses a fixed, CryoStack-managed Secrets
Manager secret internally (DEFAULT_MATLAB_LICENSE_SECRET_NAME) and stores
only the resulting (non-secret) ARN.

Advanced mode keeps the simple Configure license path primary and exposes
a visually secondary "Advanced license configuration" accordion where a
power user can paste the ARN of a secret they manage themselves -- the
ONLY place ARN / secret terminology is shown by default.

Backend (cryostack_src/cloud/matlab_license.py, AWSConnection.
matlab_license_secret_arn / with_matlab_license_secret,
cryostack_src/cloud/drivers/aws/secrets.py) is unchanged by this UX
redesign and is unit-tested elsewhere (cryostack_src/cloud/tests/
test_cloud_matlab_license.py, test_aws_secrets_manager.py).
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import ipywidgets as W
import pytest

from cryostack_src.cloud.connect.execution import CloudAccessError, CloudExecution
from cryostack_src.cloud.connect.models import AWSConnection
from cryostack_src.cloud.connect.store import AWSConnectionStore
from cryostack_src.frontend.cryolauncher.cloud_environment import (
    DEFAULT_MATLAB_LICENSE_SECRET_NAME,
    build_cloud_environment_card,
    wire_matlab_license_widgets,
)
from cryostack_src.workspace.identity import WorkspaceUser

_BYO_EXECUTION = CloudExecution(
    mode="byo", region="us-east-2",
    credentials={"AWS_ACCESS_KEY_ID": "ASIA_X", "AWS_SECRET_ACCESS_KEY": "s",
                "AWS_SESSION_TOKEN": "t"},
    account_id="774888247882",
)
_CREATED_ARN = ("arn:aws:secretsmanager:us-east-2:774888247882:secret:"
               "cryostack/issm-matlab-license-AbCdEf")


class _Log:
    """Minimal Output-widget stand-in: `with log_output: print(...)` is
    captured into `.blob()` via real stdout redirection."""

    def __init__(self):
        self._buf = io.StringIO()
        self._redir = None

    def __enter__(self):
        self._redir = redirect_stdout(self._buf)
        self._redir.__enter__()
        return self

    def __exit__(self, *a):
        self._redir.__exit__(*a)
        self._redir = None
        return False

    def clear_output(self):
        self._buf = io.StringIO()

    def blob(self) -> str:
        return self._buf.getvalue()


def _guided_setup(tmp_path, monkeypatch, *, user_id="guided-setup-user"):
    """A wired MATLAB-license card, standalone (no full gateway build): a
    real, connected AWSConnection in a tmp_path store, and
    wire_matlab_license_widgets called directly.

    wire_matlab_license_widgets's own _store()/_save() build
    AWSConnectionStore(user=owner) WITHOUT a workspace_root (same as the
    real gateway) -- it resolves the root live from
    CRYOSTACK_WORKSPACE_ROOT, so that env var (and the matching
    CRYOSTACK_WORKSPACE_USER/USER) must be set for the handler invocation
    below, not just for building the store used to seed the connection.
    """
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user_id)
    monkeypatch.setenv("USER", f"{user_id}-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))

    user = WorkspaceUser(user_id=user_id, source="env-override")
    store = AWSConnectionStore(user=user, workspace_root=tmp_path)
    connection = store.create(region="us-east-2").with_role(
        "arn:aws:iam::774888247882:role/CryoStackExecutionRole"
    ).mark_connected(account_id="774888247882")
    store.save(connection)

    card = build_cloud_environment_card()
    log = _Log()
    wire_matlab_license_widgets(card, owner=user, log_output=log)
    return card, log, user, store


def _click_create(card) -> None:
    handler = card.matlab_license_create_button._click_handlers.callbacks[0]
    handler(None)


def _click_reconfigure(card) -> None:
    handler = card.matlab_license_reconfigure_button._click_handlers.callbacks[0]
    handler(None)


def _patch_execution(monkeypatch, execution=_BYO_EXECUTION):
    monkeypatch.setattr(
        "cryostack_src.cloud.connect.resolve_cloud_execution",
        lambda **kw: execution,
    )


def _patch_create_secret(monkeypatch, *, result=None, error=None):
    calls: list[dict] = []

    def fake(config, *, name, value):
        calls.append({"config": config, "name": name, "value": value})
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(
        "cryostack_src.cloud.drivers.aws.secrets.create_matlab_license_secret",
        fake,
    )
    return calls


def _patch_describe_secret(monkeypatch, *, result=None, error=None):
    """Stub for the metadata-only DescribeSecret lookup
    (cryostack_src.cloud.drivers.aws.secrets.describe_matlab_license_secret)
    -- fired on a SecretAlreadyExists collision during Configure, and on
    Re-check for an already-configured, CryoStack-managed ARN. Never
    touches real AWS, matching _patch_create_secret's own pattern."""
    calls: list[dict] = []

    def fake(config, *, name):
        calls.append({"config": config, "name": name})
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(
        "cryostack_src.cloud.drivers.aws.secrets.describe_matlab_license_secret",
        fake,
    )
    return calls


def _patch_iam_not_prepared(monkeypatch):
    """discover_iam_resources reports no ECS execution role yet -- the
    common "never ran Prepare Cloud" case; _reconcile_license_access must
    be a no-op (never call ensure_iam_resources)."""
    from cryostack_src.cloud.drivers.aws.iam import AWSIAMResources

    monkeypatch.setattr(
        "cryostack_src.cloud.drivers.aws.iam.discover_iam_resources",
        lambda config: AWSIAMResources(
            batch_service_role=None, ecs_execution_role=None, job_role=None),
    )
    calls = []
    monkeypatch.setattr(
        "cryostack_src.cloud.drivers.aws.iam_provision.ensure_iam_resources",
        lambda *a, **kw: calls.append(kw) or None,
    )
    return calls


def _patch_iam_already_prepared(monkeypatch):
    """discover_iam_resources reports an existing ECS execution role -- the
    environment was already prepared once; _reconcile_license_access must
    call ensure_iam_resources (IAM only)."""
    from cryostack_src.cloud.drivers.aws.iam import AWSIAMResources

    monkeypatch.setattr(
        "cryostack_src.cloud.drivers.aws.iam.discover_iam_resources",
        lambda config: AWSIAMResources(
            batch_service_role="arn:aws:iam::774888247882:role/x",
            ecs_execution_role="arn:aws:iam::774888247882:role/y",
            job_role="arn:aws:iam::774888247882:role/z",
        ),
    )
    calls = []

    def _fake_ensure(config, *, bucket, matlab_secret_arn="", include_ec2=False):
        calls.append({"bucket": bucket, "matlab_secret_arn": matlab_secret_arn})

    monkeypatch.setattr(
        "cryostack_src.cloud.drivers.aws.iam_provision.ensure_iam_resources",
        _fake_ensure,
    )
    return calls


# ── Basic mode: only the license value is shown ─────────────────────────
def test_basic_shows_masked_matlab_license_input():
    card = build_cloud_environment_card()
    assert isinstance(card.matlab_license_value, W.Password)
    assert card.matlab_license_value in card.matlab_license_entry_box.children
    assert card.matlab_license_value.description == "MATLAB license:"


def test_basic_does_not_show_arn_field_by_default():
    card = build_cloud_environment_card()
    # the ARN field exists only inside the collapsed Advanced accordion --
    # never in the always-visible entry form.
    assert card.matlab_license_arn not in card.matlab_license_entry_box.children
    assert card.matlab_license_arn not in card.matlab_license_box.children
    assert card.matlab_license_arn in card.matlab_license_advanced.children[0].children


def test_basic_does_not_show_a_secret_name_field():
    card = build_cloud_environment_card()

    def walk(w):
        if isinstance(w, W.Text) and "name" in (w.description or "").lower():
            return True
        return any(walk(c) for c in getattr(w, "children", ()))

    assert not walk(card.matlab_license_box)


def test_basic_does_not_expose_mlm_license_file_terminology():
    card = build_cloud_environment_card()

    def collect_text(w, out):
        if isinstance(w, W.HTML):
            out.append(w.value)
        for c in getattr(w, "children", ()):
            collect_text(c, out)

    out: list[str] = []
    collect_text(card.matlab_license_entry_box, out)
    blob = "\n".join(out)
    assert "MLM_LICENSE_FILE" not in blob
    assert "SecretString" not in blob
    assert "IAM" not in blob
    assert "Secrets Manager" not in blob


def test_basic_matlab_license_ui_has_no_tunnel_terminology():
    """The private-service Connector tunnel (relay/connector/port/VPN/
    FlexNet/session/token) must never surface anywhere in the MATLAB
    license box -- Basic or Advanced -- per the explicit requirement that
    CryoStack selects direct vs. institutional-Connector routing silently.
    Only the pre-existing "Advanced license configuration" (existing
    secret ARN) terminology is exempt, since that predates this feature."""
    card = build_cloud_environment_card()

    def collect_text(w, out):
        if isinstance(w, W.HTML):
            out.append(w.value)
        for c in getattr(w, "children", ()):
            collect_text(c, out)

    out: list[str] = []
    collect_text(card.matlab_license_box, out)
    blob = "\n".join(out)
    for banned in ("tunnel", "Connector", "relay", "VPN", "FlexNet", "flexlm",
                   "vendor daemon", "port ", "session", "token", "websocket",
                   "matlablic", "10.138.23.10", "1711"):
        assert banned.lower() not in blob.lower(), f"{banned!r} leaked into Basic/Advanced UI: {blob!r}"


def test_basic_caption_matches_the_scientist_facing_text():
    card = build_cloud_environment_card()
    text = card.matlab_license_entry_box.children[0].value
    assert "MATLAB license" in text
    assert "your institution" in text
    assert "normally required only once" in text
    assert "reachable from the cloud environment" in text
    assert "Georgia Tech" not in text


def test_configure_license_button_label():
    card = build_cloud_environment_card()
    assert card.matlab_license_create_button.description == "Configure license"


# ── In-progress state (items 1-6) ───────────────────────────────────────
def _capture_mid_flight_state(card: dict) -> dict:
    return {
        "disabled": card.matlab_license_create_button.disabled,
        "description": card.matlab_license_create_button.description,
        "status": card.matlab_license_create_status.value,
    }


def test_button_disabled_description_and_progress_status_while_configuring(
        tmp_path, monkeypatch):
    """Items 1, 2, 3: immediately after Configure license is clicked -- and
    for the duration of the (synchronous, blocking) CreateSecret call --
    the button is disabled, its label says "Configuring...", and a concise
    progress status is shown."""
    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_iam_not_prepared(monkeypatch)

    seen = {}

    def fake(config, *, name, value):
        seen.update(_capture_mid_flight_state(card))
        return {"arn": _CREATED_ARN, "name": DEFAULT_MATLAB_LICENSE_SECRET_NAME}

    monkeypatch.setattr(
        "cryostack_src.cloud.drivers.aws.secrets.create_matlab_license_secret", fake)

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    assert seen["disabled"] is True
    assert seen["description"] == "Configuring license..."
    assert "Configuring the MATLAB license securely in your AWS account" in seen["status"]
    # the license value is still not exposed in the progress status
    assert "27000@do-not-leak-me.invalid" not in seen["status"]


def test_duplicate_clicks_cannot_trigger_multiple_createsecret_calls(
        tmp_path, monkeypatch):
    """Item 4: a click that arrives while a Configure-license call is
    already in flight must be ignored, not queued or re-executed."""
    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_iam_not_prepared(monkeypatch)

    calls: list[dict] = []

    def fake(config, *, name, value):
        calls.append({"name": name, "value": value})
        if len(calls) == 1:
            _click_create(card)    # a duplicate click while this one is in flight
        return {"arn": _CREATED_ARN, "name": DEFAULT_MATLAB_LICENSE_SECRET_NAME}

    monkeypatch.setattr(
        "cryostack_src.cloud.drivers.aws.secrets.create_matlab_license_secret", fake)

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    assert len(calls) == 1


def test_success_restores_usable_button_state(tmp_path, monkeypatch):
    """Item 5."""
    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_iam_not_prepared(monkeypatch)
    _patch_create_secret(
        monkeypatch, result={"arn": _CREATED_ARN, "name": DEFAULT_MATLAB_LICENSE_SECRET_NAME})

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    assert card.matlab_license_create_button.disabled is False
    assert card.matlab_license_create_button.description == "Configure license"


def test_failure_restores_usable_button_state(tmp_path, monkeypatch):
    """Item 6."""
    from cryostack_src.cloud.drivers.aws.secrets import SecretCreateError

    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_create_secret(
        monkeypatch,
        error=SecretCreateError(
            "An error occurred (AccessDeniedException) when calling the "
            "CreateSecret operation: not authorized"))

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    assert card.matlab_license_create_button.disabled is False
    assert card.matlab_license_create_button.description == "Configure license"


def test_missing_value_never_enters_the_in_progress_state(tmp_path, monkeypatch):
    """The empty-value guard fires before the in-progress state is entered
    -- no AWS call, and the button is never disabled/relabeled for it."""
    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    calls = _patch_create_secret(monkeypatch, result={"arn": _CREATED_ARN, "name": "x"})

    card.matlab_license_value.value = ""
    _click_create(card)

    assert calls == []
    assert card.matlab_license_create_button.disabled is False
    assert card.matlab_license_create_button.description == "Configure license"


# ── Basic Configure license: creates/configures the secret ─────────────
def test_configure_license_creates_the_secret_under_the_fixed_default_name(
        tmp_path, monkeypatch):
    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_iam_not_prepared(monkeypatch)
    calls = _patch_create_secret(
        monkeypatch, result={"arn": _CREATED_ARN, "name": DEFAULT_MATLAB_LICENSE_SECRET_NAME})

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    assert len(calls) == 1
    assert calls[0]["config"].region == "us-east-2"
    assert calls[0]["name"] == DEFAULT_MATLAB_LICENSE_SECRET_NAME
    assert calls[0]["value"] == "27000@do-not-leak-me.invalid"


def test_configure_license_persists_the_returned_arn(tmp_path, monkeypatch):
    card, _log, user, store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_iam_not_prepared(monkeypatch)
    _patch_create_secret(
        monkeypatch, result={"arn": _CREATED_ARN, "name": DEFAULT_MATLAB_LICENSE_SECRET_NAME})

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    assert card.matlab_license_arn.value == _CREATED_ARN
    reloaded = store.load()
    assert reloaded.matlab_license_secret_arn == _CREATED_ARN


def test_raw_value_cleared_after_configure(tmp_path, monkeypatch):
    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_iam_not_prepared(monkeypatch)
    _patch_create_secret(
        monkeypatch, result={"arn": _CREATED_ARN, "name": DEFAULT_MATLAB_LICENSE_SECRET_NAME})

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    assert card.matlab_license_value.value == ""


def test_configured_state_shown_without_ever_retrieving_the_secret_value(
        tmp_path, monkeypatch):
    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_iam_not_prepared(monkeypatch)
    _patch_create_secret(
        monkeypatch, result={"arn": _CREATED_ARN, "name": DEFAULT_MATLAB_LICENSE_SECRET_NAME})

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    assert card.matlab_license_entry_box.layout.display == "none"
    assert card.matlab_license_configured_row.layout.display == "flex"
    configured_status = card.matlab_license_configured_row.children[0]
    assert "MATLAB license configured" in configured_status.value
    # never a GetSecretValue / DescribeSecret call anywhere in this module
    import cryostack_src.frontend.cryolauncher.cloud_environment as mod
    assert not hasattr(mod, "get_matlab_license_secret_value")


def test_success_status_message_is_non_sensitive_and_jargon_free(tmp_path, monkeypatch):
    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_iam_not_prepared(monkeypatch)
    _patch_create_secret(
        monkeypatch, result={"arn": _CREATED_ARN, "name": DEFAULT_MATLAB_LICENSE_SECRET_NAME})

    raw = "27000@do-not-leak-me.invalid"
    card.matlab_license_value.value = raw
    _click_create(card)

    status = card.matlab_license_create_status.value
    assert "MATLAB license configured" in status
    assert raw not in status
    assert _CREATED_ARN not in status
    assert "ARN" not in status
    assert "IAM" not in status


# ── Prepare Cloud reconciliation ────────────────────────────────────────
def test_configure_license_reconciles_iam_when_environment_already_prepared(
        tmp_path, monkeypatch):
    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    calls = _patch_iam_already_prepared(monkeypatch)
    _patch_create_secret(
        monkeypatch, result={"arn": _CREATED_ARN, "name": DEFAULT_MATLAB_LICENSE_SECRET_NAME})

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    assert len(calls) == 1
    assert calls[0]["matlab_secret_arn"] == _CREATED_ARN
    status = card.matlab_license_create_status.value
    assert "MATLAB license configured" in status
    assert "Prepare cloud" not in status   # already reconciled -- no nudge needed


def test_configure_license_does_not_reconcile_iam_when_never_prepared(
        tmp_path, monkeypatch):
    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    calls = _patch_iam_not_prepared(monkeypatch)
    _patch_create_secret(
        monkeypatch, result={"arn": _CREATED_ARN, "name": DEFAULT_MATLAB_LICENSE_SECRET_NAME})

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    assert calls == []      # ensure_iam_resources never called -- no roles created
    status = card.matlab_license_create_status.value
    assert "MATLAB license configured" in status
    assert "Prepare cloud" in status
    assert "ECS" not in status and "execution role" not in status


def test_reconciliation_failure_does_not_break_the_success_message(
        tmp_path, monkeypatch):
    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_create_secret(
        monkeypatch, result={"arn": _CREATED_ARN, "name": DEFAULT_MATLAB_LICENSE_SECRET_NAME})

    def _boom(config):
        raise RuntimeError("network blip")

    monkeypatch.setattr(
        "cryostack_src.cloud.drivers.aws.iam.discover_iam_resources", _boom)

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)         # must not raise

    assert "MATLAB license configured" in card.matlab_license_create_status.value
    # the ARN was still persisted even though reconciliation failed
    assert card.matlab_license_arn.value == _CREATED_ARN


# ── Advanced mode: simple Configure license path stays primary ─────────
def test_advanced_still_shows_the_simple_configure_license_path(tmp_path, monkeypatch):
    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    # the entry form (with Configure license) is present regardless of
    # whether the Advanced accordion is opened or collapsed.
    assert card.matlab_license_create_button.description == "Configure license"
    assert card.matlab_license_value in card.matlab_license_entry_box.children


def test_advanced_existing_secret_option_exposes_arn_only_inside_it():
    card = build_cloud_environment_card()
    assert card.matlab_license_advanced.get_title(0) == "Advanced license configuration"
    body = card.matlab_license_advanced.children[0]
    assert card.matlab_license_arn in body.children
    assert card.matlab_license_save_button in body.children
    assert card.matlab_license_save_button.description == "Use existing secret"
    # collapsed by default -- a visually secondary option
    assert card.matlab_license_advanced.selected_index is None


def test_existing_arn_path_remains_functional(tmp_path):
    """The manual "paste an existing ARN" path (Advanced) still saves onto
    the connection through the same, unchanged mechanism."""
    import matplotlib
    matplotlib.use("Agg")

    user = WorkspaceUser(user_id="matlab-license-ui-user", source="env-override")
    store = AWSConnectionStore(user=user, workspace_root=tmp_path)
    connection = store.create(region="us-east-2").with_role(
        "arn:aws:iam::774888247882:role/CryoStackExecutionRole"
    ).mark_connected(account_id="774888247882")
    store.save(connection)

    import os
    os.environ["CRYOSTACK_WORKSPACE_USER"] = "matlab-license-ui-user"
    os.environ["USER"] = "matlab-license-ui-svc"
    os.environ["CRYOSTACK_WORKSPACE_ROOT"] = str(tmp_path)
    try:
        from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
        page = build_icesheets_ui()

        save_button = None

        def walk(w):
            nonlocal save_button
            if isinstance(w, W.Button) and getattr(w, "description", "") == "Use existing secret":
                save_button = w
            for c in getattr(w, "children", ()):
                walk(c)

        walk(page)
        assert save_button is not None, "Use existing secret button not found"
        assert save_button._click_handlers.callbacks

        handler = save_button._click_handlers.callbacks[0]

        def freevar(fn, name):
            idx = fn.__code__.co_freevars.index(name)
            return fn.__closure__[idx].cell_contents

        cloud_environment = freevar(handler, "widgets")
        arn = "arn:aws:secretsmanager:us-east-2:774888247882:secret:issm-license-abc123"
        cloud_environment.matlab_license_arn.value = arn
        handler(None)
    finally:
        del os.environ["CRYOSTACK_WORKSPACE_USER"]
        del os.environ["USER"]
        del os.environ["CRYOSTACK_WORKSPACE_ROOT"]

    reloaded = AWSConnectionStore(user=user, workspace_root=tmp_path).load()
    assert reloaded.matlab_license_secret_arn == arn
    assert reloaded.role_arn == connection.role_arn
    assert reloaded.account_id == "774888247882"


def test_existing_arn_path_rejects_a_pasted_license_value(tmp_path):
    import matplotlib
    matplotlib.use("Agg")

    user = WorkspaceUser(user_id="matlab-license-reject-user", source="env-override")
    store = AWSConnectionStore(user=user, workspace_root=tmp_path)
    connection = store.create(region="us-east-2").with_role(
        "arn:aws:iam::774888247882:role/CryoStackExecutionRole"
    ).mark_connected(account_id="774888247882")
    store.save(connection)

    import os
    os.environ["CRYOSTACK_WORKSPACE_USER"] = "matlab-license-reject-user"
    os.environ["USER"] = "matlab-license-reject-svc"
    os.environ["CRYOSTACK_WORKSPACE_ROOT"] = str(tmp_path)
    try:
        from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
        page = build_icesheets_ui()
    finally:
        del os.environ["CRYOSTACK_WORKSPACE_USER"]
        del os.environ["USER"]
        del os.environ["CRYOSTACK_WORKSPACE_ROOT"]

    save_button = None

    def walk(w):
        nonlocal save_button
        if isinstance(w, W.Button) and getattr(w, "description", "") == "Use existing secret":
            save_button = w
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    handler = save_button._click_handlers.callbacks[0]

    def freevar(fn, name):
        idx = fn.__code__.co_freevars.index(name)
        return fn.__closure__[idx].cell_contents

    cloud_environment = freevar(handler, "widgets")
    cloud_environment.matlab_license_arn.value = "27000@my-license-server"
    handler(None)   # must not raise -- the error is printed, not thrown

    reloaded = AWSConnectionStore(user=user, workspace_root=tmp_path).load()
    assert reloaded.matlab_license_secret_arn == ""    # rejected, never saved


# ── Non-ISSM workflows: entire section hidden ───────────────────────────
def test_non_issm_workflow_hides_the_entire_matlab_license_section():
    card = build_cloud_environment_card()
    # default (unwired) state is hidden -- the gateway sets it explicitly
    # from cryostack_src.models.workflow_capabilities.requires_matlab_license
    assert card.matlab_license_box.layout.display == "none"


# ── Reconfigure ───────────────────────────────────────────────────────
def test_reconfigure_is_not_offered_for_cryostacks_own_managed_secret(
        tmp_path, monkeypatch):
    """CryoStack cannot yet replace the value of the fixed-name secret it
    creates (no PutSecretValue path) -- Reconfigure must not be offered as
    if it could. The status stays truthful (checkmark + a note pointing at
    the one real fallback) instead of an active form that would always
    collide on resubmission."""
    card, _log, _user, store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_iam_not_prepared(monkeypatch)
    _patch_create_secret(
        monkeypatch, result={"arn": _CREATED_ARN, "name": DEFAULT_MATLAB_LICENSE_SECRET_NAME})
    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)
    assert card.matlab_license_configured_row.layout.display == "flex"

    # the button is hidden, and a truthful note takes its place
    assert card.matlab_license_reconfigure_button.layout.display == "none"
    assert card.matlab_license_rotate_note.layout.display == "flex"
    assert "AWS Secrets Manager" in card.matlab_license_rotate_note.value

    # a stray/programmatic click is a safe no-op -- it never reveals a form
    # that would always fail on resubmission
    _click_reconfigure(card)

    assert card.matlab_license_entry_box.layout.display == "none"
    assert card.matlab_license_configured_row.layout.display == "flex"
    reloaded = store.load()
    assert reloaded.matlab_license_secret_arn == _CREATED_ARN  # unchanged


def test_reconfigure_works_for_an_advanced_configured_secret(tmp_path, monkeypatch):
    """An ARN set via Advanced -> "Use existing secret" does NOT name
    CryoStack's fixed-name managed secret, so Reconfigure genuinely can do
    something (Configure license would create a fresh managed secret) --
    it must stay offered and functional for that case."""
    card, _log, _user, store = _guided_setup(tmp_path, monkeypatch)
    other_arn = ("arn:aws:secretsmanager:us-east-2:774888247882:secret:"
                 "issm-license-abc123")
    card.matlab_license_arn.value = other_arn
    handler = card.matlab_license_save_button._click_handlers.callbacks[0]
    handler(None)
    assert card.matlab_license_configured_row.layout.display == "flex"
    assert card.matlab_license_reconfigure_button.layout.display == "inline-flex"
    assert card.matlab_license_rotate_note.layout.display == "none"

    _click_reconfigure(card)

    assert card.matlab_license_entry_box.layout.display == "flex"
    assert card.matlab_license_configured_row.layout.display == "none"
    assert card.matlab_license_value.value == ""          # never pre-filled
    reloaded = store.load()
    assert reloaded.matlab_license_secret_arn == other_arn  # unchanged so far


def test_is_default_managed_arn_helper():
    from cryostack_src.frontend.cryolauncher.cloud_environment import (
        _is_default_managed_matlab_license_arn,
    )

    assert _is_default_managed_matlab_license_arn(_CREATED_ARN) is True
    assert _is_default_managed_matlab_license_arn(
        "arn:aws:secretsmanager:us-east-2:774888247882:secret:"
        "issm-license-abc123") is False
    assert _is_default_managed_matlab_license_arn("") is False
    assert _is_default_managed_matlab_license_arn("not-an-arn") is False


# ── Existing-secret collision: never silently overwritten ──────────────
def test_configuring_again_when_the_default_secret_already_exists_does_not_overwrite(
        tmp_path, monkeypatch):
    """The new value the user typed is NEVER used to overwrite the
    existing secret -- regardless of whether the metadata-only
    DescribeSecret recovery (below) succeeds or not."""
    from cryostack_src.cloud.drivers.aws.secrets import SecretAlreadyExists

    card, _log, _user, store = _guided_setup(tmp_path, monkeypatch)
    old_arn = "arn:aws:secretsmanager:us-east-2:774888247882:secret:cryostack/issm-matlab-license-old"
    connection = store.load().with_matlab_license_secret(old_arn)
    store.save(connection)
    card.matlab_license_arn.value = old_arn

    _patch_execution(monkeypatch)
    _patch_iam_not_prepared(monkeypatch)
    _patch_create_secret(
        monkeypatch,
        error=SecretAlreadyExists(
            f"A secret named {DEFAULT_MATLAB_LICENSE_SECRET_NAME!r} already exists."))
    _patch_describe_secret(
        monkeypatch, result={"arn": old_arn, "name": DEFAULT_MATLAB_LICENSE_SECRET_NAME})

    _click_reconfigure(card)
    card.matlab_license_value.value = "a-new-value@license.example.edu"
    _click_create(card)         # must not raise

    status = card.matlab_license_create_status.value
    assert "already" in status.lower()
    assert "a-new-value" not in status
    # the previously configured ARN is left exactly as it was -- recovered
    # and reconfirmed, never replaced by the new value that was typed
    assert card.matlab_license_arn.value == old_arn
    reloaded = store.load()
    assert reloaded.matlab_license_secret_arn == old_arn


def test_collision_recovers_the_existing_arn_via_describe_secret(tmp_path, monkeypatch):
    """The completed behavior: when the entry form is reachable (no ARN
    known locally) and Configure collides with an existing secret,
    DescribeSecret recovers that secret's ARN and CryoStack persists it
    and switches to the configured view automatically -- the value typed
    is never reused for anything (create failed; the ARN comes only from
    the describe response)."""
    from cryostack_src.cloud.drivers.aws.secrets import SecretAlreadyExists

    card, _log, _user, store = _guided_setup(tmp_path, monkeypatch)
    existing_arn = ("arn:aws:secretsmanager:us-east-2:774888247882:secret:"
                    "cryostack/issm-matlab-license-AbCdEf")

    _patch_execution(monkeypatch)
    _patch_iam_already_prepared(monkeypatch)
    _patch_create_secret(
        monkeypatch,
        error=SecretAlreadyExists(
            f"A secret named {DEFAULT_MATLAB_LICENSE_SECRET_NAME!r} already exists."))
    describe_calls = _patch_describe_secret(
        monkeypatch, result={"arn": existing_arn, "name": DEFAULT_MATLAB_LICENSE_SECRET_NAME})

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    assert describe_calls == [
        {"config": describe_calls[0]["config"], "name": DEFAULT_MATLAB_LICENSE_SECRET_NAME}]
    status = card.matlab_license_create_status.value
    assert "already configured" in status.lower()
    assert "keep using it automatically" in status.lower()
    assert "27000@do-not-leak-me.invalid" not in status
    # persisted through the SAME path a fresh Configure uses -- the panel
    # switches to the configured view, not left showing the entry form
    assert card.matlab_license_arn.value == existing_arn
    assert card.matlab_license_entry_box.layout.display == "none"
    assert card.matlab_license_configured_row.layout.display == "flex"
    reloaded = store.load()
    assert reloaded.matlab_license_secret_arn == existing_arn


def test_collision_recovery_falls_back_safely_when_describe_secret_fails(
        tmp_path, monkeypatch):
    """A connection whose role predates the DescribeSecret IAM grant must
    never crash and must never silently claim to have recovered the ARN
    -- it stays unconfigured, with a SPECIFIC message naming the real
    cause (missing permissions), not just a generic "could not confirm"
    -- and the real AWS error detail reaches the Run Log rather than
    being discarded."""
    from cryostack_src.cloud.drivers.aws.secrets import (
        SecretAlreadyExists,
        SecretDescribeError,
    )

    card, log, _user, store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_create_secret(
        monkeypatch,
        error=SecretAlreadyExists(
            f"A secret named {DEFAULT_MATLAB_LICENSE_SECRET_NAME!r} already exists."))
    _patch_describe_secret(
        monkeypatch, error=SecretDescribeError("AccessDeniedException: not authorized"))

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)         # must not raise

    status = card.matlab_license_create_status.value
    assert "does not yet have the permissions" in status.lower()
    assert "Update role permissions" in status
    assert "AccessDeniedException" not in status
    # the real AWS-reported cause reaches the Run Log, not silence
    assert "DescribeSecret" in log.blob()
    assert "Access denied" in log.blob()


def test_collision_recovery_generic_describe_failure_gets_a_non_permission_message(
        tmp_path, monkeypatch):
    """A describe failure that is NOT AccessDenied (e.g. throttling) must
    get the generic-but-honest message -- never falsely blamed on
    permissions, and never the raw AWS text."""
    from cryostack_src.cloud.drivers.aws.secrets import (
        SecretAlreadyExists,
        SecretDescribeError,
    )

    card, log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_create_secret(
        monkeypatch,
        error=SecretAlreadyExists(
            f"A secret named {DEFAULT_MATLAB_LICENSE_SECRET_NAME!r} already exists."))
    _patch_describe_secret(
        monkeypatch,
        error=SecretDescribeError(
            "An error occurred (ThrottlingException) when calling the "
            "DescribeSecret operation: Rate exceeded"))

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    status = card.matlab_license_create_status.value
    assert "could not automatically confirm it" in status.lower()
    assert "does not yet have the permissions" not in status.lower()
    assert "ThrottlingException" not in status
    assert "AWS Secrets Manager DescribeSecret failed." in log.blob()


# ── security: the raw value never surfaces anywhere ─────────────────────
def test_raw_value_never_reaches_the_persisted_connection(tmp_path, monkeypatch):
    card, _log, user, store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_iam_not_prepared(monkeypatch)
    _patch_create_secret(
        monkeypatch, result={"arn": _CREATED_ARN, "name": "cryostack/x"})

    raw = "27000@do-not-leak-me.invalid"
    card.matlab_license_value.value = raw
    _click_create(card)

    persisted = store.path.read_text()
    assert raw not in persisted


def test_raw_value_never_reaches_the_run_log(tmp_path, monkeypatch):
    card, log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_iam_not_prepared(monkeypatch)
    _patch_create_secret(
        monkeypatch, result={"arn": _CREATED_ARN, "name": "cryostack/x"})

    raw = "27000@do-not-leak-me.invalid"
    card.matlab_license_value.value = raw
    _click_create(card)

    assert raw not in log.blob()


def test_raw_value_never_reaches_the_status_widget(tmp_path, monkeypatch):
    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_iam_not_prepared(monkeypatch)
    _patch_create_secret(
        monkeypatch, result={"arn": _CREATED_ARN, "name": "cryostack/x"})

    raw = "27000@do-not-leak-me.invalid"
    card.matlab_license_value.value = raw
    _click_create(card)

    assert raw not in card.matlab_license_create_status.value


def test_raw_value_never_appears_in_a_surfaced_error(tmp_path, monkeypatch):
    from cryostack_src.cloud.drivers.aws.secrets import SecretCreateError

    card, log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_create_secret(
        monkeypatch, error=SecretCreateError("AccessDeniedException: not authorized"))

    raw = "27000@do-not-leak-me.invalid"
    card.matlab_license_value.value = raw
    _click_create(card)

    assert raw not in card.matlab_license_create_status.value
    assert raw not in log.blob()


def test_failed_configure_leaves_the_previously_configured_arn_unchanged(
        tmp_path, monkeypatch):
    from cryostack_src.cloud.drivers.aws.secrets import SecretCreateError

    card, _log, user, store = _guided_setup(tmp_path, monkeypatch)
    old_arn = "arn:aws:secretsmanager:us-east-2:774888247882:secret:cryostack/old-abc123"
    connection = store.load().with_matlab_license_secret(old_arn)
    store.save(connection)
    card.matlab_license_arn.value = old_arn

    _patch_execution(monkeypatch)
    _patch_create_secret(monkeypatch, error=SecretCreateError("AccessDeniedException"))

    _click_reconfigure(card)
    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    assert card.matlab_license_arn.value == old_arn
    reloaded = store.load()
    assert reloaded.matlab_license_secret_arn == old_arn


def test_missing_value_is_rejected_before_any_aws_call(tmp_path, monkeypatch):
    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    calls = _patch_create_secret(monkeypatch, result={"arn": _CREATED_ARN, "name": "x"})

    card.matlab_license_value.value = ""
    _click_create(card)

    assert calls == []
    assert "Enter your MATLAB license" in card.matlab_license_create_status.value


#: the exact AccessDenied text observed in the live test -- carries the STS
#: assumed-role ARN and account id, exactly what must never reach Basic mode.
_LIVE_ACCESS_DENIED_TEXT = (
    "An error occurred (AccessDeniedException) when calling the CreateSecret "
    "operation: User: arn:aws:sts::774888247882:assumed-role/"
    "CryoStackExecutionRole/cryostack-session is not authorized to perform: "
    "secretsmanager:CreateSecret on resource: cryostack/issm-matlab-license "
    "because no identity-based policy allows the secretsmanager:CreateSecret "
    "action")


def test_access_denied_produces_the_scientist_facing_basic_message(tmp_path, monkeypatch):
    """Item 7: the observed CreateSecret AccessDenied case produces the
    specific, actionable Basic-mode message naming the real 'Update role
    permissions' action -- not a generic failure line."""
    from cryostack_src.cloud.drivers.aws.secrets import SecretCreateError

    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_create_secret(monkeypatch, error=SecretCreateError(_LIVE_ACCESS_DENIED_TEXT))

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    status = card.matlab_license_create_status.value
    assert "Could not configure the MATLAB license" in status
    assert "Your CryoStack AWS connection needs updated permissions" in status
    assert "Update role permissions" in status


def test_access_denied_hides_the_raw_aws_error_from_basic_status(tmp_path, monkeypatch):
    """Item 8: none of the raw CreateSecret AccessDenied text reaches the
    Basic-mode status widget."""
    from cryostack_src.cloud.drivers.aws.secrets import SecretCreateError

    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_create_secret(monkeypatch, error=SecretCreateError(_LIVE_ACCESS_DENIED_TEXT))

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    status = card.matlab_license_create_status.value
    assert "AccessDeniedException" not in status
    assert "CreateSecret operation" not in status
    assert "not authorized to perform" not in status
    assert "identity-based policy" not in status


def test_access_denied_hides_the_sts_role_arn_from_basic_status(tmp_path, monkeypatch):
    """Item 9: the STS assumed-role ARN and account id from the live
    AccessDenied text never reach the Basic-mode status widget."""
    from cryostack_src.cloud.drivers.aws.secrets import SecretCreateError

    card, _log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_create_secret(monkeypatch, error=SecretCreateError(_LIVE_ACCESS_DENIED_TEXT))

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    status = card.matlab_license_create_status.value
    assert "arn:aws:sts::" not in status
    assert "774888247882" not in status
    assert "assumed-role" not in status
    assert "CryoStackExecutionRole" not in status


def test_access_denied_log_detail_is_short_and_sanitized(tmp_path, monkeypatch):
    """Item 11: even the developer/debug Run Log channel gets at most a
    short, categorized technical reason -- never the raw multi-line AWS
    CLI exception, and never the STS role ARN."""
    from cryostack_src.cloud.drivers.aws.secrets import SecretCreateError

    card, log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_create_secret(monkeypatch, error=SecretCreateError(_LIVE_ACCESS_DENIED_TEXT))

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    blob = log.blob()
    assert "Access denied for AWS Secrets Manager CreateSecret." in blob
    assert "arn:aws:sts::" not in blob
    assert "774888247882" not in blob
    assert "identity-based policy" not in blob
    # short: the technical detail is one categorized sentence, not the
    # ~240-character raw AWS message
    assert len(blob) < len(_LIVE_ACCESS_DENIED_TEXT)


def test_generic_createsecret_failure_gets_a_sanitized_message(tmp_path, monkeypatch):
    """A CreateSecret failure that is NOT AccessDenied still gets a sane,
    non-raw, actionable Basic-mode message (not merely the AccessDenied
    case) and a short log line."""
    from cryostack_src.cloud.drivers.aws.secrets import SecretCreateError

    card, log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    _patch_execution(monkeypatch)
    _patch_create_secret(
        monkeypatch,
        error=SecretCreateError(
            "An error occurred (ThrottlingException) when calling the "
            "CreateSecret operation: Rate exceeded"))

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)

    status = card.matlab_license_create_status.value
    assert "Could not configure the MATLAB license" in status
    assert "ThrottlingException" not in status
    assert "Rate exceeded" not in status
    assert "AWS Secrets Manager CreateSecret failed." in log.blob()


def test_broken_connection_is_refused_without_creating_anything(tmp_path, monkeypatch):
    card, log, _user, _store = _guided_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "cryostack_src.cloud.connect.resolve_cloud_execution",
        lambda **kw: (_ for _ in ()).throw(
            CloudAccessError("Your AWS account connection is not verified.")),
    )
    calls = _patch_create_secret(monkeypatch, result={"arn": _CREATED_ARN, "name": "x"})

    card.matlab_license_value.value = "27000@do-not-leak-me.invalid"
    _click_create(card)          # must not raise

    assert calls == []
    assert card.matlab_license_value.value == ""     # cleared even on failure
    # the SAME sanitized connection/session-failure message every other
    # cloud operation uses (cloud_run_controller.classify_cloud_failure) --
    # a sensible message for "AWS connection/session failure"
    status = card.matlab_license_create_status.value
    assert "AWS connection could not be refreshed" in status
    assert "AWS ACCOUNT" in status
    # button restored to a usable state even on this early failure
    assert card.matlab_license_create_button.disabled is False
    assert card.matlab_license_create_button.description == "Configure license"
