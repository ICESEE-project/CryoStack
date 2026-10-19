"""ICESEE run plan: Review & launch summarises the execution semantics
(mode / compute backend / model environment) and ICESEE's DA identity
(DAIdentity.summary_rows()) as first-class rows -- not a generic single-model
run -- and follows the Mode selector without leftovers from another mode.
"""
from __future__ import annotations

import sys
from pathlib import Path

import ipywidgets as W

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_GW = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"


def test_gateway_derives_the_plan_from_the_da_identity():
    src = _GW.read_text()
    assert "da_identity_from_params" in src
    assert "identity.summary_rows()" in src
    assert "launch_panel.set_summary(" in src
    # no second, independent run-plan implementation
    assert "class RunPlanPanel" not in src


def _build(monkeypatch, *, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", f"{user}-svc")
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui
    return build_icesee_ui()


def _walk(w):
    yield w
    for c in getattr(w, "children", ()) or ():
        yield from _walk(c)


def _summary(page):
    """The Review & launch summary (a key/value list in the launch card)."""
    for w in _walk(page):
        if "icw-anchor-launch" in getattr(w, "_dom_classes", ()):
            for h in _walk(w):
                if isinstance(h, W.HTML) and "icw-kv" in (h.value or ""):
                    return h
    return None


def _mode(page):
    return next(w for w in _walk(page) if isinstance(w, W.ToggleButtons) and "Cloud" in w._options_labels)


def test_plan_shows_execution_semantics_and_da_identity(monkeypatch):
    page = _build(monkeypatch, user="run-plan-user")
    summary = _summary(page)
    assert summary is not None, "Review & launch summary not found"
    for row in ("Mode", "Experiment", "Compute backend", "Model environment"):
        assert f"<dt>{row}</dt>" in summary.value
    assert "Assimilation filter" in summary.value or "Forecast model" in summary.value


def test_plan_follows_the_mode_without_leftovers(monkeypatch):
    page = _build(monkeypatch, user="run-plan-mode-user")
    summary = _summary(page)
    assert "<dd>Local</dd>" in summary.value
    _mode(page).value = "cloud"
    assert "<dd>Cloud</dd>" in summary.value and "AWS Batch" in summary.value
    assert "Slurm" not in summary.value
    _mode(page).value = "cluster"
    assert "Remote HPC" in summary.value and "Slurm" in summary.value
    assert "Region" not in summary.value
    _mode(page).value = "local"
    assert "<dd>Local</dd>" in summary.value
    assert "Slurm" not in summary.value and "Region" not in summary.value
