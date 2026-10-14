"""ASTRA parity: the Frozen Legacies port (pickers/astra.py) against the
unmodified ASTRA reference functions, executed headlessly.

Every scenario drives ASTRA's own callbacks and the port with the same
inputs on the same TIFF and compares the working window, padding, trace,
calibration, picks, title, committed rows, the CSV bytes and the QC image
bytes.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[3]
for _p in (str(_REPO), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import frozen_legacies_astra_reference as reference
from icesee_jupyter_book.applications.frozen_legacies.pickers import astra as P
from icesee_jupyter_book.applications.frozen_legacies.radar.render import decode_radar

pytestmark = pytest.mark.skipif(
    not reference.available(), reason="ASTRA reference script (Pickers/ASTRA_MAC.py) not present"
)

TIFF = "F127-C0471_C0483.tiff"


# ── synthetic A-scope strips ─────────────────────────────────────────
def strip(width=5200, height=1900, dtype=np.uint16, seed=0):
    """Light film with a dark wavy trace and noise."""
    rng = np.random.default_rng(seed)
    top = np.iinfo(dtype).max
    img = np.full((height, width), int(top * 0.9), dtype=np.float64)
    img += rng.normal(0, top * 0.02, img.shape)
    x = np.arange(width)
    centre = height * 0.45 + height * 0.15 * np.sin(x / 70.0) + height * 0.05 * np.sin(x / 13.0)
    for dy in range(-4, 5):
        rows = np.clip((centre + dy).astype(int), 0, height - 1)
        img[rows, x] = top * 0.02
    return np.clip(img, 0, top).astype(dtype)


def nav_csv(path: Path, *, lat_override=None) -> Path:
    lines = ["CBD,LAT,LON,THK,SRF"]
    for cbd in range(465, 490):
        lat = -81.4 - (cbd - 465) * 0.01
        if lat_override and cbd in lat_override:
            lat = lat_override[cbd]
        lines.append(f"{cbd},{lat:.6f},{-169.8 + (cbd - 465) * 0.03:.6f},9999,9999")
    path.write_text("\n".join(lines) + "\n")
    return path


class Pair:
    """ASTRA (oracle) and the port, driven in lock-step."""

    def __init__(self, tmp_path: Path, pixels: np.ndarray, *, name=TIFF, nav=True,
                 nav_path=None, roundtrip=False):
        self.dir = tmp_path
        self.tiff = tmp_path / "input" / name
        self.tiff.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(pixels).save(self.tiff, format="TIFF", compression="tiff_lzw")
        self.astra_tiff = tmp_path / "astra" / name
        self.astra_tiff.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.tiff, self.astra_tiff)       # ASTRA moves its TIFF at Done
        self.nav = nav_path if nav_path is not None else (nav_csv(tmp_path / "nav.csv") if nav else None)
        with contextlib.redirect_stdout(io.StringIO()):
            self.astra = reference.Astra(self.astra_tiff, nav_path=self.nav,
                                         output_dir=tmp_path / "astra_out")
        self.pixels = decode_radar(self.tiff).pixels
        self.geometry = P.AstraGeometry.for_image(self.pixels.shape[1], self.pixels.shape[0])
        self.port = P.AstraSession(self.geometry, name)
        self.roundtrip = roundtrip
        self.check()

    def trace(self):
        cache = self.__dict__.setdefault("_traces", {})
        slider = self.port.slider
        if slider not in cache:
            cache[slider] = P.astra_trace(P.astra_window(self.pixels, self.geometry, slider))[1]
        return cache[slider]

    # one ASTRA GUI action on both sides
    def do(self, kind, *args):
        a, s = self.astra, self.port
        with contextlib.redirect_stdout(io.StringIO()):
            if kind == "setup":
                name = {"x_reference": "setup_x_reference_line", "y_reference": "setup_reference_line",
                        "y_axis": "setup_y_axis", "x_axis": "setup_x_axis"}[args[0]]
                a.call(name)
                getattr(s, name)()
            elif kind == "click":
                a.click(*args)
                s.on_click(args[0], args[1], self.trace())
            elif kind == "sweep":
                a.call("set_sweep_rate", args[0])
                s.set_sweep_rate(args[0])
            elif kind == "select":
                fn = {"Surface": "select_surface", "No Surface": "select_no_surface",
                      "Bed": "select_bed", "No Bed": "select_no_bed",
                      "Noise Floor": "select_noise_floor", "Main Bang": "select_main_bang"}[args[0]]
                a.call(fn)
                s.select_feature(args[0])
            elif kind == "move":
                a.move(args[0])
                s.move(args[0])
            elif kind == "step":
                slider = a["x_slider_control"]
                maximum = a["cropped_img"].width - a["zoom_width"]
                new = {"left": max(0, slider.val - 10), "right": min(maximum, slider.val + 10),
                       "jump": min(maximum, slider.val + 1000)}[args[0]]
                slider.set_val(new)
                s.step(args[0])
            elif kind == "suggest":
                a.call("suggest_picks")
                s.suggest_picks(self.trace())
            elif kind == "next":
                a.call("next_ascope")
                s.next_ascope()
        if self.roundtrip:      # what the server does between requests
            state = json.loads(json.dumps(s.to_state(), allow_nan=False))
            self.port = P.AstraSession.from_state(self.geometry, s.filename, state)
        self.check()

    def check(self):
        a, s = self.astra, self.port
        slider = int(a["x_slider_control"].val)
        assert s.slider == slider
        window = np.array(a["cropped_img"].crop((slider, 0, slider + a["zoom_width"], a["zoom_height"])))
        np.testing.assert_array_equal(P.astra_window(self.pixels, self.geometry, slider), window)
        np.testing.assert_array_equal(self.trace(), a["trace_y"])
        for field in P.STATE_FIELDS:
            if field == "slider":
                continue
            ours, theirs = s.state[field], a[field]
            if field in ("y_axis_lines", "x_axis_lines", "y_axis_points", "x_axis_points"):
                assert [float(v) for v in ours] == [float(v) for v in theirs], field
            else:
                assert _plain(ours) == _plain(theirs), field
        # title (process_and_trace)
        cbd = a["cbd_title_override"] if a["cbd_title_override"] is not None else a["get_current_cbd"]()
        expected = f"A-scope {a['current_scope']}: CBD {cbd}" if cbd is not None else f"A-scope {a['current_scope']}"
        assert s.title() == expected

    def finish(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.astra.finish()
        self.port.done()
        stem = self.tiff.stem
        ours_csv = P.astra_csv_text(self.port.state["data"], self.tiff.name, self.nav)
        theirs_csv = (self.dir / "astra_out" / f"{stem}.csv").read_text()
        ours_qc = self.dir / "ours_QC.png"
        P.save_qc_image(self.tiff, self.port.state["data"], ours_qc)
        theirs_qc = self.dir / "astra_out" / f"{stem}_QC.png"
        return ours_csv, theirs_csv, ours_qc.read_bytes(), theirs_qc.read_bytes()


def _plain(value):
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def calibrate(pair, *, sweep=2):
    pair.do("setup", "x_reference"); pair.do("click", 101.7, 40.2)
    pair.do("setup", "y_reference"); pair.do("click", 12.0, 1401.6)
    pair.do("setup", "y_axis")
    for y in (1302.2, 1203.4, 1100.1, 1001.9):
        pair.do("click", 6.0, y)
    pair.do("sweep", sweep)
    pair.do("setup", "x_axis")
    for x in (200.3, 401.1, 600.8, 802.2):
        pair.do("click", x, 6.0)


# ── geometry, padding and trace ──────────────────────────────────────
@pytest.mark.parametrize("width, height, dtype", [
    (5200, 1900, np.uint16), (3000, 1200, np.uint16), (2600, 1810, np.uint8), (2400, 300, np.uint16),
])
def test_window_padding_and_trace_match_astra_everywhere(tmp_path, width, height, dtype):
    pair = Pair(tmp_path, strip(width, height, dtype))
    a = pair.astra
    assert pair.geometry.zoom_height == a["zoom_height"]
    assert pair.geometry.padded_width == a["cropped_img"].width
    assert pair.geometry.slider_max == a["x_slider_control"].valmax
    assert P.padding_value(pair.pixels.dtype) == np.iinfo(dtype).max
    m = pair.geometry.slider_max
    for slider in sorted({0, 1, 7, m // 3, max(0, width - 2300), m - 1, m}):
        pair.do("move", slider)


def test_astra_geometry_constants_match_the_reference(tmp_path):
    pair = Pair(tmp_path, strip(2600, 1900))
    a = pair.astra
    assert (a["crop_start_y"], a["crop_end_y"], a["zoom_width"]) == (
        P.CROP_START_Y, P.CROP_END_Y, P.ZOOM_WIDTH)
    assert a["cropped_img"].width - pair.geometry.width == P.PADDING_X == 2100


# ── full controlled sessions ─────────────────────────────────────────
def _session(pair):
    calibrate(pair)
    pair.do("select", "Noise Floor"); pair.do("click", 1500.4, 3.0)
    pair.do("select", "Main Bang"); pair.do("click", 150.2, 3.0)
    pair.do("select", "Surface"); pair.do("click", 500.6, 3.0)
    pair.do("select", "Bed"); pair.do("click", 900.49, 1000.0)
    pair.do("next")
    pair.do("step", "jump"); pair.do("step", "right"); pair.do("step", "left"); pair.do("step", "left")
    pair.do("suggest")
    pair.do("select", "Surface"); pair.do("click", 640.0, 20.0)          # correct a suggestion
    pair.do("next")
    pair.do("next")                                                      # nothing picked: scope skips
    pair.do("move", pair.geometry.slider_max)                            # into the padding
    pair.do("select", "No Bed"); pair.do("click", 10.0, 10.0)
    pair.do("select", "No Surface"); pair.do("click", 10.0, 10.0)
    pair.do("select", "Noise Floor"); pair.do("click", 2299.4, 100.0)
    pair.do("select", "Main Bang"); pair.do("click", -0.4, 5.0)
    return pair.finish()


@pytest.mark.parametrize("roundtrip", [False, True])
def test_controlled_session_csv_and_qc_are_identical(tmp_path, roundtrip):
    ours_csv, theirs_csv, ours_qc, theirs_qc = _session(
        Pair(tmp_path, strip(), roundtrip=roundtrip))
    assert ours_csv == theirs_csv
    assert ours_qc == theirs_qc
    rows = list(__import__("csv").reader(io.StringIO(ours_csv)))
    assert rows[0][:2] == ["A-scope Number", "FLT"] and len(rows[0]) == 29
    assert [r[0] for r in rows[1:]] == ["1", "2", "4"]                   # ASTRA numbering
    assert [r[22] for r in rows[1:]] == ["471", "477", "483"]            # CBD by row order


def test_uncalibrated_session_matches(tmp_path):
    pair = Pair(tmp_path, strip(3200, 1900, seed=3))
    pair.do("suggest"); pair.do("next")
    pair.do("move", 900); pair.do("suggest"); pair.do("next")
    ours_csv, theirs_csv, ours_qc, theirs_qc = pair.finish()
    assert ours_csv == theirs_csv and ours_qc == theirs_qc


def test_sweep_rates_and_recalibration_match(tmp_path):
    pair = Pair(tmp_path, strip(seed=5))
    calibrate(pair, sweep=5)
    pair.do("select", "Noise Floor"); pair.do("click", 2000.0, 1.0)
    pair.do("select", "Main Bang"); pair.do("click", 90.0, 1.0)
    pair.do("next")
    pair.do("sweep", 1)                       # clears the X grid
    pair.do("setup", "x_axis")
    for x in (150.0, 260.0, 371.5, 480.0):
        pair.do("click", x, 1.0)
    pair.do("setup", "x_axis"); pair.do("setup", "x_axis")   # "already setting" path
    pair.do("suggest"); pair.do("next")
    ours_csv, theirs_csv, *_ = pair.finish()
    assert ours_csv == theirs_csv


def test_reference_lines_cannot_be_reset_and_y_grid_needs_reference(tmp_path):
    pair = Pair(tmp_path, strip(2600, 1900))
    pair.do("setup", "y_axis")
    for y in (1300.0, 1200.0, 1100.0, 1000.0):
        pair.do("click", 5.0, y)
    assert pair.port.state["y_axis_lines"] == []          # ASTRA: no reference -> no grid
    pair.do("setup", "y_reference"); pair.do("click", 5.0, 1400.0)
    pair.do("setup", "y_reference"); pair.do("click", 5.0, 200.0)   # already set: not changed
    assert pair.port.state["reference_line_y"] == 1400
    pair.do("setup", "x_reference"); pair.do("click", 77.9, 5.0)
    pair.do("setup", "x_reference")
    assert pair.port.state["x_reference_line"] == 77


def test_selecting_without_clicking_and_clicking_without_selecting(tmp_path):
    pair = Pair(tmp_path, strip(2600, 1900))
    pair.do("click", 400.0, 400.0)            # nothing armed: no-op in ASTRA
    pair.do("select", "Surface")
    pair.do("next")                            # feature_selected cleared by Next
    pair.do("click", 400.0, 400.0)            # ignored until a feature is selected again
    assert pair.port.state["surface_coords"] is None


# ── CBD and navigation ───────────────────────────────────────────────
@pytest.mark.parametrize("name, commits", [
    ("F127-C0471_C0483.tiff", 1),
    ("F127-C0471_C0483.tiff", 5),
    ("F127-C0483_C0471.tiff", 4),             # descending range
    ("F127-C0400_C0410.tiff", 3),             # CBDs absent from the nav file
    ("no_metadata_here.tiff", 2),             # no flight/CBD in the name
])
def test_cbd_assignment_and_navigation_lookup_match(tmp_path, name, commits):
    pair = Pair(tmp_path, strip(2600, 1900, seed=1), name=name)
    for i in range(commits):
        pair.do("move", min(pair.geometry.slider_max, i * 37))
        pair.do("suggest")
        pair.do("next")
    ours_csv, theirs_csv, *_ = pair.finish()
    assert ours_csv == theirs_csv


def test_9999_navigation_values_are_written_raw_like_astra(tmp_path):
    nav = nav_csv(tmp_path / "nav9999.csv", lat_override={471: 9999.0})
    pair = Pair(tmp_path, strip(2600, 1900), nav_path=nav)
    pair.do("suggest"); pair.do("next")
    ours_csv, theirs_csv, *_ = pair.finish()
    assert ours_csv == theirs_csv
    assert ",9999.0," in ours_csv


def test_missing_navigation_file_gives_empty_positions(tmp_path):
    pair = Pair(tmp_path, strip(2600, 1900), nav=False)
    pair.do("suggest"); pair.do("next")
    ours_csv, theirs_csv, *_ = pair.finish()
    assert ours_csv == theirs_csv


# ── calibration functions over many inputs ───────────────────────────
def test_calibration_functions_match_on_random_inputs(tmp_path):
    pair = Pair(tmp_path, strip(2600, 1900))
    ns = pair.astra.ns
    rng = np.random.default_rng(42)
    for _ in range(200):
        points = list(rng.uniform(0, 1549, 4))
        ns["y_axis_points"], ns["reference_line_y"] = points, 1000
        ns["draw_y_axis_lines"]()
        lines, labels = P.draw_y_axis_lines(points, 1000)
        assert [float(v) for v in lines] == [float(v) for v in ns["y_axis_lines"]]
        assert labels == ns["y_axis_labels"]
        xs = list(rng.uniform(0, 2299, 4))
        for rate in P.SWEEP_RATES:
            ns["x_axis_points"], ns["sweep_rate"] = xs, rate
            ns["draw_x_axis_lines"]()
            xl, xb = P.draw_x_axis_lines(xs, rate)
            assert [float(v) for v in xl] == [float(v) for v in ns["x_axis_lines"]]
            assert xb == ns["x_axis_labels"]
        for value in rng.integers(-50, 2400, 25):
            assert P.pixel_to_us(int(value), ns["x_axis_lines"], ns["x_axis_labels"]) == ns["pixel_to_us"](int(value))
        if len(ns["y_axis_lines"]) >= 2:
            for value in rng.integers(-50, 1600, 25):
                assert P.pixel_to_db(int(value), ns["y_axis_lines"], ns["y_axis_labels"]) == ns["pixel_to_db"](int(value))


def test_suggest_picks_match_at_many_positions(tmp_path):
    pair = Pair(tmp_path, strip(6000, 1900, seed=9))
    pair.do("setup", "x_reference"); pair.do("click", 140.0, 5.0)
    for slider in (0, 333, 1200, 2950, 3700, pair.geometry.slider_max):
        pair.do("move", slider)
        pair.do("suggest")
