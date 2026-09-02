"""Content fingerprint of a run's *mutable inputs* (PASS 4, task 5).

The :class:`RunPlan` digest binds the **intent** (model, resource, parameters).
It only *names* the example and the datasets. Between approval and execution a
canonical example file, a sibling source file, or an uploaded dataset can
change. :class:`RunInputFingerprint` is a second binding — a single ``sha256``
over the *content* of those inputs — so an approval can additionally assert
"these exact files".

Cheap by construction (see ``overnight/AUDIT_agent_approval_integrity.md`` §2):

* the resolved ``run_target`` file: full ``sha256`` (always a small script);
* other source files in the example dir: ``(relpath, size, sha256)`` for text
  files under 256 KiB, capped at 200 files; larger/binary as ``(relpath, size)``;
* referenced datasets: ``(name, size, mtime_ns)`` plus ``sha256`` only when the
  file is ≤ 8 MiB.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_TEXT_SUFFIXES = frozenset({
    ".m", ".py", ".ipynb", ".jl", ".txt", ".md", ".yaml", ".yml", ".json",
    ".toml", ".cfg", ".ini", ".sh", ".par", ".dat", ".csv", ".tsv", ".in",
})
_PER_FILE_HASH_CAP = 256 * 1024          # source files larger than this: size only
_FILE_COUNT_CAP = 200
_DATASET_HASH_CAP = 8 * 1024 * 1024      # datasets larger than this: metadata only
_SKIP_DIRS = frozenset({".git", "__pycache__", "outputs", ".ipynb_checkpoints",
                        "figures", "results", "_modelrun_datasets", "data"})


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class RunInputFingerprint:
    run_target: dict = field(default_factory=dict)      # {"name", "sha256"|None}
    tree: list = field(default_factory=list)            # [[relpath, size, sha256|None], ...]
    datasets: list = field(default_factory=list)        # [[name, size, mtime_ns, sha256|None], ...]
    truncated: bool = False                             # file-count cap hit

    def _material(self) -> dict:
        return {
            "run_target": self.run_target,
            "tree": [list(row) for row in self.tree],
            "datasets": [list(row) for row in self.datasets],
            "truncated": self.truncated,
        }

    def digest(self) -> str:
        blob = json.dumps(self._material(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {**self._material(), "digest": self.digest()}

    @classmethod
    def from_dict(cls, d: dict) -> "RunInputFingerprint":
        return cls(
            run_target=dict(d.get("run_target") or {}),
            tree=[list(r) for r in (d.get("tree") or [])],
            datasets=[list(r) for r in (d.get("datasets") or [])],
            truncated=bool(d.get("truncated", False)),
        )

    def drift_from(self, other: "RunInputFingerprint") -> list[str]:
        """Human-readable list of what changed relative to ``other`` (the
        approved fingerprint). Empty == identical."""
        out: list[str] = []
        if self.run_target != other.run_target:
            out.append(f"run target {other.run_target.get('name')!r} changed")
        a = {row[0]: tuple(row[1:]) for row in other.tree}
        b = {row[0]: tuple(row[1:]) for row in self.tree}
        for name in sorted(set(a) | set(b)):
            if name not in a:
                out.append(f"source file added: {name}")
            elif name not in b:
                out.append(f"source file removed: {name}")
            elif a[name] != b[name]:
                out.append(f"source file changed: {name}")
        da = {row[0]: tuple(row[1:]) for row in other.datasets}
        db = {row[0]: tuple(row[1:]) for row in self.datasets}
        for name in sorted(set(da) | set(db)):
            if name not in da:
                out.append(f"dataset added: {name}")
            elif name not in db:
                out.append(f"dataset removed: {name}")
            elif da[name] != db[name]:
                out.append(f"dataset changed: {name}")
        return out


def fingerprint_inputs(example_dir: str | Path, *, run_target: str,
                       dataset_paths: list[Path] | None = None
                       ) -> RunInputFingerprint:
    """Walk ``example_dir`` (read-only) and the resolved dataset files."""
    root = Path(example_dir).expanduser().resolve()
    rt_name = Path(run_target or "").name
    rt: dict = {"name": rt_name, "sha256": None}
    tree: list = []
    truncated = False

    if root.is_dir():
        files: list[Path] = []
        for p in sorted(root.rglob("*")):
            if p.is_dir():
                continue
            if any(part in _SKIP_DIRS for part in p.relative_to(root).parts[:-1]):
                continue
            files.append(p)
        if len(files) > _FILE_COUNT_CAP:
            files = files[:_FILE_COUNT_CAP]
            truncated = True
        for p in files:
            rel = p.relative_to(root).as_posix()
            try:
                size = p.stat().st_size
            except OSError:
                continue
            digest = None
            if p.suffix.lower() in _TEXT_SUFFIXES and size <= _PER_FILE_HASH_CAP:
                try:
                    digest = _sha256_file(p)
                except OSError:
                    digest = None
            tree.append([rel, size, digest])
            if rel == rt_name or p.name == rt_name:
                rt["sha256"] = digest if digest is not None else _try_hash(p)
    elif root.is_file():
        rt = {"name": root.name, "sha256": _try_hash(root)}

    datasets: list = []
    for dp in sorted(dataset_paths or []):
        try:
            st = dp.stat()
        except OSError:
            datasets.append([dp.name, None, None, None])
            continue
        dhash = _try_hash(dp) if st.st_size <= _DATASET_HASH_CAP else None
        datasets.append([dp.name, st.st_size, st.st_mtime_ns, dhash])

    return RunInputFingerprint(run_target=rt, tree=tree, datasets=datasets,
                               truncated=truncated)


def _try_hash(path: Path) -> str | None:
    try:
        return _sha256_file(path)
    except OSError:
        return None
