"""Diagnostics checks with mocked network, TLS and time."""

from __future__ import annotations

import asyncio
import io
import os
import sqlite3
import ssl
import time
import urllib.error
from collections import namedtuple
from pathlib import Path

import pytest

from control_center.services import diagnostics as D
from control_center.storage import ControlStorage

NOW = 1_800_000_000.0
DAY = 86400


class _Target:
    def __init__(self, path="/x/", statuses=(200,), text=()):
        self.path, self.expected_statuses, self.required_text = path, statuses, text


class _Response(io.BytesIO):
    def __init__(self, status, body=b""):
        super().__init__(body)
        self.status = status


class _Opener:
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append((request, timeout))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def _http_error(code):
    return urllib.error.HTTPError("http://127.0.0.1/x/", code, "x", {}, None)


def test_probe_target_accepts_registered_statuses_and_reports_failures():
    ok = D.probe_target("http://127.0.0.1:1", _Target(statuses=(200, 302)),
                        opener=_Opener(_http_error(302)))
    assert ok["ok"] and ok["detail"] == "HTTP 302"
    bad = D.probe_target("http://127.0.0.1:1", _Target(), opener=_Opener(_http_error(502)))
    assert not bad["ok"] and "HTTP 502" in bad["detail"]
    down = D.probe_target("http://127.0.0.1:1", _Target(),
                          opener=_Opener(urllib.error.URLError("refused")))
    assert not down["ok"] and down["status"] is None and "URLError" in down["detail"]
    text = D.probe_target("http://127.0.0.1:1", _Target(text=("CryoStack",)),
                          opener=_Opener(_Response(200, b"<h1>Other</h1>")))
    assert not text["ok"] and "missing" in text["detail"]
    opener = _Opener(_Response(200))
    D.probe_target("http://127.0.0.1:9/", _Target(path="/livist/"), opener=opener)
    request, timeout = opener.requests[0]
    assert request.full_url == "http://127.0.0.1:9/livist/"
    assert request.get_header("User-agent").startswith("CryoStack-Diagnostics")
    assert timeout == D.PROBE_TIMEOUT_S


def test_tls_thresholds():
    assert D.tls_status(NOW - 1, NOW)[0] == "failed"
    assert D.tls_status(NOW + 10 * DAY, NOW)[0] == "degraded"
    status, detail, action = D.tls_status(NOW + 90 * DAY, NOW)
    assert status == "healthy" and "90 days" in detail and action is None


def _service(tmp_path, **kwargs):
    auth_db = tmp_path / "auth.db"
    defaults = dict(catalog_path=tmp_path / "none.db", working_cache_dir=tmp_path / "cache",
                    workspace_root=tmp_path / "ws", ursa_availability=lambda: {"available": True},
                    tls_probe=lambda host: {"not_after": NOW + 60 * DAY, "issuer": "Test CA"},
                    relay_opener=_Opener(_Response(200)), clock=lambda: NOW)
    defaults.update(kwargs)
    return D.DiagnosticsService(ControlStorage(auth_db), **defaults)


def test_tls_section_uses_handshake_and_never_reads_keys(tmp_path, monkeypatch):
    monkeypatch.setenv(D.PUBLIC_HOST_ENV, "cryostack.example.org")
    seen = []

    def probe(host):
        seen.append(host)
        return {"not_after": NOW + 5 * DAY, "issuer": "Test CA"}

    monkeypatch.setattr(D, "CERT_LIVE_DIR", tmp_path / "live")
    (tmp_path / "live" / "cryostack.example.org").mkdir(parents=True)
    (tmp_path / "live" / "cryostack.example.org" / "privkey.pem").write_text("PRIVATE")
    opened = []
    real_open = Path.open
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: opened.append(self) or real_open(self, *a, **k))
    section = _service(tmp_path, tls_probe=probe).tls_section(NOW)
    assert seen == ["cryostack.example.org"]
    check = section["checks"][0]
    assert check["status"] == "degraded" and "Test CA" in check["detail"]
    assert check["kind"] == "live" and check["measured_at"] == NOW
    assert not any("privkey" in str(p) for p in opened)
    assert len(section["checks"]) == 1            # no readable fullchain.pem


def test_tls_section_failures(tmp_path):
    def verify_fail(host):
        error = ssl.SSLCertVerificationError("bad")
        error.verify_message = "certificate has expired"
        raise error

    check = _service(tmp_path, tls_probe=verify_fail).tls_section(NOW)["checks"][0]
    assert check["status"] == "failed" and "expired" in check["detail"]

    def unreachable(host):
        raise OSError("no route")

    check = _service(tmp_path, tls_probe=unreachable).tls_section(NOW)["checks"][0]
    assert check["status"] == "unknown"


def _make_db(path: Path, mode=0o600):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE t (x)")
        db.execute("INSERT INTO t VALUES (1)")
    os.chmod(path, mode)


def test_database_check(tmp_path):
    good = tmp_path / "good.db"
    _make_db(good)
    check = D.database_check("db", good, now=NOW, expect_private=True)
    assert check["status"] == "healthy" and "quick_check ok" in check["detail"]
    assert "mode 600" in check["detail"] and check["measured_at"] == NOW

    shared = tmp_path / "shared.db"
    _make_db(shared, 0o644)
    check = D.database_check("db", shared, now=NOW, expect_private=True)
    assert check["status"] == "degraded" and "chmod 600" in check["action"]

    assert D.database_check("db", tmp_path / "missing.db", now=NOW,
                            expect_private=True)["status"] == "failed"
    assert D.database_check("db", tmp_path / "missing.db", now=NOW, expect_private=True,
                            optional=True)["status"] == "disabled"

    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not a database at all" * 100)
    os.chmod(broken, 0o600)
    assert D.database_check("db", broken, now=NOW, expect_private=True)["status"] == "failed"


def test_database_check_is_read_only(tmp_path):
    path = tmp_path / "ro.db"
    _make_db(path)
    before = path.read_bytes()
    D.database_check("db", path, now=NOW, expect_private=True)
    assert path.read_bytes() == before
    assert not (tmp_path / "never.db").exists()
    D.database_check("db", tmp_path / "never.db", now=NOW, expect_private=True)
    assert not (tmp_path / "never.db").exists()


def test_storage_check(tmp_path, monkeypatch):
    assert D.storage_check("x", tmp_path / "later", now=NOW)["status"] == "healthy"
    assert D.storage_check("x", tmp_path / "gone", now=NOW, needs_write=False)["status"] == "failed"
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(D.shutil, "disk_usage", lambda p: Usage(100 * 1024 ** 3, 99 * 1024 ** 3,
                                                                1 * 1024 ** 3))
    low = D.storage_check("x", tmp_path, now=NOW)
    assert low["status"] == "degraded" and "low" in low["action"]
    monkeypatch.setattr(D.shutil, "disk_usage", lambda p: Usage(100 * 1024 ** 3, 10, 90 * 1024 ** 3))
    assert D.storage_check("x", tmp_path, now=NOW)["status"] == "healthy"


def test_workers_section_flags_stalled_runs_and_failures(tmp_path):
    from icesee_jupyter_book.applications.frozen_legacies.radar.catalog import RadarCatalog

    catalog = RadarCatalog(tmp_path / "catalog.db")
    catalog.add_source(source_id="archive", name="Archive", provider="local",
                       dataset_id="ds", config={"root": "/data"})
    catalog.add_source(source_id="other", name="Other", provider="local",
                       dataset_id="ds", config={"root": "/data2"})
    stale = catalog.queue_run("archive")
    old = catalog.queue_run("other")
    catalog.finish_run(old, "other", status="interrupted", counts={}, error="worker stopped")
    clock_now = time.time() + 300            # five minutes without a heartbeat
    service = _service(tmp_path, catalog_path=tmp_path / "catalog.db",
                       ursa_availability=lambda: {"available": False,
                                                  "reason": "URSA needs cv2."},
                       clock=lambda: clock_now)
    section = service.workers_section(clock_now)
    by_name = {c["name"]: c for c in section["checks"]}
    run = by_name[f"Index run #{stale} (archive)"]
    assert run["status"] == "failed" and run["action"]
    failures = by_name["Index failures (7 days)"]
    assert failures["status"] == "degraded" and "1 interrupted" in failures["detail"]
    assert failures["kind"] == "historical" and failures["measured_at"] is None
    ursa = by_name["URSA automatic picker"]
    assert ursa["status"] == "disabled" and "cv2" in ursa["detail"]
    assert by_name["Index worker limits"]["kind"] == "configuration"


def test_relay_check_never_uses_credentials(tmp_path):
    opener = _Opener(_Response(200))
    section = _service(tmp_path, relay_opener=opener).connections_section(NOW)
    request, _timeout = opener.requests[0]
    assert request.full_url.endswith("/connector/status/diagnostics-probe")
    assert not request.get_header("Authorization") and not request.get_header("Cookie")
    relay = section["checks"][0]
    assert relay["status"] == "healthy"
    down = _service(tmp_path, relay_opener=_Opener(urllib.error.URLError("x")))
    assert down.connections_section(NOW)["checks"][0]["status"] == "failed"


def test_collect_runs_off_loop_caches_and_limits_refresh(tmp_path, monkeypatch):
    clock = {"now": NOW}
    calls = []
    service = _service(tmp_path, clock=lambda: clock["now"])

    def measure(base_url):
        calls.append(base_url)
        return {"measured_at": clock["now"], "cache_seconds": D.CACHE_S, "sections": [],
                "summary": {}}

    monkeypatch.setattr(service, "measure", measure)

    async def run():
        first = await service.collect(base_url="http://127.0.0.1:8811")
        again = await service.collect(base_url="http://127.0.0.1:8811", refresh=True)
        clock["now"] += D.MIN_REFRESH_S + 1
        refreshed = await service.collect(base_url="http://127.0.0.1:8811", refresh=True)
        clock["now"] += D.CACHE_S + 1
        expired = await service.collect(base_url="http://127.0.0.1:8811")
        return first, again, refreshed, expired

    first, again, refreshed, expired = asyncio.run(run())
    assert len(calls) == 3
    assert first["cached"] is False and again["cached"] is True
    assert refreshed["cached"] is False and expired["cached"] is False
    assert first["sections"][0]["id"] == "gateway"


def test_applications_section_reads_registered_targets(tmp_path, monkeypatch):
    registry = tmp_path / "applications.yaml"
    registry.write_text(
        "platform:\n  health:\n    cryostack:\n      path: /\n"
        "applications:\n  demo:\n    title: Demo\n    routes: [/demo/]\n"
        "    health:\n      target: demo\n      expected_statuses: [200, 302]\n")
    probed = []

    def fake_probe(base_url, target, **kwargs):
        probed.append((base_url, target.path, target.expected_statuses))
        return {"ok": target.path == "/demo/", "status": 302, "elapsed_ms": 4,
                "detail": "HTTP 302"}

    monkeypatch.setattr(D, "probe_target", fake_probe)
    section = _service(tmp_path, registry_path=registry).applications_section(
        "http://127.0.0.1:8811", NOW)
    assert sorted(probed) == [("http://127.0.0.1:8811", "/", (200,)),
                              ("http://127.0.0.1:8811", "/demo/", (200, 302))]
    statuses = {c["name"]: c["status"] for c in section["checks"]}
    assert statuses == {"Demo /demo/": "healthy", "CryoStack site /": "failed"}
    assert section["kind"] == "live"


def test_real_registry_targets_are_all_probed(tmp_path, monkeypatch):
    probed = []
    monkeypatch.setattr(D, "probe_target", lambda base, target, **k: probed.append(target.path) or
                        {"ok": True, "status": 200, "elapsed_ms": 1, "detail": "HTTP 200"})
    _service(tmp_path).applications_section("http://127.0.0.1:8811", NOW)
    assert {"/", "/icesheets/", "/icesee-gui/", "/frozen-legacies/", "/livist/",
            "/livist/docs/"} <= set(probed)
