"""Local ICESEE runs execute a private copy of the example directory.

ICESEE example scripts change into their own directory and write
``_modelrun_datasets`` there; run from the shared copy, concurrent users read
and overwrite each other's data, and a read-only (sandboxed) installation
cannot run them at all.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from icesee_jupyter_book.core import local_runner

SCRIPT = """\
import os, sys
from pathlib import Path
os.chdir(Path(__file__).resolve().parent)            # like the ICESEE examples
Path("_modelrun_datasets").mkdir(exist_ok=True)
Path("_modelrun_datasets/true-wrong-demo.h5").write_text(sys.argv[-1])
print("cwd", Path.cwd().name)
"""


def _example(tmp_path: Path) -> dict:
    base = tmp_path / "shared" / "lorenz96"
    (base / "_modelrun_datasets").mkdir(parents=True)
    (base / "_modelrun_datasets" / "stale.h5").write_text("other user's data")
    (base / "run_da_demo.py").write_text(SCRIPT)
    (base / "params.yaml").write_text("x: 1\n")
    return dict(base=base, run_script="run_da_demo.py", params="params.yaml",
                assets=["_modelrun_datasets"], model_name="lorenz")


def test_local_run_writes_only_inside_its_run_directory(tmp_path, monkeypatch):
    cfg = _example(tmp_path)
    base = cfg["base"]
    for path in [base, *base.rglob("*")]:                   # the installation is read-only
        path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    try:
        result = local_runner.run_local_example(cfg, {"x": 1}, run_dir_base=tmp_path / "alice",
                                                run_dir_name="run-1")
    finally:
        for path in [base, *base.rglob("*")]:
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
    assert result.success, result.log_text
    staged = result.run_dir / "example" / "lorenz96"
    assert "cwd lorenz96" in result.log_text                 # ICESEE finds example modules by this name
    assert (staged / "_modelrun_datasets" / "true-wrong-demo.h5").read_text().endswith("params.yaml")
    assert not (staged / "_modelrun_datasets" / "stale.h5").exists()     # earlier outputs never copied
    assert sorted(p.name for p in (base / "_modelrun_datasets").iterdir()) == ["stale.h5"]


def test_two_runs_do_not_share_outputs(tmp_path):
    cfg = _example(tmp_path)
    a = local_runner.run_local_example(cfg, {"x": 1}, run_dir_base=tmp_path / "alice", run_dir_name="a")
    b = local_runner.run_local_example(cfg, {"x": 2}, run_dir_base=tmp_path / "bob", run_dir_name="b")
    out = lambda r: r.run_dir / "example" / "lorenz96" / "_modelrun_datasets" / "true-wrong-demo.h5"
    assert out(a).read_text() != out(b).read_text() or out(a) != out(b)
    assert out(a).parent != out(b).parent
    local_runner.mirror_assets_for_report(dict(cfg, base=a.run_dir / "example" / "lorenz96"), a.run_dir)
    assert (a.run_dir / "_modelrun_datasets" / "true-wrong-demo.h5").is_file()
    assert not (a.run_dir / "_modelrun_datasets" / "stale.h5").exists()


def test_report_uses_this_runs_output_never_a_stale_result(tmp_path):
    cfg = _example(tmp_path)
    (cfg["base"] / "results").mkdir()
    (cfg["base"] / "results" / "true-wrong-lorenz.h5").write_text("July result of someone else")
    result = local_runner.run_local_example(cfg, {"x": 1}, run_dir_base=tmp_path / "alice",
                                            run_dir_name="r")
    staged = dict(cfg, base=result.run_dir / "example" / "lorenz96", model_name="lorenz")
    local_runner.mirror_assets_for_report(staged, result.run_dir)
    (result.run_dir / "_modelrun_datasets" / "true-wrong-lorenz.h5").write_text("this run")
    report_h5 = local_runner.ensure_report_h5(result.run_dir, staged, "true-wrong")
    assert report_h5.read_text() == "this run"


def test_report_finds_the_output_before_it_is_mirrored(tmp_path):
    cfg = _example(tmp_path)
    result = local_runner.run_local_example(cfg, {"x": 1}, run_dir_base=tmp_path / "alice",
                                            run_dir_name="r")
    staged = dict(cfg, base=result.run_dir / "example" / "lorenz96", model_name="demo")
    report_h5 = local_runner.ensure_report_h5(result.run_dir, staged, "true-wrong")
    assert report_h5.read_text().endswith("params.yaml")       # written by this run's script
