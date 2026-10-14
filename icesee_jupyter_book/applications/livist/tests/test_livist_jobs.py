"""LIVIST jobs: store lifecycle, worker (generator mocked at the subprocess
boundary), bounded logs, validation, inputs and the environment's isolation."""
import json
import struct
import threading
import time
from pathlib import Path

import pytest

from icesee_jupyter_book.applications.livist import (
    manifest,
    publication,
    sources,
    toolchain,
    validation,
    worker,
)
from icesee_jupyter_book.applications.livist.store import JobLimitError, LivistStore

from livist_test_support import SECRET, fake_popen, not_ready_health, use_ready_toolchain
from livist_fake_generate import pmtiles


@pytest.fixture
def store(tmp_path):
    return LivistStore(tmp_path / "livist.db")


@pytest.fixture
def local_input(tmp_path, monkeypatch):
    root = tmp_path / "inputs"
    root.mkdir()
    (root / "sample.csv").write_text("x,y,atten_rate_C0\n1,2,5.4\n")
    monkeypatch.setenv("CRYOSTACK_LIVIST_INPUT_ROOTS", str(root))
    return root / "sample.csv"


def _queue(store, tmp_path, rows, *, job_id="a" * 32, timeout_s=600, prepare=None):
    workdir = tmp_path / "ws" / job_id
    workdir.mkdir(parents=True)
    if prepare:
        prepare(workdir)
    store.queue_job(job_id=job_id, owner_id="u1", workdir=str(workdir), sources=rows,
                    timeout_s=timeout_s, max_active=4)
    return workdir


def _local_row(path):
    return {"name": "sample", "kind": "local", "location": str(path)}


# ── store ───────────────────────────────────────────────────────────
def test_store_limits_and_lifecycle(store):
    store.queue_job(job_id="1" * 32, owner_id="u1", workdir="/w1", sources=[], timeout_s=60,
                    max_active=2)
    with pytest.raises(JobLimitError):        # one active job per user
        store.queue_job(job_id="2" * 32, owner_id="u1", workdir="/w2", sources=[],
                        timeout_s=60, max_active=2)
    store.queue_job(job_id="3" * 32, owner_id="u2", workdir="/w3", sources=[], timeout_s=60,
                    max_active=2)
    with pytest.raises(JobLimitError):        # host capacity
        store.queue_job(job_id="4" * 32, owner_id="u3", workdir="/w4", sources=[],
                        timeout_s=60, max_active=2)
    assert store.claim_job("1" * 32, 4242)
    assert not store.claim_job("1" * 32, 4242)
    assert store.request_cancel("3" * 32)["status"] == "cancelled"   # queued: at once
    assert store.heartbeat("1" * 32) is False
    store.request_cancel("1" * 32)
    assert store.heartbeat("1" * 32) is True
    assert [j["job_id"] for j in store.list_jobs(owner_id="u2")] == ["3" * 32]


def test_reconcile_marks_dead_workers_interrupted(store):
    store.queue_job(job_id="1" * 32, owner_id="u1", workdir="/w", sources=[], timeout_s=60,
                    max_active=2)
    store.claim_job("1" * 32, 999999)
    assert store.reconcile_jobs(is_alive=lambda pid: True) == []
    assert store.reconcile_jobs(is_alive=lambda pid: False) == ["1" * 32]
    job = store.get_job("1" * 32)
    assert job["status"] == "interrupted" and "restart" in job["error"]


# ── worker ──────────────────────────────────────────────────────────
def test_worker_runs_generate_in_job_dir_with_clean_env(store, tmp_path, local_input,
                                                         monkeypatch):
    use_ready_toolchain(monkeypatch)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SECRET)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", SECRET)
    workdir = _queue(store, tmp_path, [_local_row(local_input)])
    calls = []
    assert worker.run(store, "a" * 32, popen=fake_popen(calls)) == "completed"

    call = calls[0]
    assert call["cwd"] == str(workdir) and call["start_new_session"] is True
    assert call["command"][:3] == ["nice", "-n", "10"]
    child_env = json.loads((workdir / "env.json").read_text())
    assert SECRET not in json.dumps(child_env)
    assert not any(k.startswith(("AWS_", "GOOGLE_", "GITHUB_", "ORCID_")) for k in child_env)
    assert child_env["UV_NO_SYNC"] == "1" and child_env["UV_FROZEN"] == "1"
    assert child_env["UV_PROJECT_ENVIRONMENT"].endswith("venv")

    config = (workdir / "config.toml").read_text()
    assert 'sample = "local/sample.csv"' in config and 'data_directory = "data"' in config
    assert (workdir / "data" / "local" / "sample.csv").resolve() == local_input.resolve()

    job = store.get_job("a" * 32)
    assert job["status"] == "completed" and job["exit_code"] == 0
    assert job["validation_status"] == "warnings"         # deep checks need the real env
    data = manifest.read(workdir)
    assert data["config_sha256"] == job["config_sha256"]
    names = {a["name"] for a in data["artifacts"]}
    assert set(validation.expected_products(["sample"])) | {"temperature-sources.json"} == names
    assert all(len(a["sha256"]) == 64 for a in data["artifacts"])
    assert data["inputs"][0]["sha256"] and str(local_input) not in json.dumps(data)
    assert "MIT" in data["attribution"]["software"]
    log = (workdir / "logs" / "generate.log").read_text()
    assert "input sample: present" in log and "finished: completed" in log


def test_worker_reports_generator_failure(store, tmp_path, local_input, monkeypatch):
    use_ready_toolchain(monkeypatch)
    _queue(store, tmp_path, [_local_row(local_input)],
           prepare=lambda w: (w / "fail").write_text("1"))
    assert worker.run(store, "a" * 32, popen=fake_popen()) == "failed"
    job = store.get_job("a" * 32)
    assert job["exit_code"] == 3 and "exited with status 3" in job["error"]
    assert job["validation_status"] is None


def test_worker_refuses_when_environment_missing(store, tmp_path, local_input, monkeypatch):
    monkeypatch.setattr(toolchain, "health", not_ready_health)
    calls = []
    _queue(store, tmp_path, [_local_row(local_input)])
    assert worker.run(store, "a" * 32, popen=fake_popen(calls)) == "failed"
    assert calls == []
    assert "GDAL (Geo)Parquet driver" in store.get_job("a" * 32)["error"]


def test_worker_cancellation_kills_process_group(store, tmp_path, local_input, monkeypatch):
    use_ready_toolchain(monkeypatch)
    monkeypatch.setattr(worker, "HEARTBEAT_S", 0.2)
    _queue(store, tmp_path, [_local_row(local_input)],
           prepare=lambda w: (w / "sleep").write_text("60"))
    threading.Timer(1.0, lambda: store.request_cancel("a" * 32)).start()
    started = time.monotonic()
    assert worker.run(store, "a" * 32, popen=fake_popen()) == "cancelled"
    assert time.monotonic() - started < 30
    assert store.get_job("a" * 32)["status"] == "cancelled"


def test_worker_timeout(store, tmp_path, local_input, monkeypatch):
    use_ready_toolchain(monkeypatch)
    _queue(store, tmp_path, [_local_row(local_input)], timeout_s=1,
           prepare=lambda w: (w / "sleep").write_text("60"))
    assert worker.run(store, "a" * 32, popen=fake_popen()) == "timed_out"
    assert "time limit" in store.get_job("a" * 32)["error"]


def test_worker_rejects_input_moved_outside_roots(store, tmp_path, local_input, monkeypatch):
    use_ready_toolchain(monkeypatch)
    _queue(store, tmp_path, [_local_row(local_input)])
    monkeypatch.setenv("CRYOSTACK_LIVIST_INPUT_ROOTS", str(tmp_path / "elsewhere"))
    calls = []
    assert worker.run(store, "a" * 32, popen=fake_popen(calls)) == "failed"
    assert calls == [] and "outside the approved" in store.get_job("a" * 32)["error"]


def test_bounded_log_keeps_head_and_tail(tmp_path):
    log = worker.BoundedLog(tmp_path / "log", head=10, tail=10)
    log.write(b"HEADHEADHE" + b"m" * 1000 + b"TAILTAIL!!")
    log.close()
    text = (tmp_path / "log").read_bytes()
    assert text.startswith(b"HEADHEADHE") and text.endswith(b"TAILTAIL!!")
    assert b"1,000 bytes of output omitted" in text and len(text) < 100


# ── validation ──────────────────────────────────────────────────────
def test_pmtiles_header_parsing():
    header = validation.parse_pmtiles_header(pmtiles())
    assert header["tile_type"] == 1 and header["max_zoom"] == 4
    assert header["bounds"][1] == pytest.approx(-80.0)
    with pytest.raises(ValueError):
        validation.parse_pmtiles_header(b"PMTiles\x02" + b"\0" * 200)
    with pytest.raises(ValueError):
        validation.parse_pmtiles_header(b"not tiles")


def _products(workdir, names=("sample",)):
    (workdir / "data").mkdir(parents=True, exist_ok=True)
    for name in names:
        for mode in validation.MODES:
            stem = workdir / "data" / f"temperature-{name}-{mode}"
            Path(f"{stem}.parquet").write_bytes(b"PAR1xxxxPAR1")
            Path(f"{stem}-wgs84.parquet").write_bytes(b"PAR1xxxxPAR1")
            Path(f"{stem}.fgb").write_bytes(b"fgb\x03fgb\x01" + b"\0" * 8)
            Path(f"{stem}.pmtiles").write_bytes(pmtiles())
    public = workdir / "frontend" / "public"
    public.mkdir(parents=True, exist_ok=True)
    (public / "temperature-sources.json").write_text(json.dumps(
        {m: [{"name": n, "url": "u"} for n in names] for m in validation.MODES}))


def _deep(crs_wgs84="EPSG:4326", rows=(10, 10), tmin=240.0):
    def fake(files, env):
        out = {}
        for path in files:
            wgs = path.name.endswith("-wgs84.parquet")
            out[path.name] = {
                "rows": rows[1] if wgs else rows[0],
                "columns": {"temperature": "double", "attenuation": "double",
                            "geometry": "binary"},
                "geo": {"primary_column": "geometry", "encoding": "WKB",
                        "crs": crs_wgs84 if wgs else "EPSG:3031", "crs_name": "x"},
                "temperature": {"finite": 10, "min": tmin, "max": 260.0},
            }
        return out
    return fake


def test_validation_passes_and_detects_problems(tmp_path, monkeypatch):
    _products(tmp_path)
    monkeypatch.setattr(validation, "_fgb_count", lambda path, env: (10, "EPSG:4326"))
    monkeypatch.setattr(validation, "_deep_parquet", _deep())
    assert validation.validate(tmp_path, ["sample"])["status"] == "passed"

    monkeypatch.setattr(validation, "_deep_parquet", _deep(crs_wgs84="EPSG:3031"))
    result = validation.validate(tmp_path, ["sample"])
    assert result["status"] == "failed"
    assert any(c["check"] == "crs" and c["level"] == "error" for c in result["checks"])

    monkeypatch.setattr(validation, "_deep_parquet", _deep(rows=(10, 9)))
    assert any(c["check"] == "rows-match" and c["level"] == "error"
               for c in validation.validate(tmp_path, ["sample"])["checks"])

    monkeypatch.setattr(validation, "_deep_parquet", _deep(tmin=100.0))
    assert validation.validate(tmp_path, ["sample"])["status"] == "warnings"

    monkeypatch.setattr(validation, "_deep_parquet", _deep())
    (tmp_path / "data" / "temperature-sample-pure-ice.pmtiles").write_bytes(b"junk")
    (tmp_path / "data" / "temperature-sample-conductivity.fgb").unlink()
    checks = validation.validate(tmp_path, ["sample"])["checks"]
    assert any(c["check"] == "pmtiles-header" and c["level"] == "error" for c in checks)
    assert any(c["artifact"] == "temperature-sample-conductivity.fgb" and c["check"] == "present"
               for c in checks)


def test_validation_without_environment_is_explicit(tmp_path, monkeypatch):
    _products(tmp_path)
    monkeypatch.setenv("CRYOSTACK_LIVIST_ENV", str(tmp_path / "no-env"))
    result = validation.validate(tmp_path, ["sample"])
    assert result["deep"] is False and result["status"] == "warnings"
    assert any(c["check"] == "deep-checks" for c in result["checks"])


# ── inputs ──────────────────────────────────────────────────────────
def test_candidates_come_from_upstream_config_and_approved_roots(tmp_path, monkeypatch):
    root = tmp_path / "roots"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "Wais Divide.txt").write_text("x")
    (root / "notes.md").write_text("x")
    (root / ".hidden.csv").write_text("x")
    outside = tmp_path / "outside.csv"
    outside.write_text("x")
    (root / "link.csv").symlink_to(outside)
    monkeypatch.setenv("CRYOSTACK_LIVIST_INPUT_ROOTS", str(root))
    found = sources.candidates()
    kinds = {(c["kind"], Path(c["location"]).name) for c in found}
    assert ("source-coop", "depth-avg-attenuation-ASE.txt") in kinds
    assert ("local", "Wais Divide.txt") in kinds
    assert not any(n in ("notes.md", ".hidden.csv", "link.csv", "outside.csv") for _k, n in kinds)
    local = next(c for c in found if c["kind"] == "local")
    assert local["suggested_name"] == "wais-divide"
    assert str(tmp_path) not in json.dumps([sources.public_candidate(c) for c in found])
    with pytest.raises(sources.SourceError):
        sources.resolve_local(str(outside))
    with pytest.raises(sources.SourceError):
        sources.resolve_local(str(root / "link.csv"))


def test_source_coop_keys_and_config_rendering():
    assert sources.valid_source_coop_key("englacial/ice-sheet-temperature/A/b.txt")
    for bad in ("other/x.txt", "englacial/ice-sheet-temperature/../x", "/englacial/x",
                "englacial/ice-sheet-temperature//x"):
        with pytest.raises(sources.SourceError):
            sources.valid_source_coop_key(bad)
    with pytest.raises(sources.SourceError):
        sources.render_config("b", {"Bad Name": "k"})
    with pytest.raises(sources.SourceError):
        sources.render_config("b", {"ok": 'k"\n[x]'})


def test_job_environment_is_built_from_scratch(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", SECRET)
    env = toolchain.job_environment(tmp_path)
    assert SECRET not in json.dumps(env)
    assert env["HOME"] == str(tmp_path / "tmp") and env["UV_OFFLINE"] == "1"


# ── publication planning ────────────────────────────────────────────
def test_publication_plan_mirrors_scripts_upload(tmp_path, monkeypatch):
    _products(tmp_path)
    job = {"job_id": "a" * 32, "status": "completed", "validation_status": "passed"}
    recorded = {"artifacts": manifest.artifacts(tmp_path), "livist": {"commit": "c" * 40}}
    probe = lambda url: {"exists": url.endswith("pure-ice.pmtiles")}
    plan = publication.plan(job, tmp_path, recorded, probe=probe)
    names = [f["name"] for f in plan["files"]]
    assert names == ["temperature-sample-conductivity.parquet",
                     "temperature-sample-conductivity.pmtiles",
                     "temperature-sample-pure-ice.parquet",
                     "temperature-sample-pure-ice.pmtiles"]
    assert plan["overwrites"] == ["temperature-sample-pure-ice.pmtiles"]
    assert "temperature-sample-pure-ice-wgs84.parquet" in plan["not_uploaded"]
    assert plan["blocking"] == [] and plan["dry_run"] is True
    assert all(f["destination"].startswith("s3://us-west-2.opendata.source.coop/englacial/")
               for f in plan["files"])

    (tmp_path / "data" / "temperature-sample-pure-ice.parquet").write_bytes(b"PAR1changedPAR1")
    plan = publication.plan(job, tmp_path, recorded, probe=probe)
    assert any("changed" in b for b in plan["blocking"])
    failed = publication.plan({**job, "validation_status": "failed"}, tmp_path, recorded,
                              probe=probe)
    assert any("validation" in b for b in failed["blocking"])


def test_execute_is_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("CRYOSTACK_LIVIST_PUBLICATION_ENABLED", raising=False)

    def never():
        raise AssertionError("no S3 client may be created")

    with pytest.raises(publication.PublicationDisabled):
        publication.execute({"files": [], "target": "s3://b/p"}, tmp_path, allow_overwrite=False,
                            client_factory=never)


def test_pmtiles_struct_layout_matches_spec():
    raw = pmtiles(lat=-60.5)
    assert struct.unpack_from("<i", raw, 114)[0] == int(-60.5e7)
