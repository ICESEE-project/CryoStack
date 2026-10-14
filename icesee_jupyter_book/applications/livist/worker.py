"""LIVIST generation worker: one process per job.

The gateway queues a job (``livist_jobs``, status ``queued``) and starts::

    python -m icesee_jupyter_book.applications.livist.worker --db <livist.db> --job <id>

The worker claims the job with its PID, writes the job's ``config.toml``
(approved inputs only), stages local inputs, and runs LIVIST's own
``scripts/generate`` -- unmodified -- in the job directory with the isolated
environment (:func:`toolchain.job_environment`). It keeps a heartbeat, honours
cancellation (``cancel_requested`` or SIGTERM) and the job timeout by
terminating the whole process group, bounds the log, then validates the
products and writes ``manifest.json``.

A worker that dies is detected by the gateway (stale heartbeat or dead PID)
and its job marked ``interrupted``; the generator's PID is recorded so the
gateway can stop a generator such a worker left behind.

Failure handling: the heartbeat runs from claim to finish (also while inputs
are staged and products validated and hashed); a job does not start without
the free-space reserve and is stopped when free space falls below half of it;
every way out of the worker records a final status with a reason that names
no server path; the worker's own diagnostics never fail a job (the gateway
that reads them may have restarted); only a completed job's manifest lists
products -- other jobs list their files as partial.
"""
from __future__ import annotations

import argparse
import collections
import email.utils
import hashlib
import os
import resource
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import input_cache, manifest, settings, sources, toolchain, validation
from .store import LivistStore

HEARTBEAT_S = 5.0
KILL_GRACE_S = 15.0
LOG_HEAD_BYTES = 1 << 20
LOG_TAIL_BYTES = 256 << 10
LOG_NAME = "generate.log"
FINISH_ATTEMPTS = 3


def _note(text: str) -> None:
    """A diagnostic line for the gateway's log. The gateway may have restarted
    (its end of the pipe is closed); that must never change the job."""
    try:
        print(f"[livist-worker] {text}", file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


def free_bytes(path: Path) -> int:
    """Free space on the file system holding ``path`` (or its nearest
    existing parent)."""
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    return shutil.disk_usage(path).free


def space_problem(path: Path, needed: int) -> str | None:
    free = free_bytes(path)
    if free >= needed:
        return None
    return (f"Not enough free disk space for a LIVIST generation: {free >> 20:,} MB free, "
            f"{needed >> 20:,} MB required.")


def _reason(failure: BaseException) -> str:
    """A job's failure reason: CryoStack's own messages as they are, file
    system errors without the path they carry."""
    if isinstance(failure, OSError):
        return ("A file system error stopped the job ("
                + (failure.strerror or type(failure).__name__) + ").")
    if isinstance(failure, (sources.SourceError, RuntimeError)):
        return str(failure)[:500]
    return f"An internal error stopped the job ({type(failure).__name__})."


class _Heartbeat(threading.Thread):
    """Records liveness from claim to finish and turns a cancellation
    request into ``stop``."""

    def __init__(self, store: LivistStore, job_id: str, stop: threading.Event):
        super().__init__(daemon=True, name=f"livist-heartbeat-{job_id[:8]}")
        self.store, self.job_id, self.stop = store, job_id, stop
        self.done = threading.Event()

    def run(self) -> None:
        while not self.done.wait(HEARTBEAT_S):
            try:
                if self.store.heartbeat(self.job_id):
                    self.stop.set()
            except Exception as beat_error:          # a busy database must not stop the job
                _note(f"heartbeat not recorded: {type(beat_error).__name__}")


class BoundedLog:
    """Keeps the first ``head`` bytes and the last ``tail`` bytes of a stream."""

    def __init__(self, path: Path, *, head: int = LOG_HEAD_BYTES, tail: int = LOG_TAIL_BYTES):
        self.path = path
        self.head = head
        self.written = 0
        self.dropped = 0
        self.tail: collections.deque = collections.deque()
        self.tail_size = 0
        self.tail_limit = tail
        self.failed = False                 # the disk refused a write; output is dropped
        self.handle = path.open("wb")

    def write(self, chunk: bytes) -> None:
        room = self.head - self.written
        if room > 0:
            try:
                self.handle.write(chunk[:room])
                self.handle.flush()
            except OSError:
                self.failed = True
            self.written += min(room, len(chunk))
            chunk = chunk[room:]
        if chunk:
            self.tail.append(chunk)
            self.tail_size += len(chunk)
            while self.tail_size > self.tail_limit and self.tail:
                first = self.tail[0]
                excess = self.tail_size - self.tail_limit
                if len(first) <= excess:
                    self.tail.popleft()
                    self.tail_size -= len(first)
                    self.dropped += len(first)
                else:
                    self.tail[0] = first[excess:]
                    self.tail_size -= excess
                    self.dropped += excess

    def line(self, text: str) -> None:
        self.write(f"[cryostack] {text}\n".encode())

    def close(self) -> None:
        try:
            if self.dropped:
                self.handle.write(f"\n[cryostack] … {self.dropped:,} bytes of output omitted …\n"
                                  .encode())
            for chunk in self.tail:
                self.handle.write(chunk)
        except OSError:
            self.failed = True
        finally:
            try:
                self.handle.close()
            except OSError:
                self.failed = True


def _pump(stream, log: BoundedLog, lock: threading.Lock) -> None:
    # keeps draining even when the log cannot be written, so LIVIST never
    # blocks on a full pipe
    for chunk in iter(lambda: stream.read1(65536), b""):
        with lock:
            log.write(chunk)


def _terminate(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        process.wait(timeout=KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        process.wait()


def prepare(job: dict, workdir: Path, *, source: Path | None = None) -> tuple[str, dict]:
    """Write config.toml and stage inputs; return (config sha256, staged keys)."""
    for sub in ("data", "frontend/public", "logs", "tmp"):
        (workdir / sub).mkdir(parents=True, exist_ok=True)
    upstream = sources.upstream_config(source)
    if not upstream["borehole_path"]:
        raise sources.SourceError("LIVIST's config.toml has no borehole_path.")
    staged = {row["name"]: sources.stage(row, workdir / "data") for row in job["sources"]}
    text = sources.render_config(upstream["borehole_path"], staged)
    (workdir / "config.toml").write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), staged


def generate_command(source: Path | None = None) -> list[str]:
    script = (source or settings.source_dir()) / "scripts" / "generate"
    return ["nice", "-n", "10", "sh", str(script)]


def measure(started: float, before: resource.struct_rusage, workdir: Path) -> dict:
    """What the LIVIST process tree actually used (not what was requested):
    wall time, CPU time and peak resident memory of the largest process,
    from the kernel's accounting of finished children, and the job
    directory's size on disk."""
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    size = 0
    for path in workdir.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                size += path.stat().st_size
        except OSError:
            pass
    return {"measured": True,
            "wall_s": round(time.monotonic() - started, 1),
            "cpu_user_s": round(after.ru_utime - before.ru_utime, 1),
            "cpu_system_s": round(after.ru_stime - before.ru_stime, 1),
            # ru_maxrss is in KiB on Linux, the peak of the largest single process
            "peak_rss_mb": round(after.ru_maxrss / 1024, 1),
            "workdir_bytes": size}


def stage_cached_inputs(job: dict, workdir: Path, staged: dict, cache) -> dict:
    """Put verified cached copies of source.coop inputs where LIVIST looks
    first; returns ``{input name: cache result}``."""
    results = {}
    for row in job["sources"]:
        key = staged.get(row["name"])
        if row["kind"] != "source-coop" or not key:
            continue
        try:
            results[row["name"]] = cache.stage(key, workdir / "data" / key)
        except input_cache.CacheBusy as failure:
            results[row["name"]] = {"cache": "busy", "reason": str(failure)}
        except (OSError, sources.SourceError, ValueError) as failure:
            results[row["name"]] = {"cache": "error", "reason": _reason(failure)[:200]}
    return results


def _http_date(timestamp: float) -> str:
    return email.utils.formatdate(timestamp, usegmt=True)


def input_identity(row: dict, record: dict, staged: Path | None, cached: dict | None,
                   stored: dict | None) -> dict:
    """The identity of an input as CryoStack observed it for this job: the
    content (size, SHA-256 of the file LIVIST read) and, for source.coop, the
    object's ETag / Last-Modified with how and whether source.coop was asked."""
    out = {"recorded": True, "sha256": record.get("sha256"), "size": record.get("size"),
           "etag": None, "last_modified": None, "upstream_size": None,
           "upstream_checked": False, "observed_at": time.time()}
    if row["kind"] != "source-coop":
        try:
            target = staged.resolve() if staged is not None else None
            out["last_modified"] = _http_date(target.stat().st_mtime) if target else None
        except OSError:
            pass
        out["observed"] = "approved local file (no upstream object)"
        return out
    after = (stored or {}).get("upstream") or {}
    before = (cached or {}).get("upstream") or {}
    if after.get("answered"):
        seen, out["observed"] = after, "source.coop HEAD after the job's download"
    elif before.get("answered"):
        seen, out["observed"] = before, "source.coop HEAD before the run"
    elif before.get("from_cache_record"):
        seen, out["observed"] = before, ("shared cache record (source.coop not reachable; "
                                         "the verified cached copy was used)")
    else:
        seen, out["observed"] = {}, "source.coop was not asked or did not answer"
    out.update(etag=seen.get("etag"), last_modified=seen.get("last_modified"),
               upstream_size=seen.get("size"), upstream_checked=bool(seen.get("answered")))
    return out


def run(store: LivistStore, job_id: str, *, popen=subprocess.Popen,
        env: Path | None = None, source: Path | None = None, cache=None) -> str:
    job = store.get_job(job_id)
    if job is None:
        raise SystemExit(f"job {job_id} does not exist")
    if not store.claim_job(job_id, os.getpid()):
        raise SystemExit(f"job {job_id} is not queued (status {job['status']})")
    stop = threading.Event()
    try:
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
    except ValueError:                      # not the main thread (embedded use, tests)
        pass
    beat = _Heartbeat(store, job_id, stop)
    beat.start()
    try:
        return _run_claimed(store, job, stop, popen=popen, env=env, source=source, cache=cache)
    finally:
        beat.done.set()


def _run_claimed(store: LivistStore, job: dict, stop: threading.Event, *, popen,
                 env: Path | None, source: Path | None, cache) -> str:
    job_id = job["job_id"]
    workdir = Path(job["workdir"])
    config_sha = None
    staged: dict = {}
    cache = cache if cache is not None else input_cache.InputCache()
    cached: dict = {}
    resources = None
    status, exit_code, error = "failed", None, None
    log = None
    process = None
    reserve = settings.job_reserve_bytes()
    try:
        health = toolchain.health(env=env, source=source, refresh=True)
        if not health["ready"]:
            failing = [c["label"] for c in health["checks"] if not c["ok"] and c["level"] == "error"]
            raise RuntimeError("The LIVIST environment is not ready: " + ", ".join(failing) + ".")
        short = space_problem(workdir, reserve)
        if short:
            raise RuntimeError(short)
        config_sha, staged = prepare(job, workdir, source=source)
        store.set_config_hash(job_id, config_sha)
        log = BoundedLog(workdir / "logs" / LOG_NAME)
        cached = stage_cached_inputs(job, workdir, staged, cache)
        for name, result in cached.items():
            log.line(f"input {name}: shared cache {result['cache']}"
                     + ("" if result.get("upstream_checked", True)
                        else " (source.coop not reachable; verified local copy used)"))
        lock = threading.Lock()
        command = generate_command(source)
        log.line("running LIVIST scripts/generate (" + ", ".join(staged) + ")")
        usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.monotonic()
        process = popen(command, cwd=str(workdir),
                        env=toolchain.job_environment(workdir, env=env, source=source),
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, start_new_session=True)
        try:
            store.set_generator_pid(job_id, process.pid)
        except Exception as failure:
            _note(f"generator pid not recorded: {type(failure).__name__}")
        pump = threading.Thread(target=_pump, args=(process.stdout, log, lock), daemon=True)
        pump.start()
        deadline = time.monotonic() + int(job["timeout_s"])
        next_space = 0.0
        outcome = None
        while process.poll() is None:
            now = time.monotonic()
            if stop.is_set():
                outcome = "cancelled"
            elif now >= deadline:
                outcome = "timed_out"
            elif reserve and now >= next_space:
                next_space = now + HEARTBEAT_S
                try:
                    if free_bytes(workdir) < reserve // 2:
                        outcome = "no_space"
                except OSError:
                    pass
            if outcome:
                with lock:
                    log.line({"cancelled": "cancelled; stopping LIVIST",
                              "timed_out": f"timed out after {job['timeout_s']} s; stopping LIVIST",
                              "no_space": "free disk space is running out; stopping LIVIST"}
                             [outcome])
                _terminate(process)
                break
            time.sleep(0.5)
        exit_code = process.wait()
        pump.join(timeout=10)
        resources = measure(started, usage_before, workdir)
        if outcome == "cancelled":
            status, error = "cancelled", "Cancelled."
        elif outcome == "timed_out":
            status, error = "timed_out", f"Stopped after the {job['timeout_s']} s time limit."
        elif outcome == "no_space":
            status, error = "failed", (f"Stopped because free disk space fell below "
                                       f"{(reserve // 2) >> 20:,} MB; files it wrote are partial.")
        elif exit_code == 0:
            status = "completed"
        else:
            status, error = "failed", f"LIVIST scripts/generate exited with status {exit_code}."
        if status == "completed" and log.failed:
            status, error = "failed", ("The generation log could not be written (is the disk "
                                       "full?); the products are not trusted.")
        with lock:
            log.line(f"finished: {status}")
    except Exception as failure:
        status, error = "failed", _reason(failure)
        if not isinstance(failure, (sources.SourceError, RuntimeError, OSError)):
            _note(f"job {job_id} stopped by {type(failure).__name__}: {failure}")
        if log is not None:
            log.line(f"error: {error}")
    finally:
        if process is not None and process.poll() is None:
            _terminate(process)             # never leave LIVIST running behind a failed worker
        if log is not None:
            log.close()

    check = None
    inputs = [{"name": row["name"], "kind": row["kind"]} for row in job["sources"]]
    try:
        if status == "completed":
            check = validation.validate(workdir, list(staged), env=env)
        inputs = [manifest.input_record(row, (workdir / "data" / staged[row["name"]])
                                        if row["name"] in staged else None)
                  for row in job["sources"]]
        for record in inputs:
            if record["name"] in cached:
                record["cache"] = {k: v for k, v in cached[record["name"]].items()
                                   if k in ("cache", "upstream_checked")}
        # downloaded source.coop inputs can be fetched again by key; keep their checksum
        # (and, from a completed job, one verified copy in the shared input cache)
        stored: dict = {}
        for row in job["sources"]:
            key = staged.get(row["name"])
            if row["kind"] == "source-coop" and key:
                path = workdir / "data" / key
                if (status == "completed" and path.is_file() and not path.is_symlink()
                        and cached.get(row["name"], {}).get("cache") != "hit"):
                    try:
                        stored[row["name"]] = cache.store(key, path)
                        record = next(r for r in inputs if r["name"] == row["name"])
                        record["cache"] = {"cache": stored[row["name"]]["cache"]}
                    except (OSError, sources.SourceError, ValueError,
                            input_cache.CacheBusy) as failure:
                        _note(f"input not cached: {_reason(failure)}")
                try:
                    path.unlink()
                except OSError:
                    pass
        for row, record in zip(job["sources"], inputs):
            key = staged.get(row["name"])
            record["identity"] = input_identity(
                row, record, (workdir / "data" / key) if key else None,
                cached.get(row["name"]), stored.get(row["name"]))
    except Exception as failure:
        if status == "completed":
            status, error = "failed", "Checking the products failed: " + _reason(failure)
        _note(f"job {job_id} post-processing: {type(failure).__name__}")

    for attempt in range(FINISH_ATTEMPTS):
        try:
            store.finish_job(job_id, status=status, exit_code=exit_code, error=error,
                             config_sha256=config_sha,
                             validation_status=check["status"] if check else None)
            break
        except Exception as failure:        # left running, the gateway marks it interrupted
            _note(f"job {job_id} final status not recorded: {type(failure).__name__}")
            time.sleep(1 + attempt)
    try:
        if workdir.is_dir():
            manifest.write(workdir, manifest.build(store.get_job(job_id), workdir=workdir,
                                                   inputs=inputs, config_sha256=config_sha,
                                                   check=check, env=env, resources=resources))
    except Exception as failure:
        _note(f"manifest not written: {_reason(failure)}")
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one LIVIST generation job.")
    parser.add_argument("--db", required=True, help="LIVIST database")
    parser.add_argument("--job", required=True, help="queued job ID")
    args = parser.parse_args(argv)
    status = run(LivistStore(args.db), args.job)
    _note(f"job {args.job}: {status}")
    return 0 if status in ("completed", "cancelled") else 1


if __name__ == "__main__":
    sys.exit(main())
