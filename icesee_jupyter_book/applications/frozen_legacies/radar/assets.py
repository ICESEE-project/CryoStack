"""Per-user radar assets.

A radar asset is one radar image a user works on, stored as
``<owner_root>/frozen_legacies/radar/<asset_id>/`` (see ``..workspace``).
Its ``asset.json`` records where the image comes from:

``origin: upload``
    The user's own TIFF, stored as ``source.tiff`` (and an optional
    ``nav.csv``) inside the asset directory.

``origin: shared``
    A reference to a shared radar source by registry key. The TIFF and
    navigation stay in the installation's storage; nothing is copied.

``origin: products``
    No raw radar: a workspace for processed products the user already has
    (see ``radar.products``). No radar metadata is invented for it.

``asset.json`` never contains server paths, and nothing returned to the
browser does either.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from ..workspace import (
    ASSET_MANIFEST,
    ASSET_NAV_CSV,
    ASSET_SOURCE_TIFF,
    AssetNotFoundError,
    FrozenLegaciesWorkspace,
)
from .ingest import (
    RadarValidationError,
    extract_flight_info,
    nav_rows_in_range,
    read_nav_csv,
    read_tiff_header,
    summarize_nav,
    validate_tiff,
)
from .sources import RadarSource


ASSET_SCHEMA = "cryostack.frozen_legacies.radar_asset"
ASSET_VERSION = 1
ORIGINS = frozenset({"upload", "shared", "products"})


class SharedSourceUnavailable(LookupError):
    """The shared radar source referenced by an asset is not configured."""


class NoRadarImage(LookupError):
    """The asset holds products only; there is no raw radar TIFF."""


def _write_manifest(path: Path, manifest: dict) -> None:
    from cryostack_src.storage_layout import atomic_write

    atomic_write(path, json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"))


def write_manifest(workspace: FrozenLegaciesWorkspace, asset_id: str, manifest: dict) -> None:
    """Atomically replace an asset's ``asset.json``."""
    _write_manifest(workspace.asset_file(asset_id, ASSET_MANIFEST), manifest)


def read_manifest(workspace: FrozenLegaciesWorkspace, asset_id: str) -> dict:
    path = workspace.asset_file(asset_id, ASSET_MANIFEST)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise AssetNotFoundError(asset_id)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != ASSET_SCHEMA
        or manifest.get("asset_id") != asset_id
        or manifest.get("origin") not in ORIGINS
    ):
        raise AssetNotFoundError(asset_id)
    return manifest


def list_manifests(workspace: FrozenLegaciesWorkspace) -> list[dict]:
    manifests = []
    for asset_id in workspace.list_asset_ids():
        try:
            manifests.append(read_manifest(workspace, asset_id))
        except (AssetNotFoundError, PermissionError, RuntimeError):
            continue
    manifests.sort(key=lambda m: m.get("created_at") or 0, reverse=True)
    return manifests


def _nav_summary(nav_path: Path | None, cbd_start, cbd_end, origin: str) -> dict:
    if nav_path is None:
        return {"present": False}
    rows = read_nav_csv(nav_path)
    return {
        "present": True,
        "origin": origin,
        **summarize_nav(rows, cbd_start=cbd_start, cbd_end=cbd_end),
    }


def _base_manifest(asset_id: str, origin: str) -> dict:
    return {
        "schema": ASSET_SCHEMA,
        "version": ASSET_VERSION,
        "asset_id": asset_id,
        "origin": origin,
        "created_at": time.time(),
    }


# ── shared ───────────────────────────────────────────────────────────
def find_shared_asset(workspace: FrozenLegaciesWorkspace, key: str) -> dict | None:
    for manifest in list_manifests(workspace):
        if manifest["origin"] == "shared" and manifest.get("shared_source") == key:
            return manifest
    return None


def create_shared_asset(workspace: FrozenLegaciesWorkspace, source: RadarSource) -> dict:
    """Create (or return the existing) asset referencing ``source``.

    Validates the source TIFF header and navigation; does not copy them.
    """
    existing = find_shared_asset(workspace, source.key)
    if existing is not None:
        return existing
    image = read_tiff_header(source.tiff_path)
    nav = _nav_summary(source.nav_path, source.cbd_start, source.cbd_end, "shared")
    asset_id, directory = workspace.create_asset()
    try:
        manifest = {
            **_base_manifest(asset_id, "shared"),
            "shared_source": source.key,
            "dataset_id": source.dataset_id,
            "title": source.title,
            "filename": source.tiff_path.name,
            "flight": source.flight,
            "cbd_start": source.cbd_start,
            "cbd_end": source.cbd_end,
            "image": image,
            "nav": nav,
        }
        _write_manifest(workspace.asset_file(asset_id, ASSET_MANIFEST), manifest)
    except BaseException:
        remove_asset_dir(workspace, directory)
        raise
    return manifest


# ── uploaded ─────────────────────────────────────────────────────────
def finalize_upload(
    workspace: FrozenLegaciesWorkspace,
    asset_id: str,
    *,
    original_filename: str,
    sha256: str,
    has_nav: bool,
) -> dict:
    """Validate a streamed upload already in place and write ``asset.json``.

    Raises :class:`RadarValidationError`; the caller removes the asset.
    """
    tiff_path = workspace.asset_file(asset_id, ASSET_SOURCE_TIFF)
    image = validate_tiff(tiff_path)
    flight, cbd_start, cbd_end = extract_flight_info(original_filename)
    nav_path = workspace.asset_file(asset_id, ASSET_NAV_CSV) if has_nav else None
    nav = _nav_summary(nav_path, cbd_start, cbd_end, "upload")
    manifest = {
        **_base_manifest(asset_id, "upload"),
        "title": Path(original_filename).stem,
        "filename": original_filename,
        "sha256": sha256,
        "flight": flight,
        "cbd_start": cbd_start,
        "cbd_end": cbd_end,
        "image": image,
        "nav": nav,
    }
    _write_manifest(workspace.asset_file(asset_id, ASSET_MANIFEST), manifest)
    return manifest


def remove_asset_dir(workspace: FrozenLegaciesWorkspace, directory: Path) -> None:
    """Remove a (partial) asset directory -- only ever inside this workspace."""
    directory = workspace.contain(directory)
    if directory.parent != workspace.radar_root:
        raise PermissionError("Refusing to remove a non-asset directory.")
    shutil.rmtree(directory, ignore_errors=True)


# ── product-only ─────────────────────────────────────────────────────
def create_products_asset(workspace: FrozenLegaciesWorkspace, *, title: str) -> tuple[str, Path, dict]:
    """A new asset without raw radar, for uploaded processed products."""
    asset_id, directory = workspace.create_asset()
    manifest = {
        **_base_manifest(asset_id, "products"),
        "title": title,
        "filename": None,
        "flight": None,
        "cbd_start": None,
        "cbd_end": None,
        "image": None,
        "nav": {"present": False},
    }
    try:
        _write_manifest(workspace.asset_file(asset_id, ASSET_MANIFEST), manifest)
    except BaseException:
        remove_asset_dir(workspace, directory)
        raise
    return asset_id, directory, manifest


def attach_navigation(workspace: FrozenLegaciesWorkspace, asset_id: str, manifest: dict) -> dict:
    """Record a newly stored ``nav.csv`` of an uploaded-radar asset."""
    nav_path = workspace.asset_file(asset_id, ASSET_NAV_CSV)
    manifest = dict(manifest)
    manifest["nav"] = _nav_summary(nav_path, manifest.get("cbd_start"), manifest.get("cbd_end"),
                                   "upload")
    _write_manifest(workspace.asset_file(asset_id, ASSET_MANIFEST), manifest)
    return manifest


# ── resolution ───────────────────────────────────────────────────────
def asset_image_paths(
    workspace: FrozenLegaciesWorkspace,
    manifest: dict,
    sources: dict[str, RadarSource],
) -> tuple[Path, Path | None]:
    """Server-side TIFF and navigation paths for an owned asset."""
    asset_id = manifest["asset_id"]
    if manifest["origin"] == "products":
        raise NoRadarImage(asset_id)
    if manifest["origin"] == "upload":
        tiff = workspace.asset_file(asset_id, ASSET_SOURCE_TIFF)
        if not tiff.is_file():
            raise AssetNotFoundError(asset_id)
        nav = workspace.asset_file(asset_id, ASSET_NAV_CSV)
        return tiff, (nav if nav.is_file() else None)
    source = sources.get(manifest.get("shared_source") or "")
    if source is None:
        raise SharedSourceUnavailable(manifest.get("shared_source"))
    return source.tiff_path, source.nav_path


def public_asset(manifest: dict, sources: dict[str, RadarSource] | None = None) -> dict:
    """Browser-safe asset description."""
    out = {
        key: manifest.get(key)
        for key in (
            "asset_id", "origin", "title", "filename", "flight", "dataset_id",
            "cbd_start", "cbd_end", "image", "nav", "created_at",
        )
    }
    if manifest["origin"] == "shared":
        out["shared_source"] = manifest.get("shared_source")
        out["available"] = sources is None or manifest.get("shared_source") in sources
        if sources and out["available"]:
            out["status"] = sources[manifest["shared_source"]].status
    else:
        out["available"] = True
    return out


def asset_nav_rows(nav_path: Path | None, manifest: dict) -> list[dict]:
    """Navigation rows for the asset's CBD range (exact CBD records only)."""
    if nav_path is None:
        return []
    try:
        rows = read_nav_csv(nav_path)
    except RadarValidationError:
        return []
    return nav_rows_in_range(rows, manifest.get("cbd_start"), manifest.get("cbd_end"))
