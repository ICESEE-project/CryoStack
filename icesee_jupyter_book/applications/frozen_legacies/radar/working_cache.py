"""Bounded local working copies of data-source objects.

The pickers need random access to a radar file (decoding, ASTRA's QC image,
URSA). :func:`WorkingCache.materialize` turns a storage object into a local
file for that purpose:

* a provider with the ``local_files`` capability already has the object as a
  file on this server: it is used in place, nothing is copied;
* any other provider streams the object into the cache directory, as
  ``<entry>/<original file name>`` where the entry is a digest of (source,
  key, version). The original name matters: ASTRA and URSA read the flight
  and CBD range from it and ASTRA writes it into its CSV. The copy is
  written to a temporary file, checked against the object's size, and
  renamed into place -- an interrupted download never leaves a partial
  file. Concurrent requests for the same object download it once. The cache
  is bounded: least recently used entries are evicted, except those with an
  active lease (:meth:`WorkingCache.lease`, e.g. while ASTRA or URSA uses the
  file).

Cached copies are disposable; the data source stays authoritative.

Configuration: ``$CRYOSTACK_FROZEN_LEGACIES_WORKING_CACHE`` (directory,
default ``var/frozen_legacies_cache``) and
``$CRYOSTACK_FROZEN_LEGACIES_WORKING_CACHE_MB`` (default 20480).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .storage import RadarStorageProvider, StorageError, StorageObject


CACHE_DIR_ENV = "CRYOSTACK_FROZEN_LEGACIES_WORKING_CACHE"
CACHE_MB_ENV = "CRYOSTACK_FROZEN_LEGACIES_WORKING_CACHE_MB"
DEFAULT_DIR = Path(__file__).resolve().parents[4] / "var" / "frozen_legacies_cache"
CHUNK = 4 * 1024 * 1024
#: free disk space always left on the cache's file system
FREE_SPACE_RESERVE = 512 * 1024 * 1024


class WorkingCache:
    def __init__(self, directory: str | Path | None = None, *, max_bytes: int | None = None):
        configured = (os.environ.get(CACHE_DIR_ENV) or "").strip()
        self.directory = Path(directory or configured or DEFAULT_DIR)
        if max_bytes is None:
            try:
                max_bytes = int(os.environ.get(CACHE_MB_ENV, "20480")) * 1024 * 1024
            except ValueError:
                max_bytes = 20480 * 1024 * 1024
        self.max_bytes = max(1, int(max_bytes))
        self._lock = threading.Lock()
        self._key_locks: dict[str, threading.Lock] = {}
        self._leases: dict[str, int] = {}
        self.downloads = 0

    @staticmethod
    def _entry(source_id: str, obj: StorageObject) -> str:
        return hashlib.sha256(f"{source_id}\0{obj.key}\0{obj.version}".encode()).hexdigest()[:40]

    def materialize(self, provider: RadarStorageProvider, source_id: str,
                    obj: StorageObject) -> Path:
        """A local file with the object's content (see module docstring)."""
        if "local_files" in provider.capabilities:
            path = provider.local_file(obj.key)
            if path is None:
                raise StorageError("The object is not available.")
            return path
        if "stream" not in provider.capabilities:
            raise StorageError("This data source cannot provide working copies.")
        if obj.size > self.max_bytes:
            raise StorageError(
                f"This file ({obj.size / 1048576:.0f} MB) is larger than this server's "
                f"working-cache limit ({self.max_bytes / 1048576:.0f} MB).")
        entry = self._entry(source_id, obj)
        # storage keys are normalized: the last segment is a plain file name
        target = self.directory / entry / Path(obj.key).name
        with self._lock:
            key_lock = self._key_locks.setdefault(entry, threading.Lock())
        with key_lock:
            if target.is_file() and target.stat().st_size == obj.size:
                os.utime(target)                     # last use, for eviction
                return target
            self.directory.mkdir(parents=True, exist_ok=True)
            self._make_room(obj.size, keep={entry})
            self._check_free_space(obj.size)
            for attempt in (1, 2):              # one retry after an interrupted transfer
                try:
                    return self._download(provider, obj, entry, target)
                except StorageError:
                    if attempt == 2:
                        raise

    def _check_free_space(self, incoming: int) -> None:
        """Never fill the disk: the cache shares it with the server."""
        try:
            free = shutil.disk_usage(self.directory).free
        except OSError:
            return
        if free < incoming + FREE_SPACE_RESERVE:
            raise StorageError("Not enough free disk space on the server for a working copy "
                               "of this file. Try again later or ask an operator.")

    def _download(self, provider, obj: StorageObject, entry: str, target: Path) -> Path:
        """Stream into a temporary file, check the size, rename into place."""
        tmp = self.directory / f".{entry}.{uuid.uuid4().hex}.part"
        try:
            written = 0
            with provider.open_stream(obj.key) as source, tmp.open("wb") as out:
                while True:
                    chunk = source.read(CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > obj.size:
                        raise StorageError("The object is larger than its metadata says.")
                    out.write(chunk)
            if written != obj.size:
                raise StorageError("The download was incomplete.")
            target.parent.mkdir(exist_ok=True)
            os.replace(tmp, target)
            self.downloads += 1
        except OSError as error:
            raise StorageError(f"The working copy could not be written ({error.strerror}).")
        finally:
            if tmp.exists():
                tmp.unlink()
        return target

    def _lease_key(self, path: Path) -> str:
        path = Path(path)
        return path.parent.name if path.parent.parent == self.directory else str(path)

    @contextmanager
    def lease(self, path: Path):
        """Keep a cached copy from eviction while it is in use (a no-op for
        files used in place)."""
        name = self._lease_key(path)
        with self._lock:
            self._leases[name] = self._leases.get(name, 0) + 1
        try:
            yield path
        finally:
            with self._lock:
                self._leases[name] -= 1
                if self._leases[name] <= 0:
                    del self._leases[name]

    def _entries(self) -> list[tuple[Path, int, float]]:
        """(entry directory, bytes, last use) of the cached copies."""
        out = []
        if not self.directory.is_dir():
            return out
        for entry in self.directory.iterdir():
            if entry.name.startswith(".") or not entry.is_dir():
                continue
            files = [f for f in entry.iterdir() if f.is_file()]
            if not files:
                continue
            out.append((entry, sum(f.stat().st_size for f in files),
                        max(f.stat().st_mtime for f in files)))
        return out

    def usage(self) -> int:
        return sum(size for _entry, size, _used in self._entries())

    def _make_room(self, incoming: int, *, keep: set[str]) -> None:
        entries = sorted(self._entries(), key=lambda e: e[2])
        total = sum(size for _entry, size, _used in entries)
        for entry, size, _used in entries:
            if total + incoming <= self.max_bytes:
                break
            with self._lock:
                leased = self._leases.get(entry.name, 0) > 0
            if leased or entry.name in keep:
                continue
            shutil.rmtree(entry, ignore_errors=True)
            total -= size

    def clear_stale(self, older_than_s: float = 86400) -> None:
        """Remove partial downloads left by a crashed process."""
        if not self.directory.is_dir():
            return
        cutoff = time.time() - older_than_s
        for path in self.directory.glob(".*.part"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)


_cache: WorkingCache | None = None
_cache_lock = threading.Lock()


def working_cache() -> WorkingCache:
    global _cache
    with _cache_lock:
        if _cache is None:
            _cache = WorkingCache()
        return _cache
