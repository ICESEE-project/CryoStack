from __future__ import annotations


def expand_remote_home(path: str | None) -> str:
    if path is None:
        return ""
    path = str(path).strip()
    return path or ""


def normalize_remote_path(path: str | None) -> str:
    path = expand_remote_home(path)
    if not path:
        return ""
    while "//" in path:
        path = path.replace("//", "/")
    return path
