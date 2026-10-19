#!/usr/bin/env python3
"""LYRA flight-level orchestrator.

Batch-processes all TIFFs for a single flight through the full LYRA pipeline:

  Phase 1: Frame Detection + CBD Assignment
  Phase 2: Pick Calibration — interactive M+R+X picks (flight mode)
  Phase 3: Per-Frame Calibration + Quality Review (GOOD/CHECK flags)
  Phase 4: Echo Extraction
  Phase 5: Validation — BEDMAP1 comparison + flight summary

Usage:
    python codes/run_flight.py <flight_number>
    python codes/run_flight.py 126 --method segment
    python codes/run_flight.py 126 --resume-from 3
    python codes/run_flight.py 126 --skip-picks
    python codes/run_flight.py 137 --cbd-start 7600:300
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# -- Paths --------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
DETECT_SCRIPT   = ROOT / "codes/detect_frames.py"
PICK_SCRIPT     = ROOT / "codes/pick_calibration.py"
CALIBRATE_SCRIPT = ROOT / "codes/calibrate.py"
ECHOES_SCRIPT   = ROOT / "codes/echoes.py"
VALIDATE_SCRIPT = ROOT / "codes/validate_flight.py"
PICKS_DIR = ROOT / "picks"


# -- Utility ------------------------------------------------------------------

def _tiff_id(path: Path) -> int:
    """Extract numeric TIFF start number from canonical filename.

    Example: 47_0002525_0002549-reel_begin_end.tiff -> 2525
    """
    parts = path.stem.split("_")
    if len(parts) >= 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return 0


def discover_tiffs(raw_dir: Path) -> list[Path]:
    """Find all .tiff files in a flight's raw directory, sorted by tiff_id."""
    tiffs = sorted(raw_dir.glob("*.tiff"), key=_tiff_id)
    return tiffs


def get_astra_coverage(flt: int) -> dict[str, list[int]]:
    """Read CombinedASTRAPicks.csv and return {tiff_stem: [cbd1, cbd2, ...]}."""
    csv_path = PICKS_DIR / str(flt) / f"{flt}_CombinedASTRAPicks.csv"
    if not csv_path.exists():
        return {}
    df = pd.read_csv(csv_path)
    coverage = {}
    for stem, grp in df.groupby("filename"):
        cbds = sorted(grp["CBD"].dropna().astype(int).tolist())
        coverage[stem] = cbds
    return coverage


def check_tiff_in_csv(tiff_name: str, csv_path: Path) -> bool:
    """Check if a TIFF already has rows in a phase output CSV."""
    if not csv_path.exists():
        return False
    df = pd.read_csv(csv_path, dtype=str, usecols=["tiff"])
    df["tiff"] = df["tiff"].str.strip()
    return tiff_name in df["tiff"].values


def _run_step(script: Path, tiff_path: Path, extra_args: list[str] | None = None,
              ) -> subprocess.CompletedProcess:
    """Run a LYRA phase script via subprocess."""
    cmd = [sys.executable, str(script), str(tiff_path)]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def _pause(msg: str = "Press ENTER to continue ..."):
    """Pause and wait for user input."""
    try:
        input(f"\n  {msg} ")
    except (EOFError, KeyboardInterrupt):
        print("\n  Interrupted.")
        sys.exit(1)


# -- Phase 1: Frame Detection ------------------------------------------------

def _count_complete_frames(tiff_name: str, index_csv: Path) -> int:
    """Count complete frames for a TIFF from the frame index CSV."""
    if not index_csv.exists():
        return 0
    df = pd.read_csv(index_csv, dtype=str)
    df.columns = df.columns.str.strip()
    tiff_rows = df[df["tiff"].str.strip() == tiff_name]
    return int((tiff_rows["frame_type"].str.strip() == "complete").sum())


def run_phase1(flt: int, tiffs: list[Path], method: str, out_dir: Path,
               cbd_start_map: dict[int, int] | None = None):
    """Run frame detection on all TIFFs, print CBD lookup table."""

    index_csv = out_dir / "phase1" / f"F{flt}_frame_index.csv"
    astra = get_astra_coverage(flt) if method == "manual" else {}
    if cbd_start_map is None:
        cbd_start_map = {}

    # Track next CBD for propagation
    next_cbd: int | None = None

    success, failed, skipped = [], [], []

    for i, tiff in enumerate(tiffs, 1):
        tid = _tiff_id(tiff)

        # Propagate cbd_start: explicit map entry takes priority, else use
        # the running next_cbd from the previous TIFF
        tiff_cbd_start: int | None = None
        if tid in cbd_start_map:
            tiff_cbd_start = cbd_start_map[tid]
        elif next_cbd is not None:
            tiff_cbd_start = next_cbd

        # Skip if already processed
        if check_tiff_in_csv(tiff.name, index_csv):
            skipped.append(tiff)
            # Still propagate: count complete frames to keep next_cbd correct
            if tiff_cbd_start is not None:
                n_complete = _count_complete_frames(tiff.name, index_csv)
                next_cbd = tiff_cbd_start + n_complete
            print(f"  [{i:>2}/{len(tiffs)}]  {tid:>5}  [skip]")
            continue

        # Determine method for this TIFF
        tiff_method = method
        extra = ["--method", method]
        if method == "manual" and tiff.stem not in astra:
            tiff_method = "segment"
            extra = ["--method", "segment"]

        # If cbd_start is known, override OCR entirely
        if tiff_cbd_start is not None:
            extra = ["--cbd-start", str(tiff_cbd_start)]
            tiff_method = "cbd-start"

        result = _run_step(DETECT_SCRIPT, tiff, extra)
        if result.returncode == 0:
            success.append(tiff)
            # Extract per-TIFF frame count from stdout
            n_frames = 0
            for line in result.stdout.splitlines():
                if "Frames" in line and "detected" in line:
                    try:
                        n_frames = int(line.split(":")[1].split("detected")[0].strip())
                    except (ValueError, IndexError):
                        pass
            # Propagate next CBD from complete frame count
            if tiff_cbd_start is not None:
                n_complete = _count_complete_frames(tiff.name, index_csv)
                next_cbd = tiff_cbd_start + n_complete
            note = ""
            if tiff_cbd_start is not None:
                note = f"  (cbd-start={tiff_cbd_start})"
            elif method == "manual" and tiff_method == "segment":
                note = "  (no ASTRA)"
            print(f"  [{i:>2}/{len(tiffs)}]  {tid:>5}  [{n_frames:>3} fr]  {tiff_method}{note}")
        else:
            err_line = (result.stderr + result.stdout).strip().split("\n")[-1]
            failed.append((tiff, err_line))
            print(f"  [{i:>2}/{len(tiffs)}]  {tid:>5}  \033[31m[FAIL]\033[0m {err_line[:60]}")
            # On failure, stop propagation — don't guess
            if tiff_cbd_start is not None:
                next_cbd = None

    # Print summary
    print(f"\n  Phase 1 summary: {len(success)} new, {len(skipped)} skipped, {len(failed)} failed")
    if failed:
        print("\n  Failed TIFFs:")
        for t, msg in failed:
            print(f"    {t.name}: {msg[:100]}")

    # Print CBD lookup table
    print_cbd_table(flt, out_dir)


def print_cbd_table(flt: int, out_dir: Path):
    """Pretty-print TIFF -> CBD mapping from the frame index."""
    index_csv = out_dir / "phase1" / f"F{flt}_frame_index.csv"
    if not index_csv.exists():
        print("  (no frame index found)")
        return

    df = pd.read_csv(index_csv)
    df.columns = df.columns.str.strip()

    print(f"\n  {'TIFF ID':>7}  {'CBD Range':>12}  {'Frames':>6}  TIFF Filename")
    print(f"  {'-'*7}  {'-'*12}  {'-'*6}  {'-'*50}")

    for tid, grp in df.groupby("tiff_id", sort=True):
        tiff_name = grp["tiff"].iloc[0]
        cbds = grp["cbd"].dropna()
        n_frames = len(grp)
        if len(cbds) > 0:
            cbd_min = int(float(cbds.min()))
            cbd_max = int(float(cbds.max()))
            cbd_range = f"{cbd_min:04d}-{cbd_max:04d}"
        else:
            cbd_range = "  (unknown)"
        short_name = tiff_name.split("-")[0] if "-" in tiff_name else tiff_name
        print(f"  {int(tid):>7}  {cbd_range:>12}  {n_frames:>6}  {short_name}")


def _delete_tiff_rows(csv_path: Path, tiff_ids: list[int]):
    """Remove rows for given tiff_ids from a phase CSV so they can be re-run."""
    if not csv_path.exists():
        return
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()
    before = len(df)
    df = df[~df["tiff_id"].isin(tiff_ids)]
    df.to_csv(csv_path, index=False)
    print(f"  Removed {before - len(df)} rows for TIFFs {tiff_ids} from {csv_path.name}")


# -- Phase 3: Calibration ----------------------------------------------------

def run_phase3(flt: int, tiffs: list[Path], out_dir: Path) -> dict:
    """Run calibration on all TIFFs with y_ref failure detection."""

    cal_csv = out_dir / "phase3" / f"F{flt}_cal.csv"
    success, failed, skipped, needs_picks = [], [], [], []

    for i, tiff in enumerate(tiffs, 1):
        tid = _tiff_id(tiff)

        if check_tiff_in_csv(tiff.name, cal_csv):
            skipped.append(tiff)
            print(f"  [{i:>2}/{len(tiffs)}]  {tid:>5}  [skip]")
            continue

        result = _run_step(CALIBRATE_SCRIPT, tiff)

        if result.returncode == 0:
            success.append(tiff)
            # Parse frame count from "Frames in index: N  (complete: M)"
            n_frames = 0
            for line in result.stdout.splitlines():
                if "Frames in index" in line:
                    try:
                        n_frames = int(line.split(":")[1].split("(")[0].strip())
                    except (ValueError, IndexError):
                        pass
            print(f"  [{i:>2}/{len(tiffs)}]  {tid:>5}  [{n_frames:>3} fr]")
        elif "No reference-line pick" in (result.stderr + result.stdout):
            needs_picks.append(tiff)
            print(f"  [{i:>2}/{len(tiffs)}]  {tid:>5}  \033[33m[NEED PICK]\033[0m missing y_ref")
        else:
            err_line = (result.stderr + result.stdout).strip().split("\n")[-1]
            failed.append((tiff, err_line))
            print(f"  [{i:>2}/{len(tiffs)}]  {tid:>5}  \033[31m[FAIL]\033[0m {err_line[:60]}")

    print(f"\n  Phase 3 summary: {len(success)} new, {len(skipped)} skipped, "
          f"{len(needs_picks)} need picks, {len(failed)} failed")

    return {
        "success": success, "failed": failed,
        "skipped": skipped, "needs_picks": needs_picks,
    }


def analyze_phase3_results(flt: int, out_dir: Path):
    """Analyze calibration results across the flight."""
    cal_csv = out_dir / "phase3" / f"F{flt}_cal.csv"
    if not cal_csv.exists():
        return

    df = pd.read_csv(cal_csv)
    df.columns = df.columns.str.strip()

    # Filter to calibrated frames (non-excluded)
    cal = df[df["exclude_reason"].isna() | (df["exclude_reason"].fillna("").astype(str).str.strip() == "")]

    if len(cal) == 0:
        print("  No calibrated frames found.")
        return

    mb_power = cal["mb_power_dB"].astype(float)
    mb_median = mb_power.median()
    x_spacing = cal["x_spacing_px"].astype(float)
    x_median = x_spacing.median()

    print(f"\n  Phase 3 flight diagnostics ({len(cal)} calibrated frames):")
    print(f"    mb_power:  median {mb_median:.1f} dB, range [{mb_power.min():.1f}, {mb_power.max():.1f}] dB")
    print(f"    x_spacing: median {x_median:.1f} px, range [{x_spacing.min():.1f}, {x_spacing.max():.1f}] px")

    # Flag outliers
    outliers = cal[mb_power < mb_median - 8]
    if len(outliers) > 0:
        tids = outliers["tiff_id"].unique()
        print(f"    WARNING: {len(outliers)} frames with mb_power > 8 dB below median "
              f"(TIFFs: {', '.join(str(int(t)) for t in tids)})")

    x_outliers = cal[(x_spacing - x_median).abs() > 10]
    if len(x_outliers) > 0:
        tids = x_outliers["tiff_id"].unique()
        print(f"    WARNING: {len(x_outliers)} frames with x_spacing > 10 px from median "
              f"(TIFFs: {', '.join(str(int(t)) for t in tids)})")

    n_excluded = len(df) - len(cal)
    if n_excluded > 0:
        print(f"    Excluded frames: {n_excluded}")


def _flag_bad_cbds(sub: pd.DataFrame, flt_xs_med: float) -> list[int]:
    """Flag individual CBDs with geometric calibration problems within a TIFF.

    Focuses on X-grid detection failures (affects h_ice accuracy).
    MB power variation is NOT flagged — it is a known instrumental effect
    corrected in phase 4 using per-frame mb_power as a gain reference.

    A frame is flagged if:
      - x_spacing_px deviates > 15 px from flight median (~7% error in TWT)
    """
    bad = sub[
        (sub["x_spacing_px"] - flt_xs_med).abs() > 15
    ]
    return sorted(bad["cbd"].dropna().astype(int).tolist())


def print_phase3_cbd_table(flt: int, out_dir: Path) -> tuple[list[int], dict[int, tuple[str, list[int]]]]:
    """Print TIFF -> CBD mapping with MB quality flags.

    Returns (check_tiff_ids, check_details) where check_details maps
    tiff_id -> (reason, bad_cbd_list).
    """
    cal_csv = out_dir / "phase3" / f"F{flt}_cal.csv"
    if not cal_csv.exists():
        return [], {}

    df = pd.read_csv(cal_csv)
    df.columns = df.columns.str.strip()
    # Ensure numeric types for flagging
    for col in ("mb_x", "mb_power_dB", "x_spacing_px"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Flight-wide x_spacing median for outlier detection
    _excl = df["exclude_reason"].fillna("").astype(str).str.strip()
    _valid = df[_excl.isin(["", "nan"])].dropna(subset=["x_spacing_px"])
    flt_xs_med = float(_valid["x_spacing_px"].median()) if len(_valid) > 0 else 205.0

    print(f"\n  TIFF -> CBD mapping (phase 3 calibration):")
    print(f"  {'TIFF':>6}  {'CBD range':>14}  {'frames':>6}  {'x_sp med':>9}  {'x_sp std':>9}  "
          f"{'mb_pwr med':>10}  {'mb_pwr std':>10}  {'flag':>6}")
    print(f"  {'-'*85}")

    check_tiffs: list[int] = []
    check_details: dict[int, tuple[str, list[int]]] = {}  # tid -> (reason, bad_cbds)

    for tid in sorted(df["tiff_id"].unique()):
        sub = df[df["tiff_id"] == tid].sort_values("cbd")
        n = len(sub)
        cbds = sub["cbd"].dropna()
        cbd_lo = f"{cbds.min():04.0f}" if len(cbds) > 0 else "?"
        cbd_hi = f"{cbds.max():04.0f}" if len(cbds) > 0 else "?"
        xs_med = sub["x_spacing_px"].median()
        xs_std = sub["x_spacing_px"].std() if len(sub) > 1 else 0.0
        mp_med = sub["mb_power_dB"].median()
        mp_std = sub["mb_power_dB"].std() if len(sub) > 1 else 0.0

        # CHECK criteria: geometric calibration problems only.
        # MB power variation is NOT flagged — it is a known instrumental
        # effect (attenuator / CRT intensity) corrected in phase 4.
        flag = "GOOD"
        reason = ""
        if xs_std > 10:
            flag = "CHECK"
            reason = "x_spacing varies > 10 px within TIFF"
        elif abs(xs_med - flt_xs_med) > 15:
            flag = "CHECK"
            reason = f"x_spacing median {xs_med:.0f} deviates from flight ({flt_xs_med:.0f})"

        if flag == "CHECK":
            check_tiffs.append(int(tid))
            bad_cbds = _flag_bad_cbds(sub, flt_xs_med)
            check_details[int(tid)] = (reason, bad_cbds)

        if flag == "CHECK":
            flag_str = f"\033[1;31m{'CHECK':>6}\033[0m"
        else:
            flag_str = f"\033[32m{'GOOD':>6}\033[0m"
        print(f"  {tid:6.0f}  {cbd_lo}-{cbd_hi:>4}  {n:6d}  {xs_med:9.1f}  {xs_std:9.1f}  "
              f"{mp_med:10.1f}  {mp_std:10.1f}  {flag_str}")

    # Summary
    n_total_tiffs = df["tiff_id"].nunique()
    n_good = n_total_tiffs - len(check_tiffs)
    print(f"\n  Total: {len(df)} frames across {n_total_tiffs} TIFFs "
          f"({n_good} GOOD, {len(check_tiffs)} CHECK)")

    if check_tiffs:
        # ANSI codes for bold yellow on terminal
        BOLD = "\033[1m"
        YELLOW = "\033[33m"
        RED = "\033[31m"
        RESET = "\033[0m"

        print(f"\n  {BOLD}{YELLOW}+{'-'*70}+{RESET}")
        print(f"  {BOLD}{YELLOW}|  [!]  CHECK TIFFs — review diagnostic PNGs in phase3/{' '*19}|{RESET}")
        print(f"  {BOLD}{YELLOW}+{'-'*70}+{RESET}")
        for tid in check_tiffs:
            reason, bad_cbds = check_details[tid]
            # Count total CBDs in this TIFF
            n_total = len(df[df["tiff_id"] == tid]["cbd"].dropna())
            if len(bad_cbds) == 0 or len(bad_cbds) >= n_total:
                cbd_str = "all CBDs"
            else:
                cbd_str = ", ".join(f"{c:04d}" for c in bad_cbds)
            line = f"TIFF {tid}: {reason} -> {cbd_str}"
            # Wrap long lines
            if len(line) <= 68:
                print(f"  {BOLD}{YELLOW}|{RESET}  {RED}{line:<68}{RESET}{BOLD}{YELLOW}|{RESET}")
            else:
                print(f"  {BOLD}{YELLOW}|{RESET}  {RED}{line[:68]}{RESET}{BOLD}{YELLOW}|{RESET}")
                print(f"  {BOLD}{YELLOW}|{RESET}  {RED}{'':>16}{line[68:]:<52}{RESET}{BOLD}{YELLOW}|{RESET}")
        # Count total flagged CBDs across all CHECK TIFFs
        n_flagged_cbds = 0
        n_total_cbds = len(df)
        for tid in check_tiffs:
            _, bad_cbds = check_details[tid]
            n_in_tiff = len(df[df["tiff_id"] == tid]["cbd"].dropna())
            n_flagged_cbds += len(bad_cbds) if bad_cbds and len(bad_cbds) < n_in_tiff else n_in_tiff
        summary = f"{n_flagged_cbds} of {n_total_cbds} frames need checking"
        print(f"  {BOLD}{YELLOW}+{'-'*70}+{RESET}")
        print(f"  {BOLD}{YELLOW}|{RESET}  {BOLD}{summary:<68}{RESET}{BOLD}{YELLOW}|{RESET}")
        print(f"  {BOLD}{YELLOW}+{'-'*70}+{RESET}")

    return check_tiffs, check_details


def run_phase4(flt: int, tiffs: list[Path], out_dir: Path) -> dict:
    """Run echo extraction on all TIFFs."""

    echo_csv = out_dir / "phase4" / f"F{flt}_echoes.csv"
    success, failed, skipped = [], [], []

    for i, tiff in enumerate(tiffs, 1):
        tid = _tiff_id(tiff)

        if check_tiff_in_csv(tiff.name, echo_csv):
            skipped.append(tiff)
            print(f"  [{i:>2}/{len(tiffs)}]  {tid:>5}  [skip]")
            continue

        result = _run_step(ECHOES_SCRIPT, tiff)

        if result.returncode == 0:
            success.append(tiff)
            # Parse echo status counts from stdout
            counts: dict[str, int] = {}
            n_frames = 0
            for line in result.stdout.splitlines():
                if "Frames processed" in line:
                    try:
                        n_frames = int(line.split(":")[-1].strip())
                    except ValueError:
                        pass
                for st in ("good", "weak_bed", "no_bed", "no_surface"):
                    if line.strip().startswith(st):
                        try:
                            counts[st] = int(line.split(":")[-1].strip())
                        except ValueError:
                            pass
            n_good = counts.get("good", 0) + counts.get("weak_bed", 0)
            n_nobed = counts.get("no_bed", 0)
            parts = []
            if n_good:
                parts.append(f"\033[32m{n_good} good\033[0m")
            if n_nobed:
                parts.append(f"\033[33m{n_nobed} no_bed\033[0m")
            n_nosurf = counts.get("no_surface", 0)
            if n_nosurf:
                parts.append(f"\033[31m{n_nosurf} no_surface\033[0m")
            summary = ", ".join(parts) if parts else f"{n_frames} frames"
            print(f"  [{i:>2}/{len(tiffs)}]  {tid:>5}  [{n_frames:>3} fr]  {summary}")
        else:
            err_line = (result.stderr + result.stdout).strip().split("\n")[-1]
            failed.append((tiff, err_line))
            print(f"  [{i:>2}/{len(tiffs)}]  {tid:>5}  \033[31m[FAIL]\033[0m {err_line[:60]}")

    print(f"\n  Phase 4 summary: {len(success)} new, {len(skipped)} skipped, {len(failed)} failed")

    return {"success": success, "failed": failed, "skipped": skipped}


# -- Phase 5: Validation -----------------------------------------------------

def run_phase5(flt: int, out_dir: Path):
    """Run BEDMAP1 validation and print flight summary."""

    if not VALIDATE_SCRIPT.exists():
        print("  Validation skipped: validate_flight.py was not included in the shared codes.")
        print("  Phase 4 echoes and thickness CSV remain available for review.")
        print_flight_summary(flt, out_dir)
        return

    result = subprocess.run(
        [sys.executable, str(VALIDATE_SCRIPT), str(flt)],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode == 0:
        # Print validation output
        for line in result.stdout.splitlines():
            print(f"  {line}")
    else:
        print(f"  Validation failed: {result.stderr.strip().split(chr(10))[-1]}")

    print_flight_summary(flt, out_dir)


def print_flight_summary(flt: int, out_dir: Path):
    """Print final flight-level summary from echo extraction."""
    echo_csv = out_dir / "phase4" / f"F{flt}_echoes.csv"
    if not echo_csv.exists():
        print("  (no echoes found)")
        return

    df = pd.read_csv(echo_csv)
    df.columns = df.columns.str.strip()

    n = len(df)
    status = df["echo_status"].str.strip()

    n_good = int((status == "good").sum())
    n_weak = int((status == "weak_bed").sum())
    n_nobed = int((status == "no_bed").sum())
    n_nosurf = int((status == "no_surface").sum())

    cbds = df["cbd"].dropna().astype(float)
    cbd_min = int(cbds.min()) if len(cbds) > 0 else 0
    cbd_max = int(cbds.max()) if len(cbds) > 0 else 0

    print(f"\n  {'='*50}")
    print(f"  Flight F{flt} Summary")
    print(f"  {'='*50}")
    print(f"    Total frames:  {n}")
    print(f"    good:          {n_good:>4}  ({100*n_good/n:.1f}%)" if n else "")
    print(f"    weak_bed:      {n_weak:>4}  ({100*n_weak/n:.1f}%)" if n else "")
    print(f"    no_bed:        {n_nobed:>4}  ({100*n_nobed/n:.1f}%)" if n else "")
    print(f"    no_surface:    {n_nosurf:>4}  ({100*n_nosurf/n:.1f}%)" if n else "")
    print(f"    CBD range:     {cbd_min:04d} - {cbd_max:04d}")

    # Good-frame statistics
    good = df[status == "good"]
    if len(good) > 0:
        h_ice = good["h_ice_m"].dropna().astype(float)
        h_air = good["h_air_m"].dropna().astype(float)
        if len(h_ice) > 0:
            print(f"    h_ice (good):  {h_ice.mean():.0f} +/- {h_ice.std():.0f} m "
                  f"(range {h_ice.min():.0f}-{h_ice.max():.0f} m)")
        if len(h_air) > 0:
            print(f"    h_air (good):  {h_air.mean():.0f} +/- {h_air.std():.0f} m "
                  f"(range {h_air.min():.0f}-{h_air.max():.0f} m)")

    n_tiffs = df["tiff_id"].nunique()
    print(f"    TIFFs:         {n_tiffs}")


# -- Main ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="LYRA flight-level orchestrator — batch process all TIFFs")
    parser.add_argument("flight", type=int, help="Flight number (e.g. 126)")
    parser.add_argument("--method", choices=["manual", "segment", "ml", "ensemble", "ncc"],
                        default="segment",
                        help="CBD assignment method for phase 1 (default: segment; no ASTRA picks needed)")
    parser.add_argument("--resume-from", type=int, choices=[1, 2, 3, 4, 5], default=1,
                        help="Resume from phase N (skip earlier phases)")
    parser.add_argument("--skip-picks", action="store_true",
                        help="Skip Phase 2 pause (assume picks are done)")
    parser.add_argument("--cbd-start", metavar="TIFF_ID:CBD",
                        help="Set starting CBD for a TIFF and propagate to all "
                             "subsequent TIFFs, e.g. --cbd-start 7600:300")
    args = parser.parse_args()

    flt = args.flight
    os.environ["LYRA_FLIGHT"] = str(flt)
    raw_dir = ROOT / "tiff" / str(flt)
    if not raw_dir.exists():
        raw_dir = ROOT / "tiff"  # single-flight flat directory
    out_dir = ROOT / "output" / f"F{flt}"

    if not raw_dir.exists():
        sys.exit(f"ERROR: Raw data directory not found: {raw_dir}")

    tiffs = discover_tiffs(raw_dir)
    if not tiffs:
        sys.exit(f"ERROR: No .tiff files found in {raw_dir}")

    # Filter out non-canonical TIFFs (no underscore-separated numbers)
    canonical = [t for t in tiffs if "_" in t.stem and t.stem[0].isdigit()]
    non_canonical = [t for t in tiffs if t not in canonical]

    # Parse --cbd-start TIFF_ID:CBD
    cbd_start_map: dict[int, int] = {}  # tiff_id -> starting CBD
    if args.cbd_start:
        if ":" not in args.cbd_start:
            sys.exit("ERROR: --cbd-start expects TIFF_ID:CBD format, e.g. 7600:300")
        try:
            _tid_str, _cbd_str = args.cbd_start.split(":", 1)
            cbd_start_map[int(_tid_str)] = int(_cbd_str)
        except ValueError:
            sys.exit(f"ERROR: --cbd-start expects integers, got '{args.cbd_start}'")

    print(f"\n  LYRA Flight Orchestrator — F{flt}")
    print(f"  {'-'*40}")
    print(f"  Raw directory:  {raw_dir}")
    print(f"  TIFFs found:    {len(canonical)} canonical" +
          (f" + {len(non_canonical)} non-canonical (skipped)" if non_canonical else ""))
    print(f"  CBD method:     {args.method}")
    if cbd_start_map:
        for _tid, _cbd in sorted(cbd_start_map.items()):
            print(f"  CBD start:      TIFF {_tid} -> CBD {_cbd:04d} (propagating to subsequent TIFFs)")
    if non_canonical:
        for t in non_canonical:
            print(f"    [skipped] {t.name}")

    tiffs = canonical

    # -- Phase 1 ----------------------------------------------------------
    if args.resume_from <= 1:
        print(f"\n  {'='*55}")
        print(f"  PHASE 1: Frame Detection + CBD Assignment")
        print(f"  {'='*55}\n")

        run_phase1(flt, tiffs, args.method, out_dir, cbd_start_map)

        print(f"\n  Check contact sheets in: {out_dir / 'phase1'}/")
        print(f"  To fix CBD assignments:")
        print(f"    python codes/detect_frames.py <TIFF> --method manual --override FR:CBD ...")
        _pause("Press ENTER when CBD assignments are correct ...")

    # -- Phase 2 ----------------------------------------------------------
    if args.resume_from <= 2 and not args.skip_picks:
        print(f"\n  {'='*55}")
        print(f"  PHASE 2: Pick Calibration (M + R + X on each TIFF)")
        print(f"  {'='*55}\n")

        print(f"  Every TIFF needs at least one frame with MB, ref-line, and X-grid picks.")
        print(f"  Launching pick_calibration in flight mode ...\n")

        result = subprocess.run(
            [sys.executable, str(PICK_SCRIPT), "--flight", str(flt)],
            cwd=ROOT,
        )
        if result.returncode != 0:
            print(f"\n  pick_calibration exited with code {result.returncode}.")
            _pause("Press ENTER to continue to phase 3 anyway, or Ctrl-C to abort ...")

    # -- Phase 3: Calibration ---------------------------------------------
    if args.resume_from <= 3:
        print(f"\n  {'='*55}")
        print(f"  PHASE 3: Per-Frame Calibration")
        print(f"  {'='*55}\n")

        s2 = run_phase3(flt, tiffs, out_dir)

        # Handle y_ref failures
        if s2["needs_picks"]:
            print(f"\n  {len(s2['needs_picks'])} TIFFs missing y_ref pick.")
            print(f"  Launching pick_calibration for those TIFFs ...\n")
            for t in s2["needs_picks"]:
                tid = _tiff_id(t)
                subprocess.run(
                    [sys.executable, str(PICK_SCRIPT), "--flight", str(flt),
                     "--tiff", str(tid)],
                    cwd=ROOT,
                )

            # Re-run calibration on previously-failed TIFFs
            print(f"\n  Re-running calibration on {len(s2['needs_picks'])} TIFFs ...\n")
            s2_retry = run_phase3(flt, s2["needs_picks"], out_dir)

            if s2_retry["needs_picks"] or s2_retry["failed"]:
                still_bad = s2_retry["needs_picks"] + [t for t, _ in s2_retry["failed"]]
                print(f"\n  WARNING: {len(still_bad)} TIFFs still failing after retry.")
                print(f"  Continuing with available data.")

        # Flight-level analysis + CBD table
        analyze_phase3_results(flt, out_dir)
        check_tiffs, check_details = print_phase3_cbd_table(flt, out_dir)

        # Fix loop — repeat until user is satisfied
        while check_tiffs:
            print(f"\n  {len(check_tiffs)} TIFFs flagged CHECK — review diagnostic PNGs in:")
            print(f"    {out_dir / 'phase3'}/")
            print(f"  Verify: red dashed mb_line should be on the main bang, not surface/bed.")
            try:
                choice = input("\n  Fix flagged TIFFs? [f]ix / [c]ontinue to phase 4: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "c"

            if not choice.startswith("f"):
                break

            # Launch pick_calibration for each CHECK TIFF (flagged CBDs only)
            cal_df = pd.read_csv(out_dir / "phase3" / f"F{flt}_cal.csv")
            cal_df.columns = cal_df.columns.str.strip()
            for tid in check_tiffs:
                reason, bad_cbds = check_details[tid]
                n_total = len(cal_df[cal_df["tiff_id"] == tid]["cbd"].dropna())
                if bad_cbds and len(bad_cbds) < n_total:
                    cbd_arg = ",".join(str(c) for c in bad_cbds)
                    print(f"\n  TIFF {tid}: fixing {len(bad_cbds)} flagged CBDs ...")
                else:
                    cbd_arg = None
                    print(f"\n  TIFF {tid}: fixing all CBDs ...")
                cmd = [sys.executable, str(PICK_SCRIPT), "--flight", str(flt),
                       "--tiff", str(tid)]
                if cbd_arg:
                    cmd.extend(["--cbds", cbd_arg])
                subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL)

            # Delete CHECK rows and re-run calibration
            cal_csv = out_dir / "phase3" / f"F{flt}_cal.csv"
            _delete_tiff_rows(cal_csv, check_tiffs)

            check_paths = [t for t in tiffs if _tiff_id(t) in check_tiffs]
            print(f"\n  Re-running calibration on {len(check_paths)} fixed TIFFs ...\n")
            run_phase3(flt, check_paths, out_dir)

            # Re-print table and loop
            analyze_phase3_results(flt, out_dir)
            check_tiffs, check_details = print_phase3_cbd_table(flt, out_dir)

        if not check_tiffs:
            print(f"\n  All TIFFs GOOD.")

        _pause("Press ENTER to proceed to phase 4 ...")

    # -- Phase 4: Echo Extraction -----------------------------------------
    if args.resume_from <= 4:
        # If resuming from an earlier phase, the echoes CSV is stale (computed
        # from old calibration).  Delete it so Phase 4 re-processes all TIFFs.
        echo_csv = out_dir / "phase4" / f"F{flt}_echoes.csv"
        if args.resume_from < 4 and echo_csv.exists():
            echo_csv.unlink()
            print(f"  Cleared stale {echo_csv.name} (re-running after Phase 3 update)")

        print(f"\n  {'='*55}")
        print(f"  PHASE 4: Echo Extraction")
        print(f"  {'='*55}\n")

        run_phase4(flt, tiffs, out_dir)

    # -- Phase 5: Validation ----------------------------------------------
    if args.resume_from <= 5:
        print(f"\n  {'='*55}")
        print(f"  PHASE 5: Validation (BEDMAP1 comparison)")
        print(f"  {'='*55}\n")

        run_phase5(flt, out_dir)

    print(f"\n  Flight F{flt} processing complete.\n")


if __name__ == "__main__":
    main()
