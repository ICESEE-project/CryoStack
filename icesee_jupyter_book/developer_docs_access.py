"""Role-restricted Developer Guide pages.

The CryoStack Developer Guide (``docs/developer_guide`` and its sections)
and application developer guides (Frozen Legacies ``developer`` and
``api_reference``) are visible only to Control Center ``maintainer``,
``admin`` and ``owner`` roles. The documentation is a static Jupyter Book
served by the gateway, so the restriction is applied at the request
boundary by :func:`developer_docs_middleware`:

* **Pages and their sources** (``*.html``, ``_sources/*.md``/``.txt``/…) of
  restricted documents: anonymous visitors are sent to sign in, signed-in
  users without one of the roles get ``403``.
* **Every other book page** served to someone without the roles has links to
  restricted documents removed -- navigation entries (sidebar, previous/next,
  directory listings, card actions, application top navigation) are dropped,
  and links in running text become plain text. Blocks marked
  ``data-cryostack-audience="maintainers"`` are dropped as a whole.
* **The search index** served to them omits restricted documents, so their
  titles and text are not searchable.

Users with the roles receive the files unchanged. Book responses are marked
``Cache-Control: private, no-cache`` and ``Vary: Cookie`` because their
content depends on the signed-in user.
"""
from __future__ import annotations

import json
import posixpath
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

from aiohttp import web


DEVELOPER_DOC_ROLES = frozenset({"maintainer", "admin", "owner"})

#: restricted documents (book-relative, without suffix); the sections must
#: match the Developer Guide's sections in ``_toc.yml`` (checked by tests)
RESTRICTED_DOCS = frozenset({
    "docs/developer_guide",
    "docs/dev_architecture",
    "docs/dev_frontend",
    "docs/dev_execution",
    "docs/dev_connector",
    "docs/dev_models_results",
    "docs/dev_extending",
    "docs/building_agents",
    "docs/dev_testing",
    "docs/dev_deployment",
    "applications/frozen_legacies/developer",
    "applications/frozen_legacies/api_reference",
})

#: Sphinx inventory: lists every document name and title
_PRIVILEGED_FILES = frozenset({"objects.inv"})
_DOC_SUFFIXES = (".html", ".md", ".ipynb", ".rst", ".pdf", ".tex")
_AUDIENCE_ATTR = "data-cryostack-audience"


def restricted_doc(path: str) -> str | None:
    """The restricted document a book path belongs to, or ``None``."""
    rel = posixpath.normpath("/" + unquote(path or "")).lstrip("/")
    if rel in _PRIVILEGED_FILES:
        return rel
    if rel.startswith("_sources/"):
        rel = rel[len("_sources/"):]
        if rel.endswith(".txt"):
            rel = rel[:-4]
    for suffix in _DOC_SUFFIXES:
        if rel.endswith(suffix):
            rel = rel[:-len(suffix)]
            break
    return rel if rel in RESTRICTED_DOCS else None


def is_privileged(auth, request: web.Request) -> bool:
    user = auth.current_user(request)
    if user is None:
        return False
    roles = {str(r).strip().lower() for r in auth.storage.get_user_roles(user_id=user.id)}
    return bool(roles & DEVELOPER_DOC_ROLES)


# ── filtering for users without the roles ────────────────────────────
def _target_restricted(page_path: str, href: str) -> bool:
    if not href or href.startswith(("#", "mailto:", "javascript:")):
        return False
    target = urlsplit(urljoin(page_path, href.strip()))
    return restricted_doc(target.path) is not None


def _is_nav_link(anchor) -> bool:
    if anchor.get("class"):
        return True
    parent = anchor.parent
    classes = " ".join(parent.get("class") or []) if parent is not None else ""
    return "actions" in classes or "nav" in classes


def filter_html(html: str, page_path: str) -> str:
    """``html`` without restricted-document links and maintainer-only blocks."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    changed = False
    for block in soup.find_all(attrs={_AUDIENCE_ATTR: "maintainers"}):
        block.decompose()
        changed = True
    for link in soup.find_all("link", href=True):
        if _target_restricted(page_path, link["href"]):
            link.decompose()
            changed = True
    for anchor in soup.find_all("a", href=True):
        if anchor.decomposed or not _target_restricted(page_path, anchor["href"]):
            continue
        changed = True
        item = anchor.find_parent("li")
        if item is not None:
            item.decompose()              # navigation entry, with its sub-entries
        elif _is_nav_link(anchor):
            anchor.decompose()
        else:
            anchor.unwrap()               # a mention in running text stays as text
    return str(soup) if changed else html


_SEARCH_PREFIX = "Search.setIndex("


def _remap(value, keep: dict[int, int]):
    if isinstance(value, int):
        return keep.get(value)
    if isinstance(value, list):
        out = [keep[v] for v in value if isinstance(v, int) and v in keep]
        return out or None
    return value


def filter_search_index(text: str) -> str:
    """A Sphinx ``searchindex.js`` without restricted documents.

    Fails closed: if the index cannot be understood, an empty one is
    returned."""
    empty = _SEARCH_PREFIX + json.dumps({
        "alltitles": {}, "docnames": [], "envversion": {}, "filenames": [],
        "indexentries": {}, "objects": {}, "objnames": {}, "objtypes": {}, "terms": {},
        "titles": [], "titleterms": {}}) + ")"
    try:
        body = text.strip()
        if not body.startswith(_SEARCH_PREFIX) or not body.endswith(")"):
            return empty
        index = json.loads(body[len(_SEARCH_PREFIX):-1])
        docnames = index["docnames"]
        keep, new = {}, 0
        for old, name in enumerate(docnames):
            if name not in RESTRICTED_DOCS:
                keep[old] = new
                new += 1
        for key in ("docnames", "filenames", "titles"):
            if key in index:
                index[key] = [v for i, v in enumerate(index[key]) if i in keep]
        for key in ("terms", "titleterms"):
            mapped = {}
            for term, docs in (index.get(key) or {}).items():
                value = _remap(docs, keep)
                if value is not None:
                    mapped[term] = value
            index[key] = mapped
        for key in ("alltitles", "indexentries"):
            mapped = {}
            for title, entries in (index.get(key) or {}).items():
                kept = [[keep[e[0]], *e[1:]] for e in entries
                        if isinstance(e, list) and e and e[0] in keep]
                if kept:
                    mapped[title] = kept
            index[key] = mapped
        if index.get("objects"):
            index["objects"] = {}          # no API objects are documented; fail closed
        return _SEARCH_PREFIX + json.dumps(index) + ")"
    except Exception:
        return empty


# ── middleware ───────────────────────────────────────────────────────
def _book_relative(request: web.Request, book_dir: Path) -> str | None:
    """The book-relative path when the request is served by the book's
    static route, else ``None``."""
    route = request.match_info.route
    resource = getattr(route, "resource", None)
    if resource is None:
        return None
    try:
        info = resource.get_info()
    except Exception:
        return None
    directory = info.get("directory")
    if directory is None or Path(directory).resolve() != book_dir:
        return None
    return request.match_info.get("filename", "")


def _private(response: web.StreamResponse) -> web.StreamResponse:
    response.headers["Cache-Control"] = "private, no-cache"
    response.headers["Vary"] = "Cookie"
    return response


def developer_docs_middleware(auth, book_root: Path, *, html_pages: dict | None = None):
    """Middleware enforcing the Developer Guide restriction (module docstring).

    ``html_pages`` maps other exact request paths (application pages such as
    ``/frozen-legacies/``) to a callable returning their HTML file, so their
    navigation is filtered the same way."""
    book_dir = Path(book_root).resolve()
    html_pages = dict(html_pages or {})

    @web.middleware
    async def middleware(request: web.Request, handler):
        rel = _book_relative(request, book_dir)
        page_file = html_pages.get(request.path) if rel is None else None
        if rel is None and page_file is None:
            return await handler(request)

        privileged = is_privileged(auth, request)
        if rel is not None and restricted_doc(rel) is not None and not privileged:
            if auth.current_user(request) is None:
                raise web.HTTPFound("/auth/login?return_to="
                                    + quote(request.path_qs, safe=""))
            raise web.HTTPForbidden(text="The Developer Guide is available to CryoStack "
                                         "maintainers, admins and owners.")

        response = await handler(request)
        if privileged or response.status != 200 or request.method != "GET":
            return _private(response) if rel is not None or page_file else response

        if page_file is not None:
            source = Path(page_file())
        else:
            target = (book_dir / unquote(rel)).resolve()
            if target != book_dir and book_dir not in target.parents:
                return _private(response)
            if target.is_dir():
                # aiohttp's directory listing is an in-memory response
                text = getattr(response, "text", None)
                if text:
                    return _private(web.Response(
                        text=filter_html(text, request.path), content_type="text/html"))
                return _private(response)
            source = target
        name = source.name
        if name == "searchindex.js":
            return _private(web.Response(
                text=filter_search_index(source.read_text(encoding="utf-8")),
                content_type="application/javascript"))
        if name.endswith((".html", ".htm")):
            return _private(web.Response(
                text=filter_html(source.read_text(encoding="utf-8"), request.path),
                content_type="text/html"))
        return _private(response)

    return middleware
