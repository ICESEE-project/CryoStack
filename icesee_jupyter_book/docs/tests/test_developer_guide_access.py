"""The Developer Guide is visible only to owners.

Covers the server-side 403 on Developer Guide pages and their sources
(including path variants), the removal of Developer Guide navigation from
pages served to other users, the filtered search index, the Frozen Legacies
top navigation, and that Getting Started and the User Manual stay public.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_BOOK = _HERE.parents[1]
_REPO = _BOOK.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book import developer_docs_access as access

SECRET = "Developer-only architecture text"

_SIDEBAR = """
<nav class="bd-links"><ul class="nav bd-sidenav">
  <li class="toctree-l1"><a class="reference internal" href="{up}documentation.html">Documentation</a></li>
  <li class="toctree-l1 has-children"><a class="reference internal" href="{up}docs/developer_guide.html">Developer Guide</a>
    <details><ul>
      <li class="toctree-l2"><a class="reference internal" href="{up}docs/dev_architecture.html">Architecture</a></li>
    </ul></details></li>
  <li class="toctree-l1"><a class="reference internal" href="{up}resources.html">Resources</a></li>
</ul></nav>
"""


def _page(title, body, up=""):
    return (f"<!doctype html><html><head><title>{title}</title>"
            f'<link rel="next" href="{up}docs/developer_guide.html"></head><body>'
            + _SIDEBAR.format(up=up) + f"<main>{body}</main></body></html>")


@pytest.fixture
def book(tmp_path):
    root = tmp_path / "html"
    (root / "docs").mkdir(parents=True)
    (root / "_sources" / "docs").mkdir(parents=True)
    (root / "applications" / "frozen_legacies").mkdir(parents=True)
    (root / "documentation.html").write_text(_page("Documentation", """
        <div><h3>Source code</h3></div>
        <div data-cryostack-audience="maintainers"><h3>CryoStack Developer Guide</h3>
          <p>The <a href="docs/developer_guide.html">Developer Guide</a> covers internals.</p></div>
        <div class="cryostack-docs-card-actions">
          <a href="applications/frozen_legacies/user_manual.html">User Manual</a>
          <a href="applications/frozen_legacies/developer.html">Developer Guide</a></div>"""))
    (root / "docs" / "getting_started.html").write_text(_page("Getting Started", """
        <p>Building CryoStack is covered separately in the
        <a href="developer_guide.html">Developer Guide</a>.</p>
        <a class="left-prev" href="developer_guide.html">previous</a>""", up="../"))
    (root / "docs" / "user_manual.html").write_text(_page("User Manual", "<p>How to run.</p>",
                                                          up="../"))
    for name in ("developer_guide", "dev_architecture", "dev_testing"):
        (root / "docs" / f"{name}.html").write_text(_page(name, f"<p>{SECRET}</p>", up="../"))
    (root / "_sources" / "docs" / "developer_guide.md").write_text(SECRET)
    (root / "_sources" / "docs" / "dev_testing.md.txt").write_text(SECRET)
    (root / "_sources" / "docs" / "getting_started.md").write_text("public source")
    (root / "objects.inv").write_bytes(b"# Sphinx inventory\n")
    (root / "applications" / "frozen_legacies" / "developer.html").write_text(SECRET)
    (root / "applications" / "frozen_legacies" / "api_reference.html").write_text(SECRET)
    (root / "applications" / "frozen_legacies" / "user_manual.html").write_text("FL manual")
    index = {
        "alltitles": {"Developer Guide": [[0, None]], "Getting Started": [[1, None]],
                      "Shared": [[0, "a"], [2, "b"]]},
        "docnames": ["docs/developer_guide", "docs/getting_started", "docs/user_manual"],
        "envversion": {"sphinx": 61}, "filenames": ["docs/developer_guide.md",
                                                    "docs/getting_started.md",
                                                    "docs/user_manual.md"],
        "indexentries": {}, "objects": {}, "objnames": {}, "objtypes": {},
        "terms": {"architectur": 0, "run": [1, 2], "both": [0, 2]},
        "titles": ["Developer Guide", "Getting Started", "User Manual"],
        "titleterms": {"develop": 0, "guid": [0], "manual": 2},
    }
    (root / "searchindex.js").write_text("Search.setIndex(" + json.dumps(index) + ")")
    app_page = tmp_path / "fl_index.html"
    app_page.write_text("""<html><body><div class="fl-topnav-links">
        <a href="/applications/frozen_legacies/getting_started.html" class="fl-topnav-link">Getting Started</a>
        <a href="/applications/frozen_legacies/user_manual.html" class="fl-topnav-link">User Manual</a>
        <a href="/applications/frozen_legacies/developer.html" class="fl-topnav-link">Developer Guide</a>
        </div></body></html>""")
    return root, app_page


def _client_run(tmp_path, monkeypatch, book, script):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from icesee_auth import AuthManager

    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(tmp_path / "auth.db"))
    root, app_page = book
    auth = AuthManager()
    app = web.Application()
    auth.install(app)
    app.middlewares.append(access.developer_docs_middleware(
        auth, root, html_pages={"/frozen-legacies/": lambda: app_page}))

    async def fl_index(request):
        return web.FileResponse(app_page)

    app.router.add_get("/frozen-legacies/", auth.require_login(fl_index))
    app.router.add_static("/", path=str(root), show_index=True)

    def login(email, *roles):
        store = auth.storage
        user = store.create_user(email=email, display_name=email, institution=None,
                                 password_hash="x")
        for role in roles:
            store.grant_role(user_id=user.id, role=role)
        return {"icesee_session": store.create_session(ttl_seconds=3600, user_id=user.id).id}

    async def go():
        async with TestClient(TestServer(app)) as client:
            return await script(client, login)

    return asyncio.run(go())


RESTRICTED_URLS = [
    "/docs/developer_guide.html",
    "/docs/dev_architecture.html",
    "/docs/dev_testing.html",
    "/_sources/docs/developer_guide.md",
    "/_sources/docs/dev_testing.md.txt",
    "/objects.inv",
    "/applications/frozen_legacies/developer.html",
    "/applications/frozen_legacies/api_reference.html",
]
VARIANT_URLS = [
    "/docs/./developer_guide.html",
    "/docs//developer_guide.html",
    "/docs/%64eveloper_guide.html",
    "/docs/developer_guide.html?print=1",
    "/docs/../docs/developer_guide.html",
]


async def _get(client, url, cookies=None):
    resp = await client.get(url, cookies=cookies, allow_redirects=False)
    return resp.status, await resp.text(errors="replace")


def test_only_owners_can_open_developer_guide_pages(
        tmp_path, monkeypatch, book):
    async def script(client, login):
        people = {"anonymous": None, "user": login("u@example.org"),
                  "developer": login("d@example.org", "developer"),
                  "maintainer": login("m@example.org", "maintainer"),
                  "admin": login("a@example.org", "admin"),
                  "owner": login("o@example.org", "owner"),
                  "delegated_maintainer": login(
                      "dm@example.org", "maintainer", "developer_docs"),
                  "delegated_admin": login(
                      "da@example.org", "admin", "developer_docs"),
                  "stale_delegation": login("stale@example.org", "developer_docs")}
        out = {}
        for who, ck in people.items():
            out[who] = {url: await _get(client, url, ck)
                        for url in RESTRICTED_URLS + VARIANT_URLS}
        return out

    out = _client_run(tmp_path, monkeypatch, book, script)
    for who in ("user", "developer", "maintainer", "admin", "stale_delegation"):
        for url in RESTRICTED_URLS:
            assert out[who][url][0] == 403, (who, url)
        for url in VARIANT_URLS:
            status, body = out[who][url]
            assert status == 403, (who, url, status)
            assert SECRET not in body
    for url in RESTRICTED_URLS + VARIANT_URLS:
        status, body = out["anonymous"][url]
        assert status in (302, 403, 404) and SECRET not in body, url
    assert out["anonymous"]["/docs/developer_guide.html"][0] == 302   # sign in first
    for who in ("owner", "delegated_maintainer", "delegated_admin"):
        status, body = out[who]["/docs/developer_guide.html"]
        assert status == 200 and SECRET in body, who
        assert out[who]["/_sources/docs/developer_guide.md"][0] == 200


def test_ordinary_users_do_not_see_developer_guide_navigation(tmp_path, monkeypatch, book):
    async def script(client, login):
        user = login("u@example.org")
        maint = login("m@example.org", "maintainer")
        owner = login("o@example.org", "owner")
        out = {}
        for who, ck in (("anonymous", None), ("user", user), ("maintainer", maint),
                        ("owner", owner)):
            out[who] = {url: await _get(client, url, ck) for url in (
                "/documentation.html", "/docs/getting_started.html", "/docs/user_manual.html",
                "/_sources/docs/getting_started.md", "/docs/", "/searchindex.js",
                "/frozen-legacies/")}
        resp = await client.get("/docs/getting_started.html", cookies=user)
        out["headers"] = dict(resp.headers)
        return out

    out = _client_run(tmp_path, monkeypatch, book, script)
    for who in ("anonymous", "user"):
        pages = out[who]
        for url in ("/documentation.html", "/docs/getting_started.html",
                    "/docs/user_manual.html", "/_sources/docs/getting_started.md"):
            assert pages[url][0] == 200, (who, url)       # Getting Started / User Manual public
        for url in ("/documentation.html", "/docs/getting_started.html",
                    "/docs/user_manual.html", "/docs/"):
            body = pages[url][1]
            assert not re.search(r'href="[^"]*(developer_guide|dev_architecture|dev_testing)\.html',
                                 body), (who, url)
            assert "frozen_legacies/developer.html" not in body
            assert 'rel="next"' not in body or "developer_guide" not in body
        doc = pages["/documentation.html"][1]
        assert "CryoStack Developer Guide" not in doc and "Source code" in doc
        assert "Documentation" in doc and "Resources" in doc        # other navigation kept
        assert "frozen_legacies/user_manual.html" in doc
        gs = pages["/docs/getting_started.html"][1]
        assert "covered separately in the\n        Developer Guide." in gs   # prose kept as text
        assert "left-prev" not in gs and "Architecture" not in gs
        search = pages["/searchindex.js"][1]
        assert "Developer Guide" not in search and "architectur" not in search
        assert "Getting Started" in search
        assert pages["/docs/"][0] == 200 and "developer_guide" not in pages["/docs/"][1]
    assert out["anonymous"]["/frozen-legacies/"][0] == 302           # app needs sign-in
    fl = out["user"]["/frozen-legacies/"][1]
    assert "User Manual" in fl and "Developer Guide" not in fl
    assert "Developer Guide" not in out["maintainer"]["/documentation.html"][1]
    owner = out["owner"]
    assert 'href="docs/developer_guide.html"' in owner["/documentation.html"][1]
    assert 'href="developer_guide.html"' in owner["/docs/getting_started.html"][1]
    assert "CryoStack Developer Guide" in owner["/documentation.html"][1]
    assert "Developer Guide" in owner["/frozen-legacies/"][1]
    assert "Developer Guide" in owner["/searchindex.js"][1]
    assert out["headers"]["Cache-Control"] == "private, no-cache"
    assert "Cookie" in out["headers"]["Vary"]


def test_search_index_filter_remaps_and_fails_closed():
    index = {"alltitles": {"A": [[0, None]], "B": [[1, "x"]]},
             "docnames": ["docs/developer_guide", "docs/user_manual"],
             "filenames": ["a.md", "b.md"], "titles": ["A", "B"],
             "terms": {"a": 0, "b": 1, "ab": [0, 1]}, "titleterms": {"a": [0], "b": 1}}
    out = json.loads(access.filter_search_index(
        "Search.setIndex(" + json.dumps(index) + ")")[len("Search.setIndex("):-1])
    assert out["docnames"] == ["docs/user_manual"] and out["titles"] == ["B"]
    assert out["terms"] == {"b": 0, "ab": [0]} and out["titleterms"] == {"b": 0}
    assert out["alltitles"] == {"B": [[0, "x"]]}
    broken = access.filter_search_index("Search.setIndex({not json})")
    assert json.loads(broken[len("Search.setIndex("):-1])["docnames"] == []


def test_livist_api_inventory_and_search_are_restricted_and_links_are_filtered():
    assert access.restricted_livist_doc("api/")
    assert access.restricted_livist_doc("api/index.html")
    assert access.restricted_livist_doc("objects.inv")
    assert access.restricted_livist_doc("search.json")
    assert access.restricted_livist_doc("sitemap.xml")
    assert not access.restricted_livist_doc("livist_user_manual/index.html")
    html = ('<nav><a href="/livist/docs/livist_user_manual/">Manual</a>'
            '<a href="/livist/docs/api/">Python API</a></nav>')
    filtered = access.filter_livist_html(html)
    assert "livist_user_manual" in filtered
    assert "Python API" not in filtered and "/docs/api" not in filtered


def test_restricted_documents_match_the_developer_guide_in_the_tocs():
    import yaml

    toc = yaml.safe_load((_BOOK / "_toc.yml").read_text())
    dev = next(c for c in toc["chapters"] if c.get("file") == "docs/developer_guide")
    expected = {"docs/developer_guide"} | {s["file"] for s in dev.get("sections", [])}
    fl = (_BOOK / "toc" / "frozen_legacies.yml").read_text()
    for doc in ("applications/frozen_legacies/developer",
                "applications/frozen_legacies/api_reference"):
        assert doc in fl
        expected.add(doc)
    assert access.RESTRICTED_DOCS == expected
    public = {"docs/getting_started", "docs/user_manual", "documentation", "index",
              "applications/frozen_legacies/getting_started",
              "applications/frozen_legacies/user_manual"}
    assert not public & access.RESTRICTED_DOCS


def test_gateway_installs_the_restriction():
    src = (_REPO / "bin" / "icesee_app.py").read_text()
    assert "developer_docs_middleware(" in src
    assert '"/frozen-legacies/": lambda: frozen_legacies_root() / "index.html"' in src
    assert access.DEVELOPER_DOC_ROLES == {"owner", "developer_docs"}


def test_built_book_pages_are_filtered_for_ordinary_users():
    built = _BOOK / "_build" / "html"
    if not (built / "docs" / "getting_started.html").exists():
        pytest.skip("book not built in this environment")
    for page in ("index.html", "documentation.html", "docs/getting_started.html",
                 "docs/user_manual.html"):
        if not (built / page).exists():
            continue
        html = access.filter_html((built / page).read_text(encoding="utf-8"), "/" + page)
        for href in re.findall(r'href="([^"]+)"', html):
            target = href.split("#")[0].split("?")[0]
            if not target or target.startswith(("http:", "https:", "mailto:")):
                continue
            resolved = access.urljoin("/" + page, target)
            assert access.restricted_doc(resolved) is None, (page, href)
        assert "Getting Started" in html
