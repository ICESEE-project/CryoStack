"""File discovery for the CryoLauncher workspace.

Pure pathlib -- no widgets, no model assumptions.

Two categories:
* *editable* -- text / source formats the Advanced editor can open in a textarea
* *data*     -- scientific formats that are **visible** in the explorer but not
  text-editable (viewed, referenced, downloaded, deleted -- not typed into)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

EDITABLE_SUFFIXES = {
    ".m", ".py", ".ipynb", ".yaml", ".yml", ".toml", ".sh", ".txt", ".md",
    ".json", ".cfg", ".ini", ".par",
}

#: scientific data formats -- visible, not text-editable
DATA_SUFFIXES = {
    ".mat", ".h5", ".hdf5", ".nc", ".csv", ".dat", ".exp", ".npy", ".npz",
    ".tif", ".tiff", ".geojson", ".shp", ".zip", ".gz", ".tar", ".pkl",
}

VISIBLE_SUFFIXES = EDITABLE_SUFFIXES | DATA_SUFFIXES


def is_text_editable(path: str | Path) -> bool:
    return Path(path).suffix.lower() in EDITABLE_SUFFIXES


def _iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.name.startswith(".cryostack"):
            yield path


def list_editable_files(example_path: str) -> list[tuple[str, str]]:
    """``[(relative_label, absolute_path), ...]`` for editable text files."""
    root = Path(example_path or "").expanduser()
    if not root.exists():
        return []
    if root.is_file():
        return [(root.name, str(root))] if is_text_editable(root) else []
    out: list[tuple[str, str]] = []
    for path in _iter_files(root):
        if path.suffix.lower() in EDITABLE_SUFFIXES:
            try:
                label = str(path.relative_to(root))
            except ValueError:
                label = path.name
            out.append((label, str(path)))
    return out


@dataclass(frozen=True)
class VisibleFile:
    label: str          # path relative to the root
    path: str           # absolute
    size: int
    editable: bool      # can be opened in the text editor


def list_visible_files(root_path: str) -> list[VisibleFile]:
    """Every explorer-visible file under a root, editable text or data alike."""
    root = Path(root_path or "").expanduser()
    if not root.exists() or not root.is_dir():
        return []
    out: list[VisibleFile] = []
    for path in _iter_files(root):
        suffix = path.suffix.lower()
        if suffix not in VISIBLE_SUFFIXES:
            continue
        try:
            label = str(path.relative_to(root))
        except ValueError:
            label = path.name
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        out.append(VisibleFile(label=label, path=str(path), size=size,
                               editable=suffix in EDITABLE_SUFFIXES))
    return out
