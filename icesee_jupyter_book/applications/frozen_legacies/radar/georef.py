"""CBD provenance and georeferencing of picked A-scopes.

Why this exists
---------------
ASTRA assigns each committed A-scope a CBD by spreading the CBD range from
the file name over the committed rows (``int(start + (end - start) * i /
(n - 1))``) and takes LAT/LON from the navigation record with exactly that
CBD. That model assumes the scan holds a complete, consecutive CBD range and
that rows map evenly onto it. On the development film F127
(``F127-C0471_C0483.tiff``) the CBDs printed on the frames read 471-475,
478-484: 476 and 477 are absent and 484 is present, so ASTRA's CBDs -- and
positions -- for later frames are two CBDs (about 4 km) off, and much more
when fewer A-scopes than frames are committed.

Neither source carries the missing mapping: the radar TIFFs have only
baseline TIFF tags (no frame, CBD or time metadata) and the navigation files
are CBD-indexed records (``CBD,LAT,LON,THK,SRF``) with no relation to image
columns. The only reliable evidence is the label printed on the film frame,
so the CBD of an A-scope is *confirmed by the user* reading that label.
Nothing is inferred: CBDs are never assumed sequential and missing labels
are never filled in.

What it does
------------
The canonical ASTRA products (CSV, QC) and the user's ``observations.json``
are never changed. This module keeps, per asset, ``georef.json`` in the
user's workspace with one entry per confirmed A-scope, and derives for every
observation:

=====================  =====================================================
``astra_cbd``          the CBD ASTRA assigned (``cbd`` of the record)
``astra_position``     ASTRA's navigation position for ``astra_cbd``
``film_cbd``           the CBD read from the film frame label, or ``None``
``film_cbd_source``    ``user_reading`` (the only source today)
``verified_cbd``       ``film_cbd`` once the user confirmed it, else ``None``
``verified_position``  the navigation record of ``verified_cbd`` (exact
                       CBD, ASTRA's lookup), or ``None``
``cbd_source``         ``astra_row_order`` or ``film_label_confirmed``
``georef_method``      ``astra_row_order_nav_exact`` (unverified) or
                       ``film_label_nav_exact`` (verified)
``geolocation_status`` ``unverified`` | ``verified`` |
                       ``verified_no_navigation`` | ``label_unreadable``
``cbd_differs``        the confirmed CBD differs from ASTRA's
=====================  =====================================================

An entry is bound to its A-scope by number *and* picker window
(``window_x``) and to the session it was made in, so a reset or a re-picked
A-scope never inherits an old confirmation.

The separately identified, reproducible product is the georeferenced CSV
(:func:`georef_csv`): deterministic content from the observations, the
confirmations and the navigation file, with provenance (hashes of the
ASTRA CSV, the navigation file and the confirmations) in
:func:`provenance`.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import time
from pathlib import Path

from ..workspace import ASSET_SESSION, FrozenLegaciesWorkspace
from . import manual


SCHEMA = "cryostack.frozen_legacies.georef"
VERSION = 1
FILENAME = "georef.json"
PRODUCT = "georef-csv"
METHOD_UNVERIFIED = "astra_row_order_nav_exact"
METHOD_VERIFIED = "film_label_nav_exact"
STATUSES = ("unverified", "verified", "verified_no_navigation", "label_unreadable")
MAX_CBD = 99_999
MAX_NOTE = 300

CSV_COLUMNS = (
    "a_scope", "window_x", "flight",
    "astra_cbd", "astra_lat", "astra_lon",
    "film_cbd", "film_cbd_source", "verified_cbd", "verified_lat", "verified_lon",
    "cbd_source", "georef_method", "geolocation_status",
    "surface_us", "bed_us", "surface_m", "bed_m", "h_ice_m",
)


class GeorefError(ValueError):
    """A confirmation that cannot be accepted (message is safe to show)."""


# ── storage ──────────────────────────────────────────────────────────
def _path(workspace: FrozenLegaciesWorkspace, asset_id: str) -> Path:
    # in the user's (validated, contained) asset directory; the file itself is
    # never followed if it is a link (load ignores it, writes refuse it)
    return workspace.asset_dir(asset_id) / FILENAME


def session_key(workspace: FrozenLegaciesWorkspace, asset_id: str) -> str | None:
    """Identity of the current manual session (its creation time)."""
    path = workspace.asset_file(asset_id, ASSET_SESSION)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        created = json.loads(path.read_text(encoding="utf-8")).get("created_at")
    except (OSError, ValueError):
        return None
    return repr(float(created)) if isinstance(created, (int, float)) else None


def load(workspace: FrozenLegaciesWorkspace, asset_id: str) -> dict | None:
    path = _path(workspace, asset_id)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(doc, dict) or doc.get("schema") != SCHEMA
            or doc.get("asset_id") != asset_id or not isinstance(doc.get("entries"), dict)):
        return None
    return doc


def _write(workspace, asset_id: str, doc: dict) -> None:
    path = _path(workspace, asset_id)
    if path.is_symlink():
        raise PermissionError("georef.json may not be a link.")
    text = json.dumps(doc, sort_keys=True, allow_nan=False)
    manual._atomic_write(path, lambda tmp: tmp.write_text(text, encoding="utf-8"))


def remove(workspace, asset_id: str) -> None:
    path = _path(workspace, asset_id)
    if path.exists() or path.is_symlink():
        path.unlink()


# ── confirmations ────────────────────────────────────────────────────
def _current(doc: dict | None, session: str | None) -> dict:
    """Entries made in the current session (others are stale)."""
    if not doc or doc.get("session") != session:
        return {}
    return doc["entries"]


def record_label(workspace, asset_id: str, records: list[dict], *, a_scope, action: str,
                 film_cbd=None, note=None) -> dict:
    """Confirm (``confirm``), mark unreadable (``unreadable``) or clear
    (``clear``) the film-frame CBD of one committed A-scope."""
    if action not in ("confirm", "unreadable", "clear"):
        raise GeorefError("action must be 'confirm', 'unreadable' or 'clear'.")
    if isinstance(a_scope, bool) or not isinstance(a_scope, int):
        raise GeorefError("a_scope must be an A-scope number.")
    record = next((r for r in records if r.get("a_scope") == a_scope), None)
    if record is None:
        raise GeorefError("That A-scope has not been committed in this session.")
    session = session_key(workspace, asset_id)
    if session is None:
        raise GeorefError("This asset has no manual session.")
    doc = load(workspace, asset_id)
    entries = dict(_current(doc, session))
    key = str(a_scope)
    if action == "clear":
        entries.pop(key, None)
    else:
        entry = {"window_x": record.get("window_x"), "updated_at": time.time(),
                 "film_cbd_source": "user_reading"}
        if action == "confirm":
            if isinstance(film_cbd, bool) or not isinstance(film_cbd, int) \
                    or not 0 <= film_cbd <= MAX_CBD:
                raise GeorefError(f"The film CBD must be a whole number from 0 to {MAX_CBD}.")
            entry.update(label="confirmed", film_cbd=film_cbd)
        else:
            entry.update(label="unreadable", film_cbd=None)
        if note:
            entry["note"] = str(note)[:MAX_NOTE]
        entries[key] = entry
    new = {"schema": SCHEMA, "version": VERSION, "asset_id": asset_id, "session": session,
           "revision": (doc or {}).get("revision", 0) + 1 if doc and doc.get("session") == session
           else 1, "entries": entries}
    _write(workspace, asset_id, new)
    return new


# ── derivation ───────────────────────────────────────────────────────
def _float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _position(lat, lon):
    lat, lon = _float(lat), _float(lon)
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 360):
        return None
    return [lon if lon <= 180 else lon - 360, lat]


class _Navigation:
    """ASTRA's exact-CBD navigation lookup (same semantics as its CSV)."""

    def __init__(self, nav_path):
        from ..pickers.astra import load_flight_coordinates

        self.frame = load_flight_coordinates(str(nav_path)) if nav_path else None

    def position(self, cbd):
        from ..pickers.astra import get_coordinates_for_cbd

        if cbd is None or self.frame is None:
            return None
        lat, lon = get_coordinates_for_cbd(self.frame, cbd)
        return _position(lat, lon)


def annotate(records: list[dict], georef_doc: dict | None, nav_path, *,
             session: str | None = None) -> list[dict]:
    """Copies of observation records with the georeferencing fields (see
    module docstring). ASTRA's own fields are left exactly as they are."""
    entries = georef_doc["entries"] if georef_doc and (
        session is None or georef_doc.get("session") == session) else {}
    nav = None
    out = []
    for record in records:
        item = dict(record)
        astra_cbd = record.get("cbd")
        item["astra_cbd"] = astra_cbd
        item["astra_position"] = record.get("position")
        entry = entries.get(str(record.get("a_scope")))
        if entry is not None and entry.get("window_x") != record.get("window_x"):
            entry = None                        # the A-scope was re-picked
        item.update(film_cbd=None, film_cbd_source=None, verified_cbd=None,
                    verified_position=None, cbd_source="astra_row_order",
                    georef_method=METHOD_UNVERIFIED, geolocation_status="unverified",
                    cbd_differs=False)
        if entry is not None and entry.get("label") == "unreadable":
            item.update(film_cbd_source=entry.get("film_cbd_source"),
                        geolocation_status="label_unreadable")
        elif entry is not None and entry.get("label") == "confirmed":
            if nav is None:
                nav = _Navigation(nav_path)
            verified = int(entry["film_cbd"])
            position = nav.position(verified)
            item.update(film_cbd=verified, film_cbd_source=entry.get("film_cbd_source"),
                        verified_cbd=verified, verified_position=position,
                        cbd_source="film_label_confirmed", georef_method=METHOD_VERIFIED,
                        geolocation_status="verified" if position else "verified_no_navigation",
                        cbd_differs=astra_cbd != verified)
        out.append(item)
    return out


def annotate_asset(workspace, asset_id: str, records: list[dict], nav_path) -> list[dict]:
    return annotate(records, load(workspace, asset_id), nav_path,
                    session=session_key(workspace, asset_id))


def warnings_for(annotated: list[dict], manifest: dict) -> list[str]:
    """Plausibility notes for the user and reviewers (never corrections)."""
    out = []
    start, end = manifest.get("cbd_start"), manifest.get("cbd_end")
    confirmed = sorted((r for r in annotated if r["verified_cbd"] is not None),
                       key=lambda r: (r.get("window_x") is None, r.get("window_x") or 0))
    for r in confirmed:
        if start is not None and end is not None and not (
                min(start, end) - 2 <= r["verified_cbd"] <= max(start, end) + 2):
            out.append(f"A-scope {r['a_scope']}: film CBD {r['verified_cbd']} is outside the "
                       f"file name's range {start}-{end}; check the label.")
        if r["geolocation_status"] == "verified_no_navigation":
            out.append(f"A-scope {r['a_scope']}: the navigation has no position for CBD "
                       f"{r['verified_cbd']}.")
    cbds = [r["verified_cbd"] for r in confirmed if r.get("window_x") is not None]
    if any(b < a for a, b in zip(cbds, cbds[1:])) and any(b > a for a, b in zip(cbds, cbds[1:])):
        out.append("Confirmed film CBDs do not change monotonically along the image; "
                   "check the labels.")
    return out


def summary(annotated: list[dict]) -> dict:
    counts = {status: 0 for status in STATUSES}
    for r in annotated:
        counts[r["geolocation_status"]] += 1
    counts["total"] = len(annotated)
    counts["cbd_differs"] = sum(1 for r in annotated if r["cbd_differs"])
    return counts


def publication_check(records: list[dict]) -> tuple[bool, str]:
    """Whether every observation has a verified geolocation."""
    if not records:
        return False, "There are no observations."
    statuses = [r.get("geolocation_status") or "unverified" for r in records]
    unverified = sum(1 for s in statuses if s != "verified")
    if unverified:
        return False, (f"{unverified} of {len(records)} observations have no verified "
                       "geolocation (film CBD not confirmed, unreadable, or without "
                       "navigation); their positions are ASTRA-assigned and unverified.")
    return True, "Every observation's CBD was confirmed from the film label and has navigation."


# ── product ──────────────────────────────────────────────────────────
def _cell(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    return str(value)


def georef_csv(annotated: list[dict]) -> bytes:
    """The georeferenced observations as CSV (deterministic, no timestamps)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for r in annotated:
        astra = r.get("astra_position") or [None, None]
        verified = r.get("verified_position") or [None, None]
        writer.writerow([_cell(v) for v in (
            r.get("a_scope"), r.get("window_x"), r.get("flight"),
            r.get("astra_cbd"), astra[1], astra[0],
            r.get("film_cbd"), r.get("film_cbd_source"), r.get("verified_cbd"),
            verified[1], verified[0],
            r.get("cbd_source"), r.get("georef_method"), r.get("geolocation_status"),
            r.get("surface_us"), r.get("bed_us"), r.get("surface_m"), r.get("bed_m"),
            r.get("h_ice_m"))])
    return buffer.getvalue().encode("utf-8")


def product_name(filename: str) -> str:
    return f"{manual.output_stem(filename)}_georef.csv"


def _sha256(path) -> str | None:
    if path is None:
        return None
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def provenance(workspace, asset_id: str, manifest: dict, nav_path, observations_doc: dict,
               georef_doc: dict | None, csv_bytes: bytes) -> dict:
    """How the georeferenced product was made (no personal data)."""
    filename = manifest.get("filename") or ""
    astra_csv = manual.existing_output(workspace, asset_id, filename, "astra-csv")
    return {
        "schema": "cryostack.frozen_legacies.georef_product", "version": VERSION,
        "product": PRODUCT, "name": product_name(filename),
        "sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "asset_id": asset_id, "dataset_id": manifest.get("dataset_id"),
        "catalog_id": (manifest.get("shared_source") or "")
        if str(manifest.get("shared_source") or "").startswith("cat-") else None,
        "filename": filename, "flight": manifest.get("flight"),
        "picker": "astra", "workflow": "astra-manual",
        "session_revision": observations_doc.get("session_revision"),
        "georef_revision": (georef_doc or {}).get("revision"),
        "georef_sha256": hashlib.sha256(json.dumps(
            (georef_doc or {}).get("entries") or {}, sort_keys=True).encode()).hexdigest(),
        "astra_csv_sha256": _sha256(astra_csv),
        "navigation_sha256": _sha256(nav_path),
        "methods": {
            METHOD_UNVERIFIED: "ASTRA's CBD (file-name range spread by committed-row order) "
                               "and its exact-CBD navigation record; not verified.",
            METHOD_VERIFIED: "CBD read from the film frame label and confirmed by the user; "
                             "position from the exact-CBD navigation record.",
        },
        "columns": list(CSV_COLUMNS),
    }


def snapshot_files(workspace, asset_id: str, manifest: dict, nav_path,
                   observations_doc: dict) -> dict[str, bytes]:
    """Files describing the georeferencing, for an immutable review snapshot."""
    doc = load(workspace, asset_id)
    session = session_key(workspace, asset_id)
    annotated = annotate(observations_doc.get("observations") or [], doc, nav_path,
                         session=session)
    data = georef_csv(annotated)
    current = dict(doc, entries=_current(doc, session)) if doc else None
    return {
        FILENAME: json.dumps(current or {"schema": SCHEMA, "version": VERSION,
                                         "asset_id": asset_id, "entries": {}},
                             sort_keys=True, indent=1).encode(),
        product_name(manifest.get("filename") or ""): data,
        "georef_provenance.json": json.dumps(
            provenance(workspace, asset_id, manifest, nav_path, observations_doc, current, data),
            sort_keys=True, indent=1).encode(),
    }
