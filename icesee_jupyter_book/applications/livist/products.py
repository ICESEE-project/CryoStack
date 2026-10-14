"""Read-only views over finished LIVIST jobs: the product table of a job, the
comparison of several jobs and the input cache report.

Everything here reads what a job already recorded (``manifest.json``, the
store's publication requests, the input cache index) and file sizes on disk.
Product identity is decided by the SHA-256 recorded in each job's manifest;
product contents are never opened or interpreted here, and nothing is
written. Files of a job that did not complete are listed as partial, never
as products. An input's upstream identity (ETag, Last-Modified) is the one
the job recorded in its manifest; older manifests did not record it, and
they are shown as "not recorded" rather than filled in from today's cache.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import urlsplit

from . import input_cache, publication, validation

#: format of each product, by file-name suffix (LIVIST's ``scripts/generate``)
FORMATS = (
    ("-wgs84.parquet", "GeoParquet (EPSG:4326)"),
    (".parquet", "GeoParquet (EPSG:3031)"),
    (".fgb", "FlatGeobuf (EPSG:4326)"),
    (".pmtiles", "PMTiles vector tiles"),
    (".json", "LIVIST sources manifest"),
)
RESOURCE_FIELDS = (
    ("wall_s", "Wall time", "s"),
    ("cpu_s", "CPU time (user + system)", "s"),
    ("peak_rss_mb", "Peak memory (largest process)", "MB"),
    ("workdir_bytes", "Job directory on disk", "bytes"),
)
ENVIRONMENT_FIELDS = ("livist_commit", "livist_version", "python", "gdal", "tippecanoe", "uv",
                      "uv_lock_sha256", "toolchain_lock_sha256")
IDENTITY_NOTE = ("Products are compared by the SHA-256 recorded in each job's manifest only; "
                 "their contents are not opened or interpreted.")
PARTIAL_NOTE = ("This job did not complete. The files it left are partial: they are not "
                "products, are not validated, and cannot be downloaded, compared or published. "
                "Retry starts a new job; nothing of this one is reused.")
NOT_RECORDED = "not recorded"
PUBLICATION_NOTE = ("Nothing is published to source.coop unless a publication request was "
                    "approved by a second maintainer and the server has uploads enabled; an "
                    "approval on a server with uploads disabled is a dry run.")


def describe(name: str) -> dict:
    """``{input, mode, format}`` of a product file name."""
    fmt = next((label for suffix, label in FORMATS if name.endswith(suffix)), "other")
    stem = name
    for suffix, _label in FORMATS:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    for mode in validation.MODES:
        if stem.startswith("temperature-") and stem.endswith(f"-{mode}"):
            return {"input": stem[len("temperature-"): -len(mode) - 1], "mode": mode,
                    "format": fmt}
    return {"input": None, "mode": None, "format": fmt}


def validation_by_product(check: dict | None) -> dict[str, dict]:
    """Per product: ``passed`` / ``warnings`` / ``failed`` and the non-OK
    findings. Products no check mentions are absent from the result."""
    out: dict[str, dict] = {}
    rank = {"ok": 0, "warn": 1, "error": 2}
    for item in (check or {}).get("checks") or []:
        entry = out.setdefault(item.get("artifact"), {"level": "ok", "findings": []})
        level = item.get("level", "ok")
        if rank.get(level, 0) > rank[entry["level"]]:
            entry["level"] = level
        if level != "ok":
            entry["findings"].append(f"{item.get('check')}: {item.get('detail')}")
    names = {"ok": "passed", "warn": "warnings", "error": "failed"}
    return {k: {"status": names[v["level"]], "findings": v["findings"]} for k, v in out.items()}


def publication_state(requests: list[dict]) -> dict:
    """What happened to a job's publication requests (newest first). Only an
    executed upload counts as published."""
    published: dict[str, str] = {}
    for item in requests:
        if item.get("status") != "published":
            continue
        shas = {f["name"]: f.get("sha256") for f in (item.get("plan") or {}).get("files") or []}
        for entry in ((item.get("result") or {}).get("uploaded") or []):
            published.setdefault(entry.get("name"), shas.get(entry.get("name")))
    latest = requests[0] if requests else None
    if published:
        state = "published"
    elif latest is None:
        state = "not-requested"
    elif latest["status"] == "approved" and (latest.get("result") or {}).get("dry_run"):
        state = "dry-run-approved"
    else:
        state = latest["status"]          # pending / rejected / failed / approved (uploading)
    return {"state": state, "requests": len(requests), "published": published,
            "note": PUBLICATION_NOTE}


def product_table(workdir: Path, data: dict | None, publication_info: dict | None = None,
                  *, status: str = "completed") -> dict:
    """The products a job recorded, with their validation and publication
    state; ``on_disk`` says whether the file is still there at the recorded
    size (checksums are not recomputed). ``status`` is the job's status in the
    store: unless it is ``completed`` the files are partial."""
    data = data or {}
    if status != "completed":
        return _partial_table(data)
    check = data.get("validation")
    per_product = validation_by_product(check)
    present = validation.product_paths(workdir) if workdir.is_dir() else {}
    published = (publication_info or {}).get("published") or {}
    rows = []
    for artifact in data.get("artifacts") or []:
        name = artifact.get("name")
        path = present.get(name)
        try:
            on_disk = path is not None and path.stat().st_size == artifact.get("size")
        except OSError:
            on_disk = False
        result = per_product.get(name)
        rows.append({
            "name": name, **describe(name),
            "size": artifact.get("size"), "sha256": artifact.get("sha256"),
            "on_disk": on_disk,
            "validation": (result["status"] if result else
                           "not-checked" if check else "unvalidated"),
            "findings": result["findings"] if result else [],
            "publishable": publication.publishable(name),
            "published": name in published and published[name] == artifact.get("sha256"),
            "partial": False,
        })
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["validation"]] = counts.get(row["validation"], 0) + 1
    return {
        "products": rows,
        "validation": None if not check else {
            "status": check.get("status"), "deep": bool(check.get("deep")),
            "checked_at": check.get("checked_at")},
        "counts": counts,
        "publication": publication_info,
        "complete": True,
    }


def _partial_table(data: dict) -> dict:
    """Files of a job that did not complete (an older manifest may still list
    them as artifacts): shown as partial, with nothing offered for them."""
    listed = data.get("partial_files") or data.get("artifacts") or []
    rows = [{"name": f.get("name"), **describe(f.get("name") or ""), "size": f.get("size"),
             "sha256": None, "on_disk": False, "validation": "partial", "findings": [],
             "publishable": False, "published": False, "partial": True} for f in listed]
    return {"products": rows, "validation": None, "counts": {"partial": len(rows)} if rows else {},
            "publication": None, "complete": False, "note": PARTIAL_NOTE}


# ── comparison ───────────────────────────────────────────────────────
def _resources(data: dict) -> dict | None:
    used = data.get("resources")
    if not isinstance(used, dict) or not used.get("measured"):
        return None
    out = {k: used.get(k) for k in ("wall_s", "peak_rss_mb", "workdir_bytes")}
    cpu = [used.get("cpu_user_s"), used.get("cpu_system_s")]
    out["cpu_s"] = round(sum(cpu), 1) if all(isinstance(v, (int, float)) for v in cpu) else None
    return out


def _same(values: list) -> bool:
    return len({repr(v) for v in values}) <= 1


def recorded_identity(record: dict) -> dict:
    """An input's upstream identity as the job recorded it; ``recorded`` is
    false for manifests written before it was recorded."""
    item = record.get("identity")
    if not isinstance(item, dict) or not item.get("recorded"):
        return {"recorded": False, "etag": None, "last_modified": None, "upstream_size": None,
                "upstream_checked": None, "observed": NOT_RECORDED, "observed_at": None}
    return {"recorded": True, "etag": item.get("etag"),
            "last_modified": item.get("last_modified"),
            "upstream_size": item.get("upstream_size"),
            "upstream_checked": item.get("upstream_checked"),
            "observed": item.get("observed") or NOT_RECORDED,
            "observed_at": item.get("observed_at")}


def compare(runs: list[dict]) -> dict:
    """Compare jobs side by side.

    ``runs``: ``[{"job": <public job>, "manifest": <manifest or None>}]`` in
    display order; the first is the reference for resource differences."""
    ids = [r["job"]["job_id"] for r in runs]
    manifests = [r.get("manifest") or {} for r in runs]
    statements: list[str] = []

    # inputs
    names = sorted({i.get("name") for m in manifests for i in m.get("inputs") or []})
    inputs = []
    for name in names:
        per_job = []
        for data in manifests:
            record = next((i for i in data.get("inputs") or [] if i.get("name") == name), None)
            ident = None if record is None else recorded_identity(record)
            per_job.append(None if record is None else {
                "kind": record.get("kind"), "location": record.get("location"),
                "size": record.get("size"), "sha256": record.get("sha256"),
                "identity_recorded": ident["recorded"],
                "etag": ident["etag"], "last_modified": ident["last_modified"],
                "upstream_size": ident["upstream_size"], "observed": ident["observed"],
                "cache": (((record.get("cache") or {}).get("cache") or "downloaded")
                          if record.get("kind") == "source-coop" else "local"),
                "upstream_checked": (ident["upstream_checked"] if ident["recorded"]
                                     else (record.get("cache") or {}).get("upstream_checked"))})
        if any(p is None for p in per_job):
            identity = "missing"
        elif any(not p["sha256"] for p in per_job):
            identity = "unknown"
        elif _same([p["sha256"] for p in per_job]) and _same([p["location"] for p in per_job]):
            identity = "identical"
        else:
            identity = "differ"
        inputs.append({"name": name, "identity": identity, "jobs": per_job})
    inputs_same = bool(inputs) and all(i["identity"] == "identical" for i in inputs)
    if inputs_same:
        statements.append("Inputs are identical (same source and SHA-256 in every job).")
    else:
        differing = [i["name"] for i in inputs if i["identity"] != "identical"]
        statements.append("Inputs differ: " + (", ".join(
            f"{i['name']} ({i['identity']})" for i in inputs if i["name"] in differing)
            or "no inputs recorded") + ".")
    unrecorded = sorted({r["job"]["job_id"][:8] for r, m in zip(runs, manifests)
                         for i in m.get("inputs") or []
                         if i.get("kind") == "source-coop" and not recorded_identity(i)["recorded"]})
    if unrecorded:
        statements.append("Upstream identity (ETag, Last-Modified) was not recorded by "
                          + ", ".join(unrecorded) + " (manifest written before it was recorded); "
                          "only the SHA-256 of the input is known for them.")
    tags = [{(j or {}).get("etag") for j in i["jobs"] if j and j.get("etag")} for i in inputs]
    if any(len(t) > 1 for t in tags):
        statements.append("The recorded source.coop ETag of an input differs between jobs: the "
                          "object on source.coop changed between the runs.")

    # LIVIST / toolchain / configuration
    environment = []

    def field(key: str, label: str, values: list) -> None:
        environment.append({"field": key, "label": label, "values": values,
                            "same": _same(values)})

    field("livist_commit", "LIVIST commit", [(m.get("livist") or {}).get("commit") for m in manifests])
    field("command", "Command", [(m.get("livist") or {}).get("command") for m in manifests])
    field("config_sha256", "LIVIST config.toml SHA-256",
          [m.get("config_sha256") or r["job"].get("config_sha256") for m, r in zip(manifests, runs)])
    for key in ENVIRONMENT_FIELDS[1:]:
        field(f"environment.{key}", f"Environment {key.replace('_', ' ')}",
              [((m.get("livist") or {}).get("environment") or {}).get(key) for m in manifests])
    field("cryostack_commit", "CryoStack commit", [m.get("cryostack_commit") for m in manifests])
    changed = [e["label"] for e in environment if not e["same"]]
    statements.append("LIVIST version, toolchain and configuration are the same."
                      if not changed else "Differences in LIVIST/toolchain/configuration: "
                      + ", ".join(changed) + ".")

    # products: identity by recorded SHA-256 only
    tables = [{a.get("name"): a for a in m.get("artifacts") or []} for m in manifests]
    checks = [validation_by_product(m.get("validation")) for m in manifests]
    product_names = sorted({n for t in tables for n in t})
    products = []
    for name in product_names:
        cells = [None if name not in t else {"size": t[name].get("size"),
                                             "sha256": t[name].get("sha256"),
                                             "validation": (c.get(name) or {}).get("status")}
                 for t, c in zip(tables, checks)]
        if any(c is None for c in cells):
            identity = "missing"
        elif _same([c["sha256"] for c in cells]):
            identity = "identical"
        else:
            identity = "differ"
        products.append({"name": name, **describe(name), "identity": identity, "jobs": cells})
    summary = {k: sum(1 for p in products if p["identity"] == k)
               for k in ("identical", "differ", "missing")}
    if not products:
        statements.append("No products were recorded for these jobs.")
    elif summary["identical"] == len(products):
        statements.append(f"All {len(products)} products are byte-identical (same SHA-256).")
    else:
        parts = []
        if summary["differ"]:
            parts.append(f"{summary['differ']} differ in content")
        if summary["missing"]:
            parts.append(f"{summary['missing']} {'is' if summary['missing'] == 1 else 'are'} "
                         "missing from at least one job")
        statements.append(f"Products differ: {' and '.join(parts)} "
                          f"({summary['identical']} of {len(products)} identical).")

    # validation and measured resources
    validations = [None if not m.get("validation") else {
        "status": m["validation"].get("status"), "deep": bool(m["validation"].get("deep")),
        "checked_at": m["validation"].get("checked_at")} for m in manifests]
    measured = [_resources(m) for m in manifests]
    resources = []
    for key, label, unit in RESOURCE_FIELDS:
        values = [None if r is None else r.get(key) for r in measured]
        base = values[0]
        diffs = []
        for value in values:
            if not isinstance(base, (int, float)) or not isinstance(value, (int, float)):
                diffs.append(None)
            else:
                diffs.append({"delta": round(value - base, 1),
                              "percent": round(100.0 * (value - base) / base, 1) if base else None})
        resources.append({"field": key, "label": label, "unit": unit, "values": values,
                          "difference": diffs})
    statements.append(IDENTITY_NOTE)
    return {
        "jobs": [{**r["job"], "has_manifest": bool(r.get("manifest")),
                  "validation": v, "written_at": m.get("written_at")}
                 for r, m, v in zip(runs, manifests, validations)],
        "job_ids": ids,
        "inputs": inputs,
        "inputs_identical": inputs_same,
        "environment": environment,
        "products": products,
        "product_summary": summary,
        "products_identical": bool(products) and summary["identical"] == len(products),
        "resources": resources,
        "reference_job": ids[0] if ids else None,
        "statements": statements,
    }


# ── input cache report ───────────────────────────────────────────────
def cache_report(cache, jobs: list[dict], *, names: dict | None = None,
                 viewer_id: str | None = None) -> dict:
    """The shared input cache, read-only: entries with provenance, the jobs
    that recorded each input, and size against the configured bounds. No
    server paths are included.

    ``jobs``: ``[{"job": <store row>, "manifest": <manifest or None>}]``."""
    index = cache.entries()
    blobs = cache.root / "blobs"
    used_by: dict[str, list[dict]] = {}
    for item in jobs:
        job, data = item["job"], item.get("manifest") or {}
        for record in data.get("inputs") or []:
            if record.get("kind") != "source-coop":
                continue
            cache_info = record.get("cache") or {}
            used_by.setdefault(record.get("location"), []).append({
                "job_id": job["job_id"],
                "owner": "You" if job["owner_id"] == viewer_id else (names or {}).get(job["owner_id"]),
                "status": job["status"], "finished_at": job.get("finished_at"),
                "cache": cache_info.get("cache") or "downloaded",
                "upstream_checked": cache_info.get("upstream_checked"),
                "sha256": record.get("sha256")})
    entries = []
    for key, entry in sorted(index.items()):
        url = urlsplit(entry.get("url") or "")
        blob = blobs / str(entry.get("sha256"))
        try:
            blob_size = blob.stat().st_size if blob.is_file() else None
        except OSError:
            blob_size = None
        users = used_by.get(key, [])
        for user in users:
            user["same_content"] = user.pop("sha256") == entry.get("sha256")
        entries.append({
            "key": key, "host": url.netloc, "path": url.path,
            "size": entry.get("size"), "sha256": entry.get("sha256"),
            "etag": entry.get("etag"), "last_modified": entry.get("last_modified"),
            "stored_at": entry.get("stored_at"), "used_at": entry.get("used_at"),
            "blob_present": blob_size is not None,
            "blob_size_matches": blob_size is not None and blob_size == entry.get("size"),
            "provenance": {
                "stored_from": "a completed job's own LIVIST download",
                "sha256_verified": "when stored (copy re-hashed) and before every reuse",
                "upstream_at_store": ("source.coop size/ETag recorded" if entry.get("etag")
                                      else "source.coop not reachable or no ETag; size checked "
                                           "against the downloaded file only"),
            },
            "jobs": users,
            "hits": sum(1 for u in users if u["cache"] == "hit"),
        })
    total = sum(int(e.get("size") or 0) for e in index.values())
    try:
        free = shutil.disk_usage(cache.root if cache.root.exists() else cache.root.parent).free
    except OSError:
        free = None
    return {
        "entries": entries,
        "total_bytes": total,
        "limit_bytes": cache.limit,
        "over_limit": bool(cache.limit) and total > cache.limit,
        "free_bytes": free,
        "reserve_bytes": input_cache.FREE_SPACE_RESERVE,
        "below_reserve": free is not None and free < input_cache.FREE_SPACE_RESERVE,
        "jobs_scanned": len(jobs),
        "eviction": "Eviction is automatic (least recently used first) when a new input is "
                    "stored; no manual removal is offered",
    }
