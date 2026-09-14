"""Phase-3: the /connect/ onboarding + pairing page.

Two layers:
  * JS unit tests (Node) for the pure manifest / detection / pairing logic --
    run here via ``node --test`` and skipped when node is unavailable.
  * Python structural checks that the static page stays manifest-driven,
    fully CryoStack-branded, and never puts a session token in a download URL.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_CONNECT = _HERE.parent / "deploy_web_nginx" / "web" / "connect"
_HTML = _CONNECT / "index.html"
_JS = _CONNECT / "connect.js"
_NODE_TEST = _HERE / "connect_page.test.mjs"

_NODE = shutil.which("node")


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_connect_page_js_unit_tests():
    result = subprocess.run(
        [_NODE, "--test", str(_NODE_TEST)],
        capture_output=True,
        text=True,
        cwd=str(_HERE),
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


def test_page_and_module_exist():
    assert _HTML.is_file()
    assert _JS.is_file()


def test_downloads_are_manifest_driven_not_hardcoded():
    html = _HTML.read_text()
    js = _JS.read_text()
    # The page fetches the manifest; it must not hardcode artifact filenames
    # in the markup.
    assert "/downloads/connectors/manifest.json" in js
    assert "CryoStack-Connector-macos-arm64.dmg" not in html
    assert "CryoStack-Connector-linux-x86_64.tar.gz" not in html
    assert "CryoStack-Connector-windows-x86_64.exe" not in html
    # Canonical filenames live in the platform metadata map (JS), not markup.
    for name in (
        "CryoStack-Connector-linux-x86_64.tar.gz",
        "CryoStack-Connector-macos-arm64.dmg",
        "CryoStack-Connector-macos-x86_64.dmg",
        "CryoStack-Connector-windows-x86_64.exe",
    ):
        assert name in js, name
    # windows-x86_64 is defined but not published yet -> it must appear only as
    # metadata, never as a rendered download decision the page hardcodes.
    assert 'filename: "CryoStack-Connector-windows-x86_64.exe"' in js


def test_no_legacy_connector_branding():
    for path in (_HTML, _JS):
        text = path.read_text()
        low = text.lower()
        assert "cryolauncher connector" not in low
        assert "cryolauncher_connector" not in low
        assert "icesee connector" not in low
        assert "icesee-connector" not in low


def test_no_session_token_in_static_download_urls():
    js = _JS.read_text()
    # downloadUrl builds only the static path; no query string, no session.
    assert "DOWNLOAD_BASE + filename" in js
    assert "?session=" not in js
    assert "download URL" not in js or "NEVER appended" in js


def test_pairing_uses_live_relay_endpoints():
    js = _JS.read_text()
    assert "/connector/status/" in js
    # global "attach to newest session anywhere" discovery is gone
    assert "/connector/latest" not in js
    assert "latestResp" not in js
    # never claims connected on a relay error
    assert 'if (relayError || !statusResp) return { state: "relay-unavailable" };' in js


def test_return_target_is_allowlisted():
    js = _JS.read_text()
    assert "RETURN_TARGETS" in js
    assert "/icesheets/" in js
    assert "/icesee-gui/" in js


def test_responsive_breakpoints_present():
    html = _HTML.read_text()
    for bp in ("768px", "430px", "360px"):
        assert f"max-width: {bp}" in html


def test_viewport_meta_present():
    assert 'name="viewport"' in _HTML.read_text()
