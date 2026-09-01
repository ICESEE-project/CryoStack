"""Model-neutral primitives for reading a CryoStack result package.

Every model's structured results land in the same on-disk shape regardless of
the execution backend (Remote / Container / Cloud)::

    <run>/outputs/
        metadata.json            # schema + what the run ACTUALLY produced
        figures/*.png            # deterministic or example-produced figures
        model/                   # native model artifacts (md_final.mat, *.h5, *.pvd, ...)
        fields/ mesh/            # structured field data (model-specific readers)

This module only owns the parts that carry no model science: locating the
``outputs/`` directory, reading ``metadata.json`` defensively, and enumerating
the figure / native-artifact files. The field / mesh / solution vocabulary is
model-specific and lives in each model's ``results.py``
(:mod:`cryostack_src.models.issm.results`, :mod:`cryostack_src.models.icepack.results`).
"""
from __future__ import annotations

import json
from pathlib import Path

METADATA_NAME = "metadata.json"

#: files treated as "figures" (shown directly) vs "native model artifacts"
FIGURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".svg", ".pdf", ".gif")
NATIVE_ARTIFACT_SUFFIXES = (
    ".mat", ".h5", ".hdf5", ".pvd", ".vtu", ".vtk", ".pvtu", ".xdmf",
    ".nc", ".npz", ".npy", ".pkl",
)


def find_outputs_dir(root: str | Path) -> Path | None:
    """Return the ``outputs/`` directory for a run, or ``None`` if absent.

    Accepts the run directory, the ``outputs`` directory itself, or a directory
    that already looks like an unpacked package (has ``metadata.json`` or one of
    the standard subdirs).
    """
    root = Path(root).expanduser()
    if not root.is_dir():
        return None
    if root.name == "outputs":
        return root
    if (root / "outputs").is_dir():
        return root / "outputs"
    if any((root / m).exists() for m in
           (METADATA_NAME, "model", "fields", "mesh", "figures")):
        return root
    return None


def read_metadata(outputs: Path | None) -> dict:
    """Read ``outputs/metadata.json`` as a dict. Never raises: a missing or
    malformed file yields ``{}``."""
    if outputs is None:
        return {}
    meta_file = Path(outputs) / METADATA_NAME
    if not meta_file.is_file():
        return {}
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def list_figures(outputs: Path | None) -> list[Path]:
    """Figure files under ``outputs/`` (``figures/`` first, then any elsewhere)."""
    if outputs is None:
        return []
    outputs = Path(outputs)
    figdir = outputs / "figures"
    figs = sorted(p for p in figdir.glob("*") if p.suffix.lower() in FIGURE_SUFFIXES) \
        if figdir.is_dir() else []
    seen = {p.name for p in figs}
    extra = sorted(
        p for p in outputs.rglob("*")
        if p.is_file() and p.suffix.lower() in FIGURE_SUFFIXES and p.name not in seen
        and figdir not in p.parents
    )
    return figs + extra


def legacy_artifacts(outputs: Path | None, *, model_mat_name: str | None = None) -> dict:
    """A model-neutral inventory of a package's raw files, in the shape the
    Results panel's legacy view expects: ``{model_mat, figures, mats, other}``.

    ``model_mat_name`` names the model's "full state" artifact if it has one
    (ISSM: ``md_final.mat``); ``None`` for models that don't.
    """
    if outputs is None:
        return {"model_mat": None, "figures": [], "mats": [], "other": []}
    outputs = Path(outputs)
    model_mat = None
    if model_mat_name:
        cand = outputs / "model" / model_mat_name
        model_mat = str(cand) if cand.is_file() else None

    figures = [str(p) for p in list_figures(outputs)]
    mats = sorted(str(p) for p in outputs.rglob("*.mat"))
    native = sorted(
        str(p) for p in outputs.rglob("*")
        if p.is_file() and p.suffix.lower() in NATIVE_ARTIFACT_SUFFIXES
        and p.suffix.lower() != ".mat"
    )
    other = sorted(
        str(p) for p in outputs.rglob("*")
        if p.is_file() and p.suffix.lower() not in
        (*FIGURE_SUFFIXES, *NATIVE_ARTIFACT_SUFFIXES, ".json")
    )
    return {"model_mat": model_mat, "figures": figures, "mats": mats,
            "native": native, "other": other}
