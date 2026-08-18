from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .adapters import (
    FrozenDataset,
    FrozenDatasetAdapter,
    LyraAdapter,
)


ADAPTERS: dict[
    str,
    type[FrozenDatasetAdapter],
] = {
    "lyra": LyraAdapter,
}


def load_manifest(
    path: Path,
) -> dict[str, Any]:
    """
    Read one Frozen Legacies dataset manifest.
    """

    path = Path(
        path
    ).resolve()

    with path.open(
        "r",
        encoding="utf-8",
    ) as handle:

        payload = (
            yaml.safe_load(
                handle
            )
            or {}
        )


    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            f"Dataset manifest must contain "
            f"a mapping: {path}"
        )


    return payload


def manifest_to_dataset(
    manifest: dict[str, Any],
) -> FrozenDataset:
    """
    Convert a YAML manifest into FrozenDataset.
    """

    source = (
        manifest.get(
            "source"
        )
        or {}
    )


    metadata = dict(
        manifest.get(
            "metadata"
        )
        or {}
    )


    # Preserve product/download declarations for later
    # catalog generation and UI capabilities.
    metadata["products"] = (
        manifest.get(
            "products"
        )
        or {}
    )

    metadata["downloads"] = (
        manifest.get(
            "downloads"
        )
        or {}
    )


    return FrozenDataset(

        dataset_id=
            str(
                manifest.get(
                    "id",
                    ""
                )
            ).strip(),

        title=
            str(
                manifest.get(
                    "title",
                    ""
                )
            ).strip(),

        adapter=
            str(
                manifest.get(
                    "adapter",
                    ""
                )
            ).strip(),

        source_type=
            str(
                source.get(
                    "type",
                    "local"
                )
            ).strip(),

        source_path=
            str(
                source.get(
                    "path",
                    ""
                )
            ).strip(),

        campaign=
            manifest.get(
                "campaign"
            ),

        institution=
            manifest.get(
                "institution"
            ),

        description=
            manifest.get(
                "description"
            ),

        metadata=
            metadata,
    )


def adapter_for_dataset(
    dataset: FrozenDataset,
    *,
    repo_root: Path,
) -> FrozenDatasetAdapter:
    """
    Instantiate the registered adapter for a dataset.
    """

    adapter_name = (
        dataset.adapter
        .strip()
        .lower()
    )


    adapter_class = (
        ADAPTERS.get(
            adapter_name
        )
    )


    if adapter_class is None:
        raise ValueError(
            f"Unknown Frozen Legacies "
            f"adapter: {adapter_name}"
        )


    return adapter_class(
        dataset,
        repo_root=repo_root,
    )


def discover_manifests(
    directory: Path,
) -> list[Path]:
    """
    Discover all dataset manifests.
    """

    directory = Path(
        directory
    )


    if not directory.exists():
        return []


    manifests = sorted(
        list(
            directory.glob(
                "*.yaml"
            )
        )
        +
        list(
            directory.glob(
                "*.yml"
            )
        )
    )


    return manifests


def load_registered_datasets(
    *,
    manifests_dir: Path,
    repo_root: Path,
) -> list[
    tuple[
        FrozenDataset,
        FrozenDatasetAdapter,
    ]
]:
    """
    Load every registered Frozen Legacies dataset.
    """

    registered = []


    for path in discover_manifests(
        manifests_dir
    ):

        print(
            "[FrozenLegacies] "
            f"Loading manifest: "
            f"{path.name}"
        )


        manifest = load_manifest(
            path
        )


        dataset = manifest_to_dataset(
            manifest
        )


        if not dataset.dataset_id:
            raise ValueError(
                f"Missing dataset id in "
                f"{path}"
            )


        if not dataset.title:
            raise ValueError(
                f"Missing dataset title in "
                f"{path}"
            )


        adapter = adapter_for_dataset(
            dataset,
            repo_root=repo_root,
        )


        registered.append(
            (
                dataset,
                adapter,
            )
        )


    return registered