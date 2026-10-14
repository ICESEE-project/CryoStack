"""Server-side radar window rendering: exact pixel geometry, display
mapping, request validation, and bounded caching."""
from __future__ import annotations

import io
import sys
import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[3]
for _p in (str(_REPO), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from frozen_legacies_radar_fixtures import radar_array, write_tiff
from icesee_jupyter_book.applications.frozen_legacies.radar import render
from icesee_jupyter_book.applications.frozen_legacies.radar.render import (
    DecodedRadar,
    RadarImageCache,
    RenderedWindowCache,
    RenderRequestError,
    check_window,
    decode_radar,
    render_cached,
    render_window_png,
)


def _png(data: bytes) -> np.ndarray:
    image = Image.open(io.BytesIO(data))
    assert image.format == "PNG" and image.mode == "L"
    return np.asarray(image)


def _naive_block_mean(window: np.ndarray, scale: int) -> np.ndarray:
    h, w = window.shape
    out = np.zeros((-(-h // scale), -(-w // scale)))
    for i in range(out.shape[0]):
        for j in range(out.shape[1]):
            out[i, j] = window[i * scale:(i + 1) * scale, j * scale:(j + 1) * scale].mean()
    return out


@pytest.mark.parametrize("x, width, scale", [
    (0, 300, 1), (0, 300, 4), (17, 101, 8), (250, 50, 16), (0, 300, 64), (299, 1, 2),
])
def test_window_geometry_is_an_exact_block_mean(x, width, scale):
    pixels = radar_array(300, 40)
    decoded = DecodedRadar(pixels=pixels, display_low=0.0, display_high=65535.0)
    out = _png(render_window_png(decoded, x=x, width=width, scale=scale))
    expected = _naive_block_mean(pixels[:, x:x + width].astype(float), scale)
    assert out.shape == expected.shape == (-(-40 // scale), -(-width // scale))
    np.testing.assert_allclose(out, np.clip(np.rint(expected * 255 / 65535), 0, 255), atol=1)


def test_chunked_column_reduction_matches_unchunked(monkeypatch):
    pixels = radar_array(1000, 12)
    decoded = DecodedRadar(pixels=pixels, display_low=0.0, display_high=65535.0)
    whole = render_window_png(decoded, x=0, width=1000, scale=8)
    monkeypatch.setattr(render, "_COLUMN_CHUNK", 16)
    assert render_window_png(decoded, x=0, width=1000, scale=8) == whole


def test_display_stretch_uses_one_mapping_per_image(tmp_path):
    pixels = np.tile(np.linspace(1000, 50000, 200, dtype=np.uint16), (10, 1))
    decoded = decode_radar(write_tiff(tmp_path / "a.tiff", pixels))
    assert 1000 <= decoded.display_low < decoded.display_high <= 50000
    left = _png(render_window_png(decoded, x=0, width=20, scale=1))
    right = _png(render_window_png(decoded, x=180, width=20, scale=1))
    assert left.max() < right.min()          # not re-stretched per window
    np.testing.assert_array_equal(decoded.pixels, pixels)   # originals untouched


def test_constant_image_does_not_divide_by_zero(tmp_path):
    decoded = decode_radar(write_tiff(tmp_path / "c.tiff", np.full((5, 5), 7, np.uint16)))
    assert _png(render_window_png(decoded, x=0, width=5, scale=1)).shape == (5, 5)


@pytest.mark.parametrize("x, width, scale", [
    (-1, 10, 1), (300, 1, 1), (0, 0, 1), (0, 301, 1), (290, 20, 1), (0, 10, 3), (0, 10, 128),
])
def test_invalid_windows_are_rejected(x, width, scale):
    with pytest.raises(RenderRequestError):
        check_window(300, 40, x=x, width=width, scale=scale)


def test_output_size_is_bounded(monkeypatch):
    monkeypatch.setattr(render, "MAX_OUTPUT_PIXELS", 300 * 40 - 1)
    with pytest.raises(RenderRequestError, match="too large"):
        check_window(300, 40, x=0, width=300, scale=1)
    assert check_window(300, 40, x=0, width=300, scale=2) == (150, 20)


def test_image_cache_decodes_each_file_once(tmp_path):
    calls = []

    def decoder(path):
        calls.append(path)
        return decode_radar(path)

    path = write_tiff(tmp_path / "a.tiff")
    cache = RadarImageCache(decoder=decoder)
    threads = [threading.Thread(target=cache.get, args=(path,)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    cache.get(path)
    assert len(calls) == 1


def test_image_cache_is_bounded_and_evicts_least_recent(tmp_path):
    paths = [write_tiff(tmp_path / f"{i}.tiff", radar_array(100, 10)) for i in range(3)]
    one = decode_radar(paths[0]).nbytes
    cache = RadarImageCache(max_bytes=2 * one)
    for p in paths:
        cache.get(p)
    assert len(cache) == 2
    calls = []
    cache._decoder = lambda p: calls.append(p) or decode_radar(p)
    cache.get(paths[0])                   # evicted -> decoded again
    assert calls == [paths[0].resolve()]


def test_image_cache_sees_a_replaced_file(tmp_path):
    path = write_tiff(tmp_path / "a.tiff", np.full((4, 4), 10, np.uint16))
    cache = RadarImageCache()
    first = cache.get(path)
    write_tiff(path, np.full((4, 6), 20, np.uint16))
    assert cache.get(path).width == 6 != first.width


def test_rendered_window_cache(tmp_path):
    path = write_tiff(tmp_path / "a.tiff")
    images, windows = RadarImageCache(), RenderedWindowCache(max_bytes=10**6)
    a = render_cached(images, windows, path, x=0, width=300, scale=4)
    b = render_cached(images, windows, path, x=0, width=300, scale=4)
    assert a is b
    small = RenderedWindowCache(max_bytes=1)
    small.put(("a",), b"xx")
    small.put(("b",), b"yy")
    assert small.get(("a",)) is None and small.get(("b",)) == b"yy"


def test_cache_budget_and_decode_bound_are_configurable(monkeypatch):
    monkeypatch.setenv(render.CACHE_MB_ENV, "5")
    monkeypatch.setenv(render.DECODES_ENV, "2")
    cache = RadarImageCache()
    assert cache.max_bytes == 5 * 1024 * 1024
    assert cache._decodes._value == 2
    monkeypatch.setenv(render.CACHE_MB_ENV, "not-a-number")
    assert RadarImageCache().max_bytes == 768 * 1024 * 1024


def test_decodes_of_different_files_are_bounded(tmp_path):
    active, peak = [0], [0]
    lock = threading.Lock()

    def decoder(path):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        import time
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return decode_radar(path)

    paths = [write_tiff(tmp_path / f"{i}.tiff") for i in range(4)]
    cache = RadarImageCache(decoder=decoder, max_decodes=1)
    threads = [threading.Thread(target=cache.get, args=(p,)) for p in paths]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == 1 and len(cache) == 4
