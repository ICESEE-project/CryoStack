from __future__ import annotations

import json
import urllib.request
from pathlib import Path


OUTPUT_ROOT = (
    Path(__file__).resolve().parent
    / "data"
    / "antarctica"
)

OUTPUT_FILE = (
    OUTPUT_ROOT
    / "antarctica_land.geojson"
)

NATURAL_EARTH_URL = (
    "https://raw.githubusercontent.com/"
    "nvkelso/natural-earth-vector/master/"
    "geojson/ne_110m_admin_0_countries.geojson"
)


def main():

    OUTPUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(
        "[FrozenLegacies] "
        "Downloading Antarctic outline..."
    )

    with urllib.request.urlopen(
        NATURAL_EARTH_URL,
        timeout=60,
    ) as response:

        data = json.load(
            response
        )


    antarctica_features = []


    for feature in data.get(
        "features",
        []
    ):

        properties = (
            feature.get(
                "properties",
                {}
            )
        )

        name = (
            properties.get("ADMIN")
            or properties.get("NAME")
            or properties.get("SOVEREIGNT")
            or ""
        )


        if (
            str(name).strip().lower()
            == "antarctica"
        ):

            antarctica_features.append(
                feature
            )


    if not antarctica_features:

        raise RuntimeError(
            "Could not locate Antarctica "
            "in Natural Earth dataset."
        )


    output = {
        "type":
            "FeatureCollection",

        "features":
            antarctica_features,
    }


    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            indent=2,
        ),
        encoding="utf-8",
    )


    print(
        "[FrozenLegacies] Wrote:",
        OUTPUT_FILE,
    )


if __name__ == "__main__":
    main()