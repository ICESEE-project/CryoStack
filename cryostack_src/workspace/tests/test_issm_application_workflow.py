"""Commit 6 -- Advanced editor + dataset lifecycle exercised as one real user
session, end to end, at the WorkspaceManager layer (the ownership / containment
authority). Complements the per-operation unit tests in test_user_examples /
test_datasets / test_example_staging.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryostack_src.models.issm.md_config import (
    OVERRIDE_SCRIPT_NAME, build_md_override_script,
)
from cryostack_src.models.issm import inject_override_step
from cryostack_src.workspace import WorkspaceManager, WorkspaceUser
from cryostack_src.workspace.manager import WorkspacePermissionError
from cryostack_src.workspace.models import RunInfo

USER_A = WorkspaceUser(user_id="user-A", source="cryostack-auth")
USER_B = WorkspaceUser(user_id="user-B", source="cryostack-auth")

_RUNME = (
    "md=model;\n"
    "md=triangle(md,'DomainOutline.exp',100000);\n"
    "md=setmask(md,'all','');\n"
    "md=parameterize(md,'Square.par');\n"
    "md=setflowequation(md,'SSA','all');\n"
    "md=solve(md,'Stressbalance');\n"
)


class _Widget:
    def __init__(self, value=None):
        self.value = value
        self.options = ()


def _mgr(owner, root, example_dir):
    return WorkspaceManager(
        owner=owner, workspace_root=root, status={}, session={"id": "s"},
        example_dir=_Widget(str(example_dir)), model=_Widget("issm"), backend=_Widget("container"),
        file_picker=_Widget(), file_editor=_Widget(), log_output=None, results_output=None,
        cluster_host=_Widget(""), cluster_user=_Widget(""), cluster_port=_Widget(1),
        access_mode=_Widget(""), normalize_remote_path=lambda p: p,
        connector_fetch_archive=None, should_use_connector=lambda: False,
        connector_ssh=None, ssh_run=None, cluster_name=_Widget(""),
    )


@pytest.fixture
def canonical(tmp_path):
    ex = tmp_path / "shipped" / "SquareIceShelf"
    ex.mkdir(parents=True)
    (ex / "runme.m").write_text(_RUNME)
    (ex / "Square.par").write_text("% params\n")
    (ex / "DomainOutline.exp").write_text("## dummy\n1\n")
    return ex


# ── 6. Advanced editor as an actual workflow ────────────────────────────
def test_advanced_editor_full_workflow(tmp_path, canonical):
    root = tmp_path / "ws"
    m = _mgr(USER_A, root, canonical)

    # canonical -> read-only
    assert m.is_user_owned(canonical) is False
    assert m.read_text_file(canonical / "runme.m") == _RUNME
    with pytest.raises(WorkspacePermissionError):
        m.save_text_file(canonical / "runme.m", "hacked\n")
    assert (canonical / "runme.m").read_text() == _RUNME

    # Clone to My Workspace
    clone = m.clone_example_to_workspace(source=canonical, model="issm", name="my-shelf")
    assert m.is_user_owned(clone) is True

    # edit runme.m, Save, reload -> exact text persisted
    edited = _RUNME.replace("100000", "50000") + "% my note\n"
    m.save_text_file(clone / "runme.m", edited)
    m2 = _mgr(USER_A, root, clone)                        # fresh session
    assert m2.read_text_file(clone / "runme.m") == edited
    assert (canonical / "runme.m").read_text() == _RUNME  # still pristine

    # create a new MATLAB file + Save As-style copy
    helper = m2.create_text_file(clone, "helper.m", "function y = helper(x)\ny = x;\n")
    assert helper.is_file()
    m2.save_text_file(clone / "helper_v2.m", helper.read_text())

    # rename example, then rediscover after "page reload"
    m2.rename_user_example(model="issm", old="my-shelf", new="shelf-final")
    m3 = _mgr(USER_A, root, root)
    names = {e["name"] for e in m3.list_user_examples("issm")}
    assert names == {"shelf-final"}
    renamed = m3._user_example_dir("issm", "shelf-final")

    # run-target discovery works on the renamed clone
    from cryostack_src.models.issm import choose_run_target
    targets = [Path(v).name for _, v in m3.list_editable_files(str(renamed)) if v]
    assert choose_run_target(targets) == "runme.m"

    # delete created file, then delete the example
    m3.delete_user_file(renamed / "helper.m")
    assert not (renamed / "helper.m").exists()
    m3.delete_user_example(model="issm", name="shelf-final")
    assert m3.list_user_examples("issm") == []
    assert canonical.is_dir()                             # canonical untouched throughout


# ── 5. Basic mode: real injection, and disabling restores defaults ──────
def test_basic_mode_stage_then_disable_restores_canonical_runme(tmp_path, canonical):
    m = _mgr(USER_A, tmp_path / "ws", canonical)

    script = build_md_override_script({"stressbalance.maxiter": 25})
    staged = m.stage_example_for_md_overrides(
        source_example=str(canonical), override_script=script,
        overrides={"stressbalance.maxiter": 25},
        entrypoint_transform=inject_override_step)
    runme = (staged.path / "runme.m").read_text()
    assert f"run('{OVERRIDE_SCRIPT_NAME}');" in runme
    assert runme.index(OVERRIDE_SCRIPT_NAME) < runme.index("solve(")
    assert (staged.path / OVERRIDE_SCRIPT_NAME).read_text() == script
    assert (canonical / "runme.m").read_text() == _RUNME
    assert staged.provenance["md_overrides"] == {"stressbalance.maxiter": 25}

    # re-run with overrides disabled -> plain working copy, no injection
    plain = m.stage_example_for_run(source_example=str(canonical))
    assert plain.path == staged.path                      # same working dir, rebuilt
    assert (plain.path / "runme.m").read_text() == _RUNME
    assert not (plain.path / OVERRIDE_SCRIPT_NAME).exists()
    assert plain.provenance["md_overrides"] == {}


# ── 7. dataset lifecycle end to end ────────────────────────────────────
def test_dataset_lifecycle_end_to_end(tmp_path, canonical):
    root = tmp_path / "ws"
    m = _mgr(USER_A, root, canonical)
    clone = m.clone_example_to_workspace(source=canonical, model="issm", name="ds-ex")

    res = m.save_datasets((
        {"name": "obs_vel.csv", "content": b"x,y,v\n0,0,1\n"},
        {"name": "bed.xyz", "content": b"0 0 -500\n"},
    ))
    assert set(res["saved"]) == {"obs_vel.csv", "bed.xyz"}
    assert {d["name"] for d in m.list_datasets()} == {"obs_vel.csv", "bed.xyz"}

    m.reference_dataset(example_path=str(clone), dataset_name="obs_vel.csv",
                        as_path="inputs/obs.csv")
    staged = m.stage_example_for_run(source_example=str(clone))
    assert (staged.path / "data" / "inputs" / "obs.csv").is_file()
    assert staged.provenance["staged_datasets"] == [
        {"name": "obs_vel.csv", "as": "data/inputs/obs.csv"}]
    # original dataset stays put under the reusable root
    assert (m.datasets_root() / "obs_vel.csv").is_file()

    # run provenance carries the staged datasets
    run = m.register_run(RunInfo(
        id="run-ds", name="run-ds", model="issm", backend="container",
        execution_mode="remote", status="completed", created=datetime.now(), jobid="j",
        metadata={"staged_datasets": staged.provenance["staged_datasets"]}))
    assert json.loads((run.workspace_directory / ".cryostack-run.json").read_text()
                      )["run"]["metadata"]["staged_datasets"][0]["as"] == "data/inputs/obs.csv"

    # remove the reference, delete one dataset, the other survives
    m.unreference_dataset(example_path=str(clone), dataset_name="obs_vel.csv")
    assert m.example_dataset_references(str(clone)) == []
    m.delete_dataset("obs_vel.csv")
    assert {d["name"] for d in m.list_datasets()} == {"bed.xyz"}

    # deleting the example leaves the reusable dataset intact
    m.delete_user_example(model="issm", name="ds-ex")
    assert {d["name"] for d in m.list_datasets()} == {"bed.xyz"}


# ── isolation: a second user cannot reach the first user's artifacts ───
def test_second_user_cannot_touch_first_users_artifacts(tmp_path, canonical):
    root = tmp_path / "ws"
    a = _mgr(USER_A, root, canonical)
    a_ex = a.clone_example_to_workspace(source=canonical, model="issm", name="a-ex")
    a.save_datasets(({"name": "a_secret.csv", "content": b"secret\n"},))

    b = _mgr(USER_B, root, canonical)
    assert b.list_user_examples("issm") == []                     # cannot discover
    assert [d["name"] for d in b.list_datasets()] == []
    with pytest.raises((WorkspacePermissionError, FileNotFoundError, ValueError)):
        b.read_text_file(a_ex / "runme.m")                        # cannot read
    with pytest.raises(Exception):
        b.rename_user_example(model="issm", old="a-ex", new="pwned")
    with pytest.raises(Exception):
        b.delete_user_example(model="issm", name="a-ex")
    with pytest.raises(Exception):
        b.delete_dataset("a_secret.csv")

    # A's artifacts are all still there and intact
    assert {e["name"] for e in a.list_user_examples("issm")} == {"a-ex"}
    assert [d["name"] for d in a.list_datasets()] == ["a_secret.csv"]
