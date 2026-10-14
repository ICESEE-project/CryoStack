"""Radar catalog benchmark with generated metadata (no TIFF files).

The 10,000-file run is part of the normal suite. The 100,000-file run is
opt-in (it takes about a minute):

    FROZEN_LEGACIES_BENCHMARK=1 python -m pytest -s \\
        icesee_jupyter_book/applications/frozen_legacies/tests/test_frozen_legacies_catalog_benchmark.py

Both drive the real indexer (header reads are stubbed) and report index,
incremental-update and query timings, database size and memory.
"""
from __future__ import annotations

import os
import resource
import sys
import time
import tracemalloc
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.applications.frozen_legacies.radar import indexer
from icesee_jupyter_book.applications.frozen_legacies.radar.catalog import RadarCatalog
from icesee_jupyter_book.applications.frozen_legacies.radar.storage import (
    RadarStorageProvider, StorageObject)


class GeneratedArchive(RadarStorageProvider):
    """Object listing of a large archive: ``per_flight`` segments per flight."""

    provider = "generated"
    capabilities = frozenset({"list", "stat"})

    def __init__(self, n: int, per_flight: int = 500):
        self.objects = {}
        for i in range(n):
            flight, seg = 100 + i // per_flight, i % per_flight
            start = 10 + seg * 13
            key = f"tiff/F{flight}/F{flight}-C{start:04d}_C{start + 12:04d}.tiff"
            self.objects[key] = StorageObject(key=key, size=110_000_000, mtime_ns=1,
                                              etag=f"v1-{i}")

    def list(self, prefix="", *, suffixes=()):
        return iter(self.objects.values())

    def stat(self, key):
        return self.objects.get(key)

    def check(self):
        return {"ok": True, "message": "ok"}

    def describe(self):
        return {"provider": self.provider, "location": "generated"}


def _ms(fn, *args, repeat=3, **kwargs):
    best = None
    for _ in range(repeat):
        t = time.perf_counter()
        value = fn(*args, **kwargs)
        elapsed = (time.perf_counter() - t) * 1000
        best = elapsed if best is None else min(best, elapsed)
    return value, best


def run_benchmark(tmp_path: Path, n: int, monkeypatch) -> dict:
    monkeypatch.setattr(indexer, "read_header",
                        lambda provider, obj: {"width": 37943, "height": 2400, "mode": "I;16"})
    db = tmp_path / f"bench-{n}.db"
    catalog = RadarCatalog(db)
    source = catalog.add_source(source_id="bench", name="Bench", provider="generated",
                                dataset_id="frozen-legacies-ascope", config={})
    archive = GeneratedArchive(n)
    tracemalloc.start()
    t = time.perf_counter()
    first = indexer.index_source(catalog, source, archive)
    index_s = time.perf_counter() - t
    index_peak_mb = tracemalloc.get_traced_memory()[1] / 2**20
    tracemalloc.stop()
    assert first["counts"]["added"] == n

    # incremental: 1% changed, 0.5% removed (below the mass-missing guard)
    keys = list(archive.objects)
    for key in keys[: n // 100]:
        old = archive.objects[key]
        archive.objects[key] = StorageObject(key=key, size=old.size, mtime_ns=2, etag="v2")
    for key in keys[-(n // 200):]:
        del archive.objects[key]
    t = time.perf_counter()
    second = indexer.index_source(catalog, source, archive)
    incremental_s = time.perf_counter() - t
    assert second["counts"]["changed"] == n // 100 and second["counts"]["missing"] == n // 200

    # per-user state for 2% of the files (as the picker would record it)
    owner = "user-bench-0123456789ab"
    ids = [r["catalog_id"] for r in catalog.search(page_size=100)["items"]]
    sample = catalog.search(flight="110", page_size=100)["items"]
    for i, item in enumerate(sample):
        catalog.set_user_state(owner, item["catalog_id"], "0" * 32,
                               manual="manual_completed" if i % 2 else "manual_in_progress",
                               automatic=None)

    total = catalog.search(page_size=100)
    pages = total["pages"]
    timings = {}
    _, timings["lookup by id"] = _ms(catalog.get_public, ids[0])
    _, timings["first page"] = _ms(catalog.search, page_size=100)
    _, timings["middle page"] = _ms(catalog.search, page=pages // 2, page_size=100)
    _, timings["last page"] = _ms(catalog.search, page=pages, page_size=100)
    _, timings["dataset filter"] = _ms(catalog.search, dataset_id="frozen-legacies-ascope",
                                       page_size=100)
    found, timings["flight filter"] = _ms(catalog.search, flight="110", page_size=100)
    assert found["total"] == 500
    _, timings["flight, last page"] = _ms(catalog.search, flight="110", page=5, page_size=100)
    found, timings["CBD lookup"] = _ms(catalog.search, flight="110", cbd=300)
    assert found["total"] == 1
    found, timings["text search"] = _ms(catalog.search, q="F110-C0023")
    assert found["total"] == 1
    found, timings["status filter (missing)"] = _ms(catalog.search, status="missing")
    assert found["total"] == n // 200
    found, timings["my state: in progress"] = _ms(catalog.search, owner=owner,
                                                  state="manual_in_progress", page_size=100)
    assert found["total"] == 50
    _, timings["my state: unprocessed"] = _ms(catalog.search, owner=owner, state="unprocessed",
                                              page_size=100)
    _, timings["summary + my progress"] = _ms(catalog.summary, owner=owner)
    return {
        "n": n,
        "db_mb": sum(p.stat().st_size for p in tmp_path.glob(db.name + "*")) / 2**20,
        "index_s": index_s,
        "index_peak_mb": index_peak_mb,
        "incremental_s": incremental_s,
        "max_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "timings_ms": timings,
    }


def _report(result):
    lines = [f"\n[catalog benchmark] {result['n']:,} files: index {result['index_s']:.2f} s "
             f"(peak Python allocations {result['index_peak_mb']:.0f} MB), incremental "
             f"update {result['incremental_s']:.2f} s, database {result['db_mb']:.1f} MB, "
             f"process max RSS {result['max_rss_mb']:.0f} MB"]
    lines += [f"    {name:<26} {ms:7.1f} ms" for name, ms in result["timings_ms"].items()]
    print("\n".join(lines))


def test_catalog_benchmark_10k(tmp_path, monkeypatch):
    result = run_benchmark(tmp_path, 10_000, monkeypatch)
    _report(result)
    assert max(result["timings_ms"].values()) < 250


@pytest.mark.skipif(not os.environ.get("FROZEN_LEGACIES_BENCHMARK"),
                    reason="set FROZEN_LEGACIES_BENCHMARK=1 to run the 100,000-file benchmark")
def test_catalog_benchmark_100k(tmp_path, monkeypatch):
    result = run_benchmark(tmp_path, 100_000, monkeypatch)
    _report(result)
    assert max(result["timings_ms"].values()) < 1000
