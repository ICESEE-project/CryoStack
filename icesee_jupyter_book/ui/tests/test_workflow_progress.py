"""Workflow stepper: Review & launch -> Monitor -> Results follows the run of
the current configuration in ICESEE and CryoLauncher, including failure,
cancellation, manual navigation and a page reload."""
from __future__ import annotations

import gc
import html
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import ipywidgets as W
import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.ui.icesee_workflow.launch import Stepper
from icesee_jupyter_book.ui.icesee_workflow.progress import follow_run, run_step_states

SETUP = {"Mode": "done", "Experiment": "done", "Environment": "done", "Parameters": "done",
         "Review & launch": "current"}


def step_classes(stepper_html: str) -> dict:
    return {html.unescape(name): cls.split() for cls, name in
            re.findall(r'<li class="icw-step ([^"]*)"[^>]*title="([^":]+)', stepper_html)}


def current(stepper_html: str) -> list:
    return [name for name, cls in step_classes(stepper_html).items() if "current" in cls]


# ── the shared rule ─────────────────────────────────────────────────────────
def test_before_a_launch_review_is_current():
    assert run_step_states(SETUP, None) == SETUP


@pytest.mark.parametrize("state", ["preparing", "submitted", "queued", "running"])
def test_an_active_run_moves_to_monitor_and_finishes_setup(state):
    states = run_step_states(SETUP, state)
    assert states["Review & launch"] == "done" and states["Monitor"] == "current active"
    assert not states.get("Results")


def test_a_completed_run_moves_to_results():
    states = run_step_states(SETUP, "completed")
    assert states["Monitor"] == "done" and states["Results"] == "current"


def test_failure_and_cancellation_mark_monitor_without_results():
    failed = run_step_states(SETUP, "failed")
    cancelled = run_step_states(SETUP, "cancelled")
    assert failed["Monitor"] == "current attention" and not failed.get("Results")
    assert cancelled["Monitor"] == "current stopped" and not cancelled.get("Results")


def test_manual_navigation_moves_the_current_marker_only():
    viewing_log = run_step_states(SETUP, "completed", viewing="Monitor")
    assert viewing_log["Monitor"] == "done current" and not viewing_log["Results"]
    # Results is not reachable before the run completed
    assert run_step_states(SETUP, "running", viewing="Results")["Monitor"] == "current active"


def test_a_setup_problem_still_needs_attention_after_launch():
    states = run_step_states(dict(SETUP, Parameters="attention"), "running")
    assert states["Parameters"] == "attention" and states["Mode"] == "done"


def _run(name, mode="remote", example="ex", minutes=0):
    return SimpleNamespace(id=name, execution_mode=mode, metadata={"example": example},
                           created=datetime(2026, 10, 21) + timedelta(minutes=minutes))


def test_follow_run_prefers_selected_then_launched_then_latest_matching():
    old, new, other = _run("old", minutes=1), _run("new", minutes=2), _run("other", example="x", minutes=3)
    runs = [old, new, other]
    matches = lambda r: r.execution_mode == "remote" and r.metadata["example"] == "ex"  # noqa: E731
    assert follow_run(old, new, runs, matches=matches) is old
    assert follow_run(None, new, runs, matches=matches) is new
    assert follow_run(None, None, runs, matches=matches) is new          # after a reload
    assert follow_run(other, None, runs, matches=matches) is new         # selected but another experiment
    assert follow_run(None, None, [other], matches=matches) is None      # back to Review & launch


def test_stepper_marks_done_current_and_cancelled_steps():
    stepper = Stepper()
    stepper.update(run_step_states(SETUP, "cancelled"))
    steps = step_classes(stepper.steps.value)
    assert "stopped" in steps["Monitor"] and current(stepper.steps.value) == ["Monitor"]
    assert 'title="Monitor: cancelled, current step"' in stepper.steps.value
    assert 'aria-current="step"' in stepper.steps.value
    stepper.update(run_step_states(SETUP, "completed"))
    assert current(stepper.steps.value) == ["Results"]
    assert "done" in step_classes(stepper.steps.value)["Review & launch"]


# ── CryoLauncher: the workspace manager drives its stepper ──────────────────
def test_workspace_manager_notifies_on_register_select_and_status(tmp_path):
    from cryostack_src.workspace.models import RunInfo
    from icesee_jupyter_book.ui.tests.test_cloud_run_card_navigation import _build_page  # noqa: F401

    from cryostack_src.workspace.manager import WorkspaceManager
    manager = WorkspaceManager.__new__(WorkspaceManager)
    manager._run_listeners, manager._runs, manager._selected_run_id = [], {}, None
    manager.manifest_root = tmp_path
    manager._owner_root = tmp_path
    seen = []
    manager.add_run_listener(lambda run: seen.append(getattr(run, "status", None)))
    manager.add_run_listener(lambda run: 1 / 0)              # a failing listener is ignored
    run = RunInfo(id="r1", name="r1", model="issm", backend="spack", execution_mode="remote")
    manager.register_run(run)
    manager.update_run_status("r1", "running")
    manager.update_run_status("r1", "running")                # unchanged: no notification
    manager.update_run_status("r1", "completed")
    assert seen == ["submitted", "running", "completed"]


def _cell(fn, name):
    return fn.__closure__[fn.__code__.co_freevars.index(name)].cell_contents


def _gateway_parts(page):
    """The page's workspace manager, stepper workflow and form widgets, reached
    through the stepper listener the gateway registered (closures)."""
    from cryostack_src.workspace.manager import WorkspaceManager

    stepper = next(w for w in _walk(page) if isinstance(w, W.HTML)
                   and (w.value or "").startswith('<ol class="icw-stepper"'))
    for manager in (o for o in gc.get_objects() if isinstance(o, WorkspaceManager)):
        for listener in getattr(manager, "_run_listeners", ()):
            try:
                progress = _cell(listener, "_cl_refresh_progress")
            except (ValueError, TypeError, AttributeError):
                continue
            workflow = _cell(progress, "workflow")
            if workflow.stepper.steps is stepper:
                followed = _cell(progress, "_cl_followed_run")
                return SimpleNamespace(page=page, manager=manager, stepper=stepper, workflow=workflow,
                                       picker=_cell(followed, "example_picker"), mode=_cell(followed, "mode_dd"))
    raise AssertionError("stepper listener not found")


@pytest.fixture
def cryolauncher(monkeypatch, tmp_path):
    from icesee_jupyter_book.ui.tests.test_cloud_run_card_navigation import _build_page

    return _gateway_parts(_build_page(monkeypatch, tmp_path, "stepper-user"))


def _walk(w):
    yield w
    for c in getattr(w, "children", ()) or ():
        yield from _walk(c)


def _register(cl, status="submitted", example=None, minutes=0):
    from cryostack_src.workspace.models import RunInfo

    run = RunInfo(id=f"run-{status}-{minutes}", name="r", model="icepack", backend="spack",
                  execution_mode=cl.mode.value, status=status,
                  metadata={"example": cl.picker.value if example is None else example},
                  created=datetime.now() + timedelta(minutes=minutes))
    cl.manager.register_run(run)
    return run


def _first_example(cl):
    values = [o[1] if isinstance(o, tuple) else o for o in cl.picker.options]
    cl.picker.value = next(v for v in values if v)


def test_cryolauncher_stepper_follows_submit_monitor_results(cryolauncher):
    cl = cryolauncher
    _first_example(cl)
    assert current(cl.stepper.value) == ["Review & launch"]
    run = _register(cl)
    assert current(cl.stepper.value) == ["Monitor"]
    assert "done" in step_classes(cl.stepper.value)["Review & launch"]
    cl.manager.update_run_status(run.id, "running")
    assert "active" in step_classes(cl.stepper.value)["Monitor"]
    cl.manager.update_run_status(run.id, "completed")
    assert current(cl.stepper.value) == ["Results"]
    assert "done" in step_classes(cl.stepper.value)["Monitor"]


@pytest.mark.parametrize("state,mark", [("failed", "attention"), ("cancelled", "stopped")])
def test_cryolauncher_failed_or_cancelled_run_stops_at_monitor(cryolauncher, state, mark):
    cl = cryolauncher
    _first_example(cl)
    run = _register(cl)
    cl.manager.update_run_status(run.id, state)
    steps = step_classes(cl.stepper.value)
    assert mark in steps["Monitor"] and current(cl.stepper.value) == ["Monitor"]
    assert "current" not in steps.get("Results", [])


def test_cryolauncher_other_experiment_returns_to_review(cryolauncher):
    cl = cryolauncher
    _first_example(cl)
    _register(cl, status="completed")
    assert current(cl.stepper.value) == ["Results"]
    values = [o[1] if isinstance(o, tuple) else o for o in cl.picker.options if (o[1] if isinstance(o, tuple) else o)]
    if len(values) < 2:
        pytest.skip("only one example for this model")
    cl.picker.value = next(v for v in values if v != cl.picker.value)
    assert current(cl.stepper.value) == ["Review & launch"]


def test_cryolauncher_reload_restores_the_latest_run(monkeypatch, tmp_path, cryolauncher):
    cl = cryolauncher
    _first_example(cl)
    example = cl.picker.value
    _register(cl, status="running")
    from icesee_jupyter_book.ui.tests.test_cloud_run_card_navigation import _build_page

    fresh = _gateway_parts(_build_page(monkeypatch, tmp_path, "stepper-user"))   # a page reload
    fresh.picker.value = example
    assert current(fresh.stepper.value) == ["Monitor"]


# ── ICESEE: a Local run through the real widgets ────────────────────────────
from icesee_jupyter_book.ui.tests.test_icesee_workflow_ui import (  # noqa: E402
    FAKE_KEY, _cls, _launch_card, _mode, _wait, page)  # noqa: F401  (page is a fixture)


def _icesee_stepper(ui):
    return next(w for w in _walk(ui) if isinstance(w, W.HTML)
                and (w.value or "").startswith('<ol class="icw-stepper"'))


def _launch_fake(ui):
    example = next(w for w in _walk(ui) if isinstance(w, W.Dropdown) and FAKE_KEY in w.options)
    example.value = FAKE_KEY
    assert current(_icesee_stepper(ui).value) == ["Review & launch"]
    hero = next(w for w in _walk(_launch_card(ui)) if isinstance(w, W.Button) and "icw-btn-hero" in w._dom_classes)
    hero.click()
    return example


def test_icesee_local_run_moves_review_monitor_results(page):
    _launch_fake(page)
    stepper = _icesee_stepper(page)
    assert _wait(lambda: current(stepper.value) == ["Results"], 60), step_classes(stepper.value)
    steps = step_classes(stepper.value)
    assert "done" in steps["Review & launch"] and "done" in steps["Monitor"]
    _cls(page, "icw-tabs")[0].children[0].value = "Logs"          # manual navigation
    assert current(stepper.value) == ["Monitor"]


def test_icesee_failed_run_stops_at_monitor(page, tmp_path):
    (tmp_path / "apps" / "fake_ex" / "run_da_fake.py").write_text("raise SystemExit(3)\n")
    _launch_fake(page)
    stepper = _icesee_stepper(page)
    assert _wait(lambda: "attention" in step_classes(stepper.value).get("Monitor", []), 60), stepper.value
    assert "current" not in step_classes(stepper.value).get("Results", [])


def test_icesee_reload_keeps_results_and_another_mode_returns_to_review(page):
    _launch_fake(page)
    assert _wait(lambda: current(_icesee_stepper(page).value) == ["Results"], 60)
    import icesee_jupyter_book.ui.icesee_gateway as gw

    reloaded = gw.build_icesee_ui()                                # same user and workspace
    example = next(w for w in _walk(reloaded) if isinstance(w, W.Dropdown) and FAKE_KEY in w.options)
    example.value = FAKE_KEY
    assert current(_icesee_stepper(reloaded).value) == ["Results"]
    _mode(reloaded).value = "cloud"                               # another configuration
    assert current(_icesee_stepper(reloaded).value) == ["Review & launch"]
