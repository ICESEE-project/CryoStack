"""Shared (installation-provided) radar sources.

Shared radar imagery belongs to the Frozen Legacies installation, not to a
user. It is declared by the operator in a YAML registry; users open it by
key, and their workspace asset only *references* it -- the TIFF is never
copied into a user's workspace and its server path is never sent to the
browser.

Registry location: ``$CRYOSTACK_FROZEN_LEGACIES_RADAR_SOURCES``, otherwise
``radar_sources.local.yaml`` in the application directory (local/development
configuration; not version controlled). Without either, there are no shared
radar sources.

Format::

    version: 1
    sources:
      - key: f127-c0471-c0483          # [a-z0-9][a-z0-9._-]*
        title: F127 A-scope C0471-C0483
        status: development            # development | reference
        tiff: path/to/F127-C0471_C0483.tiff
        nav: path/to/127.csv           # optional
        flight: "127"                  # optional; default parsed from filename
        dataset_id: null               # optional explorer dataset to link to
        observation_tiff: null         # optional: observations' `tiff` value

Relative paths resolve against the registry file's directory. An explorer
observation is linked to a source only when the source explicitly names its
``dataset_id`` (and ``flight``/``observation_tiff``); nothing is inferred.
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from .ingest import extract_flight_info


SOURCES_ENV = "CRYOSTACK_FROZEN_LEGACIES_RADAR_SOURCES"
DEFAULT_SOURCES_FILE = Path(__file__).resolve().parent.parent / "radar_sources.local.yaml"

STATUSES = frozenset({"development", "reference"})

_KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


def is_valid_source_key(value: object) -> bool:
    return isinstance(value, str) and _KEY.fullmatch(value) is not None


@dataclass(frozen=True)
class RadarSource:
    key: str
    title: str
    status: str
    tiff_path: Path
    nav_path: Path | None
    flight: str | None
    cbd_start: int | None
    cbd_end: int | None
    dataset_id: str | None
    observation_tiff: str | None

    def public(self) -> dict:
        """Browser-safe description (no server paths)."""
        return {
            "key": self.key,
            "title": self.title,
            "status": self.status,
            "flight": self.flight,
            "cbd_start": self.cbd_start,
            "cbd_end": self.cbd_end,
            "dataset_id": self.dataset_id,
            "observation_tiff": self.observation_tiff,
            "has_nav": self.nav_path is not None,
            "filename": self.tiff_path.name,
        }


def sources_file() -> Path | None:
    configured = (os.environ.get(SOURCES_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_SOURCES_FILE if DEFAULT_SOURCES_FILE.is_file() else None


def _optional_str(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_file(base: Path, raw) -> Path:
    text = _optional_str(raw)
    if text is None:
        raise ValueError("missing path")
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = base / path
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"not a file: {path}")
    return path


def parse_sources(document, *, base: Path) -> dict[str, RadarSource]:
    """Validate a registry document; invalid entries are skipped."""
    entries = (document or {}).get("sources") or []
    sources: dict[str, RadarSource] = {}
    for index, entry in enumerate(entries):
        try:
            if not isinstance(entry, dict):
                raise ValueError("entry is not a mapping")
            key = entry.get("key")
            if not is_valid_source_key(key):
                raise ValueError(f"invalid key {key!r}")
            if key in sources:
                raise ValueError(f"duplicate key {key!r}")
            if key.startswith("cat-"):
                raise ValueError("keys starting with 'cat-' are reserved for the radar catalog")
            status = _optional_str(entry.get("status")) or "development"
            if status not in STATUSES:
                raise ValueError(f"invalid status {status!r}")
            tiff_path = _resolve_file(base, entry.get("tiff"))
            if tiff_path.suffix.lower() not in {".tif", ".tiff"}:
                raise ValueError("tiff must be a .tif/.tiff file")
            nav_path = (
                _resolve_file(base, entry.get("nav"))
                if _optional_str(entry.get("nav")) else None
            )
            parsed_flight, cbd_start, cbd_end = extract_flight_info(tiff_path.name)
            sources[key] = RadarSource(
                key=key,
                title=_optional_str(entry.get("title")) or tiff_path.stem,
                status=status,
                tiff_path=tiff_path,
                nav_path=nav_path,
                flight=_optional_str(entry.get("flight")) or parsed_flight,
                cbd_start=cbd_start,
                cbd_end=cbd_end,
                dataset_id=_optional_str(entry.get("dataset_id")),
                observation_tiff=_optional_str(entry.get("observation_tiff")),
            )
        except (ValueError, TypeError, OSError) as error:
            print(f"[FrozenLegacies] skipping radar source #{index}: {error}")
    return sources


_cache_lock = threading.Lock()
_cache: tuple | None = None


class SharedSources(dict):
    """Registry sources, plus on-demand resolution of radar-catalog keys.

    Iterating lists only the (small) registry. Looking up a catalog key
    (``cat-…``) resolves that one file through the radar catalog, so every
    caller that opens shared radar by key works for catalog assets too.
    """

    def _catalog(self, key):
        from .catalog import is_catalog_key, open_catalog
        if not is_catalog_key(key):
            return None
        catalog = open_catalog()
        return resolve_catalog_source(catalog, key) if catalog is not None else None

    def get(self, key, default=None):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        found = self._catalog(key)
        return default if found is None else found

    def __contains__(self, key):
        return dict.__contains__(self, key) or self._catalog(key) is not None

    def __getitem__(self, key):
        found = self.get(key)
        if found is None:
            raise KeyError(key)
        return found


#: resolved catalog files are reused briefly, so viewing a remote file does
#: not cost a metadata request per image tile
_RESOLVED_TTL_S = 30.0
_resolved: dict[tuple, tuple[float, "RadarSource"]] = {}
_resolved_lock = threading.Lock()


def resolve_catalog_source(catalog, key: str) -> RadarSource | None:
    """A catalog asset as a shared source, when its file is available now.

    The file reaches the pickers through the working cache: in place for
    providers whose objects are already local files, otherwise as a bounded,
    validated working copy. A moved file is followed to its new location."""
    from .storage import StorageError, StorageKeyError, provider_for
    from .working_cache import working_cache

    record = catalog.resolve(key)
    if (record is None or record["source_status"] != "enabled"
            or record["status"] not in ("indexed", "changed")):
        return None
    # the catalog state is checked on every call; only the storage round
    # trips (metadata request, cache lookup) are reused for a short time
    memo = (str(catalog.path), key, record["catalog_id"], record["bytes"],
            record.get("mtime_ns"), record.get("etag"))
    now = time.monotonic()
    with _resolved_lock:
        hit = _resolved.get(memo)
    if (hit is not None and now - hit[0] < _RESOLVED_TTL_S and hit[1].tiff_path.is_file()
            and (hit[1].nav_path is None or hit[1].nav_path.is_file())):
        return hit[1]
    try:
        provider = provider_for(record["provider"], record["config"])
        obj = provider.stat(record["storage_key"])
        if obj is None:
            return None
        cache = working_cache()
        tiff_path = cache.materialize(provider, record["source_id"], obj)
        nav_path = None
        if record["nav_key"]:
            nav_obj = provider.stat(record["nav_key"])
            if nav_obj is not None:
                nav_path = cache.materialize(provider, record["source_id"], nav_obj)
    except (StorageError, StorageKeyError, OSError):
        return None
    found = RadarSource(
        key=key, title=Path(record["filename"]).stem, status="catalog",
        tiff_path=tiff_path, nav_path=nav_path, flight=record["flight"],
        cbd_start=record["cbd_start"], cbd_end=record["cbd_end"],
        dataset_id=record["dataset_id"], observation_tiff=None,
    )
    with _resolved_lock:
        if len(_resolved) > 512:
            _resolved.clear()
        _resolved[memo] = (now, found)
    return found


def load_sources() -> "SharedSources":
    """The current shared radar sources (re-read when the registry changes)."""
    global _cache
    path = sources_file()
    if path is None or not path.is_file():
        return SharedSources()
    stat = path.stat()
    signature = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    with _cache_lock:
        if _cache is not None and _cache[0] == signature:
            return _cache[1]
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        print(f"[FrozenLegacies] radar source registry unreadable: {error}")
        return SharedSources()
    sources = SharedSources(parse_sources(document, base=path.resolve().parent))
    with _cache_lock:
        _cache = (signature, sources)
    return sources
