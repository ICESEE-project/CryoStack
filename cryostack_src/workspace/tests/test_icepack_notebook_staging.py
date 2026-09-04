"""Icepack Cloud Execution checkpoint: WorkspaceManager.stage_example_for_run
accepts a single-FILE source (a canonical Icepack notebook) and materialises
the canonical {notebook, run.py} staged layout -- the file-vs-directory
contract fix, not a filename special case (any .ipynb, not just this one).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from cryostack_src.cloud.drivers.aws.models import AWSConfig
from cryostack_src.cloud.drivers.aws.staging import stage_run_inputs
from cryostack_src.models.icepack.notebook import NotebookConversionError
from cryostack_src.workspace import WorkspaceManager, WorkspaceUser

USER_A = WorkspaceUser(user_id="user-A", source="cryostack-auth")
USER_B = WorkspaceUser(user_id="user-B", source="cryostack-auth")
BUCKET = "cryostack-runs-774888247882"


class _Widget:
    def __init__(self, value=None):
        self.value = value
        self.options = ()


def _mgr(owner, root):
    return WorkspaceManager(
        owner=owner, workspace_root=root, status={}, session={"id": "s"},
        example_dir=_Widget(str(root)), model=_Widget("icepack"), backend=_Widget("c"),
        file_picker=_Widget(), file_editor=_Widget(), log_output=None,
        results_output=None,
        cluster_host=_Widget(""), cluster_user=_Widget(""), cluster_port=_Widget(1),
        access_mode=_Widget(""), normalize_remote_path=lambda p: p,
        connector_fetch_archive=None, should_use_connector=lambda: False,
        connector_ssh=None, ssh_run=None, cluster_name=_Widget(""),
    )


def _notebook(cells):
    return {
        "cells": cells,
        "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3"},
                     "language_info": {"name": "python"}},
        "nbformat": 4, "nbformat_minor": 5,
    }


def _write_tutorial_notebook(path: Path, *, cell_source="import firedrake\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_notebook([
        {"cell_type": "markdown", "source": ["# Meshes, functions\n"], "metadata": {}},
        {"cell_type": "code", "source": [cell_source], "metadata": {},
         "outputs": [], "execution_count": None},
    ])), encoding="utf-8")
    return path


class FakeS3:
    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, args):
        self.calls.append(list(args))
        return (0, "", "")


# ── 1/2/3/4: discovery-shaped source -> canonical staged layout ─────────
def test_a_bare_notebook_file_is_a_valid_stage_example_for_run_source(tmp_path):
    """Root cause reproduction: previously
    `Example directory not found: .../00-meshes-functions.ipynb` -- a single
    notebook FILE (not a directory) is exactly the canonical Icepack
    discovery shape (icesee_jupyter_book.core.icesheet_examples
    .discover_icepack_examples -> IcesheetExample(kind="notebook",
    path=<the .ipynb file>))."""
    src_root = tmp_path / "ICEPACK_ROOT" / "notebooks" / "tutorials"
    nb = _write_tutorial_notebook(src_root / "00-meshes-functions.ipynb")
    # sibling notebooks in the SAME shared canonical folder must never leak
    # into the staged example
    _write_tutorial_notebook(src_root / "01-synthetic-ice-sheet.ipynb")

    m = _mgr(USER_A, tmp_path / "ws")
    staged = m.stage_example_for_run(source_example=nb)

    assert staged.path.is_dir()
    assert staged.provenance["entrypoint"] == "run.py"
    listing = {p.name for p in staged.path.iterdir()}
    assert listing == {"00-meshes-functions.ipynb", "run.py", ".cryostack-example.json"}
    assert "import firedrake" in (staged.path / "run.py").read_text()
    # the original notebook is preserved verbatim, byte for byte
    assert json.loads((staged.path / "00-meshes-functions.ipynb").read_text()) == \
        json.loads(nb.read_text())


def test_the_fix_is_type_based_not_a_filename_special_case(tmp_path):
    """A DIFFERENT notebook name goes through the identical path -- proving
    the dispatch is by file type (.ipynb), never by this one filename."""
    src_root = tmp_path / "ICEPACK_ROOT" / "notebooks" / "how-to"
    nb = _write_tutorial_notebook(src_root / "some-other-notebook.ipynb",
                                  cell_source="print('hello')\n")
    m = _mgr(USER_A, tmp_path / "ws")
    staged = m.stage_example_for_run(source_example=nb)
    assert (staged.path / "run.py").is_file()
    assert (staged.path / "some-other-notebook.ipynb").is_file()


def test_a_non_ipynb_file_source_still_fails_the_same_way_it_always_did(tmp_path):
    """The file-vs-directory contract fix does not silently accept ANY file
    -- only registered, deterministically-convertible types."""
    loose = tmp_path / "notes.txt"
    loose.write_text("not an example")
    m = _mgr(USER_A, tmp_path / "ws")
    with pytest.raises(ValueError, match="Example directory not found"):
        m.stage_example_for_run(source_example=loose)


# ── ISSM behaviour: unchanged ───────────────────────────────────────────
def test_issm_directory_sources_are_completely_unaffected(tmp_path):
    ex = tmp_path / "SquareIceShelf"
    ex.mkdir()
    (ex / "runme.m").write_text("md=model;\n")
    m = _mgr(USER_A, tmp_path / "ws")
    staged = m.stage_example_for_run(source_example=ex, entrypoint="runme.m")
    assert staged.provenance["entrypoint"] == "runme.m"
    assert (staged.path / "runme.m").is_file()


# ── magics: clear, actionable failure -- never a silently-broken script ──
def test_a_notebook_with_a_magic_fails_closed_with_a_clear_message(tmp_path):
    nb = _write_tutorial_notebook(
        tmp_path / "src" / "demo.ipynb", cell_source="%matplotlib inline\n")
    m = _mgr(USER_A, tmp_path / "ws")
    with pytest.raises(NotebookConversionError, match="matplotlib inline"):
        m.stage_example_for_run(source_example=nb)
    # even on failure, the source of record survives in the working copy
    target = tmp_path / "ws" / "users" / USER_A.safe_id / ".cryostack" / "working" / "demo"
    assert (target / "demo.ipynb").is_file()
    assert not (target / "run.py").exists()


# ── per-user isolation is preserved for the new file-source path too ────
def test_two_users_staging_the_same_canonical_notebook_stay_isolated(tmp_path):
    nb = _write_tutorial_notebook(tmp_path / "ICEPACK_ROOT" / "notebooks" / "tutorials" / "00-meshes-functions.ipynb")
    alice = _mgr(USER_A, tmp_path / "ws").stage_example_for_run(source_example=nb)
    bob = _mgr(USER_B, tmp_path / "ws").stage_example_for_run(source_example=nb)
    assert alice.path != bob.path
    assert USER_A.safe_id in str(alice.path) and USER_B.safe_id not in str(alice.path)
    assert USER_B.safe_id in str(bob.path) and USER_A.safe_id not in str(bob.path)


def test_full_pipeline_from_real_discovery_through_cloud_staging(tmp_path):
    """The complete chain, starting from actual discovery (not a hand-built
    path): icesheet_examples.discover_icepack_examples() over a fake
    ICEPACK_ROOT -> the discovered file path -> stage_example_for_run ->
    stage_run_inputs. Proves the run target reaching cloud staging is a .py
    file and the original notebook remains available in what gets staged."""
    from icesee_jupyter_book.core.icesheet_examples import discover_icepack_examples

    icepack_root = tmp_path / "ICEPACK_ROOT"
    _write_tutorial_notebook(
        icepack_root / "notebooks" / "tutorials" / "00-meshes-functions.ipynb")

    discovered = discover_icepack_examples(icepack_root)
    assert len(discovered) == 1
    example = discovered[0]
    assert example.kind == "notebook"
    assert example.path.is_file()          # confirms the FILE-shaped discovery contract

    m = _mgr(USER_A, tmp_path / "ws")
    staged = m.stage_example_for_run(source_example=str(example.path))
    assert staged.path.is_dir()             # "effective example" is always a directory
    run_target = staged.provenance["entrypoint"]
    assert run_target.endswith(".py")
    assert (staged.path / example.path.name).is_file()   # original notebook still there

    s3 = FakeS3()
    result = stage_run_inputs(
        AWSConfig(region="us-east-2"), source=staged.path, model="icepack",
        run_target=run_target, bucket=BUCKET, s3=s3,
    )
    assert result.descriptor["run_target"] == run_target
    assert example.path.name in result.staged_files


# ── 9: discovery -> workspace preparation -> effective example -> cloud staging
def test_full_pipeline_discovery_to_cloud_staging_run_target_is_python(tmp_path):
    """discovery (a raw .ipynb path, exactly what
    icesheet_examples.discover_icepack_examples produces) -> workspace
    preparation (stage_example_for_run) -> "effective example" (a real
    directory) -> cloud staging (stage_run_inputs) -- the run target that
    reaches AWS Batch is run.py, and the original notebook is still present
    in what gets uploaded."""
    discovered_path = _write_tutorial_notebook(
        tmp_path / "ICEPACK_ROOT" / "notebooks" / "tutorials" / "00-meshes-functions.ipynb")

    m = _mgr(USER_A, tmp_path / "ws")
    staged = m.stage_example_for_run(source_example=str(discovered_path))   # str, like example_dir.value

    # "effective example": a real directory, never a bare .ipynb
    assert staged.path.is_dir()
    run_target = staged.provenance["entrypoint"]
    assert run_target == "run.py"

    s3 = FakeS3()
    result = stage_run_inputs(
        AWSConfig(region="us-east-2"), source=staged.path, model="icepack",
        run_target=run_target, bucket=BUCKET, s3=s3,
    )
    assert result.descriptor["model"] == "icepack"
    assert result.descriptor["run_target"] == "run.py"
    assert "00-meshes-functions.ipynb" in result.staged_files
    assert "run.py" in result.staged_files
    (sync,) = [c for c in s3.calls if c[:2] == ["s3", "sync"] and c[1] == "sync"
               and str(staged.path) in c[2]]
    assert sync  # the whole staged directory (notebook + run.py) was uploaded
