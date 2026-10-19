"""
lyra.py — LYRA: Layered-echo Yield from Radiometric Archives
=============================================================

Algorithmic A-scope waveform extraction from raw TIFF film scans.
Named following the existing tool constellation convention:
  URSA (bear), ASTRA (stars), TERRA (earth), ARIES (ram), LYRA (lyre).

For each A-scope frame in a TIFF this module:
  1.  Detects frame boundaries (white inter-frame gaps)
  2.  Extracts the oscilloscope trace (darkest pixel per column)
  3.  Locates the main bang (origin of the time axis)
  4.  Estimates per-frame noise floor from pre-main-bang baseline
  5.  Finds surface and bed echo peaks via prominence-based detection
  6.  Walks leading / trailing edges at +5 dB and +10 dB above noise floor
  7.  Computes waveform shape metrics:
        peakiness        = peak_linear / mean_linear  (within +10 dB window)
        asymmetry        = trailing_width_10 / leading_width_10
        trailing_tail_us = trail_5 - trail_10  (subsurface scattering length)
        leading_rise_us  = peak_twt - lead_10  (onset steepness)
  8.  Returns a flat pandas DataFrame (one row per frame)

Grid calibration (validated vs Neal 1977 Fig 1.3a, CBD 0465, F125;
  corrected 2026-03-10: true sweep is 2.0 us/div, not 1.5):
  X-axis : 2.0 µs / major division  (205.54 px/major; 4 minor ticks -> 0.4 µs/minor)
  Y-axis : 10 dB  / major division  (205.0  px/major)
  Noise floor reference : y = 1507 px  -> -60 dB

WARNING: Do NOT use ASTRA surface_us / bed_us for geometry — those times are
         1.5× too large (ASTRA assumed 3.0 µs/major; correct value is 2.0 µs/major).
         Use only LYRA-derived travel times.

Physical interpretation of waveform metrics:
  High peakiness + low asymmetry + short trailing_tail  -> specular / liquid water
  Low peak power + long trailing_tail                   -> saline / frozen marine ice
  Broad symmetric echo, moderate peakiness              -> rough / incoherent bed
"""
from __future__ import annotations

import re
import os
import warnings
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image


# -- TIFF canonical naming utility ---------------------------------------------

_CANONICAL_RE = re.compile(r'^\d+_\d+_\d+-reel_begin_end\.tiff$', re.IGNORECASE)


def _parse_rename_log(log_path: Path) -> dict[str, str]:
    """Parse a LYRA rename log. Returns {current_name: canonical_name} mapping.

    The log format has blocks like:
        Old: 43_0008375_0008399-reel_begin_end.tiff   <- canonical (target)
        New: F141-C0038_C0047.tiff                    <- current (on-disk) name
    """
    mapping: dict[str, str] = {}
    old_name = new_name = None
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("Old: "):
            old_name = line[5:].strip()
        elif line.startswith("New: "):
            new_name = line[5:].strip()
            if old_name and new_name:
                mapping[new_name] = old_name
            old_name = new_name = None
    return mapping


def ensure_canonical_name(tiff_path: Path) -> Path:
    """Return the canonical-format path for a TIFF, renaming the file if needed.

    Canonical format: ``{reel}_{start}_{end}-reel_begin_end.tiff``
    (e.g. ``43_0008375_0008399-reel_begin_end.tiff``)

    If the file already matches that pattern, the original path is returned
    unchanged.  Otherwise the function searches for a ``*_rename_log*.txt``
    file in the same directory, parses it, renames the TIFF to its canonical
    name, and returns the new path.  An error is raised if the log is missing
    or the file is not listed in it.
    """
    if _CANONICAL_RE.match(tiff_path.name):
        return tiff_path  # already canonical — nothing to do

    log_files = sorted(tiff_path.parent.glob("*_rename_log*.txt"))
    if not log_files:
        raise FileNotFoundError(
            f"TIFF '{tiff_path.name}' is not in canonical format and no "
            f"'*_rename_log*.txt' was found in {tiff_path.parent}.\n"
            f"  Canonical format: {{reel}}_{{start}}_{{end}}-reel_begin_end.tiff"
        )

    mapping = _parse_rename_log(log_files[0])
    canonical = mapping.get(tiff_path.name)
    if canonical is None:
        raise KeyError(
            f"'{tiff_path.name}' not found in rename log '{log_files[0].name}'.\n"
            f"  Log covers: {sorted(mapping.keys())[:5]} …"
        )

    new_path = tiff_path.parent / canonical
    if new_path.exists():
        print(f"  [ensure_canonical_name] Already renamed: {new_path.name}")
        return new_path

    tiff_path.rename(new_path)
    print(f"  [ensure_canonical_name] Renamed:\n"
          f"      {tiff_path.name}\n"
          f"    -> {new_path.name}")
    return new_path


def tiff_id(tiff_path: Path) -> str:
    """Extract 4-digit TIFF start number from canonical filename.

    E.g. ``40_0008400_0008424-reel_begin_end.tiff`` -> ``"8400"``.
    """
    for part in tiff_path.stem.split("_"):
        if part.isdigit() and len(part) >= 5:
            return str(int(part[-8:]))[-4:]
    return tiff_path.stem[:8]  # fallback


def resolve_tiff_arg(arg: str, root: Path) -> Path:
    """Resolve a TIFF argument to a full path.

    Accepted formats (in order of preference):
      - ``FLT/TIFF_ID``:  ``125/8700``  (recommended shorthand)
      - Full or relative path:  ``tiff/125/40_0008700_0008724-...tiff``

    Returns the resolved absolute Path.  Raises SystemExit on no match.
    """
    # If it has a file extension -> treat as a literal path
    p = Path(arg)
    if p.suffix:
        return root / p if not p.is_absolute() else p

    # FLT/TIFF_ID shorthand: "125/8700" -> search in tiff/125/
    if "/" in arg:
        parts = arg.strip("/").split("/")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            flt_dir = root / "tiff" / parts[0]
            if not flt_dir.exists():
                flt_dir = root / "tiff"  # single-flight flat directory
            os.environ["LYRA_FLIGHT"] = parts[0]
            if not flt_dir.exists():
                raise SystemExit(
                    f"ERROR: Flight directory not found: {flt_dir}")
            padded = parts[1].zfill(7)
            matches = sorted(flt_dir.glob(f"*_{padded}_*-reel_begin_end.tiff"))
            if len(matches) == 1:
                return matches[0]
            if not matches:
                raise SystemExit(
                    f"ERROR: No TIFF matching ID '{parts[1]}' in F{parts[0]}.\n"
                    f"  Searched: {flt_dir}/")
            # Multiple matches (unlikely within one flight)
            raise SystemExit(
                f"ERROR: Multiple TIFFs match ID '{parts[1]}' in F{parts[0]}.")
        # Otherwise treat as a regular relative path
        return root / p if not p.is_absolute() else p

    # If it exists as a relative path from root -> use it
    if (root / p).exists():
        return root / p

    # Bare numeric ID without flight -> reject with helpful message
    if arg.isdigit():
        raise SystemExit(
            f"ERROR: Please use FLT/TIFF_ID format, e.g. 125/{arg}\n"
            f"  Usage: python codes/<script>.py 125/{arg}")

    raise SystemExit(
        f"ERROR: Cannot resolve TIFF '{arg}'.\n"
        f"  Usage: python codes/<script>.py FLT/TIFF_ID  (e.g. 125/8700)"
    )


# -- Pure-numpy replacements (no scipy dependency) -----------------------------

def _connected_components_1d(mask: np.ndarray) -> list[tuple[int, int]]:
    """Return (start, end) index pairs for each run of True in a boolean mask."""
    runs = []
    in_run = False
    start = 0
    for i, v in enumerate(mask.tolist()):
        if v and not in_run:
            start, in_run = i, True
        elif not v and in_run:
            runs.append((start, i - 1))
            in_run = False
    if in_run:
        runs.append((start, len(mask) - 1))
    return runs


def _find_peaks_numpy(arr: np.ndarray,
                      prominence: float = 0,
                      distance: int = 1) -> np.ndarray:
    """
    Find local minima in arr with minimum prominence and minimum distance.
    Equivalent (for our use case) to scipy.signal.find_peaks(-arr, ...).

    prominence : minimum depth of the minimum below surrounding neighbours
    distance   : minimum gap (pixels) between returned minima
    """
    n = len(arr)
    # Strict local minima
    candidates = [i for i in range(1, n - 1)
                  if arr[i] < arr[i - 1] and arr[i] < arr[i + 1]]
    if not candidates:
        return np.array([], dtype=int)
    candidates = np.array(candidates, dtype=int)

    # Distance filter: greedy — keep most prominent, suppress neighbours
    if distance > 1 and len(candidates) > 1:
        order = np.argsort(arr[candidates])   # most-prominent first
        kept: list[int] = []
        used: set[int] = set()
        for idx in order:
            p = int(candidates[idx])
            if p not in used:
                kept.append(p)
                for near in candidates:
                    if abs(int(near) - p) < distance:
                        used.add(int(near))
        candidates = np.array(sorted(kept), dtype=int)

    # Prominence filter
    if prominence > 0 and len(candidates) > 0:
        valid = []
        for p in candidates:
            d     = max(int(distance) * 3, 30)
            lo, hi = max(0, p - d), min(n - 1, p + d)
            lmax  = arr[lo:p].max()   if p   > lo else arr[p]
            rmax  = arr[p + 1:hi + 1].max() if hi > p else arr[p]
            if (min(lmax, rmax) - arr[p]) >= prominence:
                valid.append(p)
        candidates = np.array(valid, dtype=int)

    return candidates

# -- Physical constants ---------------------------------------------------------
C_AIR_M_PER_US = 300.0   # m / µs  (speed of light in air)
C_ICE_M_PER_US = 168.0   # m / µs  (Millar 1981; Neal 1977 uses 169)

# -- Default grid calibration ---------------------------------------------------
# Measured algorithmically from raw TIFFs; validated vs Neal 1977 Fig 1.3a.
_X_SPACING_PX = 205.54   # pixels per major X division (measured from TIFF)
_Y_SPACING_PX = 205.0    # pixels per major Y division (user confirmed)

DEFAULT_CAL: dict = dict(
    us_per_px     = 2.0 / _X_SPACING_PX,   # 0.009732 µs/px   <- corrected 2026-03-10
    db_per_px     = 10.0 / _Y_SPACING_PX,  # 0.048780 dB/px
    y_ref_px      = 1507,    # row of -60 dB reference line
    y_ref_db      = -60.0,   # dB at the reference row
    y_disp_lo     = 300,     # top of usable display band (row index; lower = higher on image)
    y_disp_hi     = 1700,    # bottom of usable display band
    mb_x_guess    = 800,     # expected main bang column (frame-relative; heuristic)
    gauss_sigma   = 3,       # trace-smoothing Gaussian sigma (pixels)
    consec        = 5,       # consecutive threshold crossings to confirm trailing edge
    peak_min_prom_dB = 5.0,  # minimum peak prominence above noise floor for detection (dB)
    peak_min_dist_px = 80,   # minimum inter-peak distance (pixels)
    mb_skip_us    = 2.0,     # skip this many µs after main bang before searching for echoes
    min_bed_gap_us = 1.5,    # minimum surface->bed TWT gap (µs); ~126 m minimum ice thickness
    max_walk_us   = 17.0,    # rightward envelope-walk limit (µs from MB); covers all RIS depths
    graticule_mask_half_px = 5,  # ±px to suppress around each major graticule line
    signal_binary_thresh  = 0.30, # normalized pixel threshold for dark-pixel binary mask.
                                  # CRT trace ~ 0.0–0.15; background ~ 0.55–0.65.
    signal_density_sigma  = 30,   # Gaussian sigma for smoothing per-column dark-pixel count.
    signal_density_thresh = 50,   # smoothed dark-pixel count threshold for signal detection.
                                  # Used as the CAP in the adaptive threshold formula:
                                  #   thresh = max(floor, min(cap, fraction × peak_density))
                                  # For bright frames (peak ~200): thresh = 50 (same as original).
                                  # For faint frames (peak ~40): thresh = 12 (floor).
    signal_density_floor  = 12,   # minimum adaptive threshold; above film-grain noise (~5-6 px/col).
    signal_density_frac   = 0.25, # fraction of peak column density used for adaptive threshold.
    signal_grat_half      = 8,    # ±px to exclude around graticule rows in signal detection
                                  # (wider than graticule_mask_half_px to avoid dark-line leakage).
    surface_window_us   = 8.0,   # surface search window end (µs from MB); covers altitude <=1200 m
    min_surface_lead_dB = 15.0,  # if strongest surface cand. > first by this, promote it
    quiet_gap_lead_us   = 1.0,   # µs after surface echo before checking for quiet gap
    quiet_gap_dB        = 12.0,  # trace must return within this many dB of NF in the gap
                                 # before a bed candidate is accepted.  Rejects surface-echo
                                 # trailing oscillations (which are continuous, never return
                                 # to NF); passes genuine thin-ice beds (surface echo decays
                                 # to NF within <=1 µs of the surface peak, then quiet gap).
                                 # Not applied when gap < 1 µs wide (very thin ice, <=84 m).
    min_bed_width_us    = 0.2,   # minimum bed echo width (µs) at NF + min_bed_width_dB.
                                 # Rejects very narrow film artifacts / spikes (< 0.15 µs).
                                 # Thin-ice bed echoes can be as narrow as 0.25 µs (F126);
                                 # thick-ice bed echoes >= 0.45 µs (F125 TIFF 7700 CBD0817).
    min_bed_width_dB    = 10.0,  # dB above NF used for the width measurement.
)


# -- Data classes ---------------------------------------------------------------

@dataclass
class EchoResult:
    """Waveform extraction result for one echo (surface or bed)."""
    # Peak location
    peak_x:        int   = 0      # column (frame-relative pixels)
    peak_y:        int   = 0      # row (pixels; lower = higher power)
    peak_twt_us:   float = np.nan # two-way travel time from main bang (µs)
    peak_power_dB: float = np.nan # power (dB, calibration reference frame)
    peak_snr_dB:   float = np.nan # SNR above measured noise floor (dB)

    # Envelope at +10 dB above noise floor
    lead_10_us:  float = np.nan   # leading edge TWT (µs from MB)
    trail_10_us: float = np.nan   # trailing edge TWT (µs from MB)
    width_10_us: float = np.nan   # width = trail_10 - lead_10

    # Envelope at +5 dB above noise floor (wider, captures subsurface tail)
    lead_5_us:   float = np.nan
    trail_5_us:  float = np.nan
    width_5_us:  float = np.nan

    # First-break onset: where signal first rises above NF + onset_db threshold
    # Use onset_twt_us for ice thickness (shortest travel path = nadir reflection)
    # Use peak_twt_us for reflectivity R0 (maximum returned power)
    onset_twt_us: float = np.nan     # TWT at first break (us from MB)
    onset_power_dB: float = np.nan   # power at onset point (dB)

    # Derived shape metrics (NF-referenced, legacy)
    leading_rise_us:  float = np.nan  # peak_twt - lead_10  (onset steepness; lower -> more specular)
    trailing_tail_us: float = np.nan  # trail_5 - trail_10  (subsurface scattering tail length)
    peakiness:        float = np.nan  # peak_linear / mean_linear within +10 dB window (>1 = peaked)
    asymmetry:        float = np.nan  # (peak_twt - lead_10) / (trail_10 - peak_twt) (>1 = trailing-heavy)

    # Peak-relative shape metrics (SNR-independent)
    # These measure echo decay rate relative to own peak, not noise floor.
    # Directly encode interface sharpness vs gradational structure.
    decay_10_us:    float = np.nan  # time from peak to peak-10 dB on trailing side
    decay_20_us:    float = np.nan  # time from peak to peak-20 dB on trailing side
    rise_10_us:     float = np.nan  # time from peak-10 dB to peak on leading side
    pk_asymmetry:   float = np.nan  # decay_10 / rise_10 (>1 = trailing-heavy)


@dataclass
class LyraFrame:
    """Complete LYRA result for one A-scope frame."""
    frame_idx:   int = 0
    frame_left:  int = 0   # left pixel column in original TIFF
    frame_right: int = 0   # right pixel column in original TIFF
    frame_w:     int = 0
    mb_x:        int = 0   # main bang column (frame-relative)
    noise_floor_dB: float = -60.0
    surface: EchoResult = field(default_factory=EchoResult)
    bed:     EchoResult = field(default_factory=EchoResult)
    surface_detected: bool = False
    bed_detected:     bool = False
    quality:          str  = "ok"  # "ok" | "no_surface" | "no_bed" | "failed"


# -- Unit conversions -----------------------------------------------------------

def px_to_db(y, cal: dict):
    """Row pixel -> power (dB). Lower y (higher on image) = higher power."""
    return cal["y_ref_db"] + (cal["y_ref_px"] - y) * cal["db_per_px"]


def db_to_px(db: float, cal: dict) -> float:
    """Power (dB) -> row pixel."""
    return cal["y_ref_px"] - (db - cal["y_ref_db"]) / cal["db_per_px"]


def px_to_us(x, mb_x: int, cal: dict):
    """Column pixel (frame-relative) -> TWT (µs from main bang)."""
    return (x - mb_x) * cal["us_per_px"]


def us_to_px(us: float, mb_x: int, cal: dict) -> int:
    """TWT (µs from main bang) -> column pixel (frame-relative)."""
    return int(round(mb_x + us / cal["us_per_px"]))


# -- Gaussian smoothing ---------------------------------------------------------

def _gauss_smooth(arr: np.ndarray, sigma: float) -> np.ndarray:
    r = int(4 * sigma + 0.5)
    x = np.arange(-r, r + 1, dtype=float)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    k /= k.sum()
    return np.convolve(arr.astype(float), k, mode="same")


def _running_median(arr: np.ndarray, window: int = 11) -> np.ndarray:
    """Running median filter (rejects sporadic outliers, preserves real echoes)."""
    out = arr.astype(float).copy()
    hw  = window // 2
    n   = len(arr)
    for i in range(hw, n - hw):
        out[i] = np.median(arr[i - hw : i + hw + 1])
    return out


# -- Frame boundary detection ---------------------------------------------------

def detect_frames(img_norm: np.ndarray,
                  band_frac: tuple = (0.20, 0.80),
                  smooth_sigma: float = 20,
                  gap_threshold: float = 0.90,
                  min_gap_px: int = 80,
                  min_frame_px: int = 200,
                  buffer_px: int = 5,
                  expected_frames: int = 14) -> list[tuple[int, int]]:
    """
    Detect A-scope frame boundaries from inter-frame white gaps.

    Ports the working approach from extract_noise_floor_ursa_frames.py:
      1. Compute column means in central band (20%–80% of height)
      2. Gaussian smooth
      3. Normalize to [0, 1]           <- CRITICAL: do NOT threshold raw values
      4. Threshold normalized at 0.90 -> gap mask
      5. Find gap CENTERS (mean col of each run >= min_gap_px wide)
      6. Frames = intervals between gap centers, with buffer_px inward

    Parameters
    ----------
    img_norm        : (H, W) float array, values in [0, 1]
    band_frac       : (lo, hi) fractional row range for gap analysis
    smooth_sigma    : Gaussian sigma for column-mean smoothing
    gap_threshold   : threshold on normalized [0,1] profile (default 0.90)
    min_gap_px      : minimum gap width (pixels) to count as a separator
    min_frame_px    : minimum frame width (pixels) to keep
    buffer_px       : pixels to trim inward from each gap center
    expected_frames : expected number of frames per TIFF (default 14 = 12 complete
                      + 2 partial); used both for the widest-gap filter (keeps at
                      most expected_frames-1 gaps) and fallback if too few gaps found

    Returns
    -------
    List of (left, right) frame boundary tuples, sorted left-to-right.
    """
    H, W = img_norm.shape
    y_lo = int(H * band_frac[0])
    y_hi = int(H * band_frac[1])

    col_mean   = img_norm[y_lo:y_hi, :].mean(axis=0)
    col_smooth = _gauss_smooth(col_mean, smooth_sigma)

    # Normalize to [0, 1] — this is the key step that makes thresholding work
    c_min, c_max = col_smooth.min(), col_smooth.max()
    if c_max > c_min:
        normalized = (col_smooth - c_min) / (c_max - c_min)
    else:
        normalized = np.zeros_like(col_smooth)

    gap_mask = normalized > gap_threshold

    # Find centers of sufficiently wide gap regions; track widths for filtering.
    # First merge nearby runs: the smoothing boundary effects can fragment a
    # single physical gap into 2-3 bright runs separated by a narrow dark dip.
    # Any two above-threshold runs separated by < min_frame_px are part of the
    # same inter-frame gap and should be merged.
    raw_runs = _connected_components_1d(gap_mask)
    merged_runs: list[tuple[int, int]] = []
    for s, e in raw_runs:
        if merged_runs and s - merged_runs[-1][1] < min_frame_px:
            merged_runs[-1] = (merged_runs[-1][0], e)
        else:
            merged_runs.append((s, e))

    gap_info: list[tuple[int, int]] = []   # (width_px, center_px)
    for s, e in merged_runs:
        w = e - s + 1
        if w >= min_gap_px:
            gap_info.append((w, int(round((s + e) / 2))))

    # Filter to true inter-frame gaps using bimodal width distribution.
    #
    # True inter-frame gaps (white film base between A-scopes) are always much
    # wider than any intra-frame feature (graticule lines, CRT edge artifacts,
    # partial-frame edges).  Sorting by width descending and looking for the
    # largest *relative* drop between adjacent entries reliably separates the two
    # populations — e.g. F141 TIFF 8525 shows a 91 % drop from the 12th true gap
    # (1024 px) to a reel-edge artifact (92 px) that would otherwise create a
    # spurious "partial" frame at the beginning.
    #
    # The bimodal cut is applied only when the drop is dramatic (> 50 %) and
    # enough gaps remain (>= 3) to form a sensible frame sequence.  After the
    # bimodal cut the hard cap max_gaps = expected_frames - 1 still applies as
    # a safety upper bound, so the old behaviour is preserved for TIFFs where
    # gap widths are all similar (no dramatic drop).
    gap_info.sort(key=lambda t: -t[0])   # widest first
    gap_info_all = list(gap_info)  # preserve pre-cut list for validation
    if len(gap_info) > 1:
        best_cut   = len(gap_info)
        best_ratio = 0.0
        for i in range(1, len(gap_info)):
            ratio = 1.0 - gap_info[i][0] / gap_info[i - 1][0]
            if ratio > best_ratio:
                best_ratio = ratio
                best_cut   = i
        if best_ratio > 0.50 and best_cut >= 3:
            # Validate: only apply bimodal cut if the discarded gaps are truly
            # tiny relative to the kept ones.  If the largest discarded gap is
            # > 20% of the smallest kept gap, both populations are real features
            # and the bimodal model is wrong (e.g. faint-trace TIFFs where
            # dim frames are nearly as bright as inter-frame borders).
            min_kept    = gap_info[best_cut - 1][0]
            max_discard = gap_info[best_cut][0]
            if max_discard < 0.20 * min_kept:
                print(f"  [detect_frames] bimodal gap cut: keeping {best_cut} wide gaps "
                      f"(drop {best_ratio:.0%} at rank {best_cut}: "
                      f"{gap_info[best_cut-1][0]}->{gap_info[best_cut][0]} px)")
                gap_info = gap_info[:best_cut]
            else:
                print(f"  [detect_frames] bimodal cut skipped: discarded gaps too large "
                      f"({max_discard} px >= 20% of {min_kept} px)")

    max_gaps = expected_frames - 1
    if len(gap_info) > max_gaps:
        gap_info = gap_info[:max_gaps]

    gap_centers = sorted([c for _, c in gap_info])

    # Fallback: if too few gaps, estimate from expected frame count
    if len(gap_centers) < min(3, expected_frames - 1):
        est_w = W / expected_frames if expected_frames > 0 else W
        gap_centers = [int((i + 0.5) * est_w) for i in range(expected_frames - 1)]

    # -- Spacing-guided gap prediction -----------------------------------------
    # When the film has uneven exposure (e.g. bright first half, dim second half),
    # global normalization fails to detect gaps in the dim section.  Use the
    # regular frame spacing from the detected gaps to predict where missing gaps
    # should be, then confirm each prediction against a local brightness peak.
    #
    # Physical basis: the 35 mm camera advance is mechanical and regular, so
    # inter-frame gaps have approximately constant spacing across the TIFF.
    min_needed = expected_frames - 1
    # Only trigger when >30% of expected gaps are missing (avoids interfering
    # with TIFFs that just have 1-2 missed gaps handled by the oversized splitter)
    if len(gap_centers) >= 3 and len(gap_centers) < 0.7 * min_needed:
        # Compute median spacing from consecutive detected gaps
        spacings = [gap_centers[i+1] - gap_centers[i]
                    for i in range(len(gap_centers) - 1)]
        med_spacing = float(np.median(spacings))

        # Build predicted gap positions: fill oversized intervals between
        # consecutive gaps, then extend from the endpoints
        predicted = set()
        # Fill within oversized intervals between consecutive detected gaps
        all_edges = [0] + gap_centers + [W]
        for i in range(len(all_edges) - 1):
            interval = all_edges[i + 1] - all_edges[i]
            if interval > 1.5 * med_spacing:
                n_gaps = int(round(interval / med_spacing)) - 1
                if n_gaps >= 1:
                    step = interval / (n_gaps + 1)
                    for j in range(1, n_gaps + 1):
                        p = int(round(all_edges[i] + j * step))
                        if min_frame_px < p < W - min_frame_px:
                            predicted.add(p)

        # Remove predictions close to existing gap centers
        tol = med_spacing * 0.25
        predicted = {p for p in predicted
                     if all(abs(p - g) > tol for g in gap_centers)}

        # Confirm each prediction: find the local brightness maximum within
        # +/- tol of the predicted position; accept if it's a local peak
        added = []
        for pred in sorted(predicted):
            search_lo = max(0, int(pred - tol))
            search_hi = min(W - 1, int(pred + tol))
            if search_hi <= search_lo:
                continue
            local = col_smooth[search_lo:search_hi + 1]
            peak_offset = int(np.argmax(local))
            peak_col = search_lo + peak_offset
            peak_val = col_smooth[peak_col]
            # Accept if the peak stands out from the surrounding frame content:
            # check that it's above the local mean in a wider neighborhood
            neigh_lo = max(0, peak_col - int(med_spacing * 0.5))
            neigh_hi = min(W - 1, peak_col + int(med_spacing * 0.5))
            neigh_mean = col_smooth[neigh_lo:neigh_hi + 1].mean()
            if peak_val > neigh_mean:
                added.append(peak_col)

        if added:
            gap_centers = sorted(gap_centers + added)
            # Re-apply the max_gaps cap
            if len(gap_centers) > max_gaps:
                # Keep the ones closest to expected regular spacing
                gap_centers = gap_centers[:max_gaps]
            print(f"  [detect_frames] spacing-guided prediction: added {len(added)} "
                  f"gaps (median spacing={med_spacing:.0f} px, "
                  f"total gaps now={len(gap_centers)})")

    # Build frames as intervals between gap centers
    frame_edges = [0] + gap_centers + [W]
    frames = []
    for i in range(len(frame_edges) - 1):
        left  = int(frame_edges[i])  + (buffer_px if i > 0 else 0)
        right = int(frame_edges[i + 1]) - (buffer_px if i < len(frame_edges) - 2 else 0)
        if right - left > min_frame_px:
            frames.append((max(0, left), min(W - 1, right)))

    # -- Post-process: split remaining oversized frames ----------------------------
    # After spacing-guided prediction, individual frames may still be oversized
    # (e.g. one missed gap in an otherwise well-detected TIFF).  Find the
    # brightest column in the middle region and split there.
    if len(frames) >= 2:
        changed = True
        while changed:
            changed = False
            widths = [r - l for l, r in frames]
            med_w  = float(np.median(widths))
            new_frames = []
            for l, r in frames:
                if (r - l) > 1.5 * med_w and (r - l) > min_frame_px * 2:
                    sub_l    = l + int(0.20 * (r - l))
                    sub_r    = l + int(0.80 * (r - l))
                    sub_peak = sub_l + int(np.argmax(col_smooth[sub_l:sub_r]))
                    left_end  = max(l,     sub_peak - buffer_px - 1)
                    right_beg = min(W - 1, sub_peak + buffer_px + 1)
                    if (left_end - l > min_frame_px
                            and r - right_beg > min_frame_px):
                        new_frames.append((l, left_end))
                        new_frames.append((right_beg, r))
                        print(f"  [detect_frames] oversized frame {l}-{r} "
                              f"(w={r-l}) split at col {sub_peak}")
                        changed = True
                    else:
                        new_frames.append((l, r))
                else:
                    new_frames.append((l, r))
            frames = sorted(new_frames)

    # -- Post-process: discard empty-gap frames (no CRT signal) --------------------
    # Some TIFFs have extra-wide inter-frame gaps (4000+ px) that survive gap
    # detection and get treated as oversized frames, then split.  The resulting
    # "frames" are just bright film base with no dark CRT trace.  Detect these
    # by measuring column-brightness contrast in the CRT display region: real
    # frames have high std (bright background + dark trace), empty gaps have low.
    if len(frames) >= 3:
        crt_lo = int(H * 0.20)
        crt_hi = int(H * 0.80)
        crt_band = img_norm[crt_lo:crt_hi, :]
        contrasts = []
        for l, r in frames:
            col_means = crt_band[:, l:r+1].mean(axis=0)
            contrasts.append(float(col_means.std()))
        med_contrast = float(np.median(contrasts))
        # Keep frames with contrast > 15% of median (generous threshold to
        # retain faint CRT traces while rejecting truly empty gaps)
        if med_contrast > 0:
            valid = [(f, c) for f, c in zip(frames, contrasts)
                     if c > 0.15 * med_contrast]
            n_removed = len(frames) - len(valid)
            if n_removed > 0:
                print(f"  [detect_frames] removed {n_removed} empty-gap "
                      f"frame(s) (no CRT signal, contrast < 15% of median "
                      f"{med_contrast:.4f})")
                frames = [f for f, _ in valid]

    return frames


# -- Signal extent detection ----------------------------------------------------

def detect_signal_extent(frame: np.ndarray,
                         cal: dict) -> tuple[int, int]:
    """
    Detect the horizontal extent of the CRT A-scope signal within a frame.

    The CRT beam sweeps left-to-right, creating a continuous dark trace on the
    phosphor screen.  Outside the sweep, only film grain exists — no distinct
    dark line.  This function finds the first and last columns where the CRT
    trace is present.

    Algorithm
    ---------
    1. Binary threshold on the globally-normalised frame (< signal_binary_thresh)
       to isolate dark pixels (CRT trace + some film grain).
    2. Exclude graticule rows (±signal_grat_half px around each 10-dB major
       grid line) so that horizontal grid lines do not inflate the count.
    3. Sum the dark-pixel count per column and smooth with a Gaussian (sigma = signal_density_sigma).
    4. Adaptive threshold: max(floor, min(cap, fraction × peak_density)).
       Bright frames (peak ~200) -> cap = 50 (same as original fixed threshold).
       Faint frames (peak ~40) -> floor = 12 (above film-grain noise ~5-6 px/col).
    5. Signal columns are those where the smoothed count >= adaptive threshold.
    6. Return the first and last such column.

    Parameters
    ----------
    frame : (H, W) float array, globally normalised [0, 1]
        The full-height frame (not the y_disp_lo:y_disp_hi band).
    cal   : calibration dict (must include y_ref_px, db_per_px, y_disp_lo, y_disp_hi).

    Returns
    -------
    (sig_start, sig_end) : column indices (frame-relative, inclusive).
        If detection fails, returns (0, W-1) as a safe fallback.
    """
    y_lo = cal["y_disp_lo"]
    y_hi = min(cal["y_disp_hi"], frame.shape[0])
    band = frame[y_lo:y_hi, :]
    bH, W = band.shape

    # -- Binary: dark pixels below threshold ----------------------------------
    binary_thresh = cal.get("signal_binary_thresh", 0.30)
    binary = (band < binary_thresh).astype(np.uint8)

    # -- Exclude graticule rows -----------------------------------------------
    grat_half = cal.get("signal_grat_half", 8)
    y_sp_px   = 10.0 / cal["db_per_px"]
    n_lo = int(np.floor((y_lo - cal["y_ref_px"]) / y_sp_px)) - 1
    n_hi = int(np.ceil ((y_hi - cal["y_ref_px"]) / y_sp_px)) + 1
    for _n in range(n_lo, n_hi + 1):
        gl_abs = cal["y_ref_px"] + _n * y_sp_px
        gl_rel = int(round(gl_abs - y_lo))
        if 0 <= gl_rel < bH:
            r0 = max(0, gl_rel - grat_half)
            r1 = min(bH, gl_rel + grat_half + 1)
            binary[r0:r1, :] = 0

    # -- Per-column dark-pixel count, smoothed --------------------------------
    col_count  = binary.sum(axis=0).astype(float)
    sigma      = cal.get("signal_density_sigma", 30)
    col_smooth = _gauss_smooth(col_count, sigma)

    # -- Adaptive threshold -------------------------------------------------
    # Fixed threshold (50) works for bright frames but excludes real echo
    # columns in faint CRT traces (e.g. F127 CBD0440: mean 18.5 dark px/col).
    # Adaptive formula: max(floor, min(cap, fraction × peak_density)).
    # For bright frames (peak ~200): cap=50 reached -> identical to original.
    # For faint frames (peak ~40): floor=12 reached -> catches real signal.
    # Film grain noise ~ 5-6 dark px/col; floor=12 stays safely above this.
    cap      = cal.get("signal_density_thresh", 50)
    floor    = cal.get("signal_density_floor",  12)
    fraction = cal.get("signal_density_frac",   0.25)
    peak_density   = float(np.max(col_smooth)) if len(col_smooth) > 0 else 0.0
    density_thresh = max(floor, min(cap, fraction * peak_density))

    # -- Signal extent: first/last column above threshold ---------------------
    above = col_smooth >= density_thresh
    signal_cols = np.where(above)[0]

    if len(signal_cols) == 0:
        # Fallback: no signal detected -> treat entire frame as signal
        return 0, W - 1

    sig_start, sig_end = int(signal_cols[0]), int(signal_cols[-1])

    # -- Local-normalization fallback for faint CRT traces ---------------------
    # A normal CRT sweep spans ~2000+ px.  If the standard thresholding finds
    # a suspiciously narrow extent (< 500 px), the CRT trace is likely too faint
    # for the global normalisation to resolve.  Re-try with per-band local
    # normalisation, which stretches contrast so that even faint traces cross
    # the binary threshold.  This path is never reached for flights with strong
    # CRT traces (F125, F127) because their initial extent is already wide.
    if sig_end - sig_start < 500:
        b_min, b_max = float(band.min()), float(band.max())
        if b_max - b_min > 1e-9:
            band_local = (band - b_min) / (b_max - b_min)
            binary2 = (band_local < binary_thresh).astype(np.uint8)
            # Re-apply graticule exclusion
            for _n in range(n_lo, n_hi + 1):
                gl_abs = cal["y_ref_px"] + _n * y_sp_px
                gl_rel = int(round(gl_abs - y_lo))
                if 0 <= gl_rel < bH:
                    r0 = max(0, gl_rel - grat_half)
                    r1 = min(bH, gl_rel + grat_half + 1)
                    binary2[r0:r1, :] = 0
            col_count2  = binary2.sum(axis=0).astype(float)
            col_smooth2 = _gauss_smooth(col_count2, sigma)
            peak2       = float(np.max(col_smooth2)) if len(col_smooth2) > 0 else 0.0
            thresh2     = max(floor, min(cap, fraction * peak2))
            signal_cols2 = np.where(col_smooth2 >= thresh2)[0]
            if len(signal_cols2) > 0:
                s2, e2 = int(signal_cols2[0]), int(signal_cols2[-1])
                if e2 - s2 > sig_end - sig_start:
                    sig_start, sig_end = s2, e2

    return sig_start, sig_end


# -- Trace extraction -----------------------------------------------------------

def extract_trace(frame: np.ndarray,
                  cal: dict,
                  robust: bool = False,
                  mb_x: int | None = None) -> tuple[np.ndarray, np.ndarray, dict]:
    """
    Extract oscilloscope trace from one A-scope frame.

    Finds the darkest (minimum intensity) pixel per column within the
    oscilloscope display band, then applies Gaussian smoothing.

    The A-scope trace appears as a dark line on a lighter background in the
    scanned TIFF (CRT phosphor -> film -> scan inversion).

    Parameters
    ----------
    robust : bool
        If True, use a constrained-argmin approach that rejects film-grain
        artefacts and T/R ringing noise.  Requires mb_x.

        Algorithm
        ---------
        1. Compute unconstrained argmin per column.
        2. Pre-filter: replace the T/R ringing region
           [0, mb_x + mb_skip_px] and frame edges (±20 px) with the noise
           floor row so the coarse trajectory is not biased by ringing.
        3. Apply a coarse Gaussian smooth (sigma=30) to the pre-filtered trace
           to obtain a stable "expected" row position for every column.
        4. Constrained argmin: at each column, restrict the search band to
           [coarse - 250, coarse + 250].  Wide enough for deep-ice bed
           echoes (~500 px above NF) while rejecting gross outliers.
        5. Running median (window=11) on the constrained trace to reject
           sporadic film artifacts (1–5 columns of dark pixels at y=500–800
           that produce phantom dips ~30 dB above NF in the post-echo
           region).  Real echoes span hundreds of columns and are preserved.
        6. Apply fine Gaussian smooth (sigma=5) to the median-filtered result
           -> trace_y_s used for envelope walking.

        Why it works: film grain creates isolated 1–3 px dark hits; real
        echoes are 50–500 px wide.  The coarse smooth (sigma=30) is largely
        unaffected by sparse grain hits (their total weight << 1) but
        accurately tracks the broad echo envelope.  The ±250 px search
        window is wide enough to capture both shallow and deep-ice echoes.
        The median filter then rejects any remaining sporadic artifacts
        without narrowing the search window (which would miss deep-ice
        bed echoes, as observed in F125 TIFF 8300).

    mb_x : int | None
        Main-bang column (frame-relative).  Required in robust mode.

    Returns
    -------
    trace_y   : (W,) row positions (pixels; lower = higher power)
    trace_y_s : (W,) Gaussian-smoothed row positions
    """
    H, W   = frame.shape
    y_lo   = cal["y_disp_lo"]
    y_hi   = min(cal["y_disp_hi"], H)
    band   = frame[y_lo:y_hi, :]
    bH     = band.shape[0]

    # -- Graticule masking ------------------------------------------------------
    # Major graticule lines (10 dB horizontal rules) are printed with dense ink
    # and appear DARKER than the CRT echo trace in the globally-normalised TIFF.
    # Without masking, argmin picks a graticule line instead of the signal peak,
    # producing a systematic ~200 px (~10 dB) power underestimation.
    #
    # Fix: set ±graticule_mask_half_px around every known major grid row to 1.0
    # (white -> never selected by argmin).  Grid positions are computed exactly
    # from step-2 calibration (y_ref_px, db_per_px); the formula is
    # flight-independent and adapts to F125 / F127 / F141 automatically.
    mask_half = cal.get("graticule_mask_half_px", 3)
    y_sp_px   = 10.0 / cal["db_per_px"]          # px per 10 dB major division
    band_gm   = band.astype(float).copy()         # graticule-masked band
    n_lo_g = int(np.floor((y_lo - cal["y_ref_px"]) / y_sp_px)) - 1
    n_hi_g = int(np.ceil( (y_hi - cal["y_ref_px"]) / y_sp_px)) + 1
    for _n in range(n_lo_g, n_hi_g + 1):
        gl_abs = cal["y_ref_px"] + _n * y_sp_px   # absolute image row
        gl_rel = int(round(gl_abs - y_lo))          # band-relative row
        if 0 <= gl_rel < bH:
            r0 = max(0, gl_rel - mask_half)
            r1 = min(bH, gl_rel + mask_half + 1)
            band_gm[r0:r1, :] = 1.0               # white -> never picked by argmin

    if robust and mb_x is not None:
        # -- Robust trace extraction — signal-extent–based masking ------------
        #
        # Root cause of spurious peaks: outside the CRT sweep region (before
        # signal start, after signal end), direct argmin picks random dark
        # film-grain pixels, producing a wiggly trace with local minima
        # misidentified as echoes.
        #
        # Fix: detect_signal_extent() finds the horizontal range where the CRT
        # trace is actually present (per-column dark-pixel density above
        # threshold).  Outside that range, force trace_y to the NF reference
        # row.  Inside, use graticule-masked argmin.
        #
        # Pre-MB columns (0..mb_x) within the signal region are kept with raw
        # argmin (no graticule masking) — this feeds estimate_noise_floor().
        sig_start, sig_end = detect_signal_extent(frame, cal)

        mb_skip_px = max(1, int(cal.get("mb_skip_us", 2.0) / cal["us_per_px"]))
        tr_end     = min(W, mb_x + mb_skip_px)

        # -- Pass 1: unconstrained argmin -------------------------------------
        trace_raw = np.argmin(band,    axis=0).astype(float) + y_lo  # no grat mask
        trace_gm  = np.argmin(band_gm, axis=0).astype(float) + y_lo  # grat masked

        nf_row = float(cal["y_ref_px"])

        # Assemble pass-1 trace: NF outside signal, argmin inside
        trace_pass1 = np.full(W, nf_row)
        trace_pass1[sig_start:sig_end+1] = trace_gm[sig_start:sig_end+1]
        # Pre-MB within signal: raw argmin (for NF estimation)
        pre_mb_start = max(sig_start, 0)
        pre_mb_end   = min(mb_x, sig_end + 1)
        if pre_mb_start < pre_mb_end:
            trace_pass1[pre_mb_start:pre_mb_end] = trace_raw[pre_mb_start:pre_mb_end]
        # T/R ringing zone -> NF
        trace_pass1[mb_x:tr_end] = nf_row

        # -- Constrained argmin (±250 px from coarse guide) -----------------
        # Two-pass strategy:
        #
        # Pass A: NF-clamped guide (trace_pass1).  Works for F125-type signals
        #   where echoes start near NF — the ±250 px window follows signal.
        #
        # Pass B (fallback): trace_gm guide.  Activated when Pass A leaves
        #   >80% of the echo region stuck at NF.  This handles F128-type
        #   multi-pulse frames where the signal starts 500-1000 px above NF
        #   immediately after T/R — outside the ±250 px window from NF.
        max_jump = 250

        def _run_constrained(guide_trace):
            """Constrained argmin over [sig_start, sig_end] using guide."""
            _ty = trace_pass1.copy()
            _coarse = _running_median(guide_trace, window=61)
            for col in range(sig_start, sig_end + 1):
                expected_row = _coarse[col] - y_lo
                lo_row = max(0,  int(expected_row - max_jump))
                hi_row = min(bH, int(expected_row + max_jump))
                if lo_row < hi_row:
                    best_row = lo_row + np.argmin(band_gm[lo_row:hi_row, col])
                    _ty[col] = best_row + y_lo
            if pre_mb_start < pre_mb_end:
                _ty[pre_mb_start:pre_mb_end] = trace_raw[pre_mb_start:pre_mb_end]
            _ty[mb_x:tr_end] = nf_row
            return _ty

        # Pass A: NF-clamped guide
        trace_y = _run_constrained(trace_pass1)

        # Check if echo region is stuck at NF — trigger Pass B if so
        _echo_lo = max(sig_start, tr_end)
        _echo_hi = min(sig_end, W - 1)
        if _echo_hi > _echo_lo + 30:
            _echo_trace = trace_y[_echo_lo:_echo_hi + 1]
            _stuck_frac = float(np.mean(np.abs(_echo_trace - nf_row) < 50))
            if _stuck_frac > 0.40:
                trace_y = _run_constrained(trace_gm)

        # -- Median filter + fine smooth for envelope walking -----------------
        # The constrained trace may have sporadic film artifacts (1–5 columns
        # where dark pixels at y=500–800 land within the ±250 band, producing
        # phantom dips ~30 dB above NF).  These artifacts don't affect peak
        # power reading (trace_y = trace_pass1 below), but they contaminate
        # the smooth trace used for envelope walking — a single phantom dip
        # resets the consecutive-below-NF count, extending the trailing edge.
        #
        # Running median (window=11) rejects artifacts spanning <=5 columns
        # while preserving real echoes (span hundreds of columns).
        trace_constrained = trace_y.copy()
        trace_mf = _running_median(trace_constrained, window=11)
        trace_y_s = _gauss_smooth(trace_mf, sigma=5.0)

        # -- Artifact detection data ----------------------------------------
        # Store per-column difference (in pixels) between the constrained
        # trace and the median-filtered trace.  Positive values indicate
        # that the median filter removed a downward artifact (constrained
        # trace was pulled below the median by a film artifact).
        # The per-column data is passed to step3, which checks for artifacts
        # specifically in the post-bed region (artifacts elsewhere are
        # benign for bed envelope estimation).
        art_diff_px = trace_mf - trace_constrained  # positive = artifact removed
        trace_info = dict(
            art_diff_px   = art_diff_px,   # full per-column array
            mb_x          = mb_x,
            db_per_px     = cal["db_per_px"],
            us_per_px     = cal["us_per_px"],
        )

        # Return the UNCONSTRAINED pass-1 trace as trace_y for peak power
        # reading.  The unconstrained argmin correctly tracks the CRT trace
        # at echo peaks; grain contamination in flat regions does not matter
        # because peak power is only read at detected peak columns.
        trace_y = trace_pass1

    else:
        trace_y   = np.argmin(band_gm, axis=0).astype(float) + y_lo
        trace_y_s = _gauss_smooth(trace_y, cal["gauss_sigma"])
        trace_info = dict(art_diff_px=None)

    return trace_y.astype(int), trace_y_s, trace_info


# -- Main bang detection --------------------------------------------------------

def detect_mb(trace_y_s: np.ndarray, cal: dict,
              search_frac: float = 0.25,
              guide_x: int | None = None,
              frame: np.ndarray | None = None) -> int:
    """
    Locate the main bang (transmitter pulse) — leftmost maximum power column.

    Five-tier detection strategy:

    1. GUIDED (guide_x from per-frame user pick):
       Narrow search window [guide_x-100, guide_x+50].  Baseline sampled from
       200 px BEFORE the window.  Finds the first 5-column sustained crossing
       20 dB above baseline, then the first local minimum >=15 dB below baseline.

    2. GUIDE POSITION CHECK (guide_x +/-20 px):
       For stable-MB flights, verifies guide_x sits near strong signal.

    3. FIRST-DIP (trace-based, pre-bang check):
       Scans left-to-right for the first sustained dip (>=10 columns below
       noise-10 dB) whose pre-bang region (80 px before) is clean (at most
       15% of columns below noise-8 dB).  The MB is the leading edge
       (run_start) of this dip.  Rejects frame-edge artifacts (x < 50) and
       secondary radar pulses (whose pre-bang overlaps echo signal).

    4. BROAD FALLBACK (legacy):
       Global argmin in left half of the frame.

    5. LAST RESORT: guide_x or mb_x_guess (800 px).

    Parameters
    ----------
    trace_y_s   : smoothed trace Y positions (from extract_trace)
    cal         : calibration dict (uses db_per_px, y_ref_db, mb_x_guess)
    search_frac : unused; kept for API compatibility
    guide_x     : approximate main bang column from user picks (optional)
    frame       : normalised frame image (optional; enables image-aware Tier 3)

    Returns
    -------
    mb_x : column index (frame-relative)
    """
    W         = len(trace_y_s)
    db_per_px = max(cal.get("db_per_px", 0.049), 1e-6)
    mb_x: int | None = None
    _tier3_found = False   # Tier 3 validates with its own trace; skip sanity

    # -- TIER 1: GUIDED PATH (narrow window around user click) -------------
    if guide_x is not None:
        lo = max(30, guide_x - 100)
        hi = min(W,  guide_x + 50)
        if hi > lo:
            # Baseline from 200 px BEFORE window — avoids leading-edge corruption
            bl_start = max(30, lo - 200)
            bl_end   = max(bl_start + 10, lo)
            baseline = float(np.percentile(trace_y_s[bl_start:bl_end], 75))

            region   = trace_y_s[lo:hi]
            thresh_y = baseline - 20.0 / db_per_px

            _run = 0
            crossing = None
            for _i, _y in enumerate(region.tolist()):
                if _y < thresh_y:
                    _run += 1
                    if _run >= 5:
                        crossing = _i - 4   # start of sustained run
                        break
                else:
                    _run = 0

            if crossing is not None:
                # Collect ALL qualifying local minima in the search window,
                # then pick the one closest to guide_x.  This prevents
                # pre-main-bang artifacts from being selected over the real
                # MB when both are within the Tier 1 window.
                # (e.g. CBD 0457: artifact at x=757 vs real MB at x=812;
                #  guide_x=810; closest-to-guide correctly picks x=812.)
                min_depth = 15.0 / db_per_px
                sub = region[crossing : min(len(region), crossing + 300)]
                candidates = []  # list of (abs_x, depth_px)
                for i in range(1, len(sub) - 1):
                    if sub[i] < sub[i - 1] and sub[i] < sub[i + 1]:
                        if (baseline - sub[i]) >= min_depth:
                            candidates.append(lo + crossing + i)
                if candidates:
                    mb_x = min(candidates, key=lambda c: abs(c - guide_x))

    # -- Fallback tiers (when guided narrow-window found nothing) ---------
    # Noise floor reference for all fallback tiers
    global_noise_y = float(np.percentile(trace_y_s, 75))
    min_depth_px   = 10.0 / db_per_px

    # -- TIER 2: GUIDE POSITION CHECK -------------------------------------
    # When the guided narrow-window algorithm fails but guide_x exists,
    # check whether guide_x itself sits near a strong signal.  This handles
    # flights with STABLE MB positions (F125 ~800, F141 ~540) where
    # tiff_mb_estimate is correct but the narrow-window algorithm couldn't
    # find a clean crossing (e.g. noisy trace, edge effects).
    # We search ±20 px around guide_x for the local minimum and verify
    # it's >=10 dB above noise.  This avoids falling through to the broad
    # search, which can latch onto pre-trigger artifacts (observed in F141:
    # artifact at ~150 px, -17.8 dB, stronger than the real MB at ~540 px).
    if mb_x is None and guide_x is not None:
        check_lo  = max(0, guide_x - 20)
        check_hi  = min(W, guide_x + 20)
        local_min = float(np.min(trace_y_s[check_lo:check_hi]))
        if (global_noise_y - local_min) >= min_depth_px:
            mb_x = check_lo + int(np.argmin(trace_y_s[check_lo:check_hi]))

    # -- TIER 3: FIRST-DIP (pre-bang check) ---------------------------------
    # Compute an INDEPENDENT unconstrained trace from the raw frame image
    # (argmin per column in the display band, lightly smoothed).  This is
    # critical because extract_trace()'s constrained two-pass method can
    # miss faint CRT signals (observed on F128 where the trace stays at
    # noise floor even at the real MB position).
    #
    # Scan left-to-right for the first SUSTAINED dip whose preceding region
    # is clean (noise floor).  Frame-edge artifacts and secondary radar
    # pulses fail the pre-bang check because their preceding region contains
    # strong signal or frame-separator noise.
    #
    # Validated on F125, F127, F128: 94%+ correct within 20 px of user
    # picks across 229 test frames.
    if mb_x is None and frame is not None:
        _disp_lo = int(cal.get("y_disp_lo", 300))
        _disp_hi = int(cal.get("y_disp_hi", 1700))
        _H_frame = frame.shape[0]
        _disp_hi = min(_disp_hi, _H_frame)
        # Unconstrained argmin per column (independent of extract_trace)
        _raw_trace = (np.argmin(frame[_disp_lo:_disp_hi, :], axis=0)
                      .astype(float) + _disp_lo)
        _light_smooth = _gauss_smooth(_raw_trace, sigma=5)

        _skip = 50
        _min_run = 10       # sustained dip = 10+ consecutive columns
        _noise_y = float(np.percentile(
            _light_smooth[_skip : max(_skip + 1, W - 50)], 90))
        _dip_thresh = _noise_y - 10.0 / db_per_px      # must dip >= 10 dB
        _pre_check  = _noise_y - 8.0 / db_per_px       # pre-bang ceiling
        _pre_len    = 80                                # pre-bang window size
        _pre_pct    = 0.15                              # max 15% below ceiling

        _run_start: int | None = None
        for _x in range(_skip, W - 50):
            if _light_smooth[_x] < _dip_thresh:
                if _run_start is None:
                    _run_start = _x
                if _x - _run_start + 1 >= _min_run:
                    # Check pre-bang cleanliness
                    _pb_lo = max(_skip, _run_start - _pre_len)
                    _pb_hi = _run_start
                    if _pb_hi - _pb_lo < 30:
                        _run_start = None
                        continue
                    _pre_bang = _light_smooth[_pb_lo:_pb_hi]
                    _n_below = int(np.sum(_pre_bang < _pre_check))
                    if _n_below <= _pre_pct * len(_pre_bang):
                        mb_x = _run_start     # leading edge of the dip
                        _tier3_found = True
                        break
                    else:
                        _run_start = None      # contaminated pre-bang
            else:
                _run_start = None

    # -- TIER 4: BROAD FALLBACK (legacy global argmin) ----------------------
    if mb_x is None:
        broad_smooth = _gauss_smooth(trace_y_s.astype(float), sigma=20)
        search_lo = 50
        search_hi = max(search_lo + 1, W // 2)
        candidate = search_lo + int(np.argmin(broad_smooth[search_lo:search_hi]))
        if (global_noise_y - broad_smooth[candidate]) >= min_depth_px:
            mb_x = candidate

    # -- TIER 5: LAST RESORT -----------------------------------------------
    if mb_x is None:
        mb_x = guide_x if guide_x is not None else cal.get("mb_x_guess", 800)

    # Sanity: main bang must be well above the noise-floor reference.
    # Threshold relaxed from 15 dB to 10 dB to accommodate weaker frames
    # (e.g. F127 CBD0421 at -45.9 dB = 14.1 dB above noise floor).
    # Skip when Tier 3 found the MB: it uses its own independent trace for
    # validation (the constrained trace_y_s can be at noise floor at the
    # real MB position when the CRT signal is faint, as on F128).
    if not _tier3_found:
        mb_power = float(px_to_db(float(trace_y_s[mb_x]), cal))
        if mb_power < cal["y_ref_db"] + 10:
            mb_x = guide_x if guide_x is not None else cal.get("mb_x_guess", 800)

    return mb_x


# -- Noise floor estimation -----------------------------------------------------

def estimate_noise_floor(trace_y_s: np.ndarray,
                         mb_x: int,
                         cal: dict) -> float:
    """
    Estimate per-frame noise floor from the pre-main-bang baseline.

    The region before the main bang contains no real signal, so the
    trace sits at the system noise floor level.

    Returns
    -------
    noise_floor_dB : estimated noise floor in dB
    """
    pre_mb = trace_y_s[:max(1, mb_x - 30)]
    if len(pre_mb) >= 10:
        # Median of the highest-Y (lowest-power) portion -> noise baseline
        p75 = float(np.percentile(pre_mb, 75))
        baseline_px = float(np.median(pre_mb[pre_mb >= p75]))
        return float(px_to_db(baseline_px, cal))
    return float(cal["y_ref_db"])


# -- Echo peak detection --------------------------------------------------------

def detect_echoes(trace_y_s: np.ndarray,
                  mb_x: int,
                  noise_floor_dB: float,
                  cal: dict) -> tuple[int | None, int | None]:
    """
    Detect surface and bed echo peak columns.

    Surface: first prominent peak after main bang decay.
    Bed:     second prominent peak, at least 0.3 µs after surface.

    Returns
    -------
    surface_x : frame-relative column of surface peak, or None
    bed_x     : frame-relative column of bed peak, or None
    """
    W = len(trace_y_s)

    # Skip main bang + its decay
    x_start = mb_x + int(cal["mb_skip_us"] / cal["us_per_px"])
    x_end   = min(W - 1, mb_x + int(20.0 / cal["us_per_px"]))

    if x_start >= x_end:
        return None, None

    region = trace_y_s[x_start:x_end]

    # find_peaks on -trace (minima in y = maxima in power)
    prom_px  = cal["peak_min_prom_dB"] / cal["db_per_px"]
    dist_px  = cal["peak_min_dist_px"]
    peak_rel = _find_peaks_numpy(region, prominence=prom_px, distance=dist_px)

    if len(peak_rel) == 0:
        return None, None

    peak_cols   = peak_rel + x_start
    peak_powers = np.array([float(px_to_db(trace_y_s[c], cal)) for c in peak_cols])

    # Must be above noise floor by at least 3 dB
    valid       = peak_powers - noise_floor_dB > 3.0
    peak_cols   = peak_cols[valid]
    peak_powers = peak_powers[valid]

    if len(peak_cols) == 0:
        return None, None

    # -- Surface selection ------------------------------------------------------
    # Default: first peak after mb_skip_us.  Robustness guard: if a later peak
    # within the surface search window is substantially stronger (>min_surface_
    # lead_dB), prefer it.  This rejects weak T/R ringing artefacts that slip
    # past mb_skip_us (e.g. CBD0461 false peak at 2.77 µs, 30 dB below real
    # surface at 5.68 µs).  The surface_window_us bound prevents accidentally
    # promoting the bed echo (which is outside the window).
    srf_win_px   = mb_x + int(cal.get("surface_window_us", 8.0) / cal["us_per_px"])
    srf_mask     = peak_cols <= srf_win_px
    srf_cands    = peak_cols[srf_mask]
    srf_powers_c = peak_powers[srf_mask]

    if len(srf_cands) == 0:           # no peak in window -> fall back to first
        srf_cands    = peak_cols[:1]
        srf_powers_c = peak_powers[:1]

    if len(srf_cands) >= 2:
        first_power = srf_powers_c[0]
        best_idx    = int(np.argmax(srf_powers_c))
        best_power  = srf_powers_c[best_idx]
        # Promote strongest candidate if first peak is a weak artefact
        if best_power - first_power > cal.get("min_surface_lead_dB", 15.0):
            surface_x = int(srf_cands[best_idx])
        else:
            surface_x = int(srf_cands[0])
    else:
        surface_x = int(srf_cands[0])

    if len(peak_cols) < 2:
        return surface_x, None

    # Bed: first peak at least min_bed_gap_us after surface (~168 m minimum ice)
    # that also passes the quiet-gap check.
    #
    # Quiet-gap check: somewhere in the window [surface_x + lead_px, cand_x],
    # the smoothed trace must return within quiet_gap_dB of the noise floor.
    # This rejects candidates that are continuous with the surface echo (e.g.
    # phosphor afterglow, trailing ringing, film blemishes in the inter-echo
    # region) while accepting genuine bed echoes, which are preceded by a quiet
    # region where the surface echo has fully decayed.
    # The check is skipped when the gap is < 1 µs (very thin ice, h < 84 m).
    min_gap_px    = int(cal.get("min_bed_gap_us", 2.0) / cal["us_per_px"])
    candidates    = peak_cols[peak_cols >= surface_x + min_gap_px]
    if len(candidates) == 0:
        return surface_x, None

    quiet_lead_px   = int(cal.get("quiet_gap_lead_us", 1.0)  / cal["us_per_px"])
    quiet_gap_px    = cal.get("quiet_gap_dB",   12.0) / cal["db_per_px"]
    nf_row          = float(cal["y_ref_px"])
    min_bed_w_px    = int(cal.get("min_bed_width_us",  0.5) / cal["us_per_px"])
    width_thresh_y  = nf_row - cal.get("min_bed_width_dB", 10.0) / cal["db_per_px"]
    W               = len(trace_y_s)

    # Collect ALL candidates that pass quiet-gap and width checks, then
    # select the most prominent one.  Previous logic took the first passing
    # candidate, which misidentified weak intermediate features (surface
    # ringing, shallow internal reflectors) as the bed when the real bed
    # echo was further away and much stronger.
    valid_beds = []   # list of (column, power_dB)
    for cand in candidates:
        c      = int(cand)
        gap_lo = surface_x + quiet_lead_px
        gap_hi = c

        # -- Quiet-gap check ---------------------------------------------------
        # Skip when gap is < 1 µs (very thin ice, h <= 84 m)
        if gap_hi - gap_lo >= int(1.0 / cal["us_per_px"]):
            gap_trace = trace_y_s[gap_lo:gap_hi]
            if float(np.max(gap_trace)) < nf_row - quiet_gap_px:
                continue   # trace never returns to NF -> continuous artifact

        # -- Width check -------------------------------------------------------
        # The smoothed trace must stay above width_thresh_y for at least
        # min_bed_w_px consecutive columns around the candidate.
        # Real bed echoes: >= 0.83 µs wide (F125 TIFF 8400 validated data).
        # Film artifacts / surface-echo ringing: < 0.45 µs wide.
        w_lo    = max(0, c - min_bed_w_px * 3)
        w_hi    = min(W, c + min_bed_w_px * 3)
        above   = (trace_y_s[w_lo:w_hi] < width_thresh_y).astype(np.int8)
        # Maximum consecutive run of True (columns clearly above threshold)
        padded  = np.zeros(len(above) + 2, dtype=np.int8)
        padded[1:-1] = above
        diff    = np.diff(padded)
        starts  = np.where(diff > 0)[0]
        ends    = np.where(diff < 0)[0]
        max_run = 0 if len(starts) == 0 else int((ends - starts).max())
        if max_run < min_bed_w_px:
            continue   # too narrow -> film artifact or surface-echo ringing

        cand_power = float(px_to_db(trace_y_s[c], cal))
        valid_beds.append((c, cand_power))

    # Select the most prominent (strongest power) bed candidate
    if valid_beds:
        bed_x = int(max(valid_beds, key=lambda b: b[1])[0])
    else:
        bed_x = None

    return surface_x, bed_x


# -- Envelope walker ------------------------------------------------------------

def walk_envelope(trace_y_s: np.ndarray,
                  x_peak: int,
                  thresh_db: float,
                  mb_x: int,
                  frame_w: int,
                  cal: dict,
                  max_half_width_us: float = 0.0) -> tuple[float, float, float]:
    """
    Walk outward from a confirmed peak to find echo leading/trailing edges
    at a given power threshold.

    Leading edge  : walk LEFT until trace crosses threshold (first crossing).
    Trailing edge : walk RIGHT until `consec` consecutive columns are below
                    threshold (confirming sustained return to baseline).

    Parameters
    ----------
    thresh_db : absolute threshold in dB (e.g. noise_floor_dB + 10)
    max_half_width_us : maximum distance (µs) from peak to either edge.
        If > 0, caps the walk to prevent runaway envelopes (e.g., F143
        inter-echo signal staying above NF+5).  A surface echo cannot
        physically be wider than ~2 µs; a bed echo ~3-4 µs.
        Default 0 = no cap (backward compatible).

    Returns
    -------
    lead_us, trail_us, width_us : TWT values (µs from main bang)
    """
    thresh_y = db_to_px(thresh_db, cal)   # pixel row at threshold power
    consec   = cal["consec"]

    # Physical TWT bound for the rightward walk: cap at max_walk_us from MB.
    # Prevents the envelope extending into frame separators (all-white columns
    # look like "very high power" because argmin returns y_disp_lo there) or
    # beyond the maximum realistic two-way travel time for RIS geometry.
    max_walk_us = cal.get("max_walk_us", 17.0)
    x_right_max = min(frame_w - 1,
                      mb_x + int(max_walk_us / cal["us_per_px"]))

    # Per-echo width cap: limit walk distance from peak to prevent runaway
    # envelopes when inter-echo signal stays above threshold (F143 NF+5).
    if max_half_width_us > 0:
        max_half_px = int(max_half_width_us / cal["us_per_px"])
        x_right_max = min(x_right_max, x_peak + max_half_px)

    # Walk LEFT from peak
    lead = x_peak
    x_left_min = max(0, x_peak - 1500)
    if max_half_width_us > 0:
        max_half_px = int(max_half_width_us / cal["us_per_px"])
        x_left_min = max(x_left_min, x_peak - max_half_px)
    for x in range(x_peak, x_left_min, -1):
        if trace_y_s[x] >= thresh_y:   # trace at or below threshold
            lead = x
            break
    else:
        lead = x_left_min

    # Walk RIGHT — require `consec` consecutive below-threshold columns
    trail = x_peak
    count = 0
    for x in range(x_peak, x_right_max):
        if trace_y_s[x] >= thresh_y:
            count += 1
            if count >= consec:
                trail = x - consec
                break
        else:
            count = 0
    else:
        trail = x_right_max

    lead_us  = float(px_to_us(lead,  mb_x, cal))
    trail_us = float(px_to_us(trail, mb_x, cal))
    return lead_us, trail_us, float(trail_us - lead_us)


# -- Peakiness -----------------------------------------------------------------

def compute_peakiness(trace_y_s: np.ndarray,
                      x_peak: int,
                      lead_px: int,
                      trail_px: int,
                      cal: dict) -> float:
    """
    Peakiness = peak power (linear) / mean power (linear) within ±10 dB window.

    > 1 : sharply peaked (specular reflector / liquid water)
    ~ 1 : flat-topped (rough / noise-dominated)
    """
    x0 = max(0, lead_px)
    x1 = min(len(trace_y_s) - 1, trail_px) + 1
    if x1 <= x0 + 2:
        return np.nan

    powers_dB  = np.array([float(px_to_db(trace_y_s[x], cal)) for x in range(x0, x1)])
    powers_lin = 10.0 ** (powers_dB / 10.0)
    peak_lin   = 10.0 ** (float(px_to_db(int(round(trace_y_s[x_peak])), cal)) / 10.0)

    mean_lin = float(np.mean(powers_lin))
    if mean_lin <= 0:
        return np.nan
    return float(peak_lin / mean_lin)


# -- Per-echo full metrics ------------------------------------------------------

def compute_echo_metrics(trace_y_s: np.ndarray,
                         x_peak: int,
                         noise_floor_dB: float,
                         mb_x: int,
                         frame_w: int,
                         cal: dict,
                         trace_y: np.ndarray | None = None) -> EchoResult:
    """
    Compute complete waveform metrics for one detected echo peak.

    Parameters
    ----------
    trace_y : optional raw (pre-smooth) trace from extract_trace.
        When supplied, peak power is read from the raw argmin within ±2 px
        of x_peak rather than from the smoothed trace.  The smoothed trace
        (trace_y_s) is still used for all envelope-walking operations.
        Without trace_y, peak power falls back to trace_y_s[x_peak].
    """
    # Peak power: use the raw trace (or a local window around x_peak) so that
    # Gaussian smoothing does not bias the peak value downward.
    # Window ±15 px: the smoothed trace can shift the peak column by several
    # pixels (asymmetric echoes), so a narrow ±2 px window may miss the true
    # minimum.  ±15 px covers the peak of any real echo while remaining small
    # enough to avoid picking up adjacent features.
    if trace_y is not None:
        lo  = max(0, x_peak - 15)
        hi  = min(len(trace_y), x_peak + 16)
        peak_y = int(np.min(trace_y[lo:hi]))
    else:
        peak_y = int(round(trace_y_s[x_peak]))
    peak_twt   = float(px_to_us(x_peak, mb_x, cal))
    peak_power = float(px_to_db(peak_y, cal))
    peak_snr   = peak_power - noise_floor_dB

    result = EchoResult(
        peak_x=x_peak, peak_y=peak_y,
        peak_twt_us=peak_twt,
        peak_power_dB=peak_power,
        peak_snr_dB=peak_snr,
    )

    # Envelope at +10 dB above measured noise floor
    thresh_10 = noise_floor_dB + 10.0
    if peak_power > thresh_10:
        l10, t10, w10 = walk_envelope(
            trace_y_s, x_peak, thresh_10, mb_x, frame_w, cal)
        result.lead_10_us  = l10
        result.trail_10_us = t10
        result.width_10_us = w10
        result.leading_rise_us = peak_twt - l10

        lead_10_px  = us_to_px(l10, mb_x, cal)
        trail_10_px = us_to_px(t10, mb_x, cal)
        result.peakiness = compute_peakiness(
            trace_y_s, x_peak, lead_10_px, trail_10_px, cal)

        trailing_w = t10 - peak_twt
        leading_w  = peak_twt - l10
        if leading_w > 1e-6:
            result.asymmetry = trailing_w / leading_w

    # Envelope at +5 dB above measured noise floor
    thresh_5 = noise_floor_dB + 5.0
    if peak_power > thresh_5:
        l5, t5, w5 = walk_envelope(
            trace_y_s, x_peak, thresh_5, mb_x, frame_w, cal)
        result.lead_5_us  = l5
        result.trail_5_us = t5
        result.width_5_us = w5
        if not np.isnan(result.trail_10_us):
            result.trailing_tail_us = t5 - result.trail_10_us

    # -- First-break onset: walk LEFT from peak to NF + onset_db ---------------
    # The onset (first break) is where the signal first rises above the noise
    # floor.  This gives the shortest two-way travel time (nadir reflection),
    # which is more accurate for ice thickness than the peak TWT — especially
    # over rough beds where off-nadir scattering can shift the peak later.
    #
    # Threshold: NF + 3 dB (just above noise; robust against noise fluctuations
    # while catching the true first arrival).  Walk left from the peak using the
    # smoothed trace; the onset is the last column above threshold before the
    # signal drops into the noise.
    ONSET_ABOVE_NF_DB = 3.0
    onset_thresh_dB = noise_floor_dB + ONSET_ABOVE_NF_DB
    if peak_power > onset_thresh_dB:
        onset_thresh_y = db_to_px(onset_thresh_dB, cal)
        onset_x = x_peak
        for x in range(x_peak, max(mb_x, 0), -1):
            if trace_y_s[x] >= onset_thresh_y:   # at or below threshold
                onset_x = x + 1 if x < x_peak else x_peak
                break
        else:
            onset_x = max(mb_x + 1, 0)
        # Clamp to valid range
        onset_x = max(mb_x + 1, min(onset_x, x_peak))
        result.onset_twt_us = float(px_to_us(onset_x, mb_x, cal))
        result.onset_power_dB = float(px_to_db(int(round(trace_y_s[onset_x])), cal))

    return result


# -- Local column profile extraction -------------------------------------------

def extract_local_profile(frame: np.ndarray,
                          echo_x: int,
                          mb_x: int,
                          noise_floor_dB: float,
                          cal: dict,
                          half_window: int = 80,
                          guide_y: float | None = None,
                          guide_tol: int = 150,
                          max_half_width_us: float = 4.0) -> EchoResult:
    """
    Extract calibrated echo metrics from a local column window around a
    known echo position, bypassing the global continuous trace entirely.

    This is immune to the global trace failure mode where competing dark
    features (graticule lines, reference lines) pull the argmin away from
    the CRT signal.  Within a narrow local window centered on the echo,
    the echo peak is the dominant dark feature.

    Parameters
    ----------
    frame : (H, W) normalized float array [0, 1]
    echo_x : column position of the echo (frame-relative)
    mb_x : main bang column (frame-relative)
    noise_floor_dB : estimated per-frame noise floor (dB)
    cal : calibration dict (y_ref_px, db_per_px, us_per_px, y_disp_lo, y_disp_hi)
    half_window : columns left/right of echo_x to include (default 80)
    guide_y : optional Y-row hint from the global trace at echo_x.
        When provided, the local argmin is constrained to within +-guide_tol
        rows of this value, preventing dark artifacts far from the CRT trace
        from pulling the peak estimate away.
    guide_tol : half-width of the constraint window around guide_y (default 150 px)

    Returns
    -------
    EchoResult with peak power, SNR, envelope widths, peakiness, etc.
    """
    H, W   = frame.shape
    y_lo   = cal["y_disp_lo"]
    y_hi   = min(cal["y_disp_hi"], H)

    # Column bounds (clamp to frame)
    x0 = max(0, echo_x - half_window)
    x1 = min(W, echo_x + half_window + 1)
    if x1 <= x0:
        return EchoResult()

    # Extract local band (display region only)
    band = frame[y_lo:y_hi, x0:x1].astype(float).copy()
    bH   = band.shape[0]

    # -- Graticule masking (same logic as extract_trace) -----------------------
    mask_half = cal.get("graticule_mask_half_px", 3)
    y_sp_px   = 10.0 / cal["db_per_px"]
    n_lo_g = int(np.floor((y_lo - cal["y_ref_px"]) / y_sp_px)) - 1
    n_hi_g = int(np.ceil( (y_hi - cal["y_ref_px"]) / y_sp_px)) + 1
    for _n in range(n_lo_g, n_hi_g + 1):
        gl_abs = cal["y_ref_px"] + _n * y_sp_px
        gl_rel = int(round(gl_abs - y_lo))
        if 0 <= gl_rel < bH:
            r0 = max(0, gl_rel - mask_half)
            r1 = min(bH, gl_rel + mask_half + 1)
            band[r0:r1, :] = 1.0

    # -- Determine whether the global trace is usable at this echo position ----
    # When guide_y is above noise floor, the global trace is tracking the CRT
    # signal correctly.  Use guide_y directly for peak_y (power reading) so
    # dark artifacts in the local window cannot pull the estimate away.
    # When the trace has failed (near noise floor), fall back to unconstrained
    # local argmin — the original purpose of extract_local_profile().
    _guide_active = False
    if guide_y is not None:
        guide_power = px_to_db(guide_y, cal)
        if guide_power - noise_floor_dB > 5.0:
            _guide_active = True

    # -- Per-column argmin within local window ---------------------------------
    local_trace_rel = np.argmin(band, axis=0).astype(float)  # band-relative
    local_trace_abs = local_trace_rel + y_lo                  # absolute row

    # Light median filter (window=5) to reject single-pixel film grain
    local_trace_filt = _running_median(local_trace_abs, window=5)

    # Also keep raw (unfiltered) for peak power reading
    local_trace_raw = local_trace_abs.copy()

    # -- Find peak position and Y row ------------------------------------------
    if _guide_active:
        # Trust the global trace: use echo_x as peak column, guide_y as peak row.
        # Read the darkest pixel in a small +-10 row window around guide_y at
        # echo_x to handle sub-pixel variations in the CRT phosphor.
        peak_x_abs = echo_x
        gy = int(round(guide_y))
        gy_lo = max(0, gy - 10)
        gy_hi = min(H, gy + 11)
        # Read a small column band around echo_x too (+-3 px)
        gx_lo = max(0, echo_x - 3)
        gx_hi = min(W, echo_x + 4)
        peak_y = int(np.min(frame[gy_lo:gy_hi, gx_lo:gx_hi] * H))
        # But frame values are [0,1] -- we need the row, not the intensity.
        # Find the darkest row near guide_y at echo_x:
        col_slice = frame[gy_lo:gy_hi, gx_lo:gx_hi]
        mean_intensity = col_slice.mean(axis=1)  # average across the few columns
        peak_y = gy_lo + int(np.argmin(mean_intensity))
    else:
        # Trace failed: use unconstrained local argmin
        peak_local_idx = int(np.argmin(local_trace_filt))
        peak_x_abs     = x0 + peak_local_idx   # frame-relative column
        # Peak power: read from raw trace in +-5 px around detected peak
        raw_lo = max(0, peak_local_idx - 5)
        raw_hi = min(len(local_trace_raw), peak_local_idx + 6)
        peak_y = int(np.min(local_trace_raw[raw_lo:raw_hi]))

    peak_twt   = float(px_to_us(peak_x_abs, mb_x, cal))
    peak_power = float(px_to_db(peak_y, cal))
    peak_snr   = peak_power - noise_floor_dB

    result = EchoResult(
        peak_x=peak_x_abs, peak_y=peak_y,
        peak_twt_us=peak_twt,
        peak_power_dB=peak_power,
        peak_snr_dB=peak_snr,
    )

    # -- Envelope walking using local filtered trace ---------------------------
    # Build a full-frame-width trace padded with NF for the envelope walker
    # (walk_envelope expects frame-width arrays and uses absolute column indices)
    nf_row = float(cal["y_ref_px"])
    full_trace = np.full(W, nf_row, dtype=float)
    full_trace[x0:x1] = local_trace_filt

    # Fine smooth within the local window for envelope walking
    local_smooth = _gauss_smooth(local_trace_filt, sigma=3.0)
    full_trace_s = np.full(W, nf_row, dtype=float)
    full_trace_s[x0:x1] = local_smooth

    # Envelope at +10 dB above noise floor
    thresh_10 = noise_floor_dB + 10.0
    if peak_power > thresh_10:
        l10, t10, w10 = walk_envelope(
            full_trace_s, peak_x_abs, thresh_10, mb_x, W, cal,
            max_half_width_us=max_half_width_us)
        result.lead_10_us  = l10
        result.trail_10_us = t10
        result.width_10_us = w10
        result.leading_rise_us = peak_twt - l10

        lead_10_px  = us_to_px(l10, mb_x, cal)
        trail_10_px = us_to_px(t10, mb_x, cal)
        result.peakiness = compute_peakiness(
            full_trace_s, peak_x_abs, lead_10_px, trail_10_px, cal)

        trailing_w = t10 - peak_twt
        leading_w  = peak_twt - l10
        if leading_w > 1e-6:
            result.asymmetry = trailing_w / leading_w

    # Envelope at +5 dB above noise floor
    thresh_5 = noise_floor_dB + 5.0
    if peak_power > thresh_5:
        l5, t5, w5 = walk_envelope(
            full_trace_s, peak_x_abs, thresh_5, mb_x, W, cal,
            max_half_width_us=max_half_width_us)
        result.lead_5_us  = l5
        result.trail_5_us = t5
        result.width_5_us = w5
        if not np.isnan(result.trail_10_us):
            result.trailing_tail_us = t5 - result.trail_10_us

    # -- First-break onset -----------------------------------------------------
    ONSET_ABOVE_NF_DB = 3.0
    onset_thresh_dB = noise_floor_dB + ONSET_ABOVE_NF_DB
    if peak_power > onset_thresh_dB:
        onset_thresh_y = db_to_px(onset_thresh_dB, cal)
        onset_x = peak_x_abs
        for x in range(peak_x_abs, max(mb_x, x0), -1):
            if full_trace_s[x] >= onset_thresh_y:
                onset_x = x + 1 if x < peak_x_abs else peak_x_abs
                break
        else:
            onset_x = max(mb_x + 1, x0)
        onset_x = max(mb_x + 1, min(onset_x, peak_x_abs))
        result.onset_twt_us = float(px_to_us(onset_x, mb_x, cal))
        result.onset_power_dB = float(px_to_db(
            int(round(full_trace_s[onset_x])), cal))

    # -- Peak-relative decay metrics ------------------------------------------
    # Walk from peak using thresholds relative to peak power (not noise floor).
    # These are SNR-independent and directly encode interface sharpness.
    peak_y_row = full_trace_s[peak_x_abs]
    db_per_px = cal["db_per_px"]

    for drop_db, attr in [(10.0, "decay_10_us"), (20.0, "decay_20_us")]:
        # Only compute if SNR is sufficient (peak must be > drop_db above NF)
        if peak_power < noise_floor_dB + drop_db + 2.0:
            continue
        thresh_y_pk = peak_y_row + drop_db / db_per_px  # lower power = higher row
        max_walk_px = int(max_half_width_us / cal["us_per_px"])
        x_limit = min(W - 1, peak_x_abs + max_walk_px)
        for x in range(peak_x_abs, x_limit):
            if full_trace_s[x] >= thresh_y_pk:
                decay_us = float(px_to_us(x, mb_x, cal)) - peak_twt
                setattr(result, attr, round(decay_us, 4))
                break

    # Rise time: walk LEFT from peak to peak-10 dB
    if peak_power >= noise_floor_dB + 12.0:
        thresh_y_rise = peak_y_row + 10.0 / db_per_px
        max_walk_px = int(max_half_width_us / cal["us_per_px"])
        x_limit_l = max(0, peak_x_abs - max_walk_px)
        for x in range(peak_x_abs, x_limit_l, -1):
            if full_trace_s[x] >= thresh_y_rise:
                rise_us = peak_twt - float(px_to_us(x, mb_x, cal))
                result.rise_10_us = round(rise_us, 4)
                break

    # Peak-relative asymmetry
    if not np.isnan(result.decay_10_us) and not np.isnan(result.rise_10_us):
        if result.rise_10_us > 1e-4:
            result.pk_asymmetry = round(result.decay_10_us / result.rise_10_us, 3)

    return result


# -- Y grid lines: extrapolation (graticule too faint to detect directly) ------

def compute_y_grid_lines(y_ref_px: float,
                          y_spacing_px: float,
                          y_disp_lo: int,
                          y_disp_hi: int,
                          n_above: int = 6,
                          n_below: int = 6,
                          ) -> list[float]:
    """
    Compute Y (horizontal) grid line positions by extrapolation.

    CRITICAL: The -60 dB reference line sits BETWEEN two major graticule
    divisions at -55 dB and -65 dB, not on a division.  The offset from
    y_ref_px to the nearest graticule line above (-55 dB) is half a major
    division ~ y_spacing_px / 2 ~ 102.5 px (validated from F125 Frame 8:
    y_ref=1507, nearest grid=1404 -> offset=103 px, from detect_gridlines3.py).

    Graticule lines: …, -45, -55, -65, -75, … dB
    NOT at:         …, -50, -60, -70, -80, … dB

    Formula:
        y_first = y_ref_px - y_spacing_px / 2    (-> -55 dB)
        y_grid[k] = y_first + k × y_spacing_px

    Returns
    -------
    Sorted list of Y row positions within [y_disp_lo, y_disp_hi].
    """
    # First graticule above the reference line (-55 dB)
    y_first = y_ref_px - y_spacing_px / 2.0
    lines = []
    for k in range(-n_above, n_below + 1):
        y = y_first + k * y_spacing_px
        if y_disp_lo <= y <= y_disp_hi:
            lines.append(float(y))
    return sorted(lines)


# -- X grid lines: argmax in below-baseline band (validated approach) ----------

def detect_xgrid_lines(frame: np.ndarray,
                        mb_x: int,
                        x_spacing_px: float,
                        cal: dict,
                        n_major: int = 14,
                        x_band: tuple[int, int] = (1600, 1695),
                        gauss_sigma: float = 10.0,
                        half_search: int = 35,
                        inlier_thresh_px: float = 8.0,
                        guide_x_grid: list[int] | None = None,
                        d_from_mb: float | None = None,
                        ) -> tuple[np.ndarray, float, np.ndarray]:
    """
    Detect X (vertical) major grid lines using column-mean in a y-band
    between the noise floor and the bottom display line.

    Critical band selection: y=[1600, 1695] sits BETWEEN the noise floor
    (y_ref ~ 1512) and the bottom major horizontal display line (y ~ 1717).
    In this region only MAJOR vertical grid lines are visible — minor tick
    notches exist only along horizontal major lines (y~1717, 1512, …) and
    do not appear inside this intermediate band.  The previous band (1550, 1800)
    included y~1717 where minor tick notches at every x_spacing/5 ~ 41 px
    scored higher than the diffuse major vertical lines, causing the phase
    search to lock onto minor tick positions (offset 1–4 minor ticks from
    the true major tick phase).

    Key design note: the graticule is NOT anchored at mb_x.  The first tick to
    the right of mb_x is typically 69–88 px away (F125 data), well beyond the
    ±half_search snap window.  The algorithm therefore:
      1. Finds the FIRST tick by argmax over the full first division
         [mb_x, mb_x + x_spacing_px] in the below-baseline strip.
      2. Builds all subsequent guides as first_x + k * x_spacing_px.
      3. Applies ±half_search snap to each guide (handles inter-frame drift).

    Parameters
    ----------
    frame         : (H, W) float32 frame array [0, 1]
    mb_x          : main bang column (anchor for guide positions)
    x_spacing_px  : expected major-division spacing in pixels
    cal           : calibration dict (uses y_disp_lo, y_disp_hi)
    n_major       : how many major lines to search for (rightward from mb_x)
    x_band        : (y_lo, y_hi) rows of below-baseline band
    gauss_sigma   : smoothing sigma for column mean profile
    half_search   : ±px search window around each guide position
    inlier_thresh_px : residual threshold for inlier-only linear fit

    Returns
    -------
    x_fitted     : (n_major,) array of fitted X positions (float)
    spacing_px   : spacing from inlier linear fit (px / major division)
    raw_x        : raw snapped grid detections before the linear fit
    """
    H, W = frame.shape
    y_lo = min(x_band[0], H - 2)
    y_hi = min(x_band[1], H)

    if y_hi <= y_lo:
        guides = np.array([mb_x + k * x_spacing_px for k in range(n_major)
                           if 0 < mb_x + k * x_spacing_px < W])
        _g = guides.astype(float)
        return _g, x_spacing_px, _g.copy()

    below      = frame[y_lo:y_hi, :]
    col_mean   = np.mean(below, axis=0)
    col_smooth = _gauss_smooth(col_mean, gauss_sigma)

    # -- Find the first grid tick -------------------------------------------
    # The tick marks appear as bright columns in the below-baseline band.
    #
    # Priority A: use clicked x_grid guide positions (most accurate).
    # The user may click on any major division; back-calculate first_x from it.
    # If 2+ clicks are provided, also re-measure x_spacing_px from their spacing —
    # this corrects for per-TIFF oscilloscope time-base differences that would
    # otherwise cause progressive drift (each tick adds the per-division error).
    #
    # Priority B: grid phase search — NO reliance on mb_x.
    # Film frame widths vary significantly between frames (e.g. 2595–3250 px in
    # F127), so the CRT display starts at different frame-relative positions.
    # mb_x also jitters ±10–30 px due to detection noise.  Instead, we scan all
    # possible grid phases x0 in [0, x_spacing_px) and pick the one that maximises
    # the mean of col_smooth at {x0, x0+sp, x0+2sp, …}.  This is robust to any
    # per-frame CRT registration variation or mb_x inconsistency.
    if guide_x_grid:
        # Priority A
        x_sorted = sorted(float(v) for v in guide_x_grid)
        if len(x_sorted) >= 2:
            # Use ALL guide clicks, not only the first and last.  Clicks may skip
            # major divisions, so infer integer division indices from the incoming
            # spacing estimate and fit x = intercept + spacing * division_index.
            x0 = x_sorted[0]
            k_click = np.array([round((x - x0) / x_spacing_px) for x in x_sorted], dtype=float)
            if len(np.unique(k_click)) >= 2:
                x_spacing_px = abs(float(np.polyfit(k_click, np.array(x_sorted), 1)[0]))
        x_seed      = x_sorted[0]
        k_seed      = max(0, round((x_seed - mb_x) / x_spacing_px))
        first_guess = x_seed - k_seed * x_spacing_px
        snap_lo = max(0, int(first_guess) - 15)
        snap_hi = min(W, int(first_guess) + 16)
        if snap_hi > snap_lo:
            first_x = float(snap_lo + np.argmax(col_smooth[snap_lo:snap_hi]))
        else:
            first_x = first_guess
    elif d_from_mb is not None:
        # Priority A2: D_anchor — constant distance from mb_x to a known major tick.
        #
        # Physical basis: the oscilloscope sweep is triggered from the radar transmit
        # pulse, so all waveform content is time-locked to the graticule.  D = tick_x
        # - mb_x is constant across frames within a TIFF (same oscilloscope time base).
        #
        # Strategy: predict the anchor tick's frame-relative position as
        # anchor_pred = mb_x + d_from_mb, snap ±half_search around it to find the
        # actual tick, then back-calculate first_x = anchor_x - k_anchor * spacing.
        # The anchor lands in the right portion of the frame (past the bright left-side
        # artifact), giving a reliable snap even when major ticks are faint.
        k_anchor    = max(0, round(d_from_mb / x_spacing_px))
        anchor_pred = float(mb_x) + d_from_mb
        a_lo        = max(0, int(anchor_pred) - half_search)
        a_hi        = min(W, int(anchor_pred) + half_search + 1)
        if a_hi > a_lo:
            anchor_x = float(a_lo + np.argmax(col_smooth[a_lo:a_hi]))
        else:
            anchor_x = anchor_pred
        first_x = anchor_x - k_anchor * x_spacing_px
    else:
        # Priority B: grid phase search — right-portion only.
        #
        # The left side of every frame (~first 35% of width) contains a large
        # bright artifact in the below-baseline band (from the inter-frame
        # boundary, CRT unblank, and main-bang region bleeding downward).
        # Using the full frame causes the phase search to lock onto that bright
        # region rather than the faint but periodic graticule tick marks.
        #
        # Fix: score only positions in the right 65% of the frame (x > W*0.35).
        # This region is after the main bang and early echoes, where the trace
        # sits at the noise floor and the only periodic features are the CRT
        # graticule ticks.  Typically >=8 major ticks remain in this region —
        # sufficient for reliable phase estimation.
        #
        # Coarse sweep over all phases (~200 steps), then 0.1 px fine refinement.
        step     = max(0.5, x_spacing_px / 200.0)
        k_arr    = np.arange(n_major, dtype=float)
        W_sm     = len(col_smooth)
        x_start  = 200                         # exclude only inter-frame border (~0-200 px)
        min_ticks = 4                          # require at least this many valid ticks
        best_score = -np.inf
        best_x0    = 0.0
        for x0 in np.arange(0.0, x_spacing_px, step):
            idxs  = np.round(x0 + k_arr * x_spacing_px).astype(int)
            valid = (idxs >= x_start) & (idxs < W_sm)
            if valid.sum() >= min_ticks:
                s = col_smooth[idxs[valid]].mean()
                if s > best_score:
                    best_score = s
                    best_x0    = x0
        # Fine refinement ±2 coarse steps around best_x0
        for x0 in np.arange(max(0.0,          best_x0 - 2 * step),
                             min(x_spacing_px, best_x0 + 2 * step + 0.01), 0.1):
            idxs  = np.round(x0 + k_arr * x_spacing_px).astype(int)
            valid = (idxs >= x_start) & (idxs < W_sm)
            if valid.sum() >= min_ticks:
                s = col_smooth[idxs[valid]].mean()
                if s > best_score:
                    best_score = s
                    best_x0    = x0
        first_x = float(best_x0)

    # Guide positions anchored at first_x
    guides = []
    for k in range(n_major):
        gx = first_x + k * x_spacing_px
        if 0 < gx < W:
            guides.append(gx)
    guides = np.array(guides)

    if len(guides) < 2:
        _g = guides.astype(float)
        return _g, x_spacing_px, _g.copy()

    # Raw detection: ±half_search snap around each guide (accounts for spacing drift)
    raw_x = np.empty(len(guides), dtype=float)
    # k=0 already resolved above (first_x); still snap to refine sub-pixel position
    for i, g in enumerate(guides):
        lo = max(0, int(g) - half_search)
        hi = min(W, int(g) + half_search)
        if hi > lo:
            raw_x[i] = lo + float(np.argmax(col_smooth[lo:hi]))
        else:
            raw_x[i] = g

    # Initial linear fit across all guides
    k_all   = np.arange(len(raw_x), dtype=float)
    c_all   = np.polyfit(k_all, raw_x, 1)
    resid   = raw_x - np.polyval(c_all, k_all)

    # Inlier-only refit (validated approach)
    inliers = np.abs(resid) <= inlier_thresh_px
    if inliers.sum() >= 2:
        c_in    = np.polyfit(k_all[inliers], raw_x[inliers], 1)
        spacing = abs(float(c_in[0]))
    else:
        c_in    = c_all
        spacing = abs(float(c_all[0]))

    x_fitted = np.polyval(c_in, k_all)
    return x_fitted, spacing, raw_x


# -- Per-frame calibration ------------------------------------------------------

def detect_frame_calibration(
        frame: np.ndarray,
        default_cal: dict,
        guides: dict | None = None,
) -> dict:
    """
    Per-frame calibration using validated algorithms.

    Steps
    -----
    A. Main bang  (mb_x): validated argmin approach — find the leftmost
       column where the trace is deflected highest.  If a guide pick is
       provided, narrows search to ±200 px around it (find_mainbang2.py).

    B. Y reference (y_ref_px, -60 dB): pre-main-bang trace median sits at
       the system noise floor = the -60 dB reference line.

    C. X grid lines: column-mean argmax in below-baseline band y=[1550,1800].
       Grid tick marks are bright; we fit an inlier-only linear model
       (detect_gridlines3.py).

    D. Y grid lines: PURE EXTRAPOLATION from y_ref_px + k × y_spacing_px.
       The horizontal graticule lines are too faint to detect algorithmically
       (confirmed empirically — detect_gridlines3.py comment: "No algorithmic
       row-mean detection — graticule lines too faint").

    Parameters
    ----------
    frame       : (H, W) float32 array [0, 1], already cropped to this frame
    default_cal : baseline calibration dict (DEFAULT_CAL or previous per-frame)
    guides      : optional dict from pick_calibration.py output, with keys:
                    'mb'          – int, approximate main bang x (frame-rel)
                    'ref'         – int, approximate y_ref_px row
                    'x_spacing_px'– float, X major-division spacing
                    'y_spacing_px'– float, Y major-division spacing

    Returns
    -------
    cal : updated dict with added keys:
        mb_x           – detected main bang column (frame-relative pixels)
        mb_power_dB    – power at main bang (dB)
        y_ref_px       – noise-floor row = -60 dB anchor (pixels)
        db_per_px      – Y scale (dB/px; from y_spacing_px)
        hgrid_lines    – list of Y grid line rows (extrapolated)
        hgrid_spacing  – Y major-division spacing used (px)
        xgrid_lines    – list of X grid line cols (detected)
        x_spacing_px   – X major-division spacing (px; from inlier fit)
        cal_source_y   – always 'extrapolated'
    """
    guides = guides or {}
    cal    = default_cal.copy()

    # Derive spacing constants: prefer guide, then default_cal, then DEFAULT_CAL
    x_spacing_px = float(guides.get("x_spacing_px",
                         default_cal.get("x_spacing_px",
                         2.0 / default_cal["us_per_px"])))
    y_spacing_px = float(guides.get("y_spacing_px",
                         default_cal.get("y_spacing_px",
                         10.0 / default_cal["db_per_px"])))

    # -- A: Main bang ------------------------------------------------------
    trace_y, trace_y_s, _ = extract_trace(frame, cal)
    guide_mb           = guides.get("mb")

    if guide_mb is not None and guides.get("mb_is_pick"):
        # Explicit user M pick identifies WHICH feature is the transmitter pulse.
        # Treat the click as an anchor, then refine to the maximum-power point
        # (minimum image-row Y) of that local feature.  The search is deliberately
        # local so a much stronger surface echo farther to the right cannot be
        # mistaken for the main bang.
        _W = frame.shape[1]
        _mb_anchor_halfwin = 100
        _lo = max(0, int(guide_mb) - _mb_anchor_halfwin)
        _hi = min(_W, int(guide_mb) + _mb_anchor_halfwin + 1)

        if _hi > _lo:
            _local = trace_y[_lo:_hi].astype(float)
            # A short smooth suppresses single-column film-grain spikes while
            # preserving the broad transmitter-pulse peak.
            _local_s = _gauss_smooth(_local, sigma=3.0)
            _pick_mb = _lo + int(np.argmin(_local_s))

            # Refine on the unsmoothed trace only very near that pulse peak.
            _fine_lo = max(_lo, _pick_mb - 8)
            _fine_hi = min(_hi, _pick_mb + 9)
            _pick_mb = _fine_lo + int(np.argmin(trace_y[_fine_lo:_fine_hi]))

            _pick_pwr = float(px_to_db(float(trace_y[_pick_mb]), cal))
            _noise_db = cal.get("y_ref_db", -60.0)
            if _pick_pwr >= _noise_db + 3.0:
                mb_x = _pick_mb
            else:
                mb_x = detect_mb(trace_y_s, cal, guide_x=guide_mb,
                                  frame=frame)
        else:
            mb_x = detect_mb(trace_y_s, cal, guide_x=guide_mb,
                              frame=frame)
    else:
        mb_x = detect_mb(trace_y_s, cal, guide_x=guide_mb,
                          frame=frame)
    # Measure MB power from the UNCONSTRAINED trace (trace_y), not the
    # smoothed trace (trace_y_s).  The smoothed trace deliberately clamps
    # the MB region to the noise floor (to prevent T/R ringing from biasing
    # envelope walks), so trace_y_s[mb_x] reads near NF regardless of true
    # MB power.  This masked attenuator changes and CRT gain shifts.
    # Search a ±10 px window in trace_y for the actual MB peak (minimum Y
    # = maximum power) to handle slight positional offset.
    _mb_win = 10
    _mb_lo = max(0, mb_x - _mb_win)
    _mb_hi = min(len(trace_y), mb_x + _mb_win + 1)
    _mb_best_y = float(np.min(trace_y[_mb_lo:_mb_hi]))
    mb_power_dB        = float(px_to_db(_mb_best_y, cal))

    cal["mb_x"]        = mb_x
    cal["mb_power_dB"] = mb_power_dB

    # -- B: Y reference (noise floor = -60 dB) ----------------------------
    guide_ref = guides.get("ref")
    if guide_ref is not None:
        # Guide provided: use it directly (user confirmed the reference line)
        y_ref_px = float(guide_ref)
    else:
        # No guide: sample from the MIDDLE of the pre-bang region.
        # Avoid frame-boundary artifacts (cols 0–30) and the main bang's
        # leading edge (last ~50 px before mb_x).
        # Safe window: mb_x//4 -> mb_x//2, clamped away from the bang.
        pre_lo = max(30, mb_x // 4)
        pre_hi = min(max(pre_lo + 10, mb_x // 2), max(pre_lo + 5, mb_x - 50))
        if pre_hi > pre_lo + 5:
            pre_trace = trace_y_s[pre_lo:pre_hi]
            y_ref_px  = float(np.percentile(pre_trace, 75))
            # Sanity: must lie within the oscilloscope display band
            if not (cal["y_disp_lo"] < y_ref_px < cal["y_disp_hi"]):
                warnings.warn(
                    f"y_ref estimate {y_ref_px:.0f} px outside display band "
                    f"[{cal['y_disp_lo']}, {cal['y_disp_hi']}] — using default")
                y_ref_px = float(default_cal["y_ref_px"])
        else:
            y_ref_px = float(default_cal["y_ref_px"])

    cal["y_ref_px"] = y_ref_px
    cal["y_ref_db"] = -60.0

    # -- C: X grid lines (argmax in below-baseline band) ------------------
    x_fitted, x_spacing_detected, x_raw = detect_xgrid_lines(
        frame, mb_x, x_spacing_px, cal,
        guide_x_grid=guides.get("x_grid"),
        d_from_mb=guides.get("d_from_mb"))
    cal["xgrid_lines"]      = x_fitted.tolist()
    cal["xgrid_raw_lines"]  = x_raw.tolist()
    cal["x_spacing_px"]     = x_spacing_detected

    # -- D: Y grid lines (pure extrapolation) -----------------------------
    hgrid_lines = compute_y_grid_lines(
        y_ref_px, y_spacing_px,
        cal["y_disp_lo"], cal["y_disp_hi"])
    cal["hgrid_lines"]  = hgrid_lines
    cal["hgrid_spacing"] = y_spacing_px
    cal["db_per_px"]     = 10.0 / y_spacing_px
    cal["cal_source_y"]  = "extrapolated"

    return cal


# -- Main entry: process one TIFF ----------------------------------------------

def process_tiff(tiff_path: str | Path,
                 cal: dict | None = None,
                 frame_bounds: list[tuple[int, int]] | None = None,
                 verbose: bool = True) -> list[LyraFrame]:
    """
    Process all A-scope frames in a TIFF and extract waveform metrics.

    Parameters
    ----------
    tiff_path    : path to raw A-scope TIFF
    cal          : calibration dict (uses DEFAULT_CAL if None)
    frame_bounds : pre-computed (left, right) boundaries; auto-detected if None
    verbose      : print per-frame progress

    Returns
    -------
    list of LyraFrame, one per detected frame
    """
    if cal is None:
        cal = DEFAULT_CAL.copy()
    tiff_path = Path(tiff_path)

    if verbose:
        print(f"\nLYRA v1.0 — processing {tiff_path.name}")
        print("-" * 70)

    Image.MAX_IMAGE_PIXELS = None
    img      = np.array(Image.open(tiff_path), dtype=np.float32)
    img_norm = (img - img.min()) / (img.max() - img.min() + 1e-9)
    H, W     = img_norm.shape

    if verbose:
        print(f"  Image : {W} × {H} px")

    if frame_bounds is None:
        frame_bounds = detect_frames(img_norm)
    if verbose:
        print(f"  Frames detected : {len(frame_bounds)}")
        print()

    results: list[LyraFrame] = []

    for idx, (left, right) in enumerate(frame_bounds):
        frame   = img_norm[:, left : right + 1]
        frame_w = frame.shape[1]
        lf      = LyraFrame(
            frame_idx=idx, frame_left=left, frame_right=right, frame_w=frame_w)

        try:
            trace_y, trace_y_s, _ = extract_trace(frame, cal)
            mb_x               = detect_mb(trace_y_s, cal, frame=frame)
            lf.mb_x            = mb_x
            lf.noise_floor_dB  = estimate_noise_floor(trace_y_s, mb_x, cal)

            surface_x, bed_x = detect_echoes(
                trace_y_s, mb_x, lf.noise_floor_dB, cal)

            if surface_x is not None:
                lf.surface          = compute_echo_metrics(
                    trace_y_s, surface_x, lf.noise_floor_dB, mb_x, frame_w, cal)
                lf.surface_detected = True
            else:
                lf.quality = "no_surface"

            if bed_x is not None:
                lf.bed          = compute_echo_metrics(
                    trace_y_s, bed_x, lf.noise_floor_dB, mb_x, frame_w, cal)
                lf.bed_detected = True
            else:
                if lf.quality == "ok":
                    lf.quality = "no_bed"

        except Exception as exc:
            warnings.warn(f"Frame {idx}: {exc}")
            lf.quality = "failed"

        results.append(lf)

        if verbose:
            s = f"  [{idx:2d}] MB={lf.mb_x:4d}px  NF={lf.noise_floor_dB:+.1f} dB"
            if lf.surface_detected:
                s += (f"  | surf {lf.surface.peak_twt_us:.2f}µs"
                      f" {lf.surface.peak_power_dB:+.1f}dB"
                      f" SNR={lf.surface.peak_snr_dB:.1f}dB")
            if lf.bed_detected:
                s += (f"  | bed {lf.bed.peak_twt_us:.2f}µs"
                      f" {lf.bed.peak_power_dB:+.1f}dB"
                      f" SNR={lf.bed.peak_snr_dB:.1f}dB"
                      f"  peak={lf.bed.peakiness:.2f}"
                      f"  asym={lf.bed.asymmetry:.2f}")
            if lf.quality != "ok":
                s += f"  [{lf.quality}]"
            print(s)

    return results


# -- DataFrame serialisation ----------------------------------------------------

def to_dataframe(results: list[LyraFrame],
                 tiff_path: str | Path | None = None) -> pd.DataFrame:
    """
    Flatten list of LyraFrame into a tidy DataFrame (one row per frame).

    Column naming convention: {echo}_{metric}  (e.g. bed_peakiness)
    """
    tiff_name = Path(tiff_path).name if tiff_path else ""
    rows = []

    for lf in results:
        row: dict = dict(
            tiff             = tiff_name,
            frame_idx        = lf.frame_idx,
            frame_left       = lf.frame_left,
            frame_right      = lf.frame_right,
            frame_w          = lf.frame_w,
            mb_x             = lf.mb_x,
            noise_floor_dB   = lf.noise_floor_dB,
            surface_detected = lf.surface_detected,
            bed_detected     = lf.bed_detected,
            quality          = lf.quality,
        )

        # Echo columns with echo prefix
        for prefix, echo in [("surface", lf.surface), ("bed", lf.bed)]:
            for k, v in asdict(echo).items():
                row[f"{prefix}_{k}"] = v

        # Derived geometry (physical distances)
        if lf.surface_detected:
            row["h_air_m"] = lf.surface.peak_twt_us / 2.0 * C_AIR_M_PER_US
        else:
            row["h_air_m"] = np.nan

        if lf.surface_detected and lf.bed_detected:
            twt_ice        = lf.bed.peak_twt_us - lf.surface.peak_twt_us
            row["h_ice_m"] = twt_ice / 2.0 * C_ICE_M_PER_US
        else:
            row["h_ice_m"] = np.nan

        rows.append(row)

    return pd.DataFrame(rows)


# ===========================================================================
# Navigation & CBD Alignment
# ===========================================================================
#
# Maps LYRA CBD numbers to geographic positions by cross-correlating
# LYRA h_ice against Bingham ICE_THICKN along the Stanford nav track.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_NAV_DIR = _REPO_ROOT / "Navigation_Files"
_BINGHAM_DIR = _NAV_DIR / "Bingham" / "002_nav_data_rgb_corrected"
_RIGGS_CSV = _REPO_ROOT / "Data" / "RIGGS" / "riggs_stations.csv"


def load_stanford_nav(flt: int | str) -> pd.DataFrame:
    """Load Stanford navigation CSV for a flight.

    Returns DataFrame with columns: CBD, LAT, LON, THK, SRF.
    CBD is always equal to the 0-based row index.
    THK/SRF = 9999 means missing.
    """
    flt = str(flt).lstrip("Ff")
    for candidate in [_NAV_DIR / "Stanford" / f"{flt}.csv",
                      _NAV_DIR / f"{flt}.csv"]:
        if candidate.exists():
            df = pd.read_csv(candidate)
            df.columns = df.columns.str.strip()
            return df
    raise FileNotFoundError(
        f"Stanford nav not found for F{flt}: tried "
        f"{_NAV_DIR / 'Stanford' / f'{flt}.csv'} and {_NAV_DIR / f'{flt}.csv'}")


def load_bingham_ice_thickness(flt: int | str) -> pd.DataFrame | None:
    """Load Bingham corrected TXT and return ICE_THICKN indexed by Stanford CBD.

    Steps:
      1. Load Bingham TXT (handles F128 special column format).
      2. Filter to rows with valid ICE_THICKN > 0.
      3. Spatially match each Bingham row to the nearest Stanford nav row.
      4. Return DataFrame with columns: stanford_cbd, ice_thickn, lat, lon, match_km.

    Returns None if the Bingham file doesn't exist or has no valid ICE_THICKN.
    """
    from pyproj import Transformer

    flt_str = str(flt).lstrip("Ff")
    txt_path = _BINGHAM_DIR / f"sprinsftud_1974_{flt_str}_nav.txt"
    if not txt_path.exists():
        return None

    bingham = pd.read_csv(txt_path, sep="\t")
    bingham.columns = bingham.columns.str.strip()

    # Normalize column names (F128 uses different headers)
    if "ICE_THICKN" not in bingham.columns:
        return None

    valid = bingham["ICE_THICKN"].notna() & (bingham["ICE_THICKN"] > 0)
    bingham = bingham[valid].copy()
    if len(bingham) == 0:
        return None

    # Load Stanford nav for spatial matching
    try:
        stanford = load_stanford_nav(flt_str)
    except FileNotFoundError:
        return None

    # Project to EPSG:3031 for spatial matching
    T = Transformer.from_crs("EPSG:4326", "EPSG:3031", always_xy=True)
    from scipy.spatial import cKDTree

    st_x, st_y = T.transform(stanford["LON"].values, stanford["LAT"].values)
    st_xy = np.column_stack([st_x, st_y])

    bg_x, bg_y = T.transform(bingham["LONGITUDE"].values, bingham["LATITUDE"].values)
    bg_xy = np.column_stack([bg_x, bg_y])

    tree = cKDTree(st_xy)
    dists, idxs = tree.query(bg_xy)
    dists_km = dists / 1000.0

    result = pd.DataFrame({
        "stanford_cbd": stanford["CBD"].values[idxs],
        "ice_thickn":   bingham["ICE_THICKN"].values,
        "lat":          bingham["LATITUDE"].values,
        "lon":          bingham["LONGITUDE"].values,
        "match_km":     dists_km,
    })

    # Warn if any matches are far
    far = (result["match_km"] > 5.0).sum()
    if far > 0:
        warnings.warn(f"F{flt_str}: {far}/{len(result)} Bingham points > 5 km "
                      f"from nearest Stanford nav point")

    return result


@dataclass
class AlignmentResult:
    """Result of CBD-to-navigation cross-correlation alignment."""
    flight: int
    offset: int                    # nav_row = lyra_cbd + offset
    correlation: float             # peak Pearson r (best anchor or global)
    n_matched: int                 # LYRA good frames used in best match
    n_reference: int               # total Bingham ICE_THICKN values
    search_range: tuple            # (min_offset, max_offset) searched
    second_best_corr: float        # for confidence assessment
    confidence: str                # "high" / "medium" / "low"
    riggs_validation: dict | None  # RIGGS cross-check results
    n_anchor_windows: int = 0     # number of agreeing anchor windows
    method: str = "global"         # "windowed" or "global" (fallback)


# ---- Rose 1978 Navigation Fix Data (Table 2.2, Table 2.3) ----------------

ROSE_STATIONS = {
    "mcmurdo_skiway":    {"lat": -77.8750, "lon": 166.9133, "alt_m": 10},
    "mcmurdo_ice":       {"lat": -77.8817, "lon": 166.7117, "alt_m": 6},
    "byrd":              {"lat": -80.0103, "lon": -119.5021, "alt_m": 1545},
    "south_pole":        {"lat": -89.9954, "lon": 144.3411, "alt_m": 2830},
    "roosevelt_island":  {"lat": -80.1917, "lon": -161.5617, "alt_m": 80},
}

_ROSE_TABLE_PATH = _REPO_ROOT / "docs" / "ross_table2-3.xlsx"

# Stanford nav files use McMurdo Ice (not Skiway) as their McMurdo reference.
# When comparing Stanford positions to known stations, use these coordinates.
_STANFORD_NAV_STATIONS = {
    "mcmurdo_skiway": {"lat": -77.8817, "lon": 166.7117},  # Stanford uses McMurdo Ice coords
    "mcmurdo_ice":    {"lat": -77.8817, "lon": 166.7117},
    "byrd":           {"lat": -80.0103, "lon": -119.5021},
    "south_pole":     {"lat": -89.9954, "lon": 144.3411},
    "roosevelt_island": {"lat": -80.1917, "lon": -161.5617},
}


def _parse_fix_station(note: str) -> str | None:
    """Extract ROSE_STATIONS key from a Rose Table 2.3 note string.

    Only assigns station coordinates for fixes where the aircraft is AT or
    OVER a known station (overhead passes, terminals). Oblique photos are
    taken from a distance, so the aircraft position != station position.
    """
    note_lower = note.lower()
    is_oblique = "oblique" in note_lower or "oblqiue" in note_lower
    is_overhead = "overhead" in note_lower or "ovehead" in note_lower
    is_terminal = "terminal" in note_lower

    # Oblique photos: aircraft is NOT at the station
    if is_oblique:
        return None

    # Overhead passes: aircraft IS at the station
    if is_overhead:
        if "roosevelt" in note_lower:
            return "roosevelt_island"
        if "byrd" in note_lower:
            return "byrd"
        if "south pole" in note_lower:
            return "south_pole"
        return None

    # Terminal fixes
    if is_terminal:
        # Strip "originated at ..." context — describes origin, not terminal
        # e.g., "terminal (this flight originated at Pole)" = McMurdo terminal
        term_note = note_lower
        for origin_phrase in ["originated at pole", "originated at byrd",
                              "orignated at byrd", "orignated at pole"]:
            term_note = term_note.replace(origin_phrase, "")

        if "roosevelt" in term_note:
            return "roosevelt_island"
        if "byrd" in term_note:
            return "byrd"
        if "south pole" in term_note or "pole" in term_note:
            return "south_pole"
        # Bare "terminal" = McMurdo (resolved by caller)
        return None

    return None


def _parse_flight_origin(fixes: list[tuple]) -> str:
    """Determine flight origin station from fix notes."""
    for _, _, note in fixes:
        if "originated at pole" in note.lower():
            return "south_pole"
        if "originated at byrd" in note.lower() or "orignated at byrd" in note.lower():
            return "byrd"
    return "mcmurdo_skiway"


def load_rose_fixes() -> dict:
    """Load Rose 1978 Table 2.3 from the digitized Excel file.

    Returns dict mapping flight number -> list of (time_minutes, vector_km,
    description, station_key_or_None).

    station_key is a ROSE_STATIONS key for fixes with known coordinates
    (terminal/overhead), or None for oblique photos.
    """
    import pandas as pd

    if not _ROSE_TABLE_PATH.exists():
        warnings.warn(f"Rose Table 2.3 not found: {_ROSE_TABLE_PATH}")
        return {}

    df = pd.read_excel(_ROSE_TABLE_PATH, skiprows=3, header=None,
                       names=["flight", "h", "min", "vector_km", "note"])
    df["flight"] = df["flight"].ffill().astype(int)

    result = {}
    for flt, grp in df.groupby("flight"):
        fixes_raw = []
        for _, row in grp.iterrows():
            time_min = int(row["h"]) * 60 + int(row["min"])
            note = str(row["note"]).strip() if pd.notna(row["note"]) else ""
            fixes_raw.append((time_min, float(row["vector_km"]), note))

        origin = _parse_flight_origin(fixes_raw)

        fixes = []
        for time_min, vector_km, note in fixes_raw:
            station = _parse_fix_station(note)
            # Resolve bare "terminal" to flight origin/destination
            if station is None and "terminal" in note.lower():
                # Terminal = origin for originated-at flights, McMurdo otherwise
                # But terminal is at the END of the flight, so:
                # - flights originating at McMurdo terminate at McMurdo
                #   UNLESS the note says otherwise (e.g., "terminal, Byrd")
                # - flights originating at Byrd/Pole terminate at McMurdo
                #   (all non-McMurdo flights return to McMurdo)
                if origin != "mcmurdo_skiway":
                    station = "mcmurdo_skiway"
                else:
                    station = "mcmurdo_skiway"
            fixes.append((time_min, vector_km, note, station))

        result[flt] = fixes

    return result


def load_rose_flight_origins() -> dict:
    """Return dict mapping flight number -> origin station key."""
    fixes_all = load_rose_fixes()
    origins = {}
    for flt, fixes in fixes_all.items():
        raw = [(t, v, n) for t, v, n, _ in fixes]
        origins[flt] = _parse_flight_origin(raw)
    return origins


@dataclass
class NavCorrection:
    """CBD-varying navigation correction for a flight."""
    flight: int
    fix_cbds: list[int]          # CBD indices of fix points
    dx_at_fixes: list[float]     # x correction (m) in EPSG:3031 at each fix
    dy_at_fixes: list[float]     # y correction (m) in EPSG:3031 at each fix
    fix_descriptions: list[str]  # description of each fix
    assessment: str              # from diagnostics

    def correction_at_cbd(self, cbd) -> tuple:
        """Interpolate (dx, dy) correction in EPSG:3031 metres for given CBD(s).

        Returns (dx, dy) arrays in metres.  Add these to the Stanford
        EPSG:3031 coordinates to get corrected positions.
        """
        cbd = np.atleast_1d(np.asarray(cbd, dtype=float))
        dx = np.interp(cbd, self.fix_cbds, self.dx_at_fixes)
        dy = np.interp(cbd, self.fix_cbds, self.dy_at_fixes)
        return dx, dy


def diagnose_nav_fixes(flt: int | str, verbose: bool = True) -> dict:
    """Compare Stanford nav positions at Rose fix points against known positions.

    For fixes with known station coordinates (terminal fixes, overhead passes),
    computes the residual distance between the Stanford nav position and the
    true station position.  This reveals whether the Stanford nav files already
    incorporate Rose's corrections.

    Parameters
    ----------
    flt : flight number (with or without 'F' prefix)
    verbose : print results to console

    Returns
    -------
    dict with keys: flight, origin, n_nav_cbds, n_fixes, n_diagnosed,
    fixes (list of per-fix dicts), assessment.
    """
    from pyproj import Transformer

    flt_str = str(flt).lstrip("Ff")
    flt_int = int(flt_str)

    all_fixes = load_rose_fixes()
    if flt_int not in all_fixes:
        if verbose:
            print(f"F{flt_str}: no Rose fix data available")
        return {"flight": flt_int, "n_fixes": 0, "assessment": "no_data"}

    fixes = all_fixes[flt_int]
    origins = load_rose_flight_origins()
    origin = origins.get(flt_int, "mcmurdo_skiway")

    try:
        nav = load_stanford_nav(flt_str)
    except FileNotFoundError:
        if verbose:
            print(f"F{flt_str}: Stanford nav file not found")
        return {"flight": flt_int, "n_fixes": len(fixes),
                "assessment": "no_nav"}

    n_nav = len(nav)
    T = Transformer.from_crs("EPSG:4326", "EPSG:3031", always_xy=True)

    results = []
    for time_min, vector_km, desc, station_key in fixes:
        # Convert time to approximate CBD index (20 s per CBD = 3 CBDs/min)
        cbd_approx = int(round(time_min * 3))
        cbd_clamped = min(max(cbd_approx, 0), n_nav - 1)

        # For terminal fixes, use the actual last CBD of the nav file
        is_terminal = "terminal" in desc.lower()
        if is_terminal:
            cbd_clamped = n_nav - 1

        nav_lat = float(nav.iloc[cbd_clamped]["LAT"])
        nav_lon = float(nav.iloc[cbd_clamped]["LON"])

        fix_result = {
            "time_min": time_min,
            "vector_km": vector_km,
            "description": desc,
            "station": station_key,
            "nav_cbd": cbd_clamped,
            "nav_lat": round(nav_lat, 6),
            "nav_lon": round(nav_lon, 6),
            "true_lat": None,
            "true_lon": None,
            "residual_km": None,
        }

        if station_key is not None and station_key in _STANFORD_NAV_STATIONS:
            nx, ny = T.transform(nav_lon, nav_lat)

            # For McMurdo terminals, check both Ice and Skiway references
            if station_key in ("mcmurdo_skiway", "mcmurdo_ice"):
                ice = ROSE_STATIONS["mcmurdo_ice"]
                sky = ROSE_STATIONS["mcmurdo_skiway"]
                ix, iy = T.transform(ice["lon"], ice["lat"])
                sx, sy = T.transform(sky["lon"], sky["lat"])
                d_ice = np.sqrt((nx - ix)**2 + (ny - iy)**2) / 1000.0
                d_sky = np.sqrt((nx - sx)**2 + (ny - sy)**2) / 1000.0
                if d_ice < d_sky:
                    true = ice
                    dist_km = d_ice
                    fix_result["mcmurdo_ref"] = "mcmurdo_ice"
                else:
                    true = sky
                    dist_km = d_sky
                    fix_result["mcmurdo_ref"] = "mcmurdo_skiway"
            else:
                true = _STANFORD_NAV_STATIONS[station_key]
                tx, ty = T.transform(true["lon"], true["lat"])
                dist_km = np.sqrt((nx - tx)**2 + (ny - ty)**2) / 1000.0

            fix_result["true_lat"] = true["lat"]
            fix_result["true_lon"] = true["lon"]
            fix_result["residual_km"] = round(dist_km, 2)

        results.append(fix_result)

    # Assessment
    diagnosed = [r for r in results if r["residual_km"] is not None]
    n_diagnosed = len(diagnosed)

    assessment = "inconclusive"
    if n_diagnosed > 0:
        residuals = [r["residual_km"] for r in diagnosed]
        vectors = [r["vector_km"] for r in diagnosed]
        mean_residual = np.mean(residuals)
        mean_vector = np.mean(vectors)

        if mean_residual < 2.0:
            assessment = "likely_corrected"
        elif mean_residual > 0.5 * mean_vector:
            assessment = "likely_uncorrected"
        else:
            assessment = "partially_corrected"

    result = {
        "flight": flt_int,
        "origin": origin,
        "n_nav_cbds": n_nav,
        "n_fixes": len(fixes),
        "n_diagnosed": n_diagnosed,
        "fixes": results,
        "assessment": assessment,
    }

    if verbose:
        print(f"\nF{flt_str} Navigation Fix Diagnostics")
        print(f"  Origin: {origin} | Nav CBDs: {n_nav} | "
              f"Fixes: {len(fixes)} ({n_diagnosed} with known coords)")
        print(f"  {'Time':>6s}  {'CBD':>5s}  {'Rose km':>8s}  "
              f"{'Residual':>9s}  Description")
        print(f"  {'----':>6s}  {'---':>5s}  {'-------':>8s}  "
              f"{'--------':>9s}  -----------")
        for r in results:
            resid_str = (f"{r['residual_km']:8.2f}" if r["residual_km"] is not None
                         else "     N/A")
            mc_ref = r.get("mcmurdo_ref", "")
            mc_tag = f" [{mc_ref}]" if mc_ref else ""
            t = r["time_min"]
            print(f"  {t//60:2d}h{t%60:02d}m  {r['nav_cbd']:5d}  "
                  f"{r['vector_km']:8.1f}  {resid_str}  "
                  f"{r['description']}{mc_tag}")
        print(f"\n  Assessment: {assessment}")

    return result


def diagnose_all_nav_fixes(verbose: bool = True) -> dict:
    """Run diagnose_nav_fixes for all flights with Rose fix data.

    Returns dict mapping flight number to diagnostic result.
    """
    all_fixes = load_rose_fixes()
    all_results = {}
    for flt in sorted(all_fixes.keys()):
        try:
            r = diagnose_nav_fixes(flt, verbose=verbose)
            all_results[flt] = r
        except Exception as e:
            if verbose:
                print(f"F{flt}: ERROR - {e}")
            all_results[flt] = {"flight": flt, "assessment": "error",
                                "error": str(e)}
        if verbose:
            print()
    return all_results


def build_nav_correction(flt: int | str) -> NavCorrection | None:
    """Build a CBD-varying position correction from Rose fix diagnostics.

    Computes the error vector (true minus Stanford) at each fix point with
    known coordinates, then builds a piecewise-linear correction that can
    be interpolated at any CBD.

    Returns None if no fixes with known coordinates exist.
    """
    from pyproj import Transformer

    diag = diagnose_nav_fixes(flt, verbose=False)
    if diag.get("assessment") in ("no_data", "no_nav", "error"):
        return None

    flt_int = diag["flight"]
    origin = diag["origin"]

    T = Transformer.from_crs("EPSG:4326", "EPSG:3031", always_xy=True)
    nav = load_stanford_nav(flt_int)

    fix_cbds = []
    dx_list = []
    dy_list = []
    descs = []

    # Determine which McMurdo reference this flight's nav file uses
    # by checking the terminal fix from the diagnostic
    mcmurdo_ref = "mcmurdo_skiway"  # default
    for fix in diag["fixes"]:
        if fix.get("mcmurdo_ref"):
            mcmurdo_ref = fix["mcmurdo_ref"]
            break

    def _get_true_coords(station_key):
        """Get true coordinates, using the correct McMurdo reference."""
        if station_key in ("mcmurdo_skiway", "mcmurdo_ice"):
            return ROSE_STATIONS[mcmurdo_ref]
        return ROSE_STATIONS[station_key]

    # Add origin as first fix point (CBD 0 = known station)
    # Only if CBD 0 is actually near the origin station (< 10 km)
    if origin in _STANFORD_NAV_STATIONS:
        true = _get_true_coords(origin)
        nav_lat = float(nav.iloc[0]["LAT"])
        nav_lon = float(nav.iloc[0]["LON"])
        nx, ny = T.transform(nav_lon, nav_lat)
        tx, ty = T.transform(true["lon"], true["lat"])
        origin_dist_km = np.sqrt((nx - tx)**2 + (ny - ty)**2) / 1000.0
        if origin_dist_km < 10.0:
            fix_cbds.append(0)
            dx_list.append(tx - nx)
            dy_list.append(ty - ny)
            descs.append(f"origin: {origin} [{mcmurdo_ref}]")

    # Add diagnosed fixes with known station coords
    for fix in diag["fixes"]:
        if fix["residual_km"] is None or fix["station"] is None:
            continue
        cbd = fix["nav_cbd"]
        true = _get_true_coords(fix["station"])
        nx, ny = T.transform(fix["nav_lon"], fix["nav_lat"])
        tx, ty = T.transform(true["lon"], true["lat"])
        fix_cbds.append(cbd)
        dx_list.append(tx - nx)
        dy_list.append(ty - ny)
        descs.append(fix["description"])

    if len(fix_cbds) < 1:
        return None

    # Deduplicate: keep last entry for each CBD
    seen = {}
    for i, cbd in enumerate(fix_cbds):
        seen[cbd] = i
    unique_idxs = sorted(seen.values(), key=lambda i: fix_cbds[i])
    fix_cbds = [fix_cbds[i] for i in unique_idxs]
    dx_list = [dx_list[i] for i in unique_idxs]
    dy_list = [dy_list[i] for i in unique_idxs]
    descs = [descs[i] for i in unique_idxs]

    return NavCorrection(
        flight=flt_int,
        fix_cbds=fix_cbds,
        dx_at_fixes=dx_list,
        dy_at_fixes=dy_list,
        fix_descriptions=descs,
        assessment=diag["assessment"],
    )


def save_nav_correction(corr: NavCorrection, out_dir: Path) -> Path:
    """Save NavCorrection to JSON."""
    import json
    val_dir = out_dir / "validation"
    val_dir.mkdir(parents=True, exist_ok=True)
    out_path = val_dir / f"F{corr.flight}_nav_correction.json"
    d = {
        "flight": corr.flight,
        "fix_cbds": corr.fix_cbds,
        "dx_at_fixes": [round(x, 1) for x in corr.dx_at_fixes],
        "dy_at_fixes": [round(y, 1) for y in corr.dy_at_fixes],
        "fix_descriptions": corr.fix_descriptions,
        "assessment": corr.assessment,
    }
    with open(out_path, "w") as f:
        json.dump(d, f, indent=2)
    return out_path


def load_nav_correction(flt: int | str,
                        out_dir: Path | None = None) -> NavCorrection | None:
    """Load a previously saved NavCorrection from JSON."""
    import json
    flt_str = str(flt).lstrip("Ff")
    if out_dir is None:
        out_dir = _REPO_ROOT / "output" / f"F{flt_str}"
    json_path = out_dir / "validation" / f"F{flt_str}_nav_correction.json"
    if not json_path.exists():
        return None
    with open(json_path) as f:
        d = json.load(f)
    return NavCorrection(**d)


def _xcorr_at_offset(lyra_cbd, lyra_hice, ref_lookup, offset, min_pairs=10):
    """Compute Pearson r for a single offset. Returns (r, n_pairs)."""
    shifted = lyra_cbd + offset
    pl, pr = [], []
    for i, sc in enumerate(shifted):
        if sc in ref_lookup and np.isfinite(lyra_hice[i]):
            pl.append(lyra_hice[i])
            pr.append(ref_lookup[sc])
    n = len(pl)
    if n < min_pairs:
        return -9999.0, n
    pl, pr = np.array(pl), np.array(pr)
    if np.std(pl) < 1e-6 or np.std(pr) < 1e-6:
        return 0.0, n
    return float(np.corrcoef(pl, pr)[0, 1]), n


def _windowed_xcorr(
    lyra_cbd: np.ndarray,
    lyra_hice: np.ndarray,
    ref_lookup: dict,
    search_range: tuple = (-200, 200),
    window_size: int = 40,
    window_step: int = 10,
    min_std_m: float = 30.0,
    min_pairs: int = 10,
    min_r: float = 0.7,
) -> list[dict]:
    """Find anchor windows where local h_ice cross-correlation is strong.

    Slides a window across the sorted LYRA CBD sequence. In each window,
    scans all offsets and keeps windows with high correlation and sufficient
    ice-thickness variation.

    Returns list of anchor dicts sorted by r descending.
    """
    # Sort by CBD
    order = np.argsort(lyra_cbd)
    cbd_s = lyra_cbd[order]
    hice_s = lyra_hice[order]
    n_total = len(cbd_s)

    anchors = []

    for start in range(0, n_total - min_pairs, window_step):
        end = min(start + window_size, n_total)
        w_cbd = cbd_s[start:end]
        w_hice = hice_s[start:end]

        # Skip windows with insufficient terrain variation
        valid = np.isfinite(w_hice)
        if valid.sum() < min_pairs:
            continue
        if np.std(w_hice[valid]) < min_std_m:
            continue

        # Scan offsets for this window
        best_off, best_r, best_n = 0, -9999.0, 0
        second_r = -9999.0

        for off in range(search_range[0], search_range[1] + 1):
            r, n = _xcorr_at_offset(w_cbd, w_hice, ref_lookup, off, min_pairs)
            if r > best_r:
                # Update second-best before overwriting best
                if abs(off - best_off) >= 5:
                    second_r = best_r
                best_off, best_r, best_n = off, r, n
            elif r > second_r and abs(off - best_off) >= 5:
                second_r = r

        if best_r >= min_r and best_n >= min_pairs:
            anchors.append({
                "cbd_center": int(np.median(w_cbd)),
                "offset": best_off,
                "r": round(best_r, 4),
                "n_pairs": best_n,
                "lyra_std": round(float(np.std(w_hice[valid])), 1),
                "second_r": round(second_r, 4) if second_r > -9000 else -1.0,
            })

    # Sort by correlation descending
    anchors.sort(key=lambda a: a["r"], reverse=True)
    return anchors


def align_cbd_to_nav(
    echoes_csv: Path | str | pd.DataFrame,
    flt: int | str,
    search_range: tuple = (-200, 200),
    min_matched: int = 15,
) -> AlignmentResult:
    """Find optimal CBD offset using windowed cross-correlation with track propagation.

    Uses a two-stage approach:
      1. Windowed cross-correlation: slides a 40-CBD window along the LYRA
         h_ice profile, correlating against Bingham ICE_THICKN at each offset.
         Windows with strong terrain variation (std > 30 m) and high correlation
         (r > 0.7) become "anchor windows."
      2. Offset consensus: if multiple anchors agree on the same offset (within
         +/-2), that offset is adopted with high confidence. Even on flights with
         mostly flat ice, a single terrain-rich segment can anchor the entire
         flight thanks to the confirmed 1:1 CBD-to-waypoint ratio.

    Falls back to global correlation and RIGGS tiebreaking when no anchors found.

    The offset means: Stanford nav row index = LYRA CBD + offset.

    Parameters
    ----------
    echoes_csv : path to phase 4 echoes CSV, or a pre-loaded DataFrame
    flt : flight number
    search_range : (min_offset, max_offset) to test
    min_matched : minimum number of matched pairs for global correlation

    Returns
    -------
    AlignmentResult with offset, correlation, confidence, RIGGS validation,
    anchor window count, and method used.
    """
    flt_str = str(flt).lstrip("Ff")
    flt_int = int(flt_str)

    def _empty(conf="low"):
        return AlignmentResult(
            flight=flt_int, offset=0, correlation=0.0,
            n_matched=0, n_reference=0, search_range=search_range,
            second_best_corr=0.0, confidence=conf, riggs_validation=None)

    # Load LYRA echoes
    if isinstance(echoes_csv, pd.DataFrame):
        echoes = echoes_csv
    else:
        echoes = pd.read_csv(echoes_csv)
        echoes.columns = echoes.columns.str.strip()

    good = echoes[echoes["echo_status"] == "good"].copy()
    if len(good) == 0:
        return _empty()

    lyra_cbd = good["cbd"].astype(int).values
    lyra_hice = good["h_ice_m"].values

    # Load Bingham ICE_THICKN indexed by Stanford CBD
    bingham = load_bingham_ice_thickness(flt_str)
    if bingham is None or len(bingham) == 0:
        return _empty()

    ref_lookup = bingham.groupby("stanford_cbd")["ice_thickn"].mean().to_dict()

    # ---- Stage 1: windowed cross-correlation --------------------------------
    anchors = _windowed_xcorr(lyra_cbd, lyra_hice, ref_lookup, search_range)

    # ---- Stage 2: offset consensus from anchor windows ----------------------
    consensus_offset = None
    consensus_n = 0
    consensus_r = 0.0

    if anchors:
        # Group anchors by offset (within +/-2 tolerance)
        from collections import Counter
        offset_votes: dict[int, int] = {}
        offset_best_r: dict[int, float] = {}

        for a in anchors:
            off = a["offset"]
            # Find existing cluster within +/-2
            matched_key = None
            for existing in offset_votes:
                if abs(off - existing) <= 2:
                    matched_key = existing
                    break
            if matched_key is not None:
                offset_votes[matched_key] += 1
                offset_best_r[matched_key] = max(offset_best_r[matched_key], a["r"])
            else:
                offset_votes[off] = 1
                offset_best_r[off] = a["r"]

        # Pick offset with most votes, break ties by best r
        consensus_offset = max(offset_votes,
                               key=lambda o: (offset_votes[o], offset_best_r[o]))
        consensus_n = offset_votes[consensus_offset]
        consensus_r = offset_best_r[consensus_offset]

    # ---- Stage 3: global correlation as fallback ----------------------------
    global_r, global_n = _xcorr_at_offset(
        lyra_cbd, lyra_hice, ref_lookup, 0, min_matched)
    # Also find the global best offset
    best_global_off, best_global_r, best_global_n = 0, global_r, global_n
    # Quick scan: only test offsets near anchor consensus and at 0
    scan_offsets = set(range(search_range[0], search_range[1] + 1))
    for off in scan_offsets:
        r, n = _xcorr_at_offset(lyra_cbd, lyra_hice, ref_lookup, off, min_matched)
        if r > best_global_r:
            best_global_off, best_global_r, best_global_n = off, r, n

    # Second-best global (at least 5 away from best)
    second_global_r = -1.0
    for off in sorted(scan_offsets, key=lambda o: -_xcorr_at_offset(
            lyra_cbd, lyra_hice, ref_lookup, o, min_matched)[0]):
        if abs(off - best_global_off) >= 5:
            r, _ = _xcorr_at_offset(lyra_cbd, lyra_hice, ref_lookup, off, min_matched)
            if r > -9000:
                second_global_r = r
                break

    # ---- Stage 4: terrain-weighted windowed consensus -------------------------
    # Weight anchor votes by terrain richness (lyra_std) and peak sharpness
    # (r - second_r).  Flat-ice windows have high r but tiny gap to 2nd-best,
    # meaning offset is ambiguous there.  Terrain-rich windows with a clear
    # peak are far more informative.
    terrain_consensus_off = None
    terrain_consensus_n = 0
    terrain_consensus_r = 0.0

    if anchors:
        from collections import defaultdict
        offset_weight: dict[int, float] = defaultdict(float)
        offset_count: dict[int, int] = defaultdict(int)
        offset_best_r2: dict[int, float] = defaultdict(float)

        for a in anchors:
            off = a["offset"]
            gap = a["r"] - max(a["second_r"], 0)
            weight = a["lyra_std"] * gap  # terrain richness x peak sharpness

            # Find existing cluster within +/-2
            matched_key = None
            for existing in list(offset_weight):
                if abs(off - existing) <= 2:
                    matched_key = existing
                    break
            key = matched_key if matched_key is not None else off
            offset_weight[key] += weight
            offset_count[key] += 1
            offset_best_r2[key] = max(offset_best_r2[key], a["r"])

        # Pick offset with highest total weight
        terrain_consensus_off = max(offset_weight,
                                    key=lambda o: offset_weight[o])
        terrain_consensus_n = offset_count[terrain_consensus_off]
        terrain_consensus_r = offset_best_r2[terrain_consensus_off]

    # ---- Stage 5: RIGGS-arbitrated decision ---------------------------------
    # Collect all candidate offsets and pick the one with lowest RIGGS RMSE.
    # If RIGGS is unavailable or insufficient, fall back to terrain-weighted
    # consensus, then global correlation, then offset=0.
    candidates = {0}
    if terrain_consensus_off is not None:
        candidates.add(terrain_consensus_off)
    if best_global_off != 0:
        candidates.add(best_global_off)

    # Evaluate RIGGS at each candidate
    riggs_results = {}
    for cand in candidates:
        rv = _riggs_validate(lyra_cbd, lyra_hice, flt_str, cand)
        riggs_results[cand] = rv

    # Pick candidate with lowest RIGGS RMSE (if >= 3 stations available)
    has_riggs = any(
        rv and rv.get("n_stations", 0) >= 3
        for rv in riggs_results.values()
    )

    chosen_offset = 0
    confidence = "low"
    method = "global"
    n_anchor = 0
    report_r = best_global_r
    report_n = best_global_n

    if has_riggs:
        # RIGGS arbitrates between candidates
        best_rmse = 9999.0
        for cand in candidates:
            rv = riggs_results[cand]
            rmse = (rv.get("rmse_m", 9999)
                    if rv and rv.get("n_stations", 0) >= 3 else 9999)
            if rmse < best_rmse:
                best_rmse = rmse
                chosen_offset = cand

        if chosen_offset != 0 and chosen_offset == terrain_consensus_off:
            method = "windowed"
            n_anchor = terrain_consensus_n
            report_r = terrain_consensus_r
        elif chosen_offset != 0 and chosen_offset == best_global_off:
            method = "global"
            report_r = best_global_r

        # Confidence based on RMSE and method
        if best_rmse < 100:
            confidence = "high"
        elif best_rmse < 200:
            confidence = "medium"
        else:
            confidence = "low"
    else:
        # No RIGGS: rely on windowed consensus or global correlation
        if (terrain_consensus_off is not None
                and terrain_consensus_n >= 3
                and terrain_consensus_r >= 0.8):
            chosen_offset = terrain_consensus_off
            confidence = "high"
            method = "windowed"
            n_anchor = terrain_consensus_n
            report_r = terrain_consensus_r
        elif best_global_r > 0.8 and best_global_n >= 30:
            chosen_offset = best_global_off
            confidence = "medium"
            method = "global"
        # else: offset=0, low confidence (default)

    # ---- Stage 6: track-geometry sanity check -------------------------------
    try:
        nav = load_stanford_nav(flt_str)
        nav_cbds = lyra_cbd + chosen_offset
        valid_mask = (nav_cbds >= 0) & (nav_cbds < len(nav))
        if valid_mask.sum() >= 2:
            from pyproj import Transformer
            _T = Transformer.from_crs("EPSG:4326", "EPSG:3031", always_xy=True)
            lats = nav["LAT"].values[nav_cbds[valid_mask]]
            lons = nav["LON"].values[nav_cbds[valid_mask]]
            x, y = _T.transform(lons, lats)
            dists_km = np.sqrt(np.diff(x)**2 + np.diff(y)**2) / 1000.0
            n_jumps = (dists_km > 10.0).sum()
            if n_jumps > len(dists_km) * 0.1:
                confidence = "low"  # discontinuous track -> downgrade
    except FileNotFoundError:
        pass

    # ---- Stage 7: RIGGS validation at chosen offset -------------------------
    riggs_val = riggs_results.get(chosen_offset)
    if riggs_val is None:
        riggs_val = _riggs_validate(lyra_cbd, lyra_hice, flt_str, chosen_offset)

    return AlignmentResult(
        flight=flt_int,
        offset=chosen_offset,
        correlation=round(report_r, 4),
        n_matched=report_n if method == "global" else (
            anchors[0]["n_pairs"] if anchors else 0),
        n_reference=len(bingham),
        search_range=search_range,
        second_best_corr=round(second_global_r, 4),
        confidence=confidence,
        riggs_validation=riggs_val,
        n_anchor_windows=n_anchor,
        method=method,
    )


def _riggs_validate(lyra_cbd, lyra_hice, flt_str, offset,
                    match_radius_km=50) -> dict | None:
    """Cross-check alignment offset against RIGGS stations."""
    import re as _re
    from scipy.spatial import cKDTree
    from pyproj import Transformer

    if not _RIGGS_CSV.exists():
        return None

    riggs = pd.read_csv(_RIGGS_CSV)

    # Parse DMS coordinates
    def _dms(s):
        s = str(s).strip().strip('"').strip("'")
        m = _re.match(r'(\d+)\D+(\d+)\D+(\d+)["\']?\s*([NSEW])', s)
        if not m:
            return float("nan")
        dd = int(m.group(1)) + int(m.group(2)) / 60.0 + int(m.group(3)) / 3600.0
        if m.group(4) in ("S", "W"):
            dd = -dd
        return dd

    riggs["lat_dd"] = riggs["Latitude"].apply(_dms)
    riggs["lon_dd"] = riggs["Longitude"].apply(_dms)
    valid_riggs = riggs.dropna(subset=["lat_dd", "lon_dd"])

    # Get RIGGS h_ice (prefer seismic)
    h_col_seis = "h_i (seismics), m"
    h_col_radar = "h_i (radar), m"
    riggs_hice = []
    for _, r in valid_riggs.iterrows():
        h = r.get(h_col_seis)
        if pd.isna(h) or h == "" or (isinstance(h, str) and not h.strip()):
            h = r.get(h_col_radar)
        try:
            riggs_hice.append(float(h))
        except (TypeError, ValueError):
            riggs_hice.append(np.nan)
    valid_riggs = valid_riggs.copy()
    valid_riggs["h_ice"] = riggs_hice
    valid_riggs = valid_riggs[valid_riggs["h_ice"].notna()].copy()

    if len(valid_riggs) == 0:
        return None

    # Get LYRA positions using offset
    try:
        nav = load_stanford_nav(flt_str)
    except FileNotFoundError:
        return None

    T = Transformer.from_crs("EPSG:4326", "EPSG:3031", always_xy=True)

    # LYRA positions
    nav_cbds = lyra_cbd + offset
    valid_mask = (nav_cbds >= 0) & (nav_cbds < len(nav))
    if valid_mask.sum() == 0:
        return None

    lyra_lats = nav["LAT"].values[nav_cbds[valid_mask]]
    lyra_lons = nav["LON"].values[nav_cbds[valid_mask]]
    lyra_h = lyra_hice[valid_mask]
    lx, ly = T.transform(lyra_lons, lyra_lats)
    lyra_xy = np.column_stack([lx, ly])

    # RIGGS positions
    rx, ry = T.transform(valid_riggs["lon_dd"].values, valid_riggs["lat_dd"].values)
    riggs_xy = np.column_stack([rx, ry])

    # Match each RIGGS station to nearest LYRA frame
    tree = cKDTree(lyra_xy)
    dists, idxs = tree.query(riggs_xy)
    dists_km = dists / 1000.0

    matched = dists_km < match_radius_km
    if not matched.any():
        return {"n_stations": 0}

    diffs = []
    stations = []
    for i in np.where(matched)[0]:
        h_riggs = valid_riggs.iloc[i]["h_ice"]
        h_lyra = lyra_h[idxs[i]]
        if np.isfinite(h_lyra) and np.isfinite(h_riggs):
            diffs.append(h_lyra - h_riggs)
            stations.append(valid_riggs.iloc[i]["Station"])

    if not diffs:
        return {"n_stations": 0}

    diffs = np.array(diffs)
    return {
        "n_stations": len(diffs),
        "stations": stations,
        "mean_diff_m": round(float(np.mean(diffs)), 1),
        "median_diff_m": round(float(np.median(diffs)), 1),
        "rmse_m": round(float(np.sqrt(np.mean(diffs**2))), 1),
    }


def get_nav_positions(
    cbd_array,
    flt: int | str,
    offset: int = 0,
    nav_correction: NavCorrection | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Look up lat/lon positions for an array of CBDs with a CBD offset.

    Parameters
    ----------
    cbd_array : array-like of LYRA CBD numbers
    flt : flight number
    offset : nav_row = lyra_cbd + offset
    nav_correction : optional piecewise-linear position correction from
        Rose 1978 fix data.  When provided, corrects INS drift at each CBD.

    Returns
    -------
    lats, lons : arrays of latitude/longitude (NaN where out of range)
    """
    from pyproj import Transformer

    nav = load_stanford_nav(flt)
    cbd_array = np.asarray(cbd_array, dtype=int)
    nav_idx = cbd_array + offset

    lats = np.full(len(cbd_array), np.nan)
    lons = np.full(len(cbd_array), np.nan)

    valid = (nav_idx >= 0) & (nav_idx < len(nav))
    lats[valid] = nav["LAT"].values[nav_idx[valid]]
    lons[valid] = nav["LON"].values[nav_idx[valid]]

    # Apply Rose 1978 piecewise-linear nav correction if provided
    if nav_correction is not None and np.any(valid):
        T_fwd = Transformer.from_crs("EPSG:4326", "EPSG:3031", always_xy=True)
        T_inv = Transformer.from_crs("EPSG:3031", "EPSG:4326", always_xy=True)

        v_lats = lats[valid]
        v_lons = lons[valid]
        v_nav_idx = nav_idx[valid]

        # Project to EPSG:3031, apply correction, project back
        x_ps, y_ps = T_fwd.transform(v_lons, v_lats)
        dx, dy = nav_correction.correction_at_cbd(v_nav_idx)
        x_corr = x_ps + dx
        y_corr = y_ps + dy
        lon_corr, lat_corr = T_inv.transform(x_corr, y_corr)

        lats[valid] = lat_corr
        lons[valid] = lon_corr

    return lats, lons


def save_alignment(result: AlignmentResult, out_dir: Path) -> Path:
    """Save alignment result to JSON."""
    import json
    val_dir = out_dir / "validation"
    val_dir.mkdir(parents=True, exist_ok=True)
    out_path = val_dir / f"F{result.flight}_alignment.json"
    d = {
        "flight": result.flight,
        "offset": result.offset,
        "correlation": result.correlation,
        "n_matched": result.n_matched,
        "n_reference": result.n_reference,
        "search_range": list(result.search_range),
        "second_best_corr": result.second_best_corr,
        "confidence": result.confidence,
        "riggs_validation": result.riggs_validation,
        "n_anchor_windows": result.n_anchor_windows,
        "method": result.method,
    }
    with open(out_path, "w") as f:
        json.dump(d, f, indent=2)
    return out_path


def load_alignment(flt: int | str, out_dir: Path | None = None) -> AlignmentResult | None:
    """Load a previously computed alignment result from JSON.

    Returns None if no alignment file exists.
    """
    import json
    flt_str = str(flt).lstrip("Ff")
    if out_dir is None:
        out_dir = _REPO_ROOT / "output" / f"F{flt_str}"
    json_path = out_dir / "validation" / f"F{flt_str}_alignment.json"
    if not json_path.exists():
        return None
    with open(json_path) as f:
        d = json.load(f)
    return AlignmentResult(
        flight=d["flight"],
        offset=d["offset"],
        correlation=d["correlation"],
        n_matched=d["n_matched"],
        n_reference=d["n_reference"],
        search_range=tuple(d["search_range"]),
        second_best_corr=d["second_best_corr"],
        confidence=d["confidence"],
        riggs_validation=d.get("riggs_validation"),
        n_anchor_windows=d.get("n_anchor_windows", 0),
        method=d.get("method", "global"),
    )


def enrich_echoes_with_nav(flt: int | str,
                           echoes_csv: Path | str | None = None,
                           offset: int | None = None,
                           nav_correction: NavCorrection | None = None) -> Path:
    """Add lat/lon columns to a flight's echoes CSV using the alignment offset.

    If *offset* is None, loads the alignment JSON for the flight.
    If *nav_correction* is provided, applies Rose 1978 piecewise-linear
    position correction to compensate for INS drift.
    Overwrites the echoes CSV in-place with the new columns.

    Returns the path to the updated CSV.
    """
    flt_str = str(flt).lstrip("Ff")
    if echoes_csv is None:
        echoes_csv = (_REPO_ROOT / "output"
                      / f"F{flt_str}" / "phase4" / f"F{flt_str}_echoes.csv")
    echoes_csv = Path(echoes_csv)
    df = pd.read_csv(echoes_csv)
    df.columns = df.columns.str.strip()

    if offset is None:
        alignment = load_alignment(flt_str)
        if alignment is None:
            raise FileNotFoundError(
                f"No alignment JSON for F{flt_str}. Run validate_flight.py first.")
        offset = alignment.offset

    cbd_valid = df["cbd"].notna()
    cbds = df.loc[cbd_valid, "cbd"].astype(int).values
    lats_v, lons_v = get_nav_positions(cbds, flt_str, offset,
                                       nav_correction=nav_correction)

    # Drop existing lat/lon columns if present (will re-insert)
    df = df.drop(columns=["lat", "lon"], errors="ignore")

    # Insert lat/lon right before mb_x
    mb_idx = df.columns.get_loc("mb_x")
    lat_col = np.full(len(df), np.nan)
    lon_col = np.full(len(df), np.nan)
    lat_col[cbd_valid.values] = np.round(lats_v, 6)
    lon_col[cbd_valid.values] = np.round(lons_v, 6)
    df.insert(mb_idx, "lon", lon_col)
    df.insert(mb_idx, "lat", lat_col)

    df.to_csv(echoes_csv, index=False)
    return echoes_csv
