"""Radar catalog hardening: provider contract and working cache, identity,
incremental indexing (new / unchanged / changed / moved / unavailable /
deleted / duplicate / invalid), outage safety, rebuild, per-user state index
and progress, navigation segments, maintainer access, catalog assets in the
picker, and the My picks lifecycle including the map -> picker round trip."""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[3]
for _p in (str(_REPO), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from frozen_legacies_radar_fixtures import requires_astra, tiff_bytes, write_tiff
from cryostack_src.workspace import WorkspaceUser, owner_root
from icesee_jupyter_book.applications.frozen_legacies import server
from icesee_jupyter_book.applications.frozen_legacies.radar import catalog as catalog_mod
from icesee_jupyter_book.applications.frozen_legacies.radar import indexer, storage
from icesee_jupyter_book.applications.frozen_legacies.radar import working_cache as cache_mod
from icesee_jupyter_book.applications.frozen_legacies.radar.catalog import RadarCatalog, asset_key
from icesee_jupyter_book.applications.frozen_legacies.radar.indexer import index_source, read_header
from icesee_jupyter_book.applications.frozen_legacies.radar.sources import SOURCES_ENV
from icesee_jupyter_book.applications.frozen_legacies.radar.storage import (
    LocalProvider, RadarStorageProvider, StorageError, StorageKeyError, StorageObject,
    normalize_key)
from icesee_jupyter_book.applications.frozen_legacies.radar.working_cache import WorkingCache

API = "/frozen-legacies/api"


def _strip(width=2600, height=420):
    img = np.full((height, width), 58000, np.uint16)
    x = np.arange(width)
    centre = (330 + 40 * np.sin(x / 50.0)).astype(int)
    for dy in range(-3, 4):
        img[np.clip(centre + dy, 0, height - 1), x] = 600
    return img


NAV = "CBD,LAT,LON,THK,SRF\n" + "".join(
    f"{c},{-81.4 - (c - 465) * 0.01:.6f},{-169.8 + (c - 465) * 0.03:.6f},9999,9999\n"
    for c in range(465, 490))


@pytest.fixture
def archive(tmp_path, monkeypatch):
    """An approved storage root with a few real TIFFs and navigation."""
    root = tmp_path / "archive"
    (root / "tiff" / "F127").mkdir(parents=True)
    (root / "nav").mkdir()
    for start in (471, 484, 497):
        write_tiff(root / "tiff" / "F127" / f"F127-C{start:04d}_C{start + 12:04d}.tiff", _strip())
    write_tiff(root / "tiff" / "F125-C0100_C0110.tiff", _strip())
    (root / "tiff" / "broken.tiff").write_bytes(b"II*\x00not really a tiff")
    (root / "nav" / "127.csv").write_text(NAV)
    monkeypatch.setenv(storage.STORAGE_ROOTS_ENV, str(tmp_path))
    monkeypatch.setenv(catalog_mod.CATALOG_ENV, str(tmp_path / "var" / "catalog.db"))
    monkeypatch.setenv(cache_mod.CACHE_DIR_ENV, str(tmp_path / "var" / "cache"))
    monkeypatch.setattr(cache_mod, "_cache", None)
    catalog_mod._shared.clear()
    from icesee_jupyter_book.applications.frozen_legacies import catalog_routes
    catalog_routes._reconciled.clear()
    return root


def _source(catalog, root, source_id="archive", dataset="frozen-legacies-ascope"):
    return catalog.add_source(source_id=source_id, name="Test archive", provider="local",
                              dataset_id=dataset,
                              config={"root": str(root), "tiff_prefix": "tiff",
                                      "nav_template": "nav/{flight}.csv"})


# ── provider contract ────────────────────────────────────────────────
@pytest.mark.parametrize("key", ["", "/etc/passwd", "../x", "a/../b", "a//b", "a/./b",
                                 "a\\b", "a\x00b", "x" * 1025])
def test_storage_keys_are_normalized(key):
    with pytest.raises(StorageKeyError):
        normalize_key(key)


def test_local_provider_requires_an_approved_root(tmp_path, monkeypatch):
    monkeypatch.setenv(storage.STORAGE_ROOTS_ENV, str(tmp_path / "approved"))
    (tmp_path / "approved" / "a").mkdir(parents=True)
    LocalProvider(tmp_path / "approved" / "a")
    for outside in (tmp_path, tmp_path / "other", Path("/etc")):
        with pytest.raises(StorageKeyError):
            LocalProvider(outside)
    monkeypatch.delenv(storage.STORAGE_ROOTS_ENV)
    with pytest.raises(StorageKeyError):              # no roots configured: nothing allowed
        LocalProvider(tmp_path / "approved" / "a")


def test_local_provider_is_the_reference_implementation(archive, tmp_path):
    secret = tmp_path / "secret.tiff"
    secret.write_bytes(b"II*\x00secret")
    (archive / "tiff" / "link.tiff").symlink_to(secret)
    (archive / "tiff" / "dirlink").symlink_to(tmp_path)
    provider = LocalProvider(archive)
    assert provider.capabilities == {"list", "stat", "stream", "range_read", "local_files"}
    keys = [o.key for o in provider.list("tiff", suffixes=(".tiff",))]
    assert "tiff/link.tiff" not in keys and not any("dirlink" in k for k in keys)
    assert provider.stat("tiff/link.tiff") is None and provider.local_file("tiff/link.tiff") is None
    assert provider.stat("../secret.tiff") is None
    key = "tiff/F127/F127-C0471_C0483.tiff"
    obj = provider.stat(key)
    with provider.open_stream(key) as stream:
        assert stream.read(4) == b"II*\x00"
    assert provider.read_range(key, 0, 4) == b"II*\x00"
    assert obj.version == f"{obj.size}-{obj.mtime_ns}"
    described = provider.describe()
    assert str(tmp_path) not in json.dumps(described) and described["location"].startswith("…/")
    assert provider.check()["ok"] is True


class RemoteLike(RadarStorageProvider):
    """A provider without local files (object-storage semantics): listing,
    stat, streaming and ranged reads only."""

    provider = "remote"
    capabilities = frozenset({"list", "stat", "stream", "range_read"})

    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects
        self.ranges = 0
        self.streams = 0
        self.fail_stream_after: int | None = None

    def list(self, prefix="", *, suffixes=()):
        for key, data in sorted(self.objects.items()):
            if key.startswith(prefix) and (not suffixes or key.lower().endswith(suffixes)):
                yield StorageObject(key=key, size=len(data), mtime_ns=1, etag=f"etag-{len(data)}")

    def stat(self, key):
        data = self.objects.get(key)
        return None if data is None else StorageObject(key=key, size=len(data), mtime_ns=1,
                                                       etag=f"etag-{len(data)}")

    def open_stream(self, key):
        self.streams += 1
        data = self.objects[key]
        if self.fail_stream_after is not None:
            limit = self.fail_stream_after

            class Broken(io.BytesIO):
                def read(self_inner, n=-1):
                    if self_inner.tell() >= limit:
                        raise OSError("connection reset")
                    return super().read(min(n, limit - self_inner.tell()) if n > 0 else n)
            return Broken(data)
        return io.BytesIO(data)

    def read_range(self, key, offset, length):
        self.ranges += 1
        return self.objects[key][offset:offset + length]

    def check(self):
        return {"ok": True, "message": "ok"}

    def describe(self):
        return {"provider": self.provider, "location": "remote"}


def test_headers_are_read_by_range_without_downloading(tmp_path):
    data = tiff_bytes(_strip(4000, 420), compression="raw")       # ~3.4 MB
    remote = RemoteLike({"tiff/F1-C1_C2.tiff": data})
    obj = remote.stat("tiff/F1-C1_C2.tiff")
    header = read_header(remote, obj)
    assert (header["width"], header["height"], header["mode"]) == (4000, 420, "I;16")
    assert remote.streams == 0 and remote.ranges * 64 * 1024 < len(data)


def test_working_cache_materializes_validates_and_evicts(tmp_path):
    objects = {f"tiff/F1-C{i}_C{i + 1}.tiff": bytes([i]) * 1000 for i in range(4)}
    remote = RemoteLike(objects)
    cache = WorkingCache(tmp_path / "cache", max_bytes=2500)
    first = remote.stat("tiff/F1-C0_C1.tiff")
    path = cache.materialize(remote, "src", first)
    assert path.read_bytes() == objects[first.key] and cache.downloads == 1
    assert cache.materialize(remote, "src", first) == path and cache.downloads == 1   # reused
    with cache.lease(path):
        for i in (1, 2, 3):
            cache.materialize(remote, "src", remote.stat(f"tiff/F1-C{i}_C{i + 1}.tiff"))
        assert path.exists()                              # leased: never evicted
    assert cache.usage() <= 2500 + 1000
    cache.materialize(remote, "src", remote.stat("tiff/F1-C1_C2.tiff"))
    assert cache.usage() <= 2500


def test_working_cache_discards_interrupted_and_inconsistent_downloads(tmp_path):
    remote = RemoteLike({"tiff/F1-C1_C2.tiff": b"x" * 5000})
    obj = remote.stat("tiff/F1-C1_C2.tiff")
    cache = WorkingCache(tmp_path / "cache", max_bytes=10_000)
    remote.fail_stream_after = 2000
    with pytest.raises(StorageError):                       # retried once, then reported
        cache.materialize(remote, "src", obj)
    assert remote.streams == 2
    assert list((tmp_path / "cache").iterdir()) == []       # no partial file
    remote.fail_stream_after = None
    wrong = StorageObject(key=obj.key, size=4000, mtime_ns=1, etag=obj.etag)   # stale metadata
    with pytest.raises(StorageError):
        cache.materialize(remote, "src", wrong)
    assert list((tmp_path / "cache").iterdir()) == []
    assert cache.materialize(remote, "src", obj).read_bytes() == b"x" * 5000


def test_working_cache_refuses_an_object_larger_than_its_limit(tmp_path):
    remote = RemoteLike({"tiff/F1-C1_C2.tiff": b"z" * 5000})
    cache = WorkingCache(tmp_path / "cache", max_bytes=4000)
    with pytest.raises(StorageError, match="larger than this server's working-cache limit"):
        cache.materialize(remote, "src", remote.stat("tiff/F1-C1_C2.tiff"))
    assert remote.streams == 0                                # nothing downloaded


def test_working_cache_checks_free_disk_space(tmp_path, monkeypatch):
    from collections import namedtuple
    from icesee_jupyter_book.applications.frozen_legacies.radar import working_cache as wc

    remote = RemoteLike({"tiff/F1-C1_C2.tiff": b"z" * 5000})
    cache = WorkingCache(tmp_path / "cache", max_bytes=10**9)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(wc.shutil, "disk_usage", lambda path: usage(10**12, 10**12, 1000))
    with pytest.raises(StorageError, match="Not enough free disk space"):
        cache.materialize(remote, "src", remote.stat("tiff/F1-C1_C2.tiff"))
    assert remote.streams == 0
    monkeypatch.setattr(wc.shutil, "disk_usage",
                        lambda path: usage(10**12, 0, wc.FREE_SPACE_RESERVE + 5000))
    assert cache.materialize(remote, "src", remote.stat("tiff/F1-C1_C2.tiff")).stat().st_size == 5000


def test_working_cache_downloads_once_under_concurrency(tmp_path):
    remote = RemoteLike({"tiff/F1-C1_C2.tiff": b"y" * 200_000})
    obj = remote.stat("tiff/F1-C1_C2.tiff")
    cache = WorkingCache(tmp_path / "cache", max_bytes=10**7)
    paths = []
    threads = [threading.Thread(target=lambda: paths.append(cache.materialize(remote, "s", obj)))
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(paths)) == 1 and cache.downloads == 1 and remote.streams == 1


def test_local_files_are_used_in_place_never_copied(archive, tmp_path):
    provider = LocalProvider(archive)
    cache = WorkingCache(tmp_path / "cache", max_bytes=1)
    obj = provider.stat("tiff/F127/F127-C0471_C0483.tiff")
    assert cache.materialize(provider, "archive", obj) == provider.local_file(obj.key)
    assert not (tmp_path / "cache").exists()


def test_remote_source_indexes_and_opens_through_the_cache(tmp_path, monkeypatch):
    monkeypatch.setenv(cache_mod.CACHE_DIR_ENV, str(tmp_path / "cache"))
    monkeypatch.setattr(cache_mod, "_cache", None)
    data = tiff_bytes(_strip())
    remote = RemoteLike({"tiff/F127-C0471_C0483.tiff": data, "nav/127.csv": NAV.encode()})
    catalog = RadarCatalog(tmp_path / "c.db")
    source = catalog.add_source(source_id="remote", name="Remote", provider="remote",
                                dataset_id="ds", config={"tiff_prefix": "tiff",
                                                         "nav_template": "nav/{flight}.csv"})
    assert index_source(catalog, source, remote)["status"] == "completed"
    item = catalog.search()["items"][0]
    assert item["width"] == 2600 and item["has_nav"] and remote.streams == 1   # nav only
    from icesee_jupyter_book.applications.frozen_legacies.radar import sources as sources_mod
    monkeypatch.setattr(storage, "provider_for", lambda p, c: remote)
    resolved = sources_mod.resolve_catalog_source(catalog, item["catalog_id"])
    assert resolved.tiff_path.read_bytes() == data
    assert resolved.tiff_path.is_relative_to(tmp_path / "cache")


# ── identity and indexing ────────────────────────────────────────────
def test_identity_is_source_and_key_not_file_name():
    a = asset_key("source-a", "F127/F127-C0471_C0483.tiff")
    b = asset_key("source-b", "F127/F127-C0471_C0483.tiff")
    c = asset_key("source-a", "other/F127-C0471_C0483.tiff")
    assert len({a, b, c}) == 3 and all(catalog_mod.is_catalog_key(k) for k in (a, b, c))
    assert a == asset_key("source-a", "F127/F127-C0471_C0483.tiff")       # stable
    assert "F127" not in a


def test_catalog_track_geometry_splits_at_antimeridian():
    geometry = catalog_mod._track_geometry([
        [178.0, -80.0], [179.0, -81.0], [-179.0, -82.0], [-178.0, -83.0]])
    assert geometry["type"] == "MultiLineString"
    west, east = geometry["coordinates"]
    assert west == [[178.0, -80.0], [179.0, -81.0], [180.0, -81.5]]
    assert east == [[-180.0, -81.5], [-179.0, -82.0], [-178.0, -83.0]]


def test_catalog_track_geometry_preserves_ordinary_lines_and_points():
    assert catalog_mod._track_geometry([[10.0, -80.0]]) == {
        "type": "Point", "coordinates": [10.0, -80.0]}
    coords = [[10.0, -80.0], [11.0, -81.0]]
    assert catalog_mod._track_geometry(coords) == {
        "type": "LineString", "coordinates": coords}


def test_indexing_reads_metadata_tracks_and_flags_invalid_files(archive):
    catalog = RadarCatalog(catalog_mod.catalog_path())
    result = index_source(catalog, _source(catalog, archive), LocalProvider(archive))
    assert result["status"] == "completed"
    assert result["counts"]["discovered"] == 5 and result["counts"]["added"] == 5
    assert result["counts"]["invalid"] == 1
    found = catalog.search(page_size=100)
    assert found["total"] == 4                                   # invalid files are not listed
    f127 = [i for i in found["items"] if i["flight"] == "127"]
    assert [(i["cbd_start"], i["cbd_end"]) for i in f127] == [(471, 483), (484, 496), (497, 509)]
    assert all(i["width"] == 2600 and i["has_nav"] for i in f127)
    segments = catalog.segments(flight="127")["features"]
    # tracks come only from real navigation records (CBDs 465-489 exist)
    by_start = {f["properties"]["cbd_start"]: f for f in segments}
    assert set(by_start) == {471, 484}
    assert len(by_start[471]["geometry"]["coordinates"]) == 13
    assert by_start[471]["geometry"]["coordinates"][0] == [-169.62, -81.46]
    assert by_start[484]["geometry"]["type"] == "LineString"       # CBDs 484-489 only
    assert "storage_key" not in json.dumps(segments)
    # 497-509 has no navigation records: counted as unplaced, never drawn
    summary = catalog.segments(flight="127")["summary"]
    assert summary == {"returned": 2, "truncated": False, "unplaced": 1}
    invalid = catalog.search(status="invalid")
    assert invalid["items"][0]["filename"] == "broken.tiff"


def test_incremental_cases(archive, tmp_path):
    catalog = RadarCatalog(catalog_mod.catalog_path())
    source = _source(catalog, archive)
    provider = LocalProvider(archive)
    index_source(catalog, source, provider)
    ids = {i["filename"]: i["catalog_id"] for i in catalog.search(page_size=100)["items"]}

    # unchanged
    again = index_source(catalog, source, provider)
    assert again["counts"]["unchanged"] == 5 and again["counts"]["added"] == 0

    # changed: same ID, new metadata
    target = archive / "tiff" / "F127" / "F127-C0484_C0496.tiff"
    write_tiff(target, _strip(2700, 420))
    changed = index_source(catalog, source, provider)
    assert changed["counts"]["changed"] == 1
    assert catalog.get_public(ids["F127-C0484_C0496.tiff"])["width"] == 2700

    # moved within the source: new ID, old row points to it
    old = archive / "tiff" / "F127" / "F127-C0497_C0509.tiff"
    (archive / "tiff" / "moved").mkdir()
    old.rename(archive / "tiff" / "moved" / old.name)
    moved = index_source(catalog, source, provider)
    assert moved["counts"]["moved"] == 1 and moved["counts"]["missing"] == 0
    old_id = ids["F127-C0497_C0509.tiff"]
    new_id = asset_key("archive", "tiff/moved/F127-C0497_C0509.tiff")
    assert catalog.get_public(old_id)["status"] == "moved"
    assert catalog.resolve(old_id)["catalog_id"] == new_id          # followed

    # deleted: kept as missing; reappearing restores it
    gone = archive / "tiff" / "F125-C0100_C0110.tiff"
    data = gone.read_bytes()
    gone.unlink()
    deleted = index_source(catalog, source, provider)
    assert deleted["counts"]["missing"] == 1
    record = catalog.resolve(ids["F125-C0100_C0110.tiff"])
    assert record["status"] == "missing" and record["missing_since"] is not None
    gone.write_bytes(data)
    back = index_source(catalog, source, provider)
    assert catalog.get_public(ids["F125-C0100_C0110.tiff"])["status"] == "indexed"
    assert back["counts"]["missing"] == 0

    # full re-index re-reads everything
    assert index_source(catalog, source, provider, full=True)["counts"]["unchanged"] == 0


def test_temporarily_unreadable_files_are_unavailable_not_invalid(archive, monkeypatch):
    real = indexer.read_header

    def flaky(provider, obj):
        if obj.key.endswith("C0484_C0496.tiff"):
            raise OSError("I/O error on /very/secret/path")
        return real(provider, obj)

    monkeypatch.setattr(indexer, "read_header", flaky)
    catalog = RadarCatalog(catalog_mod.catalog_path())
    source = _source(catalog, archive)
    result = index_source(catalog, source, LocalProvider(archive))
    assert result["counts"]["unavailable"] == 1 and result["counts"]["invalid"] == 1
    item = catalog.search(status="unavailable")["items"][0]
    assert "/very/secret" not in (catalog.resolve(item["catalog_id"])["error"] or "")
    monkeypatch.setattr(indexer, "read_header", real)
    retried = index_source(catalog, source, LocalProvider(archive))   # retried, not skipped
    assert retried["counts"]["changed"] == 1
    assert catalog.get_public(item["catalog_id"])["status"] == "indexed"


def test_outages_never_look_like_mass_deletion(archive, tmp_path):
    catalog = RadarCatalog(catalog_mod.catalog_path())
    source = _source(catalog, archive)
    index_source(catalog, source, LocalProvider(archive))

    archive.rename(tmp_path / "offline")                     # whole source gone
    offline = index_source(catalog, source, LocalProvider(archive))
    assert offline["status"] == "unavailable"
    (tmp_path / "offline").rename(archive)

    for p in (archive / "tiff").rglob("*.tiff"):              # source lists nothing
        p.rename(tmp_path / p.name)
    empty = index_source(catalog, source, LocalProvider(archive))
    assert empty["status"] == "unavailable"
    assert catalog.search(status="missing")["total"] == 0 and catalog.search()["total"] == 4


def test_mass_missing_needs_confirmation(tmp_path):
    class Listing(RemoteLike):
        pass

    objects = {f"tiff/F9-C{i}_C{i + 1}.tiff": tiff_bytes(_strip(300, 300)) for i in range(40)}
    remote = Listing(objects)
    catalog = RadarCatalog(tmp_path / "c.db")
    source = catalog.add_source(source_id="many", name="Many", provider="remote",
                                dataset_id="ds", config={"tiff_prefix": "tiff"})
    index_source(catalog, source, remote)
    for key in list(objects)[:30]:                            # 75% vanish
        del objects[key]
    guarded = index_source(catalog, source, remote)
    assert guarded["status"] == "needs_confirmation"
    assert catalog.search(status="missing")["total"] == 0
    confirmed = index_source(catalog, source, remote, allow_mass_missing=True)
    assert confirmed["status"] == "completed" and confirmed["counts"]["missing"] == 30


def test_index_bounds_keep_partial_progress_without_marking_missing(tmp_path, monkeypatch):
    objects = {f"tiff/F9-C{i}_C{i + 1}.tiff": b"header" for i in range(6)}
    remote = RemoteLike(objects)
    catalog = RadarCatalog(tmp_path / "bounded.db")
    source = catalog.add_source(source_id="bounded", name="Bounded", provider="remote",
                                dataset_id="ds",
                                config={"tiff_prefix": "tiff", "max_index_objects": 3})
    monkeypatch.setattr(indexer, "read_header",
                        lambda provider, obj: {"width": 10, "height": 10, "mode": "L"})
    result = index_source(catalog, source, remote)
    assert result["status"] == "needs_confirmation"
    assert result["counts"]["discovered"] == 4
    assert result["counts"]["added"] == 3
    assert catalog.search(status="missing")["total"] == 0


def test_cancellation_is_checked_for_each_listed_object(tmp_path, monkeypatch):
    objects = {f"tiff/F9-C{i}_C{i + 1}.tiff": b"header" for i in range(6)}
    remote = RemoteLike(objects)
    catalog = RadarCatalog(tmp_path / "cancel.db")
    source = catalog.add_source(source_id="cancel", name="Cancel", provider="remote",
                                dataset_id="ds", config={"tiff_prefix": "tiff"})
    monkeypatch.setattr(indexer, "read_header",
                        lambda provider, obj: {"width": 10, "height": 10, "mode": "L"})
    result = index_source(catalog, source, remote,
                          should_stop=lambda: True)
    assert result["status"] == "cancelled"
    assert result["counts"]["discovered"] == 1
    assert result["counts"]["added"] == 1
    assert catalog.search(status="missing")["total"] == 0


def test_duplicate_names_stay_distinct_assets(archive):
    write_tiff(archive / "tiff" / "F127-C0471_C0483.tiff", _strip())
    catalog = RadarCatalog(catalog_mod.catalog_path())
    index_source(catalog, _source(catalog, archive), LocalProvider(archive))
    dupes = [i for i in catalog.search(flight="127", page_size=100)["items"] if i["duplicate"]]
    assert len(dupes) == 2 and len({i["catalog_id"] for i in dupes}) == 2


def test_catalog_is_an_index_that_rebuilds_with_the_same_ids(archive):
    path = catalog_mod.catalog_path()
    catalog = RadarCatalog(path)
    index_source(catalog, _source(catalog, archive), LocalProvider(archive))
    before = sorted(i["catalog_id"] for i in catalog.search(page_size=100)["items"])
    for p in path.parent.glob(path.name + "*"):
        p.unlink()
    rebuilt = RadarCatalog(path)
    index_source(rebuilt, _source(rebuilt, archive), LocalProvider(archive))
    assert sorted(i["catalog_id"] for i in rebuilt.search(page_size=100)["items"]) == before


def test_sqlite_operating_model(archive):
    catalog = RadarCatalog(catalog_mod.catalog_path())
    import sqlite3
    db = sqlite3.connect(catalog.path)
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    db.close()
    assert oct(catalog.path.stat().st_mode & 0o777) == "0o640"
    assert catalog_mod.BUSY_TIMEOUT_S == 30
    with pytest.raises(catalog_mod.CatalogError):
        catalog.search(state="manual_in_progress")           # needs a user


def test_old_catalog_files_are_migrated_in_place(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript(catalog_mod._SCHEMA)
    db.execute("INSERT INTO data_sources VALUES ('s1','S','local','d','{}','enabled',1,1,"
               "NULL,NULL,NULL)")
    db.execute("INSERT INTO radar_assets (catalog_id, source_id, dataset_id, storage_key,"
               " filename, flight, bytes, mtime_ns, status, first_indexed_at, indexed_at)"
               " VALUES ('cat-000000000000000000000001','s1','d','k','f.tiff','127',1,1,"
               "'indexed',1,1)")
    db.commit()
    db.close()
    catalog = RadarCatalog(path)
    assert catalog.search()["items"][0]["flight"] == "127"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT flight_num FROM radar_assets").fetchone()[0] == 127


# ── HTTP: maintainers, users, picker, observations ───────────────────
@pytest.fixture
def web_env(archive, tmp_path, monkeypatch):
    from icesee_auth import AuthManager

    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(tmp_path / "auth.db"))
    monkeypatch.setenv(SOURCES_ENV, str(tmp_path / "no-registry.yaml"))
    return {"tmp": tmp_path, "archive": archive, "auth": AuthManager(),
            "workspace": tmp_path / "ws"}


def _login(env, email, *roles):
    store = env["auth"].storage
    user = store.create_user(email=email, display_name=email, institution=None,
                             password_hash="x")
    for role in roles:
        store.grant_role(user_id=user.id, role=role)
    session = store.create_session(ttl_seconds=3600, user_id=user.id)
    return user, {"icesee_session": session.id}


def _relogin(env, user):
    session = env["auth"].storage.create_session(ttl_seconds=3600, user_id=user.id)
    return {"icesee_session": session.id}


def _run(env, script):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    app = web.Application()
    env["auth"].install(app)
    app[server.WORKSPACE_ROOT_KEY] = str(env["workspace"])
    server.install_frozen_legacies(app, auth=env["auth"])
    app["_root"] = env["archive"]

    async def go():
        async with TestClient(TestServer(app)) as client:
            return await script(client, app)

    return asyncio.run(go())


async def _json(resp):
    return resp.status, (await resp.json() if resp.content_type == "application/json" else None)


async def _setup_source(client, app, ck):
    status, body = await _json(await client.post(f"{API}/admin/sources", cookies=ck, json={
        "source_id": "archive", "name": "Test archive", "dataset_id": "frozen-legacies-ascope",
        "provider": "local", "root": str(app["_root"]), "tiff_prefix": "tiff",
        "nav_template": "nav/{flight}.csv"}))
    assert status == 201, body
    await _index(client, app, ck)


async def _index(client, app, ck, **payload):
    status, body = await _json(await client.post(f"{API}/admin/sources/archive/index",
                                                 cookies=ck, json=payload))
    assert status == 202, body
    await _wait_worker(app, body["run_id"])


async def _wait_worker(app, run_id):
    """The background worker process of a run has exited."""
    worker = app["frozen_legacies_index_workers"].get(run_id)
    if worker is not None:
        await asyncio.wait_for(worker[1], timeout=120)


def _asset_dir(env, user, asset_id):
    return (owner_root(WorkspaceUser(user_id=user.id, source="cryostack-auth"),
                       workspace_root=env["workspace"]) / "frozen_legacies" / "radar" / asset_id)


def test_maintainer_access_is_checked_on_every_request(web_env):
    _u, normal = _login(web_env, "user@example.org")
    _d, developer = _login(web_env, "dev@example.org", "developer")
    maint_user, maint = _login(web_env, "maint@example.org", "maintainer")

    async def script(client, app):
        out = {}
        out["anon"] = (await client.get(f"{API}/admin/sources")).status
        out["user"] = (await client.get(f"{API}/admin/sources", cookies=normal)).status
        out["user_post"] = (await client.post(f"{API}/admin/sources", cookies=normal,
                                              json={"source_id": "x"})).status
        out["developer"] = (await client.get(f"{API}/admin/sources", cookies=developer)).status
        out["page_user"] = (await client.get("/control/frozen-legacies", cookies=normal,
                                             allow_redirects=False)).status
        out["outside"] = (await client.post(f"{API}/admin/sources", cookies=maint, json={
            "source_id": "etc", "name": "x", "dataset_id": "d", "provider": "local",
            "root": "/etc"})).status
        out["s3"] = (await client.post(f"{API}/admin/sources", cookies=maint, json={
            "source_id": "s3", "name": "x", "dataset_id": "d", "provider": "s3",
            "root": "bucket"})).status
        out["cross_origin"] = (await client.post(f"{API}/admin/sources", cookies=maint,
                                                 headers={"Origin": "https://evil.example"},
                                                 json={})).status
        await _setup_source(client, app, maint)
        status, test = await _json(await client.post(f"{API}/admin/sources/archive/test",
                                                     cookies=maint, json={}))
        status, listed = await _json(await client.get(f"{API}/admin/sources", cookies=maint))
        out["listed"] = listed["sources"][0]
        page = await client.get("/control/frozen-legacies", cookies=maint)
        page_text = await page.text()
        out["page"] = (page.status, "Last successful index" in page_text)
        out["intake_help"] = all(term in page_text for term in (
            "How dataset intake works", "resumes verified chunks",
            "local durable XFS staging", "fully verified immutable release to CEDAR",
            "managed SMB gateway", "Indexing alone never makes results public"))
        # role revoked: the very next request is refused
        web_env["auth"].storage.revoke_role(user_id=maint_user.id, role="maintainer")
        out["revoked"] = (await client.get(f"{API}/admin/sources", cookies=maint)).status
        return out

    out = _run(web_env, script)
    assert (out["anon"], out["user"], out["user_post"], out["developer"], out["page_user"]) == (
        401, 403, 403, 403, 403)
    assert out["outside"] == 400 and out["s3"] == 400 and out["cross_origin"] == 403
    source = out["listed"]
    assert source["counts"]["indexed"] == 4 and source["counts"]["invalid"] == 1
    assert source["connection"]["ok"] is True and source["last_success_at"]
    assert source["location"].startswith("…/") and str(web_env["tmp"]) not in json.dumps(source)
    assert out["page"] == (200, True)
    assert out["intake_help"] is True
    assert out["revoked"] == 403


def test_catalog_api_hides_storage_details_and_validates(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    _u, normal = _login(web_env, "user@example.org")

    async def script(client, app):
        await _setup_source(client, app, maint)
        page = await client.get(f"{API}/radar/catalog?flight=127&page_size=2", cookies=normal)
        text = await page.text()
        bad = [(await client.get(f"{API}/radar/catalog?{q}", cookies=normal)).status
               for q in ("page=x", "status=weird", "state=approved-by-me", "dataset=../x", "cbd=a",
                         "flight=1;drop")]
        huge = await (await client.get(f"{API}/radar/catalog?page_size=100000",
                                       cookies=normal)).json()
        segments = await (await client.get(f"{API}/radar/catalog/segments?flight=127",
                                           cookies=normal)).json()
        return json.loads(text), text, bad, huge, segments

    body, text, bad, huge, segments = _run(web_env, script)
    assert body["total"] == 3 and len(body["items"]) == 2 and body["pages"] == 2
    assert body["items"][0]["processing"] == ["unprocessed"]
    for secret in (str(web_env["archive"]), "storage_key", "tiff/F127", "nav_key"):
        assert secret not in text
    assert bad == [400] * 6
    assert huge["page_size"] == catalog_mod.MAX_PAGE_SIZE
    assert len(segments["features"]) == 2 and "tiff/" not in json.dumps(segments)


@requires_astra
def test_my_picks_lifecycle_and_round_trip(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    user_a, a = _login(web_env, "a@example.org")
    _b, b = _login(web_env, "b@example.org")

    async def script(client, app):
        await _setup_source(client, app, maint)
        listing = await (await client.get(f"{API}/radar/catalog?flight=127&page_size=1",
                                          cookies=a)).json()
        key = listing["items"][0]["catalog_id"]
        asset = await (await client.post(f"{API}/assets/shared", cookies=a,
                                         json={"source": key})).json()
        aid = asset["asset_id"]
        base = f"{API}/assets/{aid}/manual"
        m = await (await client.get(base, cookies=a)).json()
        rev = m["revision"]
        windows = []
        for _ in range(3):
            r = await (await client.post(base, cookies=a, json={"revision": rev,
                                                                "action": "suggest"})).json()
            windows.append(r["state"]["slider"])
            r = await (await client.post(base, cookies=a, json={"revision": r["revision"],
                                                                "action": "next"})).json()
            r = await (await client.post(base, cookies=a, json={"revision": r["revision"],
                                                                "action": "step", "step": "jump"})).json()
            rev = r["revision"]
        out = {"windows": windows}
        out["draft"] = await (await client.get(f"{API}/observations", cookies=a)).json()
        out["relogin"] = await (await client.get(f"{API}/observations",
                                                 cookies=_relogin(web_env, user_a))).json()
        out["other"] = await (await client.get(f"{API}/observations", cookies=b)).json()
        out["progress"] = await (await client.get(f"{API}/radar/catalog/summary",
                                                  cookies=a)).json()
        out["progress_b"] = await (await client.get(f"{API}/radar/catalog/summary",
                                                    cookies=b)).json()
        out["state_a"] = await (await client.get(f"{API}/radar/catalog?state=manual_in_progress",
                                                 cookies=a)).json()
        out["state_b"] = await (await client.get(f"{API}/radar/catalog?state=manual_in_progress",
                                                 cookies=b)).json()
        out["unprocessed"] = await (await client.get(f"{API}/radar/catalog?state=unprocessed",
                                                     cookies=a)).json()
        # map -> picker: move the picker back to an A-scope's window
        target = out["draft"]["features"][1]["properties"]["window_x"]
        r = await (await client.post(base, cookies=a, json={"revision": rev, "action": "move",
                                                            "slider": target})).json()
        out["moved_to"] = r["state"]["slider"]
        out["title"] = r["title"]
        done = await (await client.post(base, cookies=a, json={"revision": r["revision"],
                                                               "action": "done"})).json()
        out["completed"] = await (await client.get(f"{API}/observations", cookies=a)).json()
        out["state_done"] = await (await client.get(
            f"{API}/radar/catalog?state=manual_completed", cookies=a)).json()
        await client.post(base, cookies=a, json={"action": "reset", "confirm": True})
        out["reset"] = await (await client.get(f"{API}/observations", cookies=a)).json()
        out["state_reset"] = await (await client.get(
            f"{API}/radar/catalog?state=unprocessed", cookies=a)).json()
        out["csv"] = done
        return out

    out = _run(web_env, script)
    draft = out["draft"]["features"]
    assert [f["properties"]["status"] for f in draft] == ["draft"] * 3
    assert [f["properties"]["window_x"] for f in draft] == out["windows"]
    props = draft[0]["properties"]
    assert props["scope"] == "user" and props["dataset_id"] == "frozen-legacies-ascope"
    assert props["catalog_id"].startswith("cat-") and props["workflow"] == "astra-manual"
    assert out["relogin"]["features"] == draft                       # survives re-login
    assert out["other"]["features"] == []
    flight = next(f for f in out["progress"]["flights"] if f["flight"] == "127")
    assert flight["mine"]["manual_in_progress"] == 1 and flight["mine"]["unprocessed"] == 2
    flight_b = next(f for f in out["progress_b"]["flights"] if f["flight"] == "127")
    assert flight_b["mine"]["manual_in_progress"] == 0 and flight_b["mine"]["unprocessed"] == 3
    assert out["state_a"]["total"] == 1 and out["state_b"]["total"] == 0
    assert out["unprocessed"]["total"] == 3
    assert out["moved_to"] == out["windows"][1]
    completed = out["completed"]["features"]
    assert len(completed) == 3 and {f["properties"]["status"] for f in completed} == {"completed"}
    assert [f["id"] for f in completed] == [f["id"] for f in draft]   # same picks, no duplicates
    assert out["state_done"]["total"] == 1
    assert out["reset"]["features"] == []
    assert out["state_reset"]["total"] == 4


@requires_astra
def test_deleting_an_asset_clears_its_state_but_not_the_catalog(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    _a, a = _login(web_env, "a@example.org")

    async def script(client, app):
        await _setup_source(client, app, maint)
        item = (await (await client.get(f"{API}/radar/catalog?flight=127", cookies=a)).json())["items"][0]
        asset = await (await client.post(f"{API}/assets/shared", cookies=a,
                                         json={"source": item["catalog_id"]})).json()
        base = f"{API}/assets/{asset['asset_id']}/manual"
        m = await (await client.get(base, cookies=a)).json()
        await client.post(base, cookies=a, json={"revision": m["revision"], "action": "suggest"})
        before = await (await client.get(f"{API}/radar/catalog?state=manual_in_progress",
                                         cookies=a)).json()
        await client.delete(f"{API}/assets/{asset['asset_id']}", cookies=a)
        after = await (await client.get(f"{API}/radar/catalog?state=manual_in_progress",
                                        cookies=a)).json()
        total = await (await client.get(f"{API}/radar/catalog", cookies=a)).json()
        return before, after, total

    before, after, total = _run(web_env, script)
    assert before["total"] == 1 and after["total"] == 0 and total["total"] == 4


@requires_astra
def test_missing_or_moved_catalog_files_keep_user_work(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    _a, a = _login(web_env, "a@example.org")

    async def script(client, app):
        await _setup_source(client, app, maint)
        listing = await (await client.get(f"{API}/radar/catalog?flight=127", cookies=a)).json()
        by_start = {i["cbd_start"]: i for i in listing["items"]}
        out = {}
        assets = {}
        for start in (471, 484):
            asset = await (await client.post(f"{API}/assets/shared", cookies=a,
                                             json={"source": by_start[start]["catalog_id"]})).json()
            base = f"{API}/assets/{asset['asset_id']}/manual"
            m = await (await client.get(base, cookies=a)).json()
            r = await (await client.post(base, cookies=a, json={"revision": m["revision"],
                                                                "action": "suggest"})).json()
            await client.post(base, cookies=a, json={"revision": r["revision"], "action": "next"})
            assets[start] = asset["asset_id"]
        folder = app["_root"] / "tiff" / "F127"
        (folder / "F127-C0471_C0483.tiff").unlink()                   # deleted
        (app["_root"] / "tiff" / "elsewhere").mkdir()
        (folder / "F127-C0484_C0496.tiff").rename(
            app["_root"] / "tiff" / "elsewhere" / "F127-C0484_C0496.tiff")   # moved
        await _index(client, app, maint)
        for start, aid in assets.items():
            detail = await (await client.get(f"{API}/assets/{aid}", cookies=a)).json()
            view = await client.get(f"{API}/assets/{aid}/manual/window?slider=0", cookies=a)
            out[start] = (detail["available"], view.status)
        out["observed"] = len((await (await client.get(f"{API}/observations",
                                                       cookies=a)).json())["features"])
        return out

    out = _run(web_env, script)
    assert out[471] == (False, 409)              # deleted: unavailable, work kept
    assert out[484] == (True, 200)               # moved: still opens
    assert out["observed"] == 2


@requires_astra
def test_observations_rebuild_and_reject_tampering(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    user, a = _login(web_env, "a@example.org")

    async def script(client, app):
        await _setup_source(client, app, maint)
        listing = await (await client.get(f"{API}/radar/catalog?flight=127", cookies=a)).json()
        asset = await (await client.post(f"{API}/assets/shared", cookies=a,
                                         json={"source": listing["items"][0]["catalog_id"]})).json()
        base = f"{API}/assets/{asset['asset_id']}/manual"
        m = await (await client.get(base, cookies=a)).json()
        r = await (await client.post(base, cookies=a, json={"revision": m["revision"],
                                                            "action": "suggest"})).json()
        await client.post(base, cookies=a, json={"revision": r["revision"], "action": "next"})
        directory = _asset_dir(web_env, user, asset["asset_id"])
        (directory / "observations.json").unlink()
        rebuilt = await (await client.get(f"{API}/observations", cookies=a)).json()
        (directory / "observations.json").write_text(json.dumps({"schema": "evil"}))
        tampered = await (await client.get(f"{API}/observations", cookies=a)).json()
        bad = [(await client.get(f"{API}/observations?{q}", cookies=a)).status
               for q in ("bbox=1,2,3", "bbox=a,b,c,d", "status=published", "asset=../x",
                         "limit=x")]
        return rebuilt, tampered, bad

    rebuilt, tampered, bad = _run(web_env, script)
    assert len(rebuilt["features"]) == 1 and len(tampered["features"]) == 1
    assert bad == [400] * 5


def test_users_cannot_alter_shared_catalog_data(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    _a, a = _login(web_env, "a@example.org")

    async def script(client, app):
        await _setup_source(client, app, maint)
        statuses = []
        for method, path, body in [
            ("POST", f"{API}/admin/sources/archive/index", {}),
            ("POST", f"{API}/admin/sources/archive/status", {"status": "disabled"}),
            ("POST", f"{API}/admin/sources", {"source_id": "mine", "root": "/"}),
            ("POST", f"{API}/radar/catalog", {}),
            ("PUT", f"{API}/radar/catalog", {}),
            ("DELETE", f"{API}/radar/catalog", None),
        ]:
            resp = await client.request(method, path, cookies=a, json=body)
            statuses.append(resp.status)
        listing = await (await client.get(f"{API}/radar/catalog", cookies=a)).json()
        return statuses, listing["total"]

    statuses, total = _run(web_env, script)
    assert statuses[:3] == [403, 403, 403] and all(s in (404, 405) for s in statuses[3:])
    assert total == 4


def test_explorer_returns_one_consistent_authorized_snapshot(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    _a, user = _login(web_env, "a@example.org")

    async def script(client, app):
        await _setup_source(client, app, maint)
        anonymous = await client.get(f"{API}/radar/explorer")
        response = await client.get(
            f"{API}/radar/explorer?dataset=frozen-legacies-ascope&flight=127"
            "&cbd_min=471&cbd_max=483", cookies=user)
        body = await response.json()
        invalid = await client.get(f"{API}/radar/explorer?qv=2", cookies=user)
        return anonymous.status, response.status, body, invalid.status, response.headers

    anonymous, status, body, invalid, headers = _run(web_env, script)
    assert anonymous == 401 and status == 200 and invalid == 422
    assert body["total"] == len(body["items"]) == 1
    assert {item["catalog_id"] for item in body["items"]} == {
        feature["id"] for feature in body["features"]["features"]}
    assert body["query"]["dataset"] == ["frozen-legacies-ascope"]
    assert body["facets"]["dataset"] and body["snapshot"]
    assert body["items"][0]["processing"] == ["unprocessed"]
    assert body["page"]["next_cursor"] is None
    assert headers["Cache-Control"] == "no-store"
    assert "storage_key" not in str(body)


def test_explorer_never_discloses_restricted_sources_or_cursor_results(web_env):
    _m, maint = _login(web_env, "maint@example.org", "maintainer")
    _a, user = _login(web_env, "a@example.org")

    async def script(client, app):
        await _setup_source(client, app, maint)
        catalog_mod.open_catalog().set_source_visibility("archive", "maintainers")
        ordinary = await (await client.get(
            f"{API}/radar/explorer?source=archive", cookies=user)).json()
        elevated = await (await client.get(
            f"{API}/radar/explorer?source=archive", cookies=maint)).json()
        bad_cursor = await client.get(
            f"{API}/radar/explorer?source=archive&cursor=not-a-cursor", cookies=user)
        return ordinary, elevated, bad_cursor.status

    ordinary, elevated, bad_cursor = _run(web_env, script)
    assert ordinary["total"] == 0 and ordinary["items"] == []
    assert ordinary["features"]["features"] == []
    assert ordinary["facets"]["source"] == []
    assert elevated["total"] == 4
    assert bad_cursor == 400


def test_registry_keys_cannot_claim_the_catalog_prefix(tmp_path):
    from icesee_jupyter_book.applications.frozen_legacies.radar.sources import parse_sources

    write_tiff(tmp_path / "F1-C1_C2.tiff")
    parsed = parse_sources({"sources": [
        {"key": "cat-" + "0" * 24, "tiff": "F1-C1_C2.tiff"},
        {"key": "ok", "tiff": "F1-C1_C2.tiff"}]}, base=tmp_path)
    assert list(parsed) == ["ok"]
