"""
pick_calibration.py — LYRA interactive calibration picker (multi-frame)
========================================================================
For each complete frame in a TIFF, collect guidance clicks for:

  M — Main bang              (1 click  -> red   vertical  line)
  R — Reference -60 dB      (1 click  -> cyan  horizontal line)
  Y — Y-axis major grid line (2 clicks -> lime  horizontal lines)
  X — X-axis major grid line (4 clicks -> orange vertical   lines)

These clicks are GUIDANCE ONLY — approximate hints ±tens of pixels are fine.
The algorithm will snap to the true feature near each guide pick.

Keyboard shortcuts (case-insensitive):
  M  — switch to Main Bang mode
  R  — switch to Reference line -60 dB mode
  Y  — switch to Y-grid mode     (click two visible major lines)
  X  — switch to X-grid mode     (click four visible major lines)
  U  — undo last pick in the current mode
  N  — save picks for this frame and move to next frame
  B  — go back to previous frame (save current picks first)
  S  — skip this frame (no picks saved)
  Q  — save picks and advance to next TIFF (flight mode) or quit (single mode)
  Esc — quit entirely (save current picks first)

Usage
-----
Single TIFF:
    python codes/pick_calibration.py <TIFF_PATH>

All TIFFs in a flight that need picks (M+R+X):
    python codes/pick_calibration.py --flight 126

Re-pick a specific TIFF by ID:
    python codes/pick_calibration.py --flight 126 --tiff 2750

Fix only specific flagged CBDs:
    python codes/pick_calibration.py --flight 126 --tiff 2600 --cbds 301,305,312

Outputs
-------
  output/F{FLT}/phase1/F{FLT}_cal_picks.json
  output/F{FLT}/phase1/F{FLT}_cal_derived.json
"""

from pathlib import Path
import argparse
import sys
import os
import json

import numpy as np
import pandas as pd
from PIL import Image
import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "codes"))

from lyra import ensure_canonical_name, resolve_tiff_arg, tiff_id as lyra_tiff_id

# Display crop: show full display band plus context
Y_CROP_LO = 100
Y_CROP_HI = 1950

# Default calibration constants (for drawing faint guide lines)
_DB_REF_PX    = 1507
_PX_PER_DIV_Y = 205.0
_PX_PER_DIV_X = 205.54

MODE_COLORS = {"mb": "red", "ref": "cyan", "y_grid": "limegreen", "x_grid": "orange"}
MODE_LABELS = {
    "mb":     "Main Bang  [M] — 1 click (red)",
    "ref":    "Reference -60 dB  [R] — 1 click (cyan)",
    "y_grid": "Y-grid major line  [Y] — 2 clicks (lime)",
    "x_grid": "X-grid major line  [X] — 4 clicks (orange)",
}


# -- Argument parsing ----------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="LYRA interactive calibration picker")
    parser.add_argument("tiff_path", nargs="?", default=None,
                        help="Path to a single TIFF file")
    parser.add_argument("--flight", type=int, default=None,
                        help="Flight number — auto-discover TIFFs needing picks")
    parser.add_argument("--tiff", type=int, default=None,
                        help="Specific TIFF ID to re-pick (requires --flight)")
    parser.add_argument("--cbds", type=str, default=None,
                        help="Comma-separated CBD numbers to show (skip others)")
    return parser.parse_args()


# -- TIFF queue logic ----------------------------------------------------------

def _row_fkey(row, dup_cbds: set | None = None) -> str:
    """Build a unique frame key.  When a CBD appears on multiple frames
    (duplicate CBD), disambiguate with frame_idx to avoid key collision."""
    cbd = str(getattr(row, "cbd", "") or "")
    fidx = int(getattr(row, "frame_idx", -1))
    if cbd and dup_cbds and cbd in dup_cbds:
        return f"CBD{cbd}_f{fidx}"
    return f"CBD{cbd}" if cbd else f"fr{fidx}"


def _detect_dup_cbds(rows) -> set:
    """Return set of CBD strings that appear more than once in the frame list."""
    from collections import Counter
    cbds = [str(getattr(r, "cbd", "") or "") for r in rows
            if str(getattr(r, "cbd", "") or "")]
    return {c for c, n in Counter(cbds).items() if n > 1}


def tiff_needs_picks(tiff_name: str, index_df: pd.DataFrame, picks: dict) -> bool:
    """Check if a TIFF has at least one frame with M + R + X picks."""
    tiff_rows = index_df[(index_df["tiff"] == tiff_name) &
                         (index_df["frame_type"] == "complete")]
    for _, row in tiff_rows.iterrows():
        cbd = str(row.get("cbd", "") or "")
        fkey = f"CBD{cbd}" if cbd else f"fr{row['frame_idx']}"
        p = picks.get(fkey, {})
        if (p.get("mb") is not None and p.get("ref") is not None
                and len(p.get("x_grid", [])) >= 2):
            return False
    return True


def build_tiff_queue(args) -> tuple[list[Path], int, Path]:
    """Build list of TIFF paths to process. Returns (tiff_list, flt, out_dir)."""

    if args.flight is not None:
        flt = args.flight
        raw_dir = ROOT / f"tiff/{flt}"
        if not raw_dir.exists():
            raw_dir = ROOT / "tiff"
        out_dir = ROOT / f"output/F{flt}"
        phase1_dir = out_dir / "phase1"
        index_csv = phase1_dir / f"F{flt}_frame_index.csv"
        picks_json = phase1_dir / f"F{flt}_cal_picks.json"

        if not raw_dir.exists():
            sys.exit(f"ERROR: Raw data directory not found: {raw_dir}")
        if not index_csv.exists():
            sys.exit(f"ERROR: Frame index not found: {index_csv}\n"
                     "Run phase 1 first (detect_frames.py or run_flight.py).")

        index_df = pd.read_csv(index_csv, dtype=str)
        picks = {}
        if picks_json.exists():
            with open(picks_json) as f:
                picks = json.load(f)

        # Discover all canonical TIFFs
        all_tiffs = sorted(raw_dir.glob("*.tiff"), key=lambda t: lyra_tiff_id(t))
        canonical = [t for t in all_tiffs if "_" in t.stem and t.stem[0].isdigit()]

        if args.tiff is not None:
            # Single TIFF by ID — exact match (compare as integers to handle
            # zero-padding: --tiff 25 matches tiff_id "0025")
            target_id = int(args.tiff)
            matches = [t for t in canonical
                       if lyra_tiff_id(t).lstrip("0") == str(target_id)
                       or (target_id == 0 and lyra_tiff_id(t).lstrip("0") == "")]
            if not matches:
                sys.exit(f"ERROR: No TIFF matching ID {args.tiff} in {raw_dir}")
            return [ensure_canonical_name(matches[0])], flt, out_dir

        # Filter to TIFFs needing picks
        queue = []
        for tiff in canonical:
            tiff = ensure_canonical_name(tiff)
            if tiff_needs_picks(tiff.name, index_df, picks):
                queue.append(tiff)

        if not queue:
            print(f"\n  All TIFFs in F{flt} already have M+R+X picks. Nothing to do.")
            sys.exit(0)

        print(f"\n  Flight F{flt}: {len(queue)} of {len(canonical)} TIFFs need picks")
        return queue, flt, out_dir

    else:
        # Single TIFF mode (backward compatible)
        if args.tiff is not None:
            sys.exit("ERROR: --tiff requires --flight")

        if args.tiff_path:
            tiff = resolve_tiff_arg(args.tiff_path, ROOT)
        else:
            tiff = ROOT / "tiff/125/40_0008400_0008424-reel_begin_end.tiff"

        tiff = ensure_canonical_name(tiff)
        try:
            flt = int(tiff.parent.name.lstrip("Ff"))
        except ValueError:
            flt = int(os.environ.get("LYRA_FLIGHT", "0"))
        if flt <= 0:
            sys.exit("ERROR: Cannot infer flight; use FLT/TIFF_ID or tiff/<flight>/.")
        out_dir = ROOT / f"output/F{flt}"
        return [tiff], flt, out_dir


# -- Save + derive -------------------------------------------------------------

def save_picks_and_derive(all_picks: dict, flt: int, out_dir: Path):
    """Save raw picks JSON and derive spacing constants."""
    phase1_dir = out_dir / "phase1"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    picks_json = phase1_dir / f"F{flt}_cal_picks.json"

    with open(picks_json, "w") as f:
        json.dump(all_picks, f, indent=2)

    # Derive spacing constants
    x_spacings: list[float] = []
    y_spacings: list[float] = []

    for fkey, p in all_picks.items():
        if p.get("exclude"):
            continue
        xg = sorted(float(v) for v in p.get("x_grid", []))
        if len(xg) >= 4:
            # Use all four X-grid clicks.  Clicks may skip major divisions, so
            # infer each click's integer division index from the default spacing,
            # then fit x = intercept + spacing * division_index.
            k = np.array([round((x - xg[0]) / _PX_PER_DIV_X) for x in xg], dtype=float)
            if len(np.unique(k)) >= 2:
                spacing = abs(float(np.polyfit(k, np.array(xg, dtype=float), 1)[0]))
                x_spacings.append(spacing)

        yg = sorted(p.get("y_grid", []))
        if len(yg) == 2:
            raw = abs(yg[1] - yg[0])
            n_div = max(1, round(raw / _PX_PER_DIV_Y))
            y_spacings.append(raw / n_div)

    x_spacing_px = float(np.median(x_spacings)) if x_spacings else _PX_PER_DIV_X
    y_spacing_px = float(np.median(y_spacings)) if y_spacings else _PX_PER_DIV_Y

    mb_guides  = {k: v["mb"]  for k, v in all_picks.items()
                  if v.get("mb")  is not None and not v.get("exclude")}
    ref_guides = {k: v["ref"] for k, v in all_picks.items()
                  if v.get("ref") is not None}

    derived = {
        "flight":            flt,
        "n_frames_picked":   len(all_picks),
        "x_spacing_px":      round(x_spacing_px, 3),
        "y_spacing_px":      round(y_spacing_px, 3),
        "us_per_px":         round(2.0  / x_spacing_px, 8),
        "db_per_px":         round(10.0 / y_spacing_px, 8),
        "x_spacings_per_frame": {
            k: round(abs(float(np.polyfit(
                np.array([round((x - min(v.get("x_grid", []))) / _PX_PER_DIV_X)
                          for x in sorted(float(z) for z in v.get("x_grid", []))], dtype=float),
                np.array(sorted(float(z) for z in v.get("x_grid", [])), dtype=float), 1)[0])), 2)
            for k, v in all_picks.items()
            if len(v.get("x_grid", [])) >= 4
        },
        "y_spacings_per_frame": {
            k: round(abs(sorted(v.get("y_grid",[])[:])[1] - sorted(v.get("y_grid",[])[:])[0]) /
                     max(1, round(abs(sorted(v.get("y_grid",[])[:])[1] - sorted(v.get("y_grid",[])[:])[0]) / _PX_PER_DIV_Y)), 2)
            for k, v in all_picks.items()
            if len(v.get("y_grid", [])) == 2
        },
        "mb_guides":  mb_guides,
        "ref_guides": ref_guides,
    }

    derived_json = phase1_dir / f"F{flt}_cal_derived.json"
    with open(derived_json, "w") as f:
        json.dump(derived, f, indent=2)

    return picks_json, derived_json, derived


# -- Interactive picker for one TIFF -------------------------------------------

def pick_one_tiff(tiff_path: Path, flt: int, all_picks: dict,
                  tiff_num: int, total_tiffs: int, is_flight_mode: bool,
                  cbd_filter: set[int] | None = None) -> str:
    """Run interactive picker on one TIFF.

    Args:
        cbd_filter: if set, only show frames with CBD in this set.

    Returns action: 'next_tiff' (Q in flight mode), 'quit' (Q in single mode
    or Esc), or 'done' (all frames processed).
    """
    tiff_path = ensure_canonical_name(tiff_path)
    tid = lyra_tiff_id(tiff_path)
    out_dir = ROOT / f"output/F{flt}"
    index_csv = out_dir / "phase1" / f"F{flt}_frame_index.csv"

    index = pd.read_csv(index_csv, dtype=str)
    tiff_rows = index[(index["tiff"] == tiff_path.name) &
                      (index["frame_type"] == "complete")].copy()

    if len(tiff_rows) == 0:
        print(f"  WARNING: no complete frames for {tiff_path.name} — skipping")
        return "next_tiff"

    # Load image
    tiff_label = f"TIFF {tiff_num}/{total_tiffs}" if is_flight_mode else ""
    print(f"\n{'='*60}")
    print(f"  {tiff_label}  {tiff_path.name}")
    print(f"  Flight F{flt}  |  TIFF_ID {tid}  |  Complete frames: {len(tiff_rows)}")
    print(f"  Loading TIFF ...")
    Image.MAX_IMAGE_PIXELS = None
    img = np.array(Image.open(tiff_path), dtype=np.float32)
    img_norm = (img - img.min()) / (img.max() - img.min() + 1e-9)
    H, W = img_norm.shape
    print(f"  Image: {W} x {H} px")

    if is_flight_mode:
        print(f"  Q = save & next TIFF  |  N = next  |  B = back  |  Esc = quit entirely")
    else:
        print(f"  Q = save & quit  |  N = next  |  B = back")

    # Detect duplicate CBDs within this TIFF (need disambiguated keys)
    all_rows = list(tiff_rows.itertuples())
    dup_cbds = _detect_dup_cbds(all_rows)
    if dup_cbds:
        print(f"  Duplicate CBDs in TIFF: {sorted(dup_cbds)} -- using frame_idx-disambiguated keys")
        # Migrate existing picks from old CBD-only key to disambiguated key
        for r in all_rows:
            cbd = str(getattr(r, "cbd", "") or "")
            if cbd in dup_cbds:
                old_key = f"CBD{cbd}"
                new_key = _row_fkey(r, dup_cbds)
                if old_key in all_picks and new_key not in all_picks:
                    # Only migrate if the new key doesn't exist yet
                    all_picks[new_key] = all_picks[old_key]

    # Build frame list (skip excluded)
    frame_list = [r for r in all_rows
                  if not all_picks.get(_row_fkey(r, dup_cbds), {}).get("exclude")]
    n_excl = len(all_rows) - len(frame_list)
    if n_excl:
        excl_keys = [_row_fkey(r, dup_cbds) for r in all_rows
                     if all_picks.get(_row_fkey(r, dup_cbds), {}).get("exclude")]
        print(f"  Skipping {n_excl} excluded frame(s): {excl_keys}")

    # Apply CBD filter (show only specified CBDs)
    if cbd_filter is not None:
        pre_len = len(frame_list)
        frame_list = [r for r in frame_list
                      if int(getattr(r, "cbd", 0) or 0) in cbd_filter]
        print(f"  CBD filter: showing {len(frame_list)} of {pre_len} frames")

    frame_i = 0
    final_action = "done"

    while frame_i < len(frame_list):
        row = frame_list[frame_i]
        cbd = str(getattr(row, "cbd", "") or "")
        fkey = _row_fkey(row, dup_cbds)
        left_px = int(row.left_px)
        right_px = int(row.right_px)
        frame_w = right_px - left_px + 1

        print(f"\n{'-'*60}")
        frame_label = f"  [{frame_i+1}/{len(frame_list)}]  {fkey}"
        if is_flight_mode:
            frame_label = f"  TIFF {tiff_num}/{total_tiffs}  " + frame_label
        print(f"{frame_label}  cols {left_px}–{right_px}  (width {frame_w} px)")
        print(f"  M=main bang  R=ref -60dB  Y=y-grid  X=x-grid  "
              f"U=undo  N=next  B=back  S=skip  Q={'next TIFF' if is_flight_mode else 'quit'}")

        # Extract + display-stretch this frame
        frame = img_norm[:, left_px:right_px + 1]
        crop = frame[Y_CROP_LO:min(Y_CROP_HI, H), :]
        p2, p98 = np.percentile(crop, 2), np.percentile(crop, 98)
        disp = np.clip((crop - p2) / (p98 - p2 + 1e-9), 0, 1)

        # Per-frame mutable state
        init = all_picks.get(fkey, {})
        st = {
            "mode":  "mb",
            "picks": {
                "mb":     init.get("mb"),
                "ref":    init.get("ref"),
                "y_grid": list(init.get("y_grid", [])),
                "x_grid": list(init.get("x_grid", [])),
            },
            "action": None,
            "drawn":  [],
        }

        # -- Build figure --------------------------------------------------
        # Disable matplotlib default keybindings that conflict with our keys
        for param in list(plt.rcParams):
            if param.startswith("keymap."):
                plt.rcParams[param] = []
        fig, ax = plt.subplots(figsize=(16, 8))
        fig.patch.set_facecolor("white")

        ax.imshow(disp, cmap="gray", vmin=0, vmax=1, aspect="auto",
                  extent=[0, frame_w, Y_CROP_HI, Y_CROP_LO])
        ax.set_ylim(Y_CROP_HI, Y_CROP_LO)
        ax.set_xlabel("X pixel (frame-relative)", fontsize=9)
        ax.set_ylabel("Y pixel (image)", fontsize=9)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        for k in range(-3, 7):
            y_guide = _DB_REF_PX - k * _PX_PER_DIV_Y
            if Y_CROP_LO < y_guide < Y_CROP_HI:
                ax.axhline(y_guide, color="0.65", lw=0.5, ls="--", alpha=0.5)
                db_val = -60 + k * 10
                ax.text(frame_w - 8, y_guide - 10, f"{db_val:+d} dB",
                        color="0.55", fontsize=6, ha="right", va="bottom")

        status_bar = fig.text(
            0.5, 0.005, "", ha="center", fontsize=10,
            bbox=dict(boxstyle="round", fc="wheat", alpha=0.85))

        def _update_status():
            m = st["mode"]
            p = st["picks"]
            col = MODE_COLORS[m]
            lbl = MODE_LABELS[m]
            prefix = f"TIFF {tiff_num}/{total_tiffs} | " if is_flight_mode else ""
            status_bar.set_text(
                f"{prefix}[{frame_i+1}/{len(frame_list)}] {fkey}  |  {lbl}    "
                f"mb={1 if p['mb'] is not None else 0}  "
                f"ref={1 if p['ref'] is not None else 0}  "
                f"y_grid={len(p['y_grid'])}/2  x_grid={len(p['x_grid'])}/4"
            )
            status_bar.set_color(col)

        def _redraw():
            for art in st["drawn"]:
                try:
                    art.remove()
                except Exception:
                    pass
            st["drawn"].clear()
            p = st["picks"]

            if p["mb"] is not None:
                x = p["mb"]
                st["drawn"] += [
                    ax.axvline(x, color="red", lw=2.0, ls="--", alpha=0.9),
                    ax.text(x + 8, Y_CROP_LO + 60, f"MB\nx={x}",
                            color="red", fontsize=8, fontweight="bold", va="top"),
                ]

            if p["ref"] is not None:
                y = p["ref"]
                st["drawn"] += [
                    ax.axhline(y, color="cyan", lw=2.0, ls="--", alpha=0.9),
                    ax.text(10, y - 18, f"-60 dB  y={y}",
                            color="cyan", fontsize=8, fontweight="bold"),
                ]

            for y in p["y_grid"]:
                st["drawn"] += [
                    ax.axhline(y, color="limegreen", lw=1.5, ls=":", alpha=0.9),
                    ax.text(10, y - 14, f"Ygrid y={y}",
                            color="limegreen", fontsize=7),
                ]

            for x in p["x_grid"]:
                st["drawn"] += [
                    ax.axvline(x, color="orange", lw=1.5, ls=":", alpha=0.9),
                    ax.text(x + 5, Y_CROP_LO + 130, f"Xgrid\nx={x}",
                            color="orange", fontsize=7, va="top", rotation=90),
                ]

            title_prefix = f"TIFF {tiff_num}/{total_tiffs} — " if is_flight_mode else ""
            q_label = "Q=next TIFF" if is_flight_mode else "Q=quit"
            ax.set_title(
                f"LYRA Calibration Picker — {title_prefix}TIFF {tid} — F{flt}  {fkey}  "
                f"[{frame_i+1}/{len(frame_list)}]\n"
                f"Gray dashed = default-cal prediction  |  "
                f"M=main bang  R=ref-60dB  Y=y-grid  X=x-grid  "
                f"U=undo  N=next  B=back  S=skip  {q_label}",
                fontsize=8, loc="left",
            )

        def _refresh():
            fig.canvas.draw_idle()
            fig.canvas.flush_events()

        # -- Event handlers ------------------------------------------------
        def on_click(event):
            if event.inaxes != ax or event.button != 1:
                return
            x = int(round(event.xdata))
            y = int(round(event.ydata))
            p = st["picks"]
            m = st["mode"]

            if m == "mb":
                p["mb"] = x
                print(f"    MB:     x={x} px (frame-relative)")
            elif m == "ref":
                p["ref"] = y
                print(f"    Ref:    y={y} px  ({(-60 + (_DB_REF_PX - y) * 10.0/_PX_PER_DIV_Y):+.1f} dB by default cal)")
            elif m == "y_grid":
                if len(p["y_grid"]) < 2:
                    p["y_grid"].append(y)
                    p["y_grid"].sort()
                    db_approx = -60 + (_DB_REF_PX - y) * 10.0 / _PX_PER_DIV_Y
                    print(f"    Y-grid: y={y} px  (~{db_approx:+.1f} dB by default cal)  "
                          f"total {len(p['y_grid'])}/2")
                else:
                    print(f"    Y-grid: already has 2 picks — press U to undo, or switch mode")
            elif m == "x_grid":
                if len(p["x_grid"]) < 4:
                    p["x_grid"].append(x)
                    p["x_grid"].sort()
                    us_approx = (x - (p["mb"] or 800)) * 2.0 / _PX_PER_DIV_X
                    print(f"    X-grid: x={x} px  (~{us_approx:+.2f} µs from MB guess)  "
                          f"total {len(p['x_grid'])}/4")
                else:
                    print(f"    X-grid: already has 4 picks — press U to undo, or switch mode")

            _redraw()
            _update_status()
            _refresh()

        def on_key(event):
            key = (event.key or "").lower()
            p = st["picks"]

            if key == "m":
                st["mode"] = "mb"
                print(">> Mode: Main Bang  (click near the leftmost spike)")
            elif key == "r":
                st["mode"] = "ref"
                print(">> Mode: Reference line -60 dB  (click the bottom baseline)")
            elif key == "y":
                st["mode"] = "y_grid"
                p["y_grid"].clear()
                print(">> Mode: Y-grid  (click 2 horizontal major lines)")
            elif key == "x":
                st["mode"] = "x_grid"
                p["x_grid"].clear()
                print(">> Mode: X-grid  (click 2 vertical major lines)")
            elif key == "u":
                m = st["mode"]
                if m == "mb" and p["mb"] is not None:
                    p["mb"] = None
                    print("  Undo: MB cleared")
                elif m == "ref" and p["ref"] is not None:
                    p["ref"] = None
                    print("  Undo: ref cleared")
                elif m == "y_grid" and p["y_grid"]:
                    v = p["y_grid"].pop()
                    print(f"  Undo: y_grid y={v} removed")
                elif m == "x_grid" and p["x_grid"]:
                    v = p["x_grid"].pop()
                    print(f"  Undo: x_grid x={v} removed")
            elif key == "n":
                st["action"] = "next"
                plt.close(fig)
                return
            elif key in ("b", "backspace"):
                st["action"] = "back"
                plt.close(fig)
                return
            elif key == "s":
                st["action"] = "skip"
                plt.close(fig)
                return
            elif key == "q":
                st["action"] = "quit"
                plt.close(fig)
                return
            elif key == "escape":
                st["action"] = "escape"
                plt.close(fig)
                return

            _redraw()
            _update_status()
            _refresh()

        fig.canvas.mpl_connect("button_press_event", on_click)
        fig.canvas.mpl_connect("key_press_event", on_key)
        plt.subplots_adjust(bottom=0.06, top=0.92)
        _redraw()
        _update_status()
        _refresh()
        plt.show()

        # -- Post-window: process action -----------------------------------
        p = st["picks"]

        def _save_frame_picks(fkey, p):
            existing = all_picks.get(fkey, {})
            p_save = dict(p)
            for k in ("exclude", "exclude_reason"):
                if k in existing:
                    p_save[k] = existing[k]
            all_picks[fkey] = p_save

        if st["action"] == "escape":
            _save_frame_picks(fkey, p)
            print(f"\n  Escape — picks for {fkey} saved. Quitting entirely.")
            final_action = "quit"
            break
        elif st["action"] == "quit":
            _save_frame_picks(fkey, p)
            if is_flight_mode:
                print(f"  Saved {fkey} — advancing to next TIFF.")
                final_action = "next_tiff"
            else:
                print(f"\n  Quitting — picks for {fkey} saved.")
                final_action = "quit"
            break
        elif st["action"] == "back":
            _save_frame_picks(fkey, p)
            if frame_i > 0:
                print(f"  Saved {fkey} — going back to previous frame.")
                frame_i -= 1
            else:
                print(f"  Already at first frame.")
            continue
        elif st["action"] == "skip":
            print(f"  Skipped {fkey} (no picks saved).")
            frame_i += 1
            continue
        else:  # "next" or window closed
            _save_frame_picks(fkey, p)
            print(f"  Saved {fkey}:  "
                  f"mb={p['mb']}  ref={p['ref']}  "
                  f"y_grid={p['y_grid']}  x_grid={p['x_grid']}")
            frame_i += 1

    return final_action


# -- Main ----------------------------------------------------------------------

def main():
    args = parse_args()
    tiff_queue, flt, out_dir = build_tiff_queue(args)
    is_flight_mode = args.flight is not None
    phase1_dir = out_dir / "phase1"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    picks_json = phase1_dir / f"F{flt}_cal_picks.json"

    # Load existing picks
    all_picks: dict = {}
    if picks_json.exists():
        with open(picks_json) as f:
            all_picks = json.load(f)
        print(f"  Loaded {len(all_picks)} existing picks from {picks_json.name}")

    # Parse CBD filter
    cbd_filter: set[int] | None = None
    if args.cbds:
        cbd_filter = {int(c.strip()) for c in args.cbds.split(",")}

    total = len(tiff_queue)
    for i, tiff in enumerate(tiff_queue, 1):
        action = pick_one_tiff(tiff, flt, all_picks, i, total, is_flight_mode,
                               cbd_filter=cbd_filter)

        # Save after each TIFF (incremental — don't lose work)
        pj, dj, derived = save_picks_and_derive(all_picks, flt, out_dir)
        print(f"  Picks saved -> {pj.relative_to(ROOT)}")

        if action == "quit":
            break

    # Final summary
    _, _, derived = save_picks_and_derive(all_picks, flt, out_dir)
    print(f"\nDone. Total frames with picks: {len(all_picks)}")
    print(f"  x_spacing_px : {derived['x_spacing_px']:.2f} px  -> {derived['us_per_px']:.6f} µs/px")
    print(f"  y_spacing_px : {derived['y_spacing_px']:.2f} px  -> {derived['db_per_px']:.6f} dB/px")
    print(f"  MB guides    : {len(derived['mb_guides'])}")
    print(f"  Ref guides   : {len(derived['ref_guides'])}")

    if is_flight_mode:
        # Check how many TIFFs still need picks
        index_csv = phase1_dir / f"F{flt}_frame_index.csv"
        if index_csv.exists():
            index_df = pd.read_csv(index_csv, dtype=str)
            raw_dir = ROOT / f"tiff/{flt}"
            if not raw_dir.exists():
                raw_dir = ROOT / "tiff"
            all_tiffs = sorted(raw_dir.glob("*.tiff"), key=lambda t: lyra_tiff_id(t))
            canonical = [t for t in all_tiffs if "_" in t.stem and t.stem[0].isdigit()]
            still_need = sum(1 for t in canonical
                             if tiff_needs_picks(ensure_canonical_name(t).name,
                                                 index_df, all_picks))
            if still_need:
                print(f"\n  {still_need} TIFFs still need M+R+X picks.")
                print(f"  Re-run: python codes/pick_calibration.py --flight {flt}")
            else:
                print(f"\n  All TIFFs in F{flt} now have M+R+X picks.")



if __name__ == "__main__":
    main()
