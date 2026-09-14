"""Documentation/UI-access commit:

* the public Developer Guide is restyled with the existing CryoStack theme
  components (no page-specific visual system);
* operational/maintainer material has moved to a separate Maintainer Guide and
  is not duplicated in the public guide;
* the Maintainer Guide is excluded from the public book build AND protected at
  the request boundary by the existing role mechanism -- an ordinary user
  cannot fetch it by URL.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_BOOK = _REPO / "icesee_jupyter_book"
_DEV = _BOOK / "docs" / "developer_guide.md"
_MAINT = _BOOK / "docs" / "maintainer_guide.md"
_TOC = _BOOK / "_toc.yml"
_CONFIG = _BOOK / "_config.yml"
_APP = _REPO / "bin" / "icesee_app.py"

# operational concepts that must live ONLY in the maintainer guide
_OPERATIONAL_MARKERS = (
    "release_connector.sh",
    "publish_connector_artifact.sh",
    "connector_store.py",
    "nginx_audit.sh",
    "deploy_web.sh",
    "canonical artifact store",
    "Register into the canonical store",
    "Audit nginx",
    "atomic promotion",
)

# things that must never appear in either doc, at any access level
_FORBIDDEN = (
    "bankyanjo@gmail",
    "r-arobel3",
    "gts-arobel3",
    "arobel3-0",
    "BEGIN OPENSSH PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
)
_SECRET_ASSIGN = re.compile(
    r"(password|secret|token|api[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9/+_-]{12,}",
    re.IGNORECASE,
)


# ── 1. theme reuse, no independent visual system ───────────────────────
def test_developer_guide_uses_existing_cryostack_components():
    src = _DEV.read_text()
    for cls in ("cryostack-docs-page", "cryostack-docs-hero", "cryostack-section",
                "cryostack-section-label", "cryostack-docs-summary-grid",
                "cryostack-docs-summary-card", "cryostack-btn", "cryostack-footer",
                "cryostack-status"):
        assert cls in src, cls


def test_developer_guide_introduces_no_page_specific_visual_system():
    src = _DEV.read_text()
    # the only <style> block is the shared "hide the duplicate H1" snippet
    styles = re.findall(r"<style>(.*?)</style>", src, re.DOTALL)
    assert len(styles) == 1
    assert "h1:first-child" in styles[0]
    # no new class definitions, no responsive rules defined on the page
    assert "@media" not in src
    assert "{" not in styles[0] or "display: none" in styles[0]


def test_developer_guide_hero_matches_the_documentation_pages():
    src = _DEV.read_text()
    assert "CryoStack Documentation" in src
    assert re.search(r"<h1>\s*Developer Guide\s*</h1>", src)


def test_nav_cards_anchor_to_real_headings():
    src = _DEV.read_text()
    anchors = set(re.findall(r'href="#([a-z0-9-]+)"', src))
    nav_targets = {
        "architecture", "application-development", "shared-ui",
        "models-and-adapters", "results-and-visualization", "testing",
        "connector-development", "contribution-workflow",
    }
    assert nav_targets <= anchors
    # every nav target has a matching markdown heading that Sphinx slugifies to it
    headings = re.findall(r"^##\s+(.+?)\s*$", src, re.MULTILINE)
    slugs = {re.sub(r"[^a-z0-9]+", "-", h.lower()).strip("-") for h in headings}
    assert nav_targets <= slugs


# ── 2. clean public/operational split, no duplication ─────────────────
def test_operational_material_removed_from_public_guide():
    src = _DEV.read_text()
    for marker in _OPERATIONAL_MARKERS:
        assert marker not in src, f"operational marker leaked into public guide: {marker}"


def test_operational_material_lives_in_the_maintainer_guide():
    src = _MAINT.read_text()
    for marker in _OPERATIONAL_MARKERS:
        assert marker in src, f"missing from maintainer guide: {marker}"


def test_no_operational_content_is_duplicated():
    dev = _DEV.read_text()
    for marker in _OPERATIONAL_MARKERS:
        assert dev.count(marker) == 0


# ── 3. no secrets / personal identifiers at any level ─────────────────
@pytest.mark.parametrize("path", [_DEV, _MAINT])
def test_no_credentials_or_personal_identifiers(path):
    src = path.read_text()
    for bad in _FORBIDDEN:
        assert bad not in src, f"{bad} in {path.name}"
    m = _SECRET_ASSIGN.search(src)
    assert m is None, f"possible secret assignment in {path.name}: {m.group(0)!r}"


def test_maintainer_guide_uses_placeholders_not_real_infra():
    src = _MAINT.read_text()
    assert "<release-host>" in src and "<web-root>" in src


# ── 4. maintainer guide excluded from the public build ───────────────
def test_maintainer_guide_not_in_public_toc():
    toc = _TOC.read_text()
    assert "maintainer_guide" not in toc
    assert "developer_guide" in toc


def test_config_only_builds_toc_files():
    assert "only_build_toc_files : true" in _CONFIG.read_text()


def test_maintainer_guide_absent_from_any_built_html():
    built = _BOOK / "_build" / "html"
    if not built.exists():
        pytest.skip("book not built in this environment")
    assert not (built / "docs" / "maintainer_guide.html").exists()


# ── 5. real server-side protection ──────────────────────────────────
def test_maintainer_route_is_wrapped_in_require_roles():
    src = _APP.read_text()
    assert 'auth.require_roles(' in src
    assert "maintainer_access(maintainer_guide_page)" in src
    assert '"/docs/maintainer/"' in src


def _load_app_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("_icesee_app_docs", _APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_app(mod, auth):
    from aiohttp import web

    app = web.Application()
    auth.install(app)
    access = auth.require_roles("developer", "maintainer", "admin", "owner")
    app.router.add_get("/docs/maintainer", mod.maintainer_guide_redirect)
    app.router.add_get("/docs/maintainer/", access(mod.maintainer_guide_page))
    return app


def _new_session(auth, *, roles=()):
    storage = auth.storage
    user = storage.create_user(
        email="dev@example.org", display_name="Dev",
        institution=None, password_hash="x",
    )
    for role in roles:
        storage.grant_role(user_id=user.id, role=role)
    session = storage.create_session(ttl_seconds=3600, user_id=user.id)
    return {"icesee_session": session.id}


def _fetch_maintainer(tmp_path, monkeypatch, *, roles=None):
    """Return (status, body) for GET /docs/maintainer/ (roles=None -> anonymous)."""
    import asyncio
    from aiohttp.test_utils import TestClient, TestServer
    from icesee_auth import AuthManager

    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(tmp_path / "auth.db"))
    mod = _load_app_module()
    auth = AuthManager()
    app = _build_app(mod, auth)
    cookies = None if roles is None else _new_session(auth, roles=roles)

    async def go():
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/docs/maintainer/", allow_redirects=False, cookies=cookies,
            )
            return resp.status, await resp.text()

    return asyncio.run(go())


def test_anonymous_request_cannot_fetch_the_maintainer_guide(tmp_path, monkeypatch):
    status, body = _fetch_maintainer(tmp_path, monkeypatch, roles=None)
    assert status in (302, 303, 401, 403)
    assert "Publishing production connector binaries" not in body


def test_authenticated_user_without_a_role_is_forbidden(tmp_path, monkeypatch):
    status, body = _fetch_maintainer(tmp_path, monkeypatch, roles=[])
    assert status == 403
    assert "Publishing production connector binaries" not in body


def test_role_holder_can_read_the_maintainer_guide(tmp_path, monkeypatch):
    status, body = _fetch_maintainer(tmp_path, monkeypatch, roles=["maintainer"])
    assert status == 200
    assert "Publishing production connector binaries" in body
    assert 'href="/_static/icesee.css"' in body  # reuses the shared theme


# ── 6. mobile: shared CSS remains the only responsive implementation ──
def test_developer_guide_has_no_local_responsive_css():
    assert "@media" not in _DEV.read_text()


def test_shared_docs_stylesheet_still_carries_the_responsive_foundation():
    css = (_BOOK / "_static" / "icesee.css").read_text()
    assert "@media (max-width: 750px)" in css
    assert ".cryostack-docs-page pre" in css and "overflow-x: auto" in css
    assert ".cryostack-docs-page table" in css
