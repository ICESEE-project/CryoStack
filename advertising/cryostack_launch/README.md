# CryoStack launch materials

Generated from repository revision `8f08dd28788fae9e331ba18bc3bc5e6337ec5ba7`.

## Deliverables

- `CryoStack_Advert.svg` — editable, standalone advert source
- `CryoStack_Advert.pdf` — print-quality one-page PDF
- `CryoStack_Advert.png` — 2480 × 3508 sharing image
- `CryoStack_Overview.pptx` — ten-slide, 16:9 PowerPoint deck
- `slides_rendered/` — editable SVG slide sources and inspected PNG renders
- `build_materials.py` — deterministic source generator
- `assets/` — copied/cropped source assets used in the designs

The PowerPoint preserves the inspected slide design as a high-resolution slide layer for consistent display across PowerPoint versions. Editable title and summary objects are included in each slide's Selection Pane. For complete visual editing, edit the corresponding SVG in `slides_rendered/` or the generator and rebuild.

Rebuild with:

```bash
python advertising/cryostack_launch/build_materials.py
```

## Public URLs shown

- CryoStack: `https://cryostack.eas.gatech.edu/`
- Documentation: `https://cryostack.eas.gatech.edu/documentation/`
- CryoLauncher: `https://cryostack.eas.gatech.edu/icesheets/`
- ICESEE: `https://cryostack.eas.gatech.edu/icesee-gui/`

These paths are defined in the deployed nginx configuration and linked by the current documentation and application guides.

## Source assets

- Canonical CryoStack logo: `icesee_jupyter_book/cryostack.png`
- Deployed optimized logo reference: `deployment/deploy_web_nginx/web/connect/cryostack-logo.png`
- CryoStack Connector icon: `icesee_hpc_connector/assets/cryostack-connector-512.png`
- Actual managed ISSM output: `stressbalance_velocity.png` from run `ba6537bb-c5fe-451b-98cf-47b453c84e3d`

No stock or AI-generated imagery was used. The repository contains no committed CryoLauncher interface screenshots, so the materials do not fabricate one. Slide 5 uses an actual scientific result produced by a managed CryoStack run.

## Capability audit

| Capability | Implemented? | Repository evidence | Included? |
|---|---|---|---|
| Browser-based experiment configuration | Yes | `icesee_jupyter_book/ui/icesheets_gateway.py`; CryoLauncher guides | Yes |
| ISSM workflows | Yes, on configured environments | `cryostack_src/models/issm/`; CryoLauncher guides | Yes |
| Icepack workflows | Yes, on configured environments | `cryostack_src/models/icepack/`; CryoLauncher guides | Yes |
| ICESEE ensemble data assimilation | Yes, for supported examples | `icesee_jupyter_book/ui/icesee_gateway.py`; ICESEE manuals | Yes |
| LIVIST temperature-data exploration | Yes | `/livist/` deployment route; LIVIST documentation | Yes, overview deck |
| Frozen Legacies radar-data exploration | Yes | `icesee_jupyter_book/applications/frozen_legacies/`; `/frozen-legacies/` route | Yes, overview deck |
| Remote/HPC and Slurm configuration | Yes | `cryostack_src/remote/`; `cryostack_src/execution/remote.py`; CryoLauncher manual | Yes |
| Connector v2 pairing and connector-backed SSH | Yes | `icesee_hpc_connector/`; connector relay tests | Yes |
| User-owned HPC identity | Yes | connector pairing/access implementation and documentation | Yes, explicitly |
| Job submission, status, logs, termination | Yes | `cryostack_src/remote/bridge.py`; workspace logs/runtime modules | Submission, status, logs advertised |
| Persistent run discovery/workspace selection | Yes | `cryostack_src/workspace/manifest.py`; `WorkspaceManager` | Implied as managed workflow |
| Result and figure download | Yes | `cryostack_src/workspace/manager.py` | Yes |
| Deterministic ISSM visualization | Yes | `cryostack_src/visualization/issm.py` and tests | Yes, qualified |
| Icepack visualization | Not currently implemented | `_visualizer_for()` and workspace result tests | No |
| Cloud/AWS production execution | Not established as production-ready | Cloud bridge retains incomplete/conditional paths | No |
| Documentation, Getting Started, manuals | Yes | `icesee_jupyter_book/documentation.md`; application guides | Yes |

## Deliberate exclusions and qualifications

- Cloud/AWS is not advertised.
- Icepack result visualization is not claimed; only downloadable results are mentioned.
- The Connector is shown as an implemented workflow component, but no claim of seamless installation—especially on macOS—is made.
- CryoStack, CryoLauncher, ICESEE, and CryoStack Connector are described as related but distinct components.
- LIVIST and Frozen Legacies are presented as data-exploration applications, not simulation engines.
- No claim is made that CryoStack removes the need for model expertise or HPC configuration; it provides a supported interface through those steps.
- ISSM and Icepack availability remains dependent on configured environments and examples.

## Branding and affiliation

Colors are sampled from the canonical CryoStack identity: deep navy, CryoStack blue, cyan, and restrained pale-blue surfaces. The affiliation wording follows the live repository footer: developed by ICCL and PGSL at the Georgia Institute of Technology.

## Verification

- Advert SVG rendered to PDF and PNG with `rsvg-convert`.
- All ten slides rendered at 1920 × 1080 and visually inspected as a contact sheet.
- Initial render defects involving XHTML text and logo cropping were corrected and all outputs regenerated.
- PowerPoint package passed `unzip -t` with no errors.
- PNG dimensions, PDF signature, and PPTX Office Open XML type were verified.
- No production code, connector binaries, deployment state, or application data were modified.
