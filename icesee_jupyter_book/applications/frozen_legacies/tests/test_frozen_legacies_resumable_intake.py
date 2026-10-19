from __future__ import annotations

import hashlib
import inspect
import multiprocessing

import pytest

from icesee_jupyter_book.applications.frozen_legacies.radar.curator_intake import INTAKE_ROOT_ENV
from icesee_jupyter_book.applications.frozen_legacies.radar import resumable_intake as R
from icesee_jupyter_book.applications.frozen_legacies.radar.storage import STORAGE_ROOTS_ENV, StorageError
from icesee_jupyter_book.applications.frozen_legacies import catalog_routes


def _put_same_chunk(queue, session_id, data, digest):
    try:
        queue.put(("ok", R.put_chunk(session_id, "curator-1", 0, 0,
                                      data, digest)["idempotent"]))
    except BaseException as exc:  # pragma: no cover - reported in parent
        queue.put(("error", repr(exc)))


def configured(tmp_path, monkeypatch):
    approved = tmp_path / "approved"
    intake = approved / "intakes"
    intake.mkdir(parents=True)
    monkeypatch.setenv(STORAGE_ROOTS_ENV, str(approved))
    monkeypatch.setenv(INTAKE_ROOT_ENV, str(intake))
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_INTAKE_FREE_RESERVE_BYTES", "0")
    return intake


def declaration(data=b"II*\0scientific-original"):
    return {"source_id": "flight-127", "name": "Flight 127", "dataset_id": "radar",
            "files": [{"name": "F127.tiff", "bytes": len(data),
                       "sha256": hashlib.sha256(data).hexdigest()}]}


def test_session_chunk_is_verified_idempotent_and_durable(tmp_path, monkeypatch):
    intake = configured(tmp_path, monkeypatch)
    data = b"II*\0scientific-original"
    created = R.create("curator-1", declaration(data))
    sid = created["session_id"]
    digest = hashlib.sha256(data).hexdigest()
    first = R.put_chunk(sid, "curator-1", 0, 0, data, digest)
    second = R.put_chunk(sid, "curator-1", 0, 0, data, digest)
    assert first["idempotent"] is False and second["idempotent"] is True
    assert R.status(sid, "curator-1")["received_bytes"] == len(data)
    assert (intake / ".upload-sessions" / sid / "session.json").is_file()
    with pytest.raises(StorageError, match="not found"):
        R.status(sid, "another-user")
    with pytest.raises(StorageError, match="checksum"):
        R.put_chunk(R.create("curator-1", declaration(data))["session_id"],
                    "curator-1", 0, 0, data, "0" * 64)


def test_finalize_preparation_checks_whole_file_and_cancel_is_idempotent(tmp_path, monkeypatch):
    configured(tmp_path, monkeypatch)
    data = b"II*\0scientific-original"
    session = R.create("curator-1", declaration(data))
    sid = session["session_id"]
    R.put_chunk(sid, "curator-1", 0, 0, data, hashlib.sha256(data).hexdigest())
    document, uploads = R.prepare_finalize(sid, "curator-1")
    assert document["source_id"] == "flight-127"
    assert uploads[0][1].read_bytes() == data
    other = R.create("curator-1", declaration(data))["session_id"]
    assert R.cancel(other, "curator-1")["state"] == "cancelled"
    assert R.cancel(other, "curator-1")["state"] == "cancelled"


def test_browser_session_records_server_computed_whole_file_digest(tmp_path, monkeypatch):
    configured(tmp_path, monkeypatch)
    data = b"II*\0browser-streamed-without-prehash"
    declared = declaration(data)
    declared["files"][0]["sha256"] = ""
    sid = R.create("curator-1", declared)["session_id"]
    R.put_chunk(sid, "curator-1", 0, 0, data, hashlib.sha256(data).hexdigest())
    document, uploads = R.prepare_finalize(sid, "curator-1")
    assert uploads[0][1].read_bytes() == data
    assert document["files"][0]["sha256"] == hashlib.sha256(data).hexdigest()


def test_control_center_uses_resumable_chunk_uploader_without_cli():
    script = catalog_routes._CONTROL_SCRIPT
    assert "resumableIntake" in script
    assert "crypto.subtle.digest" in script
    assert "/admin/intake-sessions" in script
    assert 'method: "PUT"' in script
    assert "X-Chunk-SHA256" in script
    assert "localStorage" in script
    assert "Cancel upload" in script


def test_control_center_exposes_owner_scoped_session_recovery_and_confirmed_cleanup():
    script = catalog_routes._CONTROL_SCRIPT
    page = inspect.getsource(catalog_routes.control_page)
    assert "loadSessions" in script
    assert "Find stale sessions" in page
    assert "only your sessions" in page
    assert "data-clean-session" in script
    assert 'confirm: "expire"' in script
    assert "{confirm: sid}" in script
    assert "Dry run only" in script
    assert "No bytes have been removed" in script


def test_missing_mount_fails_closed_and_capacity_is_bounded(tmp_path, monkeypatch):
    approved = tmp_path / "approved"
    approved.mkdir()
    monkeypatch.setenv(STORAGE_ROOTS_ENV, str(approved))
    monkeypatch.setenv(INTAKE_ROOT_ENV, str(approved / "missing"))
    with pytest.raises(StorageError, match="not mounted"):
        R.create("curator", declaration())
    configured(tmp_path, monkeypatch)
    huge = declaration(b"")
    huge["files"][0].update(bytes=R.MAX_EXPANDED_BYTES + 1, sha256="0" * 64)
    with pytest.raises(StorageError, match="4 GiB"):
        R.create("curator", huge)


def test_chunk_transition_is_serialized_between_processes(tmp_path, monkeypatch):
    configured(tmp_path, monkeypatch)
    data = b"II*\0one-scientific-chunk"
    sid = R.create("curator-1", declaration(data))["session_id"]
    digest = hashlib.sha256(data).hexdigest()
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    workers = [context.Process(target=_put_same_chunk,
                               args=(queue, sid, data, digest)) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(10)
        assert worker.exitcode == 0
    results = [queue.get(timeout=2) for _ in workers]
    assert sorted(results) == [("ok", False), ("ok", True)]
    assert R.status(sid, "curator-1")["received_bytes"] == len(data)


def test_recovery_resolves_each_durable_commit_boundary(tmp_path, monkeypatch):
    intake = configured(tmp_path, monkeypatch)
    data = b"II*\0scientific-original"

    def prepared_session(source_id):
        declared = declaration(data)
        declared["source_id"] = source_id
        sid = R.create("curator-1", declared)["session_id"]
        R.put_chunk(sid, "curator-1", 0, 0, data, hashlib.sha256(data).hexdigest())
        R.prepare_finalize(sid, "curator-1")
        return sid

    retry = prepared_session("flight-retry")
    R.begin_commit(retry, "curator-1", "worker-a")
    recovered = R.recover_commit(retry, final_exists=False, catalog_matches=False,
                                 catalog_conflict=False)
    assert recovered["state"] == "open"
    assert R.prepare_finalize(retry, "curator-1")[1][0][1].read_bytes() == data

    renamed = prepared_session("flight-renamed")
    R.begin_commit(renamed, "curator-1", "worker-b")
    (intake / "flight-renamed").mkdir()
    recovered = R.recover_commit(renamed, final_exists=True, catalog_matches=False,
                                 catalog_conflict=False)
    assert recovered["state"] == "prepared"

    complete = prepared_session("flight-complete")
    (intake / "flight-complete").mkdir()
    recovered = R.recover_commit(complete, final_exists=True, catalog_matches=True,
                                 catalog_conflict=False)
    assert recovered["state"] == "finalized"

    conflict = prepared_session("flight-conflict")
    recovered = R.recover_commit(conflict, final_exists=True, catalog_matches=False,
                                 catalog_conflict=True)
    assert recovered["state"] == "error"
    assert "operator review" in recovered["error"]
