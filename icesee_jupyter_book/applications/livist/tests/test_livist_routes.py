"""LIVIST HTTP API and Control Center page: roles, per-user isolation, the
two-step publication workflow and the absence of credentials / server paths
in responses. The generator is mocked at the subprocess boundary."""
import asyncio
import json
from pathlib import Path

import pytest

from icesee_jupyter_book.applications.livist import routes, worker

from livist_test_support import SECRET, fake_popen, not_ready_health, use_ready_toolchain

API = "/api/livist"


@pytest.fixture
def env(tmp_path, monkeypatch):
    from icesee_auth import AuthManager

    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(tmp_path / "auth.db"))
    roots = tmp_path / "approved-inputs"
    roots.mkdir()
    (roots / "sample.csv").write_text("x,y,atten_rate_C0\n1,2,5.4\n")
    monkeypatch.setenv("CRYOSTACK_LIVIST_INPUT_ROOTS", str(roots))
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SECRET)
    monkeypatch.setenv("AWS_SESSION_TOKEN", SECRET)
    use_ready_toolchain(monkeypatch)
    return {"tmp": tmp_path, "auth": AuthManager(), "roots": roots}


def _login(env, name, *roles):
    store = env["auth"].storage
    user = store.create_user(email=f"{name}@example.org", display_name=name.title(),
                             institution=None, password_hash="x")
    for role in roles:
        store.grant_role(user_id=user.id, role=role)
    session = store.create_session(ttl_seconds=3600, user_id=user.id)
    return user, {"icesee_session": session.id}


def _run(env, script, *, probe=None, s3=None):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    app = web.Application()
    env["auth"].install(app)

    async def spawn(app_, store, job_id):        # worker inline, generator faked
        await routes._blocking(worker.run, store, job_id, popen=fake_popen())

    app[routes.SPAWN_KEY] = spawn
    app[routes.PROBE_KEY] = probe or (lambda url: {"exists": False})
    if s3 is not None:
        app["livist_s3_client"] = s3
    routes.install_livist(app, auth=env["auth"])

    async def go():
        async with TestClient(TestServer(app)) as client:
            return await script(client, app)

    return asyncio.run(go())


async def _j(resp):
    body = await resp.text()
    return resp.status, (json.loads(body) if resp.content_type == "application/json" else body)


async def _approve_sample(client, ck):
    status, listed = await _j(await client.get(f"{API}/sources", cookies=ck))
    assert status == 200
    local = next(c for c in listed["candidates"] if c["kind"] == "local")
    status, body = await _j(await client.post(f"{API}/sources", cookies=ck, json={
        "candidate_id": local["id"], "name": "sample", "description": "fixture"}))
    assert status == 201, body
    return body


def _audit(env):
    import sqlite3
    with sqlite3.connect(env["tmp"] / "auth.db") as db:
        return [r[0] for r in db.execute("SELECT action FROM control_audit_log ORDER BY created_at")]


def test_roles_and_isolation(env):
    _plain, plain = _login(env, "plain")
    # Starting generations is limited to maintainer/admin/owner; "dev" owns the
    # job (as a maintainer), "devonly" is a plain developer.
    dev_user, dev = _login(env, "dev", "maintainer")
    _devonly, devonly = _login(env, "devonly", "developer")
    _other, other = _login(env, "other", "developer")
    _maint, maint = _login(env, "maint", "maintainer")

    async def script(client, app):
        out = {}
        out["anon"] = (await client.get(f"{API}/status")).status
        out["plain_status"] = (await client.get(f"{API}/status", cookies=plain)).status
        out["plain_start"] = (await client.post(f"{API}/jobs", cookies=plain,
                                                json={"sources": ["sample"]})).status
        out["plain_page"] = (await client.get("/control/livist", cookies=plain,
                                              allow_redirects=False)).status
        out["dev_sources"] = (await client.get(f"{API}/sources", cookies=devonly)).status
        out["dev_publications"] = (await client.get(f"{API}/publications", cookies=devonly)).status
        out["dev_all_jobs"] = (await client.get(f"{API}/jobs?scope=all", cookies=devonly)).status
        await _approve_sample(client, maint)
        out["devonly_status"] = (await _j(await client.get(f"{API}/status", cookies=devonly)))[1]
        out["devonly_start"] = (await client.post(f"{API}/jobs", cookies=devonly,
                                                  json={"sources": ["sample"]})).status
        out["devonly_jobs"] = (await _j(await client.get(f"{API}/jobs", cookies=devonly)))
        out["maint_status"] = (await _j(await client.get(f"{API}/status", cookies=maint)))[1]

        status, job = await _j(await client.post(f"{API}/jobs", cookies=dev,
                                                 json={"sources": ["sample"]}))
        assert status == 202, job
        job_id = job["job_id"]
        _s, detail = await _j(await client.get(f"{API}/jobs/{job_id}", cookies=dev))
        out["dev_detail"] = detail
        out["dev_log"] = (await _j(await client.get(f"{API}/jobs/{job_id}/log", cookies=dev)))[1]
        out["dev_download"] = await client.get(
            f"{API}/jobs/{job_id}/files/temperature-sample-pure-ice.pmtiles", cookies=dev)
        out["dev_download_body"] = await out["dev_download"].read()
        out["dev_manifest"] = (await client.get(f"{API}/jobs/{job_id}/files/manifest.json",
                                                cookies=dev)).status
        out["dev_traversal"] = (await client.get(
            f"{API}/jobs/{job_id}/files/..%2Fconfig.toml", cookies=dev)).status
        out["dev_config"] = (await client.get(f"{API}/jobs/{job_id}/files/config.toml",
                                              cookies=dev)).status
        # another developer cannot see, cancel, validate or download it
        out["other_detail"] = (await client.get(f"{API}/jobs/{job_id}", cookies=other)).status
        out["other_log"] = (await client.get(f"{API}/jobs/{job_id}/log", cookies=other)).status
        out["other_validate"] = (await client.post(f"{API}/jobs/{job_id}/validate",
                                                   cookies=other, json={})).status
        out["other_list"] = (await _j(await client.get(f"{API}/jobs", cookies=other)))[1]
        # maintainers see it, but downloads stay with the owner
        out["maint_detail"] = (await client.get(f"{API}/jobs/{job_id}", cookies=maint)).status
        out["maint_all"] = (await _j(await client.get(f"{API}/jobs?scope=all", cookies=maint)))[1]
        out["maint_download"] = (await client.get(
            f"{API}/jobs/{job_id}/files/temperature-sample-pure-ice.pmtiles",
            cookies=maint)).status
        out["revalidate"] = (await _j(await client.post(f"{API}/jobs/{job_id}/validate",
                                                        cookies=dev, json={})))
        out["job_id"] = job_id
        return out

    out = _run(env, script)
    assert out["anon"] == 401 and out["plain_status"] == 403 and out["plain_start"] == 403
    assert out["plain_page"] == 403
    assert out["dev_sources"] == 403 and out["dev_publications"] == 403
    assert out["dev_all_jobs"] == 403
    # developers may open LIVIST and list their own jobs, but not start one
    assert out["devonly_status"]["viewer"]["can_generate"] is False
    assert out["devonly_start"] == 403
    assert out["devonly_jobs"][0] == 200 and out["devonly_jobs"][1]["jobs"] == []
    assert out["maint_status"]["viewer"]["can_generate"] is True
    assert out["dev_detail"]["status"] == "completed" and out["dev_detail"]["mine"]
    assert {a["name"] for a in out["dev_detail"]["manifest"]["artifacts"]} >= {
        "temperature-sample-pure-ice.pmtiles", "temperature-sources.json"}
    assert "finished: completed" in out["dev_log"]["log"]
    assert out["dev_download"].status == 200
    assert out["dev_download_body"].startswith(b"PMTiles")
    assert "attachment" in out["dev_download"].headers["Content-Disposition"]
    assert out["dev_manifest"] == 200
    assert out["dev_traversal"] == 404 and out["dev_config"] == 404
    assert out["other_detail"] == 404 and out["other_log"] == 404
    assert out["other_validate"] == 404 and out["other_list"]["jobs"] == []
    assert out["maint_detail"] == 200 and out["maint_download"] == 404
    assert out["maint_all"]["jobs"][0]["owner"] == "Dev"
    assert out["revalidate"][0] == 200

    # the job ran in its owner's own workspace
    from cryostack_src.workspace.roots import owner_root
    from icesee_jupyter_book.applications.livist.workspace import workspace_user_for
    job_dir = owner_root(workspace_user_for(dev_user)) / "livist" / "jobs" / out["job_id"]
    assert (job_dir / "manifest.json").is_file()
    assert set(_audit(env)) >= {"livist.source.approve", "livist.job.start"}


def test_inputs_are_never_free_form(env):
    _m, maint = _login(env, "maint", "maintainer")

    async def script(client, app):
        out = {}
        out["path"] = await _j(await client.post(f"{API}/sources", cookies=maint, json={
            "candidate_id": "x", "name": "evil", "location": "/etc/passwd"}))
        out["unknown"] = (await client.post(f"{API}/sources", cookies=maint, json={
            "candidate_id": "0" * 20, "name": "evil"})).status
        out["badname"] = (await client.post(f"{API}/sources", cookies=maint, json={
            "candidate_id": "0" * 20, "name": "../x"})).status
        out["form"] = (await client.post(f"{API}/sources", cookies=maint,
                                         data={"candidate_id": "x", "name": "y"})).status
        out["cross"] = (await client.post(f"{API}/sources", cookies=maint, json={},
                                          headers={"Origin": "https://evil.example"})).status
        await _approve_sample(client, maint)
        out["dup"] = (await client.post(f"{API}/sources", cookies=maint, json={
            "candidate_id": (await (await client.get(f"{API}/sources", cookies=maint)).json())
            ["candidates"][0]["id"], "name": "sample"})).status
        out["disable"] = (await client.post(f"{API}/sources/sample/status", cookies=maint,
                                            json={"enabled": False})).status
        out["start_disabled"] = (await client.post(f"{API}/jobs", cookies=maint,
                                                   json={"sources": ["sample"]})).status
        out["start_unknown"] = (await client.post(f"{API}/jobs", cookies=maint,
                                                  json={"sources": ["/etc/passwd"]})).status
        out["listing"] = await (await client.get(f"{API}/sources", cookies=maint)).text()
        out["status"] = await (await client.get(f"{API}/status", cookies=maint)).text()
        return out

    out = _run(env, script)
    assert out["path"][0] == 400 and "paths cannot be entered" in out["path"][1]["error"]
    assert out["unknown"] == 400 and out["badname"] == 400
    assert out["form"] == 415 and out["cross"] == 403
    assert out["dup"] == 409 and out["disable"] == 200
    assert out["start_disabled"] == 400 and out["start_unknown"] == 400
    for text in (out["listing"], out["status"]):
        assert str(env["roots"]) not in text and str(env["tmp"]) not in text
        assert SECRET not in text


def test_generation_refused_when_toolchain_missing(env, monkeypatch):
    from icesee_jupyter_book.applications.livist import toolchain
    _m, maint = _login(env, "maint", "maintainer")

    async def script(client, app):
        await _approve_sample(client, maint)
        monkeypatch.setattr(toolchain, "health", not_ready_health)
        status = await _j(await client.get(f"{API}/status", cookies=maint))
        start = await _j(await client.post(f"{API}/jobs", cookies=maint,
                                           json={"sources": ["sample"]}))
        return status, start

    status, start = _run(env, script)
    assert status[1]["toolchain"]["ready"] is False
    assert start[0] == 409 and "not ready" in start[1]["error"]


def _publish_flow(env, *, probe=None, s3=None, change_after_request=False, allow_overwrite=False):
    _d, dev = _login(env, "dev", "developer")
    carol_user, carol = _login(env, "carol", "maintainer")   # starts the job
    _a, alice = _login(env, "alice", "maintainer")
    _b, bob = _login(env, "bob", "admin")

    async def script(client, app):
        out = {}
        await _approve_sample(client, alice)
        _s, job = await _j(await client.post(f"{API}/jobs", cookies=carol,
                                             json={"sources": ["sample"]}))
        out["dev_request"] = (await client.post(f"{API}/publications", cookies=dev,
                                                json={"job_id": job["job_id"]})).status
        out["request"] = await _j(await client.post(f"{API}/publications", cookies=alice, json={
            "job_id": job["job_id"], "allow_overwrite": allow_overwrite}))
        if out["request"][0] != 201:
            return out
        rid = out["request"][1]["request_id"]
        out["self_approve"] = (await client.post(f"{API}/publications/{rid}/approve",
                                                 cookies=alice, json={})).status
        out["dev_approve"] = (await client.post(f"{API}/publications/{rid}/approve",
                                                cookies=dev, json={})).status
        if change_after_request:
            from cryostack_src.workspace.roots import owner_root
            from icesee_jupyter_book.applications.livist.workspace import workspace_user_for
            data = (owner_root(workspace_user_for(carol_user)) / "livist" / "jobs"
                    / job["job_id"] / "data")
            (data / "temperature-sample-pure-ice.parquet").write_bytes(b"PAR1tamperedPAR1")
        out["approve"] = await _j(await client.post(f"{API}/publications/{rid}/approve",
                                                    cookies=bob, json={"note": "ok"}))
        out["again"] = (await client.post(f"{API}/publications/{rid}/approve", cookies=bob,
                                          json={})).status
        out["list"] = await (await client.get(f"{API}/publications", cookies=bob)).text()
        return out

    return _run(env, script, probe=probe, s3=s3)


class _FakeS3:
    def __init__(self):
        self.uploads = []

    def __call__(self):
        return self

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        self.uploads.append((Path(path).name, bucket, key, ExtraArgs))


def test_publication_two_step_dry_run_by_default(env):
    s3 = _FakeS3()
    out = _publish_flow(env, s3=s3)
    assert out["dev_request"] == 403
    status, request = out["request"]
    assert status == 201 and request["status"] == "pending"
    assert request["plan"]["dry_run"] and len(request["plan"]["files"]) == 4
    assert out["self_approve"] == 403 and out["dev_approve"] == 403
    status, decided = out["approve"]
    assert status == 200 and decided["status"] == "approved"
    assert decided["result"]["dry_run"] is True and decided["result"]["uploaded"] == []
    assert out["again"] == 409
    assert s3.uploads == []                         # nothing was uploaded
    assert SECRET not in out["list"] and str(env["tmp"]) not in out["list"]
    actions = _audit(env)
    assert "livist.publication.request" in actions and "livist.publication.approve" in actions


def test_publication_detects_overwrite_and_tampering(env):
    probe = lambda url: {"exists": url.endswith("pure-ice.pmtiles"), "size": 1}
    out = _publish_flow(env, probe=probe)
    assert out["request"][0] == 409 and "overwritten" in out["request"][1]["error"]
    assert out["request"][1]["plan"]["overwrites"] == ["temperature-sample-pure-ice.pmtiles"]


def test_publication_fails_when_products_change_after_request(env):
    out = _publish_flow(env, change_after_request=True)
    status, body = out["approve"]
    assert status == 409 and "changed" in body["error"]
    assert '"status": "failed"' in out["list"]


def test_real_upload_only_behind_flag(env, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_LIVIST_PUBLICATION_ENABLED", "1")
    s3 = _FakeS3()
    out = _publish_flow(env, s3=s3)
    status, body = out["approve"]
    assert status == 200 and body["status"] == "published"
    assert sorted(u[0] for u in s3.uploads) == [
        "temperature-sample-conductivity.parquet", "temperature-sample-conductivity.pmtiles",
        "temperature-sample-pure-ice.parquet", "temperature-sample-pure-ice.pmtiles"]
    assert {u[1] for u in s3.uploads} == {"us-west-2.opendata.source.coop"}
    assert all(u[2].startswith("englacial/ice-sheet-temperature/temperature/") for u in s3.uploads)


def test_upload_errors_are_not_echoed(env, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_LIVIST_PUBLICATION_ENABLED", "1")

    class Boom(_FakeS3):
        def upload_file(self, *a, **k):
            raise RuntimeError(f"AccessDenied for key {SECRET}")

    out = _publish_flow(env, s3=Boom())
    status, body = out["approve"]
    assert status == 502 and body["error"] == "The upload failed."
    assert SECRET not in out["list"]


def test_control_page_and_nav(env):
    _d, dev = _login(env, "dev", "developer")

    async def script(client, app):
        page = await client.get("/control/livist", cookies=dev)
        return page.status, await page.text()

    status, text = _run(env, script)
    assert status == 200
    assert 'href="/control/livist"' in text and "control-nav-item active" in text
    assert "/api/livist" in text and "Publication to source.coop" in text
