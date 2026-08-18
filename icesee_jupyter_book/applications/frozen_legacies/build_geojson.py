from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from icesee_jupyter_book.applications.frozen_legacies.dataset_registry import (
    load_registered_datasets,
)


APP_ROOT = Path(__file__).resolve().parent

REPO_ROOT = (
    APP_ROOT
    .parents[2]
)

DATASETS_ROOT = (
    APP_ROOT
    / "datasets"
)

OUTPUT_ROOT = (
    APP_ROOT
    / "data"
)

OBSERVATIONS_FILE = (
    OUTPUT_ROOT
    / "observations.geojson"
)

FLIGHTS_FILE = (
    OUTPUT_ROOT
    / "flights.geojson"
)

CATALOG_FILE = (
    OUTPUT_ROOT
    / "catalog.json"
)


# ============================================================
# Helpers
# ============================================================

def haversine_km(
    lon1: float,
    lat1: float,
    lon2: float,
    lat2: float,
) -> float:
    """
    Great-circle distance between two WGS84 lon/lat points.
    """

    radius_km = 6371.0088

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dphi = math.radians(
        lat2 - lat1
    )

    dlambda = math.radians(
        lon2 - lon1
    )

    a = (
        math.sin(dphi / 2.0) ** 2
        +
        math.cos(phi1)
        * math.cos(phi2)
        * math.sin(dlambda / 2.0) ** 2
    )

    c = 2.0 * math.atan2(
        math.sqrt(a),
        math.sqrt(1.0 - a),
    )

    return radius_km * c


def observation_to_feature(
    observation,
    *,
    dataset=None,
) -> dict:
    """
    Convert normalized FrozenObservation into GeoJSON.
    """

    if (
        observation.longitude is None
        or observation.latitude is None
    ):

        raise ValueError(
            f"Observation "
            f"{observation.observation_id} "
            f"is missing coordinates."
        )


    properties = (
        observation.to_properties()
    )


    if dataset is not None:

        properties[
            "products"
        ] = build_products(
            observation,
            dataset,
        )


    return {
        "type":
            "Feature",

        "id":
            observation.observation_id,

        "geometry": {
            "type":
                "Point",

            "coordinates": [
                float(
                    observation.longitude
                ),

                float(
                    observation.latitude
                ),
            ],
        },

        "properties":
            properties,
    }

def build_dataset_index(
    registered,
) -> dict:

    return {
        dataset.dataset_id:
            dataset

        for (
            dataset,
            _adapter,
        ) in registered
    }
# ============================================================
# Observations
# ============================================================

def build_observations(
    observations,
    dataset_index,
) -> dict:
    """
    Build combined observations.geojson.
    """

    features = []


    for observation in observations:

        if (
            observation.longitude is None
            or observation.latitude is None
        ):

            continue


        dataset = (
            dataset_index.get(
                observation.dataset_id
            )
        )


        features.append(
            observation_to_feature(
                observation,
                dataset=
                    dataset,
            )
        )


    return {
        "type":
            "FeatureCollection",

        "features":
            features,
    }

# ============================================================
# Flight geometry
# ============================================================

def split_flight_segments(
    observations,
    *,
    max_segment_jump_km: float = 120.0,
) -> list[list[list[float]]]:
    """
    Split one flight into continuous survey segments.

    A large spatial jump indicates that the next observation
    belongs to another radar pass rather than being connected
    directly to the preceding point.
    """

    ordered = sorted(
        observations,
        key=lambda observation: (
            observation.frame_idx
            if observation.frame_idx is not None
            else 0
        ),
    )

    valid = [
        observation
        for observation in ordered
        if (
            observation.longitude is not None
            and observation.latitude is not None
        )
    ]

    if len(valid) < 2:
        return []

    segments = []
    current_segment = []

    previous = None

    for observation in valid:

        lon = float(
            observation.longitude
        )

        lat = float(
            observation.latitude
        )

        if previous is None:

            current_segment = [
                [lon, lat]
            ]

            previous = (
                lon,
                lat,
            )

            continue

        distance = haversine_km(
            previous[0],
            previous[1],
            lon,
            lat,
        )

        if (
            distance
            >
            max_segment_jump_km
        ):

            if (
                len(current_segment)
                >= 2
            ):
                segments.append(
                    current_segment
                )

            current_segment = [
                [lon, lat]
            ]

        else:

            current_segment.append(
                [lon, lat]
            )

        previous = (
            lon,
            lat,
        )

    if (
        len(current_segment)
        >= 2
    ):
        segments.append(
            current_segment
        )

    return segments


def build_flights(
    observations,
    *,
    max_segment_jump_km: float = 120.0,
) -> dict:
    """
    Build flight-track MultiLineStrings across all datasets.
    """

    grouped = defaultdict(
        list
    )

    for observation in observations:

        flight = (
            observation.flight
            or ""
        ).strip()

        if not flight:
            continue

        key = (
            observation.dataset_id,
            flight,
        )

        grouped[key].append(
            observation
        )

    features = []

    for (
        dataset_id,
        flight,
    ), records in sorted(
        grouped.items()
    ):

        segments = split_flight_segments(
            records,
            max_segment_jump_km=
                max_segment_jump_km,
        )

        if not segments:
            continue

        source_files = sorted({
            observation.source_file
            for observation in records
            if observation.source_file
        })

        feature_id = (
            f"{dataset_id}:{flight}"
        )

        features.append(
            {
                "type":
                    "Feature",

                "id":
                    feature_id,

                "geometry": {
                    "type":
                        "MultiLineString",

                    "coordinates":
                        segments,
                },

                "properties": {
                    "dataset_id":
                        dataset_id,

                    "flight":
                        flight,

                    "observations":
                        len(records),

                    "segments":
                        len(segments),

                    "sources":
                        source_files,
                },
            }
        )

        print(
            "[FrozenLegacies] "
            f"{dataset_id} / Flight {flight}: "
            f"{len(records)} observations, "
            f"{len(segments)} segments"
        )

    return {
        "type":
            "FeatureCollection",

        "features":
            features,
    }


# ============================================================
# Catalog
# ============================================================

def build_catalog(
    registered,
    observations,
) -> dict:
    """
    Build machine-readable dataset metadata for the frontend.
    """

    observation_counts = defaultdict(
        int
    )

    flight_sets = defaultdict(
        set
    )

    for observation in observations:

        observation_counts[
            observation.dataset_id
        ] += 1

        if observation.flight:
            flight_sets[
                observation.dataset_id
            ].add(
                observation.flight
            )

    datasets = []

    for (
        dataset,
        _adapter,
    ) in registered:

        datasets.append(
            {
                "id":
                    dataset.dataset_id,

                "title":
                    dataset.title,

                "adapter":
                    dataset.adapter,

                "campaign":
                    dataset.campaign,

                "institution":
                    dataset.institution,

                "description":
                    dataset.description,

                "observations":
                    observation_counts[
                        dataset.dataset_id
                    ],

                "flights":
                    sorted(
                        flight_sets[
                            dataset.dataset_id
                        ],
                        key=lambda value: (
                            int(value)
                            if str(value).isdigit()
                            else str(value)
                        ),
                    ),

                "products":
                    dataset.metadata.get(
                        "products",
                        {},
                    ),

                "downloads":
                    dataset.metadata.get(
                        "downloads",
                        {},
                    ),

                "metadata": {
                    key: value
                    for key, value
                    in dataset.metadata.items()
                    if key not in {
                        "products",
                        "downloads",
                    }
                },
            }
        )

    return {
        "version":
            1,

        "datasets":
            datasets,

        "summary": {
            "datasets":
                len(datasets),

            "observations":
                len(observations),

            "flights":
                sum(
                    len(values)
                    for values
                    in flight_sets.values()
                ),
        },
    }

def observation_template_values(
    observation,
) -> dict:
    """
    Build a template context from a normalized observation.

    This keeps product-path generation independent of the
    original CSV adapter implementation.
    """

    values = observation.to_properties()

    values.update(
        {
            "observation_id":
                observation.observation_id,

            "dataset_id":
                observation.dataset_id,

            "flight":
                observation.flight,

            "frame_idx":
                observation.frame_idx,

            "_source_file":
                observation.source_file,
        }
    )

    return {
        key: (
            ""
            if value is None
            else value
        )
        for key, value in values.items()
    }


def render_template(
    template: str,
    values: dict,
) -> str | None:

    try:

        value = template.format_map(
            values
        )

    except (
        KeyError,
        ValueError,
    ):

        return None


    value = str(
        value
    ).strip()


    return (
        value
        if value
        else None
    )


def resolve_product_path(
    product_config: dict,
    observation,
) -> str | None:

    path_config = (
        product_config.get("path")
        or {}
    )


    if not isinstance(
        path_config,
        dict,
    ):

        return None


    values = (
        observation_template_values(
            observation
        )
    )


    # --------------------------------------------------------
    # Product path from an observation field
    # --------------------------------------------------------

    field = (
        path_config.get(
            "field"
        )
    )


    if field:

        value = values.get(
            field
        )


        if (
            value is not None
            and str(value).strip()
        ):

            return str(
                value
            ).strip()


    # --------------------------------------------------------
    # Product path from template
    # --------------------------------------------------------

    template = (
        path_config.get(
            "template"
        )
    )


    if template:

        return render_template(
            str(
                template
            ),
            values,
        )


    return None


def build_products(
    observation,
    dataset,
) -> list[dict]:
    """
    Build normalized product metadata for one observation.
    """

    metadata = (
        dataset.metadata
        or {}
    )


    build_config = (
        metadata.get("build")
        or {}
    )


    if not build_config.get(
        "include_products",
        True,
    ):

        return []


    definitions = (
        metadata.get("products")
        or {}
    )


    products: list[dict] = []


    for (
        product_id,
        product_config,
    ) in definitions.items():

        if not isinstance(
            product_config,
            dict,
        ):

            continue


        path = resolve_product_path(
            product_config,
            observation,
        )


        if not path:
            continue


        product = {
            "id":
                str(
                    product_id
                ),

            "title":
                str(
                    product_config.get(
                        "title",
                        product_id,
                    )
                ),

            "type":
                str(
                    product_config.get(
                        "type",
                        "data",
                    )
                ),

            "url":
                path,

            "downloadable":
                bool(
                    product_config.get(
                        "downloadable",
                        True,
                    )
                ),
        }


        mime_type = (
            product_config.get(
                "mime_type"
            )
        )


        if mime_type:

            product[
                "mime_type"
            ] = str(
                mime_type
            )


        products.append(
            product
        )


    return products

# ============================================================
# Main build
# ============================================================

def main() -> None:

    OUTPUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    registered = (
        load_registered_datasets(
            manifests_dir=
                DATASETS_ROOT,

            repo_root=
                REPO_ROOT,
        )
    )

    if not registered:

        raise RuntimeError(
            "No Frozen Legacies dataset "
            "manifests were found."
        )

    dataset_index = (
        build_dataset_index(
            registered
        )
    )

    all_observations = []

    for (
        dataset,
        adapter,
    ) in registered:

        print(
            "[FrozenLegacies] "
            f"Loading dataset: "
            f"{dataset.dataset_id}"
        )

        observations = (
            adapter.load()
        )

        print(
            "[FrozenLegacies] "
            f"{dataset.dataset_id}: "
            f"{len(observations)} "
            f"observations"
        )

        all_observations.extend(
            observations
        )

    observations_geojson = (
        build_observations(
            all_observations,
            dataset_index,
        )
    )

    flights_geojson = (
        build_flights(
            all_observations
        )
    )

    catalog = build_catalog(
        registered,
        all_observations,
    )

    OBSERVATIONS_FILE.write_text(
        json.dumps(
            observations_geojson,
            indent=2,
        ),
        encoding="utf-8",
    )

    FLIGHTS_FILE.write_text(
        json.dumps(
            flights_geojson,
            indent=2,
        ),
        encoding="utf-8",
    )

    CATALOG_FILE.write_text(
        json.dumps(
            catalog,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print(
        "[FrozenLegacies] Build complete."
    )

    print(
        "[FrozenLegacies] Observations:",
        len(
            observations_geojson[
                "features"
            ]
        ),
    )

    print(
        "[FrozenLegacies] Flights:",
        len(
            flights_geojson[
                "features"
            ]
        ),
    )

    print(
        "[FrozenLegacies] Datasets:",
        len(
            catalog[
                "datasets"
            ]
        ),
    )

    print()
    print(
        "[FrozenLegacies] Wrote:",
        OBSERVATIONS_FILE,
    )

    print(
        "[FrozenLegacies] Wrote:",
        FLIGHTS_FILE,
    )

    print(
        "[FrozenLegacies] Wrote:",
        CATALOG_FILE,
    )


if __name__ == "__main__":
    main()