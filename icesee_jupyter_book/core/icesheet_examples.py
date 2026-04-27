# icesee_jupyter_book/core/icesheet_examples.py
from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


# ============================================================
# Native ice-sheet example discovery
#
# This file is intentionally separate from example_registry.py.
# example_registry.py is for ICESEE-coupled workflows.
# This file is for direct ice-sheet model examples only.
#
# Models supported here:
#   - ISSM
#   - Icepack
#
# Discovery goals:
#   - Basic mode: automatically discover and present native examples
#   - Advanced mode: provide enough metadata to open/edit/deploy examples
#
# The source-of-truth locations are expected to be:
#   - ISSM/examples
#   - icepack/notebooks/tutorials
#   - icepack/notebooks/how-to
# ============================================================


# ------------------------------------------------------------
# Data model
# ------------------------------------------------------------
@dataclass(frozen=True)
class IcesheetExample:
    model_name: str                  # "issm" | "icepack"
    label: str                       # UI label
    path: Path                       # absolute local path
    kind: str                        # "directory" | "notebook"
    category: str                    # e.g. "examples", "tutorials", "how-to"
    beginner_friendly: bool          # Basic mode prioritization
    description: str = ""            # optional short description
    entrypoint: str | None = None    # e.g. "runme.m" for ISSM
    editable: bool = True            # Advanced mode can edit/deploy
    source_root: Path | None = None  # native model root if known

    def to_dict(self) -> dict:
        data = asdict(self)
        data["path"] = str(self.path)
        if self.source_root is not None:
            data["source_root"] = str(self.source_root)
        return data


# ------------------------------------------------------------
# Public API
# ------------------------------------------------------------
def discover_all_icesheet_examples(
    issm_root: str | Path | None = None,
    icepack_root: str | Path | None = None,
) -> dict[str, list[IcesheetExample]]:
    """
    Discover all supported native model examples.

    Returns:
        {
            "issm": [...],
            "icepack": [...],
        }
    """
    return {
        "issm": discover_issm_examples(issm_root=issm_root),
        "icepack": discover_icepack_examples(icepack_root=icepack_root),
    }


def discover_examples_for_model(
    model_name: str,
    issm_root: str | Path | None = None,
    icepack_root: str | Path | None = None,
) -> list[IcesheetExample]:
    model = (model_name or "").strip().lower()
    if model == "issm":
        return discover_issm_examples(issm_root=issm_root)
    if model == "icepack":
        return discover_icepack_examples(icepack_root=icepack_root)
    return []


def enabled_icesheet_example_labels(
    model_name: str,
    issm_root: str | Path | None = None,
    icepack_root: str | Path | None = None,
) -> list[str]:
    return [
        ex.label
        for ex in discover_examples_for_model(
            model_name=model_name,
            issm_root=issm_root,
            icepack_root=icepack_root,
        )
    ]


def examples_as_dropdown_options(
    model_name: str,
    issm_root: str | Path | None = None,
    icepack_root: str | Path | None = None,
    beginner_first: bool = True,
) -> list[tuple[str, str]]:
    """
    Return widget-friendly dropdown options:
        [(label, absolute_path_string), ...]
    """
    examples = discover_examples_for_model(
        model_name=model_name,
        issm_root=issm_root,
        icepack_root=icepack_root,
    )
    examples = sort_examples(examples, beginner_first=beginner_first)
    return [(ex.label, str(ex.path)) for ex in examples]


def find_example_by_path(
    model_name: str,
    selected_path: str | Path,
    issm_root: str | Path | None = None,
    icepack_root: str | Path | None = None,
) -> IcesheetExample | None:
    target = Path(selected_path).expanduser().resolve()
    for ex in discover_examples_for_model(
        model_name=model_name,
        issm_root=issm_root,
        icepack_root=icepack_root,
    ):
        try:
            if ex.path.resolve() == target:
                return ex
        except Exception:
            if str(ex.path) == str(target):
                return ex
    return None


def sort_examples(
    examples: Iterable[IcesheetExample],
    beginner_first: bool = True,
) -> list[IcesheetExample]:
    items = list(examples)

    def key(ex: IcesheetExample):
        priority = 0 if ex.beginner_friendly else 1
        if not beginner_first:
            priority = 0
        return (priority, ex.category.lower(), ex.label.lower())

    return sorted(items, key=key)


def example_summary_text(example: IcesheetExample | None) -> str:
    if example is None:
        return "No example selected."

    lines = [
        f"Model: {example.model_name.upper()}",
        f"Label: {example.label}",
        f"Type: {example.kind}",
        f"Category: {example.category}",
        f"Path: {example.path}",
    ]
    if example.entrypoint:
        lines.append(f"Entrypoint: {example.entrypoint}")
    if example.description:
        lines.append(f"Description: {example.description}")
    return "\n".join(lines)


# ------------------------------------------------------------
# ISSM discovery
# ------------------------------------------------------------
def discover_issm_examples(
    issm_root: str | Path | None = None,
) -> list[IcesheetExample]:
    """
    Discover native ISSM examples.

    Expected layout:
        <ISSM_ROOT>/examples/<example_name>/

    Discovery rule:
      - every directory under ISSM/examples is considered an example candidate
      - if runme.m exists, it is treated as the preferred entrypoint
      - Basic mode can still show directories without runme.m, but ones with
        runme.m are more naturally runnable
    """
    root = resolve_issm_root(issm_root)
    if root is None:
        return []

    examples_root = root / "examples"
    if not examples_root.exists() or not examples_root.is_dir():
        return []

    discovered: list[IcesheetExample] = []

    for item in sorted(examples_root.iterdir(), key=lambda p: p.name.lower()):
        if not item.is_dir():
            continue

        runme = item / "runme.m"
        entrypoint = "runme.m" if runme.exists() else None

        discovered.append(
            IcesheetExample(
                model_name="issm",
                label=item.name,
                path=item.resolve(),
                kind="directory",
                category="examples",
                beginner_friendly=_is_beginner_issm_example(item.name),
                description=_guess_issm_description(item.name, has_runme=runme.exists()),
                entrypoint=entrypoint,
                editable=True,
                source_root=root.resolve(),
            )
        )

    return discovered


# ------------------------------------------------------------
# Icepack discovery
# ------------------------------------------------------------
def discover_icepack_examples(
    icepack_root: str | Path | None = None,
) -> list[IcesheetExample]:
    """
    Discover native Icepack notebook examples.

    Expected layout:
        <ICEPACK_ROOT>/notebooks/tutorials/*.ipynb
        <ICEPACK_ROOT>/notebooks/how-to/*.ipynb

    Basic mode should prioritize tutorials.
    Advanced mode can expose both tutorials and how-to notebooks.
    """
    root = resolve_icepack_root(icepack_root)
    if root is None:
        return []

    notebooks_root = root / "notebooks"
    if not notebooks_root.exists() or not notebooks_root.is_dir():
        return []

    discovered: list[IcesheetExample] = []

    tutorial_dir = notebooks_root / "tutorials"
    howto_dir = notebooks_root / "how-to"

    for nb in _iter_notebooks(tutorial_dir):
        discovered.append(
            IcesheetExample(
                model_name="icepack",
                label=f"Tutorial / {humanize_name(nb.stem)}",
                path=nb.resolve(),
                kind="notebook",
                category="tutorials",
                beginner_friendly=True,
                description=_guess_icepack_description(nb.stem, category="tutorials"),
                entrypoint=nb.name,
                editable=True,
                source_root=root.resolve(),
            )
        )

    for nb in _iter_notebooks(howto_dir):
        discovered.append(
            IcesheetExample(
                model_name="icepack",
                label=f"How-to / {humanize_name(nb.stem)}",
                path=nb.resolve(),
                kind="notebook",
                category="how-to",
                beginner_friendly=False,
                description=_guess_icepack_description(nb.stem, category="how-to"),
                entrypoint=nb.name,
                editable=True,
                source_root=root.resolve(),
            )
        )

    return discovered


# ------------------------------------------------------------
# Root resolution
# ------------------------------------------------------------
def resolve_issm_root(issm_root: str | Path | None = None) -> Path | None:
    """
    Resolve ISSM source root using:
      1. explicit argument
      2. ISSM_DIR env var
      3. common local guesses
    """
    candidates = []

    if issm_root:
        candidates.append(Path(issm_root).expanduser())

    env_issm = os.environ.get("ISSM_DIR", "").strip()
    if env_issm:
        candidates.append(Path(env_issm).expanduser())

    candidates.extend(_common_issm_root_guesses())

    return _first_valid_root(candidates, required_child="examples")


def resolve_icepack_root(icepack_root: str | Path | None = None) -> Path | None:
    """
    Resolve Icepack source root using:
      1. explicit argument
      2. ICEPACK_ROOT env var
      3. import-based package location when available
      4. common local guesses
    """
    candidates = []

    if icepack_root:
        candidates.append(Path(icepack_root).expanduser())

    env_icepack = os.environ.get("ICEPACK_ROOT", "").strip()
    if env_icepack:
        candidates.append(Path(env_icepack).expanduser())

    pkg_root = _try_import_icepack_root()
    if pkg_root is not None:
        candidates.append(pkg_root)

    candidates.extend(_common_icepack_root_guesses())

    return _first_valid_root(candidates, required_child="notebooks")


# ------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------
def _iter_notebooks(directory: Path) -> list[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted(
        [p for p in directory.glob("*.ipynb") if p.is_file()],
        key=lambda p: p.name.lower(),
    )


def _first_valid_root(candidates: Iterable[Path], required_child: str) -> Path | None:
    seen: set[str] = set()

    for raw in candidates:
        try:
            p = raw.expanduser().resolve()
        except Exception:
            p = raw.expanduser()

        key = str(p)
        if key in seen:
            continue
        seen.add(key)

        if p.exists() and p.is_dir() and (p / required_child).exists():
            return p

    return None


def _common_issm_root_guesses() -> list[Path]:
    home = Path.home()
    cwd = Path.cwd()

    return [
        cwd / "ISSM",
        cwd / "issm",
        home / "ISSM",
        home / "issm",
        home / "src" / "ISSM",
        home / "src" / "issm",
        Path("/opt/ISSM"),
        Path("/opt/issm"),
    ]


def _common_icepack_root_guesses() -> list[Path]:
    home = Path.home()
    cwd = Path.cwd()

    return [
        cwd / "icepack",
        cwd / "Icepack",
        home / "icepack",
        home / "Icepack",
        home / "src" / "icepack",
        home / "src" / "Icepack",
        Path("/opt/icepack"),
        Path("/opt/Icepack"),
    ]


def _try_import_icepack_root() -> Path | None:
    try:
        import icepack  # type: ignore
    except Exception:
        return None

    try:
        module_path = Path(icepack.__file__).resolve()
    except Exception:
        return None

    # The installed package path may not be the source repo root.
    # Walk up a little and look for notebooks/.
    for parent in [module_path.parent, *module_path.parents[:6]]:
        if (parent / "notebooks").exists():
            return parent
    return None


def _is_beginner_issm_example(name: str) -> bool:
    n = name.strip().lower()
    beginner_keywords = (
        "ismip",
        "test",
        "tutorial",
        "demo",
        "hom",
    )
    return any(k in n for k in beginner_keywords)


def _guess_issm_description(name: str, has_runme: bool) -> str:
    base = f"Native ISSM example: {name}."
    if has_runme:
        return f"{base} Includes runme.m for direct example execution."
    return base


def _guess_icepack_description(stem: str, category: str) -> str:
    prefix = "Icepack tutorial notebook" if category == "tutorials" else "Icepack how-to notebook"
    return f"{prefix}: {humanize_name(stem)}."


def humanize_name(name: str) -> str:
    text = name.replace("_", " ").replace("-", " ").strip()
    return " ".join(word.capitalize() if word.islower() else word for word in text.split())