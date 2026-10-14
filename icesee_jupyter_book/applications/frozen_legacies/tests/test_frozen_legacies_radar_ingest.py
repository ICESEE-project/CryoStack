"""Radar TIFF and navigation CSV validation, and the ASTRA filename parser."""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[3]
for _p in (str(_REPO), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from frozen_legacies_radar_fixtures import NAV_TEXT, radar_array, write_nav, write_tiff
from icesee_jupyter_book.applications.frozen_legacies.radar import ingest
from icesee_jupyter_book.applications.frozen_legacies.radar.ingest import (
    RadarValidationError,
    extract_flight_info,
    nav_rows_in_range,
    read_nav_csv,
    read_tiff_header,
    safe_original_filename,
    summarize_nav,
    validate_tiff,
)

_ASTRA = _HERE.parent / "Pickers" / "ASTRA_MAC.py"


# ── ASTRA filename metadata ──────────────────────────────────────────
_NAMES = [
    "F127-C0471_C0483.tiff", "F125_C0132-C0142.tif", "F125-C0132-C0142.TIFF",
    "F125_C0132_C0142.tiff", "f141 c0010 c0020.tif", "F125-C0921_0933.tiff",
    "scan_F7_x_C12_y_C40.tiff", "40_0009125_0009149-reel_begin_end.tiff",
    "no-metadata.tiff", "F12.tiff", "",
]


def _astra_extract_flight_info():
    """The unmodified function from the ASTRA reference script."""
    tree = ast.parse(_ASTRA.read_text(encoding="utf-8"))
    node = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "extract_flight_info"
    )
    namespace = {"os": os, "re": re}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(_ASTRA), "exec"), namespace)
    return namespace["extract_flight_info"]


@pytest.mark.skipif(not _ASTRA.is_file(), reason="ASTRA reference script not present")
@pytest.mark.parametrize("name", _NAMES)
def test_filename_parser_matches_astra(name):
    assert extract_flight_info(name) == _astra_extract_flight_info()(name)


def test_filename_parser_reference_cases():
    assert extract_flight_info("F127-C0471_C0483.tiff") == ("127", 471, 483)
    assert extract_flight_info("no-metadata.tiff") == (None, None, None)


@pytest.mark.parametrize("raw, expected", [
    ("F127-C0471_C0483.tiff", "F127-C0471_C0483.tiff"),
    ("../../etc/F1-C1_C2.tif", "F1-C1_C2.tif"),
    ("C:\\Users\\x\\F1-C1_C2.TIFF", "F1-C1_C2.TIFF"),
    ("F1\x00-C1_C2.tiff", "F1-C1_C2.tiff"),
    ("..%2F..%2FF1-C1_C2.tif", "F1-C1_C2.tif"),
    ("F1-C1_C2%2etiff", "F1-C1_C2.tiff"),
])
def test_original_filename_is_reduced_to_a_display_basename(raw, expected):
    assert safe_original_filename(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "..", "/", "image.png", "radar.tiff.exe", "a" * 300 + ".tif"])
def test_unsafe_or_non_tiff_filenames_are_rejected(raw):
    with pytest.raises(RadarValidationError):
        safe_original_filename(raw)


# ── TIFF validation ──────────────────────────────────────────────────
def test_valid_16bit_tiff(tmp_path):
    path = write_tiff(tmp_path / "F127-C0471_C0483.tiff")
    info = validate_tiff(path)
    assert info["mode"] == "I;16" and info["format"] == "TIFF"
    assert (info["width"], info["height"]) == (300, 40)
    assert info["compression"] == "tiff_lzw"
    assert read_tiff_header(path) == info


def test_valid_8bit_tiff(tmp_path):
    path = write_tiff(tmp_path / "a.tif", radar_array().astype(np.uint8))
    assert validate_tiff(path)["mode"] == "L"


def test_rgb_tiff_is_rejected(tmp_path):
    path = tmp_path / "rgb.tiff"
    Image.new("RGB", (20, 10)).save(path, format="TIFF")
    with pytest.raises(RadarValidationError, match="mode"):
        validate_tiff(path)


def test_multipage_tiff_is_rejected(tmp_path):
    path = tmp_path / "pages.tiff"
    frames = [Image.fromarray(radar_array(20, 10)) for _ in range(2)]
    frames[0].save(path, format="TIFF", save_all=True, append_images=frames[1:])
    with pytest.raises(RadarValidationError, match="Multi-page"):
        validate_tiff(path)


def test_truncated_tiff_is_rejected(tmp_path):
    path = write_tiff(tmp_path / "t.tiff", radar_array(400, 200), compression="raw")
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])
    with pytest.raises(RadarValidationError):
        validate_tiff(path)


@pytest.mark.parametrize("payload", [
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
    b"not a tiff at all",
    b"",
    b"II*\x00garbage-after-a-valid-signature",
])
def test_non_tiff_contents_are_rejected(tmp_path, payload):
    path = tmp_path / "fake.tiff"
    path.write_bytes(payload)
    with pytest.raises(RadarValidationError):
        validate_tiff(path)


def test_png_with_tiff_extension_is_rejected(tmp_path):
    path = tmp_path / "F1-C1_C2.tiff"
    Image.fromarray(radar_array(20, 10).astype(np.uint8)).save(path, format="PNG")
    with pytest.raises(RadarValidationError, match="not a TIFF"):
        validate_tiff(path)


def test_pixel_and_dimension_limits(tmp_path, monkeypatch):
    path = write_tiff(tmp_path / "a.tiff")
    monkeypatch.setattr(ingest, "MAX_PIXELS", 300 * 40 - 1)
    with pytest.raises(RadarValidationError, match="pixels"):
        read_tiff_header(path)
    monkeypatch.setattr(ingest, "MAX_PIXELS", 10**9)
    monkeypatch.setattr(ingest, "MAX_WIDTH", 299)
    with pytest.raises(RadarValidationError, match="dimensions"):
        read_tiff_header(path)


# ── navigation CSV ───────────────────────────────────────────────────
def test_nav_parsing_treats_9999_as_unavailable(tmp_path):
    rows = read_nav_csv(write_nav(tmp_path / "127.csv"))
    assert rows[1] == {
        "cbd": 471, "lat": -81.479401, "lon": -169.753098, "thk": None, "srf": None,
    }
    assert rows[3]["thk"] == 1200.5 and rows[3]["srf"] is None


def test_nav_summary_and_exact_range_rows(tmp_path):
    rows = read_nav_csv(write_nav(tmp_path / "127.csv"))
    summary = summarize_nav(rows, cbd_start=471, cbd_end=483)
    assert summary["rows"] == 5
    assert summary["cbd_range_rows"] == 4 and summary["cbd_range_size"] == 13
    assert summary["thk_available"] == 1 and summary["srf_available"] == 0
    assert summary["missing_value"] == 9999.0
    in_range = nav_rows_in_range(rows, 471, 483)
    assert [r["cbd"] for r in in_range] == [471, 472, 473, 483]   # no interpolation


def test_nav_duplicate_cbd_uses_first_row_like_astra(tmp_path):
    rows = read_nav_csv(write_nav(tmp_path / "n.csv", "CBD,LAT,LON\n5,-80,160\n5,-70,150\n"))
    assert summarize_nav(rows)["duplicate_cbds"] == 1
    assert nav_rows_in_range(rows, 5, 5)[0]["lat"] == -80.0


def test_nav_without_optional_columns_and_with_bom(tmp_path):
    path = tmp_path / "n.csv"
    path.write_bytes("\ufeffCBD,LAT,LON\n1,-80,160\n".encode("utf-8"))
    assert read_nav_csv(path) == [{"cbd": 1, "lat": -80.0, "lon": 160.0}]


def test_cbd_9999_is_an_identifier_not_a_missing_value(tmp_path):
    rows = read_nav_csv(write_nav(tmp_path / "n.csv", "CBD,LAT,LON\n9999,-80,160\n"))
    assert rows[0]["cbd"] == 9999


@pytest.mark.parametrize("text, message", [
    ("CBD,LAT\n1,-80\n", "missing required"),
    ("LAT,LON\n-80,160\n", "missing required"),
    ("CBD,LAT,LON\n1.5,-80,160\n", "CBD"),
    ("CBD,LAT,LON\nabc,-80,160\n", "CBD"),
    ("CBD,LAT,LON\n1,-95,160\n", "LAT"),
    ("CBD,LAT,LON\n1,-80,400\n", "LON"),
    ("CBD,LAT,LON\n1,north,160\n", "LAT"),
    ("CBD,LAT,LON\n1,nan,160\n", "LAT"),
    ("CBD,LAT,LON\n1,-80,160,extra\n", "extra"),
    ("CBD,LAT,LON\n", "no data"),
])
def test_invalid_nav_is_rejected(tmp_path, text, message):
    with pytest.raises(RadarValidationError, match=message):
        read_nav_csv(write_nav(tmp_path / "n.csv", text))


def test_oversized_or_binary_nav_is_rejected(tmp_path, monkeypatch):
    path = write_nav(tmp_path / "n.csv")
    monkeypatch.setattr(ingest, "MAX_NAV_BYTES", 10)
    with pytest.raises(RadarValidationError, match="limit"):
        read_nav_csv(path)
    monkeypatch.setattr(ingest, "MAX_NAV_BYTES", 10**6)
    path.write_bytes(b"\xff\xfe\x00binary")
    with pytest.raises(RadarValidationError, match="UTF-8"):
        read_nav_csv(path)


def test_nav_fixture_matches_the_reference_layout():
    assert NAV_TEXT.splitlines()[0] == "CBD,LAT,LON,THK,SRF"
