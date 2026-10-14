"""Publication of LIVIST products to source.coop: plan, and a gated executor.

What LIVIST's ``scripts/upload`` publishes from ``data/`` is mirrored
exactly: every ``*.parquet`` except ``*-wgs84.parquet``, and every
``*.pmtiles``, into ``s3://us-west-2.opendata.source.coop/englacial/
ice-sheet-temperature/temperature/``.

A plan lists each file with its size and SHA-256 (re-computed and compared
with the job's manifest), its destination, and whether the destination
already exists (an anonymous HTTPS ``HEAD`` on the public mirror -- read
only, no credentials). Publication is a two-step request -> approval
workflow (see ``routes``); unless ``CRYOSTACK_LIVIST_PUBLICATION_ENABLED`` is
set, approval records the dry-run plan and uploads nothing.

Upload credentials are the server's own AWS credential chain (optionally a
named profile); they are never stored, logged or returned.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import settings, validation
from .manifest import sha256_file

PROBE_TIMEOUT_S = 10
PUBLISHABLE_STATUSES = ("passed", "warnings")


class PublicationError(RuntimeError):
    pass


class PublicationDisabled(PublicationError):
    pass


def publishable(name: str) -> bool:
    """The files ``scripts/upload`` syncs."""
    if name.endswith(".pmtiles"):
        return True
    return name.endswith(".parquet") and not name.endswith("-wgs84.parquet")


def http_probe(url: str) -> dict:
    """Anonymous HEAD of a public object: does it exist, and how big is it."""
    request = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "CryoStack-LIVIST-plan"})
    try:
        with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT_S) as response:
            return {"exists": True, "size": int(response.headers.get("Content-Length") or 0),
                    "etag": (response.headers.get("ETag") or "").strip('"') or None,
                    "last_modified": response.headers.get("Last-Modified")}
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {"exists": False}
        return {"exists": None, "error": f"HTTP {error.code}"}
    except (urllib.error.URLError, OSError, ValueError) as error:
        return {"exists": None, "error": type(error).__name__}


def plan(job: dict, workdir: Path, job_manifest: dict | None, *, probe=http_probe) -> dict:
    """The dry-run publication plan of a job (nothing is uploaded)."""
    target, http = settings.publication_target(), settings.publication_http()
    blocking = []
    if job.get("status") != "completed":
        blocking.append("The job has not completed.")
    if job.get("validation_status") not in PUBLISHABLE_STATUSES:
        blocking.append("The products have not passed validation.")
    recorded = {a["name"]: a for a in (job_manifest or {}).get("artifacts") or []}
    if not recorded:
        blocking.append("The job has no artifact manifest.")
    present = validation.product_paths(workdir)
    files, skipped = [], []
    for name in sorted(present):
        if not publishable(name):
            skipped.append(name)
            continue
        sha = sha256_file(present[name])
        if recorded.get(name, {}).get("sha256") != sha:
            blocking.append(f"{name} changed since its manifest was written.")
        remote = probe(f"{http}/{name}")
        action = ("overwrite" if remote.get("exists") else
                  "create" if remote.get("exists") is False else "unknown")
        files.append({"name": name, "size": present[name].stat().st_size, "sha256": sha,
                      "destination": f"{target}/{name}", "public_url": f"{http}/{name}",
                      "remote": remote, "action": action})
    if not files:
        blocking.append("There is nothing to publish.")
    return {
        "job_id": job.get("job_id"),
        "target": target,
        "files": files,
        "not_uploaded": skipped,
        "overwrites": [f["name"] for f in files if f["action"] == "overwrite"],
        "unknown": [f["name"] for f in files if f["action"] == "unknown"],
        "blocking": blocking,
        "total_bytes": sum(f["size"] for f in files),
        "livist_commit": ((job_manifest or {}).get("livist") or {}).get("commit"),
        "config_sha256": (job_manifest or {}).get("config_sha256"),
        "planned_at": time.time(),
        "dry_run": True,
    }


def plan_digest(item: dict) -> str:
    """Identity of a plan: which bytes go where (not the remote probe)."""
    core = [(f["name"], f["sha256"], f["destination"]) for f in item.get("files") or []]
    return hashlib.sha256(json.dumps(core).encode()).hexdigest()


def _bucket_prefix(target: str) -> tuple[str, str]:
    if not target.startswith("s3://"):
        raise PublicationError("The publication target is not an S3 location.")
    bucket, _, prefix = target[5:].partition("/")
    return bucket, prefix.strip("/")


def default_client():
    import boto3

    session = boto3.Session(profile_name=settings.publication_profile())
    return session.client("s3", region_name="us-west-2")


def execute(item: dict, workdir: Path, *, allow_overwrite: bool, client_factory=default_client) -> dict:
    """Upload an approved plan. Refuses unless publication is enabled."""
    if not settings.publication_enabled():
        raise PublicationDisabled("Publication is disabled on this server (dry run only).")
    if item.get("blocking"):
        raise PublicationError("The plan has blocking problems.")
    if item.get("unknown"):
        raise PublicationError("Some destinations could not be checked for overwrites.")
    if item.get("overwrites") and not allow_overwrite:
        raise PublicationError("The plan overwrites published files and the request did not "
                               "allow overwriting.")
    bucket, prefix = _bucket_prefix(item["target"])
    present = validation.product_paths(workdir)
    for entry in item["files"]:
        path = present.get(entry["name"])
        if path is None or sha256_file(path) != entry["sha256"]:
            raise PublicationError(f"{entry['name']} changed after approval.")
    client = client_factory()
    uploaded = []
    for entry in item["files"]:
        key = f"{prefix}/{entry['name']}" if prefix else entry["name"]
        client.upload_file(str(present[entry["name"]]), bucket, key,
                           ExtraArgs={"Metadata": {"sha256": entry["sha256"]}})
        uploaded.append({"name": entry["name"], "destination": entry["destination"]})
    return {"uploaded": uploaded, "uploaded_at": time.time()}
