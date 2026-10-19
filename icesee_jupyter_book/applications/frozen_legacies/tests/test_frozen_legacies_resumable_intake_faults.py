"""Fault and scale contracts for durable curator uploads.

These tests deliberately use logical declarations and small payloads.  They
exercise the same reservation and recovery paths as large scientific imports
without creating multi-gigabyte fixtures in CI or on a developer workstation.
"""
from __future__ import annotations

import hashlib
import json
import threading
from types import SimpleNamespace

import pytest

from icesee_jupyter_book.applications.frozen_legacies.radar import resumable_intake as R
from icesee_jupyter_book.applications.frozen_legacies.radar.curator_intake import INTAKE_ROOT_ENV
from icesee_jupyter_book.applications.frozen_legacies.radar.storage import STORAGE_ROOTS_ENV, StorageError


def _configured(tmp_path, monkeypatch):
    approved = tmp_path / "approved"
    intake = approved / "intakes"
    intake.mkdir(parents=True)
    monkeypatch.setenv(STORAGE_ROOTS_ENV, str(approved))
    monkeypatch.setenv(INTAKE_ROOT_ENV, str(intake))
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_INTAKE_FREE_RESERVE_BYTES", "0")
    return intake


def _declaration(size: int, *, digest: str = "") -> dict:
    return {
        "source_id": "fault-scale-127",
        "name": "Fault and scale flight 127",
        "dataset_id": "radar",
        "files": [{"name": "F127.tiff", "bytes": size, "sha256": digest}],
    }


def test_logical_multi_gibibyte_reservation_does_not_allocate_payload(tmp_path, monkeypatch):
    """Large declarations reserve capacity using only a small durable manifest."""
    intake = _configured(tmp_path, monkeypatch)
    logical_bytes = 3 * 1024**3

    created = R.create("curator", _declaration(logical_bytes))
    manifest = intake / ".upload-sessions" / created["session_id"] / "session.json"

    assert created["expected_bytes"] == logical_bytes
    assert manifest.stat().st_size < 16 * 1024
    assert not (manifest.parent / "chunks").exists()


def test_interrupted_upload_resumes_only_missing_chunks_after_reload(tmp_path, monkeypatch):
    intake = _configured(tmp_path, monkeypatch)
    first = b"a" * R.CHUNK_BYTES
    last = b"scientific-tail"
    data = first + last
    sid = R.create("curator", _declaration(len(data), digest=hashlib.sha256(data).hexdigest()))["session_id"]

    R.put_chunk(sid, "curator", 0, 0, first, hashlib.sha256(first).hexdigest())
    persisted = json.loads((intake / ".upload-sessions" / sid / "session.json").read_text())
    assert persisted["files"][0]["chunks"].keys() == {"0"}

    # A new request after an interruption discovers committed progress.  A
    # duplicate retry is idempotent and only the missing tail changes totals.
    assert R.status(sid, "curator")["received_bytes"] == len(first)
    assert R.put_chunk(sid, "curator", 0, 0, first,
                       hashlib.sha256(first).hexdigest())["idempotent"] is True
    R.put_chunk(sid, "curator", 0, 1, last, hashlib.sha256(last).hexdigest())
    document, uploads = R.prepare_finalize(sid, "curator")
    assert document["received_bytes"] == len(data)
    assert uploads[0][1].read_bytes() == data


def test_finalize_rejects_committed_chunk_corruption(tmp_path, monkeypatch):
    intake = _configured(tmp_path, monkeypatch)
    data = b"II*\0verified-scientific-payload"
    digest = hashlib.sha256(data).hexdigest()
    sid = R.create("curator", _declaration(len(data), digest=digest))["session_id"]
    R.put_chunk(sid, "curator", 0, 0, data, digest)

    chunk = intake / ".upload-sessions" / sid / "chunks" / "0" / "0.chunk"
    chunk.write_bytes(b"X" * len(data))
    with pytest.raises(StorageError, match="Whole-file checksum"):
        R.prepare_finalize(sid, "curator")
    assert R.status(sid, "curator")["state"] == "open"
    assert not (chunk.parents[2] / "assembled").exists()


def test_free_space_reserve_rejects_before_session_or_chunk_write(tmp_path, monkeypatch):
    intake = _configured(tmp_path, monkeypatch)
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_INTAKE_FREE_RESERVE_BYTES", "100")
    monkeypatch.setattr(R.shutil, "disk_usage",
                        lambda _path: SimpleNamespace(total=1000, used=950, free=50))

    with pytest.raises(StorageError, match="free-space reserve"):
        R.create("curator", _declaration(1))
    assert not list((intake / ".upload-sessions").glob("in-*"))

    # Prove the same guard is evaluated again for each write, not only when a
    # session is declared.
    monkeypatch.setattr(R.shutil, "disk_usage",
                        lambda _path: SimpleNamespace(total=1000, used=100, free=900))
    sid = R.create("curator", _declaration(4))["session_id"]
    monkeypatch.setattr(R.shutil, "disk_usage",
                        lambda _path: SimpleNamespace(total=1000, used=950, free=50))
    with pytest.raises(StorageError, match="free-space reserve"):
        R.put_chunk(sid, "curator", 0, 0, b"data", hashlib.sha256(b"data").hexdigest())
    assert R.status(sid, "curator")["received_bytes"] == 0


def test_mount_disappearance_fails_closed_during_create_upload_and_finalize(tmp_path, monkeypatch):
    intake = _configured(tmp_path, monkeypatch)
    data = b"II*\0payload"
    sid = R.create("curator", _declaration(len(data), digest=hashlib.sha256(data).hexdigest()))["session_id"]
    offline = intake.with_name("intakes-offline")
    intake.rename(offline)

    for operation in (
        lambda: R.create("curator", _declaration(1)),
        lambda: R.put_chunk(sid, "curator", 0, 0, data, hashlib.sha256(data).hexdigest()),
        lambda: R.prepare_finalize(sid, "curator"),
    ):
        with pytest.raises(StorageError, match="not mounted"):
            operation()
    assert not intake.exists(), "the service must not recreate a missing mount path"


def test_concurrent_creators_cannot_overbook_last_session_slot(tmp_path, monkeypatch):
    _configured(tmp_path, monkeypatch)
    monkeypatch.setattr(R, "MAX_OPEN_SESSIONS", 1)
    barrier = threading.Barrier(3)
    outcomes: list[str] = []

    def creator(owner: str) -> None:
        barrier.wait()
        try:
            R.create(owner, _declaration(1))
            outcomes.append("created")
        except StorageError as error:
            outcomes.append(str(error))

    threads = [threading.Thread(target=creator, args=(f"curator-{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)

    assert outcomes.count("created") == 1
    assert sum("capacity is currently reserved" in item for item in outcomes) == 1
