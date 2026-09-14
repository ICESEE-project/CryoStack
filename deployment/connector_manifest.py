#!/usr/bin/env python3
# =============================================================================
# CryoStack Connector — authoritative manifest / checksum generation + verify.
#
# Deployment is the source of truth: manifest.json and SHA256SUMS are always
# (re)generated from the exact set of canonical artifacts actually present in
# dist/packages/, never carried over from a single build host.
#
#   python3 deployment/connector_manifest.py generate <pkg_dir>
#   python3 deployment/connector_manifest.py verify   <dir>
#   python3 deployment/connector_manifest.py check-perms <dir>
# =============================================================================
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_NAME = "manifest.json"
CHECKSUMS_NAME = "SHA256SUMS"
MANIFEST_SCHEMA = "cryostack.connector.manifest"
MANIFEST_VERSION = 1

#: the only artifact filenames CryoStack publishes, one per supported platform.
SUPPORTED_ARTIFACTS: dict[str, str] = {
    "linux-x86_64": "CryoStack-Connector-linux-x86_64.tar.gz",
    "macos-arm64": "CryoStack-Connector-macos-arm64.dmg",
    "macos-x86_64": "CryoStack-Connector-macos-x86_64.dmg",
    "windows-x86_64": "CryoStack-Connector-windows-x86_64.exe",
}
_FILENAME_TO_PLATFORM = {v: k for k, v in SUPPORTED_ARTIFACTS.items()}

# Non-artifact files that legitimately live in the connectors directory.
_ALLOWED_EXTRA = {MANIFEST_NAME, CHECKSUMS_NAME}


class ManifestError(RuntimeError):
    """The connector artifact set / manifest is missing or inconsistent."""


# ── helpers ───────────────────────────────────────────────────────────────
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sidecar_dict(artifact: Path) -> dict:
    """Parsed ``<artifact>.build.json`` sidecar, or ``{}``."""
    sidecar = artifact.with_name(artifact.name + ".build.json")
    if sidecar.is_file():
        try:
            data = json.loads(sidecar.read_text())
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
    return {}


def _built_at(artifact: Path) -> str:
    """Build timestamp: a ``<artifact>.build.json`` sidecar written by
    build_connector.sh is authoritative (survives copying between hosts);
    otherwise fall back to the file's modification time. Never fabricated."""
    value = sidecar_dict(artifact).get("built_at")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _iso_utc(artifact.stat().st_mtime)


def discover_artifacts(pkg_dir: str | Path) -> dict[str, Path]:
    """Canonical, non-empty artifacts present in ``pkg_dir``, keyed by platform.
    Anything that is not a canonical name, or is zero bytes, is ignored."""
    pkg_dir = Path(pkg_dir)
    found: dict[str, Path] = {}
    for platform, filename in SUPPORTED_ARTIFACTS.items():
        candidate = pkg_dir / filename
        if candidate.is_file() and candidate.stat().st_size > 0:
            found[platform] = candidate
    return found


# ── generate ─────────────────────────────────────────────────────────────
def build_manifest(pkg_dir: str | Path) -> dict:
    artifacts = discover_artifacts(pkg_dir)
    if not artifacts:
        raise ManifestError(
            f"no canonical CryoStack-Connector artifacts in {pkg_dir}")
    entries = {}
    for platform, path in sorted(artifacts.items()):
        entry = {
            "filename": path.name,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "built_at": _built_at(path),
        }
        # Carry build provenance through to the public manifest so /connect/
        # can flag an outdated connector (pre-ea0a70d pairing protocol).
        side = sidecar_dict(path)
        for extra in ("pairing_protocol", "connector_build_revision"):
            value = side.get(extra)
            if isinstance(value, str) and value.strip():
                entry[extra] = value.strip()
        entries[platform] = entry
    return {
        "schema": MANIFEST_SCHEMA,
        "version": MANIFEST_VERSION,
        "generated_at": _iso_utc(datetime.now(tz=timezone.utc).timestamp()),
        "artifacts": entries,
    }


def sha256sums_text(pkg_dir: str | Path) -> str:
    artifacts = discover_artifacts(pkg_dir)
    lines = sorted(
        f"{sha256_file(p)}  {p.name}" for p in artifacts.values())
    return "\n".join(lines) + ("\n" if lines else "")


def generate(pkg_dir: str | Path) -> dict:
    """Regenerate manifest.json + SHA256SUMS in ``pkg_dir`` from the artifact
    set actually present. Overwrites any stale files. Returns the manifest."""
    pkg_dir = Path(pkg_dir)
    manifest = build_manifest(pkg_dir)          # raises if empty
    (pkg_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (pkg_dir / CHECKSUMS_NAME).write_text(sha256sums_text(pkg_dir))
    return manifest


# ── verify ───────────────────────────────────────────────────────────────
def _parse_sha256sums(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, name = line.partition("  ")
        if not name:
            digest, _, name = line.partition(" ")
        out[name.strip().lstrip("*")] = digest.strip()
    return out


def verify(target_dir: str | Path) -> dict:
    """Validate that manifest.json, SHA256SUMS and the artifacts in
    ``target_dir`` all agree. Raises :class:`ManifestError` on any problem."""
    target_dir = Path(target_dir)
    manifest_path = target_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ManifestError(f"{MANIFEST_NAME} missing in {target_dir}")
    try:
        manifest = json.loads(manifest_path.read_text())
    except ValueError as err:
        raise ManifestError(f"{MANIFEST_NAME} is not valid JSON: {err}") from err

    entries = manifest.get("artifacts") or {}
    if not entries:
        raise ManifestError("manifest has no artifacts")

    sums = {}
    sums_path = target_dir / CHECKSUMS_NAME
    if sums_path.is_file():
        sums = _parse_sha256sums(sums_path.read_text())

    problems: list[str] = []

    # every manifest entry -> a real, non-empty, matching file
    for platform, entry in entries.items():
        if platform not in SUPPORTED_ARTIFACTS:
            problems.append(f"{platform}: not a supported platform")
            continue
        filename = entry.get("filename", "")
        if filename != SUPPORTED_ARTIFACTS[platform]:
            problems.append(f"{platform}: non-canonical filename {filename!r}")
        for field in ("filename", "sha256", "size_bytes", "built_at"):
            if not entry.get(field) and entry.get(field) != 0:
                problems.append(f"{platform}: manifest entry missing {field!r}")
        path = target_dir / filename
        if not path.is_file():
            problems.append(f"{platform}: file {filename} is not present")
            continue
        size = path.stat().st_size
        if size == 0:
            problems.append(f"{platform}: {filename} is zero bytes")
            continue
        if entry.get("size_bytes") != size:
            problems.append(
                f"{platform}: size {entry.get('size_bytes')} != actual {size}")
        actual = sha256_file(path)
        if entry.get("sha256") != actual:
            problems.append(f"{platform}: manifest sha256 mismatch for {filename}")
        if sums and sums.get(filename) not in (None, actual):
            problems.append(f"{platform}: SHA256SUMS mismatch for {filename}")
        if sums and filename not in sums:
            problems.append(f"{platform}: {filename} missing from {CHECKSUMS_NAME}")

    # every real canonical artifact -> a manifest entry
    for platform, path in discover_artifacts(target_dir).items():
        if platform not in entries:
            problems.append(
                f"{platform}: {path.name} present but absent from the manifest")

    if problems:
        raise ManifestError("manifest verification failed:\n  - "
                            + "\n  - ".join(problems))
    return manifest


# ── permissions ──────────────────────────────────────────────────────────
def permission_problems(target_dir: str | Path) -> list[str]:
    """Return reasons the deployed tree would not be readable by a static
    web server (nginx). Empty list == fine."""
    target_dir = Path(target_dir)
    problems: list[str] = []
    if not target_dir.is_dir():
        return [f"{target_dir} is not a directory"]

    for root, dirs, files in os.walk(target_dir):
        rmode = stat.S_IMODE(os.stat(root).st_mode)
        if not (rmode & 0o001) or not (rmode & 0o004):
            problems.append(f"dir  {root}  mode {oct(rmode)} (need o+rx)")
        for name in files:
            p = os.path.join(root, name)
            fmode = stat.S_IMODE(os.stat(p).st_mode)
            if not (fmode & 0o004):
                problems.append(f"file {p}  mode {oct(fmode)} (need o+r)")
    return problems


def enforce_permissions(target_dir: str | Path) -> None:
    """dirs -> 0755, files -> 0644, recursively."""
    target_dir = Path(target_dir)
    os.chmod(target_dir, 0o755)
    for root, dirs, files in os.walk(target_dir):
        for d in dirs:
            os.chmod(os.path.join(root, d), 0o755)
        for f in files:
            os.chmod(os.path.join(root, f), 0o644)


# ── CLI ──────────────────────────────────────────────────────────────────
def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    cmd, path = argv[0], argv[1]
    try:
        if cmd == "generate":
            m = generate(path)
            n = len(m["artifacts"])
            print(f"[manifest] wrote {MANIFEST_NAME} + {CHECKSUMS_NAME} "
                  f"({n} platform{'s' if n != 1 else ''}: "
                  f"{', '.join(sorted(m['artifacts']))})")
            return 0
        if cmd == "verify":
            m = verify(path)
            print(f"[manifest] OK — {', '.join(sorted(m['artifacts']))}")
            return 0
        if cmd == "check-perms":
            probs = permission_problems(path)
            if probs:
                print("[perms] NOT web-readable:\n  - " + "\n  - ".join(probs),
                      file=sys.stderr)
                return 1
            print("[perms] OK — every file o+r, every dir o+rx")
            return 0
    except ManifestError as err:
        print(f"[manifest] ERROR: {err}", file=sys.stderr)
        return 1
    print(f"[manifest] unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
