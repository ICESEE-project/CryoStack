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


#: capabilities a dataset has unless its manifest says otherwise
DEFAULT_CAPABILITIES = {
    "observations": True,
    "flight_lines": True,
    "imagery": False,
    "raw_radar": False,
    "downloads": False,
    "citations": False,
    "search": False,
}


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

    # Declarative feature flags (what the frontend may offer for this
    # dataset) and build options (e.g. which downloads to provide).
    metadata["capabilities"] = dict(
        DEFAULT_CAPABILITIES,
        **(
            manifest.get(
                "capabilities"
            )
            or {}
        ),
    )
    metadata["build"] = (
        manifest.get(
            "build"
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
    dataset_manifests: dict[str, Path] = {}


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


        previous_manifest = dataset_manifests.get(
            dataset.dataset_id
        )


        if previous_manifest is not None:
            raise ValueError(
                "Duplicate dataset id "
                f"{dataset.dataset_id!r} in {path}; "
                f"already declared in {previous_manifest}"
            )


        dataset_manifests[dataset.dataset_id] = path


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
