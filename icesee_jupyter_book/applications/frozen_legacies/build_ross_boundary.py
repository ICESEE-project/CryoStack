"""Build the display-only Ross Ice Shelf boundary from the bundled ADD layer."""
from __future__ import annotations

import json
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent
SOURCE = (
    APP_ROOT.parents[2]
    / "external/living-ice-sheet-temperature/frontend/public"
    / "quantartica-simple-basemap.json"
)
OUTPUT = APP_ROOT / "data/antarctica/ross_ice_shelf.geojson"


def _ring_area(ring: list[list[float]]) -> float:
    return abs(sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(ring, ring[1:] + ring[:1])
    )) / 2.0


def _feature_area(feature: dict) -> float:
    geometry = feature["geometry"]
    polygons = (
        [geometry["coordinates"]]
        if geometry["type"] == "Polygon"
        else geometry["coordinates"]
    )
    return sum(
        _ring_area(polygon[0]) - sum(_ring_area(hole) for hole in polygon[1:])
        for polygon in polygons
        if polygon
    )


def build(source: Path = SOURCE, output: Path = OUTPUT) -> dict:
    collection = json.loads(source.read_text(encoding="utf-8"))
    shelves = [
        feature for feature in collection.get("features", [])
        if feature.get("properties", {}).get("Category") == "Ice shelf"
    ]
    if not shelves:
        raise ValueError("The ADD basemap contains no ice-shelf polygons.")
    feature = max(shelves, key=_feature_area)
    area_km2 = _feature_area(feature) / 1_000_000
    if not 470_000 <= area_km2 <= 490_000:
        raise ValueError(f"Unexpected Ross Ice Shelf area: {area_km2:.1f} km²")
    feature = {
        "type": "Feature",
        "id": "ross-ice-shelf",
        "properties": {
            "name": "Ross Ice Shelf",
            "category": "Ice shelf",
            "display_only": True,
            "source": "Antarctic Digital Database / Quantarctica derived low-resolution basemap",
            "source_feature_rule": "largest polygon classified as Ice shelf",
            "area_km2_approx": round(area_km2, 3),
        },
        "geometry": feature["geometry"],
    }
    result = {
        "type": "FeatureCollection",
        "name": "Ross Ice Shelf display boundary",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:EPSG::3031"},
        },
        "features": [feature],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    boundary = build()
    print(json.dumps(boundary["features"][0]["properties"], indent=2))
