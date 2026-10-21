"""Runs recorded before the storage migration stay visible.

The migration copied every user workspace to the durable data root but left
the old absolute ``workspace`` path inside each run manifest; the reader
rejected those, so every earlier run vanished from the Runs panel.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.models.submission import _storage_preflight
from cryostack_src.workspace.manifest import read_manifest, write_manifest
from cryostack_src.workspace.models import RunInfo


def _moved_run(tmp_path):
    old = tmp_path / "old-install" / "users" / "u" / ".cryostack" / "runs" / "r1"
    run = RunInfo(id="r1", name="issm_container", model="issm", backend="container",
                  execution_mode="remote", status="completed", created=datetime(2026, 9, 2),
                  results_directory=old / "results", figures_directory=old / "figures",
                  remote_directory=Path("/storage/home/u/icesheets/runs/issm_container"))
    write_manifest(run, old)
    new = tmp_path / "data" / "workspace" / "users" / "u" / ".cryostack" / "runs" / "r1"
    new.parent.mkdir(parents=True)
    os.rename(old, new)
    return new


def test_a_moved_workspace_is_read_with_its_local_paths_following(tmp_path):
    new = _moved_run(tmp_path)
    run = read_manifest(new / ".cryostack-run.json")
    assert run.workspace_directory == new.resolve()
    assert run.results_directory == new.resolve() / "results"
    assert run.figures_directory == new.resolve() / "figures"
    # remote paths are not local workspace paths and stay as recorded
    assert run.remote_directory == Path("/storage/home/u/icesheets/runs/issm_container")


def test_rewriting_a_moved_manifest_records_the_new_workspace(tmp_path):
    new = _moved_run(tmp_path)
    run = read_manifest(new / ".cryostack-run.json")
    write_manifest(run, run.workspace_directory)
    data = json.loads((new / ".cryostack-run.json").read_text())["run"]
    assert data["workspace"] == str(new.resolve())


def test_storage_preflight_passes_on_writable_storage_and_stops_when_full(tmp_path):
    ok = subprocess.run(["bash", "-c", _storage_preflight(str(tmp_path))], capture_output=True, text=True)
    assert ok.returncode == 0 and not list(tmp_path.iterdir())  # probe removed
    blocked = tmp_path / "ro"
    blocked.mkdir()
    blocked.chmod(0o500)
    try:
        full = subprocess.run(["bash", "-c", _storage_preflight(str(blocked))], capture_output=True, text=True)
    finally:
        blocked.chmod(0o700)
    assert full.returncode == 28
    assert "disk quota is exceeded" in full.stdout
