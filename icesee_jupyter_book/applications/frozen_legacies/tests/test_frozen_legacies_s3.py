"""Read-only S3 data sources and background indexing.

No AWS access: the S3 provider talks to a local S3-compatible test server
(:mod:`frozen_legacies_fake_s3`) through the real AWS SDK with dummy
credentials, or to a fake client for error classification (no SDK needed).

Covers source configuration (approvals, credential rejection), pagination,
metadata, ranged header reads, streaming into the working cache, transient
errors, interrupted transfers, missing objects vs access denied, incremental
indexing, the background worker (progress, heartbeat, cancellation, a killed
worker, restart recovery, retry), maintainer authorization, the end-to-end
S3 -> working cache -> Manual ASTRA -> observations -> My picks -> product
download path with byte parity against a local source, concurrent users,
cross-user isolation, and gateway responsiveness while a worker indexes.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[3]
for _p in (str(_REPO), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from frozen_legacies_fake_s3 import FakeS3
from frozen_legacies_radar_fixtures import tiff_bytes
from test_frozen_legacies_catalog import NAV, _json, _login, _strip, _wait_worker
from icesee_jupyter_book.applications.frozen_legacies import catalog_routes, server
from icesee_jupyter_book.applications.frozen_legacies.radar import catalog as catalog_mod
from icesee_jupyter_book.applications.frozen_legacies.radar import storage
from icesee_jupyter_book.applications.frozen_legacies.radar import working_cache as cache_mod
from icesee_jupyter_book.applications.frozen_legacies.radar.catalog import CatalogError, RadarCatalog
from icesee_jupyter_book.applications.frozen_legacies.radar.indexer import index_source
from icesee_jupyter_book.applications.frozen_legacies.radar.sources import SOURCES_ENV
from icesee_jupyter_book.applications.frozen_legacies.radar.storage import (
    S3Provider, StorageError, StorageKeyError, validate_s3_config)

API = "/frozen-legacies/api"
BUCKET = "radar-archive"
SECRET = "fake-secret-value-7f3a"      # dummy SDK credential; must never appear in output
F127 = [f"F127-C{s:04d}_C{s + 12:04d}.tiff" for s in (471, 484, 497)]


def _small_tiff(i=0):
    img = np.full((40, 120), 50000 + i, np.uint16)
    return tiff_bytes(img)


@pytest.fixture
def approvals(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.S3_ALLOWED_ENV, f"{BUCKET}/frozen other-bucket")
    monkeypatch.setenv(storage.S3_ENDPOINTS_ENV, "")
    monkeypatch.setenv(storage.STORAGE_ROOTS_ENV, str(tmp_path))
    monkeypatch.setenv(catalog_mod.CATALOG_ENV, str(tmp_path / "var" / "catalog.db"))
    monkeypatch.setenv(cache_mod.CACHE_DIR_ENV, str(tmp_path / "var" / "cache"))
    monkeypatch.setattr(cache_mod, "_cache", None)
    catalog_mod._shared.clear()
    catalog_routes._reconciled.clear()
    return tmp_path


@pytest.fixture
def s3(approvals, monkeypatch):
    """The local S3 server with an F127 archive, and SDK credentials from the
    standard environment chain (dummy values)."""
    pytest.importorskip("boto3")
    fake = FakeS3(BUCKET).start()
    for name in F127:
        fake.put(f"frozen/tiff/F127/{name}", tiff_bytes(_strip()))
    fake.put("frozen/tiff/F125-C0100_C0110.tiff", tiff_bytes(_strip()))
    fake.put("frozen/tiff/broken.tiff", b"II*\x00not really a tiff")
    fake.put("frozen/tiff/", b"")                               # folder marker
    fake.put("frozen/nav/127.csv", NAV.encode())
    fake.put("private/elsewhere.tiff", tiff_bytes(_strip()))   # outside the prefix
    monkeypatch.setenv(storage.S3_ENDPOINTS_ENV, f"local={fake.url}")
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SESSION_TOKEN", "AWS_ROLE_ARN",
                 "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_CONTAINER_CREDENTIALS_FULL_URI",
                 "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDTESTONLY")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SECRET)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(approvals / "no-aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(approvals / "no-aws-credentials"))
    yield fake
    fake.stop()


S3_CONFIG = {"bucket": BUCKET, "prefix": "frozen", "region": "us-east-1", "endpoint": "local",
             "tiff_prefix": "tiff", "nav_template": "nav/{flight}.csv"}


def _s3_source(catalog, source_id="s3-archive"):
    return catalog.add_source(source_id=source_id, name="S3 archive", provider="s3",
                              dataset_id="frozen-legacies-ascope", config=dict(S3_CONFIG))


# ── configuration ────────────────────────────────────────────────────
def test_s3_configuration_needs_operator_approval_and_never_takes_credentials(approvals,
                                                                              monkeypatch):
    ok = validate_s3_config({"bucket": BUCKET, "prefix": "frozen/tiff"})
    assert ok == {"bucket": BUCKET, "prefix": "frozen/tiff", "region": None, "endpoint": None}
    validate_s3_config({"bucket": "other-bucket", "prefix": "anything"})
    bad = [
        {"bucket": BUCKET, "prefix": ""},                          # above the approved prefix
        {"bucket": BUCKET, "prefix": "frozen-other"},              # sibling, not a child
        {"bucket": BUCKET, "prefix": "frozen/../private"},
        {"bucket": "unapproved", "prefix": "frozen"},
        {"bucket": "Bad_Bucket", "prefix": "frozen"},
        {"bucket": BUCKET, "prefix": "frozen", "region": "not a region"},
        {"bucket": BUCKET, "prefix": "frozen", "endpoint": "unlisted"},
        {"bucket": BUCKET, "prefix": "frozen", "aws_secret_access_key": "x"},
        {"bucket": BUCKET, "prefix": "frozen", "session_token": "x"},
    ]
    for config in bad:
        with pytest.raises(StorageKeyError):
            validate_s3_config(config)
    monkeypatch.setenv(storage.S3_ALLOWED_ENV, "")
    with pytest.raises(StorageKeyError):                           # nothing approved
        validate_s3_config({"bucket": BUCKET, "prefix": "frozen"})
    monkeypatch.setenv(storage.S3_ALLOWED_ENV, f"{BUCKET}/frozen")
    for payload in ({"provider": "s3", "bucket": BUCKET, "prefix": "frozen",
                     "aws_secret_access_key": "x"},
                    {"provider": "s3", "bucket": BUCKET, "prefix": "frozen", "AccessKeyId": "x"},
                    {"provider": "local", "root": "/tmp", "password": "x"}):
        with pytest.raises(CatalogError):
            catalog_routes._validated_config(payload)
    config = catalog_routes._validated_config({"provider": "s3", "bucket": BUCKET,
                                               "prefix": "/frozen/", "tiff_prefix": "tiff"})
    assert config == {"bucket": BUCKET, "prefix": "frozen", "region": None, "endpoint": None,
                      "tiff_prefix": "tiff", "nav_template": ""}


class _ClientError(Exception):
    def __init__(self, code, status):
        super().__init__(code)
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}


class NoCredentialsError(Exception):
    pass


class _FakeClient:
    """Minimal client with scripted failures (no AWS SDK required)."""

    def __init__(self, error):
        self.error = error

    def head_object(self, **_):
        raise self.error

    def get_object(self, **_):
        raise self.error

    def list_objects_v2(self, **_):
        raise self.error


def test_s3_errors_are_classified_without_the_sdk(approvals):
    def provider(error):
        return S3Provider({"bucket": BUCKET, "prefix": "frozen"}, client=_FakeClient(error))

    assert provider(_ClientError("404", 404)).stat("a.tiff") is None
    with pytest.raises(StorageError, match="Access denied"):    # 403 is never "missing"
        provider(_ClientError("403", 403)).stat("a.tiff")
    with pytest.raises(StorageError, match="Access denied"):
        provider(_ClientError("ExpiredToken", 400)).read_range("a.tiff", 0, 8)
    with pytest.raises(StorageError, match="no longer"):
        provider(_ClientError("NoSuchKey", 404)).open_stream("a.tiff")
    with pytest.raises(StorageError, match="temporarily unavailable"):
        provider(_ClientError("SlowDown", 503)).read_range("a.tiff", 0, 8)
    with pytest.raises(StorageError, match="temporarily unavailable"):
        provider(ConnectionResetError("reset")).stat("a.tiff")
    assert provider(_ClientError("InvalidRange", 416)).read_range("a.tiff", 99, 8) == b""
    result = provider(NoCredentialsError()).check()
    assert result["ok"] is False and "credentials" in result["message"]
    assert provider(_ClientError("403", 403)).stat("../escape") is None   # never sent


# ── provider against a local S3 endpoint ─────────────────────────────
def test_s3_provider_lists_reads_ranges_and_handles_failures(s3):
    s3.page_size = 2
    provider = S3Provider(S3_CONFIG)
    keys = [o.key for o in provider.list("tiff", suffixes=(".tiff",))]
    assert sorted(keys) == sorted([f"tiff/F127/{n}" for n in F127]
                                  + ["tiff/F125-C0100_C0110.tiff", "tiff/broken.tiff"])
    assert s3.count("GET") >= 3                                  # paginated listing
    key = f"tiff/F127/{F127[0]}"
    obj = provider.stat(key)
    assert obj.size == len(s3.objects[f"frozen/{key}"][0]) and obj.etag
    assert provider.stat("tiff/none.tiff") is None
    assert provider.read_range(key, 0, 4) == b"II*\x00"
    assert provider.read_range(key, obj.size + 10, 4) == b""
    s3.transient[f"frozen/{key}"] = 2                            # retried by the SDK
    assert provider.read_range(key, 0, 4) == b"II*\x00"
    s3.denied.add("frozen/tiff/F127/F127-C0484")
    with pytest.raises(StorageError, match="Access denied"):
        provider.stat(f"tiff/F127/{F127[1]}")
    s3.truncate.add(f"frozen/{key}")
    with pytest.raises(StorageError, match="interrupted"):
        with provider.open_stream(key) as stream:
            stream.read()
    assert provider.check()["ok"] is True
    described = json.dumps(provider.describe())
    assert s3.url not in described and SECRET not in described


def test_working_cache_streams_s3_objects_and_survives_interrupted_transfers(s3, approvals):
    provider = S3Provider(S3_CONFIG)
    key = f"tiff/F127/{F127[0]}"
    obj = provider.stat(key)
    cache = cache_mod.WorkingCache(approvals / "cache", max_bytes=10 * 1024 * 1024)
    s3.truncate.add(f"frozen/{key}")
    with pytest.raises(StorageError):
        cache.materialize(provider, "s3-archive", obj)
    assert not [p for p in (approvals / "cache").iterdir()]       # no partial file left
    s3.truncate.clear()
    path = cache.materialize(provider, "s3-archive", obj)
    assert path.read_bytes() == s3.objects[f"frozen/{key}"][0]
    assert path.name == F127[0]                                  # ASTRA reads CBDs from it
    gets = s3.count("GET")
    assert cache.materialize(provider, "s3-archive", obj) == path and s3.count("GET") == gets


# ── indexing ─────────────────────────────────────────────────────────
def test_s3_indexing_reads_headers_by_range_and_is_incremental(s3, approvals):
    catalog = RadarCatalog(approvals / "var" / "catalog.db")
    source = _s3_source(catalog)
    provider = S3Provider(source["config"])
    first = index_source(catalog, source, provider)
    assert first["status"] == "completed"
    assert (first["counts"]["added"], first["counts"]["invalid"]) == (5, 1)
    items = catalog.search(dataset_id="frozen-legacies-ascope")["items"]
    assert {i["filename"] for i in items if i["status"] == "indexed"} == set(F127) | {
        "F125-C0100_C0110.tiff"}
    segments = catalog.segments(flight="127")
    # tracks from S3 navigation (the test navigation covers CBD 465-489)
    assert sorted(f["properties"]["filename"] for f in segments["features"]) == F127[:2]
    tiff_gets = [(k, r) for m, k, r in s3.requests if m == "GET" and k.endswith(".tiff")]
    assert tiff_gets and all(ranged for _k, ranged in tiff_gets)   # headers by range only
    assert not (approvals / "var" / "cache").exists()           # indexing copies nothing

    s3.requests.clear()
    again = index_source(catalog, source, provider)
    assert again["counts"]["unchanged"] == 5 and again["counts"]["added"] == 0
    assert all(k == "" for _m, k, _r in s3.requests)             # listing only

    s3.put(f"frozen/tiff/F127/{F127[2]}", tiff_bytes(_strip(width=2700)), etag="v2")
    s3.delete("frozen/tiff/F125-C0100_C0110.tiff")
    s3.denied.add("frozen/tiff/F127/F127-C0484")                 # metadata listed, reads denied
    s3.put(f"frozen/tiff/F127/{F127[1]}", tiff_bytes(_strip()), etag="v3")
    third = index_source(catalog, source, provider)
    c = third["counts"]
    assert (c["changed"], c["missing"], c["unavailable"]) == (1, 1, 1)
    statuses = {Path(k).name: v["status"] for k, v in catalog.known_objects("s3-archive").items()}
    assert statuses[F127[1]] == "unavailable"                    # denied is not invalid/missing

    import boto3
    from botocore.config import Config

    s3.down = True                                               # no SDK retries: fast test
    once = S3Provider(source["config"], client=boto3.session.Session().client(
        "s3", region_name="us-east-1", endpoint_url=s3.url,
        config=Config(retries={"max_attempts": 1}, s3={"addressing_style": "path"})))
    outage = index_source(catalog, source, once)
    assert outage["status"] == "unavailable" and outage["counts"]["missing"] == 0
    s3.down = False
    s3.denied.clear()
    retry = index_source(catalog, source, provider, retry_invalid=True)
    assert retry["status"] == "completed" and retry["counts"]["unavailable"] == 0


# ── background worker ────────────────────────────────────────────────
def _worker(catalog, run_id):
    return subprocess.Popen(
        [sys.executable, "-m", catalog_routes.WORKER_MODULE, "--catalog", str(catalog.path),
         "--run", str(run_id)], cwd=str(_REPO), stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE)


def _wait(predicate, timeout=60.0, step=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    raise AssertionError("condition not reached")


def _bulk(s3, n, prefix="frozen/tiff/bulk"):
    data = _small_tiff()
    for i in range(n):
        s3.put(f"{prefix}/F2{i // 500:02d}-C{(i % 500) * 13 + 10:04d}_C{(i % 500) * 13 + 22:04d}.tiff",
               data)


def test_worker_indexes_in_the_background_with_progress(s3, approvals):
    catalog = RadarCatalog(approvals / "var" / "catalog.db")
    _s3_source(catalog)
    run_id = catalog.queue_run("s3-archive", requested_by="maint")
    assert catalog.queue_run("s3-archive") is None               # one active run per source
    process = _worker(catalog, run_id)
    _out, err = process.communicate(timeout=120)
    assert process.returncode == 0, err.decode()
    run = catalog.get_run(run_id)
    assert run["status"] == "completed" and run["pid"] == process.pid
    assert (run["discovered"], run["added"], run["invalid"]) == (5, 5, 1)
    assert run["heartbeat_at"] and run["finished_at"] and run["requested_by"] == "maint"
    assert SECRET not in err.decode()
    source = catalog.get_source("s3-archive")
    assert source["last_success_at"] and source["last_index_status"] == "completed"
    second = _worker(catalog, run_id)                            # a run is claimed once
    second.communicate(timeout=60)
    assert second.returncode != 0 and catalog.get_run(run_id)["status"] == "completed"


def test_cancelling_a_run_keeps_indexed_files_and_marks_nothing_missing(s3, approvals):
    _bulk(s3, 1600)
    catalog = RadarCatalog(approvals / "var" / "catalog.db")
    _s3_source(catalog)
    before = catalog.queue_run("s3-archive")
    assert _worker(catalog, before).wait(timeout=180) == 0       # baseline index
    s3.delay_s = 0.03                                            # a slow archive
    s3.put("frozen/tiff/F999-C0001_C0002.tiff", _small_tiff())  # one new file
    run_id = catalog.queue_run("s3-archive", full=True)
    process = _worker(catalog, run_id)
    _wait(lambda: (catalog.get_run(run_id) or {}).get("discovered", 0) > 0, timeout=120)
    catalog.request_cancel(run_id)
    assert process.wait(timeout=120) == 0
    run = catalog.get_run(run_id)
    assert run["status"] == "cancelled" and run["missing"] == 0
    assert 0 < run["discovered"] < 1606
    statuses = catalog.list_sources()[0]["counts"]
    assert statuses["missing"] == 0 and statuses["indexed"] >= 1604


def test_a_killed_worker_is_interrupted_and_a_retry_completes(s3, approvals):
    _bulk(s3, 1600)
    s3.delay_s = 0.03
    catalog = RadarCatalog(approvals / "var" / "catalog.db")
    _s3_source(catalog)
    run_id = catalog.queue_run("s3-archive")
    process = _worker(catalog, run_id)
    _wait(lambda: (catalog.get_run(run_id) or {}).get("added", 0) > 0, timeout=120)
    process.send_signal(signal.SIGKILL)
    process.wait(timeout=30)
    assert catalog.get_run(run_id)["status"] == "running"        # nobody finished it
    assert catalog_routes.reconcile_runs(catalog) == [run_id]    # pid is gone
    run = catalog.get_run(run_id)
    assert run["status"] == "interrupted" and catalog.active_run("s3-archive") is None
    kept = catalog.list_sources()[0]["counts"]
    assert kept["missing"] == 0 and 0 < kept["total"] < 1605
    s3.delay_s = 0
    retry = catalog.queue_run("s3-archive")
    assert _worker(catalog, retry).wait(timeout=180) == 0
    done = catalog.get_run(retry)
    assert done["status"] == "completed" and done["unchanged"] == kept["total"]
    assert catalog.list_sources()[0]["counts"]["total"] == 1605


def test_stale_runs_are_recovered_on_heartbeat_age(approvals):
    catalog = RadarCatalog(approvals / "var" / "catalog.db")
    catalog.add_source(source_id="local", name="L", provider="local", dataset_id="d",
                       config={"root": str(approvals)})
    run_id = catalog.queue_run("local")
    assert catalog.claim_run(run_id, os.getpid())                 # "alive" pid
    assert catalog.reconcile_runs(stale_after_s=90, is_alive=lambda p: True) == []
    with catalog._connect() as db:
        db.execute("UPDATE index_runs SET heartbeat_at = ? WHERE run_id = ?",
                   (time.time() - 600, run_id))
    assert catalog.reconcile_runs(stale_after_s=90, is_alive=lambda p: True) == [run_id]
    queued = catalog.queue_run("local")
    cancelled = catalog.request_cancel(queued)                   # not started: ends at once
    assert cancelled["status"] == "cancelled"


# ── HTTP: Control Center, users, picker ──────────────────────────────
@pytest.fixture
def web_env(s3, approvals, monkeypatch):
    from icesee_auth import AuthManager

    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(approvals / "auth.db"))
    monkeypatch.setenv(SOURCES_ENV, str(approvals / "no-registry.yaml"))
    local = approvals / "local-archive"
    (local / "tiff" / "F127").mkdir(parents=True)
    (local / "nav").mkdir()
    for name in F127:
        (local / "tiff" / "F127" / name).write_bytes(s3.objects[f"frozen/tiff/F127/{name}"][0])
    (local / "nav" / "127.csv").write_text(NAV)
    return {"tmp": approvals, "s3": s3, "auth": AuthManager(), "workspace": approvals / "ws",
            "local": local}


def _run(env, script, *, before=None):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    if before is not None:
        before()
    app = web.Application()
    env["auth"].install(app)
    app[server.WORKSPACE_ROOT_KEY] = str(env["workspace"])
    server.install_frozen_legacies(app, auth=env["auth"])

    async def go():
        async with TestClient(TestServer(app)) as client:
            return await script(client, app)

    return asyncio.run(go())


async def _add_s3(client, ck, **extra):
    payload = {"source_id": "s3-archive", "name": "S3 archive",
               "dataset_id": "frozen-legacies-ascope", "provider": "s3", **S3_CONFIG, **extra}
    return await _json(await client.post(f"{API}/admin/sources", cookies=ck, json=payload))


async def _index(client, app, ck, source_id, path="index", **payload):
    status, body = await _json(await client.post(f"{API}/admin/sources/{source_id}/{path}",
                                                 cookies=ck, json=payload))
    assert status == 202, body
    await _wait_worker(app, body["run_id"])
    return body


def test_control_center_manages_s3_sources_in_the_background(web_env):
    _u, normal = _login(web_env, "user@example.org")
    _m, maint = _login(web_env, "maint@example.org", "maintainer")

    async def script(client, app):
        out = {}
        out["creds"] = (await _add_s3(client, maint, aws_secret_access_key=SECRET))[0]
        out["unapproved"] = (await _add_s3(client, maint, prefix="private"))[0]
        out["endpoint"] = (await _add_s3(client, maint, endpoint="elsewhere"))[0]
        out["user_add"] = (await _add_s3(client, normal))[0]
        status, added = await _add_s3(client, maint)
        out["added"] = (status, added)
        for path in ("test", "index", "retry", "cancel"):
            out[f"user_{path}"] = (await client.post(f"{API}/admin/sources/s3-archive/{path}",
                                                     cookies=normal, json={})).status
        status, out["test"] = await _json(await client.post(
            f"{API}/admin/sources/s3-archive/test", cookies=maint, json={}))
        await _index(client, app, maint, "s3-archive")
        # an active run blocks a second one; cancelling a queued run ends it at once
        catalog = catalog_mod.open_catalog()
        queued = catalog.queue_run("s3-archive")
        out["busy"] = (await client.post(f"{API}/admin/sources/s3-archive/index",
                                         cookies=maint, json={})).status
        status, listed = await _json(await client.get(f"{API}/admin/sources", cookies=maint))
        out["during"] = listed["sources"][0]
        status, out["cancel"] = await _json(await client.post(
            f"{API}/admin/sources/s3-archive/cancel", cookies=maint, json={}))
        out["cancel_idle"] = (await client.post(f"{API}/admin/sources/s3-archive/cancel",
                                                cookies=maint, json={})).status
        await _index(client, app, maint, "s3-archive", path="retry")
        status, listed = await _json(await client.get(f"{API}/admin/sources", cookies=maint))
        out["listed"] = listed
        out["raw"] = json.dumps(listed)
        page = await client.get("/control/frozen-legacies", cookies=maint)
        out["page"] = await page.text()
        out["queued"] = queued
        return out

    out = _run(web_env, script)
    assert (out["creds"], out["unapproved"], out["endpoint"], out["user_add"]) == (
        400, 400, 400, 403)
    assert out["added"][0] == 201, out["added"]
    assert {out[f"user_{p}"] for p in ("test", "index", "retry", "cancel")} == {403}
    assert out["test"]["ok"] is True
    assert out["busy"] == 409
    assert out["during"]["indexing"] is True and out["during"]["progress"]["status"] == "queued"
    assert out["cancel"]["run"]["status"] == "cancelled" and out["cancel_idle"] == 409
    source = out["listed"]["sources"][0]
    assert source["indexing"] is False and source["last_index_status"] == "completed"
    assert source["counts"]["indexed"] == 4 and source["counts"]["invalid"] == 1
    assert source["location"] == f"s3://{BUCKET}/frozen" and source["endpoint"] == "local"
    assert source["runs"][0]["retry_invalid"] == 1
    assert [e["filename"] for e in source["recent_errors"]] == ["broken.tiff"]
    assert web_env["s3"].url not in out["raw"] and SECRET not in out["raw"]
    assert "AKIDTESTONLY" not in out["raw"]
    assert 'name="bucket"' in out["page"] and "Never enter access keys" in out["page"]
    assert "Retry failed files" in out["page"] and "Cancel indexing" in out["page"]
    # the form gets approvals and endpoint names, never endpoint URLs
    assert out["listed"]["s3"] == {"configured": True, "approved": [f"s3://{BUCKET}/frozen",
                                                                     "s3://other-bucket"],
                                   "endpoints": ["local"]}


def test_gateway_start_marks_dead_runs_interrupted(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    catalog = catalog_mod.create_catalog()
    _s3_source(catalog)
    run_id = catalog.queue_run("s3-archive")
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    catalog.claim_run(run_id, dead.pid)

    async def script(client, app):
        status, listed = await _json(await client.get(f"{API}/admin/sources", cookies=maint))
        return listed["sources"][0]

    source = _run(web_env, script)
    assert catalog.get_run(run_id)["status"] == "interrupted"
    assert source["indexing"] is False and source["last_index_status"] == "interrupted"


async def _manual_picks(client, ck, aid, n=2):
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
    return await (await client.post(base, cookies=ck, json={"revision": rev,
                                                           "action": "done"})).json()


def test_s3_radar_runs_through_astra_to_my_picks_and_products(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    _a, a = _login(web_env, "a@example.org")
    _b, b = _login(web_env, "b@example.org")

    async def script(client, app):
        assert (await _add_s3(client, maint))[0] == 201
        status, body = await _json(await client.post(f"{API}/admin/sources", cookies=maint, json={
            "source_id": "local-archive", "name": "Local", "dataset_id": "local-copy",
            "provider": "local", "root": str(web_env["local"]), "tiff_prefix": "tiff",
            "nav_template": "nav/{flight}.csv"}))
        assert status == 201, body
        await _index(client, app, maint, "s3-archive")
        await _index(client, app, maint, "local-archive")

        async def key_for(dataset):
            listing = await (await client.get(
                f"{API}/radar/catalog?dataset={dataset}&flight=127&page_size=1",
                cookies=a)).json()
            return listing["items"][0]

        remote, local = await key_for("frozen-legacies-ascope"), await key_for("local-copy")
        assert remote["filename"] == local["filename"] == F127[0]
        downloads = cache_mod.working_cache().downloads
        # two users open the same S3 file at once: one transfer
        opened = await asyncio.gather(*(client.post(f"{API}/assets/shared", cookies=ck,
                                                    json={"source": remote["catalog_id"]})
                                        for ck in (a, b)))
        assets = [await r.json() for r in opened]
        out = {"open_status": [r.status for r in opened],
               "downloads": cache_mod.working_cache().downloads - downloads}
        aid = assets[0]["asset_id"]
        local_asset = await (await client.post(f"{API}/assets/shared", cookies=a,
                                               json={"source": local["catalog_id"]})).json()
        out["remote_done"] = await _manual_picks(client, a, aid)
        out["local_done"] = await _manual_picks(client, a, local_asset["asset_id"])
        out["remote_csv"] = await (await client.get(
            f"{API}/assets/{aid}/products/astra-csv", cookies=a)).read()
        out["local_csv"] = await (await client.get(
            f"{API}/assets/{local_asset['asset_id']}/products/astra-csv", cookies=a)).read()
        out["remote_qc"] = await (await client.get(
            f"{API}/assets/{aid}/products/astra-qc", cookies=a)).read()
        out["local_qc"] = await (await client.get(
            f"{API}/assets/{local_asset['asset_id']}/products/astra-qc", cookies=a)).read()
        out["mine"] = await (await client.get(f"{API}/observations", cookies=a)).json()
        out["other"] = await (await client.get(f"{API}/observations", cookies=b)).json()
        out["steal"] = (await client.get(f"{API}/assets/{aid}/products/astra-csv",
                                         cookies=b)).status
        out["steal_manual"] = (await client.get(f"{API}/assets/{aid}/manual",
                                                cookies=b)).status
        out["summary"] = await (await client.get(f"{API}/radar/catalog/summary",
                                                 cookies=a)).json()
        out["aid"] = aid
        return out

    out = _run(web_env, script)
    assert out["open_status"] == [201, 201]
    assert out["downloads"] == 2                                 # TIFF + navigation, once each
    # the I/O path does not change ASTRA: byte-identical products from S3 and local
    assert out["remote_csv"] and out["remote_csv"] == out["local_csv"]
    assert out["remote_qc"] == out["local_qc"]
    remote_picks = [f for f in out["mine"]["features"]
                    if f["properties"]["dataset_id"] == "frozen-legacies-ascope"]
    assert len(remote_picks) == 2
    assert {f["properties"]["status"] for f in remote_picks} == {"completed"}
    assert {f["properties"]["scope"] for f in remote_picks} == {"user"}  # never published
    assert all(f["properties"]["catalog_id"].startswith("cat-") for f in remote_picks)
    assert out["other"]["features"] == []
    assert (out["steal"], out["steal_manual"]) == (404, 404)
    # no permanent copy of the radar in the user's workspace
    workspace_files = [p for p in web_env["workspace"].rglob("*")
                       if p.is_file() and p.suffix.lower() in (".tif", ".tiff")]
    assert workspace_files == [] or all(p.is_symlink() for p in workspace_files)
    cached = sorted(p.name for p in (web_env["tmp"] / "var" / "cache").rglob("*") if p.is_file())
    assert cached == ["127.csv", F127[0]]                        # original names, for ASTRA


def test_gateway_stays_responsive_while_a_worker_indexes(web_env):
    n = int(os.environ.get("FROZEN_LEGACIES_S3_BENCHMARK_N", "3000"))
    _bulk(web_env["s3"], n)
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    _a, a = _login(web_env, "a@example.org")

    async def script(client, app):
        assert (await _add_s3(client, maint))[0] == 201
        status, body = await _json(await client.post(f"{API}/admin/sources/s3-archive/index",
                                                     cookies=maint, json={}))
        assert status == 202
        worker = app[catalog_routes.INDEX_WORKERS_KEY][body["run_id"]][1]
        latencies, polls = [], 0
        started = time.perf_counter()
        while not worker.done():
            for url, ck in ((f"{API}/radar/catalog?page_size=50", a),
                            (f"{API}/radar/catalog/summary", a),
                            (f"{API}/admin/sources", maint)):
                t = time.perf_counter()
                resp = await client.get(url, cookies=ck)
                assert resp.status == 200
                await resp.read()
                latencies.append(time.perf_counter() - t)
            polls += 1
            await asyncio.sleep(0.05)
        elapsed = time.perf_counter() - started
        await worker
        status, listed = await _json(await client.get(f"{API}/admin/sources", cookies=maint))
        return latencies, polls, elapsed, listed["sources"][0]

    latencies, polls, elapsed, source = _run(web_env, script)
    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95) - 1] if len(latencies) > 1 else latencies[0]
    print(f"\n[s3 benchmark] {n + 5} TIFF objects indexed by the worker in {elapsed:.1f}s; "
          f"{len(latencies)} gateway requests during indexing: p50 {p50 * 1000:.1f} ms, "
          f"p95 {p95 * 1000:.1f} ms, max {latencies[-1] * 1000:.1f} ms")
    assert source["last_index_status"] == "completed"
    assert source["counts"]["total"] == n + 5
    assert polls >= 2 and p95 < 1.0


# ── cloud drives: planned, never enabled ────────────────────────────
def test_cloud_drive_providers_are_reserved_but_not_available(monkeypatch):
    assert storage.PLANNED_PROVIDERS == ("gdrive", "onedrive")
    assert not set(storage.PLANNED_PROVIDERS) & set(storage.PROVIDERS)
    for name, cls in (("gdrive", storage.GoogleDriveProvider), ("onedrive", storage.OneDriveProvider)):
        with pytest.raises(StorageError, match="not available on this server"):
            storage.provider_for(name, {"drive_id": "d1"})
        with pytest.raises(StorageError, match="not available on this server"):
            cls({"drive_id": "d1"})
        assert issubclass(cls, storage.RadarStorageProvider)


def test_cloud_drive_configuration_follows_the_approval_pattern(monkeypatch):
    v = storage.validate_drive_config
    monkeypatch.delenv("CRYOSTACK_FROZEN_LEGACIES_GDRIVE_ALLOWED", raising=False)
    with pytest.raises(StorageKeyError, match="not approved"):
        v("gdrive", {"drive_id": "0AbcD", "folder_id": "1xyz"})
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_GDRIVE_ALLOWED", "0AbcD")
    assert v("gdrive", {"drive_id": "0AbcD", "folder_id": "1xyz"}) == {"drive_id": "0AbcD",
                                                                       "folder_id": "1xyz"}
    for bad in ({"drive_id": "0AbcD", "folder_id": "1xyz", "refresh_token": "t"},
                {"drive_id": "0AbcD", "folder_id": "1xyz", "client_secret": "s"},
                {"drive_id": "../x", "folder_id": "1xyz"},
                {"drive_id": "0AbcD", "folder_id": ""}):
        with pytest.raises(StorageKeyError):
            v("gdrive", bad)
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_ONEDRIVE_ALLOWED", "b!drive")
    assert v("onedrive", {"drive_id": "b!drive", "folder": "/radar/F127/"})["folder"] == "radar/F127"
    with pytest.raises(StorageKeyError):
        v("onedrive", {"drive_id": "b!drive", "folder": "radar/../etc"})
    with pytest.raises(StorageKeyError):
        v("s3", {"drive_id": "x"})


def test_control_center_refuses_cloud_drive_sources(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")

    async def script(client, app):
        payload = {"source_id": "drive", "name": "Drive", "dataset_id": "frozen-legacies-ascope",
                   "provider": "gdrive", "drive_id": "0AbcD", "folder_id": "1xyz"}
        return await _json(await client.post(f"{API}/admin/sources", cookies=maint, json=payload))

    status, body = _run(web_env, script)
    assert status == 400 and "provider must be one of: local, s3" in body["error"]
