# Slide 9 demo recordings

Three short demonstration recordings for "See CryoStack in action." None of these recordings exist
yet — each subfolder currently holds only a **generated placeholder thumbnail** (clearly labeled as a
placeholder, not a screenshot of a real run) so the slide renders presentation-ready before the footage
exists.

## Recording briefs

| Folder | Demonstrates | Path (keep terminology accurate) |
|---|---|---|
| `issm_remote/` | ISSM — Remote HPC | CryoLauncher → configure ISSM → Remote → PACE → Connector/Direct SSH (as appropriate) → submit → monitor → result |
| `issm_cloud/` | ISSM — Cloud | CryoLauncher → configure ISSM → Cloud → AWS (Fargate or EC2 On-Demand — **not** Spot/GPU/multi-node) → submit → monitor → postprocess → retrieve/visualize |
| `icepack_cloud/` | Icepack — Cloud | CryoLauncher → configure Icepack → Cloud → AWS (Fargate or EC2 On-Demand) → submit → monitor → retrieve/view |

Only use configurations that have actually been demonstrated end-to-end (see the accuracy guardrails in
`../REPORT.md`). Connector/Relay is connectivity infrastructure, not an execution backend — don't narrate
it as one.

## Recording guidance (important for reuse)

These clips do double duty: a ~15–20s excerpt plays during the 10-minute launch talk, but the **full,
untrimmed recording** is the actual deliverable — it will be reused for CryoStack website tutorials,
documentation, workshop material, and potentially a CryoStack YouTube channel.

- **Do not narrate anything presentation-specific** into the source recording (no "as you can see on this
  slide," no references to the talk itself). Record it so it stands alone as a tutorial.
- Capture the full arc — Configure → Submit → Monitor → Result — at whatever length is natural for a
  tutorial. Trim a 15–20s excerpt (Configure → Submit → Run → Result, compressed) separately for the
  slide; keep the full file for reuse.

## Expected files per folder (once recorded)

```
issm_remote/
├── thumbnail.png        # replaces the placeholder — a real frame from the recording, 16:9
├── clip_15s.mp4          # the trimmed excerpt used in the launch slide
└── full_recording.mp4    # untrimmed, narration-free source for tutorials/docs/YouTube
```

Same structure for `issm_cloud/` and `icepack_cloud/`.

## Replacing a placeholder

1. Drop the real `thumbnail.png` (a representative frame, 16:9, ideally ~1280×720 or larger) into the
   folder, replacing `thumbnail_placeholder.png`.
2. Rerun `python3 ../build/build_deck.py`. Slide 9 pulls `media/<name>/thumbnail.png` if present,
   falling back to the placeholder otherwise — no code changes needed for the thumbnail swap.
3. **Video embedding is a manual PowerPoint step, done once the real MP4s exist** (see below) — the
   generator does not attempt to embed video automatically.

## Manual video embedding (do this once `clip_15s.mp4` files exist)

Automated video embedding via the Python deck generator was deliberately not attempted: python-pptx's
video support (`add_movie`) is finicky across PowerPoint versions and needs a matching poster-frame
image, and there's no real video file to embed yet anyway. Embedding by hand in PowerPoint is more
reliable and takes a minute per clip:

1. Open `output/CryoStack_Launch_Deck.pptx`, go to slide 9.
2. For each of the three panels: **Insert → Video → This Device...**, choose the matching
   `media/<name>/clip_15s.mp4`.
3. Resize/position the inserted video to exactly cover the placeholder thumbnail rectangle (the
   placeholder's rounded white border stays visible as the frame).
4. Right-click the video → **Trim Video** if the clip needs further trimming to 15–20s.
5. Playback options → set **Start: On Click** (so you control pacing live) and pick a poster frame if
   PowerPoint doesn't choose a good one automatically.
6. Delete the placeholder picture underneath once the video is confirmed positioned correctly (or leave
   it — PowerPoint shows the video on top regardless).

Do this after rebuilding the deck from the generator, since rerunning `build_deck.py` regenerates the
slide from scratch and would not preserve a manually embedded video.
