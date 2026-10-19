"""Bounded, rebuildable display derivatives for radar products.

Derivatives live below an asset-local cache directory, never beside or in
place of scientific products.  Each file has a small provenance sidecar that
binds it to the exact source bytes.  A cache miss is harmless: everything in
this directory can be regenerated from the canonical product.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path


SCHEMA = "cryostack.frozen_legacies.preview"
VERSION = 1
CACHE_DIRECTORY = ".preview-cache"
MAX_CACHE_BYTES = 32 * 1024 * 1024
MAX_CACHE_ENTRIES = 64


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.part")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _paths(asset_dir: Path, product_id: str, source_sha256: str, extension: str):
    # product_id has already passed the product model's strict identifier check.
    stem = f"{product_id}-{source_sha256[:20]}-v{VERSION}"
    root = asset_dir / CACHE_DIRECTORY
    return root / f"{stem}.{extension}", root / f"{stem}.{extension}.json"


def _valid(path: Path, meta_path: Path, source_sha256: str, media_type: str) -> dict | None:
    try:
        if path.is_symlink() or meta_path.is_symlink() or not path.is_file():
            return None
        doc = json.loads(meta_path.read_text(encoding="utf-8"))
        if (doc.get("schema") != SCHEMA or doc.get("version") != VERSION
                or doc.get("source", {}).get("sha256") != source_sha256
                or doc.get("derivative", {}).get("media_type") != media_type
                or doc.get("derivative", {}).get("bytes") != path.stat().st_size
                or doc.get("derivative", {}).get("sha256") != sha256_file(path)):
            return None
        return doc
    except (OSError, ValueError, TypeError):
        return None


def _prune(root: Path, keep: set[Path]) -> None:
    files = [p for p in root.glob("*") if p.is_file() and not p.is_symlink()]
    payloads = sorted((p for p in files if p.suffix != ".json"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    total = 0
    retained = 0
    for path in payloads:
        size = path.stat().st_size
        if path in keep or (retained < MAX_CACHE_ENTRIES and total + size <= MAX_CACHE_BYTES):
            total += size
            retained += 1
            continue
        path.unlink(missing_ok=True)
        path.with_name(path.name + ".json").unlink(missing_ok=True)


def get_or_create(*, asset_dir: Path, product_id: str, source: Path,
                  source_record: dict, extension: str, media_type: str,
                  generator: str, render) -> tuple[bytes, dict]:
    """Return a derivative and provenance, atomically caching a bounded copy."""
    # Hash the bytes we are about to render.  A manifest checksum is useful
    # provenance, but it must not keep an old derivative valid if a source was
    # replaced or corrupted after registration.
    source_sha256 = sha256_file(source)
    path, meta_path = _paths(asset_dir, product_id, source_sha256, extension)
    doc = _valid(path, meta_path, source_sha256, media_type)
    if doc is not None:
        os.utime(path, None)
        return path.read_bytes(), doc

    data = render(source)
    if len(data) > MAX_CACHE_BYTES:
        raise ValueError("Preview derivative exceeds the cache size limit.")
    now = time.time()
    doc = {
        "schema": SCHEMA, "version": VERSION, "created_at": now,
        "scientific_status": "preview-only",
        "source": {
            "asset_id": source_record["asset_id"], "product_id": product_id,
            "kind": source_record["kind"], "sha256": source_sha256,
            "bytes": source.stat().st_size,
        },
        "derivative": {
            "media_type": media_type, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "generator": generator,
        },
    }
    _atomic_bytes(path, data)
    _atomic_bytes(meta_path, json.dumps(doc, sort_keys=True, indent=2).encode("utf-8"))
    _prune(path.parent, {path})
    return data, doc
