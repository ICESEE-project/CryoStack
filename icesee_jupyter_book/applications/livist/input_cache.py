"""Shared, verified cache of LIVIST's source.coop inputs.

LIVIST downloads an attenuation file from source.coop into its job's
``data/<key>`` unless the file is already there. A large input (the ASE file
is 339 MB) would otherwise be downloaded again for every job. This cache
keeps one copy per content hash and stages it into a new job before LIVIST
starts, so LIVIST finds it present and skips the download. LIVIST's code is
not changed.

Layout (``$CRYOSTACK_LIVIST_INPUT_CACHE``, default ``var/livist_input_cache``)::

    blobs/<sha256>      read-only file contents
    index.json          {key: {sha256, size, url, etag, last_modified, stored_at, used_at}}
    .lock               serialises writers (two jobs may finish together)

Rules:

* Only the file a *completed* job downloaded is stored; CryoStack never
  downloads anything itself.
* A cached file is staged only if its SHA-256 still matches the index.
* Before staging, the object's size/ETag on source.coop is checked (HEAD).
  If source.coop reports a different object, the cached copy is not used and
  LIVIST downloads the current one. If source.coop cannot be reached, the
  verified copy is used and the job's manifest records that upstream was not
  rechecked.
* The cache is bounded (``$CRYOSTACK_LIVIST_INPUT_CACHE_MB``, default 4096);
  the least recently used inputs are removed first.
* The lock is waited for at most ``LOCK_TIMEOUT_S``; a job that cannot get it
  does without the cache (LIVIST downloads the input itself). A writer that
  died leaves no lock behind (``flock`` ends with its process); temporary
  files it left are removed by the next lock holder, and index entries whose
  copy is gone are dropped.
* ``stage`` and ``store`` return the source.coop identity they observed
  (``upstream``: size, ETag, Last-Modified, whether source.coop answered), so
  the job's manifest can record it.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import settings, sources

CACHE_ENV = "CRYOSTACK_LIVIST_INPUT_CACHE"
CACHE_MB_ENV = "CRYOSTACK_LIVIST_INPUT_CACHE_MB"
DEFAULT_DIR = settings.REPO_ROOT / "var" / "livist_input_cache"
DEFAULT_MB = 4096
SOURCE_COOP_HTTP = "https://data.source.coop"
HEAD_TIMEOUT_S = 15
#: free space always left on the cache's file system
FREE_SPACE_RESERVE = 1024 * 1024 * 1024
#: longest wait for another job's cache operation (a copy of a large input)
LOCK_TIMEOUT_S = 120.0
_LOCK_POLL_S = 0.2


class CacheBusy(RuntimeError):
    """Another process held the cache lock for longer than ``LOCK_TIMEOUT_S``."""


def cache_dir() -> Path:
    value = (os.environ.get(CACHE_ENV) or "").strip()
    return Path(value).expanduser() if value else DEFAULT_DIR


def cache_limit_bytes() -> int:
    try:
        mb = int((os.environ.get(CACHE_MB_ENV) or "").strip() or DEFAULT_MB)
    except ValueError:
        mb = DEFAULT_MB
    return max(0, mb) * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def head_source_coop(url: str) -> dict | None:
    """``{size, etag, last_modified}`` of a source.coop object, or ``None``
    when it cannot be reached."""
    # source.coop's CDN refuses urllib's default User-Agent with 403
    request = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "CryoStack-LIVIST-input-cache/1"})
    try:
        with urllib.request.urlopen(request, timeout=HEAD_TIMEOUT_S) as response:
            length = response.headers.get("Content-Length")
            return {"size": int(length) if length and length.isdigit() else None,
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified")}
    except (urllib.error.URLError, OSError, ValueError):
        return None


class InputCache:
    def __init__(self, directory: str | Path | None = None, *, head=head_source_coop,
                 limit_bytes: int | None = None):
        self.root = Path(directory) if directory is not None else cache_dir()
        self.head = head
        self.limit = cache_limit_bytes() if limit_bytes is None else limit_bytes

    # ── index ─────────────────────────────────────────────────────
    @contextlib.contextmanager
    def _locked(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o750)
        (self.root / "blobs").mkdir(exist_ok=True, mode=0o750)
        with (self.root / ".lock").open("a") as lock:
            deadline = time.monotonic() + LOCK_TIMEOUT_S
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise CacheBusy("The shared input cache is busy (another job holds "
                                        "it); the input is used without the cache.")
                    time.sleep(_LOCK_POLL_S)
            try:
                self._sweep()
                yield self._read_index()
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _sweep(self) -> None:
        """Remove temporary files of a writer that died (only lock holders
        write them, so none is in use while the lock is held)."""
        for tmp in [self.root / ".index.json.tmp",
                    *(self.root / "blobs").glob(".*.tmp")]:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

    def _read_index(self) -> dict:
        try:
            data = json.loads((self.root / "index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_index(self, index: dict) -> None:
        tmp = self.root / ".index.json.tmp"
        tmp.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.root / "index.json")

    def _blob(self, sha: str) -> Path:
        return self.root / "blobs" / sha

    @staticmethod
    def url_for(key: str) -> str:
        return f"{SOURCE_COOP_HTTP}/{sources.valid_source_coop_key(key)}"

    def entries(self) -> dict:
        """The index, for status pages (keys, sizes, hashes; no paths)."""
        return self._read_index()

    # ── staging ───────────────────────────────────────────────────
    def stage(self, key: str, target: Path) -> dict:
        """Put the cached copy of ``key`` at ``target`` if it is still valid.

        Returns ``{"cache": "hit"|"miss"|"stale"|"corrupt", ...}``; only on a
        hit does ``target`` exist afterwards. Raises :class:`CacheBusy`."""
        url = self.url_for(key)
        with self._locked() as index:
            entry = index.get(key)
            if entry and not self._blob(entry["sha256"]).is_file():
                index.pop(key, None)                  # its copy is gone: forget it
                self._write_index(index)
                entry = None
            if not entry:
                return {"cache": "miss"}
            blob = self._blob(entry["sha256"])
            if sha256_file(blob) != entry["sha256"]:
                blob.unlink(missing_ok=True)
                index.pop(key, None)
                self._write_index(index)
                return {"cache": "corrupt"}
            upstream = self.head(url)
            if upstream is not None:
                changed = ((upstream.get("size") is not None and upstream["size"] != entry["size"])
                           or (upstream.get("etag") and entry.get("etag")
                               and upstream["etag"] != entry["etag"]))
                if changed:
                    return {"cache": "stale", "sha256": entry["sha256"],
                            "upstream": _observed(upstream)}
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(blob, target)
            except OSError:
                shutil.copyfile(blob, target)
            entry["used_at"] = time.time()
            self._write_index(index)
            return {"cache": "hit", "sha256": entry["sha256"], "size": entry["size"],
                    "upstream_checked": upstream is not None,
                    "upstream": _observed(upstream) if upstream is not None else
                    {"size": entry["size"], "etag": entry.get("etag"),
                     "last_modified": entry.get("last_modified"), "answered": False,
                     "from_cache_record": True}}

    # ── storing ───────────────────────────────────────────────────
    def store(self, key: str, path: Path) -> dict:
        """Keep the file a completed job downloaded for ``key``."""
        url = self.url_for(key)
        size = path.stat().st_size
        answer = self.head(url)
        upstream = answer or {}
        seen = _observed(answer)
        if self.limit and size > self.limit:
            return {"cache": "not-stored", "reason": "larger than the cache limit",
                    "upstream": seen}
        sha = sha256_file(path)
        if upstream.get("size") is not None and upstream["size"] != size:
            return {"cache": "not-stored", "reason": "size differs from source.coop",
                    "upstream": seen}
        with self._locked() as index:
            blob = self._blob(sha)
            if not blob.is_file():
                self._make_room(index, size)
                if shutil.disk_usage(self.root).free - size < FREE_SPACE_RESERVE:
                    return {"cache": "not-stored", "reason": "not enough free disk space",
                            "upstream": seen}
                tmp = self.root / "blobs" / f".{sha}.tmp"
                try:
                    shutil.copyfile(path, tmp)
                    verified = sha256_file(tmp) == sha
                except OSError:                       # e.g. the disk filled during the copy
                    tmp.unlink(missing_ok=True)
                    return {"cache": "not-stored", "reason": "copy failed", "upstream": seen}
                if not verified:
                    tmp.unlink(missing_ok=True)
                    return {"cache": "not-stored", "reason": "copy did not verify",
                            "upstream": seen}
                os.chmod(tmp, 0o444)
                os.replace(tmp, blob)
            now = time.time()
            index[key] = {"sha256": sha, "size": size, "url": url,
                          "etag": upstream.get("etag"),
                          "last_modified": upstream.get("last_modified"),
                          "stored_at": now, "used_at": now}
            self._write_index(index)
            self._collect(index)
            return {"cache": "stored", "sha256": sha, "size": size, "upstream": seen}

    def _make_room(self, index: dict, incoming: int) -> None:
        if not self.limit:
            return
        used = sum(e["size"] for e in index.values())
        for key, entry in sorted(index.items(), key=lambda kv: kv[1].get("used_at", 0)):
            if used + incoming <= self.limit:
                break
            index.pop(key)
            used -= entry["size"]
        self._write_index(index)
        self._collect(index)

    def _collect(self, index: dict) -> None:
        """Remove blobs no index entry refers to."""
        live = {e["sha256"] for e in index.values()}
        for blob in (self.root / "blobs").iterdir():
            if not blob.name.startswith(".") and blob.name not in live:
                blob.unlink(missing_ok=True)


def _observed(answer: dict | None) -> dict:
    """What a source.coop HEAD reported (``answered`` false: no answer)."""
    answer = answer or {}
    return {"size": answer.get("size"), "etag": answer.get("etag"),
            "last_modified": answer.get("last_modified"), "answered": bool(answer)}
