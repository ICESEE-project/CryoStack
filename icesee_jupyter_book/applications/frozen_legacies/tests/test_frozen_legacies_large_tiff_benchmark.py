"""Opt-in benchmark for a representative Frozen Legacies radar TIFF.

Set ``FROZEN_LEGACIES_LARGE_TIFF`` to a real, non-synthetic TIFF.  The test
uses the production header-validation, complete-decode, and preview-rendering
paths.  It records timings and peak process RSS, while keeping hardware-
dependent performance thresholds out of the ordinary regression suite.
"""
from __future__ import annotations

import io
import os
import resource
import time
from pathlib import Path

import pytest
from PIL import Image

from icesee_jupyter_book.applications.frozen_legacies.radar import indexer
from icesee_jupyter_book.applications.frozen_legacies.radar.catalog import RadarCatalog
from icesee_jupyter_book.applications.frozen_legacies.radar.ingest import (
    read_tiff_header,
    validate_tiff,
)
from icesee_jupyter_book.applications.frozen_legacies.radar.storage import (
    RadarStorageProvider,
    StorageObject,
)
from icesee_jupyter_book.applications.frozen_legacies.radar.render import (
    RadarImageCache,
    RenderedWindowCache,
    render_cached,
)


TIFF_ENV = "FROZEN_LEGACIES_LARGE_TIFF"
SYNTHETIC_ENV = "FROZEN_LEGACIES_SYNTHETIC_TIFF_BENCHMARK"


def _elapsed(callable_, *args, **kwargs):
    started = time.perf_counter()
    result = callable_(*args, **kwargs)
    return result, time.perf_counter() - started


@pytest.mark.skipif(not os.environ.get(TIFF_ENV), reason=f"set {TIFF_ENV} to a representative TIFF")
def test_representative_large_tiff_ingest_and_preview():
    path = Path(os.environ[TIFF_ENV]).expanduser().resolve()
    assert path.is_file(), f"representative TIFF does not exist: {path}"

    header, header_s = _elapsed(read_tiff_header, path)
    validated, validate_s = _elapsed(validate_tiff, path)
    assert validated == header

    images = RadarImageCache(max_bytes=max(header["width"] * header["height"] * 2, 1))
    windows = RenderedWindowCache()
    scale = 64
    preview_width = min(header["width"], 4096 * scale)
    preview, cold_preview_s = _elapsed(
        render_cached, images, windows, path, x=0, width=preview_width, scale=scale
    )
    cached_preview, warm_preview_s = _elapsed(
        render_cached, images, windows, path, x=0, width=preview_width, scale=scale
    )
    assert cached_preview is preview

    with Image.open(io.BytesIO(preview)) as image:
        assert image.format == "PNG"
        assert image.size == (
            -(-preview_width // scale),
            -(-header["height"] // scale),
        )

    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(
        "\n[large TIFF benchmark] "
        f"bytes={path.stat().st_size:,} dimensions={header['width']}x{header['height']} "
        f"mode={header['mode']} header={header_s:.3f}s full_validate={validate_s:.3f}s "
        f"cold_preview={cold_preview_s:.3f}s warm_preview={warm_preview_s:.6f}s "
        f"decoded_bytes={images.get(path).nbytes:,} peak_rss_kib={peak_rss:,}"
    )


class _SyntheticBatch(RadarStorageProvider):
    """Many logical TIFF objects sharing one immutable synthetic byte buffer."""

    provider = "synthetic-benchmark"
    capabilities = frozenset({"list", "stat", "range_read"})

    def __init__(self, payload: bytes, count: int):
        self.payload = payload
        self.objects = [StorageObject(
            key=f"tiff/F127-C{i:06d}_C{i + 9:06d}.tiff", size=len(payload),
            mtime_ns=1, etag=f"synthetic-{i}") for i in range(count)]

    def list(self, prefix="", *, suffixes=()):
        return iter(self.objects)

    def stat(self, key):
        return next((obj for obj in self.objects if obj.key == key), None)

    def read_range(self, key, offset, length):
        return self.payload[offset:offset + length]

    def check(self):
        return {"ok": True, "message": "synthetic"}

    def describe(self):
        return {"provider": self.provider, "location": "memory"}


@pytest.mark.skipif(not os.environ.get(SYNTHETIC_ENV),
                    reason=f"set {SYNTHETIC_ENV}=1 to run the synthetic batch benchmark")
def test_synthetic_large_tiff_batch_index_and_resume(tmp_path):
    """Exercise real ranged TIFF headers over a 1-GiB logical batch."""
    image = Image.new("I;16", (4096, 512), 1234)
    output = io.BytesIO()
    image.save(output, format="TIFF", compression="raw")
    provider = _SyntheticBatch(output.getvalue(), 256)
    catalog = RadarCatalog(tmp_path / "synthetic-batch.db")
    source = catalog.add_source(source_id="synthetic", name="Synthetic benchmark",
                                provider=provider.provider, dataset_id="synthetic-benchmark",
                                config={"max_index_objects": 256})

    first, first_s = _elapsed(indexer.index_source, catalog, source, provider)
    resumed, resumed_s = _elapsed(indexer.index_source, catalog, source, provider)
    assert first["status"] == resumed["status"] == "completed"
    assert first["counts"]["added"] == 256
    assert resumed["counts"]["unchanged"] == 256
    print("\n[synthetic TIFF batch benchmark] "
          f"objects=256 logical_bytes={len(provider.payload) * 256:,} "
          f"first={first_s:.3f}s resume={resumed_s:.3f}s")
