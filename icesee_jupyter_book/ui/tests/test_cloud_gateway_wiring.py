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
    # a run is only registered when there is a real job id + s3 run
    assert 'backend="aws"' in src
    assert 'execution_mode="cloud"' in src
    assert "if _job_id and _s3_run:" in src


def test_cloud_state_chip_covers_the_documented_states():
    src = _ICESHEETS.read_text()
    for state in ("not_configured", "checking", "ready", "submitting",
                  "queued", "running", "completed", "failed"):
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
