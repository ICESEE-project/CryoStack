"""B4: shared Slurm resources panel -- reorganises existing widgets, keeps the
submission contract untouched."""
from __future__ import annotations

import sys
from pathlib import Path

import ipywidgets as W

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.ui.shared_slurm_resources_panel import build_slurm_resources_panel


def _widgets():
    return dict(
        job_name=W.Text(value="ICESEE"),
        wall_time=W.Text(value="04:00:00"),
        nodes=W.IntText(value=2),
        tasks=W.IntText(value=24),
        tasks_per_node=W.IntText(value=24),
        partition=W.Text(value="cpu-large"),
        memory=W.Text(value="256G"),
        account=W.Text(value=""),
        email=W.Text(value=""),
    )


def _all_html(widget) -> str:
    out = []

    def walk(w):
        if isinstance(w, W.HTML):
            out.append(w.value)
        for child in getattr(w, "children", ()):
            walk(child)

    walk(widget)
    return "\n".join(out)


def test_panel_reuses_the_exact_widget_instances():
    ws = _widgets()
    panel = build_slurm_resources_panel(**ws)
    # the caller's widgets are the ones placed in the panel (no copies)
    seen = []

    def walk(w):
        seen.append(id(w))
        for c in getattr(w, "children", ()):
            walk(c)

    walk(panel.container)
    for w in ws.values():
        assert id(w) in seen


def test_three_labelled_groups_and_clear_labels():
    html = _all_html(build_slurm_resources_panel(**_widgets()).container)
    for group in ("Job settings", "Compute resources", "Allocation & notifications"):
        assert group in html
    for label in ("Job name", "Wall time", "Nodes", "Tasks", "Tasks / node",
                  "Partition", "Memory", "Account", "Email"):
        assert label in html
    # no abbreviations
    for abbr in (">Job<", ">Time<", ">TPN<", ">Part<", ">Mem<", ">Acct<", ">Mail<"):
        assert abbr not in html


def test_help_text_present_for_the_documented_fields():
    html = _all_html(build_slurm_resources_panel(**_widgets()).container)
    assert "Maximum requested runtime" in html
    assert "Total Slurm tasks" in html
    assert "Maximum tasks assigned to each node" in html
    assert "Slurm partition / queue" in html
    assert "Allocation / project charged by the job" in html


def test_numeric_grid_class_present_for_responsive_3_to_1():
    ws = _widgets()
    panel = build_slurm_resources_panel(**ws)

    classes = []

    def walk(w):
        classes.extend(getattr(w, "_dom_classes", ()))
        for c in getattr(w, "children", ()):
            walk(c)

    walk(panel.container)
    assert "cryostack-slurm-numeric-grid" in classes


def test_extra_children_are_appended():
    marker = W.HTML("<div id='extra-marker'></div>")
    panel = build_slurm_resources_panel(**_widgets(), extra_children=[marker])
    assert "extra-marker" in _all_html(panel.container)
