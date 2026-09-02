"""Container-side structured export for Icepack runs (I3).

Icepack tutorial notebooks display figures inline and write nothing to disk when
run headless (see ``overnight/AUDIT_icepack_results.md``). To get a structured
result we must run a Firedrake step inside the ``with-icepack`` container, after
the example's script, and pull the final ``Function`` objects out of its
namespace.

This module is written to the run directory as ``cryostack_icepack_export.py``
and invoked as::

    python -c "import runpy, sys; sys.path.insert(0, RUN_DIR);
              ns = runpy.run_path(SCRIPT, run_name='__main__');
              import cryostack_icepack_export as e; e.export(ns, RUN_DIR)"

so the example runs exactly once and its module globals are available to
:func:`export`.

Deliberately conservative (tier 1): only a fixed allow-list of scientifically
named 2-D scalar/vector nodal fields, final state, on a non-extruded triangular
mesh. Everything is interpolated to **CG1** for a zero-dependency reader
(`matplotlib.tri` + `h5py`, no Firedrake) — the same trade-off VTK output makes;
``linearised: true`` is recorded. Unknown / non-Function / extruded / 1-D / 3-D
cases are skipped and recorded, never guessed. **Non-fatal**: any failure here
writes an honest ``status`` and returns; it never raises into the run.

The Python reader for this package is
:mod:`cryostack_src.models.icepack.results` — it needs neither Firedrake nor
icepack.
"""
from __future__ import annotations

SCHEMA = "cryostack.icepack.results"
EXPORT_VERSION = 2

#: exported field name -> candidate namespace variable names (first hit wins),
#: rank, and hard-coded units from the upstream notebook colorbar/label text
#: (see AUDIT_icepack_results.md §1). ``None`` units = unstated in the notebooks.
_FIELD_ALLOWLIST: tuple[tuple[str, tuple[str, ...], str, str | None], ...] = (
    ("thickness",    ("thickness", "h"),                 "scalar", "meters"),
    ("velocity",     ("velocity", "u"),                  "vector", "meters/year"),
    ("surface",      ("surface", "s"),                   "scalar", "meters above sea level"),
    ("bed",          ("bed", "b", "z_b"),                "scalar", "meters above sea level"),
    ("accumulation", ("accumulation", "a"),              "scalar", "meters/year"),
    ("log_fluidity", ("log_fluidity", "theta", "θ"), "scalar", "dimensionless"),
    ("damage",       ("damage", "D"),                    "scalar", "dimensionless"),
)


def _is_firedrake_function(obj) -> bool:
    """Duck-typed: a Firedrake Function has ``function_space`` and ``dat``."""
    return hasattr(obj, "function_space") and hasattr(obj, "dat") and callable(
        getattr(obj, "function_space", None)
    )


def export(namespace: dict, run_dir: str) -> dict:
    """Write ``<run_dir>/outputs/{metadata.json, mesh/mesh.h5,
    fields/icepack/<name>.h5}`` from the Icepack script's ``namespace``.
    Returns the metadata dict. Never raises."""
    import json
    import os
    import time
    import traceback

    outputs = os.path.join(run_dir, "outputs")
    for sub in ("mesh", "fields/icepack", "figures", "model"):
        os.makedirs(os.path.join(outputs, sub), exist_ok=True)

    meta: dict = {
        "schema": SCHEMA,
        "version": EXPORT_VERSION,
        "model": "icepack",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "solutions": [],
        "fields": [],
        "skipped": [],
        "figures": [],
        "model_files": [],
        "status": "empty",
        "note": ("Icepack structured export (tier 1): 2-D triangular nodal "
                 "fields interpolated to CG1 for a Firedrake-free reader."),
    }

    def _write() -> None:
        with open(os.path.join(outputs, "metadata.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)

    try:
        import numpy as np
        import h5py
        import firedrake
    except Exception as e:  # pragma: no cover - only in a broken container
        meta["status"] = "export_failed"
        meta["error"] = f"import: {type(e).__name__}: {e}"
        _write()
        return meta

    try:
        found: list[tuple[str, str, str, str | None, object]] = []
        for out_name, candidates, rank, units in _FIELD_ALLOWLIST:
            for var in candidates:
                obj = namespace.get(var)
                if obj is not None and _is_firedrake_function(obj):
                    found.append((out_name, var, rank, units, obj))
                    break

        if not found:
            meta["status"] = "empty"
            meta["note"] += (" No recognised Firedrake Function found in the "
                             "example namespace (it may wrap its state in a "
                             "function, or use an extruded/1-D mesh).")
            _write()
            return meta

        mesh = found[0][4].function_space().mesh()

        # --- mesh: node coords + P1 triangle connectivity ---------------
        try:
            coords = np.asarray(mesh.coordinates.dat.data_ro)
            cells = np.asarray(
                mesh.coordinates.function_space().cell_node_map().values
            )
        except Exception as e:
            meta["status"] = "export_failed"
            meta["error"] = f"mesh: {type(e).__name__}: {e}"
            _write()
            return meta

        gdim = coords.shape[1] if coords.ndim == 2 else 1
        if gdim != 2 or cells.ndim != 2 or cells.shape[1] != 3:
            meta["status"] = "unsupported_geometry"
            meta["note"] += (f" Mesh is not 2-D triangular (gdim={gdim}, "
                             f"cell nodes={cells.shape[-1] if cells.ndim == 2 else '?'}); "
                             "tier-1 export supports 2-D triangular meshes only.")
            _write()
            return meta

        mesh_path = os.path.join(outputs, "mesh", "mesh.h5")
        with h5py.File(mesh_path, "w") as fh:
            fh.create_dataset("x", data=coords[:, 0].astype("float64"))
            fh.create_dataset("y", data=coords[:, 1].astype("float64"))
            fh.create_dataset("elements", data=cells.astype("int64"))
        meta["mesh"] = {
            "path": "mesh/mesh.h5",
            "numberofvertices": int(coords.shape[0]),
            "numberofelements": int(cells.shape[0]),
            "dimension": 2,
            "cell": "triangle",
            "connectivity_indexing": "0-based",
        }

        cg1 = firedrake.FunctionSpace(mesh, "CG", 1)

        for out_name, var, rank, units, func in found:
            try:
                src_space = _space_label(func)
                rel = f"fields/icepack/{out_name}.h5"
                fpath = os.path.join(outputs, rel)
                comps: list[str]
                with h5py.File(fpath, "w") as fh:
                    if rank == "vector":
                        vx = firedrake.Function(cg1).interpolate(func[0])
                        vy = firedrake.Function(cg1).interpolate(func[1])
                        ax = np.asarray(vx.dat.data_ro).reshape(-1)
                        ay = np.asarray(vy.dat.data_ro).reshape(-1)
                        fh.create_dataset("values", data=ax.astype("float64"))
                        fh.create_dataset("values_y", data=ay.astype("float64"))
                        fh.create_dataset(
                            "magnitude",
                            data=np.hypot(ax, ay).astype("float64"),
                        )
                        comps = [f"{out_name}_x", f"{out_name}_y"]
                    else:
                        scal = firedrake.Function(cg1).interpolate(func)
                        fh.create_dataset(
                            "values",
                            data=np.asarray(scal.dat.data_ro).reshape(-1).astype("float64"),
                        )
                        comps = [out_name]
                meta["fields"].append({
                    "name": out_name,
                    "components": comps,
                    "rank": rank,
                    "location": "nodal",
                    "exported_space": "CG1",
                    "source_space": src_space,
                    "linearised": src_space not in (None, "CG1"),
                    "units": units,
                    "units_source": "notebook_colorbar" if units else None,
                    "mesh": "mesh/mesh.h5",
                    "path": rel,
                    "timestep": None,
                    "available_timesteps": None,
                    "source_variable": var,
                })
            except Exception as e:
                meta["skipped"].append({
                    "name": out_name, "source_variable": var,
                    "reason": f"{type(e).__name__}: {e}",
                })

        meta["model_class"] = _detect_model_class(namespace)
        meta["status"] = "ok" if meta["fields"] else "empty"
        _write()
        return meta
    except Exception as e:  # pragma: no cover - defensive
        meta["status"] = "export_failed"
        meta["error"] = f"{type(e).__name__}: {e}"
        meta["traceback"] = traceback.format_exc()[-2000:]
        _write()
        return meta


def _space_label(func) -> str | None:
    try:
        el = func.function_space().ufl_element()
        fam = getattr(el, "family", lambda: None)()
        deg = getattr(el, "degree", lambda: None)()
        if fam and deg is not None:
            return f"{'CG' if 'Lagrange' in str(fam) else str(fam)}{deg}"
    except Exception:
        pass
    return None


def _detect_model_class(namespace: dict) -> str | None:
    for v in namespace.values():
        cls = type(v).__name__
        if cls in ("IceShelf", "IceStream", "ShallowIce", "HybridModel",
                   "HeatTransport3D"):
            return cls
    return None


