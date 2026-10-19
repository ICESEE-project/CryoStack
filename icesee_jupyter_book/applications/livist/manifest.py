"""The artifact manifest of a LIVIST job (``manifest.json``).

It records what was produced (name, size, SHA-256), from what (inputs with
their SHA-256, the exact LIVIST ``config.toml`` hash, the LIVIST commit and
the isolated environment's build record) and the validation result, plus the
attribution LIVIST's MIT licence and its data sources call for.

Schema 2 adds, without changing any schema-1 field: per input an
``identity`` (SHA-256 and size of the file LIVIST read; for source.coop the
ETag, Last-Modified and size source.coop reported, how they were observed and
whether source.coop was asked), the job's ``reason`` and ``retry_of``, and
``complete``. Only a completed job lists ``artifacts``; any other job lists
what it left in ``partial_files`` (name and size, not hashed) -- those files
are not products. Readers treat a schema-1 manifest as recording no input
identity.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from . import settings, toolchain, validation
from .sources import mask_location

MANIFEST = "manifest.json"
SCHEMA = 2
_CHUNK = 1 << 20

ATTRIBUTION = {
    "software": "LIVIST (Living Ice Sheet Temperature), Copyright (c) 2026 Development Seed, "
                "MIT License",
    "repository": settings.UPSTREAM_REPOSITORY,
    "data": "Radar attenuation rates and borehole data from source.coop "
            "(englacial/ice-sheet-temperature); cite the original publications listed with "
            "the data.",
    "method": "Temperatures inverted from depth-averaged radar attenuation following "
              "elizadawson/ice_attenuation_temperature (pure-ice and borehole-conductivity "
              "Arrhenius models).",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cryostack_commit() -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(settings.REPO_ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10,
                              stdin=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin"})
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = done.stdout.strip()
    return out if done.returncode == 0 and len(out) == 40 else None


def artifacts(workdir: Path) -> list[dict]:
    return [{"name": name, "size": path.stat().st_size, "sha256": sha256_file(path)}
            for name, path in validation.product_paths(workdir).items()]


def input_record(row: dict, staged: Path | None) -> dict:
    record = {"name": row["name"], "kind": row["kind"],
              "location": row["location"] if row["kind"] == "source-coop"
              else mask_location(row["location"])}
    if staged is not None and staged.exists():
        target = staged.resolve()
        record.update(size=target.stat().st_size, sha256=sha256_file(target))
    return record


def partial_files(workdir: Path) -> list[dict]:
    out = []
    for name, path in validation.product_paths(workdir).items():
        try:
            out.append({"name": name, "size": path.stat().st_size})
        except OSError:
            pass
    return out


def build(job: dict, *, workdir: Path, inputs: list[dict], config_sha256: str | None,
          check: dict | None, env: Path | None = None, resources: dict | None = None) -> dict:
    record = toolchain.env_record(env) or {}
    complete = job.get("status") == "completed"
    return {
        "schema": SCHEMA,
        "job_id": job["job_id"],
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "livist": {
            "commit": toolchain.source_commit(),
            "environment": {k: record.get(k) for k in (
                "livist_commit", "livist_version", "python", "gdal", "tippecanoe", "uv",
                "uv_lock_sha256", "toolchain_lock_sha256", "built_at")},
            "command": "scripts/generate",
        },
        "cryostack_commit": cryostack_commit(),
        "config_sha256": config_sha256,
        "inputs": inputs,
        "complete": complete,
        "artifacts": artifacts(workdir) if complete else [],
        "partial_files": [] if complete else partial_files(workdir),
        "reason": job.get("error"),
        "retry_of": job.get("retry_of"),
        "validation": check,
        "resources": resources,
        "attribution": ATTRIBUTION,
        "written_at": time.time(),
    }


def write(workdir: Path, manifest: dict) -> str:
    """Write ``manifest.json`` atomically; return its SHA-256."""
    data = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
    tmp = workdir / f".{MANIFEST}.tmp"
    tmp.write_bytes(data)
    from cryostack_src.storage_layout import durable_replace

    durable_replace(tmp, workdir / MANIFEST)
    return hashlib.sha256(data).hexdigest()


def read(workdir: Path) -> dict | None:
    try:
        data = json.loads((workdir / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
