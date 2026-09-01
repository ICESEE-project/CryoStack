"""Shared CryoStack application header.

One reusable, compact application-shell header for every CryoStack Voila
gateway (IceSheets, ICESEE, and future Icepack). It is intentionally small --
an application shell, not a marketing hero.

Visual hierarchy::

    [CryoStack mark]   CryoStack
                       <application name>

Branding is single-source: the mark is derived from the ONE canonical logo
``icesee_jupyter_book/cryostack.png`` by ``scripts/build_brand_assets.py`` (the
same script that produces the Connector icons and the ``/connect/`` logo). This
module only base64-embeds the small derived mark; it never ships an
independently-edited image.
"""
from __future__ import annotations

import base64
import html
from functools import lru_cache
from pathlib import Path

import ipywidgets as W

#: derived by scripts/build_brand_assets.py from the canonical cryostack.png
_MARK_PATH = Path(__file__).resolve().parent / "assets" / "cryostack-mark-96.png"

#: the product wordmark -- always literally "CryoStack"
CRYOSTACK_WORDMARK = "CryoStack"


@lru_cache(maxsize=1)
def _mark_data_uri() -> str:
    """base64 data URI for the derived mark, or ``""`` when unavailable.

    Computed once per process (the mark never changes at runtime), so the
    header costs nothing after the first gateway build.
    """
    try:
        raw = _MARK_PATH.read_bytes()
    except OSError:
        return ""
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def application_header_html(application_name: str) -> str:
    """Return the header markup for ``application_name`` (e.g. ``"IceSheets"``).

    The CryoStack wordmark stays fixed; the application name is the prominent,
    distinct line beneath it.
    """
    app = html.escape((application_name or "").strip() or "Application")
    uri = _mark_data_uri()
    mark = (
        f'<img class="cryostack-app-header__mark" src="{uri}" alt="CryoStack" />'
        if uri
        else '<span class="cryostack-app-header__mark cryostack-app-header__mark--fallback">❄</span>'
    )
    return (
        '<div class="cryostack-app-header" role="banner">'
        f"{mark}"
        '<div class="cryostack-app-header__text">'
        f'<div class="cryostack-app-header__brand">{CRYOSTACK_WORDMARK}</div>'
        f'<div class="cryostack-app-header__app">{app}</div>'
        "</div>"
        "</div>"
    )


def build_application_header(application_name: str) -> W.HTML:
    """Reusable compact application-shell header widget."""
    widget = W.HTML(value=application_header_html(application_name))
    widget.layout = W.Layout(width="100%")
    widget.add_class("cryostack-app-header-host")
    return widget
