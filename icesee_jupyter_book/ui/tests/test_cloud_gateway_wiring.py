"""Cloud Commit 4/5 -- the IceSheets gateway wires the real Cloud path and
leaves the Local / Remote paths untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import ipywidgets as W

_ICESHEETS = _REPO / "icesee_jupyter_book/ui/icesheets_gateway.py"


def test_cloud_placeholder_submission_is_gone():
    src = _ICESHEETS.read_text()
    assert "Placeholder for AWS Batch submission" not in src
    assert "adapt submit_cloud_example for model-only workflows" not in src


def test_cloud_branch_validates_and_preflights_before_submit():
    src = _ICESHEETS.read_text()
    assert "resolve_cloud_config(" in src
    assert "validate_cloud_config(" in src
    assert "cloud_run_preflight(" in src
    assert "_submit_cloud_run(" in src
    # the real bridge submit signature (staged tree + model + bucket)
    assert "staged_source=" in src and "matlab_license_configured=" in src


def test_cloud_run_is_registered_with_backend_aws_and_a_real_job_id():
    src = _ICESHEETS.read_text()
    assert 'backend="aws"' in src
    assert 'execution_mode="cloud"' in src
    # registration now happens in _register_cloud_run, called by the
    # CloudRunController only after it has a real job id + S3 run
    assert "_register_cloud_run" in src
    assert "CloudRunController(" in src

    from cryostack_src.frontend.cryolauncher.cloud_run_controller import (
        CloudRunController,
    )
    calls = []

    class _Bridge:
        def submit(self, **kw):
            class _R:
                job_id = None            # no job id -> must NOT register
                metadata = {}
                working_directory = None
                messages = []
            return _R()

    ctl = CloudRunController(
        bridge_factory=_Bridge,
        register_run=lambda **kw: calls.append(kw),
        sync_results=lambda **kw: "/x",
        on_state=lambda s: None,
        on_log=lambda m: None,
        poll_interval=0.0,
    )
    import asyncio
    asyncio.run(ctl.run_once(staged_source="/x", model="issm",
                             run_target="runme.m", bucket="b"))
    assert calls == []                     # no job id -> no registration
    assert ctl.state == "failed"


def test_cloud_state_chip_covers_the_documented_states():
    src = _ICESHEETS.read_text()
    for state in ("not_configured", "checking", "ready", "staging", "submitting",
                  "queued", "running", "completed", "failed", "cancelled"):
        assert f'"{state}"' in src


def test_local_and_remote_paths_are_unchanged():
    src = _ICESHEETS.read_text()
    # Remote: the B3 identity gate + real submitters still present
    assert "enforce_remote_access(" in src
    assert "submit_remote_icesheets" in src
    assert "verify_remote_identity(" in src
    # Local: the local runner path
    assert "run_example_local" in src or "local" in src.lower()
    # cloud staging reuses the SAME working-copy helper as Remote
    assert "stage_example_for_run(" in src


def test_no_developer_or_personal_cloud_defaults():
    src = _ICESHEETS.read_text()
    for bad in ("us-east-1", "arobel3", "bankyanjo", "1711@matlablic"):
        assert bad not in src, bad
    assert "DEFAULT_CLOUD_REGION" in src  # region comes from the shared constant


@pytest.mark.parametrize("builder", ["build_icesheets_ui"])
def test_gateway_still_builds_with_the_cloud_wiring(builder, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "cloud-wire-user")
    monkeypatch.setenv("USER", "cloud-wire-service")
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    page = build_icesheets_ui()
    html = []

    def walk(w):
        if isinstance(w, W.HTML):
            html.append(w.value)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    blob = "\n".join(html)
    assert "Cloud: Not configured" in blob


# -- C7 live-acceptance: a failed AWS connection is not "Not configured" ---
def test_recovery_actions_and_new_chip_states_are_wired():
    src = _ICESHEETS.read_text()
    assert "connection_issue" in src and "Connection issue" in src
    assert "connection_required" in src and "Connection required" in src
    assert "aws_connect.retry" in src
    assert "aws_connect.change_account" in src
    assert "retry_button.on_click(aws_connect.retry)" in src
    assert "change_account_button.on_click(aws_connect.change_account)" in src
    # Change AWS account is staged: the replacement's own verify/cancel are
    # wired too, distinct from the active connection's verify/disconnect.
    assert "change_verify_button.on_click(aws_connect.change_verify)" in src
    assert "change_cancel_button.on_click(aws_connect.change_cancel)" in src


def test_a_stranded_aws_connection_shows_connection_issue_not_not_configured(monkeypatch, tmp_path):
    """The exact live-acceptance bug: a previously-attempted-but-failed AWS
    connection must render as "Cloud: Connection issue", never silently
    fall back to the first-time "Cloud: Not configured" label."""
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "cloud-recovery-user")
    monkeypatch.setenv("USER", "cloud-wire-service")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("CRYOSTACK_AWS_PRINCIPAL_ARN", raising=False)
    monkeypatch.delenv("CRYOSTACK_CF_TEMPLATE_URL", raising=False)
    import matplotlib
    matplotlib.use("Agg")

    from cryostack_src.cloud.connect import AWSConnectionStore
    from cryostack_src.workspace.identity import WorkspaceUser

    user = WorkspaceUser(user_id="cloud-recovery-user", source="env-override")
    store = AWSConnectionStore(user=user, workspace_root=tmp_path)
    conn = store.create(region="us-east-2").with_role(
        "arn:aws:iam::713938953301:role/CryoStackExecutionRole"
    ).mark_error("AWS denied the role assumption.")
    store.save(conn)

    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    page = build_icesheets_ui()
    html = []

    def walk(w):
        if isinstance(w, W.HTML):
            html.append(w.value)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    blob = "\n".join(html)
    assert "Cloud: Connection issue" in blob
    assert "Cloud: Not configured" not in blob
    # the Role ARN this user already saved must still be on disk, untouched
    assert store.load().role_arn == "arn:aws:iam::713938953301:role/CryoStackExecutionRole"


# -- Icepack Cloud Execution checkpoint -----------------------------------
def test_canonical_cloud_config_derives_the_selected_model():
    """The functions that build the Review card / drift digest / launch gate
    no longer hardcode model="issm" -- they read model_dd.value. (The
    ISSM-only scientific_overrides conditional is intentional and untouched.)"""
    src = _ICESHEETS.read_text()
    assert 'model=(model_dd.value or "issm").strip().lower()' in src
    # the old hardcoded-issm-only comment on _resolve_cloud_execution is gone
    assert 'model="issm",           # cloud execution is ISSM-only for now' not in src


def test_cloud_run_history_and_execution_follow_the_selected_model():
    src = _ICESHEETS.read_text()
    assert '(run.model or "").lower() != _model' in src
    assert "region_hint=aws_region.value.strip() or DEFAULT_CLOUD_REGION" in src
    # the ISSM-only note is gone from _resolve_cloud_execution
    assert "cloud execution is ISSM-only for now" not in src


def test_gateway_builds_with_icepack_selectable_and_cloud_supported():
    """Icepack Cloud Execution checkpoint: the model dropdown includes
    Icepack, and the capabilities registry (which the gateway/agent both
    read) now agrees Icepack is cloud-capable."""
    from cryostack_src.models.capabilities import get_model_capabilities

    cap = get_model_capabilities("icepack")
    assert cap.cloud_supported is True
    assert "cloud" in cap.execution_modes
    assert cap.requires_matlab is False

    issm_cap = get_model_capabilities("issm")
    assert issm_cap.cloud_supported is True
    assert issm_cap.requires_matlab is True             # ISSM behaviour unchanged
