"""Phase-2 follow-up: connector manifest / checksum / permission logic.

Deployment is the authoritative manifest step -- manifest.json + SHA256SUMS are
regenerated from exactly the canonical artifacts present, never carried over
from one build host.
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

LINUX = "CryoStack-Connector-linux-x86_64.tar.gz"
MAC_ARM = "CryoStack-Connector-macos-arm64.dmg"
WIN = "CryoStack-Connector-windows-x86_64.exe"


def _artifact(d: Path, name: str, content: bytes = b"binary-payload") -> Path:
    p = d / name
    p.write_bytes(content)
    return p


# ── discovery + generate ────────────────────────────────────────────────
def test_manifest_has_linux_only(tmp_path):
    _artifact(tmp_path, LINUX)
    m = cm.generate(tmp_path)
    assert set(m["artifacts"]) == {"linux-x86_64"}
    assert m["artifacts"]["linux-x86_64"]["filename"] == LINUX


def test_manifest_has_exactly_linux_and_macos(tmp_path):
    _artifact(tmp_path, LINUX)
    _artifact(tmp_path, MAC_ARM)
    m = cm.generate(tmp_path)
    assert set(m["artifacts"]) == {"linux-x86_64", "macos-arm64"}


def test_manifest_has_exactly_three_platforms(tmp_path):
    for n in (LINUX, MAC_ARM, WIN):
        _artifact(tmp_path, n)
    m = cm.generate(tmp_path)
    assert set(m["artifacts"]) == {"linux-x86_64", "macos-arm64", "windows-x86_64"}
    for entry in m["artifacts"].values():
        assert entry["size_bytes"] > 0
        assert len(entry["sha256"]) == 64
        assert entry["built_at"].endswith("Z")


def test_no_artifacts_is_an_error(tmp_path):
    with pytest.raises(cm.ManifestError):
        cm.generate(tmp_path)


def test_non_canonical_and_zero_byte_files_are_ignored(tmp_path):
    _artifact(tmp_path, LINUX)
    _artifact(tmp_path, "CryoStack-Connector-linux-arm64.tar.gz")   # not canonical
    (tmp_path / MAC_ARM).write_bytes(b"")                           # zero bytes
    m = cm.generate(tmp_path)
    assert set(m["artifacts"]) == {"linux-x86_64"}


# ── checksums agree ────────────────────────────────────────────────────
def test_sha256sums_and_manifest_hashes_agree(tmp_path):
    a = _artifact(tmp_path, LINUX, b"one")
    b = _artifact(tmp_path, MAC_ARM, b"two")
    cm.generate(tmp_path)

    sums = cm._parse_sha256sums((tmp_path / "SHA256SUMS").read_text())
    manifest = json.loads((tmp_path / "manifest.json").read_text())["artifacts"]

    for path, plat in ((a, "linux-x86_64"), (b, "macos-arm64")):
        digest = cm.sha256_file(path)
        assert sums[path.name] == digest
        assert manifest[plat]["sha256"] == digest

    cm.verify(tmp_path)                       # no raise


def test_verify_rejects_a_tampered_artifact(tmp_path):
    _artifact(tmp_path, LINUX, b"original")
    cm.generate(tmp_path)
    (tmp_path / LINUX).write_bytes(b"tampered-different-length")
    with pytest.raises(cm.ManifestError):
        cm.verify(tmp_path)


def test_verify_rejects_zero_byte_and_missing(tmp_path):
    _artifact(tmp_path, LINUX)
    cm.generate(tmp_path)
    (tmp_path / LINUX).write_bytes(b"")
    with pytest.raises(cm.ManifestError):
        cm.verify(tmp_path)

    (tmp_path / LINUX).unlink()
    with pytest.raises(cm.ManifestError):
        cm.verify(tmp_path)


def test_verify_flags_a_present_artifact_missing_from_the_manifest(tmp_path):
    _artifact(tmp_path, LINUX)
    cm.generate(tmp_path)
    _artifact(tmp_path, MAC_ARM)              # added after manifest was written
    with pytest.raises(cm.ManifestError):
        cm.verify(tmp_path)


# ── stale manifest is replaced ─────────────────────────────────────────
def test_stale_preexisting_manifest_is_fully_replaced(tmp_path):
    # a leftover manifest from a Linux-only build host
    (tmp_path / "manifest.json").write_text(json.dumps({
        "schema": cm.MANIFEST_SCHEMA, "version": 1,
        "artifacts": {"linux-x86_64": {
            "filename": LINUX, "sha256": "0" * 64,
            "size_bytes": 999, "built_at": "2000-01-01T00:00:00Z"}},
    }))
    (tmp_path / "SHA256SUMS").write_text(f"{'0'*64}  {LINUX}\n")

    # now Linux + macOS are actually present
    _artifact(tmp_path, LINUX, b"real-linux")
    _artifact(tmp_path, MAC_ARM, b"real-macos")

    m = cm.generate(tmp_path)
    assert set(m["artifacts"]) == {"linux-x86_64", "macos-arm64"}
    assert m["artifacts"]["linux-x86_64"]["sha256"] == cm.sha256_file(tmp_path / LINUX)
    assert m["artifacts"]["linux-x86_64"]["size_bytes"] == len(b"real-linux")
    cm.verify(tmp_path)


# ── build_at: sidecar authoritative, mtime fallback ───────────────────
def test_built_at_prefers_sidecar_then_falls_back_to_mtime(tmp_path):
    p = _artifact(tmp_path, LINUX)
    (tmp_path / (LINUX + ".build.json")).write_text(
        json.dumps({"built_at": "2026-08-30T12:00:00Z"}))
    m = cm.generate(tmp_path)
    assert m["artifacts"]["linux-x86_64"]["built_at"] == "2026-08-30T12:00:00Z"

    (tmp_path / (LINUX + ".build.json")).unlink()
    os.utime(p, (1_700_000_000, 1_700_000_000))
    m2 = cm.generate(tmp_path)
    assert m2["artifacts"]["linux-x86_64"]["built_at"] == cm._iso_utc(1_700_000_000)


# ── deployed permissions suitable for nginx ──────────────────────────
def test_permission_problems_and_enforce(tmp_path):
    d = tmp_path / "connectors"
    d.mkdir()
    _artifact(d, LINUX)
    cm.generate(d)

    os.chmod(d / LINUX, 0o640)               # the failure mode from the bug report
    os.chmod(d, 0o750)
    probs = cm.permission_problems(d)
    assert any(LINUX in p for p in probs)
    assert any("dir" in p for p in probs)

    cm.enforce_permissions(d)
    assert cm.permission_problems(d) == []
    assert (os.stat(d / LINUX).st_mode & 0o777) == 0o644
    assert (os.stat(d).st_mode & 0o777) == 0o755


# ── CLI ───────────────────────────────────────────────────────────────
def test_cli_generate_verify_checkperms(tmp_path, capsys):
    d = tmp_path / "connectors"
    d.mkdir()
    _artifact(d, LINUX)
    assert cm._main(["generate", str(d)]) == 0
    assert cm._main(["verify", str(d)]) == 0
    cm.enforce_permissions(d)                 # what the deploy script does
    assert cm._main(["check-perms", str(d)]) == 0
    assert cm._main(["verify", str(tmp_path / "nope")]) == 1
