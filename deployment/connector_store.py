#!/usr/bin/env python3
# =============================================================================
# CryoStack Connector -- canonical artifact store + release engine.
#
# Three distinct concepts, deliberately separated:
#
#   native build output           dist/packages/<file> (+ .build.json) on the
#                                 machine that can build that platform
#           |  register
#           v
#   canonical artifact store      <store>/<platform>/<file> (+ .build.json)
#                                 persistent, OUTSIDE the web root, one
#                                 subdirectory per platform so registering one
#                                 platform can never touch another
#           |  build-candidate  ->  candidate/ (artifacts + manifest.json + SHA256SUMS)
#           |  promote
#           v
#   served release                <web-root>/downloads/connectors/
#                                 deployment target ONLY -- never the source of truth
#
# An artifact leaves the store only through an explicit `unpublish`. Normal
# `release` preserves every registered platform. A candidate that fails
# validation never reaches the served directory.
#
#   python3 deployment/connector_store.py register <artifact> [<build.json>] [--store DIR]
#   python3 deployment/connector_store.py unpublish <platform>               [--store DIR]
#   python3 deployment/connector_store.py list                               [--store DIR]
#   python3 deployment/connector_store.py build-candidate <candidate_dir>    [--store DIR]
#   python3 deployment/connector_store.py promote <candidate_dir> <served_dir>
#   python3 deployment/connector_store.py release <served_dir>               [--store DIR]
# =============================================================================
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import connector_manifest as cm

#: canonical pairing protocol this release line expects (mirrors
#: icesee_hpc_connector.connector_core.PAIRING_PROTOCOL)
EXPECTED_PAIRING_PROTOCOL = "v2"

#: env var pointing at the persistent store (outside the web root)
STORE_ENV = "CRYOSTACK_CONNECTOR_STORE"
DEFAULT_STORE = Path.home() / ".cryostack" / "connector-artifacts"

#: keys every registered artifact's .build.json must carry
REQUIRED_BUILD_KEYS = (
    "platform", "filename", "sha256", "size_bytes",
    "built_at", "pairing_protocol", "connector_build_revision",
)


class StoreError(RuntimeError):
    """The artifact store or a release candidate is inconsistent."""


# ── store location ───────────────────────────────────────────────────────
def store_root(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = (os.environ.get(STORE_ENV) or "").strip()
    return (Path(env).expanduser() if env else DEFAULT_STORE).resolve()


def _platform_dir(store: Path, platform: str) -> Path:
    return store / platform


# ── register ─────────────────────────────────────────────────────────────
def _load_build_json(artifact: Path, build_json: Path | None) -> dict:
    path = build_json or artifact.with_name(artifact.name + ".build.json")
    if not Path(path).is_file():
        raise StoreError(f"missing build metadata sidecar: {path}")
    try:
        data = json.loads(Path(path).read_text())
    except ValueError as err:
        raise StoreError(f"{path} is not valid JSON: {err}") from err
    if not isinstance(data, dict):
        raise StoreError(f"{path} must be a JSON object")
    return data


def _validate_incoming(artifact: Path, meta: dict, *, allow_protocol_mismatch: bool) -> str:
    """Validate one incoming artifact + its metadata. Returns the platform key."""
    if not artifact.is_file():
        raise StoreError(f"artifact not found: {artifact}")
    size = artifact.stat().st_size
    if size == 0:
        raise StoreError(f"artifact is zero bytes: {artifact}")

    platform = cm._FILENAME_TO_PLATFORM.get(artifact.name)
    if platform is None:
        raise StoreError(
            f"{artifact.name} is not a canonical connector artifact name "
            f"(expected one of {sorted(cm.SUPPORTED_ARTIFACTS.values())})")

    missing = [k for k in REQUIRED_BUILD_KEYS if not str(meta.get(k, "")).strip()]
    if missing:
        raise StoreError(
            f"{artifact.name}: build metadata is missing {missing}. "
            "Rebuild with the current build_connector.sh.")

    if meta["platform"] != platform:
        raise StoreError(
            f"{artifact.name}: sidecar platform {meta['platform']!r} != {platform!r}")
    if meta["filename"] != artifact.name:
        raise StoreError(
            f"sidecar filename {meta['filename']!r} != {artifact.name!r}")

    digest = cm.sha256_file(artifact)
    if meta["sha256"] != digest:
        raise StoreError(f"{artifact.name}: sidecar sha256 does not match the file")
    if int(meta["size_bytes"]) != size:
        raise StoreError(
            f"{artifact.name}: sidecar size_bytes {meta['size_bytes']} != actual {size}")

    if meta["pairing_protocol"] != EXPECTED_PAIRING_PROTOCOL and not allow_protocol_mismatch:
        raise StoreError(
            f"{artifact.name}: pairing_protocol {meta['pairing_protocol']!r} != "
            f"expected {EXPECTED_PAIRING_PROTOCOL!r}. This connector cannot pair "
            "with the current relay; rebuild from current source. "
            "(--allow-protocol-mismatch to override deliberately.)")
    return platform


def register(
    store: str | Path,
    artifact: str | Path,
    build_json: str | Path | None = None,
    *,
    allow_protocol_mismatch: bool = False,
) -> dict:
    """Import one native build into the store, replacing only that platform."""
    store = store_root(store)
    artifact = Path(artifact).resolve()
    meta = _load_build_json(artifact, Path(build_json).resolve() if build_json else None)
    platform = _validate_incoming(artifact, meta, allow_protocol_mismatch=allow_protocol_mismatch)

    dest = _platform_dir(store, platform)
    staging = store / f".incoming-{platform}-{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        shutil.copy2(artifact, staging / artifact.name)
        (staging / (artifact.name + ".build.json")).write_text(
            json.dumps(meta, indent=2, sort_keys=True) + "\n")

        # atomic-per-platform swap: nothing else in the store is touched
        backup = store / f".replaced-{platform}-{os.getpid()}"
        if dest.exists():
            os.rename(dest, backup)
        os.rename(staging, dest)
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    return {"platform": platform, **_registered_entry(dest, platform)}


# ── inspect ──────────────────────────────────────────────────────────────
def _registered_entry(plat_dir: Path, platform: str) -> dict | None:
    """A valid registered entry for ``platform`` in ``plat_dir``, or ``None``.

    A partially-written / inconsistent platform directory is treated as absent
    so a release can never point at an incomplete artifact.
    """
    filename = cm.SUPPORTED_ARTIFACTS[platform]
    artifact = plat_dir / filename
    sidecar = plat_dir / (filename + ".build.json")
    if not artifact.is_file() or artifact.stat().st_size == 0 or not sidecar.is_file():
        return None
    try:
        meta = json.loads(sidecar.read_text())
    except (OSError, ValueError):
        return None
    if any(not str(meta.get(k, "")).strip() for k in REQUIRED_BUILD_KEYS):
        return None
    if cm.sha256_file(artifact) != meta.get("sha256"):
        return None
    if int(meta.get("size_bytes", -1)) != artifact.stat().st_size:
        return None
    return {
        "filename": filename,
        "artifact": str(artifact),
        "sidecar": str(sidecar),
        "sha256": meta["sha256"],
        "size_bytes": artifact.stat().st_size,
        "built_at": meta["built_at"],
        "pairing_protocol": meta["pairing_protocol"],
        "connector_build_revision": meta["connector_build_revision"],
    }


def list_registered(store: str | Path) -> dict[str, dict]:
    store = store_root(store)
    out: dict[str, dict] = {}
    for platform in cm.SUPPORTED_ARTIFACTS:
        entry = _registered_entry(_platform_dir(store, platform), platform)
        if entry is not None:
            out[platform] = entry
    return out


# ── unpublish ────────────────────────────────────────────────────────────
def unpublish(store: str | Path, platform: str) -> bool:
    """Explicitly remove one platform from the store. Returns True if removed."""
    if platform not in cm.SUPPORTED_ARTIFACTS:
        raise StoreError(f"not a canonical platform: {platform}")
    plat_dir = _platform_dir(store_root(store), platform)
    if not plat_dir.exists():
        return False
    shutil.rmtree(plat_dir)
    return True


# ── build a release candidate ────────────────────────────────────────────
def build_candidate(store: str | Path, candidate_dir: str | Path) -> dict:
    """Assemble a fully-validated candidate web tree from the store."""
    registered = list_registered(store)
    if not registered:
        raise StoreError("the artifact store has no valid registered platforms")

    candidate = Path(candidate_dir).resolve()
    if candidate.exists():
        shutil.rmtree(candidate)
    candidate.mkdir(parents=True)

    for entry in registered.values():
        shutil.copy2(entry["artifact"], candidate / entry["filename"])
        # the sidecar is needed only so cm.generate() can carry built_at +
        # pairing_protocol + revision into manifest.json; it is not published.
        shutil.copy2(entry["sidecar"], candidate / (entry["filename"] + ".build.json"))

    manifest = cm.generate(candidate)          # manifest.json + SHA256SUMS
    for side in candidate.glob("*.build.json"):
        side.unlink()
    cm.enforce_permissions(candidate)
    cm.verify(candidate)                       # raises on any inconsistency

    present = set(manifest["artifacts"])
    if present != set(registered):
        raise StoreError(
            f"candidate manifest {sorted(present)} != registered {sorted(registered)}")
    return manifest


# ── promote a candidate to the served directory ──────────────────────────
def promote(candidate_dir: str | Path, served_dir: str | Path) -> dict:
    """Validate ``candidate_dir`` and swap it into ``served_dir``.

    Any failure here happens before the served tree is modified, so the current
    public release is left intact.
    """
    candidate = Path(candidate_dir).resolve()
    cm.verify(candidate)                       # fail closed, served untouched

    served = Path(served_dir).resolve()
    served.parent.mkdir(parents=True, exist_ok=True)

    # Clear any stale scratch dirs left by an interrupted release.
    staging = served.with_name(served.name + ".release-new")
    backup = served.with_name(served.name + ".release-old")
    for scratch in (staging, backup):
        if scratch.exists():
            shutil.rmtree(scratch)

    shutil.copytree(candidate, staging)
    cm.enforce_permissions(staging)
    cm.verify(staging)                         # validated copy, still not live

    # Atomic swap. If the second rename fails, put the old release back so a
    # failure never leaves the served path missing.
    if served.exists():
        os.rename(served, backup)
    try:
        os.rename(staging, served)
    except OSError:
        if backup.exists() and not served.exists():
            os.rename(backup, served)
        raise
    if backup.exists():
        shutil.rmtree(backup)

    # Enforce + verify on the LIVE tree before declaring success.
    cm.enforce_permissions(served)
    manifest = cm.verify(served)
    problems = cm.permission_problems(served)
    if problems:
        raise StoreError("served tree not web-readable:\n  - " + "\n  - ".join(problems))
    return manifest


def release(store: str | Path, served_dir: str | Path) -> dict:
    """build-candidate + promote, in one idempotent step."""
    tmp = Path(tempfile.mkdtemp(prefix="cryostack-connector-release-"))
    try:
        build_candidate(store, tmp / "candidate")
        return promote(tmp / "candidate", served_dir)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── CLI ──────────────────────────────────────────────────────────────────
def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="connector_store.py")
    parser.add_argument("--store", default=None, help=f"store dir (${STORE_ENV})")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("register")
    p.add_argument("artifact")
    p.add_argument("build_json", nargs="?", default=None)
    p.add_argument("--allow-protocol-mismatch", action="store_true")

    p = sub.add_parser("unpublish")
    p.add_argument("platform")

    sub.add_parser("list")

    p = sub.add_parser("build-candidate")
    p.add_argument("candidate_dir")

    p = sub.add_parser("promote")
    p.add_argument("candidate_dir")
    p.add_argument("served_dir")

    p = sub.add_parser("release")
    p.add_argument("served_dir")

    args = parser.parse_args(argv)
    store = store_root(args.store)

    try:
        if args.cmd == "register":
            entry = register(store, args.artifact, args.build_json,
                             allow_protocol_mismatch=args.allow_protocol_mismatch)
            print(f"[store] registered {entry['platform']}: {entry['filename']} "
                  f"(protocol {entry['pairing_protocol']}, rev {entry['connector_build_revision']})")
            return 0
        if args.cmd == "unpublish":
            removed = unpublish(store, args.platform)
            print(f"[store] {'removed' if removed else 'not present'}: {args.platform}")
            return 0
        if args.cmd == "list":
            reg = list_registered(store)
            print(f"[store] {store}")
            if not reg:
                print("[store]   (no registered platforms)")
            for platform, e in sorted(reg.items()):
                print(f"[store]   {platform:14s} {e['filename']:42s} "
                      f"{e['size_bytes']:>12d}  {e['pairing_protocol']}  {e['connector_build_revision']}")
            return 0
        if args.cmd == "build-candidate":
            m = build_candidate(store, args.candidate_dir)
            print(f"[store] candidate ready: {', '.join(sorted(m['artifacts']))}")
            return 0
        if args.cmd == "promote":
            m = promote(args.candidate_dir, args.served_dir)
            print(f"[store] promoted to {args.served_dir}: {', '.join(sorted(m['artifacts']))}")
            return 0
        if args.cmd == "release":
            m = release(store, args.served_dir)
            print(f"[store] released to {args.served_dir}: {', '.join(sorted(m['artifacts']))}")
            return 0
    except (StoreError, cm.ManifestError) as err:
        print(f"[store] ERROR: {err}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
