"""Opt-in: one real LIVIST generation with the isolated environment.

    CRYOSTACK_LIVIST_INTEGRATION=1 python -m pytest .../test_livist_integration.py

Uses the points of LIVIST's own test fixture (tests/data/sample_data.json) as
a small local attenuation input and runs the real ``scripts/generate``
(both modes; the conductivity mode reads borehole data from source.coop, so
network access is needed). Skips cleanly when not requested or when the
environment (``CRYOSTACK_LIVIST_ENV`` or ~/.cryostack-envs/livist) is absent.
"""
import csv
import json
import os
from pathlib import Path

import pytest

from icesee_jupyter_book.applications.livist import settings, toolchain, worker
from icesee_jupyter_book.applications.livist.store import LivistStore

REAL_ENV = Path(os.environ.get("CRYOSTACK_LIVIST_INTEGRATION_ENV") or settings.DEFAULT_ENV)

pytestmark = pytest.mark.skipif(
    os.environ.get("CRYOSTACK_LIVIST_INTEGRATION") != "1"
    or not (REAL_ENV / "env.json").is_file(),
    reason="set CRYOSTACK_LIVIST_INTEGRATION=1 with a built LIVIST environment",
)


def test_real_generation_on_livist_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_LIVIST_ENV", str(REAL_ENV))
    fixture = settings.source_dir() / "tests" / "data" / "sample_data.json"
    points = json.loads(fixture.read_text())["points"]
    roots = tmp_path / "inputs"
    roots.mkdir()
    with (roots / "sample.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["x", "y", "atten_rate_C0"])
        for p in points:
            writer.writerow([p["x"], p["y"], p["attenuation_rate"]])
    monkeypatch.setenv("CRYOSTACK_LIVIST_INPUT_ROOTS", str(roots))
    assert toolchain.health(refresh=True)["ready"]

    store = LivistStore(tmp_path / "livist.db")
    workdir = tmp_path / "job"
    workdir.mkdir()
    store.queue_job(job_id="f" * 32, owner_id="it", workdir=str(workdir), timeout_s=1800,
                    max_active=1, sources=[{"name": "sample", "kind": "local",
                                            "location": str(roots / "sample.csv")}])
    status = worker.run(store, "f" * 32)
    log = (workdir / "logs" / "generate.log").read_text(errors="replace")
    assert status == "completed", log[-3000:]
    job = store.get_job("f" * 32)
    assert job["validation_status"] == "passed", (workdir / "manifest.json").read_text()

    manifest = json.loads((workdir / "manifest.json").read_text())
    assert manifest["validation"]["deep"] is True
    assert manifest["livist"]["commit"] == toolchain.source_commit()
    # the pure-ice inversion reproduces LIVIST's own reference temperatures
    import subprocess
    script = ("import sys, pyarrow.parquet as pq; "
              "print(pq.read_table(sys.argv[1]).column('temperature').to_pylist()[0])")
    first = subprocess.run([str(REAL_ENV / "venv" / "bin" / "python"), "-I", "-c", script,
                            str(workdir / "data" / "temperature-sample-pure-ice.parquet")],
                           capture_output=True, text=True, check=True).stdout
    assert float(first) == pytest.approx(points[0]["pure"]["temperature_K"], rel=1e-6)
