"""Backend-neutral reader for a CryoStack Icepack result package.

Scope note (deliberate): Icepack results are Firedrake ``Function`` objects on a
Firedrake function space. A model-aware structured export (field/DOF/mesh
semantics, transient representation, a "recommended plots" ordering) is a
pending scientific decision -- see ``overnight/AGENT_TRAIL.md`` §B "Needs a
scientific decision". Until that is made, this reader deliberately does **not**
invent a solution/field taxonomy. It reports:

* ``status == "missing"``   -- no ``outputs/`` directory
* ``status == "artifacts"`` -- ``outputs/`` with figures / native files the run
                               produced (collected by
                               :mod:`cryostack_src.models.icepack.postprocess`)
* ``status == "empty"``     -- an ``outputs/`` package that produced nothing
* ``status == "legacy"``    -- an ``outputs/`` tree with no recognisable metadata

``is_readable()`` is always ``False`` here (there is no structured field reader
yet), so the Results panel shows the collected figures and native artifacts and
disables the solution/field selectors -- honestly, without fabrication.
"""
from __future__ import annotations

from pathlib import Path

from cryostack_src.models.results_common import (
    find_outputs_dir,
    legacy_artifacts,
    list_figures,
    read_metadata,
)

SCHEMA = "cryostack.icepack.results"


class IcepackResultPackage:
    """A read-only view of one Icepack run's collected outputs."""

    def __init__(self, *, root: Path, outputs: Path | None, metadata: dict) -> None:
        self.root = Path(root)
        self.outputs = outputs
        self._meta = metadata or {}

    # -- top level -----------------------------------------------------------
    @property
    def schema(self) -> str | None:
        return self._meta.get("schema")

    @property
    def version(self) -> int | None:
        return self._meta.get("version")

    @property
    def model(self) -> str | None:
        return self._meta.get("model") or ("icepack" if self.outputs is not None else None)

    @property
    def metadata(self) -> dict:
        return dict(self._meta)

    @property
    def status(self) -> str:
        if self.outputs is None:
            return "missing"
        if self._meta.get("schema") == SCHEMA:
            return self._meta.get("status") or "artifacts"
        model_dir = self.outputs / "model"
        has_native = model_dir.is_dir() and any(model_dir.iterdir())
        if list_figures(self.outputs) or has_native:
            return "artifacts"
        return "legacy"

    def is_readable(self) -> bool:
        """No structured Icepack field reader exists yet -- always ``False``."""
        return False

    # -- structured access (deliberately empty until the science is decided) --
    def available_solutions(self) -> list[str]:
        return []

    def available_fields(self, solution: str, *, preferred: bool = True) -> list[str]:
        return []

    def timesteps(self, solution: str) -> list[int]:
        return []

    def recommended_plots(self, solution: str | None = None) -> list[dict]:
        return []

    # -- figures / native artifacts ---------------------------------------
    def figures(self) -> list[Path]:
        return list_figures(self.outputs)

    def model_mat(self) -> Path | None:
        return None

    def legacy_artifacts(self) -> dict:
        return legacy_artifacts(self.outputs, model_mat_name=None)

    def skipped_files(self) -> list[dict]:
        return list(self._meta.get("skipped") or [])


def discover_results(path: str | Path) -> IcepackResultPackage:
    """Locate and describe an Icepack run's collected outputs. Never raises for a
    missing / partial directory -- inspect :attr:`IcepackResultPackage.status`."""
    root = Path(path)
    outputs = find_outputs_dir(root)
    return IcepackResultPackage(
        root=root, outputs=outputs, metadata=read_metadata(outputs),
    )
