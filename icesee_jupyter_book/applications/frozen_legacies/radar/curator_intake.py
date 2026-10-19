"""Safe staging for GUI-created curator intakes.

This module only validates and stages bytes. Catalog registration, indexing,
scientific review and publication remain separate explicit actions.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

from cryostack_src.storage_layout import atomic_write

from .storage import StorageError, approved_roots


INTAKE_ROOT_ENV = "CRYOSTACK_FROZEN_LEGACIES_INTAKE_ROOT"
MAX_FILES = 5_000
MAX_EXPANDED_BYTES = 4 * 1024**3
MAX_EXPANSION_RATIO = 200
ALLOWED = {".tif", ".tiff", ".csv"}


def intake_root() -> Path | None:
    raw = (os.environ.get(INTAKE_ROOT_ENV) or "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser().resolve()
    if not any(root == allowed or allowed in root.parents for allowed in approved_roots()):
        raise StorageError("The managed intake root is not inside approved storage.")
    return root


def _safe_member(name: str) -> PurePosixPath:
    path = PurePosixPath(str(name).replace("\\", "/"))
    if (path.is_absolute() or not path.name or ".." in path.parts or "." in path.parts
            or len(path.parts) > 16):
        raise StorageError("The archive contains an unsafe path.")
    return path


def _destination(root: Path, name: str) -> Path:
    member = _safe_member(name)
    suffix = member.suffix.lower()
    if suffix not in ALLOWED:
        raise StorageError("Only TIFF imagery and CSV navigation files are accepted.")
    folder = "tiff" if suffix in {".tif", ".tiff"} else "nav"
    return root / folder / Path(*member.parts)


def stage_intake(staging: Path, uploads: list[tuple[str, Path]], *, dataset_id: str) -> dict:
    """Validate uploaded files into ``staging`` and write a checksum receipt.

    ``uploads`` are server-owned temporary files. ZIP members are extracted
    without links, traversal, overwrites, or unbounded expansion.
    """
    staging.mkdir(parents=True, exist_ok=False)
    records: list[dict] = []
    seen: set[str] = set()

    def copy_one(name: str, source, size: int) -> None:
        destination = _destination(staging, name)
        relative = destination.relative_to(staging).as_posix()
        if relative.lower() in seen:
            raise StorageError("The intake contains duplicate destination names.")
        seen.add(relative.lower())
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        written = 0
        with destination.open("xb") as output:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > size:
                    raise StorageError("An uploaded file changed while it was being staged.")
                digest.update(chunk)
                output.write(chunk)
        if written != size:
            raise StorageError("An uploaded file was incomplete.")
        records.append({"storage_key": relative, "bytes": written,
                        "sha256": digest.hexdigest(), "scientific_status": "unverified"})

    try:
        expanded = 0
        for upload_name, upload_path in uploads:
            if upload_name.lower().endswith(".zip"):
                with zipfile.ZipFile(upload_path) as archive:
                    members = [item for item in archive.infolist() if not item.is_dir()]
                    if len(records) + len(members) > MAX_FILES:
                        raise StorageError("The archive contains too many files.")
                    for item in members:
                        mode = item.external_attr >> 16
                        if stat.S_ISLNK(mode):
                            raise StorageError("Archive links are not accepted.")
                        _safe_member(item.filename)
                        if item.file_size > MAX_EXPANDED_BYTES - expanded:
                            raise StorageError("The archive expands beyond the intake limit.")
                        if item.file_size > max(1, item.compress_size) * MAX_EXPANSION_RATIO:
                            raise StorageError("The archive has an unsafe expansion ratio.")
                        expanded += item.file_size
                        with archive.open(item) as source:
                            copy_one(item.filename, source, item.file_size)
            else:
                size = upload_path.stat().st_size
                expanded += size
                if expanded > MAX_EXPANDED_BYTES or len(records) >= MAX_FILES:
                    raise StorageError("The intake exceeds its file or byte limit.")
                with upload_path.open("rb") as source:
                    copy_one(Path(upload_name).name, source, size)
        if not records or not any(r["storage_key"].lower().endswith((".tif", ".tiff"))
                                  for r in records):
            raise StorageError("An intake must contain at least one TIFF file.")
        receipt = {"schema": "cryostack.frozen-legacies.curator-intake", "version": 1,
                   "dataset_id": dataset_id, "publication_status": "unpublished",
                   "items": records}
        atomic_write(staging / "intake-receipt.json",
                     json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8"))
        return receipt
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
