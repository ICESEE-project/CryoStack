"""ICESEE run-directory parameterisation (Phase C-1).

`run_dir()` previously always used a process-global `BOOK/icesee_runs/<ts>` with
second granularity + `exist_ok=True` -- two authenticated users (or two clicks)
in the same second shared the directory. It now accepts a per-user `base` and an
explicit `name` so the caller can guarantee isolation. Default behaviour is
unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.core import local_runner
from icesee_jupyter_book.core.local_runner import run_dir


def test_default_location_is_unchanged():
    rd = run_dir()
    assert rd.parent == local_runner.BOOK / "icesee_runs"
    assert (rd / "results").is_dir() and (rd / "figures").is_dir()


def test_base_scopes_the_run_under_a_per_user_root(tmp_path):
    alice = tmp_path / "users" / "alice" / "runs"
    rd = run_dir(base=alice)
    assert alice in rd.parents
    assert (rd / "results").is_dir() and (rd / "figures").is_dir()


def test_explicit_name_removes_same_second_collisions(tmp_path):
    a = run_dir(base=tmp_path, name="run-0001")
    b = run_dir(base=tmp_path, name="run-0002")
    assert a != b
    assert a.name == "run-0001" and b.name == "run-0002"


def test_two_user_roots_never_intersect(tmp_path):
    a = run_dir(base=tmp_path / "alice", name="r1")
    b = run_dir(base=tmp_path / "bob", name="r1")
    assert a != b
    assert not str(b).startswith(str(tmp_path / "alice"))


def test_run_local_example_forwards_the_base(tmp_path, monkeypatch):
    """run_local_example threads run_dir_base/name through without running the
    DA subprocess."""
    captured = {}

    def _fake_popen(cmd, **kw):
        captured["cwd"] = kw.get("cwd")

        class _P:
            stdout = iter(())
            def wait(self):
                return 0
        return _P()

    monkeypatch.setattr(local_runner.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(local_runner, "find_run_script", lambda cfg: tmp_path / "run.py")
    monkeypatch.setattr(local_runner, "find_report_notebook", lambda cfg: None)
    (tmp_path / "run.py").write_text("")

    res = local_runner.run_local_example(
        {"base": tmp_path}, {"enkf-parameters": {}},
        run_dir_base=tmp_path / "users" / "carol" / "runs", run_dir_name="run-xyz",
    )
    assert res.run_dir.name == "run-xyz"
    assert (tmp_path / "users" / "carol" / "runs") in res.run_dir.parents
    assert captured["cwd"] == str(res.run_dir)
    assert (res.run_dir / "params.yaml").is_file()
