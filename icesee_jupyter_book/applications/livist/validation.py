"""Structural validation of the products LIVIST's ``scripts/generate`` writes.

For every attenuation name ``N`` and mode ``M`` (``conductivity``,
``pure-ice``) LIVIST writes into ``data/``:

* ``temperature-N-M.parquet``        GeoParquet, EPSG:3031, columns
                                     ``temperature`` / ``attenuation`` (double)
                                     and WKB ``geometry`` (points)
* ``temperature-N-M-wgs84.parquet``  the same rows in EPSG:4326
* ``temperature-N-M.fgb``            FlatGeobuf converted from the WGS84 file
* ``temperature-N-M.pmtiles``        PMTiles v3 vector tiles (tippecanoe)

and ``frontend/public/temperature-sources.json`` (pmtiles URLs per mode).

Byte-level checks (magic numbers, PMTiles header, JSON shape) use the
standard library. Row counts, schema and CRS are read with the isolated
environment's pyarrow (``deep_validate.py``) and GDAL (``ogrinfo``); when the
environment is missing the result says the deep checks did not run.
"""
from __future__ import annotations

import json
import struct
import subprocess
import time
from pathlib import Path

from . import toolchain

MODES = ("conductivity", "pure-ice")
PARQUET_COLUMNS = {"temperature": "double", "attenuation": "double", "geometry": "binary"}
#: the solver's bracket in LIVIST's temperature.compute_along_track (K)
TEMPERATURE_RANGE = (150.0, 350.0)
PMTILES_HEADER = 127
DEEP_TIMEOUT_S = 300
FGB_MAGIC = b"fgb\x03fgb"


def expected_products(names: list[str]) -> list[str]:
    out = []
    for name in names:
        for mode in MODES:
            stem = f"temperature-{name}-{mode}"
            out += [f"{stem}.parquet", f"{stem}-wgs84.parquet", f"{stem}.fgb", f"{stem}.pmtiles"]
    return out


def product_paths(workdir: Path) -> dict[str, Path]:
    """Products present in a job directory, by published file name."""
    found = {}
    data = workdir / "data"
    if data.is_dir():
        for path in sorted(data.iterdir()):
            if (path.name.startswith("temperature-") and path.suffix in (".parquet", ".fgb", ".pmtiles")
                    and path.is_file() and not path.is_symlink()):
                found[path.name] = path
    sources = workdir / "frontend" / "public" / "temperature-sources.json"
    if sources.is_file() and not sources.is_symlink():
        found[sources.name] = sources
    return found


class _Result:
    def __init__(self):
        self.checks: list[dict] = []

    def add(self, artifact: str, check: str, level: str, detail: str = "") -> None:
        self.checks.append({"artifact": artifact, "check": check, "level": level,
                            "detail": detail})

    def ok(self, artifact, check, detail=""):
        self.add(artifact, check, "ok", detail)

    def warn(self, artifact, check, detail):
        self.add(artifact, check, "warn", detail)

    def error(self, artifact, check, detail):
        self.add(artifact, check, "error", detail)


def parse_pmtiles_header(raw: bytes) -> dict:
    if len(raw) < PMTILES_HEADER or raw[:7] != b"PMTiles":
        raise ValueError("not a PMTiles archive")
    version = raw[7]
    if version != 3:
        raise ValueError(f"PMTiles version {version}, expected 3")
    offsets = struct.unpack_from("<11Q", raw, 8)
    clustered, internal, tile_compression, tile_type, min_zoom, max_zoom = raw[96:102]
    min_lon, min_lat, max_lon, max_lat = struct.unpack_from("<4i", raw, 102)
    return {
        "version": version,
        "root_offset": offsets[0], "root_length": offsets[1],
        "metadata_offset": offsets[2], "metadata_length": offsets[3],
        "tile_data_offset": offsets[6], "tile_data_length": offsets[7],
        "addressed_tiles": offsets[8], "tile_entries": offsets[9], "tile_contents": offsets[10],
        "clustered": bool(clustered), "internal_compression": internal,
        "tile_compression": tile_compression, "tile_type": tile_type,
        "min_zoom": min_zoom, "max_zoom": max_zoom,
        "bounds": [min_lon / 1e7, min_lat / 1e7, max_lon / 1e7, max_lat / 1e7],
    }


def _check_pmtiles(result: _Result, name: str, path: Path) -> None:
    try:
        with path.open("rb") as handle:
            header = parse_pmtiles_header(handle.read(PMTILES_HEADER))
    except (OSError, ValueError, struct.error) as error:
        result.error(name, "pmtiles-header", str(error))
        return
    size = path.stat().st_size
    end = max(header["root_offset"] + header["root_length"],
              header["tile_data_offset"] + header["tile_data_length"])
    if end > size or header["root_length"] == 0:
        result.error(name, "pmtiles-header", "header offsets point past the end of the file")
        return
    if header["tile_type"] != 1:
        result.error(name, "pmtiles-tile-type", f"tile type {header['tile_type']}, expected MVT (1)")
    elif header["addressed_tiles"] == 0:
        result.error(name, "pmtiles-tiles", "the archive holds no tiles")
    else:
        result.ok(name, "pmtiles-header",
                  f"PMTiles v3, MVT, zoom {header['min_zoom']}-{header['max_zoom']}, "
                  f"{header['addressed_tiles']} tiles")
    lon0, lat0, lon1, lat1 = header["bounds"]
    if not (-180 <= lon0 <= lon1 <= 180 and -90 <= lat0 <= lat1 <= 90):
        result.error(name, "pmtiles-bounds", "bounds are not valid WGS84 coordinates")
    elif lat1 > -50:
        result.warn(name, "pmtiles-bounds", f"bounds reach latitude {lat1:.2f}, north of Antarctica")
    else:
        result.ok(name, "pmtiles-bounds", f"lat {lat0:.2f} to {lat1:.2f}")


def _check_magic(result: _Result, name: str, path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            head = handle.read(8)
            if path.suffix == ".parquet":
                handle.seek(-4, 2)
                tail = handle.read(4)
    except OSError as error:
        result.error(name, "readable", type(error).__name__)
        return False
    if path.suffix == ".parquet":
        ok = head[:4] == b"PAR1" and tail == b"PAR1"
        (result.ok if ok else result.error)(name, "parquet-magic", "" if ok else "not a Parquet file")
        return ok
    ok = head[:7] == FGB_MAGIC
    (result.ok if ok else result.error)(name, "flatgeobuf-magic", "" if ok else "not a FlatGeobuf file")
    return ok


def _deep_parquet(files: list[Path], env: Path | None) -> dict[str, dict] | None:
    python = toolchain.paths(env)["python"]
    if not python.is_file() or not files:
        return None
    script = Path(__file__).with_name("deep_validate.py")
    try:
        done = subprocess.run([str(python), "-I", str(script), *map(str, files)],
                              capture_output=True, text=True, timeout=DEEP_TIMEOUT_S,
                              stdin=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin"})
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = {}
    for line in done.stdout.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        out[Path(item.get("path", "")).name] = item
    return out


def _fgb_count(path: Path, env: Path | None) -> tuple[int | None, str | None]:
    p = toolchain.paths(env)
    if not p["ogrinfo"].is_file():
        return None, None
    try:
        done = subprocess.run([str(p["ogrinfo"]), "-so", "-json", str(path)], capture_output=True,
                              text=True, timeout=DEEP_TIMEOUT_S, stdin=subprocess.DEVNULL,
                              env={"PATH": "/usr/bin:/bin", "GDAL_DATA": str(p["gdal_data"]),
                                   "GDAL_DRIVER_PATH": str(p["gdal_plugins"])})
        layer = json.loads(done.stdout)["layers"][0]
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError):
        return None, None
    ident = (((layer.get("geometryFields") or [{}])[0].get("coordinateSystem") or {})
             .get("projjson") or {}).get("id") or {}
    crs = f"{ident.get('authority')}:{ident.get('code')}" if ident else None
    return layer.get("featureCount"), crs


def _check_parquet_deep(result: _Result, name: str, info: dict, *, wgs84: bool) -> int | None:
    if "error" in info:
        result.error(name, "parquet-read", info["error"])
        return None
    columns = info.get("columns") or {}
    wrong = {k: v for k, v in PARQUET_COLUMNS.items() if columns.get(k) != v}
    if wrong:
        result.error(name, "parquet-schema", "expected columns " + ", ".join(
            f"{k} ({v})" for k, v in wrong.items()))
    else:
        result.ok(name, "parquet-schema", "temperature, attenuation, geometry")
    geo = info.get("geo") or {}
    expected = "EPSG:4326" if wgs84 else "EPSG:3031"
    if geo.get("primary_column") != "geometry" or geo.get("encoding") != "WKB":
        result.error(name, "geoparquet", "missing GeoParquet metadata for the geometry column")
    elif geo.get("crs") != expected:
        result.error(name, "crs", f"CRS {geo.get('crs') or 'unknown'}, expected {expected}")
    else:
        result.ok(name, "crs", f"{expected} ({geo.get('crs_name')})")
    rows = info.get("rows")
    if not rows:
        result.error(name, "rows", "no rows")
    else:
        result.ok(name, "rows", f"{rows:,} rows")
    temps = info.get("temperature") or {}
    if rows and temps:
        finite = temps.get("finite") or 0
        if finite == 0:
            result.error(name, "temperature", "no finite temperatures")
        else:
            low, high = TEMPERATURE_RANGE
            detail = (f"{finite:,}/{rows:,} finite, {temps['min']:.1f}-{temps['max']:.1f} K")
            if temps["min"] < low or temps["max"] > high:
                result.warn(name, "temperature", detail + f" (outside {low:.0f}-{high:.0f} K)")
            else:
                result.ok(name, "temperature", detail)
    return rows


def validate(workdir: Path, names: list[str], *, env: Path | None = None) -> dict:
    """Validate a job directory's products for the attenuation ``names``."""
    result = _Result()
    found = product_paths(workdir)
    for name in expected_products(names):
        if name not in found:
            result.error(name, "present", "missing")
    unexpected = set(found) - set(expected_products(names)) - {"temperature-sources.json"}
    for name in sorted(unexpected):
        result.warn(name, "expected", "not produced for the configured inputs")

    magic_ok = {}
    for name, path in found.items():
        if path.suffix == ".pmtiles":
            _check_pmtiles(result, name, path)
        elif path.suffix in (".parquet", ".fgb"):
            magic_ok[name] = _check_magic(result, name, path)

    parquet = [found[n] for n in found if n.endswith(".parquet") and magic_ok.get(n)]
    deep = _deep_parquet(parquet, env)
    rows: dict[str, int | None] = {}
    if deep is None and parquet:
        result.warn("*.parquet", "deep-checks",
                    "The isolated LIVIST environment is unavailable; schema, rows and CRS "
                    "were not checked.")
    for path in parquet:
        info = (deep or {}).get(path.name)
        if deep is not None and info is None:
            result.error(path.name, "parquet-read", "not readable")
        elif info is not None:
            rows[path.name] = _check_parquet_deep(result, path.name, info,
                                                  wgs84=path.name.endswith("-wgs84.parquet"))

    for name in names:
        for mode in MODES:
            stem = f"temperature-{name}-{mode}"
            projected, wgs84 = rows.get(f"{stem}.parquet"), rows.get(f"{stem}-wgs84.parquet")
            if projected is not None and wgs84 is not None:
                if projected == wgs84:
                    result.ok(f"{stem}-wgs84.parquet", "rows-match", "same rows as EPSG:3031")
                else:
                    result.error(f"{stem}-wgs84.parquet", "rows-match",
                                 f"{wgs84} rows, EPSG:3031 file has {projected}")
            fgb = f"{stem}.fgb"
            if magic_ok.get(fgb):
                count, crs = _fgb_count(found[fgb], env)
                if count is None:
                    result.warn(fgb, "features", "GDAL unavailable; feature count not checked")
                elif wgs84 is not None and count != wgs84:
                    result.error(fgb, "features", f"{count} features, WGS84 parquet has {wgs84}")
                elif crs not in (None, "EPSG:4326"):
                    result.error(fgb, "crs", f"CRS {crs}, expected EPSG:4326")
                else:
                    result.ok(fgb, "features", f"{count:,} features, EPSG:4326")

    sources = found.get("temperature-sources.json")
    if sources is None:
        result.error("temperature-sources.json", "present", "missing")
    else:
        try:
            doc = json.loads(sources.read_text(encoding="utf-8"))
            listed = {m: sorted(e["name"] for e in doc[m]) for m in MODES}
        except (OSError, ValueError, KeyError, TypeError):
            result.error("temperature-sources.json", "json", "not LIVIST's sources manifest")
        else:
            if all(listed[m] == sorted(names) for m in MODES):
                result.ok("temperature-sources.json", "json", "lists every input for both modes")
            else:
                result.error("temperature-sources.json", "json",
                             "does not list exactly the configured inputs")

    levels = {c["level"] for c in result.checks}
    status = "failed" if "error" in levels else "warnings" if "warn" in levels else "passed"
    return {"status": status, "checked_at": time.time(), "deep": deep is not None,
            "checks": result.checks}
