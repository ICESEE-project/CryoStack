"""Publication integrity and backup/recovery.

A published result must not change silently: not when its owner edits or
resets the session afterwards, the source radar is changed and re-indexed,
the source is unavailable, a newer version supersedes it, it is withdrawn, or
the server restarts. A damaged or missing snapshot must block a decision
instead of publishing something else. Backups must cover the catalog and the
snapshot files together and must detect damage before a restore.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[3]
for _p in (str(_REPO), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from frozen_legacies_radar_fixtures import write_tiff
from test_frozen_legacies_catalog import (  # noqa: F401  (fixtures)
    API, _login, _run, _setup_source, _strip, archive, web_env)
from test_frozen_legacies_review import _decide, _done, _open, _submit
from icesee_jupyter_book.applications.frozen_legacies.radar import backup as backup_mod
from icesee_jupyter_book.applications.frozen_legacies.radar import catalog as catalog_mod
from icesee_jupyter_book.applications.frozen_legacies.radar import review as review_mod
from icesee_jupyter_book.applications.frozen_legacies.radar.indexer import index_source
from icesee_jupyter_book.applications.frozen_legacies.radar.storage import LocalProvider


@pytest.fixture(autouse=True)
def review_root(tmp_path, monkeypatch):
    monkeypatch.setenv(review_mod.REVIEW_ROOT_ENV, str(tmp_path / "var" / "reviews"))
    return tmp_path / "var" / "reviews"


def _users(env):
    _m, maint = _login(env, "maint@example.org", "maintainer")
    _a, a = _login(env, "a@example.org")
    _r, reviewer = _login(env, "reviewer@example.org", "admin")
    return maint, a, reviewer


def _remove(directory: Path) -> None:
    """Delete a snapshot tree (its files are read-only by design)."""
    import shutil

    for path in directory.rglob("*"):
        path.chmod(0o750 if path.is_dir() else 0o640)
    shutil.rmtree(directory)


async def _published(client, ck):
    published = await (await client.get(f"{API}/published/observations", cookies=ck)).json()
    return sorted(published["features"], key=lambda f: f["id"])


async def _publish_one(client, app, maint, a, reviewer, *, setup=True, n=2):
    if setup:
        await _setup_source(client, app, maint)
    key, aid = await _open(client, a)
    await _done(client, a, aid, n)
    status, sub = await _submit(client, a, aid)
    assert status == 201, sub
    status, decided = await _decide(client, reviewer, sub["submission_id"], "approve",
                                    accept_unverified_geolocation=True)
    assert status == 200 and decided["status"] == "published", decided
    return key, aid, sub["submission_id"]


async def _products(client, ck, sid):
    out = {}
    for kind in ("astra-csv", "astra-qc", "provenance"):
        resp = await client.get(f"{API}/published/{sid}/products/{kind}", cookies=ck)
        out[kind] = (resp.status, await resp.read())
    return out


def test_published_results_do_not_change_after_edits_reindex_outage_or_restart(web_env):
    maint, a, reviewer = _users(web_env)
    state = {}

    async def publish(client, app):
        key, aid, sid = await _publish_one(client, app, maint, a, reviewer)
        state.update(key=key, aid=aid, sid=sid)
        return await _published(client, a), await _products(client, a, sid)

    before, products = _run(web_env, publish)
    assert len(before) == 2 and products["astra-csv"][0] == 200

    async def edit(client, app):
        aid = state["aid"]
        # the owner resets and re-picks after publication
        await client.post(f"{API}/assets/{aid}/manual", cookies=a,
                          json={"action": "reset", "confirm": True})
        await _done(client, a, aid, 3)
        mine = await (await client.get(f"{API}/assets/{aid}/products/astra-csv",
                                       cookies=a)).read()
        return await _published(client, a), await _products(client, a, state["sid"]), mine

    after_edit, products_edit, own_csv = _run(web_env, edit)
    assert after_edit == before and products_edit == products
    assert own_csv != products["astra-csv"][1]                   # the user's work moved on

    # the source file changes and is re-indexed; then the source disappears
    archive = web_env["archive"]
    target = archive / "tiff" / "F127" / "F127-C0471_C0483.tiff"
    write_tiff(target, _strip(width=2700))
    catalog = catalog_mod.open_catalog()
    source = catalog.get_source("archive")
    assert index_source(catalog, source, LocalProvider(archive))["counts"]["changed"] == 1
    archive.rename(archive.with_name("archive-offline"))

    async def offline(client, app):
        return await _published(client, a), await _products(client, a, state["sid"])

    after_outage, products_outage = _run(web_env, offline)
    assert after_outage == before and products_outage == products

    # a fresh database connection, as after a server restart
    catalog_mod._shared.clear()
    after_restart, products_restart = _run(web_env, offline)
    assert after_restart == before and products_restart == products
    provenance = json.loads(products["provenance"][1])
    assert provenance["radar_asset"]["catalog_id"] == state["key"]
    assert provenance["observations"]["geolocation"]["counts"]["unverified"] == 2


def test_supersession_and_withdrawal_keep_history(web_env):
    maint, a, reviewer = _users(web_env)

    async def script(client, app):
        _key, aid, first = await _publish_one(client, app, maint, a, reviewer)
        v1 = await _published(client, a)
        await client.post(f"{API}/assets/{aid}/manual", cookies=a,
                          json={"action": "reset", "confirm": True})
        await _done(client, a, aid, 3)
        status, sub = await _submit(client, a, aid, note="corrected")
        assert status == 201
        pending = await (await client.get(f"{API}/admin/reviews/{sub['submission_id']}",
                                          cookies=reviewer)).json()
        assert pending["supersedes_on_approval"]["submission_id"] == first
        assert pending["supersedes_on_approval"]["observation_count"] == 2
        await _decide(client, reviewer, sub["submission_id"], "approve",
                      accept_unverified_geolocation=True)
        v2 = await _published(client, a)
        old = await (await client.get(f"{API}/admin/reviews/{first}", cookies=reviewer)).json()
        old_product = (await client.get(f"{API}/published/{first}/products/astra-csv",
                                        cookies=a)).status
        resp = await client.post(f"{API}/admin/reviews/{sub['submission_id']}/withdraw",
                                 cookies=reviewer, json={"reason": "navigation re-processed"})
        withdrawn = await resp.json()
        empty = await _published(client, a)
        again = (await client.post(f"{API}/admin/reviews/{sub['submission_id']}/withdraw",
                                   cookies=reviewer, json={"reason": "twice"})).status
        return v1, v2, old, old_product, withdrawn, empty, again, first, sub["submission_id"]

    v1, v2, old, old_product, withdrawn, empty, again, first, second = _run(web_env, script)
    assert len(v1) == 2 and len(v2) == 3
    assert {f["properties"]["submission_id"] for f in v2} == {second}
    assert old["submission"]["status"] == "superseded"
    assert old["submission"]["superseded_by"] == second
    assert old["integrity"]["ok"] is True and len(old["observations"]) == 2   # history kept
    assert old_product == 404                                   # no longer the published version
    assert withdrawn["status"] == "withdrawn" and withdrawn["withdraw_reason"]
    assert empty == [] and again == 409


def test_damaged_or_missing_snapshots_block_decisions(web_env, review_root):
    maint, a, reviewer = _users(web_env)

    async def script(client, app):
        await _setup_source(client, app, maint)
        _key, aid = await _open(client, a)
        await _done(client, a, aid, 2)
        status, sub = await _submit(client, a, aid)
        sid = sub["submission_id"]
        snapshot = review_root / sid
        csv = next(snapshot.glob("*.csv"))
        csv.chmod(0o640)
        csv.write_bytes(csv.read_bytes() + b"tampered\n")
        out = {"tampered": await _decide(client, reviewer, sid, "approve",
                                         accept_unverified_geolocation=True)}
        out["detail"] = await (await client.get(f"{API}/admin/reviews/{sid}",
                                                cookies=reviewer)).json()
        (snapshot / "observations.json").chmod(0o640)
        (snapshot / "observations.json").unlink()
        out["missing"] = await _decide(client, reviewer, sid, "approve",
                                       accept_unverified_geolocation=True)
        out["detail_missing"] = await client.get(f"{API}/admin/reviews/{sid}", cookies=reviewer)
        out["detail_missing"] = (out["detail_missing"].status,
                                 await out["detail_missing"].json())
        out["published"] = await _published(client, a)
        out["queue"] = await (await client.get(f"{API}/admin/reviews?status=submitted",
                                               cookies=reviewer)).json()
        return out

    out = _run(web_env, script)
    status, body = out["tampered"]
    assert status == 409 and "damaged" in body["error"]
    assert out["detail"]["integrity"]["ok"] is False
    assert any("does not match" in p for p in out["detail"]["integrity"]["problems"])
    assert out["missing"][0] == 409
    status, detail = out["detail_missing"]
    assert status == 200 and detail["observations"] == [] and not detail["integrity"]["ok"]
    assert out["published"] == []                               # nothing was published
    assert out["queue"]["total"] == 1                           # still awaiting review


def test_backup_restores_catalog_and_snapshots_together(web_env, review_root, tmp_path):
    maint, a, reviewer = _users(web_env)

    async def publish(client, app):
        _key, _aid, sid = await _publish_one(client, app, maint, a, reviewer)
        return await _published(client, a), await _products(client, a, sid), sid

    before, products, sid = _run(web_env, publish)
    catalog_file = catalog_mod.catalog_path()
    target, manifest = backup_mod.create(tmp_path / "backups")
    assert manifest["problems"] == [] and manifest["submissions"] == 1
    assert manifest["counts"]["published_observations"] == 2
    assert backup_mod.verify(target)["ok"] is True
    assert oct(os.stat(target / backup_mod.CATALOG_NAME).st_mode)[-3:] == "640"
    assert oct(os.stat(target / "MANIFEST.json").st_mode)[-3:] == "640"
    assert not list(target.glob("*-wal")) and not list(target.glob("*-shm"))   # one file

    # disaster: the catalog and the review store are lost
    catalog_mod._shared.clear()
    for path in (catalog_file, Path(f"{catalog_file}-wal"), Path(f"{catalog_file}-shm")):
        path.unlink(missing_ok=True)
    _remove(review_root)
    result = backup_mod.restore(target)
    assert result["ok"] is True and result["moved_aside"] == []

    async def check(client, app):
        return await _published(client, a), await _products(client, a, sid)

    after, products_after = _run(web_env, check)
    assert after == before and products_after == products

    # a restore never overwrites silently, and refuses a damaged backup
    with pytest.raises(SystemExit, match="--force"):
        backup_mod.restore(target)
    copied = next((target / backup_mod.REVIEWS_NAME / sid).glob("*.csv"))
    copied.chmod(0o640)
    copied.write_bytes(b"damaged")
    check_result = backup_mod.verify(target)
    assert check_result["ok"] is False
    with pytest.raises(SystemExit, match="does not verify"):
        backup_mod.restore(target, force=True)


def test_backup_reports_snapshots_missing_on_the_server(web_env, review_root, tmp_path):
    maint, a, reviewer = _users(web_env)

    async def submit(client, app):
        await _setup_source(client, app, maint)
        _key, aid = await _open(client, a)
        await _done(client, a, aid, 2)
        return (await _submit(client, a, aid))[1]["submission_id"]

    sid = _run(web_env, submit)
    _remove(review_root / sid)
    target, manifest = backup_mod.create(tmp_path / "backups")
    assert manifest["problems"] == [f"snapshot {sid} is missing on the server"]
    assert backup_mod.main(["verify", str(target)]) == 1


def test_automatic_results_cannot_enter_review(web_env):
    """A completed URSA job is not a reviewed or reviewable result."""
    from test_frozen_legacies_catalog import _asset_dir
    from icesee_jupyter_book.applications.frozen_legacies.radar import automatic

    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    user, a = _login(web_env, "a@example.org")
    _r, reviewer = _login(web_env, "reviewer@example.org", "admin")

    async def script(client, app):
        await _setup_source(client, app, maint)
        _key, aid = await _open(client, a)
        job = {"schema": automatic.JOB_SCHEMA, "version": automatic.JOB_VERSION,
               "asset_id": aid, "job_id": "ursa-test", "picker": "ursa", "status": "completed",
               "created_at": 1.0, "started_at": 1.0, "finished_at": 2.0, "message": "done",
               "log_tail": [], "summary": {}, "warnings": []}
        (_asset_dir(web_env, user, aid) / "automatic.json").write_text(json.dumps(job))
        state = await (await client.get(f"{API}/assets/{aid}/review", cookies=a)).json()
        status, body = await _submit(client, a, aid)
        queue = await (await client.get(f"{API}/admin/reviews", cookies=reviewer)).json()
        return state, status, body, queue

    state, status, body, queue = _run(web_env, script)
    assert state["can_submit"] is False and "manual" in state["reason"].lower()
    assert status == 409 and "manual" in body["error"].lower()
    assert queue["total"] == 0
