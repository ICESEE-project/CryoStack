"""Application-layer validation of the Icepack pipeline, on either side of the
execution step (Firedrake is not installed here, so the run itself is not
executed):

    discover example -> run target
      -> [ Icepack executes, producing figures / *.h5 ]
      -> neutral output collector (run for real, stdlib only)
      -> IcepackResultPackage discovery -> honest status, no invented fields

Confirms the collector's metadata.json is consumed correctly by the same
discover_results the Results tab uses.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from cryostack_src.models import get_model_adapter
from cryostack_src.models.icepack import discover_results
from cryostack_src.models.icepack.postprocess import SCHEMA, build_postprocess


def _simulate_icepack_run(example_dir: Path, run_dir: Path):
    """Stand in for a real Icepack run: it produces a couple of figures and a
    Firedrake-style checkpoint, then the collector runs exactly as the sbatch
    body would."""
    (example_dir / "ice-shelf.py").write_text("import icepack\n")   # the input
    started = _now()
    # --- the "run" produces artifacts ---
    (example_dir / "velocity.png").write_bytes(b"\x89PNG\r\n")
    (example_dir / "thickness_final.png").write_bytes(b"\x89PNG\r\n")
    (example_dir / "checkpoint.h5").write_bytes(b"\x89HDF\r\n")
    # --- the collector (verbatim from the adapter) ---
    script = run_dir / "cryostack_icepack_postprocess.py"
    script.write_text(build_postprocess())
    env = dict(os.environ)
    env.update(CRYOSTACK_RUN_DIR=str(run_dir),
               CRYOSTACK_EXAMPLE_DIR=str(example_dir),
               CRYOSTACK_RUN_STARTED=str(started))
    p = subprocess.run([sys.executable, str(script)], capture_output=True,
                       text=True, env=env)
    assert p.returncode == 0, p.stderr


def _now():
    import time
    return time.time()


def test_full_icepack_pipeline_offline(tmp_path):
    adapter = get_model_adapter("icepack")

    example = tmp_path / "ice-shelf"
    example.mkdir()
    run = tmp_path / "run"
    run.mkdir()

    # discovery + run target
    _simulate_icepack_run(example, run)
    assert adapter.example_runnable(example)
    names = [p.name for p in example.iterdir()]
    assert adapter.choose_run_target(names) == "ice-shelf.py"

    # the collector wrote a conformant, honest package
    meta = json.loads((run / "outputs" / "metadata.json").read_text())
    assert meta["schema"] == SCHEMA
    assert meta["status"] == "artifacts"
    assert meta["solutions"] == [] and meta["fields"] == []
    assert set(meta["figures"]) == {"velocity.png", "thickness_final.png"}
    assert meta["model_files"] == ["checkpoint.h5"]

    # the Results-tab reader consumes it
    pkg = discover_results(run)
    assert pkg.status == "artifacts"
    assert pkg.schema == SCHEMA
    assert pkg.is_readable() is False                 # honest: no field reader
    assert pkg.available_solutions() == []
    figs = [Path(f).name for f in pkg.legacy_artifacts()["figures"]]
    assert set(figs) == {"velocity.png", "thickness_final.png"}
    assert pkg.recommended_plots() == []

    # the input script is NOT collected as a figure/artifact
    assert "ice-shelf.py" not in meta["figures"]
    assert not (run / "outputs" / "model" / "ice-shelf.py").exists()
