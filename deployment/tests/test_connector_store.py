"""Phase A: canonical connector artifact store + release engine.

Publishing one platform never disturbs another; a candidate that fails
validation never reaches the served directory; removal is explicit only.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_DEPLOYMENT = Path(__file__).resolve().parents[1]
if str(_DEPLOYMENT) not in sys.path:
    sys.path.insert(0, str(_DEPLOYMENT))

import connector_manifest as cm
import connector_store as cs

LINUX = "CryoStack-Connector-linux-x86_64.tar.gz"
MAC_ARM = "CryoStack-Connector-macos-arm64.dmg"
MAC_X86 = "CryoStack-Connector-macos-x86_64.dmg"
WIN = "CryoStack-Connector-windows-x86_64.exe"

import hashlib


def _make_build(tmp: Path, filename: str, content: bytes, *, protocol="v2", rev="abc123def456") -> tuple[Path, Path]:
    art = tmp / filename
    art.write_bytes(content)
    platform = cm._FILENAME_TO_PLATFORM[filename]
    meta = {
        "platform": platform,
        "filename": filename,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "built_at": "2026-09-01T12:00:00Z",
        "pairing_protocol": protocol,
        "connector_build_revision": rev,
    }
    side = tmp / (filename + ".build.json")
    side.write_text(json.dumps(meta))
    return art, side


@pytest.fixture
def store(tmp_path):
    return tmp_path / "store"


@pytest.fixture
def build_dir(tmp_path):
    d = tmp_path / "dist"
    d.mkdir()
    return d


# ── A8: publish Linux, then macOS -> manifest has both ───────────────────
def test_publish_linux_then_macos_keeps_both(store, build_dir, tmp_path):
    a, b = _make_build(build_dir, LINUX, b"linux-payload-1")
    cs.register(store, a, b)
    assert set(cs.list_registered(store)) == {"linux-x86_64"}

    a, b = _make_build(build_dir, MAC_ARM, b"macos-payload-1")
    cs.register(store, a, b)
    assert set(cs.list_registered(store)) == {"linux-x86_64", "macos-arm64"}

    manifest = cs.build_candidate(store, tmp_path / "cand")
    assert set(manifest["artifacts"]) == {"linux-x86_64", "macos-arm64"}


# ── replacement macOS -> Linux untouched, macOS metadata changes ─────────
def test_replacement_macos_leaves_linux_untouched(store, build_dir):
    la, lb = _make_build(build_dir, LINUX, b"linux-payload")
    cs.register(store, la, lb)
    linux_before = cs.list_registered(store)["linux-x86_64"]

    ma, mb = _make_build(build_dir, MAC_ARM, b"macos-v1", rev="rev-one-000000")
    cs.register(store, ma, mb)

    build2 = build_dir.parent / "dist2"
    build2.mkdir()
    ma2, mb2 = _make_build(build2, MAC_ARM, b"macos-v2-different", rev="rev-two-000000")
    cs.register(store, ma2, mb2)

    reg = cs.list_registered(store)
    assert reg["linux-x86_64"] == linux_before                     # byte-identical entry
    assert reg["macos-arm64"]["connector_build_revision"] == "rev-two-000000"
    assert reg["macos-arm64"]["sha256"] == hashlib.sha256(b"macos-v2-different").hexdigest()


# ── failed new macOS validation -> existing good macOS remains ───────────
def test_failed_macos_registration_leaves_prior_macos_intact(store, build_dir):
    ma, mb = _make_build(build_dir, MAC_ARM, b"good-macos", rev="good-rev-0000")
    cs.register(store, ma, mb)
    good_sha = cs.list_registered(store)["macos-arm64"]["sha256"]

    # tampered: sidecar sha does not match the file
    bad_dir = build_dir.parent / "bad"
    bad_dir.mkdir()
    bart = bad_dir / MAC_ARM
    bart.write_bytes(b"corrupt-macos")
    bside = bad_dir / (MAC_ARM + ".build.json")
    bside.write_text(json.dumps({
        "platform": "macos-arm64", "filename": MAC_ARM,
        "sha256": "0" * 64, "size_bytes": len(b"corrupt-macos"),
        "built_at": "2026-09-01T13:00:00Z",
        "pairing_protocol": "v2", "connector_build_revision": "bad-rev-00000",
    }))
    with pytest.raises(cs.StoreError):
        cs.register(store, bart, bside)

    assert cs.list_registered(store)["macos-arm64"]["sha256"] == good_sha


# ── zero-byte / non-canonical / missing metadata rejected ────────────────
def test_bad_inputs_are_rejected(store, build_dir):
    (build_dir / LINUX).write_bytes(b"")
    (build_dir / (LINUX + ".build.json")).write_text(json.dumps({
        "platform": "linux-x86_64", "filename": LINUX, "sha256": hashlib.sha256(b"").hexdigest(),
        "size_bytes": 0, "built_at": "x", "pairing_protocol": "v2", "connector_build_revision": "r",
    }))
    with pytest.raises(cs.StoreError):
        cs.register(store, build_dir / LINUX)

    weird = build_dir / "CryoStack-Connector-linux-arm64.tar.gz"
    weird.write_bytes(b"data")
    with pytest.raises(cs.StoreError):
        cs.register(store, weird)

    a, _ = _make_build(build_dir, WIN, b"win-payload")
    (build_dir / (WIN + ".build.json")).unlink()
    with pytest.raises(cs.StoreError):
        cs.register(store, a)


# ── A3: an outdated pairing protocol is refused ─────────────────────────
def test_old_pairing_protocol_is_refused(store, build_dir):
    a, b = _make_build(build_dir, LINUX, b"old-connector", protocol="v1")
    with pytest.raises(cs.StoreError):
        cs.register(store, a, b)
    # deliberate override works
    cs.register(store, a, b, allow_protocol_mismatch=True)
    assert set(cs.list_registered(store)) == {"linux-x86_64"}


# ── publish Windows -> all three ────────────────────────────────────────
def test_publish_windows_makes_three(store, build_dir, tmp_path):
    for name, payload in ((LINUX, b"l"), (MAC_ARM, b"m"), (WIN, b"w")):
        a, b = _make_build(build_dir, name, payload + b"-payload-data")
        cs.register(store, a, b)
    m = cs.build_candidate(store, tmp_path / "cand")
    assert set(m["artifacts"]) == {"linux-x86_64", "macos-arm64", "windows-x86_64"}
    for entry in m["artifacts"].values():
        assert entry["pairing_protocol"] == "v2"
        assert entry["connector_build_revision"]


# ── explicit unpublish only ────────────────────────────────────────────
def test_unpublish_is_the_only_removal(store, build_dir, tmp_path):
    for name in (LINUX, MAC_ARM, WIN):
        a, b = _make_build(build_dir, name, name.encode() + b"-data")
        cs.register(store, a, b)

    assert cs.unpublish(store, "linux-x86_64") is True
    assert set(cs.list_registered(store)) == {"macos-arm64", "windows-x86_64"}
    assert cs.unpublish(store, "linux-x86_64") is False  # already gone

    m = cs.build_candidate(store, tmp_path / "cand")
    assert set(m["artifacts"]) == {"macos-arm64", "windows-x86_64"}


# ── promote: candidate failure leaves the live tree untouched ───────────
def test_promote_failure_leaves_served_untouched(store, build_dir, tmp_path):
    a, b = _make_build(build_dir, LINUX, b"linux-live-payload")
    cs.register(store, a, b)
    served = tmp_path / "served"
    cs.release(store, served)
    live_manifest = (served / "manifest.json").read_text()
    live_tar = (served / LINUX).read_bytes()

    # a corrupt candidate must never overwrite the good served tree
    bad_cand = tmp_path / "bad_cand"
    bad_cand.mkdir()
    (bad_cand / LINUX).write_bytes(b"corrupt")
    (bad_cand / "manifest.json").write_text(json.dumps({
        "schema": cm.MANIFEST_SCHEMA, "version": 1,
        "artifacts": {"linux-x86_64": {"filename": LINUX, "sha256": "0" * 64,
                                       "size_bytes": 7, "built_at": "x"}},
    }))
    (bad_cand / "SHA256SUMS").write_text(f"{'0'*64}  {LINUX}\n")
    with pytest.raises(cm.ManifestError):
        cs.promote(bad_cand, served)

    assert (served / "manifest.json").read_text() == live_manifest
    assert (served / LINUX).read_bytes() == live_tar


# ── release is idempotent ──────────────────────────────────────────────
def test_release_is_idempotent(store, build_dir, tmp_path):
    a, b = _make_build(build_dir, LINUX, b"linux-idem")
    cs.register(store, a, b)
    served = tmp_path / "served"
    m1 = cs.release(store, served)
    files1 = sorted(p.name for p in served.iterdir())
    m2 = cs.release(store, served)
    files2 = sorted(p.name for p in served.iterdir())
    assert m1["artifacts"] == m2["artifacts"]
    assert files1 == files2
    cm.verify(served)


# ── partial platform dir in the store is ignored, not published ─────────
def test_partial_store_entry_is_not_released(store, build_dir, tmp_path):
    a, b = _make_build(build_dir, LINUX, b"good-linux")
    cs.register(store, a, b)
    # simulate an interrupted macOS import: artifact present, no sidecar
    (store / "macos-arm64").mkdir(parents=True)
    (store / "macos-arm64" / MAC_ARM).write_bytes(b"half-written")

    assert set(cs.list_registered(store)) == {"linux-x86_64"}
    m = cs.build_candidate(store, tmp_path / "cand")
    assert set(m["artifacts"]) == {"linux-x86_64"}


# ── promote re-enforces permissions on the live tree ───────────────────
def test_promote_enforces_perms_and_clears_prior_junk(store, build_dir, tmp_path):
    a, b = _make_build(build_dir, LINUX, b"linux-perm-test")
    cs.register(store, a, b)
    served = tmp_path / "served"

    # a messy prior deployment: wrong modes + a stray file
    served.mkdir()
    junk = served / "leftover-from-old-deploy.txt"
    junk.write_text("stale")
    os.chmod(junk, 0o600)
    (served / "manifest.json").write_text("{}")
    os.chmod(served / "manifest.json", 0o640)
    os.chmod(served, 0o770)

    cs.release(store, served)

    assert not junk.exists()                                  # full replace
    assert (os.stat(served).st_mode & 0o777) == 0o755
    for f in served.iterdir():
        assert (os.stat(f).st_mode & 0o777) == 0o644
    cm.verify(served)


def test_promote_clears_stale_release_scratch_dirs(store, build_dir, tmp_path):
    a, b = _make_build(build_dir, LINUX, b"linux-scratch")
    cs.register(store, a, b)
    served = tmp_path / "served"
    cs.release(store, served)

    # interrupted release leftovers
    (served.with_name(served.name + ".release-new")).mkdir()
    (served.with_name(served.name + ".release-new") / "half").write_text("x")
    (served.with_name(served.name + ".release-old")).mkdir()

    cs.release(store, served)
    assert not (served.with_name(served.name + ".release-new")).exists()
    assert not (served.with_name(served.name + ".release-old")).exists()
    cm.verify(served)


def test_multi_platform_promotion_serves_every_registered_platform(store, build_dir, tmp_path):
    for name, payload in ((LINUX, b"l-data"), (MAC_ARM, b"m-data"), (WIN, b"w-data")):
        a, b = _make_build(build_dir, name, payload)
        cs.register(store, a, b)
    served = tmp_path / "served"
    cs.release(store, served)
    served_files = {p.name for p in served.iterdir()}
    assert served_files == {LINUX, MAC_ARM, WIN, "manifest.json", "SHA256SUMS"}
    assert set(cm.verify(served)["artifacts"]) == {"linux-x86_64", "macos-arm64", "windows-x86_64"}


# ── SHA256SUMS and manifest agree in a real candidate ──────────────────
def test_candidate_checksums_and_manifest_agree(store, build_dir, tmp_path):
    for name, payload in ((LINUX, b"linux-xyz"), (MAC_ARM, b"macos-xyz")):
        a, b = _make_build(build_dir, name, payload)
        cs.register(store, a, b)
    cand = tmp_path / "cand"
    cs.build_candidate(store, cand)
    sums = cm._parse_sha256sums((cand / "SHA256SUMS").read_text())
    manifest = json.loads((cand / "manifest.json").read_text())["artifacts"]
    for plat, entry in manifest.items():
        fn = entry["filename"]
        assert sums[fn] == entry["sha256"] == cm.sha256_file(cand / fn)
