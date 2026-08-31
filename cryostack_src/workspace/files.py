"""Editable-file discovery for the CryoLauncher workspace editor.

Pure pathlib -- no widgets, no model assumptions. Text/source formats a user
may edit in the Advanced editor; scientific data files are handled by the
dataset workflow, not here.
"""
from __future__ import annotations

from pathlib import Path

EDITABLE_SUFFIXES = {
    ".m", ".py", ".ipynb", ".yaml", ".yml", ".toml", ".sh", ".txt", ".md",
    ".json", ".cfg", ".ini", ".par",
}


def list_editable_files(example_path: str) -> list[tuple[str, str]]:
    """``[(relative_label, absolute_path), ...]`` for editable files under a root."""
    root = Path(example_path or "").expanduser()
    if not root.exists():
        return []
    if root.is_file():
        return [(root.name, str(root))] if root.suffix.lower() in EDITABLE_SUFFIXES else []

    files: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if path.name.startswith(".cryostack"):
            continue
        if path.is_file() and path.suffix.lower() in EDITABLE_SUFFIXES:
            try:
                label = str(path.relative_to(root))
            except ValueError:
                label = path.name
            files.append((label, str(path)))
    return files
