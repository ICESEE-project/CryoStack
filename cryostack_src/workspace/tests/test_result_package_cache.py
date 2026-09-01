"""Performance pass: WorkspaceManager caches the discovered ResultPackage per
run, keyed by the outputs path + metadata.json mtime, and never across users."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.workspace.manager import WorkspaceManager
from cryostack_src.workspace.models import RunInfo
from cryostack_src.workspace.identity import WorkspaceUser

_METADATA = {"schema": "cryostack.issm.results", "solutions": {}}


class _Widget:
    def __init__(self, value=""):
        self.value = value


class _Output:
    def __init__(self):
        self.lines: list[str] = []

    def __enter__(self):
        import builtins
        self._orig = builtins.print
        builtins.print = lambda *a, **k: self.lines.append(" ".join(str(x) for x in a))
        return self

    def __exit__(self, *exc):
        import builtins
        builtins.print = self._orig
        return False

    def clear_output(self, *a, **k):
        self.lines.clear()


def _mgr(root):
    return WorkspaceManager(
        owner=WorkspaceUser(user_id="alice", source="cryostack-auth"),
        workspace_root=str(root), status={}, session={"id": "s"},
        example_dir=_Widget(str(root)), model=_Widget("issm"), backend=_Widget("c"),
        file_picker=_Widget(), file_editor=_Widget(), log_output=None,
        results_output=None, cluster_host=_Widget(""), cluster_user=_Widget(""),
        cluster_port=_Widget(1), access_mode=_Widget(""),
        normalize_remote_path=lambda p: p, connector_fetch_archive=None,
        should_use_connector=lambda: False, connector_ssh=None, ssh_run=None,
        cluster_name=_Widget(""),
    )


def _register_with_outputs(m, run_id="run-1"):
    run = m.register_run(RunInfo(
        id=run_id, name=run_id, model="issm", backend="c",
        execution_mode="remote", status="completed", created=datetime.now(), jobid="j"))
    outputs = run.workspace_directory / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "metadata.json").write_text(json.dumps(_METADATA), encoding="utf-8")
    return run, outputs / "metadata.json"


def _count_reads(monkeypatch):
    import cryostack_src.workspace.manager as m
    calls = {"n": 0}
    real = m._result_reader_for("issm")

    def counting_reader(model):
        def read(path):
            calls["n"] += 1
            return real(path)
        return read

    monkeypatch.setattr(m, "_result_reader_for", counting_reader)
    return calls


def test_repeated_lookups_do_not_rescan(tmp_path, monkeypatch):
    m = _mgr(tmp_path)
    _register_with_outputs(m)
    calls = _count_reads(monkeypatch)
    for _ in range(10):
        m.result_package_for_run("run-1")
    assert calls["n"] == 1


def test_metadata_mtime_change_invalidates(tmp_path, monkeypatch):
    m = _mgr(tmp_path)
    _run, meta = _register_with_outputs(m)
    calls = _count_reads(monkeypatch)
    m.result_package_for_run("run-1")
    time.sleep(0.01)
    meta.write_text(json.dumps({**_METADATA, "changed": True}), encoding="utf-8")
    os.utime(meta, None)
    m.result_package_for_run("run-1")
    assert calls["n"] == 2


def test_explicit_invalidation(tmp_path):
    m = _mgr(tmp_path)
    _register_with_outputs(m)
    m.result_package_for_run("run-1")
    assert "run-1" in m._result_pkg_cache
    m.invalidate_result_package_cache("run-1")
    assert "run-1" not in m._result_pkg_cache


def test_delete_run_drops_the_cache_entry(tmp_path):
    m = _mgr(tmp_path)
    _register_with_outputs(m)
    m.result_package_for_run("run-1")
    m.delete_run("run-1")
    assert "run-1" not in m._result_pkg_cache


def test_cache_is_per_manager_instance(tmp_path):
    a = _mgr(tmp_path / "a")
    b = _mgr(tmp_path / "b")
    _register_with_outputs(a)
    a.result_package_for_run("run-1")
    assert b._result_pkg_cache == {}
    assert a._result_pkg_cache is not b._result_pkg_cache


def test_only_one_fetch_in_flight_per_run(tmp_path):
    out = _Output()
    m = WorkspaceManager(
        owner=WorkspaceUser(user_id="alice", source="cryostack-auth"),
        workspace_root=str(tmp_path), status={}, session={"id": "s"},
        example_dir=_Widget(str(tmp_path)), model=_Widget("issm"), backend=_Widget("c"),
        file_picker=_Widget(), file_editor=_Widget(), log_output=None,
        results_output=out, cluster_host=_Widget(""), cluster_user=_Widget(""),
        cluster_port=_Widget(1), access_mode=_Widget(""),
        normalize_remote_path=lambda p: p, connector_fetch_archive=None,
        should_use_connector=lambda: False, connector_ssh=None, ssh_run=None,
        cluster_name=_Widget(""),
    )
    run, _ = _register_with_outputs(m)
    m._selected_run_id = run.id

    calls = {"n": 0}
    reentered = {"n": 0}

    def fake_locked():
        calls["n"] += 1
        # simulate the transfer re-entering refresh_results (e.g. a repeat click
        # delivered while the first is still running)
        if m.refresh_results() is None:
            reentered["n"] += 1
        return None

    m._refresh_results_locked = fake_locked
    m.refresh_results()
    assert calls["n"] == 1            # the inner call was rejected, not run again
    assert reentered["n"] == 1
    assert any("already in progress" in ln for ln in out.lines)
    # lock released afterwards
    assert m._fetch_in_flight == set()
