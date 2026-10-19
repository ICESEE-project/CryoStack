"""Durable, bounded upload sessions for curator scientific intake.

The session directory is deliberately a child of the configured intake volume:
chunks never spill to ``/tmp`` or the application checkout.  Catalog
registration and publication remain explicit, separate operations.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import uuid
import fcntl
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from cryostack_src.storage_layout import atomic_write

from .curator_intake import MAX_EXPANDED_BYTES, intake_root
from .storage import StorageError


SCHEMA = "cryostack.frozen-legacies.resumable-intake"
CHUNK_BYTES = 8 * 1024**2
MAX_FILES = 5000
MAX_OPEN_SESSIONS = 32
MAX_RESERVED_BYTES = 20 * 1024**3
DEFAULT_FREE_RESERVE = 5 * 1024**3
_LOCK = threading.RLock()


@contextmanager
def _volume_lock():
    """Serialize state transitions across threads *and* gateway processes.

    The lock inode lives on the intake volume, so every process using that
    volume observes the same advisory lock.  The in-process lock is still
    required because ``flock`` locks are associated with a process rather
    than an individual Python thread on some Unix implementations.
    """
    with _LOCK:
        lock_path = _root() / ".intake.lock"
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _serialized(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        with _volume_lock():
            return function(*args, **kwargs)
    return guarded


def _root() -> Path:
    root = intake_root()
    if root is None or not root.is_dir() or not os.access(root, os.W_OK | os.X_OK):
        raise StorageError("The managed intake volume is not mounted and writable.")
    # Never create the configured root: doing so could mask a missing mount.
    sessions = root / ".upload-sessions"
    sessions.mkdir(mode=0o700, exist_ok=True)
    if sessions.stat().st_dev != root.stat().st_dev:
        raise StorageError("The upload session store is not on the managed intake volume.")
    return sessions


def _manifest_path(session_id: str) -> Path:
    if not session_id.startswith("in-") or len(session_id) != 35 or not session_id[3:].isalnum():
        raise StorageError("Invalid upload session ID.")
    return _root() / session_id / "session.json"


def _read(session_id: str) -> dict:
    path = _manifest_path(session_id)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raise StorageError("Upload session not found or damaged.")
    if document.get("schema") != SCHEMA or document.get("session_id") != session_id:
        raise StorageError("Upload session not found or damaged.")
    return document


def _write(path: Path, document: dict) -> None:
    document["updated_at"] = int(time.time())
    atomic_write(path, json.dumps(document, sort_keys=True, indent=2).encode())


def _free_check(root: Path, needed: int) -> None:
    reserve = int(os.environ.get("CRYOSTACK_FROZEN_LEGACIES_INTAKE_FREE_RESERVE_BYTES",
                                 DEFAULT_FREE_RESERVE))
    usage = shutil.disk_usage(root)
    if usage.free - max(0, needed) < reserve:
        raise StorageError("The managed intake volume cannot preserve its free-space reserve.")


def _public(document: dict) -> dict:
    result = {key: document.get(key) for key in (
        "session_id", "source_id", "name", "dataset_id", "nav_template", "state",
        "expected_bytes", "received_bytes", "created_at", "updated_at", "error",
        "final_source_id")}
    result["chunk_bytes"] = CHUNK_BYTES
    return result


@_serialized
def create(owner_id: str, payload: dict) -> dict:
    root = _root()
    files = payload.get("files")
    if not isinstance(files, list) or not files or len(files) > MAX_FILES:
        raise StorageError("files must be a non-empty bounded list.")
    normalized, total = [], 0
    for position, item in enumerate(files):
        if not isinstance(item, dict):
            raise StorageError("Each file declaration must be an object.")
        name = Path(str(item.get("name") or "")).name
        size, digest = item.get("bytes"), str(item.get("sha256") or "").lower()
        if not name or name != str(item.get("name")) or not isinstance(size, int) or size < 0:
            raise StorageError("Each file needs a safe name and non-negative byte count.")
        if digest and (len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
            raise StorageError("A declared file SHA-256 digest is invalid.")
        total += size
        normalized.append({"file_id": position, "name": name, "bytes": size,
                           "sha256": digest, "received_bytes": 0, "chunks": {}})
    if total > MAX_EXPANDED_BYTES:
        raise StorageError("The declared intake exceeds the 4 GiB limit.")
    documents = []
    for path in root.glob("in-*/session.json"):
        try:
            candidate = json.loads(path.read_text())
            if candidate.get("state") == "open":
                documents.append(candidate)
        except (OSError, ValueError):
            continue
    if len(documents) >= MAX_OPEN_SESSIONS or sum(d.get("expected_bytes", 0) for d in documents) + total > MAX_RESERVED_BYTES:
        raise StorageError("The managed intake session capacity is currently reserved.")
    _free_check(root, total)
    session_id = "in-" + uuid.uuid4().hex
    directory = root / session_id
    directory.mkdir(mode=0o700)
    now = int(time.time())
    document = {"schema": SCHEMA, "version": 1, "session_id": session_id,
                "owner_id": owner_id, "source_id": payload.get("source_id"),
                "name": payload.get("name"), "dataset_id": payload.get("dataset_id"),
                "nav_template": payload.get("nav_template") or "nav/{flight}.csv",
                "state": "open", "expected_bytes": total, "received_bytes": 0,
                "files": normalized, "created_at": now, "updated_at": now,
                "error": None, "final_source_id": None}
    _write(directory / "session.json", document)
    return _public(document)


@_serialized
def status(session_id: str, owner_id: str) -> dict:
    document = _read(session_id)
    if document.get("owner_id") != owner_id:
        raise StorageError("Upload session not found.")
    result = _public(document)
    result["files"] = [{k: f.get(k) for k in ("file_id", "name", "bytes", "received_bytes")}
                       for f in document["files"]]
    return result


@_serialized
def put_chunk(session_id: str, owner_id: str, file_id: int, index: int,
              body: bytes, claimed_sha256: str) -> dict:
    document = _read(session_id)
    if document.get("owner_id") != owner_id or document.get("state") != "open":
        raise StorageError("Upload session is unavailable.")
    try:
        item = document["files"][file_id]
    except (IndexError, TypeError):
        raise StorageError("Unknown file ID.")
    count = (item["bytes"] + CHUNK_BYTES - 1) // CHUNK_BYTES
    expected = CHUNK_BYTES if index < count - 1 else item["bytes"] - CHUNK_BYTES * index
    if index < 0 or index >= count or len(body) != expected:
        raise StorageError("Chunk position or fixed size is invalid.")
    digest = hashlib.sha256(body).hexdigest()
    if digest != claimed_sha256.lower():
        raise StorageError("Chunk checksum does not match its bytes.")
    existing = item["chunks"].get(str(index))
    if existing:
        if existing["sha256"] != digest or existing["bytes"] != len(body):
            raise StorageError("A different chunk already occupies this position.")
        return {"idempotent": True, "sha256": digest, "received_bytes": document["received_bytes"]}
    _free_check(_root(), len(body))
    directory = _manifest_path(session_id).parent / "chunks" / str(file_id)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / f".{index}.{uuid.uuid4().hex}.part"
    with temporary.open("xb") as output:
        output.write(body); output.flush(); os.fsync(output.fileno())
    target = directory / f"{index}.chunk"
    os.replace(temporary, target)
    item["chunks"][str(index)] = {"bytes": len(body), "sha256": digest}
    item["received_bytes"] += len(body)
    document["received_bytes"] += len(body)
    _write(_manifest_path(session_id), document)
    return {"idempotent": False, "sha256": digest, "received_bytes": document["received_bytes"]}


@_serialized
def cancel(session_id: str, owner_id: str) -> dict:
    document = _read(session_id)
    if document.get("owner_id") != owner_id:
        raise StorageError("Upload session not found.")
    if document.get("state") == "cancelled":
        return _public(document)
    if document.get("state") != "open":
        raise StorageError("Only an open upload session can be cancelled.")
    document["state"] = "cancelled"
    _write(_manifest_path(session_id), document)
    shutil.rmtree(_manifest_path(session_id).parent / "chunks", ignore_errors=True)
    return _public(document)


@_serialized
def prepare_finalize(session_id: str, owner_id: str) -> tuple[dict, list[tuple[str, Path]]]:
    document = _read(session_id)
    if document.get("owner_id") != owner_id or document.get("state") not in {
            "open", "assembling", "prepared", "committing"}:
        raise StorageError("Upload session is unavailable.")
    if document["received_bytes"] != document["expected_bytes"]:
        raise StorageError("Upload session is incomplete.")
    directory = _manifest_path(session_id).parent
    assembled = directory / "assembled"
    # ``prepared`` is an idempotent durable boundary.  Verify the files again
    # before returning them; never trust a directory left by a crashed worker.
    if document.get("state") in {"prepared", "committing"}:
        uploads = []
        valid = True
        for item in document["files"]:
            path = assembled / f"{item['file_id']}.upload"
            if (not path.is_file() or path.is_symlink() or
                    path.stat().st_size != item["bytes"] or
                    _sha256_file(path) != item["sha256"]):
                valid = False
                break
            uploads.append((item["name"], path))
        if valid:
            return document, uploads

    document["state"], document["error"] = "assembling", None
    _write(_manifest_path(session_id), document)
    temporary_assembled = directory / f".assembled-{uuid.uuid4().hex}"
    temporary_assembled.mkdir(mode=0o700)
    uploads = []
    try:
        for item in document["files"]:
            output_path = temporary_assembled / f"{item['file_id']}.upload"
            digest = hashlib.sha256()
            with output_path.open("xb") as output:
                count = (item["bytes"] + CHUNK_BYTES - 1) // CHUNK_BYTES
                for index in range(count):
                    chunk = (directory / "chunks" / str(item["file_id"]) / f"{index}.chunk").read_bytes()
                    digest.update(chunk); output.write(chunk)
                output.flush(); os.fsync(output.fileno())
            computed = digest.hexdigest()
            if (item["sha256"] and computed != item["sha256"]) or output_path.stat().st_size != item["bytes"]:
                raise StorageError("Whole-file checksum verification failed.")
            item["sha256"] = computed
        shutil.rmtree(assembled, ignore_errors=True)
        os.replace(temporary_assembled, assembled)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException as exc:
        shutil.rmtree(temporary_assembled, ignore_errors=True)
        document["state"], document["error"] = "open", str(exc)
        _write(_manifest_path(session_id), document)
        raise
    uploads = [(item["name"], assembled / f"{item['file_id']}.upload")
               for item in document["files"]]
    document["state"], document["error"] = "prepared", None
    _write(_manifest_path(session_id), document)
    return document, uploads


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@_serialized
def begin_commit(session_id: str, owner_id: str, token: str) -> dict:
    document = _read(session_id)
    if document.get("owner_id") != owner_id or document.get("state") != "prepared":
        raise StorageError("Upload session is unavailable.")
    document["state"], document["error"] = "committing", None
    document["commit_token"], document["commit_started_at"] = token, int(time.time())
    _write(_manifest_path(session_id), document)
    return _public(document)


@_serialized
def recover_commit(session_id: str, *, final_exists: bool,
                   catalog_matches: bool, catalog_conflict: bool) -> dict:
    """Reconcile a commit after restart using independently observed state."""
    document = _read(session_id)
    if document.get("state") not in {"assembling", "prepared", "committing"}:
        return _public(document)
    if catalog_conflict or (catalog_matches and not final_exists):
        document["state"], document["error"] = (
            "error", "Catalog and managed intake storage disagree; operator review is required.")
    elif final_exists and catalog_matches:
        document["state"], document["final_source_id"] = "finalized", document["source_id"]
        document["error"] = None
    elif final_exists:
        # The durable rename committed, but catalog registration did not.
        document["state"], document["error"] = "prepared", None
    else:
        # Assembly/staging can be deterministically rebuilt from verified chunks.
        document["state"], document["error"] = "open", None
    document.pop("commit_token", None)
    document.pop("commit_started_at", None)
    _write(_manifest_path(session_id), document)
    if document["state"] == "finalized":
        directory = _manifest_path(session_id).parent
        shutil.rmtree(directory / "chunks", ignore_errors=True)
        shutil.rmtree(directory / "assembled", ignore_errors=True)
    return _public(document)


@_serialized
def recovery_candidates() -> list[dict]:
    candidates = []
    for path in _root().glob("in-*/session.json"):
        try:
            document = _read(path.parent.name)
        except StorageError:
            continue
        if document.get("state") in {"assembling", "prepared", "committing"}:
            candidates.append({k: document.get(k) for k in
                               ("session_id", "source_id", "state", "owner_id")})
    return candidates


@_serialized
def mark_error(session_id: str, message: str) -> dict:
    document = _read(session_id)
    if document.get("state") != "finalized":
        document["state"], document["error"] = "error", str(message)[:500]
        _write(_manifest_path(session_id), document)
    return _public(document)


@_serialized
def mark_finalized(session_id: str, owner_id: str, source_id: str) -> dict:
    document = _read(session_id)
    if document.get("owner_id") != owner_id:
        raise StorageError("Upload session not found.")
    document["state"], document["final_source_id"] = "finalized", source_id
    document.pop("commit_token", None)
    document.pop("commit_started_at", None)
    _write(_manifest_path(session_id), document)
    shutil.rmtree(_manifest_path(session_id).parent / "chunks", ignore_errors=True)
    shutil.rmtree(_manifest_path(session_id).parent / "assembled", ignore_errors=True)
    return _public(document)
