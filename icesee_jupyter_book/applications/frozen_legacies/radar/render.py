"""Server-side radar window rendering.

The browser never receives the full TIFF. It asks for a horizontal window
``[x, x + width)`` of source columns at an integer downsampling ``scale`` and
receives an 8-bit grayscale PNG covering the full image height:

* output column ``j`` is the mean of source columns
  ``[x + j*scale, min(x + (j+1)*scale, x + width))`` and output row ``i`` the
  mean of source rows ``[i*scale, min((i+1)*scale, height))`` -- an exact,
  axis-aligned mapping, so the pixel geometry is preserved;
* intensities are linearly stretched for display between the 0.5th and
  99.5th percentiles of the whole image (one mapping per image, so windows
  are consistent). This is display only; scientific processing reads the
  original pixel values.

Decoded images are held in a bounded LRU cache keyed by file identity
(path, mtime, size). Callers must authorize access to the file before using
the cache. All functions here are blocking; run them in an executor.
"""
from __future__ import annotations

import io
import os
import threading
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .ingest import RadarValidationError, check_tiff_signature


ALLOWED_SCALES = (1, 2, 4, 8, 16, 32, 64)
#: largest PNG (in output pixels) a single request may produce
MAX_OUTPUT_PIXELS = 6_000_000
DISPLAY_PERCENTILES = (0.5, 99.5)


class RenderRequestError(ValueError):
    """The requested window is invalid for this image."""


@dataclass(frozen=True)
class DecodedRadar:
    pixels: np.ndarray        # 2-D, original dtype (uint16 / uint8)
    display_low: float
    display_high: float

    @property
    def width(self) -> int:
        return int(self.pixels.shape[1])

    @property
    def height(self) -> int:
        return int(self.pixels.shape[0])

    @property
    def nbytes(self) -> int:
        return int(self.pixels.nbytes)


def decode_radar(path: Path) -> DecodedRadar:
    with path.open("rb") as handle:
        check_tiff_signature(handle.read(4))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        with Image.open(path) as image:
            pixels = np.asarray(image)
    if pixels.ndim != 2:
        raise RadarValidationError("Radar TIFF is not a single-channel image.")
    sample = pixels[:: max(1, pixels.shape[0] // 512), :: max(1, pixels.shape[1] // 2048)]
    low, high = (float(v) for v in np.percentile(sample, DISPLAY_PERCENTILES))
    if high <= low:
        low, high = float(pixels.min()), float(pixels.max())
    if high <= low:
        high = low + 1.0
    return DecodedRadar(pixels=pixels, display_low=low, display_high=high)


#: environment overrides for the decode cache (MB) and concurrent decodes
CACHE_MB_ENV = "CRYOSTACK_FROZEN_LEGACIES_RADAR_CACHE_MB"
DECODES_ENV = "CRYOSTACK_FROZEN_LEGACIES_RADAR_DECODES"


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


class RadarImageCache:
    """Bounded LRU of decoded radar images (by total decoded bytes).

    ``max_decodes`` bounds simultaneous decodes of *different* files: a
    decode briefly holds about twice the image in memory (Pillow's buffer
    and the array), so unbounded concurrent decodes would exceed the cache
    budget by far (measured: 3 x F127 at once peaked at 1.6 GB RSS).
    """

    def __init__(self, max_bytes: int | None = None, *, decoder=decode_radar,
                 max_decodes: int | None = None):
        if max_bytes is None:
            max_bytes = _env_int(CACHE_MB_ENV, 768) * 1024 * 1024
        self.max_bytes = int(max_bytes)
        self._decoder = decoder
        self._entries: "OrderedDict[tuple, DecodedRadar]" = OrderedDict()
        self._lock = threading.Lock()
        self._key_locks: dict[tuple, threading.Lock] = {}
        self._decodes = threading.BoundedSemaphore(
            max_decodes if max_decodes is not None else _env_int(DECODES_ENV, 1))

    @staticmethod
    def _key(path: Path) -> tuple:
        stat = path.stat()
        return (str(path), stat.st_mtime_ns, stat.st_size)

    def get(self, path: Path) -> DecodedRadar:
        path = Path(path).resolve()
        key = self._key(path)
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key]
            key_lock = self._key_locks.setdefault(key, threading.Lock())
        with key_lock:                      # one decode per file at a time
            with self._lock:
                if key in self._entries:
                    self._entries.move_to_end(key)
                    return self._entries[key]
            with self._decodes:
                decoded = self._decoder(path)
            with self._lock:
                self._entries[key] = decoded
                self._entries.move_to_end(key)
                self._key_locks.pop(key, None)
                total = sum(e.nbytes for e in self._entries.values())
                while total > self.max_bytes and len(self._entries) > 1:
                    _, evicted = self._entries.popitem(last=False)
                    total -= evicted.nbytes
            return decoded

    def __len__(self) -> int:
        return len(self._entries)


#: source columns reduced per step (bounds the float64 working memory)
_COLUMN_CHUNK = 4096


def _block_mean_columns(array: np.ndarray, scale: int) -> np.ndarray:
    """Mean over consecutive blocks of ``scale`` columns (last block may be
    narrower), processed in column chunks so a full-strip window never needs
    a full-size float64 copy."""
    if scale == 1:
        return array.astype(np.float32)
    n = array.shape[1]
    step = max(scale, (_COLUMN_CHUNK // scale) * scale)
    pieces = []
    for start in range(0, n, step):
        block = array[:, start:start + step]
        starts = np.arange(0, block.shape[1], scale)
        sums = np.add.reduceat(block, starts, axis=1, dtype=np.float64)
        counts = np.diff(np.append(starts, block.shape[1]))
        pieces.append((sums / counts).astype(np.float32))
    return np.concatenate(pieces, axis=1)


def _block_mean_rows(array: np.ndarray, scale: int) -> np.ndarray:
    """Mean over consecutive blocks of ``scale`` rows (last block may be shorter)."""
    if scale == 1:
        return array
    n = array.shape[0]
    starts = np.arange(0, n, scale)
    sums = np.add.reduceat(array, starts, axis=0, dtype=np.float64)
    counts = np.diff(np.append(starts, n))
    return (sums / counts[:, None]).astype(np.float32)


def check_window(
    image_width: int, image_height: int, *, x: int, width: int, scale: int,
) -> tuple[int, int]:
    """Validate a window request; return the output (width, height)."""
    if scale not in ALLOWED_SCALES:
        raise RenderRequestError(f"scale must be one of {ALLOWED_SCALES}")
    if not (0 <= x < image_width) or width < 1 or x + width > image_width:
        raise RenderRequestError(
            f"window [{x}, {x + width}) is outside the image width {image_width}"
        )
    out_w = -(-width // scale)
    out_h = -(-image_height // scale)
    if out_w * out_h > MAX_OUTPUT_PIXELS:
        raise RenderRequestError("requested window is too large; use a larger scale")
    return out_w, out_h


def render_window_png(decoded: DecodedRadar, *, x: int, width: int, scale: int) -> bytes:
    check_window(decoded.width, decoded.height, x=x, width=width, scale=scale)
    window = decoded.pixels[:, x:x + width]
    reduced = _block_mean_rows(_block_mean_columns(window, scale), scale)
    span = decoded.display_high - decoded.display_low
    scaled = (reduced - decoded.display_low) * (255.0 / span)
    out = np.clip(np.rint(scaled), 0, 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(out, mode="L").save(buffer, format="PNG", compress_level=3)
    return buffer.getvalue()


class RenderedWindowCache:
    """Small bounded LRU of rendered PNGs (overview strips are re-requested)."""

    def __init__(self, max_bytes: int = 64 * 1024 * 1024):
        self.max_bytes = int(max_bytes)
        self._entries: "OrderedDict[tuple, bytes]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple) -> bytes | None:
        with self._lock:
            data = self._entries.get(key)
            if data is not None:
                self._entries.move_to_end(key)
            return data

    def put(self, key: tuple, data: bytes) -> None:
        with self._lock:
            self._entries[key] = data
            self._entries.move_to_end(key)
            total = sum(len(v) for v in self._entries.values())
            while total > self.max_bytes and len(self._entries) > 1:
                _, evicted = self._entries.popitem(last=False)
                total -= len(evicted)


def render_cached(
    images: RadarImageCache,
    windows: RenderedWindowCache,
    path: Path,
    *,
    x: int,
    width: int,
    scale: int,
) -> bytes:
    path = Path(path).resolve()
    key = (*RadarImageCache._key(path), x, width, scale)
    cached = windows.get(key)
    if cached is not None:
        return cached
    data = render_window_png(images.get(path), x=x, width=width, scale=scale)
    windows.put(key, data)
    return data
