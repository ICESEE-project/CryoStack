import hashlib
import json
from pathlib import Path

import pytest

from icesee_jupyter_book.applications.frozen_legacies import riggs_context as R
from icesee_jupyter_book.applications.frozen_legacies.radar import storage


CSV = """Station,Latitude,Longitude,"h_i (radar), m","h_i (seismics), m"
A1,82 deg 30'S,170 deg 15'W,415,410
B2,-81.25,178.5,522,
C3,80 deg 10'S,160 deg 20'E,,
"""


def _install(root: Path, *, csv_text: str = CSV, digest: str | None = None):
    csv_path = root / "riggs_stations.csv"
    csv_path.write_text(csv_text, encoding="utf-8")
    checksum = digest or hashlib.sha256(csv_path.read_bytes()).hexdigest()
    manifest = root / "riggs.manifest.json"
    manifest.write_text(json.dumps({
        "schema": R.MANIFEST_SCHEMA,
        "version": 1,
        "title": "RIGGS ice-thickness stations",
        "citation": "Bentley (1984), Ross Ice Shelf Geophysical and Glaciological Survey.",
        "source_url": "https://example.edu/approved-riggs-record",
        "sha256": checksum,
    }), encoding="utf-8")
    return csv_path, manifest


def test_unconfigured_riggs_is_empty(monkeypatch):
    monkeypatch.delenv(R.CSV_ENV, raising=False)
    monkeypatch.delenv(R.MANIFEST_ENV, raising=False)
    result = R.riggs_collection()
    assert result["available"] is False
    assert result["stations"]["features"] == []


def test_verified_riggs_preserves_methods_and_provenance(tmp_path, monkeypatch):
    csv_path, manifest = _install(tmp_path)
    monkeypatch.setenv(storage.STORAGE_ROOTS_ENV, str(tmp_path))
    monkeypatch.setenv(R.CSV_ENV, str(csv_path))
    monkeypatch.setenv(R.MANIFEST_ENV, str(manifest))

    result = R.riggs_collection()

    assert result["summary"] == {"stations": 2, "seismic": 1, "radar": 1}
    assert result["metadata"]["sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest()
    assert "not Frozen Legacies picks" in result["metadata"]["note"]
    by_id = {feature["properties"]["station"]: feature for feature in result["stations"]["features"]}
    assert by_id["A1"]["geometry"]["coordinates"] == pytest.approx([-170.25, -82.5])
    assert by_id["A1"]["properties"]["measurement_method"] == "seismic"
    assert by_id["A1"]["properties"]["ice_thickness_m"] == 410
    assert by_id["B2"]["properties"]["measurement_method"] == "radar"


def test_riggs_rejects_checksum_mismatch(tmp_path, monkeypatch):
    csv_path, manifest = _install(tmp_path, digest="0" * 64)
    monkeypatch.setenv(storage.STORAGE_ROOTS_ENV, str(tmp_path))
    monkeypatch.setenv(R.CSV_ENV, str(csv_path))
    monkeypatch.setenv(R.MANIFEST_ENV, str(manifest))
    with pytest.raises(ValueError, match="checksum"):
        R.riggs_collection()


def test_riggs_files_must_be_on_approved_storage(tmp_path, monkeypatch):
    csv_path, manifest = _install(tmp_path)
    approved = tmp_path / "approved"
    approved.mkdir()
    monkeypatch.setenv(storage.STORAGE_ROOTS_ENV, str(approved))
    monkeypatch.setenv(R.CSV_ENV, str(csv_path))
    monkeypatch.setenv(R.MANIFEST_ENV, str(manifest))
    with pytest.raises(storage.StorageKeyError):
        R.riggs_collection()


def test_riggs_requires_complete_provenance_pair(tmp_path, monkeypatch):
    csv_path, _ = _install(tmp_path)
    monkeypatch.setenv(storage.STORAGE_ROOTS_ENV, str(tmp_path))
    monkeypatch.setenv(R.CSV_ENV, str(csv_path))
    monkeypatch.delenv(R.MANIFEST_ENV, raising=False)
    with pytest.raises(ValueError, match="configured together"):
        R.riggs_collection()


def test_riggs_allows_explicit_citation_pending_but_blocks_publication(tmp_path, monkeypatch):
    csv_path, manifest = _install(tmp_path)
    document = json.loads(manifest.read_text())
    document.update({"citation": "", "source_url": "", "citation_pending": True})
    manifest.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setenv(storage.STORAGE_ROOTS_ENV, str(tmp_path))
    monkeypatch.setenv(R.CSV_ENV, str(csv_path))
    monkeypatch.setenv(R.MANIFEST_ENV, str(manifest))

    result = R.riggs_collection()

    assert result["available"] is True
    assert result["metadata"]["citation_pending"] is True
    assert result["metadata"]["publication_eligible"] is False
    assert all(not feature["properties"]["publication_eligible"]
               for feature in result["stations"]["features"])


def test_riggs_rejects_partial_provenance_marked_pending(tmp_path, monkeypatch):
    csv_path, manifest = _install(tmp_path)
    document = json.loads(manifest.read_text())
    document.update({"citation_pending": True, "source_url": ""})
    manifest.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setenv(storage.STORAGE_ROOTS_ENV, str(tmp_path))
    monkeypatch.setenv(R.CSV_ENV, str(csv_path))
    monkeypatch.setenv(R.MANIFEST_ENV, str(manifest))
    with pytest.raises(ValueError, match="partial provenance"):
        R.riggs_collection()
