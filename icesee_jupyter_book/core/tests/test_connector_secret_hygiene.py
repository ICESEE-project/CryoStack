"""Session capabilities must not leak into logs, URLs, downloads or the page.

Scope note: the one-time cluster *password* carried by the ``bootstrap-passwordless-ssh``
command payload is audited/redacted in a later commit (credential ownership);
this file covers the relay session capabilities introduced here.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_SECRET_TOKENS = ("control_secret", "session_secret")

_RELAY = _REPO_ROOT / "icesee_jupyter_book/core/connector_relay_server.py"
_CLIENT = _REPO_ROOT / "icesee_jupyter_book/core/connector_relay_client.py"
_CONNECT_JS = _REPO_ROOT / "deployment/deploy_web_nginx/web/connect/connect.js"
_CONNECT_HTML = _REPO_ROOT / "deployment/deploy_web_nginx/web/connect/index.html"
_MANIFEST_TOOL = _REPO_ROOT / "deployment/connector_manifest.py"
_ICESHEETS_GW = _REPO_ROOT / "icesee_jupyter_book/ui/icesheets_gateway.py"


def test_static_connector_page_never_handles_session_secrets():
    js = _CONNECT_JS.read_text()
    html = _CONNECT_HTML.read_text()
    for tok in _SECRET_TOKENS + ("pairing_code", "control_secret"):
        assert tok not in js, tok
        assert tok not in html, tok


def test_manifest_tooling_carries_no_session_capability_fields():
    src = _MANIFEST_TOOL.read_text()
    for tok in _SECRET_TOKENS:
        assert tok not in src


def test_relay_and_client_do_not_print_or_format_secrets_into_strings():
    for path in (_RELAY, _CLIENT):
        src = path.read_text()
        for tok in _SECRET_TOKENS:
            assert f'print({tok}' not in src
            assert f'"{{{tok}}}"' not in src
            assert f"'{{{tok}}}'" not in src


def test_gateway_keeps_session_id_and_ws_path_in_diagnostics_not_prominent():
    """B4-follow-up (CryoStack Connector UI restore): session id / ws path
    now come from shared_remote_connection_panel.connector_diagnostics_html,
    wired into the gateway's existing (collapsed-by-default) Advanced
    accordion -- never the compact, always-visible connector status line.
    The compact line (connector_pairing_status_html) surfaces only the
    one-time pairing code -- never the session id/ws path -- and the
    browser-facing setup link (connector_pairing_link_html) carries only
    the non-secret session id + app, never the pairing code."""
    from icesee_jupyter_book.ui.shared_remote_connection_panel import (
        connector_diagnostics_html,
        connector_pairing_link_html,
        connector_pairing_status_html,
    )

    status = connector_pairing_status_html(
        session_id="sess-123", pairing_code="AB12", online=False)
    assert "sess-123" not in status
    assert "AB12" in status

    diag = connector_diagnostics_html(
        session_id="sess-123", ws_url="/connector/ws/sess-123", relay_state="online")
    assert "sess-123" in diag and "/connector/ws/sess-123" in diag

    link = connector_pairing_link_html(session_id="sess-123", app="icesheets")
    assert "session=sess-123" in link and "app=icesheets" in link
    assert "AB12" not in link

    src = _ICESHEETS_GW.read_text()
    # the diagnostics widget is wired into advanced_children (the existing
    # Advanced accordion), never into connector_card (the compact,
    # always-rendered status line)
    assert "advanced_children=[remote_tag_row, connector_diagnostics]" in src
    assert "connector_card=relay_status" in src
