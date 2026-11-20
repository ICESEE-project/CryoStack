"""A page reload keeps the user's work: the session snapshot in the user's own
workspace brings back mode, experiment, parameters, the run request, the open
workspace tab and unsaved editor text in ICESEE and CryoLauncher."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import ipywidgets as W
import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.ui import session_restore as sr  # noqa: E402
from icesee_jupyter_book.ui.session_restore import SessionRestore  # noqa: E402


# ── the shared store ────────────────────────────────────────────────────────
def _form():
    return dict(mode=W.ToggleButtons(options=[("Local", "local"), ("Cloud", "cloud")], value="local"),
                nodes=W.IntText(value=1), outputs=W.SelectMultiple(options=["a", "b", "c"], value=()),
                note=W.Textarea(value=""))


def test_values_round_trip_through_the_users_session_file(tmp_path):
    path = tmp_path / "s.json"
    first = SessionRestore("x", path=path)
    w = _form()
    first.fields(**w)
    first.restore()
    w["mode"].value, w["nodes"].value, w["outputs"].value, w["note"].value = "cloud", 4, ("a", "c"), "draft"
    assert first.save() and not first.save()            # unchanged: not written again
    assert oct(path.stat().st_mode & 0o777) == "0o600"

    again = SessionRestore("x", path=path)
    fresh = _form()
    again.fields(**fresh)
    assert set(again.restore()) == {"mode", "nodes", "outputs", "note"}
    assert (fresh["mode"].value, fresh["nodes"].value, fresh["outputs"].value, fresh["note"].value) == \
        ("cloud", 4, ("a", "c"), "draft")


def test_values_no_longer_offered_keep_the_default(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"schema_version": 1, "values": {"mode": "hpc", "outputs": ["a", "z"],
                                                                "nodes": "many"}}))
    session = SessionRestore("x", path=path)
    w = _form()
    session.fields(**w)
    assert session.restore() == ["outputs"]
    assert w["mode"].value == "local" and w["outputs"].value == ("a",) and w["nodes"].value == 1


@pytest.mark.parametrize("content", ["{broken", json.dumps({"schema_version": 99, "values": {"nodes": 5}})])
def test_an_unreadable_session_starts_from_the_defaults(tmp_path, content):
    path = tmp_path / "s.json"
    path.write_text(content)
    session = SessionRestore("x", path=path)
    w = _form()
    session.fields(**w)
    assert session.restore() == [] and w["nodes"].value == 1


def test_dependent_parts_restore_after_what_they_depend_on(tmp_path):
    """An experiment rebuilds its parameter form; the form is filled on a
    later pass, whatever order the observers ran in."""
    path = tmp_path / "s.json"
    example = W.Dropdown(options=["a", "b"], value="a")
    form = {"value": "default-a"}
    example.observe(lambda ch: form.update(value=f"default-{ch['new']}"), names="value")

    def put(v):
        if v["example"] != example.value or form["value"] == v["value"]:
            return False
        form["value"] = v["value"]
        return True

    session = SessionRestore("x", path=path)
    session.part("form", lambda: {"example": example.value, "value": form["value"]}, put)
    session.field("example", example)          # registered after the form on purpose
    path.write_text(json.dumps({"schema_version": 1, "values": {"example": "b",
                                                                "form": {"example": "b", "value": "edited"}}}))
    session.restore()
    assert example.value == "b" and form["value"] == "edited"


def test_secrets_are_never_registered_or_written(tmp_path):
    session = SessionRestore("x", path=tmp_path / "s.json")
    with pytest.raises(ValueError):
        session.field("cluster_password", W.Text())
    with pytest.raises(ValueError):
        session.field("anything", W.Password())
    session.part("cloud", lambda: {"region": "us-east-1", "aws_secret_access_key": "x"}, lambda v: False)
    session.restore()
    session._last = None
    session.save()
    text = (tmp_path / "s.json").read_text()
    assert "us-east-1" in text and "aws_secret" not in text


def test_an_oversized_snapshot_keeps_the_last_good_one(tmp_path, monkeypatch):
    path = tmp_path / "s.json"
    session = SessionRestore("x", path=path)
    note = W.Textarea(value="small")
    session.field("note", note)
    session.restore()
    note.value = "kept"
    assert session.save()
    monkeypatch.setattr(sr, "MAX_BYTES", 100)
    note.value = "x" * 500
    assert not session.save()
    assert json.loads(path.read_text())["values"]["note"] == "kept"


def test_only_a_trusted_identity_gets_a_session_file(monkeypatch, tmp_path):
    for name in ("HTTP_X_CRYOSTACK_USER_ID", "CRYOSTACK_WORKSPACE_USER"):
        monkeypatch.delenv(name, raising=False)
    assert sr.session_path("icesee", workspace_root=tmp_path) is None
    monkeypatch.setenv("HTTP_X_CRYOSTACK_USER_ID", "alice")
    alice = sr.session_path("icesee", workspace_root=tmp_path)
    monkeypatch.setenv("HTTP_X_CRYOSTACK_USER_ID", "bob")
    bob = sr.session_path("icesee", workspace_root=tmp_path)
    assert alice != bob and alice.name == "icesee.json"
    assert alice.parent.parent.parent.parent == tmp_path / "users"


def test_start_fresh_forgets_the_session(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"schema_version": 1, "values": {"nodes": 3}}))
    session = SessionRestore("x", path=path)
    session.field("nodes", W.IntText(value=1))
    session.restore()
    notice = session.notice()
    assert notice.layout.display == ""
    fresh = next(c for c in notice.children if isinstance(c, W.Button))
    fresh.click()
    assert not path.exists()


# ── ICESEE: a reload through the real page ──────────────────────────────────
from icesee_jupyter_book.ui.tests.test_icesee_workflow_ui import (  # noqa: E402
    FAKE_KEY, _mode, _walk, page)  # noqa: F401  (page is a fixture)


def _param(ui, key):
    row = next(w for w in _walk(ui) if isinstance(w, W.HBox) and len(w.children) == 2
               and isinstance(w.children[0], W.HTML) and f">{key}<" in w.children[0].value)
    return row.children[1]


def test_icesee_reload_restores_mode_experiment_parameters_tab_and_draft(page):
    example = next(w for w in _walk(page) if isinstance(w, W.Dropdown) and FAKE_KEY in w.options)
    example.value = FAKE_KEY
    _mode(page).value = "cluster"
    _param(page, "a").value = 2.5
    _param(page, "num_years").value = 7
    ws = page.session._entries[-1][1].__self__            # the RunWorkspace part
    ws.tabs.value = "Editor"
    obs = next(v for _l, v in ws.ed_files.options if v.endswith("obs.csv"))
    ws.ed_files.value = obs
    ws.ed_text.value = "a,b\n9,9\n"
    assert ws.editor_dirty()
    assert page.session.save()
    before = page.session.snapshot()

    import icesee_jupyter_book.ui.icesee_gateway as gw

    reloaded = gw.build_icesee_ui()                        # a page reload: fresh widgets
    assert reloaded.session.snapshot() == before
    assert _mode(reloaded).value == "cluster"
    assert _param(reloaded, "a").value == 2.5 and _param(reloaded, "num_years").value == 7
    rws = reloaded.session._entries[-1][1].__self__
    assert rws.tabs.value == "Editor" and rws.ed_text.value == "a,b\n9,9\n" and rws.editor_dirty()
    notice = next(w for w in _walk(reloaded) if "icw-session-notice" in w._dom_classes)
    assert notice.layout.display == ""


def test_icesee_first_visit_shows_no_restore_notice(page):
    notice = next(w for w in _walk(page) if "icw-session-notice" in w._dom_classes)
    assert notice.layout.display == "none" and page.session.restored == []


# ── CryoLauncher: a reload through the real page ────────────────────────────
def _cl_page(monkeypatch, tmp_path):
    from icesee_jupyter_book.ui.tests.test_cloud_run_card_navigation import _build_page

    return _build_page(monkeypatch, tmp_path, "session-user")


def _getters(page):
    return {name: get for name, get, _put in page.session._entries}


def _values(dd):
    return [o[1] if isinstance(o, tuple) else o for o in dd.options]


def test_cryolauncher_reload_restores_settings_parameters_and_unsaved_edit(monkeypatch, tmp_path):
    from icesee_jupyter_book.ui.tests.test_workflow_progress import _gateway_parts

    first = _cl_page(monkeypatch, tmp_path)
    _gateway_parts(first).manager.create_user_example(
        model="issm", name="my-shelf", template={"runme.m": "md=solve(md,'Stressbalance');\n"})

    page = _cl_page(monkeypatch, tmp_path)                 # discovers the new example
    w = page.session.widgets
    w["model"].value = "issm"
    w["user_mode"].value = "advanced"
    w["example"].value = next(v for v in _values(w["example"]) if v and "my-shelf" in str(v))
    w["mode"].value = "remote"
    w["nodes"].value, w["job_name"].value = 3, "shelf-test"
    md = _getters(page)["issm_parameters"].__self__
    key, (enable, control, _param) = next(iter(md._state["rows"].items()))
    enable.value = True
    editor = _getters(page)["editor"].__self__
    assert editor._loaded_path and editor._loaded_path.endswith("runme.m") and not editor._readonly
    editor.editor.value = "md=solve(md,'Transient');\n"
    assert editor.dirty
    assert page.session.save()
    before = page.session.snapshot()

    reloaded = _cl_page(monkeypatch, tmp_path)
    assert reloaded.session.snapshot() == before
    rw = reloaded.session.widgets
    assert (rw["model"].value, rw["mode"].value, rw["nodes"].value, rw["job_name"].value) == \
        ("issm", "remote", 3, "shelf-test")
    rmd = _getters(reloaded)["issm_parameters"].__self__
    assert key in rmd.session_state()
    redit = _getters(reloaded)["editor"].__self__
    assert redit.dirty and redit.editor.value == "md=solve(md,'Transient');\n"
    assert set(reloaded.session.restored) >= {"nodes", "editor"}


def test_follower_resumes_a_run_in_flight_without_moving_the_view():
    from icesee_jupyter_book.ui.icesee_workflow.monitor import RunFollower

    seen = []
    f = RunFollower(open_monitor=lambda r: seen.append(("monitor", r)),
                    open_results=lambda r: seen.append(("results", r)))
    f.resume("r1", auto=True)
    assert seen == [] and f.update("r1", "running") == "following"
    assert f.update("r1", "completed") == "results" and seen == [("results", "r1")]
    f.resume("r2", auto=False)
    assert f.update("r2", "completed") == "finished"


def test_cryolauncher_reload_keeps_following_the_selected_active_run(monkeypatch, tmp_path):
    import gc
    from datetime import datetime

    from cryostack_src.workspace.manager import WorkspaceManager
    from cryostack_src.workspace.models import RunInfo
    from icesee_jupyter_book.ui.tests.test_workflow_progress import _cell, _gateway_parts

    page = _cl_page(monkeypatch, tmp_path)
    manager = _gateway_parts(page).manager
    run = RunInfo(id="run-active", name="r", model="issm", backend="spack", execution_mode="remote",
                  status="running", metadata={}, created=datetime.now())
    manager.register_run(run)
    restore = next(put for name, _get, put in page.session._entries if name == "workspace")
    restore({"run": run.id, "tab": "Run Log"})
    assert page.session.save()

    reloaded = _cl_page(monkeypatch, tmp_path)
    assert "workspace" in reloaded.session.restored
    banner_ids = {id(w) for w in _walk(reloaded)}
    for m in (o for o in gc.get_objects() if isinstance(o, WorkspaceManager)):
        for listener in getattr(m, "_run_listeners", ()):
            if getattr(listener, "__name__", "") != "_cl_on_run_change":
                continue
            render = _cell(listener, "_cl_render_monitor")
            if id(_cell(render, "cl_monitor_banner")) not in banner_ids:
                continue
            follower = _cell(listener, "cl_follower")
            assert follower.run_id == run.id and follower.auto
            return
    raise AssertionError("monitor listener not found")


def test_autosave_keeps_running_while_nothing_changes(tmp_path):
    import time

    path = tmp_path / "s.json"
    session = SessionRestore("x", path=path, interval=0.05)
    note = W.Textarea(value="a")
    session.field("note", note)
    session.restore()
    session.start()
    try:
        time.sleep(0.3)                     # several quiet ticks
        note.value = "typed later"
        deadline = time.time() + 5
        while time.time() < deadline and not path.exists():
            time.sleep(0.05)
        assert json.loads(path.read_text())["values"]["note"] == "typed later"
    finally:
        session.stop()


def test_split_storage_keeps_session_and_unsaved_editor_text_local(monkeypatch, tmp_path):
    monkeypatch.setenv("HTTP_X_CRYOSTACK_USER_ID", "split-session-account")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_STATE_ROOT", str(tmp_path / "local-control"))
    bulk = tmp_path / "bulk-cedar"
    path = sr.session_path("icesheets", workspace_root=bulk)
    assert path.is_relative_to(tmp_path / "local-control")
    assert not path.is_relative_to(bulk)
    session = SessionRestore("icesheets", path=path)
    editor = W.Textarea(value="")
    session.field("editor_text", editor)
    session.restore()
    editor.value = "print('participant unsaved script')"
    assert session.save()
    assert sr.load_session(path)["editor_text"] == editor.value
    assert not bulk.exists()
