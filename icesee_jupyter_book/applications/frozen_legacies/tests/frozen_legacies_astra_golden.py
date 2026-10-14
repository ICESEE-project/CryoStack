"""Committed ASTRA parity goldens.

The full parity suite (``test_frozen_legacies_astra_parity.py``) executes the
unmodified ASTRA reference script and needs ``Pickers/ASTRA_MAC.py``. This
module defines one deterministic synthetic A-scope strip (no random number
generator, so it is identical on every platform) and one fixed sequence of
ASTRA actions. ``astra_golden.json`` holds what ASTRA itself produced for
them -- per step the slider, a hash of the trace, a hash of the session
state and the title; finally the CSV text -- so the port can be checked
against ASTRA's results wherever the reference script is not available.

Regenerate (only from the ASTRA reference)::

    python icesee_jupyter_book/applications/frozen_legacies/tests/frozen_legacies_astra_golden.py
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
GOLDEN = _HERE / "astra_golden.json"
NAME = "F127-C0471_C0483.tiff"
NAV = (
    "CBD,LAT,LON,THK,SRF\n"
    + "".join(f"{c},{-81.4 - (c - 465) * 0.01:.6f},{-169.8 + (c - 465) * 0.03:.6f},9999,9999\n"
              for c in range(465, 490))
)

#: (action, args) in ASTRA's GUI terms
SEQUENCE = [
    ("setup", "x_reference"), ("click", 101.7, 40.2),
    ("setup", "y_reference"), ("click", 12.0, 1401.6),
    ("setup", "y_axis"),
    ("click", 6.0, 1302.2), ("click", 6.0, 1203.4), ("click", 6.0, 1100.1), ("click", 6.0, 1001.9),
    ("sweep", 2), ("setup", "x_axis"),
    ("click", 200.3, 6.0), ("click", 401.1, 6.0), ("click", 600.8, 6.0), ("click", 802.2, 6.0),
    ("select", "Noise Floor"), ("click", 1500.4, 3.0),
    ("select", "Main Bang"), ("click", 150.2, 3.0),
    ("select", "Surface"), ("click", 500.6, 3.0),
    ("select", "Bed"), ("click", 900.49, 1000.0),
    ("next",),
    ("step", "jump"), ("step", "right"), ("step", "left"),
    ("suggest",),
    ("select", "Surface"), ("click", 640.0, 20.0),
    ("next",), ("next",),
    ("move", "max"),
    ("select", "No Bed"), ("click", 10.0, 10.0),
    ("select", "Noise Floor"), ("click", 2299.4, 100.0),
    ("select", "Main Bang"), ("click", -0.4, 5.0),
]


def strip(width: int = 3600, height: int = 1900) -> np.ndarray:
    """Light film, integer-hash noise, and a dark wavy trace (deterministic)."""
    y, x = np.mgrid[0:height, 0:width].astype(np.int64)
    noise = ((x * 73856093) ^ (y * 19349663)) % 4001 - 2000
    img = 58000 + noise
    centre = (height * 0.45 + height * 0.15 * np.sin(np.arange(width) / 70.0)
              + height * 0.05 * np.sin(np.arange(width) / 13.0)).astype(np.int64)
    for dy in range(-4, 5):
        rows = np.clip(centre + dy, 0, height - 1)
        img[rows, np.arange(width)] = 1200
    return np.clip(img, 0, 65535).astype(np.uint16)


def _digest(value) -> str:
    return hashlib.sha256(value).hexdigest()[:16]


def _state_digest(state: dict) -> str:
    return _digest(json.dumps(state, sort_keys=True, allow_nan=False).encode())


def run_port(pixels: np.ndarray, nav_path: Path) -> dict:
    """Apply SEQUENCE with the Frozen Legacies port (session JSON round trip
    after every action, as the server does)."""
    from icesee_jupyter_book.applications.frozen_legacies.pickers import astra as P

    geometry = P.AstraGeometry.for_image(pixels.shape[1], pixels.shape[0])
    session = P.AstraSession(geometry, NAME)
    steps = []
    for action, *args in SEQUENCE:
        trace = P.astra_trace(P.astra_window(pixels, geometry, session.slider))[1]
        if action == "setup":
            getattr(session, {"x_reference": "setup_x_reference_line",
                              "y_reference": "setup_reference_line",
                              "y_axis": "setup_y_axis", "x_axis": "setup_x_axis"}[args[0]])()
        elif action == "click":
            session.on_click(args[0], args[1], trace)
        elif action == "sweep":
            session.set_sweep_rate(args[0])
        elif action == "select":
            session.select_feature(args[0])
        elif action == "step":
            session.step(args[0])
        elif action == "move":
            session.move(geometry.slider_max if args[0] == "max" else args[0])
        elif action == "suggest":
            session.suggest_picks(trace)
        elif action == "next":
            session.next_ascope()
        state = json.loads(json.dumps(session.to_state(), allow_nan=False))
        session = P.AstraSession.from_state(geometry, NAME, state)
        trace = P.astra_trace(P.astra_window(pixels, geometry, session.slider))[1]
        astra_state = {k: v for k, v in state.items() if k in P.STATE_FIELDS}
        steps.append({"slider": session.slider,
                      "trace": _digest(np.ascontiguousarray(trace, dtype=np.int64).tobytes()),
                      "state": _state_digest(astra_state),
                      "title": session.title()})
    session.done()
    return {"steps": steps, "csv": P.astra_csv_text(session.state["data"], NAME, nav_path)}


def run_astra(pixels: np.ndarray, nav_path: Path, work: Path) -> dict:
    """Apply SEQUENCE with the unmodified ASTRA reference functions."""
    from PIL import Image

    import frozen_legacies_astra_reference as reference
    from icesee_jupyter_book.applications.frozen_legacies.pickers import astra as P

    tiff = work / NAME
    Image.fromarray(pixels).save(tiff, format="TIFF", compression="tiff_lzw")
    with contextlib.redirect_stdout(io.StringIO()):
        a = reference.Astra(tiff, nav_path=nav_path, output_dir=work / "out")
        steps = []
        features = {"Surface": "select_surface", "No Surface": "select_no_surface",
                    "Bed": "select_bed", "No Bed": "select_no_bed",
                    "Noise Floor": "select_noise_floor", "Main Bang": "select_main_bang"}
        for action, *args in SEQUENCE:
            slider = a["x_slider_control"]
            maximum = a["cropped_img"].width - a["zoom_width"]
            if action == "setup":
                a.call({"x_reference": "setup_x_reference_line",
                        "y_reference": "setup_reference_line",
                        "y_axis": "setup_y_axis", "x_axis": "setup_x_axis"}[args[0]])
            elif action == "click":
                a.click(args[0], args[1])
            elif action == "sweep":
                a.call("set_sweep_rate", args[0])
            elif action == "select":
                a.call(features[args[0]])
            elif action == "step":
                slider.set_val({"left": max(0, slider.val - 10),
                                "right": min(maximum, slider.val + 10),
                                "jump": min(maximum, slider.val + 1000)}[args[0]])
            elif action == "move":
                slider.set_val(maximum if args[0] == "max" else args[0])
            elif action == "suggest":
                a.call("suggest_picks")
            elif action == "next":
                a.call("next_ascope")
            state = _plain({k: a[k] for k in P.STATE_FIELDS if k != "slider"})
            state["slider"] = int(slider.val)
            for key in ("y_axis_lines", "x_axis_lines", "y_axis_points", "x_axis_points"):
                state[key] = [float(v) for v in state[key]]
            cbd = (a["cbd_title_override"] if a["cbd_title_override"] is not None
                   else a["get_current_cbd"]())
            steps.append({
                "slider": int(slider.val),
                "trace": _digest(np.ascontiguousarray(a["trace_y"], dtype=np.int64).tobytes()),
                "state": _state_digest(state),
                "title": (f"A-scope {a['current_scope']}: CBD {cbd}" if cbd is not None
                          else f"A-scope {a['current_scope']}"),
            })
        a.finish()
    return {"steps": steps, "csv": (work / "out" / f"{Path(NAME).stem}.csv").read_text()}


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


def main() -> int:
    repo = _HERE.parents[3]
    for p in (str(repo), str(_HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import frozen_legacies_astra_reference as reference

    if not reference.available():
        print("The ASTRA reference script is required to regenerate the goldens.")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        nav = work / "nav.csv"
        nav.write_text(NAV)
        golden = run_astra(strip(), nav, work)
        golden["description"] = __doc__.strip().splitlines()[0]
        GOLDEN.write_text(json.dumps(golden, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {GOLDEN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
