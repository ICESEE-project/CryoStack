"""Shared CryoStack branding: one canonical logo -> every packaging asset."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "build_brand_assets.py"
_CANONICAL = _REPO / "icesee_jupyter_book" / "cryostack.png"
_ASSETS = _REPO / "icesee_hpc_connector" / "assets"
_WEB_LOGO = _REPO / "deployment" / "deploy_web_nginx" / "web" / "connect" / "cryostack-logo.png"


def test_canonical_logo_is_the_only_hand_maintained_source():
    src = _SCRIPT.read_text()
    assert 'icesee_jupyter_book" / "cryostack.png"' in src
    # the script derives everything; it must not read a second logo file
    assert src.count("Image.open(") == 1


def test_build_brand_assets_regenerates_every_target():
    r = subprocess.run([sys.executable, str(_SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    from PIL import Image

    icns = _ASSETS / "cryostack-connector.icns"
    ico = _ASSETS / "cryostack-connector.ico"
    png = _ASSETS / "cryostack-connector-512.png"
    for p in (icns, ico, png, _WEB_LOGO):
        assert p.is_file() and p.stat().st_size > 0

    assert Image.open(png).size == (512, 512)
    with Image.open(ico) as im:
        assert im.size[0] >= 16
    assert icns.read_bytes()[:4] == b"icns"


def test_build_connector_wires_the_derived_icons():
    sh = (_REPO / "build_connector.sh").read_text()
    assert "scripts/build_brand_assets.py" in sh
    assert '--icon "$ICON_ICNS"' in sh          # macOS .app / Dock
    assert '--icon "$ICON_ICO"' in sh           # Windows .exe
    assert 'ln -s /Applications' in sh          # drag-to-install DMG
    assert "--osx-bundle-identifier" in sh


def test_connector_display_name_is_cryostack_connector():
    menu = (_REPO / "icesee_hpc_connector" / "connector_menubar_app.py").read_text()
    assert 'APP_NAME = "CryoStack Connector"' in menu
    for old in ("CryoLauncher Connector", "Cryolauncher_Connector", "ICESEE Connector"):
        assert old not in menu
    sh = (_REPO / "build_connector.sh").read_text()
    assert 'APP_BRAND="CryoStack Connector"' in sh
