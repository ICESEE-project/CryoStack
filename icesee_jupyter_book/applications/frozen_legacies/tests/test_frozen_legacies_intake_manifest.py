from __future__ import annotations

import copy
import json

import pytest

from icesee_jupyter_book.applications.frozen_legacies.radar.intake_manifest import (
    IntakeManifestError,
    complete_item,
    duplicate_items,
    fail_item,
    manifest_digest,
    new_checkpoint,
    pending_items,
    read_checkpoint,
    validate_manifest,
    write_checkpoint,
)


def manifest():
    return {
        "schema": "cryostack.frozen_legacies.intake-manifest",
        "version": 1,
        "dataset_id": "sprifilm-127",
        "provenance": {
            "source": "Data-owner transfer 2026-10-16",
            "supplied_by": "Named data custodian",
            "received_at": "2026-10-16T12:00:00Z",
        },
        "items": [
            {"id": "film", "role": "raw-tiff", "availability": "available",
             "scientific_status": "source", "storage_key": "tiff/F127-C0471_C0483.tiff",
             "bytes": 120, "sha256": "1" * 64},
            {"id": "digitized", "role": "digitized-radar", "availability": "available",
             "scientific_status": "source", "storage_key": "digitized/F127.csv",
             "bytes": 44, "sha256": "2" * 64,
             "relationships": [{"type": "digitizes", "target": "film"}]},
            {"id": "picker", "role": "automatic-output", "availability": "available",
             "scientific_status": "unvalidated", "storage_key": "automatic/F127.csv",
             "bytes": 55, "sha256": "3" * 64,
             "relationships": [{"type": "derived-from", "target": "digitized"}]},
            {"id": "pdf", "role": "preview-pdf", "availability": "unavailable",
             "scientific_status": "not-scientific",
             "reason": "Optional display derivative has not been generated.",
             "relationships": [{"type": "derived-from", "target": "film"}]},
        ],
    }


def test_manifest_preserves_product_graph_and_placeholder():
    checked = validate_manifest(manifest())
    assert [item["role"] for item in checked["items"]] == [
        "raw-tiff", "digitized-radar", "automatic-output", "preview-pdf"]
    assert checked["items"][-1]["availability"] == "unavailable"
    assert len(manifest_digest(checked)) == 64


@pytest.mark.parametrize("mutation, message", [
    (lambda d: d["items"][0].update(storage_key="../../outside.tiff"), "relative"),
    (lambda d: d["items"][2].update(scientific_status="source"), "unvalidated"),
    (lambda d: d["items"][3].update(sha256="4" * 64), "cannot claim"),
    (lambda d: d["items"][1].update(relationships=[]), "must identify"),
    (lambda d: d["items"][2]["relationships"][0].update(target="missing"), "absent"),
])
def test_manifest_rejects_unsafe_or_misleading_declarations(mutation, message):
    document = manifest()
    mutation(document)
    with pytest.raises(IntakeManifestError, match=message):
        validate_manifest(document)


def test_checkpoint_is_idempotent_and_resumes_only_changed_items(tmp_path):
    document = manifest()
    checkpoint = new_checkpoint(document)
    assert [item["id"] for item in pending_items(document, checkpoint)] == [
        "film", "digitized", "picker"]
    checkpoint = complete_item(document, checkpoint, "film")
    assert [item["id"] for item in pending_items(document, checkpoint)] == [
        "digitized", "picker"]

    path = tmp_path / "checkpoint.json"
    write_checkpoint(path, checkpoint, document)
    loaded = read_checkpoint(path, document)
    assert loaded == checkpoint

    revised = copy.deepcopy(document)
    revised["items"][0]["sha256"] = "9" * 64
    assert [item["id"] for item in pending_items(revised, loaded)] == ["film", "digitized", "picker"]


def test_checkpoint_durably_reports_failure_and_completion_clears_it(tmp_path):
    document = manifest()
    checkpoint = fail_item(document, new_checkpoint(document), "film",
                           OSError("read failed at /private/archive/source.tiff"), failed_at=42)
    checkpoint = fail_item(document, checkpoint, "film", "retry failed", failed_at=43)
    failure = checkpoint["failures"]["film"]
    assert failure["attempts"] == 2 and failure["failed_at"] == 43
    assert "/private/archive" not in failure["error"]
    assert [item["id"] for item in pending_items(document, checkpoint)][0] == "film"

    path = tmp_path / "checkpoint.json"
    write_checkpoint(path, checkpoint, document)
    loaded = read_checkpoint(path, document)
    assert loaded["failures"] == checkpoint["failures"]
    assert "film" not in complete_item(document, loaded, "film")["failures"]


def test_manifest_rejects_duplicate_object_identity_and_reports_equal_content():
    document = manifest()
    duplicate_key = copy.deepcopy(document["items"][0])
    duplicate_key["id"] = "film-copy"
    document["items"].append(duplicate_key)
    with pytest.raises(IntakeManifestError, match="storage_key duplicates"):
        validate_manifest(document)

    document = manifest()
    duplicate_content = copy.deepcopy(document["items"][0])
    duplicate_content.update(id="film-copy", storage_key="copies/film.tiff")
    document["items"].append(duplicate_content)
    duplicates = duplicate_items(document)
    assert len(duplicates) == 1
    assert {item["id"] for item in duplicates[0]["items"]} == {"film", "film-copy"}


def test_checkpoint_write_is_valid_json_and_missing_file_starts_clean(tmp_path):
    path = tmp_path / "state" / "checkpoint.json"
    clean = read_checkpoint(path, manifest())
    write_checkpoint(path, clean, manifest())
    assert json.loads(path.read_text())["completed"] == {}


def test_placeholder_cannot_be_marked_complete():
    document = manifest()
    with pytest.raises(IntakeManifestError, match="available"):
        complete_item(document, new_checkpoint(document), "pdf")
