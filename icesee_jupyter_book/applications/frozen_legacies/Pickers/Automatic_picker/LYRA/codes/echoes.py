# pyright: reportArgumentType=false, reportGeneralTypeIssues=false, reportCallIssue=false, reportAttributeAccessIssue=false
"""
echoes.py — LYRA Phase 4: Surface/bed echo extraction
============================================================
For each calibrated frame (from phase3 cal CSV) extract surface and bed echoes:

  • Noise floor estimation (pre-bang 75th-percentile baseline)
  • Echo peak detection  (prominence >= 5 dB, distance >= 80 px)
  • Envelope walking at +5 dB and +10 dB above noise floor
  • Waveform shape metrics: peakiness, asymmetry, trailing_tail, leading_rise
  • Derived geometry:
      h_air_m  = surface_twt / 2 × c_air   (air column height)
      h_ice_m  = (bed_twt - surface_twt) / 2 × c_ice   (ice thickness)
      h_eff_m  = h_air_m + h_ice_m / n_ice   (effective propagation distance)

Echo status:
  good       — surface + bed detected, bed SNR >= WEAK_BED_SNR_DB (5 dB)
  weak_bed   — bed detected but SNR < WEAK_BED_SNR_DB (marginal; inspect figure)
  no_bed     — surface detected, no bed echo found
  no_surface — surface not detected; geometry undefined

Per-frame calibration is taken directly from the phase3 cal CSV (mb_x, y_ref_px,
db_per_px, us_per_px).  Detection parameters (prominence, distance, Gaussian sigma)
are taken from DEFAULT_CAL.

Usage
-----
Normal mode (extract echoes):
    python codes/echoes.py [TIFF_PATH]

Review mode (interactive override -- click on image panel):
    python codes/echoes.py TIFF --review          # bad frames only
    python codes/echoes.py TIFF --review --all     # all frames

Flight-wide mode (all TIFFs for a flight):
    python codes/echoes.py --flight 125                    # normal mode, all TIFFs
    python codes/echoes.py --flight 125 --review           # review all TIFFs
    python codes/echoes.py --flight 125 --review --all     # review all frames in all TIFFs

    Keys: [s]=surface mode  [b]=bed mode  click=set position
          [S]=suppress surface  [B]=suppress bed  (mark as not present)
          [d]=clear all overrides  [n/Right]=next  [p/Left]=prev  [q]=save & quit

If TIFF_PATH is omitted, defaults to the F125 training TIFF (40_0008400…).

Outputs
-------
Per-flight echo CSV (updated incrementally):
    output/F{FLT}/phase4/F{FLT}_echoes.csv
      Columns: flight, tiff, cbd, file_id, echo_status,
               noise_floor_dB, mb_power_dB, mb_correction_dB,
               surface_twt_us, surface_power_dB, surface_snr_dB,
               surface_width_10_us, surface_width_5_us, surface_peakiness,
               surface_asymmetry, surface_leading_rise_us, surface_trailing_tail_us,
               bed_twt_us, bed_power_dB, bed_snr_dB,
               bed_width_10_us, bed_width_5_us, bed_peakiness,
               bed_asymmetry, bed_leading_rise_us, bed_trailing_tail_us,
               h_air_m, h_ice_m, h_eff_m
      Power/SNR values are gain-corrected using the main bang as a per-frame
      reference (mb_correction_dB = flight_median_mb - frame_mb_power).

Per-frame diagnostic figure (two-panel):
    output/F{FLT}/phase4/F{FLT}_{file_id}_echoes.png
      Left  : frame image with echo markers (pixel space, same scale as phase3)
      Right : waveform in physical units (TWT µs vs power dB)
"""

from pathlib import Path
import sys
import os
import json
import argparse

import numpy as np
import pandas as pd

# -- Parse arguments before matplotlib (backend depends on --review) -----------
_parser = argparse.ArgumentParser(
    description="LYRA Phase 4: Surface/bed echo extraction",
    epilog="Review mode: --review shows bad frames for manual echo override",
)
_parser.add_argument("tiff", nargs="?", help="TIFF path or FLT/TIFF_ID format")
_parser.add_argument("--review", action="store_true",
                     help="Interactive review: click on image to override surface/bed picks")
_parser.add_argument("--all", action="store_true",
                     help="With --review: show all frames (default: only no_bed/no_surface/weak_bed)")
_parser.add_argument("--flight", type=int, metavar="FLT",
                     help="Process all TIFFs for a flight (e.g. --flight 125). "
                          "Works with --review to iterate through every TIFF.")
_args = _parser.parse_args()

import matplotlib
if not _args.review:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

# Figure typography. On Windows Segoe UI is used and embedded in EPS output.
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "DejaVu Sans"],
    "font.size": 9,
    "axes.titlesize": 9,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "ps.fonttype": 42,
    "pdf.fonttype": 42,
    "svg.fonttype": "none",  # Keep text editable in Illustrator/Inkscape
    "svg.image_inline": True,  # Embed film images in standalone SVGs
})

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "codes"))

# -- Flight-wide mode: loop through all TIFFs for a flight ---------------------
# When --flight N is given, find all TIFFs and re-invoke echoes.py on each one.
# Works with --review, --all, and normal mode.
if _args.flight is not None:
    import subprocess
    flt = _args.flight
    cal_csv = ROOT / f"output/F{flt}/phase3/F{flt}_cal.csv"
    if not cal_csv.exists():
        sys.exit(f"ERROR: No cal CSV at {cal_csv}")
    cal_df = pd.read_csv(cal_csv, dtype=str)
    tiff_ids = sorted(cal_df["tiff_id"].unique(), key=int)
    print(f"Flight F{flt}: {len(tiff_ids)} TIFFs to process\n")
    script = str(Path(__file__).resolve())
    for i, tid in enumerate(tiff_ids, 1):
        cmd = [sys.executable, script, f"{flt}/{tid}"]
        if _args.review:
            cmd.append("--review")
        if _args.all:
            cmd.append("--all")
        print(f"{'='*60}")
        print(f"  TIFF {tid}  ({i}/{len(tiff_ids)})")
        print(f"{'='*60}")
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"  WARNING: TIFF {tid} exited with code {result.returncode}")
        print()
    print(f"Flight F{flt}: all {len(tiff_ids)} TIFFs done.")
    sys.exit(0)

from lyra import (
    DEFAULT_CAL,
    extract_trace, estimate_noise_floor,
    detect_echoes, compute_echo_metrics,
    extract_local_profile,
    px_to_db, px_to_us, db_to_px, us_to_px,
    C_AIR_M_PER_US, C_ICE_M_PER_US,
    ensure_canonical_name, resolve_tiff_arg, tiff_id,
)

# -- Scientific constants -------------------------------------------------------
N_ICE           = 1.78   # refractive index of ice (Neal 1977)
WEAK_BED_SNR_DB = 5.0    # bed SNR threshold below which status = "weak_bed"

# -- Resolve TIFF path ----------------------------------------------------------
if _args.tiff:
    TIFF = resolve_tiff_arg(_args.tiff, ROOT)
else:
    TIFF = ROOT / "tiff/125/40_0008400_0008424-reel_begin_end.tiff"

TIFF = ensure_canonical_name(TIFF)

try:
    FLT = int(TIFF.parent.name.lstrip("Ff"))
except ValueError:
    FLT = int(os.environ.get("LYRA_FLIGHT", "0"))
if FLT <= 0:
    sys.exit("ERROR: Cannot infer flight; use FLT/TIFF_ID (e.g. 127/4800) or tiff/127/.")


TIFF_ID   = tiff_id(TIFF)
OUT_DIR   = ROOT / f"output/F{FLT}"
PHASE1_DIR = OUT_DIR / "phase1"
PHASE3_DIR = OUT_DIR / "phase3"
PHASE4_DIR = OUT_DIR / "phase4"
PHASE4_DIR.mkdir(parents=True, exist_ok=True)

INDEX_CSV  = PHASE1_DIR / f"F{FLT}_frame_index.csv"
CAL_CSV    = PHASE3_DIR / f"F{FLT}_cal.csv"
ECHO_CSV   = PHASE4_DIR / f"F{FLT}_echoes.csv"

# -- Validate prerequisites -----------------------------------------------------
if not INDEX_CSV.exists():
    sys.exit(f"ERROR: frame index not found at {INDEX_CSV}\n"
             "Run phase 1 (detect_frames.py) first.")

if not CAL_CSV.exists():
    sys.exit(f"ERROR: phase 3 calibration CSV not found at {CAL_CSV}\n"
             "Run phase 3 (calibrate.py) first.")

# -- Load phase1 frame index ---------------------------------------------------
index     = pd.read_csv(INDEX_CSV, dtype=str)
tiff_rows = index[index["tiff"] == TIFF.name].copy()

if len(tiff_rows) == 0:
    sys.exit(f"ERROR: {TIFF.name} not found in frame index.\n"
             "Run phase 1 (detect_frames.py) for this TIFF first.")

# -- Load phase3 calibration CSV ------------------------------------------------
cal_df    = pd.read_csv(CAL_CSV, dtype=str)
tiff_cals = cal_df[cal_df["tiff"] == TIFF.name].copy()

if len(tiff_cals) == 0:
    sys.exit(f"ERROR: No phase 3 calibration rows for {TIFF.name} in {CAL_CSV}\n"
             "Run phase 3 (calibrate.py) for this TIFF first.")

# -- Flight-wide mb_power reference for per-frame gain correction --------------
# The main bang is a fixed internal signal (T/R switch leakage) that traverses
# the full receiver chain but never leaves the aircraft.  Variation in mb_power
# across frames reflects system gain changes (attenuator setting, CRT intensity)
# rather than geophysical signal.  We use the flight-wide median as the expected
# MB power and correct each frame's echo powers accordingly.
_all_cals = cal_df.copy()
_all_cals["mb_power_dB"] = pd.to_numeric(_all_cals["mb_power_dB"], errors="coerce")
_excl_mask = _all_cals["exclude_reason"].fillna("").astype(str).str.strip().isin(["", "nan"])
_valid_mb  = _all_cals.loc[_excl_mask, "mb_power_dB"].dropna()
FLIGHT_MB_REF_DB = float(_valid_mb.median()) if len(_valid_mb) > 0 else -37.0

# Build frame_idx -> calibration dict mapping (skip excluded frames)
frame_cal: dict[int, dict] = {}
for _, row in tiff_cals.iterrows():
    # Skip excluded frames (empty mb_x means no calibration was performed)
    if row.get("exclude_reason", "") not in ("", "nan") and str(row.get("exclude_reason", "")) not in ("", "nan"):
        print(f"  Skipping frame {row['frame_idx']} ({row.get('cbd','?')}): {row['exclude_reason']}")
        continue
    if not row["mb_x"] or str(row["mb_x"]).strip() == "":
        continue
    fidx = int(row["frame_idx"])
    _mb_pwr = float(row["mb_power_dB"]) if row.get("mb_power_dB") else FLIGHT_MB_REF_DB
    frame_cal[fidx] = dict(
        mb_x        = int(float(row["mb_x"])),
        y_ref_px    = float(row["y_ref_px"]),
        db_per_px   = float(row["db_per_px"]),
        us_per_px   = float(row["us_per_px"]),
        cbd         = row["cbd"],
        file_id     = row["file_id"],
        tiff_id     = row.get("tiff_id", TIFF_ID),
        mb_power_dB = _mb_pwr,
        mb_correction_dB = round(FLIGHT_MB_REF_DB - _mb_pwr, 2),
    )

print(f"\nLYRA Step 3 — {TIFF.name}")
print(f"  Flight : F{FLT}  |  tiff_id : {TIFF_ID}")
print(f"  Calibrated frames in step2 CSV : {len(frame_cal)}")
# Show mb_power correction info
_this_mb = [c["mb_power_dB"] for c in frame_cal.values()]
_this_corr = [c["mb_correction_dB"] for c in frame_cal.values()]
_max_abs_corr = max(abs(c) for c in _this_corr) if _this_corr else 0
print(f"  MB power ref  : {FLIGHT_MB_REF_DB:.1f} dB (flight median)")
if _max_abs_corr > 0.5:
    print(f"  MB correction : this TIFF range [{min(_this_corr):+.1f}, {max(_this_corr):+.1f}] dB")
else:
    print(f"  MB correction : < 0.5 dB (negligible)")
print()

# -- Load TIFF image ------------------------------------------------------------
print("Loading TIFF ...")
Image.MAX_IMAGE_PIXELS = None
img      = np.array(Image.open(TIFF), dtype=np.float32)
img_norm = (img - img.min()) / (img.max() - img.min() + 1e-9)
H, W_img = img_norm.shape
print(f"  Image  : {W_img} × {H} px\n")

# Contact-strip thumbnails are prepared once per TIFF and reused in the
# publication figure for every complete frame. They are visual only.
# Keep the native image proportions by resizing with thumbnail(), not resize().
pub_frame_thumbnails = []
for _, _strip_row in tiff_rows.sort_values(
        "frame_idx", key=lambda col: pd.to_numeric(col, errors="coerce")
).iterrows():
    _a = int(_strip_row["left_px"])
    _b = int(_strip_row["right_px"]) + 1
    _frame_img = np.asarray(np.clip(img_norm[:, _a:_b] * 255, 0, 255), dtype=np.uint8)
    _thumb = Image.fromarray(_frame_img)
    _thumb.thumbnail((240, 235), Image.Resampling.LANCZOS)
    pub_frame_thumbnails.append((
        int(_strip_row["frame_idx"]),
        str(_strip_row["cbd"]) if pd.notna(_strip_row["cbd"]) else "",
        str(_strip_row["frame_type"]).strip().lower() == "partial",
        np.asarray(_thumb),
    ))

# -- Build per-frame cal dict from step2 values + DEFAULT_CAL detection params -
def _make_cal(fc: dict) -> dict:
    """Merge per-frame step2 calibration values into DEFAULT_CAL."""
    cal = DEFAULT_CAL.copy()
    cal["mb_x"]     = fc["mb_x"]     # already in frame, but passed separately
    cal["y_ref_px"] = fc["y_ref_px"]
    cal["db_per_px"]= fc["db_per_px"]
    cal["us_per_px"]= fc["us_per_px"]
    # y_ref_db stays at -60 dB (reference is always picked at -60 dB line)
    return cal


# -- Echo overrides ------------------------------------------------------------
OVERRIDES_JSON = PHASE4_DIR / f"F{FLT}_echo_overrides.json"


def load_echo_overrides() -> dict:
    """Load manual echo overrides from JSON. Keys are file_id (e.g. 'CBD0465')."""
    if OVERRIDES_JSON.exists():
        with open(OVERRIDES_JSON) as f:
            return json.load(f)
    return {}


def save_echo_overrides(overrides: dict) -> None:
    """Write echo overrides to JSON."""
    with open(OVERRIDES_JSON, "w") as f:
        json.dump(overrides, f, indent=2)
    print(f"  Overrides -> {OVERRIDES_JSON.relative_to(ROOT)}  ({len(overrides)} frames)")


echo_overrides = load_echo_overrides()
if echo_overrides:
    print(f"  Echo overrides loaded: {len(echo_overrides)} frames  ({OVERRIDES_JSON.name})")


# ==============================================================================
# Review mode — interactive echo override picker
# ==============================================================================

def review_mode():
    """Interactive review: click on image panel to override surface/bed echo positions.

    Shows ALL calibrated frames in the TIFF. Users press [s] for surface mode,
    [b] for bed mode, then click on the left (image) panel to place the pick
    directly on the CRT trace overlay.
    """

    # Need existing echo CSV to know current statuses
    if not ECHO_CSV.exists():
        sys.exit("ERROR: No echo CSV found. Run normal mode first, then --review.")

    echo_df = pd.read_csv(ECHO_CSV)
    tiff_echos = echo_df[echo_df["tiff"] == TIFF.name].copy()

    if len(tiff_echos) == 0:
        sys.exit(f"ERROR: No echo rows for {TIFF.name}. Run normal mode first.")

    # Build frame queue — default: only bad frames + frames with overrides
    # Use --all to include good frames too
    BAD_STATUSES = {"no_bed", "no_surface", "weak_bed"}
    show_all = getattr(_args, "all", False)

    review_frames = []
    all_status_counts = {}

    for _, idx_row in tiff_rows.iterrows():
        frame_idx = int(idx_row["frame_idx"])
        if idx_row["frame_type"] == "partial":
            continue
        if frame_idx not in frame_cal:
            continue

        fc = frame_cal[frame_idx]
        fkey = fc["file_id"]

        erow = tiff_echos[tiff_echos["file_id"] == fkey]
        current_status = erow.iloc[0]["echo_status"] if len(erow) > 0 else "unknown"
        all_status_counts[current_status] = all_status_counts.get(current_status, 0) + 1

        if show_all or current_status in BAD_STATUSES:
            review_frames.append((frame_idx, fc, current_status, idx_row))

    # Print TIFF summary (all frames, not just filtered)
    total = sum(all_status_counts.values())
    print(f"\nTIFF {TIFF_ID}: {total} frames total")
    for s_name in ["good", "weak_bed", "no_bed", "no_surface"]:
        if s_name in all_status_counts:
            print(f"    {s_name:12s}: {all_status_counts[s_name]}")

    if not review_frames:
        print("No frames to review (all good). Use --all to review every frame.")
        return

    filter_label = "all frames" if show_all else "bad + overridden frames only"
    print(f"\nReview: {len(review_frames)} frames ({filter_label})")
    print(f"  Click on LEFT panel (image) to place pick on CRT trace")
    print(f"  Keys: [s]=surface  [b]=bed  click=set position")
    print(f"        [S]=suppress surface  [B]=suppress bed  (mark as not present)")
    print(f"        [d]=clear overrides  [n/Right]=next  [p/Left]=prev  [q]=save & quit\n")

    frame_i = 0
    while 0 <= frame_i < len(review_frames):
        frame_idx, fc, current_status, idx_row = review_frames[frame_i]
        fkey = fc["file_id"]
        cbd = fc["cbd"]
        mb_x = fc["mb_x"]

        left_px = int(idx_row["left_px"])
        right_px = int(idx_row["right_px"])
        frame = img_norm[:, left_px:right_px + 1]
        frame_w = frame.shape[1]
        cal = _make_cal(fc)

        # Extract trace (fast, pure numpy)
        trace_y, trace_y_s, _ = extract_trace(frame, cal, robust=True, mb_x=mb_x)
        noise_floor_dB = estimate_noise_floor(trace_y_s, mb_x, cal)

        # Algorithmic detection (for reference)
        algo_surface_x, algo_bed_x = detect_echoes(trace_y_s, mb_x, noise_floor_dB, cal)

        # Current override (mutable copy)
        override = dict(echo_overrides.get(fkey, {}))

        # Mutable state for event handlers
        st = {"mode": "b", "override": override, "action": None, "drawn": []}

        us_per_px = cal["us_per_px"]

        # -- Build interactive figure ------------------------------------------
        fig = plt.figure(figsize=(18, 6), constrained_layout=True)
        fig.patch.set_facecolor("white")
        gs = fig.add_gridspec(1, 3, wspace=0.08)
        ax_img = fig.add_subplot(gs[0, :2])
        ax_wave = fig.add_subplot(gs[0, 2])

        # -- Left panel: frame image (click target) ---------------------------
        ax_img.imshow(frame, cmap="gray", vmin=0, vmax=1, aspect="auto",
                      extent=[0, frame_w, frame.shape[0], 0])
        ax_img.axhline(cal["y_ref_px"], color="cyan", lw=1.2, ls="--", alpha=0.8)
        ax_img.axvline(mb_x, color="red", lw=1.5, ls="--", alpha=0.9)
        x_all = np.arange(frame_w)
        ax_img.plot(x_all, trace_y_s, color="magenta", lw=0.8, alpha=0.7, label="trace")

        # Algo markers (faded reference)
        if algo_surface_x is not None:
            algo_srf_y = trace_y_s[algo_surface_x] if algo_surface_x < len(trace_y_s) else 0
            ax_img.plot(algo_surface_x, algo_srf_y, marker="^", color="lime",
                        markersize=7, alpha=0.35, zorder=4, label="algo srf")
            ax_img.axvline(algo_surface_x, color="lime", lw=0.5, ls=":", alpha=0.35)
        if algo_bed_x is not None:
            algo_bed_y = trace_y_s[algo_bed_x] if algo_bed_x < len(trace_y_s) else 0
            ax_img.plot(algo_bed_x, algo_bed_y, marker="^", color="orange",
                        markersize=7, alpha=0.35, zorder=4, label="algo bed")
            ax_img.axvline(algo_bed_x, color="orange", lw=0.5, ls=":", alpha=0.35)

        ax_img.set_ylim(DEFAULT_CAL["y_disp_hi"] + 50, DEFAULT_CAL["y_disp_lo"] - 50)
        ax_img.set_xlim(0, frame_w)
        ax_img.set_xlabel("Column (px) — click here to place pick", fontsize=8)
        ax_img.set_ylabel("Row (px)", fontsize=8)
        ax_img.spines["top"].set_visible(False)
        ax_img.spines["right"].set_visible(False)
        ax_img.legend(fontsize=7, loc="upper right", framealpha=0.6,
                      facecolor="black", labelcolor="white")

        # -- Right panel: waveform (reference only) ----------------------------
        twt_arr = px_to_us(np.arange(frame_w, dtype=float), mb_x, cal)
        power_arr = px_to_db(trace_y_s, cal)
        t_lo = float(cal["mb_skip_us"])
        t_hi = 25.0
        wf_mask = (twt_arr >= t_lo) & (twt_arr <= t_hi)

        ax_wave.plot(twt_arr[wf_mask], power_arr[wf_mask], color="black", lw=1.2)
        ax_wave.axhline(noise_floor_dB, color="gray", lw=1.0, ls="--", alpha=0.8,
                        label=f"NF {noise_floor_dB:.1f} dB")
        ax_wave.axhline(noise_floor_dB + 5.0, color="silver", lw=0.7, ls=":", alpha=0.8)
        ax_wave.axhline(noise_floor_dB + 10.0, color="darkgray", lw=0.7, ls=":", alpha=0.8)

        # Algo surface/bed on waveform (faded)
        if algo_surface_x is not None:
            algo_srf_twt = px_to_us(float(algo_surface_x), mb_x, cal)
            algo_srf_pwr = px_to_db(trace_y_s[algo_surface_x], cal)
            ax_wave.plot(algo_srf_twt, algo_srf_pwr, marker="^", color="limegreen",
                         markersize=7, alpha=0.35, zorder=4)
            ax_wave.axvline(algo_srf_twt, color="limegreen", lw=0.5, ls=":", alpha=0.35)
        if algo_bed_x is not None:
            algo_bed_twt = px_to_us(float(algo_bed_x), mb_x, cal)
            algo_bed_pwr = px_to_db(trace_y_s[algo_bed_x], cal)
            ax_wave.plot(algo_bed_twt, algo_bed_pwr, marker="^", color="darkorange",
                         markersize=7, alpha=0.35, zorder=4)
            ax_wave.axvline(algo_bed_twt, color="darkorange", lw=0.5, ls=":", alpha=0.35)

        p_floor = noise_floor_dB - 5.0
        p_ceil = noise_floor_dB + 50.0
        ax_wave.set_ylim(p_floor, p_ceil)
        ax_wave.set_xlim(t_lo, t_hi)
        ax_wave.set_xlabel("TWT from MB (µs)", fontsize=8)
        ax_wave.set_ylabel("Power (dB)", fontsize=8)
        ax_wave.spines["top"].set_visible(False)
        ax_wave.spines["right"].set_visible(False)
        ax_wave.tick_params(labelsize=7)
        ax_wave.legend(fontsize=6.5, loc="upper right", framealpha=0.85)

        # -- Title + status bar ------------------------------------------------
        mode_label = "BED" if st["mode"] == "b" else "SURFACE"
        status_color = {"good": "green", "weak_bed": "goldenrod",
                        "no_bed": "tomato", "no_surface": "red"}.get(current_status, "gray")
        title_obj = fig.suptitle(
            f"REVIEW  F{FLT} {fkey}  [{current_status}]  "
            f"({frame_i + 1}/{len(review_frames)})  "
            f"mode=[{mode_label}]",
            fontsize=10, color=status_color,
        )

        status_bar = fig.text(
            0.5, 0.005, "", ha="center", fontsize=9,
            bbox=dict(boxstyle="round", fc="wheat", alpha=0.85),
        )

        def _update_status():
            m = st["mode"]
            ov = st["override"]
            parts = [f"Mode: {'SURFACE' if m == 's' else 'BED'}"]
            if ov.get("surface_suppress"):
                parts.append("Srf: SUPPRESSED")
            elif "surface_twt_us" in ov:
                parts.append(f"Srf: {ov['surface_twt_us']:.2f} us")
            if ov.get("bed_suppress"):
                parts.append("Bed: SUPPRESSED")
            elif "bed_twt_us" in ov:
                parts.append(f"Bed: {ov['bed_twt_us']:.2f} us")
            if not any(k in ov for k in ("surface_twt_us", "bed_twt_us",
                                          "surface_suppress", "bed_suppress")):
                parts.append("No overrides")
            status_bar.set_text("  |  ".join(parts))
            col = "magenta" if m == "s" else "deepskyblue"
            status_bar.set_color(col)

        def _redraw_overrides():
            for art in st["drawn"]:
                try:
                    art.remove()
                except Exception:
                    pass
            st["drawn"].clear()

            ov = st["override"]

            # Surface suppress: show X at algo surface position
            if ov.get("surface_suppress"):
                if algo_surface_x is not None and 0 <= algo_surface_x < frame_w:
                    y_px = trace_y_s[algo_surface_x]
                    st["drawn"].append(
                        ax_img.plot(algo_surface_x, y_px, marker="X", color="magenta",
                                    markersize=12, zorder=6, alpha=0.8,
                                    markeredgecolor="white", markeredgewidth=1.0)[0])
                # Label in top-left corner of image panel
                st["drawn"].append(
                    ax_img.text(0.02, 0.96, "SRF SUPPRESSED", transform=ax_img.transAxes,
                                fontsize=9, color="magenta", fontweight="bold",
                                va="top", ha="left",
                                bbox=dict(boxstyle="round,pad=0.2", fc="white",
                                          ec="magenta", alpha=0.85)))
            elif "surface_twt_us" in ov:
                twt = ov["surface_twt_us"]
                x_px = mb_x + int(round(twt / us_per_px))
                if 0 <= x_px < frame_w:
                    # Use clicked y if available, else fall back to smoothed trace
                    y_px = ov.get("surface_y_px", trace_y_s[x_px])
                    pwr = -(y_px - cal["y_ref_px"]) * cal["db_per_px"]
                    # Diamond on image panel (at clicked position)
                    st["drawn"].append(
                        ax_img.plot(x_px, y_px, marker="D", color="magenta",
                                    markersize=7, zorder=6, alpha=0.6,
                                    markeredgecolor="white", markeredgewidth=0.5)[0])
                    st["drawn"].append(
                        ax_img.axvline(x_px, color="magenta", lw=0.8, alpha=0.4))
                    # Mirror on waveform panel
                    st["drawn"].append(
                        ax_wave.plot(twt, pwr, marker="D", color="magenta",
                                     markersize=7, zorder=6, alpha=0.6,
                                     markeredgecolor="white", markeredgewidth=0.5)[0])
                    st["drawn"].append(
                        ax_wave.axvline(twt, color="magenta", lw=0.8, alpha=0.4))

            # Bed suppress: show X at algo bed position
            if ov.get("bed_suppress"):
                if algo_bed_x is not None and 0 <= algo_bed_x < frame_w:
                    y_px = trace_y_s[algo_bed_x]
                    st["drawn"].append(
                        ax_img.plot(algo_bed_x, y_px, marker="X", color="cyan",
                                    markersize=12, zorder=6, alpha=0.8,
                                    markeredgecolor="white", markeredgewidth=1.0)[0])
                st["drawn"].append(
                    ax_img.text(0.02, 0.90, "BED SUPPRESSED", transform=ax_img.transAxes,
                                fontsize=9, color="cyan", fontweight="bold",
                                va="top", ha="left",
                                bbox=dict(boxstyle="round,pad=0.2", fc="white",
                                          ec="cyan", alpha=0.85)))
            elif "bed_twt_us" in ov:
                twt = ov["bed_twt_us"]
                x_px = mb_x + int(round(twt / us_per_px))
                if 0 <= x_px < frame_w:
                    # Use clicked y if available, else fall back to smoothed trace
                    y_px = ov.get("bed_y_px", trace_y_s[x_px])
                    pwr = -(y_px - cal["y_ref_px"]) * cal["db_per_px"]
                    # Diamond on image panel (at clicked position)
                    st["drawn"].append(
                        ax_img.plot(x_px, y_px, marker="D", color="cyan",
                                    markersize=7, zorder=6, alpha=0.6,
                                    markeredgecolor="white", markeredgewidth=0.5)[0])
                    st["drawn"].append(
                        ax_img.axvline(x_px, color="cyan", lw=0.8, alpha=0.4))
                    # Mirror on waveform panel
                    st["drawn"].append(
                        ax_wave.plot(twt, pwr, marker="D", color="cyan",
                                     markersize=7, zorder=6, alpha=0.6,
                                     markeredgecolor="white", markeredgewidth=0.5)[0])
                    st["drawn"].append(
                        ax_wave.axvline(twt, color="cyan", lw=0.8, alpha=0.4))

            _update_status()
            fig.canvas.draw_idle()

        def on_click(event):
            # Click on image panel -> convert pixel x to TWT, capture y for display
            if event.inaxes != ax_img or event.button != 1:
                return
            x_px = event.xdata
            y_px = event.ydata
            if x_px is None or x_px < mb_x:
                return
            x_px = int(round(x_px))
            if x_px >= frame_w:
                return
            twt = (x_px - mb_x) * us_per_px
            if st["mode"] == "s":
                st["override"].pop("surface_suppress", None)
                st["override"]["surface_twt_us"] = round(twt, 3)
                st["override"]["surface_y_px"] = round(float(y_px), 1)
            elif st["mode"] == "b":
                st["override"].pop("bed_suppress", None)
                st["override"]["bed_twt_us"] = round(twt, 3)
                st["override"]["bed_y_px"] = round(float(y_px), 1)
            _redraw_overrides()

        def on_key(event):
            k = event.key
            if k == "s":
                st["mode"] = "s"
                title_obj.set_text(
                    f"REVIEW  F{FLT} {fkey}  [{current_status}]  "
                    f"({frame_i + 1}/{len(review_frames)})  mode=[SURFACE]")
                _update_status()
                fig.canvas.draw_idle()
            elif k == "b":
                st["mode"] = "b"
                title_obj.set_text(
                    f"REVIEW  F{FLT} {fkey}  [{current_status}]  "
                    f"({frame_i + 1}/{len(review_frames)})  mode=[BED]")
                _update_status()
                fig.canvas.draw_idle()
            elif k == "S":   # Shift+S: suppress surface (mark as not present)
                # Remove any surface position override, set suppress flag
                st["override"].pop("surface_twt_us", None)
                st["override"].pop("surface_y_px", None)
                st["override"]["surface_suppress"] = True
                _redraw_overrides()
            elif k == "B":   # Shift+B: suppress bed (mark as not present)
                st["override"].pop("bed_twt_us", None)
                st["override"].pop("bed_y_px", None)
                st["override"]["bed_suppress"] = True
                _redraw_overrides()
            elif k == "d":
                st["override"].clear()
                _redraw_overrides()
            elif k in ("n", "right"):
                st["action"] = "next"
                plt.close(fig)
            elif k in ("p", "left"):
                st["action"] = "prev"
                plt.close(fig)
            elif k in ("q", "escape"):
                st["action"] = "quit"
                plt.close(fig)

        # Unbind matplotlib defaults that clash with review keys
        for action in ("keymap.save", "keymap.quit", "keymap.back",
                        "keymap.forward", "keymap.fullscreen"):
            try:
                plt.rcParams[action] = []
            except KeyError:
                pass
        fig.canvas.mpl_connect("button_press_event", on_click)
        fig.canvas.mpl_connect("key_press_event", on_key)

        _redraw_overrides()
        plt.show()

        # Save override for this frame
        if st["override"]:
            echo_overrides[fkey] = st["override"]
        elif fkey in echo_overrides:
            del echo_overrides[fkey]

        # Navigate
        if st["action"] == "next" or st["action"] is None:
            frame_i += 1
        elif st["action"] == "prev":
            frame_i = max(0, frame_i - 1)
        elif st["action"] == "quit":
            break

    # Persist overrides
    save_echo_overrides(echo_overrides)
    n_ov = len(echo_overrides)
    print(f"\nReview complete. {n_ov} override{'s' if n_ov != 1 else ''} saved.")


# ==============================================================================
# Branch: review mode vs normal extraction
# ==============================================================================

if _args.review:
    review_mode()
    print("\n" + "=" * 70)
    print("Re-running normal mode to apply overrides...")
    print("=" * 70 + "\n")
    # Reload overrides that review_mode just saved to disk
    echo_overrides = load_echo_overrides()
    # Fall through to normal extraction below


# -- Per-frame echo extraction --------------------------------------------------
print(f"  {'Fr':>3}  {'CBD':>6}  {'Status':^12}  {'NF':>6}  "
      f"{'Srf TWT':>8}  {'Srf dB':>7}  "
      f"{'Bed TWT':>8}  {'Bed dB':>7}  {'Bed SNR':>7}  "
      f"{'h_air':>7}  {'h_ice':>7}")
print("  " + "-" * 90)

echo_rows = []

for _, idx_row in tiff_rows.iterrows():
    frame_idx  = int(idx_row["frame_idx"])
    frame_type = idx_row["frame_type"]

    if frame_type == "partial":
        continue
    if frame_idx not in frame_cal:
        # Frame was excluded in step2 (or step2 hasn't been run for this frame)
        continue

    fc      = frame_cal[frame_idx]
    cbd     = fc["cbd"]
    file_id = fc["file_id"]
    mb_x    = fc["mb_x"]

    left_px  = int(idx_row["left_px"])
    right_px = int(idx_row["right_px"])
    frame    = img_norm[:, left_px : right_px + 1]
    frame_w  = frame.shape[1]

    cal = _make_cal(fc)

    # -- Extract trace and noise floor ------------------------------------------
    # Use robust mode: constrained-argmin rejects film-grain artefacts and
    # T/R ringing noise that would otherwise create fake peaks in the flat
    # region between the main bang and the first real echo.
    trace_y, trace_y_s, trace_info = extract_trace(frame, cal, robust=True, mb_x=mb_x)
    noise_floor_dB     = estimate_noise_floor(trace_y_s, mb_x, cal)

    # -- Detect surface and bed echoes ------------------------------------------
    surface_x, bed_x = detect_echoes(trace_y_s, mb_x, noise_floor_dB, cal)

    # -- Save algorithmic positions before overrides ----------------------------
    algo_surface_x = surface_x
    algo_bed_x     = bed_x

    # -- Apply manual overrides (from echo_overrides.json) --------------------
    is_surface_override = is_bed_override = False
    is_surface_suppress = is_bed_suppress = False
    override = echo_overrides.get(file_id, {})
    us_per_px = cal["us_per_px"]
    if override.get("surface_suppress"):
        surface_x = None
        is_surface_suppress = True
        is_surface_override = True
    elif "surface_twt_us" in override:
        surface_x = mb_x + int(round(override["surface_twt_us"] / us_per_px))
        surface_x = max(0, min(surface_x, frame_w - 1))
        is_surface_override = True
    if override.get("bed_suppress"):
        bed_x = None
        is_bed_suppress = True
        is_bed_override = True
    elif "bed_twt_us" in override:
        bed_x = mb_x + int(round(override["bed_twt_us"] / us_per_px))
        bed_x = max(0, min(bed_x, frame_w - 1))
        is_bed_override = True

    # -- Compute echo metrics ---------------------------------------------------
    # Use local column profile extraction: immune to global trace failures
    # (graticule lines, reference lines competing with CRT signal).
    # Falls back to compute_echo_metrics only if local profile fails.
    surface = extract_local_profile(
        frame, surface_x, mb_x, noise_floor_dB, cal,
        guide_y=float(trace_y_s[surface_x]) if surface_x < len(trace_y_s) else None,
        max_half_width_us=2.0,   # surface echo physically < 2 µs half-width
    ) if surface_x is not None else None

    bed = extract_local_profile(
        frame, bed_x, mb_x, noise_floor_dB, cal,
        guide_y=float(trace_y_s[bed_x]) if bed_x < len(trace_y_s) else None,
        max_half_width_us=4.0,   # bed echo physically < 4 µs half-width
    ) if bed_x is not None else None

    # -- Classify echo_status ---------------------------------------------------
    # Use gain-corrected bed SNR for the weak_bed threshold.  The attenuator
    # sits before the receiver, so the noise floor is constant but the signal
    # level shifts with attenuator/CRT gain changes.  Raw SNR is therefore
    # inflated (or deflated) by the gain offset; corrected SNR reflects the
    # true signal-to-noise ratio.
    _mb_corr = fc["mb_correction_dB"]
    if surface is None:
        echo_status = "no_surface"
    elif bed is None:
        echo_status = "no_bed"
    elif (bed.peak_snr_dB + _mb_corr) < WEAK_BED_SNR_DB:
        echo_status = "weak_bed"
    else:
        echo_status = "good"

    # -- Original algorithmic echo_status (before overrides) -----------------
    # Preserved for post-hoc threshold tuning: what did the algorithm find
    # before the user corrected it?  Only differs from echo_status when an
    # override was applied.
    if not (is_surface_override or is_bed_override):
        algo_echo_status = echo_status
    elif algo_surface_x is None:
        algo_echo_status = "no_surface"
    elif algo_bed_x is None:
        algo_echo_status = "no_bed"
    else:
        _algo_bed = extract_local_profile(
            frame, algo_bed_x, mb_x, noise_floor_dB, cal,
            guide_y=float(trace_y_s[algo_bed_x]) if algo_bed_x < len(trace_y_s) else None)
        algo_echo_status = ("weak_bed"
                            if (_algo_bed.peak_snr_dB + _mb_corr) < WEAK_BED_SNR_DB
                            else "good")

    # -- Bed envelope artifact flag -------------------------------------------
    # Check whether film artifacts exist in the post-bed region (between
    # the bed peak and the NF+5 trailing edge + 1 µs margin).  Artifacts
    # here bias the trailing edge, inflating width_5, asymmetry, and
    # trailing_tail.  Detection: compare constrained trace vs median-
    # filtered trace (art_diff_px from extract_trace).  Columns where the
    # median filter removed a >10 dB dip in this region are flagged.
    #
    # Artifacts elsewhere (pre-MB, surface-bed gap, pre-surface) are
    # benign for bed envelope estimation and are not flagged.
    bed_envelope_suspect = False
    art_max_dB = 0.0
    art_diff_px = trace_info.get("art_diff_px")
    if bed is not None and art_diff_px is not None:
        bed_trail_5 = getattr(bed, "trail_5_us", np.nan)
        if not np.isnan(bed_trail_5):
            # Check region: bed_peak to trail_5 + 1 µs
            us_per_px = cal["us_per_px"]
            db_per_px = cal["db_per_px"]
            post_bed_start = bed.peak_x
            post_bed_end   = min(len(art_diff_px),
                                 mb_x + int((bed_trail_5 + 1.0) / us_per_px))
            if post_bed_start < post_bed_end:
                region = art_diff_px[post_bed_start:post_bed_end]
                # >10 dB discrepancy = significant artifact
                art_thresh_px = 10.0 / db_per_px
                art_mask = region > art_thresh_px
                if np.any(art_mask):
                    art_max_dB = float(np.max(region[art_mask]) * db_per_px)
                    bed_envelope_suspect = True

    # -- Derived geometry -------------------------------------------------------
    h_air_m = h_ice_m = h_eff_m = np.nan
    h_ice_onset_m = np.nan
    if surface is not None:
        h_air_m = surface.peak_twt_us / 2.0 * C_AIR_M_PER_US
    if surface is not None and bed is not None:
        h_ice_m = (bed.peak_twt_us - surface.peak_twt_us) / 2.0 * C_ICE_M_PER_US
        h_eff_m = h_air_m + h_ice_m / N_ICE
        # Onset-based ice thickness: uses first-break TWT for both surface and
        # bed when available, falling back to peak TWT when onset is NaN.
        srf_onset = surface.onset_twt_us if not np.isnan(surface.onset_twt_us) else surface.peak_twt_us
        bed_onset = bed.onset_twt_us if not np.isnan(bed.onset_twt_us) else bed.peak_twt_us
        h_ice_onset_m = (bed_onset - srf_onset) / 2.0 * C_ICE_M_PER_US

    # -- Print summary line -----------------------------------------------------
    srf_twt = f"{surface.peak_twt_us:8.3f}" if surface else f"{'—':>8}"
    srf_db  = f"{surface.peak_power_dB:+7.1f}" if surface else f"{'—':>7}"
    bed_twt = f"{bed.peak_twt_us:8.3f}" if bed else f"{'—':>8}"
    bed_db  = f"{bed.peak_power_dB:+7.1f}" if bed else f"{'—':>7}"
    bed_snr = f"{bed.peak_snr_dB:+7.1f}" if bed else f"{'—':>7}"
    h_air_s = f"{h_air_m:7.0f}" if not np.isnan(h_air_m) else f"{'—':>7}"
    h_ice_s = f"{h_ice_m:7.0f}" if not np.isnan(h_ice_m) else f"{'—':>7}"

    ov_tag = ""
    if is_surface_override or is_bed_override:
        ov_tag = "  [M]"
    print(f"  {frame_idx:>3}  {str(cbd):>6}  {echo_status:^12}  "
          f"{noise_floor_dB:+6.1f}  "
          f"{srf_twt}  {srf_db}  "
          f"{bed_twt}  {bed_db}  {bed_snr}  "
          f"{h_air_s}  {h_ice_s}{ov_tag}")

    # -- Build output row -------------------------------------------------------
    def _e(echo, attr):
        return getattr(echo, attr, np.nan) if echo is not None else np.nan

    # Per-frame MB power correction: normalise echo powers to the flight-wide
    # reference MB level.  Removes system gain variation (attenuator changes,
    # CRT intensity drift) while preserving real geophysical power differences.
    # The MB is a fixed internal signal (T/R switch leakage) — any change in
    # its measured power is purely instrumental.
    _mb_corr = fc["mb_correction_dB"]  # positive = frame was weaker -> boost

    def _corrected(raw_dB):
        """Apply MB power correction to a raw dB measurement."""
        if np.isnan(raw_dB):
            return np.nan
        return round(raw_dB + _mb_corr, 2)

    echo_rows.append(dict(
        flight      = FLT,
        tiff        = TIFF.name,
        tiff_id     = TIFF_ID,
        frame_idx   = frame_idx,
        cbd         = cbd,
        file_id     = file_id,
        mb_x        = mb_x,
        echo_status = echo_status,
        noise_floor_dB = round(noise_floor_dB, 2),
        # MB power correction
        mb_power_dB       = round(fc["mb_power_dB"], 2),
        mb_correction_dB  = round(_mb_corr, 2),
        # Surface echo (power and SNR corrected for system gain)
        surface_twt_us        = round(_e(surface, "peak_twt_us"),     4),
        surface_power_dB      = _corrected(_e(surface, "peak_power_dB")),
        surface_snr_dB        = _corrected(_e(surface, "peak_snr_dB")),
        surface_width_10_us   = round(_e(surface, "width_10_us"),     4),
        surface_width_5_us    = round(_e(surface, "width_5_us"),      4),
        surface_peakiness     = round(_e(surface, "peakiness"),       3),
        surface_asymmetry     = round(_e(surface, "asymmetry"),       3),
        surface_leading_rise_us  = round(_e(surface, "leading_rise_us"),  4),
        surface_trailing_tail_us = round(_e(surface, "trailing_tail_us"), 4),
        surface_onset_twt_us     = round(_e(surface, "onset_twt_us"),    4),
        # Bed echo (power and SNR corrected for system gain)
        bed_twt_us            = round(_e(bed, "peak_twt_us"),    4),
        bed_power_dB          = _corrected(_e(bed, "peak_power_dB")),
        bed_snr_dB            = _corrected(_e(bed, "peak_snr_dB")),
        bed_width_10_us       = round(_e(bed, "width_10_us"),    4),
        bed_width_5_us        = round(_e(bed, "width_5_us"),     4),
        bed_peakiness         = round(_e(bed, "peakiness"),      3),
        bed_asymmetry         = round(_e(bed, "asymmetry"),      3),
        bed_leading_rise_us   = round(_e(bed, "leading_rise_us"),  4),
        bed_trailing_tail_us  = round(_e(bed, "trailing_tail_us"), 4),
        bed_onset_twt_us      = round(_e(bed, "onset_twt_us"),    4),
        # Peak-relative shape metrics (SNR-independent)
        bed_decay_10_us       = round(_e(bed, "decay_10_us"),     4),
        bed_decay_20_us       = round(_e(bed, "decay_20_us"),     4),
        bed_rise_10_us        = round(_e(bed, "rise_10_us"),      4),
        bed_pk_asymmetry      = round(_e(bed, "pk_asymmetry"),    3),
        # Derived: peak-onset delay (Fresnel-zone roughness diagnostic)
        bed_peak_onset_us     = round(
            _e(bed, "peak_twt_us") - _e(bed, "onset_twt_us"), 4),
        bed_envelope_suspect  = bed_envelope_suspect,
        artifact_max_dB       = round(art_max_dB, 1),
        # Geometry (unaffected by gain correction)
        h_air_m = round(h_air_m, 1) if not np.isnan(h_air_m) else np.nan,
        h_ice_m = round(h_ice_m, 1) if not np.isnan(h_ice_m) else np.nan,
        h_ice_onset_m = round(h_ice_onset_m, 1) if not np.isnan(h_ice_onset_m) else np.nan,
        h_eff_m = round(h_eff_m, 1) if not np.isnan(h_eff_m) else np.nan,
        # Override flags
        surface_override = is_surface_override,
        bed_override     = is_bed_override,
        algo_echo_status = algo_echo_status,
        reflector_type   = "bed",
    ))

    # -- Generate single-panel diagnostic figure ---------------------------------
    # Full-width A-scope image with dual axes (px + physical units),
    # echo markers, and semi-transparent envelope polygons.
    fig, ax = plt.subplots(figsize=(14, 5))
    fig.patch.set_facecolor("white")

    fw = frame.shape[1]
    y_ref_px = cal["y_ref_px"]
    y_lo_disp = DEFAULT_CAL["y_disp_lo"] - 50
    y_hi_disp = DEFAULT_CAL["y_disp_hi"] + 50

    ax.imshow(frame, cmap="gray", vmin=0, vmax=1, aspect="auto",
              extent=[0, fw, frame.shape[0], 0])

    # Noise floor reference row (cyan dashed)
    ax.axhline(y_ref_px, color="cyan", lw=1.0, ls="--", alpha=0.6)

    # Main bang (red dashed vertical)
    ax.axvline(mb_x, color="red", lw=1.2, ls="--", alpha=0.8)

    # -- Envelope polygons (semi-transparent, on CRT image) --------------------
    def _draw_envelope(ax_obj, echo, echo_x, color):
        """Draw semi-transparent envelope polygon for an echo."""
        if echo is None:
            return
        # +10 dB envelope
        if not np.isnan(echo.lead_10_us) and not np.isnan(echo.trail_10_us):
            l10_px = us_to_px(echo.lead_10_us, mb_x, cal)
            t10_px = us_to_px(echo.trail_10_us, mb_x, cal)
            thresh_10_y = db_to_px(noise_floor_dB + 10.0, cal)
            # Polygon: from threshold row at leading edge, up to peak, back to
            # threshold at trailing edge
            xs = [l10_px, echo_x, t10_px, t10_px, l10_px]
            ys = [thresh_10_y, echo.peak_y, thresh_10_y, thresh_10_y, thresh_10_y]
            ax_obj.fill(xs[:3], ys[:3], color=color, alpha=0.15, zorder=3)
        # +5 dB envelope (wider, fainter)
        if not np.isnan(echo.lead_5_us) and not np.isnan(echo.trail_5_us):
            l5_px = us_to_px(echo.lead_5_us, mb_x, cal)
            t5_px = us_to_px(echo.trail_5_us, mb_x, cal)
            thresh_5_y = db_to_px(noise_floor_dB + 5.0, cal)
            xs5 = [l5_px, echo_x, t5_px]
            ys5 = [thresh_5_y, echo.peak_y, thresh_5_y]
            ax_obj.fill(xs5, ys5, color=color, alpha=0.08, zorder=2)

    _draw_envelope(ax, surface, surface_x if surface_x is not None else 0,
                   "limegreen")
    _draw_envelope(ax, bed, bed_x if bed_x is not None else 0,
                   "darkorange")

    # -- Echo markers ----------------------------------------------------------
    # Surface
    if is_surface_suppress:
        if algo_surface_x is not None:
            ax.plot(algo_surface_x, y_ref_px, marker="X",
                    color="lime", markersize=12, zorder=5, alpha=0.6,
                    markeredgecolor="white", markeredgewidth=1.0)
    elif surface is not None:
        srf_marker = "D" if is_surface_override else "^"
        srf_label  = (f"Srf {surface.peak_twt_us:.2f}us  "
                      f"{surface.peak_power_dB:+.1f}dB"
                      + (" [M]" if is_surface_override else ""))
        ax.plot(surface_x, surface.peak_y, marker=srf_marker, color="lime",
                markersize=10, zorder=6, label=srf_label,
                markeredgecolor="white", markeredgewidth=0.8)
        ax.axvline(surface_x, color="lime", lw=0.6, ls=":", alpha=0.5)

    # Bed
    if is_bed_suppress:
        if algo_bed_x is not None:
            ax.plot(algo_bed_x, y_ref_px, marker="X",
                    color="orange", markersize=12, zorder=5, alpha=0.6,
                    markeredgecolor="white", markeredgewidth=1.0)
    elif bed is not None:
        bed_marker = "D" if is_bed_override else "^"
        bed_label  = (f"Bed {bed.peak_twt_us:.2f}us  "
                      f"{bed.peak_power_dB:+.1f}dB  "
                      f"SNR={bed.peak_snr_dB:+.1f}dB"
                      + (" [M]" if is_bed_override else ""))
        ax.plot(bed_x, bed.peak_y, marker=bed_marker, color="orange",
                markersize=10, zorder=6, label=bed_label,
                markeredgecolor="white", markeredgewidth=0.8)
        ax.axvline(bed_x, color="orange", lw=0.6, ls=":", alpha=0.5)

    # -- Primary axes: pixel coordinates ---------------------------------------
    ax.set_ylim(y_hi_disp, y_lo_disp)
    ax.set_xlim(0, fw)
    ax.set_xlabel("Column (px, frame-relative)", fontsize=8)
    ax.set_ylabel("Row (px)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # -- Secondary X-axis: TWT from MB (us) ------------------------------------
    ax2_x = ax.twiny()
    ax2_x.set_xlim((0 - mb_x) * cal["us_per_px"],
                    (fw - mb_x) * cal["us_per_px"])
    ax2_x.set_xlabel("Two-way travel time from MB (us)", fontsize=8)
    ax2_x.tick_params(labelsize=7)
    ax2_x.spines["top"].set_linewidth(0.4)

    # -- Secondary Y-axis: Power (dB) -----------------------------------------
    ax2_y = ax.twinx()
    db_top    = px_to_db(y_lo_disp, cal)
    db_bottom = px_to_db(y_hi_disp, cal)
    ax2_y.set_ylim(db_bottom, db_top)
    ax2_y.set_ylabel("Power (dB)", fontsize=8)
    ax2_y.tick_params(labelsize=7)
    ax2_y.spines["right"].set_linewidth(0.4)

    # -- Legend and title -------------------------------------------------------
    if ax.get_legend_handles_labels()[1]:
        ax.legend(fontsize=7, loc="upper right", framealpha=0.7,
                  facecolor="black", labelcolor="white")

    # Geometry annotation (bottom-left)
    geo_parts = []
    if not np.isnan(h_air_m):
        geo_parts.append(f"h_air={h_air_m:.0f} m")
    if not np.isnan(h_ice_m):
        geo_parts.append(f"h_ice={h_ice_m:.0f} m")
    if geo_parts:
        ax.text(0.01, 0.04, "  |  ".join(geo_parts),
                transform=ax.transAxes, fontsize=7,
                va="bottom", ha="left", color="white",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="black",
                          edgecolor="none", alpha=0.6))

    ax.set_title(
        f"LYRA Phase 4 -- F{FLT} {file_id}  |  NF={noise_floor_dB:.1f} dB  "
        f"[{echo_status}]",
        fontsize=9, loc="left")

    fig_path = PHASE4_DIR / f"F{FLT}_{file_id}_echoes.png"
    fig_svg_path = PHASE4_DIR / f"F{FLT}_{file_id}_echoes.svg"
    fig.savefig(fig_path, dpi=150, bbox_inches="tight", facecolor="white")
    fig.savefig(fig_svg_path, format="svg", dpi=150,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # -- Clean calibrated waveform figure (Panel-C style) -----------------------
    # Uses the SAME calibrated trace and the SAME final surface/bed picks as the
    # diagnostic above. This is visualization only; no repicking/recalculation.
    twt_arr = px_to_us(np.arange(frame_w, dtype=float), mb_x, cal)

    # DISPLAY-ONLY full A-scope trace.
    # The robust science trace intentionally clamps the T/R ringing zone around
    # the main bang to the noise-floor reference.  That is desirable for echo
    # detection, but it removes the actual transmitter pulse from a waveform
    # visualization.  Re-extract a non-robust trace solely for this figure so
    # the red curve follows the visible CRT trace across the complete frame.
    # The science trace_y_s above remains unchanged for all picks, metrics, CSVs,
    # and thickness calculations.
    _display_trace_y, _display_trace_y_s, _display_trace_info = extract_trace(
        frame, cal, robust=False, mb_x=mb_x
    )
    power_arr = px_to_db(_display_trace_y_s, cal)

    wf_fig, wf_ax = plt.subplots(figsize=(10, 6))
    wf_fig.patch.set_facecolor("white")

    # Show the COMPLETE calibrated A-scope trace.
    # Keep all available samples before and after the detected main bang so the
    # transmitter/main-bang waveform itself is visible rather than being clipped
    # at 0 us.  Time is still referenced to mb_x, so mb_x == 0 us.
    wf_mask = np.isfinite(twt_arr) & np.isfinite(power_arr)
    if np.any(wf_mask):
        wf_ax.plot(twt_arr[wf_mask], power_arr[wf_mask], color="red", lw=1.4)

    # -60 dB calibration reference.
    wf_ax.axhline(-60.0, color="green", lw=1.0, ls=":", alpha=0.8,
                  label="Reference (-60 dB)")

    # Transmitter / main-bang time zero.
    tx_power = (float(px_to_db(_display_trace_y_s[mb_x], cal))
                if 0 <= mb_x < len(_display_trace_y_s) else np.nan)
    if np.isfinite(tx_power):
        wf_ax.plot(0.0, tx_power, "o", color="royalblue", ms=7, zorder=5, label="Tx")
        wf_ax.annotate(
            f"transmitter pulse\n(~{tx_power:.1f} dB at 0.0 us)",
            xy=(0.0, tx_power), xytext=(-0.5, tx_power - 7.0),
            textcoords="data", ha="right", va="top", fontsize=9,
            bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="0.35", alpha=0.9),
            arrowprops=dict(arrowstyle="-", color="royalblue", lw=1.0),
        )

    # Final surface pick used by Phase 4.
    if surface is not None:
        s_t = float(surface.peak_twt_us)
        s_p = float(surface.peak_power_dB)
        wf_ax.plot(s_t, s_p, "o", color="seagreen", ms=7, zorder=6, label="Surface")
        wf_ax.annotate(
            f"surface\n(~{s_p:.1f} dB at {s_t:.1f} us)",
            xy=(s_t, s_p), xytext=(s_t - 3.0, s_p - 5.0),
            ha="right", va="top", fontsize=9,
            bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="0.35", alpha=0.9),
            arrowprops=dict(arrowstyle="-", color="seagreen", lw=1.0),
        )

    # Final bed pick used by Phase 4.
    if bed is not None:
        b_t = float(bed.peak_twt_us)
        b_p = float(bed.peak_power_dB)
        wf_ax.plot(b_t, b_p, "o", color="mediumorchid", ms=7, zorder=6, label="Bed")
        wf_ax.annotate(
            f"bed\n(~{b_p:.1f} dB at {b_t:.1f} us)",
            xy=(b_t, b_p), xytext=(b_t + 3.0, b_p - 5.0),
            ha="left", va="top", fontsize=9,
            bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="0.35", alpha=0.9),
            arrowprops=dict(arrowstyle="-", color="mediumorchid", lw=1.0),
        )

    wf_ax.set_xlabel("Two-way travel time from MB (us)")
    wf_ax.set_ylabel("Power (dB)")
    wf_ax.set_title(f"LYRA Calibrated A-scope: F{FLT} {file_id}")
    wf_ax.grid(True, which="major", linestyle="-", linewidth=0.6, alpha=0.35)
    wf_ax.minorticks_on()
    wf_ax.grid(True, which="minor", linestyle=":", linewidth=0.45, alpha=0.25)
    wf_ax.legend(loc="upper right", framealpha=0.9)

    # DISPLAY CROP ONLY.  The full frame is still extracted above, but the
    # publication-style waveform omits the ugly frame-edge regions.  Keep a
    # short pre-MB interval so the transmitter pulse is visible, then continue
    # several microseconds beyond the bed to retain the useful post-bed tail.
    if np.any(wf_mask):
        _available_lo = float(np.nanmin(twt_arr[wf_mask]))
        _available_hi = float(np.nanmax(twt_arr[wf_mask]))
        _plot_lo = max(_available_lo, -2.5)
        if bed is not None and np.isfinite(float(bed.peak_twt_us)):
            _plot_hi = min(_available_hi, float(bed.peak_twt_us) + 6.0)
        elif surface is not None and np.isfinite(float(surface.peak_twt_us)):
            _plot_hi = min(_available_hi, float(surface.peak_twt_us) + 12.0)
        else:
            _plot_hi = min(_available_hi, 20.0)
        wf_ax.set_xlim(_plot_lo, _plot_hi)
    finite_power = power_arr[wf_mask]
    if finite_power.size:
        wf_ax.set_ylim(min(-65.0, float(np.nanmin(finite_power)) - 2.0),
                       max(0.0, float(np.nanmax(finite_power)) + 3.0))

    waveform_path = PHASE4_DIR / f"F{FLT}_{file_id}_waveform.png"
    waveform_svg_path = PHASE4_DIR / f"F{FLT}_{file_id}_waveform.svg"
    wf_fig.savefig(waveform_path, dpi=150, bbox_inches="tight", facecolor="white")
    wf_fig.savefig(waveform_svg_path, format="svg", dpi=150,
                   bbox_inches="tight", facecolor="white")

    # -- Space-optimized three-panel publication figure -------------------------
    # (a) film-wide frame overview; (b) cropped CRT echo image;
    # (c) calibrated waveform. The original TIFF pixels are NOT distorted.
    # Only the visible film window changes, to use the printable area well.
    # Page dimensions fixed to 165 x 100 mm in PNG / EPS / SVG.
    # All plotted traces, labels and markers are editable vectors in SVG.
    from matplotlib.ticker import MaxNLocator
    from matplotlib.lines import Line2D
    from matplotlib.patches import Rectangle

    MM_TO_IN = 1.0 / 25.4
    with plt.rc_context({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans"],
        "font.size": 8.5,
        "axes.titlesize": 9.0,
        "axes.labelsize": 8.2,
        "xtick.labelsize": 7.5,
        "ytick.labelsize": 7.5,
        "legend.fontsize": 7.3,
        "text.usetex": False,
        "ps.useafm": False,
        "ps.fonttype": 3,
        "pdf.fonttype": 42,
        "svg.fonttype": "none",  # Editable text, unlike converted text outlines
        "svg.image_inline": True,
    }):
        pub = plt.figure(figsize=(165 * MM_TO_IN, 100 * MM_TO_IN),
                         facecolor="white")

        # ---- Full-width frame strip: (a) --------------------------------------
        # A compact heading and labels leave the maximum area for both plots.
        pub.text(0.026, 0.990, "(a) Frame detection",
                 ha="left", va="top", fontsize=9.5, fontweight="bold")
        pub.text(0.975, 0.990,
                 f"LYRA  |  F{FLT}  |  CBD {str(cbd).zfill(4)}  |  {echo_status.replace('_', ' ')}",
                 ha="right", va="top", fontsize=8.1, color="#303030")

        strip_n = len(pub_frame_thumbnails)
        if strip_n:
            strip_left, strip_width = 0.015, 0.970
            tile_w = strip_width / strip_n
            strip_bottom, strip_height = 0.768, 0.113
            for i, (fi, cb, is_partial, thumb) in enumerate(pub_frame_thumbnails):
                x0 = strip_left + i * tile_w
                cx = x0 + tile_w / 2.0
                selected = (fi == frame_idx)
                cb_text = "partial" if is_partial else f"CBD {cb.zfill(4)}"
                pub.text(cx, 0.941, f"Frame {fi}\n{cb_text}",
                         ha="center", va="top", fontsize=5.6,
                         linespacing=0.91,
                         fontweight="bold" if selected else "normal",
                         color="#166534" if selected else "#171717")
                # Fill each tile while preserving ORIGINAL thumbnail proportions.
                # Matplotlib's equal aspect can letterbox tall/partial frames.
                strip_ax = pub.add_axes([x0 + 0.0008, strip_bottom,
                                         max(0.001, tile_w - 0.0016), strip_height])
                strip_ax.imshow(thumb, cmap="gray", vmin=0, vmax=255,
                                aspect="equal", interpolation="nearest",
                                rasterized=True)
                strip_ax.set_axis_off()
                if selected:
                    pub.add_artist(Rectangle(
                        (x0 + 0.0008, strip_bottom),
                        max(0.001, tile_w - 0.0016), strip_height,
                        transform=pub.transFigure,
                        fc="none", ec="#15803d", lw=1.25, zorder=10))

        pub.add_artist(Line2D([0.023, 0.977], [0.754, 0.754],
                              transform=pub.transFigure,
                              color="#dedede", lw=0.65))

        # ---- Lower image and waveform panels: (b) and (c) ---------------------
        # Panels share physical height but do not waste page width. The film
        # view is limited to the meaningful CRT interval around the main bang
        # and echoes, instead of showing large featureless frame margins.
        left_x, right_x = 0.080, 0.605
        left_w, right_w = 0.402, 0.365
        top_y, max_panel_h = 0.647, 0.430

        # The film panel must maintain the actual pixel aspect ratio. Compute
        # a minimum X span that can fit the available H without stretching.
        # Wider viewing windows are retained when needed for both echoes.
        film_y_span = max(1., float(y_hi_disp - y_lo_disp))
        min_window_px = int(np.ceil(
            left_w * (165.0 / 100.0) * film_y_span / max_panel_h))
        echo_end = bed_x if bed_x is not None else (
            surface_x if surface_x is not None else min(fw - 1, mb_x + 950))
        desired_lo = max(0, int(mb_x - 420))
        desired_hi = min(fw, int(echo_end + 700))
        if desired_hi - desired_lo < min_window_px:
            missing = min_window_px - (desired_hi - desired_lo)
            desired_lo = max(0, desired_lo - missing // 2)
            desired_hi = min(fw, desired_hi + missing - missing // 2)
            # If the image edge prevents symmetric expansion, use the other side.
            if desired_hi - desired_lo < min_window_px:
                desired_lo = max(0, desired_hi - min_window_px)
                desired_hi = min(fw, max(desired_hi, desired_lo + min_window_px))
        film_x0 = int(desired_lo)
        film_x1 = int(max(film_x0 + 1, desired_hi))
        visible_width = max(1, film_x1 - film_x0)
        panel_h = min(max_panel_h,
                      left_w * (165.0 / 100.0) * film_y_span / visible_width)
        # Align both plots at the top and bottom. The lower labels and footer
        # stay outside the data area rather than sitting on top of the waveform.
        panel_bottom = top_y - panel_h
        ax_film = pub.add_axes([left_x, panel_bottom, left_w, panel_h])
        ax_curve = pub.add_axes([right_x, panel_bottom, right_w, panel_h])

        pub.text(left_x, 0.737, "(b) Detected echoes",
                 ha="left", va="center", fontsize=9.4, fontweight="bold")
        pub.text(right_x, 0.737, "(c) Calibrated waveform",
                 ha="left", va="center", fontsize=9.4, fontweight="bold")

        # Original radargram is raster by nature; axes, markers and guides
        # remain vector in Illustrator. Crop only DISPLAY pixels on the X axis.
        ax_film.imshow(frame[:, film_x0:film_x1], cmap="gray",
                       vmin=0, vmax=1, aspect="equal", interpolation="nearest",
                       extent=[film_x0, film_x1, frame.shape[0], 0],
                       rasterized=True)
        ax_film.set_xlim(film_x0, film_x1)
        ax_film.set_ylim(y_hi_disp, y_lo_disp)
        ax_film.axvline(mb_x, color="#d62728", ls="--", lw=1.0)
        ax_film.axhline(y_ref_px, color="#00bcd4", ls="--", lw=0.9)

        for _echo, _xx, _edge, _pale in (
            (surface, surface_x, "#198754", "#b9e9cc"),
            (bed, bed_x, "#d97706", "#ffe0a3"),
        ):
            if _echo is None or _xx is None:
                continue
            if np.isfinite(_echo.lead_10_us) and np.isfinite(_echo.trail_10_us):
                _x1 = us_to_px(float(_echo.lead_10_us), mb_x, cal)
                _x2 = us_to_px(float(_echo.trail_10_us), mb_x, cal)
                _yt = db_to_px(noise_floor_dB + 10.0, cal)
                ax_film.fill([_x1, _xx, _x2], [_yt, _echo.peak_y, _yt],
                             fc=_pale, ec=_edge, lw=0.7, zorder=4)
            ax_film.plot([_xx], [_echo.peak_y], marker="^", color=_edge,
                         ms=5.0, mec="white", mew=0.7, ls="None", zorder=6)

        ax_film.set_xlabel("Image column (px)", fontsize=8.0, labelpad=1)
        ax_film.set_ylabel("Image row (px)", fontsize=8.0, labelpad=1)
        ax_film.xaxis.set_major_locator(MaxNLocator(4, integer=True))
        ax_film.yaxis.set_major_locator(MaxNLocator(5, integer=True))
        ax_film.tick_params(axis="both", labelsize=7.3, length=2.5, pad=1.5)

        ax_film_top = ax_film.twiny()
        ax_film_top.set_xlim((film_x0 - mb_x) * cal["us_per_px"],
                              (film_x1 - mb_x) * cal["us_per_px"])
        ax_film_top.set_xlabel("TWTT from MB (µs)", fontsize=8.0, labelpad=1)
        ax_film_top.xaxis.set_major_locator(MaxNLocator(5))
        ax_film_top.tick_params(axis="x", labelsize=7.3, length=2.5, pad=1.5)

        ax_film_power = ax_film.twinx()
        ax_film_power.set_ylim(px_to_db(y_hi_disp, cal),
                               px_to_db(y_lo_disp, cal))
        # Place units at the top of the right-side film scale, rather than a
        # second vertical y-label that collides with waveform's Power (dB).
        ax_film_power.set_ylabel("")
        ax_film_power.text(1.035, 1.018, "dB", transform=ax_film_power.transAxes,
                           ha="left", va="bottom", fontsize=7.0)
        ax_film_power.yaxis.set_major_locator(MaxNLocator(5))
        ax_film_power.tick_params(axis="y", labelsize=7.3, length=2.5, pad=1.5)

        # The waveform retains the COMPLETE data and calibrated peak positions.
        if np.any(wf_mask):
            ax_curve.plot(twt_arr[wf_mask], power_arr[wf_mask],
                          color="#d62728", lw=1.25, zorder=3)
        ax_curve.axhline(-60.0, color="green", ls=":", lw=0.9, zorder=2)
        if np.isfinite(tx_power):
            ax_curve.plot([0.0], [tx_power], "o", color="royalblue", ms=5, zorder=5)
        if surface is not None:
            ax_curve.plot([surface.peak_twt_us], [surface.peak_power_dB],
                          "o", color="seagreen", ms=5.2, zorder=6)
        if bed is not None:
            ax_curve.plot([bed.peak_twt_us], [bed.peak_power_dB],
                          "o", color="mediumorchid", ms=5.2, zorder=6)
        ax_curve.set_xlim(wf_ax.get_xlim())
        ax_curve.set_ylim(wf_ax.get_ylim())
        ax_curve.set_xlabel("TWTT from MB (µs)", fontsize=8.0, labelpad=1)
        ax_curve.set_ylabel("Power (dB)", fontsize=8.0, labelpad=1)
        ax_curve.xaxis.set_major_locator(MaxNLocator(5))
        ax_curve.yaxis.set_major_locator(MaxNLocator(5))
        ax_curve.tick_params(axis="both", labelsize=7.3, length=2.5, pad=1.5)
        ax_curve.grid(True, which="major", ls="-", lw=0.45,
                      color="#d0d0d0", zorder=0)

        # Legend is in the HEADER BAND rather than blocking scientific data.
        handles = [
            Line2D([0], [0], color="royalblue", marker="o", ls="None", ms=4.0, label="Tx"),
            Line2D([0], [0], color="seagreen", marker="o", ls="None", ms=4.0, label="Surface"),
            Line2D([0], [0], color="mediumorchid", marker="o", ls="None", ms=4.0, label="Bed"),
            Line2D([0], [0], color="green", ls=":", lw=1, label="−60 dB"),
        ]
        pub.legend(handles=handles, loc="center", bbox_to_anchor=(0.765, 0.703),
                   ncol=4, frameon=False, fontsize=7.2,
                   columnspacing=0.65, handletextpad=0.15,
                   handlelength=1.0, borderaxespad=0)

        # ---- Information footer ---------------------------------------------
        # These labels were previously placed INSIDE the red waveform. Keep
        # them below the graphs, in a clean two-line summary, with no overlap.
        pub.add_artist(Line2D([0.026, 0.974], [0.123, 0.123],
                              transform=pub.transFigure,
                              color="#d4d4d4", lw=0.55))
        measurements = []
        if surface is not None:
            measurements.append(
                f"Surface  {surface.peak_twt_us:.2f} µs  /  {surface.peak_power_dB:+.1f} dB")
        if bed is not None:
            measurements.append(
                f"Bed  {bed.peak_twt_us:.2f} µs  /  {bed.peak_power_dB:+.1f} dB")
        if not measurements:
            measurements = ["No resolved echoes"]
        pub.text(0.5, 0.098, "     |     ".join(measurements),
                 ha="center", va="center", fontsize=8.4, color="#1b1b1b")
        metrics = [f"Noise floor  {noise_floor_dB:.1f} dB"]
        if np.isfinite(tx_power):
            metrics.append(f"Tx  {tx_power:+.1f} dB")
        if np.isfinite(h_air_m):
            metrics.append(f"Air range  {h_air_m:.0f} m")
        if np.isfinite(h_ice_m):
            metrics.append(f"Ice thickness  {h_ice_m:.0f} m")
        pub.text(0.5, 0.045, "     |     ".join(metrics),
                 ha="center", va="center", fontsize=8.1, color="#303030")

        publication_png = PHASE4_DIR / f"F{FLT}_{file_id}_publication.png"
        publication_eps = PHASE4_DIR / f"F{FLT}_{file_id}_publication.eps"
        publication_svg = PHASE4_DIR / f"F{FLT}_{file_id}_publication.svg"
        pub.savefig(publication_png, dpi=150, facecolor="white")
        pub.savefig(publication_eps, dpi=600, format="eps", facecolor="white")
        pub.savefig(publication_svg, dpi=600, format="svg", facecolor="white")
        plt.close(pub)

    # Remove obsolete per-panel EPS files from previous processing runs.
    for old_eps_name in (f"F{FLT}_{file_id}_echoes.eps",
                         f"F{FLT}_{file_id}_waveform.eps"):
        (PHASE4_DIR / old_eps_name).unlink(missing_ok=True)
    plt.close(wf_fig)


# -- Update echo CSV (incremental, TIFF-specific rows) -------------------------
if echo_rows:
    new_df = pd.DataFrame(echo_rows)
    if ECHO_CSV.exists():
        existing = pd.read_csv(ECHO_CSV, dtype=str)
        # Preserve non-"bed" reflector_type flags set by the user
        rt_map: dict[str, str] = {}
        if "reflector_type" in existing.columns:
            for _, r in existing[existing["tiff"] == TIFF.name].iterrows():
                rt = r.get("reflector_type", "bed")
                if pd.notna(rt) and str(rt) != "bed":
                    rt_map[str(r["file_id"])] = str(rt)
        existing = existing[existing["tiff"] != TIFF.name]
        merged   = pd.concat([existing, new_df.astype(str)], ignore_index=True)
        # Re-apply preserved flags to new rows
        if rt_map:
            for fid, rt in rt_map.items():
                merged.loc[merged["file_id"] == fid, "reflector_type"] = rt
    else:
        merged = new_df.astype(str)
    # Deduplicate overlapping TIFFs: keep highest SNR per CBD
    if "cbd" in merged.columns and "bed_snr_dB" in merged.columns:
        merged["_snr_sort"] = pd.to_numeric(merged["bed_snr_dB"], errors="coerce")
        merged = merged.sort_values("_snr_sort", ascending=False)
        n_before = len(merged)
        merged = merged.drop_duplicates(subset=["cbd"], keep="first")
        merged = merged.drop(columns=["_snr_sort"])
        n_dropped = n_before - len(merged)
        if n_dropped > 0:
            print(f"  Deduped {n_dropped} overlapping-TIFF rows (kept highest SNR per CBD)")
        merged = merged.sort_values("cbd")
    merged.to_csv(ECHO_CSV, index=False)

    # -- Summary statistics -----------------------------------------------------
    print(f"\n{'-' * 60}")
    print(f"  Echo CSV -> {ECHO_CSV.relative_to(ROOT)}")
    print(f"  Phase 4 figures -> {PHASE4_DIR.relative_to(ROOT)}/")
    print(f"  Frames processed : {len(echo_rows)}")

    statuses = [r["echo_status"] for r in echo_rows]
    for st in ["good", "weak_bed", "no_bed", "no_surface"]:
        n = statuses.count(st)
        if n:
            print(f"    {st:12s}: {n}")

    good_rows = [r for r in echo_rows if r["echo_status"] in ("good", "weak_bed")]
    if good_rows:
        h_airs = [r["h_air_m"] for r in good_rows
                  if not (isinstance(r["h_air_m"], float) and np.isnan(r["h_air_m"]))]
        h_ices = [r["h_ice_m"] for r in good_rows
                  if not (isinstance(r["h_ice_m"], float) and np.isnan(r["h_ice_m"]))]
        if h_airs:
            print(f"  h_air  : {np.mean(h_airs):.0f} ± {np.std(h_airs):.0f} m "
                  f"(n={len(h_airs)})")
        if h_ices:
            print(f"  h_ice  : {np.mean(h_ices):.0f} ± {np.std(h_ices):.0f} m "
                  f"(n={len(h_ices)})")

    # -- Generate review summary JSON (full flight, all TIFFs) -------------
    review_json_path = PHASE4_DIR / f"F{FLT}_echo_review.json"
    full_df = pd.read_csv(ECHO_CSV)
    review_data = {
        "flight": FLT,
        "total_frames": len(full_df),
        "summary": {},
    }
    for st_name in ["good", "weak_bed", "no_bed", "no_surface"]:
        st_df = full_df[full_df["echo_status"] == st_name]
        review_data["summary"][st_name] = len(st_df)

    # Per-status frame lists (only non-good statuses)
    for st_name in ["no_bed", "no_surface", "weak_bed"]:
        st_df = full_df[full_df["echo_status"] == st_name]
        if len(st_df) == 0:
            continue
        frames = []
        for _, row in st_df.iterrows():
            frames.append({
                "tiff_id": str(row.get("tiff_id", "")),
                "cbd": str(int(float(row["cbd"]))) if str(row["cbd"]).replace('.','',1).isdigit() else str(row["cbd"]),
                "file_id": str(row["file_id"]),
            })
        review_data[st_name] = frames

    # Per-TIFF breakdown: how many bad frames each TIFF has
    bad_df = full_df[full_df["echo_status"].isin(["no_bed", "no_surface", "weak_bed"])]
    if len(bad_df) > 0:
        tiff_breakdown = {}
        for tid, grp in bad_df.groupby("tiff_id"):
            counts = grp["echo_status"].value_counts().to_dict()
            tiff_breakdown[str(tid)] = {
                "total_bad": len(grp),
                **{k: int(v) for k, v in counts.items()},
            }
        # Sort by total_bad descending
        review_data["tiff_breakdown"] = dict(
            sorted(tiff_breakdown.items(), key=lambda x: x[1]["total_bad"], reverse=True)
        )

    with open(review_json_path, "w") as f:
        json.dump(review_data, f, indent=2)
    print(f"  Review JSON -> {review_json_path.relative_to(ROOT)}")

print("\nDone.")
