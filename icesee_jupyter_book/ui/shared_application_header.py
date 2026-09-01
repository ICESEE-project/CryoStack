"""The canonical CryoStack mark, for the single application-shell header.

Every CryoStack Voila application (IceSheets, ICESEE, future apps) has **one**
header: the navigation bar built by ``application_menus._build_application_menu``.
This module only supplies the base64-embedded CryoStack mark that bar places
beside the application name -- it does not build a second header strip.

Branding is single-source: the mark is derived from the ONE canonical logo
``icesee_jupyter_book/cryostack.png`` by ``scripts/build_brand_assets.py`` (the
same script that produces the Connector icons and the ``/connect/`` logo). This
module never ships an independently-edited image.
"""
from __future__ import annotations

import base64
import html
from functools import lru_cache
from pathlib import Path

#: derived by scripts/build_brand_assets.py from the canonical cryostack.png
_MARK_PATH = Path(__file__).resolve().parent / "assets" / "cryostack-mark-96.png"


@lru_cache(maxsize=1)
def cryostack_mark_data_uri() -> str:
    """base64 ``data:`` URI for the canonical CryoStack mark, or ``""`` when
    unavailable. Computed once per process (the mark never changes at runtime).
    """
    try:
        raw = _MARK_PATH.read_bytes()
    except OSError:
        return ""
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


# backwards-compatible alias (used by bin/icesee_app.py's warm-up page)
_mark_data_uri = cryostack_mark_data_uri


def cryostack_mark_img(*, css_class: str = "cryostack-app-mark", alt: str = "CryoStack") -> str:
    """An ``<img>`` for the CryoStack mark, or a ``❄`` fallback span carrying
    the same class, for embedding in the application navigation header."""
    alt = html.escape(alt)
    uri = cryostack_mark_data_uri()
    if uri:
        return f'<img class="{css_class}" src="{uri}" alt="{alt}" />'
    return f'<span class="{css_class} {css_class}--fallback" aria-hidden="true">❄</span>'
