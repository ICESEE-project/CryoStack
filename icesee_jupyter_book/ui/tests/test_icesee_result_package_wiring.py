"""ICESEE ResultPackage categorisation in the Workspace: a selected run's
HDF5 outputs are listed in Files with their DA role (forecast/truth,
ensemble, observations), categorised from ICESEE's own dataset names by
icesee_jupyter_book.core.results_package -- never a fabricated schema.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

h5py = pytest.importorskip("h5py")

_GW = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"


def test_workspace_uses_the_result_package_categories():
    src = (_REPO / "icesee_jupyter_book/ui/icesee_workflow/workspace.py").read_text()
    assert "from icesee_jupyter_book.core.results_package import _categorize" in src
    assert "_categorize(key)" in src


def test_selecting_a_run_with_da_outputs_prints_a_categorized_summary(monkeypatch, tmp_path, capsys):
    import numpy as np

    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "result-package-wiring-user")
    monkeypatch.setenv("USER", "result-package-wiring-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    import matplotlib
    matplotlib.use("Agg")

    from cryostack_src.workspace import user_run_root
    from icesee_jupyter_book.core import run_records as rr

    root = user_run_root(app="icesee")
    run_dir = root / "da-summary-check"
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    with h5py.File(run_dir / "results" / "true-wrong-lorenz.h5", "w") as f:
        f.create_dataset("true_state", data=np.zeros((3, 5)))
        f.create_dataset("hu_obs", data=np.zeros((3, 2)))
    rr.record_run(
        run_dir=run_dir, run_id="da-summary-check", name="da summary check",
        params={}, example="lorenz96", execution_mode="local",
        backend="local", status="done",
    )

    import ipywidgets as W
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui

    page = build_icesee_ui()

    def find(cls):
        out = []

        def walk(w):
            if cls in getattr(w, "_dom_classes", ()):
                out.append(w)
            for c in getattr(w, "children", ()):
                walk(c)
        walk(page)
        return out[0]

    runs = find("icw-runlist")
    runs.value = "da-summary-check"
    tabs = find("icw-tabs").children[0]
    tabs.value = "Files"
    files = find("icw-filelist")
    files.value = "results/true-wrong-lorenz.h5"
    shown = []

    def walk(w):
        if isinstance(w, W.HTML) and "DA role" in (w.value or ""):
            shown.append(w.value)
        for c in getattr(w, "children", ()):
            walk(c)
    walk(page)
    assert shown, "no HDF5 preview with DA roles"
    assert "true_state</td><td>Forecast / truth" in shown[0]
    assert "hu_obs</td><td>Observations" in shown[0]
