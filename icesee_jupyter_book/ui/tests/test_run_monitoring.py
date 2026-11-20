"""Launch/Submit -> Monitor (run log, live) -> Results in ICESEE and
CryoLauncher: the log view opens at once, shows the state and what happens
next instead of a blank panel, keeps updating until the run ends, and moves
to Results when it completed. No real model, cluster or AWS account is used."""
from __future__ import annotations

import gc
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import ipywidgets as W
import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.core.remote_poll import RemoteStatusPoller
from icesee_jupyter_book.ui.icesee_workflow.monitor import RunFollower, monitor_banner


def _cell(fn, name):
    return fn.__closure__[fn.__code__.co_freevars.index(name)]


# ── the shared follower and banner ──────────────────────────────────────────
def _follower():
    seen = []
    f = RunFollower(open_monitor=lambda rid: seen.append(("monitor", rid)),
                    open_results=lambda rid: seen.append(("results", rid)))
    return f, seen


def test_follower_opens_monitor_then_results_on_completion():
    f, seen = _follower()
    f.start("r1")
    assert seen == [("monitor", "r1")]
    for state in ("submitted", "queued", "running"):
        assert f.update("r1", state) == "following"
    assert f.update("other", "completed") == "ignored"
    assert f.update("r1", "completed") == "results"
    assert seen[-1] == ("results", "r1") and f.run_id is None


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_follower_stays_on_the_log_when_the_run_did_not_complete(state):
    f, seen = _follower()
    f.start("r1")
    assert f.update("r1", state) == "finished"
    assert ("results", "r1") not in seen


def test_leaving_the_log_by_hand_stops_the_automatic_move():
    f, seen = _follower()
    f.start("r1")
    f.navigated("Monitor")
    f.navigated("Editor")
    assert f.update("r1", "completed") == "finished" and ("results", "r1") not in seen


def test_a_run_that_finished_before_following_started_still_moves_on():
    seen = []
    f = RunFollower(open_monitor=lambda rid: seen.append("monitor"), open_results=lambda rid: seen.append("results"),
                    state_of=lambda rid: "completed")
    f.start("r1")
    assert seen == ["monitor", "results"]


def _run(state, **kw):
    return SimpleNamespace(id="r1", status=state, metadata={}, created=datetime(2026, 10, 21, 12, 0, 5),
                           finished=None, execution_mode="remote", **kw)


@pytest.mark.parametrize("state,words", [("submitted", "Waiting for the scheduler"), ("queued", "Queued"),
                                         ("running", "Running"), ("completed", "Results"),
                                         ("failed", "Failed"), ("cancelled", "Cancelled")])
def test_banner_names_every_state(state, words):
    html = monitor_banner(_run(state), every=30)
    assert words in html and 'aria-live="polite"' in html
    assert ("Checked every 30 s" in html) == (state in ("submitted", "queued", "running"))


def test_banner_explains_missing_logs_and_connection_errors():
    html = monitor_banner(_run("queued"), every=60, error="Could not reach the cluster (timeout).",
                          no_log="No output from the cluster yet.")
    assert "Could not reach the cluster" in html and "No output from the cluster yet" in html
    assert "No output" not in monitor_banner(_run("completed"), no_log="No output from the cluster yet.")
    assert "Launch a run" in monitor_banner(None)


def test_remote_poller_fetches_the_log_and_reports_failures():
    run = SimpleNamespace(execution_mode="remote", jobid="7", status="running", metadata={})
    fetched, failures, results = [], [], [RuntimeError("timeout"), {"returncode": 0, "state": "RUNNING"}]

    def check(_jobid):
        item = results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    poller = RemoteStatusPoller(selected=lambda: run, check=check, apply=lambda r, u: None,
                                fetch_log=fetched.append, on_failure=lambda r, t: failures.append(t))
    assert poller.tick() == "failed" and "Could not reach the cluster" in failures[-1]
    assert "Retrying in" in failures[-1] and not fetched
    poller.tick()
    assert fetched == [run] and failures[-1] == ""


# ── ICESEE ──────────────────────────────────────────────────────────────────
from icesee_jupyter_book.ui.tests.test_icesee_workflow_ui import (  # noqa: E402
    FAKE_KEY, PARAMS, _cls, _launch_card, _wait, _walk, page)  # noqa: F401  (page is a fixture)


def _icesee_workspace(ui):
    from icesee_jupyter_book.ui.icesee_workflow import RunWorkspace
    ws_box = _cls(ui, "cryostack-output-workspace")[0]
    return next(o for o in gc.get_objects() if isinstance(o, RunWorkspace) and o.container is ws_box)


def _icesee_launch_fn(ui):
    from icesee_jupyter_book.ui.icesee_workflow import LaunchPanel
    card = _launch_card(ui)
    in_card = {id(w) for w in _walk(card)}
    panel = next(o for o in gc.get_objects() if isinstance(o, LaunchPanel) and id(o.review) in in_card)
    return panel.on_launch


def _pick_fake(ui):
    example = next(w for w in _walk(ui) if isinstance(w, W.Dropdown) and FAKE_KEY in w.options)
    example.value = FAKE_KEY


def _hero(ui):
    return next(w for w in _walk(_launch_card(ui)) if isinstance(w, W.Button) and "icw-btn-hero" in w._dom_classes)


def test_icesee_local_launch_opens_the_run_log_then_results(page, tmp_path):
    ex = tmp_path / "apps" / "fake_ex" / "run_da_fake.py"
    ex.write_text("import time\nprint('[fake] started', flush=True)\ntime.sleep(2)\n" + ex.read_text())
    _pick_fake(page)
    ws = _icesee_workspace(page)
    _hero(page).click()
    assert _wait(lambda: ws.tabs.value == "Logs", 30), ws.tabs.value
    assert ws.log_kind.value == "Run output"
    assert _wait(lambda: "Running" in ws.log_status.value or "Preparing" in ws.log_status.value, 30)
    assert _wait(lambda: "[fake] started" in ws.log_view.value, 30), ws.log_view.value[:300]
    assert _wait(lambda: ws.tabs.value == "Results", 60), ws.tabs.value


def test_icesee_failed_local_run_stays_on_the_log_with_the_failure(page, tmp_path):
    (tmp_path / "apps" / "fake_ex" / "run_da_fake.py").write_text(
        "print('[fake] boom', flush=True)\nraise SystemExit(3)\n")
    _pick_fake(page)
    ws = _icesee_workspace(page)
    _hero(page).click()
    assert _wait(lambda: "Failed" in ws.log_status.value, 60), ws.log_status.value
    assert ws.tabs.value == "Logs" and "[fake] boom" in ws.log_view.value


def test_icesee_navigating_away_keeps_the_users_view(page, tmp_path):
    ex = tmp_path / "apps" / "fake_ex" / "run_da_fake.py"
    ex.write_text("import time\ntime.sleep(2)\n" + ex.read_text())
    _pick_fake(page)
    ws = _icesee_workspace(page)
    _hero(page).click()
    assert _wait(lambda: ws.tabs.value == "Logs", 30)
    ws.tabs.value = "Editor"
    assert _wait(lambda: any("Completed" in label for label, _v in ws.run_list.options), 60)
    assert ws.tabs.value == "Editor"


def test_icesee_remote_submission_is_followed_until_results(page, monkeypatch):
    import icesee_jupyter_book.ui.icesee_gateway as gw
    from cryostack_src.workspace import user_run_root
    from icesee_jupyter_book.core import run_records

    _pick_fake(page)
    launch = _icesee_launch_fn(page)
    after_submit = _cell(launch, "_after_submit").cell_contents
    status = _cell(after_submit, "STATUS").cell_contents
    wf = _cell(after_submit, "_WF").cell_contents
    poller = wf["remote_poller"]
    _cell(poller.fetch_log, "cluster_host").cell_contents.value = "login.cluster.test"
    states = ["RUNNING"]
    monkeypatch.setattr(gw, "remote_job_status", lambda *a: {"returncode": 0, "state": states[0]})
    monkeypatch.setattr(gw, "remote_tail_log",
                        lambda *a, **k: {"returncode": 0, "stdout": "[slurm] step 1\n[slurm] step 2"})
    run_dir = user_run_root(app="icesee") / "20261021_remote-fake"
    run_records.record_run(run_dir=run_dir, run_id=run_dir.name, name=run_dir.name, params=PARAMS,
                           example=FAKE_KEY, execution_mode="remote", backend="spack", status="submitted",
                           jobid="4242", remote_directory="/scratch/run")
    status.update(local_run_dir=str(run_dir), jobid="4242", remote_dir="/scratch/run")
    after_submit("remote")
    ws = _icesee_workspace(page)
    assert ws.tabs.value == "Logs"
    assert _wait(lambda: "[slurm] step 2" in ws.log_view.value, 30), ws.log_view.value[:300]
    assert _wait(lambda: "Running" in ws.log_status.value, 30)
    states[0] = "COMPLETED"
    poller.tick()
    assert _wait(lambda: ws.tabs.value == "Results", 30), ws.tabs.value


def test_icesee_connection_errors_show_in_the_log_view(page, monkeypatch):
    import icesee_jupyter_book.ui.icesee_gateway as gw
    from cryostack_src.workspace import user_run_root
    from icesee_jupyter_book.core import run_records

    _pick_fake(page)
    launch = _icesee_launch_fn(page)
    after_submit = _cell(launch, "_after_submit").cell_contents
    status = _cell(after_submit, "STATUS").cell_contents
    poller = _cell(after_submit, "_WF").cell_contents["remote_poller"]
    _cell(poller.fetch_log, "cluster_host").cell_contents.value = "login.cluster.test"

    def down(*_a):
        raise OSError("connection refused")

    monkeypatch.setattr(gw, "remote_job_status", down)
    run_dir = user_run_root(app="icesee") / "20261021_remote-down"
    run_records.record_run(run_dir=run_dir, run_id=run_dir.name, name=run_dir.name, params=PARAMS,
                           example=FAKE_KEY, execution_mode="remote", backend="spack", status="submitted",
                           jobid="99", remote_directory="/scratch/run")
    status.update(local_run_dir=str(run_dir), jobid="99", remote_dir="/scratch/run")
    after_submit("remote")
    ws = _icesee_workspace(page)
    assert _wait(lambda: "Could not reach the cluster" in ws.log_status.value, 30), ws.log_status.value
    assert "No log output yet" in ws.log_view.value


# ── CryoLauncher ────────────────────────────────────────────────────────────
@pytest.fixture
def cryolauncher(monkeypatch, tmp_path):
    from cryostack_src.workspace.manager import WorkspaceManager
    from icesee_jupyter_book.ui.tests.test_cloud_run_card_navigation import _build_page

    page = _build_page(monkeypatch, tmp_path, "monitor-user")
    for manager in (o for o in gc.get_objects() if isinstance(o, WorkspaceManager)):
        for listener in getattr(manager, "_run_listeners", ()):
            if getattr(listener, "__name__", "") != "_cl_on_run_change":
                continue
            render = _cell(listener, "_cl_render_monitor").cell_contents
            banner = _cell(render, "cl_monitor_banner").cell_contents
            if not any(w is banner for w in _walk(page)):
                continue
            follower = _cell(listener, "cl_follower").cell_contents
            monitor = _cell(render, "_cl_monitor").cell_contents
            tick = monitor["tick"]
            opened = []
            _cell(follower.open_results, "on_results_preview").cell_contents = lambda *a: opened.append("preview")
            tabs = _cell(follower.open_monitor, "_switch_workspace_tab").cell_contents
            ws_tabs = _cell(tabs, "_workspace_tabs").cell_contents["w"]
            return SimpleNamespace(page=page, manager=manager, follower=follower, banner=banner, tick=tick,
                                   tabs=ws_tabs, opened=opened, monitor=monitor)
    raise AssertionError("monitor listener not found")


def _tab(cl):
    return cl.tabs.get_title(cl.tabs.selected_index)


def _submit(cl, mode="remote"):
    from cryostack_src.workspace.models import RunInfo

    run = RunInfo(id=f"cl-{mode}-run", name="r", model="icepack", backend="spack", execution_mode=mode,
                  jobid="777", status="submitted", metadata={"example": ""})
    cl.manager.register_run(run)
    cl.follower.start(run.id)          # what _show_new_run does after a submission
    return run


def _fake_cluster(cl, states, *, error=None):
    class Bridge:            # RemoteBridge.status returns normalised lifecycle states
        def status(self, *, job_id):
            if error:
                raise error
            return SimpleNamespace(state=states[0])

    _cell(cl.tick, "current_remote_bridge").cell_contents = lambda *a, **k: Bridge()
    tails = []
    _cell(cl.tick, "on_tail").cell_contents = lambda *a: tails.append(states[0])
    return tails


def test_cryolauncher_remote_submit_opens_run_log_and_follows_to_results(cryolauncher):
    cl = cryolauncher
    states = ["queued"]
    tails = _fake_cluster(cl, states)
    run = _submit(cl)
    assert _tab(cl) == "Run Log"
    assert "Waiting for the scheduler" in cl.banner.value and "No log output yet" in cl.banner.value
    cl.tick()
    assert "Queued" in cl.banner.value and tails == ["queued"]
    states[0] = "running"
    cl.tick()
    assert "Running" in cl.banner.value and "Checked every" in cl.banner.value
    states[0] = "completed"
    cl.tick()
    assert _tab(cl) == "Results" and cl.opened == ["preview"]
    assert cl.manager.selected_run().id == run.id


@pytest.mark.parametrize("final,word", [("failed", "Failed"), ("cancelled", "Cancelled")])
def test_cryolauncher_failed_or_cancelled_run_stays_on_run_log(cryolauncher, final, word):
    cl = cryolauncher
    states = ["running"]
    _fake_cluster(cl, states)
    _submit(cl)
    cl.tick()
    states[0] = final
    cl.tick()
    assert _tab(cl) == "Run Log" and word in cl.banner.value and not cl.opened
    cl.tick()                                   # terminal: no more checks
    assert not cl.opened


def test_cryolauncher_connection_error_is_shown_and_retried(cryolauncher):
    cl = cryolauncher
    _fake_cluster(cl, ["running"], error=OSError("no route to host"))
    _submit(cl)
    cl.tick()
    assert "Could not reach the cluster" in cl.banner.value and "Retrying in" in cl.banner.value
    _fake_cluster(cl, ["running"])
    cl.tick()
    assert "Could not reach the cluster" not in cl.banner.value and "Running" in cl.banner.value


def test_cryolauncher_cloud_status_updates_move_to_results(cryolauncher):
    cl = cryolauncher
    run = _submit(cl, mode="cloud")
    assert _tab(cl) == "Run Log" and "CloudWatch" in cl.banner.value
    cl.manager.update_run_status_by_job("777", "running")      # the cloud controller's poll
    assert "Running" in cl.banner.value
    cl.manager.update_run_status_by_job("777", "completed")
    assert _tab(cl) == "Results" and cl.opened == ["preview"]
    assert run.status == "completed"
