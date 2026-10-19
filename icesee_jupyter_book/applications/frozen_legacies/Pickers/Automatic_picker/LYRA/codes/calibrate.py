# pyright: reportArgumentType=false, reportGeneralTypeIssues=false, reportCallIssue=false, reportAttributeAccessIssue=false
"""
calibrate.py — LYRA Phase 3: Per-frame calibration
========================================================
For each complete frame in a TIFF, independently detects:

  • Main bang column  (mb_x)      -> X anchor: t = 0 µs
  • Reference line row (y_ref_px) -> Y anchor: power = -60 dB
  • X grid lines                  -> detected via argmax in below-baseline band
  • Y grid lines                  -> extrapolated from y_ref_px + k × y_spacing

Calibration values are NEVER assumed constant across frames.
Each frame gets its own (mb_x, y_ref_px, x_spacing_px, y_spacing_px).

If a guidance picks file exists (F{FLT}_cal_picks.json from pick_calibration.py),
guide picks for each frame are passed to the detection algorithm.  This narrows
the main-bang search to ±200 px around the user click, and cross-checks the
y_ref estimate.  Frames without guide picks fall back to the pure algorithm.

Quality gate
------------
After Pass 1, frames whose mb_power_dB deviates more than 8 dB below the
TIFF-median are re-run without D_anchor (Priority A2 stripped -> falls back to
Priority B phase search).  This prevents a mis-detected main bang from
corrupting the x-grid via the D_anchor offset.

Frames marked "exclude": true in the guide picks JSON are skipped entirely
(film defect, tilted graticule, or other unrecoverable artifact).

Usage
-----
Run from repo root:

    python codes/calibrate.py [TIFF_PATH]

If TIFF_PATH is omitted, defaults to the F125 training TIFF.

Outputs
-------
Per-flight calibration CSV (updated incrementally):
    output/F{FLT}/phase3/F{FLT}_cal.csv
      Columns: flight, tiff_id, frame_idx, cbd, file_id,
               mb_x, mb_power_dB, y_ref_px, db_per_px, us_per_px,
               x_spacing_px, hgrid_spacing, cal_source_y

Per-frame diagnostic figure:
    output/F{FLT}/phase3/F{FLT}_{file_id}_cal.png
      Red   dashed vertical   -> main bang (t = 0 µs)
      Cyan  dashed horizontal -> reference line (-60 dB)
      Gold  dashed horizontal -> Y grid lines (extrapolated, every 10 dB)
      Blue  dashed vertical   -> X grid lines (detected, every 1.5 µs)
      White dotted            -> user guide picks (if provided)
"""

from pathlib import Path
import sys
import os
import json

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "codes"))

from lyra import (
    DEFAULT_CAL, detect_frames, extract_trace,
    detect_mb, detect_frame_calibration, px_to_db,
    _gauss_smooth, ensure_canonical_name, resolve_tiff_arg, tiff_id,
    detect_signal_extent,
)

# -- Resolve TIFF path ----------------------------------------------------------
if len(sys.argv) > 1:
    TIFF = resolve_tiff_arg(sys.argv[1], ROOT)
else:
    TIFF = ROOT / "tiff/125/40_0008400_0008424-reel_begin_end.tiff"

# Rename to canonical format if needed (e.g. F141 files renamed from reel convention)
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
PHASE3_DIR.mkdir(parents=True, exist_ok=True)

INDEX_CSV    = PHASE1_DIR / f"F{FLT}_frame_index.csv"
CAL_CSV      = PHASE3_DIR / f"F{FLT}_cal.csv"
PICKS_JSON   = PHASE1_DIR / f"F{FLT}_cal_picks.json"
DERIVED_JSON = PHASE1_DIR / f"F{FLT}_cal_derived.json"

# -- Load frame index -----------------------------------------------------------
if not INDEX_CSV.exists():
    sys.exit(f"ERROR: frame index not found at {INDEX_CSV}\n"
             "Run phase 1 (detect_frames.py) first.")

index     = pd.read_csv(INDEX_CSV, dtype=str)
tiff_rows = index[index["tiff"] == TIFF.name].copy()

if len(tiff_rows) == 0:
    sys.exit(f"ERROR: {TIFF.name} not found in frame index.\n"
             "Run phase 1 (detect_frames.py) for this TIFF first.")

print(f"\nLYRA Phase 3 — {TIFF.name}")
print(f"  Flight : F{FLT}  |  tiff_id : {TIFF_ID}")
print(f"  Frames in index: {len(tiff_rows)}  "
      f"(complete: {(tiff_rows.frame_type == 'complete').sum()})\n")

# -- Load guidance picks (if available from pick_calibration.py) ---------------
raw_picks:   dict = {}
derived_cal: dict = {}

if PICKS_JSON.exists():
    with open(PICKS_JSON) as f:
        raw_picks = json.load(f)
    print(f"  Guide picks   : {len(raw_picks)} frames  ({PICKS_JSON.name})")

if DERIVED_JSON.exists():
    with open(DERIVED_JSON) as f:
        derived_cal = json.load(f)
    print(f"  Derived cal   : x_spacing={derived_cal.get('x_spacing_px','?')} px  "
          f"y_spacing={derived_cal.get('y_spacing_px','?')} px")

if not raw_picks:
    print("  [INFO] No guide picks file found.")
print()

# -- Measure x_spacing_px from guide picks if not already in derived_cal -------
# derived_cal["x_spacing_px"] propagates (via _build_guides) to EVERY frame.
# Without this, all frames use DEFAULT_CAL's 205.54 px (measured on F125), which
# causes progressive drift on any TIFF with a different oscilloscope time base.
if not derived_cal.get("x_spacing_px") and raw_picks:
    _default_sp = 2.0 / DEFAULT_CAL["us_per_px"]   # F125 baseline spacing
    for _picks in raw_picks.values():
        _xg = _picks.get("x_grid")
        if _xg and len(_xg) >= 4:
            _xs = np.array(sorted(float(v) for v in _xg), dtype=float)
            _kk = np.array([round((x - _xs[0]) / _default_sp) for x in _xs], dtype=float)
            if len(np.unique(_kk)) < 2:
                continue
            derived_cal["x_spacing_px"] = abs(float(np.polyfit(_kk, _xs, 1)[0]))
            print(f"  x_spacing measured from guide picks : "
                  f"{derived_cal['x_spacing_px']:.2f} px/div  "
                  f"(DEFAULT_CAL was {_default_sp:.2f})")
            break

# -- Compute tiff-level D_anchor ------------------------------------------------
# D_anchor = distance (px) from mb_x to the nearest major tick to the right.
# The oscilloscope sweep is triggered from the radar transmit pulse, so all
# waveform content is time-locked to the graticule — D is constant within a TIFF.
# Derived from the first guided frame that has both an mb pick and x_grid click(s).
tiff_d_anchor: float | None = None
if raw_picks:
    _sp = derived_cal.get("x_spacing_px", 2.0 / DEFAULT_CAL["us_per_px"])
    for _picks in raw_picks.values():
        _mb = _picks.get("mb")
        _xg = _picks.get("x_grid")
        if _mb is not None and _xg and len(_xg) >= 1:
            tiff_d_anchor = float(min(_xg)) - float(_mb)
            print(f"  D_anchor      : {tiff_d_anchor:.1f} px  "
                  f"(mb={_mb}, x_grid[0]={min(_xg):.0f})")
            break
if tiff_d_anchor is None:
    print("  D_anchor      : (none — no frame with both mb and x_grid picks)")

# -- Tiff-level MB estimate -----------------------------------------------------
# Median MB position across guided frames with mb > 200 px (> 200 excludes
# reel-begin artifacts where CRT hasn't settled; mb ~ 100–150 px in those frames).
# Used as a soft guide for unguided frames in flights where DEFAULT_CAL's
# mb_x_guess=800 is wrong (e.g. F141 where the real MB is at ~540 px).
#
# Priority: per-TIFF picks first (handles TIFFs with MB at a different position
# from the flight norm, e.g. F126 TIFF 2625 at ~730 px vs flight median ~580 px).
# Falls back to flight-wide median only if no picks exist for this TIFF.
# Detect duplicate CBDs within this TIFF (same fix as pick_calibration.py)
from collections import Counter as _Counter

def _norm_cbd(val):
    """Normalize CBD value to int (strips .0 from float CBDs)."""
    if pd.isna(val) or str(val).strip() in ("", "nan"):
        return None
    return int(float(val))

_tiff_cbds = [str(_norm_cbd(r["cbd"])) for _, r in tiff_rows.iterrows()
              if r["frame_type"] == "complete" and _norm_cbd(r["cbd"]) is not None]
_dup_cbds = {c for c, n in _Counter(_tiff_cbds).items() if n > 1}

def _cal_fkey(cbd, frame_idx):
    """Build pick-lookup key, disambiguating duplicate CBDs with frame_idx.

    Tries the normalized key first (CBD810), then falls back to zero-padded
    formats (CBD0810) to handle key format differences between
    pick_calibration.py (preserves raw CBD string) and calibrate.py
    (normalizes to int).
    """
    if cbd and str(cbd) in _dup_cbds:
        return f"CBD{cbd}_f{frame_idx}"
    key = f"CBD{cbd}" if cbd else f"fr{frame_idx}"
    # If key not in picks, try zero-padded variant (pick_calibration uses raw string)
    if key not in raw_picks and cbd is not None:
        padded = f"CBD{int(cbd):04d}"
        if padded in raw_picks:
            return padded
    return key

tiff_mb_estimate: float | None = None
if raw_picks:
    # Determine which pick keys belong to the current TIFF
    _this_tiff_keys = set()
    for _, r in tiff_rows.iterrows():
        _cbd = _norm_cbd(r["cbd"])
        _this_tiff_keys.add(_cal_fkey(_cbd, r["frame_idx"]))

    # Per-TIFF MB picks (preferred)
    _tiff_mbs = [
        float(raw_picks[k]["mb"]) for k in _this_tiff_keys
        if k in raw_picks and raw_picks[k].get("mb") is not None
        and not raw_picks[k].get("exclude") and float(raw_picks[k]["mb"]) > 200
    ]
    # Flight-wide MB picks (fallback)
    _all_mbs = [
        float(p["mb"]) for p in raw_picks.values()
        if p.get("mb") is not None and not p.get("exclude")
        and float(p["mb"]) > 200
    ]
    if _tiff_mbs:
        tiff_mb_estimate = float(np.median(_tiff_mbs))
        print(f"  MB estimate   : {tiff_mb_estimate:.0f} px  "
              f"(median of {len(_tiff_mbs)} per-TIFF MB pick(s))")
    elif _all_mbs:
        tiff_mb_estimate = float(np.median(_all_mbs))
        print(f"  MB estimate   : {tiff_mb_estimate:.0f} px  "
              f"(flight-wide median of {len(_all_mbs)} guided MB pick(s))")

# Per-frame MB estimates from CRT sweep start (sig_start).
# Populated after TIFF image is loaded; used by _build_guides().
sig_mb_by_fkey: dict = {}

# -- Identify tiff-level anchor -------------------------------------------------
# If any complete frame in this TIFF already has picks (e.g. collected by
# pick_calibration.py with Q after frame 0), propagate only its REF (y_ref_px)
# to frames without individual picks.  The REF (noise floor row) is stable
# across frames and can be safely reused from truncated or full-width frames alike.
# MB position is frame-specific and must be found algorithmically — it is NOT
# propagated even from full-width frames.
#
# Width filter: only applies to finding full-width frames for possible MB picks
# (not needed here since MB is always algorithmic).  For REF, any complete frame
# with a pick is a valid anchor — INCLUDING truncated TIFF-start/end frames.
_complete_widths = [
    int(r["right_px"]) - int(r["left_px"]) + 1
    for _, r in tiff_rows.iterrows()
    if r["frame_type"] == "complete"
]
_median_w = float(np.median(_complete_widths)) if _complete_widths else 0.0

tiff_anchor: dict = {}
for _, anchor_row in tiff_rows.iterrows():
    if anchor_row["frame_type"] != "complete":
        continue
    # REF is stable and can come from ANY frame (including truncated start/end).
    # Width check is intentionally NOT applied here.
    cbd_a  = _norm_cbd(anchor_row["cbd"])
    fkey_a = _cal_fkey(cbd_a, anchor_row["frame_idx"])
    if fkey_a in raw_picks:
        p_a = raw_picks[fkey_a]
        if p_a.get("ref") is not None:
            tiff_anchor["ref"] = int(p_a["ref"])
    if tiff_anchor:
        print(f"  Tiff anchor   : {fkey_a}  ref={tiff_anchor['ref']}  "
              f"(ref propagated to frames without individual picks; "
              f"mb detected algorithmically per frame)")
        break


# -- Enforce minimum ref pick for y_ref calibration -------------------------
# The -60 dB reference row (y_ref_px) cannot be reliably auto-detected.
# A user pick for at least one complete frame in THIS TIFF is required so
# that y_ref_px propagates accurately to all unguided frames.
# Without this, the pre-bang 75th-percentile fallback produces erratic
# y_ref values (observed range: 836–1590 px vs correct ~1509 px).
if not tiff_anchor:
    tiff_cbds = [
        str(_norm_cbd(r["cbd"])) for _, r in tiff_rows.iterrows()
        if r["frame_type"] == "complete" and _norm_cbd(r["cbd"]) is not None
    ]
    cbd_range = (
        f"CBD{tiff_cbds[0]}–CBD{tiff_cbds[-1]}" if len(tiff_cbds) >= 2
        else f"CBD{tiff_cbds[0]}" if tiff_cbds
        else f"frames in {TIFF.name}"
    )
    picks_info = (
        f"Guide picks loaded cover: {sorted(raw_picks.keys())}"
        if raw_picks
        else "No guide picks file found."
    )
    tiff_arg = sys.argv[1] if len(sys.argv) > 1 else str(TIFF)
    sys.exit(
        f"\nERROR: No reference-line pick found for TIFF {TIFF_ID} ({cbd_range}).\n"
        f"  {picks_info}\n\n"
        f"  The -60 dB reference row (y_ref_px) cannot be reliably detected\n"
        f"  without at least one user pick for the current TIFF.\n\n"
        f"  Fix:\n"
        f"    python codes/pick_calibration.py {tiff_arg}\n\n"
        f"  In the picker, open any complete frame from {cbd_range}.\n"
        f"  Press R to click the -60 dB reference line (noise floor baseline),\n"
        f"  then press Q to save and exit.\n\n"
        f"  Then re-run step 2:\n"
        f"    python codes/calibrate.py {tiff_arg}\n"
    )


def _build_guides(fkey: str) -> dict:
    """Assemble guide dict: per-frame picks -> tiff anchor ref -> global defaults.

    MB (main bang column): use per-frame pick if available; otherwise let the
    no-guide algorithm run (global noise floor + leftmost peak).  The tiff
    anchor's mb is intentionally NOT propagated — mb position can vary across
    frames and an incorrect mb guide is worse than no guide at all.

    REF (y_ref_px = -60 dB row): use per-frame pick, then tiff anchor, then
    default.  The noise floor row is stable within a TIFF, so propagation is safe.
    """
    g: dict = {}
    # Global spacing and x-offset from derived calibration
    if derived_cal.get("x_spacing_px"):
        g["x_spacing_px"] = float(derived_cal["x_spacing_px"])
    if derived_cal.get("y_spacing_px"):
        g["y_spacing_px"] = float(derived_cal["y_spacing_px"])
    # Per-frame pick: use mb, ref, and x_grid
    per_frame = raw_picks.get(fkey, {})
    if per_frame.get("mb") is not None:
        g["mb"] = int(per_frame["mb"])
        g["mb_is_pick"] = True   # explicit user pick — trust it in detect_mb
    if per_frame.get("ref") is not None:
        g["ref"] = int(per_frame["ref"])
    if per_frame.get("x_grid"):
        g["x_grid"] = [int(v) for v in per_frame["x_grid"]]
    # Tiff anchor: propagate ref only if not already set from per-frame pick
    if "ref" not in g and tiff_anchor.get("ref") is not None:
        g["ref"] = int(tiff_anchor["ref"])
    # MB estimate: soft guide for unguided frames.
    # Priority: per-frame sig_start-based estimate (adapts to film frame boundary
    # shifts) -> tiff_mb_estimate (median of guided-frame MB picks).
    if "mb" not in g and fkey in sig_mb_by_fkey:
        g["mb"] = int(round(sig_mb_by_fkey[fkey]))
    elif "mb" not in g and tiff_mb_estimate is not None:
        g["mb"] = int(round(tiff_mb_estimate))
    # D_anchor: propagate to frames without per-frame x_grid picks (Priority A2)
    if "x_grid" not in g and tiff_d_anchor is not None:
        g["d_from_mb"] = tiff_d_anchor
    return g


# -- Load TIFF image ------------------------------------------------------------
print("Loading TIFF ...")
Image.MAX_IMAGE_PIXELS = None
img      = np.array(Image.open(TIFF), dtype=np.float32)
img_norm = (img - img.min()) / (img.max() - img.min() + 1e-9)
H, W     = img_norm.shape
print(f"  Image  : {W} x {H} px")

# -- Hybrid sig_start-based MB guide -------------------------------------------
# The CRT sweep start (sig_start) is time-locked to the oscilloscope trigger,
# so D_mb = mb_x - sig_start is constant within a TIFF even when film frame
# boundaries shift.  Per-frame sig_start + median(D_mb) gives a more robust MB
# guide than tiff_mb_estimate for TIFFs with shifting frame boundaries.
#
# Robustness: some frames have faint/absent PRF timing pulses, causing sig_start
# to jump ~400+ px (landing on MB instead of the sweep start).  We use
# median(sig_start) as a robust reference and only trust frames whose sig_start
# is within 50 px of the median.  Outlier frames fall back to tiff_mb_estimate.
if raw_picks:
    _sig_starts: dict = {}   # fkey -> sig_start (px)
    for _, _r in tiff_rows.iterrows():
        if _r["frame_type"] != "complete":
            continue
        _cbd = _norm_cbd(_r["cbd"])
        _fk  = _cal_fkey(_cbd, _r["frame_idx"])
        if raw_picks.get(_fk, {}).get("exclude"):
            continue
        _left  = int(_r["left_px"])
        _right = int(_r["right_px"])
        _frame = img_norm[:, _left : _right + 1]
        try:
            _ss, _ = detect_signal_extent(_frame, DEFAULT_CAL)
            _sig_starts[_fk] = _ss
        except Exception:
            pass

    if _sig_starts:
        _ss_arr    = np.array(list(_sig_starts.values()))
        _median_ss = float(np.median(_ss_arr))

        # D_mb from guided frames with stable sig_start (within 50 px of median)
        _d_mb_vals = []
        for _fk, _ss in _sig_starts.items():
            if abs(_ss - _median_ss) > 50:
                continue   # outlier sig_start — skip
            _pp = raw_picks.get(_fk, {})
            if (_pp.get("mb") is not None and not _pp.get("exclude")
                    and float(_pp["mb"]) > 200):
                _d_mb_vals.append(float(_pp["mb"]) - _ss)

        if _d_mb_vals:
            _med_d = float(np.median(_d_mb_vals))
            for _fk, _ss in _sig_starts.items():
                if abs(_ss - _median_ss) <= 50:   # stable sig_start
                    sig_mb_by_fkey[_fk] = _ss + _med_d
            _n_stable = len(sig_mb_by_fkey)
            _n_total  = len(_sig_starts)
            print(f"  Sig-start MB  : {_n_stable}/{_n_total} frames  "
                  f"(median sig_start={_median_ss:.0f} px,  "
                  f"median D_mb={_med_d:.0f} px)")
        else:
            print(f"  Sig-start MB  : INACTIVE  (no guided MB picks with stable sig_start)")
    else:
        print(f"  Sig-start MB  : INACTIVE  (no sig_start could be computed)")
else:
    print(f"  Sig-start MB  : INACTIVE  (no guide picks)")
print()

# -- Pass 1: calibrate all frames -----------------------------------------------
# Collect (frame_idx -> data dict) for quality gate and figure generation.
# Frames marked exclude=true in guide picks are flagged and skipped.

cal_rows    = []
_frame_data = {}   # frame_idx -> dict(frame, cal, guides, cbd, fkey, file_id)

print(f"  {'Fr':>3}  {'CBD':>6}  {'mb_x':>6}  {'mb_dB':>7}  "
      f"{'y_ref':>6}  {'db/px':>7}  {'x_sp':>6}  {'Ygrid':>5}  Guide?")
print("  " + "-" * 72)

for _, row in tiff_rows.iterrows():
    frame_idx  = int(row["frame_idx"])
    frame_type = row["frame_type"]
    cbd        = _norm_cbd(row["cbd"])
    left_px    = int(row["left_px"])
    right_px   = int(row["right_px"])

    file_id = f"{TIFF_ID}_CBD{cbd}" if cbd else f"{TIFF_ID}_fr{frame_idx:02d}"
    if cbd and str(cbd) in _dup_cbds:
        file_id = f"{TIFF_ID}_CBD{cbd}_f{frame_idx}"
    fkey    = _cal_fkey(cbd, frame_idx)

    if frame_type == "partial":
        print(f"  {frame_idx:>3}  {'—':>6}  {'—':>6}  {'—':>7}  "
              f"{'—':>6}  {'—':>7}  {'—':>6}  {'—':>5}  (partial — skip)")
        continue

    # Check for explicit exclusion in guide picks
    if raw_picks.get(fkey, {}).get("exclude"):
        reason = raw_picks[fkey].get("exclude_reason", "excluded in guide picks")
        print(f"  {frame_idx:>3}  {str(cbd):>6}  {'—':>6}  {'—':>7}  "
              f"{'—':>6}  {'—':>7}  {'—':>6}  {'—':>5}  (EXCLUDED: {reason})")
        # Delete any stale figure left by a previous run before exclusion was added
        stale_png = PHASE3_DIR / f"F{FLT}_{file_id}_cal.png"
        if stale_png.exists():
            stale_png.unlink()
            print(f"        > Deleted stale figure: {stale_png.name}")
        # Write excluded row so step3 knows why this frame was skipped
        cal_rows.append(dict(
            flight        = FLT,
            tiff          = TIFF.name,
            tiff_id       = TIFF_ID,
            frame_idx     = frame_idx,
            cbd           = cbd or "",
            file_id       = file_id,
            mb_x          = "",
            mb_power_dB   = "",
            y_ref_px      = "",
            db_per_px     = "",
            us_per_px     = "",
            x_spacing_px  = "",
            hgrid_spacing = "",
            cal_source_y  = "",
            had_guide     = "",
            exclude_reason = reason,
        ))
        continue

    # Crop this frame (numpy view — no extra memory)
    frame  = img_norm[:, left_px : right_px + 1]
    guides = _build_guides(fkey)

    # Per-frame calibration (validated algorithms + optional guide picks)
    cal = detect_frame_calibration(frame, DEFAULT_CAL, guides=guides)

    mb_x         = cal["mb_x"]
    mb_power_dB  = cal["mb_power_dB"]
    y_ref_px     = cal["y_ref_px"]
    db_per_px    = cal["db_per_px"]
    x_spacing_px = cal["x_spacing_px"]
    hgrid_sp     = cal["hgrid_spacing"]
    hgrid_lines  = cal["hgrid_lines"]
    n_hgrid      = len(hgrid_lines)
    has_guide    = "[OK]" if (guides.get("mb") or guides.get("ref")) else "—"

    print(f"  {frame_idx:>3}  {str(cbd):>6}  {mb_x:>6}  {mb_power_dB:>+7.1f}  "
          f"{y_ref_px:>6.0f}  {db_per_px:>7.5f}  {x_spacing_px:>6.1f}  "
          f"{n_hgrid:>5}  {has_guide}")

    _frame_data[frame_idx] = dict(
        frame=frame, cal=cal, guides=guides,
        cbd=cbd, fkey=fkey, file_id=file_id,
    )
    cal_rows.append(dict(
        flight        = FLT,
        tiff          = TIFF.name,
        tiff_id       = TIFF_ID,
        frame_idx     = frame_idx,
        cbd           = cbd or "",
        file_id       = file_id,
        mb_x          = mb_x,
        mb_power_dB   = round(mb_power_dB, 2),
        y_ref_px      = round(y_ref_px, 1),
        db_per_px     = round(db_per_px, 6),
        us_per_px     = round(2.0 / x_spacing_px, 8) if x_spacing_px > 0 else round(DEFAULT_CAL["us_per_px"], 8),
        x_spacing_px  = round(x_spacing_px, 2),
        hgrid_spacing = round(hgrid_sp, 1) if hgrid_sp else "",
        cal_source_y  = cal["cal_source_y"],
        had_guide     = bool(guides.get("mb") or guides.get("ref")),
        exclude_reason = "",
    ))

# -- Quality gate: re-run mb-outlier frames without D_anchor -------------------
# If mb_power_dB is more than 8 dB below the TIFF median, the main bang was
# likely mis-detected (T/R transient, noise peak, faint film).  Strip D_anchor
# and re-run to let Priority B (phase search) find the graticule directly.
if cal_rows:
    valid_mb = [r["mb_power_dB"] for r in cal_rows
                if isinstance(r["mb_power_dB"], (int, float)) and r["mb_power_dB"] > -50.0]
    if valid_mb:
        tiff_med_mb = float(np.median(valid_mb))
        bad_thresh  = tiff_med_mb - 8.0
        bad_idxs    = [(i, r) for i, r in enumerate(cal_rows)
                       if isinstance(r["mb_power_dB"], (int, float))
                       and r["mb_power_dB"] < bad_thresh]
        if bad_idxs:
            print(f"\n  Quality gate  : median mb={tiff_med_mb:.1f} dB  "
                  f"threshold={bad_thresh:.1f} dB")
            for list_i, r in bad_idxs:
                d  = _frame_data[r["frame_idx"]]
                g2 = _build_guides(d["fkey"])
                g2.pop("d_from_mb", None)   # strip D_anchor -> Priority B fallback
                cal2 = detect_frame_calibration(d["frame"], DEFAULT_CAL, guides=g2)
                mb2  = cal2["mb_x"]
                mbp2 = cal2["mb_power_dB"]
                print(f"    {d['file_id']:15s}: mb_power {r['mb_power_dB']:+.1f} -> {mbp2:+.1f} dB  "
                      f"mb_x {r['mb_x']} -> {mb2}")
                # Update stored calibration and cal_row
                _frame_data[r["frame_idx"]]["cal"]    = cal2
                _frame_data[r["frame_idx"]]["guides"] = g2
                xsp2 = cal2["x_spacing_px"]
                cal_rows[list_i].update(dict(
                    mb_x          = mb2,
                    mb_power_dB   = round(mbp2, 2),
                    y_ref_px      = round(cal2["y_ref_px"], 1),
                    db_per_px     = round(cal2["db_per_px"], 6),
                    us_per_px     = round(2.0 / xsp2, 8) if xsp2 > 0 else round(DEFAULT_CAL["us_per_px"], 8),
                    x_spacing_px  = round(xsp2, 2),
                    hgrid_spacing = round(cal2["hgrid_spacing"], 1) if cal2["hgrid_spacing"] else "",
                    cal_source_y  = cal2["cal_source_y"],
                ))

# -- Generate figures (after quality gate, using final calibrations) ------------
for frame_idx in sorted(_frame_data):
    d            = _frame_data[frame_idx]
    frame        = d["frame"]
    cal          = d["cal"]
    guides       = d["guides"]
    file_id      = d["file_id"]
    mb_x         = cal["mb_x"]
    y_ref_px     = cal["y_ref_px"]
    db_per_px    = cal["db_per_px"]
    x_spacing_px = cal["x_spacing_px"]
    hgrid_lines  = cal["hgrid_lines"]
    xgrid_lines  = cal.get("xgrid_lines", [])
    xgrid_raw    = cal.get("xgrid_raw_lines", [])

    fig, ax = plt.subplots(figsize=(14, 4))
    fig.patch.set_facecolor("white")
    fw = frame.shape[1]
    ax.imshow(frame, cmap="gray", vmin=0, vmax=1, aspect="auto",
              extent=[0, fw, frame.shape[0], 0])

    # Y grid lines (gold dashed) — extrapolated from y_ref_px
    db_labels = {}
    for yg in hgrid_lines:
        db_at_line = -60.0 + (y_ref_px - yg) * db_per_px
        ax.axhline(yg, color="gold", lw=0.8, ls="--", alpha=0.7)
        db_labels[yg] = db_at_line

    # Reference line (cyan thick) — y_ref_px = -60 dB
    ax.axhline(y_ref_px, color="cyan", lw=1.5, ls="--", alpha=0.9,
               label=f"Ref -60 dB  y={y_ref_px:.0f}")

    # X grid diagnostic:
    #   red dotted = raw image detections before fitting
    #   blue dashed = final regularized/fitted grid used by LYRA
    _raw_label_done = False
    for xr in xgrid_raw:
        if 0 < xr < fw:
            ax.axvline(xr, color="red", lw=0.9, ls=":", alpha=0.85,
                       label="raw grid detection" if not _raw_label_done else None)
            _raw_label_done = True

    _fit_label_done = False
    for xg in xgrid_lines:
        if 0 < xg < fw:
            ax.axvline(xg, color="steelblue", lw=0.8, ls="--", alpha=0.75,
                       label="fitted grid" if not _fit_label_done else None)
            _fit_label_done = True

    # Main bang (red thick)
    ax.axvline(mb_x, color="red", lw=1.5, ls="--", alpha=0.9,
               label=f"MB  t=0  x={mb_x}")

    # Guide picks (white dotted) — show what the user clicked vs what algorithm found
    if guides.get("mb") is not None:
        ax.axvline(guides["mb"], color="white", lw=0.8, ls=":",
                   alpha=0.7, label=f"guide_mb x={guides['mb']}")
    if guides.get("ref") is not None:
        ax.axhline(guides["ref"], color="white", lw=0.8, ls=":",
                   alpha=0.7, label=f"guide_ref y={guides['ref']}")

    ax.set_ylim(DEFAULT_CAL["y_disp_hi"] + 50, DEFAULT_CAL["y_disp_lo"] - 50)
    ax.set_xlim(0, fw)
    ax.set_xlabel("Column (px, frame-relative)", fontsize=8)
    ax.set_ylabel("Row (px)", fontsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    src_lbl = "guide+algo" if (guides.get("mb") or guides.get("ref")) else "algo only"
    ax.set_title(
        f"LYRA Step 2 — F{FLT} {file_id}  |  "
        f"mb_x={mb_x}  y_ref={y_ref_px:.0f} (-60 dB)  "
        f"db/px={db_per_px:.5f}  x_sp={x_spacing_px:.1f} px  [{src_lbl}]",
        fontsize=8, loc="left",
    )
    ax.legend(fontsize=7, loc="upper right",
              framealpha=0.6, facecolor="black", labelcolor="white")

    # dB axis on the right
    ax2 = ax.twinx()
    ax2.set_ylim(ax.get_ylim())
    yticks = [y for y in db_labels
              if DEFAULT_CAL["y_disp_lo"] - 50 < y < DEFAULT_CAL["y_disp_hi"] + 50]
    ax2.set_yticks(yticks)
    ax2.set_yticklabels([f"{db_labels[y]:+.0f} dB" for y in yticks], fontsize=7)
    ax2.tick_params(right=True, labelright=True)
    ax2.spines["top"].set_visible(False)

    fig.tight_layout()
    fig_path = PHASE3_DIR / f"F{FLT}_{file_id}_cal.png"
    eps_path = PHASE3_DIR / f"F{FLT}_{file_id}_cal.eps"
    fig.savefig(fig_path, dpi=150, bbox_inches="tight", facecolor="white")
    fig.savefig(eps_path, format="eps", dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)

# -- Update calibration CSV -----------------------------------------------------
if cal_rows:
    new_df = pd.DataFrame(cal_rows)
    if CAL_CSV.exists():
        existing = pd.read_csv(CAL_CSV, dtype=str)
        existing = existing[existing["tiff"] != TIFF.name]
        merged   = pd.concat([existing, new_df.astype(str)], ignore_index=True)
    else:
        merged = new_df.astype(str)
    merged.to_csv(CAL_CSV, index=False)
    print(f"\n  Calibration CSV -> {CAL_CSV.relative_to(ROOT)}")
    print(f"  Phase 3 figures -> {PHASE3_DIR.relative_to(ROOT)}/")
    print(f"  Total cal rows  : {len(merged)}")
    n_guided = sum(1 for r in cal_rows if r["had_guide"])
    print(f"  Frames with guide: {n_guided}/{len(cal_rows)}")

# -- Generate calibration review JSON ------------------------------------------
# Reads the full flight cal CSV and flags CHECK TIFFs / frames.
# Updated after every TIFF run so the user always has a current overview.
REVIEW_JSON = PHASE3_DIR / f"F{FLT}_cal_review.json"

if CAL_CSV.exists():
    _review_df = pd.read_csv(CAL_CSV)
    _review_df.columns = _review_df.columns.str.strip()

    # Filter to calibrated (non-excluded) frames with valid x_spacing
    _excl = _review_df["exclude_reason"].fillna("").astype(str).str.strip()
    _cal_df = _review_df[_excl == ""].copy()
    _cal_df["x_spacing_px"] = pd.to_numeric(_cal_df["x_spacing_px"], errors="coerce")
    _cal_df["mb_power_dB"] = pd.to_numeric(_cal_df["mb_power_dB"], errors="coerce")
    _cal_df = _cal_df.dropna(subset=["x_spacing_px"])

    _review: dict = {
        "flight": FLT,
        "total_frames": len(_review_df),
        "calibrated_frames": len(_cal_df),
        "excluded_frames": int((_excl != "").sum()),
    }

    # Flight-wide x_spacing median (reference for outlier detection)
    _flt_xs_med = float(_cal_df["x_spacing_px"].median()) if len(_cal_df) > 0 else 205.0

    _check_tiffs: list[dict] = []
    _check_frames: list[dict] = []

    for _tid in sorted(_cal_df["tiff_id"].unique()):
        _sub = _cal_df[_cal_df["tiff_id"] == _tid]
        _xs_med = float(_sub["x_spacing_px"].median())
        _xs_std = float(_sub["x_spacing_px"].std()) if len(_sub) > 1 else 0.0

        _reason = ""
        if _xs_std > 10:
            _reason = f"x_spacing varies > 10 px (std={_xs_std:.1f})"
        elif abs(_xs_med - _flt_xs_med) > 15:
            _reason = (f"x_spacing median ({_xs_med:.1f}) deviates "
                       f"> 15 px from flight ({_flt_xs_med:.1f})")

        if _reason:
            # Flag individual frames with x_spacing outliers
            _bad = _sub[
                (_sub["x_spacing_px"] - _flt_xs_med).abs() > 15
            ]
            _bad_cbds = sorted(_bad["cbd"].dropna().astype(int).tolist())
            _bad_frames = []
            for _, _br in _bad.iterrows():
                _bad_frames.append({
                    "tiff_id": str(int(_br["tiff_id"])),
                    "cbd": str(int(_br["cbd"])) if pd.notna(_br["cbd"]) and str(_br["cbd"]).strip() else "",
                    "file_id": str(_br["file_id"]),
                    "x_spacing_px": round(float(_br["x_spacing_px"]), 1),
                })
            _check_tiffs.append({
                "tiff_id": str(int(_tid)),
                "reason": _reason,
                "x_spacing_median": round(_xs_med, 1),
                "x_spacing_std": round(_xs_std, 1),
                "n_frames": len(_sub),
                "n_bad": len(_bad),
                "bad_cbds": [f"{c:04d}" for c in _bad_cbds],
            })
            _check_frames.extend(_bad_frames)

    _n_good_tiffs = int(_cal_df["tiff_id"].nunique()) - len(_check_tiffs)
    _review["summary"] = {
        "good_tiffs": _n_good_tiffs,
        "check_tiffs": len(_check_tiffs),
        "total_tiffs": int(_cal_df["tiff_id"].nunique()),
        "flight_x_spacing_median": round(_flt_xs_med, 1),
    }
    _review["check_tiffs"] = _check_tiffs
    _review["check_frames"] = _check_frames

    with open(REVIEW_JSON, "w") as _f:
        json.dump(_review, _f, indent=2)
    print(f"  Review JSON   -> {REVIEW_JSON.relative_to(ROOT)}")
    if _check_tiffs:
        print(f"    {len(_check_tiffs)} CHECK TIFFs, "
              f"{len(_check_frames)} flagged frames")
    else:
        print(f"    All {_n_good_tiffs} TIFFs GOOD")

print("\nDone.")
