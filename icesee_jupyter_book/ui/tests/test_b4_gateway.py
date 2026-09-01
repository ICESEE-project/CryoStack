"""B4: both gateways adopt the shared header / Remote Connection / Slurm panels
without disturbing the submission contract, B1/B2/B3 behaviour, or Cloud."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import ipywidgets as W

_ICESHEETS = _REPO / "icesee_jupyter_book/ui/icesheets_gateway.py"
_ICESEE = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"
_SHARED_CSS = _REPO / "icesee_jupyter_book/ui/shared_app_styles.py"
_GATEWAYS = (_ICESHEETS, _ICESEE)


# ── shared, generic components ──────────────────────────────────────────
@pytest.mark.parametrize("path", _GATEWAYS)
def test_gateway_uses_the_shared_panels(path):
    src = path.read_text()
    assert "build_remote_connection_panel(" in src
    assert "build_slurm_resources_panel(" in src
    # the single application-shell header is the app-menu nav bar; the gateway
    # must NOT stamp a second header strip.
    assert "build_application_header(" not in src


@pytest.mark.parametrize("path", _GATEWAYS)
def test_gateway_no_longer_hand_builds_a_remote_connection_accordion_body(path):
    src = path.read_text()
    # the old inline layout helpers for these rows are gone
    assert 'form_pair("TPN:' not in src
    assert 'form_pair("Acct:' not in src
    assert 'set_title(0, "🔒 Authentication")' not in src


# ── submission contract unchanged (B4 must be additive) ─────────────────
def test_icesheets_slurm_serializer_keys_unchanged():
    src = _ICESHEETS.read_text()
    for key in ('"job_name"', '"time"', '"nodes"', '"tasks"', '"tasks_per_node"',
                '"partition"', '"memory"'):
        assert key in src


@pytest.mark.parametrize("path", _GATEWAYS)
def test_submission_kwargs_unchanged(path):
    src = path.read_text()
    for kw in ("slurm_time=", "slurm_job_name=", "slurm_nodes=", "slurm_ntasks=",
               "slurm_tpn=", "slurm_part=", "slurm_mem=", "slurm_account=", "slurm_mail="):
        assert kw in src


# ── B3 preserved ───────────────────────────────────────────────────────
@pytest.mark.parametrize("path", _GATEWAYS)
def test_b3_access_gate_and_identity_verification_still_wired(path):
    src = path.read_text()
    assert "enforce_remote_access(" in src
    assert "verify_remote_identity(" in src


@pytest.mark.parametrize("path", _GATEWAYS)
def test_pre_submit_slurm_validation_added(path):
    src = path.read_text()
    assert "validate_slurm_resources(" in src


# ── B1 preserved: no personal defaults reintroduced ────────────────────
@pytest.mark.parametrize("path", _GATEWAYS)
def test_no_personal_or_developer_defaults(path):
    src = path.read_text()
    for bad in ("r-arobel3-0", "gts-arobel3-atlas", "bankyanjo@gmail",
                'value=os.environ.get("USER"', "value=getpass.getuser()"):
        assert bad not in src


# ── shared responsive CSS lives in the shared stylesheet ───────────────
def test_shared_css_carries_the_b4_responsive_classes():
    css = _SHARED_CSS.read_text()
    for cls in ("cryostack-group-title",
                "cryostack-slurm-numeric-grid", "cryostack-conn-status",
                "cryostack-remote-connection-panel", "cryostack-diagnostics-accordion",
                "cryostack-help"):
        assert cls in css
    for bp in ("max-width: 768px", "max-width: 430px", "max-width: 360px"):
        assert bp in css
    # the numeric grid actually steps down 3 -> 2 -> 1
    assert "repeat(3, minmax(0, 1fr))" in css
    assert "repeat(2, minmax(0, 1fr))" in css


# ── the built pages actually render the grouped panels ─────────────────
@pytest.mark.parametrize("builder_name", ["build_icesheets_ui", "build_icesee_ui"])
def test_built_page_contains_the_grouped_panels(builder_name, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "b4-test-user")
    monkeypatch.setenv("USER", "b4-service-user")
    monkeypatch.setenv("LOGNAME", "b4-service-user")

    if builder_name == "build_icesheets_ui":
        from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui as build
    else:
        from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui as build

    page = build()

    html = []

    def walk(w):
        if isinstance(w, W.HTML):
            html.append(w.value)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    blob = "\n".join(html)
    assert "Compute resource" in blob and "Your HPC identity" in blob
    assert "cryostack-slurm-resources-panel" in blob
    # connector/session internals are behind Diagnostics, not loose in the panel
    assert "cryostack-remote-connection-panel" in blob
