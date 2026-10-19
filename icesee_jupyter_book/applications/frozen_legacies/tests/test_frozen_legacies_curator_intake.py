from __future__ import annotations

import io
import json
import zipfile

import pytest

from icesee_jupyter_book.applications.frozen_legacies.radar.curator_intake import (
    INTAKE_ROOT_ENV,
    intake_root,
    stage_intake,
)
from icesee_jupyter_book.applications.frozen_legacies.radar.storage import (
    STORAGE_ROOTS_ENV,
    StorageError,
)


def test_managed_root_must_be_operator_approved(tmp_path, monkeypatch):
    approved = tmp_path / "approved"
    monkeypatch.setenv(STORAGE_ROOTS_ENV, str(approved))
    monkeypatch.setenv(INTAKE_ROOT_ENV, str(approved / "intakes"))
    assert intake_root() == approved / "intakes"
    monkeypatch.setenv(INTAKE_ROOT_ENV, str(tmp_path / "outside"))
    with pytest.raises(StorageError, match="approved storage"):
        intake_root()


def test_stages_tiff_navigation_and_archive_with_unpublished_receipt(tmp_path):
    direct = tmp_path / "film.tiff"
    direct.write_bytes(b"II*\x00synthetic-header-only")
    archive = tmp_path / "flight.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("F127/127.csv", "CBD,LAT,LON\n")
        bundle.writestr("F127/F127-C0001_C0010.tif", b"MM\x00*synthetic")
    staging = tmp_path / "staging"
    receipt = stage_intake(staging, [(direct.name, direct), (archive.name, archive)],
                           dataset_id="dataset-127")
    assert receipt["publication_status"] == "unpublished"
    assert {item["scientific_status"] for item in receipt["items"]} == {"unverified"}
    assert {item["storage_key"] for item in receipt["items"]} == {
        "tiff/film.tiff", "nav/F127/127.csv", "tiff/F127/F127-C0001_C0010.tif"}
    assert all(len(item["sha256"]) == 64 for item in receipt["items"])
    assert json.loads((staging / "intake-receipt.json").read_text()) == receipt


@pytest.mark.parametrize("member", ["../escape.tiff", "/absolute.tiff", "folder/link.tiff"])
def test_unsafe_archive_is_rejected_and_staging_removed(tmp_path, member):
    archive = tmp_path / "bad.zip"
    info = zipfile.ZipInfo(member)
    if member.endswith("link.tiff"):
        info.external_attr = 0o120777 << 16
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(info, b"bad")
    staging = tmp_path / "staging"
    with pytest.raises(StorageError):
        stage_intake(staging, [(archive.name, archive)], dataset_id="dataset")
    assert not staging.exists()


def test_duplicate_destinations_and_missing_tiff_are_rejected(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    with pytest.raises(StorageError, match="duplicate"):
        stage_intake(tmp_path / "duplicate", [("film.tif", first), ("FILM.TIF", second)],
                     dataset_id="dataset")
    csv = tmp_path / "nav.csv"
    csv.write_text("CBD,LAT,LON\n")
    with pytest.raises(StorageError, match="at least one TIFF"):
        stage_intake(tmp_path / "csv-only", [(csv.name, csv)], dataset_id="dataset")
