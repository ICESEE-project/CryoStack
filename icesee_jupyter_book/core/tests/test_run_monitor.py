"""ICESEE run-progress report (run_monitor.py): assimilation step, ensemble
size, checkpoints + resume capability and phase timings, from fixture trees
shaped like what the pinned ICESEE drivers write (full-parallel checkpoint
JSON, icesee_enkf_ens_NNNN.h5 step files, diagnostics/icesee_timing.log,
tqdm progress on stdout). Covers complete, partial, corrupted, oversized and
symlink-escape inputs; nothing may be guessed and nothing may be written.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.core import run_monitor as rm
from icesee_jupyter_book.core.run_monitor import NOT_REPORTED, inspect_run_progress

GRAY, RESET = "\033[10m", "\033[0m"


def _timing_table(ranks: int, seconds: dict) -> str:
    """Byte-for-byte the shape tools.display_timing_verbose logs."""
    lines = [f"{GRAY}╔{'═' * 60}╗{RESET}",
             f"{GRAY}║ \033[1m[ICESEE] Performance Metrics ({ranks} ranks)     (DAY:HR:MIN:SEC.ms){RESET}   {GRAY}║{RESET}"]
    for label, secs in seconds.items():
        d, rem = divmod(secs, 86400)
        h, rem = divmod(rem, 3600)
        m, s = divmod(rem, 60)
        ms = int(round((s % 1) * 1000))
        value = f"{int(d):02d}:{int(h):02d}:{int(m):02d}:{int(s):02d}.{ms:03d}"
        lines.append(f"{GRAY}║ {label}    {value}  {RESET}{GRAY}  ║{RESET}")
    lines.append(f"{GRAY}╚{'═' * 60}╝{RESET}")
    return "\n".join(lines) + "\n"


TIMINGS = {
    "Computational Time (Σ)": 480.5,
    "Wall-Clock Time (max)": 120.25,
    "True/Wrong State Time": 4.0,
    "Ensemble Init Time": 6.0,
    "Forecast Step Time": 80.0,
    "Analysis Step Time": 20.0,
    "Assimilation Time": 106.0,
    "Init file I/O Time": 1.0,
    "Forecast File I/O Time": 3.5,
    "Analysis File I/O Time": 2.5,
    "Total File I/O Time": 7.0,
    "Forecast Noise Time": 0.75,
    "Init Ensemble Mean Computation": 0.1,
    "Forecast Ensemble Mean Computation": 0.2,
    "Analysis Ensemble Mean Computation": 0.3,
}


def _params(path: Path, **enkf):
    import yaml

    section = {"Nens": 4, "execution_mode": 2, "data_path": "_modelrun_datasets"}
    section.update(enkf)
    path.write_text(yaml.safe_dump({"enkf-parameters": section}))


def _full_run(tmp_path: Path, *, nt=10, last_done_k=9, steps=None, ckpt=True, **params) -> Path:
    run = tmp_path / "run"
    data = run / "_modelrun_datasets"
    (data / "_checkpoints").mkdir(parents=True)
    (data / "diagnostics").mkdir()
    _params(run / "params.yaml", **params)
    for k in (range(last_done_k + 1) if steps is None else steps):
        (data / f"icesee_enkf_ens_{k:04d}.h5").write_bytes(b"\0" * 16)
    if ckpt:
        (data / "_checkpoints" / "icesee_ckpt.json").write_text(json.dumps({
            "last_done_k": last_done_k, "km": 3, "nt": nt, "nd": 120, "nens": 4,
            "dataset_dir": str(data), "timestamp": 1_760_000_000.0, "base_seed": 0,
        }))
    (data / "diagnostics" / "icesee_timing.log").write_text(_timing_table(16, TIMINGS))
    bar = "\r".join(
        f"[ICESEE] Assimilation progress (16 ranks):  {10 * n}%|##   | {n}/{nt} [00:0{n}<00:10, 1.00it/s]"
        for n in range(last_done_k + 2)
    )
    (run / "run.log").write_text(
        "[ICESEE] Running default parallel mode\n"
        f"[ICESEE] Fresh start at k=0 (nt={nt})\n"
        f"[ICESEE] Launching icepack with data assimilation using the EnKF filter across 16 MPI ranks.\n"
        f"{bar}\n"
    )
    return run


def _listing(root: Path) -> list:
    return sorted((str(p), p.stat().st_size) for p in root.rglob("*"))


# ─────────────────────────────────────────────────────────────────────────────
# complete / partial runs
# ─────────────────────────────────────────────────────────────────────────────
def test_complete_full_parallel_run(tmp_path):
    run = _full_run(tmp_path)
    before = _listing(run)
    report = inspect_run_progress(run)
    assert _listing(run) == before                     # read-only

    step, source = report.assimilation_step()
    assert step == "10 of 10 steps completed (last_done_k=9)"
    assert source == "_modelrun_datasets/_checkpoints/icesee_ckpt.json"
    assert report.ensemble_size() == ("4", "_modelrun_datasets/_checkpoints/icesee_ckpt.json")
    assert report.members_completed()[0] == NOT_REPORTED
    assert report.resume.driver == "full"
    assert report.resume.possible is False
    assert "all 10 steps completed" in report.resume.reason
    assert report.log.model == "icepack" and report.log.filter_type == "EnKF"
    assert report.log.launch_ranks == 16
    assert (report.log.progress_done, report.log.progress_total) == (10, 10)

    t = report.timings
    assert t is not None and t.reported_ranks == 16 and t.tables_found == 1
    assert [label for label, _ in t.phases] == list(TIMINGS)
    assert t.seconds("Forecast Step Time") == pytest.approx(80.0)
    assert t.seconds("Wall-Clock Time (max)") == pytest.approx(120.25)
    assert t.source == "_modelrun_datasets/diagnostics/icesee_timing.log"
    ckpts = report.checkpoints()
    assert len(ckpts) == 1 and ckpts[0].state == "ok" and ckpts[0].file.size > 0


def test_interrupted_full_run_is_resumable_per_icesee_rules(tmp_path):
    run = _full_run(tmp_path, nt=10, last_done_k=3)
    report = inspect_run_progress(run)
    assert report.assimilation_step()[0] == "4 of 10 steps completed (last_done_k=3)"
    assert report.resume.possible is True
    assert report.resume.next_step == 4
    assert "resume at k=4" in report.resume.reason
    assert rm.FULL_PARALLEL_RESUME_CAVEAT in report.resume.notes


def test_missing_step_file_blocks_resume_like_enforce_contiguous_history(tmp_path):
    run = _full_run(tmp_path, nt=10, last_done_k=3, steps=[0, 1, 3])
    report = inspect_run_progress(run)
    assert report.resume.possible is False
    assert report.resume.next_step == 4
    assert "missing 2" in report.resume.reason


def test_enforce_contiguous_history_false_skips_the_contiguity_rule(tmp_path):
    run = _full_run(tmp_path, nt=10, last_done_k=3, steps=[3], enforce_contiguous_history=False)
    assert inspect_run_progress(run).resume.possible is True


def test_io_class_step_names_never_count_toward_resume(tmp_path):
    run = _full_run(tmp_path, nt=6, last_done_k=2, steps=[])
    data = run / "_modelrun_datasets"
    for k in range(6):
        (data / f"icesee_enkf_{k:04d}.h5").write_bytes(b"\0")
    report = inspect_run_progress(run)
    d = report.primary_dataset()
    assert [s.step for s in d.io_steps] == list(range(6))
    assert d.resume_steps == ()
    assert report.resume.possible is False
    assert "missing 0, 1, 2" in report.resume.reason


def test_no_checkpoint_falls_back_to_last_step_file(tmp_path):
    run = _full_run(tmp_path, nt=10, last_done_k=4, ckpt=False)
    report = inspect_run_progress(run)
    assert report.resume.possible is True and report.resume.next_step == 5
    assert "icesee_enkf_ens_0004.h5" in report.resume.reason
    # without a checkpoint the step comes from the run log, not the files
    assert report.assimilation_step() == ("5 of 10 steps", "assimilation progress bar in run log")


@pytest.mark.parametrize("key,value,expected", [
    ("restart_enabled", False, "restart_enabled is false"),
    ("force_fresh_start", True, "force_fresh_start is true"),
])
def test_params_that_disable_restart(tmp_path, key, value, expected):
    run = _full_run(tmp_path, nt=10, last_done_k=3, **{key: value})
    report = inspect_run_progress(run)
    assert report.resume.possible is False and expected in report.resume.reason


def test_k_start_override_wins(tmp_path):
    run = _full_run(tmp_path, nt=10, last_done_k=5, k_start_override=2)
    report = inspect_run_progress(run)
    assert report.resume.possible is True and report.resume.next_step == 2


def test_crash_checkpoint_and_error_lines(tmp_path):
    run = _full_run(tmp_path, nt=10, last_done_k=3)
    ckpt = run / "_modelrun_datasets/_checkpoints/icesee_ckpt.json"
    payload = json.loads(ckpt.read_text())
    payload["crash_message"] = "<b>solver diverged</b>"
    ckpt.write_text(json.dumps(payload))
    with (run / "run.log").open("a") as fh:
        fh.write("[ICESEE] An error occurred on in icesee_model_data_assimilation_full_parallel: boom\n")
        fh.write("[ICESEE][RESTART] Checkpoint saved after error; you can restart safely.\n")
    report = inspect_run_progress(run)
    assert report.checkpoints()[0].crash_message == "<b>solver diverged</b>"
    assert report.log.crash_checkpoint_saved is True
    assert any("An error occurred" in line for line in report.log.error_lines)


def test_resumed_run_log_is_reported(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "icesee-enkf-12345.out").write_text(
        "[ICESEE][RESTART] Resuming at k=7 (nt=20); km=2\n"
    )
    report = inspect_run_progress(run)
    assert report.assimilation_step() == ("resumed at k=7 (nt=20)", "run log")
    assert report.log.sources == ("icesee-enkf-12345.out",)


# ─────────────────────────────────────────────────────────────────────────────
# corrupted / oversized / escaping inputs
# ─────────────────────────────────────────────────────────────────────────────
def test_corrupt_checkpoint(tmp_path):
    run = _full_run(tmp_path, nt=10, last_done_k=3)
    (run / "_modelrun_datasets/_checkpoints/icesee_ckpt.json").write_text('{"last_done_k": 3,')
    report = inspect_run_progress(run)
    ckpt = report.checkpoints()[0]
    assert ckpt.state == "corrupt" and ckpt.last_done_k is None
    assert report.resume.possible is False
    assert "load_checkpoint would fail" in report.resume.reason
    # the step is NOT taken from a corrupt checkpoint
    assert report.assimilation_step()[1] == "assimilation progress bar in run log"


def test_checkpoint_without_last_done_k_falls_back_to_step_files(tmp_path):
    run = _full_run(tmp_path, nt=10, last_done_k=3)
    (run / "_modelrun_datasets/_checkpoints/icesee_ckpt.json").write_text('{"nt": 10}')
    report = inspect_run_progress(run)
    assert report.checkpoints()[0].state == "invalid"
    assert report.resume.possible is True and report.resume.next_step == 4


def test_non_object_checkpoint(tmp_path):
    run = _full_run(tmp_path, nt=10, last_done_k=3)
    (run / "_modelrun_datasets/_checkpoints/icesee_ckpt.json").write_text("[1, 2]")
    assert inspect_run_progress(run).checkpoints()[0].state == "corrupt"


def test_oversized_checkpoint_is_not_parsed(tmp_path):
    run = _full_run(tmp_path, nt=10, last_done_k=3)
    big = {"last_done_k": 3, "pad": "x" * (rm.MAX_CHECKPOINT_BYTES + 10)}
    (run / "_modelrun_datasets/_checkpoints/icesee_ckpt.json").write_text(json.dumps(big))
    report = inspect_run_progress(run)
    ckpt = report.checkpoints()[0]
    assert ckpt.state == "oversized" and ckpt.last_done_k is None
    assert report.resume.possible is None


def test_oversized_log_only_tail_is_parsed(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "MAX_LOG_TAIL_BYTES", 4096)
    run = tmp_path / "run"
    run.mkdir()
    with (run / "run.log").open("w") as fh:
        fh.write("[ICESEE] Launching early with data assimilation using the EnKF filter across 2 MPI ranks.\n")
        fh.write("noise line\n" * 2000)
        fh.write("[ICESEE] Assimilation progress (4 ranks):  50%|##  | 5/10 [00:05<00:05]\n")
    report = inspect_run_progress(run)
    assert report.log.truncated is True
    assert report.log.model is None                     # beyond the bound: not reported
    assert (report.log.progress_done, report.log.progress_total) == (5, 10)


def test_oversized_params_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "MAX_PARAMS_BYTES", 64)
    run = _full_run(tmp_path, nt=10, last_done_k=3)
    report = inspect_run_progress(run)
    assert report.params == {}
    # the checkpoint alone still identifies the full-parallel driver
    assert report.resume.driver == "full"


def test_symlink_escape_is_skipped(tmp_path):
    outside = tmp_path / "outside"
    (outside / "_checkpoints").mkdir(parents=True)
    (outside / "_checkpoints" / "icesee_ckpt.json").write_text(json.dumps({"last_done_k": 99, "nt": 100}))
    (outside / "secret.log").write_text("[ICESEE] Fresh start at k=0 (nt=999)\n")
    run = tmp_path / "run"
    run.mkdir()
    os.symlink(outside, run / "_modelrun_datasets")
    os.symlink(outside / "secret.log", run / "run.log")
    report = inspect_run_progress(run)
    assert report.dataset_dirs == ()
    assert report.checkpoints() == []
    assert report.log.sources == ()
    assert set(report.skipped) == {"_modelrun_datasets", "run.log"}
    assert report.assimilation_step() == (NOT_REPORTED, "")


def test_contained_symlink_dir_is_not_followed_twice(tmp_path):
    run = _full_run(tmp_path, nt=10, last_done_k=3)
    os.symlink(run / "_modelrun_datasets", run / "alias")
    report = inspect_run_progress(run)
    assert [d.path for d in report.dataset_dirs] == ["_modelrun_datasets"]
    assert report.skipped == ()


def test_walk_entry_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "MAX_WALK_ENTRIES", 5)
    run = tmp_path / "run"
    run.mkdir()
    for i in range(20):
        (run / f"f{i}.txt").write_text("x")
    assert inspect_run_progress(run).walk_truncated is True


def test_walk_depth_bound(tmp_path):
    run = tmp_path / "run"
    deep = run.joinpath(*[f"d{i}" for i in range(rm.MAX_WALK_DEPTH + 1)])
    (deep / "_checkpoints").mkdir(parents=True)
    (deep / "_checkpoints" / "icesee_ckpt.json").write_text('{"last_done_k": 1}')
    assert inspect_run_progress(run).checkpoints() == []


# ─────────────────────────────────────────────────────────────────────────────
# nothing reported / other drivers
# ─────────────────────────────────────────────────────────────────────────────
def test_empty_run_reports_nothing(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    report = inspect_run_progress(run)
    assert report.assimilation_step() == (NOT_REPORTED, "")
    assert report.ensemble_size() == (NOT_REPORTED, "")
    assert report.timings is None
    assert report.resume.driver is None and report.resume.possible is None
    rows = dict(report.summary_rows())
    assert rows["Driver"] == NOT_REPORTED
    assert rows["Resume possible"].startswith(NOT_REPORTED)


def test_missing_run_dir(tmp_path):
    report = inspect_run_progress(tmp_path / "nope")
    assert report.resume.reason == "run directory not found"


def test_serial_driver_has_no_restart(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    _params(run / "params.yaml", execution_mode=0, Nens=30)
    report = inspect_run_progress(run)
    assert report.resume.driver == "serial" and report.resume.possible is False
    assert report.ensemble_size() == ("30 (configured)", "params.yaml")


def test_timing_parser_takes_last_table_and_ignores_unknown_rows():
    first = _timing_table(4, {"Forecast Step Time": 10.0})
    second = _timing_table(8, {"Forecast Step Time": 5.0, "Made Up Row": 1.0})
    parsed = rm.parse_timing_text(first + "between\n" + second, "x.log")
    assert parsed.tables_found == 2 and parsed.reported_ranks == 8
    assert parsed.phases == (("Forecast Step Time", 5.0),)


def test_timing_parser_without_table():
    assert rm.parse_timing_text("no table here\n║ Forecast Step Time 00:00:00:01.000 ║\n", "x") is None


def _partial_run(tmp_path: Path, members) -> Path:
    h5py = pytest.importorskip("h5py")
    import numpy as np

    run = tmp_path / "run"
    data = run / "_modelrun_datasets"
    data.mkdir(parents=True)
    _params(run / "params.yaml", execution_mode=1, Nens=4)
    with h5py.File(data / "icesee_ensemble_data.h5", "w") as f:
        f.create_dataset("ensemble", data=np.zeros((3, 4, 6)))
    for m in members:
        (data / f"ensemble_output_{m}.h5").write_bytes(b"\0")
    return run


def test_partial_driver_resume_is_conditional(tmp_path):
    report = inspect_run_progress(_partial_run(tmp_path, range(4)))
    assert report.resume.driver == "partial"
    assert report.resume.possible is None
    assert "slices 1..5" in report.resume.reason
    assert report.ensemble_size()[0] == "4"
    value, source = report.members_completed()
    assert value == NOT_REPORTED and "4 member exchange files" in source


def test_partial_driver_missing_member_blocks_resume(tmp_path):
    report = inspect_run_progress(_partial_run(tmp_path, [0, 1, 3]))
    assert report.resume.possible is False
    assert "members 2" in report.resume.reason


def test_partial_driver_corrupt_history(tmp_path):
    run = _partial_run(tmp_path, range(4))
    (run / "_modelrun_datasets/icesee_ensemble_data.h5").write_bytes(b"not hdf5")
    report = inspect_run_progress(run)
    assert report.resume.possible is None
    assert "not readable" in report.resume.reason


def test_monitor_is_reporting_only():
    """No ICESEE/MPI import and no write path: the monitor cannot change a
    run's numerics or files."""
    src = Path(rm.__file__).read_text()
    for forbidden in ("import ICESEE", "from ICESEE", "mpi4py", "write_text", "write_bytes",
                      '"w"', "'w'", '"a"', "os.remove", "unlink", "rmtree"):
        assert forbidden not in src, forbidden
