"""Reproducibility record of an ICESEE run (``provenance.json``).

Everything needed to trace a finished run back to what produced it: the
experiment and execution mode, the exact ``params.yaml`` and every other
input file the run staged (with checksums, and which ones the user edited),
the CryoLauncher and ICESEE code versions, the Python environment or
container image, the command and the requested resources.

Credentials never enter it: the caller passes resource choices, not
connection secrets, and the record is passed through ``strip_secrets`` before
it is written.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
from datetime import datetime
from importlib import metadata as importlib_metadata
from pathlib import Path

from .paths import EXT, REPO

PROVENANCE_FILE = "provenance.json"
SCHEMA = "icesee-run-provenance/1"
_PACKAGES = ("numpy", "scipy", "h5py", "mpi4py", "matplotlib", "jax", "pyyaml")
_CODE_CACHE: dict = {}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(*args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def code_versions() -> dict:
    """CryoLauncher commit (and whether the checkout has local changes) and
    the ICESEE version the launcher runs. external/ICESEE is a submodule:
    ``upstream_commit`` is the ICESEE commit checked out there, ``pinned_commit``
    the one CryoLauncher records, ``vendored_tree`` that commit's source tree.
    A pre-submodule checkout falls back to ICESEE_UPSTREAM_SHA.txt and the
    vendored subtree. Cached per process."""
    if _CODE_CACHE:
        return dict(_CODE_CACHE)
    commit = _git("rev-parse", "HEAD")
    dirty = _git("status", "--porcelain", "--untracked-files=no", "--ignore-submodules=all")
    icesee_dir = REPO / "external" / "ICESEE"
    pinned = _git("rev-parse", "HEAD:external/ICESEE")
    if (icesee_dir / ".git").exists():
        checked_out = _git("-C", "external/ICESEE", "rev-parse", "HEAD")
        icesee = {
            "upstream_commit": checked_out or None,
            "pinned_commit": pinned or None,
            "vendored_tree": _git("-C", "external/ICESEE", "rev-parse", "HEAD^{tree}") or None,
            "local_changes": bool(_git("-C", "external/ICESEE", "status", "--porcelain",
                                       "--untracked-files=no")) if checked_out else None,
        }
    else:
        upstream = ""
        sha_file = REPO / "external" / "ICESEE_UPSTREAM_SHA.txt"
        if sha_file.is_file():
            upstream = sha_file.read_text(encoding="utf-8").strip()
        icesee = {"upstream_commit": upstream or None, "vendored_tree": pinned or None}
    _CODE_CACHE.update({
        "cryolauncher": {"commit": commit or None, "local_changes": bool(dirty) if commit else None},
        "icesee": icesee,
    })
    return dict(_CODE_CACHE)


def python_environment() -> dict:
    versions = {}
    for name in _PACKAGES:
        try:
            versions[name] = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            continue
    return {"python": platform.python_version(), "executable": sys.executable, "packages": versions}


def input_files(staged_example: Path | None, edited: dict | None = None) -> list[dict]:
    """Every file of the staged example copy with its checksum; ``edited``
    maps relative path -> origin for files the user changed in the editor."""
    edited = edited or {}
    files = []
    if staged_example and Path(staged_example).is_dir():
        root = Path(staged_example)
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = str(path.relative_to(root))
            if "__pycache__" in rel or rel.startswith("_modelrun_datasets"):
                continue
            files.append({"path": rel, "sha256": sha256_file(path), "bytes": path.stat().st_size,
                          "edited": rel in edited})
    return files


def collect(*, run_id: str, run_dir: Path, example: str, example_cfg: dict, mode: str, backend: str,
            params_file: Path | None, staged_example: Path | None = None, edited: dict | None = None,
            command: list | str | None = None, environment: dict | None = None,
            resources: dict | None = None, user_id: str = "") -> dict:
    from cryostack_src.workspace.resource_state import strip_secrets

    params_sha = sha256_file(params_file) if params_file and Path(params_file).is_file() else None
    record = {
        "schema": SCHEMA,
        "run_id": run_id,
        "created": datetime.now().isoformat(timespec="seconds"),
        "user": user_id or None,
        "experiment": {
            "example": example,
            "model": example_cfg.get("model_name"),
            "example_path": str(Path(example_cfg.get("base", "")).relative_to(EXT))
            if str(example_cfg.get("base", "")).startswith(str(EXT)) else str(example_cfg.get("base", "")),
            "run_script": example_cfg.get("run_script"),
        },
        "execution": {"mode": mode, "backend": backend, "host": socket.gethostname(),
                      **(environment or {})},
        "command": command if isinstance(command, (list, str)) else None,
        "resources": resources or {},
        "params": {"file": "params.yaml", "sha256": params_sha},
        "inputs": input_files(staged_example, edited),
        "edited_inputs": sorted((edited or {}).keys()),
        "code": code_versions(),
        "python": python_environment(),
    }
    record = strip_secrets(record)
    path = Path(run_dir) / PROVENANCE_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)
    return record


def summary(record: dict) -> dict:
    """The compact provenance block mirrored into the run manifest."""
    code = record.get("code") or {}
    return {
        "params_sha256": (record.get("params") or {}).get("sha256"),
        "edited_inputs": record.get("edited_inputs") or [],
        "cryolauncher_commit": (code.get("cryolauncher") or {}).get("commit"),
        "cryolauncher_local_changes": (code.get("cryolauncher") or {}).get("local_changes"),
        "icesee_upstream_commit": (code.get("icesee") or {}).get("upstream_commit"),
        "icesee_vendored_tree": (code.get("icesee") or {}).get("vendored_tree"),
        "environment": (record.get("execution") or {}).get("environment"),
        "image": (record.get("execution") or {}).get("image"),
    }


def load(run_dir: Path | str) -> dict | None:
    path = Path(run_dir) / PROVENANCE_FILE
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
