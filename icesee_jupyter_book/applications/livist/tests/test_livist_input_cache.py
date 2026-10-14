"""The shared source.coop input cache: verified reuse, provenance, bounds,
and the worker staging a cached input so LIVIST does not download it again."""
import json
import os

import pytest

from icesee_jupyter_book.applications.livist import input_cache, manifest, worker
from icesee_jupyter_book.applications.livist.store import LivistStore

from livist_test_support import fake_popen, use_ready_toolchain

KEY = "englacial/ice-sheet-temperature/AttenuationRateData/depth-avg-attenuation-ASE.txt"


def _cache(tmp_path, head=None, limit=None):
    return input_cache.InputCache(tmp_path / "cache", head=head or (lambda url: None),
                                  limit_bytes=limit)


def _file(tmp_path, name="download.txt", text="x,y\n1,2\n"):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_store_then_stage_is_a_verified_hit(tmp_path):
    meta = {"size": 8, "etag": '"e1"', "last_modified": "Mon"}
    cache = _cache(tmp_path, head=lambda url: meta)
    source = _file(tmp_path)
    stored = cache.store(KEY, source)
    assert stored["cache"] == "stored" and stored["sha256"] == input_cache.sha256_file(source)
    entry = cache.entries()[KEY]
    assert entry["url"] == f"https://data.source.coop/{KEY}" and entry["etag"] == '"e1"'
    blob = tmp_path / "cache" / "blobs" / entry["sha256"]
    assert oct(blob.stat().st_mode & 0o777) == "0o444"

    target = tmp_path / "job" / "data" / KEY
    result = cache.stage(KEY, target)
    assert result == {"cache": "hit", "sha256": entry["sha256"], "size": 8, "upstream_checked": True,
                      "upstream": {"size": 8, "etag": '"e1"', "last_modified": "Mon",
                                   "answered": True}}
    assert target.read_bytes() == source.read_bytes()


def test_changed_upstream_object_is_not_used(tmp_path):
    meta = {"size": 8, "etag": '"e1"'}
    cache = _cache(tmp_path, head=lambda url: meta)
    cache.store(KEY, _file(tmp_path))
    meta["etag"] = '"e2"'                                # replaced on source.coop
    target = tmp_path / "job" / KEY
    assert cache.stage(KEY, target)["cache"] == "stale" and not target.exists()


def test_unreachable_upstream_uses_the_verified_copy_and_says_so(tmp_path):
    cache = _cache(tmp_path)
    cache.store(KEY, _file(tmp_path))
    result = cache.stage(KEY, tmp_path / "job" / KEY)
    assert result["cache"] == "hit" and result["upstream_checked"] is False


def test_a_corrupted_copy_is_dropped(tmp_path):
    cache = _cache(tmp_path)
    cache.store(KEY, _file(tmp_path))
    blob = tmp_path / "cache" / "blobs" / cache.entries()[KEY]["sha256"]
    os.chmod(blob, 0o644)
    blob.write_text("tampered")
    target = tmp_path / "job" / KEY
    assert cache.stage(KEY, target)["cache"] == "corrupt" and not target.exists()
    assert KEY not in cache.entries() and not blob.exists()


def test_size_mismatch_with_upstream_is_not_stored(tmp_path):
    cache = _cache(tmp_path, head=lambda url: {"size": 999})
    assert cache.store(KEY, _file(tmp_path))["cache"] == "not-stored"
    assert cache.entries() == {}


def test_bounded_least_recently_used(tmp_path):
    cache = _cache(tmp_path, limit=20)
    other = KEY.replace("ASE", "WAIS")
    cache.store(KEY, _file(tmp_path, "a", "a" * 12))
    cache.store(other, _file(tmp_path, "b", "b" * 12))     # 24 > 20: the older one goes
    assert set(cache.entries()) == {other}
    assert len(list((tmp_path / "cache" / "blobs").iterdir())) == 1
    assert cache.store(KEY, _file(tmp_path, "c", "c" * 30))["cache"] == "not-stored"


def test_only_approved_source_coop_keys(tmp_path):
    from icesee_jupyter_book.applications.livist.sources import SourceError
    with pytest.raises(SourceError):
        _cache(tmp_path).store("../../etc/passwd", _file(tmp_path))


def test_second_job_reuses_the_cached_input_instead_of_downloading(tmp_path, monkeypatch):
    use_ready_toolchain(monkeypatch)
    store = LivistStore(tmp_path / "livist.db")
    cache = _cache(tmp_path)
    row = {"name": "ase", "kind": "source-coop", "location": KEY}
    workdirs = []
    for job_id in ("a" * 32, "b" * 32):
        workdir = tmp_path / "ws" / job_id
        workdir.mkdir(parents=True)
        store.queue_job(job_id=job_id, owner_id="u1", workdir=str(workdir), sources=[row],
                        timeout_s=600, max_active=4)
        assert worker.run(store, job_id, popen=fake_popen(), cache=cache) == "completed"
        workdirs.append(workdir)

    first, second = (manifest.read(w)["inputs"][0] for w in workdirs)
    assert first["cache"] == {"cache": "stored"}
    assert second["cache"] == {"cache": "hit", "upstream_checked": False}
    assert first["sha256"] == second["sha256"] and len(first["sha256"]) == 64
    used = manifest.read(workdirs[1])["resources"]
    assert used["measured"] is True and used["wall_s"] >= 0 and used["peak_rss_mb"] > 0
    assert used["workdir_bytes"] > 0
    first_log = (workdirs[0] / "logs" / "generate.log").read_text()
    second_log = (workdirs[1] / "logs" / "generate.log").read_text()
    assert "input ase: download" in first_log
    assert "input ase: present" in second_log and "shared cache hit" in second_log
    # the job directories keep checksums only, never the 339 MB input
    assert not any((w / "data" / KEY).exists() for w in workdirs)
    assert json.loads((tmp_path / "cache" / "index.json").read_text())[KEY]["size"] > 0


def test_failed_job_does_not_populate_the_cache(tmp_path, monkeypatch):
    use_ready_toolchain(monkeypatch)
    store = LivistStore(tmp_path / "livist.db")
    cache = _cache(tmp_path)
    workdir = tmp_path / "ws" / ("c" * 32)
    workdir.mkdir(parents=True)
    (workdir / "fail").write_text("1")
    store.queue_job(job_id="c" * 32, owner_id="u1", workdir=str(workdir),
                    sources=[{"name": "ase", "kind": "source-coop", "location": KEY}],
                    timeout_s=600, max_active=4)
    assert worker.run(store, "c" * 32, popen=fake_popen(), cache=cache) == "failed"
    assert cache.entries() == {}
