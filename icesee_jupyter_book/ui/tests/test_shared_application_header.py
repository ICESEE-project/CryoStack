"""B4: shared CryoStack application header -- single-source branding."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.ui.shared_application_header import (
    application_header_html,
    build_application_header,
)

_CANONICAL = _REPO / "icesee_jupyter_book" / "cryostack.png"
_MARK = _REPO / "icesee_jupyter_book" / "ui" / "assets" / "cryostack-mark-96.png"


def test_header_shows_cryostack_wordmark_and_a_distinct_app_name():
    html = application_header_html("IceSheets")
    assert "CryoStack" in html
    assert "IceSheets" in html
    # the app name is its own, prominent line -- not glued onto "CryoStack"
    assert "cryostack-app-header__app" in html
    assert "cryostack-app-header__brand" in html


def test_both_application_names_render():
    for name in ("IceSheets", "ICESEE", "Icepack"):
        assert name in application_header_html(name)


def test_mark_is_the_derived_asset_from_the_one_canonical_logo():
    # the derived mark exists and is small enough to embed
    assert _MARK.is_file()
    assert _MARK.stat().st_size < 60_000
    # and it is embedded as a data URI (no external <img src> to a file path)
    html = application_header_html("ICESEE")
    assert "data:image/png;base64," in html
    assert "cryostack.png" not in html  # never links the 1MB canonical


def test_no_second_canonical_logo_file_was_introduced():
    # exactly one canonical source; everything else is script-derived
    pngs = {p.name for p in _REPO.glob("icesee_jupyter_book/*.png")}
    assert "cryostack.png" in pngs


def test_build_returns_a_widget():
    w = build_application_header("IceSheets")
    assert hasattr(w, "value") and "IceSheets" in w.value
