"""Icepack postprocessing: collect a run's outputs into the neutral package shape.

Unlike ISSM (whose MATLAB ``md.results`` struct is serialised field-by-field),
Icepack results are Firedrake ``Function`` objects whose neutral, model-aware
export is not yet defined (a deliberate scientific-decision checkpoint -- see
``overnight/AGENT_TRAIL.md`` §B). Until then this step does the part that carries
no model science: it gathers whatever figures / native output files the example
produced into ``outputs/`` and writes an honest ``metadata.json`` that records
exactly what exists -- never a fabricated field or solution.

Runs as plain ``python`` (stdlib only -- no icepack / firedrake import needed) on
whatever resource executed the run:

    CRYOSTACK_RUN_DIR      the run directory (contains outputs/)         [required]
    CRYOSTACK_EXAMPLE_DIR  where the example executed (artifacts land)   [optional]
    CRYOSTACK_RUN_STARTED  epoch seconds; only files touched at/after    [optional]
                           this time are collected (avoids sweeping in
                           example inputs that predate the run)
"""
from __future__ import annotations

SCHEMA = "cryostack.icepack.results"

_SCRIPT = r'''# CryoStack Icepack neutral output collector (auto-generated -- do not edit)
import json, os, shutil, sys, time
from pathlib import Path

FIGURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".svg", ".pdf", ".gif")
NATIVE_SUFFIXES = (".h5", ".hdf5", ".pvd", ".vtu", ".vtk", ".pvtu", ".xdmf",
                   ".nc", ".npz", ".npy", ".pkl", ".mat")

run_dir = Path(os.environ.get("CRYOSTACK_RUN_DIR") or ".").expanduser()
example_dir = os.environ.get("CRYOSTACK_EXAMPLE_DIR") or ""
started = float(os.environ.get("CRYOSTACK_RUN_STARTED") or 0.0)

outputs = run_dir / "outputs"
for sub in ("figures", "model", "fields", "mesh"):
    (outputs / sub).mkdir(parents=True, exist_ok=True)

search_roots = []
for cand in (example_dir, str(run_dir)):
    p = Path(cand).expanduser() if cand else None
    if p and p.is_dir() and p not in search_roots:
        search_roots.append(p)

def _fresh(path):
    if started <= 0:
        return True
    try:
        return path.stat().st_mtime >= started - 1
    except OSError:
        return False

figures, model_files, skipped = [], [], []
for root in search_roots:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if outputs in path.parents:            # already collected
            continue
        suffix = path.suffix.lower()
        if suffix in FIGURE_SUFFIXES:
            dest_dir = outputs / "figures"
        elif suffix in NATIVE_SUFFIXES:
            dest_dir = outputs / "model"
        else:
            continue
        if not _fresh(path):
            skipped.append({"name": path.name, "reason": "predates run start"})
            continue
        dest = dest_dir / path.name
        try:
            shutil.copy2(path, dest)
        except OSError as e:
            skipped.append({"name": path.name, "reason": f"copy failed: {e}"})
            continue
        (figures if suffix in FIGURE_SUFFIXES else model_files).append(dest.name)

metadata = {
    "schema": "%SCHEMA%",
    "version": 1,
    "model": "icepack",
    "status": "artifacts" if (figures or model_files) else "empty",
    "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "solutions": [],
    "fields": [],
    "figures": sorted(set(figures)),
    "model_files": sorted(set(model_files)),
    "skipped": skipped,
    "note": ("Icepack structured field export is not yet available. Figures and "
             "native output files produced by the example are collected here; "
             "no fields or solutions are inferred."),
}
(outputs / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

print("[cryostack] icepack outputs collected:",
      len(metadata["figures"]), "figure(s),", len(metadata["model_files"]),
      "model file(s)")
if skipped:
    print("[cryostack] skipped", len(skipped), "file(s) (see metadata.json)")
'''.replace("%SCHEMA%", SCHEMA)


def build_postprocess() -> str:
    """The stdlib-only Python collector script (see module docstring)."""
    return _SCRIPT
