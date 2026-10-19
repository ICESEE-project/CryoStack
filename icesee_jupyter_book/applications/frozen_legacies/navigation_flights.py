"""Read-only navigation-only flight coverage for the Frozen Legacies map.

The radar catalog indexes TIFF assets and intentionally does not invent assets
from navigation CSVs.  This module exposes verified flight coverage before its
imagery arrives, from an explicitly approved external storage root.
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path

from .radar.ingest import MAX_NAV_BYTES, read_nav_bytes, summarize_nav
from .radar.storage import LocalProvider, StorageError


ROOT_ENV = "CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_ROOT"
DATASET_ENV = "CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_DATASET"
TITLE_ENV = "CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_TITLE"
FLIGHTS_ENV = "CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_FLIGHTS"
DEFAULT_DATASET = "frozen-legacies-spri-navigation"
DEFAULT_TITLE = "SPRI archival radar navigation"
MAX_FILES = 5_000
_FLIGHT = re.compile(r"(?:F)?([0-9]{1,4})", re.IGNORECASE)


def _configured_flights() -> set[str] | None:
    raw = (os.environ.get(FLIGHTS_ENV) or "").strip()
    if not raw:
        return None
    values = {v.strip().removeprefix("F").removeprefix("f") for v in raw.split(",")}
    if not values or any(not v.isdigit() for v in values):
        raise ValueError(f"{FLIGHTS_ENV} must be a comma-separated list of flight numbers.")
    return values


def _flight_from_key(key: str) -> str | None:
    match = _FLIGHT.fullmatch(Path(key).stem)
    return str(int(match.group(1))) if match else None


def _distance_km(a: list[float], b: list[float]) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    value = (math.sin(dlat / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return 6371.0088 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


def _split_antimeridian(line: list[list[float]]) -> list[list[list[float]]]:
    if not line:
        return []
    parts = [[line[0]]]
    for current in line[1:]:
        previous = parts[-1][-1]
        delta = current[0] - previous[0]
        if abs(delta) <= 180:
            parts[-1].append(current)
            continue
        unwrapped = current[0] + (-360 if delta > 180 else 360)
        boundary = -180.0 if delta > 180 else 180.0
        fraction = (boundary - previous[0]) / (unwrapped - previous[0])
        latitude = previous[1] + fraction * (current[1] - previous[1])
        parts[-1].append([boundary, latitude])
        parts.append([[-boundary, latitude], current])
    return [part for part in parts if len(part) >= 2]


def _segments(rows: list[dict], *, max_jump_km: float = 120.0) -> list[list[list[float]]]:
    positions = []
    for row in rows:
        lat, lon = row.get("lat"), row.get("lon")
        if lat is None or lon is None:
            continue
        positions.append([float(lon if lon <= 180 else lon - 360), float(lat)])
    survey_lines: list[list[list[float]]] = []
    current: list[list[float]] = []
    for position in positions:
        if current and _distance_km(current[-1], position) > max_jump_km:
            if len(current) >= 2:
                survey_lines.append(current)
            current = []
        current.append(position)
    if len(current) >= 2:
        survey_lines.append(current)
    return [part for line in survey_lines for part in _split_antimeridian(line)]


def navigation_collection() -> dict:
    """Return configured navigation flights and public dataset metadata.

    An empty collection means the operator has not configured a durable root.
    ``LocalProvider`` enforces that the root is inside
    ``CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS``.
    """
    root = (os.environ.get(ROOT_ENV) or "").strip()
    if not root:
        return {"dataset": None, "flights": {"type": "FeatureCollection", "features": []},
                "summary": {"files": 0, "flights": 0, "invalid": 0}}
    provider = LocalProvider(Path(root))
    selected = _configured_flights()
    dataset_id = (os.environ.get(DATASET_ENV) or DEFAULT_DATASET).strip()
    title = (os.environ.get(TITLE_ENV) or DEFAULT_TITLE).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", dataset_id):
        raise ValueError(f"{DATASET_ENV} is invalid.")
    features, invalid, examined = [], 0, 0
    for obj in provider.list("", suffixes=(".csv",)):
        examined += 1
        if examined > MAX_FILES:
            raise StorageError(f"Navigation root contains more than {MAX_FILES:,} CSV files.")
        flight = _flight_from_key(obj.key)
        if flight is None or (selected is not None and flight not in selected):
            continue
        try:
            rows = read_nav_bytes(provider.read_bytes(obj.key, limit=MAX_NAV_BYTES))
            segments = _segments(rows)
            if not segments:
                raise ValueError("Navigation file has fewer than two connected positions.")
        except (OSError, StorageError, ValueError):
            invalid += 1
            continue
        summary = summarize_nav(rows)
        features.append({
            "type": "Feature", "id": f"{dataset_id}:{flight}",
            "geometry": {"type": "MultiLineString", "coordinates": segments},
            "properties": {
                "dataset_id": dataset_id, "flight": flight,
                "observations": summary["positions"], "segments": len(segments),
                "cbd_min": summary["cbd_min"], "cbd_max": summary["cbd_max"],
                "navigation_available": True, "imagery_available": False,
                "availability": "navigation-only",
            },
        })
    features.sort(key=lambda f: int(f["properties"]["flight"]))
    dataset = {
        "id": dataset_id, "title": title, "adapter": "navigation",
        "description": "Verified archival navigation; radar imagery is not yet installed.",
        "observations": sum(f["properties"]["observations"] for f in features),
        "flights": [f["properties"]["flight"] for f in features],
        "capabilities": {"observations": False, "flight_lines": True, "imagery": False,
                         "raw_radar": False, "downloads": False, "citations": False,
                         "search": False},
        "availability": "navigation-only",
    }
    return {"dataset": dataset,
            "flights": {"type": "FeatureCollection", "features": features},
            "summary": {"files": examined, "flights": len(features), "invalid": invalid}}
