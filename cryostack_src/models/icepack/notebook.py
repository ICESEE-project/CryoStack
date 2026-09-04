# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Models
# Component   : Icepack Notebook -> Script Conversion
# File        : notebook.py
#
# Description :
#     Deterministic Jupyter notebook -> Python script conversion, so a
#     single canonical run.py serves the Advanced Editor and every
#     execution backend (Local/Remote/Cloud) alike.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-09-04
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
Icepack examples ship as Jupyter notebooks (``ICEPACK_ROOT/notebooks/
tutorials/*.ipynb``) -- a single loose FILE, not a directory, unlike ISSM's
one-directory-per-example canonical layout. Nothing downstream of example
selection (the Advanced Editor's file listing, run-target resolution,
``stage_run_inputs``) can treat a bare file as "the example directory".

This module produces the fix: a deterministic, in-process (no ``jupyter``
CLI dependency -- pure ``nbformat``/``nbconvert`` library calls, so it works
identically wherever staging happens, independent of what the execution
backend has installed) notebook -> script conversion, plus the materializer
that builds the canonical staged layout::

    <example-workspace>/
        <notebook-name>.ipynb     # the original, copied verbatim -- source of record
        run.py                    # generated, deterministic, never hand-edited

``run.py`` is regenerated from the notebook every time the workspace is
materialized (:mod:`cryostack_src.workspace.manager` rebuilds a working copy
per staging call, same as every other canonical example) -- it is a build
artifact, not a second, independently-maintained scientific implementation.

A notebook containing IPython/Jupyter magics, shell escapes (``!cmd``) or an
explicit ``get_ipython()`` call cannot become a plain, backend-independent
script: :func:`convert_notebook_to_script` fails closed with
:class:`NotebookConversionError` rather than silently emitting broken code
that would only fail later, deep inside a Batch container.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

#: the canonical execution target every materialized notebook example gets
RUN_SCRIPT_NAME = "run.py"

#: a Jupyter line/cell magic ("%foo", "%%foo") or shell escape ("!cmd"),
#: which are ONLY valid inside a live kernel -- never at the start of a
#: plain Python statement.
_MAGIC_OR_SHELL_LINE_RE = re.compile(r"^\s*(%{1,2}[A-Za-z]|!)")
_GET_IPYTHON_RE = re.compile(r"\bget_ipython\s*\(")


class NotebookConversionError(RuntimeError):
    """The notebook cannot be deterministically converted to a plain,
    backend-independent Python script (a magic, a shell escape, or an
    explicit ``get_ipython()`` call was found in a code cell)."""


def _check_cell_is_convertible(source: str, *, cell_index: int) -> None:
    for lineno, line in enumerate(source.splitlines(), start=1):
        if _MAGIC_OR_SHELL_LINE_RE.match(line):
            raise NotebookConversionError(
                f"cell {cell_index + 1}, line {lineno}: {line.strip()!r} is an "
                "IPython/Jupyter magic or shell escape -- it only runs inside a "
                "live notebook kernel, so this example cannot be converted to a "
                "cloud-runnable script."
            )
        if _GET_IPYTHON_RE.search(line):
            raise NotebookConversionError(
                f"cell {cell_index + 1}, line {lineno}: get_ipython() is only "
                "available inside a live kernel -- this example cannot be "
                "converted to a cloud-runnable script."
            )


def convert_notebook_to_script(notebook_path: str | Path) -> str:
    """Read ``notebook_path`` and return its deterministic Python script form.

    Every code cell is checked for magics / shell escapes / ``get_ipython()``
    calls BEFORE conversion -- :class:`NotebookConversionError` is raised
    with the exact cell/line at fault rather than emitting a script that
    would only fail later, on whatever backend tries to run it.
    """
    import nbformat

    path = Path(notebook_path)
    notebook = nbformat.read(path, as_version=4)

    for index, cell in enumerate(notebook.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "") or ""
        if isinstance(source, list):
            source = "".join(source)
        _check_cell_is_convertible(source, cell_index=index)

    from nbconvert import PythonExporter

    script, _resources = PythonExporter().from_notebook_node(notebook)
    return script


def materialize_notebook_workspace(source: str | Path, *, dest_dir: str | Path) -> str:
    """Populate ``dest_dir`` with the canonical staged layout for a notebook
    example: the original notebook copied verbatim, plus the generated
    ``run.py``. Returns ``RUN_SCRIPT_NAME`` -- the entrypoint filename the
    caller (:meth:`WorkspaceManager.stage_example_for_run`) should record.

    ``dest_dir`` must already exist. Raises :class:`NotebookConversionError`
    for a notebook that cannot be deterministically converted -- ``dest_dir``
    still receives the copied ``.ipynb`` (the source of record is preserved
    even when the conversion itself fails) but no ``run.py`` is written.
    """
    src = Path(source)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_dir / src.name)

    script_text = convert_notebook_to_script(src)
    (dest_dir / RUN_SCRIPT_NAME).write_text(script_text, encoding="utf-8")
    return RUN_SCRIPT_NAME
