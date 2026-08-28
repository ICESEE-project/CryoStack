"""Logout must not leave the browser retrying a culled Voila kernel.

After logout the server deletes the session and culls the page's Voila kernel.
Reloading the same URL (or a bfcache restore) keeps the dead
``/api/kernels/<id>/channels`` websocket retrying (404 loop) and the new
authenticated identity never drives a fresh render. The account control must
instead replace the document with a fresh top-level navigation to login.
"""
from __future__ import annotations

from pathlib import Path

_ACCOUNT_JS = (
    Path(__file__).resolve().parents[3]
    / "icesee_jupyter_book" / "_static" / "cryostack_account.js"
)


def _logout_handler_source() -> str:
    text = _ACCOUNT_JS.read_text(encoding="utf-8")
    start = text.index('fetch("/auth/logout"')
    end = text.index("addEventListener", start) if "addEventListener" in text[start:] else len(text)
    # grab a generous slice of the click handler body
    return text[start : start + 900]


def test_logout_replaces_document_instead_of_reloading():
    handler = _logout_handler_source()
    assert "window.location.replace(loginUrl())" in handler
    assert "window.location.reload()" not in handler


def test_login_url_helper_still_exists():
    text = _ACCOUNT_JS.read_text(encoding="utf-8")
    # loginUrl() is what the logout handler now navigates to
    assert "function loginUrl(" in text
    assert "LOGIN_ENDPOINT" in text
