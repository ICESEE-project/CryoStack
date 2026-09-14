"""Per-user workspace-root helpers stay consistent with WorkspaceManager."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.workspace import WorkspaceManager, WorkspaceUser
from cryostack_src.workspace.roots import (
    WORKSPACE_ROOT_ENV,
    owner_root,
    resolve_workspace_root,
    user_run_root,
)

_A = WorkspaceUser(user_id="user-a", source="cryostack-auth")
_B = WorkspaceUser(user_id="user-b", source="cryostack-auth")


class _W:
    def __init__(self, v=""):
        self.value, self.options = v, ()


def _mgr(root, owner):
    return WorkspaceManager(
        owner=owner, workspace_root=root, status={}, session={"id": "s"},
        example_dir=_W(str(root)), model="icesee", backend=_W("spack"),
        file_picker=_W(), file_editor=_W(), log_output=None, results_output=None,
        cluster_host=_W(""), cluster_user=_W(""), cluster_port=_W(1),
        access_mode=_W(""), normalize_remote_path=lambda p: p,
        connector_fetch_archive=None, should_use_connector=lambda: False,
        connector_ssh=None, ssh_run=None, cluster_name=_W(""),
    )


def test_env_var_name_matches_the_manager():
    from cryostack_src.workspace.manager import WORKSPACE_ROOT_ENV as mgr_env
    assert WORKSPACE_ROOT_ENV == mgr_env == "CRYOSTACK_WORKSPACE_ROOT"


def test_owner_root_matches_workspace_manager(tmp_path):
    assert owner_root(_A, workspace_root=tmp_path) == _mgr(tmp_path, _A)._owner_root


def test_env_var_drives_the_root(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(tmp_path / "pinned"))
    assert resolve_workspace_root() == (tmp_path / "pinned").resolve()


def test_user_run_root_is_per_user_and_created(tmp_path):
    a = user_run_root(app="icesee", user=_A, workspace_root=tmp_path)
    b = user_run_root(app="icesee", user=_B, workspace_root=tmp_path)
    assert a.is_dir() and b.is_dir()
    assert a != b
    assert not str(b).startswith(str(owner_root(_A, workspace_root=tmp_path)))
    assert a.name == "icesee_runs"
    assert a.parent.name == ".cryostack"


def test_app_segment_is_sanitised(tmp_path):
    r = user_run_root(app="ice/see runs!", user=_A, workspace_root=tmp_path)
    assert r.name == "ice-see-runs-_runs" or "/" not in r.name
    assert "/" not in r.name and " " not in r.name
