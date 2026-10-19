from pathlib import Path

import pytest

from icesee_jupyter_book.applications.frozen_legacies import navigation_flights as N
from icesee_jupyter_book.applications.frozen_legacies.radar import storage


def _nav(path: Path, positions):
    rows = ["CBD,LAT,LON,THK,SRF"]
    rows += [f"{index},{lat},{lon},1000,20" for index, (lon, lat) in enumerate(positions)]
    path.write_text("\n".join(rows) + "\n")


def test_unconfigured_navigation_collection_is_empty(monkeypatch):
    monkeypatch.delenv(N.ROOT_ENV, raising=False)
    result = N.navigation_collection()
    assert result["dataset"] is None
    assert result["flights"]["features"] == []


def test_navigation_collection_is_filtered_and_marks_imagery_pending(tmp_path, monkeypatch):
    root = tmp_path / "navigation"
    root.mkdir()
    _nav(root / "125.csv", [(-170, -80), (-169, -80.1), (-168, -80.2)])
    _nav(root / "127.csv", [(178, -81), (179, -81.1), (-179, -81.2), (-178, -81.3)])
    _nav(root / "999.csv", [(10, -80), (11, -81)])
    monkeypatch.setenv(storage.STORAGE_ROOTS_ENV, str(tmp_path))
    monkeypatch.setenv(N.ROOT_ENV, str(root))
    monkeypatch.setenv(N.FLIGHTS_ENV, "125,127")

    result = N.navigation_collection()

    assert result["dataset"]["availability"] == "navigation-only"
    assert result["dataset"]["capabilities"]["raw_radar"] is False
    assert result["summary"] == {"files": 3, "flights": 2, "invalid": 0}
    by_flight = {f["properties"]["flight"]: f for f in result["flights"]["features"]}
    assert set(by_flight) == {"125", "127"}
    assert by_flight["125"]["properties"]["imagery_available"] is False
    segments = by_flight["127"]["geometry"]["coordinates"]
    assert segments[0][-1][0] == 180.0
    assert segments[1][0][0] == -180.0


def test_navigation_root_must_be_operator_approved(tmp_path, monkeypatch):
    root = tmp_path / "navigation"
    root.mkdir()
    monkeypatch.setenv(storage.STORAGE_ROOTS_ENV, str(tmp_path / "approved"))
    monkeypatch.setenv(N.ROOT_ENV, str(root))
    with pytest.raises(storage.StorageKeyError):
        N.navigation_collection()


def test_invalid_navigation_file_is_counted_without_exposing_an_asset(tmp_path, monkeypatch):
    root = tmp_path / "navigation"
    root.mkdir()
    (root / "125.csv").write_text("not,navigation\n1,2\n")
    monkeypatch.setenv(storage.STORAGE_ROOTS_ENV, str(tmp_path))
    monkeypatch.setenv(N.ROOT_ENV, str(root))
    result = N.navigation_collection()
    assert result["summary"] == {"files": 1, "flights": 0, "invalid": 1}
    assert result["flights"]["features"] == []
