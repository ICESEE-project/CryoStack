"""Deterministic Icepack visualization on the neutral result package.

The exporter (:mod:`cryostack_src.models.icepack.export`) has already
interpolated every field to CG1 and written plain ``/x /y /elements`` +
``/values`` HDF5 in the ISSM on-disk shape, so this renderer is a thin
``matplotlib.tri`` layer -- no Firedrake, no ``icepack``.

Public API (mirrors :mod:`cryostack_src.visualization.issm` so
``WorkspaceManager`` drives both through the same calls):

* ``recommended_plots(pkg, solution=None)``
* ``render_field(pkg, solution, field, timestep=None, outdir=None)``  -- a map
* ``render_timeseries(pkg, solution, field, outdir=None)`` -- N/A for tier 1
* ``render_recommended(pkg, max_plots=...)``
"""
from __future__ import annotations

from pathlib import Path

# reuse the shared result dataclass + deterministic cache-name helper
from cryostack_src.visualization.issm import RenderResult, figure_name

_DPI = 100
_FIGSIZE = (6.4, 5.0)


class _Unsupported(Exception):
    pass


def _require_matplotlib():
    try:
        import matplotlib  # noqa: F401
    except ImportError as err:  # pragma: no cover
        raise _Unsupported("matplotlib is not installed") from err


def _figures_dir(pkg, outdir) -> Path:
    target = Path(outdir) if outdir is not None else (
        (pkg.outputs / "figures") if pkg.outputs is not None else None)
    if target is None:
        raise _Unsupported("no result directory to write the figure into")
    target.mkdir(parents=True, exist_ok=True)
    return target


def recommended_plots(pkg, solution=None) -> list[dict]:
    return pkg.recommended_plots(solution)


def render_field(pkg, solution: str, field: str, timestep=None, *, outdir=None) -> RenderResult:
    """A spatial map of a CG1 nodal Icepack field (scalar -> tripcolor;
    vector -> speed map + a light quiver overlay). Never raises into the UI."""
    try:
        if not pkg.is_readable():
            raise _Unsupported(
                f"result package is not readable (status: {pkg.status})")
        _require_matplotlib()
        import numpy as np
        import matplotlib.tri as mtri
        from matplotlib.figure import Figure

        try:
            info = pkg.field_metadata(field)
        except Exception as err:
            raise _Unsupported(str(err)) from err

        mesh = pkg.load_mesh()
        elements = np.asarray(mesh["elements"])
        if int(mesh.get("dimension", 2)) != 2 or elements.ndim != 2 or elements.shape[1] != 3:
            raise _Unsupported("only 2-D triangular meshes are supported")
        nv = int(mesh["numberofvertices"])
        triang = mtri.Triangulation(np.asarray(mesh["x"]), np.asarray(mesh["y"]), elements)

        rank = getattr(info, "rank", "scalar")
        loaded = pkg.load_field(field)
        if rank == "vector":
            vx, vy = loaded
            values = np.hypot(np.asarray(vx, float), np.asarray(vy, float)).reshape(-1)
        else:
            values = np.asarray(loaded, float).reshape(-1)

        if values.size != nv:
            raise _Unsupported(
                f"field has {values.size} values but the mesh has {nv} vertices")
        finite = np.isfinite(values)
        if not finite.any():
            raise _Unsupported("field is entirely non-finite")
        n_masked = int((~finite).sum())
        if n_masked:
            triang.set_mask(~finite[elements].all(axis=1))

        fin = values[finite]
        vmin, vmax = float(fin.min()), float(fin.max())
        clim = {"vmin": vmin, "vmax": vmax} if vmin != vmax else {}

        fig = Figure(figsize=_FIGSIZE, dpi=_DPI)
        ax = fig.add_subplot(111)
        units = getattr(info, "units", None)
        ax.set_title(f"{field}" + (f"  [{units}]" if units else ""))
        mappable = ax.tripcolor(
            triang, np.where(finite, values, vmin), shading="gouraud", **clim)
        if rank == "vector":
            # sparse quiver so the direction is visible without clutter
            step = max(1, nv // 400)
            xs = np.asarray(mesh["x"])[::step]
            ys = np.asarray(mesh["y"])[::step]
            ax.quiver(xs, ys,
                      np.asarray(vx, float)[::step], np.asarray(vy, float)[::step],
                      color="k", alpha=0.35, width=0.002, scale=None)
        ax.set_aspect("equal")
        ax.set_xlabel("x")
        ax.set_ylabel("y")
        fig.colorbar(mappable, ax=ax)

        out = _figures_dir(pkg, outdir) / figure_name(
            solution or "icepack", field, kind="map")
        fig.savefig(out, format="png", bbox_inches="tight")

        caption = (
            f"{field}"
            + (f" ({rank})" if rank != "scalar" else "")
            + f" · {values.size:,} nodes · range [{vmin:.3g}, {vmax:.3g}]"
            + (f" · {n_masked:,} masked" if n_masked else "")
            + (f" · {units}" if units else "")
            + (" · linearised to CG1" if getattr(info, "linearised", False) else "")
        )
        return RenderResult(ok=True, solution=solution or "icepack", field=field,
                            kind="map", timestep=None, path=out, caption=caption)
    except _Unsupported as err:
        return RenderResult.unsupported(solution or "icepack", field, str(err))
    except Exception as err:  # pragma: no cover - defensive
        return RenderResult.unsupported(
            solution or "icepack", field, f"render failed: {type(err).__name__}: {err}")


def render_timeseries(pkg, solution: str, field: str, *, outdir=None) -> RenderResult:
    return RenderResult.unsupported(
        solution or "icepack", field,
        "Icepack tier-1 export is final-state only; no scalar time series",
        kind="timeseries")


def render_recommended(pkg, max_plots: int = 6, *, outdir=None) -> list[RenderResult]:
    out: list[RenderResult] = []
    for desc in recommended_plots(pkg)[:max_plots]:
        out.append(render_field(pkg, desc.get("solution", "icepack"), desc["field"],
                                outdir=outdir))
    return out
