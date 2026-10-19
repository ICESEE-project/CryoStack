"""
segment_ocr.py — 7-segment structural digit recognition for LYRA
=================================================================
Instead of pixel-level NCC, identifies which of the 7 segments are lit
by measuring ink density in spatial zones. Position-invariant by design.

Production API (imported by detect_frames.py):
    from segment_ocr import recognize_frame_structural, SEGMENT_THRESHOLD

Prototype mode (run standalone for training/evaluation):
    python codes/segment_ocr.py [--diag TIFF_ID FRAME_IDX]

Segment layout:
     -a-
    |   |
    f   b
    |   |
     -g-
    |   |
    e   c
    |   |
     -d-
"""

from pathlib import Path
import sys
import csv

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "codes"))
from lyra import detect_frames
from build_digit_templates import (
    get_binary_text, find_digit_col_ranges, adjust_blobs_to_7,
    TMPL_W, TMPL_H,
)

# -- Production threshold (trained on F125, universal for Tek 465 CRT) -----
SEGMENT_THRESHOLD = 0.26

# -- Prototype config (only used when run as __main__) ---------------------
FLT = 125
RAW_DIR = ROOT / f"tiff/{FLT}"
OUT_DIR = ROOT / f"output/F{FLT}/step0"
INDEX_CSV = ROOT / f"output/F{FLT}/phase1/F{FLT}_frame_index.csv"
TRAIN_TIFFS = ["7700", "7725", "8400", "8425"]
TEST_TIFFS = ["8300"]

# -- 7-segment truth table -------------------------------------------------
#                   a  b  c  d  e  f  g
SEGMENT_TABLE = {
    "0": np.array([1, 1, 1, 1, 1, 1, 0]),
    "1": np.array([0, 1, 1, 0, 0, 0, 0]),
    "2": np.array([1, 1, 0, 1, 1, 0, 1]),
    "3": np.array([1, 1, 1, 1, 0, 0, 1]),
    "4": np.array([0, 1, 1, 0, 0, 1, 1]),
    "5": np.array([1, 0, 1, 1, 0, 1, 1]),
    "6": np.array([1, 0, 1, 1, 1, 1, 1]),
    "7": np.array([1, 1, 1, 0, 0, 0, 0]),
    "8": np.array([1, 1, 1, 1, 1, 1, 1]),
    "9": np.array([1, 1, 1, 1, 0, 1, 1]),
}
SEG_NAMES = ["a", "b", "c", "d", "e", "f", "g"]

# -- Zone definitions (fractions of DIGIT bounding box, NOT full image) -----
# Each zone: (row_start_frac, row_end_frac, col_start_frac, col_end_frac)
# These are relative to the auto-detected ink bounding box within each blob.
ZONES = {
    "a": (0.00, 0.18, 0.15, 0.85),   # top horizontal bar
    "b": (0.10, 0.48, 0.60, 1.00),   # top-right vertical
    "c": (0.52, 0.90, 0.60, 1.00),   # bottom-right vertical
    "d": (0.82, 1.00, 0.15, 0.85),   # bottom horizontal bar
    "e": (0.52, 0.90, 0.00, 0.40),   # bottom-left vertical
    "f": (0.10, 0.48, 0.00, 0.40),   # top-left vertical
    "g": (0.42, 0.58, 0.15, 0.85),   # middle horizontal bar
}

# Ink detection threshold for bounding box
BBOX_INK_THRESH = 0.05


def find_digit_bbox(digit_img, orig_aspect=None):
    """
    Find the bounding box of the actual digit ink within the template image.
    Returns (top, bottom, left, right) in pixel coordinates.

    orig_aspect: original blob width / median blob width before resize.
        If < 0.5, this is a narrow digit (e.g. "1") and horizontal zones
        should use the full image width, not the ink bbox.
    """
    H, W = digit_img.shape
    row_proj = digit_img.mean(axis=1)
    col_proj = digit_img.mean(axis=0)

    ink_rows = np.where(row_proj > BBOX_INK_THRESH)[0]
    ink_cols = np.where(col_proj > BBOX_INK_THRESH)[0]

    if len(ink_rows) < 5 or len(ink_cols) < 3:
        return 0, H, 0, W

    top = int(ink_rows[0])
    bottom = int(ink_rows[-1])

    # For narrow digits: the blob crop was narrow, then stretched to TMPL_W.
    # Use full image width so horizontal zones don't all overlap the stroke.
    if orig_aspect is not None and orig_aspect < 0.55:
        left, right = 0, W
    else:
        left = int(ink_cols[0])
        right = int(ink_cols[-1])
        # Still enforce a minimum so moderate-width digits don't collapse
        ink_w = right - left
        min_w = int(0.60 * W)
        if ink_w < min_w:
            center = (left + right) // 2
            left = max(0, center - min_w // 2)
            right = min(W, left + min_w)

    return top, bottom, left, right


def get_zone_rects(digit_img, orig_aspect=None):
    """
    Compute zone pixel rectangles relative to the actual digit bounding box.
    Returns dict {seg_name: (r0, r1, c0, c1)} and the bbox tuple.
    """
    top, bottom, left, right = find_digit_bbox(digit_img, orig_aspect)
    h = max(bottom - top, 1)
    w = max(right - left, 1)

    rects = {}
    for seg, (r0f, r1f, c0f, c1f) in ZONES.items():
        r0 = int(top + r0f * h)
        r1 = int(top + r1f * h)
        c0 = int(left + c0f * w)
        c1 = int(left + c1f * w)
        rects[seg] = (r0, r1, c0, c1)
    return rects, (top, bottom, left, right)


def measure_segment_densities(digit_img, orig_aspect=None):
    """
    Measure ink density in each of the 7 zones.
    Zones are placed relative to the auto-detected digit bounding box,
    so they adapt to where the actual content sits in the image.
    digit_img: (TMPL_H, TMPL_W) float32 binary image (1=ink, 0=bg).
    orig_aspect: blob_width / median_blob_width (< 0.55 -> narrow digit).
    Returns (densities_dict, zone_rects, bbox).
    """
    rects, bbox = get_zone_rects(digit_img, orig_aspect)
    densities = {}
    for seg in SEG_NAMES:
        r0, r1, c0, c1 = rects[seg]
        zone = digit_img[r0:r1, c0:c1]
        densities[seg] = float(zone.mean()) if zone.size > 0 else 0.0
    return densities, rects, bbox


def classify_digit(densities, threshold):
    """
    Classify a digit from its segment densities.

    threshold: float (global) or dict {seg_name: float} (per-segment).

    Approach:
    1. Threshold densities -> binary segment vector
    2. Compute Hamming distance to each digit's truth pattern
    3. Among candidates with minimum Hamming distance, use MSE as tiebreaker

    Returns (best_digit, segment_vector, min_hamming).
    """
    dens_vec = np.array([densities[s] for s in SEG_NAMES])
    if isinstance(threshold, dict):
        th_vec = np.array([threshold[s] for s in SEG_NAMES])
    else:
        th_vec = np.full(7, threshold)
    seg_vec = (dens_vec >= th_vec).astype(int)

    # Score each candidate: (hamming, mse) — sort by hamming first, mse second
    candidates = []
    for d, truth in SEGMENT_TABLE.items():
        hamming = int(np.sum(seg_vec != truth))
        mse = float(np.mean((dens_vec - truth.astype(float)) ** 2))
        candidates.append((hamming, mse, d))

    candidates.sort(key=lambda x: (x[0], x[1]))
    best_hamming, best_mse, best_digit = candidates[0]

    return best_digit, seg_vec, best_hamming


def crop_and_resize_digit(binary, s, e, med_blob_w, pad=4):
    """
    Crop a digit blob from the binary image and resize to TMPL_W x TMPL_H.
    Narrow blobs (like "1") are zero-padded to the median width BEFORE
    resizing, so the original aspect ratio is preserved and the digit
    doesn't get stretched across the full template width.

    Returns (query_img, orig_aspect) or (None, aspect) if too narrow.
    """
    crop_d = binary[:, max(0, s - pad): e + pad + 1]
    if crop_d.shape[1] < 3:
        return None, 0.0

    blob_w = e - s
    orig_aspect = blob_w / med_blob_w if med_blob_w > 0 else 1.0

    # If narrow: pad to median width so resize preserves aspect ratio
    target_w = int(med_blob_w + 2 * pad)
    actual_w = crop_d.shape[1]
    if actual_w < 0.7 * target_w:
        deficit = target_w - actual_w
        pad_left = deficit // 2
        pad_right = deficit - pad_left
        crop_d = np.pad(crop_d, ((0, 0), (pad_left, pad_right)),
                        mode="constant", constant_values=0)

    query = np.array(Image.fromarray(
        (crop_d * 255).astype(np.uint8)).resize(
        (TMPL_W, TMPL_H), Image.LANCZOS),
        dtype=np.float32) / 255.0
    return query, orig_aspect


# ===========================================================================
# Production API — imported by detect_frames.py
# ===========================================================================

def recognize_frame_structural(frame_crop, H, fw,
                               threshold=SEGMENT_THRESHOLD):
    """
    Recognize the 7-digit CBD number from a single frame using structural
    7-segment matching.

    Same interface as recognize_frame() in build_digit_templates.py, so
    step1 can swap between NCC and structural with minimal code change.

    Parameters
    ----------
    frame_crop : np.ndarray, uint8
        Cropped frame image (full height, frame width).
    H : int
        Full TIFF image height (needed by get_binary_text).
    fw : int
        Frame width in pixels.
    threshold : float
        Segment density threshold for ON/OFF classification.

    Returns
    -------
    recognized : str or None
        7-character string (e.g. "1250465") or None if blob detection fails.
    blobs : list of (int, int)
        Column ranges of detected digit blobs.
    confidences : list of int
        Per-digit Hamming distance (0 = perfect segment match, lower = better).
    """
    binary = get_binary_text(frame_crop, H, fw)
    blobs = find_digit_col_ranges(binary)

    if len(blobs) < 5:
        return None, blobs, []

    blobs = adjust_blobs_to_7(blobs)

    if len(blobs) != 7:
        return None, blobs, []

    blob_widths = [e - s for s, e in blobs]
    med_blob_w = float(np.median(blob_widths))

    recognized = ""
    confidences = []
    for s, e in blobs:
        query, orig_aspect = crop_and_resize_digit(binary, s, e, med_blob_w)
        if query is None:
            recognized += "?"
            confidences.append(7)  # worst possible
            continue
        densities, _, _ = measure_segment_densities(query, orig_aspect)
        pred, _, hamming = classify_digit(densities, threshold)
        recognized += pred
        confidences.append(hamming)

    return recognized, blobs, confidences


# ===========================================================================
# Prototype / training functions (used when run as __main__)
# ===========================================================================

def extract_digit_blobs(tiff_path, tiff_id, gt_cbds):
    """
    Extract all digit blobs from a TIFF with ground truth.
    Returns list of dicts with keys:
        tiff_id, frame_idx, pos, true_digit, digit_img, blob_coords
    """
    Image.MAX_IMAGE_PIXELS = None
    img = np.array(Image.open(tiff_path), dtype=np.float32)
    img_norm = (img - img.min()) / (img.max() - img.min() + 1e-9)
    H, W = img_norm.shape

    frames = detect_frames(img_norm)
    widths = [r - l for l, r in frames]
    med_w = float(np.median(widths))

    results = []
    for fidx, (l, r) in enumerate(frames):
        if (r - l) < 0.75 * med_w:
            continue
        true_cbd = gt_cbds.get(fidx)
        if not true_cbd:
            continue
        true_str = f"{FLT:03d}{true_cbd}"

        crop_u8 = (img_norm[:, l:r+1] * 255).clip(0, 255).astype(np.uint8)
        fw = crop_u8.shape[1]
        binary = get_binary_text(crop_u8, H, fw)
        blobs = adjust_blobs_to_7(find_digit_col_ranges(binary))

        if len(blobs) != 7:
            continue

        # Compute median blob width for aspect ratio
        blob_widths = [e - s for s, e in blobs]
        med_blob_w = float(np.median(blob_widths))

        for pos, (s, e) in enumerate(blobs):
            query, orig_aspect = crop_and_resize_digit(
                binary, s, e, med_blob_w)
            if query is None:
                continue

            true_d = true_str[pos] if pos < len(true_str) else "?"
            results.append({
                "tiff_id": tiff_id,
                "frame_idx": fidx,
                "pos": pos,
                "true_digit": true_d,
                "digit_img": query,
                "orig_aspect": orig_aspect,
                "blob_coords": (s, e),
            })

    return results


def load_ground_truth():
    gt = {}
    with open(INDEX_CSV) as f:
        for row in csv.DictReader(f):
            tid = row["tiff_id"]
            fidx = int(row["frame_idx"])
            cbd = row.get("cbd", "")
            if tid not in gt:
                gt[tid] = {}
            if cbd:
                gt[tid][fidx] = cbd
    return gt


def find_tiff(tiff_id):
    matches = list(RAW_DIR.glob(f"*_{tiff_id:>07s}_*-reel_begin_end.tiff"))
    if not matches:
        matches = list(RAW_DIR.glob(f"*_{tiff_id}_*"))
    return matches[0] if matches else None


# -- Diagnostic figure for one frame ---------------------------------------
def make_frame_diagnostic(tiff_path, tiff_id, frame_idx, gt_cbds, threshold):
    """
    Detailed diagnostic for one frame showing the structural matching
    pipeline for every digit.
    """
    Image.MAX_IMAGE_PIXELS = None
    img = np.array(Image.open(tiff_path), dtype=np.float32)
    img_norm = (img - img.min()) / (img.max() - img.min() + 1e-9)
    H, W = img_norm.shape

    frames = detect_frames(img_norm)
    l, r = frames[frame_idx]
    crop_u8 = (img_norm[:, l:r+1] * 255).clip(0, 255).astype(np.uint8)
    fw = crop_u8.shape[1]

    true_cbd = gt_cbds.get(frame_idx, "????")
    true_str = f"{FLT:03d}{true_cbd}"

    binary = get_binary_text(crop_u8, H, fw)
    blobs = adjust_blobs_to_7(find_digit_col_ranges(binary))

    n_digits = len(blobs)
    blob_widths = [e - s for s, e in blobs]
    med_blob_w = float(np.median(blob_widths)) if blob_widths else 1.0

    # -- Figure: 4 rows × n_digits columns ---------------------------------
    # Row 1: digit image with zone rectangles overlaid
    # Row 2: density bar chart per segment
    # Row 3: segment vector (lit/unlit) vs truth
    # Row 4: classification result
    fig, axes = plt.subplots(4, n_digits, figsize=(3.2 * n_digits, 14))
    if n_digits == 1:
        axes = axes[:, np.newaxis]
    fig.patch.set_facecolor("white")

    # Zone colors
    seg_colors = {
        "a": "#e41a1c", "b": "#377eb8", "c": "#4daf4a",
        "d": "#ff7f00", "e": "#984ea3", "f": "#a65628", "g": "#f781bf",
    }

    ocr_str = ""
    for col, (s, e) in enumerate(blobs):
        query, orig_aspect = crop_and_resize_digit(
            binary, s, e, med_blob_w)
        if query is None:
            ocr_str += "?"
            for row in range(4):
                axes[row, col].axis("off")
            continue

        true_d = true_str[col] if col < len(true_str) else "?"
        densities, rects_d, bbox = measure_segment_densities(
            query, orig_aspect)
        pred, seg_vec, hamming = classify_digit(densities, threshold)
        ocr_str += pred
        ok = pred == true_d

        # -- Row 1: digit image + zone overlays ----------------------------
        ax = axes[0, col]
        ax.imshow(query, cmap="gray", vmin=0, vmax=1, aspect="auto")
        # Show bounding box
        bt, bb, bl, br = bbox
        bbox_rect = patches.Rectangle(
            (bl, bt), br - bl, bb - bt,
            linewidth=1.5, edgecolor="white", facecolor="none",
            linestyle="--")
        ax.add_patch(bbox_rect)
        for seg_name in SEG_NAMES:
            r0, r1, c0, c1 = rects_d[seg_name]
            color = seg_colors[seg_name]
            rect = patches.Rectangle(
                (c0, r0), c1 - c0, r1 - r0,
                linewidth=1.5, edgecolor=color, facecolor=color,
                alpha=0.25)
            ax.add_patch(rect)
            # Label
            cx, cy = (c0 + c1) / 2, (r0 + r1) / 2
            ax.text(cx, cy, seg_name, ha="center", va="center",
                    fontsize=8, fontweight="bold", color=color)
        ax.set_title(f"Pos {col}, true='{true_d}'", fontsize=9)
        ax.axis("off")

        # -- Row 2: density bar chart --------------------------------------
        ax = axes[1, col]
        bars = [densities[s] for s in SEG_NAMES]
        bar_colors = [seg_colors[s] for s in SEG_NAMES]
        ax.bar(SEG_NAMES, bars, color=bar_colors, alpha=0.7, edgecolor="k",
               linewidth=0.5)
        ax.axhline(threshold, color="red", linewidth=1.5, linestyle="--",
                   label=f"theta={threshold:.2f}")
        ax.set_ylim(0, 1)
        ax.set_ylabel("density", fontsize=7)
        ax.tick_params(labelsize=7)
        ax.legend(fontsize=6, loc="upper right")
        ax.set_title("Segment densities", fontsize=8)

        # -- Row 3: segment vector vs truth --------------------------------
        ax = axes[2, col]
        truth_vec = SEGMENT_TABLE.get(true_d, np.zeros(7))
        x = np.arange(7)
        width = 0.35
        ax.bar(x - width/2, seg_vec, width, color="steelblue",
               label="detected", alpha=0.8)
        ax.bar(x + width/2, truth_vec, width, color="orange",
               label="truth", alpha=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(SEG_NAMES, fontsize=7)
        ax.set_ylim(-0.1, 1.5)
        ax.set_yticks([0, 1])
        ax.legend(fontsize=6, loc="upper right")
        # Mark mismatches
        for i in range(7):
            if seg_vec[i] != truth_vec[i]:
                ax.text(i, 1.2, "X", ha="center", fontsize=10,
                        color="red", fontweight="bold")
        ax.set_title("Segments: detected vs truth", fontsize=8)

        # -- Row 4: classification result ----------------------------------
        ax = axes[3, col]
        ax.axis("off")
        result_text = (
            f"Predicted: '{pred}'\n"
            f"True:      '{true_d}'\n"
            f"Hamming:   {hamming}\n"
            f"{'CORRECT' if ok else 'WRONG'}"
        )
        color = "green" if ok else "red"
        ax.text(0.5, 0.5, result_text, transform=ax.transAxes,
                fontsize=11, fontfamily="monospace",
                ha="center", va="center", color=color,
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3",
                          facecolor="lightyellow" if ok else "mistyrose",
                          edgecolor=color))

    fig.suptitle(
        f"TIFF {tiff_id}, Frame {frame_idx} — "
        f"7-segment structural matching\n"
        f"True: {true_str} | OCR: {ocr_str} | "
        f"threshold={threshold:.2f}",
        fontsize=13, fontweight="bold", y=1.01)
    fig.tight_layout()

    out_path = OUT_DIR / f"diag_segment_{tiff_id}_fr{frame_idx}.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Diagnostic saved -> {out_path.relative_to(ROOT)}")
    return ocr_str


# -- Per-segment threshold learning ----------------------------------------
def learn_per_segment_thresholds(all_digits):
    """
    Learn optimal threshold for each segment independently.
    For each segment, collect all (density, should_be_lit) pairs from
    training data, then sweep to find the threshold that minimizes errors.

    Returns dict {seg_name: optimal_threshold}.
    """
    # Collect densities grouped by segment and ON/OFF status
    seg_data = {s: {"on": [], "off": []} for s in SEG_NAMES}

    for d in all_digits:
        true_d = d["true_digit"]
        if true_d not in SEGMENT_TABLE:
            continue
        truth = SEGMENT_TABLE[true_d]
        densities, _, _ = measure_segment_densities(
            d["digit_img"], d.get("orig_aspect"))
        for i, seg in enumerate(SEG_NAMES):
            if truth[i] == 1:
                seg_data[seg]["on"].append(densities[seg])
            else:
                seg_data[seg]["off"].append(densities[seg])

    print("\n  Per-segment density statistics:")
    print(f"  {'seg':>3}  {'ON mean':>8}  {'ON std':>7}  "
          f"{'OFF mean':>9}  {'OFF std':>8}  {'best_th':>8}  {'sep':>5}")
    print("  " + "-" * 60)

    per_seg_th = {}
    for seg in SEG_NAMES:
        on_vals = np.array(seg_data[seg]["on"])
        off_vals = np.array(seg_data[seg]["off"])

        on_mean = on_vals.mean() if len(on_vals) else 0.5
        on_std = on_vals.std() if len(on_vals) else 0.1
        off_mean = off_vals.mean() if len(off_vals) else 0.1
        off_std = off_vals.std() if len(off_vals) else 0.1

        # Sweep threshold for this segment
        best_th_s = 0.20
        best_err = len(on_vals) + len(off_vals)
        for th in np.arange(0.05, 0.80, 0.01):
            err = (np.sum(on_vals < th) +     # false negatives
                   np.sum(off_vals >= th))     # false positives
            if err < best_err:
                best_err = err
                best_th_s = th

        # Separation: gap between on/off means in units of pooled std
        pooled_std = max(0.01, np.sqrt((on_std**2 + off_std**2) / 2))
        sep = (on_mean - off_mean) / pooled_std

        per_seg_th[seg] = best_th_s
        print(f"  {seg:>3}  {on_mean:>8.3f}  {on_std:>7.3f}  "
              f"{off_mean:>9.3f}  {off_std:>8.3f}  {best_th_s:>8.2f}  "
              f"{sep:>5.1f}")

    return per_seg_th


def sweep_threshold(all_digits):
    """
    Find optimal global threshold AND per-segment thresholds.
    Returns (best_global_threshold, per_seg_thresholds, accuracy_at_best).
    """
    # First: learn per-segment thresholds
    per_seg_th = learn_per_segment_thresholds(all_digits)

    # Evaluate per-segment approach
    correct_perseg = 0
    total = len(all_digits)
    for d in all_digits:
        densities, _, _ = measure_segment_densities(
            d["digit_img"], d.get("orig_aspect"))
        pred, _, _ = classify_digit(densities, per_seg_th)
        if pred == d["true_digit"]:
            correct_perseg += 1
    acc_perseg = correct_perseg / total if total > 0 else 0

    # Also sweep global for comparison
    thresholds = np.arange(0.05, 0.60, 0.01)
    best_acc_global = 0
    best_th_global = 0.20
    for th in thresholds:
        correct = 0
        for d in all_digits:
            densities, _, _ = measure_segment_densities(
                d["digit_img"], d.get("orig_aspect"))
            pred, _, _ = classify_digit(densities, th)
            if pred == d["true_digit"]:
                correct += 1
        acc = correct / total if total > 0 else 0
        if acc > best_acc_global:
            best_acc_global = acc
            best_th_global = th

    print(f"\n  Global best: theta={best_th_global:.2f} -> {best_acc_global:.1%}")
    print(f"  Per-segment:  -> {acc_perseg:.1%}")

    if acc_perseg >= best_acc_global:
        print("  Using per-segment thresholds")
        return best_th_global, per_seg_th, acc_perseg
    else:
        print("  Using global threshold")
        return best_th_global, best_th_global, best_acc_global


# -- Confusion analysis ----------------------------------------------------
def confusion_analysis(all_digits, threshold):
    """Print per-digit accuracy and common confusions."""
    from collections import Counter

    digit_counts = Counter()
    digit_correct = Counter()
    confusions = []

    for d in all_digits:
        densities, _, _ = measure_segment_densities(
            d["digit_img"], d.get("orig_aspect"))
        pred, seg_vec, hamming = classify_digit(densities, threshold)
        true_d = d["true_digit"]
        digit_counts[true_d] += 1
        if pred == true_d:
            digit_correct[true_d] += 1
        else:
            confusions.append({
                "true": true_d, "pred": pred,
                "hamming": hamming,
                "tiff": d["tiff_id"], "frame": d["frame_idx"],
                "pos": d["pos"],
                "densities": densities,
                "seg_vec": seg_vec,
            })

    th_label = (f"{threshold:.2f}" if isinstance(threshold, float)
                else "per-segment")
    print(f"\n  Per-digit accuracy (threshold={th_label}):")
    print(f"  {'digit':>5}  {'correct':>7}  {'total':>5}  {'acc':>6}")
    print("  " + "-" * 30)
    for digit in sorted(digit_counts.keys()):
        c = digit_correct[digit]
        t = digit_counts[digit]
        acc = c / t if t > 0 else 0
        marker = "" if acc == 1.0 else " <- ERRORS"
        print(f"  {digit:>5}  {c:>7}  {t:>5}  {acc:>6.1%}{marker}")

    total_correct = sum(digit_correct.values())
    total = sum(digit_counts.values())
    print(f"  {'ALL':>5}  {total_correct:>7}  {total:>5}  "
          f"{total_correct/total:.1%}")

    if confusions:
        print(f"\n  Confusions ({len(confusions)} errors):")
        for c in confusions:
            dens_str = " ".join(
                f"{s}={c['densities'][s]:.2f}" for s in SEG_NAMES)
            print(f"    TIFF {c['tiff']} fr{c['frame']} pos{c['pos']}: "
                  f"true='{c['true']}' pred='{c['pred']}' "
                  f"hamming={c['hamming']}")
            print(f"      densities: {dens_str}")
            print(f"      seg_vec:   {c['seg_vec'].tolist()}")

    return confusions


# -- Test evaluation with sequential constraint --------------------------
def recognize_tiff_structural(tiff_path, tiff_id, gt_cbds, threshold):
    """
    Run structural matching on all complete frames of a TIFF.
    Returns per-frame results for sequential constraint evaluation.
    """
    Image.MAX_IMAGE_PIXELS = None
    img = np.array(Image.open(tiff_path), dtype=np.float32)
    img_norm = (img - img.min()) / (img.max() - img.min() + 1e-9)
    H, W = img_norm.shape

    frames = detect_frames(img_norm)
    widths = [r - l for l, r in frames]
    med_w = float(np.median(widths))

    frame_results = []
    for fidx, (l, r) in enumerate(frames):
        if (r - l) < 0.75 * med_w:
            continue  # partial frame
        true_cbd = gt_cbds.get(fidx)
        true_str = f"{FLT:03d}{true_cbd}" if true_cbd else None

        crop_u8 = (img_norm[:, l:r+1] * 255).clip(0, 255).astype(np.uint8)
        fw = crop_u8.shape[1]
        binary = get_binary_text(crop_u8, H, fw)
        blobs = adjust_blobs_to_7(find_digit_col_ranges(binary))

        if len(blobs) != 7:
            frame_results.append({
                "frame_idx": fidx, "true_str": true_str,
                "raw_ocr": None, "n_blobs": len(blobs),
            })
            continue

        blob_widths = [e - s for s, e in blobs]
        med_blob_w = float(np.median(blob_widths))

        ocr_str = ""
        for pos, (s, e) in enumerate(blobs):
            query, orig_aspect = crop_and_resize_digit(
                binary, s, e, med_blob_w)
            if query is None:
                ocr_str += "?"
                continue
            densities, _, _ = measure_segment_densities(query, orig_aspect)
            pred, _, _ = classify_digit(densities, threshold)
            ocr_str += pred

        frame_results.append({
            "frame_idx": fidx, "true_str": true_str,
            "raw_ocr": ocr_str, "n_blobs": len(blobs),
        })

    return frame_results


def evaluate_test_tiff(tiff_id, threshold):
    """
    Full evaluation on a test TIFF: raw accuracy + sequential constraint.
    Returns summary dict.
    """
    from build_digit_templates import apply_sequential_constraint

    gt = load_ground_truth()
    tiff_path = find_tiff(tiff_id)
    if not tiff_path:
        print(f"  ERROR: TIFF {tiff_id} not found")
        return None
    gt_cbds = gt.get(tiff_id, {})
    if not gt_cbds:
        print(f"  ERROR: no ground truth for TIFF {tiff_id}")
        return None

    print(f"\n{'='*70}")
    print(f"  TEST EVALUATION: TIFF {tiff_id}")
    print(f"{'='*70}")

    frame_results = recognize_tiff_structural(
        tiff_path, tiff_id, gt_cbds, threshold)

    # -- Raw accuracy -----------------------------------------------------
    print(f"\n  Raw structural matching results:")
    print(f"  {'Fr':>3}  {'Raw OCR':>10}  {'True':>10}  {'Match':>6}")
    print("  " + "-" * 40)

    total_digits = 0
    correct_digits = 0
    total_frames = 0
    correct_frames = 0

    frame_indices = []
    raw_reads = []

    for fr in frame_results:
        fidx = fr["frame_idx"]
        raw = fr["raw_ocr"]
        true_s = fr["true_str"]

        if raw is None:
            print(f"  {fidx:>3}  {'(no blobs)':>10}  {true_s or '?':>10}  {'—':>6}")
            continue

        frame_indices.append(fidx)
        raw_reads.append(raw)

        if true_s:
            total_frames += 1
            frame_ok = (raw == true_s)
            if frame_ok:
                correct_frames += 1
            for i, (r, t) in enumerate(zip(raw, true_s)):
                total_digits += 1
                if r == t:
                    correct_digits += 1
            marker = "OK" if frame_ok else "MISS"
        else:
            marker = "no GT"

        print(f"  {fidx:>3}  {raw:>10}  {true_s or '?':>10}  {marker:>6}")

    raw_digit_acc = correct_digits / total_digits if total_digits > 0 else 0
    raw_frame_acc = correct_frames / total_frames if total_frames > 0 else 0

    print(f"\n  Raw digit accuracy:  {correct_digits}/{total_digits} "
          f"= {raw_digit_acc:.1%}")
    print(f"  Raw frame accuracy:  {correct_frames}/{total_frames} "
          f"= {raw_frame_acc:.1%}")

    # -- Sequential constraint --------------------------------------------
    print(f"\n  Applying sequential constraint (flight={FLT}) ...")
    corrected, n_anchors = apply_sequential_constraint(
        frame_indices, raw_reads, flight=FLT)

    print(f"  Anchor agreement: {n_anchors}/{len(frame_indices)} "
          f"raw reads match best-fit sequence")

    print(f"\n  {'Fr':>3}  {'Raw':>10}  {'Corrected':>10}  {'True':>10}  "
          f"{'Status':>8}")
    print("  " + "-" * 55)

    corrected_digits = 0
    corrected_frames = 0
    total_digits_corr = 0
    total_frames_corr = 0

    for i, (fidx, raw, corr) in enumerate(
            zip(frame_indices, raw_reads, corrected)):
        # Find ground truth for this frame
        true_s = None
        for fr in frame_results:
            if fr["frame_idx"] == fidx:
                true_s = fr["true_str"]
                break

        if true_s:
            total_frames_corr += 1
            frame_ok = (corr == true_s)
            if frame_ok:
                corrected_frames += 1
            for j, (c, t) in enumerate(zip(corr, true_s)):
                total_digits_corr += 1
                if c == t:
                    corrected_digits += 1

            raw_ok = (raw == true_s)
            if frame_ok and not raw_ok:
                status = "FIXED"
            elif frame_ok:
                status = "OK"
            elif raw_ok and not frame_ok:
                status = "BROKEN"
            else:
                status = "STILL BAD"
        else:
            status = "no GT"

        print(f"  {fidx:>3}  {raw:>10}  {corr:>10}  {true_s or '?':>10}  "
              f"{status:>8}")

    corr_digit_acc = (corrected_digits / total_digits_corr
                      if total_digits_corr > 0 else 0)
    corr_frame_acc = (corrected_frames / total_frames_corr
                      if total_frames_corr > 0 else 0)

    print(f"\n  After sequential constraint:")
    print(f"    Digit accuracy:  {corrected_digits}/{total_digits_corr} "
          f"= {corr_digit_acc:.1%}")
    print(f"    Frame accuracy:  {corrected_frames}/{total_frames_corr} "
          f"= {corr_frame_acc:.1%}")

    # -- Summary ----------------------------------------------------------
    print(f"\n  SUMMARY for TIFF {tiff_id}:")
    print(f"    Raw:       {raw_digit_acc:.1%} digit, "
          f"{raw_frame_acc:.1%} frame")
    print(f"    Corrected: {corr_digit_acc:.1%} digit, "
          f"{corr_frame_acc:.1%} frame")
    improvement = corr_digit_acc - raw_digit_acc
    if improvement > 0:
        print(f"    Sequential constraint improved digit accuracy by "
              f"+{improvement:.1%}")
    elif improvement < 0:
        print(f"    WARNING: Sequential constraint DECREASED digit accuracy "
              f"by {improvement:.1%}")
    else:
        print(f"    Sequential constraint had no effect on digit accuracy")

    return {
        "tiff_id": tiff_id,
        "raw_digit_acc": raw_digit_acc,
        "raw_frame_acc": raw_frame_acc,
        "corr_digit_acc": corr_digit_acc,
        "corr_frame_acc": corr_frame_acc,
        "n_anchors": n_anchors,
        "n_frames": total_frames,
    }


# -- Main -------------------------------------------------------------------
if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gt = load_ground_truth()

    # Parse optional diagnostic target
    diag_tiff = "8400"
    diag_frame = 7
    if "--diag" in sys.argv:
        idx = sys.argv.index("--diag")
        if idx + 2 < len(sys.argv):
            diag_tiff = sys.argv[idx + 1]
            diag_frame = int(sys.argv[idx + 2])

    # -- Step 1: extract all digit blobs from training TIFFs ---------------
    print("Extracting digit blobs from training TIFFs ...")
    all_digits = []
    for tid in TRAIN_TIFFS:
        tiff_path = find_tiff(tid)
        if not tiff_path:
            print(f"  WARNING: TIFF {tid} not found — skipping")
            continue
        gt_cbds = gt.get(tid, {})
        if not gt_cbds:
            print(f"  WARNING: no ground truth for TIFF {tid} — skipping")
            continue
        print(f"  TIFF {tid}: ", end="", flush=True)
        digits = extract_digit_blobs(tiff_path, tid, gt_cbds)
        all_digits.extend(digits)
        print(f"{len(digits)} digit blobs extracted")

    print(f"\n  Total training digits: {len(all_digits)}")

    # -- Step 2: learn thresholds --------------------------------------------
    best_th_global, best_th, best_acc = sweep_threshold(all_digits)

    # -- Step 3: confusion analysis at best threshold ----------------------
    confusions = confusion_analysis(all_digits, best_th)

    # -- Step 4: diagnostic figure for one frame ---------------------------
    print(f"\nGenerating diagnostic for TIFF {diag_tiff} frame {diag_frame}...")
    tiff_path = find_tiff(diag_tiff)
    gt_cbds = gt.get(diag_tiff, {})
    ocr = make_frame_diagnostic(
        tiff_path, diag_tiff, diag_frame, gt_cbds, best_th)

    print(f"\nTraining accuracy: {best_acc:.1%}")

    # -- Step 5: TEST on held-out TIFF(s) ---------------------------------
    print(f"\n{'#'*70}")
    print(f"  TESTING ON HELD-OUT TIFF(s): {TEST_TIFFS}")
    print(f"{'#'*70}")

    test_results = []
    for tid in TEST_TIFFS:
        result = evaluate_test_tiff(tid, best_th)
        if result:
            test_results.append(result)

    # -- Final comparison -------------------------------------------------
    if test_results:
        print(f"\n{'='*70}")
        print(f"  FINAL RESULTS")
        print(f"{'='*70}")
        print(f"  Training (TIFFs {', '.join(TRAIN_TIFFS)}):")
        print(f"    Raw digit accuracy: {best_acc:.1%}")
        print(f"\n  Test (TIFFs {', '.join(TEST_TIFFS)}):")
        for r in test_results:
            print(f"    TIFF {r['tiff_id']}: raw={r['raw_digit_acc']:.1%} -> "
                  f"corrected={r['corr_digit_acc']:.1%} "
                  f"(frame: {r['raw_frame_acc']:.1%} -> "
                  f"{r['corr_frame_acc']:.1%})")
            print(f"      Anchors: {r['n_anchors']}/{r['n_frames']}")

    print("\nDone.")
