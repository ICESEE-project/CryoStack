"""Scientific review and publication of picking results.

Lifecycle of a user's manual (ASTRA) result on shared radar::

    draft ── Done ──► completed ── submit ──► submitted ──► published
                         ▲                       │  │            │
                         └──── returned ◄────────┘  └► rejected  ├► withdrawn
                              (correct, resubmit)                └► superseded

* **Submit** (owner only): the server freezes an immutable snapshot of the
  result -- the canonical ASTRA CSV and QC image byte for byte, the
  structured observations, the session state, and provenance -- in the
  installation's review store (``$CRYOSTACK_FROZEN_LEGACIES_REVIEW_ROOT``,
  default ``frozen_legacies_reviews/`` next to the catalog database, i.e.
  ``var/frozen_legacies_reviews/<id>/``). Later edits, resets or
  deletions in the user's workspace never change a snapshot; the user's
  canonical ASTRA outputs are never modified by a review.
* **Review** (Control Center ``maintainer`` / ``admin`` / ``owner``; never
  the submitter): approve, return for correction, or reject -- the last
  two with a reason.
* **Publish** (approval): the snapshot's observations are copied into
  ``published_observations`` -- an explicit shared dataset product served
  from the catalog, never a view into a private workspace. Publishing a
  newer submission of the same user and radar file supersedes the older one.
* **Withdraw** (reviewers): a published result leaves the shared product;
  its snapshot and decision history are kept.

Personal data stays internal: submitter and reviewer IDs are kept for
authorization and audit and are never part of a published record, export
or provenance file.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path

from ..workspace import ASSET_SESSION
from . import georef


REVIEW_ROOT_ENV = "CRYOSTACK_FROZEN_LEGACIES_REVIEW_ROOT"
PROVENANCE_SCHEMA = "cryostack.frozen_legacies.result_provenance"

STATUSES = ("submitted", "returned", "rejected", "published", "withdrawn", "superseded",
            "cancelled")
OPEN = ("submitted",)
DECISIONS = {"approve": "published", "return": "returned", "reject": "rejected"}
SNAPSHOT_PRODUCTS = ("astra-csv", "astra-qc")
WORKFLOW = "astra-manual"
PRODUCER = "ASTRA (CryoStack port of Pickers/ASTRA_MAC.py)"
UNVERIFIED = "unverified"                  # georef.STATUSES vocabulary
SNAPSHOT_MANIFEST = "SNAPSHOT.json"


class ReviewError(ValueError):
    """A request that is not valid in the submission's current state."""


class ReviewForbidden(PermissionError):
    """The user may not perform this review action."""


class SnapshotUnavailable(ReviewError):
    """A snapshot's files are missing or do not match their recorded hashes."""


def review_root(catalog_path: Path) -> Path:
    """Where snapshots are kept: configured, or beside the catalog database
    (snapshots and the submissions table belong together)."""
    configured = (os.environ.get(REVIEW_ROOT_ENV) or "").strip()
    return Path(configured) if configured else Path(catalog_path).parent / "frozen_legacies_reviews"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def producer_version() -> str:
    """Identity of the ASTRA implementation that produced a result."""
    astra = Path(__file__).resolve().parents[1] / "pickers" / "astra.py"
    return f"astra.py sha256:{_sha256(astra)[:12]}"


def _map_position(record):
    from .observations import map_position
    return map_position(record)


def _public_observation(record: dict, submission: dict) -> dict:
    """A published observation: scientific values and provenance only."""
    keep = ("a_scope", "cbd", "lat", "lon", "surface_us", "surface_db", "bed_us", "bed_db",
            "noisefloor_us", "noisefloor_db", "mainbang_us", "mainbang_db", "surface_m",
            "bed_m", "h_ice_m", "picks", "window_x", "geolocation_status", "verified_cbd",
            "film_cbd", "cbd_source", "verified_position")
    from .observations import map_position

    properties = {k: record[k] for k in keep if k in record}
    properties.setdefault("geolocation_status", UNVERIFIED)
    # ASTRA's own CBD and position, always kept explicitly
    properties["astra_cbd"] = record.get("astra_cbd", record.get("cbd"))
    properties["astra_position"] = record.get("astra_position", record.get("position"))
    # the published CBD and position: verified when verified, else ASTRA's (labelled)
    position = map_position(record)
    if properties["geolocation_status"] == "verified":
        properties["cbd"] = record.get("verified_cbd", properties["astra_cbd"])
    properties["lon"], properties["lat"] = (position if position else (None, None))
    properties.update({
        "observation_id": f"{submission['submission_id']}-a{record['a_scope']}",
        "submission_id": submission["submission_id"],
        "dataset_id": submission["dataset_id"], "catalog_id": submission["catalog_id"],
        "filename": submission["filename"], "flight": submission["flight"],
        "workflow": submission["workflow"], "producer": submission["producer"],
        "producer_version": submission["producer_version"],
        "status": "published", "scope": "published",
        "published_at": submission.get("published_at"),
    })
    if properties["geolocation_status"] != "verified" and submission.get("accepted_unverified"):
        properties["geolocation_acceptance"] = ("published with ASTRA-assigned position, "
                                                "accepted by the reviewer as unverified")
    return properties


class ReviewStore:
    """Submissions and the published product, in the catalog database."""

    def __init__(self, catalog, root: Path | None = None):
        self.catalog = catalog
        self.root = Path(root) if root is not None else review_root(catalog.path)

    # ── reading ──────────────────────────────────────────────────────
    def get(self, submission_id: str) -> dict | None:
        with self.catalog._connect() as db:
            row = db.execute("SELECT * FROM submissions WHERE submission_id = ?",
                             (submission_id,)).fetchone()
        return _decode(row)

    def for_asset(self, owner: str, asset_id: str) -> list[dict]:
        with self.catalog._connect() as db:
            rows = db.execute("SELECT * FROM submissions WHERE owner = ? AND asset_id = ?"
                              " ORDER BY submitted_at DESC", (owner, asset_id)).fetchall()
        return [_decode(r) for r in rows]

    def for_owner(self, owner: str, limit: int = 200) -> list[dict]:
        with self.catalog._connect() as db:
            rows = db.execute("SELECT * FROM submissions WHERE owner = ?"
                              " ORDER BY submitted_at DESC LIMIT ?", (owner, limit)).fetchall()
        return [_decode(r) for r in rows]

    def by_asset(self, owner: str) -> dict[str, list[dict]]:
        """All of an owner's submissions grouped by asset, newest first."""
        with self.catalog._connect() as db:
            rows = db.execute("SELECT * FROM submissions WHERE owner = ?"
                              " ORDER BY submitted_at DESC", (owner,)).fetchall()
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            item = _decode(row)
            grouped.setdefault(item["asset_id"], []).append(item)
        return grouped

    def queue(self, status: str | None = None, *, page: int = 1, page_size: int = 50) -> dict:
        page, page_size = max(1, page), max(1, min(100, page_size))
        where, args = ("WHERE status = ?", [status]) if status else ("", [])
        with self.catalog._connect() as db:
            total = db.execute(f"SELECT COUNT(*) FROM submissions {where}", args).fetchone()[0]
            rows = db.execute(f"SELECT * FROM submissions {where} ORDER BY"
                              f" (status = 'submitted') DESC, submitted_at DESC"
                              f" LIMIT ? OFFSET ?",
                              args + [page_size, (page - 1) * page_size]).fetchall()
            counts = dict(db.execute("SELECT status, COUNT(*) FROM submissions"
                                     " GROUP BY status").fetchall())
        return {"items": [_decode(r) for r in rows], "total": total, "page": page,
                "page_size": page_size, "counts": counts}

    def snapshot_dir(self, submission: dict) -> Path:
        path = (self.root / submission["submission_id"]).resolve()
        if path.parent != self.root.resolve():
            raise ReviewError("Invalid submission.")
        return path

    def snapshot_file(self, submission: dict, product: str) -> Path | None:
        name = (submission["products"].get(product) or {}).get("name")
        if not name:
            return None
        path = self.snapshot_dir(submission) / name
        return path if path.is_file() and not path.is_symlink() else None

    def snapshot_observations(self, submission: dict) -> list[dict]:
        path = self.snapshot_dir(submission) / "observations.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))["observations"]
        except (OSError, ValueError, KeyError):
            raise SnapshotUnavailable("The submission's snapshot is not available on this "
                                      "server (observations missing or unreadable).")

    def provenance(self, submission: dict) -> dict:
        path = self.snapshot_dir(submission) / "provenance.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise SnapshotUnavailable("The submission's provenance file is not available.")

    def verify_snapshot(self, submission: dict) -> dict:
        """Check every snapshot file against the hashes recorded at submission.

        Returns ``{"ok", "problems", "files"}``; snapshots made before the
        manifest existed are checked against the product hashes only."""
        directory = self.snapshot_dir(submission)
        problems, expected = [], {}
        manifest = directory / SNAPSHOT_MANIFEST
        if manifest.is_file():
            try:
                expected = json.loads(manifest.read_text(encoding="utf-8"))["files"]
            except (OSError, ValueError, KeyError):
                problems.append(f"{SNAPSHOT_MANIFEST} is unreadable")
        elif directory.is_dir():
            expected = {v["name"]: v["sha256"] for v in (submission.get("products") or {}).values()}
        else:
            problems.append("the snapshot directory is missing")
        for name, digest in expected.items():
            path = directory / name
            if not path.is_file() or path.is_symlink():
                problems.append(f"{name} is missing")
            elif _sha256(path) != digest:
                problems.append(f"{name} does not match its recorded hash")
        for product in (submission.get("products") or {}).values():
            if product["name"] in expected and expected[product["name"]] != product["sha256"]:
                problems.append(f"{product['name']} differs from the submission record")
        return {"ok": not problems, "problems": problems, "files": len(expected)}

    def require_intact(self, submission: dict) -> None:
        check = self.verify_snapshot(submission)
        if not check["ok"]:
            raise SnapshotUnavailable("The submission's snapshot is damaged or incomplete ("
                                      + "; ".join(check["problems"][:5])
                                      + "). Restore it from a backup before deciding.")

    # ── submit ───────────────────────────────────────────────────────
    def submit(self, *, workspace, user_id: str, manifest: dict, doc: dict, outputs: dict,
               observations: dict, source_version: str | None, nav_path: Path | None,
               note: str | None = None) -> dict:
        """Freeze the user's completed result as a new submission."""
        owner = workspace.user.safe_id
        asset_id = manifest["asset_id"]
        if manifest.get("origin") != "shared" or not manifest.get("shared_source"):
            raise ReviewError("Only results on shared radar can be submitted for review; "
                              "uploaded radar is private to you.")
        if doc is None or doc.get("status") != "completed":
            raise ReviewError("Finish the manual session (Done) before submitting it.")
        if set(outputs) != set(SNAPSHOT_PRODUCTS):
            raise ReviewError("The ASTRA CSV and QC image are missing; reopen Manual and "
                              "select Done again.")
        if not observations or observations.get("session_revision") != doc["revision"]:
            raise ReviewError("The observations are out of date; reload the session.")
        previous = self.for_asset(owner, asset_id)
        if any(s["status"] == "submitted" for s in previous):
            raise ReviewError("This result is already awaiting review.")
        if any(s["status"] == "published"
               and same_version(s, doc["revision"], doc.get("completed_at"))
               for s in previous):
            raise ReviewError("This version of the result is already published.")

        submission_id = "sub-" + uuid.uuid4().hex[:24]
        now = time.time()
        shared = manifest["shared_source"]
        # georeferencing (film-CBD confirmations) is frozen with the result;
        # a failure here stops the submission rather than silently dropping it
        records = georef.annotate_asset(workspace, asset_id,
                                        [dict(r) for r in observations["observations"]],
                                        nav_path)
        nav_reference = None
        if nav_path is not None and Path(nav_path).is_file():
            nav_reference = {"filename": Path(nav_path).name, "sha256": _sha256(Path(nav_path)),
                             "lookup": "exact CBD record (ASTRA)"}
        submission = {
            "submission_id": submission_id, "owner": owner, "submitter_user_id": str(user_id),
            "asset_id": asset_id, "source_key": shared,
            "catalog_id": shared if shared.startswith("cat-") else None,
            "dataset_id": manifest.get("dataset_id"), "filename": manifest.get("filename") or "",
            "flight": manifest.get("flight"), "cbd_start": manifest.get("cbd_start"),
            "cbd_end": manifest.get("cbd_end"), "workflow": WORKFLOW, "producer": PRODUCER,
            "producer_version": producer_version(), "session_revision": int(doc["revision"]),
            "completed_at": doc.get("completed_at"), "source_version": source_version,
            "navigation": nav_reference, "observation_count": len(records),
            "positioned_count": sum(1 for r in records if _map_position(r)),
            "note": (note or "").strip()[:2000] or None, "status": "submitted",
            "submitted_at": now,
        }

        # the snapshot: written to a temporary directory, then renamed
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f".{submission_id}.tmp"
        target = self.root / submission_id
        products = {}
        try:
            tmp.mkdir()
            for product, path in outputs.items():
                path = Path(path)
                shutil.copyfile(path, tmp / path.name)
                products[product] = {"name": path.name, "bytes": path.stat().st_size,
                                     "sha256": _sha256(tmp / path.name)}
            session_file = workspace.asset_file(asset_id, ASSET_SESSION)
            shutil.copyfile(session_file, tmp / "session.json")
            snapshot = dict(observations, observations=records)
            (tmp / "observations.json").write_text(
                json.dumps(snapshot, sort_keys=True, allow_nan=False), encoding="utf-8")
            extra = georef.snapshot_files(workspace, asset_id, manifest, nav_path,
                                          dict(observations)) or {}
            if extra:
                (tmp / "georef").mkdir()
                for name, data in extra.items():
                    safe = Path(str(name)).name
                    if safe and not safe.startswith("."):
                        (tmp / "georef" / safe).write_bytes(data)
            (tmp / "provenance.json").write_text(json.dumps(
                _provenance(submission, products, records), indent=2, sort_keys=True),
                encoding="utf-8")
            # every file's hash, so damage or loss is detected before a decision
            # and after a restore (radar/backup.py)
            files = {str(p.relative_to(tmp)): _sha256(p)
                     for p in sorted(tmp.rglob("*")) if p.is_file()}
            (tmp / SNAPSHOT_MANIFEST).write_text(json.dumps(
                {"submission_id": submission_id, "files": files}, indent=1, sort_keys=True),
                encoding="utf-8")
            for path in tmp.rglob("*"):
                if path.is_file():
                    path.chmod(0o440)
            os.replace(tmp, target)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        submission["products"] = products
        columns = [k for k in submission]
        values = [json.dumps(submission[k]) if k in ("navigation", "products") else submission[k]
                  for k in columns]
        try:
            with self.catalog._connect() as db:
                db.execute(f"INSERT INTO submissions ({', '.join(columns)}) VALUES"
                           f" ({', '.join('?' for _ in columns)})", values)
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            raise
        return self.get(submission_id)

    def would_supersede(self, submission: dict) -> dict | None:
        """The published result that approving ``submission`` would replace
        (same submitter, same radar file), if any."""
        with self.catalog._connect() as db:
            row = db.execute("SELECT * FROM submissions WHERE owner = ? AND source_key = ?"
                             " AND status = 'published' AND submission_id != ?"
                             " ORDER BY published_at DESC LIMIT 1",
                             (submission["owner"], submission["source_key"],
                              submission["submission_id"])).fetchone()
        return _decode(row)

    def cancel(self, submission_id: str, owner: str) -> dict:
        """The submitter withdraws a submission that is still awaiting review."""
        submission = self.get(submission_id)
        if submission is None or submission["owner"] != owner:
            raise LookupError(submission_id)
        if submission["status"] != "submitted":
            raise ReviewError("Only a submission awaiting review can be cancelled.")
        with self.catalog._connect() as db:
            db.execute("UPDATE submissions SET status = 'cancelled', decided_at = ?"
                       " WHERE submission_id = ? AND status = 'submitted'",
                       (time.time(), submission_id))
        return self.get(submission_id)

    # ── review ───────────────────────────────────────────────────────
    def geolocation_check(self, submission: dict) -> tuple[bool, str]:
        """Whether every observation's position is verified (see
        :mod:`radar.georef` when installed); ASTRA-assigned positions are not."""
        return georef.publication_check(self.snapshot_observations(submission))

    def decide(self, submission_id: str, *, reviewer_user_id: str, decision: str,
               note: str | None = None, accept_unverified_geolocation: bool = False) -> dict:
        submission = self.get(submission_id)
        if submission is None:
            raise LookupError(submission_id)
        if str(reviewer_user_id) == submission["submitter_user_id"]:
            raise ReviewForbidden("You cannot review your own submission.")
        if decision not in DECISIONS:
            raise ReviewError("decision must be approve, return or reject.")
        note = (note or "").strip()[:2000] or None
        if decision in ("return", "reject") and not note:
            raise ReviewError("Give the submitter a reason.")
        status = DECISIONS[decision]
        accepted = False
        if status == "published":
            # publish only what was frozen at submission, intact
            self.require_intact(submission)
            if len(self.snapshot_observations(submission)) != submission["observation_count"]:
                raise SnapshotUnavailable("The snapshot's observations do not match the "
                                          "submission record.")
            ok, reason = self.geolocation_check(submission)
            if not ok and not accept_unverified_geolocation:
                raise ReviewError(f"{reason} To publish them labelled as unverified, approve "
                                  "with explicit acceptance of unverified positions (the "
                                  "review page's checkbox; API: accept_unverified_geolocation).")
            accepted = not ok
        now = time.time()
        with self.catalog._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT status FROM submissions WHERE submission_id = ?",
                                 (submission_id,)).fetchone()
            if current is None or current["status"] != "submitted":
                db.execute("ROLLBACK")
                raise ReviewError("This submission is no longer awaiting review.")
            db.execute("UPDATE submissions SET status = ?, reviewer_user_id = ?, decided_at = ?,"
                       " decision_note = ?, published_at = ?, accepted_unverified = ?"
                       " WHERE submission_id = ?",
                       (status, str(reviewer_user_id), now, note,
                        now if status == "published" else None, int(accepted), submission_id))
            if status == "published":
                self._publish(db, dict(submission, published_at=now,
                                       accepted_unverified=int(accepted)))
            db.execute("COMMIT")
        self.catalog._changed()
        return self.get(submission_id)

    def _publish(self, db, submission: dict) -> None:
        older = db.execute(
            "SELECT submission_id FROM submissions WHERE owner = ? AND source_key = ?"
            " AND status = 'published' AND submission_id != ?",
            (submission["owner"], submission["source_key"], submission["submission_id"])
        ).fetchall()
        for row in older:
            db.execute("UPDATE submissions SET status = 'superseded', superseded_by = ?"
                       " WHERE submission_id = ?", (submission["submission_id"],
                                                    row["submission_id"]))
            db.execute("DELETE FROM published_observations WHERE submission_id = ?",
                       (row["submission_id"],))
        if older:
            db.execute("UPDATE submissions SET supersedes = ? WHERE submission_id = ?",
                       (older[0]["submission_id"], submission["submission_id"]))
        rows = []
        from .observations import map_position

        for record in self.snapshot_observations(submission):
            properties = _public_observation(record, submission)
            position = map_position(record)
            feature = {"type": "Feature", "id": properties["observation_id"],
                       "geometry": {"type": "Point", "coordinates": position} if position else None,
                       "properties": properties}
            rows.append((properties["observation_id"], submission["submission_id"],
                         submission["dataset_id"], submission["catalog_id"],
                         submission["flight"], properties.get("cbd"),
                         position[0] if position else None, position[1] if position else None,
                         json.dumps(feature, sort_keys=True, allow_nan=False)))
        db.executemany("INSERT OR REPLACE INTO published_observations (observation_id,"
                       " submission_id, dataset_id, catalog_id, flight, cbd, lon, lat, feature)"
                       " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

    def withdraw(self, submission_id: str, *, user_id: str, reason: str) -> dict:
        reason = (reason or "").strip()[:2000]
        if not reason:
            raise ReviewError("Give a reason for withdrawing the published result.")
        with self.catalog._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM submissions WHERE submission_id = ?",
                             (submission_id,)).fetchone()
            if row is None:
                db.execute("ROLLBACK")
                raise LookupError(submission_id)
            if row["status"] != "published":
                db.execute("ROLLBACK")
                raise ReviewError("Only a published result can be withdrawn.")
            db.execute("UPDATE submissions SET status = 'withdrawn', withdrawn_at = ?,"
                       " withdrawn_by = ?, withdraw_reason = ? WHERE submission_id = ?",
                       (time.time(), str(user_id), reason, submission_id))
            db.execute("DELETE FROM published_observations WHERE submission_id = ?",
                       (submission_id,))
            db.execute("COMMIT")
        self.catalog._changed()
        return self.get(submission_id)

    # ── the shared, published product ────────────────────────────────
    def published(self, *, dataset_id=None, flight=None, bbox=None, limit: int = 5000) -> dict:
        from .catalog import _bbox_where

        where, args = ["lat IS NOT NULL"], []
        if dataset_id:
            where.append("dataset_id = ?")
            args.append(dataset_id)
        if flight:
            where.append("flight = ?")
            args.append(str(flight))
        where, args = _bbox_where(where, args, bbox)
        with self.catalog._connect() as db:
            rows = db.execute(f"SELECT feature FROM published_observations"
                              f" WHERE {' AND '.join(where)}"
                              f" ORDER BY dataset_id, flight, cbd, observation_id LIMIT ?",
                              args + [limit + 1]).fetchall()
            total = db.execute("SELECT COUNT(*) FROM published_observations").fetchone()[0]
        features = [json.loads(r[0]) for r in rows[:limit]]
        return {"type": "FeatureCollection", "features": features,
                "summary": {"returned": len(features), "truncated": len(rows) > limit,
                            "published_total": total}}


def _geolocation_summary(records: list[dict]) -> dict:
    statuses = [r.get("geolocation_status") or UNVERIFIED for r in records]
    counts = {status: statuses.count(status) for status in georef.STATUSES}
    verified = counts.get("verified", 0)
    return {
        "counts": counts,
        "method": ("film-label CBD confirmed by the submitter, exact-CBD navigation record"
                   if verified == len(records) and records else
                   "mixed: film-label CBD where confirmed (geolocation_status verified), "
                   "otherwise ASTRA-assigned CBD from the file-name range (unverified)"
                   if verified else
                   "ASTRA exact-CBD navigation lookup; CBDs assigned by ASTRA from the "
                   "file-name range (not verified against the CBD printed on the film)"),
    }


def _provenance(submission: dict, products: dict, records: list[dict]) -> dict:
    """The snapshot's provenance file: scientific identity, no personal data."""
    return {
        "schema": PROVENANCE_SCHEMA, "version": 1,
        "submission_id": submission["submission_id"],
        "dataset_id": submission["dataset_id"],
        "radar_asset": {"source_key": submission["source_key"],
                        "catalog_id": submission["catalog_id"],
                        "filename": submission["filename"],
                        "source_version": submission["source_version"]},
        "flight": submission["flight"],
        "cbd_range": {"start": submission["cbd_start"], "end": submission["cbd_end"],
                      "from": "file name (ASTRA)"},
        "processing": {"workflow": submission["workflow"], "producer": submission["producer"],
                       "producer_version": submission["producer_version"],
                       "session_revision": submission["session_revision"],
                       "completed_at": submission["completed_at"]},
        "navigation": submission["navigation"],
        "observations": {"count": submission["observation_count"],
                         "positioned": submission["positioned_count"],
                         "geolocation": _geolocation_summary(records)},
        "products": products,
        "created_at": submission["submitted_at"],
    }


def _decode(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    for key in ("navigation", "products"):
        item[key] = json.loads(item[key]) if item.get(key) else ({} if key == "products" else None)
    return item


#: where a user's own result stands in the review workflow, and who can see
#: its current version (private / reviewers / public)
STAGES = {
    "draft": "private", "completed": "private", "in_review": "reviewers",
    "returned": "private", "rejected": "private", "published": "public",
    "withdrawn": "private", "superseded": "private",
}


def session_version(workspace, asset_id: str) -> dict:
    """The status, revision and completion time of an asset's manual session
    (empty when there is none). Revisions restart at 0 after a reset, so a
    version is identified by revision *and* completion time."""
    path = workspace.asset_file(asset_id, ASSET_SESSION)
    if path.is_symlink() or not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {"status": "completed" if doc.get("status") == "completed" else "draft",
            "revision": doc.get("revision"), "completed_at": doc.get("completed_at")}


def same_version(submission: dict, revision, completed_at) -> bool:
    """Whether a submission froze this session version (see
    :func:`session_version`)."""
    return (submission.get("session_revision") == revision
            and submission.get("completed_at") == completed_at)


def result_stage(session: dict, submissions: list[dict]) -> dict:
    """The review stage of one asset's result (derived, never stored).

    ``session`` is :func:`session_version` of the asset and ``submissions``
    its submissions, newest first. A published version that was edited or
    reset afterwards is reported as the private work it now is, with the
    published version named, so later edits are never shown as reviewed."""
    live = [s for s in submissions if s.get("status") != "cancelled"]
    latest = live[0] if live else None
    status = session.get("status")
    current = status if status in ("draft", "completed") else "draft"
    changed = bool(latest) and not same_version(latest, session.get("revision"),
                                                session.get("completed_at"))
    if latest is None:
        stage = current
    elif latest["status"] == "submitted":
        stage = "in_review"
    elif latest["status"] == "published":
        stage = current if changed else "published"
    else:
        stage = latest["status"] if latest["status"] in STAGES else current
    published = next((s for s in live if s["status"] == "published"), None)
    return {
        "stage": stage, "visibility": STAGES[stage],
        "submission_id": latest["submission_id"] if latest else None,
        "submitted_revision": latest.get("session_revision") if latest else None,
        "changed_since_submission": changed,
        "published_submission_id": published["submission_id"] if published else None,
        "published_revision": published.get("session_revision") if published else None,
    }


def public_submission(submission: dict, *, reviewer: bool = False) -> dict:
    """A submission for its owner or a reviewer; account IDs only for reviewers."""
    keys = ("submission_id", "asset_id", "catalog_id", "dataset_id", "filename", "flight",
            "cbd_start", "cbd_end", "workflow", "producer", "producer_version",
            "session_revision", "completed_at", "source_version", "navigation",
            "observation_count", "positioned_count", "note", "status", "submitted_at",
            "decided_at", "decision_note", "published_at", "supersedes", "superseded_by",
            "withdrawn_at", "withdraw_reason", "accepted_unverified")
    out = {k: submission.get(k) for k in keys}
    out["products"] = {k: {"name": v["name"], "bytes": v["bytes"], "sha256": v["sha256"]}
                       for k, v in (submission.get("products") or {}).items()}
    if reviewer:
        out["submitter"] = submission["submitter_user_id"]
        out["reviewer"] = submission.get("reviewer_user_id")
        out["withdrawn_by"] = submission.get("withdrawn_by")
    return out
