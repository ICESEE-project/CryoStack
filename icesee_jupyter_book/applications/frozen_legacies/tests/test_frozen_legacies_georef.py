"""CBD provenance and georeferencing (radar/georef.py, georef_routes.py).

The film-frame CBD of an A-scope is confirmed by the user; nothing is
inferred. Covers nonsequential and missing labels, navigation association
(ASTRA's exact-CBD lookup), stale confirmations after re-picking or a reset,
validation, the separate reproducible georeferenced product and its
provenance, the publication check, owner isolation, and that ASTRA's CSV and
the user's observations are never changed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[3]
for _p in (str(_REPO), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_frozen_legacies_catalog import (  # noqa: F401  (fixtures)
    API, NAV, _json, _login, _setup_source, archive, web_env)
from frozen_legacies_radar_fixtures import requires_astra
from cryostack_src.workspace import WorkspaceUser
from icesee_jupyter_book.applications.frozen_legacies import georef_routes, server
from icesee_jupyter_book.applications.frozen_legacies.radar import georef
from icesee_jupyter_book.applications.frozen_legacies.workspace import FrozenLegaciesWorkspace


def _nav_position(cbd):
    lat = -81.4 - (cbd - 465) * 0.01
    lon = -169.8 + (cbd - 465) * 0.03
    return [round(lon, 6), round(lat, 6)]


# ── model (no HTTP) ──────────────────────────────────────────────────
@pytest.fixture
def asset(tmp_path):
    """A workspace asset with a manual session and three ASTRA observations."""
    ws = FrozenLegaciesWorkspace(WorkspaceUser(user_id="u1", source="cryostack-auth"),
                                 workspace_root=tmp_path)
    asset_id, directory = ws.create_asset()
    (directory / "session.json").write_text(json.dumps({"created_at": 100.0, "revision": 3}))
    nav = tmp_path / "127.csv"
    nav.write_text(NAV)
    records = [{"a_scope": n, "window_x": 1000 * n, "cbd": cbd, "flight": "127",
                "position": _nav_position(cbd), "h_ice_m": 2000.0 + n}
               for n, cbd in ((1, 471), (2, 477), (3, 483))]
    return ws, asset_id, records, nav


@requires_astra
def test_confirmed_film_cbds_are_not_assumed_sequential(asset):
    ws, aid, records, nav = asset
    before = json.dumps(records, sort_keys=True)
    georef.record_label(ws, aid, records, a_scope=1, action="confirm", film_cbd=471)
    georef.record_label(ws, aid, records, a_scope=2, action="confirm", film_cbd=478)
    georef.record_label(ws, aid, records, a_scope=3, action="confirm", film_cbd=484)
    out = georef.annotate_asset(ws, aid, records, nav)
    assert json.dumps(records, sort_keys=True) == before          # inputs untouched
    assert [r["cbd"] for r in out] == [471, 477, 483]             # ASTRA's CBD kept
    assert [r["astra_cbd"] for r in out] == [471, 477, 483]
    assert [r["verified_cbd"] for r in out] == [471, 478, 484]
    assert [r["cbd_differs"] for r in out] == [False, True, True]
    assert {r["geolocation_status"] for r in out} == {"verified"}
    assert {r["georef_method"] for r in out} == {georef.METHOD_VERIFIED}
    for r in out:                                                  # ASTRA's exact-CBD lookup
        assert r["verified_position"] == pytest.approx(_nav_position(r["verified_cbd"]))
        assert r["position"] == r["astra_position"]
    assert georef.publication_check(out)[0] is True


def test_missing_labels_are_never_filled_in(asset):
    ws, aid, records, nav = asset
    georef.record_label(ws, aid, records, a_scope=2, action="unreadable", note="torn frame")
    out = georef.annotate_asset(ws, aid, records, nav)
    statuses = [r["geolocation_status"] for r in out]
    assert statuses == ["unverified", "label_unreadable", "unverified"]
    assert all(r["verified_cbd"] is None and r["verified_position"] is None for r in out)
    assert [r["cbd_source"] for r in out] == ["astra_row_order"] * 3
    ok, reason = georef.publication_check(out)
    assert ok is False and "3 of 3" in reason
    assert georef.publication_check([])[0] is False


@requires_astra
def test_navigation_association_is_exact(asset, tmp_path):
    ws, aid, records, nav = asset
    georef.record_label(ws, aid, records, a_scope=1, action="confirm", film_cbd=900)
    out = georef.annotate_asset(ws, aid, records, nav)
    assert out[0]["geolocation_status"] == "verified_no_navigation"   # no record for 900
    assert out[0]["verified_position"] is None
    assert any("outside the file name's range" in w
               for w in georef.warnings_for(out, {"cbd_start": 471, "cbd_end": 483}))
    no_nav = georef.annotate_asset(ws, aid, records, None)
    assert no_nav[0]["geolocation_status"] == "verified_no_navigation"
    # the navigation's 9999 marker is not a position
    marked = tmp_path / "marked.csv"
    marked.write_text("CBD,LAT,LON,THK,SRF\n471,9999,9999,9999,9999\n")
    georef.record_label(ws, aid, records, a_scope=1, action="confirm", film_cbd=471)
    assert georef.annotate_asset(ws, aid, records, marked)[0]["verified_position"] is None


def test_confirmations_do_not_survive_repicking_or_a_new_session(asset):
    ws, aid, records, nav = asset
    georef.record_label(ws, aid, records, a_scope=1, action="confirm", film_cbd=471)
    repicked = [dict(records[0], window_x=55)] + records[1:]
    assert georef.annotate_asset(ws, aid, repicked, nav)[0]["geolocation_status"] == "unverified"
    (ws.asset_dir(aid) / "session.json").write_text(json.dumps({"created_at": 200.0}))
    assert georef.annotate_asset(ws, aid, records, nav)[0]["geolocation_status"] == "unverified"
    georef.record_label(ws, aid, records, a_scope=2, action="confirm", film_cbd=478)
    assert set(georef.load(ws, aid)["entries"]) == {"2"}            # old session dropped


@pytest.mark.parametrize("value", [True, -1, 100000, "478", 478.0, None])
def test_invalid_film_cbds_are_refused(asset, value):
    ws, aid, records, _nav = asset
    with pytest.raises(georef.GeorefError):
        georef.record_label(ws, aid, records, a_scope=1, action="confirm", film_cbd=value)


def test_unknown_actions_and_uncommitted_ascopes_are_refused(asset):
    ws, aid, records, _nav = asset
    for kwargs in ({"a_scope": 9, "action": "confirm", "film_cbd": 471},
                   {"a_scope": "1", "action": "confirm", "film_cbd": 471},
                   {"a_scope": 1, "action": "guess"}):
        with pytest.raises(georef.GeorefError):
            georef.record_label(ws, aid, records, **kwargs)
    (ws.asset_dir(aid) / "georef.json").symlink_to(ws.root / "elsewhere.json")
    with pytest.raises(PermissionError):
        georef.record_label(ws, aid, records, a_scope=1, action="confirm", film_cbd=471)


@requires_astra
def test_nonmonotonic_labels_are_flagged_not_corrected(asset):
    ws, aid, records, nav = asset
    for n, cbd in ((1, 480), (2, 471), (3, 482)):
        georef.record_label(ws, aid, records, a_scope=n, action="confirm", film_cbd=cbd)
    out = georef.annotate_asset(ws, aid, records, nav)
    assert [r["verified_cbd"] for r in out] == [480, 471, 482]
    assert any("monotonically" in w for w in georef.warnings_for(out, {}))


@requires_astra
def test_georeferenced_product_is_separate_and_reproducible(asset):
    ws, aid, records, nav = asset
    georef.record_label(ws, aid, records, a_scope=2, action="confirm", film_cbd=478)
    doc = {"observations": records, "session_revision": 3}
    manifest = {"filename": "F127-C0471_C0483.tiff", "dataset_id": "d", "flight": "127",
                "shared_source": "cat-0123456789abcdef01234567"}
    first = georef.snapshot_files(ws, aid, manifest, nav, doc)
    second = georef.snapshot_files(ws, aid, manifest, nav, doc)
    name = "F127-C0471_C0483_georef.csv"
    assert set(first) == {"georef.json", name, "georef_provenance.json"}
    assert first == second                                          # deterministic
    lines = first[name].decode().splitlines()
    assert lines[0].split(",") == list(georef.CSV_COLUMNS)
    row = dict(zip(georef.CSV_COLUMNS, lines[2].split(",")))
    assert (row["astra_cbd"], row["verified_cbd"], row["geolocation_status"]) == (
        "477", "478", "verified")
    assert float(row["verified_lat"]) == pytest.approx(_nav_position(478)[1])
    prov = json.loads(first["georef_provenance.json"])
    assert prov["sha256"] == hashlib.sha256(first[name]).hexdigest()
    assert prov["navigation_sha256"] == hashlib.sha256(nav.read_bytes()).hexdigest()
    assert prov["catalog_id"] == manifest["shared_source"]
    assert "u1" not in json.dumps(prov)                             # no personal data


# ── HTTP ─────────────────────────────────────────────────────────────
def _run(env, script):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    app = web.Application()
    env["auth"].install(app)
    app[server.WORKSPACE_ROOT_KEY] = str(env["workspace"])
    server.install_frozen_legacies(app, auth=env["auth"])
    try:                                  # installed by catalog_routes when present
        georef_routes.install_georef_routes(app, auth=env["auth"])
    except RuntimeError:
        pass
    app["_root"] = env["archive"]

    async def go():
        async with TestClient(TestServer(app)) as client:
            return await script(client, app)

    return asyncio.run(go())


async def _commit(client, ck, aid, n):
    base = f"{API}/assets/{aid}/manual"
    r = await (await client.get(base, cookies=ck)).json()
    rev = r["revision"]
    for _ in range(n):
        r = await (await client.post(base, cookies=ck, json={"revision": rev,
                                                            "action": "suggest"})).json()
        r = await (await client.post(base, cookies=ck, json={"revision": r["revision"],
                                                            "action": "next"})).json()
        r = await (await client.post(base, cookies=ck, json={"revision": r["revision"],
                                                            "action": "step",
                                                            "step": "jump"})).json()
        rev = r["revision"]
    return rev


@requires_astra
def test_georeferencing_api_keeps_astra_outputs_and_is_owner_scoped(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    _a, a = _login(web_env, "a@example.org")
    _b, b = _login(web_env, "b@example.org")

    async def script(client, app):
        await _setup_source(client, app, maint)
        listing = await (await client.get(f"{API}/radar/catalog?flight=127&cbd=471",
                                          cookies=a)).json()
        key = listing["items"][0]["catalog_id"]
        aid = (await (await client.post(f"{API}/assets/shared", cookies=a,
                                        json={"source": key})).json())["asset_id"]
        out = {}
        out["early"] = (await client.post(f"{API}/assets/{aid}/georef", cookies=a,
                                          json={"action": "confirm", "a_scope": 1,
                                                "film_cbd": 471})).status
        rev = await _commit(client, a, aid, 3)
        await client.post(f"{API}/assets/{aid}/manual", cookies=a,
                          json={"revision": rev, "action": "done"})
        csv_url = f"{API}/assets/{aid}/products/astra-csv"
        out["csv_before"] = await (await client.get(csv_url, cookies=a)).read()
        out["obs_before"] = await (await client.get(f"{API}/observations", cookies=a)).json()
        status, out["initial"] = await _json(await client.get(f"{API}/assets/{aid}/georef",
                                                              cookies=a))
        for body in ({"action": "confirm", "a_scope": 1, "film_cbd": 471},
                     {"action": "confirm", "a_scope": 2, "film_cbd": 478},
                     {"action": "unreadable", "a_scope": 3}):
            status, state = await _json(await client.post(f"{API}/assets/{aid}/georef",
                                                          cookies=a, json=body))
            assert status == 200, state
        out["state"] = state
        out["bad"] = (await client.post(f"{API}/assets/{aid}/georef", cookies=a,
                                        json={"action": "confirm", "a_scope": 1,
                                              "film_cbd": "x"})).status
        out["csv_after"] = await (await client.get(csv_url, cookies=a)).read()
        out["obs_after"] = await (await client.get(f"{API}/observations", cookies=a)).json()
        product = await client.get(f"{API}/assets/{aid}/georef/product", cookies=a)
        out["product"] = (product.status, product.headers.get("Content-Disposition"),
                          await product.read())
        out["product_again"] = await (await client.get(f"{API}/assets/{aid}/georef/product",
                                                       cookies=a)).read()
        out["provenance"] = await (await client.get(f"{API}/assets/{aid}/georef/provenance",
                                                    cookies=a)).json()
        # isolation
        out["b_get"] = (await client.get(f"{API}/assets/{aid}/georef", cookies=b)).status
        out["b_post"] = (await client.post(f"{API}/assets/{aid}/georef", cookies=b,
                                           json={"action": "clear", "a_scope": 1})).status
        out["b_product"] = (await client.get(f"{API}/assets/{aid}/georef/product",
                                             cookies=b)).status
        out["anon"] = (await client.get(f"{API}/assets/{aid}/georef")).status
        out["cross"] = (await client.post(f"{API}/assets/{aid}/georef", cookies=a,
                                          headers={"Origin": "https://evil.example"},
                                          json={"action": "clear", "a_scope": 1})).status
        # a reset session does not inherit confirmations
        await client.post(f"{API}/assets/{aid}/manual", cookies=a,
                          json={"action": "reset", "confirm": True})
        await _commit(client, a, aid, 1)
        out["after_reset"] = (await client.get(f"{API}/assets/{aid}/georef",
                                               cookies=a)).status, \
            await (await client.get(f"{API}/assets/{aid}/georef", cookies=a)).json()
        return out

    out = _run(web_env, script)
    assert out["early"] == 409
    initial = out["initial"]
    assert [o["geolocation_status"] for o in initial["observations"]] == ["unverified"] * 3
    assert initial["publication"]["ok"] is False and initial["has_navigation"] is True
    obs = out["state"]["observations"]
    assert [o["astra_cbd"] for o in obs] == [471, 477, 483]        # ASTRA's row-order CBDs
    assert [o["verified_cbd"] for o in obs] == [471, 478, None]
    assert [o["geolocation_status"] for o in obs] == ["verified", "verified", "label_unreadable"]
    assert obs[1]["verified_position"] == pytest.approx(_nav_position(478))
    assert obs[1]["astra_position"] == pytest.approx(_nav_position(477))
    assert out["state"]["summary"]["cbd_differs"] == 1
    assert out["bad"] == 400
    # canonical outputs and the user's observations are unchanged
    assert out["csv_after"] == out["csv_before"] and out["csv_before"]
    strip = lambda d: [{k: v for k, v in f["properties"].items()
                        if k not in georef_keys} for f in d["features"]]
    georef_keys = {"astra_cbd", "astra_position", "film_cbd", "film_cbd_source", "verified_cbd",
                   "verified_position", "cbd_source", "georef_method", "geolocation_status",
                   "cbd_differs", "geolocation_acceptance"}
    # the unreadable A-scope keeps its record but has no map position any more
    # (its frame's position is unknown); the others are unchanged ASTRA records
    after_ids = {f["id"] for f in out["obs_after"]["features"]}
    assert len(out["obs_before"]["features"]) == 3 and len(after_ids) == 2
    kept = {"features": [f for f in out["obs_before"]["features"] if f["id"] in after_ids]}
    assert strip(out["obs_after"]) == strip(kept)
    assert (out["obs_after"]["summary"]["without_position"]
            == out["obs_before"]["summary"]["without_position"] + 1)
    status, disposition, body = out["product"]
    assert status == 200 and "F127-C0471_C0483_georef.csv" in disposition
    assert body == out["product_again"]
    prov = out["provenance"]
    assert prov["sha256"] == hashlib.sha256(body).hexdigest()
    assert prov["astra_csv_sha256"] == hashlib.sha256(out["csv_before"]).hexdigest()
    assert (out["b_get"], out["b_post"], out["b_product"]) == (404, 404, 404)
    assert out["anon"] == 401 and out["cross"] == 403
    status, after = out["after_reset"]
    assert status == 200
    assert [o["geolocation_status"] for o in after["observations"]] == ["unverified"]


# ── georeferencing through review and publication ────────────────────
@requires_astra
def test_verified_georeferencing_reaches_the_published_product(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    _r, reviewer = _login(web_env, "reviewer@example.org", "maintainer")
    _a, a = _login(web_env, "a@example.org")
    _b, b = _login(web_env, "b@example.org")

    async def open_done(client, ck, cbd, n):
        listing = await (await client.get(f"{API}/radar/catalog?flight=127&cbd={cbd}",
                                          cookies=ck)).json()
        key = listing["items"][0]["catalog_id"]
        aid = (await (await client.post(f"{API}/assets/shared", cookies=ck,
                                        json={"source": key})).json())["asset_id"]
        rev = await _commit(client, ck, aid, n)
        await client.post(f"{API}/assets/{aid}/manual", cookies=ck,
                          json={"revision": rev, "action": "done"})
        return aid

    async def submit(client, ck, aid):
        status, body = await _json(await client.post(f"{API}/assets/{aid}/review", cookies=ck,
                                                     json={"action": "submit"}))
        assert status == 201, body
        return body.get("submission_id") or body["submission"]["submission_id"]

    async def decide(client, ck, sid, **body):
        return await _json(await client.post(f"{API}/admin/reviews/{sid}/decision",
                                             cookies=ck, json={"decision": "approve", **body}))

    async def script(client, app):
        await _setup_source(client, app, maint)
        out = {}
        verified = await open_done(client, a, 471, 2)
        for n, cbd in ((1, 471), (2, 478)):
            await client.post(f"{API}/assets/{verified}/georef", cookies=a,
                              json={"action": "confirm", "a_scope": n, "film_cbd": cbd})
        out["mine"] = await (await client.get(f"{API}/observations", cookies=a)).json()
        out["other"] = await (await client.get(f"{API}/observations", cookies=b)).json()
        sid = await submit(client, a, verified)
        out["self"] = (await decide(client, a, sid))[0]           # not a reviewer
        out["approve"] = await decide(client, reviewer, sid)
        unverified = await open_done(client, b, 484, 1)
        sid2 = await submit(client, b, unverified)
        out["no_flag"] = await decide(client, reviewer, sid2)
        out["flag"] = await decide(client, reviewer, sid2, accept_unverified_geolocation=True)
        out["published"] = await (await client.get(f"{API}/published/observations",
                                                   cookies=b)).json()
        return out

    out = _run(web_env, script)
    mine = out["mine"]["features"]
    assert [f["properties"].get("geolocation_status") for f in mine] == ["verified", "verified"]
    assert out["other"]["features"] == []
    assert out["self"] == 403
    assert out["approve"][0] == 200, out["approve"]
    assert out["no_flag"][0] == 409 and "unverified" in out["no_flag"][1]["error"]
    assert out["flag"][0] == 200
    published = {f["properties"]["observation_id"]: f for f in out["published"]["features"]}
    verified = [f for f in published.values() if f["properties"]["geolocation_status"] == "verified"]
    assert sorted(f["properties"]["verified_cbd"] for f in verified) == [471, 478]
    for f in verified:                    # the published position is the verified one
        assert f["geometry"]["coordinates"] == pytest.approx(
            _nav_position(f["properties"]["verified_cbd"]))
    flagged = [f for f in published.values() if f["properties"]["geolocation_status"] != "verified"]
    assert len(flagged) == 1 and "geolocation_acceptance" in flagged[0]["properties"]
    raw = json.dumps(out["published"])
    assert "a@example.org" not in raw and "b@example.org" not in raw
