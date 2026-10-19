"""Persistent data sources and workspace storage.

Quotas (accounting, enforcement before uploads and generated results,
reservations for concurrent writes, over-quota users keep their files,
per-user overrides, settings that survive restarts, audit records), data-source
management (visibility, safe removal that never touches storage, discovered
files for maintainers, CEDAR over a mounted network filesystem, planned
providers refused), the asset selector's server-side search, and permission
boundaries between users, maintainers and administrators.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import sys
import types
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[3]
for _p in (str(_REPO), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_frozen_legacies_catalog import (  # noqa: E402  (shared fixtures)
    API, _asset_dir, _index, _json, _login, _setup_source, _strip, archive, web_env)
from frozen_legacies_radar_fixtures import tiff_bytes  # noqa: E402
from cryostack_src.workspace import WorkspaceUser, owner_root  # noqa: E402
from icesee_jupyter_book.applications.frozen_legacies import server, storage_routes  # noqa: E402
from icesee_jupyter_book.applications.frozen_legacies.radar import quota as Q  # noqa: E402
from icesee_jupyter_book.applications.frozen_legacies.radar import storage  # noqa: E402
from icesee_jupyter_book.applications.frozen_legacies.radar.catalog import (  # noqa: E402
    RadarCatalog, asset_key)

_APP = _HERE.parent
TIFF = tiff_bytes(_strip())          # a real, small radar TIFF


@pytest.fixture
def env(web_env, tmp_path, monkeypatch):
    monkeypatch.setenv(Q.STORAGE_DB_ENV, str(tmp_path / "var" / "storage.db"))
    return web_env


def _app(env):
    from aiohttp import web

    app = web.Application()
    env["auth"].install(app)
    app[server.WORKSPACE_ROOT_KEY] = str(env["workspace"])
    server.install_frozen_legacies(app, auth=env["auth"])
    app["_root"] = env["archive"]
    return app


def run(env, script, app=None):
    from aiohttp.test_utils import TestClient, TestServer

    app = app or _app(env)

    async def go():
        async with TestClient(TestServer(app)) as client:
            return await script(client, app)

    return asyncio.run(go())


def _tiff_form(data=TIFF, name="F127-C0471_C0483.tiff"):
    from aiohttp import FormData

    form = FormData()
    form.add_field("tiff", io.BytesIO(data), filename=name)
    return form


async def _upload(client, ck, data=TIFF, name="F127-C0471_C0483.tiff"):
    return await _json(await client.post(f"{API}/assets/upload", data=_tiff_form(data, name),
                                         cookies=ck))


def _root(env, user) -> Path:
    return owner_root(WorkspaceUser(user_id=user.id, source="cryostack-auth"),
                      workspace_root=env["workspace"])


def _audit(env, action_prefix):
    with env["auth"].storage._connect() as db:
        return [dict(zip(("action", "previous_value", "new_value", "target_user_id", "reason"), r))
                for r in db.execute(
                    "SELECT action, previous_value, new_value, target_user_id, reason"
                    " FROM access_audit_log WHERE action LIKE ? ORDER BY created_at",
                    (action_prefix + "%",))]


# ── accounting ───────────────────────────────────────────────────────
def test_default_quota_is_two_gib():
    assert Q.DEFAULT_QUOTA_BYTES == 2_147_483_648
    assert Q.QuotaStore.__init__ and Q.SETTINGS["default_quota_bytes"][0] == 2_147_483_648


def test_usage_counts_each_physical_file_once_and_skips_links_partials_and_caches(tmp_path):
    root = tmp_path / "users" / "u"
    (root / "frozen_legacies" / "radar" / "a" / "outputs").mkdir(parents=True)
    asset = root / "frozen_legacies" / "radar" / "a"
    (asset / "source.tiff").write_bytes(b"x" * 1000)
    os.link(asset / "source.tiff", asset / "outputs" / "same.tiff")       # hard link: once
    (asset / "outputs" / "picks.csv").write_bytes(b"y" * 100)
    (asset / "upload.tiff.part").write_bytes(b"z" * 5000)                  # in progress
    shared = tmp_path / "shared.tiff"
    shared.write_bytes(b"s" * 9000)
    (asset / "shared.tiff").symlink_to(shared)                              # referenced only
    (asset / ".automatic-work").mkdir()
    (asset / ".automatic-work" / "tmp.bin").write_bytes(b"w" * 7000)       # transient
    (root / ".cache").mkdir()
    (root / ".cache" / "c").write_bytes(b"c" * 3000)
    (root / "examples").mkdir()
    (root / "examples" / "model.py").write_bytes(b"m" * 10)                 # other apps count
    assert Q.measure(root) == {"bytes": 1110, "files": 3}


def test_settings_and_overrides_are_validated_and_persist(tmp_path):
    path = tmp_path / "s.db"
    store = Q.QuotaStore(path)
    assert store.settings()["default_quota_bytes"] == Q.DEFAULT_QUOTA_BYTES
    assert store.set_setting("default_quota_bytes", 3 * Q.GIB) == (Q.DEFAULT_QUOTA_BYTES, 3 * Q.GIB)
    for name, value in (("default_quota_bytes", -1), ("max_upload_bytes", 500 * Q.MIB),
                        ("warn_percent", 0), ("default_quota_bytes", True),
                        ("default_quota_bytes", "2GiB"), ("bogus", 1)):
        with pytest.raises(Q.QuotaError):
            store.set_setting(name, value)
    store.set_override("user-1", 5 * Q.GIB)
    restarted = Q.QuotaStore(path)                       # a new process reads the same
    assert restarted.quota_for("user-1") == (5 * Q.GIB, True)
    assert restarted.quota_for("user-2") == (3 * Q.GIB, False)
    assert restarted.set_override("user-1", None) == (5 * Q.GIB, None)
    assert restarted.quota_for("user-1") == (3 * Q.GIB, False)


def test_reservations_make_concurrent_writes_fit_together(tmp_path):
    accounts = Q.QuotaAccounts(Q.QuotaStore(tmp_path / "s.db"))
    accounts.store.set_override("u", 1000)
    root = tmp_path / "root"
    root.mkdir()
    usage = accounts.usage(root, "u")
    first = accounts.reserve(usage, root, 600, what="this upload")
    with pytest.raises(Q.QuotaExceeded, match="only 400 B"):
        accounts.reserve(accounts.usage(root, "u"), root, 600, what="this upload")
    accounts.release(root, first)
    assert accounts.reserve(accounts.usage(root, "u"), root, 600, what="this upload") == 600


def test_local_free_space_reserve_blocks_writes_before_disk_fills(tmp_path, monkeypatch):
    accounts = Q.QuotaAccounts(Q.QuotaStore(tmp_path / "s.db"))
    accounts.store.set_override("u", 20 * Q.GIB)
    accounts.store.set_setting("disk_reserve_bytes", 5 * Q.GIB)
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(Q, "disk_status", lambda _path: {
        "total_bytes": 100 * Q.GIB, "used_bytes": 95 * Q.GIB,
        "free_bytes": 5 * Q.GIB + 100, "percent": 95.0})
    with pytest.raises(Q.QuotaExceeded, match="safe free-space reserve"):
        accounts.reserve(accounts.usage(root, "u"), root, 101, what="this upload")


# ── enforcement through the API ──────────────────────────────────────
def test_usage_api_and_immediate_upload_visibility(env):
    user, ck = _login(env, "a@example.org")

    async def script(client, app):
        _s, before = await _json(await client.get(f"{API}/storage/usage", cookies=ck))
        status, asset = await _upload(client, ck)
        assert status == 201, asset
        _s, listed = await _json(await client.get(f"{API}/assets", cookies=ck))
        _s, after = await _json(await client.get(f"{API}/storage/usage", cookies=ck))
        return before, asset, listed, after

    before, asset, listed, after = run(env, script)
    assert before["quota_bytes"] == 2_147_483_648 and before["used_bytes"] == 0
    assert before["status"] == "ok" and before["max_upload_bytes"] == Q.HARD_MAX_UPLOAD_BYTES
    # the upload is in the selector's list at once, and counted
    assert asset["asset_id"] in [a["asset_id"] for a in listed["assets"]]
    assert after["used_bytes"] >= len(TIFF)
    # original file name is preserved for the pickers
    assert next(a for a in listed["assets"] if a["asset_id"] == asset["asset_id"])["filename"] \
        == "F127-C0471_C0483.tiff"


def test_upload_beyond_the_remaining_allowance_is_refused_before_reading(env):
    user, ck = _login(env, "a@example.org")
    Q.QuotaStore().set_override(user.id, len(TIFF) // 2)

    async def script(client, app):
        return await _upload(client, ck)

    status, body = run(env, script)
    assert status == 413 and "storage quota is available" in body["error"]
    assert body["quota"]["quota_bytes"] == len(TIFF) // 2
    radar = _root(env, user) / "frozen_legacies" / "radar"
    # no asset (complete or partial) was created
    assert not radar.exists() or not any(radar.iterdir())


def test_over_quota_users_keep_their_files_but_cannot_add_more(env):
    user, ck = _login(env, "a@example.org")
    admin, ack = _login(env, "admin@example.org", "admin")

    async def script(client, app):
        status, asset = await _upload(client, ck)
        assert status == 201
        aid = asset["asset_id"]
        # an administrator lowers the quota below the current usage
        status, body = await _json(await client.post(
            f"{API}/admin/storage/users/{user.id}", cookies=ack,
            json={"quota_bytes": 1024, "reason": "test"}))
        assert status == 200 and body["status"] == "over"
        out = {}
        out["upload"] = await _upload(client, ck)
        out["manual"] = await _json(await client.post(
            f"{API}/assets/{aid}/manual", cookies=ck, json={"action": "reset"}))
        out["automatic_start"] = await _json(await client.post(
            f"{API}/assets/{aid}/automatic", cookies=ck, json={"action": "start"}))
        # cancelling is never blocked (the handler answers: nothing is running)
        out["automatic_cancel"] = await _json(await client.post(
            f"{API}/assets/{aid}/automatic", cookies=ck, json={"action": "cancel"}))
        # reading and downloading stay available
        out["read"] = (await client.get(f"{API}/assets/{aid}", cookies=ck)).status
        out["products"] = (await client.get(f"{API}/assets/{aid}/products", cookies=ck)).status
        # removing data is always possible, and frees the quota again
        out["delete"] = (await client.delete(f"{API}/assets/{aid}", cookies=ck)).status
        await client.post(f"{API}/admin/storage/users/{user.id}", cookies=ack,
                          json={"quota_bytes": 10 * len(TIFF)})
        out["after_delete"] = await _upload(client, ck)
        return out

    out = run(env, script)
    for key in ("upload", "manual", "automatic_start"):
        assert out[key][0] == 413, (key, out[key])
        assert "Your existing files remain available" in out[key][1]["error"]
    assert out["automatic_cancel"][0] == 409
    assert out["read"] == 200 and out["products"] == 200 and out["delete"] == 200
    assert out["after_delete"][0] == 201


def test_an_upload_in_flight_reserves_its_size(env):
    user, ck = _login(env, "a@example.org")
    Q.QuotaStore().set_override(user.id, int(len(TIFF) * 1.5))

    async def script(client, app):
        accounts = app[storage_routes.ACCOUNTS_KEY]
        root = _root(env, user)
        # another upload of the same size is still streaming
        held = accounts.reserve(accounts.usage(root, user.id), root, len(TIFF), what="x")
        blocked = await _upload(client, ck)
        accounts.release(root, held)
        allowed = await _upload(client, ck)
        return blocked, allowed

    blocked, allowed = run(env, script)
    assert blocked[0] == 413 and allowed[0] == 201


def test_parallel_uploads_never_overshoot_the_quota(env):
    user, ck = _login(env, "a@example.org")
    Q.QuotaStore().set_override(user.id, int(len(TIFF) * 1.5))

    async def script(client, app):
        return await asyncio.gather(*(_upload(client, ck) for _ in range(4)))

    results = run(env, script)
    codes = sorted(status for status, _body in results)
    assert codes.count(201) <= 1 and set(codes) <= {201, 413}
    assert Q.measure(_root(env, user))["bytes"] <= int(len(TIFF) * 1.5)


def test_uploads_must_declare_their_size(env):
    _user, ck = _login(env, "a@example.org")

    async def chunks():
        yield TIFF[:1000]

    async def script(client, app):
        return await _json(await client.post(f"{API}/assets/upload", data=chunks(), cookies=ck,
                                             headers={"Content-Type": "multipart/form-data; boundary=x"}))

    status, body = run(env, script)
    assert status == 411


def test_maximum_upload_size_setting(env):
    user, ck = _login(env, "a@example.org")
    Q.QuotaStore().set_setting("max_upload_bytes", Q.MIB)

    # a file just over the limit (TIFF signature, then padding): the handler
    # stops reading at the limit, and no partial asset remains
    big = TIFF[:8] + b"\0" * (Q.MIB + 100 * 1024)

    async def script(client, app):
        _s, usage = await _json(await client.get(f"{API}/storage/usage", cookies=ck))
        return usage, await _upload(client, ck, data=big)

    usage, (status, body) = run(env, script)
    assert usage["max_upload_bytes"] == Q.MIB
    assert status == 413 and "1 MB limit" in body["error"]
    radar = _root(env, user) / "frozen_legacies" / "radar"
    assert not radar.exists() or not any(radar.iterdir())


def test_other_users_files_never_count(env):
    a, ck_a = _login(env, "a@example.org")
    b, ck_b = _login(env, "b@example.org")

    async def script(client, app):
        await _upload(client, ck_a)
        _s, usage_b = await _json(await client.get(f"{API}/storage/usage", cookies=ck_b))
        return usage_b

    assert run(env, script)["used_bytes"] == 0


# ── administrator settings ───────────────────────────────────────────
def test_storage_administration_is_admin_only_and_audited(env):
    user, ck = _login(env, "a@example.org")
    _m, mck = _login(env, "m@example.org", "maintainer")
    _ad, ack = _login(env, "admin@example.org", "admin")

    async def script(client, app):
        out = {"anon": (await client.get(f"{API}/admin/storage")).status,
               "user": (await client.get(f"{API}/admin/storage", cookies=ck)).status,
               "maintainer": (await client.get(f"{API}/admin/storage", cookies=mck)).status,
               "page_user": (await client.get("/control/frozen-legacies/storage", cookies=ck,
                                              allow_redirects=False)).status,
               "legacy_admin": (await client.get("/control/frozen-legacies/storage", cookies=ack,
                                                  allow_redirects=False)).status,
               "page_admin": (await client.get("/control/storage", cookies=ack)).status}
        out["bad"] = await _json(await client.post(f"{API}/admin/storage/settings", cookies=ack,
                                                  json={"default_quota_bytes": -5}))
        out["unknown"] = await _json(await client.post(f"{API}/admin/storage/settings", cookies=ack,
                                                      json={"anything": 1}))
        out["set"] = await _json(await client.post(f"{API}/admin/storage/settings", cookies=ack, json={
            "default_quota_bytes": 3 * Q.GIB, "warn_percent": 75, "reason": "more room"}))
        out["override"] = await _json(await client.post(
            f"{API}/admin/storage/users/{user.id}", cookies=ack,
            json={"quota_bytes": 5 * Q.GIB, "reason": "large flight"}))
        out["missing_user"] = (await client.post(f"{API}/admin/storage/users/nobody", cookies=ack,
                                                 json={"quota_bytes": 1})).status
        out["overview"] = await _json(await client.get(f"{API}/admin/storage", cookies=ack))
        out["user_usage"] = await _json(await client.get(f"{API}/storage/usage", cookies=ck))
        return out

    out = run(env, script)
    assert out["anon"] == 401 and out["user"] == 403 and out["maintainer"] == 403
    assert out["page_user"] in (302, 303, 403) and out["page_admin"] == 200
    assert out["legacy_admin"] in (301, 308)
    assert out["bad"][0] == 400 and out["unknown"][0] == 400
    assert out["set"][0] == 200 and out["set"][1]["settings"]["default_quota_bytes"] == 3 * Q.GIB
    assert out["set"][1]["impact"] == {"default_changed": True,
                                          "users_using_default": 3,
                                          "users_with_overrides": 0}
    assert out["override"][0] == 200 and out["override"][1]["quota_bytes"] == 5 * Q.GIB
    assert out["missing_user"] == 404
    overview = out["overview"][1]
    row = next(u for u in overview["users"] if u["user_id"] == user.id)
    assert row["override"] is True and row["quota_bytes"] == 5 * Q.GIB
    assert {"workspace_bytes", "cache_bytes", "disk"} <= set(overview["totals"])
    assert out["user_usage"][1]["quota_bytes"] == 5 * Q.GIB
    # no paths in the overview
    text = json.dumps(overview)
    assert str(env["tmp"]) not in text and str(env["workspace"]) not in text
    records = _audit(env, "cryostack.storage.")
    actions = [r["action"] for r in records]
    assert "cryostack.storage.default_quota_bytes" in actions
    assert "cryostack.storage.warn_percent" in actions
    quota = next(r for r in records if r["action"] == "cryostack.storage.user_quota")
    assert quota["previous_value"] == "default" and quota["new_value"] == str(5 * Q.GIB)
    assert quota["target_user_id"] == user.id and quota["reason"] == "large flight"


def test_global_storage_groups_all_apps_and_bulk_delete_is_owner_scoped(env):
    user, ck = _login(env, "a@example.org")
    other, other_ck = _login(env, "b@example.org")
    root = _root(env, user)
    other_root = _root(env, other)
    (root / "datasets").mkdir(parents=True)
    (root / "datasets" / "science.nc").write_bytes(b"science")
    (root / "livist" / "jobs" / "one").mkdir(parents=True)
    (root / "livist" / "jobs" / "one" / "result.bin").write_bytes(b"result")
    (other_root / "datasets").mkdir(parents=True)
    (other_root / "datasets" / "private.nc").write_bytes(b"private")

    async def script(client, app):
        before = await _json(await client.get("/api/storage?refresh=1", cookies=ck))
        bad = await _json(await client.post("/api/storage/delete", cookies=ck, json={
            "scopes": ["datasets"], "confirmation": "wrong"}))
        deleted = await _json(await client.post("/api/storage/delete", cookies=ck, json={
            "scopes": ["datasets", "livist"], "confirmation": "DELETE MY FILES"}))
        after = await _json(await client.get("/api/storage?refresh=1", cookies=ck))
        other_after = await _json(await client.get("/api/storage?refresh=1", cookies=other_ck))
        page = await client.get("/storage/", cookies=ck)
        return before, bad, deleted, after, other_after, page.status, await page.text()

    before, bad, deleted, after, other_after, page_status, page = run(env, script)
    assert before[0] == 200 and {s["id"] for s in before[1]["scopes"]} >= {"datasets", "livist"}
    assert bad[0] == 400
    assert deleted[0] == 200 and deleted[1]["deleted_files"] == 2
    assert {s["id"] for s in after[1]["scopes"]}.isdisjoint({"datasets", "livist"})
    assert other_after[1]["used_bytes"] == len(b"private")
    assert (other_root / "datasets" / "private.nc").read_bytes() == b"private"
    assert page_status == 200 and "One allowance covers" in page and "Select all" in page


def test_quota_settings_survive_a_restart(env):
    user, ck = _login(env, "a@example.org")
    _ad, ack = _login(env, "admin@example.org", "admin")

    async def configure(client, app):
        await client.post(f"{API}/admin/storage/users/{user.id}", cookies=ack,
                          json={"quota_bytes": 7 * Q.GIB})
        status, asset = await _upload(client, ck)
        return asset["asset_id"]

    aid = run(env, configure)

    async def after_restart(client, app):              # a new application instance
        _s, usage = await _json(await client.get(f"{API}/storage/usage", cookies=ck))
        _s, listed = await _json(await client.get(f"{API}/assets", cookies=ck))
        return usage, listed

    usage, listed = run(env, after_restart)
    assert usage["quota_bytes"] == 7 * Q.GIB and usage["used_bytes"] >= len(TIFF)
    assert aid in [a["asset_id"] for a in listed["assets"]]


def test_quota_database_uses_shared_storage_layout_when_available(monkeypatch, tmp_path):
    monkeypatch.delenv(Q.STORAGE_DB_ENV, raising=False)
    expected = tmp_path / "db" / "frozen_legacies_storage.db"
    layout = types.ModuleType("cryostack_src.storage_layout")
    layout.default_path = lambda name, legacy: expected if (
        name == "frozen-legacies-storage" and legacy == Q.DEFAULT_STORAGE_DB
    ) else legacy
    monkeypatch.setitem(sys.modules, "cryostack_src.storage_layout", layout)

    assert Q.storage_db_path() == expected


# ── data sources ─────────────────────────────────────────────────────
def test_maintainers_only_sources_are_hidden_from_users(env):
    _u, ck = _login(env, "a@example.org")
    _m, mck = _login(env, "m@example.org", "maintainer")

    async def script(client, app):
        await _setup_source(client, app, mck)
        out = {}
        _s, out["user_sources"] = await _json(await client.get(f"{API}/radar/catalog/sources", cookies=ck))
        _s, out["user_search"] = await _json(await client.get(f"{API}/radar/catalog", cookies=ck))
        some = out["user_search"]["items"][0]["catalog_id"]
        status, out["restrict"] = await _json(await client.post(
            f"{API}/admin/sources/archive/visibility", cookies=mck, json={"visibility": "maintainers"}))
        assert status == 200 and out["restrict"]["visibility"] == "maintainers"
        _s, out["user_sources_after"] = await _json(await client.get(f"{API}/radar/catalog/sources", cookies=ck))
        _s, out["user_search_after"] = await _json(await client.get(f"{API}/radar/catalog", cookies=ck))
        _s, out["maint_search_after"] = await _json(await client.get(f"{API}/radar/catalog", cookies=mck))
        out["user_open"] = (await client.post(f"{API}/assets/shared", cookies=ck,
                                              json={"source": some})).status
        out["maint_open"] = (await client.post(f"{API}/assets/shared", cookies=mck,
                                               json={"source": some})).status
        out["bad_visibility"] = (await client.post(f"{API}/admin/sources/archive/visibility",
                                                   cookies=mck, json={"visibility": "public"})).status
        out["user_set"] = (await client.post(f"{API}/admin/sources/archive/visibility", cookies=ck,
                                             json={"visibility": "users"})).status
        return out

    out = run(env, script)
    assert [s["source_id"] for s in out["user_sources"]["sources"]] == ["archive"]
    assert out["user_search"]["total"] == 4
    assert out["user_sources_after"]["sources"] == []
    assert out["user_search_after"]["total"] == 0
    assert out["maint_search_after"]["total"] == 4
    assert out["user_open"] == 404 and out["maint_open"] == 201
    assert out["bad_visibility"] == 400 and out["user_set"] == 403
    actions = [r["action"] for r in _audit(env, "frozen_legacies.source.")]
    assert actions[:2] == ["frozen_legacies.source.add", "frozen_legacies.source.visibility"]


def test_gui_curator_intake_stays_unpublished_and_uses_managed_volume(
        env, tmp_path, monkeypatch):
    from aiohttp import FormData
    from icesee_jupyter_book.applications.frozen_legacies.radar.curator_intake import (
        INTAKE_ROOT_ENV,
    )

    approved = tmp_path / "approved"
    intake = approved / "intakes"
    intake.mkdir(parents=True)
    monkeypatch.setenv(storage.STORAGE_ROOTS_ENV, str(approved))
    monkeypatch.setenv(INTAKE_ROOT_ENV, str(intake))
    _maintainer, cookies = _login(env, "curator@example.org", "maintainer")

    async def script(client, app):
        form = FormData()
        form.add_field("source_id", "gui-intake-127")
        form.add_field("name", "GUI intake 127")
        form.add_field("dataset_id", "frozen-legacies-ascope")
        form.add_field("nav_template", "nav/{flight}.csv")
        form.add_field("files", io.BytesIO(TIFF),
                       filename="F127-C0471_C0483.tiff", content_type="image/tiff")
        status, created = await _json(await client.post(
            f"{API}/admin/intakes", cookies=cookies, data=form))
        blocked, message = await _json(await client.post(
            f"{API}/admin/sources/gui-intake-127/visibility", cookies=cookies,
            json={"visibility": "users"}))
        _status, listing = await _json(await client.get(
            f"{API}/admin/sources", cookies=cookies))
        return status, created, blocked, message, listing

    status, created, blocked, message, listing = run(env, script)
    assert status == 201 and created["receipt"]["publication_status"] == "unpublished"
    assert blocked == 409 and "unpublished" in message["error"].lower()
    source = next(s for s in listing["sources"] if s["source_id"] == "gui-intake-127")
    assert source["managed_intake"] and source["publication_status"] == "unpublished"
    assert source["visibility"] == "maintainers"
    # The durable ``.upload-sessions`` store is expected; only ephemeral
    # multipart request directories must be gone after the request.
    assert not [path for path in intake.glob(".upload-*")
                if path.name != ".upload-sessions"]
    assert (intake / "gui-intake-127" / "intake-receipt.json").is_file()


def test_resumable_curator_intake_is_authorized_verified_and_finalized(
        env, tmp_path, monkeypatch):
    from icesee_jupyter_book.applications.frozen_legacies.radar.curator_intake import (
        INTAKE_ROOT_ENV,
    )

    approved, intake = tmp_path / "approved", tmp_path / "approved" / "intakes"
    intake.mkdir(parents=True)
    monkeypatch.setenv(storage.STORAGE_ROOTS_ENV, str(approved))
    monkeypatch.setenv(INTAKE_ROOT_ENV, str(intake))
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_INTAKE_FREE_RESERVE_BYTES", "0")
    _maintainer, cookies = _login(env, "resumable@example.org", "maintainer")
    _other, other_cookies = _login(env, "other-curator@example.org", "maintainer")
    _user, user_cookies = _login(env, "ordinary@example.org")
    digest = hashlib.sha256(TIFF).hexdigest()

    async def script(client, app):
        payload = {"source_id": "resumable-127", "name": "Resumable 127",
                   "dataset_id": "frozen-legacies-ascope",
                   # Browser streams bounded chunks; the server computes and
                   # records the whole-file digest before staging.
                   "files": [{"name": "F127-C0471_C0483.tiff", "bytes": len(TIFF)}]}
        denied = (await client.post(f"{API}/admin/intake-sessions", cookies=user_cookies,
                                    json=payload)).status
        created_status, created = await _json(await client.post(
            f"{API}/admin/intake-sessions", cookies=cookies, json=payload))
        sid = created["session_id"]
        hidden = (await client.get(f"{API}/admin/intake-sessions/{sid}",
                                   cookies=other_cookies)).status
        headers = {"X-Chunk-SHA256": digest, "Content-Type": "application/octet-stream"}
        first_status, first = await _json(await client.put(
            f"{API}/admin/intake-sessions/{sid}/files/0/chunks/0",
            cookies=cookies, data=TIFF, headers=headers))
        again_status, again = await _json(await client.put(
            f"{API}/admin/intake-sessions/{sid}/files/0/chunks/0",
            cookies=cookies, data=TIFF, headers=headers))
        final_status, final = await _json(await client.post(
            f"{API}/admin/intake-sessions/{sid}/finalize", cookies=cookies))
        return denied, created_status, hidden, first_status, first, again_status, again, final_status, final

    denied, created, hidden, first_s, first, again_s, again, finalized, result = run(env, script)
    assert denied == 403 and created == 201 and hidden == 409
    assert first_s == again_s == 200 and not first["idempotent"] and again["idempotent"]
    assert finalized == 201 and result["session"]["state"] == "finalized"
    assert result["source"]["visibility"] == "maintainers"
    assert result["receipt"]["publication_status"] == "unpublished"


def test_removing_a_registration_never_touches_the_storage(env):
    _m, mck = _login(env, "m@example.org", "maintainer")
    user, ck = _login(env, "a@example.org")
    before = sorted(p.relative_to(env["archive"]).as_posix() for p in env["archive"].rglob("*"))
    sizes = {p: p.stat().st_size for p in env["archive"].rglob("*") if p.is_file()}

    async def script(client, app):
        await _setup_source(client, app, mck)
        _s, found = await _json(await client.get(f"{API}/radar/catalog", cookies=ck))
        ids = sorted(i["catalog_id"] for i in found["items"])
        status, asset = await _json(await client.post(f"{API}/assets/shared", cookies=ck,
                                                      json={"source": ids[0]}))
        assert status == 201
        out = {"ids": ids, "asset": asset["asset_id"]}
        out["unconfirmed"] = (await client.delete(f"{API}/admin/sources/archive", cookies=mck,
                                                  json={"confirm": "other"})).status
        out["user"] = (await client.delete(f"{API}/admin/sources/archive", cookies=ck,
                                           json={"confirm": "archive"})).status
        status, out["removed"] = await _json(await client.delete(
            f"{API}/admin/sources/archive", cookies=mck, json={"confirm": "archive", "reason": "t"}))
        assert status == 200
        _s, out["sources"] = await _json(await client.get(f"{API}/admin/sources", cookies=mck))
        _s, out["search"] = await _json(await client.get(f"{API}/radar/catalog", cookies=ck))
        _s, out["assets"] = await _json(await client.get(f"{API}/assets", cookies=ck))
        # registering the same source again restores every catalog ID
        await _setup_source(client, app, mck)
        _s, again = await _json(await client.get(f"{API}/radar/catalog", cookies=ck))
        out["ids_again"] = sorted(i["catalog_id"] for i in again["items"])
        return out

    out = run(env, script)
    assert out["unconfirmed"] == 400 and out["user"] == 403
    assert out["removed"]["removed"] is True and out["removed"]["storage_untouched"] is True
    assert out["removed"]["catalog_rows"] == 5
    assert out["sources"]["sources"] == [] and out["search"]["total"] == 0
    # the user's reference stays in the workspace (shown as unavailable)
    assert out["asset"] in [a["asset_id"] for a in out["assets"]["assets"]]
    assert out["ids_again"] == out["ids"]
    after = sorted(p.relative_to(env["archive"]).as_posix() for p in env["archive"].rglob("*"))
    assert after == before
    assert all(p.stat().st_size == size for p, size in sizes.items())
    assert any(r["action"] == "frozen_legacies.source.remove"
               for r in _audit(env, "frozen_legacies.source."))


def test_removal_waits_for_indexing(tmp_path):
    catalog = RadarCatalog(tmp_path / "c.db")
    catalog.add_source(source_id="src", name="S", provider="local", dataset_id="d",
                       config={"root": str(tmp_path)})
    catalog.queue_run("src")
    from icesee_jupyter_book.applications.frozen_legacies.radar.catalog import CatalogError
    with pytest.raises(CatalogError, match="Cancel the indexing run"):
        catalog.remove_source("src")


def test_maintainers_see_discovered_files_with_status_and_cache(env):
    _u, ck = _login(env, "a@example.org")
    _m, mck = _login(env, "m@example.org", "maintainer")

    async def script(client, app):
        await _setup_source(client, app, mck)
        out = {}
        _s, out["all"] = await _json(await client.get(
            f"{API}/admin/sources/archive/files?page_size=2", cookies=mck))
        _s, out["invalid"] = await _json(await client.get(
            f"{API}/admin/sources/archive/files?status=invalid", cookies=mck))
        _s, out["q"] = await _json(await client.get(
            f"{API}/admin/sources/archive/files?q=C0484", cookies=mck))
        out["user"] = (await client.get(f"{API}/admin/sources/archive/files", cookies=ck)).status
        out["bad"] = (await client.get(f"{API}/admin/sources/archive/files?status=x", cookies=mck)).status
        out["missing"] = (await client.get(f"{API}/admin/sources/nothere/files", cookies=mck)).status
        return out

    out = run(env, script)
    assert out["all"]["total"] == 5 and len(out["all"]["items"]) == 2 and out["all"]["pages"] == 3
    item = out["all"]["items"][0]
    assert item["cache"] == "in place" and "/" in item["key"] and not item["key"].startswith("/")
    assert [i["filename"] for i in out["invalid"]["items"]] == ["broken.tiff"]
    assert out["invalid"]["items"][0]["error"]
    assert [i["filename"] for i in out["q"]["items"]] == ["F127-C0484_C0496.tiff"]
    assert out["user"] == 403 and out["bad"] == 400 and out["missing"] == 404


def test_reindexing_never_duplicates_catalog_entries(env):
    _m, mck = _login(env, "m@example.org", "maintainer")

    async def script(client, app):
        await _setup_source(client, app, mck)
        await _index(client, app, mck)
        await _index(client, app, mck, full=True)
        _s, files = await _json(await client.get(f"{API}/admin/sources/archive/files", cookies=mck))
        return files

    files = run(env, script)
    keys = [f["key"] for f in files["items"]]
    assert files["total"] == 5 and len(keys) == len(set(keys))


def test_selector_search_by_source_and_name_is_paginated(env):
    _u, ck = _login(env, "a@example.org")
    _m, mck = _login(env, "m@example.org", "maintainer")

    async def script(client, app):
        await _setup_source(client, app, mck)
        out = {}
        _s, out["page"] = await _json(await client.get(
            f"{API}/radar/catalog?source=archive&page_size=2", cookies=ck))
        _s, out["named"] = await _json(await client.get(
            f"{API}/radar/catalog?source=archive&q=F125", cookies=ck))
        _s, out["other"] = await _json(await client.get(f"{API}/radar/catalog?source=nothere", cookies=ck))
        out["bad"] = (await client.get(f"{API}/radar/catalog?source=..%2Fx", cookies=ck)).status
        return out

    out = run(env, script)
    assert out["page"]["total"] == 4 and len(out["page"]["items"]) == 2 and out["page"]["pages"] == 2
    assert [i["filename"] for i in out["named"]["items"]] == ["F125-C0100_C0110.tiff"]
    item = out["named"]["items"][0]
    assert {"catalog_id", "bytes", "dataset_id", "source_id"} <= set(item)
    assert "storage_key" not in item and "key" not in item
    assert out["other"]["total"] == 0 and out["bad"] == 400


def test_an_external_file_opened_from_the_selector_keeps_its_name_and_is_picked_in_place(env):
    user, ck = _login(env, "a@example.org")
    _m, mck = _login(env, "m@example.org", "maintainer")

    async def script(client, app):
        await _setup_source(client, app, mck)
        _s, found = await _json(await client.get(f"{API}/radar/catalog?q=C0471", cookies=ck))
        status, asset = await _json(await client.post(
            f"{API}/assets/shared", cookies=ck, json={"source": found["items"][0]["catalog_id"]}))
        _s, manual = await _json(await client.get(f"{API}/assets/{asset['asset_id']}/manual", cookies=ck))
        _s, usage = await _json(await client.get(f"{API}/storage/usage", cookies=ck))
        return status, asset, manual, usage

    status, asset, manual, usage = run(env, script)
    assert status == 201 and asset["filename"] == "F127-C0471_C0483.tiff"
    assert asset["flight"] == "127"
    assert manual is not None
    # the external radar is not copied into the workspace and does not count
    assert usage["used_bytes"] < 100_000
    tiffs = list(_root(env, user).rglob("*.tiff"))
    assert tiffs == [] or all(p.is_symlink() for p in tiffs)


# ── providers ────────────────────────────────────────────────────────
def test_cedar_requires_a_mounted_network_filesystem(tmp_path, monkeypatch):
    root = tmp_path / "cedar"
    (root / "tiff").mkdir(parents=True)
    (root / "tiff" / "F127-C0471_C0483.tiff").write_bytes(TIFF)
    monkeypatch.setattr(storage, "mount_of", lambda path: {"mountpoint": tmp_path, "fstype": "xfs"})
    provider = storage.CedarProvider(root, roots=[tmp_path])
    assert provider.check()["ok"] is False
    with pytest.raises(storage.StorageError, match="not on a mounted network filesystem"):
        list(provider.list("tiff"))
    monkeypatch.setattr(storage, "mount_of", lambda path: {"mountpoint": tmp_path, "fstype": "nfs4"})
    check = provider.check()
    assert check["ok"] is True and "nfs4" in check["message"]
    assert [o.key for o in provider.list("tiff", suffixes=(".tiff",))] == ["tiff/F127-C0471_C0483.tiff"]
    # approved roots still apply
    with pytest.raises(storage.StorageKeyError):
        storage.CedarProvider(root, roots=[tmp_path / "elsewhere"])


def _cedar_accessible():
    try:
        root = Path("/projects/cos-lab-nuiaq")
        return (root.is_dir()
                and storage.mount_of(root)["fstype"] in storage.NETWORK_FSTYPES)
    except (OSError, PermissionError):  # absent mount or expired Kerberos ticket
        return False


@pytest.mark.skipif(not _cedar_accessible(),
                    reason="CEDAR is not a mounted network filesystem or access expired")
def test_the_real_cedar_mount_is_recognized():
    mount = storage.mount_of(Path("/projects/cos-lab-nuiaq"))
    assert mount["fstype"] in storage.NETWORK_FSTYPES
    provider = storage.CedarProvider("/projects/cos-lab-nuiaq", roots=["/projects/cos-lab-nuiaq"])
    assert provider.check()["ok"] is True


def test_cloud_provider_readiness_is_reported_without_secrets(env):
    _m, mck = _login(env, "m@example.org", "maintainer")
    for name in storage.CLOUD_PROVIDERS:
        with pytest.raises(storage.StorageKeyError):
            storage.provider_for(name, {})

    async def script(client, app):
        _s, listing = await _json(await client.get(f"{API}/admin/sources", cookies=mck))
        status, body = await _json(await client.post(f"{API}/admin/sources", cookies=mck, json={
            "source_id": "drive", "name": "Drive", "dataset_id": "d", "provider": "dropbox"}))
        return listing, status, body

    listing, status, body = run(env, script)
    assert {"cedar", "gdrive", "onedrive", "dropbox"} <= set(listing["providers"])
    assert {p["provider"] for p in listing["cloud"]} == {"gdrive", "onedrive", "dropbox"}
    assert all("missing" in p and "credentials" in p for p in listing["cloud"])
    assert listing["planned"] == []
    assert status == 400


def test_sources_never_accept_credentials_or_unapproved_locations(env, tmp_path):
    _m, mck = _login(env, "m@example.org", "maintainer")

    async def script(client, app):
        out = []
        for payload in (
            {"provider": "s3", "bucket": "b", "aws_secret_access_key": "x"},
            {"provider": "local", "root": "/etc"},
            {"provider": "cedar", "root": "/etc"},
            {"provider": "local", "root": str(app["_root"]) + "/../../../etc"},
            {"provider": "https", "url": "http://169.254.169.254/latest/meta-data"},
        ):
            out.append((await client.post(f"{API}/admin/sources", cookies=mck, json={
                "source_id": "x1", "name": "X", "dataset_id": "d", **payload})).status)
        return out

    assert run(env, script) == [400, 400, 400, 400, 400]


# ── frontend contracts ───────────────────────────────────────────────
_RADAR_JS = (_APP / "assets" / "radar.js").read_text(encoding="utf-8")
_STORAGE_JS = (_APP / "assets" / "storage.js").read_text(encoding="utf-8")
_INDEX = (_APP / "index.html").read_text(encoding="utf-8")


def test_selector_groups_external_datasets_and_my_workspace():
    assert '<optgroup label="External datasets">' in _RADAR_JS
    assert '<optgroup label="My workspace">' in _RADAR_JS
    # server-side search a page at a time; never the whole catalog
    assert 'api(`/radar/catalog?${params}`)' in _RADAR_JS and 'page_size: "50"' in _RADAR_JS
    assert 'value="more:external"' in _RADAR_JS
    assert "a newer search superseded this one" in _RADAR_JS
    for element in ('id="fl-radar-asset-search"', 'id="fl-radar-asset-source"',
                    'id="fl-radar-asset-status"', 'id="fl-storage-usage"'):
        assert element in _INDEX
    # opening still goes through the authorized shared-asset path
    assert 'value="source:${escapeHtml(item.catalog_id)}"' in _RADAR_JS


def test_uploads_are_checked_against_the_remaining_storage_first():
    assert 'document.addEventListener("submit", checkUpload, true)' in _STORAGE_JS
    assert "event.stopImmediatePropagation()" in _STORAGE_JS
    assert "Storage: ${formatBytes(usage.used_bytes)} / ${formatBytes(usage.quota_bytes)}" in _STORAGE_JS
    assert _INDEX.index("assets/storage.js") < _INDEX.index("assets/radar.js")
