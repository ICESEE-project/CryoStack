# RIGGS and A-scope release — 19 October 2026

## Production release

- Converted `RIGGS_Hice.xlsx` without modifying the source workbook.
- Source workbook SHA-256: `7da4a688b365eaa3c614e4e38785534c0dcdd1d864b277a18073645398c091f6`.
- Generated CSV SHA-256: `e83879057daf36a077f8166f54fa7fb50fcba6731f30dbc908bf719877ecc4bd`.
- Validated 177 stations: 80 with a seismic-preferred measurement and 97 radar-only.
- Published immutable release `riggs-e83879057daf36a0` beneath the durable application data root.
- Citation is explicitly pending. The API and map mark every station provisional,
  context-only, and publication-ineligible. RIGGS is not treated as a Frozen
  Legacies pick or as validation of LYRA.
- Backup `20261019T135455Z` completed: 79 files, 309,727,134 bytes, no problems.
- All six application health checks returned HTTP 200 after the GUI-only restart.

## Observation quicklook

- The map popup has separate source-film/image and radargram/echogram panels.
- Missing media is represented by an explicit unavailable state; no substitute
  or synthetic preview is generated.
- The popup can be dragged with a pointer or moved with keyboard arrow keys.
  Mobile retains a stable bottom-sheet layout.

## A-scope bounded transfer

- The source inventory contains 1,628 files and 146,651,903,177 bytes.
- The active tranche contains the ten requested flight folders (125, 126, 127,
  128, 137, 138, 139, 141, 143, 149): 432 files and 46,106,662,537 bytes.
- Each file is written as a partial, verified against its Dropbox content hash,
  and atomically renamed. The manifest is updated atomically and supports resume.
- A 25 GiB local free-space reserve is enforced before transfer. ASTRA and the
  non-Neal flights remain pending for CEDAR rather than risking the VM/scratch.

## Continuing GUI work

The existing maintainer uploader is resumable, checksum-verified, unpublished
by default, and audited for radar TIFF/navigation intake. The next Control
Center release must add typed preview/map/publish workflows for navigation,
observation tables, RIGGS workbooks, and general dataset packages. Publication
must remain separate from upload and require provenance plus scientific review.
