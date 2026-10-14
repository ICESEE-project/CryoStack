"""Frozen Legacies radar API: authentication, owner-scoped assets, safe
upload, shared-radar references, and server-rendered windows."""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[3]
for _p in (str(_REPO), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from frozen_legacies_radar_fixtures import (
    NAV_TEXT,
    radar_array,
    tiff_bytes,
    write_nav,
    write_registry,
    write_tiff,
)
from cryostack_src.workspace import WorkspaceUser, owner_root
from icesee_jupyter_book.applications.frozen_legacies import server
from icesee_jupyter_book.applications.frozen_legacies.radar.sources import SOURCES_ENV

API = "/frozen-legacies/api"
TIFF_NAME = "F127-C0471_C0483.tiff"


# ── harness ──────────────────────────────────────────────────────────
@pytest.fixture
def env(tmp_path, monkeypatch):
    """Auth DB, workspace root, and a shared-radar registry in tmp_path."""
    from icesee_auth import AuthManager

    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(tmp_path / "auth.db"))
    shared = tmp_path / "shared"
    shared.mkdir()
    write_tiff(shared / TIFF_NAME)
    write_nav(shared / "127.csv")
    registry = write_registry(tmp_path / "radar_sources.yaml", (
        "  - key: f127-c0471-c0483\n"
        "    title: F127 test strip\n"
        "    tiff: shared/F127-C0471_C0483.tiff\n"
        "    nav: shared/127.csv\n"
        "  - key: linked\n"
        "    tiff: shared/F127-C0471_C0483.tiff\n"
        "    dataset_id: frozen-legacies-lyra\n"
        "    flight: '125'\n"
    ))
    monkeypatch.setenv(SOURCES_ENV, str(registry))
    return {"tmp": tmp_path, "auth": AuthManager(), "workspace": tmp_path / "ws",
            "shared": shared, "registry": registry}


def _login(env, email):
    auth = env["auth"]
    user = auth.storage.create_user(
        email=email, display_name=email, institution=None, password_hash="x")
    session = auth.storage.create_session(ttl_seconds=3600, user_id=user.id)
    return user, {"icesee_session": session.id}


def _app(env, *, upload_limit=None):
    from aiohttp import web

    app = web.Application()
    env["auth"].install(app)
    app[server.WORKSPACE_ROOT_KEY] = str(env["workspace"])
    if upload_limit is not None:
        app[server.UPLOAD_LIMIT_KEY] = upload_limit
    server.install_frozen_legacies(app, auth=env["auth"])
    return app


def _radar_root(env, user):
    ws_user = WorkspaceUser(user_id=user.id, source="cryostack-auth")
    return owner_root(ws_user, workspace_root=env["workspace"]) / "frozen_legacies" / "radar"


def _form(tiff=None, nav=None, *, tiff_name=TIFF_NAME, extra=None):
    from aiohttp import FormData

    form = FormData()
    if tiff is not None:
        form.add_field("tiff", io.BytesIO(tiff), filename=tiff_name,
                       content_type="image/tiff")
    if nav is not None:
        form.add_field("nav", io.BytesIO(nav.encode() if isinstance(nav, str) else nav),
                       filename="127.csv", content_type="text/csv")
    for name, value in (extra or {}).items():
        form.add_field(name, value)
    return form


def _run(app, calls):
    """Run ``(method, path, kwargs)`` calls; return ``[(status, headers, body)]``."""
    from aiohttp.test_utils import TestClient, TestServer

    async def go():
        out = []
        async with TestClient(TestServer(app)) as client:
            for method, path, kwargs in calls:
                kwargs = dict(kwargs)
                if callable(kwargs.get("data")):
                    kwargs["data"] = kwargs["data"]()
                resp = await client.request(method, path, allow_redirects=False, **kwargs)
                out.append((resp.status, resp.headers, await resp.read()))
        return out

    return asyncio.run(go())


def _one(app, method, path, **kwargs):
    return _run(app, [(method, path, kwargs)])[0]


def _json(body):
    return json.loads(body)


def _upload(env, cookies, **form_kwargs):
    return _one(_app(env), "POST", f"{API}/assets/upload", cookies=cookies,
                data=lambda: _form(**form_kwargs))


def _no_paths(payload: bytes, env) -> None:
    text = payload.decode("utf-8", "replace")
    assert str(env["tmp"]) not in text and str(_REPO) not in text


# ── authentication ───────────────────────────────────────────────────
@pytest.mark.parametrize("method, path", [
    ("GET", f"{API}/radar/sources"),
    ("GET", f"{API}/assets"),
    ("POST", f"{API}/assets/shared"),
    ("POST", f"{API}/assets/upload"),
    ("GET", f"{API}/assets/{'a' * 32}"),
    ("GET", f"{API}/assets/{'a' * 32}/view?x=0&width=1&scale=1"),
])
def test_anonymous_api_requests_get_401(env, method, path):
    status, _h, body = _one(_app(env), method, path)
    assert status == 401
    assert _json(body)["error"] == "Authentication required."
    assert not env["workspace"].exists()


# ── shared radar ─────────────────────────────────────────────────────
def test_shared_sources_are_listed_without_paths(env):
    _user, cookies = _login(env, "a@example.org")
    status, _h, body = _one(_app(env), "GET", f"{API}/radar/sources", cookies=cookies)
    assert status == 200
    sources = {s["key"]: s for s in _json(body)["sources"]}
    assert sources["f127-c0471-c0483"]["flight"] == "127"
    assert (sources["f127-c0471-c0483"]["cbd_start"], sources["f127-c0471-c0483"]["cbd_end"]) == (471, 483)
    assert sources["f127-c0471-c0483"]["dataset_id"] is None     # not linked to LYRA
    assert sources["linked"]["dataset_id"] == "frozen-legacies-lyra"
    _no_paths(body, env)


def test_opening_a_shared_source_references_it_without_copying(env):
    user, cookies = _login(env, "a@example.org")
    status, _h, body = _one(_app(env), "POST", f"{API}/assets/shared", cookies=cookies,
                            json={"source": "f127-c0471-c0483"})
    assert status == 201
    asset = _json(body)
    assert asset["origin"] == "shared" and asset["shared_source"] == "f127-c0471-c0483"
    assert asset["image"]["width"] == 300 and asset["nav"]["cbd_range_rows"] == 4
    _no_paths(body, env)

    directory = _radar_root(env, user) / asset["asset_id"]
    assert sorted(p.name for p in directory.iterdir()) == ["asset.json", "outputs"]
    manifest = (directory / "asset.json").read_text()
    assert str(env["shared"]) not in manifest and "source.tiff" not in manifest

    # opening it again reuses the same asset
    status, _h, body = _one(_app(env), "POST", f"{API}/assets/shared", cookies=cookies,
                            json={"source": "f127-c0471-c0483"})
    assert status == 201 and _json(body)["asset_id"] == asset["asset_id"]
    assert len(list(_radar_root(env, user).iterdir())) == 1


@pytest.mark.parametrize("payload, status", [
    ({"source": "missing-source"}, 404),
    ({"source": "../etc/passwd"}, 400),
    ({"source": "/abs/path.tiff"}, 400),
    ({"source": "F127"}, 400),
    ({"source": None}, 400),
    ({}, 400),
    (["f127-c0471-c0483"], 400),
])
def test_shared_source_reference_validation(env, payload, status):
    user, cookies = _login(env, "a@example.org")
    got, _h, _b = _one(_app(env), "POST", f"{API}/assets/shared", cookies=cookies, json=payload)
    assert got == status
    assert not _radar_root(env, user).exists() or not any(_radar_root(env, user).iterdir())


def test_shared_source_removed_from_registry_becomes_unavailable(env):
    _user, cookies = _login(env, "a@example.org")
    _s, _h, body = _one(_app(env), "POST", f"{API}/assets/shared", cookies=cookies,
                        json={"source": "f127-c0471-c0483"})
    asset_id = _json(body)["asset_id"]
    write_registry(env["registry"], "")
    os.utime(env["registry"], ns=(1, 1))     # force the registry to be re-read
    view = f"{API}/assets/{asset_id}/view?x=0&width=300&scale=1"
    assert _one(_app(env), "GET", view, cookies=cookies)[0] == 409
    status, _h, body = _one(_app(env), "GET", f"{API}/assets/{asset_id}", cookies=cookies)
    assert status == 200 and _json(body)["available"] is False


def test_cross_origin_post_is_refused(env):
    user, cookies = _login(env, "a@example.org")
    status, _h, _b = _one(_app(env), "POST", f"{API}/assets/shared", cookies=cookies,
                          json={"source": "f127-c0471-c0483"},
                          headers={"Origin": "https://evil.example"})
    assert status == 403
    assert not _radar_root(env, user).exists() or not any(_radar_root(env, user).iterdir())


# ── upload ───────────────────────────────────────────────────────────
def test_upload_stores_the_tiff_in_the_users_workspace(env):
    user, cookies = _login(env, "a@example.org")
    data = tiff_bytes()
    status, _h, body = _upload(env, cookies, tiff=data, nav=NAV_TEXT)
    assert status == 201
    asset = _json(body)
    assert asset["origin"] == "upload" and asset["filename"] == TIFF_NAME
    assert (asset["flight"], asset["cbd_start"], asset["cbd_end"]) == ("127", 471, 483)
    assert asset["nav"]["present"] and asset["nav"]["origin"] == "upload"
    _no_paths(body, env)

    directory = _radar_root(env, user) / asset["asset_id"]
    assert sorted(p.name for p in directory.iterdir()) == [
        "asset.json", "nav.csv", "outputs", "source.tiff"]
    assert (directory / "source.tiff").read_bytes() == data
    assert (directory / "nav.csv").read_text() == NAV_TEXT
    manifest = json.loads((directory / "asset.json").read_text())
    assert manifest["origin"] == "upload" and len(manifest["sha256"]) == 64
    assert str(env["workspace"]) not in json.dumps(manifest)


def test_upload_without_navigation(env):
    user, cookies = _login(env, "a@example.org")
    status, _h, body = _upload(env, cookies, tiff=tiff_bytes(), nav="")
    assert status == 201 and _json(body)["nav"] == {"present": False}
    directory = _radar_root(env, user) / _json(body)["asset_id"]
    assert not (directory / "nav.csv").exists()


def test_malicious_filename_is_only_metadata(env):
    user, cookies = _login(env, "a@example.org")
    status, _h, body = _upload(env, cookies, tiff=tiff_bytes(),
                               tiff_name="../../../../F127-C0471_C0483.tiff")
    assert status == 201
    assert _json(body)["filename"] == TIFF_NAME
    # nothing was written outside the asset directory
    written = sorted(p.relative_to(env["tmp"]).as_posix()
                     for p in env["tmp"].rglob("*") if p.is_file())
    root = _radar_root(env, user).relative_to(env["tmp"]).as_posix()
    assert all(p.startswith(root) or not p.startswith("ws") for p in written)
    assert not (env["tmp"] / TIFF_NAME).exists()


def _assert_no_assets(env, user):
    root = _radar_root(env, user)
    assert not root.exists() or list(root.iterdir()) == []


@pytest.mark.parametrize("kwargs, status", [
    ({"tiff": b"\x89PNG\r\n\x1a\n" + b"\x00" * 64}, 400),                     # non-TIFF, .tiff name
    ({"tiff": b"plain text pretending", "tiff_name": "a.tiff"}, 400),
    ({"tiff": tiff_bytes(), "tiff_name": "F127.png"}, 400),                   # wrong extension
    ({"tiff": b"\x89PNG\r\n\x1a\n", "tiff_name": "x.png"}, 400),
    ({"tiff": tiff_bytes()[:-200]}, 400),                                     # truncated
    ({"tiff": b""}, 400),                                                     # empty
    ({"tiff": tiff_bytes(), "nav": "CBD,LAT\n1,2\n"}, 400),                   # bad nav
    ({"tiff": tiff_bytes(), "extra": {"path": "/etc/passwd"}}, 400),          # unknown field
    ({"nav": NAV_TEXT}, 400),                                                 # no TIFF
])
def test_rejected_uploads_leave_no_partial_asset(env, kwargs, status):
    user, cookies = _login(env, "a@example.org")
    got, _h, body = _upload(env, cookies, **kwargs)
    assert got == status, body
    assert "error" in _json(body)
    _assert_no_assets(env, user)


def test_truncated_raw_tiff_is_rejected(env):
    user, cookies = _login(env, "a@example.org")
    data = tiff_bytes(radar_array(400, 200), compression="raw")
    got, _h, _b = _upload(env, cookies, tiff=data[: len(data) // 2])
    assert got == 400
    _assert_no_assets(env, user)


def test_oversized_upload_is_rejected_and_cleaned_up(env):
    user, cookies = _login(env, "a@example.org")
    data = tiff_bytes()
    app = _app(env, upload_limit=len(data) - 1)
    status, _h, body = _one(app, "POST", f"{API}/assets/upload", cookies=cookies,
                            data=lambda: _form(tiff=data))
    assert status == 413 and "limit" in _json(body)["error"]
    _assert_no_assets(env, user)


def test_upload_rejects_non_multipart_bodies(env):
    user, cookies = _login(env, "a@example.org")
    status, _h, _b = _one(_app(env), "POST", f"{API}/assets/upload", cookies=cookies,
                          data=b"raw-bytes", headers={"Content-Type": "image/tiff"})
    assert status == 400
    _assert_no_assets(env, user)


def test_two_tiffs_in_one_upload_are_rejected(env):
    from aiohttp import FormData

    user, cookies = _login(env, "a@example.org")

    def form():
        f = FormData()
        f.add_field("tiff", io.BytesIO(tiff_bytes()), filename="a.tiff")
        f.add_field("tiff", io.BytesIO(tiff_bytes()), filename="b.tiff")
        return f

    status, _h, _b = _one(_app(env), "POST", f"{API}/assets/upload",
                          cookies=cookies, data=form)
    assert status == 400
    _assert_no_assets(env, user)


# ── asset detail and view ────────────────────────────────────────────
def test_detail_includes_exact_navigation_rows(env):
    _user, cookies = _login(env, "a@example.org")
    _s, _h, body = _upload(env, cookies, tiff=tiff_bytes(), nav=NAV_TEXT)
    asset_id = _json(body)["asset_id"]
    status, _h, body = _one(_app(env), "GET", f"{API}/assets/{asset_id}", cookies=cookies)
    assert status == 200
    rows = _json(body)["nav_rows"]
    assert [r["cbd"] for r in rows] == [471, 472, 473, 483]
    assert rows[0]["thk"] is None and rows[0]["srf"] is None     # 9999 -> unavailable
    _no_paths(body, env)


def test_asset_listing_is_owner_scoped(env):
    _a, cookies_a = _login(env, "a@example.org")
    _b, cookies_b = _login(env, "b@example.org")
    _upload(env, cookies_a, tiff=tiff_bytes())
    _s, _h, body_a = _one(_app(env), "GET", f"{API}/assets", cookies=cookies_a)
    _s, _h, body_b = _one(_app(env), "GET", f"{API}/assets", cookies=cookies_b)
    assert len(_json(body_a)["assets"]) == 1
    assert _json(body_b)["assets"] == []


def test_view_returns_the_requested_window(env):
    _user, cookies = _login(env, "a@example.org")
    _s, _h, body = _upload(env, cookies, tiff=tiff_bytes())
    asset_id = _json(body)["asset_id"]
    status, headers, png = _one(_app(env), "GET",
                                f"{API}/assets/{asset_id}/view?x=10&width=101&scale=4",
                                cookies=cookies)
    assert status == 200 and headers["Content-Type"] == "image/png"
    assert "private" in headers["Cache-Control"]
    assert Image.open(io.BytesIO(png)).size == (26, 10)      # ceil(101/4), ceil(40/4)


@pytest.mark.parametrize("query", [
    "x=0&width=301&scale=1", "x=-1&width=10&scale=1", "x=0&width=10&scale=3",
    "x=0&width=10", "x=a&width=10&scale=1", "x=0&width=0&scale=1",
])
def test_invalid_view_requests_are_rejected(env, query):
    _user, cookies = _login(env, "a@example.org")
    _s, _h, body = _upload(env, cookies, tiff=tiff_bytes())
    asset_id = _json(body)["asset_id"]
    status, _h, _b = _one(_app(env), "GET", f"{API}/assets/{asset_id}/view?{query}",
                          cookies=cookies)
    assert status == 400


def test_shared_asset_view_reads_the_shared_file(env):
    _user, cookies = _login(env, "a@example.org")
    _s, _h, body = _one(_app(env), "POST", f"{API}/assets/shared", cookies=cookies,
                        json={"source": "f127-c0471-c0483"})
    asset_id = _json(body)["asset_id"]
    status, _h, png = _one(_app(env), "GET",
                           f"{API}/assets/{asset_id}/view?x=0&width=300&scale=1",
                           cookies=cookies)
    assert status == 200
    assert np.asarray(Image.open(io.BytesIO(png))).shape == (40, 300)


# ── isolation and path safety ────────────────────────────────────────
def test_other_users_assets_are_not_found(env):
    _a, cookies_a = _login(env, "a@example.org")
    _b, cookies_b = _login(env, "b@example.org")
    _s, _h, body = _upload(env, cookies_a, tiff=tiff_bytes())
    asset_id = _json(body)["asset_id"]
    for path in (f"{API}/assets/{asset_id}",
                 f"{API}/assets/{asset_id}/view?x=0&width=10&scale=1"):
        status, _h, body = _one(_app(env), "GET", path, cookies=cookies_b)
        assert status == 404 and _json(body)["error"] == "Radar asset not found."


@pytest.mark.parametrize("asset_id", [
    "0" * 32, "f" * 32,
])
def test_nonexistent_asset_is_not_found(env, asset_id):
    _user, cookies = _login(env, "a@example.org")
    status, _h, _b = _one(_app(env), "GET", f"{API}/assets/{asset_id}", cookies=cookies)
    assert status == 404


@pytest.mark.parametrize("asset_id", [
    "..", "..%2F..%2Fetc", "A" * 32, "0" * 31, "0" * 33, "x" * 32,
    "%2e%2e%2f" + "0" * 23,
])
def test_malformed_asset_ids_never_reach_the_workspace(env, asset_id):
    _user, cookies = _login(env, "a@example.org")
    for suffix in ("", "/view?x=0&width=1&scale=1"):
        status, _h, _b = _one(_app(env), "GET", f"{API}/assets/{asset_id}{suffix}",
                              cookies=cookies)
        assert status == 404


def test_symlinked_source_tiff_into_another_workspace_is_refused(env):
    user_a, cookies_a = _login(env, "a@example.org")
    _b, cookies_b = _login(env, "b@example.org")
    _s, _h, body_b = _upload(env, cookies_b, tiff=tiff_bytes())
    _s, _h, body_a = _upload(env, cookies_a, tiff=tiff_bytes(radar_array(50, 5)))
    b_tiff = next(_radar_root(env, _b).glob("*/source.tiff"))
    a_dir = _radar_root(env, user_a) / _json(body_a)["asset_id"]
    (a_dir / "source.tiff").unlink()
    (a_dir / "source.tiff").symlink_to(b_tiff)
    status, _h, _b2 = _one(_app(env), "GET",
                           f"{API}/assets/{a_dir.name}/view?x=0&width=50&scale=1",
                           cookies=cookies_a)
    assert status == 404


def test_tampered_manifest_cannot_point_at_other_paths(env):
    user, cookies = _login(env, "a@example.org")
    _s, _h, body = _upload(env, cookies, tiff=tiff_bytes())
    directory = _radar_root(env, user) / _json(body)["asset_id"]
    manifest = json.loads((directory / "asset.json").read_text())
    manifest.update(origin="shared", shared_source="../../etc/passwd")
    (directory / "asset.json").write_text(json.dumps(manifest))
    status, _h, _b = _one(_app(env), "GET",
                          f"{API}/assets/{directory.name}/view?x=0&width=10&scale=1",
                          cookies=cookies)
    assert status == 409            # unknown shared key: no path is ever derived from it
