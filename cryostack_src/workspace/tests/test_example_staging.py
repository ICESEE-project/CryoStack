"""Basic-mode md overrides stage a user-owned working copy; canonical is read-only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from cryostack_src.models.issm.md_config import (
    OVERRIDE_SCRIPT_NAME,
    build_md_override_script,
    inject_override_step,
)
from cryostack_src.workspace import WorkspaceManager, WorkspaceUser

USER_A = WorkspaceUser(user_id="user-A-uuid", display_name="Ada", source="cryostack-auth")
USER_B = WorkspaceUser(user_id="user-B-uuid", display_name="Bo", source="cryostack-auth")

_RUNME = "md=model;\nmd=parameterize(md,'Square.par');\nmd=solve(md,'Stressbalance');\n"
_SCRIPT = build_md_override_script({"stressbalance.maxiter": 200})


class _Widget:
    def __init__(self, value=None):
        self.value = value
        self.options = ()


def _manager(owner, root, example_dir):
    return WorkspaceManager(
        owner=owner, workspace_root=root,
        status={}, session={"id": "s"},
        example_dir=_Widget(str(example_dir)),
        model=_Widget("issm"), backend=_Widget("container"),
        file_picker=_Widget(), file_editor=_Widget(),
        log_output=None, results_output=None,
        cluster_host=_Widget(""), cluster_user=_Widget(""), cluster_port=_Widget(1),
        access_mode=_Widget(""), normalize_remote_path=lambda p: p,
        connector_fetch_archive=None, should_use_connector=lambda: False,
        connector_ssh=None, ssh_run=None, cluster_name=_Widget(""),
    )


@pytest.fixture
def canonical(tmp_path):
    ex = tmp_path / "canonical" / "SquareIceShelf"
    ex.mkdir(parents=True)
    (ex / "runme.m").write_text(_RUNME)
    (ex / "Square.par").write_text("% params\n")
    return ex


def _stage(mgr, src):
    return mgr.stage_example_for_md_overrides(
        source_example=str(src), override_script=_SCRIPT,
        overrides={"stressbalance.maxiter": 200},
        entrypoint_transform=inject_override_step,
    )


def test_canonical_example_is_never_modified(tmp_path, canonical):
    before = (canonical / "runme.m").read_text()
    mgr = _manager(USER_A, tmp_path / "ws", canonical)
    staged = _stage(mgr, canonical)

    assert staged.from_canonical is True
    assert staged.path != canonical
    assert (canonical / "runme.m").read_text() == before                 # untouched
    assert not (canonical / OVERRIDE_SCRIPT_NAME).exists()


def test_working_copy_lands_under_the_owner_workspace_with_injection(tmp_path, canonical):
    mgr = _manager(USER_A, tmp_path / "ws", canonical)
    staged = _stage(mgr, canonical)

    assert staged.path.resolve().is_relative_to(mgr._owner_root)
    assert staged.path.resolve().is_relative_to(mgr._working_root)
    assert (staged.path / OVERRIDE_SCRIPT_NAME).read_text() == _SCRIPT
    runme = (staged.path / "runme.m").read_text()
    assert f"run('{OVERRIDE_SCRIPT_NAME}');" in runme
    assert runme.index(OVERRIDE_SCRIPT_NAME) < runme.index("solve(")
    assert (staged.path / "Square.par").exists()                          # full copy


def test_provenance_file_records_source_and_overrides(tmp_path, canonical):
    mgr = _manager(USER_A, tmp_path / "ws", canonical)
    staged = _stage(mgr, canonical)
    prov = json.loads((staged.path / ".cryostack-example.json").read_text())
    assert prov["source"] == str(canonical.resolve())
    assert prov["from_canonical"] is True
    assert prov["owner"] == USER_A.safe_id
    assert prov["md_overrides"] == {"stressbalance.maxiter": 200}


def test_restaging_rebuilds_deterministically_no_double_injection(tmp_path, canonical):
    mgr = _manager(USER_A, tmp_path / "ws", canonical)
    first = _stage(mgr, canonical).path
    (first / "scratch.txt").write_text("stale")
    second = _stage(mgr, canonical).path
    assert first == second
    assert not (second / "scratch.txt").exists()                         # rebuilt from canonical
    assert (second / "runme.m").read_text().count(OVERRIDE_SCRIPT_NAME) == 1


def test_user_owned_example_is_edited_in_place(tmp_path):
    ws = tmp_path / "ws"
    mgr = _manager(USER_A, ws, tmp_path)
    owned = mgr._owner_root / "examples" / "MyShelf"
    owned.mkdir(parents=True)
    (owned / "runme.m").write_text(_RUNME)

    staged = mgr.stage_example_for_md_overrides(
        source_example=str(owned), override_script=_SCRIPT,
        overrides={"stressbalance.maxiter": 200},
        entrypoint_transform=inject_override_step,
    )
    assert staged.from_canonical is False
    assert staged.path == owned.resolve()
    assert f"run('{OVERRIDE_SCRIPT_NAME}');" in (owned / "runme.m").read_text()


def test_two_users_get_separate_working_roots(tmp_path, canonical):
    root = tmp_path / "shared"
    a = _stage(_manager(USER_A, root, canonical), canonical)
    b = _stage(_manager(USER_B, root, canonical), canonical)
    assert a.path != b.path
    assert USER_A.safe_id in str(a.path) and USER_B.safe_id not in str(a.path)
    assert not a.path.resolve().is_relative_to((root / "users" / USER_B.safe_id).resolve())


def test_unsafe_example_name_is_rejected(tmp_path):
    ws = tmp_path / "ws"
    mgr = _manager(USER_A, ws, tmp_path)
    bad = tmp_path / "canon" / "../evil"
    (tmp_path / "canon").mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError):
        mgr._safe_example_name("../evil")
    with pytest.raises(ValueError):
        mgr._safe_example_name("has space")


def test_missing_source_example_raises(tmp_path):
    mgr = _manager(USER_A, tmp_path / "ws", tmp_path)
    with pytest.raises(ValueError):
        mgr.stage_example_for_md_overrides(
            source_example=str(tmp_path / "nope"), override_script=_SCRIPT,
            overrides={}, entrypoint_transform=inject_override_step,
        )
