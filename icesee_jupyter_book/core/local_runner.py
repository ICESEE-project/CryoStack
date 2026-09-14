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


def force_external_icesee_env() -> tuple[dict, Path]:
    external_dir = (REPO / "external").resolve()
    env = os.environ.copy()
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
    run_script = find_run_script(example_cfg)
    report_nb = find_report_notebook(example_cfg)
    rd = run_dir(run_dir_base, run_dir_name)

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