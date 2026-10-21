"""A user's own plotting code: copied into their workspace, edited, and drawn
in a sandbox that can read but never change the run's outputs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from icesee_jupyter_book.core import results_service, run_records, user_plots
from icesee_jupyter_book.core.tests.test_icesee_local_jobs import _launch, _wait, fake_example  # noqa: F401
from icesee_jupyter_book.core.user_plots import PlotFileError, PlotWorkspace

pytestmark = pytest.mark.skipif(not results_service.sandbox_available(), reason="bubblewrap is not installed")

OVERRIDE = '''
from ICESEE.src.postprocessing.views import ViewSpec, get_view, register

base = get_view("lorenz.state_estimation")
register(ViewSpec(id=base.id, title="My state estimation", description=base.description,
                  source="my plotting code", build=base.build, options=base.options))
'''


def _digest(directory: Path) -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.glob("*.h5"))}


@pytest.fixture
def finished_run(tmp_path, fake_example):  # noqa: F811
    prepared, job = _launch(tmp_path, fake_example)
    st = _wait(job)
    from icesee_jupyter_book.core import run_launcher

    run_launcher.finalize_local_run(prepared.run_dir, st)
    info = run_records.load_run(tmp_path / "runs", prepared.run_id)
    plots = PlotWorkspace(tmp_path / "owner" / "icesee_plots", "Fake", results_service.example_dir(info))
    return info, plots


def _outputs(info) -> Path:
    return next(Path(info.workspace_directory).glob("**/_modelrun_datasets"))


def test_copy_is_the_users_and_imports_icesee_by_name(tmp_path, fake_example):  # noqa: F811
    plots = PlotWorkspace(tmp_path / "plots", "Fake", fake_example["base"])
    assert not plots.exists and plots.files() == []
    files = {f.path: f for f in plots.create()}
    assert {"results.yaml", "common.py", "README.md"} <= set(files)
    assert not any(f.modified for f in files.values())
    common = plots.open("common.py")
    assert "from ICESEE.src.postprocessing import diagnostics" in common
    assert "from ICESEE.src.postprocessing.views import" in common and "from ." not in common
    compile(common, "common.py", "exec")
    # the example is never written
    assert yaml.safe_load((fake_example["base"] / "results.yaml").read_text())["views"] == ["lorenz.state_estimation"]


def test_save_validates_and_reset_restores(tmp_path, fake_example):  # noqa: F811
    plots = PlotWorkspace(tmp_path / "plots", "Fake", fake_example["base"])
    with pytest.raises(PlotFileError):
        plots.save("common.py", "x = 1\n")             # no copy yet
    plots.create()
    issues = plots.save("common.py", "def broken(:\n")
    assert issues and issues[0].level == "error" and issues[0].line == 1
    assert "def broken" not in plots.open("common.py")   # not saved
    assert not plots.save("common.py", plots.open("common.py") + "\n# mine\n")
    assert next(f for f in plots.files() if f.path == "common.py").modified
    plots.reset("common.py")
    assert not next(f for f in plots.files() if f.path == "common.py").modified
    assert plots.save("results.yaml", "views: 3\nmodel_name: fake\n")[0].level == "error"
    assert plots.save("new_views.py", "X = 1\n") == [] and plots.open("new_views.py") == "X = 1\n"
    plots.reset("new_views.py")                        # a file ICESEE does not have: removed
    assert "new_views.py" not in {f.path for f in plots.files()}


@pytest.mark.parametrize("name", ["../escape.py", "sub/dir.py", ".hidden.py", "evil.sh", "/etc/passwd", ""])
def test_files_stay_inside_the_copy(tmp_path, fake_example, name):  # noqa: F811
    plots = PlotWorkspace(tmp_path / "plots", "Fake", fake_example["base"])
    plots.create()
    with pytest.raises(PlotFileError):
        plots.save(name, "x = 1\n")


def test_user_code_draws_its_own_figures_without_touching_outputs(finished_run):
    info, plots = finished_run
    outputs = _outputs(info)
    before = _digest(outputs)
    standard = results_service.discover(info, lifecycle_state="completed")
    shipped = results_service.render(standard, "lorenz.state_estimation")
    assert shipped.ok and not shipped.customized

    plots.create()
    assert not plots.save("mine.py", OVERRIDE)
    mine = results_service.discover(info, lifecycle_state="completed", plots=plots)
    assert mine.status == "ready", mine.message
    assert mine.view("lorenz.state_estimation")["customized"]
    out = results_service.render(mine, "lorenz.state_estimation")
    assert out.ok, out.message
    assert out.customized and out.title == "My state estimation" and out.source == "my plotting code"
    assert out.png.is_file() and out.png != shipped.png
    assert out.png.is_relative_to(Path(info.workspace_directory) / results_service.CACHE_DIR / "user")
    # the ICESEE figure is still ICESEE's, and the outputs are byte-identical
    again = results_service.render(standard, "lorenz.state_estimation")
    assert again.ok and not again.customized and again.png == shipped.png
    assert _digest(outputs) == before

    # editing the code redraws (the cache is keyed by the code)
    plots.save("mine.py", OVERRIDE.replace("My state estimation", "Edited title"))
    redrawn = results_service.render(results_service.discover(info, lifecycle_state="completed", plots=plots),
                                     "lorenz.state_estimation")
    assert redrawn.ok and redrawn.title == "Edited title" and not redrawn.cached


ATTACKS = {
    "overwrite outputs": "import glob\nfor p in glob.glob('{out}/*.h5'):\n    open(p, 'wb').write(b'x')\n",
    "delete outputs": "import os, glob\nfor p in glob.glob('{out}/*.h5'):\n    os.remove(p)\n",
    "network": "import socket\nsocket.create_connection(('1.1.1.1', 53), timeout=3)\n",
    "read the code checkout": "open('{repo}/README.md', 'rb').read()\n",
    "read other users": "open('{runs}/other-user/secret.txt').read()\n",
}


@pytest.mark.parametrize("attack", sorted(ATTACKS))
def test_user_code_cannot_change_outputs_or_reach_out(finished_run, attack):
    info, plots = finished_run
    outputs = _outputs(info)
    before = _digest(outputs)
    plots.create()
    other = Path(info.workspace_directory).parent / "other-user"
    other.mkdir()
    (other / "secret.txt").write_text("not yours")
    code = ATTACKS[attack].format(out=outputs, repo=results_service.REPO, runs=Path(info.workspace_directory).parent)
    assert not plots.save("attack.py", code)
    res = results_service.discover(info, lifecycle_state="completed", plots=plots)
    assert res.status == "error"
    assert "attack.py line" in res.message, res.message
    assert ("Read-only file system" in res.message or "Network is unreachable" in res.message
            or "No such file or directory" in res.message), res.message
    assert _digest(outputs) == before


def test_errors_in_user_code_name_the_file_and_line(finished_run):
    info, plots = finished_run
    plots.create()
    plots.save("mine.py", OVERRIDE.replace("build=base.build", "build=lambda ctx, o: 1 / 0"))
    res = results_service.discover(info, lifecycle_state="completed", plots=plots)
    assert res.status == "ready"
    out = results_service.render(res, "lorenz.state_estimation")
    assert not out.ok and "mine.py line" in out.message and "ZeroDivisionError" in out.message


def test_reports_from_user_code_are_not_trusted(finished_run, tmp_path):
    info, plots = finished_run
    plots.create()
    run_dir = Path(info.workspace_directory)
    cache = results_service.user_cache_dir(run_dir, plots)
    cache.mkdir(parents=True)
    elsewhere = tmp_path / "someone-else"
    elsewhere.mkdir()
    (cache / f"describe-{results_service._run_fingerprint(run_dir)}.json").write_text(
        json.dumps({"ok": True, "views": [], "data_dir": str(elsewhere)}))
    res = results_service.discover(info, lifecycle_state="completed", plots=plots)
    assert res.status == "error" and "outside this run" in res.message


def test_without_bubblewrap_user_code_is_not_run(finished_run, monkeypatch):
    info, plots = finished_run
    plots.create()
    monkeypatch.setattr(results_service.shutil, "which", lambda _name: None)
    res = results_service.discover(info, lifecycle_state="completed", plots=plots)
    assert res.status == "error" and "bubblewrap" in res.message
    assert results_service.discover(info, lifecycle_state="completed").status == "ready"
