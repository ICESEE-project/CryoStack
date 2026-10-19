#!/usr/bin/env python3
"""Register and index explicitly temporary A-/Z-scope radar sources.

Scratch is never represented as durable or published storage.  This tool is
for maintainer workspace testing while the CEDAR volume is being prepared.
The same source IDs can later be re-pointed only through a reviewed migration.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from icesee_jupyter_book.applications.frozen_legacies.radar.catalog import create_catalog
from icesee_jupyter_book.applications.frozen_legacies.radar.indexer import index_source
from icesee_jupyter_book.applications.frozen_legacies.radar.storage import provider_for

FLIGHTS = ("125", "126", "127", "128", "137", "138", "139", "141", "143", "149")


def ensure_navigation(zscope: Path, navigation: Path) -> None:
    target = zscope / "nav"
    target.mkdir(mode=0o750, exist_ok=True)
    for flight in FLIGHTS:
        source = navigation / f"{flight}.csv"
        if not source.is_file():
            raise FileNotFoundError(f"Verified navigation is unavailable for flight {flight}: {source}")
        shutil.copyfile(source, target / f"{flight}.csv")


def register(catalog, *, source_id: str, name: str, dataset_id: str, config: dict) -> dict:
    source = catalog.get_source(source_id)
    if source is None:
        source = catalog.add_source(source_id=source_id, name=name, provider="local",
                                    dataset_id=dataset_id, config=config)
    elif source["config"] != config or source["dataset_id"] != dataset_id:
        raise RuntimeError(f"{source_id} is already registered differently; refusing to overwrite it.")
    catalog.set_source_visibility(source_id, "maintainers")
    return catalog.get_source(source_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ascope", type=Path, required=True)
    parser.add_argument("--zscope", type=Path, required=True)
    parser.add_argument("--navigation", type=Path, required=True)
    parser.add_argument("--index", action="store_true")
    args = parser.parse_args()
    ascope, zscope = args.ascope.resolve(strict=True), args.zscope.resolve(strict=True)
    ensure_navigation(zscope, args.navigation.resolve(strict=True))
    catalog = create_catalog()
    sources = [
        register(catalog, source_id="ascope-temporary", name="A-scope archival TIFFs · temporary scratch intake",
                 dataset_id="frozen-legacies-ascope-temporary",
                 config={"root": str(ascope), "tiff_prefix": "Raw_TIFFs",
                         "nav_template": "Raw_TIFFs/F{flight}/F{flight}.csv"}),
        register(catalog, source_id="zscope-temporary", name="Z-scope archival TIFFs · temporary scratch intake",
                 dataset_id="frozen-legacies-zscope-temporary",
                 config={"root": str(zscope), "tiff_prefix": "Raw_TIFFS",
                         "nav_template": "nav/{flight}.csv"}),
    ]
    for source in sources:
        print(f"registered {source['source_id']} ({source['visibility']})")
        if args.index:
            provider = provider_for(source["provider"], source["config"])
            result = index_source(catalog, source, provider)
            print(f"indexed {source['source_id']}: {result['status']} {result['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
