"""WorkspaceManager accepts a fixed model *name* (str), not only a selector
widget -- so a single-model app (ICESEE) can adopt per-user isolation + run
history without inventing a fake dropdown (Phase C-2).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.workspace import WorkspaceManager, WorkspaceUser
from cryostack_src.workspace.models import RunInfo

_USER = WorkspaceUser(user_id="ice-user-1", source="cryostack-auth")


class _W:
    def __init__(self, value="", options=()):
        self.value, self.options = value, options


def _mgr(root, *, model="icesee"):
    return WorkspaceManager(
        owner=_USER, workspace_root=root, status={}, session={"id": "s"},
        example_dir=_W(str(root)), model=model, backend=_W("spack", ["spack"]),
        file_picker=_W(), file_editor=_W(), log_output=None, results_output=None,
        cluster_host=_W(""), cluster_user=_W(""), cluster_port=_W(1),
        access_mode=_W(""), normalize_remote_path=lambda p: p,
        connector_fetch_archive=None, should_use_connector=lambda: False,
        connector_ssh=None, ssh_run=None, cluster_name=_W(""),
    )


def test_string_model_is_wrapped_and_behaves_like_a_selector(tmp_path):
    m = _mgr(tmp_path)
    assert m.model.value == "icesee"
    assert list(m.model.options) == [("icesee", "icesee")]
    m.model.observe(lambda *_a: None, names="value")   # inert, no raise


def test_widget_model_is_passed_through_untouched(tmp_path):
    w = _W("issm", ["issm", "icepack"])
    m = _mgr(tmp_path, model=w)
    assert m.model is w


def test_run_registration_and_history_work_with_a_fixed_model(tmp_path):
    m = _mgr(tmp_path)
    run = m.register_run(RunInfo(
        id="ice-run-1", name="EnKF lorenz96", model="icesee", backend="spack",
        execution_mode="local", status="completed", created=datetime.now(),
        metadata={"filter_type": "EnKF", "Nens": 32},
    ))
    assert run.workspace_directory.is_dir()
    assert "ice-user-1" in str(run.workspace_directory)      # per-user isolation
    # manifest round-trips the DA metadata + stackless model after a restart
    m2 = _mgr(tmp_path)
    ids = [r.id for r in m2.refresh()]
    assert ids == ["ice-run-1"]
    got = m2._runs["ice-run-1"]
    assert got.model == "icesee"
    assert got.metadata["filter_type"] == "EnKF"
    m2.select_run("ice-run-1")                                # no crash on str model
    assert m2.model.value == "icesee"


def test_two_icesee_users_are_isolated(tmp_path):
    a = _mgr(tmp_path)
    b = WorkspaceManager(
        owner=WorkspaceUser(user_id="ice-user-2", source="cryostack-auth"),
        workspace_root=tmp_path, status={}, session={"id": "s"},
        example_dir=_W(str(tmp_path)), model="icesee", backend=_W("spack"),
        file_picker=_W(), file_editor=_W(), log_output=None, results_output=None,
        cluster_host=_W(""), cluster_user=_W(""), cluster_port=_W(1),
        access_mode=_W(""), normalize_remote_path=lambda p: p,
        connector_fetch_archive=None, should_use_connector=lambda: False,
        connector_ssh=None, ssh_run=None, cluster_name=_W(""),
    )
    a.register_run(RunInfo(id="r1", name="r1", model="icesee", backend="spack",
                           execution_mode="local", status="completed",
                           created=datetime.now()))
    assert a._owner_root != b._owner_root
    assert [r.id for r in b.refresh()] == []      # B cannot see A's run
