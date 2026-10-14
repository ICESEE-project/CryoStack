"""scripts/icesee_scaling_benchmark.py: ``plan`` changes only Nens/data_path
and runs nothing; ``collect`` tabulates ICESEE's own timing tables and
reports missing ones instead of estimating them.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.core.tests.test_run_monitor import _timing_table


def _load():
    spec = importlib.util.spec_from_file_location(
        "icesee_scaling_benchmark", _REPO / "scripts" / "icesee_scaling_benchmark.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base_params(tmp_path: Path) -> Path:
    path = tmp_path / "base.yaml"
    path.write_text(yaml.safe_dump({
        "modeling-parameters": {"dt": 0.5, "nx": 24},
        "enkf-parameters": {"Nens": 40, "execution_mode": 1, "sig_obs": [0.1], "data_path": "_x"},
    }))
    return path


def test_plan_changes_only_nens_and_data_path(tmp_path):
    bench = _load()
    out = tmp_path / "bench"
    bench.main(["plan", "--params", str(_base_params(tmp_path)), "--run-script", "run.py",
                "--ranks", "1,2,4", "--nens", "8", "--nens-per-rank", "2", "--out", str(out)])
    manifest = json.loads((out / "plan.json").read_text())
    assert [(c["mode"], c["ranks"], c["nens"]) for c in manifest["cases"]] == [
        ("strong", 1, 8), ("strong", 2, 8), ("strong", 4, 8),
        ("weak", 1, 2), ("weak", 2, 4), ("weak", 4, 8),
    ]
    base = yaml.safe_load(_base_params(tmp_path).read_text())
    case = yaml.safe_load((out / "strong-np004-nens0008" / "params.yaml").read_text())
    assert case["modeling-parameters"] == base["modeling-parameters"]
    changed = {k for k in base["enkf-parameters"] if case["enkf-parameters"][k] != base["enkf-parameters"][k]}
    assert changed == {"Nens", "data_path"}
    commands = (out / "commands.txt").read_text().splitlines()
    assert len(commands) == 6 and "mpiexec -n 4 python" in commands[2]
    assert not any((out / c["name"] / "run.log").exists() for c in manifest["cases"])


def test_collect_computes_speedup_and_reports_missing(tmp_path, capsys):
    bench = _load()
    out = tmp_path / "bench"
    bench.main(["plan", "--params", str(_base_params(tmp_path)), "--run-script", "run.py",
                "--ranks", "1,2,4", "--nens", "8", "--out", str(out)])
    for name, wall, forecast in (("strong-np001-nens0008", 100.0, 80.0),
                                 ("strong-np002-nens0008", 55.0, 40.0)):
        (out / name / "run.log").write_text(_timing_table(2, {
            "Wall-Clock Time (max)": wall, "Forecast Step Time": forecast}))
    rows = bench.main(["collect", "--out", str(out)]) or list(csv.DictReader((out / "scaling.csv").open()))
    by_name = {r["name"]: r for r in rows}
    two = by_name["strong-np002-nens0008"]
    assert float(two["wall_speedup"]) == round(100 / 55, 4)
    assert float(two["wall_efficiency"]) == round(100 / 55 / 2, 4)
    assert float(two["forecast_speedup"]) == 2.0
    assert by_name["strong-np004-nens0008"]["wall"] == ""
    assert "not reported" in capsys.readouterr().out
