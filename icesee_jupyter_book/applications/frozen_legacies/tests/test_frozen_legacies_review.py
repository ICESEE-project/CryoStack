"""Scientific workflow: resumable manual work, indexed My picks, review and
publication (submit, authorization, approve / return / reject, explicit
acceptance of unverified geolocation, publication as a shared product,
supersession, withdrawal), provenance without personal data, cross-user
isolation, and the canonical ASTRA output left untouched."""
from __future__ import annotations

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
    API, _login, _relogin, _run, _setup_source, archive, web_env)
from icesee_jupyter_book.applications.frozen_legacies.radar import review as review_mod
from icesee_jupyter_book.applications.frozen_legacies.radar import catalog as catalog_mod


@pytest.fixture(autouse=True)
def review_root(tmp_path, monkeypatch):
    monkeypatch.setenv(review_mod.REVIEW_ROOT_ENV, str(tmp_path / "var" / "reviews"))
    return tmp_path / "var" / "reviews"


async def _open(client, ck, flight="127", index=0):
    listing = await (await client.get(f"{API}/radar/catalog?flight={flight}&page_size=10",
                                      cookies=ck)).json()
    key = listing["items"][index]["catalog_id"]
    asset = await (await client.post(f"{API}/assets/shared", cookies=ck,
                                     json={"source": key})).json()
    return key, asset["asset_id"]


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
    return r


async def _done(client, ck, aid, n=2):
    r = await _commit(client, ck, aid, n)
    return await (await client.post(f"{API}/assets/{aid}/manual", cookies=ck,
                                    json={"revision": r["revision"], "action": "done"})).json()


async def _submit(client, ck, aid, note="please review"):
    resp = await client.post(f"{API}/assets/{aid}/review", cookies=ck,
                             json={"action": "submit", "note": note})
    return resp.status, await resp.json()


async def _decide(client, ck, sid, decision, **extra):
    resp = await client.post(f"{API}/admin/reviews/{sid}/decision", cookies=ck,
                             json={"decision": decision, **extra})
    return resp.status, await resp.json()


def test_manual_work_resumes_after_leaving_and_signing_in_again(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    user, a = _login(web_env, "a@example.org")

    async def script(client, app):
        await _setup_source(client, app, maint)
        key, aid = await _open(client, a)
        await _commit(client, a, aid, 2)
        first = await (await client.get(f"{API}/observations", cookies=a)).json()
        # leave, sign in again, find the file in the catalog again
        again = _relogin(web_env, user)
        reopened = await (await client.post(f"{API}/assets/shared", cookies=again,
                                            json={"source": key})).json()
        resumed = await (await client.get(f"{API}/assets/{reopened['asset_id']}/manual",
                                          cookies=again)).json()
        state = await (await client.get(f"{API}/radar/catalog?state=manual_in_progress",
                                        cookies=again)).json()
        await _commit(client, again, aid, 1)
        after = await (await client.get(f"{API}/observations", cookies=again)).json()
        return aid, first, reopened, resumed, state, after

    aid, first, reopened, resumed, state, after = _run(web_env, script)
    assert reopened["asset_id"] == aid                          # the same workspace asset
    assert len(resumed["committed"]["rows"]) == 2 and resumed["status"] != "completed"
    assert state["total"] == 1
    assert len(first["features"]) == 2
    ids = [f["id"] for f in after["features"]]
    assert len(ids) == 3 and len(set(ids)) == 3                  # no duplicates
    assert set(f["id"] for f in first["features"]) <= set(ids)


def test_my_picks_are_served_from_an_owner_scoped_index(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    user_a, a = _login(web_env, "a@example.org")
    _b, b = _login(web_env, "b@example.org")

    async def script(client, app):
        await _setup_source(client, app, maint)
        _key, aid = await _open(client, a)
        await _commit(client, a, aid, 2)
        mine = await (await client.get(f"{API}/observations", cookies=a)).json()
        other = await (await client.get(f"{API}/observations", cookies=b)).json()
        lon, lat = mine["features"][0]["geometry"]["coordinates"]
        box = f"{lon - 0.001},{lat - 0.001},{lon + 0.001},{lat + 0.001}"
        boxed = await (await client.get(f"{API}/observations?bbox={box}", cookies=a)).json()
        await client.delete(f"{API}/assets/{aid}", cookies=a)
        gone = await (await client.get(f"{API}/observations", cookies=a)).json()
        return mine, other, boxed, gone

    mine, other, boxed, gone = _run(web_env, script)
    catalog = catalog_mod.open_catalog()
    assert len(mine["features"]) == 2 and other["features"] == []
    assert mine["features"][0]["id"] in {f["id"] for f in boxed["features"]}
    assert gone["features"] == []
    with catalog._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM user_observations").fetchone()[0] == 0


def test_review_lifecycle_publication_and_withdrawal(web_env, review_root):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    user_a, a = _login(web_env, "a@example.org")
    _b, b = _login(web_env, "b@example.org")
    _r, reviewer = _login(web_env, "reviewer@example.org", "admin")

    async def script(client, app):
        out = {}
        await _setup_source(client, app, maint)
        key, aid = await _open(client, a)
        state = await (await client.get(f"{API}/assets/{aid}/review", cookies=a)).json()
        out["early"] = (state["can_submit"], await _submit(client, a, aid))
        done = await _done(client, a, aid, 2)
        csv_url = done["outputs"]["astra-csv"]["url"]
        out["csv_before"] = await (await client.get(csv_url, cookies=a)).read()
        status, sub = await _submit(client, a, aid)
        out["submitted"] = (status, sub)
        sid = sub["submission_id"]
        out["again"] = (await _submit(client, a, aid))[0]
        out["csv_after"] = await (await client.get(csv_url, cookies=a)).read()
        # isolation and authorization
        out["b_state"] = (await client.get(f"{API}/assets/{aid}/review", cookies=b)).status
        out["b_cancel"] = (await client.post(f"{API}/assets/{aid}/review", cookies=b,
                                             json={"action": "cancel",
                                                   "submission_id": sid})).status
        out["b_queue"] = (await client.get(f"{API}/admin/reviews", cookies=b)).status
        out["a_decide"] = (await _decide(client, a, sid, "approve"))[0]
        out["unpublished_product"] = (await client.get(
            f"{API}/published/{sid}/products/astra-csv", cookies=b)).status
        queue = await (await client.get(f"{API}/admin/reviews?status=submitted",
                                        cookies=reviewer)).json()
        out["queue"] = queue
        detail = await (await client.get(f"{API}/admin/reviews/{sid}", cookies=reviewer)).json()
        out["detail"] = detail
        out["review_csv"] = await (await client.get(
            f"{API}/admin/reviews/{sid}/products/astra-csv", cookies=reviewer)).read()
        out["needs_reason"] = (await _decide(client, reviewer, sid, "reject"))[0]
        out["unverified"] = await _decide(client, reviewer, sid, "approve")
        out["approved"] = await _decide(client, reviewer, sid, "approve",
                                        accept_unverified_geolocation=True)
        out["twice"] = (await _decide(client, reviewer, sid, "approve",
                                      accept_unverified_geolocation=True))[0]
        resp = await client.get(f"{API}/published/observations", cookies=b)
        out["published_text"] = await resp.text()
        out["published"] = json.loads(out["published_text"])
        out["public_csv"] = await (await client.get(f"{API}/published/{sid}/products/astra-csv",
                                                    cookies=b)).read()
        out["provenance"] = await (await client.get(
            f"{API}/published/{sid}/products/provenance", cookies=b)).json()
        out["summary"] = await (await client.get(f"{API}/radar/catalog/summary",
                                                 cookies=a)).json()
        out["state_published"] = await (await client.get(
            f"{API}/radar/catalog?state=published", cookies=a)).json()
        # the user's later edits never change the published snapshot
        await client.post(f"{API}/assets/{aid}/manual", cookies=a,
                          json={"action": "reset", "confirm": True})
        out["after_reset"] = await (await client.get(
            f"{API}/published/{sid}/products/astra-csv", cookies=b)).read()
        out["withdraw_no_reason"] = (await client.post(
            f"{API}/admin/reviews/{sid}/withdraw", cookies=reviewer, json={})).status
        out["withdrawn"] = (await client.post(f"{API}/admin/reviews/{sid}/withdraw",
                                              cookies=reviewer,
                                              json={"reason": "navigation re-processed"})
                            ).status
        out["published_after"] = await (await client.get(f"{API}/published/observations",
                                                         cookies=b)).json()
        out["withdrawn_product"] = (await client.get(
            f"{API}/published/{sid}/products/astra-csv", cookies=b)).status
        out["mine"] = await (await client.get(f"{API}/reviews/mine", cookies=a)).json()
        out["page"] = await (await client.get("/control/frozen-legacies/review",
                                              cookies=reviewer)).text()
        out["page_user"] = (await client.get("/control/frozen-legacies/review", cookies=b,
                                             allow_redirects=False)).status
        out["user_a_id"] = str(user_a.id)
        return out

    out = _run(web_env, script)
    can_submit, (early_status, _early) = out["early"]
    assert can_submit is False and early_status == 409         # only completed results
    status, sub = out["submitted"]
    assert status == 201 and sub["status"] == "submitted" and out["again"] == 409
    assert out["csv_after"] == out["csv_before"]                # canonical output untouched
    assert sub["products"]["astra-csv"]["sha256"] == hashlib.sha256(out["csv_before"]).hexdigest()
    assert (out["b_state"], out["b_cancel"], out["b_queue"], out["a_decide"]) == (
        404, 404, 403, 403)
    assert out["unpublished_product"] == 404
    assert out["queue"]["items"][0]["submission_id"] == sub["submission_id"]
    assert out["review_csv"] == out["csv_before"]
    detail = out["detail"]
    assert len(detail["observations"]) == 2 and detail["geolocation"]["verified"] is False
    assert detail["provenance"]["processing"]["workflow"] == "astra-manual"
    assert out["needs_reason"] == 409
    assert out["unverified"][0] == 409                          # explicit acceptance needed
    status, approved = out["approved"]
    assert status == 200 and approved["status"] == "published"
    assert approved["accepted_unverified"] == 1 and out["twice"] == 409
    features = out["published"]["features"]
    assert len(features) == 2
    props = features[0]["properties"]
    assert props["scope"] == "published" and props["geolocation_status"] != "verified"
    assert "accepted by the reviewer" in props["geolocation_acceptance"]
    assert props["producer"].startswith("ASTRA") and props["catalog_id"].startswith("cat-")
    # no personal data in the shared product or its provenance
    for text in (out["published_text"], json.dumps(out["provenance"])):
        assert "a@example.org" not in text and out["user_a_id"] not in text
        assert "submitter" not in text and "reviewer_user_id" not in text
    assert out["public_csv"] == out["csv_before"]
    provenance = out["provenance"]
    assert provenance["radar_asset"]["catalog_id"] == props["catalog_id"]
    assert provenance["navigation"]["filename"] == "127.csv"
    assert provenance["products"]["astra-csv"]["sha256"] == sub["products"]["astra-csv"]["sha256"]
    flight = next(f for f in out["summary"]["flights"] if f["flight"] == "127")
    assert flight["published"] == 1 and flight["mine"]["published"] == 1
    assert flight["mine"]["needs_review"] == 0
    assert out["state_published"]["total"] == 1
    assert "published" in out["state_published"]["items"][0]["processing"]
    assert out["after_reset"] == out["csv_before"]              # snapshot is immutable
    assert out["withdraw_no_reason"] == 409 and out["withdrawn"] == 200
    assert out["published_after"]["features"] == [] and out["withdrawn_product"] == 404
    mine = out["mine"]["submissions"][0]
    assert mine["status"] == "withdrawn" and mine["withdraw_reason"] == "navigation re-processed"
    assert "submitter" not in mine and "reviewer" not in mine
    assert "Approve and publish" in out["page"] and out["page_user"] == 403
    snapshot = review_root / sub["submission_id"]
    assert sorted(p.name for p in snapshot.iterdir() if p.is_file()) == sorted(
        ["F127-C0471_C0483.csv", "F127-C0471_C0483_QC.png", "SNAPSHOT.json",
         "observations.json", "provenance.json", "session.json"])


def test_reviewers_cannot_decide_their_own_submissions(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    _o, other_reviewer = _login(web_env, "owner@example.org", "owner")

    async def script(client, app):
        await _setup_source(client, app, maint)
        _key, aid = await _open(client, maint)
        await _done(client, maint, aid, 1)
        _status, sub = await _submit(client, maint, aid)
        sid = sub["submission_id"]
        own = await _decide(client, maint, sid, "approve", accept_unverified_geolocation=True)
        listed = await (await client.get(f"{API}/admin/reviews", cookies=maint)).json()
        returned = await _decide(client, other_reviewer, sid, "return",
                                 note="Bed pick at A-scope 1 is on a multiple.")
        state = await (await client.get(f"{API}/assets/{aid}/review", cookies=maint)).json()
        return own, listed, returned, state

    own, listed, returned, state = _run(web_env, script)
    assert own[0] == 403
    assert listed["items"][0]["own"] is True
    assert returned[0] == 200 and returned[1]["status"] == "returned"
    assert state["can_submit"] is True                            # corrected and resubmitted
    assert state["submissions"][0]["decision_note"].startswith("Bed pick")


def test_resubmission_supersedes_and_rejection_is_final(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    _a, a = _login(web_env, "a@example.org")
    _r, reviewer = _login(web_env, "reviewer@example.org", "admin")

    async def script(client, app):
        await _setup_source(client, app, maint)
        _key, aid = await _open(client, a)
        await _done(client, a, aid, 1)
        first = (await _submit(client, a, aid))[1]["submission_id"]
        await _decide(client, reviewer, first, "approve", accept_unverified_geolocation=True)
        same = (await _submit(client, a, aid))[0]                 # unchanged result
        await client.post(f"{API}/assets/{aid}/manual", cookies=a,
                          json={"action": "reset", "confirm": True})
        await _done(client, a, aid, 2)
        second = (await _submit(client, a, aid))[1]["submission_id"]
        await _decide(client, reviewer, second, "approve", accept_unverified_geolocation=True)
        published = await (await client.get(f"{API}/published/observations",
                                             cookies=a)).json()
        listed = await (await client.get(f"{API}/admin/reviews", cookies=reviewer)).json()
        # a further submission rejected; the published one stays
        _key2, aid2 = await _open(client, a, index=1)
        await _done(client, a, aid2, 1)
        third = (await _submit(client, a, aid2))[1]["submission_id"]
        rejected = await _decide(client, reviewer, third, "reject", note="Not an A-scope film.")
        cancel_status = (await client.post(f"{API}/assets/{aid2}/review", cookies=a, json={
            "action": "cancel", "submission_id": third})).status
        return same, published, listed, first, second, rejected, cancel_status

    same, published, listed, first, second, rejected, cancel_status = _run(web_env, script)
    assert same == 409
    statuses = {i["submission_id"]: i for i in listed["items"]}
    assert statuses[first]["status"] == "superseded"
    assert statuses[first]["superseded_by"] == second and statuses[second]["supersedes"] == first
    assert {f["properties"]["submission_id"] for f in published["features"]} == {second}
    assert len(published["features"]) == 2
    assert rejected[1]["status"] == "rejected" and cancel_status == 409


def test_pending_submissions_can_be_cancelled_by_their_owner(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    _a, a = _login(web_env, "a@example.org")

    async def script(client, app):
        await _setup_source(client, app, maint)
        _key, aid = await _open(client, a)
        await _done(client, a, aid, 1)
        sid = (await _submit(client, a, aid))[1]["submission_id"]
        cancelled = await (await client.post(f"{API}/assets/{aid}/review", cookies=a, json={
            "action": "cancel", "submission_id": sid})).json()
        state = await (await client.get(f"{API}/assets/{aid}/review", cookies=a)).json()
        bad = [(await client.post(f"{API}/assets/{aid}/review", cookies=a, json=j)).status
               for j in ({"action": "publish"}, {"action": "cancel", "submission_id": "../x"})]
        foreign = (await client.post(f"{API}/assets/{aid}/review", cookies=a,
                                     headers={"Origin": "https://evil.example"},
                                     json={"action": "submit"})).status
        return cancelled, state, bad, foreign

    cancelled, state, bad, foreign = _run(web_env, script)
    assert cancelled["status"] == "cancelled" and state["can_submit"] is True
    assert bad == [409, 404] and foreign == 403


def test_progress_shows_review_states_and_catalog_lookup_by_id(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    _a, a = _login(web_env, "a@example.org")
    _b, b = _login(web_env, "b@example.org")

    async def script(client, app):
        await _setup_source(client, app, maint)
        key, aid = await _open(client, a)
        await _done(client, a, aid, 1)
        await _submit(client, a, aid)
        waiting = await (await client.get(f"{API}/radar/catalog?state=needs_review",
                                          cookies=a)).json()
        waiting_b = await (await client.get(f"{API}/radar/catalog?state=needs_review",
                                            cookies=b)).json()
        summary = await (await client.get(f"{API}/radar/catalog/summary", cookies=b)).json()
        by_id = await (await client.get(f"{API}/radar/catalog?id={key}", cookies=a)).json()
        bad_id = (await client.get(f"{API}/radar/catalog?id=../x", cookies=a)).status
        sources_page = await (await client.get("/control/frozen-legacies", cookies=maint)).text()
        return waiting, waiting_b, summary, by_id, bad_id, sources_page

    waiting, waiting_b, summary, by_id, bad_id, sources_page = _run(web_env, script)
    assert waiting["total"] == 1 and "needs_review" in waiting["items"][0]["processing"]
    assert waiting_b["total"] == 0                                # another user's work
    flight = next(f for f in summary["flights"] if f["flight"] == "127")
    assert flight["awaiting_review"] == 1 and flight["mine"]["needs_review"] == 0
    assert by_id["total"] == 1 and by_id["items"][0]["catalog_id"]
    assert bad_id == 400
    assert "/control/frozen-legacies/review" in sources_page


def test_frontend_wires_review_and_published_layers():
    import shutil
    import subprocess

    app = _HERE.parent
    html = (app / "index.html").read_text()
    order = [html.index(f"/frozen-legacies/assets/{name}") for name in
             ("astra_picker.js", "catalog.js", "review.js", "published_layer.js", "radar.js")]
    assert order == sorted(order)
    review_js = (app / "assets" / "review.js").read_text()
    layer_js = (app / "assets" / "published_layer.js").read_text()
    radar_js = (app / "assets" / "radar.js").read_text()
    assert "window.FrozenLegaciesReview = { mount, initialize, reload, panelHtml, bindPanel }" in review_js
    assert "window.FrozenLegaciesPublishedLayer" in layer_js and "bbox" in layer_js
    assert "FrozenLegaciesReview?.mount" in (app / "assets" / "astra_picker.js").read_text()
    assert "get(\"open\")" in radar_js and "/^cat-[0-9a-f]{24}$/" in radar_js
    # the published layer never draws user drafts; it reads the published API only
    assert "/frozen-legacies/api/published" in layer_js and "/observations\"" not in layer_js
    node = shutil.which("node")
    if node:
        for name in ("review.js", "published_layer.js", "user_layer.js", "catalog.js", "radar.js"):
            subprocess.run([node, "--check", str(app / "assets" / name)], check=True)


def _sub(status, revision, sid="sub-1", completed_at=100.0):
    return {"submission_id": sid, "status": status, "session_revision": revision,
            "completed_at": completed_at}


def _session(status, revision, completed_at=100.0):
    return {"status": status, "revision": revision, "completed_at": completed_at}


def test_result_stage_never_reports_later_edits_as_reviewed():
    stage = review_mod.result_stage
    assert stage(_session("draft", 3, None), [])["stage"] == "draft"
    assert stage({}, [])["stage"] == "draft"
    assert stage(_session("completed", 3), [])["visibility"] == "private"
    assert stage(_session("completed", 3), [_sub("cancelled", 3)])["stage"] == "completed"
    pending = stage(_session("completed", 3), [_sub("submitted", 3)])
    assert (pending["stage"], pending["visibility"], pending["changed_since_submission"]) \
        == ("in_review", "reviewers", False)
    edited = stage(_session("draft", 5, None), [_sub("submitted", 3)])
    assert edited["stage"] == "in_review" and edited["changed_since_submission"]
    assert edited["submitted_revision"] == 3
    published = stage(_session("completed", 3), [_sub("published", 3)])
    assert (published["stage"], published["visibility"]) == ("published", "public")
    # a published result edited afterwards is private work again
    later = stage(_session("completed", 4), [_sub("published", 3)])
    assert (later["stage"], later["visibility"]) == ("completed", "private")
    assert later["published_submission_id"] == "sub-1" and later["published_revision"] == 3
    # revisions restart after a reset: same number, different session
    reset = stage(_session("completed", 3, 250.0), [_sub("published", 3)])
    assert reset["stage"] == "completed" and reset["changed_since_submission"]
    returned = stage(_session("completed", 4), [_sub("returned", 3, "sub-2"), _sub("published", 2)])
    assert returned["stage"] == "returned" and returned["published_revision"] == 2
    for status in ("rejected", "withdrawn", "superseded"):
        assert stage(_session("completed", 3), [_sub(status, 3)])["stage"] == status
    assert set(review_mod.STAGES.values()) == {"private", "reviewers", "public"}


def test_a_reset_result_with_the_same_revision_count_can_be_submitted(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    _a, a = _login(web_env, "a@example.org")
    _r, reviewer = _login(web_env, "reviewer@example.org", "admin")

    async def script(client, app):
        await _setup_source(client, app, maint)
        _key, aid = await _open(client, a)
        first_done = await _done(client, a, aid, 1)
        first = (await _submit(client, a, aid))[1]["submission_id"]
        await _decide(client, reviewer, first, "approve", accept_unverified_geolocation=True)
        unchanged = (await _submit(client, a, aid))[0]
        await client.post(f"{API}/assets/{aid}/manual", cookies=a,
                          json={"action": "reset", "confirm": True})
        again_done = await _done(client, a, aid, 1)          # same number of actions
        status, second = await _submit(client, a, aid)
        return first_done["revision"], again_done["revision"], unchanged, status, second

    rev1, rev2, unchanged, status, second = _run(web_env, script)
    assert rev1 == rev2                       # the revision counter restarted
    assert unchanged == 409                   # the identical version is still refused
    assert status == 201 and second["status"] == "submitted"


def test_my_picks_carry_the_review_stage_through_the_lifecycle(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    _a, a = _login(web_env, "a@example.org")
    _b, b = _login(web_env, "b@example.org")
    _r, reviewer = _login(web_env, "reviewer@example.org", "admin")

    async def mine(client, ck):
        return await (await client.get(f"{API}/observations", cookies=ck)).json()

    async def script(client, app):
        out = {}
        await _setup_source(client, app, maint)
        _key, aid = await _open(client, a)
        await _commit(client, a, aid, 1)
        out["draft"] = await mine(client, a)
        await _done(client, a, aid, 1)
        out["completed"] = await mine(client, a)
        sid = (await _submit(client, a, aid))[1]["submission_id"]
        out["in_review"] = await mine(client, a)
        out["b"] = await mine(client, b)
        await _decide(client, reviewer, sid, "approve", accept_unverified_geolocation=True)
        out["published"] = await mine(client, a)
        out["state_published"] = await (await client.get(f"{API}/assets/{aid}/review",
                                                          cookies=a)).json()
        await client.post(f"{API}/assets/{aid}/manual", cookies=a,
                          json={"action": "reset", "confirm": True})
        await _done(client, a, aid, 2)
        out["edited"] = await mine(client, a)
        out["state_edited"] = await (await client.get(f"{API}/assets/{aid}/review",
                                                      cookies=a)).json()
        out["sid"] = sid
        return out

    out = _run(web_env, script)

    def stages(collection):
        return {f["properties"]["review"]["stage"] for f in collection["features"]}

    assert stages(out["draft"]) == {"draft"}
    assert out["draft"]["summary"]["results_by_stage"] == {"draft": 1}
    assert stages(out["completed"]) == {"completed"}
    assert stages(out["in_review"]) == {"in_review"}
    assert {f["properties"]["review"]["visibility"] for f in out["in_review"]["features"]} \
        == {"reviewers"}
    assert out["b"]["features"] == [] and out["b"]["summary"]["results_by_stage"] == {}
    assert stages(out["published"]) == {"published"}
    assert out["state_published"]["stage"]["stage"] == "published"
    # after editing, the published version is named but the edits are private
    assert stages(out["edited"]) == {"completed"}
    review = out["edited"]["features"][0]["properties"]["review"]
    assert review["visibility"] == "private" and review["published_submission_id"] == out["sid"]
    assert out["state_edited"]["stage"]["stage"] == "completed"
    assert out["state_edited"]["stage"]["changed_since_submission"]
    assert out["edited"]["summary"]["results_by_stage"] == {"completed": 1}


def test_frontend_shares_one_review_stage_vocabulary():
    import re

    app = _HERE.parent
    user_js = (app / "assets" / "user_layer.js").read_text()
    review_js = (app / "assets" / "review.js").read_text()
    block = user_js[user_js.index("const STAGES = {"):user_js.index("};", user_js.index("const STAGES = {"))]
    assert set(re.findall(r"^\s+(\w+): \[", block, re.M)) == set(review_mod.STAGES)
    for visibility in set(review_mod.STAGES.values()):
        assert f"{visibility}:" in user_js
    assert "stageChip," in user_js and "stageNote," in user_js
    assert "Completed (not reviewed)" not in user_js and "visible only to you</p>" not in user_js
    assert "layer.stageNote(stage)" in review_js
