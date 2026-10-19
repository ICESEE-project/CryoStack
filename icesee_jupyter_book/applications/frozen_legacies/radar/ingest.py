"""Validation of raw radar TIFFs and navigation CSVs.

A raw radar TIFF is the scanned film image (for example an A-scope strip such
as ``F127-C0471_C0483.tiff``). Nothing here interprets its pixels
scientifically; it only checks that the file is a single-image TIFF of a
supported mode and bounded size, that it decodes completely, and reads the
flight/CBD metadata that ASTRA derives from the filename.

Navigation CSVs carry ``CBD, LAT, LON`` (ASTRA's required columns) and may
carry ``THK`` and ``SRF``. ``9999`` marks an unavailable value and is
reported as missing, never as a measurement.
"""
from __future__ import annotations

import csv
import io
import math
import os
import re
import warnings
from pathlib import Path
from urllib.parse import unquote

from PIL import Image


class RadarValidationError(ValueError):
    """A radar TIFF or navigation file was rejected."""


# ── TIFF ─────────────────────────────────────────────────────────────

TIFF_SUFFIXES = frozenset({".tif", ".tiff"})

#: little/big-endian classic TIFF and BigTIFF signatures
TIFF_MAGIC = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")

#: grayscale film scans; the reference A-scope TIFFs are 16-bit ("I;16")
SUPPORTED_MODES = frozenset({"I;16", "I;16L", "I;16B", "L"})

MAX_WIDTH = 200_000
MAX_HEIGHT = 20_000
#: kept below Pillow's hard decompression-bomb limit (2 x MAX_IMAGE_PIXELS),
#: so the explicit checks here are what bound the decode
MAX_PIXELS = 160_000_000

_FILENAME_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def safe_original_filename(raw: object) -> str:
    """The display name of an uploaded TIFF: its basename, with control
    characters removed. It is metadata only and never used as a path.

    Multipart clients may percent-encode the filename; it is decoded before
    the basename is taken, so encoded separators cannot survive."""
    name = unquote(str(raw or "")).replace("\\", "/").rsplit("/", 1)[-1]
    name = _FILENAME_CONTROL.sub("", name).strip()
    if not name or name in {".", ".."} or len(name) > 200:
        raise RadarValidationError("The uploaded file needs a valid TIFF filename.")
    if Path(name).suffix.lower() not in TIFF_SUFFIXES:
        raise RadarValidationError("Radar images must be .tif or .tiff files.")
    return name


def check_tiff_signature(head: bytes) -> None:
    if not any(head.startswith(magic) for magic in TIFF_MAGIC):
        raise RadarValidationError("The file is not a TIFF image.")


def extract_flight_info(filename):
    """Flight number and CBD range from a TIFF filename.

    Ported unchanged from ``extract_flight_info`` in ``Pickers/ASTRA_MAC.py``.
    Supports formats like:
      F125-C0132_C0142, F125_C0132-C0142, F125-C0132-C0142, F125_C0132_C0142
    Returns: (flight_number, cbd_start, cbd_end)
    """
    try:
        basename = os.path.splitext(os.path.basename(filename))[0]
        # Match F<digits> followed by C<digits> and C<digits> with separators (-, _, space)
        match = re.search(r'F(\d+)[-_ ]*C(\d+)[-_ ]*C?(\d+)', basename, re.IGNORECASE)
        if match:
            flight_num, cbd_s, cbd_e = match.groups()
            return flight_num, int(cbd_s), int(cbd_e)

        # Fallback: search for F followed by numbers, and C followed by numbers
        f_match = re.search(r'F(\d+)', basename, re.IGNORECASE)
        c_matches = re.findall(r'C(\d+)', basename, re.IGNORECASE)
        if f_match and len(c_matches) >= 2:
            return f_match.group(1), int(c_matches[0]), int(c_matches[1])

        return None, None, None
    except Exception:
        return None, None, None


def _open_tiff(path: Path) -> Image.Image:
    with path.open("rb") as handle:
        check_tiff_signature(handle.read(4))
    with warnings.catch_warnings():
        # Size is bounded explicitly below; the large reference scans exceed
        # Pillow's default warning threshold.
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        try:
            image = Image.open(path)
        except (Image.DecompressionBombError, OSError, ValueError) as error:
            raise RadarValidationError(f"The TIFF could not be read: {error}")
    if image.format != "TIFF":
        image.close()
        raise RadarValidationError("The file is not a TIFF image.")
    return image


def _header_info(image: Image.Image, size: int) -> dict:
    width, height = image.size
    frames = int(getattr(image, "n_frames", 1) or 1)
    if frames != 1:
        raise RadarValidationError("Multi-page TIFFs are not supported.")
    if image.mode not in SUPPORTED_MODES:
        raise RadarValidationError(
            f"Unsupported TIFF image mode {image.mode!r}; "
            "expected an 8-bit or 16-bit grayscale scan."
        )
    if not (0 < width <= MAX_WIDTH and 0 < height <= MAX_HEIGHT):
        raise RadarValidationError(
            f"TIFF dimensions {width} x {height} are outside the supported range."
        )
    if width * height > MAX_PIXELS:
        raise RadarValidationError(
            f"TIFF has {width * height:,} pixels; the limit is {MAX_PIXELS:,}."
        )
    return {
        "format": "TIFF",
        "mode": image.mode,
        "width": width,
        "height": height,
        "compression": str(image.info.get("compression") or "raw"),
        "bytes": size,
    }


def read_tiff_header(path: str | Path) -> dict:
    """Validate the TIFF header only (cheap; no pixel decode)."""
    path = Path(path)
    image = _open_tiff(path)
    try:
        return _header_info(image, path.stat().st_size)
    finally:
        image.close()


def read_tiff_header_stream(stream, *, size: int) -> dict:
    """Validate a TIFF header from a seekable binary stream (for example
    ranged reads of a remote object), without reading the pixel data."""
    stream.seek(0)
    check_tiff_signature(stream.read(4))
    stream.seek(0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        try:
            image = Image.open(stream)
        except (Image.DecompressionBombError, OSError, ValueError) as error:
            raise RadarValidationError(f"The TIFF could not be read: {error}")
    try:
        if image.format != "TIFF":
            raise RadarValidationError("The file is not a TIFF image.")
        return _header_info(image, size)
    finally:
        image.close()


def validate_tiff(path: str | Path) -> dict:
    """Validate the header and decode every pixel (detects truncation)."""
    path = Path(path)
    image = _open_tiff(path)
    try:
        info = _header_info(image, path.stat().st_size)
        with warnings.catch_warnings():
            # _header_info applies the application's explicit, stricter pixel
            # bound before decoding; Pillow may emit its generic warning only
            # when load() reads the first strip.
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            try:
                image.load()
            except (OSError, ValueError, SyntaxError) as error:
                raise RadarValidationError(
                    f"The TIFF image data is incomplete or corrupt: {error}"
                )
        return info
    finally:
        image.close()


# ── navigation CSV ───────────────────────────────────────────────────

NAV_REQUIRED_COLUMNS = ("CBD", "LAT", "LON")
NAV_OPTIONAL_COLUMNS = ("THK", "SRF")
#: unavailable-value marker used by the navigation files
NAV_MISSING_VALUE = 9999.0

MAX_NAV_BYTES = 5 * 1024 * 1024
MAX_NAV_ROWS = 200_000


def _nav_number(raw: str, column: str, line: int) -> float | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        raise RadarValidationError(f"Navigation line {line}: {column} is not a number.")
    if not math.isfinite(value):
        raise RadarValidationError(f"Navigation line {line}: {column} is not finite.")
    if value == NAV_MISSING_VALUE:
        return None
    return value


def read_nav_csv(path: str | Path) -> list[dict]:
    """Parse and validate a navigation CSV.

    Returns one record per row in file order:
    ``{"cbd": int, "lat": float|None, "lon": float|None, "thk": ..., "srf": ...}``.
    """
    path = Path(path)
    size = path.stat().st_size
    if size > MAX_NAV_BYTES:
        raise RadarValidationError(
            f"Navigation file is {size // 1024} KB; the limit is {MAX_NAV_BYTES // 1024} KB."
        )
    return read_nav_bytes(path.read_bytes())


def read_nav_bytes(data: bytes) -> list[dict]:
    """:func:`read_nav_csv` for navigation content already read (e.g. from a
    storage provider)."""
    if len(data) > MAX_NAV_BYTES:
        raise RadarValidationError(
            f"Navigation file is {len(data) // 1024} KB; the limit is {MAX_NAV_BYTES // 1024} KB."
        )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise RadarValidationError("Navigation file must be UTF-8 CSV text.")

    reader = csv.DictReader(io.StringIO(text, newline=""))
    columns = [c.strip() for c in (reader.fieldnames or [])]
    missing = [c for c in NAV_REQUIRED_COLUMNS if c not in columns]
    if missing:
        raise RadarValidationError(
            "Navigation file is missing required column(s): " + ", ".join(missing)
        )
    reader.fieldnames = columns

    rows: list[dict] = []
    for line, raw in enumerate(reader, start=2):
        if len(rows) >= MAX_NAV_ROWS:
            raise RadarValidationError(f"Navigation file has more than {MAX_NAV_ROWS:,} rows.")
        if None in raw:
            raise RadarValidationError(f"Navigation line {line} has extra fields.")
        # CBD is an identifier, not a measurement: 9999 is not a missing marker here.
        try:
            cbd = float((raw.get("CBD") or "").strip())
        except ValueError:
            cbd = math.nan
        if not math.isfinite(cbd) or not cbd.is_integer():
            raise RadarValidationError(f"Navigation line {line}: CBD must be an integer.")
        lat = _nav_number(raw.get("LAT"), "LAT", line)
        lon = _nav_number(raw.get("LON"), "LON", line)
        if lat is not None and not -90.0 <= lat <= 90.0:
            raise RadarValidationError(f"Navigation line {line}: LAT is out of range.")
        if lon is not None and not -180.0 <= lon <= 360.0:
            raise RadarValidationError(f"Navigation line {line}: LON is out of range.")
        record = {"cbd": int(cbd), "lat": lat, "lon": lon}
        for column in NAV_OPTIONAL_COLUMNS:
            if column in columns:
                record[column.lower()] = _nav_number(raw.get(column), column, line)
        rows.append(record)

    if not rows:
        raise RadarValidationError("Navigation file has no data rows.")
    return rows


def summarize_nav(rows: list[dict], *, cbd_start=None, cbd_end=None) -> dict:
    """Counts describing a parsed navigation table (no interpolation)."""
    cbds = [r["cbd"] for r in rows]
    summary = {
        "rows": len(rows),
        "cbd_min": min(cbds),
        "cbd_max": max(cbds),
        "positions": sum(1 for r in rows if r["lat"] is not None and r["lon"] is not None),
        "duplicate_cbds": len(cbds) - len(set(cbds)),
        "thk_available": sum(1 for r in rows if r.get("thk") is not None),
        "srf_available": sum(1 for r in rows if r.get("srf") is not None),
        "missing_value": NAV_MISSING_VALUE,
    }
    if cbd_start is not None and cbd_end is not None:
        lo, hi = sorted((cbd_start, cbd_end))
        present = {c for c in cbds if lo <= c <= hi}
        summary["cbd_range_rows"] = len(present)
        summary["cbd_range_size"] = hi - lo + 1
    return summary


def nav_rows_in_range(rows: list[dict], cbd_start, cbd_end) -> list[dict]:
    """Navigation records for CBDs in ``[cbd_start, cbd_end]``.

    The first row per CBD is used, matching ASTRA's exact-match lookup
    (``get_coordinates_for_cbd``). No values are interpolated.
    """
    if cbd_start is None or cbd_end is None:
        return []
    lo, hi = sorted((cbd_start, cbd_end))
    seen: dict[int, dict] = {}
    for row in rows:
        if lo <= row["cbd"] <= hi and row["cbd"] not in seen:
            seen[row["cbd"]] = row
    return [seen[c] for c in sorted(seen)]
