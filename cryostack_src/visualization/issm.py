"""Deterministic ISSM visualization built on the neutral result package.

The result package (``cryostack_src.models.issm.results``) is the *only*
plotting interface -- ``md_final.mat`` is never parsed for plots. What gets
rendered is decided by solution type, field metadata, mesh topology, field
location and timestep availability -- never by the example name.

Public API
----------
* ``recommended_plots(pkg, solution=None)`` -- metadata-driven plot descriptions
* ``render_field(pkg, solution, field, timestep=None)`` -- a spatial map
* ``render_timeseries(pkg, solution, field)`` -- a scalar diagnostic vs time
* ``render_recommended(pkg, max_plots=...)`` -- render the recommended set

Every renderer returns a :class:`RenderResult`. Unsupported shapes come back
with ``ok=False`` and a human-readable ``reason`` -- they never raise into the
UI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from cryostack_src.models.issm.results import (
    ResultError, ResultPackage, preferred_order,
)

_DPI = 100
_FIGSIZE = (6.4, 5.0)


class _Unsupported(Exception):
    """Internal: a deterministic 'cannot plot this' with a clear reason."""


def _require_matplotlib():
    try:
        import matplotlib  # noqa: F401,PLC0415
    except ImportError as err:  # pragma: no cover - environment dependent
        raise _Unsupported(
            "matplotlib is not installed in this environment") from err


@dataclass(frozen=True)
class RenderResult:
    ok: bool
    solution: str
    field: str
    kind: str                       # "map" | "timeseries" | "unsupported"
    timestep: int | None
    path: Path | None
    caption: str
    reason: str | None = None

    @classmethod
    def unsupported(cls, solution: str, field: str, reason: str, *,
                    kind: str = "unsupported", timestep: int | None = None):
        return cls(ok=False, solution=solution, field=field, kind=kind,
                   timestep=timestep, path=None, caption="", reason=reason)


# ── filenames ─────────────────────────────────────────────────────────────
def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name)).strip("_") or "x"


def figure_name(solution: str, field: str, *, kind: str,
                timestep: int | None = None) -> str:
    """Deterministic cache filename for a render selection."""
    stem = f"{_safe(solution)}_{_safe(field)}"
    if kind == "timeseries":
        return f"{stem}_timeseries.png"
    if timestep is not None:
        return f"{stem}_t{int(timestep):03d}.png"
    return f"{stem}.png"


def _figures_dir(pkg: ResultPackage, outdir) -> Path:
    target = Path(outdir) if outdir is not None else (
        (pkg.outputs / "figures") if pkg.outputs is not None else None)
    if target is None:
        raise _Unsupported("no result directory to write the figure into")
    target.mkdir(parents=True, exist_ok=True)
    return target


# ── shared helpers ────────────────────────────────────────────────────────
def _guard_status(pkg: ResultPackage, solution: str, field: str):
    if pkg.status == "legacy":
        raise _Unsupported(
            "structured field visualization is unavailable for this legacy run")
    if pkg.status == "missing":
        raise _Unsupported("no structured result package for this run")
    if not pkg.is_readable():
        raise _Unsupported(f"result package is not readable (status: {pkg.status})")


def _field_info(pkg: ResultPackage, solution: str, field: str):
    try:
        return pkg.field_metadata(solution, field)
    except ResultError as err:
        raise _Unsupported(str(err)) from err


def _mesh_2d_triangular(pkg: ResultPackage):
    import numpy as np

    try:
        mesh = pkg.load_mesh()
    except ResultError as err:
        raise _Unsupported(str(err)) from err
    if int(mesh.get("dimension", 2)) != 2:
        raise _Unsupported(
            "3-D meshes are not supported by this visualization layer")
    elements = np.asarray(mesh.get("elements"))
    if elements.ndim != 2 or elements.shape[1] != 3:
        cols = elements.shape[1] if elements.ndim == 2 else "?"
        raise _Unsupported(
            f"only 2-D triangular meshes are supported (got {cols}-node elements)")
    return mesh


def _triangulation(mesh):
    import matplotlib.tri as mtri

    return mtri.Triangulation(mesh["x"], mesh["y"], mesh["elements"])


def _new_axes(title: str):
    from matplotlib.figure import Figure

    fig = Figure(figsize=_FIGSIZE, dpi=_DPI)
    ax = fig.add_subplot(111)
    ax.set_title(title)
    return fig, ax


def _resolve_timestep(sol, info, timestep):
    """Deterministic timestep selection: explicit if given & available,
    otherwise the final available timestep."""
    available = list(info.available_timesteps) if info.available_timesteps \
        else list(range(sol.timesteps))
    if not available:
        raise _Unsupported("field has no available timesteps")
    if timestep is None:
        return max(available)
    ts = int(timestep)
    if ts < 0:
        ts = sol.timesteps + ts
    if ts not in available:
        raise _Unsupported(
            f"timestep {ts} is not available for this field "
            f"(available: {available})")
    return ts


# ── field maps ────────────────────────────────────────────────────────────
def render_field(pkg: ResultPackage, solution: str, field: str,
                 timestep: int | None = None, *, outdir=None) -> RenderResult:
    """Spatial map of a nodal/elemental field (a single timestep for transient
    fields). A scalar diagnostic is redirected to :func:`render_timeseries`."""
    try:
        _guard_status(pkg, solution, field)
        _require_matplotlib()
        info = _field_info(pkg, solution, field)
        sol = pkg.solution(solution)

        if info.location == "scalar":
            if info.transient:
                return render_timeseries(pkg, solution, field, outdir=outdir)
            raise _Unsupported(
                "a static scalar diagnostic has no spatial map")
        if info.location not in ("nodal", "elemental"):
            raise _Unsupported(
                f"field location '{info.location}' cannot be mapped")

        mesh = _mesh_2d_triangular(pkg)
        import numpy as np

        ts = _resolve_timestep(sol, info, timestep) if info.transient else None
        values = np.asarray(pkg.load_field(solution, field, timestep=ts),
                            dtype="float64").reshape(-1)

        nv = int(mesh["numberofvertices"])
        ne = int(mesh["numberofelements"])
        if info.location == "nodal" and values.size != nv:
            raise _Unsupported(
                f"nodal field has {values.size} values but the mesh has {nv} "
                "vertices")
        if info.location == "elemental" and values.size != ne:
            raise _Unsupported(
                f"elemental field has {values.size} values but the mesh has "
                f"{ne} elements")
        if not np.isfinite(values).any():
            raise _Unsupported("field is entirely non-finite at this timestep")

        triang = _triangulation(mesh)
        step_txt = f" — timestep {ts + 1}/{sol.timesteps}" if ts is not None else ""
        fig, ax = _new_axes(f"{solution} · {field}{step_txt}")
        if info.location == "nodal":
            mappable = ax.tripcolor(triang, values, shading="gouraud")
        else:
            mappable = ax.tripcolor(triang, facecolors=values)
        ax.set_aspect("equal")
        ax.set_xlabel("x")
        ax.set_ylabel("y")
        fig.colorbar(mappable, ax=ax)

        out = _figures_dir(pkg, outdir) / figure_name(
            solution, field, kind="map", timestep=ts)
        fig.savefig(out, format="png", bbox_inches="tight")

        finite = values[np.isfinite(values)]
        caption = (
            f"{field}\n{info.location} · {values.size:,} values"
            + (f" · timestep {ts + 1}/{sol.timesteps}" if ts is not None else "")
            + f" · range [{finite.min():.3g}, {finite.max():.3g}]"
        )
        return RenderResult(ok=True, solution=solution, field=field, kind="map",
                            timestep=ts, path=out, caption=caption)
    except _Unsupported as err:
        return RenderResult.unsupported(solution, field, str(err), kind="map",
                                        timestep=timestep)


# ── scalar time series ────────────────────────────────────────────────────
def render_timeseries(pkg: ResultPackage, solution: str, field: str, *,
                      outdir=None) -> RenderResult:
    """Line plot of a transient scalar diagnostic against time (or step)."""
    try:
        _guard_status(pkg, solution, field)
        _require_matplotlib()
        info = _field_info(pkg, solution, field)
        sol = pkg.solution(solution)

        if not info.transient:
            raise _Unsupported("field is static -- there is no series to plot")
        if info.location != "scalar":
            raise _Unsupported(
                f"a time series needs a scalar diagnostic; '{field}' is a "
                f"{info.location} field -- use render_field for a timestep map")

        import numpy as np

        series = np.asarray(pkg.load_field(solution, field),
                            dtype="float64").reshape(-1)
        times = pkg.times(solution)
        if times is not None and len(times) == series.size:
            xs, xlabel = np.asarray(times, dtype="float64"), "time"
        else:
            xs, xlabel = np.arange(series.size, dtype="float64"), "timestep"

        finite = np.isfinite(series)
        if not finite.any():
            raise _Unsupported("series is entirely non-finite")

        fig, ax = _new_axes(f"{solution} · {field}")
        ax.plot(xs[finite], series[finite], marker="o", ms=3)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(field)
        ax.grid(True, alpha=0.3)

        out = _figures_dir(pkg, outdir) / figure_name(
            solution, field, kind="timeseries")
        fig.savefig(out, format="png", bbox_inches="tight")

        caption = f"{field}\nscalar · {series.size} timesteps"
        return RenderResult(ok=True, solution=solution, field=field,
                            kind="timeseries", timestep=None, path=out,
                            caption=caption)
    except _Unsupported as err:
        return RenderResult.unsupported(solution, field, str(err),
                                        kind="timeseries")


# ── recommendations ───────────────────────────────────────────────────────
def recommended_plots(result_package: ResultPackage,
                      solution: str | None = None) -> list[dict]:
    """Metadata-driven plot descriptions (renders nothing)."""
    if result_package.status in ("legacy", "missing"):
        return []
    return result_package.recommended_plots(solution)


def render_recommended(result_package: ResultPackage, max_plots: int = 6, *,
                       outdir=None) -> list[RenderResult]:
    """Render the recommended plot set, in preference order, capped at
    ``max_plots``. Failures are included with ``ok=False``."""
    out: list[RenderResult] = []
    for rec in recommended_plots(result_package)[:max_plots]:
        if rec["kind"] == "timeseries":
            out.append(render_timeseries(
                result_package, rec["solution"], rec["field"], outdir=outdir))
        else:
            out.append(render_field(
                result_package, rec["solution"], rec["field"],
                timestep=rec.get("timestep"), outdir=outdir))
    return out


__all__ = [
    "RenderResult", "figure_name", "preferred_order", "recommended_plots",
    "render_field", "render_recommended", "render_timeseries",
]
