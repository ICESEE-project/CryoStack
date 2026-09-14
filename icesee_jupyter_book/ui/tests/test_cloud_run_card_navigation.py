"""CLOUD RUN card -> Workspace navigation (Problem 1 of the cloud
result-lifecycle fix).

`View log` / `View results` on the completed CLOUD RUN card must:
  1. select the run the card is showing (by its Batch job id -- never "the
     most recent run in history");
  2. open the Workspace on the requested tab (`Run Log` / `Results`);
  3. keep that tab active and that run selected.

These are verified against the REAL built gateway (the gateway's internals are
deliberately not module-level -- every cloud test in this tree reaches them the
same way: build `build_icesheets_ui()`, then walk closures).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import ipywidgets as W

from cryostack_src.workspace.models import RunInfo

_ARTIFACTS_META = json.dumps({
    "schema": "cryostack.icepack.results", "version": 2, "model": "icepack",
    "status": "artifacts", "solutions": [], "fields": [],
    "figures": ["figure-01.png"], "model_files": [],
})


def _freevar(fn, name):
    idx = fn.__code__.co_freevars.index(name)
    return fn.__closure__[idx].cell_contents


def _build_page(monkeypatch, tmp_path, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", "cloud-nav-service")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.delenv("CRYOSTACK_AWS_PRINCIPAL_ARN", raising=False)
    monkeypatch.delenv("CRYOSTACK_CF_TEMPLATE_URL", raising=False)
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    return build_icesheets_ui()


def _find_buttons(page, description):
    found = []

    def walk(w):
        if isinstance(w, W.Button) and getattr(w, "description", "") == description:
            found.append(w)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    return found


def _open_active_run_fn(page):
    """The gateway's `_open_active_run` closure, via the CLOUD RUN card's
    `View results` button -> its on_click lambda -> `on_view_results` lambda."""
    btns = _find_buttons(page, "View results")
    assert btns, "no 'View results' button in the built page"
    for b in btns:
        for cb in b._click_handlers.callbacks:
            try:
                on_view = _freevar(cb, "on_view_results")
                return _freevar(on_view, "_open_active_run")
            except (ValueError, AttributeError, TypeError):
                continue
    raise AssertionError("could not reach _open_active_run from the card button")


def _workspace_tab(open_active_run):
    switch = _freevar(open_active_run, "_switch_workspace_tab")
    holder = _freevar(switch, "_workspace_tabs")
    return holder["w"]


def _register_cloud_run(mgr, *, run_id, jobid, created):
    run = mgr.register_run(RunInfo(
        id=run_id, name=run_id, model="icepack", backend="aws",
        execution_mode="cloud", status="completed", created=created, jobid=jobid,
        metadata={"cloud_run": f"s3://b/runs/{run_id}", "region": "us-east-2"}))
    out = run.workspace_directory / "cache" / "cloud_outputs" / "figures"
    out.mkdir(parents=True)
    (out.parent / "metadata.json").write_text(_ARTIFACTS_META)
    (out / "figure-01.png").write_bytes(b"\x89PNG\r\n")
    return run


@pytest.fixture
def wired(monkeypatch, tmp_path):
    page = _build_page(monkeypatch, tmp_path, "cloud-nav-user")
    open_active_run = _open_active_run_fn(page)
    mgr = _freevar(open_active_run, "workspace_manager")
    status = _freevar(open_active_run, "STATUS")
    hist = _freevar(open_active_run, "workspace_history_panel")
    tab = _workspace_tab(open_active_run)

    # an OLDER cloud run (the card's subject) + a NEWER local run that is the
    # currently-selected one -- the wrong one for these buttons.
    cloud = _register_cloud_run(
        mgr, run_id="cloud-old", jobid="job-cloud-old",
        created=datetime(2026, 9, 9, 9, 0))
    newer = mgr.register_run(RunInfo(
        id="local-new", name="local-new", model="issm", backend="local",
        execution_mode="local", status="completed",
        created=datetime(2026, 9, 9, 12, 0), jobid="job-local-new"))
    hist.refresh_button.click()
    mgr.select_run(newer.id)
    status["batch_job_id"] = "job-cloud-old"
    return {"mgr": mgr, "tab": tab, "cloud": cloud, "newer": newer,
            "open": open_active_run}


def test_view_results_selects_the_card_run_and_activates_results_tab(wired):
    wired["tab"].selected_index = 0
    wired["open"]("results")
    assert wired["tab"].selected_index == 3                    # Results
    assert wired["mgr"].selected_run().id == "cloud-old"       # not local-new


def test_view_log_selects_the_card_run_and_activates_run_log_tab(wired):
    wired["tab"].selected_index = 0
    wired["open"]("log")
    assert wired["tab"].selected_index == 2                    # Run Log
    assert wired["mgr"].selected_run().id == "cloud-old"


def test_view_results_survives_a_data_step_that_touches_widgets(wired):
    """The requested tab must remain active even after on_results_preview has
    run (it drives the visualization panel)."""
    wired["tab"].selected_index = 1
    wired["open"]("results")
    assert wired["tab"].selected_index == 3
