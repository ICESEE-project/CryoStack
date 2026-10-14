"""Product browsing, run comparison and input cache diagnostics: read-only
views over finished jobs. Jobs are written directly (products, manifest,
store rows) so their checksums are known; nothing runs LIVIST."""
import hashlib
import json
import time

import pytest

from icesee_jupyter_book.applications.livist import input_cache, manifest, products
from icesee_jupyter_book.applications.livist.store import LivistStore
from icesee_jupyter_book.applications.livist.workspace import (LivistWorkspace, new_job_id,
                                                               workspace_user_for)

from livist_test_support import SECRET
from test_livist_routes import _j, _login, _run, env  # noqa: F401  (fixture)

API = "/api/livist"
KEY = "englacial/ice-sheet-temperature/AttenuationRateData/depth-avg-attenuation-ASE.txt"
NAMES = [f"temperature-ase-{mode}{suffix}" for mode in ("conductivity", "pure-ice")
         for suffix in (".parquet", "-wgs84.parquet", ".fgb", ".pmtiles")]
INPUT = b"x,y,atten_rate_C0\n1,2,5.4\n"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _job(user, *, status="completed", files=None, input_bytes=INPUT, cache="hit",
         resources=None, check="passed", config="c" * 64, commit="a" * 40):
    """A finished job in ``user``'s workspace with a manifest like the worker's."""
    store = LivistStore()
    job_id = new_job_id()
    workdir = LivistWorkspace(workspace_user_for(user)).create_job_dir(job_id)
    store.queue_job(job_id=job_id, owner_id=user.id, workdir=str(workdir),
                    sources=[{"name": "ase", "kind": "source-coop", "location": KEY}],
                    timeout_s=60, max_active=100)
    if status in ("running", "queued"):
        if status == "running":
            store.claim_job(job_id, 0)
        return job_id
    store.claim_job(job_id, 0)
    files = {n: n.encode() for n in NAMES} if files is None else files
    (workdir / "data").mkdir()
    for name, data in files.items():
        (workdir / "data" / name).write_bytes(data)
    (workdir / "frontend" / "public").mkdir(parents=True)
    (workdir / "frontend" / "public" / "temperature-sources.json").write_text("{}")
    checks = [{"artifact": n, "check": "magic", "level": "ok", "detail": ""} for n in files]
    if check == "failed":
        checks.append({"artifact": NAMES[0], "check": "rows", "level": "error",
                       "detail": "0 rows"})
    store.finish_job(job_id, status=status, exit_code=0, config_sha256=config,
                     validation_status=check)
    data = {
        "schema": 1, "job_id": job_id,
        "livist": {"commit": commit, "command": "scripts/generate",
                   "environment": {"python": "3.13.16", "gdal": "3.13.3"}},
        "cryostack_commit": "b" * 40, "config_sha256": config,
        "inputs": [{"name": "ase", "kind": "source-coop", "location": KEY,
                    "size": len(input_bytes), "sha256": _sha(input_bytes),
                    "cache": {"cache": cache, "upstream_checked": True}}],
        "artifacts": manifest.artifacts(workdir),
        "validation": None if check is None else {"status": check, "deep": True,
                                                  "checked_at": time.time(), "checks": checks},
        "resources": resources or {"measured": True, "wall_s": 100.0, "cpu_user_s": 90.0,
                                   "cpu_system_s": 10.0, "peak_rss_mb": 1000.0,
                                   "workdir_bytes": 2000},
        "written_at": time.time(),
    }
    manifest.write(workdir, data)
    return job_id


def _compare(client, ck, *ids):
    return client.get(f"{API}/compare?jobs=" + ",".join(ids), cookies=ck)


def test_compare_respects_job_visibility(env):
    alice_user, alice = _login(env, "alice", "developer")
    bob_user, bob = _login(env, "bob", "developer")
    _p, plain = _login(env, "plain")
    _m, maint = _login(env, "maint", "maintainer")
    a1, a2 = _job(alice_user), _job(alice_user)
    b1 = _job(bob_user)
    running = _job(bob_user, status="running")

    async def script(client, app):
        out = {}
        out["anon"] = (await client.get(f"{API}/compare?jobs={a1},{a2}")).status
        out["plain"] = (await _compare(client, plain, a1, a2)).status
        out["own"] = await _j(await _compare(client, alice, a1, a2))
        out["other"] = await _j(await _compare(client, alice, a1, b1))
        out["missing"] = await _j(await _compare(client, alice, a1, "f" * 32))
        out["bad_id"] = await _j(await _compare(client, alice, a1, "../etc"))
        out["bob_alice"] = (await _compare(client, bob, a2, b1)).status
        out["maint"] = await _j(await _compare(client, maint, a1, b1))
        out["maint_running"] = (await _compare(client, maint, a1, running)).status
        out["bob_running"] = (await _compare(client, bob, b1, running)).status
        out["one"] = (await _compare(client, alice, a1)).status
        out["dup"] = (await _compare(client, alice, a1, a1)).status
        out["many"] = (await _compare(client, maint, a1, a2, b1,
                                      *[new_job_id() for _ in range(4)])).status
        out["repeated"] = (await client.get(f"{API}/compare?job={a1}&job={a2}",
                                            cookies=alice)).status
        return out

    out = _run(env, script)
    assert out["anon"] == 401 and out["plain"] == 403
    assert out["own"][0] == 200 and out["own"][1]["job_ids"] == [a1, a2]
    # someone else's job is answered exactly like a job that does not exist
    assert out["other"] == out["missing"] == out["bad_id"] == (404, {"error": "Job not found."})
    assert out["bob_alice"] == 404
    assert out["maint"][0] == 200
    assert [j["owner"] for j in out["maint"][1]["jobs"]] == ["Alice", "Bob"]
    assert out["maint_running"] == 409 and out["bob_running"] == 409
    assert out["one"] == 400 and out["dup"] == 400 and out["many"] == 400
    assert out["repeated"] == 200
    text = json.dumps(out["maint"][1])
    assert str(env["tmp"]) not in text and SECRET not in text and '"workdir"' not in text


def _pair(env, **second):
    user, ck = _login(env, "alice", "maintainer")
    first = _job(user)
    other = _job(user, **second)

    async def script(client, app):
        return await _j(await _compare(client, ck, first, other))

    status, body = _run(env, script)
    assert status == 200, body
    return body


def test_identical_runs(env):
    body = _pair(env)
    assert body["products_identical"] and body["inputs_identical"]
    assert body["product_summary"] == {"identical": 9, "differ": 0, "missing": 0}
    assert all(e["same"] for e in body["environment"])
    assert body["statements"][0].startswith("Inputs are identical")
    assert "All 9 products are byte-identical" in " ".join(body["statements"])
    assert "not opened" in body["statements"][-1]
    assert all(d == {"delta": 0.0, "percent": 0.0}
               for r in body["resources"] for d in r["difference"])


def test_different_product_is_reported(env):
    files = {n: n.encode() for n in NAMES}
    files[NAMES[3]] = b"PMTiles-other"
    body = _pair(env, files=files)
    assert not body["products_identical"] and body["inputs_identical"]
    by_name = {p["name"]: p for p in body["products"]}
    assert by_name[NAMES[3]]["identity"] == "differ"
    assert by_name[NAMES[3]]["mode"] == "conductivity" and "PMTiles" in by_name[NAMES[3]]["format"]
    assert by_name[NAMES[0]]["identity"] == "identical"
    assert body["product_summary"] == {"identical": 8, "differ": 1, "missing": 0}
    assert any(s.startswith("Products differ: 1 differ in content") for s in body["statements"])


def test_missing_product_is_reported(env):
    files = {n: n.encode() for n in NAMES[:-1]}
    body = _pair(env, files=files, check="failed")
    missing = [p for p in body["products"] if p["identity"] == "missing"]
    assert [p["name"] for p in missing] == [NAMES[-1]] and missing[0]["jobs"][1] is None
    assert body["product_summary"]["missing"] == 1
    assert [j["validation"]["status"] for j in body["jobs"]] == ["passed", "failed"]
    by_name = {p["name"]: p for p in body["products"]}
    assert by_name[NAMES[0]]["jobs"][1]["validation"] == "failed"
    assert by_name[NAMES[0]]["jobs"][0]["validation"] == "passed"


def test_different_input_checksum_and_resources(env):
    body = _pair(env, input_bytes=b"x,y,atten_rate_C0\n9,9,1\n", cache="stored", config="d" * 64,
                 resources={"measured": True, "wall_s": 150.0, "cpu_user_s": 100.0,
                            "cpu_system_s": 20.0, "peak_rss_mb": 500.0, "workdir_bytes": 4000})
    assert not body["inputs_identical"]
    assert body["inputs"][0]["identity"] == "differ"
    assert [j["cache"] for j in body["inputs"][0]["jobs"]] == ["hit", "stored"]
    assert body["statements"][0] == "Inputs differ: ase (differ)."
    config = next(e for e in body["environment"] if e["field"] == "config_sha256")
    assert not config["same"]
    res = {r["field"]: r for r in body["resources"]}
    assert res["wall_s"]["values"] == [100.0, 150.0]
    assert res["wall_s"]["difference"][1] == {"delta": 50.0, "percent": 50.0}
    assert res["cpu_s"]["values"] == [100.0, 120.0]
    assert res["peak_rss_mb"]["difference"][1]["percent"] == -50.0
    assert res["workdir_bytes"]["difference"][1]["delta"] == 2000


def test_compare_more_than_two_and_recorded_etag():
    def run(job_id, sha_input, artifacts, identity=None):
        record = {"name": "ase", "kind": "source-coop", "location": KEY, "size": 3,
                  "sha256": sha_input}
        if identity is not None:
            record["identity"] = identity
        return {"job": {"job_id": job_id, "config_sha256": "c"},
                "manifest": {"inputs": [record], "artifacts": artifacts}}
    a = [{"name": "temperature-ase-pure-ice.parquet", "size": 1, "sha256": "1"}]
    b = [{"name": "temperature-ase-pure-ice.parquet", "size": 1, "sha256": "2"}]
    seen = {"recorded": True, "sha256": "s", "size": 3, "etag": '"e1"',
            "last_modified": "Mon, 05 Oct 2026 10:00:00 GMT", "upstream_size": 3,
            "upstream_checked": True, "observed": "source.coop HEAD before the run"}
    body = products.compare([run("j1" * 16, "s", a, seen), run("j2" * 16, "s", a, seen),
                             run("j3" * 16, "s", b, seen)])
    assert body["products"][0]["identity"] == "differ"
    cells = body["inputs"][0]["jobs"]
    assert [j["etag"] for j in cells] == ['"e1"'] * 3
    assert all(j["identity_recorded"] and j["last_modified"].startswith("Mon") for j in cells)
    assert not any("not recorded" in t for t in body["statements"])
    # an older manifest recorded no identity: "not recorded", never today's cache index
    other = products.compare([run("j1" * 16, "s", a, seen), run("j2" * 16, "s", a)])
    cells = other["inputs"][0]["jobs"]
    assert [j["etag"] for j in cells] == ['"e1"', None]
    assert cells[1]["identity_recorded"] is False and cells[1]["observed"] == "not recorded"
    assert any("was not recorded by j2j2j2j2" in t for t in other["statements"])
    # a recorded ETag that changed between runs is called out
    changed = products.compare([run("j1" * 16, "s", a, seen),
                                run("j2" * 16, "s", a, {**seen, "etag": '"e2"'})])
    assert any("object on source.coop changed" in t for t in changed["statements"])


def test_job_detail_product_table(env):
    owner_user, owner = _login(env, "owner", "maintainer")
    _m, maint = _login(env, "maint", "maintainer")
    _o, other = _login(env, "other", "developer")
    passed = _job(owner_user)
    failed = _job(owner_user, check="failed")
    unvalidated = _job(owner_user, check=None)
    store = LivistStore()
    # a dry-run approval is not a publication
    store.create_request(request_id="1" * 32, job_id=passed, plan={"files": []}, plan_sha256="x",
                         allow_overwrite=False, requested_by=owner_user.id)
    store.decide_request("1" * 32, status="approved", decided_by="someone-else",
                         result={"dry_run": True, "uploaded": []})

    async def script(client, app):
        out = {}
        for key, job_id, ck in (("owner", passed, owner), ("maint", passed, maint),
                                ("failed", failed, owner), ("unvalidated", unvalidated, owner),
                                ("other", passed, other)):
            out[key] = await _j(await client.get(f"{API}/jobs/{job_id}", cookies=ck))
        return out

    out = _run(env, script)
    table = out["owner"][1]["products"]
    assert table["downloadable"] is True and out["maint"][1]["products"]["downloadable"] is False
    names = [p["name"] for p in table["products"]]
    assert set(NAMES) <= set(names)
    row = next(p for p in table["products"] if p["name"] == NAMES[1])
    assert row["mode"] == "conductivity" and row["format"] == "GeoParquet (EPSG:4326)"
    assert row["sha256"] == _sha(NAMES[1].encode()) and len(row["sha256"]) == 64
    assert row["validation"] == "passed" and row["on_disk"] and not row["published"]
    assert row["publishable"] is False                     # scripts/upload skips -wgs84
    assert table["publication"]["state"] == "dry-run-approved"
    assert "second maintainer" in table["publication"]["note"]
    assert table["counts"]["passed"] == 8
    failed_rows = {p["name"]: p for p in out["failed"][1]["products"]["products"]}
    assert failed_rows[NAMES[0]]["validation"] == "failed"
    assert failed_rows[NAMES[0]]["findings"] == ["rows: 0 rows"]
    assert out["failed"][1]["products"]["publication"]["state"] == "not-requested"
    assert {p["validation"] for p in out["unvalidated"][1]["products"]["products"]} == {
        "unvalidated"}
    assert out["other"][0] == 404
    assert str(env["tmp"]) not in json.dumps(out["owner"][1])


def test_published_only_after_executed_upload():
    shas = {"temperature-ase-pure-ice.pmtiles": "1"}
    published = {"status": "published", "plan": {"files": [
        {"name": "temperature-ase-pure-ice.pmtiles", "sha256": "1"}]},
        "result": {"dry_run": False, "uploaded": [{"name": "temperature-ase-pure-ice.pmtiles"}]}}
    state = products.publication_state([published])
    assert state["state"] == "published" and state["published"] == shas
    assert products.publication_state([])["state"] == "not-requested"
    pending = {"status": "pending", "plan": {}, "result": None}
    assert products.publication_state([pending])["published"] == {}


def test_cache_diagnostics_are_maintainer_only_and_read_only(env, tmp_path):
    owner_user, owner = _login(env, "owner", "maintainer")
    _d, dev = _login(env, "dev", "developer")
    _p, plain = _login(env, "plain")
    _a, admin = _login(env, "admin", "admin")
    cache = input_cache.InputCache(head=lambda url: {"size": len(INPUT), "etag": '"e1"'})
    source = tmp_path / "download.txt"
    source.write_bytes(INPUT)
    assert cache.store(KEY, source)["cache"] == "stored"
    used = _job(owner_user, cache="hit")
    other = _job(owner_user, input_bytes=b"other", cache="stored")
    index_before = (cache.root / "index.json").read_bytes()

    async def script(client, app):
        out = {}
        out["anon"] = (await client.get(f"{API}/cache")).status
        out["plain"] = (await client.get(f"{API}/cache", cookies=plain)).status
        out["dev"] = (await client.get(f"{API}/cache", cookies=dev)).status
        out["owner"] = await _j(await client.get(f"{API}/cache", cookies=owner))
        out["admin"] = (await client.get(f"{API}/cache", cookies=admin)).status
        out["post"] = (await client.post(f"{API}/cache", cookies=owner, json={})).status
        out["delete"] = (await client.delete(f"{API}/cache", cookies=owner)).status
        out["page"] = await (await client.get("/control/livist", cookies=dev)).text()
        return out

    out = _run(env, script)
    assert out["anon"] == 401 and out["plain"] == 403 and out["dev"] == 403
    assert out["admin"] == 200 and out["post"] == 405 and out["delete"] == 405
    status, report = out["owner"]
    assert status == 200 and len(report["entries"]) == 1
    entry = report["entries"][0]
    assert entry["host"] == "data.source.coop" and entry["path"] == "/" + KEY
    assert entry["sha256"] == _sha(INPUT) and entry["etag"] == '"e1"'
    assert entry["blob_present"] and entry["blob_size_matches"]
    assert entry["size"] == len(INPUT) and entry["stored_at"] and entry["used_at"]
    jobs = {j["job_id"]: j for j in entry["jobs"]}
    assert jobs[used]["cache"] == "hit" and jobs[used]["same_content"]
    assert jobs[other]["same_content"] is False and jobs[used]["owner"] == "You"
    assert entry["hits"] == 1
    assert report["total_bytes"] == len(INPUT) and report["limit_bytes"] == 4096 * 1024 * 1024
    assert report["reserve_bytes"] == input_cache.FREE_SPACE_RESERVE
    assert report["free_bytes"] > 0 and report["over_limit"] is False
    text = json.dumps(report)
    assert str(env["tmp"]) not in text and str(tmp_path) not in text and SECRET not in text
    assert (cache.root / "index.json").read_bytes() == index_before        # read-only
    # the page carries the sections; developers have them hidden and the API refuses them
    assert "Compare selected" in out["page"] and "Input cache" in out["page"]


@pytest.mark.parametrize("name,mode,fmt", [
    ("temperature-ase-pure-ice.parquet", "pure-ice", "GeoParquet (EPSG:3031)"),
    ("temperature-a-b-conductivity-wgs84.parquet", "conductivity", "GeoParquet (EPSG:4326)"),
    ("temperature-sources.json", None, "LIVIST sources manifest"),
])
def test_describe(name, mode, fmt):
    info = products.describe(name)
    assert info["mode"] == mode and info["format"] == fmt
    if name == "temperature-a-b-conductivity-wgs84.parquet":
        assert info["input"] == "a-b"
