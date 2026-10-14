"""GeoParquet checks run with the isolated LIVIST environment's Python.

    <env>/venv/bin/python -I deep_validate.py <file.parquet> [...]

Prints one JSON object per file: row count, column types, GeoParquet CRS
and temperature statistics. Standalone on purpose (stdlib + pyarrow, both
in LIVIST's lockfile) so the CryoStack environment needs no pyarrow.
"""
import json
import sys


def inspect(path):
    import pyarrow.parquet as pq

    out = {"path": path}
    try:
        parquet = pq.ParquetFile(path)
    except Exception as error:  # noqa: BLE001 - reported, not raised
        return {**out, "error": f"unreadable parquet: {type(error).__name__}"}
    meta = parquet.metadata
    out["rows"] = meta.num_rows
    out["columns"] = {f.name: str(f.type) for f in parquet.schema_arrow}
    try:
        geo = json.loads((meta.metadata or {}).get(b"geo", b"null"))
    except ValueError:
        geo = None
    if isinstance(geo, dict):
        column = (geo.get("columns") or {}).get(geo.get("primary_column") or "", {})
        crs = column.get("crs") or {}
        ident = crs.get("id") or {} if isinstance(crs, dict) else {}
        out["geo"] = {
            "version": geo.get("version"),
            "primary_column": geo.get("primary_column"),
            "encoding": column.get("encoding"),
            "geometry_types": column.get("geometry_types"),
            "crs": f"{ident.get('authority')}:{ident.get('code')}" if ident else None,
            "crs_name": crs.get("name") if isinstance(crs, dict) else None,
            "bbox": column.get("bbox"),
        }
    if out["columns"].get("temperature") == "double":
        import pyarrow.compute as pc

        column = parquet.read(columns=["temperature"]).column("temperature")
        finite = pc.filter(column, pc.fill_null(pc.is_finite(column), False))
        bounds = pc.min_max(finite).as_py() if len(finite) else {"min": None, "max": None}
        out["temperature"] = {"finite": len(finite), "min": bounds["min"], "max": bounds["max"]}
    return out


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(json.dumps(inspect(arg)))
