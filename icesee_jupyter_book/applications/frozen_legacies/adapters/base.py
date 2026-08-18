from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass
class FrozenObservation:
    """
    Normalized observation record used internally by Frozen Legacies.

    Source-specific adapters should convert their native records into
    this common representation.
    """

    observation_id: str
    dataset_id: str

    flight: str | None = None
    frame_idx: int | None = None
    cbd: int | str | None = None

    longitude: float | None = None
    latitude: float | None = None

    echo_status: str | None = None

    ice_thickness_m: float | None = None
    bed_snr_db: float | None = None
    surface_temperature_c: float | None = None
    reflectivity_db: float | None = None
    attenuation_db: float | None = None
    specularity: float | None = None

    image_url: str | None = None
    image_path: str | None = None
    data_url: str | None = None

    source_file: str | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_properties(self) -> dict[str, Any]:
        """
        Return the normalized GeoJSON properties payload.
        """

        properties = {
            "observation_id":
                self.observation_id,

            "dataset_id":
                self.dataset_id,

            "flight":
                self.flight,

            "frame_idx":
                self.frame_idx,

            "cbd":
                self.cbd,

            "echo_status":
                self.echo_status,

            "h_ice_m":
                self.ice_thickness_m,

            "bed_snr_dB":
                self.bed_snr_db,

            "T_surface_C":
                self.surface_temperature_c,

            "R0_dB":
                self.reflectivity_db,

            "L_atten_dB":
                self.attenuation_db,

            "specularity":
                self.specularity,

            "image_url":
                self.image_url,

            "image_path":
                self.image_path,

            "data_url":
                self.data_url,

            "_source_file":
                self.source_file,
        }

        properties.update(
            self.metadata
        )

        return {
            key: value
            for key, value in properties.items()
            if value is not None
        }


@dataclass
class FrozenDataset:
    """
    Normalized dataset definition.
    """

    dataset_id: str
    title: str

    adapter: str

    source_type: str
    source_path: str

    campaign: str | None = None
    institution: str | None = None
    description: str | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


class FrozenDatasetAdapter(
    ABC
):
    """
    Base interface for all Frozen Legacies dataset adapters.

    Each adapter is responsible for understanding one external data
    format and converting it into FrozenObservation objects.
    """

    name: str = "base"

    def __init__(
        self,
        dataset: FrozenDataset,
        *,
        repo_root: Path,
    ):
        self.dataset = dataset
        self.repo_root = Path(
            repo_root
        ).resolve()

    @property
    def source_path(self) -> Path:
        """
        Resolve a manifest source path against the CryoLauncher root.
        """

        path = Path(
            self.dataset.source_path
        )

        if path.is_absolute():
            return path

        return (
            self.repo_root
            / path
        ).resolve()

    def validate(self) -> None:
        """
        Perform common dataset validation.
        """

        if not self.dataset.dataset_id:
            raise ValueError(
                "Dataset ID cannot be empty."
            )

        if not self.dataset.adapter:
            raise ValueError(
                "Dataset adapter cannot be empty."
            )

        if (
            self.dataset.source_type
            == "local"
            and not self.source_path.exists()
        ):
            raise FileNotFoundError(
                f"Dataset source does not exist: "
                f"{self.source_path}"
            )

    @abstractmethod
    def load_observations(
        self
    ) -> Iterable[FrozenObservation]:
        """
        Read the native source and yield normalized observations.
        """

        raise NotImplementedError

    def load(
        self
    ) -> list[FrozenObservation]:
        """
        Validate and load the complete normalized dataset.
        """

        self.validate()

        observations = list(
            self.load_observations()
        )

        for observation in observations:

            if (
                observation.dataset_id
                != self.dataset.dataset_id
            ):
                raise ValueError(
                    "Adapter returned an observation "
                    "with the wrong dataset_id: "
                    f"{observation.dataset_id}"
                )

        return observations