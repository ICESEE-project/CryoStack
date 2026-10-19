#!/usr/bin/env python3
"""Convert the approved RIGGS workbook into a validated, immutable intake pair.

This intentionally uses only the Python standard library so the server does
not need a spreadsheet runtime. It reads values, never formulas or macros.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import BadZipFile, ZipFile

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
INPUT_COLUMNS = {
    "Station", "Radar_H_ice_m", "Seismic_H_ice_m", "LON_dd", "LAT_dd"
}
OUTPUT_COLUMNS = [
    "Station", "Latitude", "Longitude", "h_i (radar), m",
    "h_i (seismics), m", "OBJECTID", "delta_h_m", "Grid_Latitude",
    "Grid_Longitude", "source_file", "source_sheet",
]


def _column(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference or "")
    if not letters:
        raise ValueError("Workbook contains a cell without a column reference.")
    result = 0
    for letter in letters.group(0):
        result = result * 26 + ord(letter) - 64
    return result - 1


def _strings(archive: ZipFile) -> list[str]:
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.findall(".//x:t", NS))
            for item in root.findall("x:si", NS)]


def _rows(workbook: Path) -> list[dict[str, str]]:
    try:
        with ZipFile(workbook) as archive:
            names = set(archive.namelist())
            required = {"xl/sharedStrings.xml", "xl/worksheets/sheet1.xml"}
            if not required.issubset(names):
                raise ValueError("RIGGS workbook must contain one ordinary worksheet.")
            strings = _strings(archive)
            root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    except BadZipFile as exc:
        raise ValueError("RIGGS upload is not a valid XLSX workbook.") from exc
    matrix: list[list[str]] = []
    for row in root.findall(".//x:sheetData/x:row", NS):
        values: dict[int, str] = {}
        for cell in row.findall("x:c", NS):
            index = _column(cell.get("r", ""))
            value = cell.findtext("x:v", default="", namespaces=NS)
            if cell.get("t") == "s" and value:
                value = strings[int(value)]
            values[index] = value.strip()
        if values:
            matrix.append([values.get(index, "") for index in range(max(values) + 1)])
    if not matrix:
        raise ValueError("RIGGS workbook is empty.")
    headers = matrix[0]
    if not INPUT_COLUMNS.issubset(headers):
        missing = ", ".join(sorted(INPUT_COLUMNS.difference(headers)))
        raise ValueError(f"RIGGS workbook is missing required columns: {missing}.")
    records = []
    for values in matrix[1:]:
        values += [""] * (len(headers) - len(values))
        record = dict(zip(headers, values))
        if any(record.values()):
            records.append(record)
    if not records:
        raise ValueError("RIGGS workbook contains no station records.")
    return records


def convert(workbook: Path, output: Path, *, source_sha256: str = "") -> dict:
    workbook = workbook.resolve(strict=True)
    records = _rows(workbook)
    output.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".riggs-", suffix=".csv", dir=output)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            for record in records:
                writer.writerow({
                    "Station": record.get("Station", ""),
                    "Latitude": record.get("LAT_dd", ""),
                    "Longitude": record.get("LON_dd", ""),
                    "h_i (radar), m": record.get("Radar_H_ice_m", ""),
                    "h_i (seismics), m": record.get("Seismic_H_ice_m", ""),
                    **{name: record.get(name, "") for name in OUTPUT_COLUMNS[5:]},
                })
            stream.flush()
            os.fsync(stream.fileno())
        csv_path = output / "riggs_stations.csv"
        os.replace(temporary_name, csv_path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    manifest = {
        "schema": "cryostack.frozen_legacies.riggs_manifest",
        "version": 1,
        "title": "RIGGS ice-thickness stations",
        "citation": "",
        "source_url": "",
        "citation_pending": True,
        "publication_eligible": False,
        "sha256": digest,
        "source_workbook": workbook.name,
        "source_workbook_sha256": source_sha256 or hashlib.sha256(workbook.read_bytes()).hexdigest(),
        "station_rows": len(records),
    }
    manifest_path = output / "manifest.json"
    temporary = output / ".manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)
    return {"csv": str(csv_path), "manifest": str(manifest_path), **manifest}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-sha256", default="")
    args = parser.parse_args()
    print(json.dumps(convert(args.workbook, args.output, source_sha256=args.source_sha256), indent=2))


if __name__ == "__main__":
    main()
