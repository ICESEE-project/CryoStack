"""Curated, example-scoped Icepack figure titles.

The generic figure-capture path records only what a Matplotlib figure carries
itself. For a curated example whose plots carry no title at all
(``00-meshes-functions``), CryoStack stages an ordered title list transcribed
from the tutorial's OWN prose -- as a lowest-priority fallback that never
overrides script-produced metadata.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.models.icepack.figure_titles import (
    CURATED_FIGURE_TITLES,
    SIDECAR_FILENAME,
    curated_titles_for,
    sidecar_payload,
)
from cryostack_src.models.icepack.notebook import materialize_notebook_workspace

_EXPECTED_00_MESHES = (
    "Mesh of the unit square",
    "Filled contour of the Rosenbrock function",
    "Streamlines of the Rosenbrock negative-gradient field",
    "Tanh ramp across the domain diagonal",
    "Tanh ramp around a circle of radius 1/4",
    "Sech bump function",
    "Sech ridge around a circle of radius 1/4",
)


def test_all_seven_00_meshes_functions_titles_are_registered_in_order():
    assert curated_titles_for("00-meshes-functions") == _EXPECTED_00_MESHES
    # index 0 == figure-01.png, ... index 6 == figure-07.png
    assert len(_EXPECTED_00_MESHES) == 7


def test_unknown_example_has_no_curated_titles_and_no_sidecar_payload():
    assert curated_titles_for("99-not-a-real-example") == ()
    assert curated_titles_for("") == ()
    assert sidecar_payload("99-not-a-real-example") is None


def test_sidecar_payload_shape_for_a_curated_example():
    payload = sidecar_payload("00-meshes-functions")
    assert payload == {
        "example": "00-meshes-functions",
        "titles": list(_EXPECTED_00_MESHES),
    }


# ── notebook materializer stages the sidecar (the ONE point both Remote/HPC
#    and Cloud staging go through -- WorkspaceManager.stage_example_for_run
#    -> materialize_notebook_workspace) ──────────────────────────────────
def _nb(path: Path, *, stem: str, n_code_cells: int = 1) -> Path:
    cells = [{"cell_type": "markdown", "source": ["# demo\n"], "metadata": {}}]
    for i in range(n_code_cells):
        cells.append({"cell_type": "code", "source": [f"x = {i}\n"], "metadata": {},
                      "outputs": [], "execution_count": None})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "cells": cells,
        "metadata": {"language_info": {"name": "python"}},
        "nbformat": 4, "nbformat_minor": 5,
    }), encoding="utf-8")
    return path


def test_materializer_writes_the_curated_sidecar_for_a_curated_example(tmp_path):
    src = _nb(tmp_path / "src" / "00-meshes-functions.ipynb",
              stem="00-meshes-functions")
    dest = tmp_path / "work"
    materialize_notebook_workspace(src, dest_dir=dest)

    sidecar = dest / SIDECAR_FILENAME
    assert sidecar.is_file()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["example"] == "00-meshes-functions"
    assert tuple(data["titles"]) == _EXPECTED_00_MESHES
    # the upstream notebook itself is untouched (copied verbatim)
    assert json.loads((dest / "00-meshes-functions.ipynb").read_text()) == \
        json.loads(src.read_text())


def test_materializer_writes_no_sidecar_for_an_unknown_example(tmp_path):
    src = _nb(tmp_path / "src" / "some-other-notebook.ipynb",
              stem="some-other-notebook")
    dest = tmp_path / "work"
    materialize_notebook_workspace(src, dest_dir=dest)
    assert not (dest / SIDECAR_FILENAME).exists()
    assert {p.name for p in dest.iterdir()} == {
        "some-other-notebook.ipynb", "run.py"}


def test_registry_values_are_plain_ordered_string_tuples():
    for stem, titles in CURATED_FIGURE_TITLES.items():
        assert isinstance(stem, str) and stem
        assert isinstance(titles, tuple) and titles
        assert all(isinstance(t, str) and t.strip() for t in titles)
        # no fabricated-looking generic labels
        assert not any(t.strip().lower().startswith("figure ") for t in titles)
