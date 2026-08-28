from __future__ import annotations

from pathlib import Path

EDITABLE_SUFFIXES = {".m", ".py", ".ipynb", ".yaml", ".yml", ".sh", ".txt", ".md", ".json"}


def list_editable_files(example_path: str) -> list[tuple[str, str]]:
    root = Path(example_path).expanduser()
    if not root.exists():
        return []
    if root.is_file():
        return [(root.name, str(root))] if root.suffix.lower() in EDITABLE_SUFFIXES else []

    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in EDITABLE_SUFFIXES:
            try:
                label = str(path.relative_to(root))
            except Exception:
                label = path.name
            files.append((label, str(path)))
    return files
