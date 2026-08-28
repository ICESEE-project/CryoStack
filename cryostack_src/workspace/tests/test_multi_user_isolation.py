"""Workspace persistence must be isolated per authenticated CryoStack user.

Two fake authenticated users share one workspace root on disk; neither may see,
select, inspect, tail, download, or delete the other's runs, and neither may
discover the other's manifests after a process restart.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from cryostack_src.workspace import (
    WorkspaceIdentityError,
    WorkspaceManager,
    WorkspaceUser,
    resolve_workspace_user,
)
from cryostack_src.workspace.manager import WORKSPACE_ROOT_ENV
from cryostack_src.workspace.manifest import MANIFEST_NAME
from cryostack_src.workspace.models import RunInfo

USER_A = WorkspaceUser(user_id="cryostack-user-A-uuid", display_name="Ada", source="cryostack-auth")
USER_B = WorkspaceUser(user_id="cryostack-user-B-uuid", display_name="Bo", source="cryostack-auth")


class _Status(dict):
    def update(self, **kw):
        super().update(kw)

    def get(self, k, d=None):
        return super().get(k, d)


class _Widget:
    def __init__(self, value=None, options=()):
        self.value = value
        self.options = options


def make_manager(owner: WorkspaceUser, root: Path, *, tail=None, resolver=None) -> WorkspaceManager:
    mgr = WorkspaceManager(
        owner=owner,
        workspace_root=root,
        status=_Status(),
        session={"id": "s"},
        example_dir=_Widget(value=str(root)),
        model=_Widget(value="issm", options=["issm"]),
        backend=_Widget(value="julia", options=["julia"]),
        file_picker=_Widget(),
        file_editor=_Widget(),
        log_output=None,
        results_output=None,
        cluster_host=_Widget(value=""),
        cluster_user=_Widget(value=""),
        cluster_port=_Widget(value=1),
        access_mode=_Widget(value=""),
        normalize_remote_path=lambda p: p,
        connector_fetch_archive=None,
        should_use_connector=lambda: False,
        connector_ssh=None,
        ssh_run=None,
        cluster_name=_Widget(value=""),
    )
    if tail is not None:
        mgr.set_tail_handler(tail)
    if resolver is not None:
        mgr.set_status_resolver(resolver)
    return mgr


def make_run(run_id: str, owner_tag: str) -> RunInfo:
    return RunInfo(
        id=run_id, name=run_id, model="issm", backend="julia", execution_mode="remote",
        status="completed", created=datetime.now(), finished=datetime.now(), jobid=f"job-{owner_tag}",
        remote_directory=Path(f"/scratch/{owner_tag}/{run_id}"),
        log_file=Path(f"/scratch/{owner_tag}/{run_id}/log.out"),
        metadata={"host": "hpc", "user": owner_tag},
    )


@pytest.fixture
def two_users(tmp_path):
    """A and B each create+register one run under the shared workspace root."""
    a = make_manager(USER_A, tmp_path)
    b = make_manager(USER_B, tmp_path)
    run_a = a.register_run(make_run("run-A-0001", "A"))
    run_b = b.register_run(make_run("run-B-0001", "B"))
    with (run_a.workspace_directory / "resultA.txt").open("w") as fh:
        fh.write("A")
    with (run_b.workspace_directory / "resultB.txt").open("w") as fh:
        fh.write("B")
    return tmp_path, run_a, run_b


# --------------------------------------------------------------------------- #
# namespace layout
# --------------------------------------------------------------------------- #
def test_users_get_distinct_namespaces(tmp_path):
    a = make_manager(USER_A, tmp_path)
    b = make_manager(USER_B, tmp_path)
    assert a.manifest_root != b.manifest_root
    assert a.manifest_root.is_relative_to(tmp_path / "users" / USER_A.safe_id)
    assert b.manifest_root.is_relative_to(tmp_path / "users" / USER_B.safe_id)
    # legacy global location is not used
    assert a.manifest_root != (tmp_path / ".cryostack" / "runs")


def test_safe_id_is_filesystem_safe_and_collision_resistant():
    assert "/" not in USER_A.safe_id and ".." not in USER_A.safe_id
    # same id -> same key; different id -> different key even if slugs collide
    assert WorkspaceUser("a/b", source="cryostack-auth").safe_id != WorkspaceUser("a-b", source="cryostack-auth").safe_id
    assert WorkspaceUser("x", source="cryostack-auth").safe_id == WorkspaceUser("x", source="cryostack-auth").safe_id


# --------------------------------------------------------------------------- #
# list / discovery isolation (also across a simulated restart)
# --------------------------------------------------------------------------- #
def test_list_runs_is_isolated_after_restart(two_users):
    root, run_a, run_b = two_users
    a2 = make_manager(USER_A, root)
    b2 = make_manager(USER_B, root)
    assert [r.id for r in a2.refresh()] == ["run-A-0001"]
    assert [r.id for r in b2.refresh()] == ["run-B-0001"]
    assert [r.id for r in a2.list_runs()] == ["run-A-0001"]
    assert [r.id for r in b2.list_runs()] == ["run-B-0001"]


def test_neither_user_can_discover_the_other_manifest_after_restart(two_users):
    root, run_a, run_b = two_users
    a2 = make_manager(USER_A, root)
    b2 = make_manager(USER_B, root)
    a2.refresh()
    b2.refresh()
    assert "run-B-0001" not in a2._runs
    assert "run-A-0001" not in b2._runs
    # the manifests really are on disk, just outside each other's glob root
    assert (run_a.workspace_directory / MANIFEST_NAME).exists()
    assert (run_b.workspace_directory / MANIFEST_NAME).exists()
    assert not list(a2.manifest_root.glob(f"*/{MANIFEST_NAME}")) or all(
        "run-B" not in str(p) for p in a2.manifest_root.glob(f"*/{MANIFEST_NAME}")
    )


# --------------------------------------------------------------------------- #
# per-run operation isolation
# --------------------------------------------------------------------------- #
def test_select_run_rejects_foreign_run(two_users):
    root, run_a, run_b = two_users
    a2 = make_manager(USER_A, root)
    a2.refresh()
    assert a2.select_run(run_b.id) is None
    assert a2.selected_run() is None
    assert a2._selected_run_id is None

    b2 = make_manager(USER_B, root)
    b2.refresh()
    assert b2.select_run(run_a.id) is None
    assert b2.selected_run() is None


def test_reconcile_run_rejects_foreign_run(two_users):
    root, run_a, run_b = two_users
    a2 = make_manager(USER_A, root, resolver=lambda run: "failed")
    a2.refresh()
    assert a2.reconcile_run(run_b.id) is None
    # B's manifest status is untouched
    b2 = make_manager(USER_B, root)
    b2.refresh()
    assert b2._runs[run_b.id].status == "completed"


def test_files_rejects_foreign_run(two_users):
    root, run_a, run_b = two_users
    a2 = make_manager(USER_A, root)
    a2.refresh()
    assert a2.files(run_b.id) == []
    assert [p.name for p in a2.files(run_a.id)] == sorted(
        [MANIFEST_NAME, "resultA.txt"]
    )


def test_tail_rejects_foreign_run(two_users):
    root, run_a, run_b = two_users
    calls = []
    a2 = make_manager(USER_A, root, tail=lambda: calls.append("tail"))
    a2.refresh()
    assert a2.tail(run_b.id) is None
    assert calls == []
    a2.tail(run_a.id)
    assert calls == ["tail"]


def test_download_results_rejects_foreign_run(two_users):
    root, run_a, run_b = two_users
    a2 = make_manager(USER_A, root)
    a2.refresh()
    a2.results_output = _NullOutput()
    # passing B's id as the download target must not select or act on it
    a2.download_results(run_b.id)
    assert a2.selected_run() is None
    a2.download_figures(run_b.id)
    assert a2.selected_run() is None
    a2.preview_results_for_run(run_b.id)
    assert a2.selected_run() is None


def test_delete_run_rejects_foreign_run(two_users):
    root, run_a, run_b = two_users
    a2 = make_manager(USER_A, root)
    a2.refresh()
    assert a2.delete_run(run_b.id) is False
    assert (run_b.workspace_directory / MANIFEST_NAME).exists()
    # A can still delete its own
    assert a2.delete_run(run_a.id) is True
    assert not run_a.workspace_directory.exists()


# --------------------------------------------------------------------------- #
# path / id escape attempts
# --------------------------------------------------------------------------- #
def test_run_id_traversal_is_rejected(tmp_path):
    a = make_manager(USER_A, tmp_path)
    a.register_run(make_run("run-A-0001", "A"))
    evil = make_run("../../" + USER_B.safe_id + "/x", "A")
    with pytest.raises(ValueError):
        a.register_run(evil)
    assert a.select_run("../../users/other/.cryostack/runs/x") is None
    assert a.files("../../etc/passwd") == []
    assert a.delete_run("../../users") is False


# --------------------------------------------------------------------------- #
# identity change / logout-login must not retain previous user's state
# --------------------------------------------------------------------------- #
def test_switching_identity_resets_all_state(tmp_path):
    a = make_manager(USER_A, tmp_path)
    run_a = a.register_run(make_run("run-A-0001", "A"))
    a.select_run(run_a.id)
    a.status["remote_dir"] = str(run_a.remote_directory)
    assert a.selected_run() is not None

    # "logout / login as B" -> a brand new manager bound to B
    b = make_manager(USER_B, tmp_path)
    assert b.owner.safe_id == USER_B.safe_id
    assert b.manifest_root != a.manifest_root
    assert b._runs == {}
    assert b._selected_run_id is None
    assert b.selected_run() is None
    assert b.refresh() == []  # B has no runs; A's run is invisible

    # a fresh manager for A again also starts empty until it refreshes
    a_again = make_manager(USER_A, tmp_path)
    assert a_again._runs == {}
    assert a_again._selected_run_id is None
    assert [r.id for r in a_again.refresh()] == ["run-A-0001"]


def test_resolve_workspace_user_only_trusts_the_proxy_header():
    assert resolve_workspace_user({"HTTP_X_CRYOSTACK_USER_ID": "u-42"}).user_id == "u-42"
    assert resolve_workspace_user({"HTTP_X_CRYOSTACK_USER_ID": "u-42"}).source == "cryostack-auth"
    # widget/ssh/email/slurm/query-string style inputs are ignored
    ignored = {
        "USER": "bkyanjo3", "SLURM_JOB_USER": "bkyanjo3", "SSH_USER": "bkyanjo3",
        "QUERY_STRING": "user=attacker", "HTTP_X_CRYOSTACK_USER_EMAIL": "a@b.c",
    }
    assert resolve_workspace_user(ignored).user_id == "anonymous"
    assert resolve_workspace_user(ignored).source == "unauthenticated"


def test_two_ssh_identical_but_cryostack_distinct(tmp_path):
    """CryoStack A and B both SSH as bkyanjo3 -> still separate histories."""
    a = make_manager(USER_A, tmp_path)
    b = make_manager(USER_B, tmp_path)
    a.register_run(make_run("run-A-0001", "bkyanjo3"))
    b.register_run(make_run("run-B-0001", "bkyanjo3"))
    a2 = make_manager(USER_A, tmp_path)
    b2 = make_manager(USER_B, tmp_path)
    assert [r.id for r in a2.refresh()] == ["run-A-0001"]
    assert [r.id for r in b2.refresh()] == ["run-B-0001"]


# --------------------------------------------------------------------------- #
# same-account persistence across logout/login (reconstruction)
# --------------------------------------------------------------------------- #
def test_same_account_keeps_namespace_and_runs_across_relogin(tmp_path):
    # "login A" from the trusted proxy header
    header_env = {"HTTP_X_CRYOSTACK_USER_ID": "acct-A-stable-uuid", "HTTP_X_CRYOSTACK_USER_NAME": "Ada"}
    login_1 = resolve_workspace_user(header_env)
    m1 = make_manager(login_1, tmp_path)
    safe_id_1 = m1.owner.safe_id
    root_1 = str(m1.manifest_root)
    run = m1.register_run(make_run("run-A1", "A"))
    assert (run.workspace_directory / MANIFEST_NAME).exists()

    # "logout" ... "login A again" -- same header value, brand new manager
    login_2 = resolve_workspace_user(dict(header_env))
    m2 = make_manager(login_2, tmp_path)

    assert m2.owner.safe_id == safe_id_1          # same safe_id
    assert str(m2.manifest_root) == root_1        # same manifest_root
    assert [r.id for r in m2.refresh()] == ["run-A1"]  # A1 rediscovered
    assert m2.select_run("run-A1") is not None

    # a different account gets a different root and never sees A1
    other = resolve_workspace_user({"HTTP_X_CRYOSTACK_USER_ID": "acct-B-stable-uuid"})
    mb = make_manager(other, tmp_path)
    assert str(mb.manifest_root) != root_1
    assert mb.refresh() == []


def test_safe_id_is_a_pure_function_of_the_trusted_id():
    a = resolve_workspace_user({"HTTP_X_CRYOSTACK_USER_ID": "id-123"})
    b = resolve_workspace_user({"HTTP_X_CRYOSTACK_USER_ID": "id-123", "HTTP_X_CRYOSTACK_USER_NAME": "Renamed"})
    assert a.safe_id == b.safe_id  # display name does not affect the namespace key
    assert WorkspaceUser("id-123").safe_id == a.safe_id


# --------------------------------------------------------------------------- #
# fail closed when the protected web path has no trusted identity
# --------------------------------------------------------------------------- #
def test_protected_mode_fails_closed_without_trusted_identity(monkeypatch):
    monkeypatch.delenv("HTTP_X_CRYOSTACK_USER_ID", raising=False)
    monkeypatch.delenv("CRYOSTACK_WORKSPACE_USER", raising=False)

    with pytest.raises(WorkspaceIdentityError, match="authenticated CryoStack identity was not provided"):
        resolve_workspace_user({}, require_authenticated=True)

    with pytest.raises(WorkspaceIdentityError):
        make_manager(None, None)  # owner unresolved, require_authenticated default True

    # unprotected/dev contexts still degrade to an isolated 'anonymous' namespace
    assert resolve_workspace_user({}).user_id == "anonymous"


def test_dev_override_satisfies_protected_mode(monkeypatch):
    monkeypatch.delenv("HTTP_X_CRYOSTACK_USER_ID", raising=False)
    user = resolve_workspace_user({"CRYOSTACK_WORKSPACE_USER": "local-dev"}, require_authenticated=True)
    assert user.user_id == "local-dev"
    assert user.source == "env-override"


def test_workspace_root_env_pins_location(monkeypatch, tmp_path):
    pinned = tmp_path / "pinned-root"
    pinned.mkdir()
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(pinned))
    m = make_manager(USER_A, None)  # no explicit workspace_root -> env wins over cwd
    assert m.manifest_root.is_relative_to(pinned / "users" / USER_A.safe_id)


class _NullOutput:
    def clear_output(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
