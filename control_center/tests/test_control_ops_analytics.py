"""Analytics aggregation and the application-usage counter."""

from __future__ import annotations

import json
import sqlite3
import time
from types import SimpleNamespace

import pytest

from control_center.ops_store import OpsStore
from control_center.services import analytics as A

NOW = 1_800_000_000.0           # 2027-01-15 08:00 UTC
DAY = 86400


def _experiments_db(path, rows):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE experiments (id TEXT, user_id TEXT, application TEXT,"
                   " backend TEXT, status TEXT, created_at REAL, started_at REAL,"
                   " finished_at REAL)")
        db.executemany("INSERT INTO experiments VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)


@pytest.fixture
def env(tmp_path):
    store = OpsStore(tmp_path / "ops.db")
    cache = SimpleNamespace(usage=lambda: 512 * 1024 ** 2, max_bytes=1024 ** 3,
                            directory=tmp_path / "cache")
    return {"tmp": tmp_path, "store": store, "cache": cache}


def _service(env, **kwargs):
    options = dict(auth_database=env["tmp"] / "auth.db", store=env["store"],
                   catalog_path=env["tmp"] / "catalog.db", working_cache=env["cache"],
                   workspace_root=env["tmp"] / "ws", clock=lambda: NOW)
    options.update(kwargs)
    return A.AnalyticsService(**options)


def test_jobs_are_aggregated_per_day_status_application_and_backend(env):
    rows = [
        ("e1", "alice-id", "cryolauncher", "hpc", "completed", NOW - 1 * DAY, NOW - DAY, NOW - DAY + 3600),
        ("e2", "alice-id", "cryolauncher", "hpc", "failed", NOW - 1 * DAY, NOW - DAY, NOW - DAY + 1800),
        ("e3", "bob-id", "icesee", "cloud", "completed", NOW - 2 * DAY, NOW - 2 * DAY, NOW - 2 * DAY + 7200),
        ("e4", "bob-id", "icesee", "cloud", "running", NOW - 600, NOW - 600, None),
        ("e5", "bob-id", "icesee", "cloud", "completed", NOW - 60 * DAY, None, None),   # outside
    ]
    _experiments_db(env["tmp"] / "auth.db", rows)
    jobs = _service(env).jobs(days=30, now=NOW)
    assert jobs["kind"] == "historical" and jobs["total"] == 4
    assert jobs["by_status"] == {"completed": 2, "failed": 1, "running": 1}
    per_day = {d["day"]: d["counts"] for d in jobs["per_day"]}
    assert len(per_day) == 30
    assert per_day["2027-01-14"] == {"completed": 1, "failed": 1}
    apps = {a["name"]: a for a in jobs["by_application"]}
    assert apps["cryolauncher"]["failure_rate"] == 0.5
    assert apps["icesee"]["failure_rate"] == 0.0 and apps["icesee"]["total"] == 2
    wall = {w["backend"]: w for w in jobs["wall_time"]}
    assert wall["hpc"]["seconds"] == 5400 and wall["cloud"]["jobs"] == 1
    text = json.dumps(jobs)
    assert "alice" not in text and "bob" not in text and "user_id" not in text


def test_missing_sources_are_reported_not_created(env):
    service = _service(env)
    jobs = service.jobs(days=7, now=NOW)
    assert jobs["available"] is False and jobs["error"]
    indexing = service.indexing(days=7, now=NOW)
    assert indexing["available"] is False and indexing["error"]
    assert not (env["tmp"] / "auth.db").exists()
    assert not (env["tmp"] / "catalog.db").exists()


def test_indexing_activity(env):
    from icesee_jupyter_book.applications.frozen_legacies.radar.catalog import RadarCatalog

    catalog = RadarCatalog(env["tmp"] / "catalog.db")
    catalog.add_source(source_id="archive", name="Archive", provider="local",
                       dataset_id="ds", config={"root": "/secret/mount/point"})
    run = catalog.queue_run("archive")
    catalog.finish_run(run, "archive", status="completed",
                       counts={"discovered": 10, "added": 8, "invalid": 2})
    run = catalog.queue_run("archive")
    catalog.finish_run(run, "archive", status="failed", counts={}, error="listing failed")
    indexing = _service(env, clock=time.time).indexing(days=30, now=time.time())
    assert indexing["available"] and indexing["runs"] == 2
    assert indexing["runs_by_status"] == {"completed": 1, "failed": 1}
    assert indexing["run_totals"]["discovered"] == 10 and indexing["run_totals"]["added"] == 8
    assert indexing["recent_failures"][0]["error"] == "listing failed"
    assert indexing["sources"][0]["source_id"] == "archive"
    assert "/secret/mount/point" not in json.dumps(indexing)        # no source config


def test_storage_and_bounded_workspace_totals(env, monkeypatch):
    for user in ("u1", "u2"):
        folder = env["tmp"] / "ws" / "users" / user / "runs"
        folder.mkdir(parents=True)
        for index in range(3):
            (folder / f"f{index}.bin").write_bytes(b"x" * 100)
    storage = _service(env).storage(now=NOW)
    assert storage["kind"] == "live" and storage["measured_at"] == NOW
    assert storage["working_cache"] == {"usage_bytes": 512 * 1024 ** 2,
                                        "limit_bytes": 1024 ** 3, "exists": False}
    assert storage["workspaces"]["users"] == 2 and storage["workspaces"]["bytes"] == 600
    assert storage["workspaces"]["partial"] is False
    assert "u1" not in json.dumps(storage)

    monkeypatch.setattr(A, "WORKSPACE_SCAN_FILES", 2)
    bounded = _service(env).workspace_totals()
    assert bounded["partial"] is True and bounded["users"] == 2


def test_usage_counter_aggregates_without_user_data(env):
    clock = {"now": NOW}
    counter = A.UsageCounter(env["store"], clock=lambda: clock["now"])
    counter.record("livist")
    counter.record("livist")
    clock["now"] += DAY
    assert counter.record("frozen-legacies") is True        # a minute has passed: flush due
    counter.flush()
    with sqlite3.connect(env["store"].path) as db:
        rows = db.execute("SELECT * FROM app_usage_daily ORDER BY day").fetchall()
        columns = [c[1] for c in db.execute("PRAGMA table_info(app_usage_daily)")]
    assert columns == ["day", "application", "opens"]
    assert rows == [("2027-01-15", "livist", 2), ("2027-01-16", "frozen-legacies", 1)]
    usage = _service(env, counter=counter, clock=lambda: clock["now"]).application_usage(
        days=14, now=clock["now"])
    assert usage["totals"]["livist"] == 2 and usage["totals"]["frozen-legacies"] == 1
    assert usage["counting_since"] == "2027-01-15" and usage["kind"] == "historical"
    # pending (not yet flushed) opens are included
    counter.record("icesee")
    usage = _service(env, counter=counter, clock=lambda: clock["now"]).application_usage(
        days=14, now=clock["now"])
    assert usage["totals"]["icesee"] == 1
