# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Models
# Component   : Icepack curated example figure titles
# File        : figure_titles.py
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""Curated, example-scoped figure titles for CryoStack's curated Icepack examples.

The generic figure-capture path
(:mod:`cryostack_src.models.icepack.export` runner → ``_captured.json`` →
:mod:`cryostack_src.models.icepack.postprocess` collector → ``figures_meta``)
records **only** what each Matplotlib figure carries on its own: an explicit
figure label, a suptitle, or an axes title. Some curated tutorial examples draw
figures that carry no title at all — ``00-meshes-functions`` is the clearest
case: its seven Firedrake plots set neither title nor label nor axis labels —
yet the tutorial's own prose names each plot precisely.

This module holds those names, **transcribed from the example's own Markdown and
variable names, never inferred from a rendered image**, as an ordered tuple per
canonical example stem (index ``0`` == ``figure-01.png``; the runner numbers
still-open figures in creation order, which for a linear script is cell order).

The post-run collector applies a curated title **only**:

* as the lowest-priority fallback — a label / suptitle / axes title the script
  itself produced always wins, so a curated title never overrides
  scientific-script metadata;
* when the number of captured figures equals the curated list length (a cheap
  "the example was not modified" gate);

and it records ``"title_source": "curated-example"`` on every figure it fills,
so a reader can always tell a curated title from a script-produced one.

Nothing here modifies the upstream Icepack repository — CryoStack copies the
notebook verbatim and stages this data as an ordinary sidecar file
(:data:`SIDECAR_FILENAME`) written by the notebook materializer.
"""
from __future__ import annotations

#: The sidecar the notebook materializer writes next to ``run.py`` and that the
#: post-run collector (Remote/HPC and Cloud alike) reads.
SIDECAR_FILENAME = "cryostack_icepack_figure_titles.json"

#: canonical example stem → ordered figure titles (``figure-01.png`` == index 0).
#: Each entry is transcribed from the example's own tutorial text; the trailing
#: comment on each line points at the plotting cell and the prose that supports
#: the title.
CURATED_FIGURE_TITLES: dict[str, tuple[str, ...]] = {
    # ~/icepack/notebooks/tutorials/00-meshes-functions.ipynb  (40 cells; 7 plots)
    "00-meshes-functions": (
        # cell 4  firedrake.triplot(mesh); mesh = UnitSquareMesh(16, 16).
        # cell 1: "In this demo we'll use a mesh of the unit square."
        "Mesh of the unit square",
        # cell 8  firedrake.tricontourf(q, 36); q interpolates the cell-6 expr.
        # cell 5: "I've chosen the Rosenbrock function."  cell 7: "a contour plot".
        "Filled contour of the Rosenbrock function",
        # cell 12 firedrake.streamplot(v); v = as_vector(...) from cell 10.
        # cell 9: "a vector field representing the negative gradient of the
        # Rosenbrock function."  cell 11: "streamlines ... colored ... by
        # magnitude".
        "Streamlines of the Rosenbrock negative-gradient field",
        # cell 28 firedrake.trisurf(ramp); ramp = tanh ramp from cell 26.
        # cell 25: "a ramp function ... across the diagonal line through the
        # centre of the domain."
        "Tanh ramp across the domain diagonal",
        # cell 31 firedrake.trisurf(ramp); ramp reassigned in cell 30.
        # cell 29: "a ramping function around a circle of radius 1/4 in the
        # middle of the domain."
        "Tanh ramp around a circle of radius 1/4",
        # cell 34 firedrake.trisurf(bump); bump = sech(r/δ) from cell 33.
        # cell 32: "hyperbolic secant ... good for making bumps."
        "Sech bump function",
        # cell 37 firedrake.trisurf(ridge); ridge = sech((r-R)/δ) from cell 36.
        # cell 35: "we'll create a ridge at the circle of radius 1/4 about the
        # centre of the domain."
        "Sech ridge around a circle of radius 1/4",
    ),
}


def curated_titles_for(example_stem: str) -> tuple[str, ...]:
    """Ordered curated figure titles for a canonical example stem, or ``()``
    when the example has no curated entry."""
    return CURATED_FIGURE_TITLES.get((example_stem or "").strip(), ())


def sidecar_payload(example_stem: str) -> dict | None:
    """The sidecar-file contents for ``example_stem``, or ``None`` when there
    is nothing curated to stage."""
    titles = curated_titles_for(example_stem)
    if not titles:
        return None
    return {"example": example_stem, "titles": list(titles)}
