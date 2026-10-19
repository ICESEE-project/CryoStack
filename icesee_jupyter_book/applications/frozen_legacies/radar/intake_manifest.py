"""Validated manifests and restart-safe hooks for scientific-data intake.

This module describes files; it does not copy, interpret, or publish them.
In particular, an ``unavailable`` item is an explicit expectation and never a
synthetic observation.  Storage providers may feed the validated, pending
items into the existing :mod:`radar.catalog` incremental indexer.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path, PurePosixPath

from cryostack_src.storage_layout import atomic_write


MANIFEST_SCHEMA = "cryostack.frozen_legacies.intake-manifest"
MANIFEST_VERSION = 1
CHECKPOINT_SCHEMA = "cryostack.frozen_legacies.intake-checkpoint"
CHECKPOINT_VERSION = 1

ROLES = frozenset({
    "raw-tiff", "radargram", "digitized-radar", "navigation",
    "automatic-output", "preview-pdf",
})
AVAILABILITY = frozenset({"available", "unavailable"})
SCIENTIFIC_STATUS = frozenset({"source", "unvalidated", "not-scientific"})
RELATIONSHIPS = frozenset({"derived-from", "digitizes", "visualizes", "navigation-for"})

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class IntakeManifestError(ValueError):
    """The intake declaration or checkpoint is unsafe or inconsistent."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def manifest_digest(manifest: dict) -> str:
    """Digest of a normalized, validated manifest."""
    return hashlib.sha256(_canonical(manifest)).hexdigest()


def item_fingerprint(dataset_id: str, item: dict) -> str:
    """Stable idempotency key; changes whenever an item's declaration does."""
    body = {"dataset_id": dataset_id, "item": item}
    return hashlib.sha256(_canonical(body)).hexdigest()


def duplicate_items(manifest: dict) -> list[dict]:
    """Return available items with identical declared content.

    Equal checksums are reported rather than rejected: an archive can
    intentionally retain byte-identical products under distinct identities.
    Callers can therefore stop accidental duplicate work while preserving an
    operator's ability to review legitimate copies.
    """
    checked = validate_manifest(manifest)
    groups: dict[tuple[int, str], list[dict]] = {}
    for item in checked["items"]:
        if item["availability"] == "available":
            groups.setdefault((item["bytes"], item["sha256"]), []).append(item)
    return [{"bytes": size, "sha256": digest,
             "items": [{"id": item["id"], "storage_key": item["storage_key"]}
                       for item in items]}
            for (size, digest), items in groups.items() if len(items) > 1]


def _relative_storage_key(raw: object, *, item_id: str) -> str:
    value = str(raw or "").strip().replace("\\", "/")
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or ".." in path.parts or "." in path.parts
            or value.endswith("/")):
        raise IntakeManifestError(f"Item {item_id}: storage_key must be a relative object key.")
    return value


def validate_manifest(document: object) -> dict:
    """Return a normalized copy of a version-1 intake manifest.

    Validation intentionally covers identity, provenance and relationships,
    not scientific truth. It never infers coordinates, picks, calibration, or
    a missing file from a filename.
    """
    if not isinstance(document, dict):
        raise IntakeManifestError("The intake manifest must be a JSON object.")
    if document.get("schema") != MANIFEST_SCHEMA or document.get("version") != 1:
        raise IntakeManifestError("Unsupported intake manifest schema or version.")
    dataset_id = document.get("dataset_id")
    if not isinstance(dataset_id, str) or not _ID.fullmatch(dataset_id):
        raise IntakeManifestError("dataset_id is missing or invalid.")
    provenance = document.get("provenance")
    if not isinstance(provenance, dict):
        raise IntakeManifestError("A provenance object is required.")
    for field in ("source", "supplied_by", "received_at"):
        if not isinstance(provenance.get(field), str) or not provenance[field].strip():
            raise IntakeManifestError(f"Provenance field {field!r} is required.")
    items = document.get("items")
    if not isinstance(items, list) or not items:
        raise IntakeManifestError("The manifest must declare at least one item.")

    normalized_items: list[dict] = []
    ids: set[str] = set()
    storage_keys: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise IntakeManifestError("Every manifest item must be an object.")
        item = dict(raw)
        item_id = item.get("id")
        if not isinstance(item_id, str) or not _ID.fullmatch(item_id) or item_id in ids:
            raise IntakeManifestError("Item IDs must be unique safe identifiers.")
        ids.add(item_id)
        role = item.get("role")
        availability = item.get("availability")
        scientific_status = item.get("scientific_status")
        if role not in ROLES:
            raise IntakeManifestError(f"Item {item_id}: unsupported role.")
        if availability not in AVAILABILITY:
            raise IntakeManifestError(f"Item {item_id}: availability must be explicit.")
        if scientific_status not in SCIENTIFIC_STATUS:
            raise IntakeManifestError(f"Item {item_id}: scientific_status must be explicit.")
        if role == "automatic-output" and scientific_status != "unvalidated":
            raise IntakeManifestError(
                f"Item {item_id}: automatic output must remain scientifically unvalidated.")
        if availability == "available":
            item["storage_key"] = _relative_storage_key(item.get("storage_key"), item_id=item_id)
            if item["storage_key"] in storage_keys:
                raise IntakeManifestError(
                    f"Item {item_id}: storage_key duplicates another available item.")
            storage_keys.add(item["storage_key"])
            if not isinstance(item.get("bytes"), int) or item["bytes"] < 0:
                raise IntakeManifestError(f"Item {item_id}: bytes must be a non-negative integer.")
            if not isinstance(item.get("sha256"), str) or not _SHA256.fullmatch(item["sha256"]):
                raise IntakeManifestError(f"Item {item_id}: a lowercase SHA-256 is required.")
            if item.get("reason"):
                raise IntakeManifestError(f"Item {item_id}: available items cannot be placeholders.")
        else:
            if scientific_status != "not-scientific":
                raise IntakeManifestError(
                    f"Item {item_id}: unavailable placeholders must be marked not-scientific.")
            if not isinstance(item.get("reason"), str) or not item["reason"].strip():
                raise IntakeManifestError(f"Item {item_id}: placeholder reason is required.")
            if any(key in item for key in ("storage_key", "bytes", "sha256")):
                raise IntakeManifestError(
                    f"Item {item_id}: a placeholder cannot claim file identity or content.")
        relationships = item.get("relationships", [])
        if not isinstance(relationships, list):
            raise IntakeManifestError(f"Item {item_id}: relationships must be a list.")
        for relation in relationships:
            if (not isinstance(relation, dict) or relation.get("type") not in RELATIONSHIPS
                    or not isinstance(relation.get("target"), str)):
                raise IntakeManifestError(f"Item {item_id}: invalid relationship.")
            if relation["target"] == item_id:
                raise IntakeManifestError(f"Item {item_id}: relationships cannot be self-referential.")
        item["relationships"] = relationships
        normalized_items.append(item)

    by_id = {item["id"]: item for item in normalized_items}
    for item in normalized_items:
        for relation in item["relationships"]:
            if relation["target"] not in by_id:
                raise IntakeManifestError(
                    f"Item {item['id']}: relationship target {relation['target']!r} is absent.")
        if item["availability"] != "available":
            continue
        parents = [by_id[r["target"]] for r in item["relationships"]]
        if item["role"] == "digitized-radar" and not any(
                r["type"] == "digitizes" and by_id[r["target"]]["role"] == "raw-tiff"
                for r in item["relationships"]):
            raise IntakeManifestError(
                f"Item {item['id']}: digitized radar must identify the raw TIFF it digitizes.")
        if item["role"] == "automatic-output" and not any(
                parent["role"] in {"raw-tiff", "digitized-radar"} for parent in parents):
            raise IntakeManifestError(
                f"Item {item['id']}: automatic output must identify its source product.")

    normalized = dict(document)
    normalized["provenance"] = dict(provenance)
    normalized["items"] = normalized_items
    return normalized


def new_checkpoint(manifest: dict) -> dict:
    manifest = validate_manifest(manifest)
    return {"schema": CHECKPOINT_SCHEMA, "version": CHECKPOINT_VERSION,
            "dataset_id": manifest["dataset_id"], "manifest_digest": manifest_digest(manifest),
            "completed": {}, "failures": {}}


def validate_checkpoint(document: object, manifest: dict) -> dict:
    manifest = validate_manifest(manifest)
    if not isinstance(document, dict):
        raise IntakeManifestError("The intake checkpoint must be a JSON object.")
    if document.get("schema") != CHECKPOINT_SCHEMA or document.get("version") != 1:
        raise IntakeManifestError("Unsupported intake checkpoint schema or version.")
    if document.get("dataset_id") != manifest["dataset_id"]:
        raise IntakeManifestError("The checkpoint belongs to another dataset.")
    completed = document.get("completed")
    if not isinstance(completed, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) or not _SHA256.fullmatch(v)
            for k, v in completed.items()):
        raise IntakeManifestError("The checkpoint completed map is invalid.")
    failures = document.get("failures", {})
    if not isinstance(failures, dict):
        raise IntakeManifestError("The checkpoint failures map is invalid.")
    item_ids = {item["id"] for item in manifest["items"]}
    for item_id, failure in failures.items():
        if (item_id not in item_ids or not isinstance(failure, dict)
                or not isinstance(failure.get("fingerprint"), str)
                or not _SHA256.fullmatch(failure["fingerprint"])
                or not isinstance(failure.get("attempts"), int) or failure["attempts"] < 1
                or not isinstance(failure.get("error"), str) or not failure["error"]
                or not isinstance(failure.get("failed_at"), (int, float))):
            raise IntakeManifestError("The checkpoint failures map is invalid.")
    result = dict(document)
    result["manifest_digest"] = manifest_digest(manifest)
    result["completed"] = dict(completed)
    result["failures"] = {key: dict(value) for key, value in failures.items()}
    return result


def pending_items(manifest: dict, checkpoint: dict | None = None) -> list[dict]:
    """Items needing work, preserving manifest order.

    Unavailable placeholders are documentation and never indexing work.
    Previously completed items are skipped only when their full declaration is
    byte-for-byte equivalent after canonical JSON normalization.
    """
    manifest = validate_manifest(manifest)
    checkpoint = (new_checkpoint(manifest) if checkpoint is None
                  else validate_checkpoint(checkpoint, manifest))
    complete = checkpoint["completed"]
    return [item for item in manifest["items"]
            if item["availability"] == "available"
            and complete.get(item["id"]) != item_fingerprint(manifest["dataset_id"], item)]


def complete_item(manifest: dict, checkpoint: dict, item_id: str) -> dict:
    """Return an updated checkpoint after the caller durably indexed an item."""
    manifest = validate_manifest(manifest)
    checkpoint = validate_checkpoint(checkpoint, manifest)
    item = next((item for item in manifest["items"] if item["id"] == item_id), None)
    if item is None or item["availability"] != "available":
        raise IntakeManifestError("Only an available manifest item can be completed.")
    result = dict(checkpoint)
    result["completed"] = dict(checkpoint["completed"])
    result["completed"][item_id] = item_fingerprint(manifest["dataset_id"], item)
    result["failures"] = dict(checkpoint["failures"])
    result["failures"].pop(item_id, None)
    return result


def fail_item(manifest: dict, checkpoint: dict, item_id: str, error: object,
              *, failed_at: float | None = None) -> dict:
    """Return a checkpoint recording a bounded, non-sensitive item failure."""
    manifest = validate_manifest(manifest)
    checkpoint = validate_checkpoint(checkpoint, manifest)
    item = next((item for item in manifest["items"] if item["id"] == item_id), None)
    if item is None or item["availability"] != "available":
        raise IntakeManifestError("Only an available manifest item can fail.")
    previous = checkpoint["failures"].get(item_id, {})
    message = re.sub(r"(/[^\s'\"]+)+", "…", str(error)).strip()[:300]
    result = dict(checkpoint)
    result["completed"] = dict(checkpoint["completed"])
    result["completed"].pop(item_id, None)
    result["failures"] = dict(checkpoint["failures"])
    result["failures"][item_id] = {
        "fingerprint": item_fingerprint(manifest["dataset_id"], item),
        "attempts": int(previous.get("attempts", 0)) + 1,
        "error": message or "Unspecified intake failure.",
        "failed_at": time.time() if failed_at is None else float(failed_at),
    }
    return result


def read_checkpoint(path: str | Path, manifest: dict) -> dict:
    path = Path(path)
    if not path.exists():
        return new_checkpoint(manifest)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise IntakeManifestError(f"The intake checkpoint could not be read: {error}") from error
    return validate_checkpoint(document, manifest)


def write_checkpoint(path: str | Path, checkpoint: dict, manifest: dict) -> None:
    """Atomically persist progress after the catalog transaction succeeds."""
    checked = validate_checkpoint(checkpoint, manifest)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(checked, indent=2, sort_keys=True,
                                       allow_nan=False).encode("utf-8"))
