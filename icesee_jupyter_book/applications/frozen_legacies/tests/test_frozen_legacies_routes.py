"""Frozen Legacies is an authenticated CryoStack application: the page, its
assets and its data are protected by ``AuthManager.require_login`` exactly
like CryoLauncher and ICESEE, and entering it establishes the authenticated
user's own workspace."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.workspace import WorkspaceUser, owner_root
from icesee_jupyter_book.applications.frozen_legacies import server

_APP_PATH = _REPO / "bin" / "icesee_app.py"
_PROTECTED = (
    "/frozen-legacies/",
    "/frozen-legacies/assets/frozen_legacies.js",
    "/frozen-legacies/data/catalog.json",
)


def _auth(tmp_path, monkeypatch):
    from icesee_auth import AuthManager

    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(tmp_path / "auth.db"))
    return AuthManager()


def _app(auth, workspace_root):
    from aiohttp import web

    app = web.Application()
    auth.install(app)
    app[server.WORKSPACE_ROOT_KEY] = str(workspace_root)
    server.install_frozen_legacies(app, auth=auth)
    return app


def _login(auth, email):
    user = auth.storage.create_user(
        email=email, display_name=email.split("@")[0],
        institution=None, password_hash="x",
    )
    session = auth.storage.create_session(ttl_seconds=3600, user_id=user.id)
    return user, {"icesee_session": session.id}


def _workspace_dir(workspace_root, user):
    ws_user = WorkspaceUser(user_id=user.id, source="cryostack-auth")
    return owner_root(ws_user, workspace_root=workspace_root) / "frozen_legacies"


def _run(app, requests):
    """Issue ``(path, cookies)`` requests; return ``[(status, headers, body)]``."""
    from aiohttp.test_utils import TestClient, TestServer

    async def go():
        out = []
        async with TestClient(TestServer(app)) as client:
            for path, cookies in requests:
                resp = await client.get(path, cookies=cookies, allow_redirects=False)
                out.append((resp.status, resp.headers, await resp.read()))
        return out

    return asyncio.run(go())


# ── anonymous access ─────────────────────────────────────────────────
def test_anonymous_requests_redirect_to_login(tmp_path, monkeypatch):
    auth = _auth(tmp_path, monkeypatch)
    results = _run(_app(auth, tmp_path), [(p, None) for p in _PROTECTED])
    for path, (status, headers, _body) in zip(_PROTECTED, results):
        assert status == 302, path
        location = headers["Location"]
        assert location.startswith("/auth/login?return_to=")
        assert unquote(location.split("return_to=", 1)[1]) == path
    assert not (tmp_path / "users").exists()   # no workspace for anonymous


def test_bare_path_redirects_into_the_protected_application(tmp_path, monkeypatch):
    auth = _auth(tmp_path, monkeypatch)
    (status, headers, _), = _run(_app(auth, tmp_path), [("/frozen-legacies", None)])
    assert status == 302
    assert headers["Location"] == "/frozen-legacies/"


def test_expired_or_unknown_session_is_anonymous(tmp_path, monkeypatch):
    auth = _auth(tmp_path, monkeypatch)
    (status, headers, _), = _run(
        _app(auth, tmp_path),
        [("/frozen-legacies/", {"icesee_session": "not-a-session"})],
    )
    assert status == 302
    assert headers["Location"].startswith("/auth/login")


# ── authenticated access ─────────────────────────────────────────────
def test_authenticated_user_gets_the_explorer_and_a_workspace(tmp_path, monkeypatch):
    auth = _auth(tmp_path, monkeypatch)
    user, cookies = _login(auth, "a@example.org")
    results = _run(_app(auth, tmp_path), [(p, cookies) for p in _PROTECTED])

    (status, headers, body), asset, data = results
    assert status == 200
    assert b"Frozen Legacies" in body
    assert b'id="cryostack-account-slot"' in body       # global account control
    assert b"/_static/cryostack_account.js" in body
    assert "private" in headers["Cache-Control"]
    assert asset[0] == 200 and b"FrozenLegaciesUI" in asset[2]
    assert data[0] == 200 and b'"datasets"' in data[2]

    workspace = _workspace_dir(tmp_path, user)
    assert (workspace / "radar").is_dir()
    assert workspace.parent.parent == (tmp_path / "users").resolve()


# ── workspace isolation ──────────────────────────────────────────────
def test_two_users_get_separate_workspaces(tmp_path, monkeypatch):
    auth = _auth(tmp_path, monkeypatch)
    user_a, cookies_a = _login(auth, "a@example.org")
    user_b, cookies_b = _login(auth, "b@example.org")
    results = _run(_app(auth, tmp_path), [
        ("/frozen-legacies/", cookies_a),
        ("/frozen-legacies/", cookies_b),
    ])
    assert [r[0] for r in results] == [200, 200]

    ws_a = _workspace_dir(tmp_path, user_a)
    ws_b = _workspace_dir(tmp_path, user_b)
    assert ws_a != ws_b
    assert (ws_a / "radar").is_dir() and (ws_b / "radar").is_dir()
    assert sorted(p.name for p in (tmp_path / "users").iterdir()) == sorted(
        [ws_a.parent.name, ws_b.parent.name]
    )


def test_user_files_are_not_reachable_through_application_routes(tmp_path, monkeypatch):
    """A user's workspace is never served from the static application tree."""
    auth = _auth(tmp_path, monkeypatch)
    user_a, cookies_a = _login(auth, "a@example.org")
    _user_b, cookies_b = _login(auth, "b@example.org")
    _run(_app(auth, tmp_path), [("/frozen-legacies/", cookies_a)])
    secret = _workspace_dir(tmp_path, user_a) / "radar" / "secret.csv"
    secret.write_text("a's data")

    rel = Path("..") / ".." / ".." / ".." / secret.relative_to(_REPO.anchor)
    probes = [
        f"/frozen-legacies/data/{rel.as_posix()}",
        f"/frozen-legacies/data/%2e%2e/%2e%2e/{secret.name}",
        f"/frozen-legacies/data/..%2f..%2f{secret.name}",
    ]
    for status, _h, body in _run(_app(auth, tmp_path), [(p, cookies_b) for p in probes]):
        assert status == 404
        assert b"a's data" not in body


# ── path traversal on the application routes ─────────────────────────
@pytest.mark.parametrize("path", [
    "/frozen-legacies/data/../server.py",
    "/frozen-legacies/data/%2e%2e/server.py",
    "/frozen-legacies/data/..%2fserver.py",
    "/frozen-legacies/assets/%2e%2e/workspace.py",
    "/frozen-legacies/assets/..%2f..%2f..%2f..%2fbin/icesee_app.py",
    "/frozen-legacies/data/%2e%2e%2f%2e%2e%2fPickers/ASTRA_MAC.py",
    "/frozen-legacies/data/antarctica",          # directory: no listing
    "/frozen-legacies/data/",
    "/frozen-legacies/assets/.hidden",
    "/frozen-legacies/data/missing.json",
])
def test_traversal_and_listing_are_refused(tmp_path, monkeypatch, path):
    auth = _auth(tmp_path, monkeypatch)
    _user, cookies = _login(auth, "a@example.org")
    (status, _h, body), = _run(_app(auth, tmp_path), [(path, cookies)])
    assert status in (403, 404)
    assert b"import " not in body and b"def " not in body


# ── gateway wiring ───────────────────────────────────────────────────
def test_gateway_installs_the_protected_frozen_legacies_routes():
    src = _APP_PATH.read_text(encoding="utf-8")
    assert "install_frozen_legacies(" in src
    assert 'add_static(\n        "/frozen-legacies' not in src
    assert "frozen_legacies_assets_root" not in src


def test_gateway_redirects_anonymous_frozen_legacies_to_login(tmp_path, monkeypatch):
    """The real gateway app: Frozen Legacies is locked like /icesheets/."""
    if not (_REPO / "icesee_jupyter_book" / "_build" / "html" / "index.html").exists():
        pytest.skip("Jupyter Book is not built; the gateway refuses to start.")
    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(tmp_path / "auth.db"))
    monkeypatch.setenv("CRYOSTACK_APP_START_MODE", "lazy")
    # the full gateway also opens the LIVIST store, Control Center ops store
    # and Frozen Legacies catalog: keep them out of the repository's var/
    monkeypatch.setenv("CRYOSTACK_LIVIST_DATABASE", str(tmp_path / "livist.db"))
    monkeypatch.setenv("CRYOSTACK_CONTROL_OPS_DATABASE", str(tmp_path / "ops.db"))
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_CATALOG", str(tmp_path / "catalog.db"))
    spec = importlib.util.spec_from_file_location("_icesee_app_frozen", _APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    results = _run(mod.make_app(), [
        ("/frozen-legacies/", None),
        ("/frozen-legacies/data/catalog.json", None),
        ("/icesheets/", None),
    ])
    for status, headers, _body in results:
        assert status == 302
        assert headers["Location"].startswith("/auth/login?return_to=")
