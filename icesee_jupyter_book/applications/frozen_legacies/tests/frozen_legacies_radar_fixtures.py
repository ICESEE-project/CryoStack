"""Small synthetic radar fixtures for the Frozen Legacies tests.

Nothing here reads the large local development TIFFs; every image is built
in the test's temporary directory.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image


def radar_array(width: int = 300, height: int = 40) -> np.ndarray:
    """A deterministic 16-bit pattern (distinct value per pixel)."""
    y, x = np.mgrid[0:height, 0:width]
    return ((x * 97 + y * 13) % 60000 + 200).astype(np.uint16)


def write_tiff(path: Path, array: np.ndarray | None = None, *, compression="tiff_lzw") -> Path:
    array = radar_array() if array is None else array
    Image.fromarray(array).save(path, format="TIFF", compression=compression)
    return path


def tiff_bytes(array: np.ndarray | None = None, *, compression="tiff_lzw") -> bytes:
    array = radar_array() if array is None else array
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="TIFF", compression=compression)
    return buffer.getvalue()


NAV_TEXT = (
    "CBD,LAT,LON,THK,SRF\n"
    "470,-81.46,-169.80,9999,9999\n"
    "471,-81.479401,-169.753098,9999,9999\n"
    "472,-81.494598,-169.686996,9999,9999\n"
    "473,-81.50,-169.62,1200.5,9999\n"
    "483,-81.60,-169.10,9999,9999\n"
)


def write_nav(path: Path, text: str = NAV_TEXT) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def write_registry(path: Path, entries_yaml: str) -> Path:
    path.write_text("version: 1\nsources:\n" + entries_yaml, encoding="utf-8")
    return path
