"""Structured observations derived from a user's picking results.

When an A-scope is committed in the manual (ASTRA) picker, the asset's
observations are rebuilt from the session and stored in the user's workspace
as ``radar/<asset_id>/observations.json``. The map reads them through an
owner-scoped API, so picks appear on the map while the user works -- without
Done, a GeoJSON rebuild, or a restart. They are never written into the shared
``data/observations.geojson``.

Each observation is one row of ASTRA's CSV, built with the same function
(:func:`pickers.astra.astra_dataframe`), so it always agrees with the CSV:

* CBDs follow ASTRA (spread over the file name's CBD range by committed-row
  order), so the CBD -- and therefore the position -- of earlier A-scopes can
  change when more are committed, exactly as in ASTRA's CSV;
* LAT/LON are ASTRA's exact-CBD navigation values. A value outside the valid
  latitude/longitude range (for example the ``9999`` unavailable marker) is
  kept in the record but not mapped.

Only quantities ASTRA computes are included (travel times, power, distances,
thickness); no LYRA-derived quantities are produced.

Status: ``draft`` while the session is in progress, ``completed`` after Done.
Review and publication (:mod:`radar.review`) work on a frozen snapshot of
these records; the user's records here are never changed by a review.
"""
from __future__ import annotations

import json
import math
import time

from ..optional_pickers import astra_dataframe, load_flight_coordinates
from ..workspace import ASSET_OBSERVATIONS, ASSET_SESSION, FrozenLegaciesWorkspace
from . import manual


SCHEMA = "cryostack.frozen_legacies.observations"
VERSION = 1

#: ``on_change(workspace, asset_id, document_or_None)`` after every write or
#: removal -- keeps the server's indexed copy (My picks) current
on_change = None


def _notify(workspace, asset_id: str, document: dict | None) -> None:
    if on_change is not None:
        try:
            on_change(workspace, asset_id, document)
        except Exception:        # the index is derived; never fail the user's action
            pass

#: ASTRA CSV column -> observation field
FIELDS = {
    "CBD": "cbd", "LAT": "lat", "LON": "lon",
    "surface_us": "surface_us", "surface_dB": "surface_db",
    "bed_us": "bed_us", "bed_dB": "bed_db",
    "noisefloor_us": "noisefloor_us", "noisefloor_dB": "noisefloor_db",
    "mainbang_us": "mainbang_us", "mainbang_dB": "mainbang_db",
    "surface_m": "surface_m", "bed_m": "bed_m", "h_ice_m": "h_ice_m",
}


def _value(value):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _window_x(picks) -> int | None:
    mainbang = (picks or {}).get("mainbang")
    if not isinstance(mainbang, (list, tuple)) or len(mainbang) != 4:
        return None
    try:
        return int(mainbang[2]) - int(mainbang[0])
    except (TypeError, ValueError):
        return None


def _position(lat, lon):
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 360):
        return None
    return [lon if lon <= 180 else lon - 360, lat]


def build(asset_id: str, manifest: dict, doc: dict, nav_path) -> dict:
    """Observations of one asset from its ASTRA session document."""
    state = doc["state"]
    filename = manifest.get("filename") or ""
    df = astra_dataframe(state["data"], filename, load_flight_coordinates(nav_path))
    status = "completed" if doc["status"] == "completed" else "draft"
    observations = []
    sources = state.get("row_sources") or []
    picks = state.get("all_ascope_picks") or []
    shared = manifest.get("shared_source")
    for index, row in enumerate(df.to_dict("records")):
        number = int(row["A-scope Number"])
        record = {
            "observation_id": f"{asset_id}-a{number}",
            "asset_id": asset_id,
            "a_scope": number,
            "flight": str(row["FLT"]) if row["FLT"] not in ("", None) else None,
            "workflow": "astra-manual",
            "status": status,
            "scope": "user",
            "dataset_id": manifest.get("dataset_id"),
            "catalog_id": shared if shared and shared.startswith("cat-") else None,
            "picks": sources[index] if index < len(sources) else {},
            # the picker window this A-scope was committed in (ASTRA slider =
            # x_orig - x_zoom of its Main Bang, which every commit has)
            "window_x": _window_x(picks[index] if index < len(picks) else None),
        }
        for column, field in FIELDS.items():
            record[field] = _value(row.get(column))
        record["cbd"] = int(record["cbd"]) if record["cbd"] is not None else None
        record["position"] = _position(record["lat"], record["lon"])
        observations.append(record)
    return {
        "schema": SCHEMA, "version": VERSION, "asset_id": asset_id,
        "picker": "astra", "status": status,
        "session_revision": doc["revision"], "updated_at": time.time(),
        "source": {"origin": manifest.get("origin"), "filename": filename,
                   "shared_source": manifest.get("shared_source"),
                   "flight": manifest.get("flight"),
                   "dataset_id": manifest.get("dataset_id")},
        "observations": observations,
    }


def write(workspace: FrozenLegaciesWorkspace, asset_id: str, document: dict) -> None:
    path = workspace.asset_file(asset_id, ASSET_OBSERVATIONS)
    if path.is_symlink():
        raise PermissionError("observations.json may not be a link.")
    text = json.dumps(document, sort_keys=True, allow_nan=False)
    manual._atomic_write(path, lambda tmp: tmp.write_text(text, encoding="utf-8"))
    _notify(workspace, asset_id, document)


def remove(workspace: FrozenLegaciesWorkspace, asset_id: str) -> None:
    path = workspace.asset_file(asset_id, ASSET_OBSERVATIONS)
    if path.exists() or path.is_symlink():
        path.unlink()
    _notify(workspace, asset_id, None)


def read(workspace: FrozenLegaciesWorkspace, asset_id: str) -> dict | None:
    """The stored observations of an asset, or ``None`` (absent or unusable)."""
    path = workspace.asset_file(asset_id, ASSET_OBSERVATIONS)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(doc, dict) or doc.get("schema") != SCHEMA
            or doc.get("asset_id") != asset_id or not isinstance(doc.get("observations"), list)):
        return None
    return doc


def is_stale(workspace, asset_id: str, document: dict | None) -> bool:
    """Whether the stored observations lag behind the session."""
    session = workspace.asset_file(asset_id, ASSET_SESSION)
    if not session.is_file():
        return document is not None
    try:
        revision = json.loads(session.read_text(encoding="utf-8")).get("revision")
    except (OSError, ValueError):
        return False
    return document is None or document.get("session_revision") != revision


#: georeferencing outcomes with no usable frame position
NOT_POSITIONED = ("label_unreadable", "verified_no_navigation")


def map_position(record: dict):
    """Where an observation is drawn: the verified position when its CBD was
    verified against the film (:mod:`radar.georef`), nothing when the frame
    could not be positioned, otherwise ASTRA's own position -- which is then
    labelled unverified by ``geolocation_status``."""
    status = record.get("geolocation_status")
    if status == "verified":
        return record.get("verified_position")
    if status in NOT_POSITIONED:
        return None
    return record.get("position")


def feature(record: dict, source: dict) -> dict:
    """One observation as a GeoJSON feature (WGS84); the record's ASTRA
    values are unchanged, the geometry follows :func:`map_position`."""
    properties = {k: v for k, v in record.items() if k != "position"}
    properties["filename"] = source.get("filename")
    properties["source_origin"] = source.get("origin")
    properties.setdefault("astra_position", record.get("position"))
    position = map_position(record)
    return {"type": "Feature", "id": record["observation_id"],
            "geometry": {"type": "Point", "coordinates": position} if position else None,
            "properties": properties}


def in_bbox(position, bbox) -> bool:
    if bbox is None:
        return True
    lon, lat = position
    min_lon, min_lat, max_lon, max_lat = bbox
    if min_lon <= max_lon:
        inside_lon = min_lon <= lon <= max_lon
    else:                       # across the antimeridian
        inside_lon = lon >= min_lon or lon <= max_lon
    return inside_lon and min_lat <= lat <= max_lat
