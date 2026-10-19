"""Verified RIGGS stations exposed as optional scientific map context.

RIGGS observations are independent reference measurements.  They are never
stored as Frozen Legacies picks and never imply validation of LYRA output.
The operator must install both a CSV and a provenance manifest on an approved
storage root; an unconfigured installation returns an empty collection.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
from pathlib import Path

from .radar.storage import LocalProvider


CSV_ENV = "CRYOSTACK_FROZEN_LEGACIES_RIGGS_CSV"
MANIFEST_ENV = "CRYOSTACK_FROZEN_LEGACIES_RIGGS_MANIFEST"
MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_STATIONS = 2_000
MANIFEST_SCHEMA = "cryostack.frozen_legacies.riggs_manifest"

_STATION = "Station"
_LATITUDE = "Latitude"
_LONGITUDE = "Longitude"
_RADAR = "h_i (radar), m"
_SEISMIC = "h_i (seismics), m"
_REQUIRED = {_STATION, _LATITUDE, _LONGITUDE, _RADAR, _SEISMIC}
_DMS = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(?:deg|°|\s)\s*"
    r"(?:(\d+(?:\.\d+)?)\s*['′]?)?\s*"
    r"(?:(\d+(?:\.\d+)?)\s*[\"″]?)?\s*([NSEW])\s*$",
    re.IGNORECASE,
)


def _coordinate(value: str, *, latitude: bool) -> float:
    raw = str(value or "").strip()
    try:
        result = float(raw)
    except ValueError:
        match = _DMS.fullmatch(raw.replace("''", '"'))
        if not match:
            raise ValueError("RIGGS coordinates must be decimal degrees or DMS.")
        degrees = float(match.group(1))
        minutes = float(match.group(2) or 0)
        seconds = float(match.group(3) or 0)
        if minutes >= 60 or seconds >= 60:
            raise ValueError("RIGGS DMS minutes and seconds must be below 60.")
        result = degrees + minutes / 60 + seconds / 3600
        if match.group(4).upper() in {"S", "W"}:
            result = -result
    limit = 90 if latitude else 180
    if not math.isfinite(result) or not -limit <= result <= limit:
        raise ValueError("RIGGS coordinate is outside its geographic range.")
    return result


def _measurement(value: str) -> float | None:
    raw = str(value or "").strip()
    if not raw or raw.lower() in {"nan", "na", "n/a", "none", "-"}:
        return None
    result = float(raw)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("RIGGS ice thickness must be a positive finite value.")
    return result


def _provider(path: Path) -> tuple[LocalProvider, str]:
    return LocalProvider(path.parent), path.name


def riggs_collection() -> dict:
    """Return a provenance-carrying GeoJSON collection or an empty result."""
    csv_raw = (os.environ.get(CSV_ENV) or "").strip()
    manifest_raw = (os.environ.get(MANIFEST_ENV) or "").strip()
    if not csv_raw and not manifest_raw:
        return {
            "available": False,
            "metadata": None,
            "stations": {"type": "FeatureCollection", "features": []},
            "summary": {"stations": 0, "seismic": 0, "radar": 0},
        }
    if not csv_raw or not manifest_raw:
        raise ValueError("RIGGS CSV and provenance manifest must be configured together.")

    csv_provider, csv_key = _provider(Path(csv_raw))
    manifest_provider, manifest_key = _provider(Path(manifest_raw))
    csv_bytes = csv_provider.read_bytes(csv_key, limit=MAX_CSV_BYTES)
    manifest = json.loads(manifest_provider.read_bytes(manifest_key, limit=64 * 1024))
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("version") != 1:
        raise ValueError("RIGGS provenance manifest has an unsupported schema.")
    digest = hashlib.sha256(csv_bytes).hexdigest()
    if manifest.get("sha256") != digest:
        raise ValueError("RIGGS CSV does not match its provenance manifest checksum.")
    citation = str(manifest.get("citation") or "").strip()
    source_url = str(manifest.get("source_url") or "").strip()
    citation_pending = manifest.get("citation_pending") is True
    if citation_pending:
        if citation or source_url:
            raise ValueError("A citation-pending RIGGS manifest must not contain partial provenance.")
    elif not citation or not source_url.startswith("https://"):
        raise ValueError("RIGGS manifest requires a citation and HTTPS source URL.")

    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig")))
    if not reader.fieldnames or not _REQUIRED.issubset(reader.fieldnames):
        raise ValueError("RIGGS CSV is missing required station fields.")
    features = []
    counts = {"seismic": 0, "radar": 0}
    seen = set()
    for index, row in enumerate(reader, start=2):
        if len(features) >= MAX_STATIONS:
            raise ValueError(f"RIGGS CSV exceeds the {MAX_STATIONS:,}-station limit.")
        station = str(row.get(_STATION) or "").strip()
        if not station or len(station) > 64 or station in seen:
            raise ValueError(f"RIGGS row {index} has a missing, duplicate, or invalid station ID.")
        seen.add(station)
        latitude = _coordinate(row.get(_LATITUDE, ""), latitude=True)
        longitude = _coordinate(row.get(_LONGITUDE, ""), latitude=False)
        seismic = _measurement(row.get(_SEISMIC, ""))
        radar = _measurement(row.get(_RADAR, ""))
        if seismic is None and radar is None:
            continue
        method, thickness = ("seismic", seismic) if seismic is not None else ("radar", radar)
        counts[method] += 1
        features.append({
            "type": "Feature",
            "id": f"riggs:{station}",
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "properties": {
                "station": station,
                "measurement_method": method,
                "ice_thickness_m": thickness,
                "seismic_ice_thickness_m": seismic,
                "radar_ice_thickness_m": radar,
                "context_only": True,
                "scientific_status": (
                    "provisional-reference-citation-pending" if citation_pending
                    else "independent-reference-observation"
                ),
                "publication_eligible": not citation_pending,
            },
        })
    return {
        "available": True,
        "metadata": {
            "title": str(manifest.get("title") or "RIGGS stations"),
            "citation": citation,
            "source_url": source_url,
            "citation_pending": citation_pending,
            "scientific_status": (
                "provisional-reference-citation-pending" if citation_pending
                else "independent-reference-observation"
            ),
            "publication_eligible": not citation_pending,
            "sha256": digest,
            "note": (
                "Provisional independent reference observations; citation pending; "
                "not eligible for scientific publication or Frozen Legacies validation."
                if citation_pending else
                "Independent reference observations; not Frozen Legacies picks."
            ),
        },
        "stations": {"type": "FeatureCollection", "features": features},
        "summary": {"stations": len(features), **counts},
    }
