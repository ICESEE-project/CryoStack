"""Visual acceptance cleanup: exactly ONE application-shell header per gateway,
the navigation bar, with the canonical CryoStack mark integrated into it -- no
second full-width CRYOSTACK / <app> branding strip.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import ipywidgets as W

from icesee_jupyter_book.ui.application_menus import (
    build_icesee_app_menu,
    build_icesheets_app_menu,
)

_ICESHEETS = _REPO / "icesee_jupyter_book/ui/icesheets_gateway.py"
_ICESEE = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"
_MENUS = _REPO / "icesee_jupyter_book/ui/application_menus.py"
_SHARED_CSS = _REPO / "icesee_jupyter_book/ui/shared_app_styles.py"


def _page_html(builder_name, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "hdr-test-user")
    monkeypatch.setenv("USER", "hdr-service-user")
    if builder_name == "icesheets":
        from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui as build
    else:
        from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui as build
    page = build()
    out = []

    def walk(w):
        if isinstance(w, W.HTML):
            out.append(w.value)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    return "\n".join(out)


# ── the menu component carries the single header + the canonical mark ──
@pytest.mark.parametrize("menu_fn,name", [
    (build_icesheets_app_menu, "CryoLauncher"),
    (build_icesee_app_menu, "ICESEE"),
])
def test_app_menu_is_one_header_with_the_canonical_mark(menu_fn, name):
    html = menu_fn().value
    # exactly one application-shell header element
    assert html.count('class="cryostack-app-header"') == 1
    # the canonical CryoStack mark, embedded, beside the app name
    assert "cryostack-app-mark" in html
    assert "data:image/png;base64," in html
    assert "cryostack.png" not in html
    # application identity kept (CryoLauncher / ICESEE), not replaced
    assert "cryostack-app-home" in html
    assert re.search(rf'class="cryostack-app-home"[^>]*>\s*{re.escape(name)}\s*</a>', html)
    assert "IceSheets</a>" not in html  # never swap the app identity for "IceSheets"
    # nav unchanged
    for link in ("getting_started.html", "user_manual.html", "resources.html"):
        assert link in html
    assert "Getting Started" in html and "User Manual" in html and "Resources" in html


# ── the gateways no longer stamp a second strip ──────────────────────
@pytest.mark.parametrize("path", [_ICESHEETS, _ICESEE])
def test_gateway_does_not_add_a_second_header_strip(path):
    src = path.read_text()
    assert "build_application_header(" not in src
    assert "shared_application_header import build_application_header" not in src


def test_shared_styles_no_longer_define_the_second_strip():
    css = _SHARED_CSS.read_text()
    # the B4 double-bar classes are gone (they collided with the nav header)
    for gone in ("cryostack-app-header__mark", "cryostack-app-header__brand",
                 "cryostack-app-header__app", "cryostack-app-header__text"):
        assert gone not in css
    # .cryostack-app-header itself now lives only in application_menus.py
    assert ".cryostack-app-header {" not in css


def test_single_source_mark_lives_only_in_application_menus():
    menus = _MENUS.read_text()
    assert "cryostack_mark_img" in menus
    assert ".cryostack-app-mark" in menus  # sizing rule co-located with the markup


# ── built pages: one header, mark present, no CRYOSTACK/<app> strip ──
@pytest.mark.parametrize("builder,identity", [("icesheets", "CryoLauncher"), ("icesee", "ICESEE")])
def test_built_page_has_exactly_one_app_header(builder, identity, monkeypatch):
    blob = _page_html(builder, monkeypatch)
    assert blob.count('class="cryostack-app-header"') == 1
    assert "cryostack-app-mark" in blob
    assert identity in blob
    # no remnant of the B4 double-bar
    for gone in ("cryostack-app-header__app", "cryostack-app-header__brand",
                 "cryostack-app-header-host"):
        assert gone not in blob


# ── mobile: mark + name stay visible; nav wraps per existing rules ────
def test_mobile_rules_keep_the_mark_and_name_together():
    menus = _MENUS.read_text()
    assert ".cryostack-app-identity" in menus
    # existing responsive breakpoints for the header retained
    assert "@media (max-width: 820px)" in menus
    assert "@media (max-width: 430px)" in menus
    # the identity block is a non-shrinking row
    ident = menus.split(".cryostack-app-identity {", 1)[1].split("}", 1)[0]
    assert "flex: 0 0 auto" in ident and "align-items: center" in ident
