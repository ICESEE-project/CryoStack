# icesee_jupyter_book/core/local_runner.py
from __future__ import annotations

import os
import sys
import shutil
import subprocess

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

from .paths import BOOK, REPO
from .config_io import dump_yaml
from .example_discovery import find_run_script, find_report_notebook


# ============================================================
# Local run helpers
# ============================================================
def run_dir(base: "Path | str | None" = None,
            name: str | None = None) -> Path:
    """Create (and return) a run directory with ``results/`` + ``figures/``.

    ``base``  -- parent directory for the run. Default (``None``) keeps the
                 historical process-global location ``BOOK/icesee_runs/``; a
                 caller with per-user workspace isolation passes that user's
                 run root here so two authenticated users never collide.
    ``name``  -- the run's own directory name. Default is a second-granularity
                 timestamp (kept for backwards compatibility); pass a unique
                 run id to remove the same-second collision entirely.
    """
    root = Path(base) if base is not None else (BOOK / "icesee_runs")
    rd = root / (name or datetime.now().strftime("%Y%m%d_%H%M%S"))
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "results").mkdir(exist_ok=True)
    (rd / "figures").mkdir(exist_ok=True)
    return rd


#: never copied into a run: outputs of earlier runs and caches
_STAGE_IGNORE = shutil.ignore_patterns("_modelrun_datasets", "results", "figures", "__pycache__",
                                       ".ipynb_checkpoints", "*.pyc")


def stage_example(example_cfg: dict, rd: Path, overlays: "dict[str, Path] | None" = None) -> dict:
    """A private copy of the example directory inside the run directory.

    ICESEE example scripts change into their own directory and write
    ``_modelrun_datasets`` there; run from the shared copy, concurrent users
    would read and overwrite each other's data (and a read-only installation
    could not run them at all). The copy keeps the directory name, which
    ICESEE uses to find example-specific model modules. Returns the example
    configuration pointing at the copy.

    ``overlays`` maps a path inside the example to a replacement file (the
    user's edited inputs, see experiment_files.py); each must already exist
    in the example -- staging never adds files."""
    base = Path(example_cfg["base"])
    staged = rd / "example" / base.name
    if staged.exists():
        shutil.rmtree(staged)
    run_root = rd.resolve()

    def ignore(directory, names):
        skipped = set(_STAGE_IGNORE(directory, names))
        # never copy the run directory into itself
        return skipped | {n for n in names if run_root.is_relative_to((Path(directory) / n).resolve())}

    # files are copied without their mode: the installation may be read-only
    shutil.copytree(base, staged, ignore=ignore, symlinks=True, copy_function=shutil.copyfile)
    for path in [staged, *staged.rglob("*")]:
        if path.is_dir() and not path.is_symlink():
            path.chmod(path.stat().st_mode | 0o700)
    for rel, source in (overlays or {}).items():
        target = (staged / rel).resolve()
        if not target.is_relative_to(staged.resolve()) or not target.is_file():
            raise ValueError(f"edited input {rel!r} is not a file of the example")
        shutil.copyfile(source, target)
    return dict(example_cfg, base=staged)


def force_external_icesee_env() -> tuple[dict, Path]:
    external_dir = (REPO / "external").resolve()
    # local runs never need AWS; keep the server's AWS identity away from them
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env["PYTHONPATH"] = f"{external_dir}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["PYTHONNOUSERSITE"] = "1"
    return env, external_dir


def mirror_assets_for_report(example_cfg: dict, rd: Path) -> None:
    base = example_cfg["base"]
    for a in example_cfg.get("assets", []):
        src = base / a
        if src.exists():
            dst = rd / a
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)


def ensure_report_h5(rd: Path, example_cfg: dict, expected_prefix: str) -> Path:
    """
    Ensure results/<expected_prefix>-<model>.h5 exists in rd for report notebooks.
    If missing, search for any *-<model>.h5 under rd/results or the example base, and copy.
    """
    model_name = example_cfg.get("model_name", "lorenz")
    exp = rd / "results" / f"{expected_prefix}-{model_name}.h5"
    if exp.exists():
        return exp

    candidates = sorted(
        (rd / "results").glob(f"*-{model_name}.h5"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not candidates:
        # this run's own output (the example writes _modelrun_datasets in its
        # staged copy, mirrored into the run directory)
        own = [rd / "_modelrun_datasets", Path(example_cfg["base"]) / "_modelrun_datasets"]
        candidates = sorted(
            (p for d in own for p in d.glob(f"{expected_prefix}-{model_name}.h5")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    if not candidates:
        base = example_cfg["base"]
        candidates = sorted(
            base.glob(f"**/results/*-{model_name}.h5"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    if candidates:
        exp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidates[0], exp)

    return exp


def run_report_notebook(report_nb: Path | None, example_cfg: dict, rd: Path) -> Path | None:
    if not report_nb or not report_nb.exists():
        return None

    try:
        import papermill as pm
    except Exception as e:
        raise RuntimeError(
            "papermill is required to run read_results.ipynb automatically. "
            "Install it (pip install papermill) or replace with nbclient."
        ) from e

    nb_out = rd / "report.ipynb"
    mirror_assets_for_report(example_cfg, rd)

    pm.execute_notebook(
        input_path=str(report_nb),
        output_path=str(nb_out),
        cwd=str(rd),
        log_output=True,
    )
    return nb_out


# ============================================================
# Local execution
# ============================================================
@dataclass
class LocalRunResult:
    success: bool
    returncode: int
    run_dir: Path
    command: list[str]
    external_dir: Path
    log_lines: list[str]
    log_text: str
    report_notebook: Path | None = None


def run_local_example(
    example_cfg: dict,
    config: dict,
    output_label: str = "true-wrong",
    generate_report: bool = False,
    *,
    run_dir_base: "Path | str | None" = None,
    run_dir_name: str | None = None,
) -> LocalRunResult:
    rd = run_dir(run_dir_base, run_dir_name)
    example_cfg = stage_example(example_cfg, rd)
    run_script = find_run_script(example_cfg)
    report_nb = find_report_notebook(example_cfg)

    dump_yaml(config, rd / "params.yaml")

    env, external_dir = force_external_icesee_env()
    cmd = [sys.executable, str(run_script), "-F", str(rd / "params.yaml")]

    proc = subprocess.Popen(
        cmd,
        cwd=str(rd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )

    assert proc.stdout is not None
    log_lines = []
    for line in proc.stdout:
        log_lines.append(line.rstrip("\n"))

    rc = proc.wait()
    log_text = "\n".join(log_lines)

    looks_like_failure = (
        "Traceback (most recent call last)" in log_text
        or "Error in serial run mode" in log_text
    )
    success = (rc == 0) and (not looks_like_failure)

    executed_report = None
    if success and generate_report:
        ensure_report_h5(rd, example_cfg, output_label)
        executed_report = run_report_notebook(report_nb, example_cfg, rd)

    return LocalRunResult(
        success=success,
        returncode=rc,
        run_dir=rd,
        command=cmd,
        external_dir=external_dir,
        log_lines=log_lines,
        log_text=log_text,
        report_notebook=executed_report,
    )