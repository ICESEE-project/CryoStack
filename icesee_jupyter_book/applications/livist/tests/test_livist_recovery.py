"""Input provenance in job manifests and failure recovery: a worker killed
mid-run, a gateway restart during a run, partially written job directories,
input cache lock contention, low disk, and retrying a failed job as a new
one. The generator is ``livist_fake_generate.py`` at the subprocess
boundary; nothing runs LIVIST or downloads anything."""
import fcntl
import json
import multiprocessing
import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from icesee_jupyter_book.applications.livist import (
    input_cache,
    manifest,
    products,
    routes,
    store as store_module,
    validation,
    worker,
)
from icesee_jupyter_book.applications.livist.store import LivistStore
from icesee_jupyter_book.applications.livist.workspace import (LivistWorkspace, new_job_id,
                                                               workspace_user_for)

from livist_test_support import SECRET, fake_popen, not_ready_health, use_ready_toolchain
from test_livist_routes import _approve_sample, _audit, _j, _login, _run, env  # noqa: F401

API = "/api/livist"
KEY = "englacial/ice-sheet-temperature/AttenuationRateData/depth-avg-attenuation-ASE.txt"
COOP = {"name": "ase", "kind": "source-coop", "location": KEY}
PARTIAL = "temperature-sample-pure-ice.parquet"


@pytest.fixture
def store(tmp_path):
    return LivistStore(tmp_path / "livist.db")


@pytest.fixture
def local_input(tmp_path, monkeypatch):
    root = tmp_path / "inputs"
    root.mkdir()
    (root / "sample.csv").write_text("x,y,atten_rate_C0\n1,2,5.4\n")
    monkeypatch.setenv("CRYOSTACK_LIVIST_INPUT_ROOTS", str(root))
    return {"name": "sample", "kind": "local", "location": str(root / "sample.csv")}


def _queue(store, tmp_path, rows, *, job_id=None, timeout_s=600, files=()):
    job_id = job_id or new_job_id()
    workdir = tmp_path / "ws" / job_id
    workdir.mkdir(parents=True)
    for name, text in dict(files).items():
        (workdir / name).parent.mkdir(parents=True, exist_ok=True)
        (workdir / name).write_text(text)
    store.queue_job(job_id=job_id, owner_id="u1", workdir=str(workdir), sources=rows,
                    timeout_s=timeout_s, max_active=8)
    return job_id, workdir


def _cache(tmp_path, head=None):
    return input_cache.InputCache(tmp_path / "cache", head=head or (lambda url: None))


def _dead_pid():
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    return done.pid


def _wait(predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _gone(pid):
    """Exited (a zombie no longer has a working directory)."""
    return routes._proc_cwd(pid) is None


# ── provenance ─────────────────────────────────────────────────────────
def test_manifest_records_upstream_identity_per_input(tmp_path, store, local_input,
                                                      monkeypatch):
    use_ready_toolchain(monkeypatch)
    meta = {"size": None, "etag": '"e1"', "last_modified": "Mon, 05 Oct 2026 10:00:00 GMT"}
    answering = {"on": True}
    cache = _cache(tmp_path, head=lambda url: dict(meta) if answering["on"] else None)
    meta["size"] = len("x,y,atten_rate_C0\n" + "1,2,5.4\n" * 1000)

    def run_job(rows):
        job_id, workdir = _queue(store, tmp_path, rows)
        assert worker.run(store, job_id, popen=fake_popen(), cache=cache) == "completed"
        return manifest.read(workdir)

    first = run_job([COOP, local_input])               # downloaded by LIVIST, then cached
    second = run_job([COOP])                           # cache hit, source.coop answered
    answering["on"] = False
    third = run_job([COOP])                            # cache hit, source.coop unreachable

    assert first["schema"] == 2 and first["complete"] is True and first["partial_files"] == []
    coop, local = first["inputs"]
    ident = coop["identity"]
    assert ident["recorded"] is True and ident["etag"] == '"e1"'
    assert ident["last_modified"] == meta["last_modified"] and ident["upstream_size"] == meta["size"]
    assert ident["upstream_checked"] is True and "after the job's download" in ident["observed"]
    assert ident["sha256"] == coop["sha256"] and ident["size"] == coop["size"] == meta["size"]
    assert local["identity"]["etag"] is None and local["identity"]["last_modified"].endswith("GMT")
    assert local["identity"]["sha256"] == local["sha256"]
    assert local_input["location"] not in json.dumps(first)          # still masked

    hit = second["inputs"][0]["identity"]
    assert second["inputs"][0]["cache"]["cache"] == "hit"
    assert hit["etag"] == '"e1"' and hit["upstream_checked"] is True
    assert hit["observed"] == "source.coop HEAD before the run"
    offline = third["inputs"][0]["identity"]
    assert offline["upstream_checked"] is False and offline["etag"] == '"e1"'
    assert offline["observed"].startswith("shared cache record")
    assert hit["sha256"] == offline["sha256"] == ident["sha256"]


def test_old_manifest_shows_identity_not_recorded(env):
    user, ck = _login(env, "alice", "maintainer")
    ids = []
    for identity in (None, {"recorded": True, "etag": '"e9"', "last_modified": "Tue",
                            "upstream_checked": True, "observed": "source.coop HEAD before the run"}):
        job_id, workdir = _finished(user, "completed", inputs=[dict(
            COOP, size=3, sha256="d" * 64, **({"identity": identity} if identity else {}))])
        ids.append(job_id)

    async def script(client, app):
        detail = await _j(await client.get(f"{API}/jobs/{ids[0]}", cookies=ck))
        compared = await _j(await client.get(f"{API}/compare?jobs={ids[0]},{ids[1]}", cookies=ck))
        return detail, compared

    (status, detail), (cstatus, compared) = _run(env, script)
    assert status == 200 and cstatus == 200
    assert detail["manifest"]["inputs"][0]["identity"] == {
        "recorded": False, "etag": None, "last_modified": None, "upstream_size": None,
        "upstream_checked": None, "observed": "not recorded", "observed_at": None}
    assert detail["products"]["complete"] is True
    cells = compared["inputs"][0]["jobs"]
    assert [c["etag"] for c in cells] == [None, '"e9"']
    assert [c["identity_recorded"] for c in cells] == [False, True]
    assert any("was not recorded by " + ids[0][:8] in s for s in compared["statements"])


# ── jobs left in a known state ─────────────────────────────────────────
def _run_in_child(db_path, job_id):
    worker.run(LivistStore(db_path), job_id, popen=fake_popen())


def test_worker_killed_mid_run_is_interrupted_and_its_generator_stopped(
        tmp_path, store, local_input, monkeypatch):
    use_ready_toolchain(monkeypatch)
    job_id, workdir = _queue(store, tmp_path, [local_input], files={"sleep": "60"})
    child = multiprocessing.get_context("fork").Process(target=_run_in_child,
                                                        args=(str(store.path), job_id))
    child.start()
    try:
        assert _wait(lambda: store.get_job(job_id)["generator_pid"])
        generator = store.get_job(job_id)["generator_pid"]
        assert routes._proc_cwd(generator) == os.path.realpath(workdir)
        (workdir / "data" / PARTIAL).write_bytes(b"PAR1half")       # a partial product
        os.kill(child.pid, signal.SIGKILL)
        child.join(10)
        assert store.get_job(job_id)["status"] == "running"     # nothing recorded the death
        assert routes._pid_alive(generator)                     # LIVIST would keep running

        assert routes.reconcile(store) == [job_id]
        job = store.get_job(job_id)
        assert job["status"] == "interrupted" and job["error"] == store_module.WORKER_GONE
        assert _wait(lambda: _gone(generator), 10)              # the orphan was stopped
        assert routes.reconcile(store) == []                    # once only
        assert manifest.read(workdir) is None                   # nothing claims completion
    finally:
        if child.is_alive():
            child.kill()
            child.join()


def test_leftovers_are_signalled_only_when_provably_the_jobs(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(routes.os, "killpg", lambda pid, sig: sent.append((pid, sig)))
    monkeypatch.setattr(routes, "LEFTOVER_GRACE_S", 0.2)
    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    other = subprocess.Popen(sleeper, cwd=str(tmp_path), start_new_session=True)
    job_id = new_job_id()
    worker_like = subprocess.Popen(sleeper + [routes.WORKER_MODULE, "--job", job_id])
    try:
        elsewhere = tmp_path / "job"
        elsewhere.mkdir()
        # a reused PID running somewhere else, and a process that is not this job's worker
        routes._stop_leftovers({"job_id": job_id, "workdir": str(elsewhere),
                                "generator_pid": other.pid, "pid": other.pid})
        assert sent == [] and other.poll() is None
        routes._stop_leftovers({"job_id": "b" * 32, "workdir": str(elsewhere),
                                "generator_pid": None, "pid": worker_like.pid})
        assert worker_like.poll() is None                     # another job's worker
        routes._stop_leftovers({"job_id": job_id, "workdir": str(tmp_path),
                                "generator_pid": other.pid, "pid": worker_like.pid})
        assert sent[0] == (other.pid, signal.SIGTERM)
        assert worker_like.wait(10) == -signal.SIGTERM
    finally:
        for proc in (other, worker_like):
            proc.kill()
            proc.wait()


def test_gateway_restart_keeps_live_jobs_and_interrupts_dead_ones(env, monkeypatch):
    monkeypatch.setattr(worker, "HEARTBEAT_S", 0.2)
    user, ck = _login(env, "alice", "maintainer")
    _other, bob = _login(env, "bob", "maintainer")
    store = LivistStore()
    sample = {"name": "sample", "kind": "local", "location": str(env["roots"] / "sample.csv")}
    space = LivistWorkspace(workspace_user_for(user))
    live = new_job_id()
    live_dir = space.create_job_dir(live)
    (live_dir / "sleep").write_text("60")
    store.queue_job(job_id=live, owner_id=user.id, workdir=str(live_dir), sources=[sample],
                    timeout_s=600, max_active=8)
    # a live worker (this process) that keeps running across the restart
    result = {}
    thread = threading.Thread(target=lambda: result.update(
        status=worker.run(store, live, popen=fake_popen())))
    thread.start()
    assert _wait(lambda: store.get_job(live)["generator_pid"])
    dead = new_job_id()
    store.queue_job(job_id=dead, owner_id=user.id, workdir=str(space.create_job_dir(dead)),
                    sources=[sample], timeout_s=600, max_active=8, per_owner=2)
    store.claim_job(dead, _dead_pid())

    async def script(client, app):                      # startup ran reconciliation
        out = {"live": await _j(await client.get(f"{API}/jobs/{live}", cookies=ck)),
               "dead": await _j(await client.get(f"{API}/jobs/{dead}", cookies=ck)),
               "bob": (await client.get(f"{API}/jobs/{dead}", cookies=bob)).status}
        return out

    try:
        out = _run(env, script)
    finally:
        store.request_cancel(live)
        thread.join(30)
    assert out["live"][1]["status"] == "running"
    status, body = out["dead"]
    assert status == 200 and body["status"] == "interrupted"
    assert body["error"] == store_module.WORKER_GONE and body["retryable"] is True
    assert out["bob"] == 200                                # maintainers see it too
    assert result["status"] == "cancelled"                  # the live run ended normally
    assert str(env["tmp"]) not in json.dumps(body) and SECRET not in json.dumps(body)


def test_queued_never_started_and_silent_workers(store):
    store.queue_job(job_id="1" * 32, owner_id="u1", workdir="/w1", sources=[], timeout_s=60,
                    max_active=8)
    store.queue_job(job_id="2" * 32, owner_id="u2", workdir="/w2", sources=[], timeout_s=60,
                    max_active=8)
    store.claim_job("2" * 32, os.getpid())
    assert store.reconcile_jobs(stale_after_s=60, is_alive=lambda pid: True) == []
    with store._connect() as db:                        # two minutes without a heartbeat
        db.execute("UPDATE livist_jobs SET heartbeat_at = ?, created_at = ?",
                   (time.time() - 120, time.time() - 120))
    seen = []
    ended = store.reconcile_jobs(stale_after_s=60, is_alive=lambda pid: True,
                                 on_interrupted=lambda row: (seen.append(row["job_id"]), 1 / 0))
    assert sorted(ended) == sorted(seen) == ["1" * 32, "2" * 32]
    assert store.get_job("1" * 32)["error"] == store_module.NEVER_STARTED
    assert "no heartbeat for 60 s" in store.get_job("2" * 32)["error"]
    assert {store.get_job(i)["status"] for i in ("1" * 32, "2" * 32)} == {"interrupted"}


def test_heartbeat_continues_while_products_are_checked(tmp_path, store, local_input,
                                                        monkeypatch):
    use_ready_toolchain(monkeypatch)
    monkeypatch.setattr(worker, "HEARTBEAT_S", 0.1)
    beats = []
    real = validation.validate

    def slow_validate(workdir, names, env=None):
        beats.append(store.get_job(job_id)["heartbeat_at"])
        time.sleep(0.8)
        beats.append(store.get_job(job_id)["heartbeat_at"])
        return real(workdir, names, env=env)

    monkeypatch.setattr(validation, "validate", slow_validate)
    job_id, _workdir = _queue(store, tmp_path, [local_input])
    assert worker.run(store, job_id, popen=fake_popen()) == "completed"
    assert beats[1] > beats[0]


def test_worker_diagnostics_never_fail_a_job_after_a_gateway_restart(tmp_path, store,
                                                                     monkeypatch):
    use_ready_toolchain(monkeypatch)

    class ClosedPipe:
        def write(self, _text):
            raise BrokenPipeError(32, "Broken pipe")

        def flush(self):
            raise BrokenPipeError(32, "Broken pipe")

    class FailingCache:
        def stage(self, key, target):
            return {"cache": "miss"}

        def store(self, key, path):
            raise OSError(28, "No space left on device", str(path))

    monkeypatch.setattr(sys, "stderr", ClosedPipe())
    job_id, workdir = _queue(store, tmp_path, [COOP])
    assert worker.run(store, job_id, popen=fake_popen(), cache=FailingCache()) == "completed"
    assert store.get_job(job_id)["status"] == "completed" and manifest.read(workdir)["complete"]


def test_unexpected_errors_never_leave_a_job_or_generator_running(tmp_path, store, local_input,
                                                                  monkeypatch):
    use_ready_toolchain(monkeypatch)
    calls = {"n": 0}

    def broken_free_bytes(path):
        calls["n"] += 1
        if calls["n"] > 1:                                   # once LIVIST runs
            raise TypeError("unexpected")
        return 1 << 40

    monkeypatch.setattr(worker, "free_bytes", broken_free_bytes)
    job_id, _workdir = _queue(store, tmp_path, [local_input], files={"sleep": "60"})
    started = time.monotonic()
    assert worker.run(store, job_id, popen=fake_popen()) == "failed"
    job = store.get_job(job_id)
    assert time.monotonic() - started < 30
    assert job["error"] == "An internal error stopped the job (TypeError)."
    assert _gone(job["generator_pid"])

    monkeypatch.setattr(worker, "free_bytes", lambda path: 1 << 40)
    monkeypatch.setattr(validation, "validate",
                        lambda *a, **k: (_ for _ in ()).throw(KeyError("x")))
    job_id, workdir = _queue(store, tmp_path, [local_input])
    assert worker.run(store, job_id, popen=fake_popen()) == "failed"
    job = store.get_job(job_id)
    assert job["error"] == ("Checking the products failed: An internal error stopped the job "
                            "(KeyError).")
    data = manifest.read(workdir)
    assert data["complete"] is False and data["artifacts"] == [] and data["partial_files"]
    assert data["reason"] == job["error"]


def test_file_system_errors_name_no_server_path(tmp_path, store, local_input, monkeypatch):
    use_ready_toolchain(monkeypatch)

    def no_room(*_a, **_k):
        raise OSError(28, "No space left on device", str(tmp_path / "secret-place"))

    monkeypatch.setattr(worker, "prepare", no_room)
    job_id, _workdir = _queue(store, tmp_path, [local_input])
    assert worker.run(store, job_id, popen=fake_popen()) == "failed"
    error = store.get_job(job_id)["error"]
    assert error == "A file system error stopped the job (No space left on device)."


# ── partially written job directories ──────────────────────────────────
def _finished(user, status, *, inputs=None, artifacts=True, files=(PARTIAL,), corrupt=False):
    """A job of ``user`` that ended with ``status``; its manifest is written
    like an older worker did (artifacts listed even for a failed job)."""
    store = LivistStore()
    job_id = new_job_id()
    workdir = LivistWorkspace(workspace_user_for(user)).create_job_dir(job_id)
    store.queue_job(job_id=job_id, owner_id=user.id, workdir=str(workdir),
                    sources=[{"name": "ase", "kind": "source-coop", "location": KEY}],
                    timeout_s=60, max_active=100)
    store.claim_job(job_id, 0)
    (workdir / "data").mkdir()
    for name in files:
        (workdir / "data" / name).write_bytes(b"PAR1" + name.encode() + b"PAR1")
    store.finish_job(job_id, status=status, exit_code=None if status != "completed" else 0,
                     error=None if status == "completed" else "stopped",
                     validation_status="passed" if status == "completed" else None)
    if corrupt:
        (workdir / manifest.MANIFEST).write_text('{"schema": 1, "artif')
    else:
        manifest.write(workdir, {
            "schema": 1, "job_id": job_id, "status": status, "config_sha256": "c" * 64,
            "livist": {"commit": "a" * 40, "command": "scripts/generate", "environment": {}},
            "inputs": inputs or [dict(COOP, size=3, sha256="d" * 64)],
            "artifacts": manifest.artifacts(workdir) if artifacts else [],
            "validation": {"status": "passed", "deep": True, "checked_at": 1.0,
                           "checks": [{"artifact": n, "check": "magic", "level": "ok",
                                       "detail": ""} for n in files]}
            if status == "completed" else None,
        })
    return job_id, workdir


def test_partial_products_are_never_shown_as_complete(env):
    user, ck = _login(env, "alice", "maintainer")
    _b, bob = _login(env, "bob", "admin")
    interrupted, _w = _finished(user, "interrupted")
    done, _d = _finished(user, "completed")
    broken, _x = _finished(user, "completed", corrupt=True)

    async def script(client, app):
        out = {"detail": await _j(await client.get(f"{API}/jobs/{interrupted}", cookies=ck)),
               "file": (await client.get(f"{API}/jobs/{interrupted}/files/{PARTIAL}",
                                         cookies=ck)).status,
               "manifest_file": (await client.get(
                   f"{API}/jobs/{interrupted}/files/manifest.json", cookies=ck)).status,
               "done_file": (await client.get(f"{API}/jobs/{done}/files/{PARTIAL}",
                                              cookies=ck)).status,
               "compare": (await client.get(f"{API}/compare?jobs={done},{interrupted}",
                                            cookies=ck)).status,
               "validate": (await client.post(f"{API}/jobs/{interrupted}/validate",
                                              cookies=ck, json={})).status,
               "publish": await _j(await client.post(f"{API}/publications", cookies=bob,
                                                     json={"job_id": interrupted})),
               "broken": await _j(await client.get(f"{API}/jobs/{broken}", cookies=ck))}
        return out

    out = _run(env, script)
    status, body = out["detail"]
    table = body["products"]
    assert status == 200 and table["complete"] is False and table["downloadable"] is False
    assert table["note"] == products.PARTIAL_NOTE and table["validation"] is None
    assert [(p["name"], p["partial"], p["validation"], p["sha256"]) for p in table["products"]] \
        == [(PARTIAL, True, "partial", None)]
    assert out["file"] == 404 and out["manifest_file"] == 200 and out["done_file"] == 200
    assert out["compare"] == 409 and out["validate"] == 409
    assert out["publish"][0] == 409 and "has not completed" in out["publish"][1]["error"]
    bstatus, bbody = out["broken"]
    assert bstatus == 200 and bbody["manifest_missing"] is True and "products" not in bbody


def test_new_manifest_of_a_failed_job_lists_partial_files_only(tmp_path, store, local_input,
                                                                monkeypatch):
    use_ready_toolchain(monkeypatch)
    job_id, workdir = _queue(store, tmp_path, [local_input],
                             files={"fail": "1", f"data/{PARTIAL}": "PAR1half"})
    assert worker.run(store, job_id, popen=fake_popen()) == "failed"
    data = manifest.read(workdir)
    assert data["complete"] is False and data["artifacts"] == []
    assert data["partial_files"] == [{"name": PARTIAL, "size": 8}]
    assert data["reason"] == "LIVIST scripts/generate exited with status 3."
    table = products.product_table(workdir, data, status="failed")
    assert table["complete"] is False and table["products"][0]["partial"] is True


# ── input cache: lock contention, dead writers, inconsistencies ────────
def test_cache_lock_contention_times_out_and_the_job_does_without(tmp_path, store, monkeypatch):
    use_ready_toolchain(monkeypatch)
    monkeypatch.setattr(input_cache, "LOCK_TIMEOUT_S", 0.3)
    cache = _cache(tmp_path)
    cache.store(KEY, _write(tmp_path / "seed.txt", "x,y\n1,2\n"))
    before = (tmp_path / "cache" / "index.json").read_bytes()
    with (tmp_path / "cache" / ".lock").open("a") as held:     # another job holds the lock
        fcntl.flock(held, fcntl.LOCK_EX)
        started = time.monotonic()
        with pytest.raises(input_cache.CacheBusy):
            cache.stage(KEY, tmp_path / "x" / KEY)
        assert time.monotonic() - started < 5
        job_id, workdir = _queue(store, tmp_path, [COOP])
        assert worker.run(store, job_id, popen=fake_popen(), cache=cache) == "completed"
    record = manifest.read(workdir)["inputs"][0]
    assert record["cache"]["cache"] == "busy" and record["sha256"]
    log = (workdir / "logs" / "generate.log").read_text()
    assert "shared cache busy" in log and "input ase: download" in log
    assert (tmp_path / "cache" / "index.json").read_bytes() == before


def _hold_lock_forever(path):
    handle = open(path, "a")
    fcntl.flock(handle, fcntl.LOCK_EX)
    time.sleep(120)


def test_a_killed_lock_holder_releases_the_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(input_cache, "LOCK_TIMEOUT_S", 10)
    cache = _cache(tmp_path)
    cache.store(KEY, _write(tmp_path / "seed.txt", "x,y\n1,2\n"))
    holder = multiprocessing.get_context("fork").Process(
        target=_hold_lock_forever, args=(str(tmp_path / "cache" / ".lock"),))
    holder.start()
    try:
        time.sleep(0.5)
        threading.Timer(0.5, lambda: os.kill(holder.pid, signal.SIGKILL)).start()
        assert cache.stage(KEY, tmp_path / "job" / KEY)["cache"] == "hit"
    finally:
        holder.kill()
        holder.join()


def test_dead_writer_leftovers_and_lost_copies_are_cleaned(tmp_path):
    cache = _cache(tmp_path)
    cache.store(KEY, _write(tmp_path / "seed.txt", "x,y\n1,2\n"))
    root = tmp_path / "cache"
    (root / "blobs" / ".deadbeef.tmp").write_text("half a copy")
    (root / ".index.json.tmp").write_text("{")
    blob = root / "blobs" / cache.entries()[KEY]["sha256"]
    os.chmod(blob, 0o644)
    blob.unlink()                                       # the copy vanished
    assert cache.stage(KEY, tmp_path / "job" / KEY) == {"cache": "miss"}
    assert cache.entries() == {}
    assert not (root / "blobs" / ".deadbeef.tmp").exists()
    assert not (root / ".index.json.tmp").exists()


def test_cache_copy_failure_leaves_no_partial_blob(tmp_path, monkeypatch):
    cache = _cache(tmp_path)

    def full_disk(src, dst):
        with open(dst, "wb") as handle:
            handle.write(b"half")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(input_cache.shutil, "copyfile", full_disk)
    result = cache.store(KEY, _write(tmp_path / "seed.txt", "x,y\n1,2\n"))
    assert result["cache"] == "not-stored" and result["reason"] == "copy failed"
    assert list((tmp_path / "cache" / "blobs").iterdir()) == []
    assert cache.entries() == {}


def _write(path, text):
    path.write_text(text)
    return path


# ── low disk ───────────────────────────────────────────────────────────
def test_job_does_not_start_without_the_free_space_reserve(tmp_path, store, local_input,
                                                           monkeypatch):
    use_ready_toolchain(monkeypatch)
    monkeypatch.setenv("CRYOSTACK_LIVIST_JOB_RESERVE_MB", "2048")
    monkeypatch.setattr(worker, "free_bytes", lambda path: 100 << 20)
    calls = []
    job_id, workdir = _queue(store, tmp_path, [local_input])
    assert worker.run(store, job_id, popen=fake_popen(calls)) == "failed"
    assert calls == []
    assert store.get_job(job_id)["error"] == ("Not enough free disk space for a LIVIST "
                                              "generation: 100 MB free, 2,048 MB required.")
    assert manifest.read(workdir)["partial_files"] == []


def test_running_job_is_stopped_when_the_disk_fills(tmp_path, store, local_input, monkeypatch):
    use_ready_toolchain(monkeypatch)
    monkeypatch.setattr(worker, "HEARTBEAT_S", 0.1)
    monkeypatch.setenv("CRYOSTACK_LIVIST_JOB_RESERVE_MB", "100")
    free = {"bytes": 1 << 40}
    monkeypatch.setattr(worker, "free_bytes", lambda path: free["bytes"])
    job_id, workdir = _queue(store, tmp_path, [local_input], files={"sleep": "60"})
    threading.Timer(1.0, lambda: free.update(bytes=10 << 20)).start()
    started = time.monotonic()
    assert worker.run(store, job_id, popen=fake_popen()) == "failed"
    assert time.monotonic() - started < 30
    job = store.get_job(job_id)
    assert job["error"] == ("Stopped because free disk space fell below 50 MB; files it wrote "
                            "are partial.")
    assert _gone(job["generator_pid"])
    assert manifest.read(workdir)["artifacts"] == []
    assert "free disk space is running out" in (workdir / "logs" / "generate.log").read_text()


def test_a_full_disk_never_blocks_the_generator_through_its_log(tmp_path):
    log = worker.BoundedLog(tmp_path / "log", head=8, tail=8)

    class FullDisk:
        def write(self, _data):
            raise OSError(28, "No space left on device")

        flush = close = lambda self: None

    log.handle = FullDisk()
    read, write = os.pipe()

    def produce():                                      # more than a pipe buffer holds
        with os.fdopen(write, "wb") as out:
            out.write(b"y" * 200_000)

    producer = threading.Thread(target=produce)
    producer.start()
    with os.fdopen(read, "rb") as stream:
        worker._pump(stream, log, threading.Lock())     # drains everything, never raises
    producer.join(10)
    assert not producer.is_alive()
    log.line("finished")
    log.close()
    assert log.failed is True


def test_start_refused_below_the_free_space_reserve(env, monkeypatch):
    _m, maint = _login(env, "maint", "maintainer")
    monkeypatch.setenv("CRYOSTACK_LIVIST_JOB_RESERVE_MB", "2048")
    monkeypatch.setattr(worker, "free_bytes", lambda path: 1 << 20)

    async def script(client, app):
        await _approve_sample(client, maint)
        start = await _j(await client.post(f"{API}/jobs", cookies=maint,
                                           json={"sources": ["sample"]}))
        jobs = await _j(await client.get(f"{API}/jobs", cookies=maint))
        return start, jobs

    start, jobs = _run(env, script)
    assert start[0] == 409 and "Not enough free disk space" in start[1]["error"]
    assert jobs[1]["jobs"] == []


# ── retry ──────────────────────────────────────────────────────────────
def _interrupted_job(user, row, *, status="interrupted"):
    store = LivistStore()
    job_id = new_job_id()
    workdir = LivistWorkspace(workspace_user_for(user)).create_job_dir(job_id)
    store.queue_job(job_id=job_id, owner_id=user.id, workdir=str(workdir), sources=[row],
                    timeout_s=60, max_active=100)
    (workdir / "data").mkdir()
    (workdir / "data" / PARTIAL).write_bytes(b"PAR1half")
    if status == "queued":
        return job_id, workdir
    store.claim_job(job_id, _dead_pid())
    if status == "interrupted":
        routes.reconcile(store)
    elif status != "running":
        store.finish_job(job_id, status=status, exit_code=0 if status == "completed" else 3,
                         error=None if status == "completed" else "LIVIST failed.")
    return job_id, workdir


def test_retry_creates_a_new_linked_job_and_never_resumes(env):
    user, ck = _login(env, "alice", "maintainer")

    async def script(client, app):
        await _approve_sample(client, ck)
        row = {k: LivistStore().get_source("sample")[k] for k in ("name", "kind", "location")}
        old, old_dir = _interrupted_job(user, row)
        out = {"old": old, "old_dir": old_dir,
               "retry": await _j(await client.post(f"{API}/jobs/{old}/retry", cookies=ck,
                                                   json={}))}
        new = out["retry"][1]["job_id"]
        out["new"] = await _j(await client.get(f"{API}/jobs/{new}", cookies=ck))
        out["old_detail"] = await _j(await client.get(f"{API}/jobs/{old}", cookies=ck))
        out["again"] = await _j(await client.post(f"{API}/jobs/{old}/retry", cookies=ck,
                                                  json={}))
        return out

    out = _run(env, script)
    status, started = out["retry"]
    assert status == 202 and started["retry_of"] == out["old"] and started["job_id"] != out["old"]
    _s, new = out["new"]
    assert new["status"] == "completed" and new["retry_of"] == out["old"]
    assert new["retryable"] is False and new["products"]["complete"] is True
    assert new["sources"] == ["sample"]
    old = out["old_detail"][1]
    assert old["status"] == "interrupted" and old["retryable"] is True
    # the earlier directory is untouched; nothing of it was reused
    assert (out["old_dir"] / "data" / PARTIAL).read_bytes() == b"PAR1half"
    assert not (out["old_dir"] / "config.toml").exists()
    new_dir = out["old_dir"].parent / new["job_id"]
    assert manifest.read(new_dir)["retry_of"] == out["old"]
    assert out["again"][0] == 202                       # retrying again is another new job
    assert _audit(env).count("livist.job.retry") == 2


def test_retry_keeps_the_start_rules(env, monkeypatch):
    alice_user, alice = _login(env, "alice", "maintainer")
    dev_user, dev = _login(env, "devonly", "developer")
    _b, bob = _login(env, "bob", "admin")
    _p, plain = _login(env, "plain")

    async def script(client, app):
        await _approve_sample(client, alice)
        store = LivistStore()
        row = {k: store.get_source("sample")[k] for k in ("name", "kind", "location")}
        failed, _w = _interrupted_job(alice_user, row, status="failed")
        timed_out, _t = _interrupted_job(alice_user, row, status="timed_out")
        done, _d = _interrupted_job(alice_user, row, status="completed")
        cancelled, _c = _interrupted_job(alice_user, row, status="cancelled")
        dev_job, _x = _interrupted_job(dev_user, row, status="failed")
        post = lambda job, ck, **kw: client.post(f"{API}/jobs/{job}/retry", cookies=ck, **kw)
        out = {
            "anon": (await client.post(f"{API}/jobs/{failed}/retry", json={})).status,
            "plain": (await post(failed, plain, json={})).status,
            "developer": (await post(dev_job, dev, json={})).status,
            "other_maint": await _j(await post(failed, bob, json={})),
            "missing": await _j(await post(new_job_id(), alice, json={})),
            "cross": (await post(failed, alice, json={},
                                 headers={"Origin": "https://evil.example"})).status,
            "form": (await post(failed, alice, data="x=1",
                                headers={"Content-Type": "application/x-www-form-urlencoded"}
                                )).status,
            "completed": (await post(done, alice, json={})).status,
            "cancelled": (await post(cancelled, alice, json={})).status,
        }
        running, _r = _interrupted_job(alice_user, row, status="queued")
        out["active_status"] = (await post(running, alice, json={})).status
        out["limit"] = await _j(await post(failed, alice, json={}))   # alice has a queued job
        store.request_cancel(running)
        from icesee_jupyter_book.applications.livist import toolchain as tc
        monkeypatch.setattr(tc, "health", not_ready_health)
        out["not_ready"] = await _j(await post(failed, alice, json={}))
        use_ready_toolchain(monkeypatch)
        await client.post(f"{API}/sources/sample/status", cookies=alice, json={"enabled": False})
        out["disabled"] = await _j(await post(failed, alice, json={}))
        await client.post(f"{API}/sources/sample/status", cookies=alice, json={"enabled": True})
        with store._connect() as db:                    # re-approved elsewhere since it ran
            db.execute("UPDATE livist_sources SET location = ? WHERE name = 'sample'",
                       (str(env["roots"] / "other.csv"),))
        (env["roots"] / "other.csv").write_text("x,y,atten_rate_C0\n1,2,5.4\n")
        out["moved"] = await _j(await post(timed_out, alice, json={}))
        out["jobs"] = len(store.list_jobs(owner_id=alice_user.id))
        return out

    out = _run(env, script)
    assert out["anon"] == 401 and out["plain"] == 403 and out["developer"] == 403
    assert out["other_maint"] == (404, {"error": "Job not found."}) == out["missing"]
    assert out["cross"] == 403 and out["form"] == 415
    assert out["completed"] == out["cancelled"] == out["active_status"] == 409
    assert out["limit"][0] == 409 and "already have" in out["limit"][1]["error"]
    assert out["not_ready"][0] == 409 and "not ready" in out["not_ready"][1]["error"]
    assert out["disabled"][0] == 400 and "not an enabled" in out["disabled"][1]["error"]
    assert out["moved"][0] == 409 and "different location" in out["moved"][1]["error"]
    assert out["jobs"] == 5                             # no retry created a job
    assert "livist.job.retry" not in _audit(env)
