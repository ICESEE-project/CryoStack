"""Backend-neutral reader for a CryoStack Icepack result package.

Reads the package written by the container-side exporter
(:mod:`cryostack_src.models.icepack.export`):

    outputs/metadata.json         schema "cryostack.icepack.results", v2
    outputs/mesh/mesh.h5          /x /y /elements  (2-D triangular, 0-based)
    outputs/fields/icepack/<f>.h5 /values  (+ /values_y /magnitude for vectors)

Needs neither Firedrake nor icepack -- the exporter has already interpolated
every field to CG1 and written plain arrays. Deterministic plotting lives in
:mod:`cryostack_src.visualization.icepack`.

``status``:
  ``missing``   -- no ``outputs/`` directory
  ``ok``        -- structured fields present (``is_readable()`` is True)
  ``artifacts`` -- figures / native files only, no structured fields
  ``empty``     -- the run produced nothing collectable
  ``unsupported_geometry`` / ``export_failed`` -- the exporter said so
  ``legacy``    -- an ``outputs/`` tree with no recognisable metadata
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cryostack_src.models.results_common import (
    find_outputs_dir,
    legacy_artifacts,
    list_figures,
    read_metadata,
)

SCHEMA = "cryostack.icepack.results"

#: the single synthetic "solution" name -- Icepack has no ISSM-style solution
#: taxonomy, but the shared Results panel keys off solution -> field -> timestep,
#: so a readable package presents its fields under one solution.
SOLUTION = "icepack"

#: surfacing order when a run exports several fields
_FIELD_ORDER = ("velocity", "thickness", "surface", "bed", "accumulation",
                "log_fluidity", "damage")


class ResultError(RuntimeError):
    """A requested field / mesh could not be read."""


@dataclass(frozen=True)
class FieldInfo:
    """Compatible with the shared Results panel's use of ISSM ``FieldInfo``
    (``.location`` / ``.transient`` / ``.available_timesteps``)."""
    name: str
    solution: str
    location: str                       # "nodal" for tier-1 Icepack
    rank: str                           # "scalar" | "vector"
    transient: bool                     # always False for tier 1
    path: str
    units: str | None = None
    exported_space: str | None = None
    source_space: str | None = None
    linearised: bool = False
    available_timesteps: tuple[int, ...] | None = None
    components: tuple[str, ...] = ()


class IcepackResultPackage:
    """A read-only view of one Icepack run's exported results."""

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

    def _fields_meta(self) -> list[dict]:
        return list(self._meta.get("fields") or [])

    @property
    def status(self) -> str:
        if self.outputs is None:
            return "missing"
        if self._meta.get("schema") == SCHEMA:
            declared = self._meta.get("status")
            if declared in ("ok", "empty", "unsupported_geometry", "export_failed"):
                return declared
            if declared:
                return declared
        if self._fields_meta() and (self.outputs / "mesh" / "mesh.h5").is_file():
            return "ok"
        model_dir = self.outputs / "model"
        has_native = model_dir.is_dir() and any(model_dir.iterdir())
        if list_figures(self.outputs) or has_native:
            return "artifacts"
        return "legacy"

    def is_readable(self) -> bool:
        return bool(
            self.outputs is not None
            and self._fields_meta()
            and (self.outputs / "mesh" / "mesh.h5").is_file()
        )

    # -- structured access ------------------------------------------------
    def available_solutions(self) -> list[str]:
        return [SOLUTION] if self.is_readable() else []

    def available_fields(self, solution: str = SOLUTION, *, preferred: bool = True) -> list[str]:
        names = [f["name"] for f in self._fields_meta()]
        if not preferred:
            return names
        idx = {n: i for i, n in enumerate(_FIELD_ORDER)}
        return sorted(names, key=lambda n: (idx.get(n, len(idx)), names.index(n)))

    def field_metadata(self, solution_or_field: str, field: str | None = None) -> FieldInfo:
        """``field_metadata("icepack", "thickness")`` (shared-panel call order)
        or ``field_metadata("thickness")``."""
        name = field if field is not None else solution_or_field
        for f in self._fields_meta():
            if f["name"] == name:
                return FieldInfo(
                    name=name, solution=SOLUTION,
                    location=f.get("location", "nodal"),
                    rank=f.get("rank", "scalar"),
                    transient=bool(f.get("timestep") is not None
                                   or f.get("available_timesteps")),
                    path=f.get("path", f"fields/icepack/{name}.h5"),
                    units=f.get("units"),
                    exported_space=f.get("exported_space"),
                    source_space=f.get("source_space"),
                    linearised=bool(f.get("linearised")),
                    available_timesteps=(
                        tuple(f["available_timesteps"])
                        if f.get("available_timesteps") else None
                    ),
                    components=tuple(f.get("components", ())),
                )
        raise ResultError(f"no exported field {name!r}")

    def timesteps(self, solution: str = SOLUTION) -> list[int]:
        return [0]                    # tier 1: final state only

    def times(self, solution: str = SOLUTION):
        return None

    # -- data -----------------------------------------------------------
    def load_mesh(self) -> dict:
        self._require_readable()
        import numpy as np
        h5py = _h5py()
        path = self.outputs / "mesh" / "mesh.h5"
        with h5py.File(path, "r") as fh:
            x = np.asarray(fh["x"][()]).reshape(-1)
            y = np.asarray(fh["y"][()]).reshape(-1)
            el = np.asarray(fh["elements"][()]).astype("int64")
        return {
            "x": x, "y": y, "z": np.zeros_like(x),
            "elements": el,
            "numberofvertices": int(len(x)),
            "numberofelements": int(len(el)),
            "dimension": 2,
            "element_columns": el.shape[1] if el.ndim == 2 else 0,
            "connectivity_indexing": "0-based",
        }

    def load_field(self, field: str, timestep: int | None = None, *, solution: str = SOLUTION):
        """Return the CG1 nodal values for ``field``. For a vector field returns
        ``(values_x, values_y)``; a magnitude is available via
        :meth:`load_field_magnitude`."""
        self._require_readable()
        import numpy as np
        h5py = _h5py()
        info = self.field_metadata(field)
        path = self.outputs / info.path
        if not path.is_file():
            raise ResultError(f"field data not found: {path}")
        with h5py.File(path, "r") as fh:
            vx = np.asarray(fh["values"][()]).reshape(-1)
            if info.rank == "vector":
                vy = np.asarray(fh["values_y"][()]).reshape(-1)
                return vx, vy
            return vx

    def load_field_magnitude(self, field: str, *, solution: str = SOLUTION):
        self._require_readable()
        import numpy as np
        h5py = _h5py()
        info = self.field_metadata(field)
        path = self.outputs / info.path
        with h5py.File(path, "r") as fh:
            if "magnitude" in fh:
                return np.asarray(fh["magnitude"][()]).reshape(-1)
            v = self.load_field(field)
            return np.hypot(*v) if isinstance(v, tuple) else np.abs(v)

    # -- recommendations ------------------------------------------------
    def recommended_plots(self, solution: str | None = None) -> list[dict]:
        if not self.is_readable():
            return []
        out = []
        for name in self.available_fields():
            info = self.field_metadata(name)
            out.append({
                "solution": SOLUTION, "field": name,
                "kind": "map", "location": "nodal",
                "rank": info.rank,
                "transient": False, "timestep": None,
            })
        return out

    # -- figures / native artifacts ---------------------------------------
    def figures(self) -> list[Path]:
        return list_figures(self.outputs)

    def model_mat(self) -> Path | None:
        return None

    def legacy_artifacts(self) -> dict:
        return legacy_artifacts(self.outputs, model_mat_name=None)

    def skipped_files(self) -> list[dict]:
        return list(self._meta.get("skipped") or [])

    # -- internals ----------------------------------------------------------
    def _require_readable(self) -> None:
        if not self.is_readable():
            raise ResultError(
                f"no structured Icepack result package under {self.root} "
                f"(status: {self.status})"
            )


def discover_results(path: str | Path) -> IcepackResultPackage:
    """Locate and describe an Icepack run's results. Never raises for a missing
    / partial directory -- inspect :attr:`IcepackResultPackage.status`."""
    root = Path(path)
    outputs = find_outputs_dir(root)
    return IcepackResultPackage(
        root=root, outputs=outputs, metadata=read_metadata(outputs),
    )


def _h5py():
    try:
        import h5py
    except ImportError as err:  # pragma: no cover
        raise ResultError("reading Icepack result arrays needs h5py") from err
    return h5py
