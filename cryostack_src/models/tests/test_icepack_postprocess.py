"""Icepack neutral output collector -- gathers a run's figures / native files
into outputs/ and writes an HONEST metadata.json (no fabricated fields)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from cryostack_src.models.icepack.postprocess import SCHEMA, build_postprocess


def _run_collector(run_dir: Path, example_dir: Path, *, started: float | None = None):
    script = run_dir / "cryostack_icepack_postprocess.py"
    script.write_text(build_postprocess(), encoding="utf-8")
    env = {
        "CRYOSTACK_RUN_DIR": str(run_dir),
        "CRYOSTACK_EXAMPLE_DIR": str(example_dir),
        "PATH": "/usr/bin:/bin",
    }
    if started is not None:
        env["CRYOSTACK_RUN_STARTED"] = str(started)
    p = subprocess.run([sys.executable, str(script)], capture_output=True,
                       text=True, env=env)
    assert p.returncode == 0, p.stderr
    return json.loads((run_dir / "outputs" / "metadata.json").read_text())


def test_collects_figures_and_native_files_into_the_neutral_shape(tmp_path):
    ex = tmp_path / "example"
    ex.mkdir()
    (ex / "velocity.png").write_bytes(b"\x89PNG\r\n")
    (ex / "thickness.pdf").write_bytes(b"%PDF-1.4")
    (ex / "state.h5").write_bytes(b"\x89HDF\r\n")
    (ex / "notes.txt").write_text("not an artifact")
    run = tmp_path / "run"
    run.mkdir()

    meta = _run_collector(run, ex)

    assert meta["schema"] == SCHEMA
    assert meta["model"] == "icepack"
    assert meta["status"] == "artifacts"
    # NEVER fabricated
    assert meta["solutions"] == [] and meta["fields"] == []
    assert "note" in meta
    assert set(meta["figures"]) == {"velocity.png", "thickness.pdf"}
    assert meta["model_files"] == ["state.h5"]

    out = run / "outputs"
    assert (out / "figures" / "velocity.png").is_file()
    assert (out / "figures" / "thickness.pdf").is_file()
    assert (out / "model" / "state.h5").is_file()
    assert not (out / "figures" / "notes.txt").exists()


def test_empty_run_is_reported_honestly(tmp_path):
    ex = tmp_path / "example"; ex.mkdir()
    (ex / "input.py").write_text("print('hi')")
    run = tmp_path / "run"; run.mkdir()

    meta = _run_collector(run, ex)
    assert meta["status"] == "empty"
    assert meta["figures"] == [] and meta["model_files"] == []


def test_run_started_marker_excludes_preexisting_inputs(tmp_path):
    ex = tmp_path / "example"; ex.mkdir()
    old = ex / "reference_mesh.h5"
    old.write_bytes(b"\x89HDF\r\n")
    old_time = time.time() - 3600
    import os
    os.utime(old, (old_time, old_time))
    marker = time.time() - 60
    (ex / "result_field.png").write_bytes(b"\x89PNG\r\n")   # fresh
    run = tmp_path / "run"; run.mkdir()

    meta = _run_collector(run, ex, started=marker)
    assert meta["figures"] == ["result_field.png"]
    assert meta["model_files"] == []                       # old mesh excluded
    assert any(s["name"] == "reference_mesh.h5" for s in meta["skipped"])


def test_script_is_stdlib_only():
    src = build_postprocess()
    assert "import icepack" not in src and "import firedrake" not in src
