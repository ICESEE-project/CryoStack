from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]

FROZEN_LEGACIES_ROOT = (
    ROOT
    / "external"
    / "FrozenLegacies"
)

LYRA_ROOT = (
    FROZEN_LEGACIES_ROOT
    / "Frozen Legacy Tools"
    / "LYRA Output"
)

OUTPUT_ROOT = (
    Path(__file__).resolve().parent
    / "data"
)

OBSERVATIONS_FILE = OUTPUT_ROOT / "observations.geojson"
FLIGHTS_FILE = OUTPUT_ROOT / "flights.geojson"


def parse_value(value: str) -> Any:
    value = (value or "").strip()

    if not value:
        return None

    lower = value.lower()

    if lower == "true":
        return True

    if lower == "false":
        return False

    try:
        if "." not in value and "e" not in lower:
            return int(value)
        return float(value)
    except ValueError:
        return value


def load_lyra_rows():
    rows = []

    for csv_path in sorted(LYRA_ROOT.glob("*_echoes.csv")):
        print(f"[FrozenLegacies] Reading {csv_path.name}")

        with csv_path.open(
            "r",
            encoding="utf-8",
            newline="",
        ) as handle:

            reader = csv.DictReader(handle)

            for raw in reader:
                row = {
                    key: parse_value(value)
                    for key, value in raw.items()
                }

                lat = row.get("lat")
                lon = row.get("lon")

                if lat is None or lon is None:
                    continue

                row["_source_file"] = csv_path.name

                rows.append(row)

    return rows


def build_observations(rows):
    features = []

    for row in rows:

        properties = dict(row)

        lat = properties.pop("lat")
        lon = properties.pop("lon")

        feature_id = (
            properties.get("file_id")
            or f"{properties.get('flight')}-{properties.get('frame_idx')}"
        )

        features.append(
            {
                "type": "Feature",
                "id": str(feature_id),
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        float(lon),
                        float(lat),
                    ],
                },
                "properties": properties,
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def build_flight_lines(rows):
    flights = {}

    for row in rows:
        flight = str(row.get("flight"))

        flights.setdefault(
            flight,
            [],
        ).append(row)

    features = []

    for flight, records in sorted(flights.items()):

        records = sorted(
            records,
            key=lambda r: (
                r.get("frame_idx")
                if r.get("frame_idx") is not None
                else 0
            ),
        )

        coordinates = [
            [
                float(record["lon"]),
                float(record["lat"]),
            ]
            for record in records
            if (
                record.get("lat") is not None
                and record.get("lon") is not None
            )
        ]

        if len(coordinates) < 2:
            continue

        features.append(
            {
                "type": "Feature",
                "id": flight,
                "geometry": {
                    "type": "LineString",
                    "coordinates": coordinates,
                },
                "properties": {
                    "flight": flight,
                    "observations": len(records),
                    "source": records[0].get(
                        "_source_file"
                    ),
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def main():
    OUTPUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    rows = load_lyra_rows()

    print(
        f"[FrozenLegacies] Loaded "
        f"{len(rows)} observations."
    )

    observations = build_observations(rows)
    flights = build_flight_lines(rows)

    OBSERVATIONS_FILE.write_text(
        json.dumps(
            observations,
            indent=2,
        ),
        encoding="utf-8",
    )

    FLIGHTS_FILE.write_text(
        json.dumps(
            flights,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        "[FrozenLegacies] Wrote:",
        OBSERVATIONS_FILE,
    )

    print(
        "[FrozenLegacies] Wrote:",
        FLIGHTS_FILE,
    )

    print(
        "[FrozenLegacies] Flights:",
        len(flights["features"]),
    )


if __name__ == "__main__":
    main()