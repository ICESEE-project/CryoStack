"""The canonical CryoStack mark (single-source branding for the one app header)."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.ui.shared_application_header import (
    cryostack_mark_data_uri,
    cryostack_mark_img,
)

_CANONICAL = _REPO / "icesee_jupyter_book" / "cryostack.png"
_MARK = _REPO / "icesee_jupyter_book" / "ui" / "assets" / "cryostack-mark-96.png"


def test_mark_is_the_one_derived_asset_from_the_canonical_logo():
    assert _MARK.is_file()
    assert _MARK.stat().st_size < 60_000
    uri = cryostack_mark_data_uri()
    assert uri.startswith("data:image/png;base64,")
    # exactly one canonical source under icesee_jupyter_book/
    pngs = {p.name for p in _REPO.glob("icesee_jupyter_book/*.png")}
    assert "cryostack.png" in pngs


def test_mark_img_embeds_the_data_uri_and_never_links_the_1mb_canonical():
    html = cryostack_mark_img()
    assert "<img" in html and "data:image/png;base64," in html
    assert "cryostack.png" not in html


def test_mark_img_has_a_fallback_class_hook():
    # same class on the <img> and the fallback span so CSS sizes both
    assert 'class="cryostack-app-mark"' in cryostack_mark_img()
