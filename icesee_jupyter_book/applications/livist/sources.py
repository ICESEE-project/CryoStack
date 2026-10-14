"""Attenuation inputs a LIVIST job may use.

Inputs are never free-form paths. A maintainer approves a *candidate*:

* ``source-coop`` -- an object key LIVIST's own pinned ``config.toml`` lists
  under ``[attenuation_paths]`` (LIVIST downloads it from source.coop itself);
* ``local`` -- a ``.txt``/``.csv`` file inside one of the operator's
  ``CRYOSTACK_LIVIST_INPUT_ROOTS``.

Candidates are identified by an opaque ID derived from their location, and
the location is re-resolved and re-checked on the server whenever a job
uses it. Responses show local locations masked.
"""
from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path, PurePosixPath

from . import settings

KINDS = ("source-coop", "local")
LOCAL_SUFFIXES = (".txt", ".csv")
#: the source.coop prefix LIVIST reads its inputs from
SOURCE_COOP_PREFIX = "englacial/ice-sheet-temperature/"
#: a LIVIST attenuation name ends up in product file names
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
_SCAN_LIMIT = 500
_SCAN_DEPTH = 4


class SourceError(ValueError):
    """An input that is not (or no longer) approved."""


def is_valid_name(value: object) -> bool:
    return isinstance(value, str) and _NAME.fullmatch(value) is not None


def mask_location(location: str) -> str:
    parts = [p for p in str(location or "").split("/") if p]
    return "…/" + "/".join(parts[-2:]) if len(parts) > 2 else "/".join(parts)


def candidate_id(kind: str, location: str) -> str:
    return hashlib.sha256(f"{kind}\0{location}".encode()).hexdigest()[:20]


def upstream_config(source: Path | None = None) -> dict:
    """LIVIST's pinned ``config.toml`` (borehole path and attenuation keys)."""
    path = (source or settings.source_dir()) / "config.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {"borehole_path": None, "attenuation_paths": {}}
    paths = data.get("attenuation_paths")
    return {
        "borehole_path": data.get("borehole_path") if isinstance(data.get("borehole_path"), str)
        else None,
        "attenuation_paths": {k: v for k, v in paths.items() if isinstance(v, str)}
        if isinstance(paths, dict) else {},
    }


def valid_source_coop_key(key: object) -> str:
    if not isinstance(key, str) or not key.startswith(SOURCE_COOP_PREFIX):
        raise SourceError("Not an approved source.coop object.")
    parts = PurePosixPath(key).parts
    if key != str(PurePosixPath(key)) or any(p in ("", ".", "..") for p in parts):
        raise SourceError("Not an approved source.coop object.")
    return key


def resolve_local(location: object, roots: list[Path] | None = None) -> Path:
    """An approved local file: a regular file under an approved root."""
    roots = settings.input_roots() if roots is None else roots
    if not isinstance(location, str) or not location:
        raise SourceError("Not an approved local input.")
    try:
        path = Path(location).resolve(strict=True)
    except (OSError, RuntimeError):
        raise SourceError("The approved local input no longer exists.")
    if path.suffix.lower() not in LOCAL_SUFFIXES or not path.is_file():
        raise SourceError("Not an approved local input.")
    if not any(path.is_relative_to(root) for root in roots):
        raise SourceError("The local input is outside the approved input directories.")
    return path


def candidates(*, source: Path | None = None, roots: list[Path] | None = None) -> list[dict]:
    """Every input a maintainer may approve (server-side locations)."""
    out = []
    for name, key in sorted(upstream_config(source)["attenuation_paths"].items()):
        try:
            valid_source_coop_key(key)
        except SourceError:
            continue
        out.append({"id": candidate_id("source-coop", key), "kind": "source-coop",
                    "location": key, "suggested_name": name if is_valid_name(name) else ""})
    roots = settings.input_roots() if roots is None else roots
    seen = 0
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if seen >= _SCAN_LIMIT:
                break
            rel = path.relative_to(root)
            if len(rel.parts) > _SCAN_DEPTH or any(p.startswith(".") for p in rel.parts):
                continue
            if path.suffix.lower() not in LOCAL_SUFFIXES or path.is_symlink() or not path.is_file():
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                continue
            seen += 1
            location = str(resolved)
            stem = re.sub(r"[^a-z0-9-]+", "-", path.stem.lower()).strip("-")[:32]
            out.append({"id": candidate_id("local", location), "kind": "local",
                        "location": location, "size": path.stat().st_size,
                        "suggested_name": stem if is_valid_name(stem) else ""})
    return out


def public_candidate(item: dict) -> dict:
    out = {k: item[k] for k in ("id", "kind", "suggested_name")}
    out["location"] = (item["location"] if item["kind"] == "source-coop"
                       else mask_location(item["location"]))
    if "size" in item:
        out["size"] = item["size"]
    return out


def public_source(row: dict) -> dict:
    return {
        "name": row["name"], "kind": row["kind"],
        "location": row["location"] if row["kind"] == "source-coop"
        else mask_location(row["location"]),
        "description": row.get("description") or "",
        "enabled": bool(row.get("enabled")),
        "created_at": row.get("created_at"),
    }


def staging_key(row: dict) -> str:
    """Where the input sits under the job's ``data/`` directory: the
    source.coop key itself (LIVIST downloads it there), or ``local/<name>``."""
    if row["kind"] == "source-coop":
        return valid_source_coop_key(row["location"])
    return f"local/{row['name']}{Path(row['location']).suffix.lower()}"


def stage(row: dict, data_dir: Path, *, roots: list[Path] | None = None) -> str:
    """Prepare one approved input in a job's ``data/`` directory."""
    key = staging_key(row)
    if row["kind"] == "local":
        target = resolve_local(row["location"], roots)
        link = data_dir / key
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
    return key


def render_config(borehole_path: str, attenuation_paths: dict[str, str]) -> str:
    """A LIVIST ``config.toml`` (keys are validated names and keys only)."""
    def q(value: str) -> str:
        if any(c in value for c in '"\\\n\r'):
            raise SourceError("Unsupported character in a LIVIST configuration value.")
        return f'"{value}"'

    lines = ['data_directory = "data"', f"borehole_path = {q(borehole_path)}", "",
             "[attenuation_paths]"]
    for name, key in attenuation_paths.items():
        if not is_valid_name(name):
            raise SourceError("Invalid attenuation name.")
        lines.append(f"{name} = {q(key)}")
    return "\n".join(lines) + "\n"
