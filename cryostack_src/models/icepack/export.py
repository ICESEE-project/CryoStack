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

#: the tiny runner written next to the export module. It runs the example
#: script ONCE as ``__main__`` (its exceptions propagate -> the job fails) and
#: then calls :func:`export` on the resulting namespace (wrapped -> non-fatal:
#: a failed export never turns a good science run into a failed one).
_RUNNER_SOURCE = '''# cryostack-icepack-runner (auto-generated -- do not edit)
import runpy
import sys

script, run_dir = sys.argv[1], sys.argv[2]
sys.path.insert(0, run_dir)
_ns = runpy.run_path(script, run_name="__main__")   # science: errors propagate
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
    return _RUNNER_SOURCE


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
) -> str:
    """A **non-fatal** sbatch block, appended after the Icepack run, that runs
    the structured exporter in the ``with-icepack`` Firedrake environment.

    v1 re-runs the example script once inside the runner to capture its final
    ``Function`` namespace (deterministic; the tutorial spin-ups are
    idempotent). Folding this into the run block itself to avoid the second run
    is a tracked optimisation (see AGENT_TRAIL / MORNING_REPORT P2).
    """
    script_in_example = run_file_py if run_file_name.endswith(".ipynb") else run_file_name
    if not script_in_example or not script_in_example.endswith(".py"):
        return "\n# (no Python entrypoint for Icepack structured export)\n"

    export_path = f"{run_dir}/{EXPORT_MODULE_NAME}"
    runner_path = f"{run_dir}/{RUNNER_MODULE_NAME}"
    inner = (
        f'cd "{example_dir}" && '
        f'python "{runner_path}" "{example_dir}/{script_in_example}" "{run_dir}"'
    )

    if backend == "spack":
        run_line = (
            f'( source "{spack_path}/scripts/activate.sh" && {inner} ) '
            '|| echo "[cryostack][warn] icepack structured export step failed (non-fatal)"'
        )
    else:
        run_line = (
            f'apptainer exec '
            f'-B "{example_dir}":"{example_dir}","{run_dir}":"{run_dir}"{stack_binds} '
            f'"{sif_path}" with-icepack bash -lc \'{inner}\' '
            '|| echo "[cryostack][warn] icepack structured export step failed (non-fatal)"'
        )

    return f'''
# --- CryoStack Icepack structured export (non-fatal) ------------------
mkdir -p "{run_dir}/outputs"
{_heredoc(export_path, export_module_source(), "CRYOSTACK_ICEPACK_EXPORT_EOF")}
{_heredoc(runner_path, runner_module_source(), "CRYOSTACK_ICEPACK_RUNNER_EOF")}
{run_line}
'''
