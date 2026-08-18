from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

from .base import (
    FrozenDatasetAdapter,
    FrozenObservation,
)


def parse_value(
    value: str,
) -> Any:
    """
    Parse scalar CSV values into basic Python types.
    """

    value = (
        value or ""
    ).strip()

    if not value:
        return None

    lower = value.lower()

    if lower == "true":
        return True

    if lower == "false":
        return False

    try:
        if (
            "." not in value
            and "e" not in lower
        ):
            return int(value)

        return float(value)

    except ValueError:
        return value


class LyraAdapter(
    FrozenDatasetAdapter
):
    """
    Adapter for Frozen Legacies LYRA *_echoes.csv files.

    A dataset source may point to either:

      - one *_echoes.csv file
      - a directory containing multiple *_echoes.csv files
    """

    name = "lyra"

    def discover_files(
        self,
    ) -> list[Path]:
        """
        Find LYRA CSV files represented by this dataset.
        """

        source = self.source_path

        if source.is_file():

            if (
                source.suffix.lower()
                != ".csv"
            ):
                raise ValueError(
                    "LYRA source file must be CSV: "
                    f"{source}"
                )

            return [
                source
            ]

        if source.is_dir():

            files = sorted(
                source.glob(
                    "*_echoes.csv"
                )
            )

            if not files:
                raise FileNotFoundError(
                    "No *_echoes.csv files found in "
                    f"{source}"
                )

            return files

        raise FileNotFoundError(
            f"LYRA source does not exist: "
            f"{source}"
        )

    def load_native_rows(
        self,
    ) -> Iterable[
        tuple[Path, dict[str, Any]]
    ]:
        """
        Yield parsed LYRA rows together with their source file.
        """

        for csv_path in self.discover_files():

            print(
                "[FrozenLegacies] "
                f"Reading {csv_path.name}"
            )

            with csv_path.open(
                "r",
                encoding="utf-8",
                newline="",
            ) as handle:

                reader = csv.DictReader(
                    handle
                )

                for raw in reader:

                    row = {
                        key:
                            parse_value(
                                value
                            )
                        for key, value
                        in raw.items()
                    }

                    yield (
                        csv_path,
                        row,
                    )

    def normalize_row(
        self,
        csv_path: Path,
        row: dict[str, Any],
    ) -> FrozenObservation | None:
        """
        Convert one LYRA row into the common FrozenObservation schema.
        """

        latitude = row.get(
            "lat"
        )

        longitude = row.get(
            "lon"
        )

        if (
            latitude is None
            or longitude is None
        ):
            return None


        flight = row.get(
            "flight"
        )

        frame_idx = row.get(
            "frame_idx"
        )

        cbd = row.get(
            "cbd"
        )


        observation_id = (
            row.get(
                "file_id"
            )
            or (
                f"{flight}-"
                f"{frame_idx}"
            )
        )


        known_fields = {
            "lat",
            "lon",
            "flight",
            "frame_idx",
            "cbd",
            "file_id",
            "echo_status",
            "h_ice_m",
            "bed_snr_dB",
            "T_surface_C",
            "R0_dB",
            "L_atten_dB",
            "specularity",
        }


        extra_metadata = {
            key: value
            for key, value
            in row.items()
            if (
                key not in known_fields
                and value is not None
            )
        }


        return FrozenObservation(

            observation_id=
                str(
                    observation_id
                ),

            dataset_id=
                self.dataset.dataset_id,

            flight=(
                str(flight)
                if flight is not None
                else None
            ),

            frame_idx=(
                int(frame_idx)
                if frame_idx is not None
                else None
            ),

            cbd=
                cbd,

            longitude=
                float(longitude),

            latitude=
                float(latitude),

            echo_status=(
                str(
                    row.get(
                        "echo_status"
                    )
                )
                if row.get(
                    "echo_status"
                ) is not None
                else None
            ),

            ice_thickness_m=
                row.get(
                    "h_ice_m"
                ),

            bed_snr_db=
                row.get(
                    "bed_snr_dB"
                ),

            surface_temperature_c=
                row.get(
                    "T_surface_C"
                ),

            reflectivity_db=
                row.get(
                    "R0_dB"
                ),

            attenuation_db=
                row.get(
                    "L_atten_dB"
                ),

            specularity=
                row.get(
                    "specularity"
                ),

            source_file=
                csv_path.name,

            metadata=
                extra_metadata,
        )

    def load_observations(
        self,
    ) -> Iterable[
        FrozenObservation
    ]:
        """
        Load and normalize all observations in this LYRA dataset.
        """

        for (
            csv_path,
            row
        ) in self.load_native_rows():

            observation = (
                self.normalize_row(
                    csv_path,
                    row,
                )
            )

            if observation is None:
                continue

            yield observation