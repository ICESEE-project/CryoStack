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
    src = _ICESHEETS_GW.read_text()
    # session id / ws path appear only inside the collapsed <details> block
    assert "<summary" in src and "Diagnostics" in src
    # the pairing code (not a long-lived credential) is the surfaced pairing value
    assert "Pairing code:" in src
    # the browser-facing setup link carries only the non-secret session id + app
    assert "connect/?session={SESSION['id']}&app=icesheets" in src
    assert "pairing_code}" not in src.split("Open CryoStack Connector Setup")[0].rsplit("<a href", 1)[-1]
