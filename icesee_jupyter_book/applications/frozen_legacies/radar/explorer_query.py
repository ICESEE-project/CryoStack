"""Strict parsing and canonicalization for the V1 radar explorer query.

The parser deliberately implements only catalog fields backed by authoritative
columns today.  A documented-but-not-yet-indexed field is rejected instead of
being silently ignored, which prevents a shared URL from broadening a query.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import secrets
from dataclasses import dataclass

from .catalog import CatalogError, is_valid_dataset_id, is_valid_source_id

MAX_REPEATS = 20
MAX_TEXT = 100
ITEM_LIMIT = 50
FEATURE_LIMIT = 5000
_FLIGHT = __import__("re").compile(r"[A-Za-z0-9._-]{1,32}")
_SCALARS = {"qv", "audience", "cbd_min", "cbd_max", "bbox", "crs", "spatial",
            "q", "sort", "cursor"}
_REPEATED = {"dataset", "flight", "source", "review"}
_PRESENTATION = {"mode", "sel", "view", "asset", "cov", "seg"}
_KNOWN_NOT_INDEXED = {"frame_min", "frame_max", "scope", "frequency", "metadata",
                      "product", "picker", "picker_version", "calibration", "validation",
                      "acquired_from", "acquired_to", "history_from", "history_to"}
_REVIEWS = {"unprocessed", "in_progress", "needs_review", "returned", "published"}
_SORTS = {"flight_cbd", "relevance"}
_CURSOR_SECRET = (os.environ.get("CRYOSTACK_EXPLORER_CURSOR_SECRET") or "").encode() or secrets.token_bytes(32)


@dataclass(frozen=True)
class ExplorerQueryV1:
    datasets: tuple[str, ...] = ()
    flights: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    reviews: tuple[str, ...] = ()
    cbd_min: int | None = None
    cbd_max: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    spatial: str = "intersects"
    text: str | None = None
    sort: str = "flight_cbd"
    cursor: str | None = None

    def canonical(self, *, include_cursor: bool = True) -> dict:
        out: dict = {"qv": 1, "audience": "workspace"}
        for name, values in (("dataset", self.datasets), ("flight", self.flights),
                             ("source", self.sources), ("review", self.reviews)):
            if values:
                out[name] = list(values)
        for name, value in (("cbd_min", self.cbd_min), ("cbd_max", self.cbd_max)):
            if value is not None:
                out[name] = value
        if self.bbox is not None:
            out.update({"bbox": ",".join(format(v, ".15g") for v in self.bbox),
                        "crs": "EPSG:4326", "spatial": self.spatial})
        if self.text is not None:
            out["q"] = self.text
        if self.sort != "flight_cbd":
            out["sort"] = self.sort
        if include_cursor and self.cursor:
            out["cursor"] = self.cursor
        return out

    def fingerprint(self) -> str:
        raw = json.dumps(self.canonical(include_cursor=False), sort_keys=True,
                         separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()


def _unique(query, name: str, default=None):
    values = query.getall(name, [])
    if not values:
        return default
    if len(set(values)) != 1:
        raise CatalogError(f"Conflicting {name} values.")
    return values[0]


def parse_explorer_query(query) -> ExplorerQueryV1:
    unknown = set(query) - _SCALARS - _REPEATED - _PRESENTATION - _KNOWN_NOT_INDEXED
    if unknown:
        raise CatalogError(f"Unknown explorer field: {sorted(unknown)[0]}.")
    unavailable = sorted(set(query) & _KNOWN_NOT_INDEXED)
    if unavailable:
        raise CatalogError(f"Explorer field is not indexed yet: {unavailable[0]}.")
    if _unique(query, "qv", "1") != "1":
        raise CatalogError("Unsupported explorer query version.")
    if _unique(query, "audience", "workspace") != "workspace":
        raise CatalogError("This endpoint supports the workspace audience only.")

    def repeated(name, validator):
        values = query.getall(name, [])
        if len(values) > MAX_REPEATS:
            raise CatalogError(f"Too many {name} values.")
        if any(not validator(v) for v in values):
            raise CatalogError(f"Invalid {name}.")
        return tuple(sorted(set(values)))

    datasets = repeated("dataset", is_valid_dataset_id)
    flights = repeated("flight", lambda v: _FLIGHT.fullmatch(v) is not None)
    sources = repeated("source", is_valid_source_id)
    reviews = repeated("review", lambda v: v in _REVIEWS)

    def integer(name):
        raw = _unique(query, name)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            raise CatalogError(f"{name} must be an integer.")

    cbd_min, cbd_max = integer("cbd_min"), integer("cbd_max")
    if cbd_min is not None and cbd_max is not None and cbd_min > cbd_max:
        raise CatalogError("cbd_min must not exceed cbd_max.")
    bbox = None
    raw_bbox = _unique(query, "bbox")
    spatial = _unique(query, "spatial", "intersects")
    if spatial not in {"intersects", "within"}:
        raise CatalogError("Invalid spatial relation.")
    crs = _unique(query, "crs", "EPSG:4326")
    if crs != "EPSG:4326":
        raise CatalogError("Unsupported explorer CRS.")
    if raw_bbox is not None:
        try:
            parts = tuple(float(v) for v in raw_bbox.split(","))
        except ValueError:
            parts = ()
        if (len(parts) != 4 or not all(math.isfinite(v) for v in parts)
                or not all(-180 <= parts[i] <= 180 for i in (0, 2))
                or not (-90 <= parts[1] <= parts[3] <= 90)):
            raise CatalogError("bbox must be finite WGS84 min_lon,min_lat,max_lon,max_lat.")
        bbox = parts
    text = (_unique(query, "q") or "").strip() or None
    if text is not None and len(text) > MAX_TEXT:
        raise CatalogError(f"q must be at most {MAX_TEXT} characters.")
    sort = _unique(query, "sort", "flight_cbd")
    if sort not in _SORTS or (sort == "relevance" and text is None):
        raise CatalogError("Invalid explorer sort.")
    cursor = _unique(query, "cursor")
    result = ExplorerQueryV1(datasets, flights, sources, reviews, cbd_min, cbd_max,
                             bbox, spatial, text, sort, cursor)
    if cursor is not None:
        decode_cursor(cursor, result.fingerprint())
    return result


def encode_cursor(offset: int, fingerprint: str) -> str:
    payload = json.dumps({"v": 1, "o": offset, "q": fingerprint}, sort_keys=True,
                         separators=(",", ":")).encode()
    signature = hmac.new(_CURSOR_SECRET, payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + signature).rstrip(b"=").decode()


def decode_cursor(token: str | None, fingerprint: str) -> int:
    if not token:
        return 0
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        payload, signature = raw[:-32], raw[-32:]
        if not hmac.compare_digest(signature, hmac.new(_CURSOR_SECRET, payload, hashlib.sha256).digest()):
            raise ValueError
        data = json.loads(payload)
        offset = data["o"]
        if data != {"v": 1, "o": offset, "q": fingerprint} or not isinstance(offset, int) or offset < 0:
            raise ValueError
        return offset
    except Exception:
        raise CatalogError("Invalid or expired explorer cursor.")
