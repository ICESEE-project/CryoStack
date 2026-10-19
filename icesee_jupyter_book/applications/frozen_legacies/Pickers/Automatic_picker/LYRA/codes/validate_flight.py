#!/usr/bin/env python3
"""LYRA Phase 5 validation: compare ice thickness with ASTRA and BEDMAP1.

Usage:
    python tools/LYRA/validate_flight.py <flight_number>
    python tools/LYRA/validate_flight.py --riggs-map

Reads the Phase 4 echoes CSV for the given flight, compares against:
  - ASTRA manual picks on the same A-scope frames (d = 0; primary validation)
  - RIGGS ice thickness (independent seismic/radar; Bentley 1984)
  - BEDMAP1 SPRI (same-source, spatial context only)

Standalone maps:
  --riggs-map   Generate a map of all RIGGS stations on the Ross Ice Shelf

Output:
    tools/LYRA/output/F{FLT}/validation/F{FLT}_validation.png
    tools/LYRA/output/F{FLT}/validation/F{FLT}_validation.json
    tools/LYRA/output/RIGGS_stations_map.png  (--riggs-map)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree

# Import basemap helpers from plot_flight_tracks
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from plot_flight_tracks import load_basemap_ps, _graticule_line, _meridian_line, _geo_label

# Import alignment functions from lyra
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lyra as _lyra

# -- Paths (relative to repo root) --------------------------------------------

REPO = Path(__file__).resolve().parent.parent.parent  # FrozenLegacies/
NAV_DIR = REPO / "Navigation_Files"
BEDMAP_SHP = REPO / "Data" / "BEDMAP" / "BedMap1" / "bedmap1_clip.shp"
RIGGS_CSV = REPO / "Data" / "RIGGS" / "riggs_stations.csv"
OUTPUT_BASE = Path(__file__).resolve().parent / "output"

# -- Constants -----------------------------------------------------------------

MATCH_RADIUS_M = 20_000  # max distance (m) for nearest-neighbour match
NAV_MISSING = 9999       # sentinel for missing THK/SRF in Navigation CSVs
ASTRA_DIR = REPO / "Data" / "ascope" / "picks"

# ASTRA timing correction: ASTRA assumed 3 µs/div but correct is 2.0 µs/div
C_ICE = 168.0   # m/µs
C_AIR = 300.0   # m/µs

# BEDMAP1 mission IDs ---------------------------------------------------------
# SPRI_7475 is the same SPRI/NSF/TUD 1974-75 data that LYRA reprocesses
# (comparison is circular). All other missions are independent.
SAME_SOURCE_MISSIONS = {"SPRI_7475"}

# ColorBrewer-based palette ----------------------------------------------------
STATUS_COLORS = {
    "good":       "#1b9e77",   # teal-green (ColorBrewer Dark2)
    "weak_bed":   "#66c2a5",   # light teal-green (ColorBrewer Set2, sibling of good)
    "no_bed":     "#bdbdbd",   # gray
    "no_surface": "#e7298a",   # magenta-pink
}
STATUS_LABELS = {
    "good":       "Good echo",
    "weak_bed":   "Weak bed (SNR < 5 dB)",
    "no_bed":     "No bed echo",
    "no_surface": "No surface echo",
}
STATUS_ORDER = ["good", "weak_bed", "no_bed", "no_surface"]

# Reference dataset colors
RIGGS_SEIS_COLOR  = "#d62728"   # red (seismic — independent, high accuracy)
RIGGS_RADAR_COLOR = "#ff7f0e"   # orange (RIGGS 35 MHz radar)
SPRI_COLOR        = "#2166ac"   # blue (same-source, circular)

_TRANSFORM = Transformer.from_crs("EPSG:4326", "EPSG:3031", always_xy=True)


# -- Publication figure styling ------------------------------------------------

def _setup_rcparams():
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica Neue", "DejaVu Sans"],
        "font.size": 8,
        "axes.labelsize": 8,
        "axes.titlesize": 9.5,
        "axes.titleweight": "bold",
        "axes.titlepad": 8,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "legend.fontsize": 7,
        "legend.framealpha": 0.90,
        "legend.edgecolor": "#cccccc",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.alpha": 0.3,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
    })


def _panel_label(ax, label, x=0.015, y=0.97):
    ax.text(x, y, label, transform=ax.transAxes,
            fontsize=9, fontweight="bold", va="top", ha="left",
            bbox=dict(facecolor="white", edgecolor="none", pad=1.5, alpha=0.7))


# -- Data loading --------------------------------------------------------------

def load_echoes(flt: int) -> pd.DataFrame:
    """Load all step3 echoes for a flight."""
    csv_path = OUTPUT_BASE / f"F{flt}" / "phase4" / f"F{flt}_echoes.csv"
    if not csv_path.exists():
        sys.exit(f"Phase 4 output not found: {csv_path}")
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()
    return df.sort_values("cbd").reset_index(drop=True)


def load_navigation(flt: int) -> pd.DataFrame:
    """Load navigation CSV for a flight (via lyra.load_stanford_nav)."""
    return _lyra.load_stanford_nav(flt)


def load_bedmap() -> gpd.GeoDataFrame:
    """Load BEDMAP1 shapefile with full attribution."""
    if not BEDMAP_SHP.exists():
        sys.exit(f"BEDMAP1 shapefile not found: {BEDMAP_SHP}")
    return gpd.read_file(BEDMAP_SHP)


def load_astra(flt: int) -> pd.DataFrame | None:
    """Load ASTRA manual picks for a flight and compute corrected h_ice/h_air.

    ASTRA assumed 3 us/div but the correct calibration is 2.0 us/div,
    so all travel times must be divided by 1.5.  Then convert one-way:
        h_ice = (bed_us - surface_us) / 3 * c_ice
        h_air = surface_us / 3 * c_air
    (divide by 3 = /1.5 for ASTRA error * /2 for two-way -> one-way)

    Returns DataFrame with columns: CBD, h_ice_astra, h_air_astra
    or None if no ASTRA data exists.
    """
    csv_path = ASTRA_DIR / str(flt) / f"{flt}_CombinedASTRAPicks.csv"
    if not csv_path.exists():
        return None
    astra = pd.read_csv(csv_path)
    astra.columns = astra.columns.str.strip()

    # Need both surface and bed travel times, and a valid CBD
    has_both = (astra["surface_us"].notna() & astra["bed_us"].notna()
                & (astra["bed_us"] > 0) & astra["CBD"].notna())
    astra = astra[has_both].copy()
    if astra.empty:
        return None

    # Apply /1.5 timing correction + one-way conversion (/3 total)
    astra["h_ice_astra"] = (astra["bed_us"] - astra["surface_us"]) / 3 * C_ICE
    astra["h_air_astra"] = astra["surface_us"] / 3 * C_AIR

    # Keep only valid ice thicknesses
    astra = astra[astra["h_ice_astra"] > 0].copy()

    # Ensure CBD is integer to match LYRA's echoes CSV
    astra["CBD"] = astra["CBD"].astype(int)

    # Average multiple ASTRA picks per CBD (some have >1 A-scope per frame)
    astra = astra.groupby("CBD")[["h_ice_astra", "h_air_astra"]].mean().reset_index()

    return astra


import re as _re

def _parse_dms(s: str) -> float | None:
    """Parse a DMS or DM coordinate string to decimal degrees.

    Handles formats:
        82 deg 32'19"S          (DMS with seconds)
        84 deg 35.1'S           (DM with decimal minutes)
        84 deg 28'S             (DM with integer minutes)
    Returns negative for S/W hemispheres, None on parse failure.
    """
    if not s or not isinstance(s, str):
        return None
    s = s.strip().replace("\u00b0", " ").replace("''", '"')
    m = _re.match(
        r"(\d+)\s+(\d+(?:\.\d+)?)['\u2032]?\s*(?:(\d+(?:\.\d+)?)[\"'\u2033]?)?\s*([NSEW])",
        s,
    )
    if not m:
        return None
    deg = float(m.group(1))
    mins = float(m.group(2))
    secs = float(m.group(3)) if m.group(3) else 0.0
    dd = deg + mins / 60.0 + secs / 3600.0
    if m.group(4) in ("S", "W"):
        dd = -dd
    return dd


def load_riggs_stations() -> pd.DataFrame | None:
    """Load RIGGS ice thickness stations from riggs_stations.csv.

    Uses seismic thickness where available (+/-10 m accuracy, Bamber &
    Bentley 1994), with RIGGS radar (35 MHz) as fallback.  Both are
    independent of SPRI 60 MHz.

    Returns DataFrame with: Station, h_ice, source, LAT_dd, LON_dd, x_ps, y_ps
    or None if the CSV is missing.
    """
    if not RIGGS_CSV.exists():
        return None
    df = pd.read_csv(RIGGS_CSV)

    # Parse DMS/DM coordinates to decimal degrees
    df["LAT_dd"] = df["Latitude"].apply(_parse_dms)
    df["LON_dd"] = df["Longitude"].apply(_parse_dms)

    # Convert ice thickness columns to numeric
    df["h_radar"] = pd.to_numeric(df["h_i (radar), m"], errors="coerce")
    df["h_seismic"] = pd.to_numeric(df["h_i (seismics), m"], errors="coerce")

    # Drop stations without coordinates
    df = df[df["LAT_dd"].notna() & df["LON_dd"].notna()].copy()

    # Prefer seismic, fall back to radar
    df["h_ice"] = df["h_seismic"].fillna(df["h_radar"])
    df["source"] = np.where(df["h_seismic"].notna(), "seismic", "radar")
    df = df[df["h_ice"].notna()].copy()

    # Project to polar stereographic
    x_ps, y_ps = _TRANSFORM.transform(df["LON_dd"].values, df["LAT_dd"].values)
    df["x_ps"] = x_ps
    df["y_ps"] = y_ps

    return df[["Station", "h_ice", "source", "LAT_dd", "LON_dd",
               "x_ps", "y_ps"]].reset_index(drop=True)


# -- Core logic ----------------------------------------------------------------

def merge_with_nav(echoes: pd.DataFrame, nav: pd.DataFrame,
                   offset: int = 0) -> pd.DataFrame:
    """Join echoes with navigation on CBD, applying a CBD offset.

    The offset means: nav row index = lyra_cbd + offset.
    """
    echoes = echoes.copy()
    echoes["nav_cbd"] = echoes["cbd"] + offset
    merged = echoes.merge(nav, left_on="nav_cbd", right_on="CBD", how="left")
    merged["has_nav"] = merged["LAT"].notna()
    return merged


def _apply_nav_correction(merged: pd.DataFrame,
                          nav_correction: _lyra.NavCorrection) -> None:
    """Apply Rose 1978 piecewise-linear nav correction to merged LAT/LON.

    Modifies the DataFrame in-place.
    """
    has_nav = merged["has_nav"] & merged["LAT"].notna() & merged["LON"].notna()
    if not has_nav.any():
        return

    nav_cbds = merged.loc[has_nav, "nav_cbd"].values.astype(int)
    lats = merged.loc[has_nav, "LAT"].values
    lons = merged.loc[has_nav, "LON"].values

    T_fwd = _TRANSFORM  # EPSG:4326 -> EPSG:3031 (already defined)
    T_inv = Transformer.from_crs("EPSG:3031", "EPSG:4326", always_xy=True)

    x_ps, y_ps = T_fwd.transform(lons, lats)
    dx, dy = nav_correction.correction_at_cbd(nav_cbds)
    lon_corr, lat_corr = T_inv.transform(x_ps + dx, y_ps + dy)

    merged.loc[has_nav, "LAT"] = lat_corr
    merged.loc[has_nav, "LON"] = lon_corr


def match_reference(lats: np.ndarray, lons: np.ndarray,
                    ref_xy: np.ndarray, ref_thk: np.ndarray,
                    radius_m: float = MATCH_RADIUS_M
                    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Find nearest reference ice thickness for each (lat, lon) point.

    Returns:
        ref_ice: (N,) matched ice thickness (NaN if no match within radius)
        ref_dist: (N,) distances in metres
        ref_idx: (N,) index into ref arrays (-1 if no match)
    """
    x_ps, y_ps = _TRANSFORM.transform(lons, lats)
    flight_xy = np.column_stack([x_ps, y_ps])

    tree = cKDTree(ref_xy)
    dists, idxs = tree.query(flight_xy)

    within = dists <= radius_m
    ref_ice = np.where(within, ref_thk[idxs], np.nan)
    ref_idx = np.where(within, idxs, -1)
    return ref_ice, dists, ref_idx


def _extract_ref_arrays(gdf: gpd.GeoDataFrame
                        ) -> tuple[np.ndarray, np.ndarray]:
    """Extract (xy_coords, thickness) arrays from a BEDMAP1 subset."""
    xy = np.column_stack([gdf["PS_x"].values, gdf["PS_y"].values])
    thk = gdf["Ice_thickn"].values.astype(float)
    return xy, thk


# -- Inset map helper ---------------------------------------------------------

def _draw_inset_map(ax_map, nav, merged, status, riggs_df, spri_gdf, flt):
    """Draw spatial context map on the given inset axes.

    Uses Natural Earth basemap from plot_flight_tracks, with graticules,
    geographic labels, flight track, RIGGS stations, and BEDMAP1 SPRI.
    """
    # Load basemap
    land = load_basemap_ps()
    land.plot(ax=ax_map, color="#e4eef5", edgecolor="#7aadbb",
              linewidth=0.4, zorder=1)

    # Determine map extent from flight coordinates (with margin).
    # Expand the shorter dimension so the map fills the panel height
    # while keeping equal-aspect geographic proportions.
    has_coords = merged["LAT"].notna() & merged["LON"].notna()
    if has_coords.any():
        fx, fy = _TRANSFORM.transform(
            merged.loc[has_coords, "LON"].values,
            merged.loc[has_coords, "LAT"].values)
        margin = 150_000  # 150 km buffer
        x_lim = (fx.min() - margin, fx.max() + margin)
        y_lim = (fy.min() - margin, fy.max() + margin)
    else:
        x_lim = (-700_000, 500_000)
        y_lim = (-1_400_000, -400_000)

    # Get the panel's physical aspect ratio from the figure geometry
    fig = ax_map.get_figure()
    bbox = ax_map.get_position()
    panel_w = bbox.width * fig.get_figwidth()
    panel_h = bbox.height * fig.get_figheight()
    panel_aspect = panel_h / panel_w  # physical H/W

    x_range = x_lim[1] - x_lim[0]
    y_range = y_lim[1] - y_lim[0]
    data_aspect = y_range / x_range

    if data_aspect < panel_aspect:
        # Map is wider than tall — expand y to fill height
        needed_y = x_range * panel_aspect
        y_mid = (y_lim[0] + y_lim[1]) / 2
        y_lim = (y_mid - needed_y / 2, y_mid + needed_y / 2)
    else:
        # Map is taller than wide — expand x to fill width
        needed_x = y_range / panel_aspect
        x_mid = (x_lim[0] + x_lim[1]) / 2
        x_lim = (x_mid - needed_x / 2, x_mid + needed_x / 2)

    ax_map.set_xlim(*x_lim)
    ax_map.set_ylim(*y_lim)

    # Graticules (sparse for inset)
    lon_arr = np.linspace(-180, 180, 721)
    lat_arr = np.linspace(-90, -60, 200)
    for lat in [-85, -80, -75]:
        lx, ly = _graticule_line(lon_arr, lat)
        ax_map.plot(lx, ly, color="#cccccc", linewidth=0.3,
                    zorder=0, linestyle="--")
    for lon in range(-180, 181, 30):
        lx, ly = _meridian_line(lat_arr, lon)
        ax_map.plot(lx, ly, color="#cccccc", linewidth=0.3,
                    zorder=0, linestyle=":")

    # Full flight track from navigation
    if nav is not None:
        nav_valid = nav[nav["LAT"].notna() & nav["LON"].notna()]
        if len(nav_valid) > 0:
            tx, ty = _TRANSFORM.transform(nav_valid["LON"].values,
                                          nav_valid["LAT"].values)
            ax_map.plot(tx, ty, color="#555555", linewidth=0.8,
                        alpha=0.5, zorder=2, label=f"F{flt} track")

    # LYRA frames (colored by status)
    if has_coords.any():
        fst = status[has_coords]
        for st in STATUS_ORDER:
            sm = fst == st
            if sm.any():
                ax_map.scatter(fx[sm], fy[sm], s=6, c=STATUS_COLORS[st],
                               edgecolors="white", linewidths=0.15, zorder=4)

    # BEDMAP1 SPRI points (same-source, spatial context)
    if spri_gdf is not None and len(spri_gdf) > 0:
        ax_map.scatter(spri_gdf["PS_x"].values, spri_gdf["PS_y"].values,
                       s=2, facecolors="none", edgecolors=SPRI_COLOR,
                       linewidths=0.2, marker="D", alpha=0.2, zorder=1.5,
                       label="BEDMAP1 SPRI")

    # RIGGS stations — seismic vs radar, filled if matched to flight
    if riggs_df is not None and len(riggs_df) > 0:
        # Determine which stations were matched (used in left panel comparison)
        matched_stns = set()
        if "riggs_stn_idx" in merged.columns:
            idx_vals = merged["riggs_stn_idx"].dropna().values
            matched_stns = set(int(i) for i in idx_vals if i >= 0)
        # Map riggs_df row positions to their original index for matching
        riggs_idx = riggs_df.index.values
        is_matched = np.isin(riggs_idx, list(matched_stns))

        seis = riggs_df[riggs_df["source"] == "seismic"]
        radar = riggs_df[riggs_df["source"] == "radar"]
        seis_matched = np.isin(seis.index.values, list(matched_stns))
        radar_matched = np.isin(radar.index.values, list(matched_stns))

        # Plot unmatched (hollow) then matched (filled) for each source
        if len(seis) > 0:
            seis_label_used = False
            if (~seis_matched).any():
                ax_map.scatter(seis.loc[~seis_matched, "x_ps"].values,
                               seis.loc[~seis_matched, "y_ps"].values,
                               s=12, facecolors="none",
                               edgecolors=RIGGS_SEIS_COLOR,
                               linewidths=0.6, marker="s", zorder=6,
                               label="RIGGS seismic")
                seis_label_used = True
            if seis_matched.any():
                ax_map.scatter(seis.loc[seis_matched, "x_ps"].values,
                               seis.loc[seis_matched, "y_ps"].values,
                               s=16, facecolors=RIGGS_SEIS_COLOR,
                               edgecolors=RIGGS_SEIS_COLOR,
                               linewidths=0.6, marker="s", zorder=6.5,
                               label=("_nolegend_" if seis_label_used
                                      else "RIGGS seismic"))
        if len(radar) > 0:
            radar_label_used = False
            if (~radar_matched).any():
                ax_map.scatter(radar.loc[~radar_matched, "x_ps"].values,
                               radar.loc[~radar_matched, "y_ps"].values,
                               s=10, facecolors="none",
                               edgecolors=RIGGS_RADAR_COLOR,
                               linewidths=0.5, marker="s", zorder=5.5,
                               label="RIGGS radar")
                radar_label_used = True
            if radar_matched.any():
                ax_map.scatter(radar.loc[radar_matched, "x_ps"].values,
                               radar.loc[radar_matched, "y_ps"].values,
                               s=14, facecolors=RIGGS_RADAR_COLOR,
                               edgecolors=RIGGS_RADAR_COLOR,
                               linewidths=0.5, marker="s", zorder=6,
                               label=("_nolegend_" if radar_label_used
                                      else "RIGGS radar"))

    # Geographic labels (only those visible in extent)
    for lon, lat, text, fs in [
        (-155, -79.5, "Ross Ice\nShelf", 6),
        (-130, -80.5, "Siple Coast", 5.5),
        (170, -78.5, "Ross Sea", 5.5),
    ]:
        gx, gy = _TRANSFORM.transform(np.array([lon]), np.array([lat]))
        if x_lim[0] < gx[0] < x_lim[1] and y_lim[0] < gy[0] < y_lim[1]:
            ax_map.text(gx[0], gy[0], text, fontsize=fs, color="#557799",
                        ha="center", va="center", fontstyle="italic",
                        zorder=7,
                        path_effects=[pe.withStroke(linewidth=1.5,
                                                    foreground="white")])

    # Scale bar
    sb_len = 100_000  # 100 km
    sb_x0 = x_lim[0] + 0.06 * (x_lim[1] - x_lim[0])
    sb_y0 = y_lim[0] + 0.06 * (y_lim[1] - y_lim[0])
    ax_map.plot([sb_x0, sb_x0 + sb_len], [sb_y0, sb_y0],
                color="k", linewidth=1.2, solid_capstyle="butt", zorder=8)
    for xv in [sb_x0, sb_x0 + sb_len]:
        ax_map.plot([xv, xv], [sb_y0 - 8_000, sb_y0 + 8_000],
                    color="k", linewidth=0.8, zorder=8)
    ax_map.text(sb_x0 + sb_len / 2, sb_y0 + 15_000, "100 km",
                fontsize=4.5, ha="center", va="bottom")

    # Axes formatting
    ax_map.set_aspect("equal")
    ax_map.legend(loc="upper left", fontsize=6, markerscale=0.8,
                  handletextpad=0.3, borderpad=0.4,
                  framealpha=0.85, edgecolor="#cccccc")

    # Tick labels in km, matching left panel font sizes
    def _m2km(x, _pos=None):
        return f"{x / 1e3:.0f}"
    ax_map.xaxis.set_major_formatter(FuncFormatter(_m2km))
    ax_map.yaxis.set_major_formatter(FuncFormatter(_m2km))
    ax_map.xaxis.set_major_locator(plt.MultipleLocator(300_000))
    ax_map.yaxis.set_major_locator(plt.MultipleLocator(200_000))
    ax_map.tick_params(labelsize=7, direction="in", pad=2)
    ax_map.set_xlabel("PS easting (km)", fontsize=8)
    ax_map.set_ylabel("PS northing (km)", fontsize=8)

    # Enable all spines for the map inset
    for spine in ax_map.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.6)


# -- 1:1 scatter panel helper --------------------------------------------------

ASTRA_COLOR = "#7570b3"  # purple (ColorBrewer Dark2)


def _draw_1to1_panel(ax, ref_vals: np.ndarray, lyra_vals: np.ndarray,
                     title: str, ref_label: str,
                     color: str | np.ndarray = "#333333",
                     marker: str = "o", size: float = 18,
                     labels: list[str] | None = None,
                     label_colors: list[str] | None = None,
                     groups: dict | None = None):
    """Draw a 1:1 scatter comparison on the given axes.

    Parameters
    ----------
    groups : dict mapping group_name -> dict with keys
        mask (bool array), color, marker, size, label
        If provided, *color/marker/size* are ignored and each group
        is plotted separately with its own legend entry.
    labels : per-point text annotations (station names, CBDs, etc.)
    label_colors : per-point annotation colors (defaults to *color*).
    """
    all_h = np.concatenate([ref_vals, lyra_vals])
    finite = np.isfinite(all_h)
    if not finite.any():
        return
    lo = max(0, float(np.nanmin(all_h[finite])) - 50)
    hi = float(np.nanmax(all_h[finite])) + 50

    # 1:1 line
    ax.plot([lo, hi], [lo, hi], color="#999999", linewidth=0.8,
            linestyle="--", zorder=1)

    # Scatter
    if groups:
        for gname, g in groups.items():
            m = g["mask"]
            if not m.any():
                continue
            ax.scatter(ref_vals[m], lyra_vals[m], s=g.get("size", size),
                       facecolors=g["color"], edgecolors="white",
                       linewidths=0.4, marker=g.get("marker", "o"),
                       zorder=3, label=g.get("label", gname))
    else:
        ax.scatter(ref_vals, lyra_vals, s=size, facecolors=color,
                   edgecolors="white", linewidths=0.4, marker=marker,
                   zorder=3)

    # Per-point labels
    if labels is not None:
        for i, lbl in enumerate(labels):
            if not lbl:
                continue
            clr = label_colors[i] if label_colors else (
                color if isinstance(color, str) else "#333333")
            ax.annotate(lbl, (ref_vals[i], lyra_vals[i]),
                        textcoords="offset points", xytext=(4, 3),
                        fontsize=5, color=clr, alpha=0.85,
                        path_effects=[pe.withStroke(linewidth=1.2,
                                                    foreground="white")])

    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal")
    ax.set_xlabel(f"{ref_label} $h_{{ice}}$ (m)", fontsize=7)
    ax.set_ylabel("LYRA $h_{ice}$ (m)", fontsize=7)
    ax.set_title(title, fontsize=8, fontweight="bold", pad=4)

    # Stats box
    valid = np.isfinite(ref_vals) & np.isfinite(lyra_vals)
    diff = lyra_vals[valid] - ref_vals[valid]
    n = len(diff)
    if n == 0:
        return
    bias = float(np.mean(diff))
    rmse = float(np.sqrt(np.mean(diff ** 2)))
    md = float(np.median(np.abs(diff)))
    txt = (f"n = {n}\n"
           f"bias = {bias:+.0f} m\n"
           f"RMSE = {rmse:.0f} m\n"
           f"|diff|$_{{50}}$ = {md:.0f} m")
    if n >= 3:
        r = float(np.corrcoef(ref_vals[valid], lyra_vals[valid])[0, 1])
        txt += f"\nr = {r:.2f}"
    ax.text(0.97, 0.03, txt, transform=ax.transAxes,
            fontsize=6, va="bottom", ha="right",
            bbox=dict(facecolor="white", edgecolor="#cccccc",
                      pad=2.5, alpha=0.9))

    if groups:
        ax.legend(loc="upper left", fontsize=6, markerscale=0.8,
                  handletextpad=0.3)

    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.5)


# -- Figure generation ---------------------------------------------------------

def make_validation_figure(merged: pd.DataFrame, flt: int, out_path: Path,
                           nav: pd.DataFrame | None = None,
                           riggs_df: pd.DataFrame | None = None,
                           spri_gdf: gpd.GeoDataFrame | None = None,
                           riggs_xover: pd.DataFrame | None = None):
    """Generate validation figure: along-track + map + 1:1 scatter panels.

    Row 0: Along-track ice thickness | Spatial map
    Row 1: 1:1 scatter panels (ASTRA, RIGGS crossover, BEDMAP1 SPRI)
    Row 1 is only drawn when at least one comparison dataset has matches.
    """

    _setup_rcparams()

    # Filter out uncertain reflectors (e.g. internal horizons flagged post-hoc)
    if "reflector_type" in merged.columns:
        _bed_mask = merged["reflector_type"].isin(["bed", None]) | merged["reflector_type"].isna()
        n_uncertain = int((~_bed_mask).sum())
        merged = merged[_bed_mask].copy()
    else:
        n_uncertain = 0

    cbd = merged["cbd"].values
    status = merged["echo_status"].values
    h_ice = merged["h_ice_m"].values
    good = merged["echo_status"] == "good"

    # Count statistics
    counts = {st: int((status == st).sum()) for st in STATUS_ORDER}

    # Determine which scatter panels to show
    has_astra_scatter = ("h_ice_astra" in merged.columns
                         and (good & merged["h_ice_astra"].notna()).any())
    has_riggs_scatter = riggs_xover is not None and len(riggs_xover) > 0
    has_spri_scatter = ("spri_ice" in merged.columns
                        and (good & merged["spri_ice"].notna()).any())
    scatter_panels = []
    if has_astra_scatter:
        scatter_panels.append("astra")
    if has_riggs_scatter:
        scatter_panels.append("riggs")
    if has_spri_scatter:
        scatter_panels.append("spri")
    n_scatter = len(scatter_panels)

    # -- Layout ------------------------------------------------------------
    if n_scatter > 0:
        fig = plt.figure(figsize=(12, 8.5))
        gs = fig.add_gridspec(2, max(3, n_scatter),
                              height_ratios=[1.0, 0.85],
                              width_ratios=[1.8, 1, 0.01]
                              if n_scatter <= 2
                              else [1] * max(3, n_scatter),
                              wspace=0.35, hspace=0.38,
                              left=0.06, right=0.97, top=0.93, bottom=0.06)
        # Top row spans: along-track gets cols 0-1, map gets col 2
        # But with 3+ scatter panels we need flexible columns
        # Use nested gridspec for top row
        gs_top = gs[0, :].subgridspec(1, 2, width_ratios=[1.8, 1],
                                       wspace=0.30)
        ax_thk = fig.add_subplot(gs_top[0, 0])
        ax_map = fig.add_subplot(gs_top[0, 1])

        # Bottom row: scatter panels evenly distributed
        gs_bot = gs[1, :].subgridspec(1, 3, wspace=0.40)
        scatter_axes = []
        for i in range(n_scatter):
            scatter_axes.append(fig.add_subplot(gs_bot[0, i]))
    else:
        fig = plt.figure(figsize=(12, 4.5))
        gs = fig.add_gridspec(1, 2, width_ratios=[1.8, 1], wspace=0.30,
                              left=0.06, right=0.97, top=0.88, bottom=0.12)
        ax_thk = fig.add_subplot(gs[0, 0])
        ax_map = fig.add_subplot(gs[0, 1])

    # -- Top-left panel: Along-track ice thickness -------------------------

    # RIGGS (independent) -- seismic vs radar distinction
    has_riggs = "riggs_ice" in merged.columns
    if has_riggs:
        rm = merged["riggs_ice"].notna()
        if rm.any():
            has_source = "riggs_source" in merged.columns
            if has_source:
                rm_seis = rm & (merged["riggs_source"] == "seismic")
                rm_radar = rm & (merged["riggs_source"] == "radar")
            else:
                rm_seis = rm
                rm_radar = pd.Series(False, index=merged.index)

            if rm_seis.any():
                n_seis_stns = (int(merged.loc[rm_seis, "riggs_stn_idx"].nunique())
                               if "riggs_stn_idx" in merged.columns
                               else int(rm_seis.sum()))
                md_seis = merged.loc[rm_seis, "riggs_dist"].median()
                ax_thk.scatter(cbd[rm_seis], merged["riggs_ice"].values[rm_seis],
                               s=30, facecolors="none",
                               edgecolors=RIGGS_SEIS_COLOR,
                               linewidths=0.9, marker="s", alpha=0.8, zorder=2,
                               label=f"RIGGS seismic ($n_{{\\mathrm{{stn}}}}$="
                                     f"{n_seis_stns}, "
                                     f"$\\tilde{{d}}$={md_seis/1000:.0f} km)")

            if rm_radar.any():
                n_radar_stns = (int(merged.loc[rm_radar, "riggs_stn_idx"].nunique())
                                if "riggs_stn_idx" in merged.columns
                                else int(rm_radar.sum()))
                md_radar = merged.loc[rm_radar, "riggs_dist"].median()
                ax_thk.scatter(cbd[rm_radar],
                               merged["riggs_ice"].values[rm_radar],
                               s=25, facecolors="none",
                               edgecolors=RIGGS_RADAR_COLOR,
                               linewidths=0.8, marker="s", alpha=0.8, zorder=2,
                               label=f"RIGGS radar ($n_{{\\mathrm{{stn}}}}$="
                                     f"{n_radar_stns}, "
                                     f"$\\tilde{{d}}$={md_radar/1000:.0f} km)")

            if ("riggs_stn_name" in merged.columns
                    and "riggs_stn_idx" in merged.columns):
                labeled = set()
                for _, row in merged[rm].iterrows():
                    stn_idx = row.get("riggs_stn_idx", -1)
                    stn_name = row.get("riggs_stn_name", "")
                    src = row.get("riggs_source", "seismic")
                    clr = (RIGGS_SEIS_COLOR if src == "seismic"
                           else RIGGS_RADAR_COLOR)
                    if stn_idx >= 0 and stn_idx not in labeled and stn_name:
                        ax_thk.annotate(stn_name,
                                        (row["cbd"], row["riggs_ice"]),
                                        textcoords="offset points",
                                        xytext=(4, 4), fontsize=5.5,
                                        color=clr, alpha=0.8)
                        labeled.add(stn_idx)

    # BEDMAP1 SPRI (same-source, spatial context only)
    has_spri_track = "spri_ice" in merged.columns
    if has_spri_track:
        sm = merged["spri_ice"].notna()
        if sm.any():
            n_spri = int(sm.sum())
            md_spri = merged.loc[sm, "spri_dist"].median()
            ax_thk.scatter(cbd[sm], merged["spri_ice"].values[sm],
                           s=18, facecolors="none", edgecolors=SPRI_COLOR,
                           linewidths=0.7, marker="D", alpha=0.5, zorder=1.5,
                           label=f"BEDMAP1 SPRI ($n$={n_spri}, "
                                 f"$\\tilde{{d}}$={md_spri/1000:.0f} km)")

    # LYRA h_ice by status
    for st in STATUS_ORDER:
        mask = status == st
        if not mask.any():
            continue
        vals = h_ice[mask]
        valid = np.isfinite(vals)
        if valid.any():
            ax_thk.scatter(cbd[mask][valid], vals[valid],
                           s=18, c=STATUS_COLORS[st],
                           edgecolors="white", linewidths=0.3, zorder=3)

    # No-detection rug marks
    for st, ypos in [("no_bed", 0.02), ("no_surface", 0.06)]:
        mask = status == st
        if not mask.any():
            continue
        for c in cbd[mask]:
            ax_thk.axvline(c, ymin=0, ymax=ypos, color=STATUS_COLORS[st],
                           linewidth=0.6, alpha=0.6)
        ax_thk.plot([], [], color=STATUS_COLORS[st], linewidth=1.5,
                    label=f"{STATUS_LABELS[st]} ({counts[st]})")

    ax_thk.set_ylabel("Ice thickness (m)")
    ax_thk.set_xlabel("CBD number")
    ax_thk.legend(loc="upper right", markerscale=1.2, handletextpad=0.4,
                  fontsize=6.5)
    _panel_label(ax_thk, "a")

    # -- Title -------------------------------------------------------------

    subtitle_parts = []
    for st in STATUS_ORDER:
        if counts[st] > 0:
            subtitle_parts.append(f"{counts[st]} {STATUS_LABELS[st].lower()}")
    if n_uncertain > 0:
        subtitle_parts.append(f"{n_uncertain} uncertain reflector")
    fig.suptitle(f"F{flt} \u2014 Validation",
                 fontsize=11, fontweight="bold", y=0.99)
    fig.text(0.5, 0.955, " | ".join(subtitle_parts),
             ha="center", fontsize=7, color="#666666")

    # -- Top-right panel: Map ----------------------------------------------

    _draw_inset_map(ax_map, nav, merged, status, riggs_df, spri_gdf, flt)
    _panel_label(ax_map, "b")

    # -- Bottom row: 1:1 scatter panels ------------------------------------

    panel_idx = 0
    panel_letter = ord("c")

    if has_astra_scatter:
        ax_a = scatter_axes[panel_idx]
        both = merged[good & merged["h_ice_astra"].notna()
                      & merged["h_ice_m"].notna()]
        _draw_1to1_panel(
            ax_a,
            ref_vals=both["h_ice_astra"].values,
            lyra_vals=both["h_ice_m"].values,
            title=f"ASTRA (d = 0, n = {len(both)})",
            ref_label="ASTRA",
            color=ASTRA_COLOR, marker="o", size=14,
        )
        _panel_label(ax_a, chr(panel_letter))
        panel_letter += 1
        panel_idx += 1

    if has_riggs_scatter:
        ax_r = scatter_axes[panel_idx]
        xo = riggs_xover
        seis_mask = (xo["source"] == "seismic").values
        radar_mask = ~seis_mask
        stn_labels = [f"{r['station']} ({r['dist_m']/1000:.0f} km)"
                      for _, r in xo.iterrows()]
        lbl_colors = [RIGGS_SEIS_COLOR if s == "seismic" else RIGGS_RADAR_COLOR
                      for s in xo["source"]]
        n_s = int(seis_mask.sum())
        n_r = int(radar_mask.sum())
        groups = {}
        if seis_mask.any():
            groups["seis"] = {"mask": seis_mask, "color": RIGGS_SEIS_COLOR,
                              "marker": "s", "size": 40,
                              "label": f"Seismic (n={n_s})"}
        if radar_mask.any():
            groups["radar"] = {"mask": radar_mask, "color": RIGGS_RADAR_COLOR,
                               "marker": "s", "size": 35,
                               "label": f"Radar (n={n_r})"}
        _draw_1to1_panel(
            ax_r,
            ref_vals=xo["h_riggs"].values,
            lyra_vals=xo["h_lyra"].values,
            title=f"RIGGS crossover (n = {len(xo)} stn)",
            ref_label="RIGGS",
            groups=groups,
            labels=stn_labels, label_colors=lbl_colors,
        )
        _panel_label(ax_r, chr(panel_letter))
        panel_letter += 1
        panel_idx += 1

    if has_spri_scatter:
        ax_s = scatter_axes[panel_idx]
        both = merged[good & merged["spri_ice"].notna()
                      & merged["h_ice_m"].notna()]
        _draw_1to1_panel(
            ax_s,
            ref_vals=both["spri_ice"].values,
            lyra_vals=both["h_ice_m"].values,
            title=f"BEDMAP1 SPRI (same-source, n = {len(both)})",
            ref_label="BEDMAP1",
            color=SPRI_COLOR, marker="D", size=12,
        )
        _panel_label(ax_s, chr(panel_letter))
        panel_idx += 1

    # Save
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  Validation figure \u2192 {out_path}")


# -- Standalone RIGGS map ------------------------------------------------------

def plot_riggs_stations(out_path: Path | None = None) -> Path:
    """Generate a standalone map of all RIGGS stations on the Ross Ice Shelf.

    Stations colored by measurement source: red squares = seismic,
    orange squares = radar.  Station names labeled next to each marker.

    Returns the output path.
    """
    _setup_rcparams()

    riggs_df = load_riggs_stations()
    if riggs_df is None or len(riggs_df) == 0:
        sys.exit("No RIGGS stations found in " + str(RIGGS_CSV))

    if out_path is None:
        out_path = OUTPUT_BASE / "RIGGS_stations_map.png"

    n_seis = int((riggs_df["source"] == "seismic").sum())
    n_radar = int((riggs_df["source"] == "radar").sum())
    print(f"  {len(riggs_df)} RIGGS stations ({n_seis} seismic, {n_radar} radar)")

    fig, ax = plt.subplots(figsize=(10, 10))

    # Basemap
    land = load_basemap_ps()
    land.plot(ax=ax, color="#e4eef5", edgecolor="#7aadbb",
              linewidth=0.4, zorder=1)

    # Map extent: Ross Ice Shelf region (~75-85S, 150E-150W i.e. 150-210E)
    # Convert corner coordinates to PS
    corner_lons = [150, 210, 150, 210, 180, 180, 150, 210]
    corner_lats = [-75, -75, -85, -85, -75, -85, -80, -80]
    cx, cy = _TRANSFORM.transform(corner_lons, corner_lats)
    margin = 100_000
    x_lim = (min(cx) - margin, max(cx) + margin)
    y_lim = (min(cy) - margin, max(cy) + margin)
    ax.set_xlim(*x_lim)
    ax.set_ylim(*y_lim)

    # Graticules
    lon_arr = np.linspace(-180, 180, 721)
    lat_arr = np.linspace(-90, -60, 200)
    for lat in range(-85, -74):
        lx, ly = _graticule_line(lon_arr, lat)
        ax.plot(lx, ly, color="#cccccc", linewidth=0.3,
                zorder=0, linestyle="--")
    for lon in range(-180, 181, 10):
        lx, ly = _meridian_line(lat_arr, lon)
        ax.plot(lx, ly, color="#cccccc", linewidth=0.3,
                zorder=0, linestyle=":")

    # Graticule labels
    for lat in range(-85, -74, 2):
        gx, gy = _TRANSFORM.transform(np.array([180.0]), np.array([float(lat)]))
        if x_lim[0] < gx[0] < x_lim[1] and y_lim[0] < gy[0] < y_lim[1]:
            ax.text(gx[0], gy[0], f"{abs(lat)}S",
                    fontsize=6, color="#999999", ha="left", va="bottom",
                    path_effects=[pe.withStroke(linewidth=1.5,
                                                foreground="white")])
    for lon in range(150, 220, 10):
        disp_lon = lon if lon <= 180 else lon - 360
        label = f"{abs(disp_lon)}{'E' if disp_lon >= 0 else 'W'}"
        gx, gy = _TRANSFORM.transform(np.array([float(disp_lon)]),
                                       np.array([-75.0]))
        if x_lim[0] < gx[0] < x_lim[1] and y_lim[0] < gy[0] < y_lim[1]:
            ax.text(gx[0], gy[0], label,
                    fontsize=6, color="#999999", ha="center", va="bottom",
                    path_effects=[pe.withStroke(linewidth=1.5,
                                                foreground="white")])

    # Plot stations by source
    seis = riggs_df[riggs_df["source"] == "seismic"]
    radar = riggs_df[riggs_df["source"] == "radar"]

    if len(seis) > 0:
        ax.scatter(seis["x_ps"].values, seis["y_ps"].values,
                   s=40, facecolors=RIGGS_SEIS_COLOR,
                   edgecolors="white", linewidths=0.5, marker="s",
                   zorder=5, label=f"Seismic ({n_seis})")
    if len(radar) > 0:
        ax.scatter(radar["x_ps"].values, radar["y_ps"].values,
                   s=35, facecolors=RIGGS_RADAR_COLOR,
                   edgecolors="white", linewidths=0.5, marker="s",
                   zorder=4, label=f"Radar ({n_radar})")

    # Station name labels
    for _, row in riggs_df.iterrows():
        clr = (RIGGS_SEIS_COLOR if row["source"] == "seismic"
               else RIGGS_RADAR_COLOR)
        ax.annotate(row["Station"],
                    (row["x_ps"], row["y_ps"]),
                    textcoords="offset points", xytext=(5, 3),
                    fontsize=4.5, color=clr, alpha=0.85,
                    path_effects=[pe.withStroke(linewidth=1.2,
                                                foreground="white")])

    # Geographic labels
    for lon, lat, text, fs in [
        (-155, -79.5, "Ross Ice\nShelf", 9),
        (-130, -80.5, "Siple Coast", 7),
        (170, -78.5, "Ross Sea", 7),
        (170, -77.5, "McMurdo\nSound", 6),
        (-150, -85, "South", 6),
    ]:
        gx, gy = _TRANSFORM.transform(np.array([lon]), np.array([lat]))
        if x_lim[0] < gx[0] < x_lim[1] and y_lim[0] < gy[0] < y_lim[1]:
            ax.text(gx[0], gy[0], text, fontsize=fs, color="#557799",
                    ha="center", va="center", fontstyle="italic",
                    zorder=7,
                    path_effects=[pe.withStroke(linewidth=2,
                                                foreground="white")])

    # Scale bar
    sb_len = 200_000  # 200 km
    sb_x0 = x_lim[0] + 0.06 * (x_lim[1] - x_lim[0])
    sb_y0 = y_lim[0] + 0.05 * (y_lim[1] - y_lim[0])
    ax.plot([sb_x0, sb_x0 + sb_len], [sb_y0, sb_y0],
            color="k", linewidth=1.5, solid_capstyle="butt", zorder=8)
    for xv in [sb_x0, sb_x0 + sb_len]:
        ax.plot([xv, xv], [sb_y0 - 12_000, sb_y0 + 12_000],
                color="k", linewidth=1, zorder=8)
    ax.text(sb_x0 + sb_len / 2, sb_y0 + 20_000, "200 km",
            fontsize=7, ha="center", va="bottom")

    # Axes formatting
    ax.set_aspect("equal")
    ax.legend(loc="upper left", fontsize=8, markerscale=1.0,
              framealpha=0.9, edgecolor="#cccccc")

    def _m2km(x, _pos=None):
        return f"{x / 1e3:.0f}"
    ax.xaxis.set_major_formatter(FuncFormatter(_m2km))
    ax.yaxis.set_major_formatter(FuncFormatter(_m2km))
    ax.tick_params(labelsize=7, direction="in", pad=2)
    ax.set_xlabel("PS easting (km)", fontsize=9)
    ax.set_ylabel("PS northing (km)", fontsize=9)

    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.6)

    fig.suptitle("RIGGS stations -- Ross Ice Shelf",
                 fontsize=12, fontweight="bold", y=0.95)
    fig.text(0.5, 0.91,
             f"{len(riggs_df)} stations (Bentley 1984; "
             f"{n_seis} seismic, {n_radar} radar)",
             ha="center", fontsize=8, color="#666666")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  RIGGS station map -> {out_path}")
    return out_path


# -- RIGGS crossover analysis --------------------------------------------------

def riggs_crossover(merged: pd.DataFrame, riggs_df: pd.DataFrame,
                    radius_m: float = MATCH_RADIUS_M
                    ) -> pd.DataFrame | None:
    """Per-station RIGGS crossover: nearest good LYRA frame per station.

    For each RIGGS station within *radius_m* of the flight, finds the single
    nearest LYRA good-echo frame and extracts its h_ice.

    Returns a DataFrame with one row per matched station:
        station, source, h_riggs, h_lyra, dist_m, cbd, lat, lon
    or None if no matches.
    """
    _rt_ok = (merged["reflector_type"].isin(["bed", None])
              | merged["reflector_type"].isna()) if "reflector_type" in merged.columns else True
    good = merged[(merged["echo_status"] == "good") & _rt_ok
                  & merged["LAT"].notna() & merged["LON"].notna()].copy()
    if len(good) == 0 or riggs_df is None or len(riggs_df) == 0:
        return None

    # Project good-echo frames to PS
    gx, gy = _TRANSFORM.transform(good["LON"].values, good["LAT"].values)
    good_xy = np.column_stack([gx, gy])

    rows = []
    for idx, stn in riggs_df.iterrows():
        stn_xy = np.array([[stn["x_ps"], stn["y_ps"]]])
        dists = np.sqrt(((good_xy - stn_xy) ** 2).sum(axis=1))
        nearest = int(np.argmin(dists))
        d = dists[nearest]
        if d > radius_m:
            continue
        frame = good.iloc[nearest]
        rows.append({
            "station": stn["Station"],
            "source": stn["source"],
            "h_riggs": float(stn["h_ice"]),
            "h_lyra": float(frame["h_ice_m"]),
            "dist_m": round(float(d), 0),
            "cbd": int(frame["cbd"]),
            "lat": float(frame["LAT"]),
            "lon": float(frame["LON"]),
        })

    if not rows:
        return None
    return pd.DataFrame(rows)


def plot_riggs_crossover(xover: pd.DataFrame, flt: int, out_path: Path):
    """1:1 scatter plot of RIGGS vs LYRA ice thickness at crossover stations."""
    _setup_rcparams()

    fig, ax = plt.subplots(figsize=(5.5, 5.5))

    seis = xover[xover["source"] == "seismic"]
    radar = xover[xover["source"] == "radar"]

    # 1:1 line
    all_h = np.concatenate([xover["h_riggs"].values, xover["h_lyra"].values])
    lo, hi = float(np.min(all_h)) - 50, float(np.max(all_h)) + 50
    lo = max(0, lo)
    ax.plot([lo, hi], [lo, hi], color="#999999", linewidth=0.8,
            linestyle="--", zorder=1, label="1:1")

    # Scatter by source
    if len(seis) > 0:
        ax.scatter(seis["h_riggs"], seis["h_lyra"], s=50,
                   facecolors=RIGGS_SEIS_COLOR, edgecolors="white",
                   linewidths=0.5, marker="s", zorder=4,
                   label=f"Seismic (n={len(seis)})")
    if len(radar) > 0:
        ax.scatter(radar["h_riggs"], radar["h_lyra"], s=45,
                   facecolors=RIGGS_RADAR_COLOR, edgecolors="white",
                   linewidths=0.5, marker="s", zorder=3,
                   label=f"Radar (n={len(radar)})")

    # Station name annotations
    for _, row in xover.iterrows():
        clr = (RIGGS_SEIS_COLOR if row["source"] == "seismic"
               else RIGGS_RADAR_COLOR)
        ax.annotate(f"{row['station']} ({row['dist_m']/1000:.0f} km)",
                    (row["h_riggs"], row["h_lyra"]),
                    textcoords="offset points", xytext=(5, 4),
                    fontsize=5.5, color=clr, alpha=0.85,
                    path_effects=[pe.withStroke(linewidth=1.2,
                                                foreground="white")])

    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal")
    ax.set_xlabel("RIGGS $h_{ice}$ (m)")
    ax.set_ylabel("LYRA $h_{ice}$ (m)")
    ax.legend(loc="upper left", fontsize=7)

    # Stats annotation
    diff = xover["h_lyra"].values - xover["h_riggs"].values
    n = len(diff)
    bias = float(np.mean(diff))
    rmse = float(np.sqrt(np.mean(diff ** 2)))
    md = float(np.median(np.abs(diff)))
    stats_text = (f"n = {n} stations\n"
                  f"bias = {bias:+.0f} m\n"
                  f"RMSE = {rmse:.0f} m\n"
                  f"|diff|$_{{50}}$ = {md:.0f} m")
    if n >= 3:
        r = float(np.corrcoef(xover["h_riggs"], xover["h_lyra"])[0, 1])
        stats_text += f"\nr = {r:.2f}"
    ax.text(0.97, 0.03, stats_text, transform=ax.transAxes,
            fontsize=7, va="bottom", ha="right",
            bbox=dict(facecolor="white", edgecolor="#cccccc",
                      pad=3, alpha=0.9))

    # Separate stats for seismic only
    if len(seis) >= 2:
        sd = seis["h_lyra"].values - seis["h_riggs"].values
        seis_text = (f"Seismic only (n={len(seis)}):\n"
                     f"  bias = {np.mean(sd):+.0f} m, "
                     f"RMSE = {np.sqrt(np.mean(sd**2)):.0f} m")
        ax.text(0.03, 0.97, seis_text, transform=ax.transAxes,
                fontsize=6, va="top", ha="left", color=RIGGS_SEIS_COLOR,
                bbox=dict(facecolor="white", edgecolor="#cccccc",
                          pad=2, alpha=0.85))

    fig.suptitle(f"F{flt} -- RIGGS crossover validation",
                 fontsize=10, fontweight="bold")
    fig.text(0.5, 0.91,
             "Nearest good LYRA echo per RIGGS station "
             f"(max {MATCH_RADIUS_M/1000:.0f} km)",
             ha="center", fontsize=7, color="#666666")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  RIGGS crossover figure -> {out_path}")


# -- Main ----------------------------------------------------------------------

def _comparison_stats(lyra_vals: np.ndarray, ref_vals: np.ndarray) -> dict:
    """Compute comparison statistics between LYRA and a reference dataset."""
    diff = lyra_vals - ref_vals
    stats = {
        "n": int(len(diff)),
        "mean_diff_m": round(float(np.mean(diff)), 1),
        "std_diff_m": round(float(np.std(diff)), 1),
        "rmse_m": round(float(np.sqrt(np.mean(diff**2))), 1),
        "median_abs_diff_m": round(float(np.median(np.abs(diff))), 1),
    }
    if len(diff) >= 3:
        r = np.corrcoef(ref_vals, lyra_vals)[0, 1]
        stats["correlation_r"] = round(float(r), 3)
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="LYRA Phase 5 validation with BEDMAP1 comparison")
    parser.add_argument("flight", type=int, nargs="?", default=None,
                        help="Flight number (e.g. 126)")
    parser.add_argument("--radius", type=float, default=MATCH_RADIUS_M,
                        help=f"BEDMAP1 match radius in metres "
                             f"(default {MATCH_RADIUS_M})")
    parser.add_argument("--riggs-map", action="store_true",
                        help="Generate standalone RIGGS station map and exit")
    parser.add_argument("--recompute-alignment", action="store_true",
                        help="Force recomputation of CBD-to-nav alignment")
    parser.add_argument("--offset", type=int, default=None,
                        help="Force CBD-to-nav offset (overrides auto-alignment)")
    args = parser.parse_args()

    # -- Standalone RIGGS map mode -----------------------------------------
    if args.riggs_map:
        print("RIGGS station map")
        plot_riggs_stations()
        return

    if args.flight is None:
        parser.error("flight number is required (or use --riggs-map)")

    flt = args.flight
    report: dict = {"flight": flt, "match_radius_km": args.radius / 1000}
    print(f"LYRA Validation \u2014 F{flt}")

    # -- Echoes ------------------------------------------------------------
    print("  Loading phase 4 echoes ...")
    echoes = load_echoes(flt)
    print(f"    {len(echoes)} frames")

    # -- CBD-to-nav alignment -----------------------------------------------
    out_dir = OUTPUT_BASE / f"F{flt}"
    alignment = None
    if args.offset is not None:
        # Manual offset override -- build a synthetic high-confidence result
        print(f"  Using manual CBD offset: {args.offset:+d}")
        alignment = _lyra.AlignmentResult(
            flight=flt, offset=args.offset, correlation=1.0,
            n_matched=0, n_reference=0, search_range=(0, 0),
            second_best_corr=0.0, confidence="manual",
            riggs_validation=None, n_anchor_windows=0, method="manual")
        _lyra.save_alignment(alignment, out_dir)
    else:
        if not args.recompute_alignment:
            alignment = _lyra.load_alignment(flt, out_dir)
        if alignment is None:
            print("  Computing CBD-to-nav alignment ...")
            echoes_csv = out_dir / "phase4" / f"F{flt}_echoes.csv"
            alignment = _lyra.align_cbd_to_nav(echoes_csv, flt)
            _lyra.save_alignment(alignment, out_dir)
    anchor_str = (f", {alignment.n_anchor_windows} anchor windows"
                  if alignment.n_anchor_windows > 0 else "")
    print(f"    CBD offset: {alignment.offset:+d} "
          f"(r={alignment.correlation:.3f}, "
          f"method={alignment.method}{anchor_str}, "
          f"confidence={alignment.confidence})")
    report["alignment"] = {
        "offset": alignment.offset,
        "correlation": alignment.correlation,
        "n_matched": alignment.n_matched,
        "confidence": alignment.confidence,
        "method": alignment.method,
        "n_anchor_windows": alignment.n_anchor_windows,
        "riggs_validation": alignment.riggs_validation,
    }

    # -- Rose 1978 navigation correction -------------------------------------
    nav_correction = _lyra.load_nav_correction(flt, out_dir)
    if nav_correction is None:
        nav_correction = _lyra.build_nav_correction(flt)
        if nav_correction is not None:
            _lyra.save_nav_correction(nav_correction, out_dir)
    if nav_correction is not None:
        n_fixes = len(nav_correction.fix_cbds)
        max_corr_km = max(
            np.sqrt(dx**2 + dy**2) / 1000
            for dx, dy in zip(nav_correction.dx_at_fixes,
                              nav_correction.dy_at_fixes))
        print(f"    Nav correction: {n_fixes} fix points, "
              f"max |corr| = {max_corr_km:.2f} km")
    else:
        print("    Nav correction: none (no Rose fix data)")
    report["nav_correction"] = {
        "applied": nav_correction is not None,
        "n_fixes": len(nav_correction.fix_cbds) if nav_correction else 0,
    }

    # -- Enrich echoes CSV with lat/lon ------------------------------------
    echoes_csv_path = out_dir / "phase4" / f"F{flt}_echoes.csv"
    _lyra.enrich_echoes_with_nav(flt, echoes_csv_path, offset=alignment.offset,
                                 nav_correction=nav_correction)
    print(f"    Enriched echoes CSV with lat/lon (offset={alignment.offset:+d})")

    # -- Navigation --------------------------------------------------------
    print("  Loading navigation ...")
    nav = load_navigation(flt)
    print(f"    {len(nav)} nav waypoints")

    print("  Merging echoes with navigation (offset={:+d}) ...".format(alignment.offset))
    merged = merge_with_nav(echoes, nav, offset=alignment.offset)
    n_with_nav = int(merged["has_nav"].sum())
    print(f"    {n_with_nav}/{len(merged)} frames matched to coordinates")

    # Apply Rose nav correction to merged LAT/LON
    if nav_correction is not None:
        _apply_nav_correction(merged, nav_correction)

    # Echo status breakdown
    status_counts = merged["echo_status"].value_counts().to_dict()
    cbd_vals = merged["cbd"].dropna()
    tiffs = merged["tiff_id"].unique() if "tiff_id" in merged.columns else []
    good_ice = merged.loc[merged["echo_status"] == "good", "h_ice_m"]

    n_uncertain_total = 0
    if "reflector_type" in merged.columns:
        n_uncertain_total = int((~(merged["reflector_type"].isin(["bed", None])
                                   | merged["reflector_type"].isna())).sum())
    report["echoes"] = {
        "total_frames": len(merged),
        "n_tiffs": len(tiffs),
        "cbd_range": ([int(cbd_vals.min()), int(cbd_vals.max())]
                      if len(cbd_vals) > 0 else None),
        "echo_status": {k: int(v) for k, v in status_counts.items()},
        "n_uncertain_reflector": n_uncertain_total,
    }
    if len(good_ice) > 0:
        report["echoes"]["h_ice_good_frames"] = {
            "min": round(float(good_ice.min()), 1),
            "max": round(float(good_ice.max()), 1),
            "mean": round(float(good_ice.mean()), 1),
            "median": round(float(good_ice.median()), 1),
        }

    # Per-status frame lists (for quick review of problem frames)
    phase4_dir = OUTPUT_BASE / f"F{flt}" / "phase4"
    for st in ("no_bed", "no_surface", "weak_bed"):
        subset = merged[merged["echo_status"] == st]
        if len(subset) == 0:
            continue
        frames = []
        for _, row in subset.iterrows():
            cbd = int(row["cbd"]) if pd.notna(row["cbd"]) else None
            tid = row.get("tiff_id", "")
            file_id = row.get("file_id", "")
            entry = {"cbd": cbd, "tiff_id": str(tid)}
            # Include diagnostic PNG path if it exists
            if file_id:
                png = phase4_dir / f"F{flt}_{file_id}_echoes.png"
                if png.exists():
                    entry["diagnostic_png"] = str(png)
            frames.append(entry)
        # Sort by CBD for easy scanning
        frames.sort(key=lambda f: f["cbd"] if f["cbd"] is not None else 0)
        report["echoes"][f"{st}_frames"] = frames

    report["navigation"] = {
        "nav_cbds": len(nav),
        "frames_with_nav": n_with_nav,
        "frames_total": len(merged),
    }

    # -- ASTRA (primary validation — same frames, d = 0) ------------------
    print("  Loading ASTRA picks ...")
    astra = load_astra(flt)
    if astra is not None:
        n_before = len(merged)
        merged = merged.merge(astra, left_on="cbd", right_on="CBD",
                              how="left", suffixes=("", "_astra_dup"))
        for c in merged.columns:
            if c.endswith("_astra_dup"):
                merged.drop(columns=c, inplace=True)
        n_astra = int(merged["h_ice_astra"].notna().sum())
        print(f"    {n_astra}/{n_before} frames matched to ASTRA picks")
        report["astra"] = {
            "frames_matched": n_astra,
            "frames_total": n_before,
        }
    else:
        print("    No ASTRA picks found for this flight")
        report["astra"] = None

    # -- RIGGS (independent seismic/radar, Bentley 1984) -------------------
    print("  Loading RIGGS stations ...")
    riggs_df = load_riggs_stations()
    has_coords = merged["has_nav"] & merged["LAT"].notna() & merged["LON"].notna()
    for col in ("riggs_ice", "riggs_dist", "riggs_stn_idx", "riggs_stn_name",
                "riggs_source", "spri_ice", "spri_dist"):
        merged[col] = np.nan if col not in ("riggs_stn_name", "riggs_source") else ""

    if riggs_df is not None and has_coords.any():
        lats = merged.loc[has_coords, "LAT"].values
        lons = merged.loc[has_coords, "LON"].values
        r_xy = riggs_df[["x_ps", "y_ps"]].values
        r_thk = riggs_df["h_ice"].values
        r_ice, r_dist, r_idx = match_reference(lats, lons, r_xy, r_thk,
                                                radius_m=args.radius)
        merged.loc[has_coords, "riggs_ice"] = r_ice
        merged.loc[has_coords, "riggs_dist"] = r_dist
        merged.loc[has_coords, "riggs_stn_idx"] = r_idx.astype(float)

        # Map station names and sources
        stn_names = np.where(r_idx >= 0,
                             riggs_df["Station"].values[np.clip(r_idx, 0, None)],
                             "")
        stn_sources = np.where(r_idx >= 0,
                               riggs_df["source"].values[np.clip(r_idx, 0, None)],
                               "")
        merged.loc[has_coords, "riggs_stn_name"] = stn_names
        merged.loc[has_coords, "riggs_source"] = stn_sources

        n_riggs = int(np.isfinite(r_ice).sum())
        unique_stns = set(r_idx[r_idx >= 0])
        n_riggs_stns = len(unique_stns)
        n_total_seis = int(riggs_df["source"].eq("seismic").sum())
        n_total_radar = int(riggs_df["source"].eq("radar").sum())
        n_matched_seis = sum(1 for i in unique_stns
                             if riggs_df.iloc[i]["source"] == "seismic")
        n_matched_radar = n_riggs_stns - n_matched_seis
        print(f"    {len(riggs_df)} stations loaded "
              f"({n_total_seis} seismic, {n_total_radar} radar)")
        print(f"    Matches within {args.radius/1000:.0f} km: "
              f"{n_riggs} points \u2192 {n_riggs_stns} stations "
              f"({n_matched_seis} seismic, {n_matched_radar} radar)")
        riggs_stations = []
        for idx in sorted(unique_stns):
            stn = riggs_df.iloc[idx]
            pts_mask = r_idx == idx
            md = np.median(r_dist[pts_mask]) / 1000
            print(f"      {stn['Station']:6s}  {stn['h_ice']:.0f} m "
                  f"({stn['source']})  d\u0303={md:.1f} km")
            riggs_stations.append({
                "station": stn["Station"],
                "h_ice_m": round(float(stn["h_ice"]), 0),
                "source": stn["source"],
                "median_dist_km": round(md, 1),
                "n_matched_frames": int(pts_mask.sum()),
            })
        report["riggs"] = {
            "database": {
                "total": len(riggs_df),
                "seismic": n_total_seis,
                "radar": n_total_radar,
            },
            "matched": {
                "stations": n_riggs_stns,
                "seismic": n_matched_seis,
                "radar": n_matched_radar,
                "total_frame_matches": n_riggs,
            },
            "stations": riggs_stations,
        }
    elif riggs_df is None:
        print("    riggs_stations.csv not found")
        report["riggs"] = None
    else:
        print("    No coordinates available for RIGGS matching")
        report["riggs"] = None

    # -- BEDMAP1 SPRI (same-source, spatial context only) ------------------
    print("  Loading BEDMAP1 SPRI ...")
    spri_gdf_map = None
    if BEDMAP_SHP.exists() and has_coords.any():
        bedmap_gdf = load_bedmap()
        spri_gdf = bedmap_gdf[bedmap_gdf["MISSION_ID"].isin(SAME_SOURCE_MISSIONS)]
        if len(spri_gdf) > 0:
            lats = merged.loc[has_coords, "LAT"].values
            lons = merged.loc[has_coords, "LON"].values
            s_xy, s_thk = _extract_ref_arrays(spri_gdf)
            s_ice, s_dist, _ = match_reference(lats, lons, s_xy, s_thk,
                                               radius_m=args.radius)
            merged.loc[has_coords, "spri_ice"] = s_ice
            merged.loc[has_coords, "spri_dist"] = s_dist
            n_spri = int(np.isfinite(s_ice).sum())
            print(f"    BEDMAP1 SPRI matches within "
                  f"{args.radius/1000:.0f} km: {n_spri}")

            # Clip SPRI to region near flight for inset map
            flt_x, flt_y = _TRANSFORM.transform(lons, lats)
            margin = 150_000  # 150 km buffer
            spri_gdf_map = spri_gdf[
                (spri_gdf["PS_x"] >= flt_x.min() - margin)
                & (spri_gdf["PS_x"] <= flt_x.max() + margin)
                & (spri_gdf["PS_y"] >= flt_y.min() - margin)
                & (spri_gdf["PS_y"] <= flt_y.max() + margin)
            ]
            print(f"    {len(spri_gdf_map)} BEDMAP1 SPRI points in map region")
            report["bedmap1_spri"] = {
                "frame_matches": n_spri,
                "points_in_map_region": len(spri_gdf_map),
            }
        else:
            print("    No SPRI entries in BEDMAP1")
            report["bedmap1_spri"] = None
    else:
        print("    BEDMAP1 shapefile not found or no coordinates")
        report["bedmap1_spri"] = None

    # Clip RIGGS to map region
    riggs_df_map = None
    if riggs_df is not None and has_coords.any():
        lats = merged.loc[has_coords, "LAT"].values
        lons = merged.loc[has_coords, "LON"].values
        flt_x, flt_y = _TRANSFORM.transform(lons, lats)
        margin = 150_000
        riggs_df_map = riggs_df[
            (riggs_df["x_ps"] >= flt_x.min() - margin)
            & (riggs_df["x_ps"] <= flt_x.max() + margin)
            & (riggs_df["y_ps"] >= flt_y.min() - margin)
            & (riggs_df["y_ps"] <= flt_y.max() + margin)
        ]
        print(f"    {len(riggs_df_map)} RIGGS stations in map region")
        if report.get("riggs") is not None:
            report["riggs"]["stations_in_map_region"] = len(riggs_df_map)

    # -- RIGGS crossover (per-station nearest good echo) ------------------
    xover = riggs_crossover(merged, riggs_df, radius_m=args.radius)
    if xover is not None and len(xover) > 0:
        print(f"\n  RIGGS crossover: {len(xover)} stations matched")
        for _, row in xover.iterrows():
            d_km = row["dist_m"] / 1000
            diff = row["h_lyra"] - row["h_riggs"]
            print(f"    {row['station']:8s}  RIGGS {row['h_riggs']:.0f} m  "
                  f"LYRA {row['h_lyra']:.0f} m  "
                  f"diff {diff:+.0f} m  d={d_km:.1f} km  ({row['source']})")

        # Crossover stats for JSON report
        diff_x = xover["h_lyra"].values - xover["h_riggs"].values
        xover_stats = {
            "n_stations": len(xover),
            "bias_m": round(float(np.mean(diff_x)), 1),
            "rmse_m": round(float(np.sqrt(np.mean(diff_x ** 2))), 1),
            "median_abs_diff_m": round(float(np.median(np.abs(diff_x))), 1),
        }
        if len(xover) >= 3:
            xover_stats["r"] = round(
                float(np.corrcoef(xover["h_riggs"], xover["h_lyra"])[0, 1]), 3)
        seis_x = xover[xover["source"] == "seismic"]
        if len(seis_x) >= 2:
            sd = seis_x["h_lyra"].values - seis_x["h_riggs"].values
            xover_stats["seismic_only"] = {
                "n": len(seis_x),
                "bias_m": round(float(np.mean(sd)), 1),
                "rmse_m": round(float(np.sqrt(np.mean(sd ** 2))), 1),
            }
        xover_stats["stations"] = xover.to_dict(orient="records")
        if report.get("riggs") is None:
            report["riggs"] = {}
        report["riggs"]["crossover"] = xover_stats
    else:
        xover = None
        print("\n  No RIGGS crossover stations matched")

    # -- Generate figure ---------------------------------------------------
    out_path = OUTPUT_BASE / f"F{flt}" / "validation" / f"F{flt}_validation.png"
    print("  Generating validation figure ...")
    make_validation_figure(merged, flt, out_path,
                           nav=nav, riggs_df=riggs_df_map,
                           spri_gdf=spri_gdf_map,
                           riggs_xover=xover)

    # -- Comparison statistics ---------------------------------------------
    _rt_ok = (merged["reflector_type"].isin(["bed", None])
              | merged["reflector_type"].isna()) if "reflector_type" in merged.columns else True
    _n_uncertain_stats = int((~_rt_ok).sum()) if not isinstance(_rt_ok, bool) else 0
    good = merged[(merged["echo_status"] == "good") & _rt_ok]
    if _n_uncertain_stats > 0:
        print(f"\n  ({_n_uncertain_stats} uncertain-reflector frames excluded from stats)")

    # ASTRA comparison (primary validation)
    if "h_ice_astra" in merged.columns:
        both_astra = good[good["h_ice_astra"].notna() & good["h_ice_m"].notna()]
        if len(both_astra) > 0:
            diff = both_astra["h_ice_m"].values - both_astra["h_ice_astra"].values
            print(f"\n  LYRA vs ASTRA (n={len(both_astra)} good frames, d=0):")
            print(f"    Mean difference: {np.mean(diff):+.1f} m")
            print(f"    Std difference:  {np.std(diff):.1f} m")
            print(f"    RMSE:            {np.sqrt(np.mean(diff**2)):.1f} m")
            print(f"    Median abs diff: {np.median(np.abs(diff)):.1f} m")
            if len(both_astra) >= 3:
                r = np.corrcoef(both_astra["h_ice_astra"].values,
                                both_astra["h_ice_m"].values)[0, 1]
                print(f"    Correlation r:   {r:.3f}")
            report["astra"]["comparison"] = _comparison_stats(
                both_astra["h_ice_m"].values, both_astra["h_ice_astra"].values)

    # Spatial comparisons
    for ref_col, ref_name, report_key in [
        ("riggs_ice", "RIGGS (Bentley 1984)", "riggs"),
        ("spri_ice", "BEDMAP1 SPRI (same-source)", "bedmap1_spri"),
    ]:
        if ref_col in merged.columns:
            both = good[good[ref_col].notna() & good["h_ice_m"].notna()]
            if len(both) > 0:
                diff = both["h_ice_m"].values - both[ref_col].values
                print(f"\n  LYRA vs {ref_name} (n={len(both)} good frames):")
                print(f"    Mean difference: {np.mean(diff):+.0f} m")
                print(f"    Std difference:  {np.std(diff):.0f} m")
                print(f"    RMSE:            {np.sqrt(np.mean(diff**2)):.0f} m")
                print(f"    Median abs diff: {np.median(np.abs(diff)):.0f} m")
                if report.get(report_key) is not None:
                    report[report_key]["comparison"] = _comparison_stats(
                        both["h_ice_m"].values, both[ref_col].values)

    # -- Write JSON report -------------------------------------------------
    json_path = OUTPUT_BASE / f"F{flt}" / "validation" / f"F{flt}_validation.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  Report \u2192 {json_path}")

    print("Done.")


if __name__ == "__main__":
    main()
