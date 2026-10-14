"""Indexing of data sources into the radar catalog.

    storage provider
        -> list candidate radar files (object metadata only)
        -> new or changed files: flight/CBD from the file name (ASTRA's
           parser), TIFF header without decoding pixels (ranged reads for
           remote providers), navigation by the source's naming template,
           and the file's track from the navigation records of its CBD range
        -> catalog rows

Per file:

* **new** -- added (``indexed``, or ``invalid`` when it is not a usable TIFF);
* **unchanged** (same size, mtime, ETag) -- not read again;
* **changed** -- re-read and updated in place (same catalog ID);
* **moved/renamed** -- a file that disappears in the same run as a file with
  the same name, size and version appears elsewhere in the source: the new
  row gets its own ID; the old row becomes ``moved`` and points to it, so
  user work on the old ID keeps working;
* **deleted** -- no longer listed: ``missing`` (kept with all user work;
  ``missing_since`` records when);
* **unreadable this time** (I/O error) -- ``unavailable``, retried next run;
* **duplicate name** -- kept as distinct assets and flagged.

Source-level safety: if the source cannot be listed, or lists nothing at
all while the catalog knows files, or a run would mark more than
``max_missing_fraction`` of the known files missing, the run stops as
``unavailable`` / ``needs_confirmation`` and **no** file is marked missing --
a temporary outage never looks like mass deletion. A maintainer can confirm
real removals with ``allow_mass_missing``.

Indexing is blocking; the gateway runs it in a separate worker process
(:mod:`radar.index_worker`) with progress, heartbeat and cancellation.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .catalog import RadarCatalog, asset_key, flight_number
from .ingest import (
    MAX_NAV_BYTES,
    RadarValidationError,
    extract_flight_info,
    nav_rows_in_range,
    read_nav_bytes,
    read_tiff_header,
    read_tiff_header_stream,
)
from .storage import (
    RadarStorageProvider,
    RangeReader,
    StorageError,
    StorageKeyError,
    StorageObject,
    normalize_key,
)


TIFF_SUFFIXES = (".tif", ".tiff")
BATCH = 500
MAX_MISSING_FRACTION = 0.5
_TEMPLATE = re.compile(r"\{flight\}")


def nav_key_for(template: str | None, flight: str | None) -> str | None:
    """Navigation key from a source template such as ``nav/{flight}.csv``."""
    if not template or not flight:
        return None
    try:
        return normalize_key(_TEMPLATE.sub(flight, template))
    except StorageKeyError:
        return None


def read_header(provider: RadarStorageProvider, obj: StorageObject) -> dict:
    """TIFF header of an object without reading its pixel data."""
    if "local_files" in provider.capabilities:
        path = provider.local_file(obj.key)
        if path is None:
            raise StorageError("The file could not be opened.")
        return read_tiff_header(path)
    if "range_read" in provider.capabilities:
        return read_tiff_header_stream(RangeReader(provider, obj.key, obj.size), size=obj.size)
    raise StorageError("This data source cannot provide file headers.")


def track_for(nav_rows: list[dict] | None, cbd_start, cbd_end):
    """Positions of the navigation records in a file's CBD range (exact
    records only), with their bounding box; ``None`` without any position."""
    if not nav_rows or cbd_start is None or cbd_end is None:
        return None
    coords = []
    for row in nav_rows_in_range(nav_rows, cbd_start, cbd_end):
        lat, lon = row.get("lat"), row.get("lon")
        if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 360):
            continue
        coords.append([round(lon if lon <= 180 else lon - 360, 6), round(lat, 6)])
    if not coords:
        return None
    lats = [c[1] for c in coords]
    lons = [c[0] for c in coords]
    return {"track": json.dumps(coords), "min_lat": min(lats), "max_lat": max(lats),
            "min_lon": min(lons), "max_lon": max(lons)}


def _clean_error(error: Exception) -> str:
    # never store server paths in the catalog
    return re.sub(r"(/[^\s'\"]+)+", "…", str(error))[:300]


def _row(source_id, dataset_id, obj, nav_template, provider, nav_cache, now):
    filename = Path(obj.key).name
    flight, cbd_start, cbd_end = extract_flight_info(filename)
    nav = nav_key_for(nav_template, flight)
    if nav is not None and nav not in nav_cache:
        try:
            nav_cache[nav] = (read_nav_bytes(provider.read_bytes(nav, limit=MAX_NAV_BYTES))
                              if provider.exists(nav) else None)
        except (StorageError, RadarValidationError, OSError):
            nav_cache[nav] = None
    nav_rows = nav_cache.get(nav) if nav else None
    row = {
        "catalog_id": asset_key(source_id, obj.key), "source_id": source_id,
        "dataset_id": dataset_id, "storage_key": obj.key, "filename": filename,
        "flight": flight, "flight_num": flight_number(flight),
        "cbd_start": cbd_start, "cbd_end": cbd_end,
        "width": None, "height": None, "mode": None, "bytes": obj.size,
        "mtime_ns": obj.mtime_ns, "etag": obj.etag,
        "nav_key": nav if nav_rows is not None else None,
        "has_nav": 1 if nav_rows is not None else 0,
        "status": "indexed", "error": None,
        "track": None, "min_lat": None, "max_lat": None, "min_lon": None, "max_lon": None,
        "first_indexed_at": now, "indexed_at": now,
    }
    row.update(track_for(nav_rows, cbd_start, cbd_end) or {})
    return row


def _header_result(provider, obj):
    try:
        return read_header(provider, obj), None
    except RadarValidationError as error:
        return None, ("invalid", _clean_error(error))
    except (OSError, StorageError) as error:
        return None, ("unavailable", _clean_error(error))


def index_source(catalog: RadarCatalog, source: dict, provider: RadarStorageProvider,
                 *, full: bool = False, allow_mass_missing: bool = False,
                 max_missing_fraction: float = MAX_MISSING_FRACTION,
                 retry_invalid: bool = False, run_id: int | None = None,
                 progress=None, should_stop=None) -> dict:
    """Index one data source; returns the run's status and counts.

    ``run_id`` continues a run created by the caller (the background worker);
    ``progress(counts)`` is called after every batch; when ``should_stop()``
    becomes true the run ends as ``cancelled`` after the current batch, with
    everything indexed so far kept and nothing marked missing.
    ``retry_invalid`` also re-reads unchanged files recorded as ``invalid``
    (``unavailable`` files are always retried).
    """
    source_id = source["source_id"]
    dataset_id = source["dataset_id"]
    config = source.get("config") or {}
    prefix = config.get("tiff_prefix") or ""
    nav_template = config.get("nav_template") or None
    if run_id is None:
        run_id = catalog.start_run(source_id)
    counts = {"discovered": 0, "added": 0, "changed": 0, "unchanged": 0,
              "missing": 0, "invalid": 0, "unavailable": 0, "moved": 0}
    skip = ("indexed", "changed") if retry_invalid else ("indexed", "changed", "invalid")
    workers = max(1, int(getattr(provider, "header_concurrency", 1) or 1))
    pool = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None

    def finish(status, error=None):
        catalog.finish_run(run_id, source_id, status=status, counts=counts, error=error)
        return {"status": status, "counts": counts, "error": error, "run_id": run_id}

    known = {}
    new_rows: dict[str, dict] = {}
    pending: list[tuple] = []          # (obj, previous) awaiting header reads
    nav_cache: dict[str, list | None] = {}
    now = time.time()

    def flush():
        if not pending:
            return
        objs = [obj for obj, _ in pending]
        if pool is not None:
            results = list(pool.map(lambda o: _header_result(provider, o), objs))
        else:
            results = [_header_result(provider, o) for o in objs]
        rows = []
        for (obj, previous), (header, failure) in zip(pending, results):
            row = _row(source_id, dataset_id, obj, nav_template, provider, nav_cache, now)
            if header is not None:
                row.update(width=header["width"], height=header["height"], mode=header["mode"])
            else:
                row.update(status=failure[0], error=failure[1])
                counts[failure[0]] += 1
            if previous is None:
                counts["added"] += 1
                new_rows[obj.key] = row
            elif row["status"] == "indexed":
                counts["changed"] += 1
            rows.append(row)
        catalog.upsert_assets(rows)
        pending.clear()
        if progress is not None:
            progress(dict(counts))

    try:
        known = catalog.known_objects(source_id)
        seen: set[str] = set()
        for obj in provider.list(prefix, suffixes=TIFF_SUFFIXES):
            counts["discovered"] += 1
            seen.add(obj.key)
            previous = known.get(obj.key)
            if (not full and previous is not None
                    and previous["status"] in skip
                    and (previous["bytes"], previous["mtime_ns"], previous["etag"])
                    == (obj.size, obj.mtime_ns, obj.etag)):
                counts["unchanged"] += 1
                if counts["unchanged"] % BATCH == 0 and progress is not None:
                    progress(dict(counts))
            else:
                pending.append((obj, previous))
                if len(pending) >= BATCH:
                    flush()
            if should_stop is not None and counts["discovered"] % 100 == 0 and should_stop():
                flush()
                return finish("cancelled", "Indexing was cancelled; files indexed so far are "
                                           "kept and nothing was marked missing.")
        flush()

        gone = [k for k, v in known.items()
                if k not in seen and v["status"] not in ("missing", "moved")]
        present_before = sum(1 for v in known.values() if v["status"] not in ("missing", "moved"))
        if gone and not allow_mass_missing:
            if counts["discovered"] == 0:
                return finish("unavailable", "The source listed no files; nothing was marked missing.")
            if present_before >= 20 and len(gone) / present_before > max_missing_fraction:
                return finish("needs_confirmation",
                              f"{len(gone)} of {present_before} files were not listed. Nothing was "
                              "marked missing; re-run with confirmation if they were removed.")

        # moves: a vanished file whose name, size and version reappear under a new key
        arrivals: dict[tuple, list[str]] = {}
        for key, row in new_rows.items():
            arrivals.setdefault((row["filename"], row["bytes"], row["etag"] or row["mtime_ns"]),
                                []).append(row["catalog_id"])
        moves, missing = [], []
        for key in gone:
            old = known[key]
            match = arrivals.get((old["filename"], old["bytes"], old["etag"] or old["mtime_ns"]))
            if match and len(match) == 1:
                moves.append((old["catalog_id"], match[0]))
            else:
                missing.append(key)
        catalog.mark_moved(moves)
        catalog.mark_missing(source_id, missing)
        counts["moved"], counts["missing"] = len(moves), len(missing)
        catalog.refresh_duplicates(dataset_id)
    except StorageError as error:
        return finish("unavailable", _clean_error(error))
    except Exception as error:   # never leave a run "running"
        finish("failed", f"{type(error).__name__}: {_clean_error(error)}")
        raise
    finally:
        if pool is not None:
            pool.shutdown(wait=True)
    return finish("completed")
