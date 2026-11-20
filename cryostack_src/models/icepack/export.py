"""Icepack structured export -- shell wiring around :mod:`_export_core`.

The container-side logic lives in ``_export_core.py`` (written verbatim to the
run directory as ``cryostack_icepack_export.py``). Keeping the wiring separate
means the written module never contains this file's heredoc delimiters.
"""
from __future__ import annotations

from pathlib import Path

from cryostack_src.models.icepack._export_core import (  # noqa: F401
    EXPORT_VERSION, SCHEMA, export,
)


# ---------------------------------------------------------------------------
# shell wiring (used by submission.py)
# ---------------------------------------------------------------------------
EXPORT_MODULE_NAME = "cryostack_icepack_export.py"
RUNNER_MODULE_NAME = "cryostack_icepack_runner.py"

#: the tiny runner written next to the export module. It:
#:  1. forces a headless Matplotlib backend (Agg) BEFORE the script imports
#:     matplotlib -- the tutorials call plt.subplots()/tricontourf() and rely
#:     on Jupyter's inline display, which does nothing in a plain script;
#:  2. runs the example script ONCE as ``__main__`` (exceptions propagate ->
#:     the job fails, as it must);
#:  3. persists every still-open Matplotlib figure the script produced but
#:     never saved, to ``outputs/figures/figure-NN.png`` -- deterministic,
#:     de-duplicated against figures the script saved itself, and NEVER by
#:     injecting savefig() into the science script. For each captured figure
#:     it records what the figure ITSELF carries (suptitle, axes titles, x/y
#:     labels) into ``outputs/figures/_captured.json`` -- never inferred from
#:     a variable name, figure order, or the tutorial's identity;
#:  4. runs :func:`export` on the resulting namespace (allow-list only,
#:     never guesses a field).
#: Steps 1, 3 and 4 are all non-fatal: a good science run is never turned
#: into a failed one by figure capture or export.
_PROVENANCE_SOURCE = r'''
def _capture_runtime_provenance(run_dir, phase):
    """Best-effort observation only: never import a scientific/RNG package."""
    try:
        # Only observe random generators that the existing runtime loaded.
        # Importing a new RNG here would change its initialization point.
        states = {}
        rng = {}
        if phase == "before":
            py_random = sys.modules.get("random")
            np_random = sys.modules.get("numpy.random")
            if py_random is not None and callable(getattr(py_random, "getstate", None)):
                states["python_random"] = py_random.getstate()
                rng["python_global"] = {"captured": True, "seed": None,
                    "seed_status": "not inferable from current state", "state_member": "python_random"}
            else:
                rng["python_global"] = {"captured": False, "reason": "not loaded before science"}
            if np_random is not None and callable(getattr(np_random, "get_state", None)):
                value = np_random.get_state()
                states["numpy_random"] = {"algorithm": value[0], "keys": value[1].tolist(),
                    "position": int(value[2]), "has_gauss": int(value[3]), "cached_gaussian": float(value[4])}
                rng["numpy_global"] = {"captured": True, "algorithm": value[0], "seed": None,
                    "seed_status": "not inferable from current state", "state_member": "numpy_random"}
            else:
                rng["numpy_global"] = {"captured": False, "reason": "not loaded before science"}
        import hashlib
        import platform
        import re
        from datetime import datetime, timezone
        output = os.path.join(run_dir, "outputs")
        os.makedirs(output, exist_ok=True)
        path = os.path.join(output, "runtime-provenance.json")
        report = {}
        if phase != "before":
            try:
                with open(path, encoding="utf-8") as stream:
                    report = json.load(stream)
            except Exception:
                pass
        report.update(schema="cryostack.runtime-provenance.v1", model="icepack",
                      architecture=platform.machine(),
                      capture_time_utc=datetime.now(timezone.utc).isoformat(), phase=phase)
        report[phase + "_capture_time_utc"] = report["capture_time_utc"]
        versions = {"python": {"value": platform.python_version(), "source": "running Python interpreter"}}
        discovered = None
        for name in ("numpy", "h5py", "firedrake", "icepack", "petsc4py", "mpi4py"):
            module = sys.modules.get(name)
            value = getattr(module, "__version__", None) if module is not None else None
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+!~\-]{0,160}", value):
                versions[name] = {"value": value, "source": "loaded module __version__"}
                continue
            # Use the runtime's discovered package-to-distribution mapping;
            # never invent a distribution name for an unavailable module.
            if discovered is None:
                discovered = {}
                if phase != "before":
                    try:
                        from importlib import metadata
                        discovered = metadata.packages_distributions()
                    except Exception:
                        pass
            distributions = {}
            for distribution in discovered.get(name, ()):
                try:
                    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", distribution):
                        continue
                    value = metadata.version(distribution)
                    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+!~\-]{0,160}", value):
                        distributions[distribution] = value
                except Exception:
                    pass
            versions[name] = {"value": None, "source": "module version unavailable",
                "module_loaded": module is not None, "installed_distributions": distributions,
                "distribution_source": "runtime packages_distributions mapping"}
        petsc = sys.modules.get("petsc4py.PETSc")
        if petsc is not None:
            try:
                versions["petsc_library"] = {"value": list(petsc.Sys.getVersion()), "source": "PETSc.Sys.getVersion()"}
            except Exception:
                pass
        versions.setdefault("petsc_library", {"value": None, "source": "library not observed"})
        mpi = sys.modules.get("mpi4py.MPI")
        process = {"requested_processes": None, "requested_source": "not separately supplied to runner",
                   "observed_world_size": None, "observed_rank": None, "source": "MPI module not loaded"}
        if mpi is not None:
            try:
                process.update(observed_world_size=int(mpi.COMM_WORLD.Get_size()),
                               observed_rank=int(mpi.COMM_WORLD.Get_rank()), source="running MPI.COMM_WORLD")
                versions["mpi_standard"] = {"value": list(mpi.Get_version()), "source": "MPI.Get_version()"}
                raw = mpi.Get_library_version()
                match = re.search(r"(Open MPI|MPICH|Intel\(R\) MPI|Microsoft MPI)[^0-9\n]*([0-9]+(?:\.[0-9]+){1,3})", raw)
                versions["mpi_library"] = {"value": (match.group(1)+" "+match.group(2)) if match else None,
                    "source": "MPI.Get_library_version() vendor/version only; raw text excluded"}
            except Exception:
                pass
        versions.setdefault("mpi_standard", {"value": None, "source": "library not observed"})
        versions.setdefault("mpi_library", {"value": None, "source": "library version not observed"})
        report["versions"] = versions
        report["mpi"] = process
        report["threads"] = {name: (os.environ[name] if re.fullmatch(r"[0-9]+(?:,[0-9]+)*", os.environ.get(name, ""))
                            and len(os.environ[name]) <= 64 else "unset or nonnumeric; value not recorded")
            for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")}
        report["observed_thread_counts"] = {"value": None, "source": "not measured; environment requests only"}
        if phase == "before":
            report["before_versions"] = dict(versions)
            report["before_threads"] = dict(report["threads"])
            rng_path = os.path.join(output, "rng-before.json")
            body = (json.dumps(states, sort_keys=True, separators=(",", ":"))+"\n").encode()
            with open(rng_path, "wb") as stream:
                stream.write(body)
            report["rng"] = {"global_states": rng, "artifact": "rng-before.json",
                "sha256": hashlib.sha256(body).hexdigest(), "state_reset_or_advanced_by_capture": False,
                "unobserved": ["script-owned generators", "Triangle internal RNG", "other solver-library generators"]}
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
        # Public, bounded summary only: no RNG values, paths or environment dump.
        print("[cryostack][runtime-provenance] " + json.dumps({
            "schema": report["schema"], "model": report["model"], "phase": phase,
            "versions": versions, "threads": report["threads"], "mpi": process,
            "artifact": "outputs/runtime-provenance.json"}, sort_keys=True), flush=True)
    except Exception as error:
        print("[cryostack][warn] runtime provenance unavailable: " + type(error).__name__, flush=True)

'''

_RUNNER_SOURCE = '''# cryostack-icepack-runner (auto-generated -- do not edit)
import json
import os
import runpy
import sys

os.environ.setdefault("MPLBACKEND", "Agg")
try:
    import matplotlib
    matplotlib.use("Agg", force=True)
except Exception:
    pass

script, run_dir = sys.argv[1], sys.argv[2]
figures_dir = os.path.join(run_dir, "outputs", "figures")
os.makedirs(figures_dir, exist_ok=True)

# Note which figures the script saves itself, so the post-run sweep does not
# emit a duplicate copy of the same figure under a generic name.
_saved_fignums = set()
_plt = None
try:
    import matplotlib.pyplot as _plt
    _orig_savefig = _plt.Figure.savefig

    def _tracking_savefig(self, *a, **k):
        try:
            _saved_fignums.add(self.number)
        except Exception:
            pass
        return _orig_savefig(self, *a, **k)

    _plt.Figure.savefig = _tracking_savefig
except Exception:
    _plt = None

# __CRYOSTACK_RUNTIME_PROVENANCE_FUNCTIONS__
sys.path.insert(0, run_dir)
_capture_runtime_provenance(run_dir, "before")
try:
    _ns = runpy.run_path(script, run_name="__main__")   # science: errors propagate
finally:
    _capture_runtime_provenance(run_dir, "after")

# Persist any still-open figures the script drew but never saved, and record
# each figure's OWN metadata -- explicit figure label, suptitle, axes title,
# axis labels -- never inferred from a variable name, filename, or the
# tutorial's identity.
def _text(obj):
    try:
        t = obj.get_text() if obj is not None else ""
        return t.strip() if isinstance(t, str) else ""
    except Exception:
        return ""

_captured = []
try:
    if _plt is not None:
        _plt.Figure.savefig = _orig_savefig            # restore
        _idx = 0
        for _num in _plt.get_fignums():
            if _num in _saved_fignums:
                continue
            _idx += 1
            _fig = _plt.figure(_num)
            _name = "figure-%02d.png" % _idx
            try:
                _fig.savefig(os.path.join(figures_dir, _name),
                             dpi=120, bbox_inches="tight")
            except Exception as _fe:
                print("[cryostack][warn] figure capture failed:",
                      type(_fe).__name__, _fe)
                continue
            _entry = {"file": _name}
            try:
                # (1) an EXPLICIT label the script itself set on the figure --
                # plt.figure("Bed topography") / fig.set_label(...) / a
                # non-default window title. Highest-priority name; never
                # inferred. matplotlib's own default label is "" and its
                # default window title is "Figure <n>", both of which are
                # treated as "no label".
                _lbl = ""
                try:
                    _lbl = (_fig.get_label() or "").strip()
                except Exception:
                    _lbl = ""
                if not _lbl:
                    try:
                        _wt = (_fig.canvas.manager.get_window_title() or "").strip()
                        if _wt and _wt != ("Figure %d" % _num):
                            _lbl = _wt
                    except Exception:
                        pass
                if _lbl:
                    _entry["label"] = _lbl
                _st = _text(getattr(_fig, "_suptitle", None))
                if _st:
                    _entry["suptitle"] = _st
                _axt, _xl, _yl = [], "", ""
                for _ax in _fig.get_axes():
                    _t = _text(getattr(_ax, "title", None)) or (
                        _ax.get_title().strip() if hasattr(_ax, "get_title") else "")
                    if _t:
                        _axt.append(_t)
                    if not _xl and hasattr(_ax, "get_xlabel"):
                        _xl = (_ax.get_xlabel() or "").strip()
                    if not _yl and hasattr(_ax, "get_ylabel"):
                        _yl = (_ax.get_ylabel() or "").strip()
                if _axt:
                    _entry["axes_titles"] = _axt
                if _xl:
                    _entry["xlabel"] = _xl
                if _yl:
                    _entry["ylabel"] = _yl
            except Exception:
                pass
            _captured.append(_entry)
        if _idx:
            print("[cryostack] captured %d live matplotlib figure(s)" % _idx)
        if _captured:
            with open(os.path.join(figures_dir, "_captured.json"),
                      "w", encoding="utf-8") as _fh:
                json.dump(_captured, _fh)
except Exception as _err:
    print("[cryostack][warn] matplotlib figure capture failed:",
          type(_err).__name__, _err)

try:
    import cryostack_icepack_export as _e
    _e.export(_ns, run_dir)
except Exception as _err:  # export is best-effort only
    print("[cryostack][warn] icepack structured export failed:",
          type(_err).__name__, _err)
'''


def export_module_source() -> str:
    """Text for ``<run_dir>/cryostack_icepack_export.py`` -- the container-side
    core, which must not contain this file's heredoc delimiters."""
    return (Path(__file__).with_name("_export_core.py")).read_text(encoding="utf-8")


def runner_module_source() -> str:
    """Text for ``<run_dir>/cryostack_icepack_runner.py``."""
    return _RUNNER_SOURCE.replace("# __CRYOSTACK_RUNTIME_PROVENANCE_FUNCTIONS__", _PROVENANCE_SOURCE)


def run_command(*, script: str, run_dir: str) -> str:
    """The command that replaces a bare ``python <script>`` for an Icepack run:
    run the script once, then structured-export its namespace."""
    return f'python {run_dir}/{RUNNER_MODULE_NAME} "{script}" "{run_dir}"'


def _heredoc(path: str, text: str, tag: str) -> str:
    return f"cat > {path!r} <<'{tag}'\n{text}\n{tag}"


def build_export_shell_block(
    *,
    run_dir: str,
    example_dir: str,
    backend: str,
    sif_path: str = "",
    spack_path: str = "",
    stack_binds: str = "",
    run_file_name: str,
    run_file_py: str = "",
    primary: bool = False,
) -> str:
    """The Icepack science + capture + export step for a Remote/SLURM job.

    It stages ``cryostack_icepack_export.py`` + ``cryostack_icepack_runner.py``
    and invokes the runner in the ``with-icepack`` Firedrake environment. The
    runner runs the example script ONCE (``runpy.run_path`` -- errors
    propagate), forces a headless Matplotlib backend, persists every
    still-open figure + its metadata, then structured-exports the namespace
    (allow-list only).

    ``primary=True`` (the current Remote path): this block IS the run -- the
    science exit code propagates and a ``.ipynb`` target is nbconvert'd
    first, exactly like the Cloud runner (``cryostack_src.cloud.runtime``).
    So Cloud and Remote share ONE Icepack execution contract; only the
    provider wrapper (apptainer vs. Fargate) differs.

    ``primary=False`` (legacy, non-fatal appended step -- kept for callers
    that still run the science separately): a failure here only warns.
    """
    target = run_file_name
    py_name = run_file_py if run_file_name.endswith(".ipynb") else run_file_name
    if not py_name or not py_name.endswith(".py"):
        return "\n# (no Python entrypoint for Icepack structured export)\n"

    export_path = f"{run_dir}/{EXPORT_MODULE_NAME}"
    runner_path = f"{run_dir}/{RUNNER_MODULE_NAME}"
    nbconvert = ""
    if primary and target.endswith(".ipynb"):
        nbconvert = f'jupyter nbconvert --to script "{example_dir}/{target}" && '
    inner = (
        f'cd "{example_dir}" && {nbconvert}'
        f'python "{runner_path}" "{example_dir}/{py_name}" "{run_dir}"'
    )
    tail = "" if primary else (
        ' || echo "[cryostack][warn] icepack structured export step failed (non-fatal)"')

    if backend == "spack":
        run_line = f'( source "{spack_path}/scripts/activate.sh" && {inner} ){tail}'
    else:
        run_line = (
            f'apptainer exec '
            f'-B "{example_dir}":"{example_dir}","{run_dir}":"{run_dir}"{stack_binds} '
            f'"{sif_path}" with-icepack bash -lc \'{inner}\'{tail}'
        )

    heading = ("CryoStack Icepack run + capture + structured export"
               if primary else "CryoStack Icepack structured export (non-fatal)")
    return f'''
# --- {heading} ------------------
mkdir -p "{run_dir}/outputs"
{_heredoc(export_path, export_module_source(), "CRYOSTACK_ICEPACK_EXPORT_EOF")}
{_heredoc(runner_path, runner_module_source(), "CRYOSTACK_ICEPACK_RUNNER_EOF")}
{run_line}
'''
