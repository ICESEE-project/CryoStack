"""
build_digit_templates.py — LYRA digit template builder
=======================================================
Uses user-provided ground-truth CBD numbers to extract per-digit pixel
templates from the 7-segment display font printed on the film, then saves
them for use by the NCC-based digit recognizer on all future TIFFs.

Ground truth source: user-confirmed for 40_0008400_0008424-reel_begin_end.tiff
  Flight 125, frames 1–12, CBDs 0458–0469 (sequential, all 10 digits covered)

Recognition strategy (two-stage):
  Stage 1 — NCC matching: match each digit blob to the nearest template
  Stage 2 — Sequential constraint: |CBD[n+1] - CBD[n]| = 1 always; use
             majority-vote anchor to correct any wrong NCC reads

Outputs
-------
  codes/digit_templates.npy   — dict {digit_char: (H, W) float32 array}
  output/F125/templates_validation.png  — contact sheet showing
      each saved template and recognition result on all frames

Run from repo root:
    python codes/build_digit_templates.py
"""

from pathlib import Path
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

ROOT    = Path(__file__).resolve().parents[1]
TIFF    = ROOT / "tiff/125/40_0008400_0008424-reel_begin_end.tiff"
OUT_DIR = ROOT / "output/F125"
TMPL    = ROOT / "codes/digit_templates.npy"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "codes"))
from lyra import detect_frames, _connected_components_1d, _gauss_smooth

# -- Ground truth from user --------------------------------------------------
FLIGHT = 125
KNOWN_CBDS = {
    1: 458,  2: 459,  3: 460,  4: 461,  5: 462,  6: 463,
    7: 464,  8: 465,  9: 466, 10: 467, 11: 468, 12: 469,
}

# -- Constants for text region -----------------------------------------------
TEXT_Y0_FRAC = 0.803    # top of CBD text row (fraction of frame height)
TEXT_Y1_FRAC = 0.865    # bottom of CBD text row
TEXT_X0_FRAC = 0.25     # left crop (fraction of frame width)
TEXT_X1_FRAC = 0.75     # right crop
SCALE_X      = 5        # upscale factor horizontal
SCALE_Y      = 10       # upscale factor vertical (makes thin text taller)
THRESH_FRAC  = 0.55     # binarization threshold (fraction of intensity range)
TMPL_W       = 80       # standard template width (px)
TMPL_H       = 160      # standard template height (px)
MIN_BLOB_COL = 15       # min column width to count as a digit blob

# Spatial filter: real digit blobs are confined to 28–72% of the upscaled
# binary band width. Noise blobs from film damage land at ~8% or ~88% —
# filtering these out before blob counting removes the root cause of failures.
DIGIT_X_MIN_FRAC = 0.25
DIGIT_X_MAX_FRAC = 0.78


def get_binary_text(frame_crop, H, fw):
    """Return upscaled binary image of the CBD text region."""
    y0 = int(H * TEXT_Y0_FRAC)
    y1 = int(H * TEXT_Y1_FRAC)
    x0 = int(fw * TEXT_X0_FRAC)
    x1 = int(fw * TEXT_X1_FRAC)
    band  = frame_crop[y0:y1, x0:x1]
    big   = np.array(Image.fromarray(band).resize(
        (band.shape[1] * SCALE_X, band.shape[0] * SCALE_Y), Image.LANCZOS))
    lo, hi = int(big.min()), int(big.max())
    thresh = lo + (hi - lo) * THRESH_FRAC
    return (big < thresh).astype(np.float32)


def find_digit_col_ranges(binary):
    """
    Find x-ranges of individual digit blobs via column projection.
    Returns list of (x_start, x_end) sorted left-to-right.

    Spatial filter: only blobs whose centre falls in [DIGIT_X_MIN_FRAC,
    DIGIT_X_MAX_FRAC] of the band width are kept. This eliminates noise marks
    at the film edges that have no CBD content.

    Narrow-blob merge: digits like "4" have a thin horizontal bar that causes
    the column projection to dip mid-digit, splitting it into two narrow blobs.
    Adjacent blobs that are each <100 px wide and together <250 px are merged.
    """
    bw       = binary.shape[1]
    x_min    = DIGIT_X_MIN_FRAC * bw
    x_max    = DIGIT_X_MAX_FRAC * bw

    col_proj  = binary.sum(axis=0)
    smoothed  = _gauss_smooth(col_proj, sigma=3)
    threshold = smoothed.max() * 0.08
    is_ink    = smoothed > threshold
    runs      = _connected_components_1d(is_ink)
    blobs     = [(s, e) for s, e in runs if (e - s + 1) >= MIN_BLOB_COL]

    # Spatial filter: keep only blobs whose centre is in the digit region
    blobs = [(s, e) for s, e in blobs if x_min <= (s + e) / 2 <= x_max]

    # Merge adjacent narrow blobs that are parts of one split digit (e.g. "4").
    # A normal digit is ~150-200 px wide; split halves are <100 px each.
    merged = True
    while merged:
        merged = False
        new_blobs = []
        i = 0
        while i < len(blobs):
            if i + 1 < len(blobs):
                s1, e1 = blobs[i]
                s2, e2 = blobs[i + 1]
                w1, w2 = e1 - s1 + 1, e2 - s2 + 1
                gap = s2 - e1
                combined = e2 - s1 + 1
                if w1 < 100 and w2 < 100 and combined < 250 and gap < 100:
                    new_blobs.append((s1, e2))
                    i += 2
                    merged = True
                    continue
            new_blobs.append(blobs[i])
            i += 1
        blobs = new_blobs

    return blobs


def extract_templates(img_norm, frames, H):
    """
    Extract and average per-digit templates from known frames.
    Returns dict {digit_char: (TMPL_H, TMPL_W) float32 array}
    """
    accum  = {d: [] for d in '0123456789'}

    for frame_idx, cbd in KNOWN_CBDS.items():
        full_str = f"{FLIGHT:03d}{cbd:04d}"   # e.g. "1250465"
        l, r = frames[frame_idx]
        crop = (img_norm[:, l:r+1] * 255).clip(0, 255).astype(np.uint8)
        fw   = crop.shape[1]

        binary = get_binary_text(crop, H, fw)
        blobs  = find_digit_col_ranges(binary)

        # We expect 7 blobs (one per character in "1250XXX")
        if len(blobs) < 5 or len(blobs) > 10:
            print(f"  Frame {frame_idx}: {len(blobs)} blobs — skipping "
                  f"(expected ~7 for '{full_str}')")
            continue

        blobs = adjust_blobs_to_7(blobs)

        print(f"  Frame {frame_idx} (CBD {cbd:04d}): '{full_str}'  "
              f"{len(blobs)} blobs -> match")

        for (s, e), digit_char in zip(blobs, full_str):
            pad = 4
            crop_d = binary[:, max(0, s-pad): e+pad+1]
            if crop_d.shape[1] < 5 or crop_d.shape[0] < 5:
                continue
            resized = np.array(Image.fromarray(
                (crop_d * 255).astype(np.uint8)).resize(
                (TMPL_W, TMPL_H), Image.LANCZOS), dtype=np.float32) / 255.0
            accum[digit_char].append(resized)

    # Average multiple examples of each digit
    templates = {}
    for d, crops in accum.items():
        if crops:
            templates[d] = np.mean(crops, axis=0).astype(np.float32)
            print(f"  Digit '{d}': {len(crops)} examples averaged")
        else:
            print(f"  Digit '{d}': NO examples — missing from this TIFF!")
    return templates


def adjust_blobs_to_7(blobs):
    """
    Adjust a list of digit blob column ranges to exactly 7 entries.

    If > 7: merge the pair with the smallest gap (repeatedly).
    If < 7 (but >= 5): split the widest blob at its midpoint (once).
    If < 5 or > 10: return unchanged (caller should handle gracefully).

    Returns the adjusted list of (start, end) tuples.
    """
    if len(blobs) < 5 or len(blobs) > 10:
        return blobs
    blobs = list(blobs)
    while len(blobs) > 7:
        gaps = [(blobs[k+1][0] - blobs[k][1]) for k in range(len(blobs)-1)]
        m = int(np.argmin(gaps))
        merged = (blobs[m][0], blobs[m+1][1])
        blobs = blobs[:m] + [merged] + blobs[m+2:]
    if len(blobs) < 7:
        ws = [e - s for s, e in blobs]
        m = int(np.argmax(ws))
        s, e = blobs[m]
        mid = (s + e) // 2
        blobs = blobs[:m] + [(s, mid), (mid+1, e)] + blobs[m+1:]
    return blobs


def ncc_match(query, template):
    """Normalized cross-correlation between two equal-sized float arrays."""
    q = query   - query.mean()
    t = template - template.mean()
    denom = (np.linalg.norm(q) * np.linalg.norm(t)) + 1e-9
    return float(np.sum(q * t) / denom)


def recognize_frame(frame_crop, H, fw, templates):
    """
    Recognize the 7-digit number from a frame using NCC template matching.
    Returns (recognized_string, blobs) or (None, blobs) if recognition fails.
    """
    binary = get_binary_text(frame_crop, H, fw)
    blobs  = find_digit_col_ranges(binary)   # already spatially filtered

    if len(blobs) < 5:
        return None, blobs

    blobs = adjust_blobs_to_7(blobs)

    recognized = ""
    for s, e in blobs:
        pad    = 4
        crop_d = binary[:, max(0, s-pad): e+pad+1]
        if crop_d.shape[1] < 3:
            recognized += "?"
            continue
        query = np.array(Image.fromarray(
            (crop_d * 255).astype(np.uint8)).resize(
            (TMPL_W, TMPL_H), Image.LANCZOS), dtype=np.float32) / 255.0

        scores = {d: ncc_match(query, t) for d, t in templates.items()}
        best   = max(scores, key=scores.get)
        recognized += best

    return recognized, blobs


def apply_sequential_constraint(frame_indices, raw_reads, flight=None,
                                confidences=None):
    """
    Use the physical constraint |CBD[n+1] - CBD[n]| = 1 to validate and
    correct NCC recognition results.

    Parameters
    ----------
    frame_indices : list[int]
        Frame index (position in TIFF) for each complete frame, in order.
    raw_reads : list[str or None]
        NCC-recognized 7-char string (e.g. "1250465") per complete frame.
        None if recognition returned no result.
    flight : int or None
        If given, force the flight number prefix (e.g. 125) instead of
        majority-voting across OCR reads.  This eliminates a common failure
        mode where the flight digits are misread (e.g. "025" instead of "125"),
        which prevents correct CBD anchoring.
    confidences : list[float] or None
        Per-frame confidence scores (0.0-1.0).  When provided, anchor
        agreement is weighted by confidence instead of binary counting.
        Frames with confidence < 0.3 are excluded as candidate anchors.
        When None (default), all valid anchors are weighted equally (1.0).

    Returns
    -------
    corrected : list[str]
        Corrected 7-char strings. Frames that couldn't be corrected keep
        their raw read (or None).
    n_anchors : int
        Number of raw reads that agreed with the best-fit sequence.
    """
    # Parse CBD (last 4 digits) from each raw read — ignore the flight prefix
    # so that a misread flight number doesn't prevent anchoring.
    raw_cbds  = []
    flt_votes = {}
    for read in raw_reads:
        if read and len(read) >= 7:
            try:
                raw_cbds.append(int(read[-4:]))
                prefix = read[:3]
                if prefix.isdigit():
                    flt_votes[prefix] = flt_votes.get(prefix, 0) + 1
            except ValueError:
                raw_cbds.append(None)
        else:
            raw_cbds.append(None)

    # Flight string: use forced value if given, otherwise majority vote
    if flight is not None:
        flt_str = f"{flight:03d}"
    else:
        flt_str = max(flt_votes, key=flt_votes.get) if flt_votes else f"{FLIGHT:03d}"

    # valid = list of (list_pos, frame_idx, cbd_int)
    # When confidences are provided, filter out low-confidence anchors
    conf_threshold = 0.3
    valid = []
    for k, (fi, cbd) in enumerate(zip(frame_indices, raw_cbds)):
        if cbd is None:
            continue
        if confidences is not None and confidences[k] < conf_threshold:
            continue
        valid.append((k, fi, cbd))

    if len(valid) < 2:
        return raw_reads, len(valid)

    # Try both directions (+1 ascending, -1 descending); find best anchor
    # When confidences are provided, weight each agreeing anchor by its
    # confidence instead of counting each as 1.
    best_score        = 0
    best_anchor_fi    = frame_indices[0]
    best_anchor_cbd   = raw_cbds[0] if raw_cbds[0] is not None else 0
    best_direction    = 1

    for direction in (+1, -1):
        for _, anchor_fi, anchor_cbd in valid:
            score = sum(
                (confidences[k] if confidences is not None else 1)
                for k, fi, cbd in valid
                if cbd == anchor_cbd + direction * (fi - anchor_fi)
            )
            if score > best_score:
                best_score      = score
                best_anchor_fi  = anchor_fi
                best_anchor_cbd = anchor_cbd
                best_direction  = direction

    # Count integer anchors for reporting (how many frames agreed)
    n_anchors = sum(
        1 for _, fi, cbd in valid
        if cbd == best_anchor_cbd + best_direction * (fi - best_anchor_fi)
    )

    # Assign corrected CBD to every complete frame
    corrected = []
    for fi in frame_indices:
        expected_cbd = best_anchor_cbd + best_direction * (fi - best_anchor_fi)
        corrected.append(f"{flt_str}{expected_cbd:04d}")

    return corrected, n_anchors


# -- Main --------------------------------------------------------------------
if __name__ == "__main__":
    print(f"\nLoading {TIFF.name} ...")
    Image.MAX_IMAGE_PIXELS = None
    img      = np.array(Image.open(TIFF), dtype=np.float32)
    img_norm = (img - img.min()) / (img.max() - img.min() + 1e-9)
    H, W     = img_norm.shape
    frames   = detect_frames(img_norm)
    widths   = [r - l for l, r in frames]
    med_w    = float(np.median(widths))
    print(f"  {len(frames)} frames detected\n")

    # -- Step 1: build templates -------------------------------------------
    print("Building digit templates from known frames ...")
    templates = extract_templates(img_norm, frames, H)
    np.save(TMPL, templates)
    print(f"\n  Templates saved -> {TMPL.relative_to(ROOT)}")
    print(f"  Digits with templates: {sorted(templates.keys())}\n")

    # -- Step 2: raw NCC recognition on all complete frames ----------------
    print("Stage 1 — NCC recognition (raw) ...")
    complete_frame_indices = []
    raw_reads_list         = []

    for i, (l, r) in enumerate(frames):
        crop  = (img_norm[:, l:r+1] * 255).clip(0, 255).astype(np.uint8)
        fw    = crop.shape[1]
        ptype = "partial" if fw < 0.75 * med_w else "complete"
        if ptype == "complete":
            recog, _ = recognize_frame(crop, H, fw, templates)
            complete_frame_indices.append(i)
            raw_reads_list.append(recog)

    # -- Step 3: sequential constraint correction --------------------------
    print("Stage 2 — Sequential constraint correction ...")
    corrected_list, n_anchors = apply_sequential_constraint(
        complete_frame_indices, raw_reads_list
    )
    print(f"  Anchor agreement: {n_anchors}/{len(complete_frame_indices)} "
          f"raw reads consistent with best-fit sequence\n")

    # -- Step 4: report final results --------------------------------------
    print(f"  {'Fr':>3}  {'Raw NCC':>10}  {'Corrected':>10}  "
          f"{'Expected':>10}  {'W':>5}  {'Type':>8}  Status")
    print("  " + "-" * 72)

    comp_iter = iter(zip(complete_frame_indices, raw_reads_list, corrected_list))

    for i, (l, r) in enumerate(frames):
        fw    = r - l
        ptype = "partial" if fw < 0.75 * med_w else "complete"

        if ptype == "partial":
            print(f"  {i:>3}  {'—':>10}  {'—':>10}  {'—':>10}  "
                  f"{fw:>5}  {ptype:>8}")
            continue

        fi, raw, corr = next(comp_iter)
        expected_cbd = KNOWN_CBDS.get(i)
        expected_str = f"{FLIGHT:03d}{expected_cbd:04d}" if expected_cbd else "?"
        correct      = (corr == expected_str) if expected_cbd else None
        status       = "[OK]" if correct is True else ("[X]" if correct is False else "—")
        print(f"  {i:>3}  {str(raw):>10}  {str(corr):>10}  "
              f"{expected_str:>10}  {fw:>5}  {ptype:>8}  {status}")

    # -- Step 5: final metadata summary -----------------------------------
    print("\nFrame metadata summary (LYRA output):")
    print(f"  {'Fr':>3}  {'Type':>8}  {'CBD':>8}")
    print("  " + "-" * 25)

    comp_iter2 = iter(zip(complete_frame_indices, corrected_list))
    for i in range(len(frames)):
        fw    = frames[i][1] - frames[i][0]
        ptype = "partial" if fw < 0.75 * med_w else "complete"
        if ptype == "partial":
            print(f"  {i:>3}  {ptype:>8}  {'—':>8}")
        else:
            fi, corr = next(comp_iter2)
            cbd_str  = corr[3:] if corr and len(corr) >= 7 else "?"
            print(f"  {i:>3}  {ptype:>8}  {cbd_str:>8}")

    # -- Step 6: template contact sheet figure ----------------------------
    digits_sorted = sorted(templates.keys())
    nd   = len(digits_sorted)
    ncol = 5
    nrow = int(np.ceil(nd / ncol))

    fig, axes = plt.subplots(nrow, ncol, figsize=(ncol * 2.5, nrow * 3.5))
    fig.patch.set_facecolor("white")
    axes_flat = np.array(axes).flatten()

    for k, d in enumerate(digits_sorted):
        ax = axes_flat[k]
        ax.imshow(templates[d], cmap="gray", vmin=0, vmax=1, aspect="auto")
        n_ex = len([f for f in KNOWN_CBDS
                    if d in f"{FLIGHT:03d}{KNOWN_CBDS[f]:04d}"])
        ax.set_title(f"Digit '{d}'  ({n_ex} ex)", fontsize=10, fontweight="bold")
        ax.axis("off")

    for ax in axes_flat[nd:]:
        ax.set_visible(False)

    fig.suptitle(
        "LYRA digit templates — 7-segment font\n"
        f"Source: {TIFF.name}",
        fontsize=10, y=1.02,
    )
    fig.tight_layout()
    fig_path = OUT_DIR / "templates_validation.png"
    fig.savefig(fig_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"\n  Template figure -> {fig_path.relative_to(ROOT)}")
    print("\nDone.")
