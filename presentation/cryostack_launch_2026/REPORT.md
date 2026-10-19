# CryoStack launch deck — build report

Generated from repository revision on branch `gatech_vm_backend` (HEAD at build time: see `git log -1`).
Not committed — this whole `presentation/` directory is currently untracked, per instructions.

Originally an 8-slide, ~9:00 deck; now **9 slides, ~9:50**, with slide 9 ("See CryoStack in action")
added as a demo-video slide. Slides 1–8 were kept frozen for this addition (no redesign) — see
`## Revision history` at the bottom for what changed and when.

## Deliverables

| File | What it is |
|---|---|
| `output/CryoStack_Launch_Deck.pptx` | Editable 9-slide, 16:9 PowerPoint deck |
| `output/CryoStack_Launch_Deck.pdf` | Full-deck PDF preview (9 pages) |
| `output/previews/slide-N.png` | Per-slide QA renders used to inspect clipping/overlap/alignment |
| `output/CryoStack_Contact_Sheet.png` | 3×3 contact sheet of all 9 slides, for at-a-glance review |
| `output/slides_svg/*.svg` / `*.png` | Editable vector background per slide (diagrams, cards, images) — the design source |
| `assets/` | Copied/derived source images used in the deck |
| `media/` | Slide 9's demo-recording placeholders and briefs — see `media/README.md` |
| `build/build_deck.py` | Deterministic generator — rerun with `python3 build_deck.py` to rebuild everything |
| `build/make_contact_sheet.py` | Regenerates the contact sheet from existing previews |

### How "editable" works here

There is no LibreOffice/PowerPoint available in this environment to render `.pptx` natively, so the
pipeline is split in a way that keeps genuine editability where it matters most for a presenter:

- **Real, editable PowerPoint text** for every headline, kicker, central statement, footer, and the
  closing URL/CTA text — these are actual `python-pptx` text boxes, selectable and re-typable in
  PowerPoint/Keynote/Google Slides, positioned to match the design.
- **Vector-rendered background art** (rsvg-convert, from hand-written SVG) for diagrams, cards, pills,
  flow arrows, and result images — flattened to a crisp PNG per slide, because regenerating a diagram's
  internal geometry by dragging PowerPoint shapes isn't a realistic edit path anyway. To change a
  diagram, edit `build_deck.py` and rerun.
- Every slide has real, editable **speaker notes** in the PPTX notes pane.
- The PDF and PNG previews are produced independently (Pillow, compositing the same overlay text onto
  the same backgrounds) purely so the deck could be visually QA'd without a native renderer — they are
  not the source of truth, the script is.

## Source assets (all pre-existing in the repository; nothing fabricated)

| Asset used | Source | Notes |
|---|---|---|
| CryoStack hexagon mark | `icesee_jupyter_book/cryostack.png` | Cropped to icon-only (wordmark removed since the title slide sets "CryoStack" as live text) and background keyed to transparent |
| ISSM stress-balance velocity result | `advertising/cryostack_launch/assets/issm-stressbalance-velocity.png` | Real output from a managed CryoStack ISSM run (per that folder's own README) |
| ICESEE Lorenz-96 ensemble result | `external/ICESEE/scripts/ci/figures/lorenz96_ci.png` | Real CI/ensemble data-assimilation result plot |
| QR code | generated locally (`qrcode` library) | Encodes `https://cryostack.eas.gatech.edu/index.html`, the URL given in the request |
| Color palette | `advertising/cryostack_launch/build_materials.py` / that folder's README | Reused the same audited "canonical CryoStack identity" palette (navy `#082B59`, blue `#087EEB`, cyan `#24B8E8`) for brand consistency with prior launch materials |

**Not used, deliberately:**
- No CryoLauncher/ICESEE/Frozen Legacies/LIVIST UI screenshot — none exists anywhere in the repository
  (confirmed by search; the prior `advertising/cryostack_launch/README.md` states the same thing). Slide
  3 uses an honest abstract diagram (browser chrome + app tiles + arrow to compute) instead of a
  fabricated screenshot.
- No Frozen Legacies/LIVIST logos — the only logos found for those names belong to unrelated standalone
  submodule tools (ARIES/ASTRA/etc. under `external/FrozenLegacies/`), not CryoStack-integrated branding,
  so they're represented as plain text/color cards instead.
- No GitHub link on the closing slide — only URLs explicitly given in the request or already published in
  the repo's own README were used (`cryostack.eas.gatech.edu` and its documentation path); no URL was
  invented.
- No demo-recording thumbnails on slide 9 — the three recordings (ISSM Remote HPC, ISSM Cloud, Icepack
  Cloud) don't exist yet, so each panel shows a generated, clearly-labeled "PLACEHOLDER — recording
  pending" graphic (no UI, no fabricated screenshot) instead. See `media/README.md`.

## Live-site verification

Both URLs shown or encoded in the deck were checked against the live site, not assumed:
- `https://cryostack.eas.gatech.edu/index.html` → HTTP 200 (QR code and visible URL on slide 8).
- `cryostack.eas.gatech.edu/documentation/` → **HTTP 404** on first check; the working path is
  `documentation.html` (HTTP 200). The deck now shows the corrected path.

The two authenticated applications (`/icesheets/` = CryoLauncher, `/icesee-gui/` = ICESEE) redirect to a
sign-in wall, and no browser-automation tool was available in this environment to authenticate or render
them visually — so slide 3 intentionally uses an abstract diagram rather than a screenshot (see above),
and no attempt was made to fabricate or reconstruct one from memory.

## Accuracy guardrails applied (per the request's explicit constraints)

- Slide 4 does not imply one universal execution pipeline across the four apps.
- Slide 5 gives CryoLauncher only Remote + Cloud (no Local mode); Local is scoped to "where supported,
  particularly ICESEE"; Connector/Relay is labeled as connectivity, not an execution backend.
- Slide 6 explicitly excludes Spot, GPU, multi-node, and ISSM-coupled-ICESEE-Cloud as validated claims —
  it states only what's confirmed: institutional HPC, AWS Batch (Fargate & EC2 on-demand), MPI solves,
  postprocessing, retrieval, visualization for ISSM; Fargate/EC2 for Icepack; Lorenz-96-in-Cloud for
  ICESEE; and the AWS→Georgia Tech MATLAB license path via Connector/Relay "when required."
- Slide 7 is phrased as an active, ongoing effort ("built to carry," "actively deepening"), not a
  uniform guarantee already implemented everywhere.
- Slide 8 clearly separates PISM/Elmer/Ice/SICOPOLIS as onboarding roadmap items, not integrated apps.

## Estimated speaking time

| # | Slide | ~Seconds | ~Minutes |
|---|---|---|---|
| 1 | CryoStack (title) | 30 | 0.5 |
| 2 | The challenge is bigger than the model | 60 | 1.0 |
| 3 | Introducing CryoStack | 60 | 1.0 |
| 4 | One platform. Different scientific workflows. | 90 | 1.5 |
| 5 | From your browser to the compute you already use | 90 | 1.5 |
| 6 | It is already running real science | 90 | 1.5 |
| 7 | The experiment is more than its final output | 60 | 1.0 |
| 8 | CryoStack is live | 60 | 1.0 |
| 9 | See CryoStack in action | 50 | 0.83 |
| | **Total** | **590** | **9.83 (~9:50)** |

Within the requested 9:45–10:00 window; leaves roughly a 10-second buffer against the 10-minute cap.
The 50s on slide 9 is mostly video playback time (~15–20s per clip once real recordings exist), not
spoken narration — the notes themselves are a short bridge (~28s at a natural pace).

## Slide 9 — "See CryoStack in action"

Added as a new final slide; slides 1–8 were not redesigned, reordered, or recolored to accommodate it
(no mechanical changes to 1–8 were needed — adding a 9th slide to the generator is purely additive).

Three equal-weight panels (ISSM — Remote HPC, ISSM — Cloud, Icepack — Cloud), each a bordered white card
matching the existing card style (slide 4/6 language): a 16:9 thumbnail area with a play-button glyph
drawn in the slide's own SVG chrome (so it stays consistent even after a real thumbnail is dropped in),
and a bold caption below. A quiet bottom line notes these are short excerpts and the full recordings will
become CryoStack tutorials. No new colors, fonts, or layout idioms were introduced — same palette,
same kicker/footer treatment, same card/border/typography conventions as slides 2–7.

None of the three recordings exist yet. Each panel currently shows a generated
"PLACEHOLDER — recording pending" thumbnail (plain fill, no UI, no fabricated screenshot) so the slide
is presentation-ready today; swapping in a real `thumbnail.png` per `media/<folder>/` and rerunning the
generator updates the slide automatically. Actual video embedding is a manual PowerPoint step performed
later (documented in `media/README.md`) — python-pptx's video support was judged too unreliable to
attempt now, especially with no real video files to test against, and the task explicitly asked not to
risk the generator's stability chasing that automation.

## Visual QA performed

Every slide was rendered to PNG at full 1920×1080 (both the plain SVG background and the fully
composited version with overlay text) and visually inspected in sequence. Two rounds of fixes were
made after the first render:
1. A pill label wrapped across 4 lines and overflowed its box on slide 3 — fixed by widening the box
   and disabling aggressive character-wrap for long single-line labels.
2. The generic `box()` diagram helper mis-centered multi-line label+subtitle combinations, causing
   subtitle text to spill below the box border on slide 5 (architecture diagram nodes) and slide 6
   (evidence cards), which also caused a card/pill overlap on slide 6 — fixed by rewriting the box
   layout math to correctly center the full label+subtitle block, and by re-budgeting vertical spacing
   on both slides.

After fixes, all slides were re-rendered and re-inspected with no remaining clipping, overlap, or
overflow (repeated again after the slide 9 addition, with the same result).

## Revision history

1. **Initial 8-slide build.** Full deck generated per the original 8-slide narrative brief.
2. **Visual refinement pass.** Rebalanced slide 1's whitespace, softened slide 4's cards into
   scientific line-icon panels, made slide 6's result images dominant, bookended slide 8 with the
   CryoStack mark and a stronger QR/URL treatment. No narrative or slide-count change.
3. **Content + technical audit.** Corrected the slide 6 ISSM caption (it had attributed Fargate/EC2 to
   an image whose actual run metadata shows a PACE/Connector Remote run), fixed a broken documentation
   URL, widened the QR code's quiet zone to spec, tightened slide 7's reproducibility wording so the
   architecture/goal is distinguished from per-application maturity, and reordered slide 8's closing so
   it lands on the launch invitation rather than roadmap items. Speaker-note timing was checked against
   word count and found already comfortably under budget on every slide — no shortening needed.
4. **Slide 9 added.** New "See CryoStack in action" demo-video slide appended at the end; slides 1–8
   left untouched. Timing extended from 9:00 to ~9:50.
