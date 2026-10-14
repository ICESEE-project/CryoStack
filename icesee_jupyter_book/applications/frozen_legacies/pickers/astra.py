"""Headless port of the ASTRA manual A-scope picker.

Reference implementation: ``Pickers/ASTRA_MAC.py`` (Angelo Tarzona, Georgia
Institute of Technology; documentation dated 2026-09-11). That script is not
modified and stays the authority. This module reproduces its scientific and
bookkeeping behaviour without the Tk/matplotlib GUI:

* functions keep ASTRA's names and expressions, with ASTRA's module globals
  turned into parameters or into fields of :class:`AstraSession`;
* :class:`AstraSession` methods correspond one-to-one to ASTRA's GUI
  callbacks (``on_click``, ``setup_y_axis``, ``next_ascope`` ...), applied
  in the same order with the same guards;
* behaviour that may look questionable is kept on purpose and marked
  "ASTRA compatibility" -- it is to be reviewed separately, not fixed here.

Parity with the reference is checked by the test suite, which executes the
original ASTRA functions headlessly and compares results.

Coordinates follow ASTRA. A click arrives as matplotlib *data* coordinates
(``xdata``, ``ydata``) of the displayed working window, in which pixel
``i`` is centred on ``i`` and spans ``[i - 0.5, i + 0.5)``; ASTRA converts
them with ``int()``.
"""
from __future__ import annotations

import copy
import os
import textwrap  # noqa: F401  (kept for parity with ASTRA's QC helpers)
from dataclasses import dataclass

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter

from ..radar.ingest import extract_flight_info


# ── ASTRA constants ──────────────────────────────────────────────────
#: rows displayed: ``img.crop((0, 250, width, 1800))`` (or the image bottom)
CROP_START_Y = 250
CROP_END_Y = 1800
#: width of the working window (``zoom_width``)
ZOOM_WIDTH = 2300
#: white columns appended on the right (``padding_x = zoom_width - 200``)
PADDING_X = ZOOM_WIDTH - 200
#: trace detection (``process_and_trace``)
TRACE_SIGMA = 4
TRACE_PERCENTILE = 10
#: radar velocity in ice used for the metre columns (``save_to_csv``)
ICE_VELOCITY_M_PER_US = 168
SWEEP_RATES = (1, 2, 5)
DEFAULT_SWEEP_RATE = 2

FEATURES = ("Surface", "No Surface", "Bed", "No Bed", "Noise Floor", "Main Bang")

#: ASTRA's output CSV columns, in order (``save_to_csv``)
CSV_COLUMNS = [
    "A-scope Number",
    "FLT",
    "x_surface_px", "y_surface_px",
    "x_bed_px", "y_bed_px",
    "x_noisefloor_px", "y_noisefloor_px",
    "x_mainbang_px", "y_mainbang_px",
    "reference_line_y",
    "reference_line_x",
    "surface_us", "surface_dB",
    "bed_us", "bed_dB",
    "noisefloor_us", "noisefloor_dB",
    "mainbang_us", "mainbang_dB",
    "Filename",
    "sweep_rate_us_per_div",
]

#: QC annotation fonts tried in order (``save_tiff_with_all_points``)
QC_FONT_CANDIDATES = [
    "arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
]


class AstraError(ValueError):
    """An ASTRA operation cannot be applied (the GUI would have failed)."""


# ── working-window geometry ──────────────────────────────────────────
@dataclass(frozen=True)
class AstraGeometry:
    """ASTRA's view of one TIFF (``load_image_and_reset``)."""

    width: int            # unpadded image width (``img.width``)
    height: int
    crop_end_y: int       # 1800, or the image height when shorter
    zoom_height: int      # rows in the working window

    @classmethod
    def for_image(cls, width: int, height: int) -> "AstraGeometry":
        if height <= CROP_START_Y:
            raise AstraError(
                f"ASTRA needs images taller than {CROP_START_Y} rows (this one has {height})."
            )
        crop_end_y = CROP_END_Y
        if crop_end_y > height:
            crop_end_y = height
        return cls(width=width, height=height, crop_end_y=crop_end_y,
                   zoom_height=crop_end_y - CROP_START_Y)

    @property
    def padded_width(self) -> int:
        return self.width + PADDING_X

    @property
    def slider_max(self) -> int:
        """``x_slider_control`` range: ``cropped_img.width - zoom_width``
        (``cropped_img`` is the padded crop)."""
        return self.padded_width - ZOOM_WIDTH

    def public(self) -> dict:
        return {
            "width": self.width, "height": self.height,
            "crop_start_y": CROP_START_Y, "crop_end_y": self.crop_end_y,
            "zoom_width": ZOOM_WIDTH, "zoom_height": self.zoom_height,
            "padded_width": self.padded_width, "slider_max": self.slider_max,
        }


def padding_value(dtype) -> int:
    """``max_val`` used to pad the crop: the dtype maximum (65535 for uint16)."""
    return np.iinfo(dtype).max if np.issubdtype(dtype, np.integer) else 255


def astra_window(pixels: np.ndarray, geometry: AstraGeometry, slider: int) -> np.ndarray:
    """The working window ASTRA traces at ``slider``.

    Equivalent to ASTRA's ``cropped_img.crop((left, 0, left + zoom_width,
    zoom_height))`` on the padded crop, built directly from the decoded
    pixels (same values and dtype as ``np.array`` of the PIL crop).
    """
    if not isinstance(slider, int) or not 0 <= slider <= geometry.slider_max:
        raise AstraError(f"slider position must be an integer in [0, {geometry.slider_max}]")
    window = np.full(
        (geometry.zoom_height, ZOOM_WIDTH), padding_value(pixels.dtype), dtype=pixels.dtype
    )
    end = min(geometry.width, slider + ZOOM_WIDTH)
    if end > slider:
        window[:, : end - slider] = pixels[CROP_START_Y:geometry.crop_end_y, slider:end]
    return window


def astra_trace(window: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """``process_and_trace``: smoothed window and the detected red trace.

    Computed on the current (padded) working window, so the trace depends on
    the window position exactly as in ASTRA. ``gaussian_filter`` runs on the
    original integer dtype, as ASTRA does.
    """
    gray_img_array = window
    # Apply Gaussian filter to smooth the zoomed-in image and reduce noise
    smoothed_img = gaussian_filter(gray_img_array, sigma=TRACE_SIGMA)
    # Set the threshold for detecting black areas (signals)
    threshold_value = np.percentile(smoothed_img, TRACE_PERCENTILE)
    binary_signal = smoothed_img < threshold_value  # Detect black (dark) areas
    # Find the Y position of the topmost black pixel for each column
    trace_y = np.argmax(binary_signal, axis=0)
    return smoothed_img, trace_y


# ── calibration (ported unchanged) ───────────────────────────────────
def draw_y_axis_lines(y_axis_points, reference_line_y):
    """Returns ``(lines, labels)``, or ``None`` when ASTRA leaves them unchanged.

    ASTRA compatibility: the first grid line clicked is always -55 dB and
    lines step upwards by +10 dB; the Y reference line position does not
    enter the calculation, but it must be set or no grid is drawn.
    """
    if len(y_axis_points) != 4 or reference_line_y is None:
        return None
    # Use the first clicked point as the basepoint
    base_y = y_axis_points[0]
    # Calculate average spacing from the 4 points
    sorted_points = sorted(y_axis_points)
    avg_spacing = np.mean(np.diff(sorted_points))
    base_db = -55  # <-- Always start at -55 dB

    # Generate lines from basepoint upward, labeling each by +10 dB, until 0 dB or above top
    lines = []
    labels = []
    y = base_y
    db = base_db
    while y > 0 and db <= 0:
        lines.append(y)
        labels.append(db)
        y -= avg_spacing
        db += 10
    return lines, labels


def draw_x_axis_lines(x_axis_points, sweep_rate):
    """Returns ``(lines, labels)``, or ``None`` when ASTRA leaves them unchanged.

    ASTRA compatibility: the first grid line clicked is labelled one
    division (``sweep_rate`` µs); the X reference line does not enter it.
    """
    if len(x_axis_points) != 4:
        return None
    base_x = x_axis_points[0]
    sorted_points = sorted(x_axis_points)
    avg_spacing = np.mean(np.diff(sorted_points))
    base_us = sweep_rate

    lines = []
    labels = []
    x = base_x
    us = base_us
    max_us = 10 * sweep_rate
    while round(us, 4) <= max_us:  # Limit to 10 divisions (10, 20, or 50 μs)
        lines.append(x)
        labels.append(int(us) if us == int(us) else round(us, 2))
        x += avg_spacing
        us += sweep_rate
    return lines, labels


def pixel_to_us(x, x_axis_lines, x_axis_labels):
    """Convert x pixel to One Way Travel Time (μs) using x_axis_lines and x_axis_labels.

    ASTRA compatibility: ``x`` is a working-window column; the X reference
    line is not subtracted.
    """
    if not x_axis_lines or not x_axis_labels:
        return ""
    # Find the two nearest grid lines
    for i in range(1, len(x_axis_lines)):
        if x < x_axis_lines[i]:
            x0, x1 = x_axis_lines[i-1], x_axis_lines[i]
            us0, us1 = x_axis_labels[i-1], x_axis_labels[i]
            # Linear interpolation
            return round(us0 + (us1 - us0) * (x - x0) / (x1 - x0), 2)
    return x_axis_labels[-1]


def pixel_to_db(y, y_axis_lines, y_axis_labels):
    """Convert y pixel to Received Power (dB) using y_axis_lines and y_axis_labels, with extrapolation."""
    if not y_axis_lines or not y_axis_labels:
        return ""
    # If above the topmost line, extrapolate
    if y < y_axis_lines[-1]:
        # Use the last two grid lines for extrapolation
        y0, y1 = y_axis_lines[-2], y_axis_lines[-1]
        db0, db1 = y_axis_labels[-2], y_axis_labels[-1]
        # Linear extrapolation
        return round(db1 + (db1 - db0) * (y - y1) / (y1 - y0), 2)
    # If below the bottommost line, extrapolate
    if y > y_axis_lines[0]:
        y0, y1 = y_axis_lines[0], y_axis_lines[1]
        db0, db1 = y_axis_labels[0], y_axis_labels[1]
        return round(db0 + (db0 - db1) * (y - y0) / (y0 - y1), 2)
    # Otherwise, interpolate as usual
    for i in range(1, len(y_axis_lines)):
        if y > y_axis_lines[i]:
            y0, y1 = y_axis_lines[i-1], y_axis_lines[i]
            db0, db1 = y_axis_labels[i-1], y_axis_labels[i]
            return round(db0 + (db1 - db0) * (y - y0) / (y1 - y0), 2)
    return y_axis_labels[-1]


# ── CBD and navigation (ported unchanged) ────────────────────────────
def get_current_cbd(filename, slider_pos, image_width):
    """The estimated CBD for the current A-scope view (ASTRA title).

    ASTRA compatibility: ASTRA titles A-scopes with ``cbd_title_override``
    (``cbd_start``, then +1 per Next A-scope) whenever the filename has a CBD
    range; this slider-based value is only its fallback.
    """
    flight_number, cbd_start, cbd_end = extract_flight_info(os.path.basename(filename))
    if cbd_start is not None and cbd_end is not None:
        unpadded_w = image_width
        max_scroll = max(1, unpadded_w - ZOOM_WIDTH)
        ratio = min(1.0, max(0.0, slider_pos / max_scroll))
        return int(round(cbd_start + (cbd_end - cbd_start) * ratio))
    return None


def load_flight_coordinates(nav_path):
    """LAT/LON table as ASTRA reads it (path-based mode: the ``--nav`` file).

    Values are kept exactly as pandas parses them -- including any ``9999``
    -- because that is what ASTRA writes to its CSV.
    """
    try:
        if nav_path is not None and os.path.exists(nav_path):
            df = pd.read_csv(nav_path)
            return df[['CBD', 'LAT', 'LON']]
        return None
    except Exception:
        return None


def get_coordinates_for_cbd(flight_coords_df, cbd_value):
    """Get LAT/LON for a specific CBD value: ``(lat, lon)`` or ``(None, None)``."""
    if flight_coords_df is None:
        return None, None

    # Find the row with the matching CBD
    matching_rows = flight_coords_df[flight_coords_df['CBD'] == cbd_value]
    if len(matching_rows) > 0:
        row = matching_rows.iloc[0]
        return row['LAT'], row['LON']
    else:
        return None, None


def astra_dataframe(data, filename, flight_coords_df) -> pd.DataFrame:
    """The DataFrame ASTRA's ``save_to_csv`` writes.

    ASTRA compatibility: CBDs are spread linearly over the CBD range from
    the filename by committed-row order (``int`` truncation), not taken from
    where each A-scope was picked; LAT/LON come from an exact CBD match and
    are written empty when there is none.
    """
    # Extract flight information from current filename
    flight_number, cbd_start, cbd_end = extract_flight_info(os.path.basename(filename))

    # Load flight coordinates if available
    if not flight_number:
        flight_coords_df = None

    # Calculate CBD values for each A-scope
    # Distribute A-scopes evenly across the CBD range
    cbd_values = []
    lat_values = []
    lon_values = []

    if flight_number and cbd_start is not None and cbd_end is not None and len(data) > 0:
        for i, row in enumerate(data):
            # Calculate CBD value for this A-scope (linear interpolation)
            if len(data) == 1:
                cbd_value = cbd_start
            else:
                cbd_value = int(cbd_start + (cbd_end - cbd_start) * i / (len(data) - 1))

            # Get coordinates for this CBD
            lat, lon = get_coordinates_for_cbd(flight_coords_df, cbd_value)

            cbd_values.append(cbd_value)
            lat_values.append(lat if lat is not None else "")
            lon_values.append(lon if lon is not None else "")
    else:
        # If we can't extract flight info, fill with empty values
        for _ in data:
            cbd_values.append("")
            lat_values.append("")
            lon_values.append("")

    df = pd.DataFrame(data, columns=CSV_COLUMNS)

    # Add the GPS coordinate columns
    df['CBD'] = cbd_values
    df['LAT'] = lat_values
    df['LON'] = lon_values

    # Add the meter conversion columns
    v = ICE_VELOCITY_M_PER_US
    df['surface_m'] = df['surface_us'].apply(lambda x: (x/2)*v if x != "" and x is not None else "")
    df['bed_m'] = df['bed_us'].apply(lambda x: (x/2)*v if x != "" and x is not None else "")
    df['mainbang_m'] = df['mainbang_us'].apply(lambda x: (x/2)*v if x != "" and x is not None else "")

    # Calculate ice thickness (bed_m - surface_m)
    def calculate_h_ice(row):
        if (row['surface_m'] != "" and row['surface_m'] is not None and
            row['bed_m'] != "" and row['bed_m'] is not None):
            return row['bed_m'] - row['surface_m']
        else:
            return ""

    df['h_ice_m'] = df.apply(calculate_h_ice, axis=1)
    return df


def astra_csv_text(data, filename, nav_path) -> str:
    """Exactly what ASTRA writes to ``<TIFF basename>.csv``."""
    df = astra_dataframe(data, filename, load_flight_coordinates(nav_path))
    return df.to_csv(index=False)


# ── QC image (ported; the TIFF is not moved) ─────────────────────────
def _qc_font():
    for font_path in QC_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(font_path, 18)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def save_qc_image(tiff_path, data, out_path) -> None:
    """``save_tiff_with_all_points``: draw every committed pick on the
    original TIFF and save it as ``<TIFF basename>_QC.png``.

    ASTRA compatibility: the colour names are drawn on the original image
    mode (16-bit grayscale for the reference scans), where Pillow converts
    them to their gray levels. ASTRA then moves the TIFF into its output
    folder; Frozen Legacies keeps the source TIFF where it is.
    """
    # Open the original TIFF
    img = Image.open(tiff_path)
    draw = ImageDraw.Draw(img)
    font = _qc_font()

    for row in data:
        (ascope_num, flt, x_surface, y_surface, x_bed, y_bed, x_noisefloor, y_noisefloor, x_mainbang, y_mainbang, *_ ) = row
        for x, y, color, label in [
            (x_surface, y_surface, "green", "Surface"),
            (x_bed, y_bed, "magenta", "Bed"),
            (x_noisefloor, y_noisefloor, "maroon", "Noise"),
            (x_mainbang, y_mainbang, "blue", "MainBang"),
        ]:
            if x != "" and y != "" and x is not None and y is not None:
                try:
                    x_coord = int(x)
                    y_coord = int(y)  # y is already in original image coordinates!
                    r = 10
                    draw.ellipse((x_coord-r, y_coord-r, x_coord+r, y_coord+r), outline=color, width=3)
                    draw.text((x_coord+r+2, y_coord), f"{label} (A{ascope_num})", fill=color, font=font)
                except (ValueError, TypeError):
                    # Skip if coordinates cannot be converted to integers
                    continue

    img.save(out_path, format="PNG")


# ── session state machine ────────────────────────────────────────────
#: ASTRA globals that make up a manual picking session
STATE_FIELDS = (
    "slider", "sweep_rate", "current_scope", "cbd_title_override",
    "current_feature", "can_click", "feature_selected",
    "surface_coords", "bed_coords", "noisefloor_coords", "mainbang_coords",
    "reference_line_y", "reference_line_y_orig", "setting_reference_line",
    "x_reference_line", "x_reference_line_orig", "setting_x_reference_line",
    "y_axis_points", "setting_y_axis", "y_axis_lines", "y_axis_labels",
    "x_axis_points", "setting_x_axis", "x_axis_lines", "x_axis_labels",
    "current_y_axis_pick", "current_x_axis_pick",
    "data", "all_ascope_picks",
)
#: picks whose provenance (``manual`` / ``suggested``) is tracked
PICK_FIELDS = ("surface", "bed", "noisefloor", "mainbang")
_FEATURE_FIELD = {
    "Surface": "surface", "No Surface": "surface", "Bed": "bed", "No Bed": "bed",
    "Noise Floor": "noisefloor", "Main Bang": "mainbang",
}


def _as_float64(values):
    return [np.float64(v) for v in values]


class AstraSession:
    """One ASTRA picking session on one TIFF.

    Holds ASTRA's per-TIFF globals. ``filename`` is the TIFF basename ASTRA
    would see (``os.path.basename(image_path)``). ``trace_y`` must be the
    trace of the working window at ``slider`` (see :func:`astra_trace`).

    In addition to ASTRA's state, ``pick_sources`` records whether each
    current pick was clicked or suggested and ``row_sources`` keeps that per
    committed A-scope. They are provenance only and are not written to the
    ASTRA CSV.
    """

    def __init__(self, geometry: AstraGeometry, filename: str):
        self.geometry = geometry
        self.filename = filename
        self.messages: list[str] = []
        self.state = self.initial_state(geometry, filename)

    # -- construction / persistence ------------------------------------
    @staticmethod
    def initial_state(geometry: AstraGeometry, filename: str) -> dict:
        """State after ``load_image_and_reset`` (slider at 0)."""
        return {
            "slider": 0,
            "sweep_rate": DEFAULT_SWEEP_RATE,
            "current_scope": 1,
            "cbd_title_override": get_current_cbd(filename, 0, geometry.width),
            "current_feature": None, "can_click": True, "feature_selected": False,
            "surface_coords": None, "bed_coords": None,
            "noisefloor_coords": None, "mainbang_coords": None,
            "reference_line_y": None, "reference_line_y_orig": None,
            "setting_reference_line": False,
            "x_reference_line": None, "x_reference_line_orig": None,
            "setting_x_reference_line": False,
            "y_axis_points": [], "setting_y_axis": False,
            "y_axis_lines": [], "y_axis_labels": [],
            "x_axis_points": [], "setting_x_axis": False,
            "x_axis_lines": [], "x_axis_labels": [],
            "current_y_axis_pick": None, "current_x_axis_pick": None,
            "data": [], "all_ascope_picks": [],
            "pick_sources": {}, "row_sources": [],
        }

    @classmethod
    def from_state(cls, geometry: AstraGeometry, filename: str, state: dict) -> "AstraSession":
        session = cls(geometry, filename)
        restored = copy.deepcopy(state)
        for key in ("surface_coords", "bed_coords", "noisefloor_coords", "mainbang_coords"):
            if restored.get(key) is not None:
                restored[key] = tuple(restored[key])
        # ASTRA keeps grid lines as numpy float64 (np.mean/np.diff); keeping
        # the same type keeps round() and arithmetic bit-identical.
        for key in ("y_axis_lines", "x_axis_lines"):
            restored[key] = _as_float64(restored.get(key) or [])
        session.state = restored
        return session

    def to_state(self) -> dict:
        """JSON-serializable copy of the state."""
        def plain(value):
            if isinstance(value, (list, tuple)):
                return [plain(v) for v in value]
            if isinstance(value, dict):
                return {k: plain(v) for k, v in value.items()}
            if isinstance(value, np.integer):
                return int(value)
            if isinstance(value, np.floating):
                return float(value)
            return value
        return plain(self.state)

    def _say(self, message: str) -> None:
        self.messages.append(message)

    @property
    def slider(self) -> int:
        return self.state["slider"]

    # -- display --------------------------------------------------------
    def title(self) -> str:
        """Plot title (``process_and_trace``)."""
        s = self.state
        cbd_val = (
            s["cbd_title_override"] if s["cbd_title_override"] is not None
            else get_current_cbd(self.filename, s["slider"], self.geometry.width)
        )
        if cbd_val is not None:
            return f'A-scope {s["current_scope"]}: CBD {cbd_val}'
        return f'A-scope {s["current_scope"]}'

    def us(self, x):
        return pixel_to_us(x, self.state["x_axis_lines"], self.state["x_axis_labels"])

    def db(self, y):
        return pixel_to_db(y, self.state["y_axis_lines"], self.state["y_axis_labels"])

    # -- slider ---------------------------------------------------------
    def move(self, value: int) -> None:
        """``update``: the slider moved (the trace is recomputed by the caller)."""
        if not isinstance(value, int) or not 0 <= value <= self.geometry.slider_max:
            raise AstraError(f"X position must be an integer in [0, {self.geometry.slider_max}]")
        self.state["slider"] = value
        # Enable feature selection after adjusting the X-axis slider
        if not self.state["can_click"]:
            self.state["can_click"] = True

    def step(self, kind: str) -> int:
        """The arrow and jump buttons; returns the new slider position."""
        val = self.state["slider"]
        maximum = self.geometry.slider_max          # cropped_img.width - zoom_width
        if kind == "left":
            new_val = max(0, val - 10)
        elif kind == "right":
            new_val = min(maximum, val + 10)
        elif kind == "jump":                        # "Move 1000 px"
            new_val = min(maximum, val + 1000)
        else:
            raise AstraError(f"Unknown step {kind!r}")
        self.move(new_val)
        return new_val

    # -- setup buttons ----------------------------------------------------
    def setup_x_reference_line(self) -> None:
        if self.state["x_reference_line"] is None:
            self.state["setting_x_reference_line"] = True
            self._say("Pick the point for X axis reference line")
        else:
            self._say("X axis reference line already set. Click 'Done' to reset.")

    def setup_reference_line(self) -> None:
        # Only allow setting if not already set
        if self.state["reference_line_y"] is None:
            self.state["setting_reference_line"] = True
            self._say("Pick the point for reference line")
        else:
            self._say("Reference line already set. Click 'Done' to reset.")

    def setup_y_axis(self) -> None:
        s = self.state
        if not s["setting_y_axis"]:
            s["setting_y_axis"] = True
            s["y_axis_points"] = []
            s["y_axis_lines"] = []
            s["y_axis_labels"] = []
            self._say("Pick the points for y-axis (4 points needed)")
        else:
            self._say("Already setting up Y axis. Finish picking 4 points.")

    def setup_x_axis(self) -> None:
        s = self.state
        if not s["setting_x_axis"]:
            s["setting_x_axis"] = True
            s["x_axis_points"] = []
            s["x_axis_lines"] = []
            s["x_axis_labels"] = []
            self._say("Pick the points for x-axis (4 points needed)")
        else:
            self._say("Already setting up X axis. Finish picking 4 points.")

    def set_sweep_rate(self, sr: int) -> None:
        if sr not in SWEEP_RATES:
            raise AstraError(f"Sweep rate must be one of {SWEEP_RATES}")
        s = self.state
        s["sweep_rate"] = sr
        # Clear x axis calibration so user must click Set Up X Axis to rebuild X axis grid
        s["x_axis_lines"] = []
        s["x_axis_labels"] = []
        s["x_axis_points"] = []
        s["setting_x_axis"] = False
        self._say(f"Sweep rate set to {sr} µs/div. Click 'Set Up X Axis' to rebuild X axis grid.")

    def select_feature(self, feature: str) -> None:
        """``select_surface`` / ``select_no_surface`` / ... buttons."""
        if feature not in FEATURES:
            raise AstraError(f"Unknown feature {feature!r}")
        self.state["current_feature"] = feature
        self.state["feature_selected"] = True
        self._say(f"{feature} selected")

    # -- the plot click ------------------------------------------------
    def on_click(self, xdata, ydata, trace_y) -> None:
        """ASTRA's ``on_click`` for a click at data coordinates inside the plot."""
        s = self.state
        slider = s["slider"]

        # Handle x-axis reference line setup
        if s["setting_x_reference_line"] and s["x_reference_line"] is None:
            if xdata is not None:
                s["x_reference_line"] = int(xdata)
                s["x_reference_line_orig"] = s["x_reference_line"] + int(slider)
                self._say(f"X Reference line set at x = {s['x_reference_line']} "
                          f"(orig: {s['x_reference_line_orig']})")
            s["setting_x_reference_line"] = False
            return

        # Handle reference line setup (Y axis reference line)
        if s["setting_reference_line"] and s["reference_line_y"] is None:
            if ydata is not None:
                s["reference_line_y"] = int(ydata)
                s["reference_line_y_orig"] = s["reference_line_y"] + CROP_START_Y
                self._say(f"Reference Y-axis line set at y = {s['reference_line_y']} "
                          f"(orig: {s['reference_line_y_orig']})")
            s["setting_reference_line"] = False
            return

        # Handle Y axis setup (collect 4 points)
        if s["setting_y_axis"]:
            if ydata is not None:
                s["y_axis_points"].append(ydata)
                s["current_y_axis_pick"] = ydata  # Store for guide line
                if len(s["y_axis_points"]) == 4:
                    drawn = draw_y_axis_lines(s["y_axis_points"], s["reference_line_y"])
                    if drawn is not None:
                        s["y_axis_lines"], s["y_axis_labels"] = drawn
                    s["setting_y_axis"] = False
                    s["current_y_axis_pick"] = None  # Clear after done
            return

        # Handle X axis setup (collect 4 points)
        if s["setting_x_axis"]:
            if xdata is not None:
                s["x_axis_points"].append(xdata)
                s["current_x_axis_pick"] = xdata  # Store for guide line
                if len(s["x_axis_points"]) == 4:
                    drawn = draw_x_axis_lines(s["x_axis_points"], s["sweep_rate"])
                    if drawn is not None:
                        s["x_axis_lines"], s["x_axis_labels"] = drawn
                    s["setting_x_axis"] = False
                    s["current_x_axis_pick"] = None  # Clear after done
            return

        if s["current_feature"] is None or not s["can_click"] or not s["feature_selected"]:
            return

        feature = s["current_feature"]
        x_zoom = int(xdata)
        # Snap y_zoom to the red trace if picking a feature
        if feature in ["Surface", "Bed", "Noise Floor", "Main Bang"]:
            if 0 <= x_zoom < len(trace_y):
                y_zoom = int(trace_y[x_zoom])
            else:
                y_zoom = int(ydata)
        else:
            y_zoom = int(ydata)
        x_orig = x_zoom + int(slider)
        y_orig = y_zoom + CROP_START_Y
        coords = (x_zoom, y_zoom, x_orig, y_orig)

        # Record coordinates for the selected feature
        field = _FEATURE_FIELD[feature]
        if feature in ("No Surface", "No Bed"):
            s[f"{field}_coords"] = None
            self._say(f"{'Surface' if field == 'surface' else 'Bed'} set to NaN.")
        else:
            s[f"{field}_coords"] = coords
            self._say(f"{feature}: (zoom: {x_zoom},{y_zoom}) (orig: {x_orig},{y_orig})")
        s["pick_sources"][field] = "manual"

    # -- Suggest Picks ------------------------------------------------------
    def suggest_picks(self, trace_y) -> None:
        s = self.state
        if trace_y is None or len(trace_y) == 0:
            self._say("No trace data available for suggesting picks.")
            return

        n = len(trace_y)
        x_val = int(s["slider"])
        x_reference_line = s["x_reference_line"]

        # 1. Main Bang (near x_reference_line or early trace)
        x_ref = int(x_reference_line) if (x_reference_line is not None and 0 <= x_reference_line < n) else int(n * 0.05)
        mb_range_start = max(0, x_ref - 50)
        mb_range_end = min(n, x_ref + 150)
        if mb_range_end > mb_range_start:
            x_mb = mb_range_start + int(np.argmin(trace_y[mb_range_start:mb_range_end]))
        else:
            x_mb = x_ref
        y_mb = int(trace_y[x_mb])
        s["mainbang_coords"] = (x_mb, y_mb, x_mb + x_val, y_mb + CROP_START_Y)

        # 2. Surface: Search after main bang
        surf_start = min(n - 1, x_mb + 50)
        surf_end = min(n, surf_start + int(n * 0.35))
        if surf_end > surf_start:
            x_surf = surf_start + int(np.argmin(trace_y[surf_start:surf_end]))
        else:
            x_surf = min(n - 1, x_mb + 100)
        y_surf = int(trace_y[x_surf])
        s["surface_coords"] = (x_surf, y_surf, x_surf + x_val, y_surf + CROP_START_Y)

        # 3. Bed: Search after surface
        bed_start = min(n - 1, x_surf + 100)
        bed_end = min(n, bed_start + int(n * 0.45))
        if bed_end > bed_start:
            x_bed = bed_start + int(np.argmin(trace_y[bed_start:bed_end]))
        else:
            x_bed = min(n - 1, x_surf + 300)
        y_bed = int(trace_y[x_bed])
        s["bed_coords"] = (x_bed, y_bed, x_bed + x_val, y_bed + CROP_START_Y)

        # 4. Noise Floor: Search toward end of trace
        nf_start = min(n - 1, max(x_bed + 150, int(n * 0.75)))
        nf_end = min(n, nf_start + int(n * 0.2))
        if nf_end > nf_start:
            x_nf = nf_start + (nf_end - nf_start) // 2
        else:
            x_nf = min(n - 1, x_bed + 200)
        y_nf = int(trace_y[x_nf])
        s["noisefloor_coords"] = (x_nf, y_nf, x_nf + x_val, y_nf + CROP_START_Y)

        for field in PICK_FIELDS:
            s["pick_sources"][field] = "suggested"
        self._say(f"Suggested picks - MB: {x_mb}, Surf: {x_surf}, Bed: {x_bed}, NF: {x_nf}")

    # -- committing --------------------------------------------------------
    def commit_current_ascope(self) -> bool:
        s = self.state
        surface_coords, bed_coords = s["surface_coords"], s["bed_coords"]
        noisefloor_coords, mainbang_coords = s["noisefloor_coords"], s["mainbang_coords"]
        # Only require noisefloor and mainbang to be present to save an A-scope
        if not (noisefloor_coords and mainbang_coords):
            return False
        if not s["current_scope"] > len(s["data"]):
            return False
        reference_line_y_orig = s["reference_line_y_orig"]
        x_reference_line_orig = s["x_reference_line_orig"]
        flight_number, _, _ = extract_flight_info(os.path.basename(self.filename))
        row = [
            s["current_scope"],
            flight_number if flight_number else "",  # FLT column
            surface_coords[2] if surface_coords else "", surface_coords[3] if surface_coords else "",  # x_surface_px, y_surface_px (orig)
            bed_coords[2] if bed_coords else "", bed_coords[3] if bed_coords else "",
            noisefloor_coords[2], noisefloor_coords[3],
            mainbang_coords[2], mainbang_coords[3],
            int(reference_line_y_orig) if reference_line_y_orig is not None else "",
            int(x_reference_line_orig) if x_reference_line_orig is not None else "",
            self.us(surface_coords[0]) if surface_coords else "",
            self.db(surface_coords[1]) if surface_coords else "",
            self.us(bed_coords[0]) if bed_coords else "",
            self.db(bed_coords[1]) if bed_coords else "",
            self.us(noisefloor_coords[0]),
            self.db(noisefloor_coords[1]),
            self.us(mainbang_coords[0]),
            self.db(mainbang_coords[1]),
            os.path.basename(self.filename),
            s["sweep_rate"],
        ]
        s["data"].append(row)
        s["all_ascope_picks"].append({
            'surface': surface_coords,
            'bed': bed_coords,
            'noisefloor': noisefloor_coords,
            'mainbang': mainbang_coords,
        })
        s["row_sources"].append({
            field: (s["pick_sources"].get(field, "manual")
                    if s[f"{field}_coords"] is not None else None)
            for field in PICK_FIELDS
        })
        self._say(f"Completed A-scope {s['current_scope']}")
        return True

    def next_ascope(self) -> None:
        """"Next A-scope" (the caller then rewrites the CSV, as ASTRA's
        ``save_to_csv`` does)."""
        s = self.state
        self.commit_current_ascope()

        s["current_scope"] += 1
        current_cbd = (
            s["cbd_title_override"] if s["cbd_title_override"] is not None
            else get_current_cbd(self.filename, s["slider"], self.geometry.width)
        )
        s["cbd_title_override"] = current_cbd + 1 if current_cbd is not None else None
        s["can_click"] = True
        s["feature_selected"] = False
        s["surface_coords"] = None
        s["bed_coords"] = None
        s["noisefloor_coords"] = None
        s["mainbang_coords"] = None
        s["pick_sources"] = {}
        self._say(f"Moving to A-scope {s['current_scope']}")

    def done(self) -> None:
        """"Done": commit the current eligible A-scope (the caller writes the
        CSV and QC image; the TIFF is not moved)."""
        self.commit_current_ascope()
