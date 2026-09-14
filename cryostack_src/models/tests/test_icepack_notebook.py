"""Icepack Cloud Execution checkpoint: deterministic notebook -> run.py
conversion (cryostack_src.models.icepack.notebook).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.models.icepack.notebook import (
    RUN_SCRIPT_NAME,
    NotebookConversionError,
    convert_notebook_to_script,
    materialize_notebook_workspace,
)


def _notebook(cells: list[dict]) -> dict:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def _code_cell(source) -> dict:
    return {"cell_type": "code", "source": source, "metadata": {},
            "outputs": [], "execution_count": None}


def _markdown_cell(source) -> dict:
    return {"cell_type": "markdown", "source": source, "metadata": {}}


def _write_notebook(path: Path, cells: list[dict]) -> Path:
    path.write_text(json.dumps(_notebook(cells)), encoding="utf-8")
    return path


# ── clean conversion ──────────────────────────────────────────────────
def test_plain_notebook_converts_to_a_runnable_script(tmp_path):
    nb = _write_notebook(tmp_path / "demo.ipynb", [
        _markdown_cell(["# A title\n", "Some prose."]),
        _code_cell(["import math\n", "print(math.pi)\n"]),
    ])
    script = convert_notebook_to_script(nb)
    assert "import math" in script
    assert "print(math.pi)" in script
    # markdown became a comment, not executable prose
    assert "# A title" in script
    compile(script, "demo.py", "exec")   # genuinely valid Python


def test_multiple_code_cells_all_survive_in_order(tmp_path):
    nb = _write_notebook(tmp_path / "demo.ipynb", [
        _code_cell(["a = 1\n"]),
        _code_cell(["b = a + 1\n", "print(b)\n"]),
    ])
    script = convert_notebook_to_script(nb)
    assert script.index("a = 1") < script.index("b = a + 1")


# ── magics / shell escapes / kernel-only constructs: fail closed ──────
@pytest.mark.parametrize("bad_line", [
    "%matplotlib inline",
    "%%time",
    "%timeit foo()",
    "!pip install icepack",
    "!ls -la",
])
def test_magics_and_shell_escapes_fail_closed_with_a_clear_message(tmp_path, bad_line):
    nb = _write_notebook(tmp_path / "demo.ipynb", [
        _code_cell(["import icepack\n", f"{bad_line}\n"]),
    ])
    with pytest.raises(NotebookConversionError) as exc:
        convert_notebook_to_script(nb)
    assert bad_line in str(exc.value)
    assert "cell 1" in str(exc.value)


def test_get_ipython_call_fails_closed(tmp_path):
    nb = _write_notebook(tmp_path / "demo.ipynb", [
        _code_cell(["get_ipython().run_line_magic('matplotlib', 'inline')\n"]),
    ])
    with pytest.raises(NotebookConversionError, match="get_ipython"):
        convert_notebook_to_script(nb)


def test_magic_deep_in_a_later_cell_is_still_caught(tmp_path):
    """The check runs over every code cell, not just the first."""
    nb = _write_notebook(tmp_path / "demo.ipynb", [
        _code_cell(["x = 1\n"]),
        _code_cell(["y = 2\n"]),
        _code_cell(["!echo hi\n"]),
    ])
    with pytest.raises(NotebookConversionError) as exc:
        convert_notebook_to_script(nb)
    assert "cell 3" in str(exc.value)


def test_magic_inside_a_markdown_cell_is_not_flagged(tmp_path):
    """Only CODE cells are checked -- a magic mentioned in prose (e.g. inside
    a code-fenced markdown example) must not false-positive."""
    nb = _write_notebook(tmp_path / "demo.ipynb", [
        _markdown_cell(["Try `%matplotlib inline` in your own notebook.\n"]),
        _code_cell(["import icepack\n"]),
    ])
    script = convert_notebook_to_script(nb)
    assert "import icepack" in script


# ── materialization: the canonical staged layout ───────────────────────
def test_materialize_notebook_workspace_produces_the_canonical_layout(tmp_path):
    nb = tmp_path / "source" / "00-meshes-functions.ipynb"
    nb.parent.mkdir()
    _write_notebook(nb, [_code_cell(["import icepack\n"])])

    dest = tmp_path / "workspace"
    entrypoint = materialize_notebook_workspace(nb, dest_dir=dest)

    assert entrypoint == RUN_SCRIPT_NAME == "run.py"
    assert (dest / "00-meshes-functions.ipynb").is_file()
    assert (dest / "run.py").is_file()
    assert "import icepack" in (dest / "run.py").read_text()
    # the original notebook is copied VERBATIM -- never rewritten
    assert json.loads((dest / "00-meshes-functions.ipynb").read_text()) == json.loads(nb.read_text())


def test_materialize_preserves_the_notebook_even_when_conversion_fails(tmp_path):
    """A magic makes run.py impossible to generate, but the source of record
    (the notebook itself) must still be present -- never silently lost."""
    nb = _write_notebook(tmp_path / "source.ipynb", [
        _code_cell(["!pip install icepack\n"]),
    ])
    dest = tmp_path / "workspace"
    with pytest.raises(NotebookConversionError):
        materialize_notebook_workspace(nb, dest_dir=dest)

    assert (dest / "source.ipynb").is_file()
    assert not (dest / "run.py").exists()


def test_materialize_is_idempotent_and_deterministic(tmp_path):
    nb = _write_notebook(tmp_path / "source.ipynb", [_code_cell(["x = 1\n"])])
    dest = tmp_path / "workspace"
    materialize_notebook_workspace(nb, dest_dir=dest)
    first = (dest / "run.py").read_text()
    materialize_notebook_workspace(nb, dest_dir=dest)
    second = (dest / "run.py").read_text()
    assert first == second


# ── the real Icepack tutorial notebook, when available on this machine ──
def test_the_real_icepack_tutorial_notebook_converts_cleanly():
    """No mocks: proves the conversion works against an actual upstream
    Icepack tutorial, not just synthetic fixtures. Skips when this dev
    machine has no local Icepack checkout (ICEPACK_ROOT / common guesses)."""
    from icesee_jupyter_book.core.icesheet_examples import resolve_icepack_root

    root = resolve_icepack_root()
    if root is None:
        pytest.skip("no local Icepack checkout on this machine")
    nb = root / "notebooks" / "tutorials" / "00-meshes-functions.ipynb"
    if not nb.is_file():
        pytest.skip("00-meshes-functions.ipynb not present in this Icepack checkout")

    script = convert_notebook_to_script(nb)
    compile(script, "00-meshes-functions.py", "exec")
    assert "firedrake" in script
