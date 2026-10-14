"""Manual (ASTRA) picking sessions on radar assets.

The session lives in the asset directory::

    radar/<asset_id>/session.json        ASTRA picking state (atomic writes)
    radar/<asset_id>/outputs/<stem>.csv      ASTRA CSV (rewritten on Next A-scope and Done)
    radar/<asset_id>/outputs/<stem>_QC.png   ASTRA QC image (written on Done)

``session.json`` holds only picking state: ASTRA's per-TIFF variables, pick
provenance, a revision counter and the session status. It never contains
identities or filesystem paths. A session file that fails validation is
treated as unusable (the user can reset it); it never breaks the asset.

All functions are blocking; the server runs them in an executor under a
per-asset lock.
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path

import numpy as np
from PIL import Image

from ..pickers.astra import (
    CSV_COLUMNS,
    FEATURES,
    STATE_FIELDS,
    SWEEP_RATES,
    ZOOM_WIDTH,
    AstraError,
    AstraGeometry,
    AstraSession,
    astra_csv_text,
    astra_trace,
    astra_window,
    save_qc_image,
)
from ..workspace import ASSET_OUTPUTS, ASSET_SESSION, FrozenLegaciesWorkspace
from .render import RadarImageCache, RenderedWindowCache, _block_mean_columns, _block_mean_rows


SESSION_SCHEMA = "cryostack.frozen_legacies.astra_session"
SESSION_VERSION = 1
STATUSES = ("in_progress", "completed")
MAX_SESSION_BYTES = 4 * 1024 * 1024
MAX_ROWS = 20_000

#: downloadable manual-picker products and their file suffixes
PRODUCTS = {"astra-csv": ".csv", "astra-qc": "_QC.png"}

#: display downsampling of the working window PNG (display only)
DISPLAY_SCALE = 2


class SessionInvalid(ValueError):
    """``session.json`` exists but cannot be trusted."""


class SessionConflict(RuntimeError):
    """The client acted on an out-of-date revision, or a finished session."""


# ── names ────────────────────────────────────────────────────────────
_UNSAFE_STEM = re.compile(r"[^A-Za-z0-9._-]+")


def output_stem(filename: str) -> str:
    """ASTRA's ``current_filename`` (the TIFF basename without extension),
    reduced to characters allowed in workspace output names."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    safe = _UNSAFE_STEM.sub("_", stem).lstrip("._-")[:180]
    return safe or "radar"


def product_name(filename: str, product: str) -> str:
    return output_stem(filename) + PRODUCTS[product]


# ── atomic files ─────────────────────────────────────────────────────
def _atomic_write(path: Path, writer) -> None:
    """Write via a temporary sibling and ``os.replace`` it into place."""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        writer(tmp)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _outputs_dir(workspace: FrozenLegaciesWorkspace, asset_id: str) -> Path:
    directory = workspace.asset_dir(asset_id) / ASSET_OUTPUTS
    if directory.is_symlink() or not directory.is_dir():
        raise PermissionError("The outputs directory is not usable.")
    return workspace.contain(directory)


def output_path(workspace: FrozenLegaciesWorkspace, asset_id: str, name: str) -> Path:
    _outputs_dir(workspace, asset_id)
    path = workspace.output_file(asset_id, name)
    if path.is_symlink():
        raise PermissionError("Output files may not be symbolic links.")
    return path


def existing_output(workspace, asset_id: str, filename: str, product: str) -> Path | None:
    path = output_path(workspace, asset_id, product_name(filename, product))
    if os.path.lexists(path) and (path.is_symlink() or not path.is_file()):
        raise PermissionError("Output files must be regular files.")
    return path if path.is_file() else None


# ── session document ─────────────────────────────────────────────────
def new_document(asset_id: str, session: AstraSession) -> dict:
    now = time.time()
    return {
        "schema": SESSION_SCHEMA,
        "version": SESSION_VERSION,
        "asset_id": asset_id,
        "picker": "astra",
        "status": "in_progress",
        "revision": 0,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "state": session.to_state(),
    }


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _check(condition: bool, what: str) -> None:
    if not condition:
        raise SessionInvalid(what)


def _check_coords(value, geometry: AstraGeometry, name: str) -> None:
    if value is None:
        return
    _check(isinstance(value, list) and len(value) == 4 and all(_is_int(v) for v in value), name)
    x_zoom, y_zoom, x_orig, y_orig = value
    _check(0 <= x_zoom < ZOOM_WIDTH and 0 <= y_zoom < geometry.zoom_height, name)
    _check(0 <= x_orig < geometry.padded_width, name)
    _check(250 <= y_orig < 250 + geometry.zoom_height, name)


def _check_points(values, limit: float, name: str, max_len: int) -> None:
    _check(isinstance(values, list) and len(values) <= max_len, name)
    for v in values:
        _check(_is_number(v) and -0.5 <= v < limit, name)


def validate_document(doc, asset_id: str, geometry: AstraGeometry, filename: str) -> dict:
    """Reject anything ASTRA itself could not have produced."""
    _check(isinstance(doc, dict), "document")
    _check(doc.get("schema") == SESSION_SCHEMA and doc.get("version") == SESSION_VERSION, "schema")
    _check(doc.get("asset_id") == asset_id and doc.get("picker") == "astra", "asset")
    _check(doc.get("status") in STATUSES, "status")
    _check(_is_int(doc.get("revision")) and doc["revision"] >= 0, "revision")
    state = doc.get("state")
    _check(isinstance(state, dict), "state")
    _check(set(state) == set(STATE_FIELDS) | {"pick_sources", "row_sources"}, "state keys")

    s = state
    _check(_is_int(s["slider"]) and 0 <= s["slider"] <= geometry.slider_max, "slider")
    _check(s["sweep_rate"] in SWEEP_RATES and _is_int(s["sweep_rate"]), "sweep_rate")
    _check(_is_int(s["current_scope"]) and 1 <= s["current_scope"] <= MAX_ROWS + 1, "current_scope")
    _check(s["cbd_title_override"] is None or _is_int(s["cbd_title_override"]), "cbd")
    _check(s["current_feature"] is None or s["current_feature"] in FEATURES, "feature")
    for key in ("can_click", "feature_selected", "setting_reference_line",
                "setting_x_reference_line", "setting_y_axis", "setting_x_axis"):
        _check(isinstance(s[key], bool), key)
    for key in ("surface_coords", "bed_coords", "noisefloor_coords", "mainbang_coords"):
        _check_coords(s[key], geometry, key)
    for key, limit in (("reference_line_y", geometry.zoom_height), ("x_reference_line", ZOOM_WIDTH)):
        _check(s[key] is None or (_is_int(s[key]) and 0 <= s[key] < limit), key)
    _check(s["reference_line_y_orig"] is None or _is_int(s["reference_line_y_orig"]), "ref_y_orig")
    _check(s["x_reference_line_orig"] is None or _is_int(s["x_reference_line_orig"]), "ref_x_orig")
    _check_points(s["y_axis_points"], geometry.zoom_height - 0.5, "y_axis_points", 4)
    _check_points(s["x_axis_points"], ZOOM_WIDTH - 0.5, "x_axis_points", 4)
    for key in ("y_axis_lines", "x_axis_lines", "y_axis_labels", "x_axis_labels"):
        _check(isinstance(s[key], list) and len(s[key]) <= 64
               and all(_is_number(v) for v in s[key]), key)
    _check(len(s["y_axis_lines"]) == len(s["y_axis_labels"]), "y axis")
    _check(len(s["x_axis_lines"]) == len(s["x_axis_labels"]), "x axis")
    for key, limit in (("current_y_axis_pick", geometry.zoom_height - 0.5),
                       ("current_x_axis_pick", ZOOM_WIDTH - 0.5)):
        _check(s[key] is None or (_is_number(s[key]) and -0.5 <= s[key] < limit), key)

    rows = s["data"]
    _check(isinstance(rows, list) and len(rows) <= MAX_ROWS, "data")
    basename = os.path.basename(filename)
    for row in rows:
        _check(isinstance(row, list) and len(row) == len(CSV_COLUMNS), "row")
        _check(_is_int(row[0]) and row[20] == basename and row[21] in SWEEP_RATES, "row")
        for value in row[1:20]:
            _check(value == "" or _is_number(value)
                   or (isinstance(value, str) and len(value) <= 32), "row value")
    _check(isinstance(s["all_ascope_picks"], list) and len(s["all_ascope_picks"]) == len(rows), "picks")
    _check(isinstance(s["row_sources"], list) and len(s["row_sources"]) == len(rows), "row sources")
    _check(isinstance(s["pick_sources"], dict)
           and set(s["pick_sources"]) <= {"surface", "bed", "noisefloor", "mainbang"}
           and set(s["pick_sources"].values()) <= {"manual", "suggested"}, "pick sources")
    return doc


def load_document(workspace, asset_id: str, geometry: AstraGeometry, filename: str) -> dict | None:
    path = workspace.asset_file(asset_id, ASSET_SESSION)
    if path.is_symlink():
        raise SessionInvalid("session file is a link")
    if not path.exists():
        return None
    if path.stat().st_size > MAX_SESSION_BYTES:
        raise SessionInvalid("session file too large")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SessionInvalid("session file unreadable")
    return validate_document(doc, asset_id, geometry, filename)


def save_document(workspace, asset_id: str, doc: dict) -> None:
    path = workspace.asset_file(asset_id, ASSET_SESSION)
    if path.is_symlink():
        raise SessionInvalid("session file is a link")
    text = json.dumps(doc, sort_keys=True, allow_nan=False)
    _atomic_write(path, lambda tmp: tmp.write_text(text, encoding="utf-8"))


# ── working-window cache ─────────────────────────────────────────────
class AstraViewCache:
    """Traces and display PNGs of ASTRA working windows, by file and slider.

    Windows are cut from the decoded-image cache; nothing is re-read from disk.
    """

    def __init__(self, images: RadarImageCache, windows: RenderedWindowCache,
                 max_traces: int = 256):
        self.images = images
        self.windows = windows
        self.max_traces = max_traces
        self._traces: "OrderedDict[tuple, np.ndarray]" = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _key(path: Path, slider: int) -> tuple:
        path = Path(path).resolve()
        stat = path.stat()
        return ("astra", str(path), stat.st_mtime_ns, stat.st_size, slider)

    def _compute(self, path: Path, geometry: AstraGeometry, slider: int):
        pixels = self.images.get(path).pixels
        smoothed, trace_y = astra_trace(astra_window(pixels, geometry, slider))
        return smoothed, trace_y

    def trace(self, path: Path, geometry: AstraGeometry, slider: int) -> np.ndarray:
        key = self._key(path, slider)
        with self._lock:
            if key in self._traces:
                self._traces.move_to_end(key)
                return self._traces[key]
        smoothed, trace_y = self._compute(path, geometry, slider)
        self._remember(key, trace_y)
        self.windows.put(key, _display_png(smoothed))
        return trace_y

    def png(self, path: Path, geometry: AstraGeometry, slider: int) -> bytes:
        key = self._key(path, slider)
        cached = self.windows.get(key)
        if cached is not None:
            return cached
        smoothed, trace_y = self._compute(path, geometry, slider)
        self._remember(key, trace_y)
        data = _display_png(smoothed)
        self.windows.put(key, data)
        return data

    def _remember(self, key, trace_y) -> None:
        with self._lock:
            self._traces[key] = trace_y
            self._traces.move_to_end(key)
            while len(self._traces) > self.max_traces:
                self._traces.popitem(last=False)


def _display_png(smoothed: np.ndarray) -> bytes:
    """The smoothed window as ASTRA shows it (``imshow(..., cmap='gray')``,
    stretched to the window's own min/max), downsampled for transfer."""
    reduced = _block_mean_rows(_block_mean_columns(smoothed, DISPLAY_SCALE), DISPLAY_SCALE)
    low, high = float(smoothed.min()), float(smoothed.max())
    span = high - low if high > low else 1.0
    out = np.clip(np.rint((reduced - low) * (255.0 / span)), 0, 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(out, mode="L").save(buffer, format="PNG", compress_level=3)
    return buffer.getvalue()


# ── actions ──────────────────────────────────────────────────────────
SETUP_ACTIONS = {
    "x_reference": "setup_x_reference_line",
    "y_reference": "setup_reference_line",
    "y_axis": "setup_y_axis",
    "x_axis": "setup_x_axis",
}
STEPS = ("left", "right", "jump")


def _coordinate(value, limit: float, name: str) -> float:
    if not _is_number(value):
        raise AstraError(f"{name} must be a finite number")
    value = float(value)
    if not -0.5 <= value < limit:
        raise AstraError(f"{name} is outside the ASTRA working window")
    return value


def apply_action(session: AstraSession, payload: dict, trace_for) -> str:
    """Apply one client action; returns its kind. ``trace_for(slider)``
    returns the working-window trace at a slider position."""
    action = payload.get("action")
    g = session.geometry
    if action == "setup":
        target = payload.get("target")
        if target not in SETUP_ACTIONS:
            raise AstraError("Unknown setup target.")
        getattr(session, SETUP_ACTIONS[target])()
    elif action == "sweep_rate":
        rate = payload.get("rate")
        if not _is_int(rate):
            raise AstraError("Sweep rate must be 1, 2 or 5.")
        session.set_sweep_rate(rate)
    elif action == "select":
        feature = payload.get("feature")
        if feature not in FEATURES:
            raise AstraError("Unknown feature.")
        session.select_feature(feature)
    elif action == "click":
        x = _coordinate(payload.get("x"), ZOOM_WIDTH - 0.5, "x")
        y = _coordinate(payload.get("y"), g.zoom_height - 0.5, "y")
        session.on_click(x, y, trace_for(session.slider))
    elif action == "move":
        slider = payload.get("slider")
        if not _is_int(slider):
            raise AstraError("X position must be an integer.")
        session.move(slider)
    elif action == "step":
        if payload.get("step") not in STEPS:
            raise AstraError("Unknown step.")
        session.step(payload["step"])
    elif action == "suggest":
        session.suggest_picks(trace_for(session.slider))
    elif action == "next":
        session.next_ascope()
    else:
        raise AstraError("Unknown action.")
    return action


def write_csv(workspace, asset_id: str, filename: str, data, nav_path) -> None:
    text = astra_csv_text(data, filename, nav_path)
    path = output_path(workspace, asset_id, product_name(filename, "astra-csv"))
    _atomic_write(path, lambda tmp: tmp.write_text(text, encoding="utf-8"))


#: full-resolution QC images are written one at a time (each holds the whole
#: TIFF in memory while Pillow draws and encodes it)
_QC_WRITES = threading.BoundedSemaphore(1)


def write_outputs(workspace, asset_id: str, filename: str, data, tiff_path, nav_path) -> None:
    """Write CSV and QC so that either both are replaced or neither is."""
    csv_path = output_path(workspace, asset_id, product_name(filename, "astra-csv"))
    qc_path = output_path(workspace, asset_id, product_name(filename, "astra-qc"))
    token = uuid.uuid4().hex
    csv_tmp = csv_path.with_name(f".{csv_path.name}.{token}.tmp")
    qc_tmp = qc_path.with_name(f".{qc_path.name}.{token}.tmp")
    try:
        csv_tmp.write_text(astra_csv_text(data, filename, nav_path), encoding="utf-8")
        with _QC_WRITES:
            save_qc_image(tiff_path, data, qc_tmp)
        os.replace(qc_tmp, qc_path)
        os.replace(csv_tmp, csv_path)
    finally:
        for tmp in (csv_tmp, qc_tmp):
            if tmp.exists():
                tmp.unlink()


def remove_outputs(workspace, asset_id: str, filename: str) -> None:
    for product in PRODUCTS:
        path = output_path(workspace, asset_id, product_name(filename, product))
        if os.path.lexists(path):
            path.unlink()


# ── response ─────────────────────────────────────────────────────────
def csv_preview(data, filename: str, nav_path) -> dict:
    """The committed rows exactly as they appear in the ASTRA CSV."""
    import csv

    if not data:
        return {"columns": [], "rows": []}
    reader = csv.reader(io.StringIO(astra_csv_text(data, filename, nav_path)))
    rows = list(reader)
    return {"columns": rows[0], "rows": rows[1:]}


def describe(session: AstraSession, doc: dict | None, trace_y, *, nav_path, outputs: dict) -> dict:
    s = session.to_state()
    picks = {}
    for field in ("surface", "bed", "noisefloor", "mainbang"):
        coords = s[f"{field}_coords"]
        picks[field] = None if coords is None else {
            "x_zoom": coords[0], "y_zoom": coords[1], "x_orig": coords[2], "y_orig": coords[3],
            "us": session.us(coords[0]), "db": session.db(coords[1]),
            "source": s["pick_sources"].get(field, "manual"),
        }
    return {
        "status": doc["status"] if doc else "new",
        "revision": doc["revision"] if doc else 0,
        "completed_at": doc.get("completed_at") if doc else None,
        "geometry": session.geometry.public(),
        "title": session.title(),
        "state": s,
        "picks": _plain(picks),
        "trace": [int(v) for v in trace_y],
        "committed": csv_preview(session.state["data"], session.filename, nav_path),
        "messages": list(session.messages),
        "outputs": outputs,
        "products": {p: product_name(session.filename, p) for p in PRODUCTS},
    }


def _plain(value):
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value
