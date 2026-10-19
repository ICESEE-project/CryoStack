from pathlib import Path

import pytest

from icesee_jupyter_book.applications.frozen_legacies.dataset_registry import (
    load_registered_datasets,
)


def _manifest(path: Path, *, dataset_id: str, title: str) -> None:
    path.write_text(
        "\n".join(
            (
                f"id: {dataset_id}",
                f"title: {title}",
                "adapter: lyra",
                "source:",
                "  type: local",
                "  path: source",
                "",
            )
        ),
        encoding="utf-8",
    )


def test_registered_dataset_ids_must_be_unique(tmp_path):
    manifests = tmp_path / "datasets"
    manifests.mkdir()
    first = manifests / "first.yaml"
    second = manifests / "second.yml"
    _manifest(first, dataset_id="shared-id", title="First dataset")
    _manifest(second, dataset_id="shared-id", title="Second dataset")

    with pytest.raises(ValueError) as exc_info:
        load_registered_datasets(
            manifests_dir=manifests,
            repo_root=tmp_path,
        )

    message = str(exc_info.value)
    assert "Duplicate dataset id 'shared-id'" in message
    assert str(first) in message
    assert str(second) in message


def test_distinct_registered_dataset_ids_are_preserved(tmp_path):
    manifests = tmp_path / "datasets"
    manifests.mkdir()
    _manifest(manifests / "first.yaml", dataset_id="first", title="First dataset")
    _manifest(manifests / "second.yml", dataset_id="second", title="Second dataset")

    registered = load_registered_datasets(
        manifests_dir=manifests,
        repo_root=tmp_path,
    )

    assert [dataset.dataset_id for dataset, _adapter in registered] == [
        "first",
        "second",
    ]
